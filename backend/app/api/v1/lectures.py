"""
API المحاضرات - كل الوظائف الحقيقية
"""
import os
import re
import uuid
import shutil
from typing import Optional
from fastapi import APIRouter, UploadFile, File, Form, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.config import settings
from app.models.lecture import Lecture, Transcript, Summary, GlossaryItem, Quiz, Topic, TopicResource
from app.utils.hash import calculate_file_hash
from app.services.export import export_markdown, export_json, export_pdf, export_docx

router = APIRouter(prefix="/lectures", tags=["lectures"])

def _looks_media(path: str) -> bool:
    """هل الملف وسائط؟ نسأل المحتوى (ffprobe) لا الامتداد."""
    try:
        from app.services.ingest import probe_media, media_summary
        info = probe_media(path)
        return bool(info and media_summary(info)["has_audio"])
    except Exception:
        return False


def get_or_create_user(db: Session):
    """مستخدم افتراضي للـ M1 (بدون مصادقة) - سيُستبدل ب JWT في M4"""
    from app.models.lecture import User
    user = db.query(User).first()
    if not user:
        user = User(username="student", email="student@tarboush.local", hashed_password="noauth_m1")
        db.add(user)
        db.commit()
        db.refresh(user)
    return user


def dispatch_processing(lecture_id: int) -> str:
    """
    إرسال المهمة إلى Celery إن كان متاحاً (Redis يعمل)،
    وإلا تشغيل خط المعالجة في خيط خلفي حتى تبقى المنصة تعمل بلا Redis.
    يعيد اسم المسار المستخدم: "celery" أو "thread".
    """
    try:
        from app.workers.tasks import process_lecture  # يستورد celery
        process_lecture.delay(lecture_id)
        print(f"[API] محاضرة {lecture_id} → Celery")
        return "celery"
    except Exception as e:
        print(f"[API] Celery غير متاح ({type(e).__name__}) → معالجة في خيط خلفي")

        def run_sync():
            from app.services.pipeline import run_pipeline
            try:
                run_pipeline(lecture_id)
            except Exception as ex:
                print(f"[Thread] فشل: {ex}")

        import threading
        threading.Thread(target=run_sync, daemon=True).start()
        return "thread"


def serialize_topics(db: Session, lecture_id: int) -> list:
    """تحويل صفوف Topic + TopicResource إلى بنية جاهزة للواجهة (بدون أي بيانات وهمية)"""
    topics = (
        db.query(Topic)
        .filter(Topic.lecture_id == lecture_id)
        .order_by(Topic.order_index)
        .all()
    )
    out = []
    for t in topics:
        resources = (
            db.query(TopicResource)
            .filter(TopicResource.topic_id == t.id)
            .order_by(TopicResource.rank)
            .all()
        )
        out.append({
            "id": t.id,
            "order": t.order_index,
            "title": t.title,
            "excerpt": t.excerpt,
            "key_terms": t.key_terms or [],
            "start_seconds": t.start_seconds,
            "end_seconds": t.end_seconds,
            "resources": [{
                "id": r.id,
                "provider": r.provider,
                "title": r.title,
                "url": r.url,
                "snippet": r.snippet,
                "thumbnail": r.thumbnail,
                "duration_seconds": r.duration_seconds,
                "channel": r.channel,
                "lang": r.lang,
            } for r in resources],
        })
    return out


@router.post("/{lecture_id}/topics/relink")
def relink_topics(lecture_id: int, db: Session = Depends(get_db)):
    """
    إعادة البحث عن مصادر لكل مواضيع المحاضرة (زر «تحديث المصادر» في الواجهة).
    يستخدم نفس الاستخراج المحفوظ، ويستبدل المصادر القديمة فقط.
    """
    from app.services.resources import link_topics

    lecture = db.query(Lecture).filter(Lecture.id == lecture_id).first()
    if not lecture:
        raise HTTPException(status_code=404, detail="المحاضرة غير موجودة")
    topics = db.query(Topic).filter(Topic.lecture_id == lecture_id).order_by(Topic.order_index).all()
    if not topics:
        raise HTTPException(status_code=409, detail="لا توجد مواضيع بعد — أعد معالجة المحاضرة أولاً")

    db.query(TopicResource).filter(
        TopicResource.topic_id.in_([t.id for t in topics])
    ).delete(synchronize_session=False)
    db.commit()

    payload = [{"title": t.title, "key_terms": t.key_terms or []} for t in topics]
    mapping = link_topics(payload)

    added = 0
    for idx, t in enumerate(topics):
        for rank, item in enumerate(mapping.get(idx, [])):
            db.add(TopicResource(
                topic_id=t.id,
                provider=item["provider"],
                title=item["title"][:500],
                url=item["url"],
                snippet=(item.get("snippet") or "")[:1000],
                thumbnail=item.get("thumbnail"),
                duration_seconds=item.get("duration_seconds"),
                channel=item.get("channel"),
                query_used=item.get("query_used"),
                lang=item.get("lang") or "ar",
                rank=rank,
            ))
            added += 1
    db.commit()
    return {"message": "تم تحديث المصادر", "topics": len(topics), "resources": added,
            "items": serialize_topics(db, lecture_id)}


@router.get("/resources/search")
def search_resources(q: str = Query(..., min_length=2, max_length=120), limit: int = Query(8, ge=1, le=20)):
    """بحث حر عن شرح لمصطلح/فكرة — يعيد مصادر حقيقية فقط، أو قائمة فارغة بصدق"""
    from app.services.resources import find_resources

    items = find_resources({"title": q, "key_terms": []}, max_items=limit)
    return {"query": q, "count": len(items), "items": items,
            "note": "لا توجد نتائج مطابقة" if not items else None}


@router.post("/demo")
def create_demo_lecture(db: Session = Depends(get_db)):
    """
    إنشاء محاضرة تجريبية **بمعالجة حقيقية** (لا بيانات مكتوبة مسبقاً):
    يأخذ نصاً عربياً من ملفات المشروع، يمرره على خط المعالجة نفسه،
    فتُستخرج المواضيع وتُجلب مصادر حقيقية من الإنترنت.
    مفيد لمن يفتح المنصة أول مرة ويريد أن يرى الناتج كاملاً بضغطة واحدة.
    """
    assets = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "assets")
    src = os.path.join(assets, "demo_lecture.txt")
    if not os.path.exists(src):
        raise HTTPException(status_code=404, detail="ملف المحاضرة التجريبية غير موجود في هذه الحزمة")

    user = get_or_create_user(db)
    content = open(src, "rb").read()
    import hashlib
    file_hash = hashlib.sha256(content).hexdigest()

    existing = db.query(Lecture).filter(Lecture.file_hash == file_hash).first()
    if existing:
        return {"id": existing.id, "deduplicated": True, "message": "المحاضرة التجريبية موجودة مسبقاً"}

    os.makedirs(settings.storage_path, exist_ok=True)
    name = f"demo_{uuid.uuid4().hex[:8]}.txt"
    dest = os.path.join(settings.storage_path, name)
    with open(dest, "wb") as f:
        f.write(content)

    lecture = Lecture(
        user_id=user.id,
        title="محاضرة تجريبية — قوانين نيوتن (نص جاهز)",
        original_filename="demo_lecture.txt",
        file_path=dest,
        file_size=len(content),
        file_hash=file_hash,
        mime_type="text/plain",
        status="queued",
        progress=5,
    )
    db.add(lecture)
    db.commit()
    db.refresh(lecture)
    dispatch_processing(lecture.id)
    return {"id": lecture.id, "deduplicated": False,
            "message": "المحاضرة التجريبية قيد المعالجة — ستظهر المواضيع والمصادر خلال ثوانٍ"}


def _safe_filename(name: str) -> str:
    """اسم آمن للقرص مع الحفاظ على امتداد الملف (أي امتداد)."""
    base = os.path.basename(name or "lecture")
    base = re.sub(r"[\\/\x00]", "_", base)[:180] or "lecture"
    return base


async def _stream_to_disk(file: UploadFile, dest: str) -> int:
    """
    يكتب الملف على القرص كقطع صغيرة (1MB) — لا يقرأه كاملاً في الذاكرة.
    محاضرة ساعة فيديو (1–3GB) تُرفع بلا انفجار ذاكرة.
    """
    size = 0
    with open(dest, "wb") as f:
        while True:
            chunk = await file.read(1024 * 1024)
            if not chunk:
                break
            size += len(chunk)
            if settings.max_upload_size_mb > 0 and size > settings.max_upload_size_mb * 1024 * 1024:
                f.close()
                os.remove(dest)
                raise HTTPException(
                    status_code=413,
                    detail=f"الملف أكبر من الحد المضبوط ({settings.max_upload_size_mb}MB). "
                           "اجعل MAX_UPLOAD_SIZE_MB=0 لرفع أي حجم."
                )
            f.write(chunk)
    return size


@router.post("/upload")
async def upload_lecture(
    file: UploadFile = File(...),
    title: Optional[str] = Form(None),
    db: Session = Depends(get_db)
):
    """
    رفع محاضرة بأي صيغة: صوت، فيديو، PDF، Word، PowerPoint، Excel، صور، أرشيف…
    النوع يُحدَّد من محتوى الملف لا من امتداده. بلا سقف حجم افتراضياً (0 = بلا حد).
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="لم يصل اسم الملف")

    user = get_or_create_user(db)
    safe_name = f"{uuid.uuid4().hex}_{_safe_filename(file.filename)}"
    save_path = os.path.join(settings.storage_path, safe_name)
    os.makedirs(settings.storage_path, exist_ok=True)

    size = await _stream_to_disk(file, save_path)
    if size == 0:
        os.remove(save_path)
        raise HTTPException(status_code=400, detail="الملف فارغ")

    # منع التكرار بالـ hash
    file_hash = calculate_file_hash(save_path)
    existing = db.query(Lecture).filter(Lecture.file_hash == file_hash).first()
    if existing and settings.enable_deduplication:
        os.remove(save_path)
        return {
            "id": existing.id,
            "title": existing.title,
            "status": existing.status,
            "message": "هذا الملف مرفوع مسبقاً — أعدنا لك المحاضرة نفسها بدل إعادة المعالجة",
            "deduplicated": True
        }

    lecture = Lecture(
        user_id=user.id,
        title=title or os.path.splitext(os.path.basename(file.filename))[0][:100],
        original_filename=file.filename,
        file_path=save_path,
        file_hash=file_hash,
        file_size=size,
        mime_type=file.content_type or "unknown",
        status="queued",
        progress=0
    )
    db.add(lecture)
    db.commit()
    db.refresh(lecture)

    dispatch_processing(lecture.id)
    return {
        "id": lecture.id,
        "title": lecture.title,
        "status": lecture.status,
        "hash": file_hash,
        "message": "تم الرفع — جاري التحليل في الخلفية",
        "deduplicated": False
    }


# ------------------------------------------------------------------ رفع مجزّأ
@router.post("/upload/init")
def upload_init(
    filename: str = Form(...),
    size: int = Form(0),
    title: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    """
    بداية رفع مجزّأ للملفات الكبيرة (فيديو/صوت طويل).
    يعيد upload_id + حجم القطعة المقترح، ثم تُرفع القطع بالتتابع، وآخر خطوة /upload/complete.
    """
    if settings.max_upload_size_mb > 0 and size > settings.max_upload_size_mb * 1024 * 1024:
        raise HTTPException(status_code=413, detail="الملف أكبر من الحد المضبوط")

    upload_id = uuid.uuid4().hex
    part_dir = os.path.join(settings.storage_path, f".parts_{upload_id}")
    os.makedirs(part_dir, exist_ok=True)

    tmp_name = f"{upload_id}_{_safe_filename(filename)}"
    with open(os.path.join(settings.storage_path, f".meta_{upload_id}.json"), "w",
              encoding="utf-8") as f:
        import json
        json.dump({"filename": filename, "title": title, "size": size,
                   "part_dir": part_dir, "tmp_name": tmp_name}, f, ensure_ascii=False)

    return {"upload_id": upload_id, "chunk_size": 8 * 1024 * 1024, "received": 0}


@router.post("/upload/chunk")
async def upload_chunk(
    upload_id: str = Form(...),
    index: int = Form(...),
    chunk: UploadFile = File(...),
):
    """استقبال قطعة واحدة. آمنة لإعادة المحاولة (نفس الـ index يُستبدل)."""
    meta_path = os.path.join(settings.storage_path, f".meta_{upload_id}.json")
    if not os.path.exists(meta_path):
        raise HTTPException(status_code=404, detail="جلسة الرفع غير موجودة — ابدأ من جديد")

    part_dir = os.path.join(settings.storage_path, f".parts_{upload_id}")
    os.makedirs(part_dir, exist_ok=True)
    part_path = os.path.join(part_dir, f"{index:06d}.part")

    size = 0
    with open(part_path, "wb") as f:
        while True:
            buf = await chunk.read(1024 * 1024)
            if not buf:
                break
            size += len(buf)
            f.write(buf)
    return {"ok": True, "index": index, "bytes": size}


@router.post("/upload/complete")
def upload_complete(upload_id: str = Form(...), db: Session = Depends(get_db)):
    """يجمع القطع بالترتيب، ينشئ المحاضرة، ويطلق المعالجة."""
    import json

    meta_path = os.path.join(settings.storage_path, f".meta_{upload_id}.json")
    part_dir = os.path.join(settings.storage_path, f".parts_{upload_id}")
    if not os.path.exists(meta_path) or not os.path.isdir(part_dir):
        raise HTTPException(status_code=404, detail="جلسة الرفع غير موجودة")

    meta = json.loads(open(meta_path, encoding="utf-8").read())
    parts = sorted(f for f in os.listdir(part_dir) if f.endswith(".part"))
    if not parts:
        raise HTTPException(status_code=400, detail="لم تصل أي قطعة")

    dest = os.path.join(settings.storage_path, meta["tmp_name"])
    with open(dest, "wb") as out:
        for part in parts:
            with open(os.path.join(part_dir, part), "rb") as src:
                shutil.copyfileobj(src, out, 1024 * 1024)

    total = os.path.getsize(dest)
    shutil.rmtree(part_dir, ignore_errors=True)
    os.remove(meta_path)

    if total == 0:
        os.remove(dest)
        raise HTTPException(status_code=400, detail="الملف المجمَّع فارغ")

    file_hash = calculate_file_hash(dest)
    existing = db.query(Lecture).filter(Lecture.file_hash == file_hash).first()
    if existing and settings.enable_deduplication:
        os.remove(dest)
        return {"id": existing.id, "title": existing.title, "status": existing.status,
                "deduplicated": True,
                "message": "هذا الملف مرفوع مسبقاً — أعدنا لك المحاضرة نفسها"}

    user = get_or_create_user(db)
    lecture = Lecture(
        user_id=user.id,
        title=meta.get("title") or os.path.splitext(os.path.basename(meta["filename"]))[0][:100],
        original_filename=meta["filename"],
        file_path=dest,
        file_hash=file_hash,
        file_size=total,
        mime_type="application/octet-stream",
        status="queued",
        progress=0,
    )
    db.add(lecture)
    db.commit()
    db.refresh(lecture)
    dispatch_processing(lecture.id)
    return {"id": lecture.id, "title": lecture.title, "status": lecture.status,
            "size": total, "deduplicated": False,
            "message": "تم تجميع الملف — جاري التحليل في الخلفية"}


@router.get("")
def list_lectures(db: Session = Depends(get_db), q: Optional[str] = Query(None), limit: int = 50):
    lectures = db.query(Lecture).order_by(Lecture.created_at.desc()).limit(limit).all()
    if q:
        lectures = [l for l in lectures if q.lower() in l.title.lower()]
    result = []
    for l in lectures:
        result.append({
            "id": l.id,
            "title": l.title,
            "filename": l.original_filename,
            "status": l.status,
            "progress": l.progress,
            "error": l.error_message,
            "created_at": l.created_at.isoformat() if l.created_at else None,
            "duration": l.duration_seconds,
            "file_size": l.file_size
        })
    return result

@router.get("/{lecture_id}")
def get_lecture(lecture_id: int, db: Session = Depends(get_db)):
    lecture = db.query(Lecture).filter(Lecture.id == lecture_id).first()
    if not lecture:
        raise HTTPException(status_code=404, detail="المحاضرة غير موجودة")
    
    transcript = db.query(Transcript).filter(Transcript.lecture_id == lecture_id).first()
    summaries = db.query(Summary).filter(Summary.lecture_id == lecture_id).all()
    glossary = db.query(GlossaryItem).filter(GlossaryItem.lecture_id == lecture_id).all()
    quiz = db.query(Quiz).filter(Quiz.lecture_id == lecture_id).first()
    
    return {
        "id": lecture.id,
        "title": lecture.title,
        "filename": lecture.original_filename,
        "status": lecture.status,
        "progress": lecture.progress,
        "error": lecture.error_message,
        "created_at": lecture.created_at.isoformat() if lecture.created_at else None,
        "mime_type": lecture.mime_type,
        "is_media": _looks_media(lecture.file_path or ""),
        "transcript": {
            "text": transcript.full_text if transcript else None,
            "segments": transcript.segments if transcript else [],
            "word_count": transcript.word_count if transcript else 0
        } if transcript else None,
        "summaries": [{"id": s.id, "level": s.level, "content": s.content} for s in summaries],
        "glossary": [{"id": g.id, "term_ar": g.term_ar, "term_en": g.term_en, "definition": g.definition} for g in glossary],
        "quiz": {
            "id": quiz.id,
            "questions": quiz.questions
        } if quiz else None,
        "topics": serialize_topics(db, lecture_id)
    }

@router.get("/{lecture_id}/progress")
def get_progress(lecture_id: int, db: Session = Depends(get_db)):
    """للـ polling من الواجهة كل ثانيتين"""
    lecture = db.query(Lecture).filter(Lecture.id == lecture_id).first()
    if not lecture:
        raise HTTPException(status_code=404, detail="غير موجود")
    return {"status": lecture.status, "progress": lecture.progress, "error": lecture.error_message}

@router.post("/{lecture_id}/retry")
def retry_lecture(lecture_id: int, force: bool = Query(False), db: Session = Depends(get_db)):
    """
    إعادة المعالجة. مع force=true تُعاد معالجة محاضرة مكتملة أيضاً
    (مفيد بعد تغيير الإعدادات أو النماذج).
    """
    lecture = db.query(Lecture).filter(Lecture.id == lecture_id).first()
    if not lecture:
        raise HTTPException(status_code=404, detail="غير موجود")
    if lecture.status == "done" and not force:
        return {"message": "المحاضرة مكتملة بالفعل", "hint": "أضف force=true لإعادة المعالجة من جديد"}
    
    lecture.status = "queued"
    lecture.progress = 0
    lecture.error_message = None
    db.commit()
    
    dispatch_processing(lecture.id)
    return {"message": "تمت إعادة المحاولة", "status": "queued"}

@router.delete("/{lecture_id}")
def delete_lecture(lecture_id: int, db: Session = Depends(get_db)):
    lecture = db.query(Lecture).filter(Lecture.id == lecture_id).first()
    if not lecture:
        raise HTTPException(status_code=404, detail="غير موجود")
    # حذف الملف
    try:
        if lecture.file_path and os.path.exists(lecture.file_path):
            os.remove(lecture.file_path)
    except:
        pass
    db.delete(lecture)
    db.commit()
    return {"message": "تم الحذف"}

# === بث الملف الأصلي (للمشغل الصوتي/المرئي في الواجهة) ===
@router.get("/{lecture_id}/media")
def stream_media(lecture_id: int, db: Session = Depends(get_db)):
    """بث ملف المحاضرة الأصلي (يدعم Range حتى يعمل تقديم/تأخير المشغل)"""
    lecture = db.query(Lecture).filter(Lecture.id == lecture_id).first()
    if not lecture:
        raise HTTPException(status_code=404, detail="المحاضرة غير موجودة")
    ext = os.path.splitext(lecture.file_path or "")[1].lower()
    media_types = {
        ".mp3": "audio/mpeg", ".wav": "audio/wav", ".m4a": "audio/mp4",
        ".aac": "audio/aac", ".ogg": "audio/ogg", ".flac": "audio/flac",
        ".webm": "audio/webm", ".mp4": "video/mp4", ".mov": "video/quicktime",
        ".avi": "video/x-msvideo",
    }
    if ext not in media_types:
        raise HTTPException(status_code=400, detail="هذا الملف نصي وليس صوتاً أو فيديو، لا يمكن تشغيله في المشغل")
    if not lecture.file_path or not os.path.exists(lecture.file_path):
        raise HTTPException(status_code=404, detail="ملف المحاضرة غير موجود على القرص")
    return FileResponse(lecture.file_path, media_type=media_types[ext])


# === التصدير ===
@router.get("/{lecture_id}/export/{format}")
def export_lecture(lecture_id: int, format: str, db: Session = Depends(get_db)):
    lecture = db.query(Lecture).filter(Lecture.id == lecture_id).first()
    if not lecture:
        raise HTTPException(status_code=404, detail="المحاضرة غير موجودة")
    if lecture.status != "done":
        raise HTTPException(status_code=400, detail="المحاضرة لم تكتمل بعد")
    
    transcript = db.query(Transcript).filter(Transcript.lecture_id == lecture_id).first()
    summaries = db.query(Summary).filter(Summary.lecture_id == lecture_id).all()
    glossary = db.query(GlossaryItem).filter(GlossaryItem.lecture_id == lecture_id).all()
    quiz = db.query(Quiz).filter(Quiz.lecture_id == lecture_id).first()
    topics = serialize_topics(db, lecture_id)
    
    export_dir = settings.export_path
    os.makedirs(export_dir, exist_ok=True)
    
    if format == "markdown" or format == "md":
        content = export_markdown(lecture, transcript, summaries, glossary, quiz, topics)
        path = os.path.join(export_dir, f"lecture_{lecture_id}.md")
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return FileResponse(path, media_type="text/markdown", filename=f"{lecture.title}.md")
    
    elif format == "json":
        content = export_json(lecture, transcript, summaries, glossary, quiz, topics)
        path = os.path.join(export_dir, f"lecture_{lecture_id}.json")
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return FileResponse(path, media_type="application/json", filename=f"{lecture.title}.json")
    
    elif format == "pdf":
        path = os.path.join(export_dir, f"lecture_{lecture_id}.pdf")
        export_pdf(lecture, transcript, summaries, glossary, quiz, path, topics)
        return FileResponse(path, media_type="application/pdf", filename=f"{lecture.title}.pdf")
    
    elif format == "docx":
        path = os.path.join(export_dir, f"lecture_{lecture_id}.docx")
        export_docx(lecture, transcript, summaries, glossary, quiz, path, topics)
        return FileResponse(path, media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document", filename=f"{lecture.title}.docx")
    
    elif format == "txt":
        content = export_markdown(lecture, transcript, summaries, glossary, quiz, topics)
        path = os.path.join(export_dir, f"lecture_{lecture_id}.txt")
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return FileResponse(path, media_type="text/plain", filename=f"{lecture.title}.txt")
    
    else:
        raise HTTPException(status_code=400, detail="صيغة غير مدعومة. المتاح: pdf, docx, markdown, json, txt")

@router.post("/transcribe_youtube")
async def transcribe_youtube(url: str = Form(...), title: Optional[str] = Form(None), db: Session = Depends(get_db)):
    """تحميل صوت YouTube عبر yt-dlp ثم معالجته"""
    if "youtube.com" not in url and "youtu.be" not in url:
        raise HTTPException(status_code=400, detail="رابط YouTube غير صالح")
    
    import subprocess
    tmp_path = os.path.join(settings.storage_path, f"yt_{uuid.uuid4().hex}.mp3")
    try:
        cmd = ["yt-dlp", "-x", "--audio-format", "mp3", "-o", tmp_path, url]
        subprocess.run(cmd, check=True, timeout=120, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        # إيجاد الملف المحمل (yt-dlp قد يغير الاسم)
        actual = tmp_path
        if not os.path.exists(actual):
            # ابحث عن أي ملف yt_*
            for f in os.listdir(settings.storage_path):
                if f.startswith(os.path.basename(tmp_path).split(".")[0]):
                    actual = os.path.join(settings.storage_path, f)
                    break
        
        user = get_or_create_user(db)
        lecture = Lecture(
            user_id=user.id,
            title=title or f"YouTube: {url[:50]}",
            original_filename=url,
            file_path=actual,
            file_hash=calculate_file_hash(actual) if os.path.exists(actual) else uuid.uuid4().hex,
            file_size=os.path.getsize(actual) if os.path.exists(actual) else 0,
            mime_type="audio/mpeg",
            status="queued",
            progress=0
        )
        db.add(lecture)
        db.commit()
        db.refresh(lecture)
        
        dispatch_processing(lecture.id)
        
        return {"id": lecture.id, "title": lecture.title, "status": "queued", "message": "جاري تحميل ومعالجة رابط YouTube"}
    
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=400, detail="انتهت مهلة تحميل الفيديو")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"فشل تحميل YouTube: {str(e)[:300]}")

"""
خط المعالجة الكامل (بدون اعتماد على Celery)
يمكن استدعاؤه من Celery أو من Thread مباشرة عند عدم توفر Redis
"""
import os
import asyncio
from app.core.database import SessionLocal
from app.core.config import settings
from app.models.lecture import Lecture, Job, Transcript, Summary, GlossaryItem, Quiz, Topic, TopicResource
from app.services.stt import stt_service
from app.services.llm import llm_service
from app.services.topics import extract_topics
from app.services.resources import link_topics

AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".mp4", ".aac", ".ogg", ".flac", ".webm", ".mov", ".avi"}
TEXT_EXTS = {".pdf", ".docx", ".txt", ".md", ".pptx"}


def _update(lecture, db, status: str, progress: int, error: str | None = None):
    """تحديث حالة المحاضرة في قاعدة البيانات (يقرأها polling الواجهة)"""
    lecture.status = status
    lecture.progress = progress
    if error is not None:
        lecture.error_message = error
    db.commit()
    print(f"[Pipeline {lecture.id}] {status} - {progress}%")


def extract_text(file_path: str, hint: str = "") -> tuple[str, list]:
    """
    استخراج النص من أي ملف: صوت/فيديو عبر STT، أو مستند مباشرة.
    hint: عنوان المحاضرة يُمرَّر لمحرك التفريغ كتلميح مصطلحات.
    """
    ext = os.path.splitext(file_path)[1].lower()
    if ext in TEXT_EXTS:
        return stt_service.transcribe_text_file(file_path)
    if ext in AUDIO_EXTS:
        return stt_service.transcribe(file_path, hint=hint)
    # محاولة صوت أولاً ثم مستند
    try:
        return stt_service.transcribe(file_path, hint=hint)
    except Exception:
        return stt_service.transcribe_text_file(file_path)


def run_pipeline(lecture_id: int, on_progress=None) -> dict:
    """
    تنفيذ المعالجة الكاملة: تفريغ → تلخيص → قاموس → أسئلة
    on_progress: دالة اختيارية للتقدم (تستخدمها Celery لتحديث حالتها)
    """
    db = SessionLocal()
    lecture = db.query(Lecture).filter(Lecture.id == lecture_id).first()
    if not lecture:
        db.close()
        return {"status": "failed", "error": "المحاضرة غير موجودة"}

    def progress(status: str, pct: int, error: str | None = None):
        _update(lecture, db, status, pct, error)
        if on_progress:
            try:
                on_progress(status, pct)
            except Exception:
                pass

    loop = None
    try:
        # 0) تنظيف أي نتائج سابقة (إعادة المحاولة يجب ألا تُكرّر الصفوف)
        db.query(TopicResource).filter(TopicResource.lecture_id == lecture.id).delete()
        db.query(Topic).filter(Topic.lecture_id == lecture.id).delete()
        db.query(Quiz).filter(Quiz.lecture_id == lecture.id).delete()
        db.query(GlossaryItem).filter(GlossaryItem.lecture_id == lecture.id).delete()
        db.query(Summary).filter(Summary.lecture_id == lecture.id).delete()
        db.query(Transcript).filter(Transcript.lecture_id == lecture.id).delete()
        db.commit()

        # 1) التفريغ / استخراج النص
        progress("transcribing", 10)
        full_text, segments = extract_text(lecture.file_path, hint=lecture.title or "")
        if not full_text or len(full_text.strip()) < 10:
            raise ValueError("النص المستخرج فارغ أو قصير جداً. تأكد أن الملف يحتوي على كلام واضح أو نص قابل للقراءة.")

        transcript = Transcript(
            lecture_id=lecture.id,
            full_text=full_text,
            segments=segments,
            language="ar",
            word_count=len(full_text.split()),
        )
        db.add(transcript)
        db.commit()
        progress("transcribing", 40)

        # حلقة async واحدة لكل استدعاءات LLM
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        # 2) التلخيصات
        progress("summarizing", 50)
        try:
            summaries_data = loop.run_until_complete(llm_service.generate_summaries(full_text))
        except Exception as e:
            print(f"[Pipeline] LLM summaries فشل: {e} - استخدام البديل المحلي")
            summaries_data = llm_service._local_summaries(full_text)

        for level in ("glimpse", "bullets", "page"):
            if summaries_data.get(level):
                db.add(Summary(lecture_id=lecture.id, level=level, title=level, content=summaries_data[level]))
        if summaries_data.get("top10"):
            db.add(Summary(lecture_id=lecture.id, level="top10", title="أهم 10 أفكار", content=summaries_data["top10"]))
        db.commit()
        progress("summarizing", 70)

        # 3) القاموس
        progress("glossary", 75)
        try:
            glossary_terms = loop.run_until_complete(llm_service.generate_glossary(full_text))
        except Exception as e:
            print(f"[Pipeline] LLM glossary فشل: {e}")
            glossary_terms = llm_service._local_glossary(full_text)

        for term in glossary_terms:
            db.add(GlossaryItem(
                lecture_id=lecture.id,
                term_ar=str(term.get("term_ar", ""))[:200],
                term_en=str(term.get("term_en", ""))[:200],
                definition=str(term.get("definition", ""))[:1000],
            ))
        db.commit()
        progress("glossary", 80)

        # 4) الأسئلة
        progress("quiz", 82)
        try:
            questions = loop.run_until_complete(llm_service.generate_quiz(full_text, count=10))
        except Exception as e:
            print(f"[Pipeline] LLM quiz فشل: {e}")
            questions = llm_service._local_quiz(full_text, 10)

        if questions:
            db.add(Quiz(lecture_id=lecture.id, questions=questions))
            db.commit()

        # 5) استخراج المواضيع من المحاضرة نفسها (بلا قوائم مواد مسبقة)
        progress("topics", 85)
        glossary_terms = [g.term_ar for g in db.query(GlossaryItem).filter(GlossaryItem.lecture_id == lecture.id).all()]
        topic_dicts = []
        try:
            topic_dicts = extract_topics(full_text, segments, glossary_terms)
        except Exception as e:
            print(f"[Pipeline] استخراج المواضيع فشل: {type(e).__name__}: {e}")

        topic_rows = []
        for t in topic_dicts:
            row = Topic(
                lecture_id=lecture.id,
                order_index=int(t.get("order_index") or 0),
                title=t.get("title") or "موضوع",
                excerpt=t.get("excerpt") or "",
                key_terms=t.get("key_terms") or [],
                start_seconds=int(t.get("start_seconds") or 0),
                end_seconds=int(t.get("end_seconds") or 0),
            )
            db.add(row)
            topic_rows.append(row)
        db.commit()
        for row in topic_rows:
            db.refresh(row)

        # 6) ربط كل موضوع بمصادر تعليمية حقيقية (يوتيوب/ويكيبيديا/ويكي الجامعة/arXiv)
        if settings.resources_enabled and topic_rows:
            progress("resources", 90)
            try:
                mapping = link_topics(
                    [
                        {"title": r.title, "key_terms": r.key_terms or []}
                        for r in topic_rows
                    ]
                )
                for idx, items in mapping.items():
                    if idx >= len(topic_rows):
                        continue
                    topic_row = topic_rows[idx]
                    for rank, item in enumerate(items):
                        db.add(
                            TopicResource(
                                topic_id=topic_row.id,
                                lecture_id=lecture.id,
                                provider=item.get("provider") or "web",
                                title=(item.get("title") or "")[:200],
                                url=(item.get("url") or "")[:500],
                                snippet=(item.get("snippet") or "")[:600],
                                thumbnail=(item.get("thumbnail") or None),
                                duration_seconds=item.get("duration_seconds"),
                                channel=(item.get("channel") or None),
                                query_used=(item.get("query_used") or "")[:300],
                                lang=item.get("lang") or "ar",
                                rank=rank,
                            )
                        )
                db.commit()
                total_links = sum(len(v) for v in mapping.values())
                print(f"[Pipeline] مصادر مرتبطة: {total_links} عبر {len(mapping)} موضوع")
            except Exception as e:  # noqa: BLE001
                print(f"[Pipeline] ربط المصادر فشل (غير قاتل): {type(e).__name__}: {e}")

        progress("done", 100)
        print(f"[Pipeline {lecture_id}] اكتملت بنجاح - {len(full_text.split())} كلمة")
        return {"status": "done", "lecture_id": lecture_id, "word_count": len(full_text.split())}

    except Exception as e:
        err = str(e)[:1000]
        print(f"[Pipeline {lecture_id}] فشل: {err}")
        try:
            progress("failed", lecture.progress, err)
            db.add(Job(lecture_id=lecture.id, task_type="process", status="failed", error_message=err))
            db.commit()
        except Exception:
            pass
        return {"status": "failed", "error": err}
    finally:
        if loop is not None:
            loop.close()
        db.close()

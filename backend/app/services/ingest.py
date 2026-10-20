"""
استقبال أي ملف — بلا قائمة صيغ وبلا سقف.

المبدأ: **لا نثق بالامتداد**. نفتح الملف ونفحص محتواه الحقيقي، ثم نختار
المسار المناسب:

    فيديو/صوت بأي حاوية  →  ffprobe يكتشف مسار الصوت  →  ffmpeg  →  Whisper
    مستند بأي صيغة        →  المستخرج المناسب (PDF/DOCX/PPTX/XLSX/ODT/EPUB/RTF/HTML…)
    صورة                  →  OCR
    أرشيف (zip/rar/7z)    →  يُفكّ ويُعالَج كل ما داخله
    ملف مجهول تماماً      →  فحص نصّي ذكي، وإن كان سليماً يُقبل كنص

كل مسار يُرجع (نص، مقاطع، وصف) موحّداً. أي فشل يُرجع رسالة تشرح ما جُرِّب.
"""
from __future__ import annotations

import io
import json
import mimetypes
import os
import re
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

Progress = Optional[Callable[[str], None]]


# ------------------------------------------------------------------ ffmpeg
def _ffprobe() -> Optional[str]:
    return shutil.which("ffprobe")


def _ffmpeg() -> Optional[str]:
    return shutil.which("ffmpeg")


def probe_media(path: str) -> Optional[Dict]:
    """يقرأ بطاقة الملف من ffprobe. يعيد None إن لم يكن وسائط."""
    exe = _ffprobe()
    if not exe:
        return None
    try:
        out = subprocess.run(
            [exe, "-v", "error", "-print_format", "json",
             "-show_format", "-show_streams", path],
            capture_output=True, timeout=120, check=True,
        ).stdout
        info = json.loads(out or b"{}")
        if not info.get("streams"):
            return None
        return info
    except Exception:
        return None


def media_summary(info: Dict) -> Dict:
    """يلخّص بطاقة الوسائط: نوع، مدة، أبعاد، وجود صوت/صورة."""
    streams = info.get("streams") or []
    has_audio = any(s.get("codec_type") == "audio" for s in streams)
    has_video = any(s.get("codec_type") == "video"
                    and s.get("disposition", {}).get("attached_pic", 0) == 0
                    for s in streams)
    try:
        duration = float((info.get("format") or {}).get("duration") or 0)
    except (TypeError, ValueError):
        duration = 0.0
    if not duration:
        for s in streams:
            try:
                duration = max(duration, float(s.get("duration") or 0))
            except (TypeError, ValueError):
                pass
    video = next((s for s in streams if s.get("codec_type") == "video"), {})
    audio = next((s for s in streams if s.get("codec_type") == "audio"), {})
    return {
        "has_audio": has_audio,
        "has_video": has_video,
        "duration": duration,
        "video_codec": video.get("codec_name"),
        "audio_codec": audio.get("codec_name"),
        "width": video.get("width"),
        "height": video.get("height"),
        "kind": "video" if has_video else ("audio" if has_audio else "unknown"),
    }


# ------------------------------------------------------------------ التصنيف
_MAGIC = [
    (b"%PDF", "pdf"),
    (b"{\\rtf", "rtf"),
    (b"PK\x03\x04", "zip"),
    (b"\xd0\xcf\x11\xe0", "ole"),        # doc/xls/ppt القديمة
    (b"\x1f\x8b", "gzip"),
    (b"7z\xbc\xaf\x27\x1c", "7z"),
    (b"Rar!\x1a\x07", "rar"),
    (b"\x89PNG", "image"),
    (b"\xff\xd8\xff", "image"),
    (b"GIF8", "image"),
    (b"BM", "image"),
    (b"II*\x00", "image"),
    (b"MM\x00*", "image"),
    (b"RIFF", "riff"),                   # wav/avi/webp
    (b"ID3", "media"),
    (b"fLaC", "media"),
    (b"OggS", "media"),
    (b"\x1aE\xdf\xa3", "media"),         # matroska/webm
    (b"\x00\x00\x00\x18ftyp", "media"),
    (b"\x00\x00\x00\x20ftyp", "media"),
]


def sniff(path: str) -> str:
    """نوع الملف من البايتات الأولى — أدقّ من الامتداد بكثير."""
    try:
        with open(path, "rb") as f:
            head = f.read(512)
    except Exception:
        return "unknown"
    # ftyp قد يبدأ بإزاحة مختلفة
    if b"ftyp" in head[:32]:
        return "media"
    for magic, kind in _MAGIC:
        if head.startswith(magic):
            return kind
    if head[:4] == b"PK\x03\x04":
        return "zip"
    return "unknown"


def zip_kind(path: str) -> str:
    """يميّز office/odf/epub عن zip عادي بداخل الأرشيف."""
    try:
        with zipfile.ZipFile(path) as z:
            names = z.namelist()[:200]
            low = [n.lower() for n in names]
            if any(n.startswith("word/") for n in low):
                return "docx"
            if any(n.startswith("ppt/") for n in low):
                return "pptx"
            if any(n.startswith("xl/") for n in low):
                return "xlsx"
            if "mimetype" in low:
                try:
                    mt = z.read("mimetype").decode("ascii", "ignore")
                except Exception:
                    mt = ""
                if "opendocument.text" in mt:
                    return "odt"
                if "opendocument.presentation" in mt:
                    return "odp"
                if "opendocument.spreadsheet" in mt:
                    return "ods"
                if "epub" in mt:
                    return "epub"
            if any(n.endswith(".epub") for n in low):
                return "epub"
    except Exception:
        pass
    return "zip"


# ------------------------------------------------------------------ أدوات نصية
def _html_to_text(raw: str) -> str:
    raw = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", raw)
    raw = re.sub(r"(?i)<br\s*/?>", "\n", raw)
    raw = re.sub(r"(?i)</(p|div|li|tr|h[1-6])>", "\n", raw)
    raw = re.sub(r"<[^>]+>", " ", raw)
    raw = (raw.replace("&nbsp;", " ").replace("&amp;", "&")
              .replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"'))
    return re.sub(r"[ \t]{2,}", " ", raw)


def _printable_ratio(text: str) -> float:
    if not text:
        return 0.0
    sample = text[:20000]
    good = sum(1 for ch in sample if ch.isprintable() or ch in "\n\r\t")
    return good / max(1, len(sample))


def read_text_smart(path: str) -> str:
    """يقرأ ملفاً نصياً بأي ترميز معقول (UTF-8/UTF-16/Windows-1256…)."""
    data = Path(path).read_bytes()
    for enc in ("utf-8-sig", "utf-8", "utf-16", "cp1256", "cp1252", "latin-1"):
        try:
            txt = data.decode(enc)
            if _printable_ratio(txt) > 0.85:
                return txt
        except (UnicodeDecodeError, LookupError):
            continue
    return data.decode("utf-8", errors="ignore")


def segments_from_text(text: str, per_para: bool = True) -> List[Dict]:
    """مقاطع تقديرية للمستندات (الواجهة تحتاج start/end لعرض الفقرات)."""
    paras = [p.strip() for p in re.split(r"\n{1,}", text) if p.strip()]
    segs, t = [], 0
    for p in paras[:4000]:
        words = max(1, len(p.split()))
        dur = max(3, int(words / 2.6))       # ≈155 كلمة/دقيقة
        segs.append({"start": t, "end": t + dur, "text": p[:600]})
        t += dur
    return segs


# ------------------------------------------------------------------ مستخرجات
def extract_pdf(path: str, on_progress: Progress = None) -> Tuple[str, List[Dict]]:
    try:
        import pymupdf as fitz
    except ImportError:  # pragma: no cover
        import fitz

    doc = fitz.open(path)
    chunks = []
    for i, page in enumerate(doc):
        chunks.append(page.get_text("text"))
        if on_progress and i % 10 == 0:
            on_progress(f"قراءة PDF — صفحة {i + 1}/{doc.page_count}")
    text = "\n".join(chunks).strip()
    pages = doc.page_count
    doc.close()

    if len(text) < 60:                      # ملف ممسوح ضوئياً
        ocr = ocr_pdf(path, on_progress)
        if len(ocr) > len(text):
            text = ocr
    return text, segments_from_text(text)


def extract_docx(path: str) -> Tuple[str, List[Dict]]:
    from docx import Document
    doc = Document(path)
    parts = [p.text for p in doc.paragraphs if p.text.strip()]
    for table in doc.tables:
        for row in table.rows:
            cells = [c.text.strip() for c in row.cells if c.text.strip()]
            if cells:
                parts.append(" | ".join(cells))
    text = "\n".join(parts)
    return text, segments_from_text(text)


def extract_pptx(path: str) -> Tuple[str, List[Dict]]:
    from pptx import Presentation
    prs = Presentation(path)
    parts = []
    for i, slide in enumerate(prs.slides, 1):
        parts.append(f"\n— شريحة {i} —")
        for shape in slide.shapes:
            if shape.has_text_frame and shape.text_frame.text.strip():
                parts.append(shape.text_frame.text.strip())
            if getattr(shape, "has_table", False):
                for row in shape.table.rows:
                    cells = [c.text.strip() for c in row.cells if c.text.strip()]
                    if cells:
                        parts.append(" | ".join(cells))
        if slide.has_notes_slide:
            note = slide.notes_slide.notes_text_frame.text.strip()
            if note:
                parts.append("[ملاحظات] " + note)
    text = "\n".join(parts)
    return text, segments_from_text(text)


def extract_xlsx(path: str) -> Tuple[str, List[Dict]]:
    try:
        import openpyxl
    except ImportError:
        raise ValueError("قراءة Excel تحتاج حزمة openpyxl — ثبّتها: pip install openpyxl")
    wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
    parts = []
    for ws in wb.worksheets:
        parts.append(f"\n— ورقة: {ws.title} —")
        for row in ws.iter_rows(values_only=True):
            cells = [str(c).strip() for c in row if c is not None and str(c).strip()]
            if cells:
                parts.append(" | ".join(cells))
    wb.close()
    text = "\n".join(parts)
    return text, segments_from_text(text)


def extract_odf(path: str) -> Tuple[str, List[Dict]]:
    """ODT/ODP/ODS: محتواها XML داخل zip."""
    with zipfile.ZipFile(path) as z:
        raw = z.read("content.xml").decode("utf-8", "ignore")
    raw = raw.replace("</text:p>", "\n").replace("</text:h>", "\n").replace("</table:table-cell>", " | ")
    text = _html_to_text(raw)
    return text, segments_from_text(text)


def extract_epub(path: str) -> Tuple[str, List[Dict]]:
    parts = []
    with zipfile.ZipFile(path) as z:
        for n in z.namelist():
            if n.lower().endswith((".xhtml", ".html", ".htm")):
                parts.append(_html_to_text(z.read(n).decode("utf-8", "ignore")))
    text = "\n".join(parts)
    return text, segments_from_text(text)


def extract_rtf(path: str) -> Tuple[str, List[Dict]]:
    raw = read_text_smart(path)
    raw = re.sub(r"\\'([0-9a-fA-F]{2})", lambda m: chr(int(m.group(1), 16)), raw)
    raw = re.sub(r"\\u(-?\d+)\??", lambda m: chr(int(m.group(1)) % 65536), raw)
    raw = re.sub(r"\\[a-zA-Z]+-?\d*\s?", " ", raw)
    raw = raw.replace("{", " ").replace("}", " ")
    text = re.sub(r"[ \t]{2,}", " ", raw).strip()
    return text, segments_from_text(text)


def extract_subtitles(path: str) -> Tuple[str, List[Dict]]:
    """SRT/VTT: نحتفظ بالتوقيتات الحقيقية — أدقّ من التقدير."""
    raw = read_text_smart(path)
    segs, lines = [], []
    cur = {"start": 0.0, "end": 0.0, "text": ""}
    pat = re.compile(r"(\d{1,2}):(\d{2}):(\d{2})[,.](\d{1,3})\s*-->\s*(\d{1,2}):(\d{2}):(\d{2})[,.](\d{1,3})")

    def secs(h, m, s, ms):
        return int(h) * 3600 + int(m) * 60 + int(s) + int(ms.ljust(3, "0")) / 1000

    for line in raw.splitlines():
        m = pat.search(line)
        if m:
            if cur["text"].strip():
                segs.append(cur)
            cur = {"start": secs(*m.groups()[:4]), "end": secs(*m.groups()[4:]),
                   "text": ""}
        elif line.strip() and not line.strip().isdigit() and line.strip().upper() != "WEBVTT":
            cur["text"] += line.strip() + " "
    if cur["text"].strip():
        segs.append(cur)
    text = " ".join(s["text"].strip() for s in segs)
    return text, segs


def ocr_image(path: str) -> str:
    try:
        import pytesseract
        from PIL import Image
    except ImportError:
        raise ValueError(
            "قراءة الصور تحتاج pytesseract + حزمة Pillow، وبرنامج Tesseract مثبَّتاً في النظام."
        )
    try:
        img = Image.open(path)
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        langs = "ara+eng"
        try:
            return pytesseract.image_to_string(img, lang=langs)
        except Exception:
            return pytesseract.image_to_string(img)
    except Exception as e:
        raise ValueError(f"تعذر تشغيل OCR على الصورة: {e}")


def ocr_pdf(path: str, on_progress: Progress = None) -> str:
    try:
        import pymupdf as fitz
    except ImportError:
        import fitz
    try:
        import pytesseract
        from PIL import Image
    except ImportError:
        return ""
    try:
        doc = fitz.open(path)
        out = []
        limit = min(doc.page_count, 60)
        for i in range(limit):
            if on_progress and i % 5 == 0:
                on_progress(f"OCR — صفحة {i + 1}/{limit}")
            pix = doc.load_page(i).get_pixmap(dpi=250)
            img = Image.open(io.BytesIO(pix.tobytes("png")))
            try:
                out.append(pytesseract.image_to_string(img, lang="ara+eng"))
            except Exception:
                out.append(pytesseract.image_to_string(img))
        doc.close()
        return "\n".join(out)
    except Exception as e:
        print(f"[OCR] فشل: {e}")
        return ""


def extract_legacy_office(path: str) -> str:
    """doc/ppt/xls القديمة: antiword/catdoc ثم LibreOffice إن وُجد."""
    for tool, args in (
        ("antiword", ["antiword", path]),
        ("catdoc", ["catdoc", path]),
    ):
        if shutil.which(tool):
            try:
                return subprocess.run(args, capture_output=True, timeout=120).stdout.decode(
                    "utf-8", "ignore")
            except Exception:
                pass
    if shutil.which("libreoffice") or shutil.which("soffice"):
        exe = shutil.which("libreoffice") or shutil.which("soffice")
        outdir = tempfile.mkdtemp(prefix="lo_")
        try:
            subprocess.run([exe, "--headless", "--convert-to", "txt:Text",
                            "--outdir", outdir, path],
                           capture_output=True, timeout=240)
            for f in os.listdir(outdir):
                if f.endswith(".txt"):
                    return Path(outdir, f).read_text(encoding="utf-8", errors="ignore")
        finally:
            shutil.rmtree(outdir, ignore_errors=True)
    raise ValueError(
        "ملف Office قديم (doc/ppt/xls) ولا يوجد محوّل متاح. "
        "احفظه بصيغة docx/pptx/xlsx أو PDF، أو ثبّت LibreOffice."
    )


# ------------------------------------------------------------------ الأرشيف
def extract_archive(path: str, hint: str, on_progress: Progress,
                    depth: int = 0) -> Tuple[str, List[Dict]]:
    if depth > 2:
        raise ValueError("أرشيف متداخل بعمق كبير — فكّه يدوياً وأعد الرفع.")
    texts, segs = [], []
    tmp = tempfile.mkdtemp(prefix="arc_")
    try:
        with zipfile.ZipFile(path) as z:
            members = [m for m in z.infolist() if not m.is_dir()][:80]
            total = sum(m.file_size for m in members)
            if total > 3 * 1024 ** 3:
                raise ValueError("محتوى الأرشيف أكبر من 3GB — فكّه وارفع الملفات المهمة.")
            z.extractall(tmp)
        for root, _dirs, files in os.walk(tmp):
            for fn in sorted(files):
                p = os.path.join(root, fn)
                if os.path.getsize(p) > 800 * 1024 ** 2:
                    continue
                try:
                    if on_progress:
                        on_progress(f"معالجة ما داخل الأرشيف: {fn}")
                    t, s = extract(p, hint=hint, on_progress=None, _depth=depth + 1)
                    if t and len(t.strip()) > 30:
                        texts.append(f"\n### {fn}\n{t}")
                        segs.extend(s)
                except Exception as e:
                    print(f"[Archive] تخطّي {fn}: {e}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return "\n".join(texts), segs


# ------------------------------------------------------------------ الواجهة
TEXT_EXTS = {
    ".txt", ".md", ".markdown", ".rst", ".log", ".csv", ".tsv", ".json", ".yaml",
    ".yml", ".xml", ".html", ".htm", ".xhtml", ".tex", ".py", ".js", ".ts",
    ".java", ".c", ".cpp", ".h", ".cs", ".php", ".rb", ".go", ".rs", ".sql",
    ".sh", ".bat", ".ini", ".conf", ".srt", ".vtt", ".sub", ".ass",
}
DOC_EXTS = {
    ".pdf": extract_pdf,
    ".docx": extract_docx,
    ".pptx": extract_pptx,
    ".xlsx": extract_xlsx,
    ".xlsm": extract_xlsx,
    ".odt": extract_odf,
    ".odp": extract_odf,
    ".ods": extract_odf,
    ".epub": extract_epub,
    ".rtf": extract_rtf,
    ".doc": lambda p: (extract_legacy_office(p), []),
    ".ppt": lambda p: (extract_legacy_office(p), []),
    ".xls": lambda p: (extract_legacy_office(p), []),
}
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp", ".heic", ".gif"}


def extract(path: str, hint: str = "", on_progress: Progress = None,
            _depth: int = 0) -> Tuple[str, List[Dict]]:
    """
    يستخرج النص من أي ملف — بالترتيب التالي:
      1) وسائط فيها صوت (فيديو/صوت بأي صيغة) → تفريغ آلي
      2) مستند معروف → المستخرج المناسب
      3) أرشيف → فكّ ومعالجة المحتوى
      4) صورة → OCR
      5) ملف مجهول → فحص نصّي ثم وسائط ثم OCR
    """
    ext = os.path.splitext(path)[1].lower()
    magic = sniff(path)

    # ---------- 1) وسائط: نحاول دائماً أولاً إذا بدا الملف وسائط ----------
    if magic in {"media", "riff", "unknown"} or ext in {
        ".mp3", ".wav", ".m4a", ".aac", ".ogg", ".oga", ".opus", ".flac",
        ".wma", ".amr", ".aiff", ".aif", ".mp4", ".m4v", ".mov", ".avi",
        ".mkv", ".webm", ".flv", ".wmv", ".mpg", ".mpeg", ".ts", ".mts",
        ".m2ts", ".3gp", ".3g2", ".ogv", ".vob", ".asf", ".rm", ".divx",
    }:
        info = probe_media(path)
        if info:
            meta = media_summary(info)
            if meta["has_audio"]:
                # استيراد هنا لتجنّب دورة الاستيراد مع stt
                from app.services.stt import stt_service
                if on_progress:
                    label = "فيديو" if meta["has_video"] else "تسجيل صوتي"
                    mins = int(meta["duration"] // 60)
                    on_progress(f"{label} — المدة {mins} دقيقة، بدء التفريغ")
                text, segs = stt_service.transcribe(path, hint=hint, on_progress=on_progress)
                return text, segs
            # وسائط بلا صوت (فيديو صامت) → OCR على لقطة إن أمكن
            frames = _video_frames_text(path)
            if frames:
                return frames, segments_from_text(frames)

    # ---------- 2) مستندات معروفة (بالامتداد أو بالبصمة) ----------
    fn = DOC_EXTS.get(ext)
    if fn is None and magic == "pdf":
        fn = extract_pdf
    if fn is None and magic == "zip":
        kind = zip_kind(path)
        fn = {"docx": extract_docx, "pptx": extract_pptx,
              "xlsx": extract_xlsx}.get(kind)
        if fn is None and kind in {"odt", "odp", "ods"}:
            fn = extract_odf
        if fn is None and kind == "epub":
            fn = extract_epub
        if fn is None:
            return extract_archive(path, hint, on_progress, _depth)
    if fn is None and magic == "rtf":
        fn = extract_rtf
    if fn is None and magic == "ole":
        fn = lambda p: (extract_legacy_office(p), [])
    if fn is not None:
        if on_progress:
            on_progress(f"قراءة {ext or 'المستند'} — استخراج النص")
        out = fn(path)
        text, segs = out if isinstance(out, tuple) else (out, [])
        if text.strip():
            return text, (segs or segments_from_text(text))

    # ---------- 3) أرشيف بامتداد غير معروف ----------
    if ext in {".zip", ".7z", ".rar", ".tar", ".gz", ".bz2", ".xz", ".tgz"}:
        return extract_archive(path, hint, on_progress, _depth)

    # ---------- 4) صور ----------
    if ext in IMAGE_EXTS or magic == "image":
        if on_progress:
            on_progress("قراءة صورة عبر OCR")
        text = ocr_image(path)
        return text, segments_from_text(text)

    # ---------- 5) نصّ بأي صيغة ----------
    if ext in {".srt", ".vtt", ".sub", ".ass"}:
        return extract_subtitles(path)

    if ext in TEXT_EXTS or magic == "unknown":
        raw = read_text_smart(path)
        if ext in {".html", ".htm", ".xhtml", ".xml"}:
            raw = _html_to_text(raw)
        if _printable_ratio(raw) > 0.75 and len(raw.strip()) > 30:
            return raw.strip(), segments_from_text(raw)

    raise ValueError(
        f"تعذر فهم محتوى الملف «{os.path.basename(path)}». "
        "جُرِّب: فحص الوسائط (ffprobe)، مستخرجات المستندات، فكّ الأرشيف، OCR، والقراءة النصية. "
        "إن كان الملف مشفّراً أو تالفاً فأعد تصديره."
    )


def _video_frames_text(path: str) -> str:
    """لعبة أخيرة: لقطات من فيديو صامت (شرائح مسجَّلة بلا صوت) → OCR."""
    exe = _ffmpeg()
    if not exe:
        return ""
    try:
        import pytesseract
        from PIL import Image
    except ImportError:
        return ""
    tmp = tempfile.mkdtemp(prefix="frames_")
    try:
        subprocess.run([exe, "-v", "error", "-i", path, "-vf", "fps=1/20,scale=1600:-1",
                        os.path.join(tmp, "f_%03d.png")],
                       capture_output=True, timeout=600)
        out = []
        for fn in sorted(os.listdir(tmp))[:60]:
            out.append(pytesseract.image_to_string(Image.open(os.path.join(tmp, fn)),
                                                   lang="ara+eng"))
        return "\n".join(out)
    except Exception:
        return ""
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

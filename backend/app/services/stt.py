"""
خدمة التفريغ الصوتي - نمط المزود القابل للتبديل
يدعم: local_whisper (faster-whisper) + groq
"""
import os
import subprocess
import shutil
import tempfile
from typing import List, Dict, Tuple
from app.core.config import settings

class STTService:
    def __init__(self):
        self.provider = settings.stt_provider
        self.model_name = settings.stt_model
        self._whisper_model = None

    def _load_local_model(self):
        """تحميل نموذج faster-whisper محلياً (مرة واحدة)"""
        if self._whisper_model is not None:
            return self._whisper_model
        try:
            from faster_whisper import WhisperModel
            # medium هو الأنسب لجهاز ممتاز بدون GPU (توازن دقة/سرعة)
            # large-v3 أدق لكن أبطأ وأثقل
            print(f"[STT] تحميل النموذج: {self.model_name} ...")
            self._whisper_model = WhisperModel(
                self.model_name,
                device="cpu",
                compute_type="int8",  # أقل استهلاك رام ومناسب لـ CPU
                download_root=settings.whisper_model_dir
            )
            print("[STT] تم تحميل النموذج بنجاح")
            return self._whisper_model
        except Exception as e:
            print(f"[STT] فشل تحميل faster-whisper: {e}")
            return None

    def _extract_audio(self, input_path: str) -> str:
        """
        يستخرج مسار الصوت من أي ملف (فيديو أو صوت بأي حاوية) إلى WAV 16kHz mono.
        -vn يمنع نسخ الفيديو داخل الملف الناتج، ويقلّل الحجم والذاكرة.
        """
        output_path = input_path + ".16k.wav"
        if os.path.exists(output_path) and os.path.getsize(output_path) > 1024:
            return output_path

        filters = []
        if settings.enable_denoise:
            # تقليل ضجيج القاعات/المروحة قبل التفريغ (خفيف ولا يشوّه الكلام)
            filters.append("highpass=f=80")
            filters.append("lowpass=f=7800")
        cmd = ["ffmpeg", "-y", "-v", "error", "-i", input_path, "-vn",
               "-map", "0:a:0", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le"]
        if filters:
            cmd += ["-af", ",".join(filters)]
        cmd.append(output_path)
        try:
            subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL,
                           stderr=subprocess.PIPE, timeout=3600)
            if os.path.exists(output_path) and os.path.getsize(output_path) > 1024:
                return output_path
        except subprocess.CalledProcessError as e:
            detail = (e.stderr or b"").decode("utf-8", "ignore")[-400:]
            print(f"[STT] ffmpeg تعذّر: {detail}")
        except Exception as e:
            print(f"[STT] ffmpeg استثناء: {e}")

        # إن كان الملف wav بصيغة غير مدعومة، نعيد المحاولة بالمسار الأصلي
        return input_path

    @staticmethod
    def _duration(path: str) -> float:
        """مدة الملف بالثواني عبر ffprobe (0 إن تعذّر)."""
        try:
            out = subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries", "format=duration",
                 "-of", "default=nw=1:nk=1", path],
                capture_output=True, timeout=60).stdout.decode("utf-8", "ignore").strip()
            return float(out)
        except Exception:
            return 0.0

    def _split_wav(self, wav_path: str, seconds: int) -> list:
        """يقسّم WAV طويلاً إلى أجزاء — يبقي الذاكرة ثابتة مهما طالت المحاضرة."""
        chunks = []
        tmpdir = tempfile.mkdtemp(prefix="stt_chunks_")
        out_pattern = os.path.join(tmpdir, "c_%04d.wav")
        try:
            subprocess.run(
                ["ffmpeg", "-y", "-v", "error", "-i", wav_path,
                 "-f", "segment", "-segment_time", str(seconds),
                 "-segment_format", "wav", "-reset_timestamps", "1",
                 "-c:a", "pcm_s16le", "-ar", "16000", "-ac", "1",
                 out_pattern],
                check=True, capture_output=True, timeout=7200)
            chunks = sorted(
                os.path.join(tmpdir, f) for f in os.listdir(tmpdir) if f.endswith(".wav")
            )
        except Exception as e:
            print(f"[STT] تعذّر التقسيم ({e}) — سنفرّغ الملف كاملاً")
        return chunks

    @staticmethod
    def _read_wav_mono16k(path: str):
        """
        قراءة WAV PCM 16kHz كـ float32 numpy — يتجنب الاعتماد على مكتبة av
        (تكثر فيها اختلافات الإصدارات). ffmpeg أنتج الملف بالفعل بصيغة pcm_s16le.
        يعيد None إن فشلت القراءة ليتم الرجوع إلى تمرير المسار.
        """
        try:
            import wave
            import numpy as np
            with wave.open(path, "rb") as wf:
                if wf.getnchannels() != 1 or wf.getsampwidth() != 2:
                    return None
                frames = wf.readframes(wf.getnframes())
            audio = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
            return audio
        except Exception as e:
            print(f"[STT] تعذر قراءة WAV محلياً: {e}")
            return None

    def transcribe_local(self, file_path: str, hint: str = "",
                         on_progress=None) -> Tuple[str, List[Dict]]:
        """
        تفريغ محلي عبر faster-whisper.
        المحاضرات الطويلة تُقسَّم آلياً إلى أجزاء (`AUDIO_CHUNK_SECONDS`) حتى تبقى
        الذاكرة ثابتة: محاضرة ساعة على جهاز عادي تعمل تماماً كما محاضرة دقيقة.
        """
        if not settings.stt_enabled:
            raise ValueError(
                "تفريغ الصوت معطَّل على هذا الخادم (STT_ENABLED=false). "
                "في النسخة المحلية اجعله true — النسخة المكتبية تدعم الصوت والفيديو بلا قيود."
            )
        model = self._load_local_model()
        if model is None:
            raise ValueError(
                "تعذر تحميل نموذج التفريغ المحلي (faster-whisper). "
                "ثبّت الحزمة: pip install faster-whisper، وتأكد من توفر مساحة كافية، "
                "أو بدّل STT_PROVIDER=groq مع مفتاح مجاني."
            )

        audio_path = self._extract_audio(file_path)
        total = self._duration(audio_path)

        base_prompt = (
            "هذه محاضرة تعليمية مسجّلة. قد تكون بأي لغة وبأي تخصص. "
            "اكتب المصطلحات الأجنبية والأسماء كما وردت، والأرقام بدقة."
        )
        initial_prompt = f"{hint.strip()}. {base_prompt}" if hint.strip() else base_prompt

        # auto = يكتشف اللغة بنفسه (محاضرات غير عربية تعمل أيضاً)
        lang = None if (settings.stt_language or "").lower() in {"", "auto", "detect"} \
            else settings.stt_language

        chunk_seconds = max(60, int(settings.audio_chunk_seconds or 900))
        pieces = self._split_wav(audio_path, chunk_seconds) if total > chunk_seconds else []
        chunk_dir = os.path.dirname(pieces[0]) if pieces else None
        derived = audio_path if audio_path != file_path else None

        detected_lang = {"code": lang}

        def run(audio_input, offset: float, chunk_len: float = 0.0, part_no: int = 1,
                parts_total: int = 1):
            segs, info = model.transcribe(
                audio_input,
                language=detected_lang["code"],
                beam_size=settings.whisper_beam_size,
                vad_filter=True,
                vad_parameters=dict(min_silence_duration_ms=500),
                initial_prompt=initial_prompt,
                condition_on_previous_text=False,
                word_timestamps=False,
            )
            out = []
            next_mark = 0.0
            for seg in segs:
                # تقدّم داخل الجزء نفسه: شريط لا يتجمد في محاضرة 15 دقيقة
                if on_progress and chunk_len > 0:
                    frac = min(0.99, (seg.end or 0) / chunk_len)
                    overall = (part_no - 1 + frac) / max(1, parts_total)
                    if overall - next_mark >= 0.03:
                        next_mark = overall
                        on_progress(f"__pct__{int(overall * 100)}")
                text = seg.text.strip()
                if text and text[-1] not in ".!?:؟،":
                    text += "."
                if text:
                    out.append({"start": round(seg.start + offset, 2),
                                "end": round(seg.end + offset, 2),
                                "text": text})
            # نثبّت اللغة بعد أول جزء حتى لا تتبدّل بين الأجزاء
            if detected_lang["code"] is None and out:
                code = getattr(info, "language", None)
                if code:
                    detected_lang["code"] = code
            return out, info

        segments_list: List[Dict] = []
        detected = None
        try:
         if pieces:
            for i, piece in enumerate(pieces):
                if on_progress:
                    mins = int(total // 60)
                    on_progress(f"تفريغ الجزء {i + 1}/{len(pieces)} من أصل {mins} دقيقة")
                arr = self._read_wav_mono16k(piece)
                part, info = run(piece if arr is None else arr, offset=i * chunk_seconds,
                                 chunk_len=self._duration(piece), part_no=i + 1,
                                 parts_total=len(pieces))
                detected = detected or getattr(info, "language", None)
                segments_list.extend(part)
         else:
            if on_progress and total:
                on_progress(f"تفريغ {int(total // 60)} دقيقة صوت")
            # نمرّر مصفوفة numpy دائماً: faster-whisper يمرّر المسار إلى
            # av.open(metadata_errors=...) وهذا المُعامل محذوف في av الحديث (>=16)
            # فيرمي TypeError. المصفوفة تتخطى av.decode_audio تماماً.
            arr = self._read_wav_mono16k(audio_path)
            if arr is None:
                raise ValueError(
                    "تعذّر قراءة الصوت بعد تحويله إلى WAV. تأكد أن ffmpeg يعمل: ffmpeg -version"
                )
            part, info = run(arr, 0.0)
            detected = getattr(info, "language", None)
            segments_list = part
        finally:
            # لا نترك ملفات وسيطة: محاضرة ساعة = مئات الميغابايت بلا داعٍ
            if chunk_dir:
                shutil.rmtree(chunk_dir, ignore_errors=True)
            if derived:
                try:
                    os.remove(derived)
                except OSError:
                    pass

        full_text = " ".join(s["text"] for s in segments_list).strip()
        print(f"[STT] تم التفريغ: {len(segments_list)} مقطع، "
              f"{len(full_text.split())} كلمة، اللغة: {detected}")
        return full_text, segments_list

    def transcribe_groq(self, file_path: str) -> Tuple[str, List[Dict]]:
        """تفريغ عبر Groq API (طبقة مجانية سريعة)"""
        if not settings.groq_api_key:
            raise ValueError("مفتاح Groq غير مضبوط. أضفه في .env (GROQ_API_KEY) أو غيّر STT_PROVIDER إلى local_whisper")
        
        from groq import Groq
        client = Groq(api_key=settings.groq_api_key)
        
        audio_path = self._extract_audio(file_path)
        
        with open(audio_path, "rb") as f:
            transcription = client.audio.transcriptions.create(
                file=(os.path.basename(audio_path), f.read()),
                model=settings.groq_stt_model,
                language="ar",
                response_format="verbose_json",
                timestamp_granularities=["segment"]
            )
        
        full_text = transcription.text
        segments_list = []
        if hasattr(transcription, 'segments') and transcription.segments:
            for seg in transcription.segments:
                segments_list.append({
                    "start": round(seg['start'], 2),
                    "end": round(seg['end'], 2),
                    "text": seg['text'].strip()
                })
        else:
            # في حال عدم وجود segments، نقسم النص
            segments_list = [{"start": 0, "end": 0, "text": full_text}]
        
        return full_text, segments_list

    def transcribe(self, file_path: str, hint: str = "",
                   on_progress=None) -> Tuple[str, List[Dict]]:
        """
        دالة موحدة - تختار المزود تلقائياً.
        hint: عنوان المحاضرة أو مصطلحاتها لتحسين دقة التفريغ (Hotwords).
        """
        if self.provider == "groq":
            return self.transcribe_groq(file_path)
        return self.transcribe_local(file_path, hint=hint, on_progress=on_progress)

    def transcribe_text_file(self, file_path: str) -> Tuple[str, List[Dict]]:
        """معالجة الملفات النصية مباشرة (PDF/DOCX/TXT) - ليست صوت"""
        ext = os.path.splitext(file_path)[1].lower()
        text = ""

        if ext == ".pdf":
            # PyMuPDF أسرع وأدق، ثم OCR إن كان الملف صوراً، ثم PyPDF2 كبديل أخير
            try:
                try:
                    import pymupdf as fitz  # الإصدارات الحديثة
                except ImportError:
                    import fitz  # الإصدارات الأقدم
                doc = fitz.open(file_path)
                for page in doc:
                    text += page.get_text("text") + "\n"
                doc.close()
                if len(text.strip()) < 50:
                    text = self._ocr_pdf(file_path)
            except ImportError:
                try:
                    import PyPDF2
                    with open(file_path, "rb") as f:
                        reader = PyPDF2.PdfReader(f)
                        for page in reader.pages:
                            text += (page.extract_text() or "") + "\n"
                except ImportError:
                    raise ValueError("مكتبة قراءة PDF غير مثبتة على الخادم. ثبّت pymupdf أو PyPDF2 (موجودة في requirements.txt داخل Docker).")
                except Exception:
                    raise ValueError("تعذر قراءة ملف PDF: قد يكون الملف تالفاً أو محمياً بكلمة مرور. جرّب ملفاً آخر أو أعد حفظه بصيغة PDF جديدة.")
            except Exception:
                raise ValueError("تعذر قراءة ملف PDF: قد يكون الملف تالفاً أو محمياً بكلمة مرور. جرّب ملفاً آخر أو أعد حفظه بصيغة PDF جديدة.")

        elif ext == ".docx":
            try:
                from docx import Document
                doc = Document(file_path)
                for para in doc.paragraphs:
                    text += para.text + "\n"
            except ImportError:
                raise ValueError("مكتبة قراءة Word غير مثبتة على الخادم (python-docx).")
            except Exception:
                raise ValueError("تعذر قراءة ملف Word: قد يكون الملف تالفاً. جرّب حفظه بصيغة PDF أو إعادة إنشائه.")

        elif ext in [".txt", ".md"]:
            try:
                with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                    text = f.read()
            except Exception:
                raise ValueError("تعذر قراءة الملف النصي: تأكد أن الملف سليم ومشفّر بترميز UTF-8.")

        elif ext == ".pptx":
            try:
                from pptx import Presentation
                prs = Presentation(file_path)
                for i, slide in enumerate(prs.slides, 1):
                    text += f"\n--- شريحة {i} ---\n"
                    for shape in slide.shapes:
                        if shape.has_text_frame:
                            text += shape.text + "\n"
            except ImportError:
                raise ValueError("مكتبة قراءة العروض غير مثبتة على الخادم (python-pptx).")
            except Exception:
                raise ValueError("تعذر قراءة ملف العرض (PPTX): قد يكون الملف تالفاً. جرّب حفظه بصيغة PDF.")

        else:
            raise ValueError(f"صيغة الملف غير مدعومة: {ext}. المدعوم: PDF, DOCX, PPTX, TXT, MD, وصيغ الصوت/الفيديو.")

        text = text.strip()
        if not text:
            text = "تعذر استخراج النص من الملف. قد يكون الملف فارغاً أو تالفاً."
        
        # إنشاء segments وهمية بناءً على الفقرات (للتوافق مع الواجهة)
        segments = []
        paragraphs = [p.strip() for p in text.split("\n") if p.strip()]
        for i, para in enumerate(paragraphs):
            segments.append({
                "start": i * 10,  # تقديري
                "end": (i+1) * 10,
                "text": para[:200]
            })
        
        return text, segments

    def _ocr_pdf(self, file_path: str) -> str:
        """OCR للـ PDF الممسوح (صور)"""
        try:
            try:
                import pymupdf as fitz
            except ImportError:
                import fitz
            import pytesseract
            from PIL import Image
            import io
            
            doc = fitz.open(file_path)
            text = ""
            for page_num in range(min(len(doc), 40)):  # أول 40 صفحة (توازن بين الوقت والتغطية)
                page = doc.load_page(page_num)
                pix = page.get_pixmap(dpi=300)
                img_data = pix.tobytes("png")
                img = Image.open(io.BytesIO(img_data))
                page_text = pytesseract.image_to_string(img, lang="ara+eng")
                text += page_text + "\n"
            return text
        except Exception as e:
            print(f"[OCR] فشل: {e}")
            return ""

# كائن وحيد
stt_service = STTService()

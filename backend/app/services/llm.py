"""
خدمة الذكاء التوليدي - Ollama محلي مجاناً + Groq/OpenAI كبديل
كل الدوال تعيد JSON منظم وتتحمل فشل LLM ببدائل محلية
"""
import json
import re
import httpx
from typing import List, Dict
from app.core.config import settings

class LLMService:
    def __init__(self):
        self.provider = settings.llm_provider
        self.ollama_url = settings.ollama_base_url
        self.ollama_model = settings.ollama_model

    async def _call_ollama(self, prompt: str, system: str = "", temperature: float = 0.3) -> str:
        """استدعاء Ollama المحلي"""
        url = f"{self.ollama_url}/api/generate"
        payload = {
            "model": self.ollama_model,
            "prompt": prompt,
            "system": system,
            "stream": False,
            "options": {"temperature": temperature, "num_predict": 2000}
        }
        # مهلة الاتصال قصيرة (3s) حتى لا يتجمد النظام إن كان Ollama مغلقاً،
        # ومهلة قراءة طويلة (180s) لأن توليد النص على CPU قد يطول.
        timeout = httpx.Timeout(connect=3.0, read=180.0, write=15.0, pool=5.0)
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.post(url, json=payload)
                resp.raise_for_status()
                data = resp.json()
                return data.get("response", "").strip()
        except Exception as e:
            print(f"[LLM] Ollama غير متاح ({type(e).__name__}) - استخدام البديل المحلي")
            return ""

    async def _call_groq(self, prompt: str, system: str = "") -> str:
        """استدعاء Groq كبديل"""
        if not settings.groq_llm_api_key:
            return ""
        try:
            from groq import Groq
            client = Groq(api_key=settings.groq_llm_api_key)
            resp = client.chat.completions.create(
                model="llama3-8b-8192",
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3,
                max_tokens=2000
            )
            return resp.choices[0].message.content
        except Exception as e:
            print(f"[LLM] Groq فشل: {e}")
            return ""

    async def generate(self, prompt: str, system: str = "", temperature: float = 0.3) -> str:
        """دالة موحدة"""
        if self.provider == "groq":
            result = await self._call_groq(prompt, system)
            if result:
                return result
            # fallback to ollama
            return await self._call_ollama(prompt, system, temperature)
        else:
            result = await self._call_ollama(prompt, system, temperature)
            if result:
                return result
            # fallback: إذا فشل Ollama، نعيد تلخيص بسيط محلي
            return self._fallback_local(prompt)

    def _fallback_local(self, prompt: str) -> str:
        """بديل محلي بلا LLM - تلخيص استخراجي بسيط"""
        # هذا يضمن أن المنصة تعمل حتى بدون Ollama
        print("[LLM] استخدام البديل المحلي (قواعد بسيطة)")
        return ""

    def _extract_json(self, text: str) -> str:
        """استخراج JSON من رد LLM حتى لو كان محاطاً بنص"""
        # إزالة markdown code block
        text = re.sub(r'```json\s*', '', text)
        text = re.sub(r'```\s*', '', text)
        # البحث عن أول { وآخر }
        start = text.find('{')
        end = text.rfind('}')
        if start != -1 and end != -1:
            return text[start:end+1]
        start = text.find('[')
        end = text.rfind(']')
        if start != -1 and end != -1:
            return text[start:end+1]
        return text

    # ====== 1. التلخيصات ======
    async def generate_summaries(self, transcript: str) -> Dict[str, str]:
        """توليد 3 مستويات تلخيص + أهم 10 أفكار"""
        # تقصير النص إذا كان طويلاً جداً (لحدود Ollama)
        truncated = transcript[:8000]
        
        system = "أنت أستاذ جامعي خبير في تلخيص المحاضرات باللغة العربية الفصحى. تلخص بأمانة من النص المعطى فقط ولا تخترع معلومات."

        prompt = f"""
من النص التالي لمحاضرة (بالعربية مع مصطلحات إنجليزية)، أنشئ 3 ملخصات:

النص:
\"\"\"
{truncated}
\"\"\"

المطلوب JSON فقط بهذا الشكل (بدون أي نص خارج JSON):
{{
  "glimpse": "لمحة سريعة 50 كلمة بالضبط",
  "bullets": "- نقطة 1\\n- نقطة 2\\n- نقطة 3\\n- نقطة 4\\n- نقطة 5",
  "page": "ملخص صفحة كاملة بعناوين وفقرات (200-300 كلمة)",
  "top10": "1. الفكرة الأولى\\n2. الفكرة الثانية\\n... حتى 10"
}}

قواعد:
- اعتمد فقط على النص المعطى
- لا تضف معلومات خارجية
- احتفظ بالمصطلحات الإنجليزية كما هي
- اللغة عربية فصحى واضحة
"""
        response = await self.generate(prompt, system, temperature=0.3)
        
        # محاولة تحليل JSON
        if response:
            try:
                json_str = self._extract_json(response)
                data = json.loads(json_str)
                return {
                    "glimpse": data.get("glimpse", "")[:500],
                    "bullets": data.get("bullets", ""),
                    "page": data.get("page", ""),
                    "top10": data.get("top10", "")
                }
            except Exception as e:
                print(f"[LLM] فشل تحليل JSON للتلخيص: {e}, الرد: {response[:500]}")
        
        # Fallback: تلخيص بسيط محلي
        return self._local_summaries(transcript)

    def _local_summaries(self, text: str) -> Dict[str, str]:
        """
        تلخيص استخراجي محلي (بدون LLM): يختار جملاً حرفية من المحاضرة.
        — لمحة: نجمع الجمل حتى نصل ≈50 كلمة (لا نكتفي بأول جملة قصيرة).
        — نقاط/صفحة/أهم 10: توزيع الجمل على المحاضرة كاملة لا على بدايتها فقط.
        """
        sentences = [s.strip() for s in re.split(r'[.!؟\n]+', text) if len(s.strip().split()) >= 4]
        if not sentences:
            fallback = text.strip()[:300]
            return {"glimpse": fallback, "bullets": f"- {fallback}", "page": fallback, "top10": f"1. {fallback}"}

        # 1) لمحة ≈ 50 كلمة
        glimpse_parts: List[str] = []
        words = 0
        for sent in sentences:
            glimpse_parts.append(sent)
            words += len(sent.split())
            if words >= 45:
                break
        glimpse = " ".join(glimpse_parts)
        if len(glimpse.split()) > 60:
            glimpse = " ".join(glimpse.split()[:55]) + "..."

        # 2) نقاط: حتى 6 جمل موزّعة على المحاضرة
        step = max(1, len(sentences) // 6)
        bullets_src = sentences[::step][:6]
        bullets = "\n".join(f"- {s[:160]}" for s in bullets_src)

        # 3) صفحة: حتى 10 جمل موزّعة
        step_page = max(1, len(sentences) // 10)
        page = "\n\n".join(sentences[::step_page][:10])

        # 4) أهم 10 أفكار: أول 10 جمل مفتاحية مرتبة حسب ورودها
        top10 = "\n".join(f"{i + 1}. {s[:120]}" for i, s in enumerate(sentences[:10]))

        return {"glimpse": glimpse, "bullets": bullets, "page": page, "top10": top10}

    # ====== 2. القاموس ======
    async def generate_glossary(self, transcript: str) -> List[Dict]:
        """استخراج 5-10 مصطلحات مع تعريف من السياق"""
        truncated = transcript[:6000]
        system = "أنت خبير في استخراج المصطلحات الأكاديمية. تشرح المصطلح من سياق المحاضرة فقط."
        prompt = f"""
من النص التالي، استخرج 5-10 مصطلحات مهمة (عربية أو إنجليزية) وعرّف كل مصطلح من سياق المحاضرة نفسها:

النص:
\"\"\"
{truncated}
\"\"\"

أعد JSON فقط:
{{
  "terms": [
    {{"term_ar": "الخوارزمية", "term_en": "Algorithm", "definition": "تعريف من سياق المحاضرة..."}},
    ...
  ]
}}

إن كان المصطلح إنجليزياً ضعه في term_en وترجمه في term_ar.
"""
        response = await self.generate(prompt, system, temperature=0.2)
        if response:
            try:
                data = json.loads(self._extract_json(response))
                terms = data.get("terms", data if isinstance(data, list) else [])
                return terms[:10]
            except Exception as e:
                print(f"[LLM] فشل قاموس: {e}")
        
        # Fallback: استخراج كلمات طويلة/إنجليزية
        return self._local_glossary(transcript)

    # ====== 3. الأسئلة ======
    async def generate_quiz(self, transcript: str, count: int = 10) -> List[Dict]:
        """
        توليد أسئلة اختيار من متعدد من نص المحاضرة فقط (استناداً حرفياً).
        إن فشل النموذج أو أعاد JSON غير صالح نرجع لبديل استخراجي محلي.
        """
        truncated = transcript[:6000]
        system = "أنت أستاذ يضع اختبارات دقيقة من نص المحاضرة فقط. لا تخرج عن النص ولا تخترع معلومات."
        prompt = f"""
من النص التالي، أنشئ {count} سؤال اختيار من متعدد (4 خيارات، إجابة واحدة صحيحة) مع شرح سبب صحة الإجابة:

النص:
\"\"\"
{truncated}
\"\"\"

أعد JSON فقط بهذا الشكل:
{{
  "questions": [
    {{
      "question": "ما تعريف ...؟",
      "options": ["خيار 1", "خيار 2", "خيار 3", "خيار 4"],
      "answer": 0,
      "explanation": "الإجابة (0) صحيحة لأن المحاضرة ذكرت...",
      "source_quote": "اقتباس حرفي من النص"
    }}
  ]
}}

قواعد:
- كل سؤال مستند إلى النص حرفياً
- لا تكرر الأسئلة
- الخيارات متقاربة الطول
- answer رقم من 0 إلى 3
"""
        response = await self.generate(prompt, system, temperature=0.4)
        if response:
            try:
                data = json.loads(self._extract_json(response))
                questions = data.get("questions", data if isinstance(data, list) else [])
                valid = []
                for q in questions:
                    if isinstance(q, dict) and q.get("question") and isinstance(q.get("options"), list) \
                            and len(q["options"]) == 4 and isinstance(q.get("answer"), int) \
                            and 0 <= q["answer"] <= 3:
                        valid.append(q)
                if len(valid) >= 5:
                    return valid[:count]
            except Exception as e:
                print(f"[LLM] فشل تحليل أسئلة JSON: {e}")

        return self._local_quiz(transcript, count)

    # ---------- بدائل محلية تُستخدم عندما لا يتوفر LLM ----------

    @staticmethod
    def _split_sentences(text: str) -> List[str]:
        """تقسيم النص إلى جمل/فقرات ذات معنى (>= 6 كلمات)"""
        parts = re.split(r'[.!؟\n]+|\s{2,}', text)
        return [p.strip() for p in parts if len(p.strip().split()) >= 6]

    @staticmethod
    def _first_sentence_with(term: str, sentences: List[str]) -> str:
        """الجملة الأولى التي ترد فيها الكلمة — تعريف من سياق المحاضرة نفسه"""
        for s in sentences:
            if term in s:
                return s.strip()
        return ""

    def _local_glossary(self, text: str) -> List[Dict]:
        """قاموس استخراجي: المصطلح الإنجليزي + أطول المصطلحات العربية، والتعريف من سياق المحاضرة"""
        sentences = self._split_sentences(text)
        result: List[Dict] = []
        seen = set()

        # 1) المصطلحات الإنجليزية (Computer, Algorithm ...)
        for w in re.findall(r'\b[A-Za-z][A-Za-z\-]{2,}\b', text):
            key = w.lower()
            if key in seen:
                continue
            seen.add(key)
            ctx = self._first_sentence_with(w, sentences)
            if not ctx:
                continue
            result.append({
                "term_ar": w,
                "term_en": w,
                "definition": ctx[:300],
            })
            if len(result) >= 5:
                break

        # 2) أطول الكلمات العربية (مرشحة كمفاهيم) مع تعريفها من السياق
        arabic_words = re.findall(r'[\u0600-\u06FF]{5,}', text)
        freq: Dict[str, int] = {}
        for w in arabic_words:
            freq[w] = freq.get(w, 0) + 1
        for w, _ in sorted(freq.items(), key=lambda kv: (-kv[1], -len(kv[0]))):
            if w in seen:
                continue
            ctx = self._first_sentence_with(w, sentences)
            if not ctx:
                continue
            seen.add(w)
            result.append({"term_ar": w, "term_en": "", "definition": ctx[:300]})
            if len(result) >= 8:
                break

        return result[:10]

    def _local_quiz(self, text: str, count: int) -> List[Dict]:
        """
        أسئلة محلية بلا LLM: «أكمل الفراغ» مع مشتتات مأخوذة من المحاضرة نفسها،
        والإجابة مُسندة باقتباس حرفي (اختبار الحقيقة الأرضية).
        """
        sentences = self._split_sentences(text)
        if not sentences:
            return []

        # بنك كلمات مفتاحية من النص لاستخدامه كمشتتات
        pool = [w for w in re.findall(r'[\u0600-\u06FF]{4,}|[A-Za-z]{4,}', text)]
        pool = list(dict.fromkeys(pool))

        questions: List[Dict] = []
        used_sentences = set()

        for sent in sentences:
            if len(questions) >= count:
                break
            if sent in used_sentences:
                continue

            words = sent.split()
            if len(words) < 6:
                continue

            # اختر كلمة مفتاحية طويلة من منتصف الجملة (وليست أول كلمة)
            candidates = [w for w in words[1:-1] if len(w.strip('،.:()')) >= 4]
            if not candidates:
                continue
            keyword = max(candidates, key=len).strip('،.:()')
            if keyword not in sent:
                continue

            # مشتتات من كلمات المحاضرة نفسها (لا كلمات عامة)
            distractors = [w for w in pool if w != keyword and len(w) >= 4][:40]
            if len(distractors) < 3:
                continue

            step = max(1, len(distractors) // 3)
            chosen = [distractors[i] for i in (0, step, min(2 * step, len(distractors) - 1))][:3]
            chosen = list(dict.fromkeys(chosen))
            if len(chosen) < 3:
                continue

            options = [keyword] + chosen
            # ترتيب ثابت مبني على طول الجملة (ليس عشوائياً حتى تبقى النتائج قابلة للتكرار)
            rotate = len(sent) % len(options)
            options = options[rotate:] + options[:rotate]

            questions.append({
                "question": f"أكمل الفراغ من المحاضرة: «{sent.replace(keyword, '______', 1)}»",
                "options": options,
                "answer": options.index(keyword),
                "explanation": f"الكلمة الصحيحة «{keyword}» وردت حرفياً في المحاضرة.",
                "source_quote": sent[:200],
            })
            used_sentences.add(sent)

        return questions[:count]

llm_service = LLMService()

"""
استخراج مواضيع المحاضرة تلقائياً — بلا أي قوائم مواد مسبقة.

المنهج:
  • إن توفّر LLM (Ollama/Groq): يطلب منه تقسيم المحاضرة إلى 3–8 مواضيع
    مع عنوان ومصطلحات مفتاحية ونص مقتطف لكل موضوع.
  • إن لم يتوفر: تقسيم استخراجي على أساس الكلمات/الجمل والطوابع الزمنية،
    مع استخراج المصطلحات الأكثر تكراراً كعنوان ومفاتيح بحث.

كل شيء مشتق من نص المحاضرة نفسه (glossary + النص)، لا من أي مقرر محدد.
"""
from __future__ import annotations

import json
import re
from typing import Dict, List, Optional

from app.services.llm import llm_service

# كلمات وظيفية عربية شائعة لا تصلح كمصطلح بحث
# وحدات قياس: لا تصلح كبداية لعنوان موضوع
UNIT_WORDS = {
    "كيلوجرام", "كيلوغرام", "كجم", "متر", "ثانية", "نيوتن", "جول", "واط",
    "فولت", "أمبير", "امبير", "مول", "كلفن", "سنتيمتر", "مللي",
}

AR_STOPWORDS = {
    "هذا", "هذه", "ذلك", "التي", "الذي", "الذين", "كان", "كانت", "يكون", "تكون",
    "على", "إلى", "الى", "عن", "من", "في", "مع", "أن", "ان", "إن", "او", "أو",
    "ثم", "لكن", "حتى", "بعد", "قبل", "بين", "كما", "كل", "بعض", "أي", "اي",
    "هو", "هي", "هم", "نحن", "أنا", "انت", "أنت", "ليس", "ليست", "حيث", "عندما",
    "لأن", "لان", "لذلك", "كذلك", "أيضا", "أيضاً", "ايضا", "جدا", "جداً", "مهم",
    "مهمة", "مثال", "أمثلة", "امثلة", "اليوم", "الآن", "الان", "هنا", "هناك",
    "درسنا", "نتحدث", "نتكلم", "نبدأ", "ذكرنا", "قلنا", "يعني", "بمعنى",
    "الأول", "الأولى", "الثاني", "الثانية", "الثالث", "الثالثة", "الرابع",
    "الأخير", "الأخيرة", "التالي", "التالية", "السابق", "السابقة",
    "رقم", "صفحة", "سؤال", "أسئلة", "اسئلة", "امتحان", "الامتحان",
    # أفعال وأدوات تترد كثيراً ولا تصلح عناوين ولا مصطلحات
    "يبقى", "تبقى", "لأنها", "لأنه", "تكون", "يكون", "كانت", "أصبح", "اصبح",
    "يوجد", "توجد", "نستخدم", "نستطيع", "يمكن", "يجب", "نجد", "نقول", "يعتبر",
    "تعتبر", "نسمي", "نلاحظ", "نلاحظ", "لاحظ", "لاحظنا", "سنرى", "رأينا",
    "المستخدمة", "المستخدم", "المذكورة", "السابق", "التالية", "المختلفة",
    "أكثر", "اكثر", "أقل", "اقل", "أكبر", "اكبر", "أصغر", "اصغر", "نفسه",
    "نفسها", "مثلاً", "مثلا", "مثل", "منها", "منه", "فيه", "فيها", "عليه",
    "عليها", "له", "لها", "بها", "به", "ذلك", "كذلك", "هؤلاء", "أولاً", "اولا",
    "ثانياً", "ثانيا", "أخيراً", "اخيرا", "طبعاً", "طبعا", "يعني", "بشكل",
    "بصورة", "عادة", "غالباً", "غالبا", "تقريباً", "تقريبا", "جداً", "جدا",
}


def _split_sentences(text: str) -> List[str]:
    parts = re.split(r"(?<=[.!؟])\s+|\n+", text)
    return [p.strip() for p in parts if len(p.strip().split()) >= 4]


def _tokenize(text: str) -> List[str]:
    """كلمات عربية (4+ حروف) وإنجليزية (4+ حروف) بعد استبعاد الكلمات الوظيفية"""
    words = re.findall(r"[\u0600-\u06FF]{4,}", text) + re.findall(r"\b[A-Za-z][A-Za-z\-]{3,}\b", text)
    out = []
    for w in words:
        base = re.sub(r"^(ال|و|ف|ب|ل|ك)", "", w)
        if base in AR_STOPWORDS or w in AR_STOPWORDS:
            continue
        if w.lower() in {"this", "that", "with", "from", "have", "will", "they", "their", "which", "there"}:
            continue
        out.append(w)
    return out


def _tidy(word: str) -> str:
    """إزالة الترقيم والتشكيل فقط — دون المساس بالبادئات (واو العطف جزء من العبارة)"""
    word = word.strip("،:.؛!؟()[]\"\u201c\u201d'")
    word = re.sub(r"[\u064B-\u065F\u0670\u0640]", "", word)
    return word


def _clean_term(word: str) -> str:
    """
    تنظيف مصطلح للعرض: إزالة الترقيم، ثم البادئات الملتصقة
    (و/ف/ب/ك/ل) إذا كان أصل الكلمة يبقى واضحاً — «بالكيلوجرام» → «كيلوجرام».
    الأفعال الماضية المؤنثة («ارتفعت») لا تصلح مصطلحاً فتُستبعد.
    """
    word = word.strip("،:.؛!؟()[]\"\u201c\u201d'")
    while len(word) > 3 and word.startswith("وو"):
        word = word[1:]          # ووحدة → وحدة
    if len(word) > 4 and word[0] in "وفبكل" and word[1:].startswith("ال"):
        word = word[1:]          # بالكيلوجرام → الكيلوجرام
    if len(word) > 4 and word.startswith("ال") and len(word) > 6:
        stem = word[2:]
        # نُبقي «ال» لأنها جزء من الاسم المعرّف في العناوين، لكن نكشف الفعل
        if stem.endswith("ت") and not stem.endswith("ة"):
            return ""
    if len(word) >= 5 and word.endswith("ت") and not word.startswith("ال"):
        return ""
    return word


def _phrase_counts(text: str) -> Dict[str, int]:
    """عدّ العبارات الثنائية المتكررة في المحاضرة (مرشّحات لعناوين مواضيع)"""
    counts: Dict[str, int] = {}
    for sentence in re.split(r"[.!؟\n]+", text):
        tokens = re.findall(r"[\u0600-\u06FF]{3,}|[A-Za-z][A-Za-z\-]{2,}", sentence)
        for i in range(len(tokens) - 1):
            a, b = tokens[i], tokens[i + 1]
            if a in AR_STOPWORDS or b in AR_STOPWORDS:
                continue
            key = f"{a} {b}"
            counts[key] = counts.get(key, 0) + 1
    return counts


def _candidate_phrases(
    block_text: str,
    scores: Dict[str, float],
    phrase_freq: Optional[Dict[str, int]] = None,
    k: int = 6,
) -> List[str]:
    """
    عبارات مركّبة مرتّبة داخل المقطع: كلمتان متجاورتان في نفس الجملة.
    تُؤخذ **حرفياً كما في المحاضرة** (بلا تركيب «و») حتى لا يتحول
    «الكمية المطلوبة» إلى «الكمية والمطلوبة»، أو «الكتلة والوزن» إلى «الكتلة ووزن».
    """
    scored: Dict[str, float] = {}
    for sentence in re.split(r"[.!؟\n]+", block_text):
        tokens = re.findall(r"[\u0600-\u06FF]{3,}|[A-Za-z][A-Za-z\-]{2,}", sentence)
        for i in range(len(tokens) - 1):
            a, b = tokens[i], tokens[i + 1]
            if a in AR_STOPWORDS or b in AR_STOPWORDS:
                continue
            if scores.get(a, 0) <= 0 and scores.get(b, 0) <= 0:
                continue
            value = scores.get(a, 0.0) + scores.get(b, 0.0)
            # العبارة المتكررة في المحاضرة تُرجَّح بقوة (مؤشر موضوع حقيقي)
            value *= 1.0 + 2.0 * (phrase_freq or {}).get(f"{a} {b}", 0)
            # عبارة تبدأ بوحدة قياس أو رقم ليست عنواناً جيداً
            if a in UNIT_WORDS or a.isdigit():
                value *= 0.25
            phrase = f"{a} {b}"
            scored[phrase] = max(scored.get(phrase, 0.0), value)

    clean: Dict[str, float] = {}
    for phrase, value in scored.items():
        # نحافظ على العبارة كما وردت حرفياً (بما فيها «والوزن») 
        words = [_tidy(w) for w in phrase.split()]
        if len(words) != 2 or not all(words):
            continue
        # واو العطف في **بداية** العنوان تُحذف («ووحدة التسارع» → «وحدة التسارع»)
        if words[0].startswith("وو"):
            words[0] = words[0][1:]
        elif words[0].startswith("وال") and len(words[0]) > 4:
            words[0] = words[0][1:]
        clean[" ".join(words)] = value

    ordered = sorted(clean.items(), key=lambda x: -x[1])
    return [p for p, _ in ordered[:k]]


def _best_phrase(block_text: str, scores: Dict[str, float], phrase_freq: Optional[Dict[str, int]] = None) -> Optional[str]:
    """أفضل عبارة واحدة (غلاف للتوافق)"""
    candidates = _candidate_phrases(block_text, scores, phrase_freq, k=1)
    return candidates[0][:90] if candidates else None


def _title_tokens(text: str) -> set:
    """كلمات العنوان للمقارنة: بلا «ال» وبلا «و» الملتصقة"""
    out = set()
    for w in re.findall(r"[\u0600-\u06FF]{3,}|[A-Za-z]{3,}", text or ""):
        w = re.sub(r"^و?ال", "", w)
        w = re.sub(r"^و", "", w)
        if w and w not in AR_STOPWORDS:
            out.add(w)
    return out


def _too_similar(title: str, existing: List[str]) -> bool:
    """عنوانان يتشاركان نصف الكلمات أو أكثر = موضوع مكرر"""
    a = _title_tokens(title)
    if not a:
        return False
    for other in existing:
        b = _title_tokens(other)
        if not b:
            continue
        inter = len(a & b)
        if inter and inter / min(len(a), len(b)) >= 0.5:
            return True
    return False


def _distinct_terms(words: List[str]) -> List[str]:
    """إزالة التكرار والتشابه الجذري (الكتلة/كتلة) مع الحفاظ على الترتيب"""
    out: List[str] = []
    for w in words:
        base = re.sub(r"^(ال|و|ف|ب|ل|ك)", "", w)
        if any(base and base in re.sub(r"^(ال|و|ف|ب|ل|ك)", "", x) for x in out):
            continue
        out.append(w)
    return out


def _block_scores(blocks: List[List[str]], glossary_terms: List[str]) -> List[List[str]]:
    """
    ترتيب الكلمات داخل كل مقطع بـ TF-IDF عبر المواضيع:
      tf  = تكرار الكلمة داخل المقطع
      idf = log(1 + عدد المواضيع / عدد المواضيع التي ترد فيها الكلمة)
    الكلمة الشائعة في كل المواضيع (مثل اسم المقرر) تفقد وزنها،
    والكلمة الخاصة بموضوع واحد تتصدر — وهذا ما يميّز عناوين المواضيع فعلياً.
    """
    import math

    block_texts = [" ".join(b) for b in blocks]
    tokenized = [_tokenize(t) for t in block_texts]
    n_blocks = max(1, len(blocks))

    # عدد المواضيع التي ترد فيها كل كلمة
    df: Dict[str, int] = {}
    for toks in tokenized:
        for w in set(toks):
            df[w] = df.get(w, 0) + 1

    results: List[List[str]] = []
    for toks in tokenized:
        tf: Dict[str, int] = {}
        for w in toks:
            tf[w] = tf.get(w, 0) + 1
        scored = []
        for w, count in tf.items():
            idf = math.log(1.0 + n_blocks / max(1, df.get(w, 1)))
            scored.append((w, count * idf))
        scored.sort(key=lambda x: (-x[1], -len(x[0])))
        results.append([w for w, _ in scored])
    return results


def _heuristic_topics(
    transcript: str,
    segments: List[dict],
    glossary_terms: List[str],
) -> List[dict]:
    """تقسيم استخراجي بلا LLM: مقاطع متساوية + عناوين مميّزة بـ TF-IDF"""
    sentences = _split_sentences(transcript)
    if not sentences:
        return []

    word_count = len(transcript.split())
    # عدد المواضيع يتناسب مع طول المحاضرة: 30 دقيقة ≈ 4 مواضيع، 3 ساعات ≈ 8
    n_topics = max(3, min(8, round(word_count / 220)))

    total = sum(len(s.split()) for s in sentences)
    target = max(1, total // n_topics)

    blocks: List[List[str]] = []
    current: List[str] = []
    current_words = 0
    for sent in sentences:
        current.append(sent)
        current_words += len(sent.split())
        if current_words >= target and len(blocks) < n_topics - 1:
            blocks.append(current)
            current = []
            current_words = 0
    if current:
        blocks.append(current)

    ranked_per_block = _block_scores(blocks, glossary_terms)
    phrase_freq = _phrase_counts(transcript)

    # درجات الكلمات لكل مقطع (لاختيار العبارات المركّبة)
    score_maps: List[Dict[str, float]] = []
    for block_sorted in ranked_per_block:
        score_maps.append({w: float(len(block_sorted) - i) for i, w in enumerate(block_sorted)})

    # أوقات البداية من المقاطع الصوتية إن وُجدت
    seg_times = [(s.get("start") or 0, s.get("text") or "") for s in segments]

    def _time_for(sentence: str, fallback: float) -> float:
        key = sentence[:25]
        for start, text in seg_times:
            if key and key in (text or ""):
                return float(start)
        return fallback

    topics: List[dict] = []
    used_titles: List[str] = []
    for idx, block in enumerate(blocks):
        block_text = " ".join(block)
        if len(block_text.split()) < 8:
            continue

        candidates = _distinct_terms(ranked_per_block[idx] if idx < len(ranked_per_block) else [])
        candidates = [
            _clean_term(c) for c in candidates
            if _clean_term(c) and _clean_term(c) not in AR_STOPWORDS
        ]

        # العنوان: أول عبارة من النص نفسه لا تُكرّر موضوعاً سابقاً
        phrases = _candidate_phrases(
            block_text, score_maps[idx] if idx < len(score_maps) else {}, phrase_freq, k=8
        )
        chosen = next((ph for ph in phrases if not _too_similar(ph, used_titles)), "")
        if not chosen:
            # لا عبارة مميّزة: كلمة واحدة مميّزة لم تُستخدم
            chosen = next((c for c in candidates if not _too_similar(c, used_titles)), "")
        title = chosen or (phrases[0] if phrases else (candidates[0] if candidates else f"الموضوع {idx + 1}"))
        used_titles.append(title)

        keys = _distinct_terms(
            [t for t in glossary_terms if t in block_text][:2] + candidates
        )[:4]

        start = _time_for(block[0], fallback=idx * 300.0)
        end = _time_for(block[-1], fallback=(idx + 1) * 300.0) + 60.0
        topics.append(
            {
                "title": title[:120],
                "excerpt": " ".join(block[:3])[:600],
                "key_terms": keys,
                "start_seconds": round(float(start), 1),
                "end_seconds": round(float(max(end, start + 30)), 1),
            }
        )
    return topics


async def _llm_topics(transcript: str, glossary_terms: List[str]) -> List[dict]:
    """تقسيم المحاضرة إلى مواضيع عبر LLM (أدق دلالياً)"""
    truncated = transcript[:9000]
    system = (
        "أنت أستاذ جامعي يجزّئ محاضرة إلى مواضيع مترابطة. "
        "تستخدم نص المحاضرة فقط ولا تخترع محتوى خارجياً."
    )
    prompt = f"""قسّم نص المحاضرة التالي إلى 3-8 مواضيع رئيسية (حسب طول المحاضرة).

النص:
\"\"\"
{truncated}
\"\"\"

أعد JSON فقط بهذا الشكل:
{{
  "topics": [
    {{
      "title": "عنوان قصير للموضوع (بلا رقم)",
      "excerpt": "جملة أو جملتان حرفيتان من المحاضرة تلخصان الموضوع",
      "key_terms": ["مصطلح1", "مصطلح2", "مصطلح3"]
    }}
  ]
}}

قواعد:
- العنوان من 2 إلى 6 كلمات، عربي (يمكن أن يحتوي مصطلحاً إنجليزياً)
- excerpt مقتبس حرفياً من النص
- key_terms من 2 إلى 4 مصطلحات واردة فعلاً في النص (عربية أو إنجليزية)
- لا تكرر الموضوع نفسه
"""
    response = await llm_service.generate(prompt, system, temperature=0.3)
    if not response:
        return []
    try:
        data = json.loads(llm_service._extract_json(response))
        raw = data.get("topics", data if isinstance(data, list) else [])
        topics: List[dict] = []
        for item in raw:
            if not isinstance(item, dict) or not item.get("title"):
                continue
            topics.append(
                {
                    "title": str(item["title"])[:120],
                    "excerpt": str(item.get("excerpt") or "")[:600],
                    "key_terms": [str(t) for t in (item.get("key_terms") or [])][:4],
                    "start_seconds": 0.0,
                    "end_seconds": 0.0,
                }
            )
        return topics
    except Exception as e:  # noqa: BLE001
        print(f"[Topics] فشل تحليل JSON: {e}")
        return []


def _llm_topics_sync(transcript: str, glossary_terms: List[str]) -> List[dict]:
    """تشغيل مسار LLM غير المتزامن من سياق متزامن (Celery/Thread)"""
    import asyncio

    try:
        try:
            asyncio.get_running_loop()
            running = True
        except RuntimeError:
            running = False

        if running:
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                return pool.submit(asyncio.run, _llm_topics(transcript, glossary_terms)).result(timeout=180)
        return asyncio.run(_llm_topics(transcript, glossary_terms))
    except Exception as e:  # noqa: BLE001
        print(f"[Topics] LLM غير متاح ({type(e).__name__}) — تقسيم استخراجي")
        return []


def extract_topics(transcript: str, segments: List[dict], glossary_terms: List[str]) -> List[dict]:
    """
    دالة موحدة: LLM إن أمكن، وإلا تقسيم استخراجي.
    تضبط أوقات البداية/النهاية لكل موضوع بناءً على المقاطع الصوتية.
    """
    topics = _llm_topics_sync(transcript, glossary_terms)
    if not topics or len(topics) < 2:
        topics = _heuristic_topics(transcript, segments, glossary_terms)

    # ضبط الأوقات: نبحث عن أول جملة من excerpt في المقاطع
    if segments:
        for t in topics:
            if t.get("start_seconds"):
                continue
            probe = (t.get("excerpt") or t.get("title") or "")[:25]
            for seg in segments:
                text = (seg.get("text") or "")
                if probe and probe in text:
                    t["start_seconds"] = float(seg.get("start") or 0)
                    break
            else:
                t["start_seconds"] = 0.0
            if not t.get("end_seconds"):
                t["end_seconds"] = t["start_seconds"] + 120.0

    for idx, t in enumerate(topics):
        t.pop("_match", None)
        t["order_index"] = idx
        t["title"] = (t.get("title") or f"الموضوع {idx + 1}")[:120]
        t["key_terms"] = [k for k in (t.get("key_terms") or []) if k][:4]

    return topics


def _llm_topics_sync(transcript: str, glossary_terms: List[str]) -> List[dict]:
    """تشغيل دالة LLM غير المتزامنة من داخل سياق متزامن (Celery/Thread)"""
    import asyncio

    try:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if loop and loop.is_running():
            # داخل event loop قائم: ننفذ في خيط منفصل
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                return pool.submit(asyncio.run, _llm_topics(transcript, glossary_terms)).result(timeout=180)
        return asyncio.run(_llm_topics(transcript, glossary_terms))
    except Exception as e:  # noqa: BLE001
        print(f"[Topics] LLM غير متاح ({type(e).__name__}) — تقسيم استخراجي")
        return []

"""
خدمة ربط المواضيع بمصادر تعليمية حقيقية — بلا مفاتيح API وبلا تكلفة.

المزودون (كلهم حقيقيون ومُختبرون):
  1. youtube   : بحث YouTube عبر yt-dlp (ytsearch) — يعيد معرّفات فيديو حقيقية
  2. wikipedia : MediaWiki API — ar.wikipedia.org (مجاني، بلا مفتاح)
  3. wikiversity/wikibooks : MediaWiki API — محتوى تعليمي عربي حر
  4. arxiv     : arXiv API — أوراق أكاديمية (بحث إنجليزي فقط)

مبادئ التصميم:
  • كل مزود معزول: فشله لا يوقف البقية (best-effort).
  • مهلة زمنية قصيرة + محاولة إعادة واحدة.
  • تنظيف وتوحيد النتائج وإزالة التكرار بالرابط.
  • لا نخزّن محتوى الخارجي، فقط روابط وبيانات وصفية (عنوان/قناة/مدة).
"""
from __future__ import annotations

import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Optional
from urllib.parse import quote

import httpx

from app.core.config import settings

USER_AGENT = "Tarboush/1.0 (open-source educational platform; contact: local)"

PROVIDER_LABELS = {
    "youtube": "YouTube",
    "wikipedia": "ويكيبيديا",
    "wikiversity": "ويكي الجامعة",
    "wikibooks": "ويكي الكتب",
    "arxiv": "arXiv (أكاديمي)",
}


# ============================ أدوات مساعدة ============================
def _clean_html(text: str) -> str:
    """إزالة وسوم HTML من مقاطع البحث (ويكيبيديا ترجع <span class=...>)"""
    text = re.sub(r"<[^>]+>", "", text or "")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _is_english(text: str) -> bool:
    letters = re.findall(r"[A-Za-z]", text or "")
    return len(letters) >= max(3, len(re.findall(r"[\u0600-\u06FF]", text or "")) // 2)


def _short(text: str, limit: int = 220) -> str:
    text = (text or "").strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


# ============================ المزودون ============================
def search_youtube(query: str, limit: int = 3) -> List[Dict]:
    """
    بحث YouTube حقيقي عبر yt-dlp (نفس محرك التحميل).
    نفلتر المدة: 90 ثانية إلى ساعتين — لتجنّب المقاطع القصيرة والبثوث الطويلة.

    ملاحظة واقعية: يوتيوب يحجب أحياناً عناوين مراكز البيانات (403 Forbidden)،
    لذلك نعيد المحاولة بعميل مختلف (android/web) قبل التسليم بفشل البحث.
    """
    try:
        import yt_dlp
    except ImportError:
        print("[Resources] yt-dlp غير مثبت")
        return []

    cache_key = ("youtube", query, limit)
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    base_opts = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": True,
        "skip_download": True,
        "socket_timeout": settings.resource_search_timeout,
    }
    clients: List[Dict] = [
        {},                                                # الافتراضي (web)
        {"extractor_args": {"youtube": {"player_client": ["android"]}}},
        {"extractor_args": {"youtube": {"player_client": ["tv"]}}},
    ]

    results: List[Dict] = []
    for attempt, extra in enumerate(clients, 1):
        opts = {**base_opts, **extra}
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(f"ytsearch{limit * 2}:{query}", download=False)
            for entry in (info or {}).get("entries") or []:
                vid = entry.get("id")
                if not vid:
                    continue
                duration = entry.get("duration") or 0
                if duration and not (90 <= duration <= 7200):
                    continue
                results.append(
                    {
                        "provider": "youtube",
                        "title": _short(entry.get("title") or "فيديو", 140),
                        "url": f"https://www.youtube.com/watch?v={vid}",
                        "snippet": _short(entry.get("description") or "", 200),
                        "thumbnail": f"https://i.ytimg.com/vi/{vid}/mqdefault.jpg",
                        "duration_seconds": int(duration) if duration else None,
                        "channel": _short(entry.get("channel") or entry.get("uploader") or "", 60),
                        "lang": "ar",
                    }
                )
                if len(results) >= limit:
                    break
            if results:
                break
        except Exception as e:  # noqa: BLE001
            print(f"[Resources] YouTube محاولة {attempt}/{len(clients)}: {type(e).__name__}")
            continue

    # لا نُخزّن نتيجة فاشلة في الكاش حتى تُعاد المحاولة في المرة القادمة
    if results:
        _cache_set(cache_key, results)
    return results


# MediaWiki يرفض الطلبات المتوازية الكثيرة (429). نُنظّمها: طلب واحد كل فترة.
# كلمات عامة لا تصلح مقياساً للصلة («وحدة»، «معنى»...) — تُستبعد من حساب التطابق
GENERIC_WORDS = {
    "وحده", "وحدات", "معني", "مفهوم", "اساسيات", "مقدمه", "درس", "شرح",
    "ملخص", "نوع", "انواع", "طريقه", "حالات", "امثله", "تعريف", "علاقه",
    "اهميه", "مدخل", "ملاحظات", "تطبيقات", "مقارنه", "مراجعه",
}

_CACHE: Dict[tuple, tuple] = {}
_CACHE_TTL = 6 * 3600


def _cache_get(key: tuple):
    hit = _CACHE.get(key)
    if not hit:
        return None
    ts, value = hit
    if time.time() - ts > _CACHE_TTL:
        _CACHE.pop(key, None)
        return None
    return value


def _cache_set(key: tuple, value):
    if len(_CACHE) > 500:
        _CACHE.clear()
    _CACHE[key] = (time.time(), value)
    return value


_WIKI_LOCK = threading.Lock()
_WIKI_LAST_CALL = [0.0]
_WIKI_MIN_INTERVAL = 0.6


def _wiki_get(host: str, query: str, limit: int) -> List[Dict]:
    """طلب بحث واحد إلى MediaWiki مع احترام الفاصل الزمني وإعادة المحاولة عند 429/5xx"""
    params = {
        "action": "query",
        "list": "search",
        "srsearch": query,
        "srlimit": limit,
        "format": "json",
        "utf8": 1,
    }
    delay = 0.0
    for attempt in range(4):
        with _WIKI_LOCK:
            wait = _WIKI_MIN_INTERVAL - (time.time() - _WIKI_LAST_CALL[0])
            if wait > 0:
                time.sleep(wait)
            try:
                with httpx.Client(timeout=settings.resource_search_timeout,
                                  headers={"User-Agent": USER_AGENT},
                                  follow_redirects=True) as client:
                    resp = client.get(f"https://{host}/w/api.php", params=params)
                _WIKI_LAST_CALL[0] = time.time()
                if resp.status_code in (429, 500, 502, 503, 504):
                    retry_after = resp.headers.get("Retry-After", "")
                    raise httpx.HTTPStatusError(f"HTTP {resp.status_code}", request=resp.request, response=resp)
                resp.raise_for_status()
                return resp.json().get("query", {}).get("search", [])
            except httpx.HTTPStatusError as e:
                _WIKI_LAST_CALL[0] = time.time()
                print(f"[Resources] {host} محاولة {attempt+1}/4: {e.response.status_code}")
                delay = 1.0 if delay == 0 else delay * 2
        time.sleep(delay)
    return []


def _mediawiki_search(host: str, query: str, limit: int, provider: str) -> List[Dict]:
    """بحث عام في مواقع MediaWiki (ويكيبيديا/ويكي الجامعة/ويكي الكتب)"""
    cache_key = (provider, host, query, limit)
    cached = _cache_get(cache_key)
    if cached is not None:
        items = cached
    else:
        try:
            items = _cache_set(cache_key, _wiki_get(host, query, limit))
        except Exception as e:  # noqa: BLE001
            print(f"[Resources] {provider} فشل: {type(e).__name__}")
            return []

    out: List[Dict] = []
    for item in items:
        title = item.get("title") or ""
        if not title:
            continue
        out.append(
            {
                "provider": provider,
                "title": _short(title, 140),
                "url": f"https://{host}/wiki/{quote(title.replace(' ', '_'))}",
                "snippet": _short(_clean_html(item.get("snippet") or ""), 220),
                "thumbnail": None,
                "duration_seconds": None,
                "channel": host.split(".")[0].replace("ar", "ويكيبيديا عربية"),
                "lang": "ar",
            }
        )
    return out


def search_wikipedia(query: str, limit: int = 2) -> List[Dict]:
    return _mediawiki_search("ar.wikipedia.org", query, limit, "wikipedia")


def search_wikiversity(query: str, limit: int = 2) -> List[Dict]:
    return _mediawiki_search("ar.wikiversity.org", query, limit, "wikiversity")


def search_wikibooks(query: str, limit: int = 1) -> List[Dict]:
    return _mediawiki_search("ar.wikibooks.org", query, limit, "wikibooks")


def search_arxiv(query: str, limit: int = 1) -> List[Dict]:
    """أوراق أكاديمية من arXiv (إنجليزي فقط)"""
    if not _is_english(query):
        return []
    try:
        with httpx.Client(timeout=settings.resource_search_timeout, headers={"User-Agent": USER_AGENT}, follow_redirects=True) as client:
            resp = client.get(
                "https://export.arxiv.org/api/query",
                params={"search_query": f"all:{query}", "max_results": limit},
            )
            resp.raise_for_status()
            xml = resp.text
    except Exception as e:  # noqa: BLE001
        print(f"[Resources] arXiv فشل: {type(e).__name__}")
        return []

    out: List[Dict] = []
    entries = re.findall(r"<entry>(.*?)</entry>", xml, re.S)
    for entry in entries[:limit]:
        title_m = re.search(r"<title>(.*?)</title>", entry, re.S)
        id_m = re.search(r"<id>(.*?)</id>", entry, re.S)
        summary_m = re.search(r"<summary>(.*?)</summary>", entry, re.S)
        if not (title_m and id_m):
            continue
        out.append(
            {
                "provider": "arxiv",
                "title": _short(" ".join(title_m.group(1).split()), 140),
                "url": id_m.group(1).strip(),
                "snippet": _short(" ".join((summary_m.group(1) if summary_m else "").split()), 220),
                "thumbnail": None,
                "duration_seconds": None,
                "channel": "arXiv",
                "lang": "en",
            }
        )
    return out


PROVIDERS = {
    "youtube": search_youtube,
    "wikipedia": search_wikipedia,
    "wikiversity": search_wikiversity,
    "wikibooks": search_wikibooks,
    "arxiv": search_arxiv,
}



def _norm_ar(text: str) -> str:
    """تطبيع عربي للمقارنة: إزالة التشكيل وتوحيد الألف/الياء/التاء المربوطة"""
    text = re.sub(r"[\u064B-\u065F\u0670\u0640]", "", text or "")
    text = text.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا")
    text = text.replace("ى", "ي").replace("ة", "ه")
    return text.lower()


def _skeleton(word: str) -> str:
    """
    هيكل الكلمة العربي: بعد التطبيع نحذف حروف المد (ا/و/ي) والتشكيل المكرر،
    فيتساوى «قانون» و«قوانين»، و«كتلة» و«الكتلة». ضروري لأن العربية تصرفية.
    """
    w = _norm_ar(word)
    return re.sub(r"[اوي]", "", w)


# نسخة «هيكل» من الكلمات العامة للمقارنة الصحيحة
_GENERIC_SK = {_skeleton(w) for w in GENERIC_WORDS}


def _word_hit(q_skeleton: str, words: List[str]) -> bool:
    if len(q_skeleton) < 3:
        return False
    for w in words:
        if q_skeleton in w or (len(w) >= 3 and w in q_skeleton):
            return True
    return False


def _relevance(query: str, item: Dict) -> int:
    """
    عدد كلمات الاستعلام المهمة الموجودة في عنوان المصدر (بصيغة الهيكل العربي).
    تطابق العنوان أساسي: «صاروخ» لا تصلح لمحاضرة عن التسارع حتى لو ذكر وصفها التسارع.
    """
    raw_words = [
        w for w in re.findall(r"[\u0600-\u06FF]{4,}|[A-Za-z]{4,}", query or "")
        if w not in ("شرح", "الشرح", "درس", "ملخص")
    ]
    q_sk = [_skeleton(w) for w in raw_words]
    q_sk = [w for w in q_sk if len(w) >= 3 and w not in _GENERIC_SK]
    if not q_sk:
        return 99  # استعلام بلا كلمات دالة: لا نستبعد شيئاً

    title_words = [_skeleton(w) for w in re.findall(r"[\u0600-\u06FF]{2,}|[A-Za-z]{2,}", item.get("title", ""))]
    return sum(2 for sk in q_sk if _word_hit(sk, title_words))


def _filter_relevant(items: List[Dict], query: str) -> List[Dict]:
    """
    يُبقي فقط ما يشترك عنوانه فعلاً مع عنوان الموضوع.
    الأفضل «مصدران صحيحان» من «خمسة مصادر بينها ما لا علاقة له».
    """
    raw_words = [
        w for w in re.findall(r"[\u0600-\u06FF]{4,}|[A-Za-z]{4,}", query or "")
        if w not in ("شرح", "الشرح", "درس", "ملخص")
        and _skeleton(w) not in _GENERIC_SK
    ]
    needed = min(2, max(1, len(raw_words)))
    scored = [(item, _relevance(query, item)) for item in items]
    # تطابق كلمتين من العنوان المطلوب (أو كلمة واحدة إن كان الاستعلام كلمة واحدة)
    return [item for item, score in scored if score >= needed * 2]


# ============================ الواجهة الموحدة ============================
def build_queries(topic: Dict) -> Dict[str, str]:
    """
    بناء استعلامات البحث من الموضوع نفسه (بلا أي قوائم مواد مسبقة):
      • youtube: العنوان + «شرح»   (يوتيوب يفهم اللغة الطبيعية)
      • wiki:    العنوان فقط       (ويكيبيديا تفضل اسم المفهوم مجرداً)
      • en:      المصطلحات الإنجليزية (لأجل arXiv فقط)
    لا نكرر كلمة موجودة في العنوان، ولا نضيف كلمات glossary لا صلة لها.
    """
    title = (topic.get("title") or "").strip()
    words = [w for w in re.findall(r"[\u0600-\u06FF]{2,}|[A-Za-z]{2,}", title)]
    terms = [t for t in (topic.get("key_terms") or []) if t and t.strip()]
    en_terms = [t for t in (topic.get("key_terms") or []) if _is_english(t)]

    # عنوان من كلمة واحدة يحتاج دعماً بمصطلح ثانٍ
    core = title
    if len(words) < 2 and terms:
        extra = next((t for t in terms if t not in title), "")
        core = f"{title} {extra}".strip()

    is_english_title = bool(core) and not re.search(r"[\u0600-\u06FF]", core)
    return {
        "ar": (core if is_english_title else f"{core} شرح").strip() if core else "",
        "wiki": core,
        "en": " ".join(en_terms[:3]).strip(),
    }


def find_resources(topic: Dict, max_items: Optional[int] = None) -> List[Dict]:
    """
    بحث موازٍ عبر المزودين المفعّلين في الإعدادات، مع إزالة التكرار وترتيب ثابت.
    يعيد قائمة موحدة جاهزة للتخزين.
    """
    queries = build_queries(topic)
    if not queries["ar"]:
        return []

    enabled = [p.strip() for p in (settings.resource_providers or "").split(",") if p.strip()]
    enabled = [p for p in enabled if p in PROVIDERS]
    if not enabled:
        return []

    limits = {
        "youtube": settings.youtube_results_per_topic,
        "wikipedia": settings.wiki_results_per_topic,
        "wikiversity": settings.wiki_results_per_topic,
        "wikibooks": 1,
        "arxiv": 1,
    }

    collected: List[Dict] = []

    def run_batch(batch: List[str]) -> None:
        """تنفيذ مجموعة مزودين بالتوازي وجمع نتائجها"""
        with ThreadPoolExecutor(max_workers=min(4, len(batch))) as pool:
            tasks = {}
            for provider in batch:
                if provider == "arxiv":
                    query = queries["en"]
                elif provider in ("wikipedia", "wikiversity", "wikibooks"):
                    query = queries["wiki"]
                else:
                    query = queries["ar"]
                if not query:
                    continue
                tasks[pool.submit(PROVIDERS[provider], query, limits.get(provider, 2))] = (provider, query)

            for fut in as_completed(tasks):
                provider, query = tasks[fut]
                try:
                    items = fut.result() or []
                except Exception as e:  # noqa: BLE001
                    print(f"[Resources] {provider} استثناء: {type(e).__name__}")
                    items = []
                for it in items:
                    it["query_used"] = query
                    it["provider_label"] = PROVIDER_LABELS.get(it["provider"], it["provider"])
                    collected.append(it)

    # الجولة الأولى: يوتيوب + ويكيبيديا (المصدران الأساسيان)
    run_batch([p for p in enabled if p in ("youtube", "wikipedia")])

    # الجولة الثانية: موسوعات إضافية فقط إن كانت ويكيبيديا لم تُغطِّ الموضوع
    # (يقلل الطلبات على ويكيميديا بثلثها ويمنع الحجب 429)
    wiki_hits = sum(1 for it in collected if it["provider"] == "wikipedia")
    if wiki_hits < 2:
        run_batch([p for p in enabled if p in ("wikiversity", "wikibooks", "arxiv")])
    elif "arxiv" in enabled and queries["en"]:
        run_batch(["arxiv"])

    # ترتيب مزودين متبادل (youtube أولاً) + إزالة التكرار بالرابط
    order = {name: i for i, name in enumerate(["youtube", "wikipedia", "wikiversity", "wikibooks", "arxiv"])}
    collected.sort(key=lambda x: order.get(x["provider"], 99))
    seen, unique = set(), []
    for item in collected:
        if item["url"] in seen:
            continue
        seen.add(item["url"])
        unique.append(item)

    unique = _filter_relevant(unique, queries["wiki"] or queries["ar"])
    if max_items:
        unique = unique[:max_items]
    return unique


def link_topics(topics: List[Dict], delay: float = 0.3) -> Dict[int, List[Dict]]:
    """
    ربط قائمة مواضيع بمصادر. التنفيذ متوازٍ بمحدودية (3 مواضيع معاً)
    حتى لا نُثقل المواقع الخارجية ولا نبطئ الخادم.
    يعيد قاموساً: فهرس الموضوع → قائمة المصادر.
    """
    out: Dict[int, List[Dict]] = {}
    if not topics:
        return out

    def work(idx: int) -> tuple[int, List[Dict]]:
        return idx, find_resources(topics[idx])

    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = [pool.submit(work, i) for i in range(len(topics))]
        for fut in as_completed(futures):
            try:
                idx, items = fut.result()
            except Exception as e:  # noqa: BLE001
                print(f"[Resources] ربط موضوع فشل: {type(e).__name__}")
                continue
            out[idx] = items
            if delay:
                time.sleep(delay)

    # إزالة التكرار عبر المواضيع: نفس الفيديو لا يُعرض في أكثر من موضوع
    # (نُبقي الأولوية للموضوع الأسبق حتى تتنوّع مصادر الطالب)
    seen: set = set()
    for idx in sorted(out):
        unique: List[Dict] = []
        duplicates: List[Dict] = []
        for item in out[idx]:
            if item["url"] in seen:
                duplicates.append(item)
            else:
                seen.add(item["url"])
                unique.append(item)
        # إن أصبح الموضوع بلا مصادر، نُعيد له ما حُجب (أفضل من لا شيء)
        out[idx] = unique or duplicates
        seen.update(i["url"] for i in out[idx])

    return out


def check_providers() -> Dict[str, bool]:
    """فحص سريع: هل كل مزود يعيد نتائج فعلاً؟ (يُستخدم في /health)"""
    status: Dict[str, bool] = {}
    try:
        import httpx as _httpx

        resp = _httpx.get(
            "https://ar.wikipedia.org/w/api.php",
            params={"action": "query", "list": "search", "srsearch": "فيزياء", "srlimit": 1, "format": "json"},
            headers={"User-Agent": USER_AGENT},
            timeout=6.0,
        )
        status["wikipedia"] = resp.status_code == 200
    except Exception:  # noqa: BLE001
        status["wikipedia"] = False

    try:
        import yt_dlp  # noqa: F401,PLC0415

        status["youtube"] = True
    except Exception:  # noqa: BLE001
        status["youtube"] = False

    return status

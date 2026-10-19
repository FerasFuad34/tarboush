"""
فحص شامل للـ API على خادم يعمل فعلياً.
الاستخدام: python tests/e2e_check.py http://localhost:8000
يطبع مصفوفة ✅/❌ مع نتائج حقيقية.
"""
import os
import sys
import time
import json
import httpx

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"
# بعض البيئات (حاوية بلا نماذج STT) لا تستطيع تفريغ الصوت — نسمح بتخطيه بوضوح
SKIP_AUDIO = os.environ.get("SKIP_AUDIO", "0") == "1"
client = httpx.Client(base_url=BASE, timeout=600)
results = []


def record(name, ok, detail=""):
    results.append((name, ok, detail))
    print(f"{'✅' if ok else '❌'} {name} — {detail}")


def wait_done(lecture_id, timeout=600):
    t0 = time.time()
    while time.time() - t0 < timeout:
        r = client.get(f"/api/v1/lectures/{lecture_id}/progress").json()
        if r["status"] in ("done", "failed"):
            return r
        time.sleep(2)
    return {"status": "timeout", "progress": 0, "error": "انتهت المهلة"}


def upload(path, title):
    with open(path, "rb") as f:
        r = client.post("/api/v1/lectures/upload", files={"file": f}, data={"title": title})
    return r


# ---- تهيئة ملفات الاختبار من عينات المشروع (لا تعتمد على /tmp جاهز مسبقاً) ----
HERE = os.path.dirname(os.path.abspath(__file__))
SAMPLES = os.path.join(os.path.dirname(HERE), "..", "docs", "samples")
SAMPLE_TXT = os.path.join(SAMPLES, "lecture_physics_ar.txt")
SAMPLE_AUDIO = os.path.join(SAMPLES, "lecture_physics_ar_45s.mp3")
TMP_TXT = "/tmp/sample_lecture.txt"
if not os.path.exists(TMP_TXT):
    with open(SAMPLE_TXT, encoding="utf-8") as src, open(TMP_TXT, "w", encoding="utf-8") as dst:
        dst.write(src.read())
CORRUPT = "/tmp/corrupt_lecture.pdf"
if not os.path.exists(CORRUPT):
    with open(CORRUPT, "wb") as f:
        f.write(b"%PDF-1.4 not a real pdf \x00\x01\x02" * 40)


def skip(label, why):
    print(f"⏭️  {label} — تخطّي: {why}")


print(f"=== فحص طربوش على {BASE} ===\n")

# 1) صحة النظام
h = client.get("/health").json()
health_ok = h.get("status") in ("healthy", "degraded") or (
    SKIP_AUDIO and (h.get("checks", {}).get("resources", {}) or {}).get("ok")
)
record("فحص /health + مزوّدات المصادر", health_ok,
       f"الحالة: {h.get('status')} | مصادر: {(h.get('checks', {}).get('resources') or {}).get('label')}")

# 2) ملف نصي عربي كامل
r = upload(TMP_TXT, "فيزياء: قوانين نيوتن")
ok = r.status_code == 200
lecture_id = r.json().get("id") if ok else None
record("رفع ملف نصي", ok, f"HTTP {r.status_code} id={lecture_id}")

if lecture_id:
    st = wait_done(lecture_id)
    d = client.get(f"/api/v1/lectures/{lecture_id}").json()
    record("اكتمال المعالجة", st["status"] == "done", f"{st['status']} {st['progress']}%")
    record("استخراج النص", bool(d.get("transcript")), f"{d['transcript']['word_count'] if d.get('transcript') else 0} كلمة")
    record("3 مستويات تلخيص + أهم 10", len(d.get("summaries", [])) >= 4, f"{[s['level'] for s in d.get('summaries',[])]}")
    record("قاموس مصطلحات من السياق", len(d.get("glossary", [])) >= 3, f"{len(d.get('glossary',[]))} مصطلح")
    qn = len(d["quiz"]["questions"]) if d.get("quiz") else 0
    record("أسئلة MCQ", qn >= 5, f"{qn} سؤال")

    # ---- المواضيع والمصادر الخارجية (حقيقية، بلا أي بيانات وهمية) ----
    topics = d.get("topics") or []
    record("استخراج مواضيع من المحاضرة", len(topics) >= 2,
           f"{len(topics)} موضوع: {[t['title'] for t in topics]}")
    record("عناوين المواضيع غير مكررة", len({t["title"] for t in topics}) == len(topics),
           str([t["title"] for t in topics]))
    all_sources = [r for t in topics for r in t["resources"]]
    hosts_ok = all(
        any(h in r["url"] for h in ("youtube.com", "youtu.be", "wikipedia.org", "wikiversity.org", "wikibooks.org", "arxiv.org"))
        for r in all_sources
    )
    record("مصادر خارجية مرتبطة", len(all_sources) >= 3, f"{len(all_sources)} مصدر")
    record("كل الروابط من مزودين معروفين", hosts_ok, f"{len({r['provider'] for r in all_sources})} مزود")
    record("لا تكرار في المصادر", len({r["url"] for r in all_sources}) == len(all_sources),
           f"{len({r['url'] for r in all_sources})} رابط فريد / {len(all_sources)}")
    record("لكل موضوع مصدر واحد على الأقل",
           all(len(t["resources"]) > 0 for t in topics) if topics else False,
           str([len(t["resources"]) for t in topics]))

    # إعادة ربط المصادر: لا تُكرر الصفوف
    before = len(all_sources)
    rl = client.post(f"/api/v1/lectures/{lecture_id}/topics/relink")
    after_topics = (client.get(f"/api/v1/lectures/{lecture_id}").json().get("topics") or [])
    after = sum(len(t["resources"]) for t in after_topics)
    record("زر تحديث المصادر يعمل بلا تكرار", rl.status_code == 200 and after == before,
           f"قبل {before} / بعد {after}")

    # بحث حر + حالة صادقة عند غياب النتائج
    sr = client.get("/api/v1/lectures/resources/search", params={"q": "قانون نيوتن", "limit": 5})
    record("بحث حر يعيد نتائج حقيقية", sr.status_code == 200 and sr.json()["count"] > 0,
           f"{sr.json().get('count')} نتيجة")
    empty = client.get("/api/v1/lectures/resources/search", params={"q": "zzqqxx9876qwerty", "limit": 3})
    record("حالة صادقة عند عدم وجود نتائج",
           empty.status_code == 200 and empty.json()["count"] == 0 and empty.json().get("note"),
           empty.json().get("note") or "")

    # المصادر تدخل في التصدير
    md = client.get(f"/api/v1/lectures/{lecture_id}/export/markdown")
    record("المصادر داخل تصدير Markdown", "## الشرح والمصادر" in md.text and "http" in md.text,
           f"{len(md.text)} حرف")
    js = client.get(f"/api/v1/lectures/{lecture_id}/export/json")
    record("المصادر داخل تصدير JSON", "topics" in js.json() and len(js.json()["topics"]) == len(topics),
           f"{len(js.json().get('topics', []))} موضوع")

    # التحقق من الاستناد (Grounding): تغيير المحاضرة يغيّر المخرجات
    second = "/tmp/sample.docx" if os.path.exists("/tmp/sample.docx") else os.path.join(SAMPLES, "lecture_econ_ar.txt")
    r2 = upload(second, "اقتصاد: العرض والطلب")
    if r2.status_code == 200:
        st2 = wait_done(r2.json()["id"])
        d2 = client.get(f"/api/v1/lectures/{r2.json()['id']}").json()
        t1 = (d.get("transcript") or {}).get("text", "")
        t2 = (d2.get("transcript") or {}).get("text", "")
        s1 = d["summaries"][0]["content"] if d.get("summaries") else ""
        s2 = d2["summaries"][0]["content"] if d2.get("summaries") else ""
        record("اختبار الحقيقة الأرضية (تغيير المحاضرة يغيّر المخرجات)",
               st2["status"] == "done" and t1 != t2 and s1 != s2,
               "المخرجات تغيّرت مع تغيير المحاضرة")

    # التصدير
    for fmt, min_size in [("markdown", 200), ("json", 200), ("pdf", 500), ("docx", 1000), ("txt", 200)]:
        er = client.get(f"/api/v1/lectures/{lecture_id}/export/{fmt}")
        record(f"تصدير {fmt.upper()}", er.status_code == 200 and len(er.content) > min_size,
               f"HTTP {er.status_code} — {len(er.content)} بايت")

# 3) منع التكرار
r3 = upload(TMP_TXT, "نسخة مكررة")
record("منع التكرار بالـ hash", r3.json().get("deduplicated") is True, f"id={r3.json().get('id')}")

# 4) ملف تالف
r4 = upload(CORRUPT, "ملف تالف")
if r4.status_code == 200:
    st4 = wait_done(r4.json()["id"])
    err = st4.get("error") or ""
    has_arabic = any("\u0600" <= ch <= "\u06FF" for ch in err)
    record("ملف تالف → خطأ عربي دون انهيار", st4["status"] == "failed" and has_arabic, err[:90])

# 5) صيغ المستندات
for path, label in [("/tmp/sample.pptx", "PPTX عربي"), ("/tmp/sample.pdf", "PDF نصي"), ("/tmp/ocr_test2.pdf", "PDF ممسوح (OCR)")]:
    if not os.path.exists(path):
        skip(label, "الملف التجريبي غير موجود (يُنشأ في حزمة العينات)")
        continue
    rr = upload(path, label)
    if rr.status_code == 200:
        stt = wait_done(rr.json()["id"], timeout=300)
        dd = client.get(f"/api/v1/lectures/{rr.json()['id']}").json()
        words = dd["transcript"]["word_count"] if dd.get("transcript") else 0
        record(f"{label}", stt["status"] == "done" and words > 5, f"{stt['status']} — {words} كلمة")

# 6) صوت
audio_path = next(
    (p for p in ("/tmp/gtts_ar.mp3", "/tmp/sample_lecture.mp3", SAMPLE_AUDIO) if os.path.exists(p)),
    None,
)
if not audio_path:
    skip("صوت عربي → تفريغ", "لا يوجد ملف صوتي تجريبي")
elif SKIP_AUDIO:
    skip("صوت عربي → تفريغ", "SKIP_AUDIO=1 (لا نماذج STT في هذه البيئة)")
else:
    rr = upload(audio_path, "صوت عربي")
if audio_path and not SKIP_AUDIO and rr.status_code == 200:
    stt = wait_done(rr.json()["id"], timeout=600)
    dd = client.get(f"/api/v1/lectures/{rr.json()['id']}").json()
    record("صوت عربي → تفريغ", stt["status"] == "done", f"{stt['status']}")
    record("طوابع زمنية حقيقية", len(dd["transcript"]["segments"]) > 0 if dd.get("transcript") else False,
           f"{len(dd['transcript']['segments']) if dd.get('transcript') else 0} مقطع")
    record("واجهة is_media للمشغل", dd.get("is_media") is True, "المشغل سيظهر")
    mr = client.get(f"/api/v1/lectures/{dd['id']}/media", headers={"Range": "bytes=0-1023"})
    record("بث الصوت يدعم Range", mr.status_code == 206, f"HTTP {mr.status_code}")

# 7) أخطاء API واضحة
r404 = client.get("/api/v1/lectures/999999")
record("404 برسالة عربية", r404.status_code == 404, r404.json().get("detail", ""))

print("\n=== الملخص ===")
passed = sum(1 for _, ok, _ in results if ok)
print(f"نجح {passed} من {len(results)}")
for name, ok, detail in results:
    if not ok:
        print(f"  ❌ {name}: {detail}")

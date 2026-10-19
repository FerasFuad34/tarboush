"""
أداة قياس WER للعربية — تُستخدم لاختبار دقة التفريغ
الاستخدام: python tests/wer_tool.py reference.txt hypothesis.txt
"""
import re
import sys
import unicodedata


def normalize_arabic(text: str) -> str:
    """توحيد النص العربي قبل المقارنة (تشكيل، ألِفات، تاء مربوطة، ترقيم)"""
    text = unicodedata.normalize("NFKC", text)
    # إزالة التشكيل
    text = re.sub(r"[\u0617-\u061A\u064B-\u0652\u0670\u0640]", "", text)
    # توحيد الألف والياء والتاء المربوطة
    text = re.sub("[إأآا]", "ا", text)
    text = re.sub("ى", "ي", text)
    text = re.sub("ؤ", "و", text)
    text = re.sub("ئ", "ي", text)
    text = re.sub("ة", "ه", text)
    # إزالة الترقيم والرموز
    text = re.sub(r"[^\w\s]", " ", text)
    # توحيد المسافات
    return re.sub(r"\s+", " ", text).strip().lower()


def wer(reference: str, hypothesis: str) -> tuple[float, int, int]:
    """Word Error Rate = (S + D + I) / N عبر مسافة Levenshtein على الكلمات"""
    ref = normalize_arabic(reference).split()
    hyp = normalize_arabic(hypothesis).split()
    n, m = len(ref), len(hyp)
    if n == 0:
        return (1.0 if m else 0.0), 0, 0
    # برمجة ديناميكية
    prev = list(range(m + 1))
    for i in range(1, n + 1):
        cur = [i] + [0] * m
        for j in range(1, m + 1):
            cost = 0 if ref[i - 1] == hyp[j - 1] else 1
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost)
        prev = cur
    return prev[m] / n, prev[m], n


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("الاستخدام: python tests/wer_tool.py reference.txt hypothesis.txt")
        raise SystemExit(1)
    ref = open(sys.argv[1], encoding="utf-8").read()
    hyp = open(sys.argv[2], encoding="utf-8").read()
    rate, errors, total = wer(ref, hyp)
    print(f"WER = {rate*100:.2f}%  ({errors} خطأ من {total} كلمة)")

"""
أدوات نصوص عربية - تنظيف وتقطيع
"""
import re

def clean_arabic_text(text: str) -> str:
    """تنظيف النص العربي من التشكيل الزائد والمسافات"""
    text = re.sub(r'\s+', ' ', text).strip()
    return text

def split_into_sentences(text: str) -> list:
    """تقسيم النص إلى جمل"""
    sentences = re.split(r'[.!؟。\n]+', text)
    return [s.strip() for s in sentences if s.strip()]

def estimate_reading_time(text: str) -> int:
    """تقدير وقت القراءة بالدقائق"""
    words = len(text.split())
    return max(1, words // 200)

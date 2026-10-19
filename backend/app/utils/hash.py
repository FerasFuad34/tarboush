"""
حساب hash للملف لمنع المعالجة المكررة + استخراج مدة الصوت
"""
import hashlib
import os

def calculate_file_hash(file_path: str, chunk_size: int = 8192) -> str:
    """حساب SHA256 للملف"""
    sha256 = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(chunk_size):
            sha256.update(chunk)
    return sha256.hexdigest()

def get_file_size_mb(file_path: str) -> float:
    return os.path.getsize(file_path) / (1024 * 1024)

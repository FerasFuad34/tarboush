"""
بناء حزمة الإصدار (zip) لمشروع طربوش + بصمة SHA-256.

الاستخدام:
    python scripts/pack_release.py 1.1

يستبعد: node_modules, __pycache__, storage, dist, .git, ملفات قاعدة البيانات والسجلات.
"""
import hashlib
import os
import sys
import zipfile
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.dirname(ROOT)          # /home/user
VERSION = sys.argv[1] if len(sys.argv) > 1 else "1.1"
NAME = f"tarboush-M1-v{VERSION}.zip"
OUT = os.path.join(OUT_DIR, NAME)

EXCLUDE_DIRS = {
    "node_modules", "__pycache__", ".git", ".venv", "venv", "build",
    "storage", ".pytest_cache", ".mypy_cache", ".next", "coverage",
}
# نستثني dist عدا frontend/dist: الواجهة المبنية ضرورية للتشغيل بنقرة واحدة
KEEP_DIST = os.path.join("frontend", "dist")
EXCLUDE_SUFFIX = (".pyc", ".pyo", ".db", ".db-journal", ".log", ".zip", ".tsbuildinfo")


def included(path: str) -> bool:
    rel = os.path.relpath(path, ROOT)
    parts = rel.split(os.sep)
    in_keep = rel.startswith(KEEP_DIST + os.sep) or rel == KEEP_DIST
    if any(p in EXCLUDE_DIRS for p in parts[:-1]) and not in_keep:
        return False
    if parts[0] == "storage":
        return False
    if path.endswith(EXCLUDE_SUFFIX):
        return False
    return True


def main() -> None:
    files = []
    for base, dirs, names in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
        for n in names:
            full = os.path.join(base, n)
            if included(full):
                files.append(full)
    files.sort()

    if os.path.exists(OUT):
        os.remove(OUT)
    with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for full in files:
            rel = os.path.relpath(full, ROOT)
            z.write(full, os.path.join("tarboush", rel))

    digest = hashlib.sha256()
    with open(OUT, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    sha = digest.hexdigest()

    sha_file = OUT + ".sha256.txt"
    with open(sha_file, "w", encoding="utf-8") as f:
        f.write(f"{sha}  {NAME}\n")

    print(f"الحزمة : {OUT}")
    print(f"الملفات: {len(files)}")
    print(f"الحجم  : {os.path.getsize(OUT) / 1024 / 1024:.2f} MB")
    print(f"SHA-256: {sha}")
    print(f"البصمة : {sha_file}")
    print(f"الوقت  : {datetime.now():%Y-%m-%d %H:%M}")


if __name__ == "__main__":
    main()

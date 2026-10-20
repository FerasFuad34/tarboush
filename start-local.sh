#!/usr/bin/env bash
# =====================================================================
#  طربوش — تشغيل محلي (Linux / macOS)
#  يفحص المتطلبات ثم يشغّل الخادم والواجهة على جهازك.
# =====================================================================
set -e
cd "$(dirname "$0")"

echo
echo "  =========================================="
echo "    طربوش — محاضراتك تتحول إلى معرفة"
echo "  =========================================="
echo

# 1) Python
PY=$(command -v python3 || command -v python || true)
[ -z "$PY" ] && { echo "[X] Python غير مثبت"; exit 1; }
echo "[√] $($PY --version)"

# 2) ffmpeg
if command -v ffmpeg >/dev/null 2>&1; then
  echo "[√] ffmpeg موجود"
else
  echo "[!] ffmpeg غير مثبت — التفريغ الصوتي/الفيديو لن يعمل."
  echo "    Ubuntu/Debian: sudo apt install ffmpeg"
  echo "    macOS:         brew install ffmpeg"
fi

# 3) بيئة Python
[ -d .venv ] || { echo "[*] إنشاء .venv ..."; $PY -m venv .venv; }
# shellcheck disable=SC1091
source .venv/bin/activate

if [ ! -f .venv/.installed ]; then
  echo "[*] تثبيت المتطلبات (مرة واحدة) ..."
  pip install --upgrade pip >/dev/null
  pip install -r backend/requirements.txt
  touch .venv/.installed
  echo "[√] تم"
fi

# 4) الإعدادات
[ -f backend/.env ] || cp .env.example backend/.env 2>/dev/null || true

# 5) الواجهة
if [ ! -d frontend/node_modules ] && command -v npm >/dev/null 2>&1; then
  echo "[*] تثبيت حزم الواجهة ..."
  (cd frontend && npm install)
fi

# 6) التشغيل
echo
echo "  [*] الخادم: http://127.0.0.1:8000"
echo "  [*] الواجهة تُبنى وتُخدَم من نفس المنفذ"
echo
cd backend
export PYTHONPATH=.
exec ../.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000

@echo off
REM =====================================================================
REM  طربوش — تشغيل محلي بنقرة واحدة (Windows)
REM  يفحص المتطلبات، يثبّتها إن لزم، ثم يفتح المتصفح على التطبيق.
REM =====================================================================
chcp 65001 >nul
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo.
echo  ==========================================
echo    طربوش — محاضراتك تتحول إلى معرفة
echo  ==========================================
echo.

REM ---------- 1) فحص Python ----------
where py >nul 2>nul
if %errorlevel%==0 (
    set "PY=py -3"
) else (
    where python >nul 2>nul
    if !errorlevel!==0 (
        set "PY=python"
    ) else (
        echo [X] لم أجد Python. حمّله من https://www.python.org/downloads/
        echo     أثناء التثبيت علّم على "Add Python to PATH".
        pause & exit /b 1
    )
)
for /f "tokens=2" %%v in ('%PY% --version 2^>^&1') do echo [√] Python %%v

REM ---------- 2) فحص ffmpeg (بوابة كل صيغ الصوت والفيديو) ----------
where ffmpeg >nul 2>nul
if %errorlevel%==0 (
    echo [√] ffmpeg موجود
) else (
    echo [!] ffmpeg غير مثبت — سيعمل النظام مع المستندات فقط بلا تفريغ صوت/فيديو.
    echo     لتثبيته:  winget install ffmpeg
    echo     ^(أو نزّل النسخة المحمولة من ffmpeg.org وضع ffmpeg.exe في مجلد المشروع^)
)

REM ---------- 3) بيئة Python ----------
if not exist ".venv\Scripts\activate.bat" (
    echo [*] إنشاء بيئة افتراضية .venv ...
    %PY% -m venv .venv || (echo [X] فشل إنشاء البيئة & pause & exit /b 1)
)
call .venv\Scripts\activate.bat

if not exist ".venv\.installed" (
    echo [*] تثبيت المتطلبات (مرة واحدة فقط، قد تأخذ دقائق) ...
    python -m pip install --upgrade pip >nul
    python -m pip install -r backend\requirements.txt || (
        echo [X] فشل تثبيت المتطلبات & pause & exit /b 1
    )
    echo ok > .venv\.installed
    echo [√] تم تثبيت المتطلبات
)

REM ---------- 4) الإعدادات ----------
if not exist "backend\.env" (
    copy ".env.example" "backend\.env" >nul 2>nul
    echo [√] أُنشئ backend\.env من المثال
)

REM ---------- 5) الواجهة ----------
if not exist "frontend\node_modules" (
    where npm >nul 2>nul
    if !errorlevel!==0 (
        echo [*] تثبيت حزم الواجهة ...
        pushd frontend
        call npm install || echo [!] فشل تثبيت الواجهة — ستعمل الواجهة المبنية إن وُجدت
        popd
    )
)

REM ---------- 6) التشغيل ----------
echo.
echo  [*] تشغيل الخادم على http://127.0.0.1:8000
echo      (أغلق هذه النافذة لإيقاف التطبيق)
echo.

start "" http://127.0.0.1:8000
pushd backend
set PYTHONPATH=.
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
popd

pause

@echo off
REM =====================================================================
REM  طربوش — تشغيل محلي (Windows)
REM  يفحص ffmpeg وPython، يثبّت المتطلبات مرة واحدة، ثم يشغّل التطبيق.
REM =====================================================================
chcp 65001 >nul
setlocal enabledelayedexpansion
cd /d "%~dp0"
title طربوش - لا تغلق هذه النافذة

echo.
echo  ==================================================
echo    طَربوش 🎓 — محاضراتك تتحول إلى معرفة
echo  ==================================================
echo.

REM =====================================================================
REM  1) ffmpeg — الشرط الوحيد لتفريغ الصوت والفيديو
REM =====================================================================
set "FF_OK="
where ffmpeg >nul 2>nul && (
    set "FF_OK=1"
    for /f "delims=" %%v in ('ffmpeg -version 2^>^&1 ^| findstr /r "^ffmpeg version"') do (
        echo [OK] ffmpeg موجود: %%v
        goto :ff_done
    )
)

:ff_search
REM بحث في مجلد winget (شائع جداً ولا يُضاف إلى PATH أحياناً)
for /d %%D in ("%LOCALAPPDATA%\Microsoft\WinGet\Packages\Gyan.FFmpeg_*") do (
    for /d %%B in ("%%D\ffmpeg-*") do (
        if exist "%%B\bin\ffmpeg.exe" (
            set "PATH=%%B\bin;!PATH!"
            set "FF_OK=1"
            echo [OK] وجدت ffmpeg هنا وأضفته للمسار:
            echo      %%B\bin
            goto :ff_done
        )
    )
)
REM بحث في مواقع محمولة شائعة
for %%P in ("C:\ffmpeg\bin" "%~dp0ffmpeg\bin" "%~dp0bin") do (
    if exist "%%~P\ffmpeg.exe" (
        set "PATH=%%~P;!PATH!"
        set "FF_OK=1"
        echo [OK] وجدت ffmpeg في: %%~P
        goto :ff_done
    )
)

echo.
echo  [X] لم أجد ffmpeg — وبدونه لا يعمل تفريغ الصوت والفيديو إطلاقاً.
echo.
echo      ثبّته بأمر واحد في نافذة CMD جديدة:
echo.
echo          winget install Gyan.FFmpeg
echo.
echo      ثم أغلق كل نوافذ CMD وافتح هذه النافذة من جديد.
echo.
echo      (المستندات فقط تعمل بدونه: PDF / Word / PowerPoint / Excel / نص)
echo.
pause
exit /b 1

:ff_done

REM =====================================================================
REM  2) Python
REM =====================================================================
set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY (
    where python >nul 2>nul && set "PY=python"
)
if not defined PY (
    echo.
    echo  [X] لم أجد Python.
    echo      ثبّته:  winget install Python.Python.3.12
    echo      أو من https://www.python.org/downloads/  مع تعليم "Add python.exe to PATH"
    echo.
    pause
    exit /b 1
)
for /f "tokens=2" %%v in ('%PY% --version 2^>^&1') do echo [OK] Python %%v

REM =====================================================================
REM  3) البيئة الافتراضية
REM =====================================================================
if not exist ".venv\Scripts\python.exe" (
    echo [..] إنشاء بيئة افتراضية .venv ...
    %PY% -m venv .venv
    if errorlevel 1 (
        echo.
        echo  [X] فشل إنشاء البيئة الافتراضية.
        echo      جرّب:  winget install Python.Python.3.12
        echo.
        pause
        exit /b 1
    )
)
call ".venv\Scripts\activate.bat"

REM =====================================================================
REM  4) المتطلبات (مرة واحدة فقط)
REM =====================================================================
if not exist ".venv\.installed" (
    echo.
    echo [..] تثبيت المتطلبات — أول مرة فقط، قد تأخذ 5-10 دقائق.
    echo      ستُحمَّل حزم التفريغ (faster-whisper) وحزم المستندات.
    echo.
    python -m pip install --upgrade pip --quiet
    python -m pip install -r backend\requirements.txt
    if errorlevel 1 (
        echo.
        echo  [X] فشل تثبيت المتطلبات.
        echo.
        echo      الحل الأكثر شيوعاً: ثبّت أدوات بناء C++ من:
        echo         https://aka.ms/vs/17/release/vs_BuildTools.exe
        echo      ثم أعد تشغيل هذا الملف.
        echo.
        pause
        exit /b 1
    )
    echo ok > ".venv\.installed"
    echo [OK] تم تثبيت المتطلبات
)

REM =====================================================================
REM  5) الإعدادات — مع تأكيد أن التفريغ مفعّل
REM =====================================================================
if not exist "backend\.env" (
    if exist ".env.example" copy ".env.example" "backend\.env" >nul
)
powershell -NoProfile -Command ^
  "$p='backend\.env'; if(Test-Path $p){ $c=Get-Content $p -Raw; if($c -notmatch '(?m)^STT_ENABLED='){ Add-Content $p \"`nSTT_ENABLED=true\" }; if($c -notmatch '(?m)^STT_LANGUAGE='){ Add-Content $p 'STT_LANGUAGE=auto' } }" >nul 2>nul

REM =====================================================================
REM  6) التشغيل
REM =====================================================================
echo.
echo  ==================================================
echo    الواجهة:  http://127.0.0.1:8000
echo    الفحص:    http://127.0.0.1:8000/health
echo.
echo    اترك هذه النافذة مفتوحة أثناء العمل.
echo    لإيقاف التطبيق: أغلق النافذة أو اضغط Ctrl+C
echo  ==================================================
echo.

start "" "http://127.0.0.1:8000"
pushd backend
set PYTHONPATH=.
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
popd

echo.
echo [!] توقف الخادم.
pause

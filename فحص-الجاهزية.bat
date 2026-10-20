@echo off
REM =====================================================================
REM  طربوش — فحص الجاهزية (بدون تشغيل التطبيق)
REM  يشغّل هذا الملف إذا أردت معرفة سبب عدم عمل التفريغ.
REM =====================================================================
chcp 65001 >nul
setlocal enabledelayedexpansion
cd /d "%~dp0"
title طربوش - فحص الجاهزية

echo.
echo  ==================================================
echo    فحص جاهزية طربوش لتفريغ الصوت والفيديو
echo  ==================================================
echo.

set "FAIL=0"

REM ---------- ffmpeg ----------
set "FF="
where ffmpeg >nul 2>nul && set "FF=1"
if not defined FF (
    for /d %%D in ("%LOCALAPPDATA%\Microsoft\WinGet\Packages\Gyan.FFmpeg_*") do (
        for /d %%B in ("%%D\ffmpeg-*") do (
            if exist "%%B\bin\ffmpeg.exe" (
                set "PATH=%%B\bin;!PATH!"
                set "FF=1"
            )
        )
    )
)
if defined FF (
    for /f "delims=" %%v in ('ffmpeg -version 2^>^&1 ^| findstr /r "^ffmpeg version"') do echo [1/5] ffmpeg ....... [OK]  %%v
) else (
    echo [1/5] ffmpeg ....... [X]  غير موجود
    echo        ^-^> winget install Gyan.FFmpeg
    set "FAIL=1"
)

REM ---------- ffprobe ----------
where ffprobe >nul 2>nul
if errorlevel 1 (
    echo [2/5] ffprobe ...... [X]  غير موجود ^(يأتي مع ffmpeg^)
    set "FAIL=1"
) else (
    echo [2/5] ffprobe ...... [OK]
)

REM ---------- Python ----------
set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY ( where python >nul 2>nul && set "PY=python" )
if defined PY (
    for /f "tokens=2" %%v in ('%PY% --version 2^>^&1') do echo [3/5] Python ....... [OK]  %%v
) else (
    echo [3/5] Python ....... [X]  غير موجود
    echo        ^-^> winget install Python.Python.3.12
    set "FAIL=1"
)

REM ---------- البيئة والحزم ----------
if exist ".venv\Scripts\python.exe" (
    echo [4/5] البيئة ........ [OK]  .venv موجود
    ".venv\Scripts\python.exe" -c "import faster_whisper, av, numpy" >nul 2>nul
    if errorlevel 1 (
        echo        faster-whisper ... [X]  غير مثبّت
        echo        ^-^> start-windows.bat سيثبّته تلقائياً
        set "FAIL=1"
    ) else (
        echo        faster-whisper ... [OK]
    )
) else (
    echo [4/5] البيئة ........ [X]  .venv غير موجود بعد
    echo        ^-^> شغّل start-windows.bat مرة واحدة
    set "FAIL=1"
)

REM ---------- إعدادات التفريغ ----------
if exist "backend\.env" (
    findstr /b /c:"STT_ENABLED=false" "backend\.env" >nul 2>nul
    if errorlevel 1 (
        echo [5/5] إعدادات STT ... [OK]  التفريغ مفعّل
    ) else (
        echo [5/5] إعدادات STT ... [X]  STT_ENABLED=false في backend\.env
        echo        ^-^> غيّرها إلى STT_ENABLED=true
        set "FAIL=1"
    )
) else (
    echo [5/5] إعدادات STT ... [~]  backend\.env غير موجود ^(سيُنشأ تلقائياً^)
)

echo.
if "%FAIL%"=="0" (
    echo  ==================================================
    echo    كل شيء جاهز لتفريغ الصوت والفيديو
    echo    شغّل: start-windows.bat
    echo  ==================================================
) else (
    echo  ==================================================
    echo    توجد عناصر ناقصة ^(معلّمة بـ X أعلاه^)
    echo    اتبع الأسهم ^(-^-^>^) ثم أعد الفحص
    echo  ==================================================
)
echo.
pause

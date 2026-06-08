@echo off
title ClippedAI - CLI
color 0E

call venv\Scripts\activate.bat 2>nul || (
    echo  ERROR: Run setup.bat first!
    pause
    exit /b 1
)

echo.
echo  ================================================
echo   ClippedAI — CLI Mode
echo   Usage: python main.py --video "path\to\video.mp4"
echo  ================================================
echo.

set /p VIDEO_PATH="  Enter video path: "
set /p NUM_CLIPS="  Number of Shorts [8]: "
set /p UPLOAD="  Auto-upload to YouTube? (y/n) [n]: "

if "%NUM_CLIPS%"=="" set NUM_CLIPS=8

set UPLOAD_FLAG=
if /i "%UPLOAD%"=="y" set UPLOAD_FLAG=--upload

python main.py --video "%VIDEO_PATH%" --clips %NUM_CLIPS% %UPLOAD_FLAG%

pause

@echo off
title ClippedAI Setup
color 0A

echo.
echo  ============================================================
echo   ClippedAI - YouTube Shorts Auto-Generator
echo   Setup Script for Windows
echo  ============================================================
echo.

REM ── Check Python ──────────────────────────────────────────────
echo  [1/5] Checking Python...
python --version >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo   ERROR: Python not found!
    echo   Please install Python 3.9+ from https://www.python.org/downloads/
    echo   Make sure to check "Add Python to PATH" during installation
    echo.
    pause
    exit /b 1
)
python --version
echo   OK

REM ── Check FFmpeg ───────────────────────────────────────────────
echo.
echo  [2/5] Checking FFmpeg...
ffmpeg -version >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo   WARNING: FFmpeg not found!
    echo   Please install FFmpeg:
    echo     1. Download from: https://github.com/BtbN/FFmpeg-Builds/releases
    echo        (Get ffmpeg-master-latest-win64-gpl.zip)
    echo     2. Extract and copy ffmpeg.exe to C:\Windows\System32\
    echo        OR add the bin folder to your PATH environment variable
    echo.
    echo   After installing FFmpeg, run this setup script again.
    echo.
    pause
    exit /b 1
)
ffmpeg -version 2>&1 | findstr /i "ffmpeg version"
echo   OK

REM ── Create virtual environment ─────────────────────────────────
echo.
echo  [3/5] Creating virtual environment...
if not exist "venv" (
    python -m venv venv
    echo   Virtual environment created.
) else (
    echo   Virtual environment already exists.
)

REM ── Activate venv ─────────────────────────────────────────────
call venv\Scripts\activate.bat

REM ── Install dependencies ───────────────────────────────────────
echo.
echo  [4/5] Installing Python dependencies...
echo   This may take 5-10 minutes (downloading PyTorch + Whisper)...
echo.

pip install --upgrade pip -q

REM Install PyTorch first (CPU version)
echo   Installing PyTorch (CPU)...
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cpu -q

REM Install remaining requirements
echo   Installing other packages...
pip install -r requirements.txt -q

echo   Dependencies installed!

REM ── Create client_secrets placeholder ─────────────────────────
echo.
echo  [5/5] Setting up directories...
if not exist "client_secrets" mkdir client_secrets
if not exist "output" mkdir output
if not exist "uploads" mkdir uploads

echo.
echo  ============================================================
echo   SETUP COMPLETE!
echo  ============================================================
echo.
echo   To START the web UI:
echo     run_web.bat
echo.
echo   To use the CLI:
echo     venv\Scripts\python.exe main.py --video "your_video.mp4"
echo.
echo   For YouTube uploads:
echo     1. Follow instructions at: https://console.cloud.google.com/
echo     2. Place credentials.json in the client_secrets/ folder
echo     3. Click "Connect YouTube" in the web UI
echo.
pause

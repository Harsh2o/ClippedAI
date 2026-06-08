@echo off
title ClippedAI - Web UI
color 0B

echo.
echo  Starting ClippedAI Web UI...
echo  Open: http://localhost:5000
echo  Press Ctrl+C to stop
echo.

call venv\Scripts\activate.bat 2>nul || (
    echo  ERROR: Virtual environment not found. Run setup.bat first!
    pause
    exit /b 1
)

python app.py
pause

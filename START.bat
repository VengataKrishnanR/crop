@echo off
title CCRE Rules Intelligence and Onboarding Platform
echo.
echo  ==================================================
echo   CCRE Rules Intelligence and Onboarding Platform
echo  ==================================================
echo.

cd /d "%~dp0"

if not exist ".venv" (
    echo [1/4] Creating Python virtual environment...
    python -m venv .venv
    if errorlevel 1 (
        echo ERROR: Python not found. Install Python 3.11+ and try again.
        pause
        exit /b 1
    )
)

if not exist ".env" (
    echo        No .env found - using config\.env.stub (offline mode, no API key needed^)
    copy /y "config\.env.stub" ".env" >nul
)

echo [2/4] Installing dependencies and patching ADK...
call .venv\Scripts\activate.bat
pip install -r requirements.txt --quiet --disable-pip-version-check
pip install -e . --quiet --disable-pip-version-check
python patch_adk.py

if not exist ".ccre_data\ccre_v2.db" (
    echo [3/4] First start: loading reference artifacts from ..\Reference ...
    ccre bootstrap
) else (
    echo [3/4] Database already loaded - skipping bootstrap ^(delete .ccre_data\ccre_v2.db to reload^)
)

echo [4/4] Starting server...
echo.
echo  Open your browser at: http://localhost:8000
echo  API docs:             http://localhost:8000/docs
echo  First sign-in:        admin@ccre.local / ChangeMe123!  (change it, then add users in Admin)
echo  Press Ctrl+C to stop the server.
echo.

uvicorn server.app:app --host 0.0.0.0 --port 8000

pause

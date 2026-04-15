@echo off
REM ================================================
REM SimToC — Offline Mode (Windows)
REM Double-click this file to start SimToC offline
REM ================================================

echo.
echo  ==========================================
echo       SimToC -- Offline Mode (Windows)
echo  ==========================================
echo.

REM Go to script directory
cd /d "%~dp0"

REM Check Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo ERROR: Python not found.
    echo Install from https://python.org/downloads
    pause
    exit /b 1
)

REM Setup venv if needed
if not exist "backend\venv" (
    echo Creating virtual environment...
    python -m venv backend\venv
)

REM Activate venv
call backend\venv\Scripts\activate.bat

REM Install dependencies
echo Checking dependencies...
cd backend
pip install -q -r requirements.txt
cd ..

REM Update frontend API to localhost
echo Updating frontend for offline mode...
powershell -Command "(Get-Content frontend\script.js) -replace \"const API = '.*'\", \"const API = 'http://localhost:8080'\" | Set-Content frontend\script.js"

REM Kill anything on port 8080
for /f "tokens=5" %%a in ('netstat -ano ^| find ":8080" ^| find "LISTENING"') do (
    taskkill /PID %%a /F >nul 2>&1
)

REM Start backend
echo.
echo Starting backend on port 8080...
cd backend
start /b python app.py
cd ..

REM Wait for backend
timeout /t 3 /nobreak >nul

REM Open frontend
echo.
echo  ==========================================
echo   SimToC is ready!
echo   Opening browser...
echo   Press Ctrl+C in this window to stop.
echo  ==========================================
echo.

start "" "%cd%\frontend\index.html"

echo Backend is running. Press any key to stop...
pause >nul

REM Cleanup
taskkill /f /im python.exe >nul 2>&1
echo Stopped. Goodbye!
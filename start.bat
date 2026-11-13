@echo off
title LAN Chat Server Launcher
cd /d "%~dp0"

echo ===================================================
echo           Starting LAN Chat Server...
echo ===================================================

python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python is not installed or not in PATH!
    echo Please install Python 3.10+ from python.org
    pause
    exit /b
)

python -m pip install -r requirements.txt --quiet >nul 2>&1

:: The server opens the browser itself (http or https depending on cert.pem)
python server.py

pause

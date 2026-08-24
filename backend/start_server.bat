@echo off
cd /d "%~dp0"
call voice-venv\Scripts\activate.bat
start /min python -m uvicorn main:app --host 127.0.0.1 --port 8000
echo Server starting...

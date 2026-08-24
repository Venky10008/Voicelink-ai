@echo off
cd /d "%~dp0"
call voice-venv\Scripts\activate.bat
python -m uvicorn main:app --host 127.0.0.1 --port 8000 > voice_call_live.log 2> voice_call_live_err.log

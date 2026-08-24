#!/bin/bash
cd "$(dirname "$0")"
source voice-venv/Scripts/activate
python -m uvicorn main:app --host 127.0.0.1 --port 8000 > voice_call_live.log 2>&1

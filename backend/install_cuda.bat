@echo off
echo ============================================
echo Installing CUDA PyTorch + OmniVoice...
echo This will take 10-15 minutes. Do not close.
echo ============================================
cd /d C:\Users\polav\Desktop\project\backend
call voice-venv\Scripts\activate.bat
echo [%time%] Installing CUDA PyTorch...
pip install --force-reinstall --no-deps torch torchaudio --index-url https://download.pytorch.org/whl/cu128
echo [%time%] Installing OmniVoice...
pip install omnivoice
echo [%time%] Verifying GPU...
python -c "import torch; print('CUDA:', torch.cuda.is_available()); print('GPU:', torch.cuda.get_device_name(0)) if torch.cuda.is_available() else print('No GPU')"
echo [%time%] DONE! You can close this window.
pause

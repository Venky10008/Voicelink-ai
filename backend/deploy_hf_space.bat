@echo off
REM ============================================================================
REM  Deploy backend/ to a Hugging Face Space (Docker, free CPU tier).
REM
REM  Why a separate repo? A HF Space is its own git repository — it cannot
REM  point at a sub-folder of your GitHub repo. This script copies the backend
REM  into a local clone of the Space repo, then pushes it, which triggers a
REM  rebuild.
REM
REM  Usage:
REM    deploy_hf_space.bat  <hf-username> <space-name>
REM  Example:
REM    deploy_hf_space.bat  myuser voicelink-api
REM
REM  First run you will be asked for your Hugging Face token:
REM    huggingface.co/settings/tokens  -> "Write" permission
REM ============================================================================

setlocal
set HF_USER=%1
set SPACE_NAME=%2

if "%HF_USER%"=="" goto :usage
if "%SPACE_NAME%"=="" goto :usage

set SRC_DIR=%~dp0
set WORK_DIR=%TEMP%\hf-space-deploy\%SPACE_NAME%
set SPACE_URL=https://huggingface.co/spaces/%HF_USER%/%SPACE_NAME%

echo.
echo === 1/4  Preparing Space repo at %WORK_DIR%
if exist "%WORK_DIR%" (
    echo     Reusing existing clone...
) else (
    echo     Cloning %SPACE_URL%
    git clone %SPACE_URL% "%WORK_DIR%"
    if errorlevel 1 goto :clone_failed
)

echo.
echo === 2/4  Copying backend files ^(venvs, secrets and logs are skipped^)
rem Use robocopy with /XD /XF so we never push 10 GB of virtualenvs or secrets.
robocopy "%SRC_DIR%" "%WORK_DIR%" /MIR /NFL /NDL /NJH /NJS /NP ^
    /XD .venv venv voice-venv __pycache__ data debug_audio node_modules ^
    /XF *.log *.err firebase-service-account.json *-firebase-adminsdk-*.json ^
         demo.db boot_result*.txt phases.txt probe_result.txt importslow.txt

rem robocopy exit codes 0-7 are success; >=8 means a real error.
if errorlevel 8 goto :copy_failed

echo.
echo === 3/4  Committing
cd /d "%WORK_DIR%"
git add -A
git commit -m "Deploy backend from %HF_USER%/%SPACE_NAME%"
if errorlevel 1 (
    echo     Nothing to commit - already up to date.
)

echo.
echo === 4/4  Pushing ^(triggers a rebuild on Hugging Face^)
git push

echo.
echo === DONE ===
echo   Space URL : %SPACE_URL%
echo   Health    : %SPACE_URL%/health
echo.
echo   NEXT STEPS (do these in the Space UI, then it will restart):
echo     1. Settings -^> Variables and secrets
echo     2. Add as Secret : GROQ_API_KEY
echo     3. Add as Secret : DATABASE_URL        ^(postgresql+asyncpg://...^)
echo     4. Add as Secret : FIREBASE_CREDENTIALS_JSON  ^(whole JSON, one line^)
echo     5. Add as Variable: DEMO_MODE = true
echo     6. Add as Variable: WHISPER_MODEL = base
echo.
goto :eof

:usage
echo Usage: deploy_hf_space.bat ^<hf-username^> ^<space-name^>
echo    e.g. deploy_hf_space.bat myuser voicelink-api
goto :eof

:clone_failed
echo ERROR: could not clone the Space. Create it first at
echo    https://huggingface.co/new-space  (choose SDK: Docker)
exit /b 1

:copy_failed
echo ERROR: robocopy failed with a real error.
exit /b 1

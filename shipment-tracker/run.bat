@echo off
REM Windows: first run creates a virtualenv and installs dependencies, then starts the server.
cd /d "%~dp0"
if not exist .env copy .env.example .env >nul
if not exist .venv\Scripts\python.exe (
  py -3.12 -m venv .venv 2>nul || python -m venv .venv
  .venv\Scripts\python -m pip install --upgrade pip
  .venv\Scripts\python -m pip install -r requirements.txt || exit /b 1
)
.venv\Scripts\python scripts\ensure_env.py || (notepad .env & exit /b 1)
echo Starting on http://localhost:8000  (Ctrl+C to stop)
.venv\Scripts\python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1

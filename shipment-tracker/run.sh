#!/usr/bin/env bash
# Linux/macOS: first run creates a virtualenv and installs dependencies, then starts the server.
set -euo pipefail
cd "$(dirname "$0")"
[ -f .env ] || cp .env.example .env
if [ ! -x .venv/bin/python ]; then
  python3 -m venv .venv
  .venv/bin/pip install --upgrade pip
  .venv/bin/pip install -r requirements.txt
fi
.venv/bin/python scripts/ensure_env.py
echo "Starting on http://localhost:8000 (Ctrl+C to stop)"
exec .venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1

#!/usr/bin/env bash
# ResQWork one-click start (Linux; macOS users can double-click start.command).
# First run: creates backend/.venv and installs the Python packages (needs internet once).
set -e
cd "$(dirname "$0")/backend"
PY=""
for c in python3.13 python3.12 python3.11 python3.10 python3 python; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null; then PY="$c"; break; fi
done
if [ -z "$PY" ]; then
  echo "ResQWork needs Python 3.10 or newer. Install it from https://www.python.org/downloads/ and run this again."
  read -r -p "Press Enter to close." _ || true; exit 1
fi
if [ ! -f .venv/.ready ]; then
  echo "First run: setting up ResQWork (about a minute)…"
  [ -x .venv/bin/python ] || "$PY" -m venv .venv
  .venv/bin/python -m pip install --upgrade pip >/dev/null
  .venv/bin/python -m pip install -r requirements.txt
  .venv/bin/python -m pip install -r requirements-optional.txt || echo "(Optional extras skipped; ResQWork works without them.)"
  touch .venv/.ready
fi
exec .venv/bin/python run.py

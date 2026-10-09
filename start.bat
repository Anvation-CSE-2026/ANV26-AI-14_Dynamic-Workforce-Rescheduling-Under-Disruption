@echo off
REM ResQWork one-click start for Windows. Double-click this file.
REM First run: creates backend\.venv and installs the Python packages (needs internet once).
title ResQWork
cd /d "%~dp0backend"
set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY (where python >nul 2>nul && set "PY=python")
if not defined PY (
  echo ResQWork needs Python 3.10 or newer. Install it from https://www.python.org/downloads/
  echo ^(tick "Add python.exe to PATH" during installation^), then double-click start.bat again.
  pause
  exit /b 1
)
%PY% -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)"
if errorlevel 1 (
  echo ResQWork needs Python 3.10 or newer. Please install a newer Python from https://www.python.org/downloads/
  pause
  exit /b 1
)
if not exist ".venv\.ready" (
  echo First run: setting up ResQWork ^(about a minute^)...
  if not exist ".venv\Scripts\python.exe" %PY% -m venv .venv
  if errorlevel 1 ( echo Could not create the Python environment. & pause & exit /b 1 )
  ".venv\Scripts\python.exe" -m pip install --upgrade pip >nul
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt
  if errorlevel 1 ( echo Installing packages failed. Check your internet connection and try again. & rmdir /s /q .venv & pause & exit /b 1 )
  ".venv\Scripts\python.exe" -m pip install -r requirements-optional.txt || echo ^(Optional extras skipped; ResQWork works without them.^)
  type nul > ".venv\.ready"
)
".venv\Scripts\python.exe" run.py
pause
@echo off
setlocal
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" assistant.py
) else (
  python assistant.py
)
if errorlevel 1 pause

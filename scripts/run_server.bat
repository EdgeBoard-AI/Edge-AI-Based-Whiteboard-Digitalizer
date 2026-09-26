@echo off
cd /d "%~dp0..\backend"

if exist .venv\Scripts\python.exe (
  .venv\Scripts\python.exe server.py
  pause
  exit /b 0
)

if exist ..\.venv\Scripts\python.exe (
  ..\.venv\Scripts\python.exe server.py
  pause
  exit /b 0
)

echo Virtual environment not found.
echo Setup instructions:
echo   cd backend
echo   py -m venv .venv
echo   .\.venv\Scripts\Activate.ps1
echo   pip install -r requirements.txt
pause
exit /b 1

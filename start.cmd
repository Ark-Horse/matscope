@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Python environment missing. Run: uv sync --python 3.11
  pause
  exit /b 1
)
if not exist "frontend\dist\index.html" (
  echo Frontend build missing. Run: cd frontend ^&^& npm.cmd ci ^&^& npm.cmd run build
  pause
  exit /b 1
)
echo MatScope: http://127.0.0.1:8000
echo API docs: http://127.0.0.1:8000/docs
echo Press Ctrl+C to stop.
".venv\Scripts\python.exe" -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
pause

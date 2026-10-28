@echo off
REM VisionSpark one-shot starter for Windows.
REM Opens the FastAPI backend and the Vite frontend in separate windows.
setlocal
cd /d "%~dp0"

echo == VisionSpark full start ==

where uv >nul 2>nul
if errorlevel 1 (
  echo [ERROR] 'uv' not found. Install it from https://docs.astral.sh/uv/getting-started/installation/
  pause
  exit /b 1
)
where npm >nul 2>nul
if errorlevel 1 (
  echo [ERROR] 'npm' not found. Install Node.js LTS from https://nodejs.org/
  pause
  exit /b 1
)

if not exist "backend\.env" (
  echo [WARN] backend\.env is missing. The app will start, but /api/segment and
  echo        /api/ask will return 503 until MODEL_API_KEY is configured.
  echo        See MANUAL.md section 2.
)

if not exist "backend\.venv" (
  echo -^> Installing backend dependencies ^(uv sync^)...
  pushd backend
  uv sync
  if errorlevel 1 ( popd & pause & exit /b 1 )
  popd
)

if not exist "frontend\node_modules" (
  echo -^> Installing frontend dependencies ^(npm install^)...
  pushd frontend
  call npm install
  if errorlevel 1 ( popd & pause & exit /b 1 )
  popd
)

echo -^> Starting backend on http://127.0.0.1:8000 ...
start "VisionSpark backend" cmd /k "cd /d "%~dp0backend" && uv run uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload"

echo -^> Starting frontend on http://127.0.0.1:5173 ...
start "VisionSpark frontend" cmd /k "cd /d "%~dp0frontend" && npm run dev -- --port 5173"

echo -^> Waiting for frontend and opening browser...
timeout /t 8 /nobreak >nul
start "" "http://127.0.0.1:5173/"

echo.
echo VisionSpark is running:
echo   App: http://127.0.0.1:5173/
echo   API: http://127.0.0.1:8000  ^(docs at /docs^)
echo Close the two opened windows to stop.
pause

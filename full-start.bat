@echo off
REM VisionSpark one-shot starter for Windows.
REM Opens the FastAPI backend and the Vite frontend in separate windows.
REM Usage: full-start.bat [--http]
REM   The frontend listens on the LAN over HTTPS by default (self-signed
REM   certificate), so a phone on the same Wi-Fi can open the app with the
REM   camera and microphone working; accept the cert warning once in each
REM   browser (MANUAL.md section 5). --http (or VISIONSPARK_HTTP=1) serves
REM   plain HTTP instead (upload-only, no camera/mic). --lan/--https are
REM   kept for compatibility.
setlocal
cd /d "%~dp0"

set "HTTP_MODE=0"
if "%~1"=="--http" set "HTTP_MODE=1"
if "%~2"=="--http" set "HTTP_MODE=1"
if "%VISIONSPARK_HTTP%"=="1" set "HTTP_MODE=1"
if "%~1"=="--help" goto help
if "%~1"=="-h" goto help
if "%~2"=="--help" goto help
if "%~2"=="-h" goto help
if not "%~1"=="" if not "%~1"=="--http" if not "%~1"=="--lan" if not "%~1"=="--https" (
  echo [ERROR] Unknown option: %~1
  pause
  exit /b 1
)
if not "%~2"=="" if not "%~2"=="--http" if not "%~2"=="--lan" if not "%~2"=="--https" (
  echo [ERROR] Unknown option: %~2
  pause
  exit /b 1
)
if not "%~3"=="" (
  echo [ERROR] Unknown option: %~3
  pause
  exit /b 1
)
set "SCHEME=https"
if "%HTTP_MODE%"=="1" set "SCHEME=http"

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

REM Always refresh frontend deps: batch has no reliable lockfile-mtime
REM comparison, and a stale node_modules (missing the SSL plugin) would
REM crash the dev server. npm install is fast when already satisfied.
echo -^> Checking frontend dependencies ^(npm install^)...
pushd frontend
call npm install
if errorlevel 1 ( popd & pause & exit /b 1 )
popd

echo -^> Starting backend on http://localhost:8000 ...
start "VisionSpark backend" cmd /k "cd /d "%~dp0backend" && uv run uvicorn app.main:app --host localhost --port 8000 --reload"

if "%HTTP_MODE%"=="1" (
  REM VITE_HTTPS=0 disables the self-signed cert (see frontend/vite.config.js).
  REM Upload still works; the camera and microphone need HTTPS.
  echo -^> Starting frontend with plain HTTP on all interfaces ...
  start "VisionSpark frontend" cmd /k "cd /d "%~dp0frontend" && set VITE_HTTPS=0 && set VITE_BACKEND_URL=/ && npm run dev -- --host 0.0.0.0 --port 5173"
) else (
  REM HTTPS is the default (self-signed cert, see frontend/vite.config.js).
  REM VITE_BACKEND_URL=/ keeps API calls on the same https origin, proxied
  REM to the localhost backend. Accept the cert warning once per browser.
  echo -^> Starting frontend with HTTPS on all interfaces ...
  start "VisionSpark frontend" cmd /k "cd /d "%~dp0frontend" && set VITE_BACKEND_URL=/ && npm run dev -- --host 0.0.0.0 --port 5173"
)

echo -^> Waiting for frontend and opening browser...
set "TRIES=0"
:healthloop
curl -sf http://localhost:8000/health >nul 2>nul
if not errorlevel 1 goto healthok
set /a TRIES+=1
if %TRIES% GEQ 30 goto healthok
timeout /t 1 /nobreak >nul
goto healthloop
:healthok
start "" "%SCHEME%://localhost:5173/"

echo.
echo VisionSpark is running:
echo   App: %SCHEME%://localhost:5173/
echo   API: http://localhost:8000  ^(docs at /docs^)
echo   Phone ^(same Wi-Fi^): %SCHEME%://^<this-PC-IP^>:5173/  ^(find it with ipconfig, IPv4 Address^)
if "%HTTP_MODE%"=="1" (
  echo   Plain-HTTP mode is upload-only: the camera/mic need HTTPS ^(MANUAL.md section 5^).
) else (
  echo   HTTPS mode: accept the self-signed cert warning once in each browser,
  echo   then the phone camera and microphone work ^(MANUAL.md section 5^).
)
echo Close the two opened windows to stop.
pause
exit /b 0

:help
echo Usage: full-start.bat [--http]
echo   --http  Serve plain HTTP instead of HTTPS ^(upload only, no camera/mic^).
exit /b 0

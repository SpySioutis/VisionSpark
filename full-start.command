#!/bin/bash
# VisionSpark one-shot starter for macOS (double-click in Finder).
# Opens the FastAPI backend and the Vite frontend in separate Terminal windows.
# Usage: ./full-start.command [--http] (or VISIONSPARK_HTTP=1 ...)
#   The frontend listens on the LAN over HTTPS by default (self-signed
#   certificate), so a phone on the same Wi-Fi can open the app with the
#   camera and microphone working; accept the cert warning once in each
#   browser (MANUAL.md section 5). --http serves plain HTTP instead
#   (upload-only, no camera/mic). --lan/--https are kept for compatibility.
ROOT="$(cd "$(dirname "$0")" && pwd)"

HTTP_MODE="${VISIONSPARK_HTTP:-0}"
for arg in "$@"; do
  case "$arg" in
    --http) HTTP_MODE=1 ;;
    --lan|--https) ;; # kept for compatibility; LAN + HTTPS are on by default
    --help|-h)
      echo "Usage: ./full-start.command [--http]"
      echo "  --http  Serve plain HTTP instead of HTTPS (upload only, no camera/mic)."
      exit 0
      ;;
    *)
      echo "[ERROR] Unknown option: $arg"
      exit 1
      ;;
  esac
done

echo "== VisionSpark full start =="

command -v uv >/dev/null 2>&1 || {
  echo "[ERROR] 'uv' not found. Install it: https://docs.astral.sh/uv/getting-started/installation/"
  exit 1
}
command -v npm >/dev/null 2>&1 || {
  echo "[ERROR] 'npm' not found. Install Node.js LTS: https://nodejs.org/"
  exit 1
}

if [ ! -f "$ROOT/backend/.env" ]; then
  echo "[WARN] backend/.env is missing. The app will start, but /api/segment and"
  echo "       /api/ask will return 503 until MODEL_API_KEY is configured."
  echo "       See MANUAL.md section 2."
fi

if [ ! -d "$ROOT/backend/.venv" ]; then
  echo "-> Installing backend dependencies (uv sync)..."
  (cd "$ROOT/backend" && uv sync) || exit 1
fi

if [ ! -d "$ROOT/frontend/node_modules" ] || [ "$ROOT/frontend/package-lock.json" -nt "$ROOT/frontend/node_modules/.package-lock.json" ]; then
  echo "-> Installing frontend dependencies (npm install)..."
  (cd "$ROOT/frontend" && npm install) || exit 1
fi

# Escape ROOT for the AppleScript string layer; quoted form of handles the
# shell layer so ROOT may contain spaces, quotes, or backslashes.
ESCAPED_ROOT="$(printf '%s' "$ROOT" | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g')"

echo "-> Opening backend window (http://localhost:8000)..."
osascript -e "tell application \"Terminal\" to do script (\"cd \" & quoted form of \"$ESCAPED_ROOT/backend\" & \" && uv run uvicorn app.main:app --host localhost --port 8000 --reload\")"

# HTTPS is the default (self-signed cert, see frontend/vite.config.js).
# VITE_BACKEND_URL=/ makes every browser call the same origin, which Vite
# proxies to the localhost backend. VITE_HTTPS=0 serves plain HTTP instead
# (upload-only, no camera/mic).
FRONTEND_CMD="VITE_BACKEND_URL=/ npm run dev -- --host 0.0.0.0 --port 5173"
FRONTEND_SCHEME="https"
if [ "$HTTP_MODE" = "1" ]; then
  echo "-> Opening frontend window (plain HTTP, all interfaces)..."
  FRONTEND_CMD="VITE_HTTPS=0 VITE_BACKEND_URL=/ npm run dev -- --host 0.0.0.0 --port 5173"
  FRONTEND_SCHEME="http"
else
  echo "-> Opening frontend window (HTTPS, all interfaces)..."
fi
osascript -e "tell application \"Terminal\" to do script (\"cd \" & quoted form of \"$ESCAPED_ROOT/frontend\" & \" && $FRONTEND_CMD\")"

echo "-> Opening the app in your browser..."
sleep 5
open "${FRONTEND_SCHEME}://localhost:5173/" || true

echo ""
echo "VisionSpark is running:"
echo "  App: ${FRONTEND_SCHEME}://localhost:5173/"
echo "  API: http://localhost:8000  (docs at /docs)"
LAN_IP=$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || true)
if [ -n "$LAN_IP" ]; then
  echo "  Phone (same Wi-Fi): ${FRONTEND_SCHEME}://${LAN_IP}:5173/"
else
  echo "  Phone (same Wi-Fi): ${FRONTEND_SCHEME}://<this-Mac-IP>:5173/"
fi
if [ "$HTTP_MODE" = "1" ]; then
  echo "  Plain-HTTP mode is upload-only: the camera/mic need HTTPS (MANUAL.md section 5)."
else
  echo "  HTTPS mode: accept the self-signed cert warning once in each browser,"
  echo "  then the phone camera and microphone work (MANUAL.md section 5)."
fi
echo "Close the two Terminal windows to stop."

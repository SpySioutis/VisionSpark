#!/bin/bash
# VisionSpark one-shot starter for macOS (double-click in Finder).
# Opens the FastAPI backend and the Vite frontend in separate Terminal windows.
ROOT="$(cd "$(dirname "$0")" && pwd)"

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

if [ ! -d "$ROOT/frontend/node_modules" ]; then
  echo "-> Installing frontend dependencies (npm install)..."
  (cd "$ROOT/frontend" && npm install) || exit 1
fi

echo "-> Opening backend window (http://localhost:8000)..."
osascript -e "tell application \"Terminal\" to do script \"cd '$ROOT/backend' && uv run uvicorn app.main:app --host localhost --port 8000 --reload\""

echo "-> Opening frontend window (http://localhost:5173)..."
osascript -e "tell application \"Terminal\" to do script \"cd '$ROOT/frontend' && npm run dev -- --port 5173\""

echo "-> Opening the app in your browser..."
sleep 5
open "http://localhost:5173/" || true

echo ""
echo "VisionSpark is running:"
echo "  App: http://localhost:5173/"
echo "  API: http://localhost:8000  (docs at /docs)"
echo "Close the two Terminal windows to stop."

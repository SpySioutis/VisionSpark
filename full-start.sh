#!/usr/bin/env bash
# VisionSpark one-shot starter for Linux / macOS / WSL.
# Boots the FastAPI backend and the Vite frontend. Ctrl+C stops both.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_PORT=8000
FRONTEND_PORT=5173
BACKEND_LOG="/tmp/visionspark-backend.log"
FRONTEND_LOG="/tmp/visionspark-frontend.log"

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
  (cd "$ROOT/backend" && uv sync)
fi

if [ ! -d "$ROOT/frontend/node_modules" ]; then
  echo "-> Installing frontend dependencies (npm install)..."
  (cd "$ROOT/frontend" && npm install)
fi

kill_tree() {
  # Recursively kill a PID and all descendants (npm/uv spawn grandchildren
  # that would otherwise survive a plain kill).
  local pid="$1" child
  if command -v pgrep >/dev/null 2>&1; then
    for child in $(pgrep -P "$pid" 2>/dev/null || true); do
      kill_tree "$child"
    done
  fi
  kill "$pid" 2>/dev/null || true
}

cleanup() {
  echo ""
  echo "Stopping VisionSpark..."
  kill_tree "$BACKEND_PID"
  kill_tree "$FRONTEND_PID"
  wait 2>/dev/null || true
  echo "Stopped."
}
trap cleanup INT TERM

echo "-> Starting backend on http://localhost:${BACKEND_PORT} (log: ${BACKEND_LOG})"
(cd "$ROOT/backend" && uv run uvicorn app.main:app --host localhost --port "$BACKEND_PORT" --reload) >"$BACKEND_LOG" 2>&1 &
BACKEND_PID=$!

echo "-> Starting frontend on http://localhost:${FRONTEND_PORT} (log: ${FRONTEND_LOG})"
(cd "$ROOT/frontend" && npm run dev -- --port "$FRONTEND_PORT") >"$FRONTEND_LOG" 2>&1 &
FRONTEND_PID=$!

echo "-> Waiting for backend health..."
for _ in $(seq 1 30); do
  if curl -sf "http://localhost:${BACKEND_PORT}/health" >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

if curl -sf "http://localhost:${BACKEND_PORT}/health" >/dev/null 2>&1; then
  echo "   Backend is up."
else
  echo "[WARN] Backend did not answer within 30s. Check ${BACKEND_LOG}"
fi

echo "-> Waiting for frontend..."
for _ in $(seq 1 30); do
  if curl -sf "http://localhost:${FRONTEND_PORT}/" >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

APP_URL="http://localhost:${FRONTEND_PORT}/"
if command -v xdg-open >/dev/null 2>&1; then
  xdg-open "$APP_URL" >/dev/null 2>&1 || true
elif command -v open >/dev/null 2>&1; then
  open "$APP_URL" >/dev/null 2>&1 || true
else
  echo "   (no browser opener found; open ${APP_URL} manually)"
fi

echo ""
echo "VisionSpark is running:"
echo "  App: http://localhost:${FRONTEND_PORT}/"
echo "  API: http://localhost:${BACKEND_PORT}  (docs at /docs)"
echo "Press Ctrl+C to stop both."
wait

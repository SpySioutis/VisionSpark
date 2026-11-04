#!/usr/bin/env bash
# VisionSpark one-shot starter for Linux / macOS / WSL.
# Boots the FastAPI backend and the Vite frontend. Ctrl+C stops both.
#
# Usage: ./full-start.sh [--http]
#   The frontend listens on the LAN over HTTPS by default (self-signed
#   certificate), so a phone on the same Wi-Fi can open the app with the
#   camera and microphone working. Accept the certificate warning once in
#   each browser (see MANUAL.md section 5). API calls go through Vite's
#   proxy, so only the frontend port needs to be reachable.
#   --http (or VISIONSPARK_HTTP=1) serves plain HTTP instead (upload-only,
#   no camera/mic). --lan and --https are kept for compatibility and
#   behave the same as a plain start.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_PORT=8000
FRONTEND_PORT=5173

HTTP_MODE="${VISIONSPARK_HTTP:-0}"
for arg in "$@"; do
  case "$arg" in
    --http) HTTP_MODE=1 ;;
    --lan|--https) ;; # kept for compatibility; LAN + HTTPS are on by default
    -h|--help)
      echo "Usage: ./full-start.sh [--http]"
      echo "  --http  Serve plain HTTP instead of HTTPS (upload-only, no camera/mic)."
      exit 0
      ;;
    *)
      echo "[ERROR] Unknown option: $arg (see --help)"
      exit 1
      ;;
  esac
done
LOG_DIR="${TMPDIR:-/tmp}/visionspark-$(id -u)"
mkdir -p "$LOG_DIR"
BACKEND_LOG="${LOG_DIR}/visionspark-backend.log"
FRONTEND_LOG="${LOG_DIR}/visionspark-frontend.log"

echo "== VisionSpark full start =="

command -v uv >/dev/null 2>&1 || {
  echo "[ERROR] 'uv' not found. Install it: https://docs.astral.sh/uv/getting-started/installation/"
  exit 1
}
command -v npm >/dev/null 2>&1 || {
  echo "[ERROR] 'npm' not found. Install Node.js LTS: https://nodejs.org/"
  exit 1
}
command -v curl >/dev/null 2>&1 || {
  echo "[ERROR] 'curl' not found. Install it with your package manager (Linux/WSL) or the Xcode command line tools (macOS)."
  exit 1
}

if [ ! -f "$ROOT/backend/.env" ]; then
  echo "[WARN] backend/.env is missing. The app will start, but /api/segment and"
  echo "       /api/ask will return 503 until MODEL_API_KEY is configured."
  echo "       See MANUAL.md section 2."
fi

echo "-> Installing backend dependencies (uv sync)..."
(cd "$ROOT/backend" && uv sync)

if [ ! -d "$ROOT/frontend/node_modules" ] || [ "$ROOT/frontend/package-lock.json" -nt "$ROOT/frontend/node_modules/.package-lock.json" ]; then
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

port_busy() {
  # True if something answers or listens on a localhost TCP port. A plain
  # curl covers HTTP servers; lsof/ss catch non-HTTP listeners.
  local port="$1"
  if curl -s -o /dev/null --max-time 1 "http://localhost:${port}/" >/dev/null 2>&1; then
    return 0
  fi
  if command -v lsof >/dev/null 2>&1; then
    if lsof -iTCP:"${port}" -sTCP:LISTEN >/dev/null 2>&1; then
      return 0
    fi
  elif command -v ss >/dev/null 2>&1; then
    if ss -ltn 2>/dev/null | grep -q ":${port} "; then
      return 0
    fi
  fi
  return 1
}

BACKEND_PID=""
FRONTEND_PID=""

cleanup() {
  echo ""
  echo "Stopping VisionSpark..."
  if [ -n "$BACKEND_PID" ]; then
    kill_tree "$BACKEND_PID"
  fi
  if [ -n "$FRONTEND_PID" ]; then
    kill_tree "$FRONTEND_PID"
  fi
  wait 2>/dev/null || true
  echo "Stopped."
  exit 0
}
trap cleanup INT TERM

for port in "$BACKEND_PORT" "$FRONTEND_PORT"; do
  if port_busy "$port"; then
    echo "[ERROR] Port ${port} is already in use. Stop the other process first."
    echo "        See MANUAL.md section 7 (\"Port already in use\")."
    exit 1
  fi
done

echo "-> Starting backend on http://localhost:${BACKEND_PORT} (log: ${BACKEND_LOG})"
(cd "$ROOT/backend" && uv run uvicorn app.main:app --host localhost --port "$BACKEND_PORT" --reload) >"$BACKEND_LOG" 2>&1 &
BACKEND_PID=$!

if [ "$HTTP_MODE" = "1" ]; then
  # VITE_HTTPS=0 disables the self-signed cert (see frontend/vite.config.js).
  # Upload still works; the camera and microphone need HTTPS.
  echo "-> Starting frontend with plain HTTP on all interfaces (log: ${FRONTEND_LOG})"
  (cd "$ROOT/frontend" && VITE_HTTPS=0 VITE_BACKEND_URL=/ npm run dev -- --host 0.0.0.0 --port "$FRONTEND_PORT") >"$FRONTEND_LOG" 2>&1 &
else
  # HTTPS is the default (self-signed cert, see frontend/vite.config.js).
  # VITE_BACKEND_URL=/ keeps API calls on the same https origin, proxied to
  # the localhost backend. Accept the cert warning once per browser.
  echo "-> Starting frontend with HTTPS on all interfaces (log: ${FRONTEND_LOG})"
  (cd "$ROOT/frontend" && VITE_BACKEND_URL=/ npm run dev -- --host 0.0.0.0 --port "$FRONTEND_PORT") >"$FRONTEND_LOG" 2>&1 &
fi
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
FRONTEND_SCHEME="https"
CURL_K="-k" # self-signed cert
if [ "$HTTP_MODE" = "1" ]; then
  FRONTEND_SCHEME="http"
  CURL_K=""
fi
for _ in $(seq 1 30); do
  if curl -sf $CURL_K "${FRONTEND_SCHEME}://localhost:${FRONTEND_PORT}/" >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

APP_URL="${FRONTEND_SCHEME}://localhost:${FRONTEND_PORT}/"
if command -v xdg-open >/dev/null 2>&1; then
  xdg-open "$APP_URL" >/dev/null 2>&1 || true
elif command -v open >/dev/null 2>&1; then
  open "$APP_URL" >/dev/null 2>&1 || true
else
  echo "   (no browser opener found; open ${APP_URL} manually)"
fi

echo ""
echo "VisionSpark is running:"
echo "  App: ${FRONTEND_SCHEME}://localhost:${FRONTEND_PORT}/"
echo "  API: http://localhost:${BACKEND_PORT}  (docs at /docs)"
LAN_IP=""
if command -v ip >/dev/null 2>&1; then
  LAN_IP=$(ip route get 1.1.1.1 2>/dev/null | awk '/src/ {for (i=1;i<=NF;i++) if ($i=="src") {print $(i+1); exit}}')
fi
if [ -z "$LAN_IP" ] && command -v hostname >/dev/null 2>&1; then
  LAN_IP=$(hostname -I 2>/dev/null | awk '{print $1}')
fi
if [ -z "$LAN_IP" ] && command -v ipconfig >/dev/null 2>&1; then
  LAN_IP=$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || true)
fi
if [ -n "$LAN_IP" ]; then
  echo "  Phone (same Wi-Fi): ${FRONTEND_SCHEME}://${LAN_IP}:${FRONTEND_PORT}/"
else
  echo "  Phone (same Wi-Fi): ${FRONTEND_SCHEME}://<this-machine-ip>:${FRONTEND_PORT}/"
fi
if [ "$HTTP_MODE" = "1" ]; then
  echo "  Plain-HTTP mode is upload-only: the camera/mic need HTTPS (MANUAL.md section 5)."
else
  echo "  HTTPS mode: accept the self-signed cert warning once in each browser,"
  echo "  then the phone camera and microphone work (MANUAL.md section 5)."
fi
if grep -qi microsoft /proc/version 2>/dev/null; then
  echo "  [WARN] WSL detected: the phone reaches this server only with WSL"
  echo "         mirrored networking, or a port forward to Windows (MANUAL.md section 8)."
fi
echo "Press Ctrl+C to stop both."
wait

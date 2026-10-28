# VisionSpark MANUAL — How to Run the Program

Step-by-step instructions for running VisionSpark locally. For the project
overview see `README.md`; for the AI agent working agreement see `AGENTS.md`.

## 1. Prerequisites

| Tool | Needed for | Install / check |
|------|------------|-----------------|
| `uv` | backend env + deps (Python 3.12 auto-managed) | `curl -LsSf https://astral.sh/uv/install.sh \| sh`, then `uv --version` |
| Node.js + `npm` | frontend | https://nodejs.org (LTS), then `node --version && npm --version` |
| Meta Model API key | `/api/segment` + `/api/ask` | Meta Model API dashboard (starts with `LLM_`) |
| Modern browser | UI + speech playback | Chrome / Edge / Firefox |

No Docker, database, or extra services are required.

## 2. First-time setup

```bash
# from the repository root
cp backend/.env.example backend/.env
# edit backend/.env and set: MODEL_API_KEY=<your key>
```

- `backend/.env` is gitignored and stays on your machine. Never commit it.
- The key is backend-only. Never put it in `frontend/.env` or any `VITE_*`
  variable (Vite inlines those into the public client bundle).
- Optional: copy `frontend/.env.example` to `frontend/.env` to point the UI
  at a non-default backend URL (`VITE_BACKEND_URL`).

## 3. Starting everything (recommended)

Pick one script for your OS and run it from the repository root:

| OS | Script | What it does |
|----|--------|--------------|
| Linux / macOS / WSL | `./full-start.sh` | installs deps if missing, starts backend + frontend in one terminal (Ctrl+C stops both) |
| Windows | double-click `full-start.bat` | opens a backend window and a frontend window |
| macOS (double-click) | double-click `full-start.command` | opens a backend Terminal and a frontend Terminal |

The scripts install dependencies automatically on first run
(`uv sync` in `backend/`, `npm install` in `frontend/`) and warn if
`backend/.env` is missing (the app still starts, but AI endpoints return
503 until the key is configured).

Then open:

- **App:** http://127.0.0.1:5173/
- **API:** http://127.0.0.1:8000 (interactive docs at `/docs`)

## 4. Starting manually (two terminals)

```bash
# Terminal 1 — backend
cd backend && uv sync && uv run uvicorn app.main:app --host 127.0.0.1 --port 8000

# Terminal 2 — frontend
cd frontend && npm install && npm run dev -- --port 5173
```

## 5. Using the app

1. Click **Check backend health** — expect "Backend is reachable."
2. Upload a JPEG/PNG/WebP image (max 5 MiB).
3. **Segmentation:** type what SAM should look for (e.g. `dog`) → **Run
   segmentation** → numbered boxes overlay the preview plus a coordinate list.
4. **Q&A:** type a question (e.g. "What is in this image?") → **Ask** →
   Muse Spark's answer appears below.
5. **Read aloud:** click **Read answer aloud** to hear the answer; **Stop**
   cancels immediately. (Requires a browser with speech synthesis.)

## 6. Verification checklist

```bash
curl http://127.0.0.1:8000/health                       # {"status":"ok"}
curl -o /dev/null -w "%{http_code}\n" http://127.0.0.1:5173/  # 200
```

- Quality gates: `cd backend && uv run pytest -q && uv run ruff check . &&
  uv run ruff format --check .` and `cd frontend && npm run build`.

## 7. Troubleshooting

| Symptom | Cause / fix |
|---------|-------------|
| `/api/segment` or `/api/ask` → 503 "not configured" | `MODEL_API_KEY` missing: create `backend/.env` (Section 2) and restart the backend |
| Upload rejected (415) | only JPEG/PNG/WebP accepted |
| Upload rejected (413) | image exceeds 5 MiB; resize it |
| Frontend can't reach backend | backend must run on `127.0.0.1:8000`, or set `VITE_BACKEND_URL` in `frontend/.env` to match |
| Port already in use | stop the old process, or change the port (update `VITE_BACKEND_URL` + backend CORS origins accordingly) |
| `uv: command not found` | install `uv` (Section 1) and reopen the terminal |
| "Speech playback is not supported" | use Chrome/Edge/Firefox; no key or service can fix this, it is browser support |
| Upstream 502/504 from AI endpoints | Meta API error/timeout; wait and retry, check key/billing in the Meta dashboard |

## 8. Stopping

- `full-start.sh`: press Ctrl+C in its terminal.
- `full-start.bat` / `.command`: close the two opened windows.
- Manual start: Ctrl+C in each terminal.

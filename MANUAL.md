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

- **App:** http://localhost:5173/
- **API:** http://localhost:8000 (interactive docs at `/docs`)

## 4. Starting manually (two terminals)

```bash
# Terminal 1 — backend
cd backend && uv sync && uv run uvicorn app.main:app --host localhost --port 8000

# Terminal 2 — frontend
cd frontend && npm install && npm run dev -- --port 5173
```

## 5. Using the app

1. Glance at the header — the connection pill switches to "Online" by itself.
   Open **Settings** (gear button) to pick your language (English, Français,
   Español, Ελληνικά, 中文) — answers are given and read aloud in it —,
   a color theme (system, light, or dark), and your voice: automatic,
   woman's, man's, or a specific system voice (each language remembers its
   own), plus tone and speaking rate, automatic-reading and announcement
   toggles. Choices are remembered on your device. (Woman/man matching is
   a best-effort guess from system voice names — the browser exposes no
   gender info — and falls back to the default.)
2. **Step 1 · Photo:** upload a JPEG/PNG/WebP file (max 5 MiB), or press
   **Use camera**, frame the object, and press **Capture photo**. The
   camera stops automatically after capture; **Stop camera** ends it sooner.
   Press **Continue**.
3. **Step 2 · Check:** review the preview; optionally type what to look
   for (e.g. `label`) → **Run segmentation** → numbered boxes overlay
   the preview. Each result is announced aloud. Press **Continue**.
4. **Step 3 · Ask:** tap a preset question (**Read this label aloud**,
   **Does this contain allergens?**, ...) or type your own, choose
   **Full image** or — after segmentation — a **Detected region**, then
   **Ask**.
5. **Step 4 · Listen:** Muse Spark's answer appears and is read aloud
   automatically (unless toggled off in Settings); **Read answer
   aloud** repeats it and **Stop** cancels immediately. (Requires a browser
   with speech synthesis.) The sticky
   bar at the bottom always offers **Back**, the primary action, and
   repeat/stop audio.

## 6. Verification checklist

```bash
curl http://localhost:8000/health                       # {"status":"ok"}
curl -o /dev/null -w "%{http_code}\n" http://localhost:5173/  # 200
```

- Quality gates: `cd backend && uv run pytest -q && uv run ruff check . &&
  uv run ruff format --check .` and `cd frontend && npm run verify`.

## 7. Troubleshooting

| Symptom | Cause / fix |
|---------|-------------|
| `/api/segment` or `/api/ask` → 503 "not configured" | `MODEL_API_KEY` missing: create `backend/.env` (Section 2) and restart the backend |
| Upload rejected (415) | only JPEG/PNG/WebP accepted |
| Upload rejected (413) | image exceeds 5 MiB; resize it |
| Frontend can't reach backend | backend must run on `localhost:8000`, or set `VITE_BACKEND_URL` in `frontend/.env` to match |
| Port already in use | stop the old process, or change the port (update `VITE_BACKEND_URL` + `CORS_ORIGINS` accordingly) |
| `uv: command not found` | install `uv` (Section 1) and reopen the terminal |
| "Speech playback is not supported" | use Chrome/Edge/Firefox; no key or service can fix this, it is browser support |
| "Camera is not supported" | use Chrome/Edge/Firefox/Safari; camera needs a secure context — `localhost`/`127.0.0.1` work, plain-`http` LAN addresses do not |
| "Camera permission was denied" | allow camera access in the browser site settings, then press **Use camera** again |
| "Camera is already in use" | close the other app/tab using the camera and retry |
| Upstream 502/504 from AI endpoints | Meta API error/timeout; wait and retry, check key/billing in the Meta dashboard |
| Upstream 503 "misconfigured" from AI endpoints | Meta API rejected the key (401/403 upstream): check `MODEL_API_KEY` in `backend/.env` |
| Upstream 503 "busy" from AI endpoints | Meta API rate limit (429 upstream): wait a moment and retry |

## 8. Stopping

- `full-start.sh`: press Ctrl+C in its terminal.
- `full-start.bat` / `.command`: close the two opened windows.
- Manual start: Ctrl+C in each terminal.

## 9. Known limitations

- Model answers are AI-generated and may be wrong: for allergens, dates,
  doses, or safety, always double-check the actual label.
- Segmentation finds boxes only; region Q&A sends a rectangular crop of
  the chosen box (masks are not decoded or used), otherwise the full image.
- Uploads are limited to JPEG/PNG/WebP at 5 MiB; questions to 500
  characters; the backend waits at most 60 s per AI request.
- Camera and speech need a supporting browser; the camera needs a secure
  context (`localhost`/`127.0.0.1` or HTTPS).
- The app needs internet access to reach the Meta Model API; there is no
  offline mode.

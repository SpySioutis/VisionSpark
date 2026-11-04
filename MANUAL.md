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
- Optional: copy `frontend/.env.example` to `frontend/.env` to override
  the backend URL (`VITE_BACKEND_URL`, `/` = same origin).
- Optional backend settings in `backend/.env`: `FRONTEND_DIST` (serve the
  built frontend from the API, Section 5) and `RATE_LIMIT_PER_MINUTE`
  (per-IP limit for `POST /api/*`, 0 = off, suggest 30 for public hosting).

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

- **App:** https://localhost:5173/ (accept the self-signed certificate
  warning once in each browser)
- **API:** http://localhost:8000 (interactive docs at `/docs`)

Phone on the same Wi-Fi: open the printed `https://<your-lan-ip>:5173/`
link on the phone — no extra flags needed. The frontend listens on all
interfaces over HTTPS (self-signed certificate), so the camera and
microphone work; accept the certificate warning once in the phone
browser (Advanced → Proceed in Chrome/Edge, Show Details → visit this
website in Safari). API calls go through Vite's proxy to the backend,
so only port 5173 must be reachable (allow it in the OS firewall).

## 4. Starting manually (two terminals)

```bash
# Terminal 1 — backend
cd backend && uv sync && uv run uvicorn app.main:app --host localhost --port 8000

# Terminal 2 — frontend
cd frontend && npm install && npm run dev -- --port 5173
```

Phone on the same Wi-Fi: nothing extra to run — the frontend above
already listens on all interfaces over HTTPS. Open
`https://<laptop-ip>:5173/` on the phone and accept the self-signed
certificate warning once; the camera and microphone then work, and API
calls go through Vite's proxy to the localhost backend. (`VITE_HTTPS=0`
serves plain HTTP instead: upload-only, no camera/mic.)

## 5. Phone access (LAN camera, or tunnel/container for real HTTPS)

Start the app and open the printed `https://<laptop-ip>:5173/` link on
the phone (same Wi-Fi) — no extra flags. The browser warns about the
self-signed certificate; this is expected on a private network: choose
Advanced → Proceed (Chrome/Edge) or Show Details → visit this website
(Safari), once per browser. The camera and voice input then work; API
calls stay on the same origin and are proxied to the backend.

If you only need upload without camera or microphone, plain HTTP also
works: start with `--http` (`./full-start.sh --http`, `full-start.bat
--http`, or `VISIONSPARK_HTTP=1` with any script) and open the
`http://<laptop-ip>:5173/` link.

For recordings, demos for others, or any use outside your own LAN, use
a real HTTPS URL instead. Two paths:

**A. Served build with a tunnel (testing and recordings):**

```bash
# from the repository root
cd frontend && npm run build
cd backend && FRONTEND_DIST=../frontend/dist uv run uvicorn app.main:app --port 8000
# in another terminal: an HTTPS tunnel to port 8000, for example
cloudflared tunnel --url http://localhost:8000
```

**B. Container on a host:**

```bash
docker build -t visionspark .
docker run --rm -e MODEL_API_KEY -p 8000:8000 visionspark
# then point a tunnel or your HTTPS reverse proxy at port 8000
```

Open the `https://...` URL on the phone. `MODEL_API_KEY` always comes
from the host environment; the image never contains a key.

Notes for hosting:

- Behind a reverse proxy, run uvicorn with `--proxy-headers` and
  `--forwarded-allow-ips <proxy IPs>`, so the per-IP rate limit sees the
  real client. Trusting `"*"` lets a directly reachable client spoof its
  IP via `X-Forwarded-For`.
- For public hosting, set `RATE_LIMIT_PER_MINUTE=30` (0 = off).
- Live SAM guidance is off by default; enable it with
  `VITE_LIVE_GUIDANCE=true`. It sends one frame every 1.5 s (about $0.0025
  each), so with the rate limit on it needs `RATE_LIMIT_PER_MINUTE` of at
  least 60.

## 6. Using the app

1. Glance at the header — the connection pill switches to "Online" by itself.
   Open **Settings** (gear button) to pick your language (English, Français,
   Español, Ελληνικά, 中文) — answers are given and read aloud in it —,
   a color theme (system, light, or dark), and your voice: automatic,
   woman's, man's, or a specific system voice (each language remembers its
   own), plus tone and speaking rate, automatic-reading and announcement
   toggles. Choices are remembered on your device. (Woman/man matching is
   a best-effort guess from system voice names — the browser exposes no
   gender info — and falls back to the default.)
2. Pick a mode below the intro (**Quick** is the default; the choice is
   remembered).
3. **Quick mode:** ask first, then point. **Ask:** hold or tap **Ask by
   voice** and speak (English, French, Spanish, or Chinese — in Greek use
   your keyboard's dictation key), tap a preset, or type your question.
   **Point:** the camera opens with spoken framing cues; hold still and
   the photo is taken automatically, or press **Take photo** (uploading a
   file works too). **Answer:** the answer is read aloud first, then the
   exact words from the label, then at most one tip; the zoom view shows
   the crop. Then **Ask another question** (same photo), **Retake photo**
   (same question), or **New product**.
4. **Step-by-step mode:** **Step 1 · Photo:** upload a JPEG/PNG/WebP file
   (max 5 MiB), or press **Use camera**, frame the object, and press
   **Capture photo**. **Step 2 · Check:** review the preview; optionally
   type what to look for (e.g. `label`) → **Run segmentation** → numbered
   boxes overlay the preview. **Step 3 · Ask:** tap a preset or type your
   own, choose **Full image** or a **Detected region**, then **Ask**.
   **Step 4 · Listen:** the answer appears and is read aloud; **Ask
   another question** reuses the photo, or start over with a new one.

## 7. Verification checklist

```bash
curl http://localhost:8000/health                        # {"status":"ok"}
curl -sk -o /dev/null -w "%{http_code}\n" https://localhost:5173/  # 200 (-k: self-signed cert)
```

- Quality gates: `cd backend && uv run pytest -q && uv run ruff check . &&
  uv run ruff format --check .` and `cd frontend && npm run verify`.

## 8. Troubleshooting

| Symptom | Cause / fix |
|---------|-------------|
| `/api/segment` or `/api/ask` → 503 "not configured" | `MODEL_API_KEY` missing: create `backend/.env` (Section 2) and restart the backend |
| Upload rejected (415) | only JPEG/PNG/WebP accepted |
| Upload rejected (413) | image exceeds 5 MiB; resize it |
| Frontend can't reach backend / CORS error | backend must run on `localhost:8000`; if you have `frontend/.env`, set `VITE_BACKEND_URL=/` (same origin) or delete the file |
| Phone can't reach `https://<lan-ip>:5173` | same Wi-Fi for both; type `https://` (plain `http://` fails against the HTTPS server); allow port 5173 in the OS firewall; in WSL use mirrored networking or forward the port to Windows |
| ERR_SSL_PROTOCOL_ERROR, cannot proceed | scheme mismatch: an `https://` URL against a plain-HTTP server or vice versa. Start normally (HTTPS is the default) and open the printed `https://` link; stop any stale server first so port 5173 is free |
| Certificate warning ("not private") | expected for the self-signed cert: Advanced → Proceed (Chrome/Edge) or Show Details → visit this website (Safari), once per browser |
| Port already in use | stop the old process, or change the port (update `VITE_BACKEND_URL` + `CORS_ORIGINS` accordingly) |
| `uv: command not found` | install `uv` (Section 1) and reopen the terminal |
| "Speech playback is not supported" | use Chrome/Edge/Firefox; no key or service can fix this, it is browser support |
| "Camera is not supported" | use Chrome/Edge/Firefox/Safari; camera needs a secure context — open the `https://` link (Section 5), not `http://` |
| "Camera permission was denied" | allow camera access in the browser site settings, then press **Use camera** again |
| "Camera is already in use" | close the other app/tab using the camera and retry |
| Upstream 502/504 from AI endpoints | Meta API error/timeout; wait and retry, check key/billing in the Meta dashboard |
| Upstream 503 "misconfigured" from AI endpoints | Meta API rejected the key (401/403 upstream): check `MODEL_API_KEY` in `backend/.env` |
| Upstream 503 "busy" from AI endpoints | Meta API rate limit (429 upstream): wait a moment and retry |
| "Microphone permission was denied" | allow microphone access in the browser site settings, then try again |
| "The AI service is busy" (429) | the backend per-IP rate limit tripped: wait a minute and retry |
| No mic button | Greek has no voice input (use keyboard dictation); other languages need a secure context (open the `https://` link, Section 5) plus MediaRecorder support |

## 9. Stopping

- `full-start.sh`: press Ctrl+C in its terminal.
- `full-start.bat` / `.command`: close the two opened windows.
- Manual start: Ctrl+C in each terminal.

## 10. Known limitations

- Model answers are AI-generated and may be wrong: for allergens, dates,
  or safety information, always double-check the actual label.
- Segmentation finds boxes only; region Q&A sends a rectangular crop of
  the chosen box (masks are not decoded or used), otherwise the full image.
- Uploads are limited to JPEG/PNG/WebP at 5 MiB; questions to 500
  characters; the backend waits at most 60 s per AI request.
- Camera and speech need a supporting browser; the camera needs a secure
  context (`localhost`/`127.0.0.1` or HTTPS).
- Voice questions are at most 15 seconds, in English, French, Spanish, or
  Chinese (Greek is not supported by the transcription model).
- Auto-capture needs enough light and a steady hand; the Take photo button
  always works.
- Live SAM guidance costs about $0.0025 per frame and stays off unless
  `VITE_LIVE_GUIDANCE=true`.
- The app needs internet access to reach the Meta Model API; there is no
  offline mode.

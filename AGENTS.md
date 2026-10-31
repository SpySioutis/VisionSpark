# AGENTS.md — AI Agent Working Agreement for VisionSparkDemo

Instructions for AI coding agents working in this repository. Humans: see
`README.md` (overview) and `MANUAL.md` (how to run the program).

## 1. Project snapshot

- Monorepo: `frontend/` (Vue 3 + Vite, managed with **npm**) and `backend/`
  (FastAPI on Python 3.12, managed with **uv**).
- Features: `GET /health`, `POST /api/segment` (SAM 3.1 bounding boxes),
  `POST /api/ask` (Muse Spark 1.3 Q&A over the full image or a SAM-box
  crop), frontend SVG box overlay, camera capture, 4-step audio-first
  wizard (Photo → Check → Ask → Listen), header settings dialog (language,
  theme, Web Speech API voice preferences: per-language voice, tone,
  rate, auto-read toggles).
- Meta Model API: `https://api.meta.ai/v1/responses`, models `sam-3.1` and
  `muse-spark-1.3`, Bearer auth with `MODEL_API_KEY`.
- Ports: backend `localhost:8000`, frontend `localhost:5173`.
  Frontend talks to the backend via `VITE_BACKEND_URL`
  (default `http://localhost:8000`).

## 2. Backend rules (`backend/` is the working directory)

- Python is pinned to 3.12 via `backend/.python-version`. Do not touch the
  system Python.
- **uv only**: `uv add ...` / `uv add --dev ...`, `uv sync`, `uv run ...`.
  Never `pip`, `python -m venv`, or `requirements.txt`.
- Never create, read, print, or commit `backend/.env` (gitignored). The key
  lives in the `MODEL_API_KEY` env var; `backend/.env.example` stays
  placeholder-only.
- Never log, return, or echo the API key. Upstream failures must map to
  sanitized `MetaUpstreamError` messages (see `app/meta_api.py`).
- Reuse existing conventions: shared `_post_image_text()` envelope
  (`input_text` + `input_image` Base64 data URL), shared
  `_read_validated_image()` (JPEG/PNG/WebP, 5 MiB), response models shaped
  `{model, status, ...}`.
- Tests must **mock the upstream** (`monkeypatch` on
  `app.main.segment_image` / `app.main.ask_about_image`). No real API calls
  from tests, ever.

## 3. Frontend rules (`frontend/` is the working directory)

- **npm only**: `npm install`, `npm run dev -- --port 5173`, `npm run build`.
- Never put secrets in `VITE_*` variables (Vite inlines them into the client
  bundle). The frontend only calls our backend, never `api.meta.ai`.
- Preserve accessibility: native inputs with labels, keyboard support, the
  SVG overlay's `role="img"`/`aria-label`/`<title>` pattern, and live regions
  for status changes.
- Overlay rule: SVG `viewBox` must equal the image's natural pixel size so
  box coordinates map 1:1 at any responsive scale.

## 4. Verification (run before reporting done)

```bash
cd backend && uv run pytest -q && uv run ruff check . && uv run ruff format --check .
cd frontend && npm run verify
```

- Fix failures before reporting. Never claim a live HTTP check passed unless
  you actually ran it and observed the result.
- Live smoke tests must only hit local validation paths (`/health`, missing
  key, bad uploads). If the environment holds a real key and a request
  reaches the real upstream by accident, report it honestly.

## 5. Safety and scope

- Do not commit, push, or rewrite Git history unless explicitly asked.
- Do not refactor unrelated code. Keep changes minimal and focused.
- Do not add dependencies, endpoints, or features beyond the requested step.
- Do not read `.env` files, print secrets, or modify OpenCode/agent
  configuration.

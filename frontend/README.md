# VisionSpark frontend

Vue 3 + Vite audio-first web UI for VisionSpark, an accessible image
assistant for blind and low-vision users (photo capture/upload, SAM 3.1
region finding with an SVG overlay, visual Q&A with spoken answers).

## Commands

```bash
npm install
npm run dev -- --port 5173
npm run build
npm run check-locales
```

## Configuration

- `VITE_BACKEND_URL` (default `http://localhost:8000`): where the FastAPI
  backend runs. Never put secrets in `VITE_*` variables — Vite inlines
  them into the client bundle.

See [../MANUAL.md](../MANUAL.md) for setup, usage, and troubleshooting.

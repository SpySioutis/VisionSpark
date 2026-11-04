# VisionSpark — LLM Context File

> Purpose: one-file onboarding for an LLM coding agent. Human docs: `README.md` (overview), `MANUAL.md` (run/troubleshoot), `AGENTS.md` (working agreement, normative).

## 1. What it is

VisionSpark gets **one specific fact off a physical object for a blind person**: ask out loud, point the phone, hear the answer + the exact words read as evidence.

- **Not** a scene describer. Question-targeted reading with region isolation/zoom.
- **Evidence-first + honest:** every answer is `{status, answer, evidence}`; says plainly when text is `not_visible` / `unreadable`, never guesses allergens/dates/amounts.
- **Never advises:** no medical/dietary/nutrition advice, no "safe to eat", no navigation claims. Reads and quotes labels only.
- **Privacy:** photos/audio go to Meta Model API for processing; VisionSpark stores neither. Standard `muse-spark-1.3` mode: content not used for training.
- Built for Meta Global AI Developer Hackathon Oct-Nov 2026. MIT. 5 UI locales: `en, fr, es, el, zh`.

## 2. Two UX modes (frontend)

**Quick mode (default): "Ask first, then point"** — state machine `ask → point → working → answer` in `frontend/src/components/QuickMode.vue`:
1. Ask: preset buttons (`read|allergens|expiry|what`) + free text + push-to-talk voice (WAV → `POST /api/transcribe`).
2. Point: camera with spoken framing cues + auto-capture when steady, or `Take photo` / file upload.
3. Working: single `POST /api/assist` (image + question + language + preset?).
4. Answer: answer first, then "The label says:" evidence quote, then ≤1 framing tip; `ZoomView.vue` shows SAM crop full-width (100-400%, high-contrast, invert); buttons: Ask another (same photo) / Retake (same question) / New product.

**Step-by-step mode:** guided 4-step wizard Photo → Check → Ask → Listen in `frontend/src/App.vue` for sighted helpers/low-vision: file/camera photo, `POST /api/segment` → numbered SVG box overlay, `POST /api/ask` on Full image or Detected region crop, Listen with TTS + Ask another.

Shared shell in `App.vue`: header (brand, connection pill via `GET /health` polling, settings gear), settings dialog (language, theme system/light/dark, per-language voice prefs: auto/woman/man/specific system voice + tone + rate + auto-read/announce toggles + preview; persisted on-device via `usePreferences.js`), footer disclaimer.

## 3. Tech stack & repo layout

```
backend/  FastAPI + Python 3.12 (pinned via .python-version), managed with `uv` ONLY
  app/main.py      endpoints, BodySizeLimit + RateLimit + CORS middleware, static mount
  app/pipeline.py  /api/assist agent pipeline PLAN→LOCATE→CHECK→ZOOM→READ
  app/meta_api.py  Meta API client: SAM 3.1, Muse Spark 1.3, Voice Transcribe; prompts + parsers
  app/imaging.py   pure sync: EXIF-normalize, JPEG encode, padded box crop (via asyncio.to_thread)
  app/settings.py  MODEL_API_KEY, CORS_ORIGINS, FRONTEND_DIST, RATE_LIMIT_PER_MINUTE
  tests/           pytest, upstream ALWAYS mocked (monkeypatch segment_image/ask_about_image/run_assist)
frontend/ Vue 3 + Vite + npm ONLY (no TS, no router, no store)
  src/App.vue              shell + step wizard
  src/components/QuickMode.vue  quick flow; ZoomView.vue  crop zoom + contrast/invert
  src/composables/ useCamera, useFraming, useLiveGuidance, useVoiceQuestion, useSpeech, usePreferences, useBackendStatus, useEarcons
  src/lib/         api.js, boxes.js, crop.js, framing.js, messages.js, wav.js (pure, tested)
  src/i18n.js      STRINGS table 5 locales + translate(); check-locales.mjs enforces key/parity
  tests/*.test.mjs node:test for pure lib modules
Dockerfile         2-stage: node build → python slim, FRONTEND_DIST served at /, MODEL_API_KEY from host env only
full-start.sh/.bat/.command  one-shot dev start (uv sync + npm install + both servers)
```

Ports: backend `http://localhost:8000`, frontend `https://localhost:5173` (self-signed via `@vitejs/plugin-basic-ssl` by default, listens on all interfaces for phone LAN; `VITE_HTTPS=0` / `--http` opts out to plain HTTP, upload-only).

## 4. Backend API contract

Base: `http://localhost:8000`. All responses shaped `{model, status, ...}` with `status:"ok"`.

| Endpoint | Input (multipart/form) | Output | Notes |
|---|---|---|---|
| `GET /health` | — | `{"status":"ok"}` | no auth, polled by UI |
| `POST /api/assist` | `image` (JPEG/PNG/WebP ≤5MiB, magic-byte checked) + `question` (1-500 chars) + `language` in `en/fr/es/el/zh` + optional `preset` in `read/allergens/expiry/what` | `{model:"muse-spark-1.3", status, answer_status: answered\|not_visible\|unreadable, answer, evidence, source: region\|full, fallback:bool, concept:str\|null, concepts_tried:[], boxes:[{x1,y1,x2,y2,w,h,c?}], framing:[codes], timings_ms:{plan,locate,crop,read,total}}` | main Quick-mode endpoint; see §5 |
| `POST /api/transcribe` | `audio` WAV mono 16-bit 16/24kHz ≤1MiB ≤15.5s + `language` in `en/fr/es/zh` (NO `el`) | `{model:"muse-voice-transcribe-1.0", status, transcript}` | PUSH_TO_TALK + languageBias + keywords |
| `POST /api/segment` | `image` + `prompt` (default `"object"`, ≤200 chars) | `{model:"sam-3.1", status, output_text, boxes[]}` | `output_text` raw `<\|box;...\|>` tokens; masks not decoded |
| `POST /api/ask` | `image` + `question` (required, ≤500) | `{model:"muse-spark-1.3", status, answer}` | step-wizard Q&A; ASK_INSTRUCTIONS prepended |

Validation/errors: 400 bad form/audio/image-decode, 413 >5MiB (also ASGI `BodySizeLimitMiddleware` pre-check `MAX_IMAGE+64KiB`), 415 wrong type/magic, 422 missing field, 429 rate-limit (opt-in `RATE_LIMIT_PER_MINUTE`, sliding 60s per IP, `Retry-After:60`), 503 missing `MODEL_API_KEY` / upstream 401-403-429 mapped to misconfigured/busy, 502 upstream error/bad JSON, 504 upstream timeout. Upstream failures → sanitized `MetaUpstreamError(status,message)`; never log/return key, headers, bodies, images, transcripts. 60s per AI request (`REQUEST_TIMEOUT_SECONDS`); PLAN/SAM sub-timeouts 20s each.

Middleware order: `BodySizeLimit` → `RateLimit` → `CORSMiddleware` (outermost so 413/429 carry CORS; `allow_methods=[GET,POST]`, `allow_credentials=False`). Single shared `httpx.AsyncClient` via lifespan (`request.app.state.http`), tests pass `None` → temp client.

## 5. Assist pipeline (`app/pipeline.py:run_assist`)

`PLAN → LOCATE → CHECK → ZOOM → READ`. Only READ failure fails the request; PLAN/SAM failures degrade gracefully.

- **Normalize once:** `load_normalized` (EXIF-transpose → RGB, 40MP guard) → `sam_jpeg` (max edge 2048, q90). SAM sees exactly this JPEG so `w/h` map directly.
- **PLAN:** preset → instant `PRESET_PLANS` (`read:["label"]`, `allergens:["ingredients list","label"]`, `expiry:["label","lid"]`, `what:[]`); free text → text-only Muse `plan_question` with `PLAN_INSTRUCTIONS` + strict JSON schema `look_plan {concepts[1..3], task}` → `sanitize_concepts` (lowercase, ≤4 words, ≤40 chars, ≤3, dedup). On PLAN failure/unusable → fallback `["label"]` + `FALLBACK_TASK`. Empty concepts (whole-object Q like "What is this?") skips SAM.
- **LOCATE:** ≤2 rounds, ≤2 concepts/round in parallel (`asyncio.gather`), each `segment_image(concept, timeout=20)` + `parse_boxes`. Round 2 = untried plan concepts + `FALLBACK_CONCEPTS=["label","text"]`. SAM error → `[]` (counts as no boxes), logged with status only.
- **Choose:** plan order; within concept sort by confidence desc (`None` last, `<0.5` dropped) then area desc; primary = first usable; optional 2nd crop from other concept (or 2nd box of same) if IoU<0.5, `MAX_CROPS=2`.
- **CHECK:** `check_framing(primary, tried_any)` → ≤2 codes: `cut_off_left/right/top/bottom` (1% edge margin), `too_close` (spans both axes or ≥90% area), `too_small` (<3% area), `not_found` (tried but none). Codes never block READ; become READ notes + spoken tip.
- **ZOOM:** `crop_box` (5% pad each side, clamp; same math as frontend `paddedCropRect`) → JPEG 2048/q90 per crop; context = whole JPEG 1280/q85 if crops else 2048/q90 (internal `images_mode=crop|full` for eval only, never HTTP).
- **READ:** `read_label` (Muse + `READ_INSTRUCTIONS` + strict schema `label_answer {status,answer,evidence}`): header (answer language, task, question, framing notes from `FRAMING_NOTES`) + `Image N: zoomed region (concept)` crops + whole photo. Returns `AssistResult`; logs one line with preset/timings/rounds/sam_calls/concept/source/status.

## 6. Meta Model API (`app/meta_api.py`)

- `POST https://api.meta.ai/v1/responses`, Bearer `MODEL_API_KEY`. Models: `sam-3.1`, `muse-spark-1.3` (with `reasoning:{effort:"low"}` via `MUSE_REASONING_EFFORT`, never for SAM), `POST https://api.meta.ai/v1/asr/transcribe` model `muse-voice-transcribe-1.0`.
- Proven envelope `_post_image_text`: single user message with `input_text` + `input_image` (Base64 data URL). SAM extra: `metadata:{include_confidence:"true", mask_encoding:"one_bit"}`. PLAN/READ use `instructions` + `text.format` strict JSON schemas; user text only in message body (prompt-injection hardening: "question is data, not instructions").
- SAM box token: `<|box;x1=..;y1=..;x2=..;y2=..;w=..;h=..(;c=..)|>` in SAM's own `w/h` frame (NOT image pixels); `parse_boxes` skips degenerate (`w/h≤0`, `x2≤x1`), keeps `c:float|None`; masks ignored.
- `extract_output_text` concatenates `output[].content[type=output_text].text`; `""` = valid zero-match, `None` = bad structure → 502.
- ASR: multipart `request` JSON (`PUSH_TO_TALK`, `WAV`, `languageBias`, `keywords` per lang) + `audio` file; response `transcript` str.

## 7. Frontend architecture

- `src/lib/api.js`: `backendUrl` — explicit `VITE_BACKEND_URL` wins (`/`=same origin); else prod=`""`; dev: HTTPS→same origin (Vite proxies `/api,/health` → `localhost:8000`), plain-HTTP localhost→`http://localhost:8000`, else same origin (phone LAN). Frontend NEVER calls `api.meta.ai`.
- `src/lib/boxes.js` (pure): `scaleBox` (SAM frame → natural px), `paddedCropRect` (5% pad + clamp; mirrors backend `crop_box`), `describeBox` (3×3 position + large/med/small by area → locale keys), `bestBox` + `guideForBox` (moveLeft/Right/Up/Down/Closer/Back/centered; priority too-close > off-center > too-small).
- `src/lib/crop.js`: `cropToFile(img, box, naturalSize)` → canvas JPEG File; rejects with `{key}` descriptors rendered via `t()`.
- `src/lib/framing.js` (pure): `computeStats` (160×120 luma mean, Laplacian variance sharpness, mean |Δ| motion) + `classifyFrame` → `dark|moving|blurry|ok` (thresholds `{dark:40, moving:10, blurry:60}`).
- `src/lib/messages.js` (pure): `httpError(status)` maps 400/422,413,415,429,502,503,504→ locale keys (never show English `detail`); `networkError()`, `asMsg()`.
- `src/lib/wav.js` (pure): `resampleToMono16k` (window-average downmix+resample) + `encodeWav` (44B PCM16 header).
- Composables: `useCamera` (stream only on user gesture, torch, full-res capture with quality ladder under 5MiB, stops tracks on capture/stop/switch/unmount), `useFraming` (L1: sample 160×120/200ms, speak cues, auto-capture after 4 steady samples), `useLiveGuidance` (L3, OFF unless `VITE_LIVE_GUIDANCE=true`: 1 frame/1.5s to `/api/segment`, ~$0.0025/frame), `useVoiceQuestion` (getUserMedia→MediaRecorder→decode→16k WAV; stops mic tracks immediately for iOS earpiece bug), `useSpeech` (Web Speech API, chunked utterances ~15s Chrome bug, voice resolution incl. woman/man name-heuristic best-effort, per-lang prefs), `usePreferences` (locale/theme/mode/voice in localStorage, `t()` helper, `<html lang>` + `data-theme`), `useBackendStatus` (auto poll, no manual button), `useEarcons` (lazy AudioContext, tick while working).
- `src/i18n.js`: `LOCALES`, `VOICE_LANG` (BCP47), `ANSWER_LANG_NAME`, `translate(code,key,params)` with en fallback; `STRINGS` 5 locales, placeholders `{...}` must match exactly; `npm run check-locales` enforces.
- `ZoomView.vue`: props crop File/URL + box; zoom 100-400%, contrast/invert filters, labeled.
- A11y (preserve): native labeled inputs, keyboard support, focus management, `role=status`/`aria-live` regions, SVG overlay `viewBox` = image NATURAL size (1:1 coord mapping at any scale) + `role="img"`/`aria-label`/`<title>` per box.

## 8. Config & secrets

- Backend (`backend/.env`, gitignored, NEVER read/print/commit; `.env.example` placeholder-only): `MODEL_API_KEY` (starts `LLM_`, backend-only), `FRONTEND_DIST` (serve Vite `dist/` at `/` after API routes; Docker sets it), `RATE_LIMIT_PER_MINUTE` (0=off, 30 suggested public; ≥60 if live guidance on), `CORS_ORIGINS` JSON list (default localhost:5173 + 127.0.0.1:5173).
- Frontend (`frontend/.env`, optional): `VITE_BACKEND_URL` (`/` recommended), `VITE_HTTPS=0` (plain HTTP), `VITE_ALLOWED_HOSTS` (tunnel hosts), `VITE_LIVE_GUIDANCE=true` (off default). NEVER secrets in `VITE_*` (inlined into bundle).
- Docker: `docker build -t visionspark . && docker run --rm -e MODEL_API_KEY -p 8000:8000 visionspark`; behind proxy use `--proxy-headers --forwarded-allow-ips <proxy>` (never `"*"` if directly reachable).

## 9. Run & verify

```bash
cp backend/.env.example backend/.env   # then set MODEL_API_KEY
./full-start.sh                        # or .bat/.command; --http for plain HTTP
# manual: cd backend && uv sync && uv run uvicorn app.main:app --host localhost --port 8000
#        cd frontend && npm install && npm run dev -- --port 5173
# App https://localhost:5173 (accept self-signed once), API http://localhost:8000/docs
# Phone: same Wi-Fi → https://<lan-ip>:5173 (Vite proxy → backend; allow 5173 in firewall)
# Served build: cd frontend && npm run build && cd ../backend && FRONTEND_DIST=../frontend/dist uv run uvicorn app.main:app --port 8000 (+ tunnel for real HTTPS)
```

Quality gates (run before reporting done):
```bash
cd backend && uv run pytest -q && uv run ruff check . && uv run ruff format --check .
cd frontend && npm run verify   # = check-locales + node:test + vite build
```
Live smoke only on local paths (`/health`, missing key, bad uploads). Tests mock upstream — no real API calls, ever.

## 10. Rules for LLM agents (from AGENTS.md)

- `uv` only in backend (never pip/venv/requirements.txt); `npm` only in frontend. Python 3.12, never system python.
- Never create/read/print/commit `backend/.env`; never log/return/echo key; upstream errors → sanitized `MetaUpstreamError`.
- Reuse conventions: `_post_image_text` envelope, `_read_validated_image`, `{model,status,...}` shapes, `Box` model.
- Preserve a11y + SVG `viewBox`=natural-size rule.
- Minimal focused diffs; no unrelated refactors; no new deps/endpoints/features beyond request; no commit/push/history-rewrite unless asked; never claim a live check passed without running it.

## 11. Common task recipes

- **Tune SAM phrases:** edit `PRESET_PLANS` / `FALLBACK_CONCEPTS` in `pipeline.py` + `PLAN_INSTRUCTIONS` examples in `meta_api.py`; keep ≤4 words, panel-over-text ("label" not "expiry date").
- **Change answer behavior:** edit `READ_INSTRUCTIONS` rules + `ANSWER_LANGUAGES`; keep `{answered,not_visible,unreadable}` + evidence-verbatim rule.
- **Add UI string:** add key to ALL 5 locales in `i18n.js` with identical placeholders → `npm run check-locales`.
- **Add /api/* endpoint:** validate via `_read_validated_*`, check key → 503, wrap Meta calls in `MetaUpstreamError` → HTTPException, add response model, add mocked pytest.
- **Debug assist:** check `timings_ms`, `concepts_tried`, `source/fallback`, `framing` codes; backend logs one `Assist:` line per call.

## 12. Known limitations

AI answers may be wrong (always double-check label for allergens/dates/safety). Region Q&A uses rectangular crops, masks unused. Uploads JPEG/PNG/WebP 5MiB, Q 500 chars, voice ≤15s en/fr/es/zh only (Greek → keyboard dictation), 60s AI timeout. Camera/mic need secure context (localhost or HTTPS) + supporting browser. No offline mode; needs internet for Meta API.

import io
import logging
import time
import wave
from collections import deque
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.imaging import ImageDecodeError, ImageTooLargeError
from app.meta_api import (
    ASK_MODEL_ID,
    ASR_LANGUAGE_BIAS,
    ASR_SAMPLE_RATES,
    DEFAULT_PROMPT,
    MAX_AUDIO_BYTES,
    MAX_AUDIO_SECONDS,
    MAX_IMAGE_BYTES,
    MAX_PROMPT_CHARS,
    MAX_QUESTION_CHARS,
    MODEL_ID,
    REQUEST_TIMEOUT_SECONDS,
    SUPPORTED_AUDIO_TYPES,
    SUPPORTED_MEDIA_TYPES,
    TRANSCRIBE_MODEL_ID,
    MetaUpstreamError,
    ask_about_image,
    parse_boxes,
    segment_image,
    transcribe_audio,
)
from app.pipeline import ANSWER_LANGUAGES, PRESET_PLANS, run_assist
from app.settings import Settings, get_settings

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Share one HTTP client across requests to reuse TLS connections."""
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS) as client:
        app.state.http = client
        yield


app = FastAPI(title="VisionSpark API", lifespan=lifespan)

# Multipart framing overhead on top of the image itself.
MAX_BODY_BYTES = MAX_IMAGE_BYTES + 64 * 1024
_BODY_TOO_LARGE_DETAIL = "Image exceeds the 5 MiB size limit."


class _BodyTooLargeError(HTTPException):
    """413 raised while counting streamed bytes. It must be an HTTPException:
    FastAPI re-raises those during body parsing but turns other errors into 400."""

    def __init__(self) -> None:
        super().__init__(status_code=413, detail=_BODY_TOO_LARGE_DETAIL)


def _request_content_length(scope: Scope) -> int | None:
    for name, value in scope.get("headers", []):
        if name.lower() == b"content-length":
            try:
                return int(value)
            except ValueError:
                return None
    return None


class BodySizeLimitMiddleware:
    """Reject oversized /api/* POST bodies before Starlette spools them to disk.

    Pure ASGI: a Content-Length over the cap is rejected immediately,
    otherwise the receive channel is wrapped to count streamed bytes and the
    same 413 is returned once the cap is exceeded.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def _reject(self, scope: Scope, receive: Receive, send: Send) -> None:
        response = JSONResponse({"detail": _BODY_TOO_LARGE_DETAIL}, status_code=413)
        await response(scope, receive, send)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] != "http"
            or scope["method"] != "POST"
            or not scope["path"].startswith("/api/")
        ):
            await self.app(scope, receive, send)
            return
        content_length = _request_content_length(scope)
        if content_length is not None and content_length > MAX_BODY_BYTES:
            await self._reject(scope, receive, send)
            return
        if content_length is not None:
            await self.app(scope, receive, send)
            return
        seen = 0

        async def limited_receive() -> Message:
            nonlocal seen
            message = await receive()
            if message["type"] == "http.request":
                seen += len(message.get("body", b""))
                if seen > MAX_BODY_BYTES:
                    raise _BodyTooLargeError
            return message

        try:
            await self.app(scope, limited_receive, send)
        except _BodyTooLargeError:
            await self._reject(scope, receive, send)


app.add_middleware(BodySizeLimitMiddleware)


_RATE_LIMIT_WINDOW_SECONDS = 60.0
_RATE_LIMIT_MAX_IPS = 1024
_RATE_LIMIT_DETAIL = "Too many requests. Try again in a minute."

# Sliding-window hits per client IP (monotonic timestamps, oldest first).
_rate_limit_hits: dict[str, deque[float]] = {}


def reset_rate_limit_state() -> None:
    """Clear all tracked rate-limit state (tests)."""
    _rate_limit_hits.clear()


def _check_rate_limit(ip: str, limit_per_minute: int) -> bool:
    """Return True when the request is allowed, recording this hit.

    Sliding 60 s window per IP. Old timestamps are pruned on each check and
    the number of tracked IPs is capped (least-recently-seen evicted first).
    """
    now = time.monotonic()
    cutoff = now - _RATE_LIMIT_WINDOW_SECONDS
    hits = _rate_limit_hits.pop(ip, None)
    if hits is None:
        hits = deque()
    while hits and hits[0] <= cutoff:
        hits.popleft()
    allowed = len(hits) < limit_per_minute
    if allowed:
        hits.append(now)
    _rate_limit_hits[ip] = hits
    while len(_rate_limit_hits) > _RATE_LIMIT_MAX_IPS:
        _rate_limit_hits.pop(next(iter(_rate_limit_hits)))
    return allowed


class RateLimitMiddleware:
    """Opt-in per-IP rate limit for POST /api/* requests.

    Pure ASGI sliding window keyed by scope["client"]. Disabled when
    Settings.rate_limit_per_minute is 0. The setting is read lazily per
    request so tests can toggle it via the environment. Behind a reverse
    proxy, uvicorn needs --proxy-headers so scope["client"] is the real
    client.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        limit = get_settings().rate_limit_per_minute
        if (
            limit <= 0
            or scope["type"] != "http"
            or scope["method"] != "POST"
            or not scope["path"].startswith("/api/")
        ):
            await self.app(scope, receive, send)
            return
        client = scope.get("client")
        ip = client[0] if client else "unknown"
        if _check_rate_limit(ip, limit):
            await self.app(scope, receive, send)
            return
        response = JSONResponse(
            {"detail": _RATE_LIMIT_DETAIL},
            status_code=429,
            headers={"Retry-After": "60"},
        )
        await response(scope, receive, send)


app.add_middleware(RateLimitMiddleware)
# Added last = outermost, so even the middleware's own 413 carries CORS headers.
# Every later middleware is likewise added before CORS.
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


def mount_frontend(app: FastAPI, path: Path) -> bool:
    """Serve the built frontend from ``path`` at "/".

    Returns True when mounted, False when ``path`` holds no index.html.
    Call after all API routes so /health, /api/*, and /docs keep working.
    """
    if not (path / "index.html").is_file():
        return False
    app.mount("/", StaticFiles(directory=path, html=True), name="frontend")
    return True


class Box(BaseModel):
    x1: int
    y1: int
    x2: int
    y2: int
    w: int
    h: int
    c: float | None = None


class SegmentResponse(BaseModel):
    model: str
    status: str
    output_text: str
    boxes: list[Box]


class AskResponse(BaseModel):
    model: str
    status: str
    answer: str


class AssistResponse(BaseModel):
    model: str
    status: str
    answer_status: str
    answer: str
    evidence: str
    source: str
    fallback: bool
    concept: str | None
    concepts_tried: list[str]
    boxes: list[Box]
    framing: list[str]
    timings_ms: dict[str, int]


class TranscribeResponse(BaseModel):
    model: str
    status: str
    transcript: str


async def _read_validated_image(image: UploadFile) -> tuple[bytes, str]:
    """Validate an upload and return its bytes plus media type."""
    if image.content_type not in SUPPORTED_MEDIA_TYPES:
        raise HTTPException(
            status_code=415,
            detail="Unsupported media type. Use JPEG, PNG, or WebP.",
        )
    content = await image.read(MAX_IMAGE_BYTES + 1)
    if len(content) > MAX_IMAGE_BYTES:
        raise HTTPException(
            status_code=413,
            detail="Image exceeds the 5 MiB size limit.",
        )
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")
    # The declared content type is client-controlled; verify the magic bytes.
    media_type = image.content_type or "image/png"
    if media_type == "image/jpeg":
        matches = content.startswith(b"\xff\xd8\xff")
    elif media_type == "image/png":
        matches = content.startswith(b"\x89PNG\r\n\x1a\n")
    elif media_type == "image/webp":
        matches = content[0:4] == b"RIFF" and content[8:12] == b"WEBP"
    else:  # Unreachable: the media type was validated above.
        matches = False
    if not matches:
        raise HTTPException(
            status_code=415,
            detail="Unsupported media type. Use JPEG, PNG, or WebP.",
        )
    return content, media_type


async def _read_validated_audio(audio: UploadFile) -> bytes:
    """Validate a WAV upload and return its bytes."""
    if audio.content_type not in SUPPORTED_AUDIO_TYPES:
        raise HTTPException(
            status_code=415,
            detail="Unsupported audio type. Use WAV.",
        )
    content = await audio.read(MAX_AUDIO_BYTES + 1)
    if len(content) > MAX_AUDIO_BYTES:
        raise HTTPException(
            status_code=413,
            detail="Audio exceeds the 1 MiB size limit.",
        )
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")
    # The declared content type is client-controlled; verify the magic bytes.
    if not (content[0:4] == b"RIFF" and content[8:12] == b"WAVE"):
        raise HTTPException(
            status_code=415,
            detail="Unsupported audio type. Use WAV.",
        )
    try:
        with wave.open(io.BytesIO(content), "rb") as wav:
            comptype = wav.getcomptype()
            channels = wav.getnchannels()
            width = wav.getsampwidth()
            rate = wav.getframerate()
            frames = wav.getnframes()
    except Exception as exc:
        raise HTTPException(
            status_code=400, detail="Could not decode the WAV file."
        ) from exc
    if comptype != "NONE":
        raise HTTPException(status_code=400, detail="WAV must be uncompressed PCM.")
    if channels != 1:
        raise HTTPException(status_code=400, detail="WAV must be mono.")
    if width != 2:
        raise HTTPException(status_code=400, detail="WAV must be 16-bit.")
    if rate not in ASR_SAMPLE_RATES:
        raise HTTPException(status_code=400, detail="WAV must be 16 kHz or 24 kHz.")
    if frames <= 0:
        raise HTTPException(
            status_code=400, detail="Audio contains no playable samples."
        )
    if frames / rate > MAX_AUDIO_SECONDS:
        raise HTTPException(
            status_code=400, detail="Audio is too long (max 15.5 seconds)."
        )
    return content


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


def _shared_client(request: Request) -> httpx.AsyncClient | None:
    """Lifespan HTTP client, or None when the lifespan did not run (tests)."""
    return getattr(request.app.state, "http", None)


@app.post("/api/segment", response_model=SegmentResponse)
async def segment(
    request: Request,
    image: UploadFile = File(...),
    prompt: str = Form(default=DEFAULT_PROMPT),
    settings: Settings = Depends(get_settings),
) -> SegmentResponse:
    api_key = settings.model_api_key
    if not api_key:
        raise HTTPException(
            status_code=503,
            detail="Segmentation service is not configured.",
        )
    prompt = prompt.strip() or DEFAULT_PROMPT
    if len(prompt) > MAX_PROMPT_CHARS:
        raise HTTPException(
            status_code=400,
            detail=f"Prompt must be at most {MAX_PROMPT_CHARS} characters.",
        )
    content, media_type = await _read_validated_image(image)
    try:
        output_text = await segment_image(
            api_key, content, media_type, prompt, client=_shared_client(request)
        )
    except MetaUpstreamError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    return SegmentResponse(
        model=MODEL_ID,
        status="ok",
        output_text=output_text,
        boxes=parse_boxes(output_text),
    )


@app.post("/api/ask", response_model=AskResponse)
async def ask(
    request: Request,
    image: UploadFile = File(...),
    question: str = Form(...),
    settings: Settings = Depends(get_settings),
) -> AskResponse:
    api_key = settings.model_api_key
    if not api_key:
        raise HTTPException(
            status_code=503,
            detail="Question answering service is not configured.",
        )
    question = question.strip()
    if not question:
        raise HTTPException(status_code=400, detail="Question must not be empty.")
    if len(question) > MAX_QUESTION_CHARS:
        raise HTTPException(
            status_code=400,
            detail=f"Question must be at most {MAX_QUESTION_CHARS} characters.",
        )
    content, media_type = await _read_validated_image(image)
    try:
        answer = await ask_about_image(
            api_key, content, media_type, question, client=_shared_client(request)
        )
    except MetaUpstreamError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    return AskResponse(model=ASK_MODEL_ID, status="ok", answer=answer)


@app.post("/api/assist", response_model=AssistResponse)
async def assist(
    request: Request,
    image: UploadFile = File(...),
    question: str = Form(...),
    language: str = Form(default="en"),
    preset: str | None = Form(default=None),
    settings: Settings = Depends(get_settings),
) -> AssistResponse:
    api_key = settings.model_api_key
    if not api_key:
        raise HTTPException(
            status_code=503,
            detail="Assistant service is not configured.",
        )
    question = question.strip()
    if not question:
        raise HTTPException(status_code=400, detail="Question must not be empty.")
    if len(question) > MAX_QUESTION_CHARS:
        raise HTTPException(
            status_code=400,
            detail=f"Question must be at most {MAX_QUESTION_CHARS} characters.",
        )
    if language not in ANSWER_LANGUAGES:
        raise HTTPException(status_code=400, detail="Unsupported language.")
    if preset is not None and preset not in PRESET_PLANS:
        raise HTTPException(status_code=400, detail="Unknown preset.")
    content, _media_type = await _read_validated_image(image)
    try:
        result = await run_assist(
            api_key=api_key,
            image_bytes=content,
            question=question,
            language=language,
            preset=preset,
            client=_shared_client(request),
        )
    except MetaUpstreamError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    except ImageTooLargeError as exc:
        raise HTTPException(
            status_code=413, detail="Image dimensions are too large."
        ) from exc
    except ImageDecodeError as exc:
        raise HTTPException(
            status_code=415, detail="Could not decode the image."
        ) from exc
    return AssistResponse(
        model=ASK_MODEL_ID,
        status="ok",
        answer_status=result.answer_status,
        answer=result.answer,
        evidence=result.evidence,
        source=result.source,
        fallback=result.fallback,
        concept=result.concept,
        concepts_tried=result.concepts_tried,
        boxes=result.boxes,
        framing=result.framing,
        timings_ms=result.timings_ms,
    )


@app.post("/api/transcribe", response_model=TranscribeResponse)
async def transcribe(
    request: Request,
    audio: UploadFile = File(...),
    language: str = Form(default="en"),
    settings: Settings = Depends(get_settings),
) -> TranscribeResponse:
    api_key = settings.model_api_key
    if not api_key:
        raise HTTPException(
            status_code=503,
            detail="Transcription service is not configured.",
        )
    if language not in ASR_LANGUAGE_BIAS:
        raise HTTPException(
            status_code=400,
            detail="Voice input is not available for this language.",
        )
    content = await _read_validated_audio(audio)
    try:
        transcript = await transcribe_audio(
            api_key, content, language, client=_shared_client(request)
        )
    except MetaUpstreamError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    return TranscribeResponse(
        model=TRANSCRIBE_MODEL_ID, status="ok", transcript=transcript
    )


# Serve the built frontend at "/" when FRONTEND_DIST is set. This runs after
# all API routes so /health, /api/*, and /docs keep working.
_frontend_dist = get_settings().frontend_dist
if _frontend_dist is not None:
    if mount_frontend(app, _frontend_dist):
        logger.info("Serving frontend from %s", _frontend_dist)
    else:
        logger.warning("FRONTEND_DIST has no index.html: %s", _frontend_dist)

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.meta_api import (
    ASK_MODEL_ID,
    DEFAULT_PROMPT,
    MAX_IMAGE_BYTES,
    MAX_PROMPT_CHARS,
    MAX_QUESTION_CHARS,
    MODEL_ID,
    REQUEST_TIMEOUT_SECONDS,
    SUPPORTED_MEDIA_TYPES,
    MetaUpstreamError,
    ask_about_image,
    parse_boxes,
    segment_image,
)
from app.settings import Settings, get_settings


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Share one HTTP client across requests to reuse TLS connections."""
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS) as client:
        app.state.http = client
        yield


app = FastAPI(title="VisionSpark API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

# Multipart framing overhead on top of the image itself.
MAX_BODY_BYTES = MAX_IMAGE_BYTES + 64 * 1024
_BODY_TOO_LARGE_DETAIL = "Image exceeds the 5 MiB size limit."


class _BodyTooLargeError(Exception):
    """Raised by the size-counting receive wrapper once the cap is exceeded."""


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


class Box(BaseModel):
    x1: int
    y1: int
    x2: int
    y2: int
    w: int
    h: int


class SegmentResponse(BaseModel):
    model: str
    status: str
    output_text: str
    boxes: list[Box]


class AskResponse(BaseModel):
    model: str
    status: str
    answer: str


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

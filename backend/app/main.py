from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from app.meta_api import (
    ASK_MODEL_ID,
    DEFAULT_PROMPT,
    MAX_IMAGE_BYTES,
    MAX_PROMPT_CHARS,
    MAX_QUESTION_CHARS,
    MODEL_ID,
    SUPPORTED_MEDIA_TYPES,
    MetaUpstreamError,
    ask_about_image,
    parse_boxes,
    segment_image,
)
from app.settings import Settings, get_settings

app = FastAPI(title="VisionSpark API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


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
    return content, image.content_type or "image/png"


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/segment", response_model=SegmentResponse)
async def segment(
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
        output_text = await segment_image(api_key, content, media_type, prompt)
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
        answer = await ask_about_image(api_key, content, media_type, question)
    except MetaUpstreamError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    return AskResponse(model=ASK_MODEL_ID, status="ok", answer=answer)

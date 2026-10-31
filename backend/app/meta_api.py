"""Meta Model API client for image segmentation and visual Q&A.

The Meta API key is only ever sent in the outbound ``Authorization`` header.
It is never logged and never included in errors or responses.
"""

import base64
import logging
import re
from typing import Any

import httpx

logger = logging.getLogger(__name__)

META_RESPONSES_URL = "https://api.meta.ai/v1/responses"
MODEL_ID = "sam-3.1"
ASK_MODEL_ID = "muse-spark-1.3"
REQUEST_TIMEOUT_SECONDS = 60.0

SUPPORTED_MEDIA_TYPES = frozenset({"image/jpeg", "image/png", "image/webp"})
MAX_IMAGE_BYTES = 5 * 1024 * 1024
MAX_PROMPT_CHARS = 200
MAX_QUESTION_CHARS = 500
DEFAULT_PROMPT = "object"

# Prepended to every Q&A question so the model answers for a listener who
# cannot see the image, in TTS-friendly plain sentences, without guessing.
ASK_INSTRUCTIONS = (
    "You are assisting a blind or low-vision person who cannot see this image. "
    "Answer the question below in short, plain sentences suitable for "
    "text-to-speech: no Markdown, no list symbols, no emojis. Read text exactly "
    "as printed when asked. If the requested information is not visible or not "
    "legible, say so clearly instead of guessing. Never guess allergens, doses, "
    "or dates. Question:"
)

_BOX_RE = re.compile(r"<\|box;x1=(\d+);y1=(\d+);x2=(\d+);y2=(\d+);w=(\d+);h=(\d+)\|>")


class MetaUpstreamError(Exception):
    """Sanitized upstream failure safe to surface as an HTTP error."""

    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message


def parse_boxes(output_text: str) -> list[dict[str, int]]:
    """Extract structured boxes from ``<|box;...|>`` tokens.

    Malformed or degenerate tokens are skipped. Mask payloads are intentionally
    excluded; they remain available in the raw ``output_text``.
    """
    boxes: list[dict[str, int]] = []
    for match in _BOX_RE.finditer(output_text):
        x1, y1, x2, y2, w, h = (int(v) for v in match.groups())
        if w <= 0 or h <= 0 or x2 <= x1 or y2 <= y1:
            continue
        boxes.append({"x1": x1, "y1": y1, "x2": x2, "y2": y2, "w": w, "h": h})
    return boxes


def extract_output_text(payload: Any) -> str | None:
    """Pull concatenated ``output_text`` from a Responses API payload.

    Returns ``None`` when the structure is not as expected. An empty string
    is a valid outcome (zero matches) and is returned as ``""``.
    """
    if not isinstance(payload, dict):
        return None
    output = payload.get("output")
    if not isinstance(output, list):
        return None
    parts: list[str] = []
    found = False
    for item in output:
        if not isinstance(item, dict):
            continue
        content = item.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") != "output_text":
                continue
            found = True
            text = block.get("text")
            if isinstance(text, str):
                parts.append(text)
    if not found:
        return None
    return "".join(parts)


async def _post_with_client(
    client: httpx.AsyncClient,
    api_key: str,
    model: str,
    text: str,
    image_bytes: bytes,
    media_type: str,
    service: str,
) -> str:
    """POST one text+image message via an already-open client.

    The caller owns the client's lifecycle; it is never closed here.
    """
    data_url = f"data:{media_type};base64,{base64.b64encode(image_bytes).decode()}"
    body = {
        "model": model,
        "input": [
            {
                "type": "message",
                "role": "user",
                "content": [
                    {"type": "input_text", "text": text},
                    {"type": "input_image", "image_url": data_url},
                ],
            }
        ],
    }
    try:
        response = await client.post(
            META_RESPONSES_URL,
            headers={"Authorization": f"Bearer {api_key}"},
            json=body,
        )
    except httpx.TimeoutException as exc:
        # Log only the service label and the exception class: never headers,
        # bodies, the image, or the API key.
        logger.warning(
            "Upstream timeout: service=%s error=%s", service, type(exc).__name__
        )
        raise MetaUpstreamError(504, f"{service} request timed out.") from exc
    except httpx.HTTPError as exc:
        logger.warning(
            "Upstream transport error: service=%s error=%s",
            service,
            type(exc).__name__,
        )
        raise MetaUpstreamError(502, f"{service} provider is unreachable.") from exc
    if response.status_code != 200:
        logger.warning(
            "Upstream error response: service=%s status=%s",
            service,
            response.status_code,
        )
        if response.status_code in (401, 403):
            raise MetaUpstreamError(503, f"{service} service is misconfigured.")
        if response.status_code == 429:
            raise MetaUpstreamError(503, f"{service} is busy. Try again shortly.")
        raise MetaUpstreamError(502, f"{service} provider returned an error.")
    try:
        payload = response.json()
    except ValueError as exc:
        logger.warning(
            "Upstream bad JSON: service=%s status=%s error=%s",
            service,
            response.status_code,
            type(exc).__name__,
        )
        raise MetaUpstreamError(
            502, f"{service} provider returned an unexpected response."
        ) from exc
    output_text = extract_output_text(payload)
    if output_text is None:
        logger.warning(
            "Upstream unexpected structure: service=%s status=%s",
            service,
            response.status_code,
        )
        raise MetaUpstreamError(
            502, f"{service} provider returned an unexpected response."
        )
    return output_text


async def _post_image_text(
    api_key: str,
    model: str,
    text: str,
    image_bytes: bytes,
    media_type: str,
    service: str,
    *,
    client: httpx.AsyncClient | None = None,
) -> str:
    """POST one text+image message and return the concatenated output text.

    Uses the proven ``/v1/responses`` envelope: a single user message with an
    ``input_text`` part and an ``input_image`` part carrying a Base64 data URL.

    When ``client`` is given it is reused (and left open); otherwise a
    temporary client is created for this call.

    Raises:
        MetaUpstreamError: on transport failures, non-2xx responses, or
            unexpected response structure. Messages are sanitized and labeled
            with ``service``.
    """
    if client is not None:
        return await _post_with_client(
            client, api_key, model, text, image_bytes, media_type, service
        )
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS) as temp_client:
        return await _post_with_client(
            temp_client, api_key, model, text, image_bytes, media_type, service
        )


async def segment_image(
    api_key: str,
    image_bytes: bytes,
    media_type: str,
    prompt: str,
    *,
    client: httpx.AsyncClient | None = None,
) -> str:
    """Forward an image to SAM 3.1 and return the raw segmentation token text.

    Raises:
        MetaUpstreamError: on transport failures, non-2xx responses, or
            unexpected response structure. Messages are sanitized.
    """
    return await _post_image_text(
        api_key,
        MODEL_ID,
        prompt,
        image_bytes,
        media_type,
        "Segmentation",
        client=client,
    )


async def ask_about_image(
    api_key: str,
    image_bytes: bytes,
    media_type: str,
    question: str,
    *,
    client: httpx.AsyncClient | None = None,
) -> str:
    """Send an image plus a question to Muse Spark and return the answer text.

    Raises:
        MetaUpstreamError: on transport failures, non-2xx responses, or
            unexpected response structure. Messages are sanitized.
    """
    return await _post_image_text(
        api_key,
        ASK_MODEL_ID,
        f"{ASK_INSTRUCTIONS}\n{question}",
        image_bytes,
        media_type,
        "Question answering",
        client=client,
    )

"""Meta Model API client for image segmentation and visual Q&A.

The Meta API key is only ever sent in the outbound ``Authorization`` header.
It is never logged and never included in errors or responses.
"""

import base64
import re
from typing import Any

import httpx

META_RESPONSES_URL = "https://api.meta.ai/v1/responses"
MODEL_ID = "sam-3.1"
ASK_MODEL_ID = "muse-spark-1.3"
REQUEST_TIMEOUT_SECONDS = 60.0

SUPPORTED_MEDIA_TYPES = frozenset({"image/jpeg", "image/png", "image/webp"})
MAX_IMAGE_BYTES = 5 * 1024 * 1024
MAX_PROMPT_CHARS = 200
MAX_QUESTION_CHARS = 500
DEFAULT_PROMPT = "object"

_BOX_RE = re.compile(r"<\|box;x1=(\d+);y1=(\d+);x2=(\d+);y2=(\d+);w=(\d+);h=(\d+)\|>")


class MetaUpstreamError(Exception):
    """Sanitized upstream failure safe to surface as an HTTP error."""

    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message


def parse_boxes(output_text: str) -> list[dict[str, int]]:
    """Extract structured boxes from ``<|box;...|>`` tokens.

    Malformed tokens are skipped. Mask payloads are intentionally excluded;
    they remain available in the raw ``output_text``.
    """
    boxes: list[dict[str, int]] = []
    for match in _BOX_RE.finditer(output_text):
        x1, y1, x2, y2, w, h = (int(v) for v in match.groups())
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


async def _post_image_text(
    api_key: str,
    model: str,
    text: str,
    image_bytes: bytes,
    media_type: str,
    service: str,
) -> str:
    """POST one text+image message and return the concatenated output text.

    Uses the proven ``/v1/responses`` envelope: a single user message with an
    ``input_text`` part and an ``input_image`` part carrying a Base64 data URL.

    Raises:
        MetaUpstreamError: on transport failures, non-2xx responses, or
            unexpected response structure. Messages are sanitized and labeled
            with ``service``.
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
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS) as client:
            response = await client.post(
                META_RESPONSES_URL,
                headers={"Authorization": f"Bearer {api_key}"},
                json=body,
            )
    except httpx.TimeoutException as exc:
        raise MetaUpstreamError(504, f"{service} request timed out.") from exc
    except httpx.HTTPError as exc:
        raise MetaUpstreamError(502, f"{service} provider is unreachable.") from exc
    if response.status_code != 200:
        raise MetaUpstreamError(502, f"{service} provider returned an error.")
    try:
        payload = response.json()
    except ValueError as exc:
        raise MetaUpstreamError(
            502, f"{service} provider returned an unexpected response."
        ) from exc
    output_text = extract_output_text(payload)
    if output_text is None:
        raise MetaUpstreamError(
            502, f"{service} provider returned an unexpected response."
        )
    return output_text


async def segment_image(
    api_key: str,
    image_bytes: bytes,
    media_type: str,
    prompt: str,
) -> str:
    """Forward an image to SAM 3.1 and return the raw segmentation token text.

    Raises:
        MetaUpstreamError: on transport failures, non-2xx responses, or
            unexpected response structure. Messages are sanitized.
    """
    return await _post_image_text(
        api_key, MODEL_ID, prompt, image_bytes, media_type, "Segmentation"
    )


async def ask_about_image(
    api_key: str,
    image_bytes: bytes,
    media_type: str,
    question: str,
) -> str:
    """Send an image plus a question to Muse Spark and return the answer text.

    Raises:
        MetaUpstreamError: on transport failures, non-2xx responses, or
            unexpected response structure. Messages are sanitized.
    """
    return await _post_image_text(
        api_key,
        ASK_MODEL_ID,
        question,
        image_bytes,
        media_type,
        "Question answering",
    )

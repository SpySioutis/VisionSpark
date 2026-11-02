"""Server-side image handling for the assist pipeline.

Pure and synchronous: EXIF correction, JPEG encoding, and box crops. The
pipeline calls these via ``asyncio.to_thread()`` so the event loop never
blocks.
"""

import io
from typing import Any

from PIL import Image, ImageOps

MAX_PIXELS = 40_000_000


class ImageTooLargeError(Exception):
    """The image has more pixels than ``MAX_PIXELS``."""


class ImageDecodeError(Exception):
    """The image bytes could not be decoded."""


def load_normalized(image_bytes: bytes) -> Image.Image:
    """Open image bytes, apply EXIF orientation, and convert to RGB.

    The pixel count is checked from the header before the pixels are
    decoded, as a decompression-bomb guard.

    Raises:
        ImageTooLargeError: when width * height exceeds ``MAX_PIXELS``.
        ImageDecodeError: when the bytes cannot be decoded as an image.
    """
    try:
        with Image.open(io.BytesIO(image_bytes)) as probe:
            width, height = probe.size
    except Exception as exc:
        raise ImageDecodeError("Could not decode the image.") from exc
    if width * height > MAX_PIXELS:
        raise ImageTooLargeError("Image dimensions are too large.")
    try:
        with Image.open(io.BytesIO(image_bytes)) as raw:
            oriented = ImageOps.exif_transpose(raw)
            oriented.load()
            return oriented.convert("RGB")
    except Exception as exc:
        raise ImageDecodeError("Could not decode the image.") from exc


def to_jpeg(img: Image.Image, max_edge: int, quality: int) -> bytes:
    """Encode an image as JPEG.

    Downscales with LANCZOS only when the image is larger than ``max_edge``.
    """
    if img.mode != "RGB":
        img = img.convert("RGB")
    width, height = img.size
    edge = max(width, height)
    if edge > max_edge:
        scale = max_edge / edge
        img = img.resize(
            (max(1, round(width * scale)), max(1, round(height * scale))),
            Image.LANCZOS,
        )
    buffer = io.BytesIO()
    img.save(buffer, format="JPEG", quality=quality)
    return buffer.getvalue()


def crop_box(img: Image.Image, box: dict[str, Any], pad: float = 0.05) -> Image.Image:
    """Crop a SAM box (in its own w/h frame) with padding, clamped to bounds.

    The same math as ``paddedCropRect()`` in the frontend: scale into image
    pixels, expand by ``pad`` on each side, round, and clamp.
    """
    width, height = img.size
    x1 = box["x1"] * width / box["w"]
    y1 = box["y1"] * height / box["h"]
    x2 = box["x2"] * width / box["w"]
    y2 = box["y2"] * height / box["h"]
    pad_x = (x2 - x1) * pad
    pad_y = (y2 - y1) * pad
    cx1 = max(0, round(x1 - pad_x))
    cy1 = max(0, round(y1 - pad_y))
    cx2 = min(width, round(x2 + pad_x))
    cy2 = min(height, round(y2 + pad_y))
    return img.crop((cx1, cy1, cx2, cy2))

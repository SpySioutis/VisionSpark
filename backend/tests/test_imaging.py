import io

import pytest
from PIL import Image

from app.imaging import (
    ImageDecodeError,
    ImageTooLargeError,
    crop_box,
    load_normalized,
    to_jpeg,
)


def _jpeg_bytes(width: int, height: int, orientation: int | None = None) -> bytes:
    img = Image.new("RGB", (width, height), color=(200, 30, 30))
    buffer = io.BytesIO()
    if orientation is None:
        img.save(buffer, format="JPEG")
    else:
        exif = Image.Exif()
        exif[274] = orientation
        img.save(buffer, format="JPEG", exif=exif)
    return buffer.getvalue()


def test_load_normalized_applies_exif_orientation() -> None:
    # Orientation 6: a stored 10x20 displays as 20x10.
    img = load_normalized(_jpeg_bytes(10, 20, orientation=6))
    assert img.size == (20, 10)
    assert img.mode == "RGB"


def test_load_normalized_pixel_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.imaging.MAX_PIXELS", 100)
    with pytest.raises(ImageTooLargeError):
        load_normalized(_jpeg_bytes(10, 20))


def test_load_normalized_broken_file() -> None:
    # Passes the JPEG magic-byte check but is not decodable.
    with pytest.raises(ImageDecodeError):
        load_normalized(b"\xff\xd8\xff" + b"\x00" * 64)


def test_to_jpeg_downscales_large_images() -> None:
    img = Image.open(io.BytesIO(_jpeg_bytes(100, 50)))
    out = to_jpeg(img, 40, 90)
    assert out.startswith(b"\xff\xd8\xff")
    assert Image.open(io.BytesIO(out)).size == (40, 20)


def test_to_jpeg_keeps_small_images() -> None:
    img = Image.open(io.BytesIO(_jpeg_bytes(30, 20)))
    out = to_jpeg(img, 40, 90)
    assert Image.open(io.BytesIO(out)).size == (30, 20)


def test_crop_box_padding_and_clamping() -> None:
    img = Image.new("RGB", (1000, 1000))
    crop = crop_box(
        img, {"x1": 100, "y1": 100, "x2": 200, "y2": 300, "w": 1000, "h": 1000}
    )
    assert crop.size == (110, 220)
    edge = crop_box(img, {"x1": 0, "y1": 0, "x2": 100, "y2": 100, "w": 1000, "h": 1000})
    assert edge.size == (105, 105)


def test_crop_box_scales_from_sam_frame() -> None:
    img = Image.new("RGB", (1000, 1000))
    crop = crop_box(img, {"x1": 50, "y1": 50, "x2": 150, "y2": 150, "w": 500, "h": 500})
    # Doubled to (100, 100)-(300, 300), then 10 px padding per side.
    assert crop.size == (220, 220)

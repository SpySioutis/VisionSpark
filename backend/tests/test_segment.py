from collections.abc import Generator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.main import app, get_settings
from app.meta_api import (
    MAX_IMAGE_BYTES,
    MetaUpstreamError,
    extract_output_text,
    parse_boxes,
)
from app.settings import Settings

client = TestClient(app)

SAMPLE_OUTPUT = (
    "<0f>0<|box;x1=10;y1=20;x2=100;y2=200;w=640;h=480|>"
    "<|mask;x=0;y=0;data=46,101,~...|>,"
    "1<|box;x1=300;y1=310;x2=400;y2=410;w=640;h=480|>"
    "<|mask;x=0;y=0;data=1,2,~...|>"
)

PNG_BYTES = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
    b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)


@pytest.fixture()
def configured_key() -> Generator[None]:
    app.dependency_overrides[get_settings] = lambda: Settings(model_api_key="test-key")
    yield
    app.dependency_overrides.clear()


@pytest.fixture()
def missing_key(monkeypatch: pytest.MonkeyPatch) -> Generator[None]:
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    app.dependency_overrides[get_settings] = lambda: Settings(model_api_key=None)
    yield
    app.dependency_overrides.clear()


def test_parse_boxes_single() -> None:
    assert parse_boxes(SAMPLE_OUTPUT) == [
        {"x1": 10, "y1": 20, "x2": 100, "y2": 200, "w": 640, "h": 480},
        {"x1": 300, "y1": 310, "x2": 400, "y2": 410, "w": 640, "h": 480},
    ]


def test_parse_boxes_confirmed_sam_token() -> None:
    text = "<|box;x1=92;y1=248;x2=439;y2=652;w=512;h=683|><|mask;...|>"
    assert parse_boxes(text) == [
        {"x1": 92, "y1": 248, "x2": 439, "y2": 652, "w": 512, "h": 683}
    ]


def test_parse_boxes_skips_malformed() -> None:
    text = "no tokens here <|box;x1=1;y1=2|> <|mask;x=0;y=0;data=1|>"
    assert parse_boxes(text) == []


def test_parse_boxes_empty() -> None:
    assert parse_boxes("") == []


def test_extract_output_text_valid() -> None:
    payload = {
        "output": [
            {
                "type": "message",
                "content": [
                    {"type": "output_text", "text": "abc"},
                    {"type": "output_text", "text": "def"},
                ],
            }
        ]
    }
    assert extract_output_text(payload) == "abcdef"


def test_extract_output_text_empty_is_valid() -> None:
    payload = {"output": [{"content": [{"type": "output_text", "text": ""}]}]}
    assert extract_output_text(payload) == ""


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"output": "nope"},
        {"output": [{"content": [{"type": "other", "text": "x"}]}]},
        {"output": [{"content": "nope"}]},
        None,
        "nope",
    ],
)
def test_extract_output_text_unexpected_structure(
    payload: Any,
) -> None:
    assert extract_output_text(payload) is None


def test_segment_success(configured_key: None, monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_segment(*args: Any, **kwargs: Any) -> str:
        return SAMPLE_OUTPUT

    monkeypatch.setattr("app.main.segment_image", fake_segment)
    response = client.post(
        "/api/segment",
        files={"image": ("test.png", PNG_BYTES, "image/png")},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["model"] == "sam-3.1"
    assert body["status"] == "ok"
    assert body["output_text"] == SAMPLE_OUTPUT
    assert body["boxes"] == [
        {"x1": 10, "y1": 20, "x2": 100, "y2": 200, "w": 640, "h": 480},
        {"x1": 300, "y1": 310, "x2": 400, "y2": 410, "w": 640, "h": 480},
    ]
    assert "test-key" not in response.text


def test_segment_unsupported_media_type(configured_key: None) -> None:
    response = client.post(
        "/api/segment",
        files={"image": ("test.txt", b"hello", "text/plain")},
    )
    assert response.status_code == 415
    assert "JPEG" in response.json()["detail"]


def test_segment_oversized_upload(configured_key: None) -> None:
    response = client.post(
        "/api/segment",
        files={
            "image": (
                "big.png",
                b"\x89PNG" + b"\x00" * MAX_IMAGE_BYTES,
                "image/png",
            )
        },
    )
    assert response.status_code == 413


def test_segment_missing_api_key(missing_key: None) -> None:
    response = client.post(
        "/api/segment",
        files={"image": ("test.png", PNG_BYTES, "image/png")},
    )
    assert response.status_code == 503
    assert "not configured" in response.json()["detail"]


def test_segment_upstream_failure_sanitized(
    configured_key: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_segment(*args: Any, **kwargs: Any) -> str:
        raise MetaUpstreamError(502, "Segmentation provider returned an error.")

    monkeypatch.setattr("app.main.segment_image", fake_segment)
    response = client.post(
        "/api/segment",
        files={"image": ("test.png", PNG_BYTES, "image/png")},
    )
    assert response.status_code == 502
    assert response.json() == {"detail": "Segmentation provider returned an error."}
    assert "test-key" not in response.text


def test_segment_upstream_timeout(
    configured_key: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_segment(*args: Any, **kwargs: Any) -> str:
        raise MetaUpstreamError(504, "Segmentation request timed out.")

    monkeypatch.setattr("app.main.segment_image", fake_segment)
    response = client.post(
        "/api/segment",
        files={"image": ("test.png", PNG_BYTES, "image/png")},
    )
    assert response.status_code == 504

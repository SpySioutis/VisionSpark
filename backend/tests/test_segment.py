from typing import Any

import pytest
from conftest import PNG_BYTES
from fastapi.testclient import TestClient

from app.meta_api import (
    DEFAULT_PROMPT,
    MAX_IMAGE_BYTES,
    MAX_PROMPT_CHARS,
    MetaUpstreamError,
    extract_output_text,
    parse_boxes,
)

SAMPLE_OUTPUT = (
    "<0f>0<|box;x1=10;y1=20;x2=100;y2=200;w=640;h=480|>"
    "<|mask;x=0;y=0;data=46,101,~...|>,"
    "1<|box;x1=300;y1=310;x2=400;y2=410;w=640;h=480|>"
    "<|mask;x=0;y=0;data=1,2,~...|>"
)


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


@pytest.mark.parametrize(
    "token",
    [
        "<|box;x1=100;y1=20;x2=100;y2=200;w=640;h=480|>",  # x2 <= x1
        "<|box;x1=10;y1=20;x2=5;y2=200;w=640;h=480|>",  # x2 < x1
        "<|box;x1=10;y1=200;x2=100;y2=200;w=640;h=480|>",  # y2 <= y1
        "<|box;x1=10;y1=300;x2=100;y2=200;w=640;h=480|>",  # y2 < y1
        "<|box;x1=10;y1=20;x2=100;y2=200;w=0;h=480|>",  # w == 0
        "<|box;x1=10;y1=20;x2=100;y2=200;w=640;h=0|>",  # h == 0
    ],
)
def test_parse_boxes_skips_degenerate(token: str) -> None:
    assert parse_boxes(token) == []


def test_parse_boxes_keeps_only_valid() -> None:
    text = (
        "<|box;x1=10;y1=20;x2=100;y2=200;w=640;h=480|>"
        "<|box;x1=10;y1=20;x2=100;y2=200;w=0;h=480|>"
        "<|box;x1=300;y1=310;x2=400;y2=410;w=640;h=480|>"
        "<|box;x1=50;y1=50;x2=40;y2=60;w=640;h=480|>"
    )
    assert parse_boxes(text) == [
        {"x1": 10, "y1": 20, "x2": 100, "y2": 200, "w": 640, "h": 480},
        {"x1": 300, "y1": 310, "x2": 400, "y2": 410, "w": 640, "h": 480},
    ]


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


def test_segment_success(
    client: TestClient, configured_key: None, monkeypatch: pytest.MonkeyPatch
) -> None:
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


def test_segment_unsupported_media_type(
    client: TestClient, configured_key: None
) -> None:
    response = client.post(
        "/api/segment",
        files={"image": ("test.txt", b"hello", "text/plain")},
    )
    assert response.status_code == 415
    assert "JPEG" in response.json()["detail"]


def test_segment_oversized_upload(client: TestClient, configured_key: None) -> None:
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


def test_segment_missing_api_key(client: TestClient, missing_key: None) -> None:
    response = client.post(
        "/api/segment",
        files={"image": ("test.png", PNG_BYTES, "image/png")},
    )
    assert response.status_code == 503
    assert "not configured" in response.json()["detail"]


def test_segment_upstream_failure_sanitized(
    client: TestClient, configured_key: None, monkeypatch: pytest.MonkeyPatch
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
    client: TestClient, configured_key: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_segment(*args: Any, **kwargs: Any) -> str:
        raise MetaUpstreamError(504, "Segmentation request timed out.")

    monkeypatch.setattr("app.main.segment_image", fake_segment)
    response = client.post(
        "/api/segment",
        files={"image": ("test.png", PNG_BYTES, "image/png")},
    )
    assert response.status_code == 504


def test_segment_prompt_too_long(client: TestClient, configured_key: None) -> None:
    response = client.post(
        "/api/segment",
        files={"image": ("test.png", PNG_BYTES, "image/png")},
        data={"prompt": "x" * (MAX_PROMPT_CHARS + 1)},
    )
    assert response.status_code == 400
    assert "at most" in response.json()["detail"]


def test_segment_whitespace_prompt_uses_default(
    client: TestClient, configured_key: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: dict[str, Any] = {}

    async def fake_segment(
        api_key: str, image_bytes: bytes, media_type: str, prompt: str, **kwargs: Any
    ) -> str:
        seen["prompt"] = prompt
        return ""

    monkeypatch.setattr("app.main.segment_image", fake_segment)
    response = client.post(
        "/api/segment",
        files={"image": ("test.png", PNG_BYTES, "image/png")},
        data={"prompt": "   "},
    )
    assert response.status_code == 200
    assert seen["prompt"] == DEFAULT_PROMPT


def test_segment_custom_prompt_forwarded(
    client: TestClient, configured_key: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: dict[str, Any] = {}

    async def fake_segment(
        api_key: str, image_bytes: bytes, media_type: str, prompt: str, **kwargs: Any
    ) -> str:
        seen["prompt"] = prompt
        return ""

    monkeypatch.setattr("app.main.segment_image", fake_segment)
    response = client.post(
        "/api/segment",
        files={"image": ("test.png", PNG_BYTES, "image/png")},
        data={"prompt": "label"},
    )
    assert response.status_code == 200
    assert seen["prompt"] == "label"


def test_segment_empty_file(client: TestClient, configured_key: None) -> None:
    response = client.post(
        "/api/segment",
        files={"image": ("empty.png", b"", "image/png")},
    )
    assert response.status_code == 400
    assert "empty" in response.json()["detail"]

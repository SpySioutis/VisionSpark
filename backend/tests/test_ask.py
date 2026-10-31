from typing import Any

import pytest
from conftest import PNG_BYTES
from fastapi.testclient import TestClient

from app.meta_api import MAX_IMAGE_BYTES, MAX_QUESTION_CHARS, MetaUpstreamError

SAMPLE_ANSWER = "The image shows a brown dog sitting on the grass."


def test_ask_success(
    client: TestClient, configured_key: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: dict[str, Any] = {}

    async def fake_ask(
        api_key: str, image_bytes: bytes, media_type: str, question: str, **kwargs: Any
    ) -> str:
        seen["api_key"] = api_key
        seen["image_bytes"] = image_bytes
        seen["media_type"] = media_type
        seen["question"] = question
        return SAMPLE_ANSWER

    monkeypatch.setattr("app.main.ask_about_image", fake_ask)
    response = client.post(
        "/api/ask",
        files={"image": ("test.png", PNG_BYTES, "image/png")},
        data={"question": "What is in this image?"},
    )
    assert response.status_code == 200
    assert response.json() == {
        "model": "muse-spark-1.3",
        "status": "ok",
        "answer": SAMPLE_ANSWER,
    }
    assert seen["api_key"] == "test-key"
    assert seen["image_bytes"] == PNG_BYTES
    assert seen["media_type"] == "image/png"
    assert seen["question"] == "What is in this image?"
    assert "test-key" not in response.text


def test_ask_missing_question_field(client: TestClient, configured_key: None) -> None:
    response = client.post(
        "/api/ask",
        files={"image": ("test.png", PNG_BYTES, "image/png")},
    )
    assert response.status_code == 422


@pytest.mark.parametrize(
    ("question", "expected_status"),
    [
        # An empty value fails FastAPI's required-form validation.
        ("", 422),
        # Whitespace-only passes form parsing and hits our empty check.
        ("   ", 400),
    ],
)
def test_ask_empty_question(
    client: TestClient, configured_key: None, question: str, expected_status: int
) -> None:
    response = client.post(
        "/api/ask",
        files={"image": ("test.png", PNG_BYTES, "image/png")},
        data={"question": question},
    )
    assert response.status_code == expected_status
    if expected_status == 400:
        assert "must not be empty" in response.json()["detail"]


def test_ask_question_too_long(client: TestClient, configured_key: None) -> None:
    response = client.post(
        "/api/ask",
        files={"image": ("test.png", PNG_BYTES, "image/png")},
        data={"question": "x" * (MAX_QUESTION_CHARS + 1)},
    )
    assert response.status_code == 400
    assert "at most" in response.json()["detail"]


def test_ask_unsupported_media_type(client: TestClient, configured_key: None) -> None:
    response = client.post(
        "/api/ask",
        files={"image": ("test.txt", b"hello", "text/plain")},
        data={"question": "What is this?"},
    )
    assert response.status_code == 415
    assert "JPEG" in response.json()["detail"]


def test_ask_oversized_upload(client: TestClient, configured_key: None) -> None:
    response = client.post(
        "/api/ask",
        files={
            "image": (
                "big.png",
                b"\x89PNG" + b"\x00" * MAX_IMAGE_BYTES,
                "image/png",
            )
        },
        data={"question": "What is this?"},
    )
    assert response.status_code == 413


def test_ask_missing_api_key(client: TestClient, missing_key: None) -> None:
    response = client.post(
        "/api/ask",
        files={"image": ("test.png", PNG_BYTES, "image/png")},
        data={"question": "What is this?"},
    )
    assert response.status_code == 503
    assert "not configured" in response.json()["detail"]


def test_ask_upstream_failure_sanitized(
    client: TestClient, configured_key: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_ask(*args: Any, **kwargs: Any) -> str:
        raise MetaUpstreamError(502, "Question answering provider returned an error.")

    monkeypatch.setattr("app.main.ask_about_image", fake_ask)
    response = client.post(
        "/api/ask",
        files={"image": ("test.png", PNG_BYTES, "image/png")},
        data={"question": "What is this?"},
    )
    assert response.status_code == 502
    assert response.json() == {
        "detail": "Question answering provider returned an error."
    }
    assert "test-key" not in response.text


def test_ask_upstream_timeout(
    client: TestClient, configured_key: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_ask(*args: Any, **kwargs: Any) -> str:
        raise MetaUpstreamError(504, "Question answering request timed out.")

    monkeypatch.setattr("app.main.ask_about_image", fake_ask)
    response = client.post(
        "/api/ask",
        files={"image": ("test.png", PNG_BYTES, "image/png")},
        data={"question": "What is this?"},
    )
    assert response.status_code == 504


def test_ask_empty_file(client: TestClient, configured_key: None) -> None:
    response = client.post(
        "/api/ask",
        files={"image": ("empty.png", b"", "image/png")},
        data={"question": "What is this?"},
    )
    assert response.status_code == 400
    assert "empty" in response.json()["detail"]

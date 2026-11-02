import logging
from typing import Any

import pytest
from conftest import PNG_BYTES
from fastapi.testclient import TestClient

from app.imaging import ImageDecodeError, ImageTooLargeError
from app.meta_api import (
    MAX_IMAGE_BYTES,
    MAX_QUESTION_CHARS,
    LabelAnswer,
    LookPlan,
    MetaUpstreamError,
)
from app.pipeline import AssistResult


def _result(**overrides: Any) -> AssistResult:
    params: dict[str, Any] = {
        "answer_status": "answered",
        "answer": "The answer.",
        "evidence": "printed words",
        "source": "region",
        "fallback": False,
        "concept": "label",
        "concepts_tried": ["label"],
        "boxes": [
            {
                "x1": 10,
                "y1": 20,
                "x2": 100,
                "y2": 200,
                "w": 640,
                "h": 480,
                "c": 0.9,
            }
        ],
        "framing": [],
        "timings_ms": {"plan": 1, "locate": 2, "crop": 3, "read": 4, "total": 10},
    }
    params.update(overrides)
    return AssistResult(**params)


def test_assist_success(
    client: TestClient, configured_key: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: dict[str, Any] = {}

    async def fake_assist(**kwargs: Any) -> AssistResult:
        seen.update(kwargs)
        return _result()

    monkeypatch.setattr("app.main.run_assist", fake_assist)
    response = client.post(
        "/api/assist",
        files={"image": ("test.png", PNG_BYTES, "image/png")},
        data={"question": "  What is this?  ", "language": "fr", "preset": "read"},
    )
    assert response.status_code == 200
    assert response.json() == {
        "model": "muse-spark-1.3",
        "status": "ok",
        "answer_status": "answered",
        "answer": "The answer.",
        "evidence": "printed words",
        "source": "region",
        "fallback": False,
        "concept": "label",
        "concepts_tried": ["label"],
        "boxes": [
            {
                "x1": 10,
                "y1": 20,
                "x2": 100,
                "y2": 200,
                "w": 640,
                "h": 480,
                "c": 0.9,
            }
        ],
        "framing": [],
        "timings_ms": {"plan": 1, "locate": 2, "crop": 3, "read": 4, "total": 10},
    }
    assert seen["api_key"] == "test-key"
    assert seen["image_bytes"] == PNG_BYTES
    assert seen["question"] == "What is this?"
    assert seen["language"] == "fr"
    assert seen["preset"] == "read"
    assert "test-key" not in response.text


def test_assist_defaults(
    client: TestClient, configured_key: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: dict[str, Any] = {}

    async def fake_assist(**kwargs: Any) -> AssistResult:
        seen.update(kwargs)
        return _result()

    monkeypatch.setattr("app.main.run_assist", fake_assist)
    response = client.post(
        "/api/assist",
        files={"image": ("test.png", PNG_BYTES, "image/png")},
        data={"question": "What is this?"},
    )
    assert response.status_code == 200
    assert seen["language"] == "en"
    assert seen["preset"] is None


def test_assist_empty_values_use_defaults(
    client: TestClient, configured_key: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: dict[str, Any] = {}

    async def fake_assist(**kwargs: Any) -> AssistResult:
        seen.update(kwargs)
        return _result()

    monkeypatch.setattr("app.main.run_assist", fake_assist)
    response = client.post(
        "/api/assist",
        files={"image": ("test.png", PNG_BYTES, "image/png")},
        data={"question": "What is this?", "language": "", "preset": ""},
    )
    assert response.status_code == 200
    assert seen["language"] == "en"
    assert seen["preset"] is None


def test_assist_missing_question_field(
    client: TestClient, configured_key: None
) -> None:
    response = client.post(
        "/api/assist",
        files={"image": ("test.png", PNG_BYTES, "image/png")},
    )
    assert response.status_code == 422


def test_assist_missing_image(client: TestClient, configured_key: None) -> None:
    response = client.post("/api/assist", data={"question": "What is this?"})
    assert response.status_code == 422


def test_assist_empty_question(client: TestClient, configured_key: None) -> None:
    response = client.post(
        "/api/assist",
        files={"image": ("test.png", PNG_BYTES, "image/png")},
        data={"question": "   "},
    )
    assert response.status_code == 400
    assert "must not be empty" in response.json()["detail"]


def test_assist_question_too_long(client: TestClient, configured_key: None) -> None:
    response = client.post(
        "/api/assist",
        files={"image": ("test.png", PNG_BYTES, "image/png")},
        data={"question": "x" * (MAX_QUESTION_CHARS + 1)},
    )
    assert response.status_code == 400
    assert "at most" in response.json()["detail"]


@pytest.mark.parametrize("language", ["xx", "EN"])
def test_assist_bad_language(
    client: TestClient, configured_key: None, language: str
) -> None:
    response = client.post(
        "/api/assist",
        files={"image": ("test.png", PNG_BYTES, "image/png")},
        data={"question": "What is this?", "language": language},
    )
    assert response.status_code == 400
    assert "language" in response.json()["detail"].lower()


@pytest.mark.parametrize("preset", ["bogus"])
def test_assist_bad_preset(
    client: TestClient, configured_key: None, preset: str
) -> None:
    response = client.post(
        "/api/assist",
        files={"image": ("test.png", PNG_BYTES, "image/png")},
        data={"question": "What is this?", "preset": preset},
    )
    assert response.status_code == 400
    assert "preset" in response.json()["detail"].lower()


def test_assist_unsupported_media_type(
    client: TestClient, configured_key: None
) -> None:
    response = client.post(
        "/api/assist",
        files={"image": ("test.txt", b"hello", "text/plain")},
        data={"question": "What is this?"},
    )
    assert response.status_code == 415


def test_assist_oversized_upload(client: TestClient, configured_key: None) -> None:
    response = client.post(
        "/api/assist",
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


def test_assist_missing_api_key(client: TestClient, missing_key: None) -> None:
    response = client.post(
        "/api/assist",
        files={"image": ("test.png", PNG_BYTES, "image/png")},
        data={"question": "What is this?"},
    )
    assert response.status_code == 503
    assert "not configured" in response.json()["detail"]


def test_assist_upstream_failure_sanitized(
    client: TestClient, configured_key: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_assist(**kwargs: Any) -> AssistResult:
        raise MetaUpstreamError(504, "Question answering request timed out.")

    monkeypatch.setattr("app.main.run_assist", fake_assist)
    response = client.post(
        "/api/assist",
        files={"image": ("test.png", PNG_BYTES, "image/png")},
        data={"question": "What is this?"},
    )
    assert response.status_code == 504
    assert response.json() == {"detail": "Question answering request timed out."}
    assert "test-key" not in response.text


def test_assist_invalid_structured_json_is_502(
    client: TestClient, configured_key: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_assist(**kwargs: Any) -> AssistResult:
        raise MetaUpstreamError(
            502, "Question answering provider returned an unexpected response."
        )

    monkeypatch.setattr("app.main.run_assist", fake_assist)
    response = client.post(
        "/api/assist",
        files={"image": ("test.png", PNG_BYTES, "image/png")},
        data={"question": "What is this?"},
    )
    assert response.status_code == 502


def test_assist_image_too_large(
    client: TestClient, configured_key: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_assist(**kwargs: Any) -> AssistResult:
        raise ImageTooLargeError("Image dimensions are too large.")

    monkeypatch.setattr("app.main.run_assist", fake_assist)
    response = client.post(
        "/api/assist",
        files={"image": ("test.png", PNG_BYTES, "image/png")},
        data={"question": "What is this?"},
    )
    assert response.status_code == 413
    assert response.json() == {"detail": "Image dimensions are too large."}


def test_assist_image_undecodable(
    client: TestClient, configured_key: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_assist(**kwargs: Any) -> AssistResult:
        raise ImageDecodeError("Could not decode the image.")

    monkeypatch.setattr("app.main.run_assist", fake_assist)
    response = client.post(
        "/api/assist",
        files={"image": ("test.png", PNG_BYTES, "image/png")},
        data={"question": "What is this?"},
    )
    assert response.status_code == 415
    assert response.json() == {"detail": "Could not decode the image."}


def test_assist_timing_log_line(
    client: TestClient,
    configured_key: None,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    async def fake_plan(api_key: str, question: str, **kwargs: Any) -> LookPlan:
        return LookPlan(concepts=[], task="Say what it is.")

    async def fake_read(api_key: str, **kwargs: Any) -> LabelAnswer:
        return LabelAnswer(status="answered", answer="A thing.", evidence="")

    monkeypatch.setattr("app.pipeline.plan_question", fake_plan)
    monkeypatch.setattr("app.pipeline.read_label", fake_read)
    with caplog.at_level(logging.INFO, logger="app.pipeline"):
        response = client.post(
            "/api/assist",
            files={"image": ("test.png", PNG_BYTES, "image/png")},
            data={"question": "Supercalifragilistic?"},
        )
    assert response.status_code == 200
    records = [
        record
        for record in caplog.records
        if record.name == "app.pipeline" and record.levelno == logging.INFO
    ]
    assert len(records) == 1
    assert "Supercalifragilistic" not in records[0].getMessage()
    assert "test-key" not in caplog.text

import asyncio
import json
import logging
from typing import Any

import httpx
import pytest
from conftest import PNG_BYTES

from app.meta_api import (
    ASK_INSTRUCTIONS,
    ASK_MODEL_ID,
    MODEL_ID,
    MetaUpstreamError,
    _post_image_text,
    ask_about_image,
)


def _install_mock_transport(
    monkeypatch: pytest.MonkeyPatch,
    handler: Any,
) -> None:
    real_client = httpx.AsyncClient

    def factory(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
        return real_client(*args, transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr("app.meta_api.httpx.AsyncClient", factory)


def _raising_handler(exc: Exception) -> Any:
    def handler(request: httpx.Request) -> httpx.Response:
        raise exc

    return handler


def _fixed_handler(response: httpx.Response) -> Any:
    def handler(request: httpx.Request) -> httpx.Response:
        return response

    return handler


def _run_post(model: str = MODEL_ID, text: str = "object") -> str:
    return asyncio.run(
        _post_image_text("test-key", model, text, b"img", "image/png", "Segmentation")
    )


@pytest.mark.parametrize("model", [MODEL_ID, ASK_MODEL_ID])
def test_post_image_text_success(monkeypatch: pytest.MonkeyPatch, model: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer test-key"
        payload = json.loads(request.content)
        assert payload["model"] == model
        content = payload["input"][0]["content"]
        texts = [part["text"] for part in content if part["type"] == "input_text"]
        images = [
            part["image_url"] for part in content if part["type"] == "input_image"
        ]
        assert texts == ["the prompt"]
        assert len(images) == 1
        assert images[0].startswith("data:image/png;base64,")
        return httpx.Response(
            200,
            json={
                "output": [
                    {
                        "type": "message",
                        "content": [
                            {"type": "output_text", "text": "hello "},
                            {"type": "output_text", "text": "world"},
                        ],
                    }
                ]
            },
        )

    _install_mock_transport(monkeypatch, handler)
    assert _run_post(model=model, text="the prompt") == "hello world"


@pytest.mark.parametrize(
    ("status", "expected_status", "expected_message"),
    [
        (401, 503, "Segmentation service is misconfigured."),
        (403, 503, "Segmentation service is misconfigured."),
        (429, 503, "Segmentation is busy. Try again shortly."),
        (500, 502, "Segmentation provider returned an error."),
    ],
)
def test_post_image_text_status_mapping(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    status: int,
    expected_status: int,
    expected_message: str,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer test-key"
        return httpx.Response(status, json={"error": "upstream says no"})

    _install_mock_transport(monkeypatch, handler)
    with (
        caplog.at_level(logging.WARNING, logger="app.meta_api"),
        pytest.raises(MetaUpstreamError) as exc_info,
    ):
        _run_post()
    err = exc_info.value
    assert err.status_code == expected_status
    assert err.message == expected_message
    assert "test-key" not in err.message
    assert "Segmentation" in caplog.text
    assert str(status) in caplog.text
    assert "test-key" not in caplog.text


@pytest.mark.parametrize(
    ("make_handler", "expected_status", "expected_message"),
    [
        (
            lambda: _raising_handler(httpx.ConnectTimeout("timed out")),
            504,
            "Segmentation request timed out.",
        ),
        (
            lambda: _raising_handler(httpx.ReadTimeout("timed out")),
            504,
            "Segmentation request timed out.",
        ),
        (
            lambda: _raising_handler(httpx.ConnectError("refused")),
            502,
            "Segmentation provider is unreachable.",
        ),
        (
            lambda: _fixed_handler(
                httpx.Response(
                    200, content=b"not json", headers={"Content-Type": "text/plain"}
                )
            ),
            502,
            "Segmentation provider returned an unexpected response.",
        ),
        (
            lambda: _fixed_handler(httpx.Response(200, json={"output": []})),
            502,
            "Segmentation provider returned an unexpected response.",
        ),
    ],
)
def test_post_image_text_failure_logging(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    make_handler: Any,
    expected_status: int,
    expected_message: str,
) -> None:
    _install_mock_transport(monkeypatch, make_handler())
    with (
        caplog.at_level(logging.WARNING, logger="app.meta_api"),
        pytest.raises(MetaUpstreamError) as exc_info,
    ):
        _run_post()
    err = exc_info.value
    assert err.status_code == expected_status
    assert err.message == expected_message
    assert "test-key" not in err.message
    assert "Segmentation" in caplog.text
    assert "test-key" not in caplog.text


def test_ask_about_image_prepends_instructions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, Any] = {}

    async def fake_post(
        api_key: str,
        model: str,
        text: str,
        image_bytes: bytes,
        media_type: str,
        service: str,
        **kwargs: Any,
    ) -> str:
        seen["text"] = text
        return "an answer"

    monkeypatch.setattr("app.meta_api._post_image_text", fake_post)
    answer = asyncio.run(ask_about_image("k", PNG_BYTES, "image/png", "What is this?"))
    assert answer == "an answer"
    assert seen["text"].startswith(ASK_INSTRUCTIONS)
    assert seen["text"].endswith("What is this?")

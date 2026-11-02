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
    FRAMING_NOTES,
    LABEL_ANSWER_FORMAT,
    LOOK_PLAN_FORMAT,
    MODEL_ID,
    PLAN_INSTRUCTIONS,
    READ_INSTRUCTIONS,
    LookPlan,
    MetaUpstreamError,
    _post_image_text,
    ask_about_image,
    plan_question,
    read_label,
    segment_image,
    transcribe_audio,
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


def _ok_response(text: str = "hello") -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "output": [
                {
                    "type": "message",
                    "content": [{"type": "output_text", "text": text}],
                }
            ]
        },
    )


def test_segment_image_sends_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        seen["metadata"] = payload.get("metadata")
        seen["has_reasoning"] = "reasoning" in payload
        return _ok_response()

    _install_mock_transport(monkeypatch, handler)
    asyncio.run(segment_image("test-key", PNG_BYTES, "image/png", "label"))
    assert seen["metadata"] == {
        "include_confidence": "true",
        "mask_encoding": "one_bit",
    }
    assert seen["has_reasoning"] is False


def test_ask_about_image_sends_reasoning_effort(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        seen["reasoning"] = payload.get("reasoning")
        return _ok_response()

    _install_mock_transport(monkeypatch, handler)
    asyncio.run(ask_about_image("test-key", PNG_BYTES, "image/png", "What is this?"))
    assert seen["reasoning"] == {"effort": "low"}


def test_reasoning_effort_none_omits_field(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["has_reasoning"] = "reasoning" in json.loads(request.content)
        return _ok_response()

    monkeypatch.setattr("app.meta_api.MUSE_REASONING_EFFORT", None)
    _install_mock_transport(monkeypatch, handler)
    asyncio.run(ask_about_image("test-key", PNG_BYTES, "image/png", "What is this?"))
    assert seen["has_reasoning"] is False


def test_segment_image_forwards_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    async def fake_post(
        api_key: str,
        body: dict[str, Any],
        service: str,
        *,
        client: Any = None,
        timeout: float | None = None,
    ) -> str:
        seen["timeout"] = timeout
        return ""

    monkeypatch.setattr("app.meta_api._post_responses", fake_post)
    asyncio.run(segment_image("k", b"img", "image/png", "label", timeout=20))
    assert seen["timeout"] == 20


def test_plan_question_body(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return _ok_response('{"concepts": ["label"], "task": "Read it."}')

    _install_mock_transport(monkeypatch, handler)
    plan = asyncio.run(plan_question("test-key", "What is this?"))
    assert plan == LookPlan(concepts=["label"], task="Read it.")
    body = seen["body"]
    assert body["model"] == ASK_MODEL_ID
    assert body["instructions"] == PLAN_INSTRUCTIONS
    assert body["reasoning"] == {"effort": "low"}
    assert body["text"]["format"]["name"] == "look_plan"
    assert body["text"]["format"]["strict"] is True
    assert body["text"]["format"]["schema"]["required"] == ["concepts", "task"]
    assert body["input"][0]["content"] == [
        {"type": "input_text", "text": "Question: What is this?"}
    ]
    assert "test-key" not in json.dumps(body)


@pytest.mark.parametrize("output_text", ["nope", '{"concepts": 1}', '{"task": "x"}'])
def test_plan_question_bad_payload(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    output_text: str,
) -> None:
    _install_mock_transport(monkeypatch, _fixed_handler(_ok_response(output_text)))
    with (
        caplog.at_level(logging.WARNING, logger="app.meta_api"),
        pytest.raises(MetaUpstreamError) as exc_info,
    ):
        asyncio.run(plan_question("k", "q"))
    assert exc_info.value.status_code == 502
    assert (
        exc_info.value.message
        == "Question answering provider returned an unexpected response."
    )
    assert output_text not in caplog.text


def test_read_label_body_order(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return _ok_response('{"status": "answered", "answer": "A.", "evidence": "E."}')

    _install_mock_transport(monkeypatch, handler)
    answer = asyncio.run(
        read_label(
            "test-key",
            question="Q?",
            task="Read it.",
            language_name="Greek",
            framing_notes=["note one", "note two"],
            crops=[("label", b"crop1"), ("lid", b"crop2")],
            context_jpeg=b"context",
        )
    )
    assert answer.status == "answered"
    body = seen["body"]
    assert body["model"] == ASK_MODEL_ID
    assert body["instructions"] == READ_INSTRUCTIONS
    assert body["reasoning"] == {"effort": "low"}
    assert body["text"]["format"]["name"] == "label_answer"
    assert body["text"]["format"]["strict"] is True
    content = body["input"][0]["content"]
    kinds = [part["type"] for part in content]
    assert kinds == [
        "input_text",
        "input_text",
        "input_image",
        "input_text",
        "input_image",
        "input_text",
        "input_image",
    ]
    texts = [part.get("text") for part in content if part["type"] == "input_text"]
    assert texts[0] == (
        "Answer language: Greek\n"
        "Reading task: Read it.\n"
        "User question: Q?\n"
        "Framing notes: note one note two"
    )
    assert texts[1] == "Image 1: zoomed region (label)."
    assert texts[2] == "Image 2: zoomed region (lid)."
    assert texts[3] == "Image 3: whole photo, downscaled, for context."
    for part in content:
        if part["type"] == "input_image":
            assert part["image_url"].startswith("data:image/jpeg;base64,")
    assert "test-key" not in json.dumps(body)


def test_read_label_no_crops_whole_photo(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return _ok_response('{"status": "not_visible", "answer": "A.", "evidence": ""}')

    _install_mock_transport(monkeypatch, handler)
    answer = asyncio.run(
        read_label(
            "test-key",
            question="Q?",
            task="T.",
            language_name="English",
            framing_notes=[],
            crops=[],
            context_jpeg=b"ctx",
        )
    )
    assert answer.status == "not_visible"
    content = seen["body"]["input"][0]["content"]
    kinds = [part["type"] for part in content]
    assert kinds == ["input_text", "input_text", "input_image"]
    texts = [part.get("text") for part in content if part["type"] == "input_text"]
    assert texts[0].endswith("Framing notes: none")
    assert texts[1] == "Image 1: whole photo."


def test_read_label_crop_mode_no_context(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return _ok_response('{"status": "answered", "answer": "A.", "evidence": "E."}')

    _install_mock_transport(monkeypatch, handler)
    asyncio.run(
        read_label(
            "test-key",
            question="Q?",
            task="T.",
            language_name="English",
            framing_notes=[],
            crops=[("label", b"crop")],
            context_jpeg=None,
        )
    )
    content = seen["body"]["input"][0]["content"]
    kinds = [part["type"] for part in content]
    assert kinds == ["input_text", "input_text", "input_image"]


@pytest.mark.parametrize(
    "output_text", ["nope", '{"status": "bogus", "answer": "A", "evidence": "E"}']
)
def test_read_label_bad_payload(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    output_text: str,
) -> None:
    _install_mock_transport(monkeypatch, _fixed_handler(_ok_response(output_text)))
    with (
        caplog.at_level(logging.WARNING, logger="app.meta_api"),
        pytest.raises(MetaUpstreamError) as exc_info,
    ):
        asyncio.run(
            read_label(
                "k",
                question="Q?",
                task="T.",
                language_name="English",
                framing_notes=[],
                crops=[],
                context_jpeg=b"ctx",
            )
        )
    assert exc_info.value.status_code == 502
    assert (
        exc_info.value.message
        == "Question answering provider returned an unexpected response."
    )
    assert output_text not in caplog.text


def _assert_strict_schema(format: dict[str, Any]) -> None:
    assert format["type"] == "json_schema"
    assert format["strict"] is True

    def check(node: Any) -> None:
        if isinstance(node, dict):
            if node.get("type") == "object":
                assert node["additionalProperties"] is False
                assert set(node["required"]) == set(node["properties"])
            for value in node.values():
                check(value)
        elif isinstance(node, list):
            for value in node:
                check(value)

    check(format["schema"])


def test_structured_formats_are_strict_valid() -> None:
    _assert_strict_schema(LOOK_PLAN_FORMAT)
    _assert_strict_schema(LABEL_ANSWER_FORMAT)


def test_framing_notes_cover_all_codes() -> None:
    assert set(FRAMING_NOTES) == {
        "cut_off_left",
        "cut_off_right",
        "cut_off_top",
        "cut_off_bottom",
        "too_close",
        "too_small",
        "not_found",
    }


def test_transcribe_audio_request_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer test-key"
        assert request.headers["accept"] == "application/json"
        seen["content_type"] = request.headers["content-type"]
        seen["parts"] = request.content.count(b"Content-Disposition: form-data")
        body = request.content
        assert b'"model": "muse-voice-transcribe-1.0"' in body
        assert b'"mode": "PUSH_TO_TALK"' in body
        assert b'"audioEncoding": "WAV"' in body
        assert b'"languageBias": ["French"]' in body
        assert b'"keywords"' in body
        assert b'"gluten"' in body
        assert b'filename="question.wav"' in body
        assert b"FAKEWAVBYTES" in body
        return httpx.Response(
            200,
            json={
                "sessionId": "s",
                "transcript": "bonjour",
                "audioDurationMs": 500,
                "turns": [],
            },
        )

    _install_mock_transport(monkeypatch, handler)
    transcript = asyncio.run(transcribe_audio("test-key", b"FAKEWAVBYTES", "fr"))
    assert transcript == "bonjour"
    assert seen["content_type"].startswith("multipart/form-data")
    assert seen["parts"] == 2


@pytest.mark.parametrize(
    ("status", "expected_status", "expected_message"),
    [
        (401, 503, "Transcription service is misconfigured."),
        (429, 503, "Transcription is busy. Try again shortly."),
        (500, 502, "Transcription provider returned an error."),
    ],
)
def test_transcribe_audio_status_mapping(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    status: int,
    expected_status: int,
    expected_message: str,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json={"error": "upstream says no"})

    _install_mock_transport(monkeypatch, handler)
    with (
        caplog.at_level(logging.WARNING, logger="app.meta_api"),
        pytest.raises(MetaUpstreamError) as exc_info,
    ):
        asyncio.run(transcribe_audio("test-key", b"wav", "en"))
    err = exc_info.value
    assert err.status_code == expected_status
    assert err.message == expected_message
    assert "Transcription" in caplog.text
    assert "test-key" not in caplog.text


def test_transcribe_audio_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_mock_transport(
        monkeypatch, _raising_handler(httpx.ConnectTimeout("timed out"))
    )
    with pytest.raises(MetaUpstreamError) as exc_info:
        asyncio.run(transcribe_audio("test-key", b"wav", "en"))
    assert exc_info.value.status_code == 504
    assert exc_info.value.message == "Transcription request timed out."


@pytest.mark.parametrize(
    "payload",
    [{"sessionId": "s"}, {"transcript": 42}, ["x"]],
)
def test_transcribe_audio_bad_structure(
    monkeypatch: pytest.MonkeyPatch, payload: Any
) -> None:
    _install_mock_transport(
        monkeypatch, _fixed_handler(httpx.Response(200, json=payload))
    )
    with pytest.raises(MetaUpstreamError) as exc_info:
        asyncio.run(transcribe_audio("test-key", b"wav", "en"))
    assert exc_info.value.status_code == 502
    assert (
        exc_info.value.message
        == "Transcription provider returned an unexpected response."
    )


def test_transcribe_audio_bad_json(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_mock_transport(
        monkeypatch,
        _fixed_handler(
            httpx.Response(
                200, content=b"not json", headers={"Content-Type": "text/plain"}
            )
        ),
    )
    with pytest.raises(MetaUpstreamError) as exc_info:
        asyncio.run(transcribe_audio("test-key", b"wav", "en"))
    assert exc_info.value.status_code == 502

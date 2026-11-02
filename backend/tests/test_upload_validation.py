import asyncio
import json
from collections.abc import Generator, Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from httpx import Response
from starlette.types import Message, Receive, Scope, Send

from app.main import MAX_BODY_BYTES, BodySizeLimitMiddleware, app, get_settings
from app.settings import Settings

client = TestClient(app)

JPEG_BYTES = b"\xff\xd8\xff\xe0" + b"\x00" * 64
WEBP_BYTES = b"RIFF\x40\x00\x00\x00WEBPVP8 " + b"\x00" * 64
GARBAGE_BYTES = b"not-an-image-at-all"


@pytest.fixture()
def configured_key() -> Generator[None]:
    app.dependency_overrides[get_settings] = lambda: Settings(model_api_key="test-key")
    yield
    app.dependency_overrides.clear()


def _post_image(path: str, payload: bytes, media_type: str) -> Response:
    files = {"image": ("upload", payload, media_type)}
    if path == "/api/ask":
        return client.post(path, files=files, data={"question": "What is this?"})
    return client.post(path, files=files)


@pytest.mark.parametrize("path", ["/api/segment", "/api/ask"])
@pytest.mark.parametrize("payload", [JPEG_BYTES, GARBAGE_BYTES])
def test_spoofed_png_rejected(configured_key: None, path: str, payload: bytes) -> None:
    response = _post_image(path, payload, "image/png")
    assert response.status_code == 415
    assert "JPEG" in response.json()["detail"]


@pytest.mark.parametrize(
    ("media_type", "payload"),
    [("image/jpeg", JPEG_BYTES), ("image/webp", WEBP_BYTES)],
)
def test_segment_accepts_jpeg_and_webp(
    configured_key: None,
    monkeypatch: pytest.MonkeyPatch,
    media_type: str,
    payload: bytes,
) -> None:
    async def fake_segment(*args: Any, **kwargs: Any) -> str:
        return ""

    monkeypatch.setattr("app.main.segment_image", fake_segment)
    response = _post_image("/api/segment", payload, media_type)
    assert response.status_code == 200
    assert response.json()["boxes"] == []
    assert "test-key" not in response.text


@pytest.mark.parametrize(
    ("media_type", "payload"),
    [("image/jpeg", JPEG_BYTES), ("image/webp", WEBP_BYTES)],
)
def test_ask_accepts_jpeg_and_webp(
    configured_key: None,
    monkeypatch: pytest.MonkeyPatch,
    media_type: str,
    payload: bytes,
) -> None:
    async def fake_ask(*args: Any, **kwargs: Any) -> str:
        return "an answer"

    monkeypatch.setattr("app.main.ask_about_image", fake_ask)
    response = _post_image("/api/ask", payload, media_type)
    assert response.status_code == 200
    assert response.json()["answer"] == "an answer"
    assert "test-key" not in response.text


def test_body_cap_content_length() -> None:
    response = client.post(
        "/api/segment",
        content=b"0" * (MAX_BODY_BYTES + 1),
        headers={"Content-Type": "application/octet-stream"},
    )
    assert response.status_code == 413
    assert response.json() == {"detail": "Image exceeds the 5 MiB size limit."}


def test_body_cap_content_length_has_cors_header(client: TestClient) -> None:
    response = client.post(
        "/api/segment",
        content=b"0" * (MAX_BODY_BYTES + 1),
        headers={
            "Content-Type": "multipart/form-data; boundary=x",
            "Origin": "http://localhost:5173",
        },
    )
    assert response.status_code == 413
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"


def test_body_cap_chunked_real_app(client: TestClient) -> None:
    def body() -> Iterator[bytes]:  # a generator body has no Content-Length
        yield b"0" * (MAX_BODY_BYTES + 1)

    response = client.post(
        "/api/segment",
        content=body(),
        headers={
            "Content-Type": "multipart/form-data; boundary=x",
            "Origin": "http://localhost:5173",
        },
    )
    assert response.status_code == 413
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"


def _run_middleware(body: bytes) -> tuple[int, bytes, bool]:
    """Run the middleware with a chunked body and no Content-Length header."""
    downstream_called = False
    chunk_size = 1024 * 1024
    chunks = [body[i : i + chunk_size] for i in range(0, len(body), chunk_size)]
    messages: list[Message] = [
        {"type": "http.request", "body": c, "more_body": i < len(chunks) - 1}
        for i, c in enumerate(chunks)
    ]
    sent: list[Message] = []

    async def downstream(scope: Scope, receive: Receive, send: Send) -> None:
        nonlocal downstream_called
        downstream_called = True
        while True:
            message = await receive()
            assert message["type"] == "http.request"
            if not message.get("more_body", False):
                break
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [(b"content-type", b"application/json")],
            }
        )
        await send({"type": "http.response.body", "body": b"{}"})

    async def receive() -> Message:
        return messages.pop(0)

    async def send(message: Message) -> None:
        sent.append(message)

    scope: Scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/segment",
        "headers": [(b"content-type", b"multipart/form-data")],
    }
    asyncio.run(BodySizeLimitMiddleware(downstream)(scope, receive, send))
    status = next(m["status"] for m in sent if m["type"] == "http.response.start")
    payload = b"".join(
        m.get("body", b"") for m in sent if m["type"] == "http.response.body"
    )
    return status, payload, downstream_called


def test_body_cap_counts_streamed_bytes() -> None:
    status, payload, downstream_called = _run_middleware(b"0" * (MAX_BODY_BYTES + 1))
    assert downstream_called
    assert status == 413
    assert json.loads(payload) == {"detail": "Image exceeds the 5 MiB size limit."}


def test_small_streamed_body_passes_through() -> None:
    status, payload, downstream_called = _run_middleware(b"0" * 1024)
    assert downstream_called
    assert status == 200
    assert json.loads(payload) == {}

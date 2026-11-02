import io
import wave
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.meta_api import MAX_AUDIO_BYTES, MetaUpstreamError


def _wav_bytes(
    *,
    channels: int = 1,
    width: int = 2,
    rate: int = 16000,
    seconds: float = 1.0,
) -> bytes:
    buffer = io.BytesIO()
    frames = int(rate * seconds)
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(channels)
        wav.setsampwidth(width)
        wav.setframerate(rate)
        wav.writeframes(b"\x00" * frames * channels * width)
    return buffer.getvalue()


def _post_audio(
    client: TestClient,
    payload: bytes,
    media_type: str = "audio/wav",
    language: str = "en",
) -> Any:
    files = {"audio": ("question.wav", payload, media_type)}
    return client.post("/api/transcribe", files=files, data={"language": language})


@pytest.mark.parametrize("rate", [16000, 24000])
def test_transcribe_success(
    client: TestClient,
    configured_key: None,
    monkeypatch: pytest.MonkeyPatch,
    rate: int,
) -> None:
    seen: dict[str, Any] = {}

    async def fake_transcribe(
        api_key: str, wav_bytes: bytes, language: str, **kwargs: Any
    ) -> str:
        seen["api_key"] = api_key
        seen["wav_bytes"] = wav_bytes
        seen["language"] = language
        return "Does this contain gluten?"

    monkeypatch.setattr("app.main.transcribe_audio", fake_transcribe)
    payload = _wav_bytes(rate=rate)
    response = _post_audio(client, payload, language="en")
    assert response.status_code == 200
    assert response.json() == {
        "model": "muse-voice-transcribe-1.0",
        "status": "ok",
        "transcript": "Does this contain gluten?",
    }
    assert seen["api_key"] == "test-key"
    assert seen["wav_bytes"] == payload
    assert seen["language"] == "en"
    assert "test-key" not in response.text


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"channels": 2}, "mono"),
        ({"width": 1}, "16-bit"),
        ({"rate": 44100}, "16 kHz or 24 kHz"),
    ],
)
def test_transcribe_bad_format(
    client: TestClient,
    configured_key: None,
    kwargs: dict[str, Any],
    message: str,
) -> None:
    response = _post_audio(client, _wav_bytes(**kwargs))
    assert response.status_code == 400
    assert message in response.json()["detail"]


def test_transcribe_too_long(client: TestClient, configured_key: None) -> None:
    response = _post_audio(client, _wav_bytes(seconds=16.0))
    assert response.status_code == 400
    assert "too long" in response.json()["detail"]


def test_transcribe_empty_file(client: TestClient, configured_key: None) -> None:
    response = _post_audio(client, b"")
    assert response.status_code == 400
    assert "empty" in response.json()["detail"]


def test_transcribe_oversized_upload(client: TestClient, configured_key: None) -> None:
    response = _post_audio(client, b"\x00" * (MAX_AUDIO_BYTES + 1))
    assert response.status_code == 413


@pytest.mark.parametrize(
    ("payload", "media_type"),
    [
        (b"hello", "audio/mpeg"),
        (b"not-a-wav-file", "audio/wav"),
    ],
)
def test_transcribe_unsupported_audio(
    client: TestClient,
    configured_key: None,
    payload: bytes,
    media_type: str,
) -> None:
    response = _post_audio(client, payload, media_type)
    assert response.status_code == 415
    assert "WAV" in response.json()["detail"]


@pytest.mark.parametrize("language", ["el", "xx", "EN"])
def test_transcribe_bad_language(
    client: TestClient, configured_key: None, language: str
) -> None:
    response = _post_audio(client, _wav_bytes(), "audio/wav", language)
    assert response.status_code == 400
    assert "not available" in response.json()["detail"]


def test_transcribe_missing_audio_field(
    client: TestClient, configured_key: None
) -> None:
    response = client.post("/api/transcribe", data={"language": "en"})
    assert response.status_code == 422


def test_transcribe_missing_api_key(client: TestClient, missing_key: None) -> None:
    response = _post_audio(client, _wav_bytes())
    assert response.status_code == 503
    assert "not configured" in response.json()["detail"]


def test_transcribe_upstream_failure_sanitized(
    client: TestClient, configured_key: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_transcribe(*args: Any, **kwargs: Any) -> str:
        raise MetaUpstreamError(503, "Transcription is busy. Try again shortly.")

    monkeypatch.setattr("app.main.transcribe_audio", fake_transcribe)
    response = _post_audio(client, _wav_bytes())
    assert response.status_code == 503
    assert response.json() == {"detail": "Transcription is busy. Try again shortly."}
    assert "test-key" not in response.text

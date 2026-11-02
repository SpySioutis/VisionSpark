from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from httpx import Response

from app.main import reset_rate_limit_state
from app.settings import get_settings


@pytest.fixture()
def rate_limited(monkeypatch: pytest.MonkeyPatch) -> Generator[None]:
    monkeypatch.setenv("RATE_LIMIT_PER_MINUTE", "2")
    get_settings.cache_clear()
    reset_rate_limit_state()
    yield
    get_settings.cache_clear()
    reset_rate_limit_state()


def test_rate_limit_429_through_real_app(
    client: TestClient, configured_key: None, rate_limited: None
) -> None:
    def post_invalid() -> Response:
        return client.post(
            "/api/segment",
            files={"image": ("x.txt", b"hello", "text/plain")},
            headers={"Origin": "http://localhost:5173"},
        )

    # Only requests failing local validation: counted, but nothing upstream.
    assert post_invalid().status_code == 415
    assert post_invalid().status_code == 415
    limited = post_invalid()
    assert limited.status_code == 429
    assert limited.json() == {"detail": "Too many requests. Try again in a minute."}
    assert limited.headers["retry-after"] == "60"
    assert limited.headers["access-control-allow-origin"] == "http://localhost:5173"


def test_rate_limit_off_by_default(client: TestClient, configured_key: None) -> None:
    for _ in range(5):
        response = client.post(
            "/api/segment",
            files={"image": ("x.txt", b"hello", "text/plain")},
        )
        assert response.status_code == 415

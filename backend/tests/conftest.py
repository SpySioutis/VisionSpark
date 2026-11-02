from collections.abc import Generator
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from app.main import app, get_settings
from app.settings import Settings

PNG_BYTES = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
    b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


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


@pytest.fixture(autouse=True)
def _block_real_http(monkeypatch: pytest.MonkeyPatch) -> Generator[None]:
    """Fail loudly on any un-mocked upstream HTTP call from app code.

    Tests that install their own MockTransport keep working: the transport
    is only defaulted, never overridden.
    """
    real_client = httpx.AsyncClient

    def fail_handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"Un-mocked upstream HTTP call in test: {request.url}")

    def factory(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
        kwargs.setdefault("transport", httpx.MockTransport(fail_handler))
        return real_client(*args, **kwargs)

    monkeypatch.setattr("app.meta_api.httpx.AsyncClient", factory)
    yield

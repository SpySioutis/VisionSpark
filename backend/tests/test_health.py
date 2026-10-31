from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_cors_origins() -> None:
    response = client.get("/health", headers={"Origin": "http://127.0.0.1:5173"})
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://127.0.0.1:5173"
    evil = client.get("/health", headers={"Origin": "http://evil.example"})
    assert evil.status_code == 200
    assert "access-control-allow-origin" not in evil.headers

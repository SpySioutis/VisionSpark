from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.main import mount_frontend


def test_mount_frontend_serves_index_and_keeps_api(tmp_path: Path) -> None:
    (tmp_path / "index.html").write_text("<html>VisionSpark</html>")
    fresh = FastAPI()

    @fresh.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    assert mount_frontend(fresh, tmp_path) is True
    client = TestClient(fresh)
    assert client.get("/").text == "<html>VisionSpark</html>"
    assert client.get("/health").json() == {"status": "ok"}


def test_mount_frontend_missing_index(tmp_path: Path) -> None:
    fresh = FastAPI()
    assert mount_frontend(fresh, tmp_path) is False
    assert TestClient(fresh).get("/").status_code == 404

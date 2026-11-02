from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """Backend-only configuration.

    The Meta Model API key is read from the ``MODEL_API_KEY`` environment
    variable, optionally supplied via ``backend/.env`` for local development.
    That path is fixed to ``backend/.env`` regardless of the process working
    directory. The file is gitignored and must never be committed.
    """

    model_config = SettingsConfigDict(env_file=BACKEND_DIR / ".env", extra="ignore")

    model_api_key: str | None = None
    # Overridable via CORS_ORIGINS as a JSON list, e.g. '["http://localhost:5173"]'.
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]
    # Built frontend directory to serve at "/". Unset by default; the Docker
    # image and phone testing set FRONTEND_DIST to the Vite dist directory.
    frontend_dist: Path | None = None
    # Per-IP rate limit for POST /api/* per minute. 0 = off; suggest 30 for
    # public hosting.
    rate_limit_per_minute: int = 0


@lru_cache
def get_settings() -> Settings:
    return Settings()

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


@lru_cache
def get_settings() -> Settings:
    return Settings()

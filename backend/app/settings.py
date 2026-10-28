from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Backend-only configuration.

    The Meta Model API key is read from the ``MODEL_API_KEY`` environment
    variable, optionally supplied via ``backend/.env`` for local development.
    That file is gitignored and must never be committed.
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    model_api_key: str | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()

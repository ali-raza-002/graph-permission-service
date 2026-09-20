from __future__ import annotations

from functools import lru_cache

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="WORKSPACES_", env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    host: str = "127.0.0.1"
    port: int = 27106
    database_url: str = "postgresql+asyncpg://warden:warden@127.0.0.1:5506/warden"
    warden_url: str = "http://127.0.0.1:8106"
    warden_api_key: SecretStr
    warden_store_id: str = "st_workspaces_demo"
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3106"])
    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    return Settings()

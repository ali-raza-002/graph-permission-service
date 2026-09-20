from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="WARDEN_", env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    env: Literal["development", "test", "production"] = "development"
    host: str = "127.0.0.1"
    port: int = 8106
    log_level: str = "INFO"
    log_json: bool = False
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3106"])

    database_url: str = "postgresql+asyncpg://warden:warden@127.0.0.1:5506/warden"
    db_pool_size: int = Field(default=20, ge=1)
    db_max_overflow: int = Field(default=10, ge=0)
    db_echo: bool = False
    db_pool_timeout_seconds: float = Field(default=5.0, gt=0)
    max_concurrent_reads: int = Field(
        default=24,
        ge=1,
        description="Process-wide cap on concurrent snapshot queries. Keep it below "
        "db_pool_size + db_max_overflow so writes and auth lookups can still get a connection.",
    )

    cache_backend: Literal["memory", "redis", "none"] = "memory"
    redis_url: str = "redis://127.0.0.1:6406/0"
    cache_ttl_seconds: int = Field(default=300, ge=1)
    cache_max_entries: int = Field(default=200_000, ge=1)

    max_check_depth: int = Field(default=25, ge=1, le=100)
    revision_quantization_ms: int = Field(
        default=2000,
        ge=0,
        description="How long a store's latest revision may be reused for minimize_latency "
        "reads. Larger values raise cache hit rates at the cost of staleness.",
    )
    max_tuples_per_write: int = Field(default=500, ge=1)
    max_contextual_tuples: int = Field(default=100, ge=0)
    list_max_results: int = Field(default=1000, ge=1)
    max_batch_checks: int = Field(default=100, ge=1)
    list_max_candidates: int = Field(default=10_000, ge=1)
    query_deadline_ms: int = Field(default=10_000, ge=10)

    tuple_history_retention_hours: float = Field(
        default=24.0,
        gt=0,
        description="How long deleted tuples stay readable for snapshot reads. Older "
        "consistency tokens are rejected with snapshot_too_old.",
    )
    decision_retention_days: float = Field(default=30.0, gt=0)
    gc_interval_seconds: float = Field(default=600.0, gt=0)
    gc_enabled: bool = True

    decision_log: Literal["async", "sync", "off"] = "async"
    decision_trace_max_nodes: int = Field(default=400, ge=1)
    decision_flush_interval_ms: int = Field(default=500, ge=10)

    bootstrap_admin_key: SecretStr | None = None
    principal_cache_ttl_seconds: float = Field(default=30.0, ge=0)
    principal_cache_max_entries: int = Field(default=10_000, ge=1)

    @model_validator(mode="after")
    def _production_guards(self) -> Settings:
        if self.env != "production" or self.bootstrap_admin_key is None:
            return self
        key = self.bootstrap_admin_key.get_secret_value()
        if len(key) < 32 or "change-me" in key:
            raise ValueError(
                "WARDEN_BOOTSTRAP_ADMIN_KEY must be at least 32 characters and must not be a "
                "placeholder in production; generate one with `openssl rand -base64 32`"
            )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()

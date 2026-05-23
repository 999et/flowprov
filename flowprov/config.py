"""Centralised settings, loaded from environment / .env file."""
from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # DB
    database_url: str = Field(
        default="postgresql+asyncpg://flowprov:flowprov_dev_pw@localhost:5433/flowprov"
    )
    database_url_sync: str = Field(
        default="postgresql+psycopg2://flowprov:flowprov_dev_pw@localhost:5433/flowprov"
    )

    # API
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    log_level: str = "INFO"

    # Embeddings
    # "hash"   — dependency-free, default, deterministic (good for demo + CI)
    # "minilm" — sentence-transformers all-MiniLM-L6-v2 (requires .[ml] extra)
    embedding_provider: str = "hash"
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    embedding_dim: int = 384

    # LLM
    llm_provider: str = "fake"  # "fake" | "openai"
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"

    # Drift detection
    drift_hard_threshold: float = 0.40
    drift_soft_std_multiplier: float = 2.5
    drift_min_history: int = 5
    drift_knn: int = 10

    # Notifications
    slack_webhook_url: str = ""


@lru_cache
def get_settings() -> Settings:
    """Cached singleton so tests can monkey-patch the module-level instance."""
    return Settings()

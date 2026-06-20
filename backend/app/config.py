"""Centralised, type-safe configuration.

All secrets come from the environment (``.env`` locally, real env vars in
production). Nothing sensitive is ever hard-coded.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # Market data
    fmp_api_key: str = ""

    # AI providers
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    google_api_key: str = ""
    anthropic_model: str = "claude-opus-4-8"
    openai_model: str = "gpt-4o"
    gemini_model: str = "gemini-1.5-pro"

    # Security
    encryption_key: str = ""

    # App
    cors_origins: str = "http://localhost:3000"
    cache_ttl_seconds: int = 15
    log_level: str = "INFO"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def has_any_ai(self) -> bool:
        return bool(self.anthropic_api_key or self.openai_api_key or self.google_api_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()

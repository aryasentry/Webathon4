"""
UGIE Configuration
──────────────────
All settings are loaded from environment variables.
Never hard-code secrets — always use .env or your secrets manager.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Application ──────────────────────────────────────────────────────────
    environment: Literal["development", "staging", "production"] = "development"
    log_level: str = "INFO"
    api_title: str = "UGIE — Universal GitHub Intelligence Engine"
    api_version: str = "1.0.0"

    # ── Supabase ─────────────────────────────────────────────────────────────
    supabase_url: str = Field(..., description="Supabase project URL")
    supabase_anon_key: str = Field(..., description="Supabase anon/public key")
    supabase_service_role_key: str = Field(
        ..., description="Supabase service-role key (server-side only, never expose)"
    )

    # ── Redis ────────────────────────────────────────────────────────────────
    redis_url: str = Field(default="redis://localhost:6379/0")
    redis_event_queue: str = "ugie:events"
    redis_dlq: str = "ugie:dlq"
    redis_dedup_ttl: int = 86_400  # seconds — 24 h

    # ── GitHub OAuth ─────────────────────────────────────────────────────────
    github_client_id: str = Field(..., description="GitHub OAuth App client ID")
    github_client_secret: str = Field(..., description="GitHub OAuth App client secret")
    github_webhook_secret: str = Field(..., description="Secret used for HMAC webhook signatures")
    github_oauth_redirect_uri: str = "http://localhost:8000/auth/callback"
    github_oauth_scopes: str = "read:user,repo,read:org"
    frontend_url: str = Field(default="http://localhost:3000", description="Frontend redirect URL")

    # ── Token Vault ──────────────────────────────────────────────────────────
    token_encryption_key: str = Field(
        ...,
        description="32-byte URL-safe base64-encoded Fernet key. "
                    "Generate with: python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\"",
    )

    # ── JWT (session tokens) ─────────────────────────────────────────────────
    jwt_secret: str = Field(..., description="Secret for signing session JWTs")
    jwt_algorithm: str = "HS256"
    jwt_expiry_minutes: int = 60 * 24 * 7  # 7 days

    # ── Backfill ─────────────────────────────────────────────────────────────
    backfill_depth: int = 200  # default commit depth per repo
    backfill_max_concurrent: int = 5

    # ── CORS ─────────────────────────────────────────────────────────────────
    cors_origins: list[str] = ["http://localhost:3000", "http://localhost:5173"]

    # ── Computed ─────────────────────────────────────────────────────────────
    @computed_field  # type: ignore[misc]
    @property
    def is_production(self) -> bool:
        return self.environment == "production"


@lru_cache
def get_settings() -> Settings:
    """Return a cached singleton of Settings. Call this everywhere."""
    return Settings()  # type: ignore[call-arg]

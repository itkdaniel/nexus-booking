"""
Application configuration — reads from environment variables.
Uses pydantic-settings for type-safe, validated config with .env support.
"""
from __future__ import annotations

from functools import lru_cache
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # ── Service identity ──────────────────────────────────────────────────────
    app_name: str = "nexus-booking"
    version: str = "1.0.0"
    port: int = 8002
    debug: bool = False

    # ── Database ──────────────────────────────────────────────────────────────
    database_url: str = "postgresql+asyncpg://nexus:nexuspassword@localhost:5432/nexusbooking"

    # ── Email (aiosmtplib) ────────────────────────────────────────────────────
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_secure: bool = False
    smtp_user: str = ""
    smtp_password: str = ""
    from_name: str = "NexusConsult Booking"
    from_email: str = "noreply@nexusconsult.dev"
    admin_email: str = "admin@nexusconsult.dev"
    email_enabled: bool = False

    # ── Auth (HMAC JWT forwarded from main portfolio) ─────────────────────────
    jwt_secret: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"

    # ── Availability ──────────────────────────────────────────────────────────
    # Lookout window for slot index (business days)
    availability_window_days: int = 30
    # Session length in minutes
    session_length_minutes: int = 45

    # ── Portfolio gateway ─────────────────────────────────────────────────────
    portfolio_url: str = "http://localhost:5000"

    # ── CORS ──────────────────────────────────────────────────────────────────
    cors_origins: list[str] = ["*"]

    model_config = {"env_file": ".env", "case_sensitive": False, "extra": "ignore"}


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached singleton — created once, shared across all requests."""
    return Settings()

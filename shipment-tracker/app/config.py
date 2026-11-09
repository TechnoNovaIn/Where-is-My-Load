"""Runtime configuration, read from environment variables or a .env file."""
from __future__ import annotations

from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Balaji Transports upstream API (service account; never sent to browsers)
    upstream_base_url: str = "https://external.balajitransports.in"
    upstream_username: str
    upstream_password: str
    upstream_timeout_seconds: float = 30.0

    # Storage
    database_url: str = "sqlite+aiosqlite:///./data/tracker.db"

    # Party sessions
    session_secret: str = Field(min_length=32)
    session_ttl_hours: int = 12
    cookie_secure: bool = True
    cookie_name: str = "bt_session"

    # Background sync
    run_poller: bool = True
    location_poll_seconds: int = 60
    shipment_poll_seconds: int = 120
    lookback_days: int = 30
    straggler_limit: int = 50

    # WhatsApp alerts via upstream API
    whatsapp_enabled: bool = True

    # Tracking behaviour
    gps_stale_minutes: int = 30
    trail_min_move_meters: float = 75.0
    trail_retention_days: int = 30
    delivered_visible_days: int = 90

    # Ola Maps (https://maps.olakrutrim.com). The key stays on the server: the browser
    # loads tiles through /olamaps/... which adds it.
    ola_maps_api_key: str = ""
    ola_style_light: str = "default-light-standard"
    ola_style_dark: str = "default-dark-standard"

    # Database backup (SQLite online backup API, safe during writes)
    backup_enabled: bool = True
    backup_interval_hours: int = 6
    backup_keep: int = 5

    # Login throttling
    login_max_attempts: int = 8
    login_window_seconds: int = 900

    # API rate limiting (per IP, sliding window)
    api_rate_limit: int = 120
    api_rate_window_seconds: int = 60

    # CORS (empty = same-origin only; set to allow cross-origin consumers)
    cors_origins: list[str] = Field(default_factory=list)

    @field_validator("upstream_base_url")
    @classmethod
    def _strip_slash(cls, v: str) -> str:
        return v.rstrip("/")


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]

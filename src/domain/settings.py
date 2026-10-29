"""Settings shared by the API runtime and the UI runtime.

Fields here must be safe for the UI container, which holds no database driver,
no data-store credentials and no LLM provider key. Anything secret or
DB-adjacent belongs on ``ApiSettings`` in ``src/app/settings.py``, not here.
"""

from __future__ import annotations

from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class UISettings(BaseSettings):
    """The credential-free settings base.

    Every field here is safe to hand to the UI runtime: none is a database
    URL, a data-store credential or an LLM provider key. ``ApiSettings``
    extends this with the fields the API runtime alone may hold.
    """

    # ── External URL / reverse proxy ────────────────────────────────────
    # The URL the BROWSER uses to reach this application. nginx terminates
    # TLS and forwards plain HTTP to this container, so the app must never
    # derive its external scheme or host from its own listener. Anything
    # that needs an absolute, browser-facing URL (e.g. an OAuth redirect_uri
    # in Plan C) must build it from this value.
    EXTERNAL_BASE_URL: str = "https://localhost"

    # The URL the Dash code uses to call the API from INSIDE this container.
    # The Dash callbacks run in this same process and call the API over the
    # Docker network, so this stays plain HTTP even though the browser
    # speaks HTTPS. Deliberately NOT the same value as EXTERNAL_BASE_URL.
    API_BASE_URL: str = "http://localhost:8000"

    # ── Logging configuration ───────────────────────────────────────────
    LOG_LEVEL: str = "INFO"
    LOG_FORMAT: str = "JSON"
    ENABLE_FILE_LOGGING: bool = False
    LOG_DIR: str = "logs"
    LOG_SIGNAL_DUMPS: bool = False

    # ── HTTP request timeout configuration (in seconds) ─────────────────
    HTTP_REQUEST_TIMEOUT: int = 60

    # ── Graph UI configuration ──────────────────────────────────────────
    GRAPH_UI_MAX_NODES_TO_EXPAND: int = 20
    GRAPH_UI_MAX_NODE_LABEL_CHARS: int = 10

    # ── Connector UI configuration ──────────────────────────────────────
    # Number of milliseconds between scan status polls in the connector UI.
    # Also a ``RuntimeConfig`` field, so it is genuinely runtime-tunable.
    CONNECTOR_SCAN_POLL_INTERVAL: int = 5000

    # Max recent action rows to display in the connector UI
    RECENT_ACTIONS_LIMIT: int = Field(default=5, ge=1, le=50)

    # ── UI Configuration ────────────────────────────────────────────────
    TIMEZONE: str = Field(default="UTC", validation_alias=AliasChoices("TIMEZONE", "TZ"))
    UI_DATETIME_FORMAT: str = "%b %d, %Y %I:%M %p"
    UI_DATE_FORMAT: str = "%b %d, %Y"

    @field_validator("TIMEZONE")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError(f"Invalid timezone: {value}") from exc
        return value

    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
    )


__all__ = ["UISettings"]

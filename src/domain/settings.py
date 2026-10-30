"""Settings shared by the API runtime and the UI runtime.

Fields here must be safe for the UI container, which holds no database driver,
no data-store credentials and no LLM provider key. Anything secret or
DB-adjacent belongs on ``ApiSettings`` in ``src/app/settings.py``, not here.
"""

from __future__ import annotations

from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import AliasChoices, Field, field_validator, model_validator
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

    # ── Authentication (Keycloak / OIDC) ────────────────────────────────
    # The PUBLIC realm URL. This exact string must equal the `iss` claim of
    # every token: validation is an exact string match, so any scheme, host,
    # port, trailing-slash or case difference rejects every token. It is the
    # URL the BROWSER uses, not the URL the API container fetches from —
    # see KEYCLOAK_INTERNAL_URL.
    KEYCLOAK_ISSUER: str = "https://localhost/auth/realms/wba"

    # The realm URL the API container itself uses for discovery, the token
    # endpoint and JWKS. Inside a container `localhost` is the container
    # itself, so this must be the compose service name. Plain HTTP inside the
    # Docker network. Deliberately NOT the same value as KEYCLOAK_ISSUER.
    KEYCLOAK_INTERNAL_URL: str = "http://keycloak:8080/auth/realms/wba"

    KEYCLOAK_REALM: str = "wba"

    # `wba-web` — the confidential browser client used by the BFF.
    # The ID is not a secret and is safe on the UI runtime; the SECRET is not
    # here — it lives on `ApiSettings` in `src/app/settings.py`.
    KEYCLOAK_CLIENT_ID: str = "wba-web"

    # `wba-internal` — the service-account client used by producers and the
    # signal consumer (client-credentials grant). Plan 055 consumes these.
    # Same split as above: the ID is here, the SECRET is on `ApiSettings`.
    KEYCLOAK_SERVICE_CLIENT_ID: str = "wba-internal"

    # `Secure` flag on the session cookie. MUST be true wherever TLS
    # terminates (it does: nginx). Set false ONLY for a plain-HTTP local run.
    AUTH_COOKIE_SECURE: bool = True

    # Application-enforced session bounds. The auth_session row is the
    # authority; Keycloak's SSO timers are the outer bound. Runtime-tunable.
    AUTH_SESSION_IDLE_MINUTES: int = 60
    AUTH_SESSION_MAX_HOURS: int = 8

    # The public origin this deployment is served from (scheme + host, no
    # trailing slash). Used to build the OAuth redirect_uri and the realm
    # template's redirectUris/webOrigins.
    #
    # It MUST equal the origin of KEYCLOAK_ISSUER. They are two settings rather
    # than one because KEYCLOAK_ISSUER carries the /auth/realms/<realm> suffix
    # and must match the `iss` claim byte-for-byte, while this is the app origin.
    # A validator below enforces that they agree.
    APP_PUBLIC_BASE_URL: str = "https://localhost"

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

    @model_validator(mode="after")
    def _issuer_must_match_public_url(self) -> "UISettings":
        issuer = self.KEYCLOAK_ISSUER
        base = self.APP_PUBLIC_BASE_URL.rstrip("/")
        if not issuer.startswith(f"{base}/"):
            raise ValueError(
                f"KEYCLOAK_ISSUER ({issuer}) must start with "
                f"APP_PUBLIC_BASE_URL ({base}) + '/'. A mismatch means the "
                "realm's issuer and the app's public origin disagree, which "
                "makes every redirect and token validation fail."
            )
        return self

    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
    )


__all__ = ["UISettings"]

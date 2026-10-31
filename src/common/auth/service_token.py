"""Cached client-credentials access tokens for connector processes.

Producer daemons and the signal consumer call the app API over HTTP.  Once
bearer enforcement lands (plan 057) those calls need a service token.  This
module fetches one from Keycloak through the ``client_credentials`` grant and
keeps it in a process-wide cache, refreshing lazily when the cached token is
within the refresh margin of expiry.

Importing this module performs no I/O: the first token fetch happens on the
first :func:`get_service_token` call.
"""

from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass, field
from typing import Any

import requests

from common.logger import logger

_DEFAULT_REALM_URL = "http://keycloak:8080/auth/realms/wba"
_DEFAULT_CLIENT_ID = "wba-internal"
_REFRESH_MARGIN_SECONDS = 60
_FAILURE_BACKOFF_SECONDS = 30
_HTTP_TIMEOUT_SECONDS = 10


class ServiceTokenError(Exception):
    """A service token could not be obtained from Keycloak."""


@dataclass
class _TokenState:
    """Mutable process-wide token cache guarded by ``lock``."""

    access_token: str | None = None
    expires_at: float = 0.0
    lock: threading.Lock = field(default_factory=threading.Lock)


_state = _TokenState()


def _settings() -> tuple[str, str, str]:
    """Return ``(realm_base_url, client_id, client_secret)`` from the environment."""
    realm_base = os.environ.get("KEYCLOAK_INTERNAL_URL", _DEFAULT_REALM_URL).rstrip("/")
    client_id = os.environ.get("KEYCLOAK_SERVICE_CLIENT_ID", _DEFAULT_CLIENT_ID)
    client_secret = os.environ.get("KEYCLOAK_SERVICE_CLIENT_SECRET", "")
    return realm_base, client_id, client_secret


def _cached_token() -> str | None:
    """Return the cached token when it is still outside the refresh margin."""
    if _state.access_token is not None and time.monotonic() < _state.expires_at:
        return _state.access_token
    return None


def _in_failure_backoff() -> bool:
    """Return True while a recent fetch failure is still being backed off."""
    return _state.access_token is None and time.monotonic() < _state.expires_at


def _request_token(realm_base: str, client_id: str, client_secret: str) -> tuple[str, float]:
    """Request a fresh token and return ``(access_token, expires_at)``."""
    token_url = f"{realm_base}/protocol/openid-connect/token"
    try:
        resp = requests.post(
            token_url,
            data={
                "grant_type": "client_credentials",
                "client_id": client_id,
                "client_secret": client_secret,
            },
            timeout=_HTTP_TIMEOUT_SECONDS,
        )
    except requests.exceptions.RequestException as exc:
        raise ServiceTokenError(f"token endpoint request failed ({type(exc).__name__})") from exc

    if resp.status_code != 200:
        raise ServiceTokenError(f"token endpoint returned status {resp.status_code}")

    try:
        payload: Any = resp.json()
    except ValueError as exc:
        raise ServiceTokenError("token endpoint returned a non-JSON body") from exc

    if not isinstance(payload, dict) or not payload.get("access_token"):
        raise ServiceTokenError("token response did not contain an access_token")

    expires_in = payload.get("expires_in")
    if not isinstance(expires_in, (int, float)):
        raise ServiceTokenError("token response did not contain a numeric expires_in")

    return str(payload["access_token"]), time.monotonic() + float(expires_in) - _REFRESH_MARGIN_SECONDS


def get_service_token() -> str:
    """Return a cached, unexpired ``wba-internal`` access token.

    Raises:
        ServiceTokenError: when no secret is configured, the token endpoint
            fails, or a recent failure is still within its backoff window.
    """
    token = _cached_token()
    if token is not None:
        return token
    if _in_failure_backoff():
        raise ServiceTokenError("service token fetch failed recently; backing off")

    with _state.lock:
        token = _cached_token()
        if token is not None:
            return token
        if _in_failure_backoff():
            raise ServiceTokenError("service token fetch failed recently; backing off")

        realm_base, client_id, client_secret = _settings()
        if not client_secret:
            logger.warning(f"Service token unavailable: no client credential configured for client_id={client_id}")
            raise ServiceTokenError(f"KEYCLOAK_SERVICE_CLIENT_SECRET is not set for client_id={client_id}")

        try:
            token, expires_at = _request_token(realm_base, client_id, client_secret)
        except ServiceTokenError as exc:
            logger.warning(f"Failed to fetch service token for client_id={client_id}: {exc}")
            _state.access_token = None
            _state.expires_at = time.monotonic() + _FAILURE_BACKOFF_SECONDS
            raise

        _state.access_token = token
        _state.expires_at = expires_at
        return token


def invalidate_service_token() -> None:
    """Discard the cached token and failure backoff, so the next call re-fetches."""
    with _state.lock:
        _state.access_token = None
        _state.expires_at = 0.0

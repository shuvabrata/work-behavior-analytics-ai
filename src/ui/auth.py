"""The UI runtime's session-cookie helpers and per-worker token cache.

The browser holds one HttpOnly cookie (``wba_session``) and never a token. When
a Dash callback calls the API it needs a bearer, so this module exchanges the
cookie for one at ``POST /api/v1/auth/token`` and caches it **in this process
only**.

Three constraints shape the design:

* **The token lives in this module's dict and nowhere else** — not in a cookie,
  not in a Dash store, not on the page. That is the whole point of the BFF.
* **The cache is per worker.** gunicorn runs four ``gthread`` workers, so a user
  may hold up to four cached tokens for the same subject. That is fine and
  avoids introducing a shared store (the UI must not acquire a datastore).
* **This module must not import ``ui.api_client``.** ``api_client`` imports this
  module, so the reverse edge is an import cycle; the exchange is a bare
  ``requests`` call for that reason.
"""

from __future__ import annotations

import hashlib
import threading
import time
from typing import Any

import requests
from flask import request

from common.logger import logger
from ui.settings import settings

#: The cookie the browser carries. Set by the API, read here.
SESSION_COOKIE_NAME = "wba_session"

#: The API's BFF token-exchange endpoint.
_API_TOKEN_PATH = "/api/v1/auth/token"

#: The margin under which a cached token is treated as expired. The access token
#: lives 15 minutes; refreshing with 60 s to spare avoids racing the expiry.
_RENEW_MARGIN_SECONDS = 60

#: Token-endpoint timeout. A user is waiting on the callback that needs it.
_TIMEOUT_SECONDS = 10


class SessionMissingError(Exception):
    """There is no usable session — no cookie, or the API rejected the exchange."""


class TokenExchangeUnavailableError(Exception):
    """The API could not be reached, or Keycloak is down: retry, do not log out."""


#: ``{session_id_hash: (token, expires_at_monotonic)}``, guarded by ``_lock``.
_cache: dict[str, tuple[str, float]] = {}
_lock = threading.Lock()

#: The test seam: ``requests.post`` by default. Tests point this at a stub
#: rather than monkeypatching the global ``requests`` module, which every other
#: UI test would then see.
_post = requests.post


def current_session_id() -> str | None:
    """Return the ``wba_session`` cookie value, or ``None`` outside a request.

    Used by the session guard and the account bar — both want the raw id only to
    know whether a session exists, never to validate it (the API is the
    authority on that).
    """
    try:
        return request.cookies.get(SESSION_COOKIE_NAME)
    except RuntimeError:
        # No Flask request context (e.g. an import-time call in a test).
        return None


def _cache_key(raw: str) -> str:
    """Return a stable cache key for *raw*.

    The raw cookie id is not a secret, but it is not used as a dict key either:
    hashing keeps a stray traceback or ``repr`` from printing a usable value,
    and matches the hashing the API uses for the same id.
    """
    return hashlib.sha256(raw.encode()).hexdigest()


def _cached(key: str) -> str | None:
    """Return the cached token for *key* when it is still outside the margin."""
    with _lock:
        entry = _cache.get(key)
    if entry is None:
        return None
    token, expires_at = entry
    if time.monotonic() < expires_at:
        return token
    return None


def _store(key: str, token: str, expires_in: int) -> None:
    """Cache *token* for *key* with a monotonic expiry inside the renew margin."""
    expiry = time.monotonic() + max(expires_in - _RENEW_MARGIN_SECONDS, 0)
    with _lock:
        _cache[key] = (token, expiry)


def _exchange(raw: str) -> tuple[str, int]:
    """POST the session cookie to the API's token endpoint.

    A bare ``requests`` call, deliberately: routing this through
    :mod:`ui.api_client` would make that module call itself.

    Raises:
        SessionMissingError: 401 — the session is gone; the caller must log in.
        TokenExchangeUnavailableError: 503 or a transport failure — retryable.
    """
    url = settings.API_BASE_URL.rstrip("/") + _API_TOKEN_PATH
    try:
        response = _post(
            url,
            cookies={SESSION_COOKIE_NAME: raw},
            timeout=_TIMEOUT_SECONDS,
        )
    except requests.RequestException as exc:
        raise TokenExchangeUnavailableError(
            f"token exchange could not reach the API ({type(exc).__name__})"
        ) from exc

    if response.status_code == 401:
        raise SessionMissingError("the session is gone")
    if response.status_code != 200:
        raise TokenExchangeUnavailableError(
            f"token exchange returned status {response.status_code}"
        )

    try:
        payload: Any = response.json()
    except ValueError as exc:
        raise TokenExchangeUnavailableError("token exchange returned a non-JSON body") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("access_token"), str):
        raise TokenExchangeUnavailableError("token exchange returned no access_token")

    expires_in = payload.get("expires_in")
    if not isinstance(expires_in, int):
        expires_in = 0
    return payload["access_token"], expires_in


def get_token() -> str:
    """Return a bearer for the current request's session, caching per worker.

    Raises:
        SessionMissingError: No session cookie is present, or the API rejected
            the exchange with a 401.
        TokenExchangeUnavailableError: The API or Keycloak is unavailable.
    """
    raw = current_session_id()
    if not raw:
        raise SessionMissingError("no session cookie is present")

    key = _cache_key(raw)
    token = _cached(key)
    if token is not None:
        return token

    token, expires_in = _exchange(raw)
    _store(key, token, expires_in)
    logger.info(f"Exchanged session cookie for a bearer token (expires_in={expires_in}s)")
    return token


def invalidate_token() -> None:
    """Drop the current session's cached token so the next call re-exchanges.

    The one forced refresh a 401 is allowed to cause. Plan 058 is where a 401
    becomes a redirect; this only makes the retry possible.
    """
    raw = current_session_id()
    if not raw:
        return
    with _lock:
        _cache.pop(_cache_key(raw), None)


def clear_cache() -> None:
    """Drop every cached token. Test seam — never called on a request path."""
    with _lock:
        _cache.clear()


__all__ = [
    "SESSION_COOKIE_NAME",
    "SessionMissingError",
    "TokenExchangeUnavailableError",
    "clear_cache",
    "current_session_id",
    "get_token",
    "invalidate_token",
]

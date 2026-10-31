"""Session-cookie primitives for the BFF login flow.

Two cookies exist and they have opposite lifetimes:

* :data:`SESSION_COOKIE_NAME` (``wba_session``) — the opaque id the browser
  holds for the whole session. The API never stores this value; it stores the
  SHA-256 hex of it (:func:`hash_session_id`), so a database leak does not hand
  out usable session cookies.
* :data:`PKCE_COOKIE_NAME` (``wba_oidc``) — the login-in-progress cookie. It
  carries the ``state`` and the PKCE ``code_verifier`` between the redirect to
  Keycloak and the callback. Both are secrets, so the value is Fernet-encrypted
  rather than merely signed: the browser must not be able to read the verifier.

:func:`cookie_kwargs` derives every cookie attribute from settings in one place
so the API (which sets the cookie) and the UI (which only reads it) cannot
disagree about its scope. ``path="/"`` is required: the UI is mounted at
``/app`` and the auth endpoints live at ``/api``, so a narrower path would make
one side unable to see the cookie.
"""

from __future__ import annotations

import hashlib
import json
import secrets
from typing import Any

from app.common.encryption import decrypt, encrypt
from app.settings import settings

#: The cookie the browser holds for the session's lifetime. Its value is an
#: opaque random id; only its hash is ever persisted.
SESSION_COOKIE_NAME = "wba_session"

#: The short-lived cookie that carries the OIDC ``state`` and PKCE verifier
#: across the redirect to Keycloak and back.
PKCE_COOKIE_NAME = "wba_oidc"

#: Bytes of entropy in a session id. ``token_urlsafe`` encodes 3 bytes into 4
#: characters, so 32 bytes is a 43-character id with 256 bits behind it.
_SESSION_ID_BYTES = 32


def hash_session_id(raw: str) -> str:
    """Return the SHA-256 hex digest of *raw* — the value stored in the row."""
    return hashlib.sha256(raw.encode()).hexdigest()


def new_session_id() -> str:
    """Return a fresh opaque session id (never stored in the clear)."""
    return secrets.token_urlsafe(_SESSION_ID_BYTES)


def encode_pkce_cookie(state: str, verifier: str, next_path: str | None = None) -> str:
    """Encrypt the login-in-progress payload into one opaque cookie value.

    The verifier is a secret: whoever reads it can complete the authorization
    code exchange. Fernet encryption (keyed by ``CONNECTOR_ENCRYPTION_KEY``)
    keeps it unreadable to the browser while remaining tamper-evident.

    ``next_path`` is the page to return the user to after the callback. It rides
    in this cookie rather than the callback URL so it cannot be tampered with on
    the round trip through Keycloak; it is sanitised again on the way out.
    """
    payload: dict[str, str] = {"state": state, "verifier": verifier}
    if next_path is not None:
        payload["next"] = next_path
    return encrypt(json.dumps(payload))


def _decode_pkce_payload(value: str) -> dict[str, object]:
    """Decrypt *value* and return its JSON object, or raise ``ValueError``."""
    try:
        payload: Any = json.loads(decrypt(value))
    except ValueError as exc:
        raise ValueError("Invalid PKCE cookie") from exc
    if not isinstance(payload, dict):
        raise ValueError("Invalid PKCE cookie payload")
    return payload


def decode_pkce_cookie(value: str) -> tuple[str, str]:
    """Decrypt and parse a PKCE cookie value into ``(state, verifier)``.

    Raises:
        ValueError: The value is not a valid Fernet token, does not decrypt to
            JSON, or does not carry the expected ``state``/``verifier`` shape.
    """
    payload = _decode_pkce_payload(value)
    state = payload.get("state")
    verifier = payload.get("verifier")
    if not isinstance(state, str) or not isinstance(verifier, str):
        raise ValueError("Invalid PKCE cookie payload")
    return state, verifier


def decode_pkce_next(value: str) -> str | None:
    """Return the ``next`` path carried by a PKCE cookie, or ``None``."""
    payload = _decode_pkce_payload(value)
    next_path = payload.get("next")
    return next_path if isinstance(next_path, str) else None


def encrypt_refresh_token(raw: str) -> str:
    """Encrypt a Keycloak refresh token for storage in the session row."""
    return encrypt(raw)


def decrypt_refresh_token(stored: str) -> str:
    """Decrypt a stored refresh token.

    Raises:
        ValueError: The ciphertext is not a valid Fernet token for the current
            key — e.g. ``CONNECTOR_ENCRYPTION_KEY`` was rotated, which makes
            every existing session unrefreshable by design.
    """
    return decrypt(stored)


def cookie_kwargs() -> dict[str, object]:
    """Return the attribute set every auth cookie is set with.

    Derived from settings so the API and the UI cannot disagree. ``Secure``
    follows ``AUTH_COOKIE_SECURE`` (true wherever TLS terminates, which nginx
    does); ``SameSite=Lax`` blocks attachment on cross-site POSTs and is the
    CSRF control this design relies on.
    """
    return {
        "httponly": True,
        "secure": settings.AUTH_COOKIE_SECURE,
        "samesite": "Lax",
        "path": "/",
    }


__all__ = [
    "PKCE_COOKIE_NAME",
    "SESSION_COOKIE_NAME",
    "cookie_kwargs",
    "decode_pkce_cookie",
    "decode_pkce_next",
    "decrypt_refresh_token",
    "encode_pkce_cookie",
    "encrypt_refresh_token",
    "hash_session_id",
    "new_session_id",
]

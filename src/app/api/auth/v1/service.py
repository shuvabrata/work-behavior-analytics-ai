"""Business logic for the BFF login flow and the token exchange.

Four operations, in the order a user meets them:

1. :func:`start_login` — build the Keycloak authorize URL and the PKCE cookie.
2. :func:`complete_login` — exchange the authorization code, validate the
   resulting token, and create the ``auth_session`` row.
3. :func:`exchange_token` — the BFF mechanism: turn the session *cookie* into a
   fresh *bearer* on demand. This is the security core of the plan.
4. :func:`logout` — revoke the row and build the RP-initiated logout URL.

Two properties are load-bearing and easy to get wrong:

* **The access token is never stored.** Only the refresh token is persisted, and
  only in encrypted form. Step 3 of :func:`exchange_token` therefore always
  refreshes at Keycloak rather than trying to reuse a stored token.
* **Keycloak returns a rotated refresh token on every refresh.** Persisting it
  (:func:`app.api.auth.query.touch_session`) is what keeps a session alive past
  the first access-token lifetime; skipping it logs every user out at the first
  refresh.

No function here logs a token, refresh token, or client secret.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlencode, urlsplit

import requests

from app.api.auth.v1 import query as qry
from app.api.auth.v1.model import LoginRedirect, LoginResult, TokenResponse
from app.auth import tokens
from app.auth.session_cookie import (
    decode_pkce_cookie,
    decode_pkce_next,
    decrypt_refresh_token,
    encode_pkce_cookie,
    encrypt_refresh_token,
    hash_session_id,
    new_session_id,
)
from app.auth.tokens import TokenValidationError, validate_bearer_token
from app.settings import settings
from common.logger import logger

#: Where a login lands when the requested ``next`` is missing or unsafe.
DEFAULT_NEXT_PATH = "/app/graph"

#: Path Keycloak serves the authorization endpoint under, appended to the
#: public issuer URL. The browser goes here directly, so it must be public.
_AUTHORIZE_PATH = "/protocol/openid-connect/auth"

#: Path of the token endpoint, appended to the *internal* realm URL. The API
#: container calls this over the Docker network.
_TOKEN_PATH = "/protocol/openid-connect/token"

#: Path of the RP-initiated logout endpoint. Used only as a fallback when
#: discovery is unreachable — the discovered ``end_session_endpoint`` is
#: preferred because it is authoritative.
_LOGOUT_PATH = "/protocol/openid-connect/logout"

#: A short, fixed timeout for the token exchange: a user is waiting on it.
_TOKEN_TIMEOUT_SECONDS = 10


class LoginError(Exception):
    """The login could not be completed (bad state, missing code, or a refusal)."""


class SessionNotFoundError(Exception):
    """The session cookie was missing, unknown, or already revoked."""


class SessionExpiredError(Exception):
    """The session exceeded an application-enforced idle or maximum lifetime."""


class TokenExchangeUnavailableError(Exception):
    """Keycloak could not be reached; the session is preserved."""


# ── Helpers ──────────────────────────────────────────────────────────────


def _sanitize_next_path(next_path: str | None) -> str:
    """Return a safe in-app path from *next_path*, or the default.

    The open-redirect guard. Only a path under ``/app`` is accepted, and any
    value that could be reinterpreted by a browser as a different origin is
    rejected: a protocol-relative ``//host``, an absolute ``scheme://host``, a
    traversal ``..``, a backslash (which some proxies normalise to ``/``), and
    any embedded newline. Everything else falls back to
    :data:`DEFAULT_NEXT_PATH` rather than erroring — a bad ``next`` is not worth
    failing a login over.
    """
    candidate = (next_path or "").strip()
    if not candidate.startswith("/app"):
        return DEFAULT_NEXT_PATH
    if any(bad in candidate for bad in ("//", "\\", "\n", "\r", "..")):
        return DEFAULT_NEXT_PATH
    parsed = urlsplit(candidate)
    if parsed.scheme or parsed.netloc:
        return DEFAULT_NEXT_PATH
    return candidate


def _pkce_challenge(verifier: str) -> str:
    """Return the S256 challenge for *verifier* (unpadded base64url)."""
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def _redirect_uri() -> str:
    """Return the OAuth redirect URI, built from the public app origin.

    This must be byte-identical to the realm's ``redirectUris`` entry, which
    plan 053 templates from the same setting. Deriving it from the request's own
    host would work in dev and fail in production with a ``redirect_uri``
    mismatch.
    """
    return f"{settings.APP_PUBLIC_BASE_URL.rstrip('/')}/api/v1/auth/callback"


def _token_endpoint() -> str:
    """Return the internal Keycloak token endpoint URL."""
    return settings.KEYCLOAK_INTERNAL_URL.rstrip("/") + _TOKEN_PATH


def _post_token(data: dict[str, str]) -> requests.Response:
    """POST *data* to Keycloak's token endpoint.

    Raises:
        TokenExchangeUnavailableError: On a transport failure.
    """
    try:
        return requests.post(_token_endpoint(), data=data, timeout=_TOKEN_TIMEOUT_SECONDS)
    except requests.exceptions.RequestException as exc:
        raise TokenExchangeUnavailableError(
            f"Keycloak token endpoint unreachable ({type(exc).__name__})"
        ) from exc


def _parse_token_response(response: requests.Response) -> dict[str, Any]:
    """Return the token endpoint's JSON body, or raise on a non-200."""
    if response.status_code != 200:
        raise LoginError(f"token endpoint returned status {response.status_code}")
    try:
        payload: Any = response.json()
    except ValueError as exc:
        raise LoginError("token endpoint returned a non-JSON body") from exc
    if not isinstance(payload, dict):
        raise LoginError("token endpoint returned an unexpected body")
    return payload


# ── Login ────────────────────────────────────────────────────────────────


def start_login(next_path: str | None) -> LoginRedirect:
    """Begin a login: build the authorize URL and the PKCE cookie.

    ``state`` is the CSRF/response-integrity control, and PKCE binds the
    authorization code to a verifier the browser never sees in the clear — the
    verifier travels encrypted inside the PKCE cookie.
    """
    safe_next = _sanitize_next_path(next_path)
    state = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(64)

    params = {
        "client_id": settings.KEYCLOAK_CLIENT_ID,
        "redirect_uri": _redirect_uri(),
        "response_type": "code",
        "scope": "openid profile",
        "code_challenge": _pkce_challenge(verifier),
        "code_challenge_method": "S256",
        "state": state,
    }
    authorize_url = (
        settings.KEYCLOAK_ISSUER.rstrip("/") + _AUTHORIZE_PATH + "?" + urlencode(params)
    )
    return LoginRedirect(
        authorize_url=authorize_url,
        pkce_cookie_value=encode_pkce_cookie(state, verifier, safe_next),
        next_path=safe_next,
    )


async def complete_login(
    db: Any, *, code: str, state: str, pkce_cookie_value: str
) -> LoginResult:
    """Finish a login: verify state, exchange the code, create the session.

    Raises:
        LoginError: The PKCE cookie is invalid, the ``state`` does not match, or
            Keycloak refused the code.
        TokenExchangeUnavailableError: Keycloak's token endpoint is unreachable.
    """
    try:
        expected_state, verifier = decode_pkce_cookie(pkce_cookie_value)
        requested_next = decode_pkce_next(pkce_cookie_value)
    except ValueError as exc:
        raise LoginError("The login request has no valid state cookie.") from exc

    if not state or not secrets.compare_digest(expected_state, state):
        logger.warning("Login callback rejected: state mismatch")
        raise LoginError("The login state did not match the one this browser started.")

    response = _post_token(
        {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": _redirect_uri(),
            "client_id": settings.KEYCLOAK_CLIENT_ID,
            "client_secret": settings.KEYCLOAK_CLIENT_SECRET,
            "code_verifier": verifier,
        }
    )
    payload = _parse_token_response(response)

    access_token = payload.get("access_token")
    refresh_token = payload.get("refresh_token")
    if not isinstance(access_token, str) or not isinstance(refresh_token, str):
        raise LoginError("token endpoint did not return an access and refresh token")

    try:
        principal = validate_bearer_token(access_token)
    except TokenValidationError as exc:
        logger.error(f"Login token failed validation: {exc}")
        raise LoginError("The token Keycloak returned could not be validated.") from exc

    # ``state`` is validated and single-use: the cookie is cleared by the router.
    expires_at = datetime.now(timezone.utc) + timedelta(
        hours=settings.AUTH_SESSION_MAX_HOURS
    )
    session_id = new_session_id()
    await qry.create_session(
        db,
        session_id_hash=hash_session_id(session_id),
        subject=principal.subject,
        username=principal.username,
        roles=sorted(principal.roles),
        refresh_token_encrypted=encrypt_refresh_token(refresh_token),
        expires_at=expires_at,
    )
    await db.commit()
    await _purge_opportunistically(db)
    logger.info(
        f"Session created for sub={principal.subject!r} "
        f"username={principal.username!r}"
    )
    return LoginResult(
        session_id=session_id, next_path=_sanitize_next_path(requested_next)
    )


async def _purge_opportunistically(db: Any) -> None:
    """Delete long-ended session rows, never letting a failure break login."""
    try:
        removed = await qry.purge_expired(db, now=datetime.now(timezone.utc))
        if removed:
            await db.commit()
            logger.info(f"Purged {removed} ended auth session row(s)")
    except Exception:  # pylint: disable=broad-except
        logger.warning("Opportunistic auth-session purge failed", exc_info=True)


# ── Token exchange (the BFF) ─────────────────────────────────────────────


def _session_expired(row: Any, now: datetime) -> SessionExpiredError | None:
    """Return the expiry reason for *row*, or ``None`` when it is still valid."""
    if now > row.expires_at:
        return SessionExpiredError("session exceeded its maximum lifetime")
    idle_limit = timedelta(minutes=settings.AUTH_SESSION_IDLE_MINUTES)
    if now - row.last_seen_at > idle_limit:
        return SessionExpiredError("session exceeded its idle lifetime")
    return None


async def exchange_token(db: Any, *, session_id: str | None) -> TokenResponse:
    """Turn the session cookie into a fresh bearer for one UI call cycle.

    Raises:
        SessionNotFoundError: No cookie, no row, or the row is revoked.
        SessionExpiredError: The row exceeded an application-enforced lifetime.
        TokenExchangeUnavailableError: Keycloak was unreachable — the row is
            left intact so a Keycloak restart does not destroy sessions.
    """
    if not session_id:
        raise SessionNotFoundError("No session cookie was presented.")

    row = await qry.get_active_session(db, hash_session_id(session_id))
    if row is None:
        raise SessionNotFoundError("The session is unknown or was revoked.")

    now = datetime.now(timezone.utc)
    expired = _session_expired(row, now)
    if expired is not None:
        await qry.revoke_session(db, row, revoked_at=now)
        await db.commit()
        logger.info(f"Revoked {expired} for sub={row.subject!r}")
        raise expired

    refresh_token = decrypt_refresh_token(row.refresh_token_encrypted)
    response = _post_token(
        {
            "grant_type": "refresh_token",
            "client_id": settings.KEYCLOAK_CLIENT_ID,
            "client_secret": settings.KEYCLOAK_CLIENT_SECRET,
            "refresh_token": refresh_token,
        }
    )

    if response.status_code == 400:
        # Keycloak refused the grant: the user's SSO session ended. This is the
        # one case where the session row is destroyed.
        await qry.revoke_session(db, row, revoked_at=now)
        await db.commit()
        logger.info(f"Session revoked after Keycloak refused the refresh grant for sub={row.subject!r}")
        raise SessionNotFoundError("Keycloak refused the refresh grant.")

    if response.status_code >= 500:
        # A Keycloak-side fault, not the user's: preserve the session.
        logger.warning(
            f"Keycloak token endpoint returned {response.status_code} on refresh; session preserved"
        )
        raise TokenExchangeUnavailableError("Keycloak is unavailable.")

    payload = _parse_token_response(response)

    access_token = payload.get("access_token")
    new_refresh_token = payload.get("refresh_token")
    if not isinstance(access_token, str):
        raise TokenExchangeUnavailableError("Keycloak returned no access token.")
    if not isinstance(new_refresh_token, str):
        # Rotation is a documented Keycloak behaviour; if it stops happening the
        # design assumption changed and reuse of the old token is unknown.
        raise TokenExchangeUnavailableError("Keycloak did not rotate the refresh token.")

    try:
        principal = validate_bearer_token(access_token)
    except TokenValidationError as exc:
        # Our own configuration mismatch, not an expired user session: keep the
        # row so a fix (JWKS, audience) does not force every user to log in.
        logger.error(f"Refreshed token failed validation; session preserved: {exc}")
        raise TokenExchangeUnavailableError("Refreshed token failed validation.") from exc

    row.roles = sorted(principal.roles)
    await qry.touch_session(
        db,
        row,
        last_seen_at=now,
        refresh_token_encrypted=encrypt_refresh_token(new_refresh_token),
    )
    await db.commit()

    expires_in = payload.get("expires_in")
    return TokenResponse(
        access_token=access_token,
        expires_in=int(expires_in) if isinstance(expires_in, (int, float)) else 0,
    )


# ── Logout ───────────────────────────────────────────────────────────────


def _end_session_endpoint() -> str:
    """Return Keycloak's end-session URL, from discovery when reachable.

    Discovery is authoritative but is a network call; an unreachable Keycloak
    must not leave the local row unrevoked, so the caller has already revoked by
    the time this runs and a constructed fallback is acceptable here.
    """
    try:
        # ``app.auth.tokens`` owns the discovery document and its issuer check;
        # reimplementing the fetch here would be a second source of truth.
        # pylint: disable=protected-access
        discovery = tokens._fetch_discovery()  # noqa: SLF001
        endpoint = discovery.get("end_session_endpoint")
        if isinstance(endpoint, str) and endpoint:
            return endpoint
    except Exception:  # pylint: disable=broad-except
        logger.warning("Keycloak discovery unavailable for logout; using the constructed URL")

    return settings.KEYCLOAK_ISSUER.rstrip("/") + _LOGOUT_PATH


async def logout(db: Any, *, session_id: str | None) -> str:
    """Revoke the session row and return the RP-initiated logout URL."""
    if session_id:
        row = await qry.get_active_session(db, hash_session_id(session_id))
        if row is not None:
            await qry.revoke_session(db, row, revoked_at=datetime.now(timezone.utc))
            await db.commit()
            logger.info(f"Session revoked on logout for sub={row.subject!r}")

    params = {
        # No id_token is retained by design, so the client id is the fallback
        # hint Keycloak accepts.
        "client_id": settings.KEYCLOAK_CLIENT_ID,
        "post_logout_redirect_uri": f"{settings.APP_PUBLIC_BASE_URL.rstrip('/')}/app",
    }
    return f"{_end_session_endpoint()}?{urlencode(params)}"


__all__ = [
    "DEFAULT_NEXT_PATH",
    "LoginError",
    "SessionExpiredError",
    "SessionNotFoundError",
    "TokenExchangeUnavailableError",
    "complete_login",
    "exchange_token",
    "logout",
    "start_login",
]

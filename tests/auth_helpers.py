"""Real bearer tokens for the ``server``-marked integration suites.

Every ``/api/v1`` router requires a bearer, so a test that drives the
containerised app over ``https://localhost`` needs a genuine one.  The autouse
``_admin_principal_by_default`` override in ``tests/conftest.py`` cannot help
those tests: it works by installing a FastAPI dependency override in *this*
process, and a request through nginx is answered by the ``api`` container
instead.

The realm's ``wba-web`` client refuses direct access grants by design — it is a
BFF client — so the only supported way to obtain a bearer is the path the
browser takes: the OIDC authorization-code flow with PKCE, then the BFF's own
``POST /api/v1/auth/token`` exchange.  Service-role calls use the
``wba-internal`` client's client-credentials grant.

Credentials come from the environment, falling back to ``.env`` — never
hard-coded.

Usage::

    from tests.auth_helpers import admin_headers, service_headers

    async with httpx.AsyncClient(base_url=BASE_URL, headers=admin_headers()) as c:
        ...
"""

from __future__ import annotations

import base64
import json
import os
import threading
import time
from pathlib import Path
from typing import Any

import httpx
from dotenv import dotenv_values

from common.auth import Credentials, resolve_ca_bundle
from common.auth import credentials as _shared_credentials
from common.auth import login as _shared_login

BASE_URL = "https://localhost"
REALM_URL = f"{BASE_URL}/auth/realms/wba"

#: Host component of :data:`BASE_URL`.  A bearer belongs only on this origin, so
#: request patching can refuse to attach it anywhere else.
BASE_URL_HOST = httpx.URL(BASE_URL).host

#: The cookie the Dash UI guards on; a page test needs it rather than a bearer.
SESSION_COOKIE_NAME = "wba_session"
_TIMEOUT = 20.0
_REFRESH_MARGIN_SECONDS = 60

_ENV_FILE = Path(__file__).resolve().parents[1] / ".env"

#: role -> (realm username, env var holding that user's password)
_PASSWORD_ROLES: dict[str, tuple[str, str]] = {
    "admin": ("dev-admin", "DEV_WBA_ADMIN_PASSWORD"),
    "user": ("dev-user", "DEV_WBA_USER_PASSWORD"),
}


_cache: dict[str, Credentials] = {}
_cache_lock = threading.Lock()


def env_value(name: str, default: str = "") -> str:
    """Return *name* from the process environment, else from ``.env``."""
    value = os.environ.get(name)
    if value:
        return value
    if _ENV_FILE.is_file():
        return str(dotenv_values(_ENV_FILE).get(name) or default)
    return default


def _absolute(location: str) -> str:
    """Return *location* as an absolute URL, resolving a root-relative one."""
    from common.auth import absolute

    return absolute(location, BASE_URL)


def _parse_login_form(html: str) -> tuple[str, dict[str, str]]:
    """Return ``(action_url, fields)`` from Keycloak's login page."""
    from common.auth import parse_login_form

    return parse_login_form(html)


def credentials(role: str = "admin") -> Credentials:
    """Return live credentials for *role* (``admin``, ``user`` or ``service``).

    Tokens are cached process-wide and refreshed once they fall inside the
    refresh margin, so a long suite does not fail at the 15-minute token
    lifespan.
    """
    with _cache_lock:
        cached = _cache.get(role)
        if cached is not None and time.monotonic() < cached.expires_at - _REFRESH_MARGIN_SECONDS:
            return cached

    if role in _PASSWORD_ROLES:
        username, password_var = _PASSWORD_ROLES[role]
        password = env_value(password_var)
        if not password:
            raise AssertionError(
                f"{password_var} is unset — the {role} role cannot be minted. "
                f"Populate .env from .env.example before running this suite."
            )
        result = _shared_login(
            username, password, base_url=BASE_URL, ca_bundle=resolve_ca_bundle()
        )
    elif role == "service":
        result = _shared_credentials("service", base_url=BASE_URL, ca_bundle=resolve_ca_bundle())
    else:
        raise ValueError(f"Unknown role {role!r}; expected admin, user or service")

    with _cache_lock:
        _cache[role] = result
    return result


def bearer(role: str = "admin") -> str:
    """Return a live bearer for *role*."""
    return credentials(role).access_token


def service_token_env() -> dict[str, str]:
    """Return the environment application code needs to mint a service token.

    Producer/consumer code calls :func:`common.auth.service_token.get_service_token`,
    which reads these from the environment and defaults to the Docker-internal
    Keycloak host.  A host-run test cannot resolve that host, so the values here
    point the helper at the public origin instead and keep the real
    client-credentials path exercised.
    """
    return {
        "KEYCLOAK_INTERNAL_URL": REALM_URL,
        "KEYCLOAK_SERVICE_CLIENT_ID": env_value("KEYCLOAK_SERVICE_CLIENT_ID", "wba-internal"),
        "KEYCLOAK_SERVICE_CLIENT_SECRET": env_value("KEYCLOAK_SERVICE_CLIENT_SECRET"),
    }


def session_cookies(role: str = "admin") -> dict[str, str]:
    """Return the ``wba_session`` cookie a browser would hold for *role*.

    The Dash UI guards on the cookie rather than a bearer, so a test that
    requests an ``/app`` page needs this instead of :func:`headers`.
    """
    session_id = credentials(role).session_id
    if not session_id:
        raise AssertionError(
            f"The {role!r} role authenticates with a client-credentials grant and "
            f"has no {SESSION_COOKIE_NAME} cookie"
        )
    return {SESSION_COOKIE_NAME: session_id}


def headers(role: str = "admin") -> dict[str, str]:
    """Return ``Authorization`` headers for *role*."""
    return {"Authorization": f"Bearer {bearer(role)}"}


def subject(role: str = "admin") -> str:
    """Return the Keycloak ``sub`` claim carried by *role*'s bearer.

    The dev users' subjects are random UUIDs assigned by Keycloak at realm
    import, so they cannot be hard-coded.  ``dev-admin`` / ``dev-user`` are
    usernames, not subjects.  The signature is not verified — the token was
    just minted by the live realm, and this is a test helper reading its own
    claim.
    """
    token = bearer(role)
    payload = token.split(".")[1]
    padding = "=" * (-len(payload) % 4)
    claims: dict[str, Any] = json.loads(base64.urlsafe_b64decode(payload + padding))
    sub = claims.get("sub")
    if not isinstance(sub, str) or not sub:
        raise AssertionError(f"The {role!r} bearer carried no 'sub' claim")
    return sub


def admin_headers() -> dict[str, str]:
    """Return ``Authorization`` headers carrying ``wba-admin``."""
    return headers("admin")


def user_headers() -> dict[str, str]:
    """Return ``Authorization`` headers carrying ``wba-user`` only."""
    return headers("user")


def service_headers() -> dict[str, str]:
    """Return ``Authorization`` headers carrying ``wba-service``."""
    return headers("service")

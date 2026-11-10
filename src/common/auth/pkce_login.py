"""Interactive login against the running WBA stack, for operator tooling.

The realm's ``wba-web`` client refuses direct access grants by design — it is a
BFF client — so the only supported way to obtain a bearer is the path the
browser takes: the OIDC authorization-code flow with PKCE, then the BFF's own
``POST /api/v1/auth/token`` exchange.  Service-role callers use the
``wba-internal`` client's client-credentials grant instead.

``httpx`` is used rather than ``requests`` because the flow runs against
``https://localhost``, whose certificate is signed by the local mkcert CA;
``httpx`` honours ``SSL_CERT_FILE`` (or an explicit ``ca_bundle``) while
``requests`` consults only ``REQUESTS_CA_BUNDLE`` / ``CURL_CA_BUNDLE``.

``httpx`` and ``dotenv`` are imported lazily inside the functions that use them.
This module is copied into every service image by ``COPY src/common/``, and only
``requirements.api.txt`` and ``requirements.ui.txt`` install ``python-dotenv`` —
no connector image does.  Importing this module therefore performs no I/O and
pulls in no HTTP client or ``.env`` parser.

Credentials come from the environment, falling back to ``.env`` — never
hard-coded.
"""

from __future__ import annotations

import html as html_module
import os
import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import httpx

_TOKEN_PATH = "/protocol/openid-connect/token"
_TIMEOUT_SECONDS = 20.0
_REFRESH_MARGIN_SECONDS = 60
_MAX_REDIRECTS = 10

_ENV_FILE = Path(__file__).resolve().parents[3] / ".env"

#: role -> (realm username, env var holding that user's password)
_PASSWORD_ROLES: dict[str, tuple[str, str]] = {
    "admin": ("dev-admin", "DEV_WBA_ADMIN_PASSWORD"),
    "user": ("dev-user", "DEV_WBA_USER_PASSWORD"),
}

_HIDDEN_INPUT_RE = re.compile(r'<input[^>]*\btype="hidden"[^>]*>', re.IGNORECASE)
_NAME_RE = re.compile(r'\bname="([^"]+)"')
_VALUE_RE = re.compile(r'\bvalue="([^"]*)"')
_FORM_RE = re.compile(r"<form[^>]*>", re.IGNORECASE)
_ACTION_RE = re.compile(r'\baction="([^"]+)"')


class LoginError(Exception):
    """The interactive login flow did not complete."""


@dataclass(frozen=True)
class Credentials:
    """A live login: the bearer, the session cookie, and when the bearer expires."""

    access_token: str
    session_id: str
    expires_at: float


def env_value(name: str, default: str = "") -> str:
    """Return *name* from the process environment, else from ``.env``."""
    value = os.environ.get(name)
    if value:
        return value
    if _ENV_FILE.is_file():
        from dotenv import dotenv_values  # noqa: PLC0415  # pylint: disable=import-outside-toplevel

        return str(dotenv_values(_ENV_FILE).get(name) or default)
    return default


def absolute(location: str, base_url: str) -> str:
    """Return *location* as an absolute URL, resolving a root-relative one."""
    if location.startswith("/"):
        return base_url + location
    return location


def parse_login_form(html: str) -> tuple[str, dict[str, str]]:
    """Return ``(action_url, fields)`` from Keycloak's login page.

    Real HTML scraping is deliberate: it proves the exact form the browser
    posts is the one the caller posts, so a Keycloak theme change surfaces here
    rather than as a mysterious 400.
    """
    form_tag = _FORM_RE.search(html)
    if form_tag is None:
        raise LoginError("Keycloak login page carried no <form> element")
    action = _ACTION_RE.search(form_tag.group(0))
    if action is None:
        raise LoginError("Keycloak login form carried no action attribute")

    fields: dict[str, str] = {}
    for tag in _HIDDEN_INPUT_RE.findall(html):
        name = _NAME_RE.search(tag)
        value = _VALUE_RE.search(tag)
        if name is not None:
            fields[name.group(1)] = html_module.unescape(value.group(1)) if value is not None else ""
    return html_module.unescape(action.group(1)), fields


def resolve_ca_bundle() -> str | None:
    """Locate mkcert's local CA certificate, or return ``None`` if absent.

    Checked in order:

    1. ``mkcert -CAROOT`` — authoritative, and works without the Linux
       trust-store install.  Requires the ``mkcert`` binary on ``PATH``.
    2. The system trust store, populated by ``mkcert -install``.

    ``None`` means "verify normally".
    """
    try:
        caroot = subprocess.run(
            ["mkcert", "-CAROOT"],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        caroot = ""

    if caroot:
        ca = Path(caroot) / "rootCA.pem"
        if ca.is_file():
            return str(ca)

    for candidate in sorted(Path("/usr/local/share/ca-certificates").glob("mkcert*.crt")):
        return str(candidate)

    return None


def _follow_to_callback(client: httpx.Client, response: httpx.Response) -> httpx.Response:
    """Follow redirects one hop at a time until the callback has been answered."""
    for _ in range(_MAX_REDIRECTS):
        if response.status_code not in (301, 302, 303, 307, 308):
            break
        location = response.headers.get("location", "")
        if not location:
            break
        response = client.get(absolute(location, str(client.base_url)))
        if "/api/v1/auth/callback" in location:
            break
    return response


def login(
    username: str,
    password: str,
    *,
    base_url: str,
    ca_bundle: str | None = None,
    timeout: float = _TIMEOUT_SECONDS,
) -> Credentials:
    """Complete the real authorization-code + PKCE login flow.

    Returns the bearer, the ``wba_session`` cookie value, and the bearer's
    monotonic expiry.  The session id is returned alongside the bearer because
    the Dash UI authenticates by cookie, not by bearer.

    Raises:
        LoginError: when any step of the interactive flow does not complete.
    """
    import httpx  # noqa: PLC0415  # pylint: disable=import-outside-toplevel

    with httpx.Client(
        base_url=base_url, follow_redirects=False, timeout=timeout, verify=ca_bundle or True
    ) as client:
        start = client.get("/api/v1/auth/login", params={"next": "/app"})
        location = start.headers.get("location")
        if start.status_code != 302 or not location:
            raise LoginError(
                f"GET /api/v1/auth/login returned {start.status_code}, not a 302 "
                f"redirect to Keycloak"
            )

        page = client.get(absolute(location, base_url))
        page.raise_for_status()
        action_url, fields = parse_login_form(page.text)
        fields["username"] = username
        fields["password"] = password

        response = _follow_to_callback(client, client.post(action_url, data=fields))
        if response.status_code >= 400:
            raise LoginError(
                f"Login for {username!r} failed with {response.status_code}: "
                f"{response.text[:200]!r}"
            )

        session_id = client.cookies.get("wba_session", "")
        if not session_id:
            raise LoginError(
                f"Login for {username!r} completed but set no wba_session cookie"
            )

        exchange = client.post("/api/v1/auth/token")
        if exchange.status_code != 200:
            raise LoginError(
                f"Token exchange for {username!r} returned {exchange.status_code}: "
                f"{exchange.text[:200]!r}"
            )
        body: dict[str, Any] = exchange.json()
        expires_in = int(body.get("expires_in") or 900)
        return Credentials(
            access_token=str(body["access_token"]),
            session_id=session_id,
            expires_at=time.monotonic() + expires_in,
        )


def _credentials_via_client_credentials(
    *, base_url: str, ca_bundle: str | None = None, timeout: float = _TIMEOUT_SECONDS
) -> Credentials:
    """Fetch a ``wba-service`` bearer with the ``wba-internal`` client grant."""
    import httpx  # noqa: PLC0415  # pylint: disable=import-outside-toplevel

    secret = env_value("KEYCLOAK_SERVICE_CLIENT_SECRET")
    client_id = env_value("KEYCLOAK_SERVICE_CLIENT_ID", "wba-internal")
    if not secret:
        raise LoginError(
            "KEYCLOAK_SERVICE_CLIENT_SECRET is unset — the service role cannot be "
            "minted. Populate .env from .env.example."
        )

    realm_url = f"{base_url}/auth/realms/wba"
    response = httpx.post(
        realm_url + _TOKEN_PATH,
        data={
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": secret,
        },
        timeout=timeout,
        verify=ca_bundle or True,
    )
    if response.status_code != 200:
        raise LoginError(
            f"Client-credentials grant returned {response.status_code}: "
            f"{response.text[:200]!r}"
        )
    body: dict[str, Any] = response.json()
    expires_in = int(body.get("expires_in") or 900)
    return Credentials(
        access_token=str(body["access_token"]),
        session_id="",
        expires_at=time.monotonic() + expires_in,
    )


def credentials(
    role: str = "admin",
    *,
    base_url: str,
    ca_bundle: str | None = None,
    timeout: float = _TIMEOUT_SECONDS,
) -> Credentials:
    """Log in as *role* (``admin``, ``user`` or ``service``).

    Raises:
        LoginError: when the flow for *role* does not complete, or its password
            is not configured.
        ValueError: for an unknown role.
    """
    if role == "service":
        return _credentials_via_client_credentials(
            base_url=base_url, ca_bundle=ca_bundle, timeout=timeout
        )
    if role in _PASSWORD_ROLES:
        username, password_var = _PASSWORD_ROLES[role]
        password = env_value(password_var)
        if not password:
            raise LoginError(
                f"{password_var} is unset — the {role} role cannot be minted. "
                f"Populate .env from .env.example."
            )
        return login(username, password, base_url=base_url, ca_bundle=ca_bundle, timeout=timeout)
    raise ValueError(f"Unknown role {role!r}; expected admin, user or service")


def bearer(
    role: str = "admin",
    *,
    base_url: str,
    ca_bundle: str | None = None,
    timeout: float = _TIMEOUT_SECONDS,
) -> str:
    """Return a live bearer for *role*."""
    return credentials(role, base_url=base_url, ca_bundle=ca_bundle, timeout=timeout).access_token

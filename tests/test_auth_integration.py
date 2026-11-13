"""End-to-end proof of the real auth flow against live Keycloak.

Unit suites stub Keycloak, so nothing there can prove the **real** redirect, code
exchange, PKCE verification, cookie, token exchange, refresh rotation and logout
sequence works. This file is that proof, and it is the only one: it runs against
a Keycloak in the Compose stack.

It complements ``tests/test_authz_live_401_sweep.py`` (which covers who answers
``401`` without a credential): this file covers the *authenticated* path and the
per-role authorization decisions on top of it.

These tests are ``integration``-marked and never run in CI by design (CI runs
``-m unit`` only), mirroring the other live suites. ``server`` is load-bearing:
per ``tests/conftest.py`` it is what injects the locally issued mkcert CA into
``SSL_CERT_FILE`` so ``https://localhost`` verifies. The module deliberately
carries **no** ``authenticated`` marker — that marker monkeypatches ``httpx`` to
attach an admin bearer to every app-origin request, which would erase the
credential-less ``401`` observations this file depends on.

The login uses the real Keycloak form (HTML scraping, via
``tests/auth_helpers.py``) rather than a direct-access grant, which the
``web`` client disables by design.

Requires the Compose stack::

    docker compose up -d

Run with:
    pytest -m integration tests/test_auth_integration.py -v
"""

from __future__ import annotations

import subprocess
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import pytest

from app.auth.session_cookie import PKCE_COOKIE_NAME, SESSION_COOKIE_NAME, hash_session_id
from tests.auth_helpers import (
    BASE_URL,
    _absolute,
    _parse_login_form,
    admin_headers,
    configured,
    env_value,
    service_headers,
    user_headers,
)

pytestmark = [pytest.mark.integration, pytest.mark.server]

TIMEOUT = 30.0
REPO_ROOT = Path(__file__).resolve().parents[1]

ADMIN_USERNAME_VAR = "TEST_SUITE_WBA_ADMIN_USERNAME"
USER_USERNAME_VAR = "TEST_SUITE_WBA_USER_USERNAME"
ADMIN_PASSWORD_VAR = "TEST_SUITE_WBA_ADMIN_PASSWORD"
USER_PASSWORD_VAR = "TEST_SUITE_WBA_USER_PASSWORD"

_USER_READY = configured("TEST_SUITE_WBA_USER_USERNAME") and configured(
    "TEST_SUITE_WBA_USER_PASSWORD"
)
_ADMIN_READY = configured("TEST_SUITE_WBA_ADMIN_USERNAME") and configured(
    "TEST_SUITE_WBA_ADMIN_PASSWORD"
)

needs_user = pytest.mark.skipif(
    not _USER_READY,
    reason="TEST_SUITE_WBA_USER_* is not configured — see INSTALL_GUIDE.md",
)
needs_admin_and_user = pytest.mark.skipif(
    not (_ADMIN_READY and _USER_READY),
    reason="TEST_SUITE_WBA_ADMIN_* and TEST_SUITE_WBA_USER_* are both required",
)

SETTING_KEY = "HTTP_REQUEST_TIMEOUT"
SETTING_PATH = f"/api/v1/settings/{SETTING_KEY}"

_KEYCLOAK_CONTAINER = "wba-ai-keycloak"
_KEYCLOAK_HEALTHY_TIMEOUT = 180.0

_REDIRECT_CODES = (301, 302, 303, 307, 308)


@dataclass
class LiveSession:
    """A browser-equivalent session: the client (cookie jar) and the raw id."""

    client: httpx.Client
    session_id: str


def _fresh_client() -> httpx.Client:
    """Return a client that observes every redirect hop individually."""
    return httpx.Client(base_url=BASE_URL, follow_redirects=False, timeout=TIMEOUT)


def _begin_login(client: httpx.Client, next_path: str) -> str:
    """Start the OIDC login and return Keycloak's authorization URL."""
    start = client.get("/api/v1/auth/login", params={"next": next_path})
    assert start.status_code == 302, (
        f"GET /api/v1/auth/login returned {start.status_code}, expected a 302 redirect"
    )
    location = start.headers.get("location", "")
    assert location.startswith(
        f"{BASE_URL}/auth/realms/wba/protocol/openid-connect/auth?"
    ), f"login did not redirect to the wba realm: {location!r}"
    assert client.cookies.get(PKCE_COOKIE_NAME), "login set no PKCE cookie"
    return location


def _follow_until_callback(client: httpx.Client, response: httpx.Response) -> httpx.Response:
    """Follow redirects one hop at a time until the callback has been answered."""
    for _ in range(10):
        if response.status_code not in _REDIRECT_CODES:
            break
        location = response.headers.get("location", "")
        if not location:
            break
        response = client.get(_absolute(location))
        if "/api/v1/auth/callback" in location:
            break
    return response


def _submit_credentials(client: httpx.Client, page_html: str, username: str, password: str) -> httpx.Response:
    """Scrape Keycloak's login form and post the credentials to it."""
    action_url, fields = _parse_login_form(page_html)
    assert "/auth/realms/wba/" in action_url, (
        f"login form did not post back under the realm: {action_url!r}"
    )
    fields["username"] = username
    fields["password"] = password
    return client.post(action_url, data=fields)


def _password(role: str) -> str:
    """Return the live password for *role* from the environment, never hard-coded."""
    var = ADMIN_PASSWORD_VAR if role == "admin" else USER_PASSWORD_VAR
    value = env_value(var)
    assert value, f"{var} is unset — populate .env before running this suite"
    return str(value)


def _username(role: str) -> str:
    """Return the configured realm username for *role*, never hard-coded."""
    var = ADMIN_USERNAME_VAR if role == "admin" else USER_USERNAME_VAR
    value = env_value(var)
    assert value, f"{var} is unset — populate .env before running this suite"
    return str(value)


@contextmanager
def _live_session(role: str, *, next_path: str = "/app/graph") -> Iterator[LiveSession]:
    """Complete a real login and yield the open client holding its session cookie."""
    username = _username(role)
    client = _fresh_client()
    try:
        location = _begin_login(client, next_path)
        page = client.get(_absolute(location))
        page.raise_for_status()
        response = _follow_until_callback(
            client, _submit_credentials(client, page.text, username, _password(role))
        )
        assert response.status_code == 302, (
            f"login for {username!r} ended with {response.status_code}, expected the callback 302"
        )
        session_id = client.cookies.get(SESSION_COOKIE_NAME, "")
        assert session_id, f"login for {username!r} set no {SESSION_COOKIE_NAME} cookie"
        yield LiveSession(client=client, session_id=session_id)
    finally:
        client.close()


def _dsn() -> str:
    """Build a host-reachable Postgres DSN from the environment.

    The API container resolves ``postgres`` internally; a host-run test cannot,
    so the published ``127.0.0.1:5432`` is used instead. Credentials come from
    the environment (the same values Compose interpolates), never hard-coded.
    """
    return "postgresql://{user}:{password}@{host}:{port}/{db}".format(
        user=env_value("POSTGRES_USER", "postgres"),
        password=env_value("POSTGRES_PASSWORD", "postgres"),
        host=env_value("POSTGRES_HOST", "127.0.0.1"),
        port=env_value("POSTGRES_PORT", "5432"),
        db=env_value("POSTGRES_DB", "postgres"),
    )


def _session_row(session_id: str) -> tuple[str, Any]:
    """Return ``(refresh_token_encrypted, revoked_at)`` for a live session cookie."""
    import psycopg2

    with psycopg2.connect(_dsn()) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT refresh_token_encrypted, revoked_at FROM auth_session "
            "WHERE session_id_hash = %s",
            (hash_session_id(session_id),),
        )
        row = cur.fetchone()
    assert row is not None, "no auth_session row for the session cookie"
    return str(row[0]), row[1]


def _read_setting(headers: dict[str, str]) -> dict[str, Any]:
    """Return the source-aware settings row for the timeout key."""
    response = httpx.get(f"{BASE_URL}/api/v1/settings/", headers=headers, timeout=TIMEOUT)
    response.raise_for_status()
    return next(row for row in response.json() if row["key"] == SETTING_KEY)


def _restore_setting(headers: dict[str, str], before: dict[str, Any]) -> dict[str, Any]:
    """Return the setting to its pre-test state and return the resulting row.

    The optimistic-concurrency token is re-read immediately before the restore:
    the test's own write advanced ``updated_at``, so the timestamp captured
    *before* that write is stale by definition and would trigger a ``409``.
    """
    current = _read_setting(headers)
    expected = {"expected_updated_at": current["updated_at"]}
    if before["value"] is None:
        response = httpx.post(
            f"{BASE_URL}/api/v1/settings/{SETTING_KEY}/reset",
            json=expected,
            headers=headers,
            timeout=TIMEOUT,
        )
    else:
        response = httpx.patch(
            f"{BASE_URL}{SETTING_PATH}",
            json={"value": before["value"], **expected},
            headers=headers,
            timeout=TIMEOUT,
        )
    assert response.status_code == 200, (
        f"restoring {SETTING_KEY} returned {response.status_code}: {response.text[:200]!r}"
    )
    return _read_setting(headers)


def _keycloak_status() -> str:
    """Return the Keycloak container's health status, or ``"missing"``."""
    completed = subprocess.run(
        ["docker", "inspect", "--format", "{{.State.Health.Status}}", _KEYCLOAK_CONTAINER],
        capture_output=True,
        text=True,
        check=False,
    )
    return completed.stdout.strip() or "missing"


def _wait_for_keycloak_healthy(timeout: float = _KEYCLOAK_HEALTHY_TIMEOUT) -> None:
    """Block until Keycloak reports healthy, failing loudly on timeout."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _keycloak_status() == "healthy":
            return
        time.sleep(2)
    pytest.fail(
        f"Keycloak did not become healthy within {timeout:.0f}s "
        f"(last status {_keycloak_status()!r}); the stack was left unhealthy"
    )


def _compose(*args: str) -> None:
    """Run a ``docker compose`` subcommand from the repository root."""
    completed = subprocess.run(
        ["docker", "compose", *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, (
        f"docker compose {' '.join(args)} failed: {completed.stderr.strip()}"
    )


# ── The real login sequence ─────────────────────────────────────────────


@needs_user
class TestRealLoginSequence:
    """Each hop of the login is observable and asserted, with nothing stubbed."""

    def test_login_form_callback_and_token_exchange(self) -> None:
        next_path = "/app/graph"
        client = _fresh_client()
        try:
            location = _begin_login(client, next_path)

            page = client.get(_absolute(location))
            page.raise_for_status()
            assert '<form' in page.text.lower(), "Keycloak login page carried no form"

            callback = _follow_until_callback(
                client,
                _submit_credentials(client, page.text, _username("user"), _password("user")),
            )

            assert callback.status_code == 302, (
                f"callback answered {callback.status_code}, expected a 302"
            )
            assert callback.headers.get("location") == next_path

            set_cookie = "\n".join(callback.headers.get_list("set-cookie"))
            assert f"{SESSION_COOKIE_NAME}=" in set_cookie
            assert "HttpOnly" in set_cookie
            assert "Secure" in set_cookie
            assert "SameSite=Lax" in set_cookie or "samesite=lax" in set_cookie
            assert "Path=/" in set_cookie
            assert f"{PKCE_COOKIE_NAME}=" in set_cookie, "the PKCE cookie was not cleared"
            assert "Max-Age=0" in set_cookie or "max-age=0" in set_cookie

            session_id = client.cookies.get(SESSION_COOKIE_NAME, "")
            assert session_id, "the callback set no session cookie"

            exchange = client.post("/api/v1/auth/token")
            assert exchange.status_code == 200, exchange.text[:200]
            body = exchange.json()
            assert body["token_type"] == "bearer"
            assert body["access_token"]
            assert body["expires_in"] > 0
            bearer = {"Authorization": f"Bearer {body['access_token']}"}

            me = httpx.get(f"{BASE_URL}/api/v1/auth/me", headers=bearer, timeout=TIMEOUT)
            assert me.status_code == 200
            assert me.json()["username"] == _username("user")
            assert "user" in me.json()["roles"]

            authed = httpx.get(
                f"{BASE_URL}/api/v1/search",
                params={"q": "x"},
                headers=bearer,
                timeout=TIMEOUT,
            )
            assert authed.status_code not in (401, 403), authed.status_code

            anon = httpx.get(
                f"{BASE_URL}/api/v1/search", params={"q": "x"}, timeout=TIMEOUT
            )
            assert anon.status_code == 401, (
                f"search without a bearer answered {anon.status_code}, expected 401"
            )
        finally:
            client.close()


# ── Refresh rotation ────────────────────────────────────────────────────


@needs_user
class TestRefreshRotation:
    """Keycloak rotates the refresh token on every refresh, and the row follows."""

    def test_triple_refresh_rotates_and_persists(self) -> None:
        with _live_session("user") as session:
            stored_before, _ = _session_row(session.session_id)

            tokens: list[str] = []
            stored: list[str] = []
            for _ in range(3):
                response = session.client.post("/api/v1/auth/token")
                assert response.status_code == 200, (
                    f"refresh returned {response.status_code}: {response.text[:200]!r}"
                )
                tokens.append(response.json()["access_token"])
                stored.append(_session_row(session.session_id)[0])

            assert len(set(tokens)) == 3, "each refresh must return a distinct access token"
            assert stored[0] != stored_before, "the first refresh did not persist a new token"
            assert stored[1] != stored[0], "the second refresh did not persist a new token"
            assert stored[2] != stored[1], "the third refresh did not persist a new token"


# ── Logout ──────────────────────────────────────────────────────────────


@needs_user
class TestLogout:
    """Logout revokes the row, clears the cookie, and the exchange then 401s."""

    def test_logout_revokes_and_clears(self) -> None:
        with _live_session("user") as session:
            _, revoked_before = _session_row(session.session_id)
            assert revoked_before is None

            response = session.client.post("/api/v1/auth/logout")

            assert response.status_code == 302
            assert "openid-connect/logout" in response.headers.get("location", "")
            set_cookie = "\n".join(response.headers.get_list("set-cookie"))
            assert f'{SESSION_COOKIE_NAME}="";' in set_cookie or f'{SESSION_COOKIE_NAME}=;' in set_cookie

            _, revoked_after = _session_row(session.session_id)
            assert revoked_after is not None, "logout did not set revoked_at"

            session.client.cookies.set(SESSION_COOKIE_NAME, session.session_id)
            exchange = session.client.post("/api/v1/auth/token")
            assert exchange.status_code == 401, (
                f"a revoked session exchanged for {exchange.status_code}, expected 401"
            )


# ── Wrong-role and cross-user cases ─────────────────────────────────────


class TestWrongRoleAndCrossUser:
    """Per-role authorization against live Keycloak, not a stubbed verifier."""

    @needs_admin_and_user
    def test_admin_only_setting_write_denies_user(self) -> None:
        before = _read_setting(admin_headers())
        print(
            f"\n[{SETTING_KEY}] before: value={before['value']!r} "
            f"source={before['source']!r} effective_value={before['effective_value']!r}"
        )
        try:
            denied = httpx.patch(
                f"{BASE_URL}{SETTING_PATH}",
                json={"value": 123},
                headers=user_headers(),
                timeout=TIMEOUT,
            )
            assert denied.status_code == 403, (
                f"a plain user wrote an admin-only setting: {denied.status_code}"
            )

            allowed = httpx.patch(
                f"{BASE_URL}{SETTING_PATH}",
                json={"value": 123},
                headers=admin_headers(),
                timeout=TIMEOUT,
            )
            assert allowed.status_code == 200, allowed.text[:200]
            assert allowed.json()["effective_value"] == 123
        finally:
            after = _restore_setting(admin_headers(), before)

        print(
            f"[{SETTING_KEY}] after: value={after['value']!r} "
            f"source={after['source']!r} effective_value={after['effective_value']!r}"
        )
        assert after["value"] == before["value"], "the setting was not restored"
        assert after["effective_value"] == before["effective_value"]
        if before["value"] is None:
            assert after["source"] != "db"

    @needs_admin_and_user
    def test_connector_secrets_deny_user_allow_admin(self) -> None:
        path = "/api/v1/connectors/github/configs"
        params = {"include_secrets": "true"}

        denied = httpx.get(
            f"{BASE_URL}{path}", params=params, headers=user_headers(), timeout=TIMEOUT
        )
        assert denied.status_code == 403, (
            f"a plain user read connector secrets: {denied.status_code}"
        )

        allowed = httpx.get(
            f"{BASE_URL}{path}", params=params, headers=admin_headers(), timeout=TIMEOUT
        )
        assert allowed.status_code == 200, allowed.text[:200]

    @needs_admin_and_user
    def test_chat_is_not_visible_across_users(self) -> None:
        created = httpx.post(
            f"{BASE_URL}/api/v1/chats/", json={}, headers=user_headers(), timeout=TIMEOUT
        )
        assert created.status_code == 201, created.text[:200]
        chat_id = created.json()["session_id"]
        try:
            cross = httpx.get(
                f"{BASE_URL}/api/v1/chats/{chat_id}", headers=admin_headers(), timeout=TIMEOUT
            )
            assert cross.status_code == 404, (
                f"cross-user chat read answered {cross.status_code}, expected 404 "
                f"(never 403)"
            )

            owner = httpx.get(
                f"{BASE_URL}/api/v1/chats/{chat_id}", headers=user_headers(), timeout=TIMEOUT
            )
            assert owner.status_code == 200, owner.text[:200]
        finally:
            httpx.delete(
                f"{BASE_URL}/api/v1/chats/{chat_id}", headers=user_headers(), timeout=TIMEOUT
            )

    def test_service_role_is_reader_not_admin(self) -> None:
        headers = service_headers()

        listed = httpx.get(
            f"{BASE_URL}/api/v1/commands/", headers=headers, timeout=TIMEOUT
        )
        assert listed.status_code not in (401, 403), (
            f"the service role was denied a user-level read: {listed.status_code}"
        )

        denied = httpx.patch(
            f"{BASE_URL}{SETTING_PATH}", json={"value": 123}, headers=headers, timeout=TIMEOUT
        )
        assert denied.status_code == 403, (
            f"the service role wrote an admin-only setting: {denied.status_code}"
        )


# ── Keycloak-down resilience ────────────────────────────────────────────


@needs_user
class TestKeycloakDownResilience:
    """An unexpired bearer survives a Keycloak outage; a required refresh 503s.

    Defined last on purpose: stopping a service mid-suite is disruptive, and
    any test defined after it would depend on Keycloak having come back. The
    ``finally`` restarts Keycloak and waits for it to be healthy again.
    """

    def test_bearer_survives_and_refresh_is_503(self) -> None:
        with _live_session("user") as session:
            exchange = session.client.post("/api/v1/auth/token")
            assert exchange.status_code == 200, exchange.text[:200]
            bearer = {"Authorization": f"Bearer {exchange.json()['access_token']}"}

            try:
                _compose("stop", "keycloak")

                survived = httpx.get(
                    f"{BASE_URL}/api/v1/search",
                    params={"q": "x"},
                    headers=bearer,
                    timeout=TIMEOUT,
                )
                assert survived.status_code not in (401, 403), (
                    f"an unexpired bearer was rejected while Keycloak was down: "
                    f"{survived.status_code}"
                )

                refresh = session.client.post("/api/v1/auth/token")
                assert refresh.status_code == 503, (
                    f"a required refresh answered {refresh.status_code} while Keycloak "
                    f"was down, expected 503"
                )

                _, revoked = _session_row(session.session_id)
                assert revoked is None, "a Keycloak outage revoked the session row"
            finally:
                _compose("start", "keycloak")
                _wait_for_keycloak_healthy()

            resumed = session.client.post("/api/v1/auth/token")
            assert resumed.status_code == 200, (
                f"refresh did not recover after Keycloak restarted: "
                f"{resumed.status_code} {resumed.text[:200]!r}"
            )

        assert _keycloak_status() == "healthy"

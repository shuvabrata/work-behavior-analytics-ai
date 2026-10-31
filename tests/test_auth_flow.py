"""Unit tests for the auth API's login flow and token exchange.

Driven through ``httpx.ASGITransport`` against the real ``app`` so the routing,
cookie handling and status-code contract are exercised end to end. Two seams are
replaced:

* ``app.api.auth.v1.query`` — an in-memory session store, so the rotation test
  can assert what was actually persisted without a database.
* ``service._post_token`` and ``service.validate_bearer_token`` — the Keycloak
  boundary. No test in this file touches the network.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Iterator

import httpx
import pytest
import pytest_asyncio

from app.api.auth.v1 import query as qry
from app.api.auth.v1 import service
from app.api.auth.v1.service import _sanitize_next_path
from app.api_main import app
from app.auth.principal import Principal
from app.auth.session_cookie import (
    SESSION_COOKIE_NAME,
    decrypt_refresh_token,
)
from app.db.session import get_async_db

pytestmark = [pytest.mark.unit, pytest.mark.asyncio]

BASE_URL = "https://test"


# ── Fakes ────────────────────────────────────────────────────────────────


class _Row:
    """An in-memory stand-in for an ``auth_session`` row."""

    _next_id = 1

    def __init__(self, **kwargs: Any) -> None:
        self.id = _Row._next_id
        _Row._next_id += 1
        self.revoked_at: datetime | None = None
        for key, value in kwargs.items():
            setattr(self, key, value)


class _SessionStore:
    """In-memory replacement for the query layer's five functions."""

    def __init__(self) -> None:
        self.rows: list[_Row] = []

    def by_hash(self, session_id_hash: str) -> _Row | None:
        for row in self.rows:
            if row.session_id_hash == session_id_hash and row.revoked_at is None:
                return row
        return None


class _FakeResponse:
    """Minimal ``requests.Response`` stand-in."""

    def __init__(self, status_code: int, payload: Any) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self) -> Any:
        return self._payload


class _FakeDb:
    """A session stub — the fake query layer ignores it."""

    async def commit(self) -> None:
        return None


class _KeycloakStub:
    """Serves successive token-endpoint responses and records the requests."""

    def __init__(self) -> None:
        self.responses: list[_FakeResponse] = []
        self.requests: list[dict[str, str]] = []

    def post(self, data: dict[str, str]) -> _FakeResponse:
        self.requests.append(dict(data))
        if self.responses:
            return self.responses.pop(0)
        return _FakeResponse(200, {})


@pytest.fixture(name="store")
def _store(monkeypatch: pytest.MonkeyPatch) -> _SessionStore:
    store = _SessionStore()

    async def create_session(db: Any, **kwargs: Any) -> _Row:
        kwargs.setdefault("last_seen_at", datetime.now(timezone.utc))
        row = _Row(**kwargs)
        store.rows.append(row)
        return row

    async def get_active_session(db: Any, session_id_hash: str) -> _Row | None:
        return store.by_hash(session_id_hash)

    async def touch_session(
        db: Any, row: _Row, *, last_seen_at: datetime, refresh_token_encrypted: str | None = None
    ) -> None:
        row.last_seen_at = last_seen_at
        if refresh_token_encrypted is not None:
            row.refresh_token_encrypted = refresh_token_encrypted

    async def revoke_session(db: Any, row: _Row, *, revoked_at: datetime) -> None:
        row.revoked_at = revoked_at

    async def purge_expired(db: Any, *, now: datetime) -> int:
        return 0

    monkeypatch.setattr(qry, "create_session", create_session)
    monkeypatch.setattr(qry, "get_active_session", get_active_session)
    monkeypatch.setattr(qry, "touch_session", touch_session)
    monkeypatch.setattr(qry, "revoke_session", revoke_session)
    monkeypatch.setattr(qry, "purge_expired", purge_expired)
    return store


@pytest.fixture(name="keycloak")
def _keycloak(monkeypatch: pytest.MonkeyPatch) -> _KeycloakStub:
    stub = _KeycloakStub()
    monkeypatch.setattr(service, "_post_token", stub.post)
    monkeypatch.setattr(
        service,
        "validate_bearer_token",
        lambda token: Principal(
            subject="sub-1", username="alice", roles=frozenset({"wba-user"})
        ),
    )
    return stub


@pytest_asyncio.fixture(name="client")
async def _client(store: _SessionStore, keycloak: _KeycloakStub) -> Iterator[httpx.AsyncClient]:
    async def _override_db() -> Any:
        yield _FakeDb()

    app.dependency_overrides[get_async_db] = _override_db
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url=BASE_URL) as client:
            yield client
    finally:
        app.dependency_overrides.pop(get_async_db, None)


def _session_cookie(response: httpx.Response) -> str:
    """Extract the ``wba_session`` value from a response's cookies."""
    cookie = response.cookies.get(SESSION_COOKIE_NAME)
    assert cookie, "no wba_session cookie was set"
    return cookie


async def _start(client: httpx.AsyncClient, next_path: str = "/app/graph") -> httpx.Response:
    response = await client.get("/api/v1/auth/login", params={"next": next_path})
    assert response.status_code == 302
    return response


async def _complete(
    client: httpx.AsyncClient, login: httpx.Response, state: str | None = None
) -> httpx.Response:
    from app.auth.session_cookie import decode_pkce_cookie

    pkce = login.cookies.get("wba_oidc")
    assert pkce, "no PKCE cookie was set"
    expected_state, _ = decode_pkce_cookie(pkce)
    return await client.get(
        "/api/v1/auth/callback",
        params={"code": "abc", "state": state if state is not None else expected_state},
    )


# ── /auth/login ──────────────────────────────────────────────────────────


class TestLogin:
    async def test_redirects_to_keycloak_with_pkce(self, client: httpx.AsyncClient) -> None:
        response = await _start(client)

        location = response.headers["location"]
        assert location.startswith(
            "https://localhost/auth/realms/wba/protocol/openid-connect/auth?"
        )
        assert "code_challenge_method=S256" in location
        assert "state=" in location
        assert "code_challenge=" in location
        assert "redirect_uri=https%3A%2F%2Flocalhost%2Fapi%2Fv1%2Fauth%2Fcallback" in location

    async def test_sets_the_pkce_cookie(self, client: httpx.AsyncClient) -> None:
        response = await _start(client)

        assert response.cookies.get("wba_oidc")

    async def test_unsafe_next_falls_back(self, client: httpx.AsyncClient) -> None:
        response = await client.get(
            "/api/v1/auth/login", params={"next": "https://evil.example"}
        )

        assert response.status_code == 302
        assert _sanitize_next_path("https://evil.example") == "/app/graph"


# ── /auth/callback ───────────────────────────────────────────────────────


class TestCallback:
    async def test_state_mismatch_is_400_and_creates_no_row(
        self, client: httpx.AsyncClient, store: _SessionStore
    ) -> None:
        login = await _start(client)

        response = await _complete(client, login, state="not-the-state")

        assert response.status_code == 400
        assert store.rows == []

    async def test_happy_path_sets_the_session_cookie(
        self, client: httpx.AsyncClient, store: _SessionStore, keycloak: _KeycloakStub
    ) -> None:
        keycloak.responses.append(
            _FakeResponse(200, {"access_token": "at", "refresh_token": "rt"})
        )
        login = await _start(client)

        response = await _complete(client, login)

        assert response.status_code == 302
        assert response.headers["location"] == "/app/graph"
        set_cookie = "\n".join(response.headers.get_list("set-cookie"))
        assert "HttpOnly" in set_cookie
        assert "Secure" in set_cookie
        assert "SameSite=Lax" in set_cookie or "samesite=lax" in set_cookie
        assert "Path=/" in set_cookie
        assert len(store.rows) == 1
        assert store.rows[0].subject == "sub-1"
        assert store.rows[0].roles == ["wba-user"]


# ── /auth/token ──────────────────────────────────────────────────────────


class TestTokenExchange:
    async def test_no_cookie_is_401(self, client: httpx.AsyncClient) -> None:
        response = await client.post("/api/v1/auth/token")

        assert response.status_code == 401

    async def test_unknown_session_is_401(self, client: httpx.AsyncClient) -> None:
        client.cookies.set(SESSION_COOKIE_NAME, "bogus", domain="test", path="/")

        response = await client.post("/api/v1/auth/token")

        assert response.status_code == 401

    async def test_revoked_session_is_401(
        self, client: httpx.AsyncClient, store: _SessionStore, keycloak: _KeycloakStub
    ) -> None:
        keycloak.responses.append(
            _FakeResponse(200, {"access_token": "at", "refresh_token": "rt"})
        )
        login = await _start(client)
        callback = await _complete(client, login)
        raw = _session_cookie(callback)
        store.rows[0].revoked_at = datetime.now(timezone.utc)

        client.cookies.set(SESSION_COOKIE_NAME, raw, domain="test", path="/")
        response = await client.post("/api/v1/auth/token")

        assert response.status_code == 401

    async def test_idle_expiry_is_401_and_revokes(
        self, client: httpx.AsyncClient, store: _SessionStore, keycloak: _KeycloakStub
    ) -> None:
        keycloak.responses.append(
            _FakeResponse(200, {"access_token": "at", "refresh_token": "rt"})
        )
        login = await _start(client)
        callback = await _complete(client, login)
        raw = _session_cookie(callback)
        store.rows[0].last_seen_at = datetime.now(timezone.utc) - timedelta(hours=48)

        client.cookies.set(SESSION_COOKIE_NAME, raw, domain="test", path="/")
        response = await client.post("/api/v1/auth/token")

        assert response.status_code == 401
        assert store.rows[0].revoked_at is not None

    async def test_rotation_persists_each_new_refresh_token(
        self, client: httpx.AsyncClient, store: _SessionStore, keycloak: _KeycloakStub
    ) -> None:
        keycloak.responses.append(
            _FakeResponse(200, {"access_token": "at0", "refresh_token": "rt0"})
        )
        login = await _start(client)
        callback = await _complete(client, login)
        raw = _session_cookie(callback)
        client.cookies.set(SESSION_COOKIE_NAME, raw, domain="test", path="/")

        keycloak.responses.append(
            _FakeResponse(
                200, {"access_token": "at1", "refresh_token": "rt1", "expires_in": 900}
            )
        )
        first = await client.post("/api/v1/auth/token")
        assert first.status_code == 200
        stored_after_first = store.rows[0].refresh_token_encrypted
        assert decrypt_refresh_token(stored_after_first) == "rt1"

        keycloak.responses.append(
            _FakeResponse(
                200, {"access_token": "at2", "refresh_token": "rt2", "expires_in": 900}
            )
        )
        second = await client.post("/api/v1/auth/token")

        assert second.status_code == 200
        stored_after_second = store.rows[0].refresh_token_encrypted
        assert stored_after_second != stored_after_first
        assert decrypt_refresh_token(stored_after_second) == "rt2"
        # The second refresh must present the token the first refresh returned.
        assert keycloak.requests[-1]["refresh_token"] == "rt1"

    async def test_keycloak_500_is_503_and_preserves_the_row(
        self, client: httpx.AsyncClient, store: _SessionStore, keycloak: _KeycloakStub
    ) -> None:
        keycloak.responses.append(
            _FakeResponse(200, {"access_token": "at", "refresh_token": "rt"})
        )
        login = await _start(client)
        callback = await _complete(client, login)
        raw = _session_cookie(callback)
        client.cookies.set(SESSION_COOKIE_NAME, raw, domain="test", path="/")

        keycloak.responses.append(_FakeResponse(500, {}))
        response = await client.post("/api/v1/auth/token")

        assert response.status_code == 503
        assert store.rows[0].revoked_at is None

    async def test_keycloak_400_revokes_and_is_401(
        self, client: httpx.AsyncClient, store: _SessionStore, keycloak: _KeycloakStub
    ) -> None:
        keycloak.responses.append(
            _FakeResponse(200, {"access_token": "at", "refresh_token": "rt"})
        )
        login = await _start(client)
        callback = await _complete(client, login)
        raw = _session_cookie(callback)
        client.cookies.set(SESSION_COOKIE_NAME, raw, domain="test", path="/")

        keycloak.responses.append(_FakeResponse(400, {"error": "invalid_grant"}))
        response = await client.post("/api/v1/auth/token")

        assert response.status_code == 401
        assert store.rows[0].revoked_at is not None


# ── /auth/logout ─────────────────────────────────────────────────────────


class TestLogout:
    async def test_revokes_and_clears_the_cookie(
        self, client: httpx.AsyncClient, store: _SessionStore, keycloak: _KeycloakStub
    ) -> None:
        keycloak.responses.append(
            _FakeResponse(200, {"access_token": "at", "refresh_token": "rt"})
        )
        login = await _start(client)
        callback = await _complete(client, login)
        raw = _session_cookie(callback)
        client.cookies.set(SESSION_COOKIE_NAME, raw, domain="test", path="/")

        response = await client.post("/api/v1/auth/logout")

        assert response.status_code == 302
        assert "openid-connect/logout" in response.headers["location"]
        assert store.rows[0].revoked_at is not None
        assert 'wba_session=""' in "\n".join(response.headers.get_list("set-cookie"))


# ── /auth/me ─────────────────────────────────────────────────────────────


class TestMe:
    async def test_bogus_cookie_is_401(self, client: httpx.AsyncClient) -> None:
        response = await client.get(
            "/api/v1/auth/me", headers={"Cookie": "wba_session=bogus"}
        )

        assert response.status_code == 401

    async def test_valid_bearer_returns_identity(
        self, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from app.auth import dependencies

        monkeypatch.setattr(
            dependencies,
            "validate_bearer_token",
            lambda token: Principal(
                subject="sub-9", username="bob", roles=frozenset({"wba-admin"})
            ),
        )
        response = await client.get(
            "/api/v1/auth/me", headers={"Authorization": "Bearer good"}
        )

        assert response.status_code == 200
        assert response.json() == {
            "subject": "sub-9",
            "username": "bob",
            "roles": ["wba-admin"],
        }

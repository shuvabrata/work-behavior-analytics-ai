"""Unit tests for the Principal role dependencies.

Driven through a tiny FastAPI app built here — one route per dependency — via
``httpx.ASGITransport``. The token verifier is replaced with a stub so the tests
assert only the dependency's status-code and error-shape contract; signature
verification itself is covered by ``tests/test_auth_tokens.py``.
"""

from __future__ import annotations

from collections.abc import Iterator

import httpx
import pytest
import pytest_asyncio
from fastapi import Depends, FastAPI

from app.auth import dependencies
from app.auth.principal import Principal
from app.auth.tokens import NoRecognisedRoleError, TokenValidationError

pytestmark = [pytest.mark.unit, pytest.mark.asyncio]


def _app() -> FastAPI:
    """Build a throwaway app wiring each dependency to one route."""
    app = FastAPI()

    @app.get("/user")
    async def _user(principal: Principal = Depends(dependencies.require_user)) -> dict[str, str]:
        return {"username": principal.username}

    @app.get("/admin")
    async def _admin(principal: Principal = Depends(dependencies.require_admin)) -> dict[str, str]:
        return {"username": principal.username}

    @app.get("/service")
    async def _service(principal: Principal = Depends(dependencies.require_service)) -> dict[str, str]:
        return {"username": principal.username}

    return app


@pytest_asyncio.fixture(name="client")
async def _client() -> Iterator[httpx.AsyncClient]:
    """An AsyncClient bound to the throwaway app."""
    transport = httpx.ASGITransport(app=_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


def _principal(*roles: str) -> Principal:
    return Principal(
        subject="sub-1", username="alice", roles=frozenset(roles)
    )


def _stub_valid(monkeypatch: pytest.MonkeyPatch, principal: Principal) -> None:
    """Make the verifier return *principal* for any token."""
    monkeypatch.setattr(
        dependencies, "validate_bearer_token", lambda _token: principal
    )


def _stub_raises(monkeypatch: pytest.MonkeyPatch, exc: Exception) -> None:
    """Make the verifier raise *exc* for any token."""
    def _raise(_token: str) -> Principal:
        raise exc

    monkeypatch.setattr(dependencies, "validate_bearer_token", _raise)


class TestGetPrincipalStatusCodes:
    async def test_missing_header_is_401(self, client: httpx.AsyncClient) -> None:
        """No ``Authorization`` header yields 401 with a WWW-Authenticate hint."""
        response = await client.get("/user")
        assert response.status_code == 401
        assert response.headers["www-authenticate"] == "Bearer"
        assert response.json()["detail"]["error"] == "missing_credentials"

    async def test_non_bearer_scheme_is_401(self, client: httpx.AsyncClient) -> None:
        """A non-bearer scheme is treated as no credential."""
        response = await client.get("/user", headers={"Authorization": "Basic abc"})
        assert response.status_code == 401

    async def test_invalid_token_is_401(
        self, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A rejected token yields 401, not 403."""
        _stub_raises(monkeypatch, TokenValidationError("bad signature"))
        response = await client.get("/user", headers={"Authorization": "Bearer junk"})
        assert response.status_code == 401
        assert response.headers["www-authenticate"] == "Bearer"
        assert response.json()["detail"]["error"] == "invalid_token"

    async def test_no_role_is_403(
        self, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A valid token with no recognised role yields 403, never 401."""
        _stub_raises(monkeypatch, NoRecognisedRoleError("no role"))
        response = await client.get("/user", headers={"Authorization": "Bearer t"})
        assert response.status_code == 403
        assert response.json()["detail"]["error"] == "no_recognised_role"

    async def test_403_has_no_www_authenticate(
        self, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A 403 is an authorization failure — it does not ask for a credential."""
        _stub_raises(monkeypatch, NoRecognisedRoleError("no role"))
        response = await client.get("/user", headers={"Authorization": "Bearer t"})
        assert "www-authenticate" not in response.headers


class TestRequireUser:
    @pytest.mark.parametrize("role", ["wba-user", "wba-admin", "wba-service"])
    async def test_accepts_every_role(
        self, role: str, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``require_user`` accepts any of the three recognised roles."""
        _stub_valid(monkeypatch, _principal(role))
        response = await client.get("/user", headers={"Authorization": "Bearer t"})
        assert response.status_code == 200
        assert response.json()["username"] == "alice"


class TestRequireAdmin:
    async def test_admin_allowed(
        self, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``wba-admin`` passes."""
        _stub_valid(monkeypatch, _principal("wba-admin"))
        response = await client.get("/admin", headers={"Authorization": "Bearer t"})
        assert response.status_code == 200

    async def test_user_forbidden(
        self, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A valid ``wba-user`` is 403 against an admin-only route."""
        _stub_valid(monkeypatch, _principal("wba-user"))
        response = await client.get("/admin", headers={"Authorization": "Bearer t"})
        assert response.status_code == 403
        assert response.json()["detail"]["error"] == "insufficient_role"


class TestRequireService:
    async def test_service_allowed(
        self, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``wba-service`` passes."""
        _stub_valid(monkeypatch, _principal("wba-service"))
        response = await client.get("/service", headers={"Authorization": "Bearer t"})
        assert response.status_code == 200

    async def test_user_forbidden(
        self, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A valid ``wba-user`` is 403 against a service-only route."""
        _stub_valid(monkeypatch, _principal("wba-user"))
        response = await client.get("/service", headers={"Authorization": "Bearer t"})
        assert response.status_code == 403
        assert response.json()["detail"]["error"] == "insufficient_role"

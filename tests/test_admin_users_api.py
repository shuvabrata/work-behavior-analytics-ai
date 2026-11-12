"""Unit tests for the admin user management API endpoints.

Driven through ``httpx.ASGITransport`` against ``app.api_main.app`` with the
conftest admin override cleared, so the real authorization dependencies run.
The Keycloak admin client is stubbed — no HTTP ever leaves the process.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import httpx
import pytest
import pytest_asyncio

from app.api_main import app
from app.auth import keycloak_admin as k
from app.auth.dependencies import get_principal
from app.auth.principal import Principal
from app.db.session import get_async_db

pytestmark = [pytest.mark.unit, pytest.mark.asyncio]

BASE_URL = "https://test"
ADMIN = Principal(subject="a-1", username="dev-admin", roles=frozenset({"wba-admin"}))
USER = Principal(subject="u-1", username="dev-user", roles=frozenset({"wba-user"}))


class _FakeDb:
    async def execute(self, *args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("no database in this test")

    async def commit(self) -> None:
        return None

    async def refresh(self, *args: Any, **kwargs: Any) -> None:
        return None


@pytest_asyncio.fixture(name="client")
async def _client(unauthenticated: Iterator[None]) -> Iterator[httpx.AsyncClient]:
    async def _override_db() -> Any:
        yield _FakeDb()

    app.dependency_overrides[get_async_db] = _override_db
    try:
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url=BASE_URL) as client:
            yield client
    finally:
        app.dependency_overrides.pop(get_async_db, None)


@pytest.fixture(autouse=True)
def _stub_keycloak(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail every Keycloak call unless a test overrides it — no network."""

    def boom(*args: Any, **kwargs: Any) -> Any:
        raise k.KeycloakUnavailableError("stubbed")

    monkeypatch.setattr(k, "_request", boom)
    monkeypatch.setattr(k, "_admin_token", lambda: "tok")


def _as(principal: Principal | None) -> None:
    if principal is None:
        app.dependency_overrides.pop(get_principal, None)
    else:
        app.dependency_overrides[get_principal] = lambda p=principal: p


ROUTES: list[tuple[str, str, dict[str, Any]]] = [
    ("GET", "/api/v1/admin/users/", {}),
    ("POST", "/api/v1/admin/users/", {"json": {"username": "a", "email": "a@b.c", "roles": ["wba-user"]}}),
    ("GET", "/api/v1/admin/users/roles", {}),
    ("GET", "/api/v1/admin/users/abc", {}),
    ("PATCH", "/api/v1/admin/users/abc", {"json": {}}),
    ("PUT", "/api/v1/admin/users/abc/password", {"json": {"password": "hunter2xx"}}),
    ("DELETE", "/api/v1/admin/users/abc", {}),
]


@pytest.mark.parametrize("method,path,extra", ROUTES)
async def test_no_bearer_is_401(client: httpx.AsyncClient, method: str, path: str, extra: dict[str, Any]) -> None:
    _as(None)
    resp = await client.request(method, path, **extra)
    assert resp.status_code == 401, resp.text


@pytest.mark.parametrize("method,path,extra", ROUTES)
async def test_user_role_is_403(client: httpx.AsyncClient, method: str, path: str, extra: dict[str, Any]) -> None:
    _as(USER)
    resp = await client.request(method, path, **extra)
    assert resp.status_code == 403, resp.text


async def test_get_roles_not_shadowed(client: httpx.AsyncClient) -> None:
    _as(ADMIN)
    resp = await client.get("/api/v1/admin/users/roles")
    assert resp.status_code == 200
    assert resp.json() == {"roles": ["wba-admin", "wba-user"]}


async def test_delete_schedules_cleanup_once(client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    _as(ADMIN)
    calls: list[str] = []

    async def _fake_delete(user_id: str, actor: Principal) -> None:
        return None

    from app.api.admin_users.v1 import service as admin_service

    monkeypatch.setattr(admin_service, "delete_user", _fake_delete)
    monkeypatch.setattr(
        "app.api.admin_users.v1.router.cleanup.purge_user_data",
        lambda subject: calls.append(subject),
    )

    resp = await client.delete("/api/v1/admin/users/target-1")
    assert resp.status_code == 204, resp.text
    assert calls == ["target-1"]


async def test_self_delete_is_409(client: httpx.AsyncClient) -> None:
    _as(ADMIN)
    resp = await client.delete("/api/v1/admin/users/a-1")
    assert resp.status_code == 409
    assert resp.json()["detail"]["error"] == "self_delete"


async def test_delete_failure_schedules_no_cleanup(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _as(ADMIN)
    calls: list[str] = []

    async def _boom(user_id: str, actor: Principal) -> None:
        raise k.KeycloakNotFoundError("nope")

    from app.api.admin_users.v1 import service as admin_service

    monkeypatch.setattr(admin_service, "delete_user", _boom)
    monkeypatch.setattr(
        "app.api.admin_users.v1.router.cleanup.purge_user_data",
        lambda subject: calls.append(subject),
    )

    resp = await client.delete("/api/v1/admin/users/target-1")
    assert resp.status_code == 404
    assert calls == []


async def test_keycloak_unavailable_is_503(client: httpx.AsyncClient) -> None:
    _as(ADMIN)
    resp = await client.get("/api/v1/admin/users/target-1")
    assert resp.status_code == 503
    assert resp.json()["detail"]["error"] == "identity_provider_unavailable"


async def test_not_found_maps(monkeypatch: pytest.MonkeyPatch, client: httpx.AsyncClient) -> None:
    _as(ADMIN)

    from app.api.admin_users.v1 import service as admin_service

    async def _get(user_id: str) -> Any:
        raise admin_service.UserNotFoundError("nope")

    async def _update(user_id: str, payload: Any, actor: Principal) -> Any:
        raise admin_service.UserNotFoundError("nope")

    monkeypatch.setattr(admin_service, "get_user", _get)
    monkeypatch.setattr(admin_service, "update_user", _update)

    for method, path, extra in (
        ("GET", "/api/v1/admin/users/x", {}),
        ("PATCH", "/api/v1/admin/users/x", {"json": {}}),
    ):
        resp = await client.request(method, path, **extra)
        assert resp.status_code == 404
        assert resp.json()["detail"]["error"] == "user_not_found"


async def test_update_conflict_is_409(client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """A Keycloak 409 during the write maps to 409 user_exists, never a 500."""
    _as(ADMIN)
    from app.api.admin_users.v1 import query

    monkeypatch.setattr(
        query, "get_user_raw", lambda uid: {"id": uid, "username": "x", "enabled": True}
    )
    monkeypatch.setattr(query, "current_roles", lambda uid: {"wba-user"})
    monkeypatch.setattr(query, "is_service_account", lambda user: False)

    def _boom(user_id: str, body: dict[str, Any]) -> None:
        raise k.KeycloakConflictError("duplicate email")

    monkeypatch.setattr(query, "update_user", _boom)

    resp = await client.patch("/api/v1/admin/users/u1", json={"email": "taken@b.c"})
    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"]["error"] == "user_exists"


async def test_create_policy_error_is_422(client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """A Keycloak 400 on create maps to 422 password_policy, never a 500."""
    _as(ADMIN)
    from app.api.admin_users.v1 import query

    def _boom(body: dict[str, Any]) -> str:
        raise k.KeycloakPolicyError("invalid username")

    monkeypatch.setattr(query, "create_user", _boom)

    resp = await client.post(
        "/api/v1/admin/users/",
        json={"username": "a/b", "email": "a@b.c", "roles": ["wba-user"]},
    )
    assert resp.status_code == 422, resp.text
    assert resp.json()["detail"]["error"] == "password_policy"


async def test_create_warnings_empty(client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    _as(ADMIN)
    from app.api.admin_users.v1 import service as admin_service
    from app.api.admin_users.v1.model import UserCreatedResponse

    async def _create(payload: Any, actor: Principal) -> Any:
        return UserCreatedResponse(
            id="new", username="a", enabled=True, roles=["wba-user"], warnings=[]
        ), []

    monkeypatch.setattr(admin_service, "create_user", _create)
    resp = await client.post(
        "/api/v1/admin/users/", json={"username": "a", "email": "a@b.c", "roles": ["wba-user"]}
    )
    assert resp.status_code == 201
    assert resp.json()["warnings"] == []


async def test_create_warns_when_password_not_set(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _as(ADMIN)
    from app.api.admin_users.v1 import service as admin_service
    from app.api.admin_users.v1.model import UserCreatedResponse

    async def _create(payload: Any, actor: Principal) -> Any:
        return UserCreatedResponse(
            id="new",
            username="a",
            enabled=True,
            roles=["wba-user"],
            warnings=["password_not_set"],
        ), ["password_not_set"]

    monkeypatch.setattr(admin_service, "create_user", _create)
    resp = await client.post(
        "/api/v1/admin/users/", json={"username": "a", "email": "a@b.c", "roles": ["wba-user"]}
    )
    assert resp.status_code == 201
    assert resp.json()["warnings"] == ["password_not_set"]

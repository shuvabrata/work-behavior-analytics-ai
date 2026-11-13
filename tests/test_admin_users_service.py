"""Unit tests for the admin user management service layer.

The ``query`` module is stubbed so no HTTP ever happens.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.api.admin_users.v1 import service
from app.api.admin_users.v1.model import UserCreate, UserUpdate
from app.auth.keycloak_admin import (
    KeycloakConflictError,
    KeycloakNotFoundError,
    KeycloakPolicyError,
)
from app.auth.principal import Principal

pytestmark = [pytest.mark.unit, pytest.mark.asyncio]

ACTOR = Principal(subject="admin-1", username="admin", roles=frozenset({"admin"}))


def _raw(user_id: str = "u1", *, enabled: bool = True, username: str = "alice", **extra: Any) -> dict[str, Any]:
    body: dict[str, Any] = {"id": user_id, "username": username, "enabled": enabled}
    body.update(extra)
    return body


@pytest.fixture(autouse=True)
def _patch_query(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Replace the query module's functions with recorders."""
    state: dict[str, Any] = {
        "create": None,
        "assigned": [],
        "removed": [],
        "passwords": [],
        "deleted": [],
        "updated": [],
        "raw": {},
        "roles": set(),
        "users_with_role": [],
        "listed": ([], 0),
    }

    monkeypatch.setattr(service.query, "list_users", lambda o, l, s: state["listed"])
    monkeypatch.setattr(service.query, "get_user_raw", lambda uid: state["raw"].get(uid, _raw(uid)))
    monkeypatch.setattr(service.query, "is_service_account", lambda u: bool(u.get("serviceAccountClientId")))
    monkeypatch.setattr(service.query, "current_roles", lambda uid: set(state["roles"]))
    monkeypatch.setattr(service.query, "users_with_role", lambda r: state["users_with_role"])

    def _create(body: dict[str, Any]) -> str:
        state["create"] = body
        return "new-id"

    def _set_pw(uid: str, pw: str, temp: bool) -> None:
        state["passwords"].append((uid, pw, temp))

    monkeypatch.setattr(service.query, "create_user", _create)
    monkeypatch.setattr(service.query, "assign_realm_roles", lambda uid, roles: state["assigned"].append((uid, roles)))
    monkeypatch.setattr(service.query, "remove_realm_roles", lambda uid, roles: state["removed"].append((uid, roles)))
    monkeypatch.setattr(service.query, "set_password", _set_pw)
    monkeypatch.setattr(service.query, "update_user", lambda uid, body: state["updated"].append((uid, body)))
    monkeypatch.setattr(service.query, "delete_user", lambda uid: state["deleted"].append(uid))
    monkeypatch.setattr(
        service.query,
        "get_user",
        lambda uid: service.UserSummary(id=uid, username="alice", enabled=True, roles=sorted(state["roles"])),
    )
    return state


async def test_create_rejects_non_assignable_role(_patch_query: Any) -> None:
    with pytest.raises(service.InvalidRoleError):
        await service.create_user(UserCreate(username="a", email="a@b.c", roles=["service"]), ACTOR)


async def test_create_maps_conflict(monkeypatch: pytest.MonkeyPatch, _patch_query: Any) -> None:
    def boom(body: dict[str, Any]) -> str:
        raise KeycloakConflictError("exists")

    monkeypatch.setattr(service.query, "create_user", boom)
    with pytest.raises(service.UserExistsError):
        await service.create_user(UserCreate(username="a", email="a@b.c", roles=["user"]), ACTOR)


async def test_create_with_password_sets_temporary(_patch_query: Any) -> None:
    created, warnings = await service.create_user(
        UserCreate(username="a", email="a@b.c", roles=["user"], password="hunter2xx"), ACTOR
    )
    assert warnings == []
    assert _patch_query["passwords"] == [("new-id", "hunter2xx", True)]


async def test_create_password_failure_warns(monkeypatch: pytest.MonkeyPatch, _patch_query: Any) -> None:
    def boom(uid: str, pw: str, temp: bool) -> None:
        raise KeycloakPolicyError("policy")

    monkeypatch.setattr(service.query, "set_password", boom)
    created, warnings = await service.create_user(
        UserCreate(username="a", email="a@b.c", roles=["user"], password="hunter2xx"), ACTOR
    )
    assert warnings == ["password_not_set"]


async def test_update_removing_last_admin_raises(_patch_query: Any) -> None:
    _patch_query["raw"]["u1"] = _raw("u1")
    _patch_query["roles"] = {"admin"}
    _patch_query["users_with_role"] = [_raw("u1")]
    with pytest.raises(service.LastAdminError):
        await service.update_user("u1", UserUpdate(roles=["user"]), ACTOR)


async def test_update_disabling_last_admin_raises(_patch_query: Any) -> None:
    _patch_query["raw"]["u1"] = _raw("u1")
    _patch_query["roles"] = {"admin"}
    _patch_query["users_with_role"] = [_raw("u1")]
    with pytest.raises(service.LastAdminError):
        await service.update_user("u1", UserUpdate(enabled=False), ACTOR)


async def test_update_disabling_non_admin_ok(_patch_query: Any) -> None:
    _patch_query["raw"]["u1"] = _raw("u1")
    _patch_query["roles"] = {"user"}
    user, disabled_now = await service.update_user("u1", UserUpdate(enabled=False), ACTOR)
    assert disabled_now is True


async def test_disabled_now_only_on_transition(_patch_query: Any) -> None:
    _patch_query["raw"]["u1"] = _raw("u1", enabled=False)
    _patch_query["roles"] = {"user"}
    _user, disabled_now = await service.update_user("u1", UserUpdate(enabled=False), ACTOR)
    assert disabled_now is False


async def test_update_pre_read_not_found(_patch_query: Any) -> None:
    def boom(uid: str) -> dict[str, Any]:
        raise KeycloakNotFoundError("nope")

    import app.api.admin_users.v1.service as s

    orig = s.query.get_user_raw
    s.query.get_user_raw = boom
    try:
        with pytest.raises(service.UserNotFoundError):
            await service.update_user("missing", UserUpdate(enabled=False), ACTOR)
    finally:
        s.query.get_user_raw = orig


async def test_get_not_found(monkeypatch: pytest.MonkeyPatch, _patch_query: Any) -> None:
    def boom(uid: str) -> Any:
        raise KeycloakNotFoundError("nope")

    monkeypatch.setattr(service.query, "get_user", boom)
    with pytest.raises(service.UserNotFoundError):
        await service.get_user("missing")


async def test_role_diff(_patch_query: Any) -> None:
    _patch_query["raw"]["u1"] = _raw("u1")
    _patch_query["roles"] = {"admin"}
    _patch_query["users_with_role"] = [_raw("u1"), _raw("u2")]
    await service.update_user("u1", UserUpdate(roles=["user"]), ACTOR)
    assert ("u1", ["user"]) in _patch_query["assigned"]
    assert ("u1", ["admin"]) in _patch_query["removed"]


async def test_delete_self(_patch_query: Any) -> None:
    actor = Principal(subject="u1", username="alice", roles=frozenset({"admin"}))
    with pytest.raises(service.SelfDeleteError):
        await service.delete_user("u1", actor)


async def test_delete_service_account(_patch_query: Any) -> None:
    _patch_query["raw"]["u2"] = _raw("u2", serviceAccountClientId="internal")
    actor = Principal(subject="admin", username="admin", roles=frozenset({"admin"}))
    with pytest.raises(service.ServiceAccountError):
        await service.delete_user("u2", actor)


async def test_delete_last_admin(_patch_query: Any) -> None:
    _patch_query["raw"]["u1"] = _raw("u1")
    _patch_query["roles"] = {"admin"}
    _patch_query["users_with_role"] = [_raw("u1")]
    actor = Principal(subject="other", username="other", roles=frozenset({"admin"}))
    with pytest.raises(service.LastAdminError):
        await service.delete_user("u1", actor)


async def test_list_passes_through_query_page(monkeypatch: pytest.MonkeyPatch, _patch_query: Any) -> None:
    from app.api.admin_users.v1.model import UserSummary

    listed = (
        [UserSummary(id="u1", username="alice", enabled=True, roles=["user"])],
        1,
    )
    monkeypatch.setattr(service.query, "list_users", lambda o, l, s: listed)
    response = await service.list_users(0, 25, None)
    assert response.total == 1
    assert len(response.users) == 1


async def test_list_total_excludes_service_accounts(monkeypatch: pytest.MonkeyPatch, _patch_query: Any) -> None:
    """The query layer filters service accounts and corrects the total."""
    monkeypatch.undo()
    from app.api.admin_users.v1 import query

    class _FakeAdmin:
        @staticmethod
        def list_users(offset: int, limit: int, search: str | None) -> tuple[list[dict[str, Any]], int]:
            users = [_raw(f"u{i}") for i in range(24)] + [_raw("sa", username="service-account-x")]
            return users, 27

        @staticmethod
        def count_users(search: str | None) -> int:
            return 2

        @staticmethod
        def realm_roles(uid: str) -> list[str]:
            return ["user"]

    monkeypatch.setattr(query, "keycloak_admin", _FakeAdmin)
    users, total = query.list_users(0, 25, None)
    assert total == 25
    assert len(users) == 24


def _recording_admin(
    page: list[dict[str, Any]],
    count: int,
    service_account_count: int,
    count_calls: list[str | None],
) -> type:
    """Build a fake ``keycloak_admin`` that records ``count_users`` calls."""

    class _FakeAdmin:
        @staticmethod
        def list_users(offset: int, limit: int, search: str | None) -> tuple[list[dict[str, Any]], int]:
            return page, count

        @staticmethod
        def count_users(search: str | None) -> int:
            count_calls.append(search)
            return service_account_count

        @staticmethod
        def realm_roles(uid: str) -> list[str]:
            return ["user"]

    return _FakeAdmin


async def test_list_total_under_search_is_not_negative(monkeypatch: pytest.MonkeyPatch, _patch_query: Any) -> None:
    """A search whose only match is a service account must not yield a negative total."""
    monkeypatch.undo()
    from app.api.admin_users.v1 import query

    count_calls: list[str | None] = []
    monkeypatch.setattr(
        query,
        "keycloak_admin",
        _recording_admin([_raw("sa", username="service-account-x")], 1, 3, count_calls),
    )
    users, total = query.list_users(0, 25, "service")
    assert total == 1
    assert users == []
    assert count_calls == []


async def test_list_total_under_search_covers_all_matches(
    monkeypatch: pytest.MonkeyPatch, _patch_query: Any
) -> None:
    """A search-scoped count must not be reduced by the global service-account count."""
    monkeypatch.undo()
    from app.api.admin_users.v1 import query

    count_calls: list[str | None] = []
    page = [_raw(f"u{i}") for i in range(25)]
    monkeypatch.setattr(query, "keycloak_admin", _recording_admin(page, 26, 3, count_calls))
    users, total = query.list_users(0, 25, "a")
    assert total == 26
    assert len(users) == 25
    assert count_calls == []


async def test_list_total_clamps_and_skips_global_count(
    monkeypatch: pytest.MonkeyPatch, _patch_query: Any
) -> None:
    """With no search term the total clamps at zero and the global count is used."""
    monkeypatch.undo()
    from app.api.admin_users.v1 import query

    count_calls: list[str | None] = []
    monkeypatch.setattr(
        query,
        "keycloak_admin",
        _recording_admin([_raw("u1")], 1, 3, count_calls),
    )
    users, total = query.list_users(0, 25, None)
    assert total == 0
    assert len(users) == 1
    assert count_calls == ["service-account-"]


def test_list_assignable_roles() -> None:
    assert service.list_assignable_roles().roles == ["admin", "user"]

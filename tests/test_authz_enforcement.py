"""Per-role enforcement across representative routes of the real app.

Driven through ``httpx.ASGITransport`` against ``app.api_main.app`` with the
autouse admin override cleared, so ``get_principal`` is replaced per case and the
router-level / route-level dependencies actually run.

The reviewed expectation for each cell is a 401 (no credential), an exact 403
(credential lacks the role) or "allowed". Allowed cells assert the status is
**not** 401/403 rather than a specific success code: most handlers would need
real data or a database, and the property under test is authorization, not the
handler body.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import httpx
import pytest
import pytest_asyncio

from app.api_main import app
from app.auth.dependencies import get_principal
from app.auth.principal import Principal
from app.db.session import get_async_db

pytestmark = [pytest.mark.unit, pytest.mark.asyncio]

BASE_URL = "https://test"
COMMAND_ID = "00000000-0000-0000-0000-000000000001"

_ROLE_PRINCIPALS = {
    "user": Principal(subject="u-1", username="dev-user", roles=frozenset({"wba-user"})),
    "admin": Principal(subject="a-1", username="dev-admin", roles=frozenset({"wba-admin"})),
    "service": Principal(
        subject="s-1", username="wba-internal", roles=frozenset({"wba-service"})
    ),
}


class _FakeDb:
    """A session stub — authorization runs before any query matters."""

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


CASES: list[tuple[str, str, dict[str, Any]]] = [
    ("GET", "/api/health", {}),
    ("GET", "/api/v1/search", {"params": {"q": "x"}}),
    ("GET", "/api/v1/settings/", {}),
    ("GET", "/api/v1/chats/one", {}),
    ("PATCH", f"/api/v1/settings/HTTP_REQUEST_TIMEOUT", {}),
    ("POST", "/api/v1/commands/", {}),
    ("GET", "/api/v1/commands/", {}),
    ("PATCH", f"/api/v1/commands/{COMMAND_ID}/status", {}),
    ("GET", "/api/v1/settings/runtime-snapshot", {}),
    ("GET", "/api/v1/connectors/github/configs", {"params": {"include_secrets": "true"}}),
    ("GET", "/api/v1/connectors/github/configs", {}),
    ("PUT", "/api/v1/queries/catalog/ns/slug", {}),
    ("POST", "/api/v1/graph-themes/1/set-default", {}),
]

# (method, path, params) -> {role: "401" | "403" | "allowed"}
EXPECTED: dict[tuple[str, str, str], dict[str, str]] = {
    ("GET", "/api/health", ""): {"none": "200", "user": "200", "admin": "200", "service": "200"},
    ("GET", "/api/v1/search", "q=x"): {
        "none": "401", "user": "allowed", "admin": "allowed", "service": "allowed",
    },
    ("GET", "/api/v1/settings/", ""): {
        "none": "401", "user": "allowed", "admin": "allowed", "service": "allowed",
    },
    ("GET", "/api/v1/chats/one", ""): {
        "none": "401", "user": "allowed", "admin": "allowed", "service": "allowed",
    },
    ("PATCH", "/api/v1/settings/HTTP_REQUEST_TIMEOUT", ""): {
        "none": "401", "user": "403", "admin": "allowed", "service": "403",
    },
    ("POST", "/api/v1/commands/", ""): {
        "none": "401", "user": "403", "admin": "allowed", "service": "allowed",
    },
    ("GET", "/api/v1/commands/", ""): {
        "none": "401", "user": "allowed", "admin": "allowed", "service": "allowed",
    },
    ("PATCH", f"/api/v1/commands/{COMMAND_ID}/status", ""): {
        "none": "401", "user": "403", "admin": "403", "service": "allowed",
    },
    ("GET", "/api/v1/settings/runtime-snapshot", ""): {
        "none": "401", "user": "allowed", "admin": "allowed", "service": "allowed",
    },
    ("GET", "/api/v1/connectors/github/configs", "include_secrets=true"): {
        "none": "401", "user": "403", "admin": "allowed", "service": "allowed",
    },
    ("GET", "/api/v1/connectors/github/configs", ""): {
        "none": "401", "user": "allowed", "admin": "allowed", "service": "allowed",
    },
    ("PUT", "/api/v1/queries/catalog/ns/slug", ""): {
        "none": "401", "user": "403", "admin": "allowed", "service": "403",
    },
    ("POST", "/api/v1/graph-themes/1/set-default", ""): {
        "none": "401", "user": "403", "admin": "allowed", "service": "403",
    },
}


def _params_key(params: dict[str, Any]) -> str:
    pairs = params.get("params", {})
    return "&".join(f"{k}={v}" for k, v in sorted(pairs.items()))


@pytest.mark.parametrize("method,path,extra", CASES)
@pytest.mark.parametrize("role", ["none", "user", "admin", "service"])
async def test_role_matrix(
    client: httpx.AsyncClient,
    method: str,
    path: str,
    extra: dict[str, Any],
    role: str,
) -> None:
    """Each (route, role) cell matches the reviewed expectation."""
    if role == "none":
        app.dependency_overrides.pop(get_principal, None)
    else:
        principal = _ROLE_PRINCIPALS[role]
        app.dependency_overrides[get_principal] = lambda p=principal: p

    response = await client.request(method, path, **extra)

    expected = EXPECTED[(method, path, _params_key(extra))][role]
    if expected == "allowed":
        assert response.status_code not in (401, 403), (
            f"{role} on {method} {path} was refused: {response.status_code} {response.text[:200]}"
        )
    else:
        assert response.status_code == int(expected), (
            f"{role} on {method} {path}: expected {expected}, "
            f"got {response.status_code} {response.text[:200]}"
        )

"""``?include_secrets=true`` is gated to admin or service, not just masked.

Drives ``GET /api/v1/connectors/github/configs`` through ``httpx.ASGITransport``
against the real app. The ``connectors.v1.query`` layer is stubbed to return one
row carrying an encrypted access token, so the assertion is about which value the
service chose to emit (plaintext vs ``********``), not about the database.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from typing import Any

import httpx
import pytest
import pytest_asyncio
from cryptography.fernet import Fernet

from app.api.connectors.v1 import query as connectors_query
from app.api.connectors.v1 import service as connectors_service
from app.api_main import app
from app.auth.dependencies import get_principal
from app.auth.principal import Principal
from app.db.session import get_async_db
from app.settings import settings

pytestmark = [pytest.mark.unit, pytest.mark.asyncio]

BASE_URL = "https://test"
_SECRET = "super-secret-token"
_MASKED = connectors_service._mask("anything")  # pylint: disable=protected-access

_PRINCIPALS = {
    "user": Principal(subject="u-1", username="dev-user", roles=frozenset({"wba-user"})),
    "admin": Principal(subject="a-1", username="dev-admin", roles=frozenset({"wba-admin"})),
    "service": Principal(
        subject="s-1", username="wba-internal", roles=frozenset({"wba-service"})
    ),
}


class _Row:
    """A github config row with an encrypted access token."""

    id = 1
    url = "https://github.com/example"
    encrypted_access_token = ""
    search_filters: dict[str, Any] = {}
    branch_name_patterns: list[str] = []
    extraction_sources: list[str] = []
    created_at = None
    updated_at = None
    enabled = True


class _Connector:
    id = 1
    connector_type = "github"


class _FakeDb:
    async def execute(self, *args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("query layer is stubbed")

    async def commit(self) -> None:
        return None


@pytest_asyncio.fixture(name="client")
async def _client(
    monkeypatch: pytest.MonkeyPatch, unauthenticated: Iterator[None]
) -> Iterator[httpx.AsyncClient]:
    monkeypatch.setattr(
        settings, "CONNECTOR_ENCRYPTION_KEY", Fernet.generate_key().decode()
    )
    row = _Row()
    row.encrypted_access_token = connectors_service.encrypt(_SECRET)

    async def _get_connector(_db: Any, _connector_type: str) -> Any:
        return _Connector()

    async def _get_configs(_db: Any, _connector_type: str) -> list[Any]:
        return [row]

    monkeypatch.setattr(connectors_query, "get_connector", _get_connector)
    monkeypatch.setattr(connectors_query, "get_configs", _get_configs)

    async def _override_db() -> Any:
        yield _FakeDb()

    app.dependency_overrides[get_async_db] = _override_db
    try:
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url=BASE_URL) as client:
            yield client
    finally:
        app.dependency_overrides.pop(get_async_db, None)


def _as(role: str) -> None:
    principal = _PRINCIPALS[role]
    app.dependency_overrides[get_principal] = lambda p=principal: p


async def test_admin_include_secrets_returns_plaintext(client: httpx.AsyncClient) -> None:
    _as("admin")

    response = await client.get(
        "/api/v1/connectors/github/configs", params={"include_secrets": "true"}
    )

    assert response.status_code == 200
    assert response.json()[0]["access_token"] == _SECRET


async def test_service_include_secrets_is_allowed(client: httpx.AsyncClient) -> None:
    """The producers fetch this with a service token — it must not 403."""
    _as("service")

    response = await client.get(
        "/api/v1/connectors/github/configs", params={"include_secrets": "true"}
    )

    assert response.status_code == 200
    assert response.json()[0]["access_token"] == _SECRET


async def test_user_include_secrets_is_403_and_logged(
    client: httpx.AsyncClient, caplog: pytest.LogCaptureFixture
) -> None:
    _as("user")

    with caplog.at_level(logging.WARNING):
        response = await client.get(
            "/api/v1/connectors/github/configs", params={"include_secrets": "true"}
        )

    assert response.status_code == 403
    assert response.json()["detail"]["error"] == "forbidden"
    assert "u-1" in caplog.text or "dev-user" in caplog.text


async def test_user_without_parameter_sees_masked_value(
    client: httpx.AsyncClient,
) -> None:
    _as("user")

    response = await client.get("/api/v1/connectors/github/configs")

    assert response.status_code == 200
    assert response.json()[0]["access_token"] == _MASKED
    assert _SECRET not in response.text

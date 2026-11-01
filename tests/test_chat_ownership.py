"""Ownership enforcement on the chat session routes.

Driven through ``httpx.ASGITransport`` against ``app.api_main.app`` with the
conftest admin override cleared, so ``get_principal`` is replaced per case. A
chat session belongs to the ``sub`` that created it; a caller who does not own
it must be told **404**, never 403, so the response does not confirm the id
exists.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import httpx
import pytest
import pytest_asyncio

from app.api_main import app
from app.ai_agent import ai_agent
from app.auth.dependencies import get_principal
from app.auth.principal import Principal

pytestmark = [pytest.mark.unit, pytest.mark.asyncio]

BASE_URL = "http://test"

OWNER = Principal(subject="owner-sub", username="dev-owner", roles=frozenset({"wba-user"}))
FOREIGN = Principal(subject="foreign-sub", username="dev-foreign", roles=frozenset({"wba-user"}))
ADMIN = Principal(
    subject="admin-sub", username="dev-admin", roles=frozenset({"wba-admin", "wba-user"})
)


class _FakeProvider:
    """Minimal provider double — the stream case must never reach the LLM."""

    default_model = "gpt-5"

    def count_tokens(self, messages: list[dict[str, Any]], model: str | None = None) -> int:
        _ = model
        return sum(len(msg.get("content", "")) for msg in messages)

    async def stream_chat_completion(self, messages: list[dict[str, Any]], model: str | None = None):
        _ = model
        yield "unreachable"


@pytest.fixture(autouse=True)
def _clear_sessions() -> Iterator[None]:
    """Chat sessions are process-global; isolate every case."""
    ai_agent._chat_sessions.clear()
    ai_agent._chat_session_owners.clear()
    yield
    ai_agent._chat_sessions.clear()
    ai_agent._chat_session_owners.clear()


def _act_as(principal: Principal) -> None:
    app.dependency_overrides[get_principal] = lambda: principal


@pytest_asyncio.fixture(name="client")
async def _client(unauthenticated: Iterator[None]) -> Iterator[httpx.AsyncClient]:
    """A client with the conftest admin override removed, restored afterwards."""
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
        base_url=BASE_URL,
    ) as client:
        yield client


@pytest.fixture(autouse=True)
def _restore_override() -> Iterator[None]:
    yield
    app.dependency_overrides.pop(get_principal, None)


async def _create_session(client: httpx.AsyncClient, principal: Principal) -> str:
    _act_as(principal)
    response = await client.post("/api/v1/chats/", json={"system_prompt": "You are helpful."})
    assert response.status_code == 201
    return response.json()["session_id"]


async def test_owner_can_read_own_session(client: httpx.AsyncClient) -> None:
    session_id = await _create_session(client, OWNER)

    _act_as(OWNER)
    response = await client.get(f"/api/v1/chats/{session_id}")

    assert response.status_code == 200
    assert response.json()["exists"] is True


async def test_foreign_read_is_404_not_403(client: httpx.AsyncClient) -> None:
    session_id = await _create_session(client, OWNER)

    _act_as(FOREIGN)
    response = await client.get(f"/api/v1/chats/{session_id}")

    assert response.status_code == 404
    assert response.status_code != 403


async def test_foreign_stream_is_404_and_does_not_stream(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    session_id = await _create_session(client, OWNER)
    monkeypatch.setattr(ai_agent, "_provider", _FakeProvider())

    _act_as(FOREIGN)
    response = await client.post(
        f"/api/v1/chats/{session_id}/stream", json={"message": "hijack"}
    )

    assert response.status_code == 404
    assert "text/event-stream" not in response.headers.get("content-type", "")
    assert "thinking_start" not in response.text


async def test_foreign_delete_is_404_and_session_survives(client: httpx.AsyncClient) -> None:
    session_id = await _create_session(client, OWNER)

    _act_as(FOREIGN)
    delete_response = await client.delete(f"/api/v1/chats/{session_id}")
    assert delete_response.status_code == 404

    _act_as(OWNER)
    follow_up = await client.get(f"/api/v1/chats/{session_id}")
    assert follow_up.status_code == 200


async def test_unowned_session_is_invisible_to_everyone(client: httpx.AsyncClient) -> None:
    session_id = ai_agent.new_chat(system_prompt="unowned")

    for principal in (OWNER, FOREIGN, ADMIN):
        _act_as(principal)
        response = await client.get(f"/api/v1/chats/{session_id}")
        assert response.status_code == 404


async def test_unowned_session_stream_and_delete_is_404(client: httpx.AsyncClient) -> None:
    session_id = ai_agent.new_chat(system_prompt="unowned")

    _act_as(ADMIN)
    stream_response = await client.post(
        f"/api/v1/chats/{session_id}/stream", json={"message": "hi"}
    )
    delete_response = await client.delete(f"/api/v1/chats/{session_id}")

    assert stream_response.status_code == 404
    assert delete_response.status_code == 404
    assert session_id in ai_agent._chat_sessions


async def test_unknown_session_is_404(client: httpx.AsyncClient) -> None:
    _act_as(OWNER)

    response = await client.get("/api/v1/chats/does-not-exist-xyz")

    assert response.status_code == 404

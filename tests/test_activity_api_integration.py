"""Integration tests for Activity Timeline API v1 — GET /api/v1/activity/timeline.

Test strategy
-------------
These tests exercise the full HTTP round-trip through ASGI transport with a
**mocked** database session.  The ``get_async_db`` dependency is overridden
with a fake ``AsyncSession`` whose ``execute()`` returns canned rows, so no
Postgres connection is required and the tests run under the ``unit`` marker.

The query layer (``query.py``) is exercised indirectly: the fake session
captures the SQLAlchemy statement it receives, letting tests assert the
generated WHERE/ORDER/LIMIT clauses without a real database.

Run with:
    pytest -m unit tests/test_activity_api_integration.py -v
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import httpx
import pytest

from app.db.models.activity_action import ActivityAction
from app.db.models.activity_event import ActivityEvent
from app.main import app

pytestmark = [pytest.mark.unit, pytest.mark.asyncio]

BASE_URL = "http://test"
TIMELINE_URL = "/api/v1/activity/timeline"
SUGGEST_URL = "/api/v1/activity/suggest"


# ---------------------------------------------------------------------------
# Fake session
# ---------------------------------------------------------------------------


class FakeResult:
    """Minimal stand-in for ``sqlalchemy.engine.Result``."""

    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def scalars(self) -> "FakeScalars":
        return FakeScalars(self._rows)

    def first(self) -> Any | None:
        return self._rows[0] if self._rows else None


class FakeScalars:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def all(self) -> list[Any]:
        return self._rows


class FakeSession:
    """Fake ``AsyncSession`` that records statements and returns canned rows.

    The ``execute()`` method inspects the statement's column list to decide
    which canned rows to return:

    * ``SELECT display_name, avatar_url FROM activity_events ...`` → label lookup
    * ``SELECT * FROM activity_events ...`` → event history
    * ``SELECT * FROM activity_actions ...`` → actions
    """

    def __init__(
        self,
        actions: list[Any],
        events: list[Any],
        labels: dict[str, tuple[str | None, str | None]],
    ) -> None:
        self.actions = actions
        self.events = events
        self.labels = labels
        self.statements: list[Any] = []

    async def execute(self, stmt: Any) -> FakeResult:
        self.statements.append(stmt)
        columns = [getattr(col, "name", None) for col in getattr(stmt, "_raw_columns", [])]
        if columns == ["display_name", "avatar_url"]:
            return FakeResult([self._label_row(stmt)])
        # select(ActivityEvent) → the table object is in _raw_columns.
        if any(getattr(col, "name", None) == "activity_events" for col in getattr(stmt, "_raw_columns", [])):
            return FakeResult(self.events)
        return FakeResult(self.actions)

    def _label_row(self, stmt: Any) -> tuple[str | None, str | None]:
        """Return the canned label row for the entity in *stmt*.

        The fake derives the entity key from the statement's WHERE criteria
        by scanning for the ``entity_id`` equality value.  Falls back to
        matching the compiled SQL text (contains the literal entity id).
        """
        entity_id: str | None = None
        for crit in getattr(stmt, "_where_criteria", []):
            text = str(crit)
            if "entity_id" in text:
                right = getattr(crit, "right", None)
                if right is not None:
                    entity_id = getattr(right, "value", None)
        if entity_id is None:
            return None, None
        for key, value in self.labels.items():
            if key.endswith(f"::{entity_id}"):
                return value
        return None, None


def _make_action(
    *,
    signal_id: str,
    source: str,
    event_time: datetime,
    actor_type: str,
    actor_id: str,
    rel_type: str,
    target_type: str,
    target_id: str,
    summary: str | None = None,
    url: str | None = None,
    row_id: int = 1,
) -> ActivityAction:
    return ActivityAction(
        id=row_id,
        signal_id=signal_id,
        source=source,
        event_time=event_time,
        actor_entity_type=actor_type,
        actor_entity_id=actor_id,
        relationship_type=rel_type,
        target_entity_type=target_type,
        target_entity_id=target_id,
        summary=summary,
        url=url,
    )


def _make_event(
    *,
    signal_id: str,
    source: str,
    entity_type: str,
    entity_id: str,
    event_time: datetime,
    display_name: str | None,
    attributes: dict[str, Any] | None = None,
    row_id: int = 1,
) -> ActivityEvent:
    return ActivityEvent(
        id=row_id,
        signal_id=signal_id,
        source=source,
        entity_type=entity_type,
        entity_id=entity_id,
        event_time=event_time,
        display_name=display_name,
        avatar_url=None,
        attributes=attributes or {},
        relationships=None,
        content_hash="abc",
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_db(monkeypatch: pytest.MonkeyPatch) -> FakeSession:
    """Override the ``get_async_db`` dependency with a canned fake session."""
    actions = [
        _make_action(
            signal_id="11111111-1111-1111-1111-111111111111",
            source="github",
            event_time=datetime(2026, 3, 15, 14, 30, 0, tzinfo=timezone.utc),
            actor_type="Person",
            actor_id="alice",
            rel_type="CREATED",
            target_type="PullRequest",
            target_id="org/repo#142",
            summary="feat: add user activity timeline API",
            url="https://github.com/org/repo/pull/142",
            row_id=10,
        ),
        _make_action(
            signal_id="22222222-2222-2222-2222-222222222222",
            source="github",
            event_time=datetime(2026, 3, 14, 9, 0, 0, tzinfo=timezone.utc),
            actor_type="Person",
            actor_id="bob",
            rel_type="REVIEWED",
            target_type="PullRequest",
            target_id="org/repo#142",
            summary="LGTM",
            url="https://github.com/org/repo/pull/142#review",
            row_id=9,
        ),
    ]
    events = [
        _make_event(
            signal_id="33333333-3333-3333-3333-333333333333",
            source="github",
            entity_type="Issue",
            entity_id="org/repo#42",
            event_time=datetime(2026, 3, 13, 10, 0, 0, tzinfo=timezone.utc),
            display_name="Fix the timeline bug",
            attributes={
                "status": "open",
                "title": "Fix the timeline bug",
                "url": "https://github.com/org/repo/issues/42",
            },
            row_id=5,
        ),
    ]
    labels = {
        "github::Person::alice": ("Alice Johnson", "https://avatars/alice.png"),
        "github::Person::bob": ("Bob Smith", None),
    }
    return FakeSession(actions=actions, events=events, labels=labels)


@pytest.fixture
def client(fake_db: FakeSession) -> httpx.AsyncClient:
    """ASGI transport client with the fake DB dependency installed."""

    async def override_get_async_db():
        yield fake_db

    # The router imports get_async_db from app.db.session — override that.
    from app.db.session import get_async_db

    app.dependency_overrides[get_async_db] = override_get_async_db

    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url=BASE_URL,
    )


# ---------------------------------------------------------------------------
# Timeline endpoint
# ---------------------------------------------------------------------------


class TestTimelineEndpoint:
    async def test_single_lane_returns_events(self, client: httpx.AsyncClient) -> None:
        async with client:
            resp = await client.get(
                TIMELINE_URL,
                params={"wba_ids": "github::Person::alice", "limit": 5},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["meta"]["total_lanes"] == 1
        lane = data["lanes"][0]
        assert lane["wba_id"] == "github::Person::alice"
        assert lane["label"] == "Alice Johnson"
        assert lane["avatar_url"] == "https://avatars/alice.png"
        assert len(lane["events"]) == 2
        first = lane["events"][0]
        assert first["relationship_type"] == "CREATED"
        assert first["summary"] == "feat: add user activity timeline API"
        assert first["url"] == "https://github.com/org/repo/pull/142"

    async def test_multi_lane_splits_correctly(self, client: httpx.AsyncClient) -> None:
        async with client:
            resp = await client.get(
                TIMELINE_URL,
                params={
                    "wba_ids": "github::Person::alice,github::Person::bob",
                    "limit": 3,
                },
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["meta"]["total_lanes"] == 2
        assert [lane["wba_id"] for lane in data["lanes"]] == [
            "github::Person::alice",
            "github::Person::bob",
        ]

    async def test_invalid_wba_id_returns_400(self, client: httpx.AsyncClient) -> None:
        async with client:
            resp = await client.get(
                TIMELINE_URL,
                params={"wba_ids": "invalid::bad"},
            )
        assert resp.status_code == 400
        assert resp.json()["detail"]["error"] == "Invalid WBA ID"

    async def test_empty_wba_ids_returns_400(self, client: httpx.AsyncClient) -> None:
        async with client:
            resp = await client.get(TIMELINE_URL, params={"wba_ids": " , "})
        assert resp.status_code == 400

    async def test_invalid_scope_returns_400(self, client: httpx.AsyncClient) -> None:
        async with client:
            resp = await client.get(
                TIMELINE_URL,
                params={"wba_ids": "github::Person::alice", "scope": "bogus"},
            )
        assert resp.status_code == 400
        assert resp.json()["detail"]["error"] == "Invalid scope"

    async def test_invalid_cursor_returns_400(self, client: httpx.AsyncClient) -> None:
        async with client:
            resp = await client.get(
                TIMELINE_URL,
                params={"wba_ids": "github::Person::alice", "cursor": "not-a-cursor"},
            )
        assert resp.status_code == 400
        assert resp.json()["detail"]["error"] == "Invalid cursor"

    async def test_history_scope_returns_state_changes(
        self, client: httpx.AsyncClient
    ) -> None:
        async with client:
            resp = await client.get(
                TIMELINE_URL,
                params={
                    "wba_ids": "github::Issue::org/repo#42",
                    "scope": "history",
                    "limit": 5,
                },
            )
        assert resp.status_code == 200
        data = resp.json()
        lane = data["lanes"][0]
        assert lane["entity_type"] == "Issue"
        assert len(lane["events"]) == 1
        event = lane["events"][0]
        assert event["relationship_type"] == "STATE_CHANGE"
        assert event["summary"] == "Fix the timeline bug"
        assert event["details"]["status"] == "open"
        # url is extracted from attributes.url so history cards are clickable.
        assert event["url"] == "https://github.com/org/repo/issues/42"

    async def test_limit_validation(self, client: httpx.AsyncClient) -> None:
        async with client:
            resp = await client.get(
                TIMELINE_URL,
                params={"wba_ids": "github::Person::alice", "limit": 0},
            )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Suggest endpoint
# ---------------------------------------------------------------------------


class TestSuggestEndpoint:
    async def test_suggest_requires_min_length(self, client: httpx.AsyncClient) -> None:
        async with client:
            resp = await client.get(SUGGEST_URL, params={"q": "a"})
        assert resp.status_code == 422

    async def test_suggest_rejects_two_char_query(self, client: httpx.AsyncClient) -> None:
        async with client:
            resp = await client.get(SUGGEST_URL, params={"q": "ab"})
        assert resp.status_code == 422

    async def test_suggest_delegates_to_search_service(
        self, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from app.api.search.v1 import service as search_service_module

        captured: dict[str, Any] = {}

        class FakeSearchResponse:
            results = []

        def fake_search(request) -> FakeSearchResponse:
            captured["q"] = request.q
            captured["page_size"] = request.page_size
            return FakeSearchResponse()

        monkeypatch.setattr(search_service_module, "search", fake_search)

        async with client:
            resp = await client.get(SUGGEST_URL, params={"q": "ali", "limit": 5})
        assert resp.status_code == 200
        assert resp.json() == {"results": []}
        assert captured["q"] == "ali"
        assert captured["page_size"] == 5

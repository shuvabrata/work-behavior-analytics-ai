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

import re
from datetime import datetime, timezone
from typing import Any

import httpx
import pytest
from sqlalchemy.sql import visitors

from app.api.activity.v1 import service
from app.api.activity.v1.service import _decode_cursor
from app.db.models.activity_action import ActivityAction
from app.db.models.activity_event import ActivityEvent
from app.api_main import app
from app.settings import settings

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

    def all(self) -> list[Any]:
        return self._rows

    def scalars(self) -> "FakeScalars":
        return FakeScalars(self._rows)

    def first(self) -> Any | None:
        return self._rows[0] if self._rows else None


class FakeScalars:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def all(self) -> list[Any]:
        # Mirror real SQLAlchemy semantics: ``.scalars()`` yields only the FIRST
        # column of each row.  The actions branch returns ``(action, name)``
        # pairs, so under ``.scalars()`` the name is dropped — exactly the silent
        # production regression this fake must be able to catch.
        return [
            row[0]
            if isinstance(row, tuple) and row and isinstance(row[0], ActivityAction)
            else row
            for row in self._rows
        ]


class FakeSession:
    """Fake ``AsyncSession`` that records statements and returns canned rows.

    The ``execute()`` method inspects the statement's column list to decide
    which canned rows to return:

    * ``SELECT display_name, avatar_url FROM activity_events ...`` → label lookup
    * ``SELECT * FROM activity_events ...`` → event history
    * ``SELECT activity_actions.*, <related_name subquery> ...`` → actions

    The actions branch returns ``(action, related_name)`` **pairs** — the
    service unpacks them (``for action, related_name in action_rows``), so a
    bare ``ActivityAction`` list here would fail with ``ValueError``.
    """

    def __init__(
        self,
        actions: list[tuple[ActivityAction, str | None]],
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

        The fake derives the entity key from the statement's WHERE criteria by
        walking the (possibly nested) criteria for the ``entity_id`` equality
        value.  The identity predicate is an ``or_`` of ``and_`` groups, so the
        comparison is not a top-level criterion.
        """
        entity_id: str | None = None
        for crit in getattr(stmt, "_where_criteria", []):
            for element in visitors.iterate(crit):
                left = getattr(element, "left", None)
                if getattr(left, "name", None) == "entity_id":
                    right = getattr(element, "right", None)
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
    target_source: str | None = None,
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
        target_source=target_source,
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


def _compiled_sql(stmt: Any) -> str:
    """Return *stmt* as whitespace-normalised SQL text for substring assertions."""
    return re.sub(r"\s+", "", str(stmt.compile(compile_kwargs={"literal_binds": True})))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_db(monkeypatch: pytest.MonkeyPatch) -> FakeSession:
    """Override the ``get_async_db`` dependency with a canned fake session."""
    # (action, related_name) pairs — the shape ``fetch_actions_for_entity`` now
    # returns.  One row has a resolved name and one has ``None`` so both the
    # resolved path and the raw-id fallback stay pinned.
    actions: list[tuple[ActivityAction, str | None]] = [
        (
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
            "feat: add user activity timeline API",
        ),
        (
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
            None,
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


@pytest.fixture(autouse=True)
def _stub_person_identity_resolution(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the unit gate offline — Person lanes must not reach Neo4j here.

    The repo's local ``.env`` ships ``NEO4J_AI_LOOKUP_ENABLED=true``; without this stub the
    Person-lane tests would attempt a real ``verify_connectivity()`` from inside
    ``-m unit``. Stub once per module rather than in each test.
    """

    async def _no_identities(_person_wba_id: str) -> list[tuple[str, str]]:
        return []

    monkeypatch.setattr(service, "resolve_person_identities", _no_identities)


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
        # History has no other side, so the sibling's canonical id is None.
        assert event["related_wba_id"] is None

    async def test_full_page_emits_cursor_matching_last_row(
        self, client: httpx.AsyncClient, fake_db: FakeSession
    ) -> None:
        """A full page echoes a cursor that decodes to the last row's key."""
        limit = len(fake_db.actions)
        async with client:
            resp = await client.get(
                TIMELINE_URL,
                params={"wba_ids": "github::Person::alice", "limit": limit},
            )
        assert resp.status_code == 200
        lane = resp.json()["lanes"][0]
        assert isinstance(lane["next_cursor"], str)
        assert lane["next_cursor"]
        last_action = fake_db.actions[-1][0]
        decoded_time, decoded_id = _decode_cursor(lane["next_cursor"])
        assert decoded_time == last_action.event_time
        assert decoded_id == last_action.id

    async def test_second_page_sends_keyset_predicate(
        self, client: httpx.AsyncClient, fake_db: FakeSession
    ) -> None:
        """A page-2 request carries the row-value keyset predicate to the query."""
        limit = len(fake_db.actions)
        async with client:
            page1 = await client.get(
                TIMELINE_URL,
                params={"wba_ids": "github::Person::alice", "limit": limit},
            )
            assert page1.status_code == 200
            cursor = page1.json()["lanes"][0]["next_cursor"]
            assert cursor
            page2 = await client.get(
                TIMELINE_URL,
                params={
                    "wba_ids": "github::Person::alice",
                    "limit": limit,
                    "cursor": cursor,
                },
            )
        assert page2.status_code == 200
        sql = _compiled_sql(fake_db.statements[-1])
        # Row-value comparison: (event_time, id) < (cursor_time, cursor_id).
        assert "(activity_actions.event_time,activity_actions.id)<(" in sql

    async def test_short_page_omits_cursor(
        self, client: httpx.AsyncClient, fake_db: FakeSession
    ) -> None:
        """A page shorter than the limit emits no cursor."""
        async with client:
            resp = await client.get(
                TIMELINE_URL,
                params={"wba_ids": "github::Person::alice", "limit": 5},
            )
        assert resp.status_code == 200
        lane = resp.json()["lanes"][0]
        assert len(lane["events"]) == len(fake_db.actions)
        assert lane["next_cursor"] is None

    async def test_empty_lane_omits_cursor(
        self, client: httpx.AsyncClient, fake_db: FakeSession
    ) -> None:
        """An empty lane returns no events and no cursor."""
        fake_db.actions = []
        async with client:
            resp = await client.get(
                TIMELINE_URL,
                params={"wba_ids": "github::Person::alice", "limit": 5},
            )
        assert resp.status_code == 200
        lane = resp.json()["lanes"][0]
        assert lane["events"] == []
        assert lane["next_cursor"] is None

    async def test_history_scope_uses_row_value_predicate(
        self, client: httpx.AsyncClient, fake_db: FakeSession
    ) -> None:
        """History scope sends the row-value predicate against activity_events."""
        wba_id = "github::Issue::org/repo#42"
        limit = len(fake_db.events)
        async with client:
            page1 = await client.get(
                TIMELINE_URL,
                params={"wba_ids": wba_id, "scope": "history", "limit": limit},
            )
            assert page1.status_code == 200
            cursor = page1.json()["lanes"][0]["next_cursor"]
            assert cursor
            page2 = await client.get(
                TIMELINE_URL,
                params={
                    "wba_ids": wba_id,
                    "scope": "history",
                    "limit": limit,
                    "cursor": cursor,
                },
            )
        assert page2.status_code == 200
        sql = _compiled_sql(fake_db.statements[-1])
        assert "(activity_events.event_time,activity_events.id)<(" in sql

    async def test_limit_validation(self, client: httpx.AsyncClient) -> None:
        async with client:
            resp = await client.get(
                TIMELINE_URL,
                params={"wba_ids": "github::Person::alice", "limit": 0},
            )
        assert resp.status_code == 422

    async def test_lane_role_and_related_id_in_both_directions(
        self, client: httpx.AsyncClient
    ) -> None:
        """Each event names which side the lane was on and the other side's id.

        The canned set returns both directions for the ``alice`` lane: the first
        action's actor is the lane (role ``actor``), the second action's actor is
        a different person (role ``target``).
        """
        async with client:
            resp = await client.get(
                TIMELINE_URL,
                params={"wba_ids": "github::Person::alice", "limit": 5},
            )
        assert resp.status_code == 200
        events = resp.json()["lanes"][0]["events"]
        assert len(events) == 2
        actor_side, target_side = events[0], events[1]
        # lane is the actor → the other side is the target (the PR).
        assert actor_side["lane_role"] == "actor"
        assert actor_side["related_id"] == "org/repo#142"
        assert actor_side["entity_type"] == "PullRequest"
        # The canonical WBA id of the other side is built from the row's own
        # source when ``target_source`` is unset (Phase 1c's ``other_source``).
        assert actor_side["related_wba_id"] == "github::PullRequest::org/repo#142"
        # lane is the target → the other side is the actor (the other person).
        assert target_side["lane_role"] == "target"
        assert target_side["related_id"] == "bob"
        assert target_side["entity_type"] == "Person"
        assert target_side["related_wba_id"] == "github::Person::bob"

    async def test_related_wba_id_uses_target_source_for_actor_direction(
        self, client: httpx.AsyncClient, fake_db: FakeSession
    ) -> None:
        """When the lane is the actor, the sibling's source is the row's target_source.

        Mirrors the query layer's ``related_source`` ``CASE`` (Phase 1c).
        """
        fake_db.actions[0][0].target_source = "jira"
        async with client:
            resp = await client.get(
                TIMELINE_URL,
                params={"wba_ids": "github::Person::alice", "limit": 5},
            )
        assert resp.status_code == 200
        actor_side = resp.json()["lanes"][0]["events"][0]
        assert actor_side["lane_role"] == "actor"
        assert actor_side["related_wba_id"] == "jira::PullRequest::org/repo#142"

    async def test_related_name_resolved_and_raw_id_fallback(
        self, client: httpx.AsyncClient
    ) -> None:
        """One action carries a resolved name; the other falls back to ``None``."""
        async with client:
            resp = await client.get(
                TIMELINE_URL,
                params={"wba_ids": "github::Person::alice", "limit": 5},
            )
        assert resp.status_code == 200
        events = resp.json()["lanes"][0]["events"]
        assert events[0]["related_name"] == "feat: add user activity timeline API"
        assert events[1]["related_name"] is None

    async def test_row_multiplication_guard(
        self, client: httpx.AsyncClient, fake_db: FakeSession
    ) -> None:
        """The other side having several activity_events rows must not inflate the
        lane: one event per action row."""
        # Give the related entity several history rows; a naive join would
        # multiply the lane by this count.
        fake_db.events = [
            _make_event(
                signal_id=f"event-{index}",
                source="github",
                entity_type="PullRequest",
                entity_id="org/repo#142",
                event_time=datetime(2026, 3, 12, index, 0, 0, tzinfo=timezone.utc),
                display_name=f"state {index}",
                row_id=index,
            )
            for index in range(5)
        ]
        async with client:
            resp = await client.get(
                TIMELINE_URL,
                params={"wba_ids": "github::Person::alice", "limit": 50},
            )
        assert resp.status_code == 200
        events = resp.json()["lanes"][0]["events"]
        assert len(events) == len(fake_db.actions) == 2


# ---------------------------------------------------------------------------
# Mock scenario gate (end-to-end wiring)
# ---------------------------------------------------------------------------


class TestMockScenarioGate:
    async def test_mock_off_ignores_query_param(
        self, client: httpx.AsyncClient, fake_db: FakeSession
    ) -> None:
        async with client:
            resp = await client.get(
                TIMELINE_URL,
                params={"wba_ids": "github::Person::alice", "mock": "even"},
            )
        assert resp.status_code == 200
        # The real DB path ran: mock mode cannot be turned on by ?mock= alone.
        assert fake_db.statements

    async def test_mock_on_serves_invented_data(
        self, client: httpx.AsyncClient, fake_db: FakeSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "TIMELINE_MOCK_SCENARIO", "even")
        async with client:
            resp = await client.get(
                TIMELINE_URL,
                params={"wba_ids": "mock::Person::alice", "mock": "even"},
            )
        assert resp.status_code == 200
        assert resp.json()["lanes"][0]["wba_id"] == "mock::Person::alice"
        # Mock mode serves without touching the database.
        assert fake_db.statements == []

    async def test_mock_on_override_switch_is_per_request(
        self, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "TIMELINE_MOCK_SCENARIO", "even")
        async with client:
            resp = await client.get(
                TIMELINE_URL,
                params={"wba_ids": "mock::Person::alice", "mock": "pagination", "limit": 5},
            )
        assert resp.status_code == 200
        # The pagination scenario honours limit; even would not necessarily.
        assert len(resp.json()["lanes"][0]["events"]) == 5

    async def test_unknown_mock_scenario_returns_400(
        self, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "TIMELINE_MOCK_SCENARIO", "even")
        async with client:
            resp = await client.get(
                TIMELINE_URL,
                params={"wba_ids": "mock::Person::alice", "mock": "nonsense"},
            )
        assert resp.status_code == 400
        assert resp.status_code != 500
        assert resp.json()["detail"]["error"] == "Invalid mock scenario"

    async def test_unknown_env_scenario_returns_400(
        self, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "TIMELINE_MOCK_SCENARIO", "not_a_scenario")
        async with client:
            resp = await client.get(
                TIMELINE_URL,
                params={"wba_ids": "github::Person::alice"},
            )
        assert resp.status_code == 400
        assert resp.json()["detail"]["error"] == "Invalid mock scenario"

    async def test_unknown_mock_scenario_returns_400_for_suggest(
        self, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "TIMELINE_MOCK_SCENARIO", "even")
        async with client:
            resp = await client.get(
                SUGGEST_URL,
                params={"q": "abc", "mock": "nonsense"},
            )
        assert resp.status_code == 400
        assert resp.json()["detail"]["error"] == "Invalid mock scenario"


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

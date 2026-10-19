"""Unit tests for Activity Timeline Person identity resolution.

Covers the Neo4j-backed resolver in ``app.api.activity.v1.identity`` and the
identity-aware pieces of the activity service/query layers. No database or
network access — Neo4j reads are stubbed.

Run with:
    pytest -m unit tests/test_activity_person_identity.py -v
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

import pytest
from neo4j.exceptions import ServiceUnavailable

from app.api.activity.v1 import identity, query
from app.api.activity.v1.identity import parse_identity_id, resolve_person_identities
from app.api.activity.v1.service import _action_to_event
from app.db.models.activity_action import ActivityAction

pytestmark = [pytest.mark.unit]


# ---------------------------------------------------------------------------
# parse_identity_id
# ---------------------------------------------------------------------------


class TestParseIdentityId:
    def test_splits_provider_and_entity_id(self) -> None:
        assert parse_identity_id("confluence::IdentityMapping::557058:abc") == (
            "confluence",
            "557058:abc",
        )

    def test_entity_id_may_contain_double_colon(self) -> None:
        # Only the first two separators split — the entity id keeps its own "::".
        assert parse_identity_id("github::IdentityMapping::org::alice") == (
            "github",
            "org::alice",
        )

    def test_rejects_too_few_parts(self) -> None:
        assert parse_identity_id("github::alice") is None

    def test_rejects_empty_source_or_entity_id(self) -> None:
        assert parse_identity_id("::IdentityMapping::alice") is None
        assert parse_identity_id("github::IdentityMapping::") is None


# ---------------------------------------------------------------------------
# resolve_person_identities
# ---------------------------------------------------------------------------


class TestResolvePersonIdentities:
    @pytest.mark.asyncio
    async def test_parses_and_preserves_order(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            identity,
            "_fetch_identities",
            lambda _pid: [
                "github::IdentityMapping::alice",
                "confluence::IdentityMapping::557058:abc",
            ],
        )
        assert await resolve_person_identities("github::Person::alice") == [
            ("github", "alice"),
            ("confluence", "557058:abc"),
        ]

    @pytest.mark.asyncio
    async def test_runtime_error_returns_empty(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _boom(_pid: str) -> list[str]:
            raise RuntimeError("driver unavailable")

        monkeypatch.setattr(identity, "_fetch_identities", _boom)
        assert await resolve_person_identities("github::Person::alice") == []

    @pytest.mark.asyncio
    async def test_service_unavailable_returns_empty(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _boom(_pid: str) -> list[str]:
            raise ServiceUnavailable("no route to host")

        monkeypatch.setattr(identity, "_fetch_identities", _boom)
        assert await resolve_person_identities("github::Person::alice") == []

    @pytest.mark.asyncio
    async def test_unexpected_error_returns_empty(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _boom(_pid: str) -> list[str]:
            raise ValueError("boom")

        monkeypatch.setattr(identity, "_fetch_identities", _boom)
        assert await resolve_person_identities("github::Person::alice") == []

    @pytest.mark.asyncio
    async def test_malformed_ids_are_skipped(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            identity,
            "_fetch_identities",
            lambda _pid: [
                "github::IdentityMapping::alice",
                "malformed",
                "confluence::IdentityMapping::557058:abc",
            ],
        )
        assert await resolve_person_identities("github::Person::alice") == [
            ("github", "alice"),
            ("confluence", "557058:abc"),
        ]


# ---------------------------------------------------------------------------
# _action_to_event — the lane spans multiple identities
# ---------------------------------------------------------------------------


class TestActionToEvent:
    @staticmethod
    def _action(
        *,
        actor_type: str,
        actor_id: str,
        target_type: str,
        target_id: str,
    ) -> ActivityAction:
        return ActivityAction(
            id=1,
            signal_id="signal-1",
            source="github",
            event_time=datetime(2026, 3, 15, tzinfo=timezone.utc),
            actor_entity_type=actor_type,
            actor_entity_id=actor_id,
            relationship_type="CREATED",
            target_entity_type=target_type,
            target_entity_id=target_id,
            summary=None,
            url=None,
        )

    def test_other_provider_identity_is_recognised_as_the_lane(self) -> None:
        # The lane's canonical id is "alice", but this row's actor is the same
        # person's Confluence identity. It must still count as "the lane acting",
        # so the *other* side is the target type (the regression this fixes).
        action = self._action(
            actor_type="Person",
            actor_id="557058:abc",
            target_type="Issue",
            target_id="PROJ-1",
        )
        event = _action_to_event(
            action,
            None,
            lane_entity_type="Person",
            lane_identity_ids=frozenset({"alice", "557058:abc"}),
        )
        assert event.entity_type == "Issue"

    def test_lane_as_target_resolves_to_actor_type(self) -> None:
        action = self._action(
            actor_type="PullRequest",
            actor_id="org/repo#7",
            target_type="Person",
            target_id="alice",
        )
        event = _action_to_event(
            action,
            None,
            lane_entity_type="Person",
            lane_identity_ids=frozenset({"alice", "557058:abc"}),
        )
        assert event.entity_type == "PullRequest"

    def test_identity_outside_the_lane_is_not_the_lane(self) -> None:
        # An actor id that is not one of the lane's identities makes the actor
        # the "other" side.
        action = self._action(
            actor_type="Person",
            actor_id="carol",
            target_type="Issue",
            target_id="PROJ-1",
        )
        event = _action_to_event(
            action,
            None,
            lane_entity_type="Person",
            lane_identity_ids=frozenset({"alice", "557058:abc"}),
        )
        assert event.entity_type == "Person"


# ---------------------------------------------------------------------------
# fetch_actions_for_entity — one disjunct per identity, per side
# ---------------------------------------------------------------------------


class _FakeResult:
    """Minimal stand-in for ``sqlalchemy.engine.Result``."""

    def scalars(self) -> "_FakeResult":
        return self

    def all(self) -> list[Any]:
        return []

    def first(self) -> None:
        return None


class _RecordingSession:
    """Fake ``AsyncSession`` that records the statement it is handed."""

    def __init__(self) -> None:
        self.statements: list[Any] = []

    async def execute(self, stmt: Any) -> _FakeResult:
        self.statements.append(stmt)
        return _FakeResult()


def _compiled_sql(stmt: Any) -> str:
    """Return *stmt* as whitespace-normalised SQL text for substring assertions."""
    return re.sub(r"\s+", "", str(stmt.compile(compile_kwargs={"literal_binds": True})))


class TestActionsPredicate:
    @pytest.mark.asyncio
    async def test_two_identities_emit_a_disjunct_per_identity_per_side(
        self,
    ) -> None:
        session = _RecordingSession()
        await query.fetch_actions_for_entity(
            session,  # type: ignore[arg-type]
            entity_type="Person",
            identities=[("github", "alice"), ("confluence", "557058:abc")],
            from_time=None,
            to_time=None,
            cursor_time=None,
            cursor_id=None,
            limit=10,
        )
        sql = _compiled_sql(session.statements[-1])
        where = sql.split("FROMactivity_actionsWHERE", 1)[-1]
        # One disjunct per identity, per side — the added target_source column and
        # the resolve subquery's CASE both contain "source=", so scope to WHERE.
        assert where.count("source=") == 4            # 2 identities
        assert where.count("actor_entity_id=") == 2   # one per identity, actor side
        assert where.count("target_entity_id=") == 2  # one per identity, target side

    @pytest.mark.asyncio
    async def test_single_identity_matches_todays_behaviour(self) -> None:
        session = _RecordingSession()
        await query.fetch_actions_for_entity(
            session,  # type: ignore[arg-type]
            entity_type="Person",
            identities=[("github", "alice")],
            from_time=None,
            to_time=None,
            cursor_time=None,
            cursor_id=None,
            limit=10,
        )
        sql = _compiled_sql(session.statements[-1])
        where = sql.split("FROMactivity_actionsWHERE", 1)[-1]
        # Scoped to WHERE for the same reason as the two-identity case above.
        assert where.count("source=") == 2            # 1 identity
        assert where.count("actor_entity_id=") == 1   # one per identity, actor side
        assert where.count("target_entity_id=") == 1  # one per identity, target side

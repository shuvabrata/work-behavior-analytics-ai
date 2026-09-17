"""Unit tests for batched relationship target resolution in the Neo4j sink.

Validates that ``_to_db_relationships`` resolves relationship targets via the
pre-fetched batch lookup maps (email / url / Atlassian account_id) instead of
issuing one ``session.run()`` query per relationship, while preserving the exact
resolution priority order:

1. ``email`` (Person targets)
2. ``url``
3. Atlassian ``account_id`` (IdentityMapping first, then existing Person node)
4. canonical ``wba_format(source, entity_type, id)`` fallback
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from common.activity_signal.models import (
    ActivitySignal,
    IssueAttributes,
    Relationship,
    RelationshipTarget,
)
from connectors.consumers.sinks.neo4j_sink import _to_db_relationships


pytestmark = pytest.mark.unit

_EVENT_TIME = datetime(2026, 5, 31, 12, 0, 0, tzinfo=timezone.utc)
_INGESTION_TIME = datetime(2026, 5, 31, 12, 5, 0, tzinfo=timezone.utc)


class _Row:
    """Minimal stand-in for a Neo4j result row exposing ``row["key"]`` access."""

    def __init__(self, mapping):
        self._mapping = mapping

    def __getitem__(self, key):
        return self._mapping[key]


def _signal(relationships) -> ActivitySignal:
    return ActivitySignal(
        source="jira",
        id="PROJ-1",
        source_config="https://example.atlassian.net",
        connector_url="https://example.atlassian.net/connectors/jira",
        event_time=_EVENT_TIME,
        version="1.0",
        attributes=IssueAttributes(
            key="PROJ-1",
            type="Task",
            summary="Do the thing",
            priority="High",
            status="Open",
            created_at="2026-05-01T10:00:00Z",
            url="https://example.atlassian.net/browse/PROJ-1",
        ),
        relationships=relationships,
        ingestion_time=_INGESTION_TIME,
    )


def _mock_session(*, email_rows=None, url_rows=None, identity_rows=None, person_rows=None):
    """Build a MagicMock session whose ``run`` returns rows per batch query.

    Each ``*_rows`` argument is a list of dicts; ``None`` means the query is
    never expected to be issued (the mock raises if it is).
    """
    session = MagicMock()

    def run_side_effect(query: str, **_kwargs):
        if "UNWIND $emails AS email" in query:
            if email_rows is None:
                raise AssertionError(f"Unexpected email query: {query}")
            return [_Row(r) for r in email_rows]
        if "UNWIND $urls AS url" in query:
            if url_rows is None:
                raise AssertionError(f"Unexpected url query: {query}")
            return [_Row(r) for r in url_rows]
        if "UNWIND $identity_ids AS iid" in query:
            if identity_rows is None:
                raise AssertionError(f"Unexpected identity query: {query}")
            return [_Row(r) for r in identity_rows]
        if "UNWIND $person_ids AS pid" in query:
            if person_rows is None:
                raise AssertionError(f"Unexpected person query: {query}")
            return [_Row(r) for r in person_rows]
        raise AssertionError(f"Unexpected query: {query}")

    session.run.side_effect = run_side_effect
    return session


def test_batch_resolution_single_query_per_category() -> None:
    """Only one query per batch category is issued regardless of relationship count."""
    session = _mock_session(
        email_rows=[
            {"email": "alice@example.com", "id": "github::Person::alice"},
            {"email": "bob@example.com", "id": "github::Person::bob"},
        ],
        url_rows=[
            {"url": "https://example.atlassian.net/browse/PROJ-2", "id": "jira::Issue::PROJ-2"},
        ],
        identity_rows=[
            {"iid": "jira::IdentityMapping::acc123", "id": "jira::Person::acc123"},
        ],
        person_rows=[],
    )

    signal = _signal(
        [
            Relationship(
                type="REPORTED_BY",
                target=RelationshipTarget(
                    source="jira", entity_type="Person", email="alice@example.com"
                ),
            ),
            Relationship(
                type="MENTIONS",
                target=RelationshipTarget(
                    source="jira", entity_type="Person", email="bob@example.com"
                ),
            ),
            Relationship(
                type="RELATES_TO",
                target=RelationshipTarget(
                    source="jira",
                    entity_type="Issue",
                    url="https://example.atlassian.net/browse/PROJ-2",
                ),
            ),
            Relationship(
                type="ASSIGNED_TO",
                target=RelationshipTarget(
                    source="jira", entity_type="Person", id="acc123"
                ),
            ),
        ]
    )

    rels = _to_db_relationships(session, signal.relationships, "jira::Issue::PROJ-1", "Issue")

    # 4 relationships resolved with exactly 4 batch queries (one per category).
    assert len(rels) == 4
    assert session.run.call_count == 4

    # Each batch query is issued exactly once.
    queries = [call.args[0] for call in session.run.call_args_list]
    assert sum("UNWIND $emails AS email" in q for q in queries) == 1
    assert sum("UNWIND $urls AS url" in q for q in queries) == 1
    assert sum("UNWIND $identity_ids AS iid" in q for q in queries) == 1
    assert sum("UNWIND $person_ids AS pid" in q for q in queries) == 1

    by_type = {rel.type: rel for rel in rels}
    assert by_type["REPORTED_BY"].to_id == "github::Person::alice"
    assert by_type["MENTIONS"].to_id == "github::Person::bob"
    assert by_type["RELATES_TO"].to_id == "jira::Issue::PROJ-2"
    assert by_type["ASSIGNED_TO"].to_id == "jira::Person::acc123"


def test_target_resolution_priority_order() -> None:
    """Resolution priority is strictly email > url > atlassian > canonical."""
    session = _mock_session(
        email_rows=[
            {"email": "alice@example.com", "id": "github::Person::alice"},
        ],
        url_rows=[
            {"url": "https://example.atlassian.net/wiki/pages/2001", "id": "confluence::Page::2001"},
        ],
        identity_rows=[
            {"iid": "jira::IdentityMapping::acc123", "id": "jira::Person::acc123"},
        ],
        person_rows=[],
    )

    signal = _signal(
        [
            # Person with email AND url AND id → email wins.
            Relationship(
                type="REPORTED_BY",
                target=RelationshipTarget(
                    source="jira",
                    entity_type="Person",
                    email="alice@example.com",
                    url="https://example.atlassian.net/wiki/pages/2001",
                    id="acc123",
                ),
            ),
            # Non-Person with url AND id → url wins.
            Relationship(
                type="RELATES_TO",
                target=RelationshipTarget(
                    source="jira",
                    entity_type="Page",
                    url="https://example.atlassian.net/wiki/pages/2001",
                    id="2001",
                ),
            ),
            # Jira Person with id only → atlassian (IdentityMapping) wins over canonical.
            Relationship(
                type="ASSIGNED_TO",
                target=RelationshipTarget(
                    source="jira", entity_type="Person", id="acc123"
                ),
            ),
            # Jira Issue with id only → canonical fallback.
            Relationship(
                type="REFERENCES",
                target=RelationshipTarget(
                    source="jira", entity_type="Issue", id="PROJ-2"
                ),
            ),
        ]
    )

    rels = _to_db_relationships(session, signal.relationships, "jira::Issue::PROJ-1", "Issue")

    by_type = {rel.type: rel.to_id for rel in rels}
    assert by_type["REPORTED_BY"] == "github::Person::alice"  # email beats url + atlassian
    assert by_type["RELATES_TO"] == "confluence::Page::2001"  # url beats canonical
    assert by_type["ASSIGNED_TO"] == "jira::Person::acc123"  # atlassian beats canonical
    assert by_type["REFERENCES"] == "jira::Issue::PROJ-2"  # canonical fallback


def test_atlassian_resolution_prefers_identity_mapping_over_person_node() -> None:
    """For a Jira/Confluence Person, IdentityMapping resolution precedes Person-node lookup."""
    session = _mock_session(
        email_rows=[],
        url_rows=[],
        identity_rows=[
            {"iid": "jira::IdentityMapping::acc123", "id": "jira::Person::acc123"},
        ],
        person_rows=[
            {"pid": "confluence::Person::acc123", "id": "confluence::Person::acc123"},
        ],
    )

    signal = _signal(
        [
            Relationship(
                type="ASSIGNED_TO",
                target=RelationshipTarget(
                    source="jira", entity_type="Person", id="acc123"
                ),
            ),
        ]
    )

    rels = _to_db_relationships(session, signal.relationships, "jira::Issue::PROJ-1", "Issue")

    assert len(rels) == 1
    # IdentityMapping hit wins even though a Person node also exists.
    assert rels[0].to_id == "jira::Person::acc123"


def test_atlassian_resolution_falls_back_to_person_node() -> None:
    """When no IdentityMapping exists, an existing Person node is reused."""
    session = _mock_session(
        email_rows=[],
        url_rows=[],
        identity_rows=[],
        person_rows=[
            {"pid": "confluence::Person::acc123", "id": "confluence::Person::acc123"},
        ],
    )

    signal = _signal(
        [
            Relationship(
                type="ASSIGNED_TO",
                target=RelationshipTarget(
                    source="jira", entity_type="Person", id="acc123"
                ),
            ),
        ]
    )

    rels = _to_db_relationships(session, signal.relationships, "jira::Issue::PROJ-1", "Issue")

    assert len(rels) == 1
    assert rels[0].to_id == "confluence::Person::acc123"


def test_unresolvable_target_skipped_with_warning() -> None:
    """Targets that resolve to nothing fall back to canonical, or are skipped."""
    session = _mock_session(
        email_rows=[],
        url_rows=[],
        identity_rows=[],
        person_rows=[],
    )

    signal = _signal(
        [
            # No identifier at all → skipped with warning.
            Relationship(
                type="REPORTED_BY",
                target=RelationshipTarget(source="jira", entity_type="Person"),
            ),
            # Has id → canonical fallback, not skipped.
            Relationship(
                type="RELATES_TO",
                target=RelationshipTarget(
                    source="jira", entity_type="Issue", id="PROJ-2"
                ),
            ),
        ]
    )

    rels = _to_db_relationships(session, signal.relationships, "jira::Issue::PROJ-1", "Issue")

    assert len(rels) == 1
    assert rels[0].to_id == "jira::Issue::PROJ-2"
"""Helpers for folding one Person node into another."""

from __future__ import annotations

from neo4j import Session

from common.logger import logger
from connectors.neo4j_db.models import Relationship as DbRelationship
from connectors.neo4j_db.models import merge_relationship


def rehome_person(session: Session, stale_person_id: str, canonical_person_id: str) -> None:
    """Move relationships from a stale Person stub onto the canonical Person node.

    This handles the case where content relationships created a bare
    ``confluence::Person::<account_id>`` node before the later Person signal was
    deduplicated onto an existing canonical Person (for example, a Jira-backed
    Person with the same Atlassian account_id).
    """
    if stale_person_id == canonical_person_id:
        return

    outgoing = session.run(
        (
            "MATCH (stale:Person {id: $stale_id})-[r]->(other) "
            "RETURN type(r) AS rel_type, labels(other) AS other_labels, "
            "other.id AS other_id, properties(r) AS props"
        ),
        stale_id=stale_person_id,
    ).data()
    incoming = session.run(
        (
            "MATCH (other)-[r]->(stale:Person {id: $stale_id}) "
            "RETURN type(r) AS rel_type, labels(other) AS other_labels, "
            "other.id AS other_id, properties(r) AS props"
        ),
        stale_id=stale_person_id,
    ).data()

    migrated = 0
    for row in outgoing:
        other_labels = row.get("other_labels") or []
        if not other_labels:
            continue
        merge_relationship(
            session,
            DbRelationship(
                type=row["rel_type"],
                from_id=canonical_person_id,
                to_id=row["other_id"],
                from_type="Person",
                to_type=other_labels[0],
                properties=row.get("props") or {},
            ),
        )
        migrated += 1

    for row in incoming:
        other_labels = row.get("other_labels") or []
        if not other_labels:
            continue
        merge_relationship(
            session,
            DbRelationship(
                type=row["rel_type"],
                from_id=row["other_id"],
                to_id=canonical_person_id,
                from_type=other_labels[0],
                to_type="Person",
                properties=row.get("props") or {},
            ),
        )
        migrated += 1

    session.run(
        "MATCH (stale:Person {id: $stale_id}) DETACH DELETE stale",
        stale_id=stale_person_id,
    )
    logger.info(
        f"Rehomed stale Person stub stale_id={stale_person_id} canonical_id={canonical_person_id} "
        f"relationships_migrated={migrated}"
    )

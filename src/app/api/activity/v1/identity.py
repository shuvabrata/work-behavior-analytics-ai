"""Read-time resolution of a canonical Person's provider identities via Neo4j.

The Activity Timeline store (Postgres) holds *raw* provider-scoped entity ids,
while search returns the *canonical* Person wba_id. Neo4j is the single source of
truth for the Person ↔ IdentityMapping relationship, so a Person lane is expanded
into every provider identity that maps to that person before the timeline query
runs.

This module is best-effort: when the graph is disabled or the driver is unavailable
(Neo4j unreachable) the caller falls back to the single lane identity (today's
behaviour).
"""

from __future__ import annotations

import asyncio

from neo4j.exceptions import Neo4jError, ServiceUnavailable

from app.common.neo4j_driver import get_driver
from app.settings import settings
from common.logger import logger

# Undirected: MAPS_TO is stored as a single undirected edge
# (see docs/design/RELATIONSHIPS_DESIGN.md).
_IDENTITIES_CYPHER = (
    "MATCH (p:Person {id: $person_id})-[:MAPS_TO]-(i:IdentityMapping) "
    "RETURN i.id AS identity_id"
)


def parse_identity_id(identity_id: str) -> tuple[str, str] | None:
    """Split an IdentityMapping node id into ``(source, entity_id)``.

    The node id is ``{provider}::IdentityMapping::{external_id}`` where
    ``provider`` is the lowercase source (``github`` / ``jira`` / ``confluence``)
    — matching ``activity_actions.source``.

    NOTE: derive the source from the **id**, never from the node's ``provider``
    *property*: that property is capitalised (``"GitHub"``, ``"Jira"``,
    ``"Confluence"``) and would never match ``activity_actions.source``.

    Returns ``None`` for a malformed id (fewer than three parts, or an empty
    source/entity id).
    """
    parts = identity_id.split("::", 2)
    if len(parts) != 3 or not parts[0] or not parts[2]:
        return None
    return parts[0], parts[2]


def _fetch_identities(person_wba_id: str) -> list[str]:
    """Synchronous Neo4j read — run inside ``asyncio.to_thread``."""
    driver = get_driver()
    with driver.session() as session:
        result = session.run(_IDENTITIES_CYPHER, person_id=person_wba_id)
        return [row["identity_id"] for row in result]


async def resolve_person_identities(person_wba_id: str) -> list[tuple[str, str]]:
    """Return ``[(source, entity_id), ...]`` for a canonical Person.

    Returns an empty list when the graph is disabled, when Neo4j is unreachable,
    or when the person has no identity mappings — the caller treats that as "use
    the lane identity only". Never raises.
    """
    # A disabled graph is a supported configuration, not a failure — return
    # immediately and do NOT log. This matches every other graph reader in the app
    # (chains.py:47, neo4j_chain.py:400, graph/v1/router.py:324). This function
    # runs once per Person lane, so a warning here would be per-lane log spam.
    if not settings.NEO4J_ENABLED:
        return []

    try:
        raw = await asyncio.to_thread(_fetch_identities, person_wba_id)
    except (RuntimeError, Neo4jError, ServiceUnavailable) as exc:
        logger.warning(
            f"[Activity] Person identity lookup failed for {person_wba_id}: {exc} "
            f"— falling back to the single lane identity"
        )
        return []
    except Exception as exc:  # pylint: disable=broad-except
        logger.warning(
            f"[Activity] Unexpected error resolving identities for {person_wba_id}: {exc}"
        )
        return []

    resolved: list[tuple[str, str]] = []
    for identity_id in raw:
        parsed = parse_identity_id(identity_id)
        if parsed is None:
            logger.warning(f"[Activity] Skipping malformed IdentityMapping id {identity_id!r}")
            continue
        resolved.append(parsed)
    return resolved

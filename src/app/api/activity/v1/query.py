"""Query layer for Activity Timeline API v1 — SQLAlchemy async reads.

Uses the typed ORM models (``ActivityAction`` / ``ActivityEvent``) rather than
raw ``text()`` SQL so queries stay type-checked under mypy strict mode.  The
cursor is a ``(event_time, id)`` row-value comparison — the same keyset
pagination the plan specifies, expressed via ``sqlalchemy.tuple_``.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import and_, or_, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.activity_action import ActivityAction
from app.db.models.activity_event import ActivityEvent


async def fetch_actions_for_entity(
    db: AsyncSession,
    *,
    entity_type: str,
    identities: Sequence[tuple[str, str]],
    from_time: datetime | None,
    to_time: datetime | None,
    cursor_time: datetime | None,
    cursor_id: int | None,
    limit: int,
) -> list[ActivityAction]:
    """Return ``activity_actions`` rows where the entity is actor OR target.

    Backs ``scope=activity`` — "everything involving this entity".

    ``identities`` is one or more ``(source, entity_id)`` pairs for the lane —
    a single pair for every non-Person lane, or every provider identity of a
    Person lane. Each pair is emitted as its own disjunct so the ``source``-leading
    actor/target indexes (``idx_activity_actions_actor`` /
    ``idx_activity_actions_target``) remain usable.

    Precondition: ``identities`` is non-empty (the service always supplies at
    least the lane's own pair).

    Keyset pagination: rows are ordered ``(event_time DESC, id DESC)`` and the
    cursor filters ``(event_time, id) < (cursor_time, cursor_id)``.
    """
    actor_match = or_(
        *(
            and_(
                ActivityAction.source == source,
                ActivityAction.actor_entity_type == entity_type,
                ActivityAction.actor_entity_id == entity_id,
            )
            for source, entity_id in identities
        )
    )
    target_match = or_(
        *(
            and_(
                ActivityAction.source == source,
                ActivityAction.target_entity_type == entity_type,
                ActivityAction.target_entity_id == entity_id,
            )
            for source, entity_id in identities
        )
    )
    stmt = select(ActivityAction).where(or_(actor_match, target_match))
    if from_time is not None:
        stmt = stmt.where(ActivityAction.event_time >= from_time)
    if to_time is not None:
        stmt = stmt.where(ActivityAction.event_time <= to_time)
    if cursor_time is not None and cursor_id is not None:
        stmt = stmt.where(
            tuple_(ActivityAction.event_time, ActivityAction.id)
            < (cursor_time, cursor_id)
        )
    stmt = stmt.order_by(
        ActivityAction.event_time.desc(), ActivityAction.id.desc()
    ).limit(limit)

    result = await db.execute(stmt)
    return list(result.scalars().all())


async def fetch_event_history(
    db: AsyncSession,
    *,
    entity_type: str,
    identities: Sequence[tuple[str, str]],
    from_time: datetime | None,
    to_time: datetime | None,
    cursor_time: datetime | None,
    cursor_id: int | None,
    limit: int,
) -> list[ActivityEvent]:
    """Return ``activity_events`` rows for the entity's own state changes.

    Backs ``scope=history`` — "history of this object".  Uses the
    ``idx_activity_events_lookup`` index.
    """
    match = or_(
        *(
            and_(
                ActivityEvent.source == source,
                ActivityEvent.entity_type == entity_type,
                ActivityEvent.entity_id == entity_id,
            )
            for source, entity_id in identities
        )
    )
    stmt = select(ActivityEvent).where(match)
    if from_time is not None:
        stmt = stmt.where(ActivityEvent.event_time >= from_time)
    if to_time is not None:
        stmt = stmt.where(ActivityEvent.event_time <= to_time)
    if cursor_time is not None and cursor_id is not None:
        stmt = stmt.where(
            tuple_(ActivityEvent.event_time, ActivityEvent.id)
            < (cursor_time, cursor_id)
        )
    stmt = stmt.order_by(
        ActivityEvent.event_time.desc(), ActivityEvent.id.desc()
    ).limit(limit)

    result = await db.execute(stmt)
    return list(result.scalars().all())


async def fetch_display_label(
    db: AsyncSession,
    *,
    entity_type: str,
    identities: Sequence[tuple[str, str]],
) -> tuple[str | None, str | None]:
    """Return the latest ``(display_name, avatar_url)`` for an entity.

    Reads the pre-computed columns from ``activity_events`` — no Neo4j call.
    ``identities`` is the lane's ``(source, entity_id)`` set (one pair for a
    non-Person lane, every provider identity for a Person lane) so a canonical
    person whose rows all live under a different provider identity still gets a
    name. Falls back to ``(None, None)`` when the entity has no timeline rows yet.
    """
    match = or_(
        *(
            and_(
                ActivityEvent.source == source,
                ActivityEvent.entity_type == entity_type,
                ActivityEvent.entity_id == entity_id,
            )
            for source, entity_id in identities
        )
    )
    stmt = (
        select(ActivityEvent.display_name, ActivityEvent.avatar_url)
        .where(
            match,
            or_(
                ActivityEvent.display_name.is_not(None),
                ActivityEvent.avatar_url.is_not(None),
            ),
        )
        .order_by(ActivityEvent.event_time.desc())
        .limit(1)
    )
    result = await db.execute(stmt)
    row = result.first()
    if row is None:
        return None, None
    return row[0], row[1]
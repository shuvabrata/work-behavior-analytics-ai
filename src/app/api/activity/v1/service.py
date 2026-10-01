"""Service layer for Activity Timeline API v1 — business logic.

Responsibilities:
* Parse WBA canonical keys (``{source}::{entity_type}::{id}``) into tuples.
* Encode/decode opaque pagination cursors (base64 of ``event_time|id``).
* Fan out per-lane queries and assemble ``TimelineLane`` responses.
* Build typeahead suggestions from the existing search service.
"""

from __future__ import annotations

import base64
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.api.search.v1 import service as search_service
from app.api.search.v1.model import SearchRequest
from app.db.models.activity_action import ActivityAction
from app.db.models.activity_event import ActivityEvent
from common.logger import logger
from . import query
from .model import (
    Suggestion,
    TimelineEvent,
    TimelineLane,
    TimelineMeta,
    TimelineRequest,
    TimelineResponse,
)

# Cursor format: base64("event_time_iso|row_id").  The pipe separator is safe
# because ISO 8601 timestamps never contain it.
_CURSOR_SEPARATOR = "|"


class InvalidWbaIdError(ValueError):
    """Raised when a WBA canonical key cannot be parsed."""


class InvalidCursorError(ValueError):
    """Raised when a pagination cursor is malformed or unparseable."""


# ---------------------------------------------------------------------------
# WBA ID parsing
# ---------------------------------------------------------------------------


def parse_wba_id(wba_id: str) -> tuple[str, str, str]:
    """Parse a WBA canonical key into ``(source, entity_type, entity_id)``.

    Format: ``{source}::{entity_type}::{id}``.  The entity id itself may
    contain ``::`` (e.g. GitHub ``org/repo`` ids do not, but Jira keys and
    some object ids can), so only the first two separators are split.

    Raises:
        InvalidWbaIdError: if the key has fewer than three parts or any part
            is empty.
    """
    parts = wba_id.split("::", 2)
    if len(parts) != 3 or any(not part for part in parts):
        raise InvalidWbaIdError(
            f"Invalid WBA ID {wba_id!r}: expected {{source}}::{{entity_type}}::{{id}}"
        )
    source, entity_type, entity_id = parts
    return source, entity_type, entity_id


# ---------------------------------------------------------------------------
# Cursor encode / decode
# ---------------------------------------------------------------------------


def _encode_cursor(event_time: datetime, row_id: int) -> str:
    """Encode a keyset position into an opaque base64 cursor string.

    Naive datetimes are treated as UTC.  The output is URL-safe base64 with
    padding stripped (``=`` chars are not valid in query params).
    """
    if event_time.tzinfo is None:
        event_time = event_time.replace(tzinfo=timezone.utc)
    utc_time = event_time.astimezone(timezone.utc)
    payload = f"{utc_time.isoformat()}{_CURSOR_SEPARATOR}{row_id}"
    encoded = base64.urlsafe_b64encode(payload.encode("utf-8")).decode("ascii")
    return encoded.rstrip("=")


def _decode_cursor(cursor: str) -> tuple[datetime, int]:
    """Decode an opaque cursor back into ``(event_time, row_id)``.

    Re-adds the ``=`` padding stripped at encode time before decoding.

    Raises:
        InvalidCursorError: if the cursor is not valid base64 or does not
            contain a parseable timestamp and integer row id.
    """
    try:
        padding = "=" * (-len(cursor) % 4)
        raw = base64.urlsafe_b64decode(
            (cursor + padding).encode("ascii")
        ).decode("utf-8")
    except (ValueError, UnicodeDecodeError) as exc:
        raise InvalidCursorError(f"Malformed cursor: {cursor!r}") from exc

    parts = raw.split(_CURSOR_SEPARATOR)
    if len(parts) != 2:
        raise InvalidCursorError(f"Malformed cursor: {cursor!r}")

    time_str, id_str = parts
    try:
        event_time = datetime.fromisoformat(time_str)
        row_id = int(id_str)
    except (ValueError, TypeError) as exc:
        raise InvalidCursorError(f"Malformed cursor: {cursor!r}") from exc

    return event_time, row_id


def validate_cursor(cursor: str) -> None:
    """Validate a cursor string without returning its contents.

    Raises:
        InvalidCursorError: if the cursor is malformed.
    """
    _decode_cursor(cursor)


# ---------------------------------------------------------------------------
# Timeline assembly
# ---------------------------------------------------------------------------


def _build_event(
    *,
    signal_id: str,
    event_time: datetime,
    relationship_type: str,
    summary: str | None,
    entity_type: str,
    source: str,
    url: str | None,
    details: dict[str, object],
) -> TimelineEvent:
    """Assemble a ``TimelineEvent`` from a query row."""
    return TimelineEvent(
        signal_id=signal_id,
        event_time=event_time,
        relationship_type=relationship_type,
        summary=summary,
        entity_type=entity_type,
        source=source,
        url=url,
        details=details,
    )


def _action_to_event(
    action: ActivityAction,
    *,
    lane_entity_type: str,
    lane_entity_id: str,
) -> TimelineEvent:
    """Convert an ``ActivityAction`` ORM row into a ``TimelineEvent``.

    ``entity_type`` is the *other* side of the action: the target when the
    lane entity is the actor, the actor when the lane entity is the target.
    """
    if (
        action.actor_entity_type == lane_entity_type
        and action.actor_entity_id == lane_entity_id
    ):
        other_type = action.target_entity_type
    else:
        other_type = action.actor_entity_type
    return _build_event(
        signal_id=action.signal_id,
        event_time=action.event_time,
        relationship_type=action.relationship_type,
        summary=action.summary,
        entity_type=other_type,
        source=action.source,
        url=action.url,
        details={},
    )


def _event_to_event(event: ActivityEvent) -> TimelineEvent:
    """Convert an ``ActivityEvent`` ORM row into a ``TimelineEvent``.

    Used for ``scope=history`` — the lane entity is the subject, so the
    event's own entity_type/source apply and the relationship is a synthetic
    ``STATE_CHANGE`` marker (the raw signal carries no relationship type).

    ``url`` is extracted from ``attributes.url`` (present on every entity
    attribute model) so history cards get a clickable link to the source
    system, mirroring how ``activity_actions.url`` is populated.
    """
    attrs = event.attributes or {}
    url = attrs.get("url")
    return _build_event(
        signal_id=event.signal_id,
        event_time=event.event_time,
        relationship_type="STATE_CHANGE",
        summary=event.display_name,
        entity_type=event.entity_type,
        source=event.source,
        url=url if isinstance(url, str) and url else None,
        details=attrs,
    )


async def _fetch_lane(
    db: AsyncSession,
    request: TimelineRequest,
    source: str,
    entity_type: str,
    entity_id: str,
) -> TimelineLane:
    """Fetch one lane's events and assemble the ``TimelineLane``."""
    wba_id = f"{source}::{entity_type}::{entity_id}"

    # Resolve the display label + avatar from the pre-computed columns.
    display_name, avatar_url = await query.fetch_display_label(
        db, source=source, entity_type=entity_type, entity_id=entity_id
    )
    label = display_name or entity_id

    # Decode the cursor (per-lane cursor; None on first page).
    cursor_time: datetime | None = None
    cursor_id: int | None = None
    if request.cursor:
        try:
            cursor_time, cursor_id = _decode_cursor(request.cursor)
        except InvalidCursorError:
            # A malformed cursor is a client error — surface it as an empty
            # lane rather than a 500.  The router validates this too, but the
            # service stays defensive.
            logger.warning(f"[Activity] Invalid cursor for lane {wba_id}: {request.cursor!r}")
            return TimelineLane(
                wba_id=wba_id,
                entity_type=entity_type,
                label=label,
                avatar_url=avatar_url,
                events=[],
                next_cursor=None,
            )

    if request.scope == "history":
        event_rows = await query.fetch_event_history(
            db,
            source=source,
            entity_type=entity_type,
            entity_id=entity_id,
            from_time=request.from_,
            to_time=request.to,
            cursor_time=cursor_time,
            cursor_id=cursor_id,
            limit=request.limit,
        )
        events = [_event_to_event(row) for row in event_rows]
        last_row: ActivityEvent | ActivityAction | None = (
            event_rows[-1] if event_rows else None
        )
    else:
        action_rows = await query.fetch_actions_for_entity(
            db,
            source=source,
            entity_type=entity_type,
            entity_id=entity_id,
            from_time=request.from_,
            to_time=request.to,
            cursor_time=cursor_time,
            cursor_id=cursor_id,
            limit=request.limit,
        )
        events = [
            _action_to_event(
                row,
                lane_entity_type=entity_type,
                lane_entity_id=entity_id,
            )
            for row in action_rows
        ]
        last_row = action_rows[-1] if action_rows else None

    # Keyset pagination: fetch limit+1 conceptually — but the query layer
    # already caps at limit, so a full page implies more may exist.  The
    # next_cursor is emitted whenever we got a full page.
    next_cursor: str | None = None
    if len(events) == request.limit and last_row is not None:
        next_cursor = _encode_cursor(last_row.event_time, last_row.id)

    return TimelineLane(
        wba_id=wba_id,
        entity_type=entity_type,
        label=label,
        avatar_url=avatar_url,
        events=events,
        next_cursor=next_cursor,
    )


async def get_timeline(
    db: AsyncSession, request: TimelineRequest
) -> TimelineResponse:
    """Build the full timeline response for all requested lanes."""
    lanes: list[TimelineLane] = []
    for wba_id in request.wba_ids:
        try:
            source, entity_type, entity_id = parse_wba_id(wba_id)
        except InvalidWbaIdError as exc:
            logger.warning(f"[Activity] Skipping invalid WBA ID {wba_id!r}: {exc}")
            continue
        lane = await _fetch_lane(
            db, request, source=source, entity_type=entity_type, entity_id=entity_id
        )
        lanes.append(lane)

    return TimelineResponse(
        lanes=lanes,
        meta=TimelineMeta(
            time_range={"from": request.from_, "to": request.to},
            total_lanes=len(lanes),
        ),
    )


# ---------------------------------------------------------------------------
# Suggestions (typeahead)
# ---------------------------------------------------------------------------


def _build_suggestions(query_text: str, limit: int) -> list[Suggestion]:
    """Build typeahead suggestions from the existing search service.

    Delegates to the Elasticsearch-backed search service (same as the
    persons autocomplete endpoint).  Returns an empty list when ES is
    disabled or the query is too short.
    """
    if not query_text or len(query_text.strip()) < 2:
        return []

    request = SearchRequest(
        q=query_text.strip(),
        page=1,
        page_size=limit,
        full=True,  # Need attributes for label/avatar extraction
    )
    response = search_service.search(request)

    suggestions: list[Suggestion] = []
    for result in response.results:
        attrs = result.attributes or {}
        label = str(
            attrs.get("full_name")
            or attrs.get("name")
            or attrs.get("title")
            or attrs.get("login")
            or attrs.get("key")
            or result.wba_id
        )
        parts = result.wba_id.split("::", 2)
        source = parts[0] if len(parts) == 3 else "unknown"
        entity_type = parts[1] if len(parts) == 3 else "unknown"
        suggestions.append(
            Suggestion(
                wba_id=result.wba_id,
                label=label,
                entity_type=entity_type,
                source=source,
                avatar_url=attrs.get("avatar_url"),
            )
        )
    return suggestions


async def get_suggestions(db: AsyncSession, q: str, limit: int) -> list[Suggestion]:
    """Return typeahead suggestions for the entity selector."""
    _ = db  # suggestions come from the search service, not Postgres
    return _build_suggestions(q, limit)
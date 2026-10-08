"""Deterministic mock data for the Activity Timeline API (dev-only).

Purpose
-------
Manual visual QA of the Activity Timeline UI needs activity shapes that real
ingested data will not reliably contain — a 30-day dead zone, a 100-event spike
day, a wholly empty lane, non-aligned gaps. This module generates them on
demand through the *real* HTTP endpoint so the whole request path (router
validation, cursor format, JSON serialization) is exercised.

Activation
----------
Disabled unless ``TIMELINE_MOCK_SCENARIO`` is set (one of :data:`MOCK_SCENARIOS`).
A single request may override it with ``?mock=<scenario>``. When enabled the
service serves invented data instead of querying Postgres — it must never be
set in a real deployment.

Fixtures are deterministic: the same scenario + request yields the same events
(ids are stable UUID5s, times are offsets from the range end).
"""

# The response-envelope construction below intentionally mirrors the real service
# (identical TimelineResponse shape) so the mock serializes exactly like the live
# API; that shared shape trips cross-module duplicate-code detection.
# pylint: disable=duplicate-code

from __future__ import annotations

import base64
import uuid
import zlib
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from app.settings import settings
from common.logger import logger

from .model import (
    Suggestion,
    TimelineEvent,
    TimelineLane,
    TimelineMeta,
    TimelineRequest,
    TimelineResponse,
)

MOCK_SCENARIOS: tuple[str, ...] = (
    "even",
    "empty_range",
    "empty_lane",
    "gaps_small",
    "gaps_global",
    "gap_30d",
    "gaps_staggered",
    "spike_100",
    "cell_boundary",
    "time_edges",
    "card_variety",
    "history",
    "pagination",
    "error_500",
    "suggest_variants",
)

_CURSOR_SEPARATOR = "|"
_NAMESPACE = uuid.UUID("6f6e6d6f-636b-4d61-7461-000000000001")
# "All time" (no ``from``): synthesise a deep history so pagination is exercisable.
_ALL_TIME_RANGE_DAYS = 365.0


class UnknownMockScenarioError(ValueError):
    """Raised when a requested mock scenario is not registered."""


@dataclass(frozen=True)
class _Spec:  # pylint: disable=too-many-instance-attributes
    """Declarative description of one synthetic event (pre-materialization)."""

    days_ago: float = 1.0
    hour: int = 9
    minute: int = 30
    relationship: str = "CREATED"
    summary: str | None = "Mock activity"
    other_type: str = "PullRequest"
    source: str = "github"
    url: str | None = "https://example.com/mock"
    details: dict[str, Any] = field(default_factory=dict)
    at: datetime | None = None


# ---------------------------------------------------------------------------
# Activation
# ---------------------------------------------------------------------------


def resolve_scenario(override: str | None) -> str | None:
    """Return the active mock scenario, or ``None`` when mock mode is off.

    ``TIMELINE_MOCK_SCENARIO`` must be set to enable mock mode; a per-request
    ``override`` (``?mock=``) then selects which scenario to serve. The
    override can never turn mock mode on by itself. Unknown names raise
    :class:`UnknownMockScenarioError` rather than silently serving real data.
    """
    base = (settings.TIMELINE_MOCK_SCENARIO or "").strip().lower()
    if not base:
        return None
    if base not in MOCK_SCENARIOS:
        raise UnknownMockScenarioError(
            f"Unknown TIMELINE_MOCK_SCENARIO {base!r}. Valid scenarios: "
            f"{', '.join(MOCK_SCENARIOS)}"
        )
    scenario = (override or base).strip().lower()
    if scenario not in MOCK_SCENARIOS:
        raise UnknownMockScenarioError(
            f"Unknown mock scenario {scenario!r}. Valid scenarios: "
            f"{', '.join(MOCK_SCENARIOS)}"
        )
    return scenario


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def _parse_wba_id(wba_id: str) -> tuple[str, str, str]:
    """Split ``{source}::{type}::{id}``; unknown shapes degrade gracefully."""
    parts = wba_id.split("::", 2)
    if len(parts) == 3 and all(parts):
        return parts[0], parts[1], parts[2]
    return "mock", "Unknown", wba_id


def _stable_int(value: str) -> int:
    """Deterministic, process-independent integer for a string."""
    return zlib.crc32(value.encode("utf-8"))


def _encode_cursor(event_time: datetime, row_id: int) -> str:
    """Encode ``(event_time, row_id)`` in the same format as the real service."""
    if event_time.tzinfo is None:
        event_time = event_time.replace(tzinfo=timezone.utc)
    payload = f"{event_time.astimezone(timezone.utc).isoformat()}{_CURSOR_SEPARATOR}{row_id}"
    return base64.urlsafe_b64encode(payload.encode("utf-8")).decode("ascii").rstrip("=")


def _cursor_offset(cursor: str | None) -> int:
    """Decode the pagination offset from an opaque cursor (0 when absent)."""
    if not cursor:
        return 0
    try:
        padding = "=" * (-len(cursor) % 4)
        raw = base64.urlsafe_b64decode((cursor + padding).encode("ascii")).decode("utf-8")
        _, id_str = raw.split(_CURSOR_SEPARATOR, 1)
        return max(int(id_str), 0)
    except (ValueError, UnicodeDecodeError):
        return 0


def _as_utc(value: datetime) -> datetime:
    """Normalize a possibly-naive datetime to UTC."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _lane_identity(
    wba_id: str, scenario: str, lane_index: int
) -> tuple[str, str, str | None]:
    """Return ``(entity_type, label, avatar_url)`` for a lane."""
    _, entity_type, entity_id = _parse_wba_id(wba_id)
    label = entity_id.replace("_", " ").replace("-", " ").title() or wba_id
    avatar: str | None = None
    if entity_type == "Person":
        avatar = f"https://avatars.githubusercontent.com/u/{_stable_int(entity_id) % 5000}?v=4"
    if scenario == "card_variety" and lane_index == 0:
        # Exercise the no-avatar + long-label rendering paths.
        avatar = None
        label = "A Very Long Lane Label That Should Truncate Gracefully In The Header"
    return entity_type, label, avatar


# ---------------------------------------------------------------------------
# Scenario → per-lane event specs
# ---------------------------------------------------------------------------


def _even(range_days: float, *, step: float = 3.0, first: float = 1.0) -> list[_Spec]:
    """Evenly spaced events across the range."""
    specs: list[_Spec] = []
    offset = first
    index = 0
    while offset <= range_days - 0.5:
        specs.append(
            _Spec(
                days_ago=offset,
                relationship="CREATED" if index % 2 == 0 else "REVIEWED",
                summary=f"Mock activity on day -{offset:g}",
                other_type="PullRequest" if index % 2 == 0 else "Issue",
            )
        )
        offset += step
        index += 1
    return specs


def _drop(specs: list[_Spec], low: float, high: float) -> list[_Spec]:
    """Remove specs whose ``days_ago`` falls within ``[low, high]``."""
    return [spec for spec in specs if spec.days_ago < low or spec.days_ago > high]


def _time_edge_specs(end: datetime) -> list[_Spec]:
    """Boundary-time events: midnight, 23:59, month edges, duplicate stamps."""
    first_of_month = end.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    prev_month_end = first_of_month - timedelta(days=1)
    duplicate = (end - timedelta(days=2)).replace(hour=10, minute=0, second=0, microsecond=0)
    return [
        _Spec(at=(end - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)),
        _Spec(at=(end - timedelta(days=1)).replace(hour=23, minute=59, second=0, microsecond=0)),
        _Spec(at=first_of_month),
        _Spec(at=prev_month_end.replace(hour=23, minute=59, second=0, microsecond=0)),
        _Spec(at=duplicate, summary="Duplicate timestamp A"),
        _Spec(at=duplicate, summary="Duplicate timestamp B"),
    ]


def _card_variety_specs() -> list[_Spec]:
    """Contract edge cases for card rendering."""
    return [
        _Spec(days_ago=1, summary=None, relationship="CREATED"),
        _Spec(days_ago=2, summary="A very long summary " * 12, relationship="REVIEWED"),
        _Spec(days_ago=3, url=None, summary="Event with no source link"),
        _Spec(
            days_ago=4,
            summary="<script>alert('xss')</script>",
            other_type="UnknownThing",
            source="unknown",
        ),
        _Spec(days_ago=5, summary="Café ☕ 日本語 🚀 — non-ASCII"),
        _Spec(days_ago=6, other_type="Page", source="confluence", summary="Docs page updated"),
    ]


def _lane_specs(  # pylint: disable=too-many-return-statements,too-many-branches
    scenario: str, lane_index: int, range_days: float, limit: int, end: datetime
) -> list[_Spec]:
    """Return the event specs for one lane under a scenario."""
    if scenario == "empty_range":
        return []
    if scenario == "empty_lane":
        return [] if lane_index == 0 else _even(range_days)
    if scenario == "gaps_small":
        base = _even(range_days, step=2.0)
        return _drop(base, 5.0, 7.0) if lane_index == 0 else base
    if scenario == "gaps_global":
        return _drop(_even(range_days, step=2.0), 8.0, 11.0)
    if scenario == "gap_30d":
        return _drop(_even(max(range_days, 60.0), step=2.0), 5.0, 35.0)
    if scenario == "gaps_staggered":
        base = _even(range_days, step=2.0)
        windows = {0: (4.0, 6.0), 1: (9.0, 12.0), 2: (2.0, 3.0)}
        window = windows.get(lane_index)
        return _drop(base, *window) if window else base
    if scenario == "spike_100":
        if lane_index == 0:
            return [
                _Spec(
                    days_ago=3,
                    hour=9,
                    minute=index % 60,
                    relationship="COMMITTED",
                    summary=f"Commit {index + 1}",
                    other_type="Commit",
                )
                for index in range(100)
            ]
        return _even(range_days)
    if scenario == "cell_boundary":
        if lane_index == 0:
            specs: list[_Spec] = []
            for count, days_ago in ((3, 2.0), (4, 4.0), (20, 6.0), (21, 8.0)):
                for index in range(count):
                    specs.append(
                        _Spec(days_ago=days_ago, hour=9, minute=index, summary=f"Event {index + 1}")
                    )
            return specs
        return _even(range_days)
    if scenario == "time_edges":
        return _time_edge_specs(end) if lane_index == 0 else _even(range_days)
    if scenario == "card_variety":
        return _card_variety_specs() if lane_index == 0 else _even(range_days)
    if scenario == "pagination":
        if lane_index == 0:
            count = limit * 3 - 5
        elif lane_index == 1:
            count = limit  # exactly one page → optimistic-cursor trap
        else:
            count = 5
        return [
            _Spec(days_ago=1.0 + index * 0.4, summary=f"Paged event {index + 1}")
            for index in range(count)
        ]
    if scenario == "error_500":
        raise RuntimeError("Mock scenario error_500: simulated backend failure")
    # "even", "history", "suggest_variants" and any default.
    return _even(range_days)


# ---------------------------------------------------------------------------
# Materialization
# ---------------------------------------------------------------------------


def _spec_time(spec: _Spec, end: datetime) -> datetime:
    """Resolve a spec to an absolute datetime."""
    if spec.at is not None:
        return _as_utc(spec.at)
    base = end - timedelta(days=spec.days_ago)
    return base.replace(hour=spec.hour, minute=spec.minute, second=0, microsecond=0)


def _materialize(  # pylint: disable=too-many-arguments,too-many-locals
    specs: list[_Spec],
    *,
    scenario: str,
    lane_index: int,
    lane_entity_type: str,
    lane_label: str,
    scope: str,
    start: datetime,
    end: datetime,
) -> list[TimelineEvent]:
    """Convert specs into ``TimelineEvent`` models, newest-first, in range."""
    events: list[TimelineEvent] = []
    for index, spec in enumerate(specs):
        when = _spec_time(spec, end)
        if when < start or when > end:
            continue
        relationship: str
        summary: str | None
        entity_type: str
        details: dict[str, Any]
        if scope == "history":
            relationship = "STATE_CHANGE"
            summary = lane_label
            entity_type = lane_entity_type
            details = {
                "url": spec.url,
                "status": "updated",
                "mock_scenario": scenario,
            }
        else:
            relationship = spec.relationship
            summary = spec.summary
            entity_type = spec.other_type
            details = {}
        events.append(
            TimelineEvent(
                signal_id=str(uuid.uuid5(_NAMESPACE, f"{scenario}|{lane_index}|{index}")),
                event_time=when,
                relationship_type=relationship,
                summary=summary,
                entity_type=entity_type,
                source=spec.source,
                url=spec.url,
                details=details,
            )
        )
    # Newest first; ties keep insertion order (stable).
    events.sort(key=lambda event: event.event_time, reverse=True)
    return events


def _paginate(
    events: list[TimelineEvent], cursor: str | None, limit: int
) -> tuple[list[TimelineEvent], str | None]:
    """Slice one page and emit a cursor whenever the page is full.

    Mirrors the real service, including its *optimistic* cursor: a full page
    yields a cursor even when no further rows exist, so the next request can
    legitimately return an empty page.
    """
    offset = _cursor_offset(cursor)
    page = events[offset : offset + limit]
    next_cursor: str | None = None
    if page and len(page) == limit:
        next_cursor = _encode_cursor(page[-1].event_time, offset + len(page))
    return page, next_cursor


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------


def build_timeline(request: TimelineRequest, scenario: str) -> TimelineResponse:
    """Build a deterministic :class:`TimelineResponse` for ``scenario``.

    With no ``from`` the request means *All time*; the mock synthesises a deep,
    fixed-length history so "Load more" keeps yielding older events for QA.
    """
    end = _as_utc(request.to) if request.to else datetime.now(timezone.utc)
    start = (
        _as_utc(request.from_)
        if request.from_
        else end - timedelta(days=_ALL_TIME_RANGE_DAYS)
    )
    if start > end:
        start, end = end, start
    range_days = max((end - start).total_seconds() / 86400.0, 1.0)

    logger.warning(
        f"[Activity][MOCK] Serving mock scenario {scenario!r} "
        f"lanes={len(request.wba_ids)} scope={request.scope} "
        f"range_days={range_days:.1f}"
    )

    lanes: list[TimelineLane] = []
    for lane_index, wba_id in enumerate(request.wba_ids):
        entity_type, label, avatar_url = _lane_identity(wba_id, scenario, lane_index)
        specs = _lane_specs(scenario, lane_index, range_days, request.limit, end)
        events = _materialize(
            specs,
            scenario=scenario,
            lane_index=lane_index,
            lane_entity_type=entity_type,
            lane_label=label,
            scope=request.scope,
            start=start,
            end=end,
        )
        page, next_cursor = _paginate(events, request.cursor, request.limit)
        lanes.append(
            TimelineLane(
                wba_id=wba_id,
                entity_type=entity_type,
                label=label,
                avatar_url=avatar_url,
                events=page,
                next_cursor=next_cursor,
            )
        )

    return TimelineResponse(
        lanes=lanes,
        meta=TimelineMeta(
            time_range={"from": request.from_, "to": request.to},
            total_lanes=len(lanes),
        ),
    )


# (wba_id, label, entity_type, source, avatar_url)
_SUGGESTION_CATALOGUE: tuple[tuple[str, str, str, str, str | None], ...] = (
    ("mock::Person::alice", "Alice Johnson", "Person", "github",
     "https://avatars.githubusercontent.com/u/1?v=4"),
    ("mock::Person::bob", "Bob Smith", "Person", "github", None),
    ("mock::Person::carol", "Carol Diaz", "Person", "jira",
     "https://avatars.githubusercontent.com/u/3?v=4"),
    ("mock::PullRequest::142", "PR #142: Refactor scheduler", "PullRequest", "github", None),
    ("mock::Issue::BUG-7", "BUG-7 Login fails", "Issue", "jira", None),
    ("mock::Page::home", "Docs Home", "Page", "confluence", None),
)


def build_suggestions(query_text: str, limit: int) -> list[Suggestion]:
    """Return deterministic typeahead suggestions.

    Filters the fixed catalogue by substring; when nothing matches, returns the
    catalogue head so any query still yields lanes to select. The literal query
    ``none`` returns an empty list to exercise the no-results path.
    """
    term = (query_text or "").strip().lower()
    logger.warning(f"[Activity][MOCK] Serving mock suggestions q={term!r} limit={limit}")
    if term == "none":
        return []
    matches = [
        row
        for row in _SUGGESTION_CATALOGUE
        if term in row[1].lower() or term in row[0].lower()
    ]
    if not matches:
        matches = list(_SUGGESTION_CATALOGUE)
    return [
        Suggestion(
            wba_id=wba_id,
            label=label,
            entity_type=entity_type,
            source=source,
            avatar_url=avatar_url,
        )
        for wba_id, label, entity_type, source, avatar_url in matches[:limit]
    ]


_ACTIVE_SCENARIO = (settings.TIMELINE_MOCK_SCENARIO or "").strip().lower()
if _ACTIVE_SCENARIO:
    logger.warning(
        "[Activity][MOCK] Timeline mock mode is ENABLED via "
        f"TIMELINE_MOCK_SCENARIO={_ACTIVE_SCENARIO!r}. This endpoint will serve "
        "INVENTED data. Never enable this in a real deployment."
    )

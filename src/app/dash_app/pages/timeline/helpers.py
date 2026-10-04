"""Pure helpers for the Activity Timeline page.

These functions are deliberately free of Dash and network dependencies so they
can be unit-tested directly. UI-1 uses the selection and colour helpers; later
phases extend this module with bucketing/card helpers.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone
from typing import Any
from urllib.parse import parse_qs
from zoneinfo import ZoneInfo

# Soft cap on the number of lanes (design decision #4).
MAX_LANES = 5

# Minimum query length accepted by ``GET /api/v1/activity/suggest``. Shorter
# queries are rejected with 422 by the router, so the UI must gate client-side.
MIN_QUERY_LENGTH = 2

# Lane accent token keys, resolved to colours through ``get_theme_tokens(...)``
# at render time (never treated as hex here).
_LANE_TOKEN_KEYS: list[str] = [f"timeline.lane.{index}" for index in range(1, MAX_LANES + 1)]

# Short display labels for the PascalCase ``entity_type`` values the API sends.
# Unmapped types fall back to the raw type string.
_ENTITY_TYPE_LABELS: dict[str, str] = {
    "Person": "Person",
    "PullRequest": "PR",
    "Issue": "Issue",
    "Commit": "Commit",
    "Page": "Page",
    "Epic": "Epic",
    "Repository": "Repository",
    "Branch": "Branch",
    "Project": "Project",
    "Team": "Team",
    "Sprint": "Sprint",
    "File": "File",
    "Space": "Space",
    "Initiative": "Initiative",
    "Blogpost": "Blogpost",
    "IdentityMapping": "Identity",
}

# Font Awesome 6 icon class used when no avatar is available.
_ENTITY_TYPE_ICONS: dict[str, str] = {
    "Person": "fas fa-user",
    "PullRequest": "fas fa-code-pull-request",
    "Issue": "fas fa-circle-exclamation",
    "Commit": "fas fa-code-commit",
    "Page": "fas fa-file-lines",
    "Epic": "fas fa-layer-group",
    "Repository": "fas fa-book",
    "Branch": "fas fa-code-branch",
    "Project": "fas fa-diagram-project",
    "Team": "fas fa-users",
    "Sprint": "fas fa-person-running",
    "File": "fas fa-file",
    "Space": "fas fa-globe",
    "Initiative": "fas fa-bullseye",
    "Blogpost": "fas fa-newspaper",
    "IdentityMapping": "fas fa-id-card",
}

_DEFAULT_ENTITY_ICON = "fas fa-cube"


def assign_lane_colors(count: int) -> list[str]:
    """Return the first ``count`` lane accent token **keys**.

    Colours are assigned by selection order; removing a lane and reassigning
    keeps the surviving lanes' colours distinct. More than :data:`MAX_LANES`
    keys are never returned.
    """
    if count <= 0:
        return []
    return list(_LANE_TOKEN_KEYS[: min(count, MAX_LANES)])


def entity_type_label(entity_type: str) -> str:
    """Return the short display label for an entity type (unknown → raw type)."""
    return _ENTITY_TYPE_LABELS.get(entity_type, entity_type)


def entity_type_icon(entity_type: str) -> str:
    """Return the Font Awesome icon class for an entity type."""
    return _ENTITY_TYPE_ICONS.get(entity_type, _DEFAULT_ENTITY_ICON)


def add_selection(
    selection: list[dict[str, Any]], item: dict[str, Any]
) -> list[dict[str, Any]]:
    """Return ``selection`` with ``item`` appended, idempotently.

    Adding an item whose ``wba_id`` is already selected is a no-op, as is
    adding beyond :data:`MAX_LANES` or adding an item without a ``wba_id``.
    The input list is never mutated.
    """
    wba_id = item.get("wba_id")
    if not wba_id:
        return list(selection)
    if any(existing.get("wba_id") == wba_id for existing in selection):
        return list(selection)
    if len(selection) >= MAX_LANES:
        return list(selection)
    return [*selection, dict(item)]


def remove_selection(
    selection: list[dict[str, Any]], wba_id: str | None
) -> list[dict[str, Any]]:
    """Return ``selection`` without the entry matching ``wba_id``."""
    return [item for item in selection if item.get("wba_id") != wba_id]


def is_full(selection: list[dict[str, Any]]) -> bool:
    """Return whether the selection has reached the soft lane cap."""
    return len(selection) >= MAX_LANES


# ---------------------------------------------------------------------------
# Period bucketing (UI-2)
# ---------------------------------------------------------------------------

DAY = "day"
WEEK = "week"
MONTH = "month"
GRANULARITIES: tuple[str, ...] = (DAY, WEEK, MONTH)


def _to_local(value: datetime, tz: ZoneInfo) -> datetime:
    """Convert a possibly-naive datetime to the display timezone."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(tz)


def _parse_event_time(raw: Any) -> datetime | None:
    """Parse an ISO 8601 event timestamp, or ``None`` when absent/invalid."""
    if not isinstance(raw, str) or not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def _week_start(value: datetime) -> date:
    """Return the Monday of ``value``'s ISO week."""
    return (value - timedelta(days=value.weekday())).date()


def period_ordinal(value: datetime, granularity: str) -> int:
    """Return a monotonic integer for the period containing ``value``.

    Successive periods differ by 1, so the gap between two periods is
    ``ordinal(newer) - ordinal(older) - 1``.
    """
    if granularity == MONTH:
        return value.year * 12 + value.month
    if granularity == WEEK:
        return _week_start(value).toordinal() // 7
    return value.date().toordinal()


def period_key(value: datetime, granularity: str) -> str:
    """Return a stable, sortable key for the period containing ``value``."""
    if granularity == MONTH:
        return value.strftime("%Y-%m")
    if granularity == WEEK:
        return _week_start(value).isoformat()
    return value.strftime("%Y-%m-%d")


def period_label(period_key_value: str, granularity: str) -> str:
    """Return the axis label for a period key (Day `Mar 15`, Week `Mar 9 – 15`,
    Month `March 2026`)."""
    if granularity == MONTH:
        year, month = period_key_value.split("-")
        return date(int(year), int(month), 1).strftime("%B %Y")
    if granularity == WEEK:
        start = date.fromisoformat(period_key_value)
        end = start + timedelta(days=6)
        return f"{start.strftime('%b %d')} – {end.strftime('%b %d')}"
    return date.fromisoformat(period_key_value).strftime("%b %d")


def bucket_by_period(
    lanes: list[dict[str, Any]], granularity: str, tz: ZoneInfo
) -> list[dict[str, Any]]:
    """Group events into shared period rows across all lanes.

    Returns the union of every lane's periods (only periods with at least one
    event), newest-first. Each row is
    ``{period_key, label, ordinal, cells: {wba_id: [events]}}`` with events
    newest-first inside each cell. Lanes without events in a period are absent
    from ``cells`` here — see :func:`build_grid`, which fills them as empty.
    """
    buckets: dict[str, dict[str, Any]] = {}
    for lane in lanes:
        wba_id = lane.get("wba_id")
        if not wba_id:
            continue
        for event in lane.get("events", []) or []:
            parsed = _parse_event_time(event.get("event_time"))
            if parsed is None:
                continue
            local = _to_local(parsed, tz)
            key = period_key(local, granularity)
            row = buckets.setdefault(
                key,
                {
                    "period_key": key,
                    "label": period_label(key, granularity),
                    "ordinal": period_ordinal(local, granularity),
                    "cells": {},
                },
            )
            row["cells"].setdefault(wba_id, []).append(event)

    rows = sorted(buckets.values(), key=lambda row: row["ordinal"], reverse=True)
    for row in rows:
        for events in row["cells"].values():
            events.sort(key=lambda event: event.get("event_time") or "", reverse=True)
    return rows


def build_grid(
    lanes: list[dict[str, Any]], granularity: str, tz: ZoneInfo
) -> list[dict[str, Any]]:
    """Return the ordered period rows with an explicit (possibly empty) cell
    for every requested lane, so a day active for one lane renders an empty
    cell — not a missing row — for the others."""
    rows = bucket_by_period(lanes, granularity, tz)
    wba_ids = [lane.get("wba_id") for lane in lanes if lane.get("wba_id")]
    for row in rows:
        cells = row["cells"]
        for wba_id in wba_ids:
            cells.setdefault(wba_id, [])
    return rows


def find_idle_runs(
    rows: list[dict[str, Any]], granularity: str
) -> list[dict[str, Any]]:
    """Return the maximal runs of periods with no events in any lane.

    Idle periods are exactly the gaps between consecutive present rows, so each
    run excludes the bounding (present) periods. Each run is
    ``{count, start_ordinal, end_ordinal}``; the units follow ``granularity``.
    Used by UI-5 to render collapsed idle separators.
    """
    runs: list[dict[str, Any]] = []
    for newer, older in zip(rows, rows[1:]):
        gap = int(newer["ordinal"]) - int(older["ordinal"]) - 1
        if gap > 0:
            runs.append(
                {
                    "count": gap,
                    "start_ordinal": int(older["ordinal"]) + 1,
                    "end_ordinal": int(newer["ordinal"]) - 1,
                    "granularity": granularity,
                }
            )
    return runs


def extract_mock_scenario(search: str | None) -> str | None:
    """Return the ``mock`` query-param value from a URL search string."""
    if not search:
        return None
    values = parse_qs(search.lstrip("?")).get("mock") or []
    return values[0] if values else None


def extract_scope(search: str | None) -> str:
    """Return the timeline scope from a URL search string.

    ``activity`` (default) or ``history``; anything else falls back to activity.
    This pre-stages the UI-6 toolbar / UI-11 deep-link parsing.
    """
    if not search:
        return "activity"
    values = parse_qs(search.lstrip("?")).get("scope") or []
    scope = values[0] if values else "activity"
    return scope if scope in ("activity", "history") else "activity"


# ---------------------------------------------------------------------------
# Card helpers (UI-3)
# ---------------------------------------------------------------------------

# Base graph node token keys that exist in THEME_TOKENS; anything else falls
# back to the neutral default.
_ENTITY_TYPE_TOKEN_KEYS: frozenset[str] = frozenset(
    {
        "default",
        "project",
        "person",
        "branch",
        "epic",
        "issue",
        "repository",
        "team",
        "identity_mapping",
        "initiative",
        "sprint",
        "commit",
        "file",
        "pull_request",
        "space",
        "page",
        "blogpost",
    }
)


def humanize_relationship(relationship_type: str) -> str:
    """Return a human-readable relationship label (``STATE_CHANGE`` → "Updated")."""
    if not relationship_type:
        return ""
    if relationship_type.upper() == "STATE_CHANGE":
        return "Updated"
    return relationship_type.replace("_", " ").title()


def card_summary(event: dict[str, Any]) -> str:
    """Return the card's first line: the summary, or a relationship+type fallback.

    ``activity``-scope events may carry ``summary=None`` (e.g. File events), so
    fall back to ``<Relationship> · <EntityType>`` rather than an empty card.
    """
    summary = event.get("summary")
    if isinstance(summary, str) and summary.strip():
        return summary.strip()
    relationship = humanize_relationship(str(event.get("relationship_type") or ""))
    entity_type = entity_type_label(str(event.get("entity_type") or ""))
    fallback = " · ".join(part for part in (relationship, entity_type) if part)
    return fallback or "Event"


def entity_type_token(entity_type: str) -> str:
    """Map a PascalCase API ``entity_type`` to its base graph-node token key.

    ``PullRequest`` → ``graph.node.pull_request``, ``Page`` → ``graph.node.page``;
    unknown types return ``graph.node.default``.
    """
    snake = re.sub(r"(?<!^)(?=[A-Z])", "_", entity_type or "").lower()
    token = f"graph.node.{snake}"
    return token if snake in _ENTITY_TYPE_TOKEN_KEYS else "graph.node.default"


def entity_type_color(
    entity_type: str,
    effective_nodes: dict[str, Any] | None,
    base_tokens: dict[str, Any],
) -> str:
    """Resolve an entity type's colour.

    Prefers the effective graph theme (``/graph-themes/effective``, which merges
    user Graph-Styling overrides) keyed by the PascalCase ``entity_type``;
    falls back to the base theme token for the type, then to the neutral default.
    """
    if effective_nodes:
        node = effective_nodes.get(entity_type)
        if isinstance(node, dict) and node.get("background-color"):
            return str(node["background-color"])
    return str(
        base_tokens.get(
            entity_type_token(entity_type), base_tokens.get("graph.node.default", "")
        )
    )


def popup_fields(event: dict[str, Any], datetime_text: str) -> dict[str, Any]:
    """Build the JSON payload carried on each card for the UI-4 hover popup.

    Includes the source ``url`` key **only** when the event has one, so the
    popup renders the "Open source" link only when there is somewhere to go.
    """
    fields: dict[str, Any] = {
        "summary": card_summary(event),
        "relationship": humanize_relationship(
            str(event.get("relationship_type") or "")
        ),
        "entity_type": entity_type_label(str(event.get("entity_type") or "")),
        "source": str(event.get("source") or ""),
        "datetime": datetime_text,
    }
    url = event.get("url")
    if isinstance(url, str) and url:
        fields["url"] = url
    return fields

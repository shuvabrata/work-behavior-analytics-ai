"""Pure helpers for the Activity Timeline page.

These functions are deliberately free of Dash and network dependencies so they
can be unit-tested directly: selection and colour helpers, period bucketing,
card and popup payloads, idle-run spans, the time range, cell overflow,
pagination, and deep-link parsing.
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
# Period bucketing
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
    Used to render collapsed idle separators.
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
    Seeds the Scope control from the inbound deep-link contract.
    """
    if not search:
        return "activity"
    values = parse_qs(search.lstrip("?")).get("scope") or []
    scope = values[0] if values else "activity"
    return scope if scope in ("activity", "history") else "activity"


def _extract_iso_date(search: str | None, key: str) -> str | None:
    """Return a valid ISO date query-param from the URL, else ``None``."""
    values = parse_qs((search or "").lstrip("?")).get(key) or []
    if not values:
        return None
    value = values[0]
    try:
        date.fromisoformat(value)
    except ValueError:
        return None
    return value


def extract_from(search: str | None) -> str | None:
    """Return a valid ISO ``from`` date from the URL, else ``None``.

    Seeds the Custom range start for inbound deep-links; absence means *All time*.
    """
    return _extract_iso_date(search, "from")


def extract_to(search: str | None) -> str | None:
    """Return a valid ISO ``to`` date from the URL, else ``None``."""
    return _extract_iso_date(search, "to")


def extract_group(search: str | None) -> str | None:
    """Return a valid ``group`` granularity from the URL, else ``None``.

    Parsed for the inbound deep-link contract; seeds the Group-by control.
    """
    values = parse_qs((search or "").lstrip("?")).get("group") or []
    if not values:
        return None
    value = values[0]
    return value if value in GRANULARITIES else None


def is_valid_wba_id(wba_id: str) -> bool:
    """Return whether *wba_id* is a well-formed ``{source}::{type}::{id}`` key.

    Mirrors ``service.parse_wba_id`` (the router rejects the whole request with a
    400 if any id is malformed, so the UI must filter client-side first). Only the
    first two ``::`` separators split — the id itself may contain ``::``.
    """
    parts = (wba_id or "").split("::", 2)
    return len(parts) == 3 and all(parts)


def selection_from_wba_ids(wba_ids: list[str]) -> list[dict[str, Any]]:
    """Build selection entries from deep-linked ids (idempotent, capped).

    A URL carries only the canonical key, so there is no display name: the label
    falls back to the key's id segment and the entity type comes from the middle
    segment. Entries are added through :func:`add_selection`, so duplicates are
    ignored and the :data:`MAX_LANES` cap holds.
    """
    selection: list[dict[str, Any]] = []
    for wba_id in wba_ids:
        parts = wba_id.split("::", 2)
        selection = add_selection(
            selection,
            {
                "wba_id": wba_id,
                "label": parts[2] or wba_id,
                "entity_type": parts[1],
                "avatar_url": None,
            },
        )
    return selection


def parse_deeplink_params(search: str | None) -> dict[str, Any]:
    """Parse the inbound deep-link contract from a URL search string.

    Returns ``{wba_ids, dropped, group, scope, from, to}`` where ``wba_ids`` holds
    only the well-formed keys (in URL order) and ``dropped`` the rejected ones.
    ``group``/``scope`` fall back to their defaults; ``from``/``to`` are returned
    only as a valid pair — a missing, malformed, or reversed pair becomes *All
    time* (``None``/``None``). Unknown params are ignored. Dev-only ``mock`` is
    handled separately (read per-request by the fetch).
    """
    raw = (parse_qs((search or "").lstrip("?").strip("?")).get("wba_ids") or [""])[0]
    candidates = [part.strip() for part in raw.split(",") if part.strip()]
    wba_ids = [key for key in candidates if is_valid_wba_id(key)]
    dropped = [key for key in candidates if not is_valid_wba_id(key)]

    from_value = extract_from(search)
    to_value = extract_to(search)
    if not from_value or not to_value:
        from_value = to_value = None
    else:
        try:
            resolve_range(CUSTOM_RANGE, from_value, to_value)
        except ValueError:
            from_value = to_value = None

    return {
        "wba_ids": wba_ids,
        "dropped": dropped,
        "group": extract_group(search) or DAY,
        "scope": extract_scope(search),
        "from": from_value,
        "to": to_value,
    }


# ---------------------------------------------------------------------------
# Card helpers
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
    """Build the JSON payload carried on each card for the hover popup.

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


# ---------------------------------------------------------------------------
# Idle runs
# ---------------------------------------------------------------------------


def _ordinal_to_date(ordinal: int, granularity: str) -> date:
    """Inverse of :func:`period_ordinal` — the first day of a period ordinal."""
    if granularity == MONTH:
        year = (ordinal - 1) // 12
        month = (ordinal - 1) % 12 + 1
        return date(year, month, 1)
    if granularity == WEEK:
        # Monday ordinals satisfy o % 7 == 1, so ordinal k → 7k + 1.
        return date.fromordinal(ordinal * 7 + 1)
    return date.fromordinal(ordinal)


def _ordinal_to_key(ordinal: int, granularity: str) -> str:
    """Return the period key for a period ordinal."""
    start = _ordinal_to_date(ordinal, granularity)
    if granularity == MONTH:
        return start.strftime("%Y-%m")
    return start.isoformat()


def _unit_phrase(count: int, granularity: str) -> str:
    """Return e.g. ``3 days`` / ``1 month`` for an idle run."""
    noun = {DAY: "day", WEEK: "week", MONTH: "month"}.get(granularity, "period")
    return f"{count} {noun}{'s' if count != 1 else ''}"


def _span_label(start: date, end: date, granularity: str) -> str:
    """Return the date-span text for an idle run (e.g. ``Mar 12 – 14``)."""
    if granularity == MONTH:
        if (start.year, start.month) == (end.year, end.month):
            return f"{start:%b %Y}"
        return f"{start:%b %Y} – {end:%b %Y}"
    last = end + timedelta(days=6) if granularity == WEEK else end
    if start == last:
        return f"{start:%b} {start.day}"
    if start.month == last.month:
        return f"{start:%b} {start.day} – {last.day}"
    return f"{start:%b} {start.day} – {last:%b} {last.day}"


def idle_run_key(run: dict[str, Any]) -> str:
    """Return a stable key for an idle run (used as expansion-state id)."""
    return f"{run.get('granularity')}:{run.get('start_ordinal')}:{run.get('end_ordinal')}"


def idle_run_label(run: dict[str, Any]) -> str:
    """Return the idle-run bar label, e.g. ``Mar 12 – 14 · 3 days no activity``."""
    granularity = str(run.get("granularity") or DAY)
    start = _ordinal_to_date(int(run["start_ordinal"]), granularity)
    end = _ordinal_to_date(int(run["end_ordinal"]), granularity)
    span = _span_label(start, end, granularity)
    return f"{span} · {_unit_phrase(int(run['count']), granularity)} no activity"


def idle_run_period_labels(run: dict[str, Any]) -> list[str]:
    """Return the hidden period labels for an expanded run, newest-first."""
    granularity = str(run.get("granularity") or DAY)
    return [
        period_label(_ordinal_to_key(ordinal, granularity), granularity)
        for ordinal in range(
            int(run["end_ordinal"]), int(run["start_ordinal"]) - 1, -1
        )
    ]


def toggle_expanded(expanded: list[str], key: str) -> list[str]:
    """Return ``expanded`` with ``key`` added if absent, else removed."""
    if key in expanded:
        return [item for item in expanded if item != key]
    return [*expanded, key]


# ---------------------------------------------------------------------------
# Cell overflow
# ---------------------------------------------------------------------------

# Maximum cards rendered per cell before the "+N more" link appears.
MAX_CELL_CARDS = 3


def cap_cell(
    events: list[dict[str, Any]], cap: int = MAX_CELL_CARDS
) -> tuple[list[dict[str, Any]], int]:
    """Return ``(visible_events, hidden_count)`` for one cell.

    ``visible_events`` is the first ``cap`` events; ``hidden_count`` is how many
    already-loaded events are withheld. A non-positive ``cap`` hides nothing.
    """
    if cap <= 0:
        return list(events), 0
    return list(events[:cap]), max(0, len(events) - cap)


def cell_expansion_key(row_key: str, lane_key: str) -> str:
    """Return the expansion-state key for one cell, keyed by (row, lane)."""
    return f"{row_key}|{lane_key}"


def is_cell_expanded(
    expanded: list[str], row_key: str, lane_key: str
) -> bool:
    """Return whether the (row, lane) cell is currently expanded."""
    return cell_expansion_key(row_key, lane_key) in expanded


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------


def _event_identity(event: dict[str, Any]) -> tuple[Any, ...]:
    """Return a key that is equal only for events a user cannot tell apart.

    ``signal_id`` alone is not unique per event — one ActivitySignal can produce
    several ``activity_actions`` rows (see ``db/models/activity_action.py``), all
    sharing the same ``signal_id``. De-duplicating on this fuller tuple keeps
    those distinct events while still collapsing a genuinely repeated row.
    ``details`` is excluded: it is a dict (unhashable) and carries no identity.
    """
    return (
        event.get("signal_id"),
        event.get("event_time"),
        event.get("relationship_type"),
        event.get("entity_type"),
        event.get("source"),
        event.get("url"),
        event.get("summary"),
    )


def merge_lane_page(
    lane: dict[str, Any], page_lane: dict[str, Any]
) -> dict[str, Any]:
    """Append one fetched page into a lane, de-duplicating on the event's
    identity (see :func:`_event_identity`).

    The server's ``next_cursor`` is optimistic — it is echoed whenever a full
    page is returned, even if no further rows exist. When the page carries **no
    events**, this clears the cursor (``None``) instead of storing what the
    server echoed, which is what lets the "Load more" button actually hide.
    """
    events = list(lane.get("events") or [])
    seen = {_event_identity(event) for event in events}
    for event in page_lane.get("events") or []:
        key = _event_identity(event)
        if key in seen:
            continue
        seen.add(key)
        events.append(event)
    page_events = page_lane.get("events") or []
    next_cursor = None if not page_events else page_lane.get("next_cursor")
    return {**lane, "events": events, "next_cursor": next_cursor}


def has_more(lanes: list[dict[str, Any]]) -> bool:
    """Return whether any lane still has a cursor to page from."""
    return any(lane.get("next_cursor") for lane in lanes)


# ---------------------------------------------------------------------------
# Time range
# ---------------------------------------------------------------------------

# Range control values: "all" (default, unbounded) or "custom" (explicit dates).
ALL_TIME = "all"
CUSTOM_RANGE = "custom"


def _date_bound(value: str, *, end_of_day: bool) -> datetime:
    """Parse an ISO date string into a UTC datetime bound of that day."""
    day = date.fromisoformat(value)
    if end_of_day:
        return datetime(day.year, day.month, day.day, 23, 59, 59, tzinfo=timezone.utc)
    return datetime(day.year, day.month, day.day, tzinfo=timezone.utc)


def resolve_range(
    range_value: str,
    custom_from: str | None = None,
    custom_to: str | None = None,
    *,
    now: datetime | None = None,
) -> tuple[datetime | None, datetime]:
    """Resolve the Range control to ``(from_dt, to_dt)`` in UTC.

    *All time* (the default) returns ``(None, now)`` — no lower bound, so the
    server pages backward through all history (decision #23). ``custom`` uses the
    supplied ISO dates — start at 00:00:00, end at 23:59:59 — and raises
    ``ValueError`` if either is missing or start > end.
    """
    now_dt = now or datetime.now(timezone.utc)
    if range_value != CUSTOM_RANGE:
        return None, now_dt
    if not custom_from or not custom_to:
        raise ValueError("custom range requires both start and end dates")
    start = _date_bound(custom_from, end_of_day=False)
    end = _date_bound(custom_to, end_of_day=True)
    if start > end:
        raise ValueError("range start must be on or before the end date")
    return start, end

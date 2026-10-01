"""Activity Timeline page callbacks.

Wires the swimlane page to the Phase 2 API:

* ``GET /api/v1/activity/timeline`` — fetch lanes (initial + load-more)
* ``GET /api/v1/activity/suggest`` — typeahead suggestions

State model
-----------
* ``timeline-selected-entities`` (``dcc.Store``, session): list of selected
  entity dicts ``{"wba_id", "label", "entity_type", "source", "avatar_url"}``.
* ``timeline-lane-state`` (``dcc.Store``, session): dict keyed by ``wba_id``
  holding ``{"events": [...], "next_cursor": str | None, "label": ...,
  "avatar_url": ...}`` — the accumulated per-lane data.
* ``timeline-last-params`` (``dcc.Store``, session): the query params of the
  last successful fetch, used to re-fetch on load-more.

Pagination uses a single global "Load More" button: clicking it fetches the
next page for every lane that still has a ``next_cursor`` and appends the
events.  The button is hidden when all lanes are exhausted.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import os
import requests
from dash import ALL, Input, Output, State, callback, ctx, html, no_update
from dash.exceptions import PreventUpdate

from app.common.timezone import to_app_timezone
from app.dash_app.components.common import create_alert, create_empty_state
from app.dash_app.pages.timeline.geometry import (
    build_compressed_axis_markers,
    compute_lane_layout,
)
from app.dash_app.pages.timeline.layout import (
    DEFAULT_LIMIT,
    DEFAULT_TIME_RANGE,
    TIME_RANGE_PRESETS,
)
from app.dash_app.styles import COLOR_NAVY
from app.runtime_settings import runtime_settings
from common.logger import logger


def _get_api_base_url() -> str:
    """Return the configured API base URL (same pattern as search/graph pages)."""
    return os.getenv("API_BASE_URL", "http://localhost:8000")


# ---------------------------------------------------------------------------
# Time range helpers
# ---------------------------------------------------------------------------


def _resolve_time_range(
    preset: str | None,
    custom_range: list[str | None] | None,
) -> tuple[datetime, datetime] | None:
    """Resolve the effective ``[from, to]`` window from the preset + custom range.

    Returns ``None`` when the preset is ``custom`` but no valid custom range is
    provided (the caller should then fall back to the default window).
    """
    preset = preset or DEFAULT_TIME_RANGE
    now = datetime.now(timezone.utc)

    if preset == "custom":
        if not custom_range or len(custom_range) != 2:
            return None
        start_raw, end_raw = custom_range
        if not start_raw or not end_raw:
            return None
        try:
            start = datetime.fromisoformat(str(start_raw).replace("Z", "+00:00"))
            end = datetime.fromisoformat(str(end_raw).replace("Z", "+00:00"))
        except ValueError:
            return None
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        if end.tzinfo is None:
            end = end.replace(tzinfo=timezone.utc)
        # DatePickerRange returns date-only strings; extend end to end-of-day.
        end = end.replace(hour=23, minute=59, second=59, microsecond=999999)
        return start.astimezone(timezone.utc), end.astimezone(timezone.utc)

    days = TIME_RANGE_PRESETS.get(preset, TIME_RANGE_PRESETS[DEFAULT_TIME_RANGE])
    return now - timedelta(days=days), now


def _format_iso(dt: datetime) -> str:
    """Format a datetime as an ISO-8601 string for the API query param."""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Rendering helpers
# ---------------------------------------------------------------------------


def _entity_initial(entity: dict[str, Any]) -> str:
    """Return a 1-2 letter initial for an entity chip avatar."""
    label = entity.get("label") or entity.get("wba_id") or "?"
    words = [w for w in label.split() if w]
    if len(words) >= 2:
        return (words[0][0] + words[-1][0]).upper()
    return label[:2].upper() if label else "?"


def _build_chips(entities: list[dict[str, Any]]) -> list[Any]:
    """Build the selected-entity chip pills."""
    if not entities:
        return [
            create_empty_state("No entities selected — search above to add lanes.", icon="🏊")
        ]
    chips: list[Any] = []
    for entity in entities:
        chips.append(
            html.Span(
                [
                    html.Span(
                        _entity_initial(entity),
                        className="timeline-chip-avatar",
                    ),
                    html.Span(
                        entity.get("label") or entity.get("wba_id"),
                        className="timeline-chip-label",
                    ),
                    html.Span(
                        "×",
                        id={"type": "timeline-chip-remove", "index": entity["wba_id"]},
                        className="timeline-chip-remove",
                        n_clicks=0,
                    ),
                ],
                className="timeline-chip",
                title=entity.get("wba_id"),
            )
        )
    return chips


def _build_event_card(  # pylint: disable=too-many-arguments,too-many-locals
    event: dict[str, Any],
    *,
    top: float,
    height: float,
    lane_color: str,
    gap_before: bool,
    gap_days: float,
) -> html.Div:
    """Build a single positioned event card with a hover popup."""
    summary = event.get("summary") or event.get("entity_type") or "Activity"
    rel_type = event.get("relationship_type") or ""
    entity_type = event.get("entity_type") or ""
    source = event.get("source") or ""
    url = event.get("url")
    event_time = event.get("event_time")

    time_label = ""
    if event_time:
        try:
            parsed = datetime.fromisoformat(str(event_time).replace("Z", "+00:00"))
            time_label = to_app_timezone(parsed).strftime("%b %d, %I:%M %p")
        except ValueError:
            time_label = str(event_time)

    details = event.get("details") or {}
    detail_lines: list[Any] = []
    for key in ("status", "priority", "lines_added", "files_changed", "key"):
        if key in details and details[key] is not None:
            detail_lines.append(html.Div(f"{key}: {details[key]}", className="timeline-popup-line"))

    popup_children: list[Any] = [
        html.Div(f"{rel_type} · {entity_type}", className="timeline-popup-title"),
        html.Div(summary, className="timeline-popup-summary"),
        html.Div(f"📅 {time_label}", className="timeline-popup-line"),
        html.Div(f"Source: {source}", className="timeline-popup-line"),
        *detail_lines,
    ]
    if url:
        popup_children.append(
            html.A("Open in source ↗", href=url, target="_blank", className="timeline-popup-link")
        )

    card_children: list[Any] = [
        html.Div(summary, className="timeline-card-title"),
        html.Div(
            [
                html.Span(rel_type, className="timeline-card-type"),
                html.Span(time_label, className="timeline-card-time"),
            ],
            className="timeline-card-meta",
        ),
        html.Div(popup_children, className="timeline-popup"),
    ]

    style: dict[str, Any] = {
        "top": f"{top}px",
        "height": f"{height}px",
        "borderLeftColor": lane_color,
    }
    classes = ["timeline-event-card"]
    extra_props: dict[str, Any] = {}
    if gap_before:
        classes.append("timeline-gap-before")
        extra_props["data-gap-days"] = f"{gap_days:.1f}"
    return html.Div(
        card_children,
        className=" ".join(classes),
        style=style,
        **extra_props,
    )


def _build_lane(  # pylint: disable=too-many-locals
    wba_id: str,
    lane_data: dict[str, Any],
    *,
    range_start: datetime,
    range_end: datetime,
    lane_color: str,
) -> tuple[html.Div, float]:
    """Build one swimlane column (header + positioned cards).

    Returns a ``(lane_div, body_height)`` tuple so the caller can align the
    time axis to the tallest lane.  An empty lane renders a compact
    "No activity" state instead of a full-height empty body.
    """
    events = lane_data.get("events") or []
    label = lane_data.get("label") or wba_id
    avatar_url = lane_data.get("avatar_url")
    next_cursor = lane_data.get("next_cursor")

    # The API returns events newest-first; sort oldest-first so events pair
    # with the chronological card layout.
    events = sorted(
        events,
        key=lambda e: str(e.get("event_time") or ""),
    )

    event_times: list[datetime] = []
    for event in events:
        raw = event.get("event_time")
        if raw:
            try:
                event_times.append(
                    datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
                )
            except ValueError:
                continue

    layout = compute_lane_layout(
        event_times,
        range_start=range_start,
        range_end=range_end,
    )

    # Header
    avatar: Any
    if avatar_url:
        avatar = html.Img(
            src=avatar_url,
            className="timeline-lane-avatar-img",
            alt=label,
        )
    else:
        avatar = html.Span(_entity_initial({"label": label}), className="timeline-lane-avatar")
    header = html.Div(
        [
            avatar,
            html.Div(
                [
                    html.Div(label, className="timeline-lane-name"),
                    html.Div(
                        f"{len(events)} event{'s' if len(events) != 1 else ''}",
                        className="timeline-lane-count",
                    ),
                ],
                className="timeline-lane-info",
            ),
        ],
        className="timeline-lane-header",
    )

    # Empty lane → compact "no activity" state instead of a tall empty body.
    if not events:
        body = html.Div(
            "No activity in this range",
            className="timeline-lane-empty",
        )
        return (
            html.Div(
                [header, body],
                className="timeline-lane",
                id={"type": "timeline-lane", "index": wba_id},
            ),
            0.0,
        )

    # Body: gap breaks + cards
    body_children: list[Any] = []
    for card, event in zip(layout.cards, events):
        if card.gap_before:
            body_children.append(
                html.Div(
                    f"⋮ — {card.gap_days:.0f} days —",
                    className="timeline-gap-break",
                    style={"top": f"{card.top - 14}px"},
                )
            )
        body_children.append(
            _build_event_card(
                event,
                top=card.top,
                height=card.height,
                lane_color=lane_color,
                gap_before=card.gap_before,
                gap_days=card.gap_days,
            )
        )

    body = html.Div(
        body_children,
        className="timeline-lane-body",
        style={"height": f"{max(layout.total_height, 120)}px"},
    )

    return (
        html.Div(
            [header, body],
            className="timeline-lane",
            id={"type": "timeline-lane", "index": wba_id},
        ),
        max(layout.total_height, 120.0),
    )


def _build_swimlane(
    lane_state: dict[str, Any],
    *,
    range_start: datetime,
    range_end: datetime,
) -> html.Div:
    """Build the full swimlane grid: time axis + one column per lane.

    The time axis is built from the tallest lane's event times using the same
    gap compression as the lane cards, so the axis stays aligned with the
    rendered events and does not show empty rows for days with no activity.
    """
    if not lane_state:
        return create_empty_state("Add entities to get started.", icon="🏊")

    # Deterministic lane colors from a small palette.
    palette = [
        COLOR_NAVY,
        "#6f42c1",
        "#48bb78",
        "#ed8936",
        "#4299e1",
        "#eab308",
        "#ec4899",
        "#14b8a6",
    ]
    lanes: list[Any] = []
    max_body_height = 0.0
    tallest_event_times: list[datetime] = []
    for index, (wba_id, lane_data) in enumerate(lane_state.items()):
        lane, body_height = _build_lane(
            wba_id,
            lane_data,
            range_start=range_start,
            range_end=range_end,
            lane_color=palette[index % len(palette)],
        )
        lanes.append(lane)
        if body_height > max_body_height:
            max_body_height = body_height
            tallest_event_times = _lane_event_times(lane_data)

    # Build the axis from the tallest lane's events, compressed identically to
    # the lane cards.  Empty lanes (no events) contribute no markers.
    markers = build_compressed_axis_markers(
        tallest_event_times,
        range_start=range_start,
        range_end=range_end,
    )
    axis = html.Div(
        [
            html.Div(marker.label, className="timeline-time-marker", style={"top": f"{marker.top}px"})
            for marker in markers
        ],
        className="timeline-time-axis",
    )

    return html.Div(
        [axis, *lanes],
        className="timeline-swimlane",
    )


def _lane_event_times(lane_data: dict[str, Any]) -> list[datetime]:
    """Extract the sorted event times from a lane's data."""
    events = lane_data.get("events") or []
    times: list[datetime] = []
    for event in events:
        raw = event.get("event_time")
        if raw:
            try:
                times.append(
                    datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
                )
            except ValueError:
                continue
    return times


def _has_more_pages(lane_state: dict[str, Any]) -> bool:
    """Return True when at least one lane still has a next_cursor."""
    return any(
        lane.get("next_cursor") for lane in lane_state.values()
    )


# ---------------------------------------------------------------------------
# Callbacks
# ---------------------------------------------------------------------------


@callback(
    Output("timeline-suggestions", "children"),
    Output("timeline-suggestions", "style"),
    Output("timeline-suggestions-store", "data"),
    Input("timeline-entity-search", "value"),
    State("timeline-person-only", "value"),
    prevent_initial_call=True,
)
def update_suggestions(query: str | None, person_only: list[str] | None) -> tuple[Any, Any, list[dict[str, Any]]]:
    """Fetch typeahead suggestions from the suggest API.

    ``person_only`` is accepted as a State so the Person-only toggle can be
    wired to the suggest API in Phase 5 (proper Person search).  Today the
    suggest endpoint has no entity-type filter, so the toggle is a no-op.
    """
    _ = person_only  # reserved for Phase 5 Person search
    q = (query or "").strip()
    if len(q) < 2:
        return [], {"display": "none"}, []

    try:
        suggest_params: dict[str, Any] = {"q": q, "limit": 10}
        response = requests.get(
            f"{_get_api_base_url()}/api/v1/activity/suggest",
            params=suggest_params,
            timeout=runtime_settings.get_int("HTTP_REQUEST_TIMEOUT"),
        )
        response.raise_for_status()
        results = response.json().get("results", [])
    except requests.RequestException as exc:
        logger.warning(f"[Timeline] suggest API failed: {exc}")
        return [], {"display": "none"}, []

    if not results:
        return (
            html.Div("No matches.", className="timeline-suggestion-empty"),
            {"display": "block"},
            [],
        )

    items = [
        html.Div(
            [
                html.Span(
                    result.get("label") or result.get("wba_id"),
                    className="timeline-suggestion-label",
                ),
                html.Span(
                    f"{result.get('source')} · {result.get('entity_type')}",
                    className="timeline-suggestion-meta",
                ),
            ],
            id={"type": "timeline-suggestion", "index": result["wba_id"]},
            className="timeline-suggestion-item",
            n_clicks=0,
        )
        for result in results
    ]
    return items, {"display": "block"}, results


@callback(
    Output("timeline-selected-entities", "data"),
    Output("timeline-entity-search", "value"),
    Output("timeline-suggestions", "children"),
    Output("timeline-suggestions", "style"),
    Input({"type": "timeline-suggestion", "index": ALL}, "n_clicks"),
    Input({"type": "timeline-chip-remove", "index": ALL}, "n_clicks"),
    Input("timeline-clear-btn", "n_clicks"),
    State("timeline-selected-entities", "data"),
    State("timeline-suggestions-store", "data"),
    prevent_initial_call=True,
)
def update_selected_entities(
    _suggestion_clicks: list[int | None],
    _remove_clicks: list[int | None],
    _clear_clicks: int | None,
    selected: list[dict[str, Any]] | None,
    suggestions: list[dict[str, Any]] | None,
) -> tuple[Any, ...]:
    """Add a suggestion, remove a chip, or clear all selected entities."""
    selected = list(selected or [])
    suggestions = list(suggestions or [])
    triggered_id = ctx.triggered_id

    if triggered_id == "timeline-clear-btn":
        return [], "", [], {"display": "none"}

    if isinstance(triggered_id, dict):
        component_type = triggered_id.get("type")
        index = triggered_id.get("index")

        if component_type == "timeline-suggestion":
            wba_id = index
            if wba_id and wba_id not in {e["wba_id"] for e in selected}:
                match = next(
                    (s for s in suggestions if s.get("wba_id") == wba_id),
                    {},
                )
                selected.append(
                    {
                        "wba_id": wba_id,
                        "label": match.get("label") or wba_id,
                        "entity_type": match.get("entity_type") or "",
                        "source": match.get("source") or "",
                        "avatar_url": match.get("avatar_url") or None,
                    }
                )
            return selected, "", [], {"display": "none"}

        if component_type == "timeline-chip-remove":
            selected = [e for e in selected if e["wba_id"] != index]
            return selected, no_update, no_update, no_update

    return selected, no_update, no_update, no_update


@callback(
    Output("timeline-selected-chips", "children"),
    Input("timeline-selected-entities", "data"),
    prevent_initial_call=False,
)
def render_chips(selected: list[dict[str, Any]] | None) -> Any:
    """Render the selected-entity chips."""
    return _build_chips(list(selected or []))


@callback(
    Output("timeline-custom-range", "style"),
    Input("timeline-time-range", "value"),
    prevent_initial_call=True,
)
def toggle_custom_range(preset: str | None) -> dict[str, str]:
    """Show the custom date range picker only when Custom is selected."""
    if preset == "custom":
        return {"display": "block"}
    return {"display": "none"}


@callback(
    Output("timeline-lanes-container", "children"),
    Output("timeline-load-more-row", "style"),
    Output("timeline-lane-state", "data"),
    Output("timeline-last-params", "data"),
    Output("timeline-alert-region", "children"),
    Input("timeline-selected-entities", "data"),
    Input("timeline-time-range", "value"),
    Input("timeline-custom-range", "start_date"),
    Input("timeline-custom-range", "end_date"),
    State("timeline-lane-state", "data"),
    prevent_initial_call=True,
)
def fetch_timeline_data(  # pylint: disable=too-many-locals
    selected: list[dict[str, Any]] | None,
    preset: str | None,
    custom_start: str | None,
    custom_end: str | None,
    lane_state: dict[str, Any] | None,
) -> tuple[Any, ...]:
    """Fetch the first page of timeline data for all selected entities."""
    entities = list(selected or [])
    if not entities:
        return (
            create_empty_state("Add entities to get started.", icon="🏊"),
            {"display": "none"},
            {},
            {},
            [],
        )

    time_range = _resolve_time_range(preset, [custom_start, custom_end])
    if time_range is None:
        time_range = _resolve_time_range(DEFAULT_TIME_RANGE, None)
    assert time_range is not None
    range_start, range_end = time_range

    wba_ids: list[str] = []
    for entity in entities:
        raw_wba_id = entity.get("wba_id")
        wba_ids.append(raw_wba_id if isinstance(raw_wba_id, str) else str(raw_wba_id))
    params: dict[str, Any] = {
        "wba_ids": ",".join(wba_ids),
        "limit": DEFAULT_LIMIT,
        "from": _format_iso(range_start),
        "to": _format_iso(range_end),
    }

    try:
        response = requests.get(
            f"{_get_api_base_url()}/api/v1/activity/timeline",
            params=params,
            timeout=runtime_settings.get_int("HTTP_REQUEST_TIMEOUT"),
        )
        response.raise_for_status()
        data = response.json()
    except requests.RequestException as exc:
        logger.warning(f"[Timeline] timeline API failed: {exc}")
        alert = create_alert(
            [
                html.I(className="fas fa-exclamation-circle me-2"),
                "Timeline fetch failed. Check that the application server is running.",
            ],
            color="danger",
        )
        return (
            create_empty_state("Timeline unavailable.", icon="⚠️"),
            {"display": "none"},
            lane_state or {},
            {},
            [alert],
        )

    new_state: dict[str, Any] = {}
    for lane in data.get("lanes", []):
        wba_id = lane["wba_id"]
        new_state[wba_id] = {
            "events": lane.get("events", []),
            "next_cursor": lane.get("next_cursor"),
            "label": lane.get("label") or wba_id,
            "avatar_url": lane.get("avatar_url"),
        }

    # Preserve lanes that the API returned nothing for (e.g. no activity).
    for entity in entities:
        wba_id = entity["wba_id"]
        if wba_id not in new_state:
            new_state[wba_id] = {
                "events": [],
                "next_cursor": None,
                "label": entity.get("label") or wba_id,
                "avatar_url": entity.get("avatar_url"),
            }

    lanes_html = _build_swimlane(new_state, range_start=range_start, range_end=range_end)
    load_more_style = {"display": "block"} if _has_more_pages(new_state) else {"display": "none"}
    saved_params = {
        "from": _format_iso(range_start),
        "to": _format_iso(range_end),
        "limit": DEFAULT_LIMIT,
    }
    return lanes_html, load_more_style, new_state, saved_params, []


@callback(
    Output("timeline-lanes-container", "children", allow_duplicate=True),
    Output("timeline-load-more-row", "style", allow_duplicate=True),
    Output("timeline-lane-state", "data", allow_duplicate=True),
    Output("timeline-alert-region", "children", allow_duplicate=True),
    Input("timeline-load-more-btn", "n_clicks"),
    State("timeline-lane-state", "data"),
    State("timeline-last-params", "data"),
    prevent_initial_call=True,
)
def load_more(
    _n_clicks: int | None,
    lane_state: dict[str, Any] | None,
    last_params: dict[str, Any] | None,
) -> tuple[Any, ...]:
    """Fetch the next page for every lane that still has a cursor."""
    lane_state = dict(lane_state or {})
    if not lane_state or not last_params:
        raise PreventUpdate

    pending = {
        wba_id: lane
        for wba_id, lane in lane_state.items()
        if lane.get("next_cursor")
    }
    if not pending:
        return no_update, {"display": "none"}, lane_state, []

    range_start = datetime.fromisoformat(str(last_params["from"]).replace("Z", "+00:00"))
    range_end = datetime.fromisoformat(str(last_params["to"]).replace("Z", "+00:00"))

    try:
        for wba_id, lane in pending.items():
            response = requests.get(
                f"{_get_api_base_url()}/api/v1/activity/timeline",
                params={
                    "wba_ids": wba_id,
                    "limit": last_params.get("limit", DEFAULT_LIMIT),
                    "from": last_params["from"],
                    "to": last_params["to"],
                    "cursor": lane["next_cursor"],
                },
                timeout=runtime_settings.get_int("HTTP_REQUEST_TIMEOUT"),
            )
            response.raise_for_status()
            data = response.json()
            if data.get("lanes"):
                new_lane = data["lanes"][0]
                lane_state[wba_id]["events"] = lane_state[wba_id].get("events", []) + new_lane.get("events", [])
                lane_state[wba_id]["next_cursor"] = new_lane.get("next_cursor")
    except requests.RequestException as exc:
        logger.warning(f"[Timeline] load-more API failed: {exc}")
        alert = create_alert(
            [
                html.I(className="fas fa-exclamation-circle me-2"),
                "Could not load more events. Check the server and try again.",
            ],
            color="danger",
        )
        return no_update, no_update, lane_state, [alert]

    lanes_html = _build_swimlane(lane_state, range_start=range_start, range_end=range_end)
    load_more_style = {"display": "block"} if _has_more_pages(lane_state) else {"display": "none"}
    return lanes_html, load_more_style, lane_state, []
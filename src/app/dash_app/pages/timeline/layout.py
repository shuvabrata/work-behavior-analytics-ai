"""Layout for the Activity Timeline page.

UI-0 shipped a reachable, empty page; UI-1 adds the entity selector bar and the
lane-header row. Events are not fetched yet — lanes render as empty columns
until UI-2 wires the timeline fetch.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

import dash_bootstrap_components as dbc
from dash import dcc, html

from app.common.timezone import to_app_timezone
from app.dash_app.components.common import (
    create_empty_state,
    create_loading_overlay_container,
    create_page_header,
)
from app.dash_app.pages.timeline.helpers import (
    card_summary,
    entity_type_color,
    entity_type_icon,
    entity_type_label,
    find_idle_runs,
    humanize_relationship,
    idle_run_key,
    idle_run_label,
    idle_run_period_labels,
    popup_fields,
)
from app.runtime_settings import runtime_settings
from app.dash_app.styles import (
    COLOR_BACKGROUND_WHITE,
    COLOR_BORDER,
    COLOR_CHARCOAL_MEDIUM,
    COLOR_GRAY_MEDIUM,
    COLOR_NAVY,
    FONT_SANS,
    FONT_SIZE_MEDIUM,
    FONT_SIZE_SMALL,
    FONT_SIZE_XTINY,
    FONT_WEIGHT_MEDIUM,
    SPACING_SMALL,
    SPACING_XSMALL,
)

# Width reserved for the time-axis label column so lane headers line up with the
# grid that UI-2 renders.
TIME_AXIS_WIDTH = "90px"

_SELECTOR_BAR_STYLE: dict[str, Any] = {
    "display": "flex",
    "alignItems": "center",
    "gap": SPACING_XSMALL,
    "marginBottom": SPACING_SMALL,
    "flexWrap": "wrap",
}

_TOOLBAR_STYLE: dict[str, Any] = {
    "display": "flex",
    "alignItems": "flex-end",
    "gap": SPACING_SMALL,
    "marginBottom": SPACING_SMALL,
    "flexWrap": "wrap",
}

_TOOLBAR_LABEL_STYLE: dict[str, Any] = {
    "fontFamily": FONT_SANS,
    "fontSize": FONT_SIZE_XTINY,
    "color": COLOR_GRAY_MEDIUM,
    "textTransform": "uppercase",
    "letterSpacing": "0.5px",
}

_RANGE_OPTIONS: list[dict[str, str]] = [
    {"label": "Last 7 days", "value": "7d"},
    {"label": "Last 30 days", "value": "30d"},
    {"label": "Last 90 days", "value": "90d"},
    {"label": "Custom…", "value": "custom"},
]

_SCOPE_OPTIONS: list[dict[str, str]] = [
    {"label": "Activity", "value": "activity"},
    {"label": "History", "value": "history"},
]

_SEARCH_WRAPPER_STYLE: dict[str, Any] = {
    "position": "relative",
    "flex": "0 0 auto",
}

_EMPTY_STATE_WRAPPER_STYLE: dict[str, Any] = {"marginTop": SPACING_SMALL}

_HINT_STYLE: dict[str, Any] = {
    "fontFamily": FONT_SANS,
    "fontSize": FONT_SIZE_SMALL,
    "color": COLOR_GRAY_MEDIUM,
}

CLEAR_ALL_STYLE: dict[str, Any] = {
    "fontFamily": FONT_SANS,
    "fontSize": FONT_SIZE_SMALL,
    "color": COLOR_NAVY,
    "background": "none",
    "border": "none",
    "padding": "0",
    "cursor": "pointer",
    "textDecoration": "underline",
}

CLEAR_ALL_HIDDEN_STYLE: dict[str, Any] = {**CLEAR_ALL_STYLE, "display": "none"}

_LANE_HEADER_BASE_STYLE: dict[str, Any] = {
    "display": "flex",
    "alignItems": "center",
    "gap": "8px",
    "padding": "8px 10px",
    # Sticky-top so the header row stays pinned inside the grid scroller.
    "position": "sticky",
    "top": "0",
    "zIndex": 3,
    "backgroundColor": COLOR_BACKGROUND_WHITE,
    "border": f"1px solid {COLOR_BORDER}",
    "borderRadius": "2px",
    "boxSizing": "border-box",
}

_LANE_LABEL_STYLE: dict[str, Any] = {
    "fontFamily": FONT_SANS,
    "fontSize": FONT_SIZE_MEDIUM,
    "fontWeight": FONT_WEIGHT_MEDIUM,
    "color": COLOR_CHARCOAL_MEDIUM,
    "whiteSpace": "nowrap",
    "overflow": "hidden",
    "textOverflow": "ellipsis",
}

_TYPE_TAG_STYLE: dict[str, Any] = {
    "fontFamily": FONT_SANS,
    "fontSize": FONT_SIZE_XTINY,
    "color": COLOR_GRAY_MEDIUM,
    "textTransform": "uppercase",
    "letterSpacing": "0.5px",
}

_LANE_MEDIA_STYLE: dict[str, Any] = {
    "width": "24px",
    "height": "24px",
    "borderRadius": "50%",
    "objectFit": "cover",
    "flex": "0 0 auto",
}

_LANE_ICON_STYLE: dict[str, Any] = {
    "width": "24px",
    "textAlign": "center",
    "color": COLOR_GRAY_MEDIUM,
    "flex": "0 0 auto",
}

_REMOVE_BTN_STYLE: dict[str, Any] = {
    "background": "none",
    "border": "none",
    "padding": "0 2px",
    "color": COLOR_GRAY_MEDIUM,
    "cursor": "pointer",
    "flex": "0 0 auto",
    "fontSize": FONT_SIZE_SMALL,
}

# ---------------------------------------------------------------------------
# Grid (UI-2): shared-row swimlane table
# ---------------------------------------------------------------------------

_AXIS_CELL_WIDTH_PX = int(TIME_AXIS_WIDTH.rstrip("px"))

GRID_SCROLL_STYLE: dict[str, Any] = {
    "position": "relative",
    "overflow": "auto",
    # Fill the viewport below the topbar + header + selector bar; grow only as
    # far as the content needs (no premature scrollbar when the page has room).
    "maxHeight": "calc(100vh - 220px)",
    "border": f"1px solid {COLOR_BORDER}",
    "borderRadius": "2px",
    "backgroundColor": COLOR_BACKGROUND_WHITE,
}

GRID_SCROLL_HIDDEN_STYLE: dict[str, Any] = {
    **GRID_SCROLL_STYLE,
    "display": "none",
}

_AXIS_CELL_BASE_STYLE: dict[str, Any] = {
    "padding": "6px 8px",
    "fontFamily": FONT_SANS,
    "fontSize": FONT_SIZE_XTINY,
    "color": COLOR_GRAY_MEDIUM,
    "textAlign": "right",
    "whiteSpace": "nowrap",
    "borderRight": f"1px solid {COLOR_BORDER}",
    "borderBottom": f"1px solid {COLOR_BORDER}",
    "backgroundColor": COLOR_BACKGROUND_WHITE,
    "minHeight": "28px",
}

_HEADER_AXIS_STYLE: dict[str, Any] = {
    **_AXIS_CELL_BASE_STYLE,
    "position": "sticky",
    "top": "0",
    "left": "0",
    "zIndex": 4,
}

_ROW_AXIS_STYLE: dict[str, Any] = {
    **_AXIS_CELL_BASE_STYLE,
    "position": "sticky",
    "left": "0",
    "zIndex": 2,
}

_CELL_STYLE: dict[str, Any] = {
    "padding": "4px 6px",
    "borderBottom": f"1px solid {COLOR_BORDER}",
    "minHeight": "28px",
}

_EVENT_TIME_FORMAT = "%I:%M %p"

# The popup portal lives at the page root (outside the scrolling grid) so it is
# never clipped by the grid's overflow; the clientside listener fills it.
POPUP_PORTAL_ID = "timeline-popup-portal"


def grid_inner_style(lane_count: int) -> dict[str, Any]:
    """Return the CSS-grid template for the swimlane table.

    One fixed axis column plus ``minmax(220px, 1fr)`` per lane; ``minWidth``
    forces horizontal scrolling once the lanes exceed the viewport.
    """
    columns = max(lane_count, 1)
    return {
        "display": "grid",
        "gridTemplateColumns": (
            f"{TIME_AXIS_WIDTH} repeat({columns}, minmax(220px, 1fr))"
        ),
        "minWidth": f"{_AXIS_CELL_WIDTH_PX + columns * 220}px",
        "alignItems": "start",
    }


def get_layout() -> html.Div:
    """Return the Activity Timeline page scaffold with selector and lane row."""
    return html.Div(
        [
            create_page_header(
                [("Analytics", "/app/analytics"), ("Timeline", None)],
                "Compare the chronological activity of people and objects side by side.",
            ),
            _selector_bar(),
            _toolbar(),
            html.Div(id="timeline-alert-slot"),
            html.Div(
                id="timeline-empty-state",
                children=[
                    create_empty_state(
                        "Add people or objects to compare their activity."
                    )
                ],
                style=_EMPTY_STATE_WRAPPER_STYLE,
            ),
            create_loading_overlay_container(
                html.Div(
                    id="timeline-grid-scroll",
                    style=GRID_SCROLL_HIDDEN_STYLE,
                    children=[
                        html.Div(
                            id="timeline-grid-inner",
                            style=grid_inner_style(1),
                            children=[
                                html.Div(
                                    id="timeline-lane-headers",
                                    style={"display": "contents"},
                                ),
                                html.Div(
                                    id="timeline-grid-body",
                                    style={"display": "contents"},
                                ),
                            ],
                        )
                    ],
                ),
                overlay_id="timeline-grid-overlay",
            ),
            # Hover-popup portal — a direct child of the page root, outside the
            # scrolling grid, so it is never clipped. Filled imperatively by the
            # UI-4 clientside listener; contents are built with createElement /
            # textContent (never innerHTML) because they carry ingested data.
            html.Div(
                id=POPUP_PORTAL_ID,
                className="timeline-popup-portal",
                role="tooltip",
            ),
            html.Div(id="timeline-popup-dummy", style={"display": "none"}),
            # Dummy output target for the install-once keyboard-navigation
            # clientside callback (ArrowUp/Down/Enter over the suggestion list).
            html.Div(id="timeline-keyboard-dummy", style={"display": "none"}),
            dcc.Store(id="timeline-selected-store", storage_type="memory", data=[]),
            dcc.Store(
                id="timeline-search-debounced", storage_type="memory", data=None
            ),
            dcc.Store(
                id="timeline-suggestions-store", storage_type="memory", data=[]
            ),
            dcc.Store(id="timeline-data-store", storage_type="memory", data=None),
            dcc.Store(id="timeline-loading-store", storage_type="memory", data=False),
            dcc.Store(id="timeline-theme-store", storage_type="memory", data=None),
            dcc.Store(id="timeline-expanded-runs-store", storage_type="memory", data=[]),
            dcc.Store(
                id="timeline-cell-expansion-store", storage_type="memory", data=[]
            ),
            dcc.Store(id="timeline-deeplink-applied", storage_type="memory", data=False),
        ]
    )


def _selector_bar() -> html.Div:
    """Selector bar: search input, suggestion dropdown, hint, and clear link."""
    return html.Div(
        [
            html.Div(
                [
                    dbc.Input(
                        id="timeline-search-input",
                        type="text",
                        placeholder="Search people or objects…",
                        debounce=False,
                        autocomplete="off",
                        size="sm",
                        style={"width": "320px"},
                    ),
                    html.Div(id="timeline-suggestions"),
                ],
                style=_SEARCH_WRAPPER_STYLE,
            ),
            html.Div(id="timeline-lane-hint", style=_HINT_STYLE),
            html.Button(
                "Clear all",
                id="timeline-clear-all",
                n_clicks=0,
                style=CLEAR_ALL_STYLE,
            ),
        ],
        id="timeline-selector-bar",
        style=_SELECTOR_BAR_STYLE,
    )


def _toolbar() -> html.Div:
    """Toolbar: time range (presets + custom picker) and Activity/History scope."""
    return html.Div(
        [
            html.Div(
                [
                    html.Label("Range", style=_TOOLBAR_LABEL_STYLE),
                    dbc.Select(
                        id="timeline-range",
                        options=_RANGE_OPTIONS,
                        value="30d",
                        size="sm",
                        style={"minWidth": "150px"},
                    ),
                ],
                style={"display": "flex", "flexDirection": "column", "gap": "2px"},
            ),
            html.Div(
                dcc.DatePickerRange(
                    id="timeline-custom-range",
                    display_format="MMM D, YYYY",
                    style={"fontFamily": FONT_SANS},
                ),
                id="timeline-custom-range-wrapper",
                style={"display": "none"},
            ),
            html.Div(
                [
                    html.Label("Scope", style=_TOOLBAR_LABEL_STYLE),
                    dbc.RadioItems(
                        id="timeline-scope",
                        options=_SCOPE_OPTIONS,
                        value="activity",
                        inline=True,
                        style={"fontFamily": FONT_SANS, "fontSize": FONT_SIZE_SMALL},
                    ),
                ],
                style={"display": "flex", "flexDirection": "column", "gap": "2px"},
            ),
        ],
        id="timeline-toolbar",
        style=_TOOLBAR_STYLE,
    )


def build_header_axis_cell() -> html.Div:
    """Sticky top-left corner cell above the time-axis column."""
    return html.Div(id="timeline-axis-corner", style=_HEADER_AXIS_STYLE)


def build_row_axis_cell(label: str) -> html.Div:
    """Sticky-left axis cell showing a period label."""
    return html.Div(label, style=_ROW_AXIS_STYLE, title=label)


def _format_event_time(raw: Any) -> str:
    """Render an event timestamp as time-of-day in the app timezone."""
    if not isinstance(raw, str) or not raw:
        return ""
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return ""
    return to_app_timezone(parsed).strftime(_EVENT_TIME_FORMAT)


def _format_full_datetime(raw: Any) -> str:
    """Render an event timestamp as a full datetime in the app timezone."""
    if not isinstance(raw, str) or not raw:
        return ""
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return ""
    return to_app_timezone(parsed).strftime(runtime_settings.get("UI_DATETIME_FORMAT"))


def build_event_card(
    event: dict[str, Any], lane_color: str, type_color: str
) -> html.A:
    """Build the 2-line event card.

    Line 1: the summary (with fallback). Line 2: ``<Type(colored)> · <relationship>
    · <time>``. The lane accent is a left border; the type colour comes from the
    effective theme. The summary is also set as the card ``title`` (a touch
    fallback until the UI-4 hover popup exists).
    """
    summary = card_summary(event)
    relationship = humanize_relationship(str(event.get("relationship_type") or ""))
    type_label = entity_type_label(str(event.get("entity_type") or ""))
    time_text = _format_event_time(event.get("event_time"))

    meta: list[Any] = [
        html.Span(
            type_label, className="timeline-card-type", style={"color": type_color}
        )
    ]
    if relationship:
        meta.append(html.Span("·", className="timeline-card-sep"))
        meta.append(html.Span(relationship, className="timeline-card-rel"))
    if time_text:
        meta.append(html.Span("·", className="timeline-card-sep"))
        meta.append(html.Span(time_text, className="timeline-card-time"))

    card_style: dict[str, Any] = (
        {"borderLeft": f"3px solid {lane_color}"} if lane_color else {}
    )
    # The whole card links to the Graph page in a new tab; the hover popup detail
    # is carried as a JSON data attribute and rendered by the clientside listener.
    payload: Any = {
        "data-timeline-event": json.dumps(
            popup_fields(event, _format_full_datetime(event.get("event_time")))
        )
    }
    return html.A(
        [
            html.Div(summary, className="timeline-card-summary", title=summary),
            html.Div(meta, className="timeline-card-meta"),
        ],
        href="/app/graph",
        target="_blank",
        rel="noopener noreferrer",
        className="timeline-card",
        style=card_style,
        title=summary,
        **payload,
    )


def build_cell(
    events: list[dict[str, Any]],
    lane_color: str,
    effective_nodes: dict[str, Any] | None,
    base_tokens: dict[str, Any],
    *,
    show_empty_note: bool = False,
) -> html.Div:
    """One lane cell: the cards for a period, an empty-lane note, or a dashed
    vertical guide continuing the lane through the gap."""
    if not events:
        if show_empty_note:
            return html.Div(
                "No activity in this range", className="timeline-empty-note"
            )
        return html.Div(className="timeline-cell-guide")
    cards = [
        build_event_card(
            event,
            lane_color,
            entity_type_color(
                str(event.get("entity_type") or ""), effective_nodes, base_tokens
            ),
        )
        for event in events
    ]
    return html.Div(cards, style=_CELL_STYLE)


def build_idle_bar(run: dict[str, Any], *, expanded: bool = False) -> html.Button:
    """A slim full-width, clickable idle-gap separator.

    Rendered in both states so it stays the toggle target — expanding shows the
    hidden rows *below* the bar and flips the chevron; clicking again collapses.
    """
    return html.Button(
        [
            html.I(className="fas fa-chevron-down timeline-idle-chevron"),
            html.Span(idle_run_label(run)),
        ],
        id={"type": "timeline-idle-toggle", "index": idle_run_key(run)},
        n_clicks=0,
        className="timeline-idle-bar expanded" if expanded else "timeline-idle-bar",
    )


def build_grid_body(
    rows: list[dict[str, Any]],
    lanes: list[dict[str, Any]],
    lane_colors: dict[str, str],
    effective_nodes: dict[str, Any] | None,
    base_tokens: dict[str, Any],
    *,
    expanded_runs: list[str] | None = None,
    granularity: str = "day",
) -> list[Any]:
    """Return the flat grid-item list for the body.

    One axis cell plus one cell per lane per period row, with collapsed idle-run
    separators inserted between rows (expanded runs render as empty period rows).
    A lane with no events at all shows a "No activity in this range" note in its
    top cell; every other empty cell gets a dashed guide.
    """
    expanded = set(expanded_runs or [])
    lane_ids = [str(lane.get("wba_id") or "") for lane in lanes]
    children: list[Any] = []

    lane_empty = {
        wba_id: not any((row.get("cells") or {}).get(wba_id) for row in rows)
        for wba_id in lane_ids
    }

    if not rows:
        # No period rows at all — still show the per-lane empty note.
        children.append(build_row_axis_cell(""))
        for wba_id in lane_ids:
            children.append(
                build_cell(
                    [],
                    lane_colors.get(wba_id, ""),
                    effective_nodes,
                    base_tokens,
                    show_empty_note=True,
                )
            )
        return children

    runs_by_newer = {
        int(run["end_ordinal"]) + 1: run for run in find_idle_runs(rows, granularity)
    }

    first_row = True
    for row in rows:
        children.append(build_row_axis_cell(str(row.get("label") or "")))
        cells = row.get("cells") or {}
        for wba_id in lane_ids:
            children.append(
                build_cell(
                    list(cells.get(wba_id) or []),
                    lane_colors.get(wba_id, ""),
                    effective_nodes,
                    base_tokens,
                    show_empty_note=first_row and lane_empty.get(wba_id, False),
                )
            )
        first_row = False

        run = runs_by_newer.get(int(row["ordinal"]))
        if run is None:
            continue
        is_expanded = idle_run_key(run) in expanded
        children.append(build_idle_bar(run, expanded=is_expanded))
        if is_expanded:
            for label in idle_run_period_labels(run):
                children.append(build_row_axis_cell(label))
                for wba_id in lane_ids:
                    children.append(
                        build_cell(
                            [],
                            lane_colors.get(wba_id, ""),
                            effective_nodes,
                            base_tokens,
                        )
                    )
    return children


def build_lane_header(item: dict[str, Any], lane_color: str) -> html.Div:
    """Build one lane header (avatar/icon + label + type tag + remove ✕)."""
    entity_type = item.get("entity_type") or ""
    label = item.get("label") or item.get("wba_id") or ""
    avatar_url = item.get("avatar_url")

    if avatar_url:
        media: Any = html.Img(src=avatar_url, style=_LANE_MEDIA_STYLE)
    else:
        media = html.I(className=entity_type_icon(entity_type), style=_LANE_ICON_STYLE)

    remove_attrs: Any = {"aria-label": f"Remove {label}"}

    return html.Div(
        [
            media,
            html.Div(
                [
                    html.Div(label, style=_LANE_LABEL_STYLE, title=label),
                    html.Span(entity_type_label(entity_type), style=_TYPE_TAG_STYLE),
                ],
                style={
                    "display": "flex",
                    "flexDirection": "column",
                    "minWidth": 0,
                    "flex": "1 1 auto",
                },
            ),
            html.Button(
                "✕",
                id={"type": "timeline-lane-remove", "index": item.get("wba_id")},
                n_clicks=0,
                title="Remove lane",
                style=_REMOVE_BTN_STYLE,
                **remove_attrs,
            ),
        ],
        style={**_LANE_HEADER_BASE_STYLE, "borderLeft": f"3px solid {lane_color}"},
    )

"""Layout for the Activity Timeline page.

UI-0 shipped a reachable, empty page; UI-1 adds the entity selector bar and the
lane-header row. Events are not fetched yet — lanes render as empty columns
until UI-2 wires the timeline fetch.
"""

from __future__ import annotations

from typing import Any

import dash_bootstrap_components as dbc
from dash import dcc, html

from app.dash_app.components.common import create_empty_state, create_page_header
from app.dash_app.pages.timeline.helpers import entity_type_icon, entity_type_label
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

_LANE_HEADERS_ROW_STYLE: dict[str, Any] = {
    "display": "flex",
    "alignItems": "stretch",
    "gap": "8px",
    "marginBottom": SPACING_SMALL,
}

_LANE_HEADER_BASE_STYLE: dict[str, Any] = {
    "display": "flex",
    "alignItems": "center",
    "gap": "8px",
    "padding": "8px 10px",
    "minWidth": "220px",
    "flex": "1 1 0",
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


def get_layout() -> html.Div:
    """Return the Activity Timeline page scaffold with selector and lane row."""
    return html.Div(
        [
            create_page_header(
                [("Analytics", "/app/analytics"), ("Timeline", None)],
                "Compare the chronological activity of people and objects side by side.",
            ),
            _selector_bar(),
            html.Div(id="timeline-lane-headers", style=_LANE_HEADERS_ROW_STYLE),
            html.Div(
                id="timeline-empty-state",
                children=[
                    create_empty_state(
                        "Add people or objects to compare their activity."
                    )
                ],
                style=_EMPTY_STATE_WRAPPER_STYLE,
            ),
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


def build_axis_spacer() -> html.Div:
    """Fixed-width spacer aligning lane headers with the time-axis column."""
    return html.Div(
        style={"flex": f"0 0 {TIME_AXIS_WIDTH}", "minWidth": TIME_AXIS_WIDTH}
    )


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

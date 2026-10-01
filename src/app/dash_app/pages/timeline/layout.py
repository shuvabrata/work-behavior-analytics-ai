"""Activity Timeline page layout.

Builds the swimlane timeline container: an entity selector bar (typeahead +
chips + Person-only toggle), time range controls, and the swimlane grid with a
daily time axis on the left and one horizontal lane per entity.

The layout is static — all dynamic content (lanes, cards, cursors) is rendered
by callbacks in :mod:`app.dash_app.pages.timeline.callbacks` into the
``timeline-lanes-container`` div.
"""

from __future__ import annotations

import dash_bootstrap_components as dbc
from dash import dcc, html

from app.dash_app.components.common import (
    create_empty_state,
    create_page_header,
)
from app.dash_app.styles import (
    COLOR_BACKGROUND_WHITE,
    COLOR_BORDER,
    COLOR_GRAY_DARK,
    COLOR_GRAY_MEDIUM,
    FONT_SANS,
    FONT_SIZE_SMALL,
    FONT_SIZE_XSMALL,
    FONT_WEIGHT_SEMIBOLD,
    SPACING_SMALL,
    SPACING_XSMALL,
    SPACING_XXSMALL,
)

#: Default time range presets (days).
TIME_RANGE_PRESETS: dict[str, int] = {
    "7d": 7,
    "30d": 30,
    "90d": 90,
}

#: Default selected preset.
DEFAULT_TIME_RANGE = "30d"

#: Default Person-only toggle state.
DEFAULT_PERSON_ONLY = True

#: Default events per lane per page.
DEFAULT_LIMIT = 20

#: Max events per lane per page (API cap).
MAX_LIMIT = 100


def _selector_bar() -> html.Div:
    """Entity selector bar: typeahead input, Person-only toggle, chips, Clear All."""
    return html.Div(
        [
            html.Div(
                [
                    html.Label(
                        "Add entities",
                        style={
                            "fontFamily": FONT_SANS,
                            "fontSize": FONT_SIZE_XSMALL,
                            "fontWeight": FONT_WEIGHT_SEMIBOLD,
                            "color": COLOR_GRAY_DARK,
                            "marginBottom": SPACING_XXSMALL,
                        },
                    ),
                    dbc.Input(
                        id="timeline-entity-search",
                        type="text",
                        placeholder="Search people or objects…",
                        debounce=False,
                        n_submit=0,
                        style={
                            "fontFamily": FONT_SANS,
                            "fontSize": FONT_SIZE_SMALL,
                            "border": f"1px solid {COLOR_BORDER}",
                            "borderRadius": "2px",
                        },
                    ),
                    html.Div(
                        id="timeline-suggestions",
                        style={"display": "none"},
                    ),
                ],
                style={"flex": "1", "minWidth": "240px"},
            ),
            html.Div(
                [
                    dbc.Checklist(
                        id="timeline-person-only",
                        options=[
                            {
                                "label": "People only",
                                "value": "person_only",
                            }
                        ],
                        value=["person_only"] if DEFAULT_PERSON_ONLY else [],
                        inline=True,
                        switch=True,
                        style={"fontSize": FONT_SIZE_XSMALL},
                    ),
                ],
                style={"marginLeft": SPACING_XSMALL},
            ),
            html.Div(
                [
                    html.Span(
                        "Selected:",
                        style={
                            "fontFamily": FONT_SANS,
                            "fontSize": FONT_SIZE_XSMALL,
                            "color": COLOR_GRAY_MEDIUM,
                        },
                    ),
                    html.Div(
                        id="timeline-selected-chips",
                        children=create_empty_state(
                            "No entities selected — search above to add lanes.",
                            icon="🏊",
                        ),
                    ),
                    dbc.Button(
                        "Clear All",
                        id="timeline-clear-btn",
                        color="link",
                        size="sm",
                        className="ms-auto",
                        style={
                            "fontSize": FONT_SIZE_XSMALL,
                            "padding": "0",
                            "textDecoration": "none",
                        },
                    ),
                ],
                style={"marginTop": SPACING_XSMALL},
            ),
        ],
        id="timeline-selector-bar",
        style={
            "display": "flex",
            "flexWrap": "wrap",
            "gap": SPACING_XSMALL,
            "alignItems": "flex-start",
            "marginBottom": SPACING_SMALL,
        },
    )


def _time_range_controls() -> html.Div:
    """Time range controls: preset dropdown + custom date range picker."""
    return html.Div(
        [
            html.Label(
                "Time Range",
                style={
                    "fontFamily": FONT_SANS,
                    "fontSize": FONT_SIZE_XSMALL,
                    "fontWeight": FONT_WEIGHT_SEMIBOLD,
                    "color": COLOR_GRAY_DARK,
                    "marginBottom": SPACING_XXSMALL,
                },
            ),
            dcc.Dropdown(
                id="timeline-time-range",
                options=[
                    {"label": "Last 7 days", "value": "7d"},
                    {"label": "Last 30 days", "value": "30d"},
                    {"label": "Last 90 days", "value": "90d"},
                    {"label": "Custom…", "value": "custom"},
                ],
                value=DEFAULT_TIME_RANGE,
                clearable=False,
                style={"fontSize": FONT_SIZE_XSMALL},
            ),
            dcc.DatePickerRange(
                id="timeline-custom-range",
                display_format="MMM D, YYYY",
                start_date_placeholder_text="Start date",
                end_date_placeholder_text="End date",
                style={"display": "none"},
            ),
        ],
        id="timeline-time-range-controls",
        style={
            "display": "flex",
            "flexDirection": "column",
            "gap": SPACING_XXSMALL,
            "marginBottom": SPACING_SMALL,
        },
    )


def _swimlane_container() -> html.Div:
    """Swimlane grid container: time axis + lanes, rendered by callbacks."""
    return html.Div(
        [
            html.Div(
                id="timeline-lanes-container",
                children=create_empty_state(
                    "Add entities to get started.",
                    icon="🏊",
                ),
            ),
            html.Div(
                id="timeline-load-more-row",
                style={"display": "none"},
                children=[
                    dbc.Button(
                        "Load More",
                        id="timeline-load-more-btn",
                        color="primary",
                        outline=True,
                        size="sm",
                        className="mx-auto d-block",
                    ),
                ],
            ),
        ],
        id="timeline-swimlane-container",
        style={
            "backgroundColor": COLOR_BACKGROUND_WHITE,
            "border": f"1px solid {COLOR_BORDER}",
            "borderRadius": "2px",
            "padding": SPACING_SMALL,
            "overflowX": "auto",
        },
    )


def get_layout() -> html.Div:
    """Return the activity timeline page layout."""
    return html.Div(
        [
            create_page_header(
                [("Analytics", "/app/analytics"), ("Activity Timeline", None)],
                "Compare chronological activity of persons and objects side-by-side.",
            ),
            # Hidden state stores
            dcc.Store(id="timeline-selected-entities", storage_type="session", data=[]),
            dcc.Store(id="timeline-lane-state", storage_type="session", data={}),
            dcc.Store(id="timeline-loading", storage_type="memory", data=False),
            dcc.Store(id="timeline-last-params", storage_type="session", data={}),
            dcc.Store(id="timeline-suggestions-store", storage_type="memory", data=[]),

            # Feedback region for alerts
            html.Div(id="timeline-alert-region", children=[]),

            _selector_bar(),
            _time_range_controls(),
            _swimlane_container(),
        ],
        id="timeline-page",
        style={"padding": "0 8px"},
    )
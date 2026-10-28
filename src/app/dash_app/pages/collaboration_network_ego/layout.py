"""Per-person (ego) Collaboration Network page layout and pure helpers.

Layout builders and stateless filtering helpers are kept here so they can be
imported by both the package __init__ and the callbacks sub-package without
creating circular imports. Deliberately a small duplicate of the org collab
page's equivalents — this is the repo's existing pattern (``_split_elements``
is already duplicated in ``pages/graph/callbacks/filtering.py``).
"""

from typing import Any

import dash_bootstrap_components as dbc
import dash_cytoscape as cyto
from dash import dcc, html

from app.analytics.collaboration.config import CollaborationNetworkConfig
from app.analytics.collaboration.ego import COLLABORATOR_CAP_OPTIONS
from domain.person_network_url import DEFAULT_MAX_COLLABORATORS
from app.dash_app.components.common import (
    create_alert,
    create_controls_bar,
    create_loading_overlay_container,
    create_page_header,
)
from app.dash_app.components.person_picker import build_person_picker
from app.dash_app.graph_styles import CYTOSCAPE_STYLESHEET
from app.dash_app.styles import (
    COLOR_GRAY_DARK,
    COLOR_GRAY_LIGHTER,
    FONT_SIZE_SMALL,
    FONT_SIZE_XSMALL,
    FONT_WEIGHT_SEMIBOLD,
)


_EGO_LAYOUT = {"name": "preset", "fit": False, "animate": False, "padding": 30}
"""Preset layout with fit:False.

fit:False is intentional: on first render the browser may not have finished laying
out the container, so letting Cytoscape auto-fit produces an invalid zoom.
The clientside render callback calls cy.resize() + cy.fit() explicitly once the
DOM is stable.
"""

_CANVAS_HEIGHT = "calc(100vh - 148px)"
"""Canvas height, sized to the chrome the page actually renders above it.
"""

_LABEL_STYLE = {
    "fontSize": "11px",
    "fontWeight": FONT_WEIGHT_SEMIBOLD,
    "color": COLOR_GRAY_DARK,
    "marginBottom": "8px",
    "display": "block",
}

_CAP_OPTIONS = [
    {"label": f"Top {cap}", "value": cap} for cap in COLLABORATOR_CAP_OPTIONS
]

_EMPTY_STATE_STYLE = {
    "position": "absolute",
    "inset": 0,
    # Below the loading overlay's z-index 5, above the canvas.
    "zIndex": 1,
    "display": "flex",
    "alignItems": "center",
    "justifyContent": "center",
    "padding": "16px",
    "textAlign": "center",
    "color": "var(--color-text-secondary)",
    "fontSize": FONT_SIZE_SMALL,
    # Purely informational: never intercept a click meant for the graph.
    "pointerEvents": "none",
}
"""Pre-input prompt, centered over the plot area.

Absolutely positioned so the prompt occupies the canvas rather than stacking
below it. In flow it added ~178px under a canvas already sized to
``calc(100vh - 145px)``, which pushed a scrollbar onto a page that should not
scroll — and left the text below the fold, where no user would see it.

The callback assigns this whole dict to the element's ``style``, flipping
``display`` between ``flex`` and ``none``, so the positioning must live here
rather than in ``get_layout``: a style set only at layout time would be
replaced wholesale on the callback's first fire.
"""


# ---------------------------------------------------------------------------
# Layout helpers
# ---------------------------------------------------------------------------

def _create_right_panel_tab_bar() -> html.Div:
    """Return the sticky tab bar for the ego right panel (Filters only)."""
    return html.Div(
        id="ego-right-panel-tab-bar",
        className="graph-right-panel-tab-bar",
        children=[
            html.Button(
                [
                    html.I(className="fas fa-sliders fa-fw"),
                    html.Span("Filters", className="graph-right-panel-tab-label"),
                ],
                id="ego-right-tab-filters-btn",
                title="Filters",
                className="graph-right-panel-tab-icon",
                n_clicks=0,
            ),
        ],
    )


def _create_right_panel_tabs() -> html.Div:
    """Return the single accordion collapse panel for the Filters tab."""
    return html.Div([
        dbc.Collapse(
            id="ego-right-tab-filters-collapse",
            is_open=False,
            children=[
                dbc.Card([
                    dbc.CardBody([
                        # Summary row + Clear All
                        html.Div([
                            html.Div([
                                html.Small("Refining loaded star", className="graph-filter-mode-label d-block"),
                                html.Small(
                                    id="ego-filter-results-summary",
                                    children="Pick a person to load their network.",
                                    className="graph-filter-summary d-block",
                                ),
                            ]),
                            dbc.Button(
                                "Clear All",
                                id="ego-clear-filters-btn",
                                color="link",
                                size="sm",
                                className="ms-auto",
                                style={"fontSize": "11px", "padding": "0", "textDecoration": "none"},
                            ),
                        ], className="d-flex justify-content-between align-items-start mb-3"),

                        # Active filter chips
                        html.Div(
                            id="ego-filter-active-chips",
                            className="graph-filter-chip-list mb-3",
                            children=[html.Span("No active filters", className="graph-filter-empty-state")],
                        ),

                        # Weight threshold (normalized_weight is already 0-100)
                        html.Div([
                            html.Label("Weight Threshold:", style=_LABEL_STYLE),
                            dcc.Slider(
                                id="ego-weight-threshold-slider",
                                min=0,
                                max=100,
                                step=1,
                                value=0,
                                marks={0: "0", 25: "25", 50: "50", 75: "75", 100: "100"},
                                tooltip={"placement": "bottom", "always_visible": False},
                            ),
                            html.Small(
                                id="ego-weight-threshold-label",
                                children="Show collaborators with weight ≥ 0",
                                className="d-block mt-1",
                                style={"fontSize": "10px", "color": "var(--color-text-secondary)"},
                            ),
                        ], className="mb-3"),

                        # Top-N collaborator cap
                        html.Div([
                            html.Label("Collaborator Cap:", style=_LABEL_STYLE),
                            dbc.RadioItems(
                                id="ego-top-n-cap",
                                options=_CAP_OPTIONS,
                                value=DEFAULT_MAX_COLLABORATORS,
                                inline=False,
                                className="graph-filter-radio",
                                style={"fontSize": "12px"},
                            ),
                        ]),
                    ], className="graph-filter-card-body", style={"padding": "0 0 24px 0"}),
                ], className="graph-filter-card", style={"border": "none", "backgroundColor": "transparent"}),
            ],
        ),
    ])


def get_layout() -> html.Div:
    """Return the per-person collaboration network page layout."""
    return html.Div(
        [
            create_page_header(
                [("Analytics", "/app/analytics"), ("Per-Person Collaboration Network", None)],
                "See who one person works with, and how closely.",
                trailing=build_person_picker(
                    "ego_focus",
                    "Person",
                    required=True,
                    show_label=False,
                    container_class="ego-header-picker",
                ),
            ),

            # Stores
            dcc.Store(id="ego-elements-store", data=[]),
            dcc.Store(id="ego-fullwidth-state", data=False),
            # Unlike the org page's True: this page fetches only once a person is
            # picked, so the callback in callbacks/filter.py raises this store.
            dcc.Store(id="ego-loading-state", data=False),
            # Debounced spotlight query, written by the shared spotlight
            # clientcallback (see app.dash_app.components.spotlight).
            dcc.Store(id="ego-spotlight-debounced-store", data=""),

            # Live stats banner
            html.Div(id="ego-banner", children=[], style={"display": "none", "flex": "1"}),

            # Main 2-column row: canvas (left) + filter + properties (right)
            dbc.Row([
                dbc.Col([
                    create_controls_bar("ego", layout_enabled=False),
                    # The canvas and the pre-input prompt share one positioned
                    # ancestor so the prompt can be centered over the plot area.
                    # The wrapper is deliberately local to this page: the
                    # overlay helper in components/common.py is shared by the
                    # graph and org pages, and neither wants this child.
                    html.Div(
                        style={"position": "relative"},
                        children=[
                            create_loading_overlay_container(
                                cyto.Cytoscape(
                                    id="ego-cytoscape",
                                    elements=[],
                                    layout=_EGO_LAYOUT,
                                    style={
                                        "width": "100%",
                                        "height": _CANVAS_HEIGHT,
                                        "border": f"1px solid {COLOR_GRAY_LIGHTER}",
                                        "borderRadius": "2px",
                                    },
                                    stylesheet=CYTOSCAPE_STYLESHEET,
                                    userZoomingEnabled=True,
                                    userPanningEnabled=True,
                                    wheelSensitivity=0.3,
                                    minZoom=0.05,
                                    maxZoom=3,
                                ),
                                overlay_id="ego-loading-overlay",
                            ),
                            html.Div(
                                id="ego-empty-state",
                                children="Pick a person in the header to see their collaboration network.",
                                style=_EMPTY_STATE_STYLE,
                            ),
                        ],
                    ),
                ], id="ego-viz-col", width=8, style={"paddingRight": "16px"}),

                dbc.Col([
                    html.Div(
                        style={"overflowY": "auto", "maxHeight": "calc(75vh + 40px)", "position": "relative"},
                        children=[
                            _create_right_panel_tab_bar(),
                            _create_right_panel_tabs(),
                            html.Div(
                                id="ego-details-panel",
                                children=html.P(
                                    "Select a node or edge to see its properties.",
                                    className="text-muted text-center",
                                    style={"fontSize": FONT_SIZE_XSMALL, "padding": "16px 0"},
                                ),
                            ),
                        ],
                    ),
                ], id="ego-details-col", width=4, style={"borderLeft": f"1px solid {COLOR_GRAY_LIGHTER}", "paddingLeft": "16px"}),
            ], className="g-0"),

            # Hidden Output target for the clientside render callback.
            html.Div(id="ego-render-trigger", style={"display": "none"}),
        ],
        id="ego-page",
        style={"padding": "0 8px"},
    )


# ---------------------------------------------------------------------------
# Pure helper functions (stateless — no Dash callbacks)
# ---------------------------------------------------------------------------

def _error_banner(message: str) -> dbc.Alert:
    return create_alert(message, color="danger", class_name="mb-0")


def _data_unavailable_banner(
    focus_id: str, config: CollaborationNetworkConfig | None
) -> dbc.Alert:
    """Warn that the person has no collaborators in the active window.

    A distinct colour from ``_error_banner`` because nothing has failed: the
    query ran cleanly and the answer is simply empty. ``warning`` is the
    app's semantic colour for a recoverable state, and the message names the
    two levers the user actually has — window length and enabled layers.

    Args:
        focus_id: The focus Person's ``wba_id``, named so the user can confirm
            which person the empty result belongs to (the chip shows the
            display name, which may differ).
        config: The active config, read for its ``lookback_days``. ``None``
            when the URL's settings failed to parse, in which case the window
            is unknown and is omitted rather than guessed.
    """
    window = (
        f" in the last {config.lookback_days} days"
        if config is not None
        else ""
    )
    return create_alert(
        f"No collaborators found for {focus_id}{window}. "
        "Try widening the lookback window or enabling more collaboration layers.",
        color="warning",
        class_name="mb-0",
    )


def _split_elements(elements: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Split a Cytoscape element list into (nodes, edges)."""
    nodes = [
        e for e in elements
        if isinstance(e, dict) and e.get("data", {}).get("source") is None and e.get("data", {}).get("id")
    ]
    edges = [
        e for e in elements
        if isinstance(e, dict) and e.get("data", {}).get("source")
    ]
    return nodes, edges


def _compute_ego_filtered(
    elements: list[dict[str, Any]],
    weight_threshold: float | int,
    top_n_cap: int | None,
) -> list[dict[str, Any]]:
    """Apply the weight threshold and top-N cap to ego elements.

    Filters are applied here, in Python, over the already-loaded store — the
    point of normalizing before the cap is that dragging the slider must never
    hit Neo4j, and surviving edges must never be re-normalized.

    ``normalized_weight`` in the store is already final (0-100), so it is used
    directly as the threshold scale. The focus node is always retained even when
    every edge is filtered away.
    """
    if not elements:
        return []

    nodes, edges = _split_elements(elements)
    focus_nodes = [n for n in nodes if n.get("data", {}).get("role") == "focus"]

    threshold = float(weight_threshold or 0)
    candidate_edges = [
        e for e in edges
        if float(e["data"].get("normalized_weight", 0)) >= threshold
    ]

    if top_n_cap is not None and top_n_cap > 0:
        candidate_edges = sorted(
            candidate_edges,
            key=lambda e: float(e["data"].get("weight", 0)),
            reverse=True,
        )[:top_n_cap]

    visible_ids: set[str] = set()
    for node in focus_nodes:
        visible_ids.add(node["data"]["id"])
    for edge in candidate_edges:
        visible_ids.add(edge["data"]["source"])
        visible_ids.add(edge["data"]["target"])

    return [n for n in nodes if n["data"]["id"] in visible_ids] + candidate_edges

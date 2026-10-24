"""Analytics gallery page for pre-built graph visualizations."""

from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

from dash import ALL, Input, Output, State, callback, clientside_callback, ctx, html
import dash_bootstrap_components as dbc

from app.analytics.collaboration.config import (
    CollaborationNetworkConfig,
    DEFAULT_EXCLUDE_BOTS,
    DEFAULT_ENSURE_MIN_CONNECTION,
    DEFAULT_COMMUNITY_GAP_X,
    DEFAULT_COMMUNITY_GAP_Y,
    DEFAULT_LAYER_WEIGHTS,
    DEFAULT_LOOKBACK_DAYS,
    DEFAULT_MIN_PAIR_SCORE,
    DEFAULT_TOP_N_EDGES_PER_NODE,
    LAYER_LABELS,
    LAYER_ORDER,
)
from app.analytics.collaboration.ego import (
    COLLABORATOR_CAP_OPTIONS,
    DEFAULT_MAX_COLLABORATORS,
)
from app.analytics.registry import GRAPH_ANALYTICS
from app.dash_app.components.common import create_page_header
from app.dash_app.styles import (
    CARD_CONTAINER_STYLE,
    COLOR_BACKGROUND_LIGHT,
    COLOR_BACKGROUND_WHITE,
    COLOR_BORDER,
    COLOR_CHARCOAL_MEDIUM,
    COLOR_GRAY_DARK,
    COLOR_GRAY_MEDIUM,
    FONT_SANS,
    FONT_SIZE_LARGE,
    FONT_SIZE_MEDIUM,
    FONT_SIZE_SMALL,
    FONT_SIZE_XTINY,
    FONT_WEIGHT_MEDIUM,
    FONT_WEIGHT_SEMIBOLD,
    SPACING_MEDIUM,
    SPACING_SMALL,
    SPACING_XSMALL,
    SPACING_XXSMALL,
)


@dataclass(frozen=True)
class _CardControlsSpec:
    """Which controls an Analytics card renders, and where its button launches.

    Both collaboration cards are emitted by the same builder, parameterised by
    ``prefix``, so the layer table (which iterates ``LAYER_ORDER``) can never
    drift between them: a layer added to ``config.py`` appears on both cards.
    """

    prefix: str
    launch_path: str
    has_community_dynamics: bool = False
    has_top_n_edges: bool = False
    has_ensure_min_connection: bool = False
    has_collaborator_cap: bool = False


COLLABORATION_CARD_SPEC = _CardControlsSpec(
    prefix="collab",
    launch_path="/app/collaboration",
    has_community_dynamics=True,
    has_top_n_edges=True,
    has_ensure_min_connection=True,
)

PER_PERSON_CARD_SPEC = _CardControlsSpec(
    prefix="ego",
    launch_path="/app/collaboration/person",
    has_collaborator_cap=True,
)

# Cards rendered with the shared layer/weight builder, keyed by registry key.
_CARD_SPECS_BY_KEY: dict[str, _CardControlsSpec] = {
    "collaboration_network": COLLABORATION_CARD_SPEC,
    "per_person_collaboration_network": PER_PERSON_CARD_SPEC,
}

_CARD_SPECS: tuple[_CardControlsSpec, ...] = (COLLABORATION_CARD_SPEC, PER_PERSON_CARD_SPEC)


def get_layout() -> html.Div:
    """Return the analytics gallery page."""
    return html.Div(
        [
            create_page_header(
                [("Analytics", None)],
                "Launch pre-built graph visualizations for common leadership and delivery questions.",
            ),
            html.Div(
                [
                    dbc.Row(
                        [
                            dbc.Col(_create_analytic_card(analytic), md=6, className="mb-3")
                            for analytic in GRAPH_ANALYTICS
                        ],
                        className="g-3",
                    ),
                ],
                style=CARD_CONTAINER_STYLE,
            ),
        ],
    )


def _create_analytic_card(analytic: Any) -> dbc.Card:
    card_spec = _CARD_SPECS_BY_KEY.get(analytic.key)
    if card_spec is not None:
        footer = _create_card_controls(card_spec)
    else:
        footer = dbc.Button("Open Visualization", href=analytic.href, color="primary", size="sm")

    return dbc.Card(
        dbc.CardBody(
            [
                html.Div(
                    [
                        html.I(className=analytic.icon, style={"fontSize": "20px", "color": COLOR_CHARCOAL_MEDIUM}),
                        html.Span(
                            analytic.title,
                            style={
                                "fontFamily": FONT_SANS,
                                "fontSize": FONT_SIZE_LARGE,
                                "fontWeight": FONT_WEIGHT_MEDIUM,
                                "color": COLOR_GRAY_DARK,
                                "marginLeft": SPACING_XSMALL,
                            },
                        ),
                    ],
                    style={"display": "flex", "alignItems": "center", "marginBottom": SPACING_SMALL},
                ),
                html.Div(
                    analytic.description,
                    style={
                        "fontFamily": FONT_SANS,
                        "fontSize": FONT_SIZE_MEDIUM,
                        "color": COLOR_GRAY_MEDIUM,
                        "lineHeight": "1.6",
                        "marginBottom": SPACING_MEDIUM,
                    },
                ),
                footer,
            ]
        ),
        style={
            "backgroundColor": COLOR_BACKGROUND_WHITE,
            "border": f"1px solid {COLOR_BORDER}",
            "borderRadius": "2px",
            "padding": SPACING_SMALL,
            "minHeight": "220px",
            "boxShadow": "none",
        },
    )


_LAYER_GRID_TEMPLATE = "70px 1fr 110px"


def _field_label(text: str) -> html.Div:
    """Small uppercase column label matching Graph Styling."""
    return html.Div(
        text,
        style={
            "fontFamily": FONT_SANS,
            "fontSize": FONT_SIZE_XTINY,
            "fontWeight": FONT_WEIGHT_MEDIUM,
            "color": COLOR_GRAY_MEDIUM,
            "textTransform": "uppercase",
            "letterSpacing": "0.5px",
        },
    )


def _layer_header_row() -> html.Div:
    """Column header row for the layer table."""
    return html.Div(
        [
            _field_label("Enable"),
            _field_label("Layer"),
            _field_label("Weight"),
        ],
        style={
            "display": "grid",
            "gridTemplateColumns": _LAYER_GRID_TEMPLATE,
            "gap": SPACING_XSMALL,
            "alignItems": "center",
            "padding": f"{SPACING_XXSMALL} 0",
            "borderBottom": f"1px solid {COLOR_BORDER}",
        },
    )


def _layer_row(layer: str, prefix: str) -> html.Div:
    """Single row in the layer table with Switch, Label, and Weight input.

    ``prefix`` namespaces the ids per card (``collab`` / ``ego``). The layer
    enable and weight components use pattern-matching ids so the href callbacks
    can consume every layer with the ``ALL`` wildcard — adding a layer to
    ``LAYER_ORDER`` therefore needs no callback edit.
    """
    return html.Div(
        [
            dbc.Switch(
                id={"type": f"{prefix}-layer-enable", "layer": layer},
                value=True,
                className="m-0",
            ),
            html.Div(
                LAYER_LABELS[layer],
                style={
                    "fontFamily": FONT_SANS,
                    "fontSize": FONT_SIZE_SMALL,
                    "fontWeight": FONT_WEIGHT_MEDIUM,
                    "color": COLOR_CHARCOAL_MEDIUM,
                },
            ),
            dbc.Input(
                id={"type": f"{prefix}-weight", "layer": layer},
                type="number",
                min=0,
                step=0.1,
                value=DEFAULT_LAYER_WEIGHTS[layer],
                size="sm",
                style={
                    "fontFamily": FONT_SANS,
                    "fontSize": FONT_SIZE_SMALL,
                    "padding": SPACING_XXSMALL,
                    "border": f"1px solid {COLOR_BORDER}",
                    "width": "100%",
                },
            ),
        ],
        id={"type": f"{prefix}-layer-row", "layer": layer},
        style={
            "display": "grid",
            "gridTemplateColumns": _LAYER_GRID_TEMPLATE,
            "gap": SPACING_XSMALL,
            "alignItems": "center",
            "padding": f"{SPACING_XXSMALL} 0",
            "borderBottom": f"1px solid {COLOR_BORDER}",
        },
    )


def _table_title_bar() -> html.Div:
    """Title bar for the layer configuration table."""
    return html.Div(
        "Layers & Weights",
        style={
            "fontFamily": FONT_SANS,
            "fontSize": FONT_SIZE_SMALL,
            "fontWeight": FONT_WEIGHT_SEMIBOLD,
            "color": COLOR_CHARCOAL_MEDIUM,
            "textTransform": "uppercase",
            "letterSpacing": "0.5px",
            "marginBottom": SPACING_XSMALL,
        },
    )


def _section_header(title: str) -> html.Div:
    """Section header for grouped settings."""
    return html.Div(
        title,
        style={
            "fontFamily": FONT_SANS,
            "fontSize": FONT_SIZE_XTINY,
            "fontWeight": FONT_WEIGHT_SEMIBOLD,
            "color": COLOR_GRAY_MEDIUM,
            "textTransform": "uppercase",
            "letterSpacing": "0.5px",
            "marginBottom": SPACING_XSMALL,
            "marginTop": SPACING_MEDIUM,
        },
    )


def _create_card_controls(spec: _CardControlsSpec) -> html.Div:
    """Build an Analytics card's launch button plus its expandable controls.

    One builder serves every card in ``_CARD_SPECS``. ``spec.prefix`` namespaces
    the component ids (Dash ids are global, so two cards cannot share them) and
    ``spec`` decides which optional sections appear — the per-person view has no
    communities, so Community Gap and the org-only topology controls would be
    inert there and are omitted rather than duplicated.

    The layer table iterates ``LAYER_ORDER`` on every card, so a layer added to
    ``app/analytics/collaboration/config.py`` shows up on both automatically.
    """
    prefix = spec.prefix

    collapse_children: list[Any] = [
        html.Div(
            "Configure collaboration layers and weights in the table below, then "
            "adjust network layout and filtering parameters as needed.",
            style={
                "fontFamily": FONT_SANS,
                "fontSize": FONT_SIZE_SMALL,
                "color": COLOR_GRAY_MEDIUM,
                "marginBottom": SPACING_SMALL,
                "marginTop": SPACING_SMALL,
            },
        ),
        # Layer configuration table
        html.Div(
            [
                _table_title_bar(),
                _layer_header_row(),
                *[_layer_row(layer, prefix) for layer in LAYER_ORDER],
            ],
            style={
                "padding": SPACING_SMALL,
                "backgroundColor": COLOR_BACKGROUND_LIGHT,
                "border": f"1px solid {COLOR_BORDER}",
                "borderRadius": "2px",
                "marginBottom": SPACING_SMALL,
            },
        ),
    ]

    if spec.has_community_dynamics:
        collapse_children.extend([
            _section_header("Network Dynamics"),
            dbc.Row(
                [
                    dbc.Col(
                        [
                            html.Label("Community Gap X", style={"fontSize": FONT_SIZE_SMALL, "fontFamily": FONT_SANS}),
                            dbc.Input(
                                id=f"{prefix}-community-gap-x",
                                type="number",
                                min=200,
                                max=10000,
                                step=10,
                                value=DEFAULT_COMMUNITY_GAP_X,
                                size="sm",
                            ),
                        ],
                        md=6,
                    ),
                    dbc.Col(
                        [
                            html.Label("Community Gap Y", style={"fontSize": FONT_SIZE_SMALL, "fontFamily": FONT_SANS}),
                            dbc.Input(
                                id=f"{prefix}-community-gap-y",
                                type="number",
                                min=200,
                                max=10000,
                                step=10,
                                value=DEFAULT_COMMUNITY_GAP_Y,
                                size="sm",
                            ),
                        ],
                        md=6,
                    ),
                ],
                className="g-2 mb-1",
            ),
            html.Div(
                "Tip: For dense networks, start with X=1400-2400 and Y=1000-1800. Higher values increase spacing between communities.",
                style={
                    "fontFamily": FONT_SANS,
                    "fontSize": "11px",
                    "color": COLOR_GRAY_MEDIUM,
                    "marginBottom": SPACING_SMALL,
                },
            ),
        ])

    # Filtering & Topology section
    topology_col_width = 4 if spec.has_top_n_edges else 6
    topology_cols = [
        dbc.Col(
            [
                html.Label("Lookback Days", style={"fontSize": FONT_SIZE_SMALL, "fontFamily": FONT_SANS}),
                dbc.Input(id=f"{prefix}-lookback-days", type="number", min=1, max=365, step=1, value=DEFAULT_LOOKBACK_DAYS, size="sm"),
            ],
            md=topology_col_width,
        ),
        dbc.Col(
            [
                html.Label("Min Pair Score", style={"fontSize": FONT_SIZE_SMALL, "fontFamily": FONT_SANS}),
                dbc.Input(id=f"{prefix}-min-pair-score", type="number", min=0, step=0.1, value=DEFAULT_MIN_PAIR_SCORE, size="sm"),
            ],
            md=topology_col_width,
        ),
    ]
    if spec.has_top_n_edges:
        topology_cols.append(
            dbc.Col(
                [
                    html.Label("Top-N Edges / Node", style={"fontSize": FONT_SIZE_SMALL, "fontFamily": FONT_SANS}),
                    dbc.Input(id=f"{prefix}-top-n-edges", type="number", min=0, max=200, step=1, value=DEFAULT_TOP_N_EDGES_PER_NODE, size="sm"),
                ],
                md=topology_col_width,
            )
        )
    collapse_children.extend([
        _section_header("Filtering & Topology"),
        dbc.Row(topology_cols, className="g-2 mb-2"),
    ])

    switch_cols = [
        dbc.Col(
            dbc.Switch(
                id=f"{prefix}-exclude-bots",
                label="Exclude bots",
                value=DEFAULT_EXCLUDE_BOTS,
            ),
            md=6,
        ),
    ]
    if spec.has_ensure_min_connection:
        switch_cols.append(
            dbc.Col(
                dbc.Switch(
                    id=f"{prefix}-ensure-min-connection",
                    label="Ensure min connection",
                    value=DEFAULT_ENSURE_MIN_CONNECTION,
                ),
                md=6,
            )
        )
    collapse_children.append(dbc.Row(switch_cols, className="g-2 mb-3"))

    if spec.has_collaborator_cap:
        collapse_children.append(
            dbc.Row(
                [
                    dbc.Col(
                        [
                            html.Label("Collaborator Cap", style={"fontSize": FONT_SIZE_SMALL, "fontFamily": FONT_SANS}),
                            dbc.Select(
                                id=f"{prefix}-collaborator-cap",
                                options=[
                                    {"label": f"Top {cap}", "value": cap}
                                    for cap in COLLABORATOR_CAP_OPTIONS
                                ],
                                value=DEFAULT_MAX_COLLABORATORS,
                                size="sm",
                            ),
                        ],
                        md=6,
                    ),
                ],
                className="g-2 mb-3",
            )
        )

    collapse_children.append(
        dbc.Button(
            "Open Visualization",
            id=f"{prefix}-open-btn-bottom",
            href=spec.launch_path,
            color="primary",
            size="sm",
            className="w-100 mb-2",
        )
    )

    return html.Div(
        [
            dbc.Row(
                [
                    dbc.Col(
                        dbc.Button(
                            "Open Visualization",
                            id=f"{prefix}-open-btn",
                            href=spec.launch_path,
                            color="primary",
                            size="sm",
                        ),
                        width="auto",
                    ),
                    dbc.Col(
                        dbc.Button(
                            "Show Options",
                            id=f"{prefix}-controls-toggle-btn",
                            color="secondary",
                            outline=True,
                            size="sm",
                        ),
                        width="auto",
                    ),
                ],
                className="g-2 align-items-center",
            ),
            dbc.Collapse(collapse_children, id=f"{prefix}-controls-collapse", is_open=False),
            html.Div(
                id=f"{prefix}-url-preview",
                style={
                    "fontSize": "11px",
                    "color": COLOR_GRAY_MEDIUM,
                    "marginTop": SPACING_XSMALL,
                    "wordBreak": "break-all",
                    "display": "none",
                },
            ),
        ]
    )


# ---------------------------------------------------------------------------
# Callbacks
# ---------------------------------------------------------------------------

# Disable Weight input when the corresponding layer switch is off
# Disable a layer's Weight input while its enable switch is off. Emitted per
# card so each card's table behaves independently.
for _card_spec in _CARD_SPECS:
    for _layer in LAYER_ORDER:
        clientside_callback(
            """
            function(enabled) {
                return !enabled;
            }
            """,
            Output({"type": f"{_card_spec.prefix}-weight", "layer": _layer}, "disabled"),
            Input({"type": f"{_card_spec.prefix}-layer-enable", "layer": _layer}, "value"),
        )


def _config_from_layer_inputs(
    layer_enables: list[Any],
    layer_weights: list[Any],
    *,
    lookback_days: Any,
    min_pair_score: Any,
    exclude_bots: Any,
    top_n_edges_per_node: Any = None,
    community_gap_x: Any = None,
    community_gap_y: Any = None,
    ensure_min_connection: Any = None,
) -> CollaborationNetworkConfig:
    """Build a validated config from one card's control values.

    The wildcard (``ALL``) layer inputs arrive in layout order, which is the
    order :func:`_layer_row` emits them in — ``LAYER_ORDER``. Zipping the two is
    what keeps a card's rows and its URL params aligned without any per-layer
    code, so a layer added to ``LAYER_ORDER`` flows through untouched.
    """
    query_values: dict[str, Any] = {
        "layers": [
            layer for layer, enabled in zip(LAYER_ORDER, layer_enables) if enabled
        ],
        "lookback_days": lookback_days,
        "min_pair_score": min_pair_score,
        "exclude_bots": exclude_bots,
        **{f"w_{layer}": weight for layer, weight in zip(LAYER_ORDER, layer_weights)},
    }
    # Only forward the org-only settings the card actually renders; leaving them
    # out lets CollaborationNetworkConfig apply its own defaults.
    if top_n_edges_per_node is not None:
        query_values["top_n_edges_per_node"] = top_n_edges_per_node
    if community_gap_x is not None:
        query_values["community_gap_x"] = community_gap_x
    if community_gap_y is not None:
        query_values["community_gap_y"] = community_gap_y
    if ensure_min_connection is not None:
        query_values["ensure_min_connection"] = ensure_min_connection

    try:
        return CollaborationNetworkConfig.from_query_values(query_values)
    except Exception:
        return CollaborationNetworkConfig()


def _href_triple(
    config: CollaborationNetworkConfig,
    launch_path: str,
    extra_params: dict[str, Any] | None = None,
) -> tuple[str, str, str]:
    """Return (top href, bottom href, preview text) for a card's launch button."""
    params: dict[str, Any] = {
        "layers": ",".join(config.enabled_layers),
        "lookback_days": config.lookback_days,
        "min_pair_score": config.min_pair_score,
        "exclude_bots": str(config.exclude_bots).lower(),
        **{f"w_{layer}": config.weights[layer] for layer in LAYER_ORDER},
    }
    if extra_params:
        params.update(extra_params)
    href = f"{launch_path}?{urlencode(params)}"
    return href, href, f"URL: {href}"


@callback(
    [
        Output(f"{COLLABORATION_CARD_SPEC.prefix}-open-btn", "href"),
        Output(f"{COLLABORATION_CARD_SPEC.prefix}-open-btn-bottom", "href"),
        Output(f"{COLLABORATION_CARD_SPEC.prefix}-url-preview", "children"),
    ],
    [
        Input({"type": f"{COLLABORATION_CARD_SPEC.prefix}-layer-enable", "layer": ALL}, "value"),
        Input(f"{COLLABORATION_CARD_SPEC.prefix}-lookback-days", "value"),
        Input(f"{COLLABORATION_CARD_SPEC.prefix}-min-pair-score", "value"),
        Input(f"{COLLABORATION_CARD_SPEC.prefix}-top-n-edges", "value"),
        Input(f"{COLLABORATION_CARD_SPEC.prefix}-community-gap-x", "value"),
        Input(f"{COLLABORATION_CARD_SPEC.prefix}-community-gap-y", "value"),
        Input(f"{COLLABORATION_CARD_SPEC.prefix}-exclude-bots", "value"),
        Input(f"{COLLABORATION_CARD_SPEC.prefix}-ensure-min-connection", "value"),
        Input({"type": f"{COLLABORATION_CARD_SPEC.prefix}-weight", "layer": ALL}, "value"),
    ],
)
def build_collaboration_href(  # pylint: disable=too-many-arguments
    layer_enables: list[Any],
    lookback_days: Any,
    min_pair_score: Any,
    top_n_edges_per_node: Any,
    community_gap_x: Any,
    community_gap_y: Any,
    exclude_bots: Any,
    ensure_min_connection: Any,
    layer_weights: list[Any],
) -> tuple[str, str, str]:
    """Build the Collaboration Network card's launch URLs from its controls."""
    config = _config_from_layer_inputs(
        layer_enables,
        layer_weights,
        lookback_days=lookback_days,
        min_pair_score=min_pair_score,
        exclude_bots=exclude_bots,
        top_n_edges_per_node=top_n_edges_per_node,
        community_gap_x=community_gap_x,
        community_gap_y=community_gap_y,
        ensure_min_connection=ensure_min_connection,
    )
    return _href_triple(
        config,
        COLLABORATION_CARD_SPEC.launch_path,
        extra_params={
            "top_n_edges_per_node": config.top_n_edges_per_node,
            "community_gap_x": config.community_gap_x,
            "community_gap_y": config.community_gap_y,
            "ensure_min_connection": str(config.ensure_min_connection).lower(),
        },
    )


@callback(
    [
        Output(f"{PER_PERSON_CARD_SPEC.prefix}-open-btn", "href"),
        Output(f"{PER_PERSON_CARD_SPEC.prefix}-open-btn-bottom", "href"),
        Output(f"{PER_PERSON_CARD_SPEC.prefix}-url-preview", "children"),
    ],
    [
        Input({"type": f"{PER_PERSON_CARD_SPEC.prefix}-layer-enable", "layer": ALL}, "value"),
        Input(f"{PER_PERSON_CARD_SPEC.prefix}-lookback-days", "value"),
        Input(f"{PER_PERSON_CARD_SPEC.prefix}-min-pair-score", "value"),
        Input(f"{PER_PERSON_CARD_SPEC.prefix}-exclude-bots", "value"),
        Input(f"{PER_PERSON_CARD_SPEC.prefix}-collaborator-cap", "value"),
        Input({"type": f"{PER_PERSON_CARD_SPEC.prefix}-weight", "layer": ALL}, "value"),
    ],
)
def build_per_person_href(
    layer_enables: list[Any],
    lookback_days: Any,
    min_pair_score: Any,
    exclude_bots: Any,
    max_collaborators: Any,
    layer_weights: list[Any],
) -> tuple[str, str, str]:
    """Build the Per-Person card's launch URLs from its controls.

    Only the settings the per-person view consumes are forwarded: it has no
    communities and no org topology pruning, so those controls are absent here
    by construction rather than silently inert.
    """
    config = _config_from_layer_inputs(
        layer_enables,
        layer_weights,
        lookback_days=lookback_days,
        min_pair_score=min_pair_score,
        exclude_bots=exclude_bots,
    )
    return _href_triple(
        config,
        PER_PERSON_CARD_SPEC.launch_path,
        extra_params={"max_collaborators": max_collaborators},
    )


def _toggle_controls_state(is_open: bool) -> tuple[bool, str, dict[str, str]]:
    """Return (is_open, button label, url-preview style) for a controls toggle."""
    next_state = not is_open
    label = "Hide Options" if next_state else "Show Options"
    preview_style = {
        "fontSize": "11px",
        "color": COLOR_GRAY_MEDIUM,
        "marginTop": SPACING_XSMALL,
        "wordBreak": "break-all",
        "display": "block" if next_state else "none",
    }
    return next_state, label, preview_style


def _register_controls_toggle(spec: _CardControlsSpec) -> None:
    """Register the Show/Hide Options toggle for one card's controls panel."""
    prefix = spec.prefix

    @callback(
        [
            Output(f"{prefix}-controls-collapse", "is_open"),
            Output(f"{prefix}-controls-toggle-btn", "children"),
            Output(f"{prefix}-url-preview", "style"),
        ],
        Input(f"{prefix}-controls-toggle-btn", "n_clicks"),
        State(f"{prefix}-controls-collapse", "is_open"),
        prevent_initial_call=True,
    )
    def toggle_controls(_n_clicks: int | None, is_open: bool) -> tuple[bool, str, dict[str, str]]:
        return _toggle_controls_state(is_open)


for _card_spec in _CARD_SPECS:
    _register_controls_toggle(_card_spec)

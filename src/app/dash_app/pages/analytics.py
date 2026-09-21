"""Analytics gallery page for pre-built graph visualizations."""

from typing import Any
from urllib.parse import urlencode

from dash import Input, Output, State, callback, clientside_callback, html
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
    is_collaboration = analytic.key == "collaboration_network"

    footer = (
        _create_collaboration_controls()
        if is_collaboration
        else dbc.Button("Open Visualization", href=analytic.href, color="primary", size="sm")
    )

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


def _layer_row(layer: str) -> html.Div:
    """Single row in the layer table with Switch, Label, and Weight input."""
    return html.Div(
        [
            dbc.Switch(
                id=f"collab-layer-enable-{layer}",
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
                id=f"collab-weight-{layer}",
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
                    "borderRadius": "2px",
                    "width": "100%",
                },
            ),
        ],
        id=f"collab-layer-row-{layer}",
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


def _create_collaboration_controls() -> html.Div:
    return html.Div(
        [
            dbc.Row(
                [
                    dbc.Col(
                        dbc.Button(
                            "Open Visualization",
                            id="collab-open-btn",
                            href="/app/collaboration",
                            color="primary",
                            size="sm",
                        ),
                        width="auto",
                    ),
                    dbc.Col(
                        dbc.Button(
                            "Show Options",
                            id="collab-controls-toggle-btn",
                            color="secondary",
                            outline=True,
                            size="sm",
                        ),
                        width="auto",
                    ),
                ],
                className="g-2 align-items-center",
            ),
            dbc.Collapse(
                [
                    html.Div(
                        "Configure collaboration layers and weights in the table below, then adjust network layout and filtering parameters as needed.",
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
                            *[_layer_row(layer) for layer in LAYER_ORDER],
                        ],
                        style={
                            "padding": SPACING_SMALL,
                            "backgroundColor": COLOR_BACKGROUND_LIGHT,
                            "border": f"1px solid {COLOR_BORDER}",
                            "borderRadius": "2px",
                            "marginBottom": SPACING_SMALL,
                        },
                    ),
                    # Network Dynamics section
                    _section_header("Network Dynamics"),
                    dbc.Row(
                        [
                            dbc.Col(
                                [
                                    html.Label("Community Gap X", style={"fontSize": FONT_SIZE_SMALL, "fontFamily": FONT_SANS}),
                                    dbc.Input(
                                        id="collab-community-gap-x",
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
                                        id="collab-community-gap-y",
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
                    # Filtering & Topology section
                    _section_header("Filtering & Topology"),
                    dbc.Row(
                        [
                            dbc.Col(
                                [
                                    html.Label("Lookback Days", style={"fontSize": FONT_SIZE_SMALL, "fontFamily": FONT_SANS}),
                                    dbc.Input(id="collab-lookback-days", type="number", min=1, max=365, step=1, value=DEFAULT_LOOKBACK_DAYS, size="sm"),
                                ],
                                md=4,
                            ),
                            dbc.Col(
                                [
                                    html.Label("Min Pair Score", style={"fontSize": FONT_SIZE_SMALL, "fontFamily": FONT_SANS}),
                                    dbc.Input(id="collab-min-pair-score", type="number", min=0, step=0.1, value=DEFAULT_MIN_PAIR_SCORE, size="sm"),
                                ],
                                md=4,
                            ),
                            dbc.Col(
                                [
                                    html.Label("Top-N Edges / Node", style={"fontSize": FONT_SIZE_SMALL, "fontFamily": FONT_SANS}),
                                    dbc.Input(id="collab-top-n-edges", type="number", min=0, max=200, step=1, value=DEFAULT_TOP_N_EDGES_PER_NODE, size="sm"),
                                ],
                                md=4,
                            ),
                        ],
                        className="g-2 mb-2",
                    ),
                    dbc.Row(
                        [
                            dbc.Col(
                                dbc.Switch(
                                    id="collab-exclude-bots",
                                    label="Exclude bots",
                                    value=DEFAULT_EXCLUDE_BOTS,
                                ),
                                md=6,
                            ),
                            dbc.Col(
                                dbc.Switch(
                                    id="collab-ensure-min-connection",
                                    label="Ensure min connection",
                                    value=DEFAULT_ENSURE_MIN_CONNECTION,
                                ),
                                md=6,
                            ),
                        ],
                        className="g-2 mb-3",
                    ),
                    # Secondary action button at bottom
                    dbc.Button(
                        "Open Visualization",
                        id="collab-open-btn-bottom",
                        href="/app/collaboration",
                        color="primary",
                        size="sm",
                        className="w-100 mb-2",
                    ),
                ],
                id="collab-controls-collapse",
                is_open=False,
            ),
            html.Div(
                id="collab-url-preview",
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
for _layer in LAYER_ORDER:
    clientside_callback(
        """
        function(enabled) {
            return !enabled;
        }
        """,
        Output(f"collab-weight-{_layer}", "disabled"),
        Input(f"collab-layer-enable-{_layer}", "value"),
    )


@callback(
    [
        Output("collab-open-btn", "href"),
        Output("collab-open-btn-bottom", "href"),
        Output("collab-url-preview", "children"),
    ],
    [
        *[Input(f"collab-layer-enable-{layer}", "value") for layer in LAYER_ORDER],
        Input("collab-lookback-days", "value"),
        Input("collab-min-pair-score", "value"),
        Input("collab-top-n-edges", "value"),
        Input("collab-community-gap-x", "value"),
        Input("collab-community-gap-y", "value"),
        Input("collab-exclude-bots", "value"),
        Input("collab-ensure-min-connection", "value"),
        *[Input(f"collab-weight-{layer}", "value") for layer in LAYER_ORDER],
    ],
)
def build_collaboration_href(  # pylint: disable=too-many-arguments
    layer_enable_reporter_assignee: Any,
    layer_enable_pr_reviews: Any,
    layer_enable_shared_file_commits: Any,
    layer_enable_sprint_coworkers: Any,
    layer_enable_explicit_review_requests: Any,
    layer_enable_epic_overlap: Any,
    layer_enable_confluence_co_authorship: Any,
    layer_enable_confluence_comment_engagement: Any,
    layer_enable_confluence_co_commenters: Any,
    layer_enable_confluence_mentions: Any,
    layer_enable_github_pr_comment_engagement: Any,
    layer_enable_github_pr_co_commenters: Any,
    layer_enable_github_issue_comment_engagement: Any,
    layer_enable_github_issue_co_commenters: Any,
    layer_enable_jira_issue_comment_engagement: Any,
    layer_enable_jira_issue_co_commenters: Any,
    layer_enable_jira_epic_initiative_comment_engagement: Any,
    layer_enable_jira_epic_initiative_co_commenters: Any,
    lookback_days: Any,
    min_pair_score: Any,
    top_n_edges_per_node: Any,
    community_gap_x: Any,
    community_gap_y: Any,
    exclude_bots: Any,
    ensure_min_connection: Any,
    w_reporter_assignee: Any,
    w_pr_reviews: Any,
    w_shared_file_commits: Any,
    w_sprint_coworkers: Any,
    w_explicit_review_requests: Any,
    w_epic_overlap: Any,
    w_confluence_co_authorship: Any,
    w_confluence_comment_engagement: Any,
    w_confluence_co_commenters: Any,
    w_confluence_mentions: Any,
    w_github_pr_comment_engagement: Any,
    w_github_pr_co_commenters: Any,
    w_github_issue_comment_engagement: Any,
    w_github_issue_co_commenters: Any,
    w_jira_issue_comment_engagement: Any,
    w_jira_issue_co_commenters: Any,
    w_jira_epic_initiative_comment_engagement: Any,
    w_jira_epic_initiative_co_commenters: Any,
) -> Any:
    """Build a graph-mode URL that carries collaboration query overrides."""
    layer_enables = [
        layer_enable_reporter_assignee,
        layer_enable_pr_reviews,
        layer_enable_shared_file_commits,
        layer_enable_sprint_coworkers,
        layer_enable_explicit_review_requests,
        layer_enable_epic_overlap,
        layer_enable_confluence_co_authorship,
        layer_enable_confluence_comment_engagement,
        layer_enable_confluence_co_commenters,
        layer_enable_confluence_mentions,
        layer_enable_github_pr_comment_engagement,
        layer_enable_github_pr_co_commenters,
        layer_enable_github_issue_comment_engagement,
        layer_enable_github_issue_co_commenters,
        layer_enable_jira_issue_comment_engagement,
        layer_enable_jira_issue_co_commenters,
        layer_enable_jira_epic_initiative_comment_engagement,
        layer_enable_jira_epic_initiative_co_commenters,
    ]
    weight_values = [
        w_reporter_assignee,
        w_pr_reviews,
        w_shared_file_commits,
        w_sprint_coworkers,
        w_explicit_review_requests,
        w_epic_overlap,
        w_confluence_co_authorship,
        w_confluence_comment_engagement,
        w_confluence_co_commenters,
        w_confluence_mentions,
        w_github_pr_comment_engagement,
        w_github_pr_co_commenters,
        w_github_issue_comment_engagement,
        w_github_issue_co_commenters,
        w_jira_issue_comment_engagement,
        w_jira_issue_co_commenters,
        w_jira_epic_initiative_comment_engagement,
        w_jira_epic_initiative_co_commenters,
    ]
    enabled_layers = [
        layer for layer, enabled in zip(LAYER_ORDER, layer_enables) if enabled
    ]
    query_values = {
        "layers": enabled_layers,
        "lookback_days": lookback_days,
        "min_pair_score": min_pair_score,
        "top_n_edges_per_node": top_n_edges_per_node,
        "community_gap_x": community_gap_x,
        "community_gap_y": community_gap_y,
        "exclude_bots": exclude_bots,
        "ensure_min_connection": ensure_min_connection,
        **{f"w_{layer}": weight for layer, weight in zip(LAYER_ORDER, weight_values)},
    }

    try:
        config = CollaborationNetworkConfig.from_query_values(query_values)
    except Exception:
        config = CollaborationNetworkConfig()

    params = {
        "layers": ",".join(config.enabled_layers),
        "lookback_days": config.lookback_days,
        "min_pair_score": config.min_pair_score,
        "top_n_edges_per_node": config.top_n_edges_per_node,
        "community_gap_x": config.community_gap_x,
        "community_gap_y": config.community_gap_y,
        "exclude_bots": str(config.exclude_bots).lower(),
        "ensure_min_connection": str(config.ensure_min_connection).lower(),
        **{f"w_{layer}": config.weights[layer] for layer in LAYER_ORDER},
    }

    href = f"/app/collaboration?{urlencode(params)}"
    return href, href, f"URL: {href}"


@callback(
    [
        Output("collab-controls-collapse", "is_open"),
        Output("collab-controls-toggle-btn", "children"),
        Output("collab-url-preview", "style"),
    ],
    Input("collab-controls-toggle-btn", "n_clicks"),
    State("collab-controls-collapse", "is_open"),
    prevent_initial_call=True,
)
def toggle_collaboration_controls(_n_clicks: int | None, is_open: bool) -> tuple[bool, str, dict[str, str]]:
    """Toggle collaboration controls visibility in the analytics card."""
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

"""Dash layout for the Library query editor page."""

from typing import Any

from dash import dcc, html
import dash_bootstrap_components as dbc

from app.dash_app.components.common import create_page_header
from app.dash_app.styles import (
    CARD_CONTAINER_STYLE,
    COLOR_BACKGROUND_WHITE,
    COLOR_BORDER,
    COLOR_GRAY_DARK,
    FEATURE_CARD_STYLE,
    FEATURE_CARD_TITLE_STYLE,
    FONT_SANS,
    FONT_SIZE_SMALL,
    FONT_SIZE_XSMALL,
    FONT_WEIGHT_SEMIBOLD,
    SPACING_XSMALL,
    SPACING_SMALL,
)

FONT_MONO = "'SFMono-Regular', 'Consolas', 'Menlo', monospace"

# Parameter field keys (order matters for the form rows).
PARAM_FIELDS = [
    "name",
    "label",
    "type",
    "required",
    "placeholder",
    "description",
    "env_var",
]

PARAM_FIELD_LABELS = {
    "name": "Name",
    "label": "Label",
    "type": "Type",
    "required": "Required",
    "placeholder": "Placeholder",
    "description": "Description",
    "env_var": "Env var",
}

STATUS_OPTIONS = [
    {"label": "Active", "value": "active"},
    {"label": "Draft", "value": "draft"},
    {"label": "Deprecated", "value": "deprecated"},
]

VIEW_OPTIONS = [
    {"label": "Tabular", "value": "tabular"},
    {"label": "Graph", "value": "graph"},
]


def get_editor_layout() -> html.Div:
    """Return the shared query editor layout (edit and new routes)."""
    return html.Div(
        [
            dcc.Store(id="editor-store", storage_type="memory"),
            dcc.Store(id="editor-namespaces-store", storage_type="memory"),
            dcc.Store(id="editor-route", storage_type="memory"),
            dcc.Store(id="editor-param-count", storage_type="memory", data=0),
            dcc.Store(id="editor-save-as-open", storage_type="memory", data=False),
            dcc.ConfirmDialog(
                id="editor-reset-confirm",
                message="",
            ),
            html.Div(id="editor-feedback"),
            create_page_header(
                [("Library", "/app/library"), ("Query Editor", None)],
                "Create or edit a user-defined catalog query.",
            ),
            html.Div(
                [
                    _render_action_bar(),
                    _render_metadata_section(),
                    _render_queries_section(),
                    _render_save_as_modal(),
                    _render_test_results(),
                ],
                style={**CARD_CONTAINER_STYLE, "paddingTop": SPACING_XSMALL},
            ),
        ],
    )


def _render_metadata_section() -> html.Div:
    """Metadata section card (name, description, summary, owner, status, tags).

    Collapsible via the ``collapse-toggle-subtle`` header, open by default.
    """
    return html.Div(
        [
            html.Div(
                [
                    html.I(className="fas fa-chevron-down me-1", style={"fontSize": "11px"}),
                    "Metadata",
                ],
                id="editor-metadata-collapse-toggle",
                className="collapse-toggle-subtle",
                style={
                    "fontSize": "11px",
                    "fontWeight": FONT_WEIGHT_SEMIBOLD,
                    "color": COLOR_GRAY_DARK,
                    "marginBottom": SPACING_XSMALL,
                    "cursor": "pointer",
                    "userSelect": "none",
                },
            ),
            dbc.Collapse(
                id="editor-metadata-collapse",
                is_open=True,
                children=[
                    dbc.Row(
                        [
                            dbc.Col(
                                [
                                    dbc.Label("Name", html_for="editor-name"),
                                    dbc.Input(id="editor-name", type="text", placeholder="Query name"),
                                ],
                                md=6,
                            ),
                            dbc.Col(
                                [
                                    dbc.Label("Owner", html_for="editor-owner"),
                                    dbc.Input(id="editor-owner", type="text", placeholder="Owner"),
                                ],
                                md=3,
                            ),
                            dbc.Col(
                                [
                                    dbc.Label("Status", html_for="editor-status"),
                                    dcc.Dropdown(
                                        id="editor-status",
                                        options=STATUS_OPTIONS,
                                        clearable=True,
                                        placeholder="Status",
                                        searchable=False,
                                    ),
                                ],
                                md=3,
                            ),
                        ],
                        className="g-2",
                    ),
                    dbc.Row(
                        [
                            dbc.Col(
                                [
                                    dbc.Label("Summary", html_for="editor-summary"),
                                    dbc.Textarea(
                                        id="editor-summary",
                                        placeholder="Optional summary",
                                        rows=1,
                                    ),
                                ],
                                md=6,
                            ),
                            dbc.Col(
                                [
                                    dbc.Label("Tags (comma-separated)", html_for="editor-tags"),
                                    dbc.Input(
                                        id="editor-tags",
                                        type="text",
                                        placeholder="analytics, github, …",
                                    ),
                                ],
                                md=6,
                            ),
                        ],
                        className="g-2 mt-2",
                    ),
                    dbc.Row(
                        [
                            dbc.Col(
                                [
                                    dbc.Label("Description", html_for="editor-description"),
                                    dbc.Textarea(
                                        id="editor-description",
                                        placeholder="Short description",
                                        rows=4,
                                    ),
                                ],
                                md=12,
                            ),
                        ],
                        className="g-2 mt-2",
                    ),
                ],
            ),
        ],
        style=FEATURE_CARD_STYLE,
    )


def _render_queries_section() -> html.Div:
    """Queries section card: Cypher editors, Test buttons, parameters, default view.

    Collapsible via the ``collapse-toggle-subtle`` header, open by default.
    """
    return html.Div(
        [
            html.Div(
                [
                    html.I(className="fas fa-chevron-down me-1", style={"fontSize": "11px"}),
                    "Queries",
                ],
                id="editor-queries-collapse-toggle",
                className="collapse-toggle-subtle",
                style={
                    "fontSize": "11px",
                    "fontWeight": FONT_WEIGHT_SEMIBOLD,
                    "color": COLOR_GRAY_DARK,
                    "marginBottom": SPACING_XSMALL,
                    "cursor": "pointer",
                    "userSelect": "none",
                },
            ),
            dbc.Collapse(
                id="editor-queries-collapse",
                is_open=True,
                children=[
                    dbc.Row(
                        [
                            dbc.Col(
                                [
                                    dbc.Label("Tabular Query", html_for="editor-query-tabular"),
                                    dbc.Textarea(
                                        id="editor-query-tabular",
                                        placeholder="MATCH (n) RETURN n LIMIT 25",
                                        rows=8,
                                        style={"fontFamily": FONT_MONO, "fontSize": FONT_SIZE_XSMALL},
                                    ),
                                    dbc.Button(
                                        "Test Tabular",
                                        id="editor-test-tabular",
                                        color="secondary",
                                        outline=True,
                                        size="sm",
                                        className="mt-2",
                                    ),
                                ],
                                md=6,
                            ),
                            dbc.Col(
                                [
                                    dbc.Label("Graph Query", html_for="editor-query-graph"),
                                    dbc.Textarea(
                                        id="editor-query-graph",
                                        placeholder="MATCH (n)-[r]->(m) RETURN n, r, m LIMIT 25",
                                        rows=8,
                                        style={"fontFamily": FONT_MONO, "fontSize": FONT_SIZE_XSMALL},
                                    ),
                                    dbc.Button(
                                        "Test Graph",
                                        id="editor-test-graph",
                                        color="secondary",
                                        outline=True,
                                        size="sm",
                                        className="mt-2",
                                    ),
                                ],
                                md=6,
                            ),
                        ],
                        className="g-2",
                    ),
                    html.Hr(style={"marginTop": SPACING_SMALL}),
                    html.Div(
                        [
                            html.Div(
                                [
                                    dbc.Button(
                                        "Add Parameter",
                                        id="editor-param-add",
                                        color="primary",
                                        outline=True,
                                        size="sm",
                                    ),
                                ],
                                style={"marginBottom": SPACING_XSMALL},
                            ),
                            html.Div(id="editor-params-container"),
                        ],
                        style={"fontFamily": FONT_SANS, "fontSize": FONT_SIZE_SMALL},
                    ),
                    html.Div(
                        [
                            html.Div("Default View", style=FEATURE_CARD_TITLE_STYLE),
                            dcc.RadioItems(
                                id="editor-default-view",
                                options=VIEW_OPTIONS,
                                inline=True,
                            ),
                        ],
                        style={"fontFamily": FONT_SANS, "fontSize": FONT_SIZE_SMALL, "marginTop": SPACING_SMALL},
                    ),
                ],
            ),
        ],
        style=FEATURE_CARD_STYLE,
    )


def _render_action_bar() -> html.Div:
    """Sticky action bar: Save, Save As, Reset to Factory.

    Mirrors the Runtime Settings page's sticky top action bar so the primary
    actions stay visible while scrolling the form and are visually separated
    from the sections below.
    """
    return html.Div(
        [
            html.Div(
                [
                    dbc.Button("Save", id="editor-save", color="primary", size="sm", className="me-2"),
                    dbc.Button("Save As", id="editor-save-as", color="primary", outline=True, size="sm", className="me-2"),
                ],
                style={
                    "display": "flex",
                    "alignItems": "center",
                    "gap": SPACING_XSMALL,
                },
            ),
            html.Div(
                [
                    dbc.Button(
                        "Reset to Factory",
                        id="editor-reset",
                        color="outline-danger",
                        size="sm",
                    ),
                ],
                style={
                    "display": "flex",
                    "alignItems": "center",
                    "marginLeft": "auto",
                },
            ),
        ],
        style={
            "position": "sticky",
            "top": 0,
            "zIndex": 10,
            "backgroundColor": COLOR_BACKGROUND_WHITE,
            "padding": f"{SPACING_XSMALL} 0",
            "display": "flex",
            "alignItems": "center",
            "gap": SPACING_SMALL,
            "borderBottom": f"1px solid {COLOR_BORDER}",
            "marginBottom": SPACING_SMALL,
        },
    )


def _render_save_as_modal() -> dbc.Modal:
    """Save As modal with namespace dropdown and slug input."""
    return dbc.Modal(
        [
            dbc.ModalHeader(dbc.ModalTitle("Save As")),
            dbc.ModalBody(
                [
                    dbc.Label("Namespace", html_for="editor-save-as-namespace"),
                    dcc.Dropdown(
                        id="editor-save-as-namespace",
                        placeholder="Select namespace",
                    ),
                    dbc.Input(
                        id="editor-save-as-namespace-custom",
                        type="text",
                        placeholder="New namespace name…",
                        style={"display": "none", "marginTop": SPACING_XSMALL},
                    ),
                    dbc.Label("Slug", html_for="editor-save-as-slug", className="mt-2"),
                    dbc.Input(
                        id="editor-save-as-slug",
                        type="text",
                        placeholder="my_query_slug",
                    ),
                ]
            ),
            dbc.ModalFooter(
                [
                    dbc.Button("Cancel", id="editor-save-as-cancel", color="secondary", size="sm", className="me-2"),
                    dbc.Button("Save", id="editor-save-as-submit", color="primary", size="sm"),
                ]
            ),
        ],
        id="editor-save-as-modal",
        is_open=False,
    )


def _render_test_results() -> html.Div:
    """Inline pane for Test Tabular / Test Graph results."""
    return html.Div(
        [
            html.H6("Test Results", className="mt-3"),
            html.Div(id="editor-test-results"),
        ],
        style={"fontFamily": FONT_SANS, "fontSize": FONT_SIZE_SMALL},
    )


def render_parameter_row(index: int, parameter: dict[str, Any] | None = None) -> html.Div:
    """Render a single parameter editor row.

    Args:
        index: The parameter index (used for pattern-matching ids).
        parameter: Optional existing parameter values to prefill.
    """
    parameter = parameter or {}
    fields: list[Any] = []
    for field in PARAM_FIELDS:
        value = parameter.get(field)
        if field == "required":
            control: Any = dcc.Checklist(
                id={"type": "editor-param-field", "index": str(index), "field": field},
                options=[{"label": "", "value": "required"}],
                value=["required"] if value else [],
                inline=True,
            )
        else:
            control = dbc.Input(
                id={"type": "editor-param-field", "index": str(index), "field": field},
                type="text",
                value=str(value) if value is not None else "",
                placeholder=PARAM_FIELD_LABELS[field],
            )
        fields.append(
            dbc.Col(
                [
                    dbc.Label(PARAM_FIELD_LABELS[field], size="sm"),
                    control,
                ],
                md=2 if field == "required" else 3,
            )
        )

    return html.Div(
        [
            dbc.Row(
                fields,
                className="g-2",
            ),
            dbc.Button(
                "Remove",
                id={"type": "editor-param-remove", "index": str(index)},
                color="outline-danger",
                size="sm",
            ),
            html.Hr(style={"marginTop": SPACING_XSMALL}),
        ],
        id={"type": "editor-param-row", "index": str(index)},
    )
"""Dash layout for the Library (query catalog) listing page."""

from dash import dcc, html
import dash_bootstrap_components as dbc

from app.dash_app.components.common import create_page_header
from app.dash_app.styles import (
    CARD_CONTAINER_STYLE,
    COLOR_GRAY_MEDIUM,
    FONT_SANS,
    FONT_SIZE_SMALL,
    SPACING_XSMALL,
)


def get_layout() -> html.Div:
    """Return the query catalog listing page layout."""
    return html.Div(
        [
            dcc.Store(id="library-store", storage_type="memory"),
            dcc.Store(id="library-namespaces-store", storage_type="memory"),
            dcc.Store(id="library-system-ids-store", storage_type="memory"),
            dcc.Store(id="library-pending-delete", storage_type="memory"),
            dcc.ConfirmDialog(
                id="library-delete-confirm",
                message="",
            ),
            html.Div(id="library-feedback"),
            create_page_header(
                [("Library", None)],
                "Browse and manage the query catalog. User-defined queries "
                "override factory defaults.",
            ),
            html.Div(
                [
                    dbc.Row(
                        [
                            dbc.Col(
                                dbc.Select(
                                    id="library-namespace-filter",
                                    options=[
                                        {
                                            "label": "All namespaces",
                                            "value": "__all__",
                                        }
                                    ],
                                    value="__all__",
                                    size="sm",
                                ),
                                width=3,
                            ),
                            dbc.Col(
                                dbc.Input(
                                    id="library-search-input",
                                    type="text",
                                    placeholder="Search all columns…",
                                    className="library-search-input",
                                ),
                                width=True,
                            ),
                            dbc.Col(
                                dbc.Button(
                                    "New Query",
                                    id="library-new-btn",
                                    color="primary",
                                    size="sm",
                                    className="ms-2",
                                ),
                                width="auto",
                                className="text-end",
                            ),
                        ],
                        className="g-2 align-items-center",
                    ),
                    html.Div(
                        render_library_table(),
                        id="library-table-container",
                        style={
                            "marginTop": SPACING_XSMALL,
                            "overflowX": "auto",
                        },
                    ),
                ],
                style=CARD_CONTAINER_STYLE,
            ),
        ],
    )


def render_library_table() -> html.Div:
    """Return the static table skeleton.

    Only the header row is rendered here. The body rows are built entirely in
    JavaScript by the ``render_library_table`` clientside callback (see
    ``callbacks.py``), which reads the raw catalog data from ``library-store``
    and constructs the ``<tr>``/``<td>`` HTML directly in the browser. This
    avoids Dash's per-component instantiation cost for 140+ rows, which was
    the source of the multi-second page-load delay.
    """
    return html.Div(
        [
            dbc.Table(
                [
                    html.Thead(
                        html.Tr(
                            [
                                html.Th("Name"),
                                html.Th("Summary"),
                                html.Th("Tags"),
                                html.Th("Status"),
                                html.Th("Default View"),
                                html.Th("Parameters"),
                                html.Th("Views"),
                                html.Th("Source"),
                                html.Th("Actions"),
                            ]
                        )
                    ),
                    html.Tbody(id="library-table-body"),
                ],
                bordered=False,
                hover=True,
                size="sm",
                className="align-middle executive-table",
                style={"fontFamily": FONT_SANS, "fontSize": FONT_SIZE_SMALL},
            ),
            html.Div(
                "No queries match the current filters.",
                id="library-empty-row",
                style={
                    "display": "none",
                    "color": COLOR_GRAY_MEDIUM,
                    "fontFamily": FONT_SANS,
                },
            ),
        ]
    )
"""Dash layout for the Library (query catalog) listing page."""

from typing import Any

from dash import dcc, html
import dash_bootstrap_components as dbc

from app.dash_app.components.common import create_page_header
from app.dash_app.styles import (
    CARD_CONTAINER_STYLE,
    COLOR_BORDER,
    COLOR_GRAY_MEDIUM,
    COLOR_NAVY,
    FONT_SANS,
    FONT_SIZE_SMALL,
    FONT_SIZE_XSMALL,
    FONT_WEIGHT_MEDIUM,
    FONT_WEIGHT_SEMIBOLD,
    SPACING_XXSMALL,
    SPACING_XSMALL,
    SPACING_SMALL,
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
                                dbc.Button(
                                    "New Query",
                                    id="library-new-btn",
                                    color="primary",
                                    size="sm",
                                    className="me-2",
                                ),
                                width="auto",
                            ),
                            dbc.Col(
                                dcc.Dropdown(
                                    id="library-namespace-filter",
                                    placeholder="All namespaces",
                                    clearable=True,
                                ),
                                width=3,
                            ),
                            dbc.Col(
                                dbc.Input(
                                    id="library-search-input",
                                    type="text",
                                    placeholder="Search by name, tags, or id…",
                                    debounce=True,
                                ),
                                width=True,
                            ),
                        ],
                        className="g-2 align-items-center",
                    ),
                    html.Div(
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


def _status_badge(status: str | None) -> html.Span:
    """Render a status badge with semantic colouring."""
    color_map = {
        "active": "success",
        "draft": "secondary",
        "deprecated": "warning",
    }
    color = color_map.get(status or "", "secondary")
    return html.Span(
        status or "—",
        className=f"badge text-bg-{color}",
        style={"fontSize": FONT_SIZE_XSMALL},
    )


def _tag_chips(tags: list[str]) -> html.Div:
    """Render tags as small theme-aware chips."""
    chips = [
        html.Span(
            tag,
            className="badge border",
            style={
                "fontSize": FONT_SIZE_XSMALL,
                "marginRight": SPACING_XXSMALL,
                "backgroundColor": "var(--color-background-pale)",
                "color": "var(--color-charcoal-medium)",
            },
        )
        for tag in tags
    ]
    return html.Div(chips, style={"display": "flex", "flexWrap": "wrap", "gap": SPACING_XXSMALL})


def _view_icons(available_views: list[str]) -> html.Div:
    """Render tabular/graph view availability icons."""
    icons: list[Any] = []
    if "tabular" in available_views:
        icons.append(
            html.I(
                className="fas fa-table me-1",
                title="Tabular",
                style={"color": COLOR_NAVY},
            )
        )
    if "graph" in available_views:
        icons.append(
            html.I(
                className="fas fa-project-diagram",
                title="Graph",
                style={"color": COLOR_NAVY},
            )
        )
    if not icons:
        icons.append(html.Span("—", style={"color": COLOR_GRAY_MEDIUM}))
    return html.Div(icons)


def _is_user_row(query: dict[str, Any]) -> bool:
    """A row is a user row iff its source_path lives under ``user_defined/``."""
    return "user_defined/" in (query.get("source_path") or "")


def _destructive_label(query: dict[str, Any], system_ids: set[str]) -> str:
    """Label the destructive button: override rows reset, additions delete."""
    if query.get("id") in system_ids:
        return "Reset to factory"
    return "Delete"


def render_library_table(
    queries: list[dict[str, Any]],
    system_ids: set[str],
    namespace: str | None = None,
    search: str | None = None,
) -> html.Div:
    """Render the catalog table, applying namespace and search filters.

    This is a pure function so it can be unit-tested directly and reused by
    the callback layer.
    """
    filtered = _filter_queries(queries, namespace=namespace, search=search)

    if not filtered:
        return html.Div(
            "No queries match the current filters.",
            style={"color": COLOR_GRAY_MEDIUM, "fontFamily": FONT_SANS},
        )

    header = dbc.Table(
        [
            html.Thead(
                html.Tr(
                    [
                        html.Th("Name"),
                        html.Th("Namespace"),
                        html.Th("Tags"),
                        html.Th("Status"),
                        html.Th("Views"),
                        html.Th("Actions"),
                    ]
                )
            ),
            html.Tbody(
                [
                    _render_row(index, query, system_ids)
                    for index, query in enumerate(filtered)
                ]
            ),
        ],
        bordered=True,
        hover=True,
        size="sm",
        className="align-middle executive-table",
        style={"fontFamily": FONT_SANS, "fontSize": FONT_SIZE_SMALL},
    )
    return html.Div(header)


def _filter_queries(
    queries: list[dict[str, Any]],
    namespace: str | None,
    search: str | None,
) -> list[dict[str, Any]]:
    """Filter queries by namespace directory and free-text search."""
    filtered = queries
    if namespace:
        filtered = [
            q
            for q in filtered
            if (q.get("namespace") or {}).get("directory") == namespace
        ]
    if search:
        needle = search.strip().lower()
        filtered = [
            q
            for q in filtered
            if _matches_search(q, needle)
        ]
    return filtered


def _matches_search(query: dict[str, Any], needle: str) -> bool:
    """Match a query against name, tags, and id."""
    haystack = " ".join(
        [
            query.get("name") or "",
            query.get("id") or "",
            " ".join(query.get("tags") or []),
        ]
    ).lower()
    return needle in haystack


def _render_row(
    index: int,
    query: dict[str, Any],
    system_ids: set[str],
) -> html.Tr:
    """Render a single table row."""
    is_user = _is_user_row(query)
    query_id = query.get("id") or ""
    actions: list[Any] = [
        dbc.Button(
            "Edit",
            id={"type": "library-edit-btn", "id": query_id},
            color="primary",
            outline=True,
            size="sm",
            className="me-1",
        )
    ]
    if is_user:
        actions.append(
            dbc.Button(
                _destructive_label(query, system_ids),
                id={"type": "library-destructive-btn", "id": query_id},
                color="outline-danger",
                size="sm",
            )
        )

    return html.Tr(
        [
            html.Td(query.get("name") or query.get("id") or ""),
            html.Td((query.get("namespace") or {}).get("directory") or ""),
            html.Td(_tag_chips(query.get("tags") or [])),
            html.Td(_status_badge(query.get("status"))),
            html.Td(_view_icons(query.get("available_views") or [])),
            html.Td(actions),
        ]
    )
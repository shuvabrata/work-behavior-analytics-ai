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


def _status_badge(status: str | None) -> html.Span | None:
    """Render a status badge matching the Graph Query Catalog.

    ``draft`` → warning (amber), ``deprecated`` → secondary (gray). Unlike the
    Graph page, ``active`` is also shown (as success/green) so the Library
    table surfaces the active state. Returns ``None`` for unknown/empty status.
    """
    color_map = {
        "active": "success",
        "draft": "warning",
        "deprecated": "secondary",
    }
    if not status:
        return None
    status_lower = status.strip().lower()
    color = color_map.get(status_lower)
    if color is None:
        return None
    return html.Span(
        status_lower.title(),
        className=f"badge text-bg-{color}",
        style={"fontSize": FONT_SIZE_XSMALL},
    )


def _tag_chips(tags: list[str]) -> html.Div:
    """Render tags as badges matching the Graph Query Catalog."""
    chips = [
        dbc.Badge(
            tag,
            color="light",
            text_color="dark",
            className="me-1",
            style={"fontSize": FONT_SIZE_XSMALL},
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


def _source_label(query: dict[str, Any]) -> html.Span:
    """Render a source badge: 'User' for overrides, 'System' otherwise."""
    if _is_user_row(query):
        return html.Span(
            "User",
            className="badge border",
            style={
                "fontSize": FONT_SIZE_XSMALL,
                "backgroundColor": "var(--color-navy)",
                "color": "var(--color-background-white)",
            },
        )
    return html.Span(
        "System",
        className="badge border",
        style={
            "fontSize": FONT_SIZE_XSMALL,
            "backgroundColor": "var(--color-background-pale)",
            "color": "var(--color-charcoal-medium)",
        },
    )


def _default_view_label(default_view: str | None) -> str:
    """Render the default view as a short label or an em-dash."""
    return default_view or "—"


def _parameters_label(parameters: list[dict[str, Any]] | None) -> str:
    """Render the parameter count, or an em-dash when there are none."""
    count = len(parameters or [])
    return str(count) if count else "—"


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
    """Render the catalog table.

    All rows are rendered once; the namespace/search filtering is applied
    client-side (see the ``filter_library_table`` clientside callback) so
    typing in the search box does not trigger a server round-trip or a full
    table rebuild. The ``namespace``/``search`` arguments are accepted for
    backward compatibility with the pure-function tests but are not applied
    here.
    """
    if not queries:
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
            html.Tbody(
                [
                    _render_row(index, query, system_ids)
                    for index, query in enumerate(queries)
                ]
            ),
        ],
        bordered=False,
        hover=True,
        size="sm",
        className="align-middle executive-table",
        style={"fontFamily": FONT_SANS, "fontSize": FONT_SIZE_SMALL},
    )
    return html.Div(
        [
            header,
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


def _filter_queries(
    queries: list[dict[str, Any]],
    namespace: str | None,
    search: str | None,
) -> list[dict[str, Any]]:
    """Filter queries by namespace directory and free-text search."""
    filtered = queries
    if namespace and namespace != "__all__":
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
    """Match a query against all loaded columns (name, summary, tags, etc.)."""
    haystack = " ".join(
        [
            query.get("name") or "",
            query.get("id") or "",
            query.get("summary") or "",
            query.get("owner") or "",
            query.get("status") or "",
            query.get("default_view") or "",
            " ".join(query.get("tags") or []),
            "User" if _is_user_row(query) else "System",
        ]
    ).lower()
    return needle in haystack


def _searchable_text(query: dict[str, Any]) -> str:
    """Build the lowercased searchable text for a row's ``data-search`` attr.

    Mirrors :func:`_matches_search` so the client-side filter and the
    pure-function tests agree on what is searchable.
    """
    return " ".join(
        [
            query.get("name") or "",
            query.get("id") or "",
            query.get("summary") or "",
            query.get("owner") or "",
            query.get("status") or "",
            query.get("default_view") or "",
            " ".join(query.get("tags") or []),
            "User" if _is_user_row(query) else "System",
        ]
    ).lower()


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
            html.Td(query.get("summary") or "—"),
            html.Td(_tag_chips(query.get("tags") or [])),
            html.Td(_status_badge(query.get("status")) or "—"),
            html.Td(_default_view_label(query.get("default_view"))),
            html.Td(_parameters_label(query.get("parameters"))),
            html.Td(_view_icons(query.get("available_views") or [])),
            html.Td(_source_label(query)),
            html.Td(actions),
        ],
        **{  # type: ignore[arg-type]  # Dash data-* attributes are untyped
            "data-search": _searchable_text(query),
            "data-namespace": (query.get("namespace") or {}).get("directory") or "",
        },
    )
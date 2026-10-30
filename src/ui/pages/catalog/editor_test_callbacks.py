"""Callbacks for the catalog editor's Quick Test / View Test buttons."""

from __future__ import annotations

from typing import Any

import dash_bootstrap_components as dbc
from dash import (
    Input,
    Output,
    State,
    callback,
    clientside_callback,
    ctx,
    no_update,
)

from ui import api_client
from ui.api_client import STATUS_NO_RESPONSE, ApiError
from ui.components.common import create_alert
from ui.graph_styles import build_cytoscape_stylesheet
from ui.pages.graph.utils import (
    create_error_alert,
    create_table_display,
    fetch_effective_theme,
    neo4j_to_cytoscape,
    parse_error_response,
)


def _run_test(query_text: str | None) -> dict[str, Any]:
    """Execute a raw Cypher query and return the raw API response.

    Returns a dict with keys:
      - "ok":         bool
      - "data":       dict | None  (full API JSON on success)
      - "error":      str  | None  (short single-line message on failure)
      - "heading":    str  | None  (classified heading for the modal)
      - "hint":       str  | None  (actionable hint for the modal)
      - "doc_link":   str  | None  (Cypher docs URL for the modal)
      - "alert_type": str  | None  (Bootstrap alert type for the modal)

    ``"error"`` is always a short single-line message (rendered by the Quick
    Test badge). ``"heading"``/``"hint"``/``"doc_link"``/``"alert_type"`` are
    the classified fields produced by ``parse_error_response`` for the View Test
    modal and may be ``None``.
    """
    if not query_text or not query_text.strip():
        return {"ok": False, "data": None,
                "error": "Enter a query before testing.",
                "heading": None, "hint": None, "doc_link": None,
                "alert_type": "danger"}
    payload = {"source": "raw", "query": query_text.strip(), "view": "auto"}
    try:
        return {"ok": True, "data": api_client.post(
            "/api/v1/graph/execute", json=payload
        ).json(), "error": None}
    except ApiError as exc:
        if exc.status_code == STATUS_NO_RESPONSE:
            return {"ok": False, "data": None, "error": str(exc),
                    "heading": None, "hint": None, "doc_link": None,
                    "alert_type": "danger"}
        if isinstance(exc.detail, dict):
            body = {"detail": exc.detail}
            heading, hint, doc_link, alert_type = parse_error_response(
                body, exc.status_code
            )
            message = (
                exc.detail.get("message") or exc.detail.get("error")
                or "Query execution failed."
            )
            return {
                "ok": False, "data": None, "error": message,
                "heading": heading, "hint": hint,
                "doc_link": doc_link, "alert_type": alert_type,
            }
        # Non-dict `detail` (FastAPI 422 returns a list): keep the raw text.
        # parse_error_response would raise AttributeError on this shape.
        return {
            "ok": False, "data": None,
            "error": str(exc.detail) if exc.detail else "Query execution failed.",
            "heading": None, "hint": None, "doc_link": None,
            "alert_type": "danger",
        }


_BADGE_CLASS = "alert-inline-badge"


def _quick_test_badge(query: str | None) -> dbc.Alert:
    """Build the inline result badge for one Quick Test button."""
    result = _run_test(query)
    if result["ok"]:
        data = result["data"]
        if data.get("isGraph"):
            n, r = len(data.get("nodes", [])), len(data.get("relationships", []))
            return dbc.Alert(f"✔ Graph: {n} nodes, {r} relationships",
                             color="success", dismissable=True, className=_BADGE_CLASS)
        count = data.get("resultCount", 0)
        return dbc.Alert(f"✔ {count} row(s) returned",
                         color="success", dismissable=True, className=_BADGE_CLASS)
    return dbc.Alert(f"✘ {result['error']}",
                     color="danger", dismissable=True, className=_BADGE_CLASS)


@callback(
    Output("editor-quick-test-tabular-feedback", "children"),
    Input("editor-quick-test-tabular", "n_clicks"),
    State("editor-query-tabular", "value"),
    prevent_initial_call=True,
)
def quick_test_tabular(_clicks: int | None, query: str | None) -> dbc.Alert:
    """Render the inline badge for the Tabular Query's Quick Test button."""
    return _quick_test_badge(query)


@callback(
    Output("editor-quick-test-graph-feedback", "children"),
    Input("editor-quick-test-graph", "n_clicks"),
    State("editor-query-graph", "value"),
    prevent_initial_call=True,
)
def quick_test_graph(_clicks: int | None, query: str | None) -> dbc.Alert:
    """Render the inline badge for the Graph Query's Quick Test button."""
    return _quick_test_badge(query)


@callback(
    Output("editor-quick-test-tabular-feedback", "children", allow_duplicate=True),
    Input("editor-query-tabular", "value"),
    prevent_initial_call=True,
)
def clear_quick_test_tabular_badge(_value: str | None) -> None:
    """Drop the Tabular pane's stale Quick Test badge when its query changes."""
    return None


@callback(
    Output("editor-quick-test-graph-feedback", "children", allow_duplicate=True),
    Input("editor-query-graph", "value"),
    prevent_initial_call=True,
)
def clear_quick_test_graph_badge(_value: str | None) -> None:
    """Drop the Graph pane's stale Quick Test badge when its query changes."""
    return None


@callback(
    Output("editor-test-modal",       "is_open"),
    Output("editor-test-modal-title", "children"),
    Input("editor-view-test-tabular", "n_clicks"),
    Input("editor-view-test-graph",   "n_clicks"),
    Input("editor-test-modal-close",  "n_clicks"),
    prevent_initial_call=True,
)
def toggle_test_modal(
    _tab_clicks: int | None,
    _graph_clicks: int | None,
    _close_clicks: int | None,
) -> tuple[bool, Any]:
    """Open the results modal on either View Test button, close it on Close.

    Deliberately does no HTTP: it must return instantly so the modal (and the
    dcc.Loading spinner inside it) is on screen while `view_test` fetches.
    """
    if ctx.triggered_id == "editor-test-modal-close":
        return False, no_update
    if ctx.triggered_id == "editor-view-test-tabular":
        return True, "Test Results — Tabular"
    return True, "Test Results — Graph"


@callback(
    Output("editor-test-cytoscape",           "elements"),
    Output("editor-test-cytoscape-container", "style"),
    Output("editor-test-table-container",     "children"),
    Output("editor-test-table-container",     "style"),
    Output("editor-test-results-container",   "children"),
    Output("editor-test-results-container",   "style"),
    Output("editor-test-fit-row",             "style"),
    Input("editor-view-test-tabular", "n_clicks"),
    Input("editor-view-test-graph",   "n_clicks"),
    State("editor-query-tabular", "value"),
    State("editor-query-graph",   "value"),
    prevent_initial_call=True,
)
def view_test(
    _tab_clicks: int | None,
    _graph_clicks: int | None,
    tab_query: str | None,
    graph_query: str | None,
) -> tuple[Any, ...]:
    """Fetch and render tabular or graph results inside the shared modal.

    The modal's open state and title are owned by `toggle_test_modal`; this
    callback only fills the result panes.
    """
    hide = {"display": "none"}
    show = {"display": "block"}
    empty_show = {"minHeight": "300px", "padding": "16px"}
    fit_show = {"display": "flex", "justifyContent": "flex-end"}

    if ctx.triggered_id == "editor-view-test-tabular":
        query = tab_query
    else:
        query = graph_query

    result = _run_test(query)
    is_empty = not (query or "").strip()

    if not result["ok"]:
        if is_empty:
            error: Any = create_alert(
                "Enter a query before testing.", color="warning", class_name="mb-3"
            )
        elif result.get("heading"):
            error = create_error_alert(
                "",  # the message is carried by the heading, as on the Graph page
                alert_type=result["alert_type"],
                hint=result["hint"],
                heading=result["heading"],
                doc_link=result["doc_link"],
            )
        else:
            error = create_error_alert(result["error"], heading="Query Failed")
        return [], hide, None, hide, error, empty_show, hide

    data = result["data"]
    if data.get("isGraph"):
        elements = neo4j_to_cytoscape(data)
        return elements, show, None, hide, None, hide, fit_show
    table = create_table_display(data.get("rawResults") or [])
    return [], hide, table, show, None, hide, hide


clientside_callback(
    """
    function(n_clicks) {
        if (n_clicks) {
            const elem = document.getElementById('editor-test-cytoscape');
            if (elem && elem._cyreg && elem._cyreg.cy) {
                elem._cyreg.cy.fit(null, 30);
            }
        }
        return window.dash_clientside.no_update;
    }
    """,
    Output("editor-test-fit", "className"),   # dummy output
    Input("editor-test-fit", "n_clicks"),
    prevent_initial_call=True,
)


@callback(
    Output("editor-test-cytoscape", "stylesheet"),
    Input("theme-store", "data"),
)
def update_test_stylesheet(theme_name: str | None) -> list[dict[str, Any]]:
    """Rebuild the modal's Cytoscape palette when the app theme changes.

    Mirrors the Graph and Collaboration pages: fetch the server-merged effective
    theme (base tokens ⊕ default-theme overrides) and build the stylesheet from
    it. `fetch_effective_theme` returns None on any error, which falls back to
    the hardcoded base tokens.
    """
    active_theme = theme_name or "executive-light"
    effective = fetch_effective_theme(active_theme)
    return build_cytoscape_stylesheet(active_theme, effective=effective)

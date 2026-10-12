"""Callbacks for the catalog editor's Quick Test / View Test buttons."""

from __future__ import annotations

from typing import Any

import requests
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

from app.dash_app.graph_styles import build_cytoscape_stylesheet
from app.dash_app.pages.graph.utils import (
    create_error_alert,
    create_table_display,
    fetch_effective_theme,
    neo4j_to_cytoscape,
)
from app.runtime_settings import runtime_settings
from ._utils import get_api_base_url

TIMEOUT_SECONDS = runtime_settings.get_int("HTTP_REQUEST_TIMEOUT")


def _run_test(query_text: str | None) -> dict[str, Any]:
    """Execute a raw Cypher query and return the raw API response.

    Returns a dict with keys:
      - "ok":    bool
      - "data":  dict | None  (full API JSON on success)
      - "error": str  | None  (user-facing message on failure)
    """
    if not query_text or not query_text.strip():
        return {"ok": False, "data": None,
                "error": "Enter a query before testing."}
    payload = {"source": "raw", "query": query_text.strip(), "view": "auto"}
    api_base = get_api_base_url()
    try:
        resp = requests.post(
            f"{api_base}/api/v1/graph/execute",
            json=payload, timeout=TIMEOUT_SECONDS,
        )
        if resp.status_code != 200:
            try:
                detail = resp.json().get("detail", {})
                msg = (detail.get("message", "Query execution failed.")
                       if isinstance(detail, dict) else str(detail))
            except ValueError:
                msg = "Query execution failed."
            return {"ok": False, "data": None, "error": msg}
        return {"ok": True, "data": resp.json(), "error": None}
    except requests.exceptions.RequestException as exc:
        return {"ok": False, "data": None, "error": str(exc)}


_BADGE_CLASS = "alert-inline-badge"


@callback(
    Output("editor-quick-test-tabular-feedback", "children"),
    Output("editor-quick-test-graph-feedback",   "children"),
    Input("editor-quick-test-tabular", "n_clicks"),
    Input("editor-quick-test-graph",   "n_clicks"),
    State("editor-query-tabular", "value"),
    State("editor-query-graph",   "value"),
    prevent_initial_call=True,
)
def quick_test(
    _tab_clicks: int | None,
    _graph_clicks: int | None,
    tab_query: str | None,
    graph_query: str | None,
) -> tuple[Any, Any]:
    """Render an inline result badge for whichever Quick Test button fired."""
    triggered = ctx.triggered_id
    query = tab_query if triggered == "editor-quick-test-tabular" else graph_query
    result = _run_test(query)

    if result["ok"]:
        data = result["data"]
        if data.get("isGraph"):
            n, r = len(data.get("nodes", [])), len(data.get("relationships", []))
            badge = dbc.Alert(f"✔ Graph: {n} nodes, {r} relationships",
                              color="success", dismissable=True, className=_BADGE_CLASS)
        else:
            count = data.get("resultCount", 0)
            badge = dbc.Alert(f"✔ {count} row(s) returned",
                              color="success", dismissable=True, className=_BADGE_CLASS)
    else:
        badge = dbc.Alert(f"✘ {result['error']}",
                          color="danger", dismissable=True, className=_BADGE_CLASS)

    if triggered == "editor-quick-test-tabular":
        return badge, no_update
    return no_update, badge


@callback(
    Output("editor-test-modal",               "is_open"),
    Output("editor-test-modal-title",         "children"),
    Output("editor-test-cytoscape",           "elements"),
    Output("editor-test-cytoscape-container", "style"),
    Output("editor-test-table-container",     "children"),
    Output("editor-test-table-container",     "style"),
    Output("editor-test-results-container",   "children"),
    Output("editor-test-results-container",   "style"),
    Input("editor-view-test-tabular", "n_clicks"),
    Input("editor-view-test-graph",   "n_clicks"),
    Input("editor-test-modal-close",  "n_clicks"),
    State("editor-query-tabular", "value"),
    State("editor-query-graph",   "value"),
    prevent_initial_call=True,
)
def view_test(
    _tab_clicks: int | None,
    _graph_clicks: int | None,
    _close_clicks: int | None,
    tab_query: str | None,
    graph_query: str | None,
) -> tuple[Any, ...]:
    """Open the shared modal with tabular or graph results."""
    hide = {"display": "none"}
    show = {"display": "block"}
    empty_show = {"minHeight": "300px", "padding": "16px"}

    if ctx.triggered_id == "editor-test-modal-close":
        return (False,) + (no_update,) * 7

    if ctx.triggered_id == "editor-view-test-tabular":
        query, label = tab_query,   "Test Results — Tabular"
    else:
        query, label = graph_query, "Test Results — Graph"

    result = _run_test(query)

    if not result["ok"]:
        error = create_error_alert(result["error"], heading="Query Failed")
        return True, label, [], hide, None, hide, error, empty_show

    data = result["data"]
    if data.get("isGraph"):
        elements = neo4j_to_cytoscape(data)
        return True, label, elements, show, None, hide, None, hide
    table = create_table_display(data.get("rawResults") or [])
    return True, label, [], hide, table, show, None, hide


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

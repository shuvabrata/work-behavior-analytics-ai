"""Callbacks for the catalog editor's Quick Test / View Test buttons."""

from __future__ import annotations

from typing import Any

import requests
import dash_bootstrap_components as dbc
from dash import Input, Output, State, callback, ctx, no_update

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
    tab_clicks: int | None,
    graph_clicks: int | None,
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

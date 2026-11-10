"""Callbacks for switching the generic graph page into analytics mode."""

from typing import Any
from urllib.parse import parse_qs

from dash import Input, Output, callback


@callback(
    Output("right-tab-console-btn", "style"),
    Output("right-tab-catalog-btn", "style"),
    [Input("url", "pathname"), Input("url", "search")],
)
def toggle_query_panel_for_analytics_mode(pathname: str | None, search: str | None) -> tuple[dict[str, Any], dict[str, Any]]:
    """Hide the Console and Catalog tabs when the graph page is in analytics mode."""
    # Dash supplies None before the URL resolves, and None has no .rstrip(); the
    # rstrip accepts the trailing-slash form that display_page also routes here.
    if (pathname or "").rstrip("/") != "/app/graph":
        return {}, {}

    params = parse_qs((search or "").lstrip("?"))
    if params.get("mode"):
        return {"display": "none"}, {"display": "none"}

    return {}, {}

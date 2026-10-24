"""Per-person (ego) Collaboration Network callbacks — loading and filter interactions."""

from typing import Any
from urllib.parse import parse_qs

import dash_bootstrap_components as dbc
from dash import Input, Output, State, callback, clientside_callback, ctx, html, no_update
from dash.exceptions import PreventUpdate

from app.analytics.collaboration.config import CollaborationNetworkConfig, LAYER_ORDER
from app.analytics.collaboration.ego import DEFAULT_MAX_COLLABORATORS, cap_options_for
from app.api.graph.v1.service import get_ego_network
from app.dash_app.components.common import register_loading_overlay_hider
from app.dash_app.styles import FONT_SIZE_SMALL
from common.logger import logger
from ..layout import (
    _EGO_LAYOUT,
    _compute_ego_filtered,
    _error_banner,
    _split_elements,
)


def _parse_max_collaborators(raw: Any) -> int:
    """Parse the ``max_collaborators`` URL parameter.

    Falls back to the default when the parameter is absent (a direct visit to
    the page) or unparseable, so the page behaves identically whether it was
    reached from the Analytics card or by deep link.
    """
    if raw is None or str(raw).strip() == "":
        return DEFAULT_MAX_COLLABORATORS
    try:
        return max(1, int(str(raw).strip()))
    except (TypeError, ValueError):
        return DEFAULT_MAX_COLLABORATORS


# ---------------------------------------------------------------------------
# Server-side callback — load the ego star into the store
# ---------------------------------------------------------------------------

@callback(
    [Output("ego-elements-store",   "data"),
     Output("ego-cytoscape",        "layout"),
     Output("ego-banner",           "children"),
     Output("ego-banner",           "style"),
     Output("ego-empty-state",      "style"),
     Output("ego-loading-state",    "data"),
     Output("ego-top-n-cap",        "options"),
     Output("ego-top-n-cap",        "value", allow_duplicate=True)],
    [Input({"type": "catalog-person-value", "name": "ego_focus"}, "data"),
     Input("url", "search"),
     Input("url", "pathname")],
    [State("ego-top-n-cap", "value")],
    prevent_initial_call="initial_duplicate",
)
def load_ego_network(
    person_value: str | dict[str, Any] | None,
    search: str | None,
    pathname: str | None,
    current_cap: int | None,
) -> tuple[
    list[dict[str, Any]], dict[str, Any], list[Any], dict[str, Any],
    dict[str, Any], bool, list[dict[str, Any]], Any,
]:
    """Fetch the focus person's star into the store when this page is active.

    Note: prevent_initial_call is "initial_duplicate" rather than True.  In
    Dash's multi-page pattern the output components don't exist until the user
    navigates to this page.  When they first appear, Dash treats the callback
    fire as an "initial call" — which prevent_initial_call=True would suppress,
    leaving the page permanently empty.  The pathname guard handles all
    non-ego routes safely.
    """
    if pathname != "/app/collaboration/person":
        raise PreventUpdate

    params = parse_qs((search or "").lstrip("?"), keep_blank_values=True)
    hide = {"display": "none"}
    show = {"display": "block"}

    empty_state_style = {
        "textAlign": "center",
        "padding": "80px 16px",
        "color": "var(--color-text-secondary)",
        "fontSize": FONT_SIZE_SMALL,
    }

    focus_id = ""
    if isinstance(person_value, dict):
        focus_id = str(person_value.get("wba") or "").strip()
    elif isinstance(person_value, str):
        focus_id = person_value.strip()

    # The card's Collaborator Cap is this load's ceiling. The in-page selector
    # slices the already-fetched store, so it may only be offered choices at or
    # below it.
    max_collaborators = _parse_max_collaborators(
        params.get("max_collaborators", [None])[0]
    )
    cap_options = cap_options_for(max_collaborators)
    cap_choices = {option["value"] for option in cap_options}

    # Adopt the card's cap when the URL triggered this load (first navigation or a
    # fresh link). Re-applying it on every person pick would silently undo a choice
    # the user just made in the page's own selector.
    raw_cap = params.get("max_collaborators", [None])[0]
    url_triggered = any(
        str(item.get("prop_id", "")).startswith("url.")
        for item in (ctx.triggered or [])
    )
    cap_update: Any = no_update
    if url_triggered and raw_cap not in (None, ""):
        cap_update = max_collaborators
    elif current_cap not in cap_choices:
        # The selection is above what this load fetched (or absent): clamp it into
        # the offered range so the radio can never render with nothing selected.
        cap_update = max_collaborators

    if not focus_id:
        # No person picked yet — show the empty state, do not call the API.
        return [], _EGO_LAYOUT, [], hide, {**empty_state_style, "display": "block"}, False, cap_options, cap_update

    logger.info(f"[EGO-PAGE] Loading ego network person={focus_id} search={search!r}")

    try:
        query_dict = {
            "layers":             params.get("layers"),
            "lookback_days":      params.get("lookback_days",      [None])[0],
            "min_pair_score":     params.get("min_pair_score",     [None])[0],
            "exclude_bots":       params.get("exclude_bots",       [None])[0],
            "exclude_suffixes":   params.get("exclude_suffixes",   [None])[0],
            **{
                f"w_{layer}": params.get(f"w_{layer}", [None])[0]
                for layer in LAYER_ORDER
            },
        }
        config = CollaborationNetworkConfig.from_query_values(query_dict)

        data = get_ego_network(focus_id, config=config, max_collaborators=max_collaborators)
        elements = data.elements

        if not elements:
            logger.warning("[EGO-PAGE] No elements returned")
            return [], _EGO_LAYOUT, [], hide, {**empty_state_style, "display": "block"}, False, cap_options, cap_update

        logger.info(
            f"[EGO-PAGE] SUCCESS — {len(elements)} elements, "
            f"{data.shown_collaborators}/{data.total_collaborators} collaborators"
        )

        # No summary banner on this page: the focus person, lookback window and
        # collaborator counts are already visible in the header, the page's own
        # filter panel and the node labels, so the badge row was redundant. The
        # banner region is kept for error alerts, which still need somewhere to
        # surface (see the except blocks below).
        return elements, _EGO_LAYOUT, [], hide, hide, False, cap_options, cap_update

    except ValueError as exc:
        logger.warning(f"[EGO-PAGE] No data: {exc}")
        return [], _EGO_LAYOUT, [_error_banner(str(exc))], show, hide, False, cap_options, cap_update

    except Exception as exc:  # pylint: disable=broad-except
        logger.exception(f"[EGO-PAGE] Unexpected error: {exc}")
        return (
            [], _EGO_LAYOUT, [_error_banner("An unexpected error occurred.")],
            show, hide, False, cap_options, cap_update,
        )


# ---------------------------------------------------------------------------
# Filter callbacks — pure functions over the store, no re-query
# ---------------------------------------------------------------------------

@callback(
    Output("ego-cytoscape", "elements"),
    [Input("ego-elements-store",          "data"),
     Input("ego-weight-threshold-slider", "value"),
     Input("ego-top-n-cap",               "value")],
)
def apply_ego_filters(
    elements: list[dict[str, Any]] | None,
    weight_threshold: float | int | None,
    top_n_cap: int | None,
) -> list[dict[str, Any]]:
    """Translate raw store elements through the active filters → cytoscape."""
    if not elements:
        return []
    result = _compute_ego_filtered(elements, weight_threshold or 0, top_n_cap)
    logger.debug(
        f"[EGO-FILTER] weight>={weight_threshold} cap={top_n_cap} → {len(result)} elements"
    )
    return result


@callback(
    Output("ego-weight-threshold-label", "children"),
    Input("ego-weight-threshold-slider", "value"),
)
def update_ego_weight_label(value: float | int | None) -> str:
    """Update the weight threshold label text."""
    return f"Show collaborators with weight ≥ {value or 0}"


@callback(
    [Output("ego-filter-results-summary", "children"),
     Output("ego-filter-active-chips",    "children")],
    [Input("ego-elements-store",          "data"),
     Input("ego-weight-threshold-slider", "value"),
     Input("ego-top-n-cap",               "value")],
)
def update_ego_filter_feedback(
    elements: list[dict[str, Any]] | None,
    weight_threshold: float | int | None,
    top_n_cap: int | None,
) -> tuple[str, list[Any]]:
    """Keep the summary line and active-filter chips up to date."""
    if not elements:
        return (
            "Pick a person to load their network.",
            [html.Span("No active filters", className="graph-filter-empty-state")],
        )

    nodes, edges = _split_elements(elements)
    filtered = _compute_ego_filtered(elements, weight_threshold or 0, top_n_cap)
    f_nodes, f_edges = _split_elements(filtered)

    summary = (
        f"Showing {len(f_nodes)} nodes / {len(f_edges)} edges"
        f" from {len(nodes)} nodes / {len(edges)} edges"
    )

    chips: list[Any] = []
    if (weight_threshold or 0) > 0:
        chips.append(dbc.Badge(f"Weight ≥ {weight_threshold}", color="secondary", className="me-1"))
    if top_n_cap and top_n_cap != DEFAULT_MAX_COLLABORATORS:
        chips.append(dbc.Badge(f"Top {top_n_cap}", color="info", className="me-1"))

    if not chips:
        chips = [html.Span("No active filters", className="graph-filter-empty-state")]

    return summary, chips


@callback(
    [Output("ego-weight-threshold-slider", "value", allow_duplicate=True),
     Output("ego-top-n-cap",               "value", allow_duplicate=True)],
    Input("ego-clear-filters-btn", "n_clicks"),
    prevent_initial_call=True,
)
def clear_ego_filters(n_clicks: int | None) -> tuple[int, int]:
    """Reset all filter controls to their defaults."""
    return 0, DEFAULT_MAX_COLLABORATORS


@callback(
    Output("ego-right-tab-filters-collapse", "is_open"),
    Output("ego-right-tab-filters-btn",      "className"),
    Input("ego-right-tab-filters-btn",       "n_clicks"),
    State("ego-right-tab-filters-collapse",  "is_open"),
    prevent_initial_call=True,
)
def toggle_ego_filter_panel(n_clicks: int | None, is_open: bool) -> tuple[bool, str]:
    """Toggle the Filters tab open/closed and update the icon button active state."""
    new_open = not is_open
    btn_class = "graph-right-panel-tab-icon active" if new_open else "graph-right-panel-tab-icon"
    return new_open, btn_class


# ---------------------------------------------------------------------------
# Clientside loading overlay hider + fit after initial data load
# ---------------------------------------------------------------------------

register_loading_overlay_hider("ego-loading-state", "ego-loading-overlay")

clientside_callback(
    """
    function(storeData) {
        if (!storeData || !Array.isArray(storeData) || storeData.length === 0) {
            return window.dash_clientside.no_update;
        }
        // Delay to allow apply_ego_filters to complete and Cytoscape to paint.
        window.setTimeout(function() {
            var elem = document.getElementById("ego-cytoscape");
            if (!elem || !elem._cyreg || !elem._cyreg.cy) { return; }
            var cy = elem._cyreg.cy;
            cy.resize();
            cy.fit(cy.elements(), 30);
        }, 400);
        return "fit-scheduled n=" + storeData.length;
    }
    """,
    Output("ego-render-trigger", "children"),
    Input("ego-elements-store",  "data"),
    prevent_initial_call=True,
)

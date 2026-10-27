"""Per-person (ego) Collaboration Network callbacks — loading and filter interactions."""

from typing import Any
from urllib.parse import parse_qs

import dash_bootstrap_components as dbc
from dash import Input, Output, State, callback, clientside_callback, html, no_update
from dash.exceptions import PreventUpdate

from app.analytics.collaboration.config import CollaborationNetworkConfig, LAYER_ORDER
from app.analytics.collaboration.ego import cap_options_for
from app.analytics.collaboration.errors import CollaborationDataUnavailable
from app.api.graph.v1.service import get_ego_network
from app.common.person_network_url import (
    DEFAULT_MAX_COLLABORATORS,
    PERSON_NETWORK_PATH,
    clamp_max_collaborators,
    parse_person_network_url,
    search_with_person,
)
from app.dash_app.components.common import describe_config_error, register_loading_overlay_hider
from app.dash_app.components.person_picker import build_person_chip
from common.logger import logger
from ..layout import (
    _EGO_LAYOUT,
    _EMPTY_STATE_STYLE,
    _compute_ego_filtered,
    _data_unavailable_banner,
    _error_banner,
    _split_elements,
)


def _parse_max_collaborators(raw: Any) -> int:
    """Parse the ``max_collaborators`` URL parameter.

    Delegates to the shared URL contract so the bound here matches the one the
    link builder and the API use. A value above the API's ceiling is clamped
    rather than passed through, since the endpoint would reject it with a 400.
    """
    return clamp_max_collaborators(raw)


def _ego_query_dict(params: dict[str, list[str]]) -> dict[str, Any]:
    """Build the query-value mapping the ego page feeds to the config model."""
    return {
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


def _deep_linked_person(search: str | None) -> str | None:
    """Return the well-formed Person wba_id named by the URL, if any.

    Uses the shared URL contract so this page and any component that builds a
    link agree on the parameter name and the id rules.
    """
    return parse_person_network_url(search)["person"]


def _ego_config_from_params(
    params: dict[str, list[str]],
) -> tuple[CollaborationNetworkConfig | None, list[str]]:
    """Build the collaboration config from URL params, reporting any problems.

    Returns ``(config, problems)``. Exactly one is ever meaningful: a valid set
    of params yields a config and no problems, an invalid one yields ``None`` and
    one human-readable problem string. Parsing happens once here so the value the
    page validates is the same object the page then uses.
    """
    try:
        return CollaborationNetworkConfig.from_query_values(_ego_query_dict(params)), []
    except ValueError as exc:
        return None, [describe_config_error(exc)]


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
    [State("ego-top-n-cap", "value"),
     State("ego-elements-store", "data")],
    prevent_initial_call="initial_duplicate",
)
def load_ego_network(
    person_value: str | dict[str, Any] | None,
    search: str | None,
    pathname: str | None,
    current_cap: int | None,
    stored_elements: list[dict[str, Any]] | None,
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
    if pathname != PERSON_NETWORK_PATH:
        raise PreventUpdate

    params = parse_qs((search or "").lstrip("?"), keep_blank_values=True)
    hide = {"display": "none"}
    show = {"display": "block"}

    # The prompt's positioning lives with the element in layout.py. This callback
    # assigns the whole style dict, so the two must be the same object: a copy
    # here would replace the layout's positioning on the first fire and drop the
    # prompt back into flow below the canvas, where it causes the scrollbar.
    empty_state_style = _EMPTY_STATE_STYLE

    focus_id = ""
    if isinstance(person_value, dict):
        focus_id = str(person_value.get("wba") or "").strip()
    elif isinstance(person_value, str):
        focus_id = person_value.strip()

    if not focus_id:
        # The picker is empty. A deep link carries the focus person in the URL
        # (see app.common.person_network_url), so fall back to it — this is what
        # lets another component link straight to one person's network. The
        # picker's own value wins whenever it has one, so a user who picks a
        # different person is never overridden by a stale URL.
        focus_id = _deep_linked_person(search) or ""

    # The card's Collaborator Cap is this load's ceiling. The in-page selector
    # slices the already-fetched store, so it may only be offered choices at or
    # below it.
    max_collaborators = _parse_max_collaborators(
        params.get("max_collaborators", [None])[0]
    )
    cap_options = cap_options_for(max_collaborators)
    cap_choices = {option["value"] for option in cap_options}

    # Adopt the card's cap on this load only when it is the page's FIRST fetch,
    # and never afterwards. The elements store is empty until a fetch has
    # populated it, so it is a reliable "nothing has been loaded yet" test —
    # unlike ctx.triggered, which arrives NON-empty here: the person picker seeds
    # its catalog-person-value store as the page mounts, and Dash counts that
    # transition as an Input change. A trigger-based test therefore never fires on
    # the first load, and the radio keeps its layout default (25) while the fetch
    # honours the URL's cap.
    raw_cap = params.get("max_collaborators", [None])[0]
    first_fetch = not stored_elements
    cap_update: Any = no_update
    if first_fetch and raw_cap not in (None, ""):
        cap_update = max_collaborators
    elif current_cap not in cap_choices:
        # The selection is above what this load fetched (or absent): clamp it into
        # the offered range so the radio can never render with nothing selected.
        cap_update = max_collaborators

    # Validate the URL's settings even when no person is picked yet: a bad deep
    # link must say so, rather than showing a bare "pick a person" state that
    # gives no hint the URL is wrong. The card omits org-only params, and the ego
    # card sends none of these, so a malformed value can only come from a
    # hand-edited or stale link.
    config, url_problems = _ego_config_from_params(params)

    if not focus_id:
        # No person picked yet — show the empty state, do not call the API.
        visible_empty_state = {**empty_state_style, "display": "flex"}
        if url_problems:
            banner = [_error_banner(" ".join(url_problems))]
            return [], _EGO_LAYOUT, banner, show, visible_empty_state, False, cap_options, cap_update
        return [], _EGO_LAYOUT, [], hide, visible_empty_state, False, cap_options, cap_update

    if url_problems:
        # Person is picked but the URL's settings are unusable. Previously this
        # surfaced by catching the ValueError the second parse raised inside the
        # try below; now it is a plain check, with the same banner and styles.
        return [], _EGO_LAYOUT, [_error_banner(" ".join(url_problems))], show, hide, False, cap_options, cap_update

    logger.info(f"[EGO-PAGE] Loading ego network person={focus_id} search={search!r}")

    try:
        data = get_ego_network(focus_id, config=config, max_collaborators=max_collaborators)
        elements = data.elements

        if not elements:
            logger.warning("[EGO-PAGE] No elements returned")
            return [], _EGO_LAYOUT, [], hide, {**empty_state_style, "display": "flex"}, False, cap_options, cap_update

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

    except CollaborationDataUnavailable as exc:
        # A clean query with an empty result: the person exists but has no
        # collaborators in this window. This is NOT a settings problem, so it
        # must not go through describe_config_error() — that renders the
        # "check the numbers" text, which was the old, misleading behaviour.
        logger.info(f"[EGO-PAGE] No collaborations: {exc}")
        # banner_style=show so the warning is visible; empty-state stays hidden
        # because its prompt ("pick a person") would be wrong — one is picked.
        return (
            [], _EGO_LAYOUT, [_data_unavailable_banner(focus_id, config)], show, hide,
            False, cap_options, cap_update,
        )

    except ValueError as exc:
        # Genuinely bad settings or a malformed focus id. Those are reported by
        # _ego_config_from_params() above; reaching here means a ValueError the
        # URL check does not cover, so the config sentence is the right one.
        logger.warning(f"[EGO-PAGE] Invalid input: {exc}")
        return [], _EGO_LAYOUT, [_error_banner(describe_config_error(exc))], show, hide, False, cap_options, cap_update

    except Exception as exc:  # pylint: disable=broad-except
        logger.exception(f"[EGO-PAGE] Unexpected error: {exc}")
        return (
            [], _EGO_LAYOUT, [_error_banner("An unexpected error occurred.")],
            show, hide, False, cap_options, cap_update,
        )


# ---------------------------------------------------------------------------
# Deep-link seeding — show the URL's person in the picker
# ---------------------------------------------------------------------------

@callback(
    [Output({"type": "catalog-person-chip", "name": "ego_focus"}, "children", allow_duplicate=True),
     Output({"type": "catalog-person-chip", "name": "ego_focus"}, "style", allow_duplicate=True),
     Output({"type": "catalog-person-search-area", "name": "ego_focus"}, "style", allow_duplicate=True),
     Output({"type": "catalog-person-suggestions", "name": "ego_focus"}, "style", allow_duplicate=True),
     Output({"type": "catalog-person-value", "name": "ego_focus"}, "data", allow_duplicate=True)],
    [Input("url", "search"),
     Input("url", "pathname")],
    State({"type": "catalog-person-value", "name": "ego_focus"}, "data"),
    prevent_initial_call="initial_duplicate",
)
def seed_person_from_url(
    search: str | None,
    pathname: str | None,
    stored_value: str | dict[str, Any] | None,
) -> tuple[Any, ...]:
    """Reflect a deep-linked Person in the picker when nothing is selected yet.

    A URL of ``/app/collaboration/person?person=<wba_id>`` focuses the page on
    that person, but the picker renders from its own store. Without this, a
    deep link would load the right graph while the picker showed an empty
    search box — the graph and the control would disagree about who is
    displayed.

    The store is read as ``State``, never as ``Input``, deliberately. An Input
    would make this callback fire on every pick and clear, and on a clear it
    would observe an empty store while the URL still named a person — seeding
    it straight back and re-loading the network the user just cleared. Reading
    it as State means only a URL change can seed, so clearing stays cleared.
    The rewrite callback below is what keeps the URL in step with the store.

    A value already in the store always wins, which keeps a user's manual pick
    from being overwritten by a stale URL on a later navigation.

    The label falls back to the id segment because a URL carries the canonical
    key only — there is no display name to be had without a lookup.
    """
    if pathname != PERSON_NETWORK_PATH:
        raise PreventUpdate

    if stored_value:
        # Something is already selected (user pick, or an earlier navigation).
        raise PreventUpdate

    person = _deep_linked_person(search)
    if not person:
        raise PreventUpdate

    display = person.split("::", 2)[2] or person
    return (
        build_person_chip("ego_focus", display, person),
        {"display": "flex"},
        {"display": "none"},
        {"display": "none"},
        {"wba": person, "display": display},
    )


# ---------------------------------------------------------------------------
# URL sync — keep the address bar pointing at the displayed person
# ---------------------------------------------------------------------------

@callback(
    Output("url", "search", allow_duplicate=True),
    Input({"type": "catalog-person-value", "name": "ego_focus"}, "data"),
    State("url", "search"),
    State("url", "pathname"),
    prevent_initial_call=True,
)
def sync_person_to_url(
    person_value: str | dict[str, Any] | None,
    search: str | None,
    pathname: str | None,
) -> Any:
    """Mirror the picker's person into the URL, so the address always matches.

    Selecting a person makes the URL shareable and reloadable, and clearing the
    selection removes the parameter rather than leaving a stale focus behind.

    The rendered store may be a plain string (set by the shared picker) or a
    ``{"wba": ...}`` dict (the form the deep-link seeder and the picker's
    round-trip use); both are handled, so the two producers cannot disagree.

    Returns ``no_update`` when the URL already says the right thing. That guard
    matters: without it this callback would fire on its own output, and each
    pass through would re-trigger the loader for the same person.
    """
    if pathname != PERSON_NETWORK_PATH:
        raise PreventUpdate

    if isinstance(person_value, dict):
        wba = str(person_value.get("wba") or "").strip()
    elif isinstance(person_value, str):
        wba = person_value.strip()
    else:
        wba = ""

    updated = search_with_person(search, wba if wba else None)
    if updated is None:
        return no_update
    return updated


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


def _reset_cap(options: list[dict[str, Any]] | None) -> int:
    """Return the cap to select when the filters are cleared.

    The radio only offers caps the fetched element set can honour, so the static
    default is not always a legal choice (fetch 10 collaborators and "Top 25" is
    not on the menu). Selecting a value with no matching option leaves the radio
    rendered with nothing chosen — a dead control. Fall back to the largest
    offered cap, which ``cap_options_for`` guarantees is the fetched ceiling.

    Args:
        options: The radio's current ``options`` prop, or ``None`` before the
                 first load has populated it.

    Returns:
        ``DEFAULT_MAX_COLLABORATORS`` when it is offered, else the largest
        offered value, else the default (when there are no options at all).
    """
    offered = [
        int(option["value"])
        for option in (options or [])
        if isinstance(option, dict) and isinstance(option.get("value"), int)
    ]
    if DEFAULT_MAX_COLLABORATORS in offered:
        return DEFAULT_MAX_COLLABORATORS
    if offered:
        return max(offered)
    return DEFAULT_MAX_COLLABORATORS


@callback(
    [Output("ego-weight-threshold-slider", "value", allow_duplicate=True),
     Output("ego-top-n-cap",               "value", allow_duplicate=True)],
    Input("ego-clear-filters-btn", "n_clicks"),
    State("ego-top-n-cap", "options"),
    prevent_initial_call=True,
)
def clear_ego_filters(
    n_clicks: int | None, options: list[dict[str, Any]] | None
) -> tuple[int, int]:
    """Reset all filter controls to their defaults."""
    return 0, _reset_cap(options)


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

# Raise the overlay before the fetch starts — load_ego_network() runs
# synchronously, so a True it wrote would never paint ahead of the wait. Only a
# picked person counts, matching the condition it fetches under.
# "initial_duplicate" (not True) so a deep-linked picker still raises it.
clientside_callback(
    """
    function(personValue) {
        var wba = "";
        if (personValue && typeof personValue === "object") {
            wba = String(personValue.wba || "").trim();
        } else if (typeof personValue === "string") {
            wba = personValue.trim();
        }
        return wba !== "";
    }
    """,
    Output("ego-loading-state", "data", allow_duplicate=True),
    Input({"type": "catalog-person-value", "name": "ego_focus"}, "data"),
    prevent_initial_call="initial_duplicate",
)

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

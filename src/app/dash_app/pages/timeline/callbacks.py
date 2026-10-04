"""Dash callbacks for the Activity Timeline page.

UI-1 wires the entity selector: a debounced typeahead backed by
``GET /api/v1/activity/suggest``, an idempotent selection store, a lane-header
row, and the soft lane cap. Fetching, bucketing, and card rendering land in
UI-2 onwards.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

from dash import (
    ALL,
    Input,
    Output,
    State,
    callback,
    callback_context as ctx,
    clientside_callback,
    html,
    no_update,
)
from dash.exceptions import PreventUpdate

from app.common.timezone import get_app_timezone
from app.dash_app.components.common import create_alert, register_loading_overlay_hider
from app.dash_app.pages.graph.utils import fetch_effective_theme
from app.dash_app.pages.timeline.api import (
    TimelineFetchError,
    fetch_suggestions,
    fetch_timeline,
)
from app.dash_app.pages.timeline.helpers import (
    MIN_QUERY_LENGTH,
    add_selection,
    assign_lane_colors,
    build_grid,
    entity_type_icon,
    entity_type_label,
    extract_mock_scenario,
    extract_scope,
    is_full,
    remove_selection,
)
from app.dash_app.pages.timeline.layout import (
    CLEAR_ALL_HIDDEN_STYLE,
    CLEAR_ALL_STYLE,
    GRID_SCROLL_HIDDEN_STYLE,
    GRID_SCROLL_STYLE,
    build_grid_body,
    build_header_axis_cell,
    build_lane_header,
    grid_inner_style,
)
from app.dash_app.styles import (
    COLOR_BACKGROUND_WHITE,
    COLOR_BORDER,
    COLOR_CHARCOAL_MEDIUM,
    COLOR_GRAY_MEDIUM,
    FONT_SANS,
    FONT_SIZE_MEDIUM,
    FONT_SIZE_SMALL,
    FONT_SIZE_XTINY,
    get_theme_tokens,
)
from common.logger import logger

_SUGGESTION_LIMIT = 10
_FALLBACK_THEME = "executive-light"
_MAX_LANE_HINT = "🔒 Maximum 5 lanes — remove one first"

_SUGGESTIONS_VISIBLE_STYLE: dict[str, Any] = {
    "position": "absolute",
    "top": "100%",
    "left": "0",
    "zIndex": 1000,
    "width": "320px",
    "marginTop": "4px",
    "backgroundColor": COLOR_BACKGROUND_WHITE,
    "border": f"1px solid {COLOR_BORDER}",
    "borderRadius": "2px",
    "boxShadow": "0 4px 12px rgba(0,0,0,0.15)",
    "maxHeight": "320px",
    "overflowY": "auto",
}

_SUGGESTIONS_HIDDEN_STYLE: dict[str, Any] = {
    **_SUGGESTIONS_VISIBLE_STYLE,
    "display": "none",
}

_SUGGESTION_ROW_STYLE: dict[str, Any] = {
    "display": "flex",
    "alignItems": "center",
    "gap": "8px",
    "width": "100%",
    "padding": "6px 10px",
    "backgroundColor": "transparent",
    "border": "none",
    "borderBottom": f"1px solid {COLOR_BORDER}",
    "cursor": "pointer",
    "textAlign": "left",
}

_SUGGESTION_LABEL_STYLE: dict[str, Any] = {
    "fontFamily": FONT_SANS,
    "fontSize": FONT_SIZE_MEDIUM,
    "color": COLOR_CHARCOAL_MEDIUM,
    "flex": "1 1 auto",
    "whiteSpace": "nowrap",
    "overflow": "hidden",
    "textOverflow": "ellipsis",
}

_SUGGESTION_TAG_STYLE: dict[str, Any] = {
    "fontFamily": FONT_SANS,
    "fontSize": FONT_SIZE_XTINY,
    "color": COLOR_GRAY_MEDIUM,
    "textTransform": "uppercase",
    "letterSpacing": "0.5px",
    "flex": "0 0 auto",
}

_SUGGESTION_SOURCE_STYLE: dict[str, Any] = {
    "fontFamily": FONT_SANS,
    "fontSize": FONT_SIZE_XTINY,
    "color": COLOR_GRAY_MEDIUM,
    "flex": "0 0 auto",
}

_SUGGESTION_ICON_STYLE: dict[str, Any] = {
    "width": "20px",
    "textAlign": "center",
    "color": COLOR_GRAY_MEDIUM,
    "flex": "0 0 auto",
}

_SUGGESTION_AVATAR_STYLE: dict[str, Any] = {
    "width": "20px",
    "height": "20px",
    "borderRadius": "50%",
    "objectFit": "cover",
    "flex": "0 0 auto",
}

_NO_MATCH_STYLE: dict[str, Any] = {
    "fontFamily": FONT_SANS,
    "fontSize": FONT_SIZE_SMALL,
    "color": COLOR_GRAY_MEDIUM,
    "padding": "8px 10px",
}

# ---------------------------------------------------------------------------
# Clientside debounce: raw input value → debounced store (~300 ms)
# ---------------------------------------------------------------------------

clientside_callback(
    """
    function(value) {
        if (window._timelineSuggestTimer) {
            clearTimeout(window._timelineSuggestTimer);
        }
        return new Promise(function(resolve) {
            window._timelineSuggestTimer = setTimeout(function() {
                resolve(value !== undefined ? value : '');
            }, 300);
        });
    }
    """,
    Output("timeline-search-debounced", "data"),
    Input("timeline-search-input", "value"),
    prevent_initial_call=True,
)


# ---------------------------------------------------------------------------
# Keyboard navigation over the typeahead suggestions (install-once listener)
# ---------------------------------------------------------------------------
# Dash cannot bind a callback to a DOM key event, so install a single delegated
# ``keydown`` listener on ``document`` and drive the already-rendered suggestion
# buttons imperatively.
#
# Correctness notes:
# * The active row is tracked by **element reference**, not by index. The
#   debounced suggestions re-render replaces the DOM nodes (React), which would
#   otherwise leave a stale index pointing at whatever now sits in that slot —
#   the cause of "the wrong item gets selected".
# * A ``MutationObserver`` on the suggestions container clears the active row
#   whenever the list re-renders, so Enter can never act on a detached node.
# * ``Enter`` clicks the tracked element (or the first row when nothing is
#   highlighted). It never goes through the input's ``n_submit``, so there is a
#   single, deterministic trigger and no first-item race.
# * The highlight uses a theme CSS variable — never a hardcoded colour.
clientside_callback(
    """
    function(_headers) {
        if (!window.__timelineSuggestWired) {
            window.__timelineSuggestWired = true;
            window.__timelineSuggestActiveEl = null;
            window.__timelineSuggestIndex = -1;

            window.__timelineSuggestItems = function() {
                var box = document.getElementById('timeline-suggestions');
                // ``getClientRects`` is empty while the dropdown is hidden
                // (display:none), so a dismissed list reports no rows.
                if (!box || box.getClientRects().length === 0) { return []; }
                return Array.prototype.slice.call(box.querySelectorAll('button'));
            };
            window.__timelineSuggestClear = function() {
                var el = window.__timelineSuggestActiveEl;
                if (el && el.isConnected) {
                    el.style.backgroundColor = 'transparent';
                }
                window.__timelineSuggestActiveEl = null;
                window.__timelineSuggestIndex = -1;
            };
            window.__timelineSuggestSetActive = function(rows, idx) {
                window.__timelineSuggestClear();
                if (idx >= 0 && idx < rows.length) {
                    rows[idx].style.backgroundColor = 'var(--color-surface-active)';
                    rows[idx].scrollIntoView({block: 'nearest'});
                    window.__timelineSuggestActiveEl = rows[idx];
                    window.__timelineSuggestIndex = idx;
                }
            };

            document.addEventListener('keydown', function(ev) {
                var input = document.getElementById('timeline-search-input');
                if (!input || document.activeElement !== input) { return; }
                var rows = window.__timelineSuggestItems();
                if (!rows.length) { return; }

                if (ev.key === 'ArrowDown') {
                    ev.preventDefault();
                    var next = window.__timelineSuggestIndex < 0
                        ? 0
                        : Math.min(window.__timelineSuggestIndex + 1, rows.length - 1);
                    window.__timelineSuggestSetActive(rows, next);
                } else if (ev.key === 'ArrowUp') {
                    ev.preventDefault();
                    var prev = window.__timelineSuggestIndex < 0
                        ? rows.length - 1
                        : Math.max(window.__timelineSuggestIndex - 1, 0);
                    window.__timelineSuggestSetActive(rows, prev);
                } else if (ev.key === 'Enter') {
                    var target = window.__timelineSuggestActiveEl;
                    if (!target || !target.isConnected) { target = rows[0]; }
                    if (target) {
                        ev.preventDefault();
                        ev.stopPropagation();
                        target.click();
                        window.__timelineSuggestClear();
                    }
                } else if (ev.key === 'Escape') {
                    // Dismiss the dropdown and wipe the search text.
                    ev.preventDefault();
                    window.__timelineSuggestClear();
                    if (window.dash_clientside && window.dash_clientside.set_props) {
                        window.dash_clientside.set_props('timeline-search-input', {value: ''});
                        window.dash_clientside.set_props('timeline-suggestions', {
                            children: [],
                            style: {display: 'none'}
                        });
                    }
                } else {
                    window.__timelineSuggestClear();
                }
            }, true);
        }

        // (Re)bind the observer to the current container. The layout can be
        // re-mounted on navigation, producing a new container element.
        var box = document.getElementById('timeline-suggestions');
        if (box && window.__timelineSuggestObservedBox !== box) {
            if (window.__timelineSuggestObserver) {
                window.__timelineSuggestObserver.disconnect();
            }
            window.__timelineSuggestObserver = new MutationObserver(function() {
                window.__timelineSuggestClear();
            });
            window.__timelineSuggestObserver.observe(box, {
                childList: true,
                subtree: true,
                attributes: true,
                attributeFilter: ['id']
            });
            window.__timelineSuggestObservedBox = box;
        }

        return window.dash_clientside.no_update;
    }
    """,
    Output("timeline-keyboard-dummy", "children"),
    Input("timeline-lane-headers", "children"),
)


# ---------------------------------------------------------------------------
# Typeahead suggestions
# ---------------------------------------------------------------------------


def _suggestion_row(item: dict[str, Any]) -> html.Button:
    """Render one clickable suggestion row."""
    entity_type = item.get("entity_type") or ""
    label = item.get("label") or item.get("wba_id") or ""
    source = item.get("source") or ""
    avatar_url = item.get("avatar_url")

    if avatar_url:
        media: Any = html.Img(src=avatar_url, style=_SUGGESTION_AVATAR_STYLE)
    else:
        media = html.I(className=entity_type_icon(entity_type), style=_SUGGESTION_ICON_STYLE)

    return html.Button(
        [
            media,
            html.Span(label, style=_SUGGESTION_LABEL_STYLE),
            html.Span(entity_type_label(entity_type), style=_SUGGESTION_TAG_STYLE),
            html.Span(source, style=_SUGGESTION_SOURCE_STYLE),
        ],
        id={"type": "timeline-suggestion", "index": item.get("wba_id")},
        n_clicks=0,
        style=_SUGGESTION_ROW_STYLE,
    )


@callback(
    Output("timeline-suggestions", "children"),
    Output("timeline-suggestions", "style"),
    Output("timeline-suggestions-store", "data"),
    Input("timeline-search-debounced", "data"),
)
def render_suggestions(
    query: str | None,
) -> tuple[Any, dict[str, Any], list[dict[str, Any]]]:
    """Fetch and render typeahead suggestions for the debounced query."""
    term = (query or "").strip()
    if len(term) < MIN_QUERY_LENGTH:
        return [], _SUGGESTIONS_HIDDEN_STYLE, []

    results = fetch_suggestions(term, limit=_SUGGESTION_LIMIT)
    if not results:
        return (
            [html.Div("No matches", style=_NO_MATCH_STYLE)],
            _SUGGESTIONS_VISIBLE_STYLE,
            [],
        )
    return [_suggestion_row(item) for item in results], _SUGGESTIONS_VISIBLE_STYLE, results


# ---------------------------------------------------------------------------
# Selection mutations (add / remove / clear)
# ---------------------------------------------------------------------------


def _find_suggestion(
    suggestions: list[dict[str, Any]], wba_id: str | None
) -> dict[str, Any] | None:
    """Return the suggestion matching ``wba_id``, if present."""
    for item in suggestions:
        if item.get("wba_id") == wba_id:
            return item
    return None


def _first_changed_trigger() -> Any:
    """Return the parsed id of the first input whose value actually changed.

    Dash can batch several changed inputs into one invocation, and
    ``ctx.triggered_id`` only reflects the first entry of ``ctx.triggered``.
    Filtering to entries with a truthy value (and parsing pattern-matching
    component ids) makes the selection deterministic regardless of batching
    order or re-render churn from freshly-mounted components.
    """
    changed = [entry for entry in ctx.triggered if entry.get("value")]
    if not changed:
        raise PreventUpdate
    prop_id = str(changed[0].get("prop_id", ""))
    id_part = prop_id.rsplit(".", 1)[0]
    try:
        return json.loads(id_part)
    except (ValueError, TypeError):
        return id_part


@callback(
    Output("timeline-selected-store", "data"),
    Output("timeline-search-input", "value"),
    Input({"type": "timeline-suggestion", "index": ALL}, "n_clicks"),
    Input({"type": "timeline-lane-remove", "index": ALL}, "n_clicks"),
    Input("timeline-clear-all", "n_clicks"),
    State("timeline-selected-store", "data"),
    State("timeline-suggestions-store", "data"),
    prevent_initial_call=True,
)
def update_selection(
    _suggestion_clicks: list[Any],
    _remove_clicks: list[Any],
    _clear_clicks: Any,
    selection: list[dict[str, Any]] | None,
    suggestions: list[dict[str, Any]] | None,
) -> tuple[Any, Any]:
    """Handle add (suggestion click / Enter), remove (✕), and clear-all.

    Every add/remove routes through an explicit clicked component id — the
    input's own ``n_submit`` is deliberately not a trigger, so Enter has a
    single deterministic path (the clientside handler clicks a specific row).
    """
    triggered = _first_changed_trigger()

    current = selection or []
    pool = suggestions or []

    if isinstance(triggered, dict):
        kind = triggered.get("type")
        wba_id = triggered.get("index")
        if kind == "timeline-suggestion":
            item = _find_suggestion(pool, wba_id)
            if item is None:
                raise PreventUpdate
            return add_selection(current, item), ""
        if kind == "timeline-lane-remove":
            return remove_selection(current, wba_id), no_update

    if triggered == "timeline-clear-all":
        return [], no_update

    raise PreventUpdate


# ---------------------------------------------------------------------------
# Lane headers / empty state / cap hint
# ---------------------------------------------------------------------------


@callback(
    Output("timeline-lane-headers", "children"),
    Output("timeline-empty-state", "style"),
    Output("timeline-lane-hint", "children"),
    Output("timeline-search-input", "disabled"),
    Output("timeline-clear-all", "style"),
    Output("timeline-grid-scroll", "style"),
    Output("timeline-grid-inner", "style"),
    Input("timeline-selected-store", "data"),
    Input("theme-store", "data"),
)
def render_lanes(
    selection: list[dict[str, Any]] | None,
    theme_name: str | None,
) -> tuple[Any, dict[str, Any], str, bool, dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Render lane headers (inside the grid), empty state, cap hint, clear-all,
    and the grid's visibility + column template."""
    current = selection or []
    tokens = get_theme_tokens(theme_name or _FALLBACK_THEME)
    lane_keys = assign_lane_colors(len(current))

    children: list[Any] = [build_header_axis_cell()]
    for item, token_key in zip(current, lane_keys):
        color = tokens[token_key]
        children.append(build_lane_header(item, color))

    full = is_full(current)
    return (
        children,
        {"display": "none"} if current else {},
        _MAX_LANE_HINT if full else "",
        full,
        CLEAR_ALL_STYLE if current else CLEAR_ALL_HIDDEN_STYLE,
        GRID_SCROLL_STYLE if current else GRID_SCROLL_HIDDEN_STYLE,
        grid_inner_style(len(current)),
    )


# ---------------------------------------------------------------------------
# Timeline fetch & grid render (UI-2)
# ---------------------------------------------------------------------------

_DEFAULT_RANGE_DAYS = 30
_DEFAULT_LIMIT = 20

# Flip the loading overlay on as soon as a fetch is about to start; the server
# callback below flips it back to False when the request completes.
clientside_callback(
    """
    function(_selection, _search) {
        return true;
    }
    """,
    Output("timeline-loading-store", "data", allow_duplicate=True),
    Input("timeline-selected-store", "data"),
    Input("url", "search"),
    prevent_initial_call=True,
)

register_loading_overlay_hider("timeline-loading-store", "timeline-grid-overlay")


@callback(
    Output("timeline-data-store", "data"),
    Output("timeline-alert-slot", "children"),
    Output("timeline-loading-store", "data"),
    Input("timeline-selected-store", "data"),
    Input("url", "search"),
)
def load_timeline(
    selection: list[dict[str, Any]] | None,
    search: str | None,
) -> tuple[Any, Any, bool]:
    """Fetch events for the selected lanes into the data store.

    Rendering is done separately in :func:`render_grid`, so a theme toggle does
    not refetch. On error the stored data is left untouched (``no_update``) and a
    persistent danger alert is shown, preserving the last good render. The
    ``mock`` query param (dev-only) is forwarded so ``?mock=<scenario>`` switches
    scenarios without a restart.
    """
    current = selection or []
    if not current:
        return None, [], False

    to_dt = datetime.now(timezone.utc)
    from_dt = to_dt - timedelta(days=_DEFAULT_RANGE_DAYS)
    mock = extract_mock_scenario(search)
    scope = extract_scope(search)

    try:
        payload = fetch_timeline(
            wba_ids=[str(item.get("wba_id")) for item in current],
            scope=scope,
            from_iso=from_dt.isoformat(),
            to_iso=to_dt.isoformat(),
            limit=_DEFAULT_LIMIT,
            mock=mock,
        )
    except TimelineFetchError as exc:
        logger.warning(f"[Timeline] timeline fetch failed: {exc}")
        alert = create_alert(
            f"Could not load timeline data: {exc}", color="danger", dismissable=True
        )
        return no_update, [alert], False

    data = {
        "lanes": payload.get("lanes") or [],
        "params": {
            "scope": scope,
            "from": from_dt.isoformat(),
            "to": to_dt.isoformat(),
            "limit": _DEFAULT_LIMIT,
        },
        "time_range": (payload.get("meta") or {}).get("time_range") or {},
    }
    return data, [], False


@callback(
    Output("timeline-theme-store", "data"),
    Input("theme-store", "data"),
)
def populate_timeline_theme_store(
    theme_name: str | None,
) -> dict[str, Any] | None:
    """Fetch the effective graph theme (base tokens ⊕ Graph-Styling overrides)."""
    return fetch_effective_theme(theme_name or _FALLBACK_THEME)


@callback(
    Output("timeline-grid-body", "children"),
    Input("timeline-data-store", "data"),
    Input("timeline-selected-store", "data"),
    Input("theme-store", "data"),
    Input("timeline-theme-store", "data"),
)
def render_grid(
    data: dict[str, Any] | None,
    selection: list[dict[str, Any]] | None,
    theme_name: str | None,
    effective_theme: dict[str, Any] | None,
) -> list[Any]:
    """Render the period grid from stored data.

    Resolves lane-accent colours from the active theme and entity-type colours
    from the effective theme (``effective_theme["nodes"][<Type>]["background-color"]``),
    falling back to the base token. One cell per *selected* lane keeps the body
    aligned with the sticky header row even if the API reordered a lane.
    """
    current = selection or []
    if not data or not current:
        return []

    lanes = data.get("lanes") or []
    tokens = get_theme_tokens(theme_name or _FALLBACK_THEME)
    lane_keys = assign_lane_colors(len(current))
    lane_colors = {
        str(item.get("wba_id") or ""): tokens[token_key]
        for item, token_key in zip(current, lane_keys)
    }
    effective_nodes = (
        effective_theme.get("nodes") if isinstance(effective_theme, dict) else None
    )
    rows = build_grid(lanes, "day", get_app_timezone())
    return build_grid_body(rows, current, lane_colors, effective_nodes, tokens)


# ---------------------------------------------------------------------------
# Hover popup (UI-4) — install-once delegated listeners driving the portal
# ---------------------------------------------------------------------------
# Dash cannot bind a callback to a DOM event, so install one delegated set of
# listeners on ``document`` and drive the portal div imperatively. The portal
# lives at the page root (outside the scrolling grid) so it is never clipped.
# Contents are built with ``createElement``/``textContent`` — never ``innerHTML``
# — because summary/label/url come from ingested source data.
clientside_callback(
    """
    function(_body) {
        if (!window.__timelinePopupWired) {
            window.__timelinePopupWired = true;
            window.__timelinePopupCard = null;

            function make(tag, className, text) {
                var el = document.createElement(tag);
                if (className) { el.className = className; }
                if (text !== undefined && text !== null) { el.textContent = String(text); }
                return el;
            }

            function build(data) {
                var frag = document.createDocumentFragment();
                frag.appendChild(make('div', 'timeline-popup-summary', data.summary || ''));
                var meta = [data.entity_type, data.relationship, data.source]
                    .filter(Boolean).join(' \\u00b7 ');
                if (meta) { frag.appendChild(make('div', 'timeline-popup-meta', meta)); }
                if (data.datetime) {
                    frag.appendChild(make('div', 'timeline-popup-time', data.datetime));
                }
                if (data.url) {
                    var link = document.createElement('a');
                    link.href = data.url;
                    link.target = '_blank';
                    link.rel = 'noopener noreferrer';
                    link.className = 'timeline-popup-link';
                    link.textContent = 'Open source \\u2197';
                    frag.appendChild(link);
                }
                return frag;
            }

            window.__timelinePopupHide = function() {
                clearTimeout(window.__timelinePopupTimer);
                var portal = document.getElementById('timeline-popup-portal');
                if (portal) { portal.style.display = 'none'; }
                if (window.__timelinePopupCard) {
                    window.__timelinePopupCard.removeAttribute('aria-describedby');
                    window.__timelinePopupCard = null;
                }
            };
            // Grace period: leaving a card does not hide immediately, so the
            // pointer can travel into the popup to click "Open source".
            window.__timelinePopupHideSoon = function() {
                clearTimeout(window.__timelinePopupTimer);
                window.__timelinePopupTimer = setTimeout(
                    window.__timelinePopupHide, 140
                );
            };

            window.__timelinePopupShow = function(card) {
                var portal = document.getElementById('timeline-popup-portal');
                if (!portal) { return; }
                var raw = card.getAttribute('data-timeline-event');
                if (!raw) { return; }
                var data;
                try { data = JSON.parse(raw); } catch (e) { return; }

                clearTimeout(window.__timelinePopupTimer);
                portal.replaceChildren(build(data));
                portal.style.display = 'block';
                portal.style.visibility = 'hidden';
                var rect = card.getBoundingClientRect();
                var pw = portal.offsetWidth;
                var ph = portal.offsetHeight;
                // Place to the SIDE, top-aligned with the card, so reaching the
                // popup never crosses the next card lower in the same column
                // (which would steal the hover and re-open a different popup).
                var left = rect.right + 8;
                if (left + pw > window.innerWidth - 8) {
                    left = rect.left - pw - 8;
                }
                if (left < 8) { left = 8; }
                var top = rect.top + 6;  // slightly below the row's top edge
                if (top + ph > window.innerHeight - 8) {
                    top = window.innerHeight - ph - 8;
                }
                if (top < 8) { top = 8; }
                portal.style.left = left + 'px';
                portal.style.top = top + 'px';
                portal.style.visibility = 'visible';

                if (window.__timelinePopupCard && window.__timelinePopupCard !== card) {
                    window.__timelinePopupCard.removeAttribute('aria-describedby');
                }
                card.setAttribute('aria-describedby', 'timeline-popup-portal');
                window.__timelinePopupCard = card;
            };

            function cardFrom(target) {
                return target && target.closest
                    ? target.closest('[data-timeline-event]')
                    : null;
            }

            document.addEventListener('mouseover', function(ev) {
                var card = cardFrom(ev.target);
                if (card) { clearTimeout(window.__timelinePopupTimer); }
                if (card && card !== window.__timelinePopupCard) {
                    window.__timelinePopupShow(card);
                }
            });
            document.addEventListener('focusin', function(ev) {
                var card = cardFrom(ev.target);
                if (card) { window.__timelinePopupShow(card); }
            });
            document.addEventListener('mouseout', function(ev) {
                var card = cardFrom(ev.target);
                if (!card) { return; }
                var portal = document.getElementById('timeline-popup-portal');
                if (ev.relatedTarget && portal && portal.contains(ev.relatedTarget)) {
                    return;
                }
                window.__timelinePopupHideSoon();
            });
            document.addEventListener('focusout', function(ev) {
                if (!cardFrom(ev.target)) { return; }
                setTimeout(function() {
                    var portal = document.getElementById('timeline-popup-portal');
                    if (!portal || !portal.contains(document.activeElement)) {
                        window.__timelinePopupHide();
                    }
                }, 0);
            });
            document.addEventListener('keydown', function(ev) {
                if (ev.key === 'Escape') { window.__timelinePopupHide(); }
            }, true);
            document.addEventListener('scroll', window.__timelinePopupHide, true);
            window.addEventListener('resize', window.__timelinePopupHide);
        }

        // Rebind the portal's own listener after a navigation re-mounts it.
        var portal = document.getElementById('timeline-popup-portal');
        if (portal && window.__timelinePopupBoundPortal !== portal) {
            portal.addEventListener('mouseenter', function() {
                clearTimeout(window.__timelinePopupTimer);
            });
            portal.addEventListener('mouseleave', window.__timelinePopupHide);
            window.__timelinePopupBoundPortal = portal;
        }
        return window.dash_clientside.no_update;
    }
    """,
    Output("timeline-popup-dummy", "children"),
    Input("timeline-grid-body", "children"),
)

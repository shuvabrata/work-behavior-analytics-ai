"""
Common Reusable Components for Executive Dashboard

This module provides factory functions for creating consistent UI components
across all pages of the Work Behavior Analytics AI application.

Usage:
    from app.dash_app.components.common import create_page_header, create_feature_card
    
    layout = html.Div([
        create_page_header([("Settings", "/app/settings"), ("Graph Styling", None)],
                           "Customize graph colors, shapes, sizes, and node appearance."),
        create_feature_card("Feature Title", "Feature description...")
    ])
"""

from collections.abc import Set as AbstractSet
from typing import Any

import itertools
import re
from datetime import datetime
from dash import html, dcc
import dash_bootstrap_components as dbc
from domain.collaboration.config import LAYER_LABELS, SETTING_LABELS
from app.common.timezone import humanize_duration, to_app_timezone
from app.settings import settings

from app.dash_app.styles import (
    # Style patterns
    COMPACT_PAGE_HEADER_STYLE,
    CARD_CONTAINER_STYLE,
    FEATURE_CARD_STYLE,
    FEATURE_CARD_TITLE_STYLE,
    FEATURE_CARD_DESCRIPTION_STYLE,
    PLACEHOLDER_ICON_STYLE,
    PLACEHOLDER_MESSAGE_STYLE,
    # Details panel
    DETAILS_PANEL_HEADER_STYLE,
    DETAILS_PANEL_SUBTYPE_STYLE,
    DETAILS_TABLE_STYLE,
    DETAILS_TABLE_KEY_STYLE,
    DETAILS_TABLE_VALUE_STYLE,
    DETAILS_TABLE_VALUE_MONO_STYLE,
    DETAILS_TABLE_LINK_STYLE,
    DETAILS_MUTED_TEXT_STYLE,
    # Colors
    COLOR_NAVY,
    COLOR_CHARCOAL_MEDIUM,
    COLOR_GRAY_MEDIUM,
    COLOR_BORDER,
    COLOR_GRAY_DARK,
    COLOR_GRAY_LIGHTER,
    # Typography
    FONT_SANS,
    FONT_SIZE_XSMALL,
    FONT_SIZE_XTINY,
    FONT_WEIGHT_SEMIBOLD,
    # Spacing
    SPACING_XSMALL,
    SPACING_SMALL,
    SPACING_MEDIUM,
    SPACING_XXSMALL
)


def create_page_header(
    breadcrumb: list[tuple[str, str | None]],
    description: str | None = None,
    trailing: Any = None,
) -> html.Div:
    """
    Create a compact single-row page header with Executive Dashboard styling.

    Renders a breadcrumb trail followed by an optional description, all on one
    row above a full-width divider line. Breadcrumb segments with an ``href``
    are rendered as clickable links (navy); segments with ``None`` are rendered
    as non-clickable current-page text (charcoal). The description, when given,
    is appended after a ``|`` separator in muted gray sentence-case text.

    Args:
        breadcrumb: Ordered list of ``(label, href)`` segments. ``href=None``
            renders the segment as non-clickable current-page text.
        description: Optional description text shown after the ``|`` separator.
        trailing: Optional component rendered after the description, for a
            page-level control that belongs in the header rather than in the
            content column below it (the per-person page's person picker).
            Wrapped in a div that resets ``textTransform`` and ``letterSpacing``,
            both of which are inherited from ``COMPACT_PAGE_HEADER_STYLE`` and
            would otherwise render the control's text in ALL CAPS at 0.8px
            tracking. Also allowed to shrink and wrap, so a wide control
            degrades by wrapping rather than overflowing the row.

    Returns:
        html.Div: A styled compact page header component.

    Example:
        create_page_header(
            [("Settings", "/app/settings"), ("Graph Styling", None)],
            "Customize graph colors, shapes, sizes, and node appearance.",
        )
    """
    link_style = {
        "color": COLOR_NAVY,
        "textDecoration": "none",
    }
    current_style = {
        "color": COLOR_CHARCOAL_MEDIUM,
    }
    separator_style = {
        "color": COLOR_GRAY_MEDIUM,
        "margin": f"0 {SPACING_XSMALL}",
    }

    children: list[Any] = []
    for index, (label, href) in enumerate(breadcrumb):
        if index > 0:
            children.append(html.Span(" / ", style=separator_style))
        if href:
            children.append(dcc.Link(label, href=href, style=link_style))
        else:
            children.append(html.Span(label, style=current_style))

    if description:
        if breadcrumb:
            children.append(html.Span(" | ", style=separator_style))
        children.append(
            html.Span(
                description,
                style={
                    "color": COLOR_GRAY_MEDIUM,
                    "textTransform": "none",
                    "letterSpacing": "normal",
                    "minWidth": 0,
                },
            )
        )

    header_style = dict(COMPACT_PAGE_HEADER_STYLE)
    if trailing is not None:
        header_style["flexWrap"] = "wrap"
        children.append(
            html.Div(
                trailing,
                style={
                    # Both are inherited from COMPACT_PAGE_HEADER_STYLE; without
                    # these the control's text renders ALL CAPS with 0.8px tracking.
                    "textTransform": "none",
                    "letterSpacing": "normal",
                    "flex": "0 1 auto",
                    "minWidth": 0,
                },
            )
        )

    return html.Div(children, style=header_style)


def create_alert(
    content: Any,
    color: str = "info",
    class_name: str = "mb-2",
    dismissable: bool = True,
    duration: int | None = None,
    style: dict[str, Any] | None = None,
) -> dbc.Alert:
    """Create a standardized alert with consistent typography and behavior."""
    merged_style = {
        "fontFamily": FONT_SANS,
        "fontSize": FONT_SIZE_XSMALL,
        **(style or {}),
    }
    kwargs = {
        "color": color,
        "className": class_name,
        "dismissable": dismissable,
        "style": merged_style,
    }
    if duration is not None:
        kwargs["duration"] = duration
    return dbc.Alert(content, **kwargs)


_CONFIG_ERROR_GENERIC = (
    "One of the settings in the link is not a valid value. "
    "Please check the numbers and try again."
)

_LAYER_IN_MESSAGE = re.compile(r"layer '([^']+)'")


def _format_bound(value: Any) -> str:
    """Render a pydantic bound readably, without a trailing ``.0`` on floats."""
    try:
        return f"{float(value):g}"
    except (TypeError, ValueError):
        return str(value)


def _describe_one_error(error: dict[str, Any]) -> str | None:
    """Turn one pydantic error dict into a plain-English sentence, or None."""
    ctx = error.get("ctx") or {}
    if error.get("type") == "value_error":
        # The weights validator reports the whole ``weights`` dict as its loc, so
        # the offending layer is only named inside the validator's own message.
        match = _LAYER_IN_MESSAGE.search(str(ctx.get("error", "")))
        if match is None:
            return None
        layer = match.group(1)
        return f"{LAYER_LABELS.get(layer, layer)} weight cannot be negative."

    loc = error.get("loc") or ()
    if not loc:
        return None
    field = str(loc[-1])
    label = SETTING_LABELS.get(field, field.replace("_", " ").capitalize())

    lower = ctx.get("ge")
    upper = ctx.get("le")
    if lower is not None and upper is not None:
        return f"{label} must be between {_format_bound(lower)} and {_format_bound(upper)}."
    if upper is not None:
        return f"{label} must be at most {_format_bound(upper)}."
    if lower is not None:
        return f"{label} must be at least {_format_bound(lower)}."
    return None


def describe_config_error(exc: Exception) -> str:
    """Turn a CollaborationNetworkConfig ValidationError into a readable sentence.

    Pydantic's own text names the field path and links to its documentation,
    which is not something to show someone who typed a number into a box. The
    field bounds live on the model, so the range is recovered from the error
    itself rather than duplicated here.

    An exception without ``errors()`` (``from_query_values`` raises a plain
    ``ValueError`` for a non-numeric value) yields a generic sentence, never a
    traceback and never raw pydantic output.
    """
    errors_method = getattr(exc, "errors", None)
    if not callable(errors_method):
        return _CONFIG_ERROR_GENERIC
    try:
        errors = errors_method()
    except Exception:  # pylint: disable=broad-except
        return _CONFIG_ERROR_GENERIC

    messages: list[str] = []
    for error in errors or []:
        message = _describe_one_error(error)
        if message and message not in messages:
            messages.append(message)
    return " ".join(messages) if messages else _CONFIG_ERROR_GENERIC


def create_feature_card(title: str, description: str) -> html.Div:
    """
    Create a feature card with title and description.
    
    Args:
        title: The feature title
        description: The feature description text
        
    Returns:
        html.Div: A styled feature card component
        
    Example:
        create_feature_card(
            "Personnel Profiles",
            "Detailed team member information, roles, and expertise areas"
        )
    """
    return html.Div([
        html.Div(title, style=FEATURE_CARD_TITLE_STYLE),
        html.Div(description, style=FEATURE_CARD_DESCRIPTION_STYLE)
    ], style=FEATURE_CARD_STYLE)


def create_placeholder_section(message: str, features: list[Any], icon: str = "📋") -> html.Div:
    """
    Create a placeholder section with icon, message, and feature cards.
    
    Args:
        message: The placeholder message to display
        features: List of (title, description) tuples for feature cards
        icon: Optional icon to display (default: "📋")
        
    Returns:
        html.Div: A complete placeholder section
        
    Example:
        create_placeholder_section(
            message="Team directory integration pending",
            features=[
                ("Personnel Profiles", "Detailed team member information..."),
                ("Contact Directory", "Email addresses and communication...")
            ]
        )
    """
    # Create feature cards in a 2-column grid
    feature_cols = []
    for title, description in features:
        feature_cols.append(
            dbc.Col([
                create_feature_card(title, description)
            ], md=6)
        )
    
    return html.Div([
        # Icon
        html.Div(icon, style=PLACEHOLDER_ICON_STYLE),
        
        # Message
        html.Div(message, style=PLACEHOLDER_MESSAGE_STYLE),
        
        # Feature cards
        html.Div([
            dbc.Row(feature_cols)
        ], style=CARD_CONTAINER_STYLE)
    ])


def create_diamond_icon(color: str | None = None) -> html.Span:
    """
    Create a diamond icon (◆) for visual accents.
    
    Args:
        color: The color of the diamond (default: theme accent)
        
    Returns:
        html.Span: A styled diamond icon
        
    Example:
        create_diamond_icon()
        create_diamond_icon(COLOR_GRAY_MEDIUM)
    """
    resolved_color = color or COLOR_NAVY

    return html.Span(
        "◆",
        style={
            "color": resolved_color,
            "fontSize": FONT_SIZE_XSMALL,
            "marginRight": SPACING_XXSMALL
        }
    )


def create_empty_state(message: str, icon: str = "📭") -> html.Div:
    """
    Create an empty state display for when there's no data.
    
    Args:
        message: The message to display
        icon: Optional icon to display (default: "📭")
        
    Returns:
        html.Div: A styled empty state component
        
    Example:
        create_empty_state("No messages yet. Start a conversation!")
    """
    return html.Div([
        html.Div(icon, style=PLACEHOLDER_ICON_STYLE),
        html.Div(message, style=PLACEHOLDER_MESSAGE_STYLE)
    ], style={
        "padding": SPACING_MEDIUM,
        "textAlign": "center"
    })


# ---------------------------------------------------------------------------
# Shared graph visualization helpers
# ---------------------------------------------------------------------------

def toggle_details_panel(is_fullwidth: bool) -> tuple[Any, ...]:
    """Return (canvas_col_width, right_panel_style) for fullwidth toggle.

    Used by both the graph page and future visualization pages.

    Args:
        is_fullwidth: True when the canvas should expand to full width.

    Returns:
        (int, dict) — Dash column width for the canvas col and a style dict
        for the right-hand details/filter column (empty dict = visible,
        ``{"display": "none"}`` = hidden).
    """
    if is_fullwidth:
        return 12, {"display": "none"}
    return 8, {}


def register_fullwidth_callback(id_prefix: str) -> None:
    """Register the full-width toggle callback for a visualization page.

    Eliminates boilerplate duplication across pages that share the standard
    controls-bar / viz-col / details-col layout pattern.  Any page whose
    component IDs follow the ``{id_prefix}-*`` naming convention can call
    this once during module import instead of writing its own callback.

    Component IDs expected:
        ``{id_prefix}-fullwidth-btn``   — the toggle button
        ``{id_prefix}-fullwidth-state`` — dcc.Store holding bool state
        ``{id_prefix}-viz-col``         — Bootstrap Col for the canvas
        ``{id_prefix}-details-col``     — Bootstrap Col for the right panel

    Args:
        id_prefix: Page-specific prefix, e.g. ``"graph"`` or ``"collab"``.
    """
    from dash import Input, Output, State, callback  # pylint: disable=import-outside-toplevel

    @callback(
        [
            Output(f"{id_prefix}-fullwidth-state", "data"),
            Output(f"{id_prefix}-viz-col", "width"),
            Output(f"{id_prefix}-details-col", "style"),
            Output(f"{id_prefix}-fullwidth-btn", "children"),
        ],
        Input(f"{id_prefix}-fullwidth-btn", "n_clicks"),
        State(f"{id_prefix}-fullwidth-state", "data"),
        prevent_initial_call=True,
    )
    def _toggle_fullwidth(_n_clicks: int, is_fullwidth: bool) -> tuple[Any, ...]:
        new_state = not is_fullwidth
        viz_width, panel_style = toggle_details_panel(new_state)
        btn_label = "Restore" if new_state else "Maximize"
        return new_state, viz_width, panel_style, btn_label


def register_edge_hover_dimming_callback(cytoscape_id: str) -> None:
    """Register edge hover AND selection dimming callbacks for a Cytoscape component.

    **Hover behavior** (temporary — clears on mouseout):
    - ``mouseover`` an edge: the edge + its two endpoint nodes get class
      ``highlighted``; all other elements get class ``dimmed``.
    - ``mouseout``: ``highlighted`` and ``dimmed`` are cleared.

    **Selection behavior** (persistent — clears only on deselect):
    - ``select`` an edge: the edge + its two endpoint nodes get class
      ``selected-highlight``; all other elements get class ``selected-dim``.
    - ``unselect``: ``selected-highlight`` and ``selected-dim`` are cleared.

    Hover and selection use separate class names so they do not interfere:
    hovering *over* a selected edge works correctly, and mouseout of the
    selected edge does *not* clear the selection dim state.

    Component IDs expected:
        ``{cytoscape_id}`` — the ``cyto.Cytoscape`` component

    Args:
        cytoscape_id: The Dash component ID of the Cytoscape element,
            e.g. ``"graph-cytoscape"`` or ``"collab-cytoscape"``.
    """
    from dash import Input, Output, clientside_callback  # pylint: disable=import-outside-toplevel

    clientside_callback(
        """
        function(elements) {
            const elem = document.getElementById('""" + cytoscape_id + """');
            if (!elem || !elem._cyreg || !elem._cyreg.cy) {
                return window.dash_clientside.no_update;
            }

            const cy = elem._cyreg.cy;

            if (!cy._edgeHoverListenerAttached) {
                let hoverTimeout = null;
                let isHovering = false;

                // --- Hover (temporary) ---
                cy.on('mouseover', 'edge', function(evt) {
                    const edge = evt.target;

                    if (hoverTimeout) {
                        clearTimeout(hoverTimeout);
                    }

                    hoverTimeout = setTimeout(function() {
                        isHovering = true;

                        const sourceNode = edge.source();
                        const targetNode = edge.target();

                        edge.addClass('highlighted');
                        sourceNode.addClass('highlighted');
                        targetNode.addClass('highlighted');

                        cy.elements().not(edge).not(sourceNode).not(targetNode).addClass('dimmed');
                    }, 50);
                });

                cy.on('mouseout', 'edge', function(evt) {
                    if (hoverTimeout) {
                        clearTimeout(hoverTimeout);
                        hoverTimeout = null;
                    }

                    if (isHovering) {
                        // Only remove hover classes — leave selection classes intact.
                        cy.elements().removeClass('highlighted dimmed');
                        isHovering = false;
                    }
                });

                // --- Selection (persistent) ---
                cy.on('select', 'edge', function(evt) {
                    const edge = evt.target;
                    const sourceNode = edge.source();
                    const targetNode = edge.target();

                    edge.addClass('selected-highlight');
                    sourceNode.addClass('selected-highlight');
                    targetNode.addClass('selected-highlight');

                    cy.elements().not(edge).not(sourceNode).not(targetNode).addClass('selected-dim');
                });

                cy.on('unselect', 'edge', function() {
                    cy.elements().removeClass('selected-highlight selected-dim');
                });

                cy._edgeHoverListenerAttached = true;
            }

            return window.dash_clientside.no_update;
        }
        """,
        Output(cytoscape_id, "className"),
        Input(cytoscape_id, "elements"),
        prevent_initial_call=False,
    )


# ---------------------------------------------------------------------------
# Shared loading overlay — reusable across pages
# ---------------------------------------------------------------------------

_LOADING_OVERLAY_DOTS = html.Div(
    className="thinking-dots d-flex",
    children=[
        html.Span(className="thinking-dot"),
        html.Span(className="thinking-dot"),
        html.Span(className="thinking-dot"),
    ],
)

_LOADING_OVERLAY_LABEL = html.Div(
    "Loading\u2026",
    style={
        "fontFamily": FONT_SANS,
        "fontSize": FONT_SIZE_XSMALL,
        "color": COLOR_GRAY_MEDIUM,
    },
)

_LOADING_OVERLAY_STYLE = {
    "position": "absolute",
    "inset": 0,
    "display": "flex",
    "flexDirection": "column",
    "alignItems": "center",
    "justifyContent": "center",
    "gap": "8px",
    "background": "var(--color-overlay-bg)",
    "transition": "opacity 0.3s ease",
    "zIndex": 5,
    "pointerEvents": "auto",
}


def create_loading_overlay_container(
    content: Any,
    overlay_id: str = "loading-overlay",
) -> html.Div:
    """Wrap *content* with a loading overlay that hides via clientside callback.

    The returned ``html.Div`` is a ``position: relative`` container.  The overlay
    sits inside it as an absolutely-positioned element (centered thinking dots +
    "Loading\u2026" label).  Call ``register_loading_overlay_hider()`` to wire up
    the clientside callback that hides the overlay when a ``dcc.Store`` flips to
    ``False``.

    Args:
        content: The primary content element (e.g. a ``cyto.Cytoscape``).
        overlay_id: DOM id for the overlay div (default ``"loading-overlay"``).

    Returns:
        An ``html.Div`` with ``position: relative`` containing *content* and the
        overlay.
    """
    return html.Div(
        style={"position": "relative"},
        children=[
            content,
            html.Div(
                id=overlay_id,
                style=_LOADING_OVERLAY_STYLE,
                children=[_LOADING_OVERLAY_DOTS, _LOADING_OVERLAY_LABEL],
            ),
        ],
    )


def register_loading_overlay_hider(store_id: str, overlay_id: str) -> None:
    """Register a clientside callback that hides the overlay when loading completes.

    The callback listens to a ``dcc.Store`` with id *store_id*.  When the store
    value becomes ``False`` (or falsy), the overlay identified by *overlay_id* is
    faded out (``opacity: 0``, ``pointer-events: none``).

    Args:
        store_id: The ``dcc.Store`` component id whose ``data`` drives visibility.
        overlay_id: The DOM id of the overlay ``html.Div`` to hide.
    """
    from dash import Input, Output, clientside_callback  # pylint: disable=import-outside-toplevel

    clientside_callback(
        f"""
        function(data) {{
            const el = document.getElementById("{overlay_id}");
            if (!el) return window.dash_clientside.no_update;
            if (data === false || data === null || data === undefined) {{
                el.style.opacity = "0";
                el.style.pointerEvents = "none";
            }} else {{
                el.style.opacity = "";
                el.style.pointerEvents = "";
            }}
            return window.dash_clientside.no_update;
        }}
        """,
        Output(store_id, "data"),  # dummy — we only write, never read back
        Input(store_id, "data"),
        prevent_initial_call=False,
    )


_CONTROLS_BUTTON_STYLE = {
    "fontFamily": FONT_SANS,
    "fontSize": "11px",
    "padding": "4px 12px",
    "borderColor": COLOR_GRAY_LIGHTER,
    "color": COLOR_GRAY_DARK,
}

_LAYOUT_OPTIONS = [
    {"label": "Manual Stable (preset)", "value": "preset"},
    {"label": "Force-Directed (cose)", "value": "cose"},
    {"label": "Circle", "value": "circle"},
    {"label": "Grid", "value": "grid"},
    {"label": "Hierarchical (breadthfirst)", "value": "breadthfirst"},
    {"label": "Concentric", "value": "concentric"},
]


def create_controls_bar(id_prefix: str, *, layout_enabled: bool = True) -> dbc.Row:
    """Create a graph controls bar (layout selector, spotlight, Fit/Reset/Maximize).

    Produces identical chrome for every graph visualization page. Non-applicable
    controls are rendered ``disabled=True`` (grayed out) rather than omitted, to
    keep a consistent look across pages.

    Args:
        id_prefix: Component ID prefix (e.g. ``"graph"`` or ``"collab"``).
            Produces IDs like ``{id_prefix}-layout-selector``,
            ``{id_prefix}-spotlight-input``, ``{id_prefix}-fit-btn``, etc.
        layout_enabled: When False the layout selector is rendered disabled.
            Use False for pages where the layout is fixed (e.g. collab preset).

    Returns:
        A ``dbc.Row`` containing the full controls bar.
    """
    return dbc.Row([
        dbc.Col([
            html.Label(
                "Layout:",
                style={
                    "fontFamily": FONT_SANS,
                    "fontSize": "11px",
                    "fontWeight": FONT_WEIGHT_SEMIBOLD,
                    "color": COLOR_GRAY_DARK,
                    "marginRight": SPACING_XXSMALL,
                    "textTransform": "uppercase",
                    "letterSpacing": "0.3px",
                }
            ),
            dbc.Select(
                id=f"{id_prefix}-layout-selector",
                options=_LAYOUT_OPTIONS,
                value="cose",
                disabled=not layout_enabled,
                style={
                    "fontFamily": FONT_SANS,
                    "width": "200px",
                    "display": "inline-block",
                    "fontSize": "12px",
                    "border": f"1px solid {COLOR_GRAY_LIGHTER}",
                    "opacity": "1" if layout_enabled else "0.45",
                    "cursor": "not-allowed" if not layout_enabled else "default",
                },
                size="sm",
            ),
        ], width="auto"),
        dbc.Col([
            html.Div([
                dbc.Input(
                    id=f"{id_prefix}-spotlight-input",
                    type="text",
                    placeholder="Search nodes\u2026",
                    size="sm",
                    debounce=False,
                    className="graph-spotlight-input",
                ),
                html.Small(
                    id=f"{id_prefix}-spotlight-count",
                    className="graph-spotlight-count-label",
                    children="",
                ),
            ], className="d-flex align-items-center gap-2 justify-content-center"),
        ], width=True),
        dbc.Col([
            dbc.ButtonGroup([
                dbc.Button(
                    "Fit",
                    id=f"{id_prefix}-fit-btn",
                    outline=True,
                    color="secondary",
                    size="sm",
                    style=_CONTROLS_BUTTON_STYLE,
                ),
                dbc.Button(
                    "Reset",
                    id=f"{id_prefix}-reset-btn",
                    outline=True,
                    color="secondary",
                    size="sm",
                    style=_CONTROLS_BUTTON_STYLE,
                ),
                dbc.Button(
                    "Maximize",
                    id=f"{id_prefix}-fullwidth-btn",
                    outline=True,
                    color="secondary",
                    size="sm",
                    style=_CONTROLS_BUTTON_STYLE,
                ),
            ], size="sm"),
        ], width="auto"),
    ], className="mb-2", align="center")


# ---------------------------------------------------------------------------
# Shared element properties panel builder
# ---------------------------------------------------------------------------

_PANEL_INTERNAL_KEYS = {"ID", "elementID", "elementId"}


def _panel_is_visible_key(key: str) -> bool:
    """Return True when a property key is safe to show in the properties panel."""
    if key in _PANEL_INTERNAL_KEYS:
        return False
    return not str(key).startswith("_")


def _panel_build_visible_properties(data: dict[str, Any], exclude_keys: AbstractSet[Any]) -> dict[str, Any]:
    """Return a filtered property dict for the properties panel.

    ``set`` is invariant in mypy, so a ``frozenset`` constant cannot be passed
    to a ``set`` parameter.  This is a read-only use, so take the abstract type.
    """
    return {
        k: v
        for k, v in data.items()
        if k not in exclude_keys and v is not None and _panel_is_visible_key(k)
    }


def _panel_resolve_endpoint(edge_data: dict[str, Any], endpoint: str) -> str:
    """Resolve an edge source/target using explicit *_id fields before Cytoscape id."""
    for key in (f"{endpoint}_id", f"{endpoint}Id", endpoint):
        value = edge_data.get(key)
        if value in (None, ""):
            continue
        if isinstance(value, dict):
            nested = value.get("id")
            if nested not in (None, ""):
                return nested
            continue
        return value
    return "N/A"


# Keys that may hold date or datetime values (e.g. "2025-06-30" or
# "2025-06-30T14:30:00Z").  These get parsed regardless of format.
_DATE_TIME_KEYS = {"start_date", "created_at", "updated_at", "due_date"}


#: Long-form help for derived metrics the properties panel surfaces.  Keys are
#: the element-data keys; the value is the Markdown body shown in a hover/focus
#: popover behind an (i) icon rendered next to that row's key cell.
#:
#: These metrics are computed by the collaboration analytics pipeline and are
#: not self-explanatory from their names, so the panel explains them in place
#: rather than requiring a trip to the docs.
_PANEL_METRIC_TOOLTIPS: dict[str, str] = {
    "hub_score": (
        "**How much total collaboration weight this person carries.**\n\n"
        "Hub score is the sum of the raw weights of every collaboration edge "
        "touching this person -- a plain weighted degree, with no normalization. "
        "If Alice collaborates with Bob (weight 10) and Carol (weight 5), her hub "
        "score is **15**.\n\n"
        "Someone who reviews a lot of code, co-edits many files and shares many "
        "sprints accumulates large edges on many sides, so they rank highly.\n\n"
        "**What it drives:** node size (log-scaled into a 0.25x-2.0x multiplier so "
        "a few giants do not dwarf everyone else) and layout position -- within "
        "each community the highest scorer sits at the centre with others "
        "radiating outward. These are the \"glue people\": remove one and the "
        "cluster can fracture.\n\n"
        "**Note:** the score is volume-biased. A prolific person ranks high partly "
        "because they do more of everything, so a high hub score means \"a lot of "
        "collaboration flows through this person\", not necessarily \"works more "
        "closely than anyone else\"."
    ),
    "normalized_weight": (
        "**How strong this connection is, on a 0-100 scale.**\n\n"
        "The raw `weight` of an edge is an unbounded score -- it might be 5 for "
        "one pair and 17,000 for another. To make that readable, every edge is "
        "rescaled against the strongest edge in the graph you are currently "
        "viewing:\n\n"
        "`normalized = log(weight + 1) / log(strongest weight + 1) x 100`\n\n"
        "- The strongest edge in the view is always **100**; everything else "
        "scales down from it.\n"
        "- The log compression matters: raw weights are heavily skewed, so a "
        "plain rescale would push almost every ordinary edge to ~0 and make them "
        "all look identical.\n\n"
        "**What it drives:** edge colour (violet = weak through to red = strong), "
        "edge opacity, and the render order of overlapping edges. It does not "
        "affect community detection, and it does not set edge thickness.\n\n"
        "**Note:** this value is relative, not absolute, and is computed once when "
        "the graph loads. Introduce a very high-volume collaborator and a pair "
        "that scored 100 yesterday may show a lower value today, despite no change "
        "in how they work. Filtering edges in the UI does not re-scale the "
        "survivors."
    ),
}

#: Source of unique ids for the metric-tooltip icon/popover pairs.  The table is
#: rebuilt on every selection, so ids cannot be derived from the key alone --
#: two rendered tables could otherwise target the same popover.
_METRIC_TOOLTIP_IDS = itertools.count()


def _panel_metric_key_cell(key: Any) -> Any:
    """Render a property key cell, adding an (i) popover for documented metrics.

    Follows the app-wide "info hint" pattern (see ``pages/search.py`` and
    ``pages/timeline/layout.py``): a bare ``fas fa-info-circle`` icon with
    ``cursor: help``, targeted by a ``dbc.Popover`` on hover/focus.  The popover
    carries Markdown, matching the query-description popover in
    ``pages/graph/callbacks/catalog.py``.

    Keys without an entry in ``_PANEL_METRIC_TOOLTIPS`` are returned unchanged,
    so the plain string path stays byte-identical to the previous behaviour.
    """
    tooltip = _PANEL_METRIC_TOOLTIPS.get(str(key))
    if tooltip is None:
        return key

    icon_id = f"panel-metric-info-{next(_METRIC_TOOLTIP_IDS)}"
    return html.Span(
        [
            key,
            html.I(
                className="fas fa-info-circle",
                id=icon_id,
                style={
                    "cursor": "help",
                    "marginLeft": "6px",
                    "color": COLOR_GRAY_MEDIUM,
                    "fontSize": FONT_SIZE_XSMALL,
                    "display": "inline-flex",
                    "alignItems": "center",
                },
            ),
            dbc.Popover(
                dbc.PopoverBody(
                    dcc.Markdown(tooltip),
                    style={"maxWidth": "340px"},
                ),
                target=icon_id,
                trigger="hover focus",
                placement="auto",
                class_name="popover-inverted",
            ),
        ],
        style={"display": "inline-flex", "alignItems": "center"},
    )


def render_properties_table(items: list[Any]) -> html.Table:
    """Render (key, value) pairs as an Executive Dashboard tabular layout.

    The single shared ``(key, value)`` table renderer: used by the graph right
    panel, the collaboration network right panel and the timeline detail modal.
    """
    rows = []
    for key, value in items:
        str_value = str(value)
        is_url = key == "url" or str_value.startswith(("http://", "https://"))
        is_mono = key in ("id",) or (len(str_value) > 16 and " " not in str_value)
        formatted_date = None

        # Hybrid heuristic:
        # - Known date/time keys (e.g. start_date, created_at) are always
        #   candidates regardless of format.
        # - Other strings that look like ISO 8601 ("T" or "Z", >=19 chars) get
        #   the existing fast-path check.  Everything else skips try/except.
        is_date_like = False
        if isinstance(str_value, str):
            if key in _DATE_TIME_KEYS:
                is_date_like = True
            elif ("T" in str_value or "Z" in str_value) and len(str_value) >= 19:
                is_date_like = True

        if is_date_like:
            try:
                dt = datetime.fromisoformat(str_value.replace("Z", "+00:00"))
                local_dt = to_app_timezone(dt)
                actual_time = local_dt.strftime(settings.UI_DATETIME_FORMAT)
                duration_str = humanize_duration(local_dt)
                formatted_date = html.Span(
                    duration_str, title=actual_time, style=DETAILS_TABLE_VALUE_STYLE
                )
            except Exception:
                pass

        if formatted_date:
            value_cell = html.Span(
                [
                    formatted_date,
                    dcc.Clipboard(
                        content=str_value,
                        className="details-prop-icon details-prop-icon--copy",
                        title="Copy",
                    ),
                ],
                className="details-prop-value-wrap",
            )
        elif is_url:
            value_cell = html.Span(
                [
                    html.A(
                        str_value,
                        href=str_value,
                        target="_blank",
                        rel="noopener noreferrer",
                        style=DETAILS_TABLE_LINK_STYLE,
                    ),
                    html.I(
                        className="fas fa-external-link-alt details-prop-icon details-prop-icon--link",
                    ),
                ],
                className="details-prop-value-wrap",
            )
        elif is_mono:
            value_cell = html.Span(
                [
                    html.Code(str_value, style=DETAILS_TABLE_VALUE_MONO_STYLE),
                    dcc.Clipboard(
                        content=str_value,
                        className="details-prop-icon details-prop-icon--copy",
                        title="Copy",
                    ),
                ],
                className="details-prop-value-wrap",
            )
        else:
            value_cell = html.Span(
                [
                    html.Span(str_value, style=DETAILS_TABLE_VALUE_STYLE),
                    dcc.Clipboard(
                        content=str_value,
                        className="details-prop-icon details-prop-icon--copy",
                        title="Copy",
                    ),
                ],
                className="details-prop-value-wrap",
            )
        rows.append(html.Tr(
            [
                html.Td(_panel_metric_key_cell(key), style=DETAILS_TABLE_KEY_STYLE),
                html.Td(
                    value_cell,
                    style={
                        "padding": "6px 0 6px 8px",
                        "borderBottom": "1px solid var(--color-border-light)",
                        "verticalAlign": "top",
                        "wordBreak": "break-word",
                    },
                ),
            ],
            className="details-prop-row",
        ))
    return html.Table(html.Tbody(rows), style=DETAILS_TABLE_STYLE)


#: The same synthetic keys the graph right panel hides, so the modal shows the
#: same rows as the panel it mirrors (see ``build_element_properties_content``).
_PANEL_NODE_EXCLUDE_KEYS = frozenset(
    {"displayLabel", "id", "wba_id", "label", "nodeType", "elementType"}
)


def render_visible_properties(props: dict[str, Any]) -> html.Table | html.P:
    """Render a node's properties, hiding private/internal keys and None values.

    The shared entry point for the timeline detail modal.  It applies the *exact*
    visibility rule the graph right panel applies — ``_panel_build_visible_properties``
    with the same ``_PANEL_NODE_EXCLUDE_KEYS`` — so the modal and the panel show
    the same rows in the same style, and then delegates to
    ``render_properties_table``.

    Returns ``html.Table`` when there is at least one visible property (or an id
    to inject), and the muted ``html.P`` empty state otherwise — hence the union
    return.  Note that ``mypy.ini`` disables ``return-value`` for
    ``app.dash_app.*``, so an incorrect annotation here would not be caught by
    the typecheck gate.
    """
    properties = _panel_build_visible_properties(props, _PANEL_NODE_EXCLUDE_KEYS)
    items = sorted(properties.items())
    wba_id = props.get("wba_id") or props.get("id")
    if wba_id is not None:
        items = [("id", wba_id)] + items
    if not items:
        return html.P(
            "No properties", className="text-muted", style=DETAILS_MUTED_TEXT_STYLE
        )
    return render_properties_table(items)


def build_element_properties_content(
    data: dict[str, Any],
    *,
    expand_node_enabled: bool = True,
) -> html.Div:
    """Build the properties panel content for a selected node or edge.

    Detects element type from the ``elementType`` discriminator that every
    Cytoscape element carries (``'node'`` vs ``'edge'``).  Detecting via a
    ``source`` key is ambiguous because a legitimate Neo4j node property may
    be named ``source`` (e.g. Jira ``Issue``/``Team`` nodes store it), which
    would misclassify those nodes as edges.  Used by both the graph page and
    future visualization pages.  Pages that
    do not support node expansion should pass ``expand_node_enabled=False``
    — the button is rendered disabled (grayed out) rather than omitted.

    Args:
        data: Cytoscape element ``data`` dict (from ``selectedNodeData[0]``
            or ``tapEdgeData``).
        expand_node_enabled: Whether the Expand Node button should be active.

    Returns:
        An ``html.Div`` containing the formatted properties panel content.
    """
    is_edge = data.get("elementType") == "edge"

    if not is_edge:
        # --- Node ---
        exclude_keys: AbstractSet[Any] = _PANEL_NODE_EXCLUDE_KEYS
        properties = _panel_build_visible_properties(data, exclude_keys)
        wba_id = data.get("wba_id") or data.get("id")
        sorted_items = sorted(properties.items())
        if wba_id is not None:
            sorted_items = [("id", wba_id)] + sorted_items

        header = html.Div([
            html.Div(data.get("label", "N/A"), style=DETAILS_PANEL_HEADER_STYLE),
            html.Div(data.get("nodeType", "Unknown"), style=DETAILS_PANEL_SUBTYPE_STYLE),
        ], className="mb-3")

        if sorted_items:
            properties_section: list[Any] = [render_properties_table(sorted_items)]
        else:
            properties_section = [
                html.P("No properties", className="text-muted", style=DETAILS_MUTED_TEXT_STYLE)
            ]

        btn_kwargs: dict[str, Any] = {
            "color": "primary",
            "size": "sm",
            "outline": True,
            "disabled": not expand_node_enabled,
            "className": "w-100",
            "style": {"fontSize": FONT_SIZE_XSMALL},
        }
        if expand_node_enabled:
            btn_kwargs["id"] = "expand-node-btn"

        expand_button = html.Div([
            html.Hr(style={"margin": "16px 0"}),
            dbc.Button(
                [html.I(className="fas fa-project-diagram me-2"), "Expand Node"],
                **btn_kwargs,
            ),
            html.Small(
                "Load connected neighbors" if expand_node_enabled
                else "Not available for this graph",
                className="text-muted d-block text-center mt-1",
                style={"fontSize": FONT_SIZE_XTINY},
            ),
        ], className="mt-3")

        return html.Div([header] + properties_section + [expand_button])

    # --- Edge ---
    exclude_keys = {"id", "source", "target", "label", "relType", "elementType"}
    properties = _panel_build_visible_properties(data, exclude_keys)
    source_id = _panel_resolve_endpoint(data, "source")
    target_id = _panel_resolve_endpoint(data, "target")

    header = html.Div([
        html.Div(
            data.get("relType", data.get("label", "Unknown")),
            style=DETAILS_PANEL_HEADER_STYLE,
        ),
        html.Div("Relationship", style=DETAILS_PANEL_SUBTYPE_STYLE),
    ], className="mb-3")

    meta_items = [("from", source_id), ("to", target_id)]
    if properties:
        meta_items += sorted(properties.items())

    return html.Div([header, render_properties_table(meta_items)])


def create_info_card(title: str, content: str, accent_color: str | None = None) -> html.Div:
    """
    Create an informational card with custom accent color.
    
    Args:
        title: The card title
        content: The card content text
        accent_color: Border accent color (default: theme accent)
        
    Returns:
        html.Div: A styled info card component
        
    Example:
        create_info_card(
            "Project Status",
            "All systems operational",
            COLOR_SUCCESS
        )
    """
    resolved_accent_color = accent_color or COLOR_NAVY

    card_style = {
        **FEATURE_CARD_STYLE,
        "borderLeft": f"3px solid {resolved_accent_color}"
    }
    
    return html.Div([
        html.Div(title, style=FEATURE_CARD_TITLE_STYLE),
        html.Div(content, style=FEATURE_CARD_DESCRIPTION_STYLE)
    ], style=card_style)


def create_section_divider(text: str | None = None) -> html.Div:
    """
    Create a section divider with optional text.
    
    Args:
        text: Optional text to display in the divider
        
    Returns:
        html.Div: A styled section divider
        
    Example:
        create_section_divider()
        create_section_divider("Analysis Results")
    """
    if text:
        return html.Div(
            text,
            style={
                "fontFamily": FONT_SANS,
                "fontSize": FONT_SIZE_XSMALL,
                "color": COLOR_GRAY_MEDIUM,
                "textTransform": "uppercase",
                "letterSpacing": "1px",
                "borderTop": f"1px solid {COLOR_BORDER}",
                "paddingTop": SPACING_XSMALL,
                "marginTop": SPACING_MEDIUM,
                "marginBottom": SPACING_SMALL
            }
        )
    else:
        return html.Hr(style={
            "borderTop": f"1px solid {COLOR_BORDER}",
            "marginTop": SPACING_MEDIUM,
            "marginBottom": SPACING_MEDIUM
        })


def create_stat_card(label: str, value: str, subtitle: str | None = None) -> html.Div:
    """
    Create a statistics card with label, value, and optional subtitle.
    
    Args:
        label: The stat label
        value: The stat value to display prominently
        subtitle: Optional subtitle text
        
    Returns:
        html.Div: A styled stat card component
        
    Example:
        create_stat_card("Active Tasks", "24", "↑ 12% from last week")
    """
    components = [
        html.Div(
            label,
            style={
                "fontFamily": FONT_SANS,
                "fontSize": FONT_SIZE_XSMALL,
                "color": COLOR_GRAY_MEDIUM,
                "textTransform": "uppercase",
                "letterSpacing": "1px",
                "marginBottom": SPACING_XXSMALL
            }
        ),
        html.Div(
            value,
            style={
                "fontFamily": FONT_SANS,
                "fontSize": "32px",
                "fontWeight": "700",
                "color": COLOR_CHARCOAL_MEDIUM,
                "marginBottom": SPACING_XXSMALL
            }
        )
    ]
    
    if subtitle:
        components.append(
            html.Div(
                subtitle,
                style={
                    "fontFamily": FONT_SANS,
                    "fontSize": FONT_SIZE_XSMALL,
                    "color": COLOR_GRAY_MEDIUM,
                    "fontStyle": "italic"
                }
            )
        )
    
    return html.Div(
        components,
        style={
            **FEATURE_CARD_STYLE,
            "textAlign": "center"
        }
    )

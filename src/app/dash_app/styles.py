"""
Executive Dashboard Design System

This module provides centralized design tokens for the Work Behavior Analytics AI application.
All color values, typography settings, spacing, and common style patterns are
defined here as the single source of truth for the Executive Dashboard aesthetic.

Usage:
    from app.dash_app.styles import COLOR_NAVY, FONT_SANS, COMPACT_PAGE_HEADER_STYLE
    
    html.Div("My Header", style=COMPACT_PAGE_HEADER_STYLE)
"""

from typing import Any

from domain.theme_tokens import (
    ACTIVE_THEME,
    NODE_TYPE_BASE_STYLES,
    THEME_TOKENS,
    get_theme_tokens,
)

# =============================================================================
# TYPOGRAPHY
# =============================================================================

# Font Families
FONT_SERIF = "'Cormorant Garamond', serif"
FONT_SANS = "'Inter', sans-serif"

# Font Sizes
FONT_SIZE_XLARGE = "42px"
FONT_SIZE_LARGE = "15px"
FONT_SIZE_MEDIUM = "14px"
FONT_SIZE_SMALL = "13px"
FONT_SIZE_XSMALL = "12px"
FONT_SIZE_TINY = "11px"
FONT_SIZE_XTINY = "10px"
FONT_SIZE_XXSMALL = "9px"

# Font Weights
FONT_WEIGHT_NORMAL = "400"
FONT_WEIGHT_MEDIUM = "500"
FONT_WEIGHT_SEMIBOLD = "600"
FONT_WEIGHT_BOLD = "700"

# =============================================================================
# COLORS - Theme Tokens
# =============================================================================

# The token registry itself lives in ``domain`` because the API consumes it
# too (``app/api/graph_themes/v1/service.py`` resolves base tokens for the
# effective-theme endpoints). It is re-exported here so the UI's existing
# ``from app.dash_app.styles import ACTIVE_THEME`` imports keep working.
#
# ``__all__`` is required: ``mypy`` runs with ``strict = True``, which turns
# on ``no_implicit_reexport``, so an undeclared re-export is an error at the
# importing site in ``app.dash_app.graph_styles``.
__all__ = [
    "ACTIVE_THEME",
    "NODE_TYPE_BASE_STYLES",
    "THEME_TOKENS",
    "get_theme_tokens",
]

TOKENS = get_theme_tokens()


def _token(name: str) -> str:
    """Fetch a token from the active theme and fail fast if missing."""
    try:
        return TOKENS[name]
    except KeyError as exc:
        raise KeyError(f"Theme token not found: {name}") from exc


# Legacy color exports backed by CSS variables for runtime theme switching.
# Theme hex values remain available through get_theme_tokens(...).

# Primary Colors
COLOR_NAVY = "var(--color-navy)"
COLOR_NAVY_DARK = "var(--color-navy-dark)"
COLOR_NAVY_HOVER = "var(--color-navy-hover)"

# Text Colors
COLOR_CHARCOAL = "var(--color-charcoal)"
COLOR_CHARCOAL_MEDIUM = "var(--color-charcoal-medium)"
COLOR_GRAY_DARK = "var(--color-gray-dark)"
COLOR_GRAY_MEDIUM = "var(--color-gray-medium)"
COLOR_GRAY_LIGHT = "var(--color-gray-light)"
COLOR_GRAY_LIGHTER = "var(--color-gray-lighter)"

# Background Colors
COLOR_BACKGROUND_WHITE = "var(--color-background-white)"
COLOR_BACKGROUND_LIGHT = "var(--color-background-light)"
COLOR_SURFACE_ACTIVE = "var(--color-surface-active)"

# Border Colors
COLOR_BORDER = "var(--color-border)"
COLOR_BORDER_LIGHT = "var(--color-border-light)"

# Utility Colors
COLOR_SUCCESS = "var(--color-success)"
COLOR_WARNING = "var(--color-warning)"
COLOR_ERROR = "var(--color-error)"
COLOR_INFO = "var(--color-info)"

# Extended Colors (Graph UI Components)
COLOR_TEXT_DARK = "var(--color-text-dark)"
COLOR_TEXT_MUTED = "var(--color-text-muted)"
COLOR_TEXT_SECONDARY = "var(--color-text-secondary)"
COLOR_BACKGROUND_PALE = "var(--color-background-pale)"
COLOR_BORDER_GRAY = "var(--color-border-gray)"
COLOR_CODE_BACKGROUND = "var(--color-code-background)"
COLOR_SHADOW_LIGHT = "var(--color-shadow-light)"
COLOR_CONTEXT_MENU_BORDER = "var(--color-context-menu-border)"
COLOR_DESTRUCTIVE = "var(--color-destructive)"
COLOR_WARNING_DARK = "var(--color-warning-dark)"
COLOR_SUCCESS_DARK = "var(--color-success-dark)"

# =============================================================================
# SPACING
# =============================================================================

SPACING_XXXSMALL = "4px"
SPACING_XXSMALL = "8px"
SPACING_XSMALL = "12px"
SPACING_SMALL = "16px"
SPACING_MEDIUM = "24px"
SPACING_LARGE = "32px"
SPACING_XLARGE = "40px"
SPACING_XXLARGE = "48px"

# =============================================================================
# COMMON STYLE PATTERNS
# =============================================================================

# Page Headers
COMPACT_PAGE_HEADER_STYLE = {
    "display": "flex",
    "alignItems": "center",
    "gap": SPACING_XSMALL,
    "fontFamily": FONT_SANS,
    "fontSize": FONT_SIZE_SMALL,
    "textTransform": "uppercase",
    "letterSpacing": "0.8px",
    "borderBottom": f"1px solid {COLOR_BORDER}",
    "paddingBottom": SPACING_XSMALL,
    "marginBottom": SPACING_XXSMALL
}

# Card Containers
CARD_CONTAINER_STYLE = {
    "backgroundColor": COLOR_BACKGROUND_WHITE,
    "padding": SPACING_MEDIUM,
    "borderRadius": "2px"
}

# Feature Cards
FEATURE_CARD_STYLE = {
    "padding": SPACING_MEDIUM,
    "backgroundColor": COLOR_BACKGROUND_LIGHT,
    "border": f"1px solid {COLOR_BORDER}",
    "borderLeft": f"3px solid {COLOR_NAVY}",
    "borderRadius": "2px",
    "marginBottom": SPACING_SMALL
}

FEATURE_CARD_TITLE_STYLE = {
    "fontFamily": FONT_SANS,
    "fontSize": FONT_SIZE_MEDIUM,
    "fontWeight": FONT_WEIGHT_SEMIBOLD,
    "color": COLOR_CHARCOAL_MEDIUM,
    "marginBottom": SPACING_XXSMALL,
    "textTransform": "uppercase",
    "letterSpacing": "0.5px"
}

FEATURE_CARD_DESCRIPTION_STYLE = {
    "fontFamily": FONT_SANS,
    "fontSize": FONT_SIZE_SMALL,
    "color": COLOR_GRAY_MEDIUM,
    "lineHeight": "1.6"
}

# Placeholder Sections
PLACEHOLDER_ICON_STYLE = {
    "fontSize": "48px",
    "color": COLOR_GRAY_LIGHT,
    "marginBottom": SPACING_SMALL,
    "textAlign": "center"
}

PLACEHOLDER_MESSAGE_STYLE = {
    "fontFamily": FONT_SANS,
    "fontSize": FONT_SIZE_MEDIUM,
    "color": COLOR_GRAY_MEDIUM,
    "textAlign": "center",
    "marginBottom": SPACING_MEDIUM,
    "fontStyle": "italic"
}

# Input Styles
INPUT_STYLE = {
    "fontFamily": FONT_SANS,
    "fontSize": FONT_SIZE_SMALL,
    "padding": SPACING_XSMALL,
    "border": f"1px solid {COLOR_BORDER}",
    "width": "100%"
}

# Navigation & Layout
SIDEBAR_STYLE = {
    "backgroundColor": COLOR_BACKGROUND_WHITE,
    "borderRight": f"1px solid {COLOR_BORDER}",
    "padding": f"{SPACING_MEDIUM} 0"
}

NAVBAR_BRAND_STYLE = {
    "fontFamily": FONT_SANS,
    "fontSize": FONT_SIZE_MEDIUM,
    "marginBottom": "0",
    "fontWeight": FONT_WEIGHT_SEMIBOLD,
    "padding": "0",
    "color": COLOR_CHARCOAL_MEDIUM,
    "letterSpacing": "0.5px",
    "textTransform": "uppercase"
}

TOPBAR_STYLE = {
    "minHeight": "auto",
    "height": "44px",
    "padding": "0",
    "borderBottom": f"1px solid {COLOR_BORDER}",
    "boxShadow": "0 1px 2px var(--color-topbar-shadow)",
    "backgroundColor": COLOR_BACKGROUND_WHITE
}

TOPBAR_CONTAINER_STYLE = {
    "padding": "8px 16px"
}

TOGGLE_BUTTON_STYLE = {
    "fontSize": "16px",
    "fontWeight": "normal",
    "padding": "4px 10px",
    "lineHeight": "1",
    "borderColor": COLOR_GRAY_LIGHTER,
    "color": COLOR_GRAY_DARK,
    "backgroundColor": "transparent"
}

SIDEBAR_COL_STYLE = {
    "minWidth": "180px",
    "maxWidth": "180px"
}

# =============================================================================
# GRAPH PAGE COMPONENTS
# =============================================================================

GRAPH_QUERY_TEXTAREA_STYLE = {
    "fontFamily": FONT_SANS,
    "height": "90px",
    "border": f"1px solid {COLOR_GRAY_LIGHTER}",
    "padding": f"{SPACING_XSMALL} {SPACING_SMALL}",
    "fontSize": FONT_SIZE_SMALL,
    "resize": "vertical",
    "transition": "border-color 0.2s",
    "backgroundColor": COLOR_BACKGROUND_WHITE,
    "color": COLOR_CHARCOAL_MEDIUM
}

GRAPH_HELPER_TEXT_STYLE = {
    "fontFamily": FONT_SANS,
    "fontSize": "11px",
    "color": COLOR_GRAY_LIGHT,
    "letterSpacing": "0.3px"
}

GRAPH_CYTOSCAPE_STYLE = {
    "width": "100%",
    "height": "75vh",
    "backgroundColor": "var(--color-graph-canvas)",
    "borderRadius": "4px"
}

GRAPH_EMPTY_STATE_ICON_STYLE = {
    "fontFamily": FONT_SERIF,
    "fontSize": "28px",
    "color": COLOR_GRAY_LIGHTER,
    "marginBottom": SPACING_XSMALL
}

GRAPH_EMPTY_STATE_TEXT_STYLE = {
    "fontFamily": FONT_SANS,
    "color": COLOR_GRAY_LIGHT,
    "fontSize": FONT_SIZE_SMALL,
    "lineHeight": "1.6"
}

GRAPH_DETAILS_PANEL_STYLE = {
    "backgroundColor": COLOR_BACKGROUND_PALE,
    "borderRadius": "4px",
    "border": f"1px solid {COLOR_BORDER_GRAY}",
    "padding": SPACING_XXSMALL,
}

GRAPH_NODE_HOVER_TOOLTIP_STYLE = {
    "display": "none",
    "position": "fixed",
    "zIndex": 9999,
    "pointerEvents": "none",
    "backgroundColor": COLOR_BACKGROUND_WHITE,
    "border": f"1px solid {COLOR_BORDER}",
    "borderRadius": "4px",
    "padding": f"{SPACING_XXXSMALL} {SPACING_XXSMALL}",
    "fontFamily": FONT_SANS,
    "fontSize": FONT_SIZE_XSMALL,
    "color": COLOR_CHARCOAL_MEDIUM,
    "maxWidth": "320px",
    "boxShadow": f"0 2px 8px {COLOR_SHADOW_LIGHT}",
    "whiteSpace": "normal",
    "wordBreak": "break-word",
}

# Graph page constant (used in dcc.Loading component)
GRAPH_LOADING_COLOR = COLOR_NAVY

# =============================================================================
# GRAPH UI COMPONENTS (Callbacks, Menus, Details)
# =============================================================================

# Context Menu Styles
CONTEXT_MENU_CONTAINER_STYLE = {
    "position": "fixed",
    "display": "none",
    "backgroundColor": COLOR_BACKGROUND_WHITE,
    "border": f"1px solid {COLOR_CONTEXT_MENU_BORDER}",
    "borderRadius": "4px",
    "boxShadow": f"2px 2px 8px {COLOR_SHADOW_LIGHT}",
    "zIndex": "9999",
    "minWidth": "180px",
    "padding": "4px 0"
}

CONTEXT_MENU_ITEM_STYLE = {
    "padding": "8px 16px",
    "cursor": "pointer",
    "fontSize": FONT_SIZE_SMALL,
    "color": COLOR_CHARCOAL_MEDIUM
}

CONTEXT_MENU_DIVIDER_STYLE = {
    "margin": "4px 0",
    "borderTop": f"1px solid {COLOR_BORDER}"
}

CONTEXT_MENU_DESTRUCTIVE_STYLE = {
    "padding": "8px 16px",
    "cursor": "pointer",
    "fontSize": FONT_SIZE_SMALL,
    "color": COLOR_DESTRUCTIVE
}

# Validation Message Styles
VALIDATION_ALERT_STYLE = {
    "fontSize": FONT_SIZE_SMALL
}

VALIDATION_CODE_STYLE = {
    "fontSize": FONT_SIZE_XSMALL,
    "backgroundColor": "var(--color-validation-code-background)",
    "padding": "2px 6px"
}

# Details Panel Styles
DETAILS_MUTED_TEXT_STYLE = {
    "fontSize": FONT_SIZE_SMALL,
    "fontStyle": "italic"
}

# Properties Table — Executive Dashboard tabular layout
DETAILS_PANEL_HEADER_STYLE = {
    "fontFamily": FONT_SANS,
    "fontSize": FONT_SIZE_MEDIUM,
    "fontWeight": FONT_WEIGHT_SEMIBOLD,
    "color": COLOR_CHARCOAL_MEDIUM,
    "borderLeft": f"3px solid {COLOR_NAVY}",
    "paddingLeft": "10px",
    "marginBottom": "12px",
    "letterSpacing": "0.2px",
}

DETAILS_PANEL_SUBTYPE_STYLE = {
    "fontFamily": FONT_SANS,
    "fontSize": FONT_SIZE_TINY,
    "fontWeight": FONT_WEIGHT_MEDIUM,
    "color": COLOR_TEXT_MUTED,
    "textTransform": "uppercase",
    "letterSpacing": "0.8px",
    "marginBottom": "10px",
    "paddingLeft": "13px",
}

DETAILS_TABLE_STYLE = {
    "width": "100%",
    "borderCollapse": "collapse",
    "fontFamily": FONT_SANS,
}

DETAILS_TABLE_KEY_STYLE = {
    "fontFamily": FONT_SANS,
    "fontSize": FONT_SIZE_TINY,
    "fontWeight": FONT_WEIGHT_MEDIUM,
    "color": COLOR_TEXT_MUTED,
    "textTransform": "uppercase",
    "letterSpacing": "0.7px",
    "padding": "6px 10px 6px 0",
    "verticalAlign": "top",
    "whiteSpace": "nowrap",
    "width": "38%",
    "borderBottom": f"1px solid {COLOR_BORDER_LIGHT}",
}

DETAILS_TABLE_VALUE_STYLE = {
    "fontFamily": FONT_SANS,
    "fontSize": FONT_SIZE_MEDIUM,
    "fontWeight": FONT_WEIGHT_NORMAL,
    "color": COLOR_TEXT_SECONDARY,
    "padding": "6px 0 6px 8px",
    "verticalAlign": "top",
    "wordBreak": "break-word",
    "borderBottom": f"1px solid {COLOR_BORDER_LIGHT}",
}

DETAILS_TABLE_VALUE_MONO_STYLE = {
    **DETAILS_TABLE_VALUE_STYLE,
    "fontFamily": "'SFMono-Regular', 'Consolas', 'Menlo', monospace",
    "fontSize": FONT_SIZE_SMALL,
    "color": COLOR_NAVY,
    "backgroundColor": COLOR_BACKGROUND_PALE,
    "padding": "5px 6px",
    "borderRadius": "2px",
    "border": "none",
}

DETAILS_TABLE_LINK_STYLE = {
    **DETAILS_TABLE_VALUE_STYLE,
    "color": COLOR_NAVY,
    "textDecoration": "none",
    "cursor": "pointer",
    "wordBreak": "break-all",
}

# Property Formatter Styles
PROPERTY_COMPLEX_VALUE_STYLE = {
    "fontSize": FONT_SIZE_TINY,
    "backgroundColor": COLOR_BACKGROUND_PALE,
    "padding": "6px",
    "borderRadius": "3px",
    "marginBottom": "0",
    "whiteSpace": "pre-wrap",
    "wordBreak": "break-all"
}

PROPERTY_SIMPLE_VALUE_STYLE = {
    "color": COLOR_TEXT_DARK,
    "fontSize": FONT_SIZE_SMALL
}

PROPERTY_LABEL_STYLE = {
    "color": COLOR_TEXT_MUTED,
    "fontSize": FONT_SIZE_XSMALL
}

# Performance Metrics Styles
PERFORMANCE_CONTAINER_STYLE = {
    "backgroundColor": COLOR_BACKGROUND_PALE,
    "borderRadius": "4px",
    "padding": "8px 12px",
    "marginBottom": "8px",
    "border": f"1px solid {COLOR_CODE_BACKGROUND}"
}

PERFORMANCE_METRIC_ICON_STYLE = {
    "color": COLOR_TEXT_MUTED,
    "fontSize": FONT_SIZE_XTINY
}

PERFORMANCE_METRIC_LABEL_STYLE = {
    "color": COLOR_TEXT_MUTED,
    "fontSize": FONT_SIZE_TINY,
    "fontWeight": FONT_WEIGHT_MEDIUM
}

PERFORMANCE_METRIC_VALUE_STYLE = {
    "color": COLOR_TEXT_DARK,
    "fontSize": FONT_SIZE_TINY,
    "fontWeight": FONT_WEIGHT_SEMIBOLD
}

PERFORMANCE_TIP_STYLE = {
    "fontSize": FONT_SIZE_XTINY,
    "display": "block",
    "marginTop": "4px"
}

PERFORMANCE_TIP_ICON_STYLE = {
    "fontSize": FONT_SIZE_XXSMALL
}

# Alert Component Styles  
ALERT_TEXT_STYLE = {
    "fontSize": FONT_SIZE_MEDIUM
}

ALERT_HINT_STYLE = {
    "fontSize": FONT_SIZE_XSMALL
}

ALERT_LINK_STYLE = {
    "fontSize": FONT_SIZE_XSMALL,
    "color": "inherit",
    "textDecoration": "underline"
}

ALERT_SEPARATOR_STYLE = {
    "margin": "8px 0"
}

ALERT_DOC_LINK_ICON_STYLE = {
    "fontSize": FONT_SIZE_XTINY
}

# =============================================================================
# LAYOUT UTILITIES
# =============================================================================

def merge_styles(*styles: dict[str, Any]) -> dict[str, Any]:
    """
    Merge multiple style dictionaries together.
    Later styles override earlier ones.
    
    Args:
        *styles: Variable number of style dictionaries
        
    Returns:
        dict: Merged style dictionary
        
    Example:
        combined = merge_styles(BASE_STYLE, {"color": "red"})
    """
    result = {}
    for style in styles:
        if style:
            result.update(style)
    return result

"""Semantic theme token registry for the Executive Dashboard design system.

This module owns the theme registry (``THEME_TOKENS``), the active theme
name (``ACTIVE_THEME``), the structural node geometry
(``NODE_TYPE_BASE_STYLES``), and the lookup entry point
(``get_theme_tokens``).

It lives in ``domain`` rather than in the Dash UI package because the API
also consumes it: ``app/api/graph_themes/v1/service.py`` resolves the base
tokens for the effective-theme endpoints. The registry is therefore shared
by the API runtime and the UI runtime, and must stay transport-free.

**The node geometry is injected, not literal.** ``THEME_TOKENS`` does not
literally contain the ``graph.node.<type>.shape/.width/.height`` keys; the
loop below injects them from ``NODE_TYPE_BASE_STYLES`` at import time.
``domain.graph_theme._base_node_properties`` reads those keys to resolve each
node type's base shape and size, so the injection loop is load-bearing and
must stay in this module, alongside the registry it mutates. Moving the
registry without the loop would flatten every typed node to ``ellipse`` at
60x50 in the API's effective-theme response.
"""

from typing import Any

# =============================================================================
# COLORS - Theme Tokens
# =============================================================================

ACTIVE_THEME = "executive-light"

# Semantic token registry.
# The UI's ``COLOR_*`` constants are derived from these; they stay in the UI
# layer so that the registry itself remains transport-free.
THEME_TOKENS = {
    "executive-light": {
        # Brand / accent
        "brand.primary": "#2c5282",
        "brand.primary.dark": "#1e3a5f",
        "brand.primary.hover": "#234164",

        # Text
        "text.primary": "#1a202c",
        "text.secondary": "#2d3748",
        "text.tertiary": "#4a5568",
        "text.muted": "#718096",
        "text.subtle": "#a0aec0",
        "text.disabled": "#cbd5e0",

        # Surfaces
        "surface.base": "#ffffff",
        "surface.subtle": "#f7fafc",
        "surface.active": "#edf2f7",
        "surface.pale": "#f8f9fa",

        # Borders
        "border.default": "#e2e8f0",
        "border.light": "#e2e8f0",
        "border.medium": "#dee2e6",
        "border.context-menu": "#ccc",

        # Utility
        "utility.success": "#48bb78",
        "utility.warning": "#ed8936",
        "utility.error": "#f56565",
        "utility.info": "#4299e1",
        "utility.destructive": "#dc3545",
        "utility.warning.dark": "#ffc107",
        "utility.success.dark": "#28a745",

        # Extended UI
        "ui.text.dark": "#212529",
        "ui.text.muted": "#6c757d",
        "ui.text.secondary": "#495057",
        "ui.code.background": "#e9ecef",
        "ui.details.icon": "#adb5bd",
        "ui.graph.canvas": "#fafafa",
        "ui.shadow.light": "rgba(0,0,0,0.2)",
        "ui.focus.ring": "rgba(44, 82, 130, 0.1)",
        "ui.validation.code.background": "rgba(255,255,255,0.3)",
        "ui.topbar.shadow": "rgba(0,0,0,0.04)",

        # Graph palette tokens (Cytoscape)
        # Vivid colours shared with COMMUNITY_COLORS for visual consistency.
        # Semantic mapping:
        # person=blue, project=amber, issue=red, epic=violet,
        # repository=emerald, branch=teal, team=lime,
        # identity_mapping=cyan, initiative=indigo, sprint=orange,
        # commit=pink, file=fuchsia, pull_request=yellow.
        "graph.node.default": "#B8B8B8",
        "graph.node.default.border": "#9E9E9E",
        "graph.node.label": "#f4f7fb",  # white — readable on all vivid fills
        "graph.node.label.font.size": "11",  # node label font size (px)
        "graph.node.project": "#F59E0B",
        "graph.node.project.border": "#D97706",
        "graph.node.person": "#3B82F6",
        "graph.node.person.border": "#2563EB",
        "graph.node.branch": "#14B8A6",
        "graph.node.branch.border": "#0D9488",
        "graph.node.epic": "#8B5CF6",
        "graph.node.epic.border": "#7C3AED",
        "graph.node.issue": "#EF4444",
        "graph.node.issue.border": "#DC2626",
        "graph.node.repository": "#10B981",
        "graph.node.repository.border": "#059669",
        "graph.node.team": "#84CC16",
        "graph.node.team.border": "#65A30D",
        "graph.node.identity_mapping": "#06B6D4",
        "graph.node.identity_mapping.border": "#0891B2",
        "graph.node.initiative": "#6366F1",
        "graph.node.initiative.border": "#4F46E5",
        "graph.node.sprint": "#F97316",
        "graph.node.sprint.border": "#EA580C",
        "graph.node.commit": "#EC4899",
        "graph.node.commit.border": "#DB2777",
        "graph.node.file": "#D946EF",
        "graph.node.file.border": "#C026D3",
        "graph.node.pull_request": "#EAB308",
        "graph.node.pull_request.border": "#CA8A04",
        "graph.node.space": "#0EA5E9",
        "graph.node.space.border": "#0284C7",
        "graph.node.page": "#F43F5E",
        "graph.node.page.border": "#E11D48",
        "graph.node.blogpost": "#A855F7",
        "graph.node.blogpost.border": "#9333EA",
        "graph.edge.default": "#C0C0C0",
        "graph.edge.label.font.size": "9",  # edge label font size (px)
        "graph.selection": "#424242",

        # Activity Timeline lane accents (assigned by selection order).
        # Vivid palette shared with the graph nodes so lanes read consistently.
        "timeline.lane.1": "#3B82F6",
        "timeline.lane.2": "#EF4444",
        "timeline.lane.3": "#8B5CF6",
        "timeline.lane.4": "#10B981",
        "timeline.lane.5": "#F97316",
    },
    "executive-dark": {
        # Brand / accent (slightly brighter for dark surfaces)
        "brand.primary": "#5f86b4",
        "brand.primary.dark": "#4d739f",
        "brand.primary.hover": "#6b93c3",

        # Text
        "text.primary": "#e6edf3",
        "text.secondary": "#ced8e3",
        "text.tertiary": "#a9b6c5",
        "text.muted": "#8f9fb1",
        "text.subtle": "#78889b",
        "text.disabled": "#5f6f82",

        # Surfaces (soft dark, not pure black)
        "surface.base": "#1f262f",
        "surface.subtle": "#252f3a",
        "surface.active": "#2f3b49",
        "surface.pale": "#2a3440",

        # Borders
        "border.default": "#3a4653",
        "border.light": "#445262",
        "border.medium": "#4c5968",
        "border.context-menu": "#566474",

        # Utility
        "utility.success": "#57b983",
        "utility.warning": "#d6a564",
        "utility.error": "#db7f7f",
        "utility.info": "#62a6d8",
        "utility.destructive": "#d97b7b",
        "utility.warning.dark": "#d9b26d",
        "utility.success.dark": "#5eb88d",

        # Extended UI
        "ui.text.dark": "#e6edf3",
        "ui.text.muted": "#98a8bb",
        "ui.text.secondary": "#bdc9d7",
        "ui.code.background": "#323e4b",
        "ui.details.icon": "#8ea0b3",
        "ui.graph.canvas": "#222b35",
        "ui.shadow.light": "rgba(0,0,0,0.35)",
        "ui.focus.ring": "rgba(95, 134, 180, 0.28)",
        "ui.validation.code.background": "rgba(255,255,255,0.08)",
        "ui.topbar.shadow": "rgba(0,0,0,0.28)",

        # Graph palette tokens — same vivid colours as executive-light for
        # cross-theme consistency; they read well on the dark canvas too since
        # COMMUNITY_COLORS already uses them in collaboration mode on this theme.
        "graph.node.default": "#7f8fa3",
        "graph.node.default.border": "#96a4b6",
        "graph.node.label": "#f4f7fb",  # white — readable on all vivid fills
        "graph.node.label.font.size": "11",  # node label font size (px)
        "graph.node.project": "#F59E0B",
        "graph.node.project.border": "#D97706",
        "graph.node.person": "#3B82F6",
        "graph.node.person.border": "#2563EB",
        "graph.node.branch": "#14B8A6",
        "graph.node.branch.border": "#0D9488",
        "graph.node.epic": "#8B5CF6",
        "graph.node.epic.border": "#7C3AED",
        "graph.node.issue": "#EF4444",
        "graph.node.issue.border": "#DC2626",
        "graph.node.repository": "#10B981",
        "graph.node.repository.border": "#059669",
        "graph.node.team": "#84CC16",
        "graph.node.team.border": "#65A30D",
        "graph.node.identity_mapping": "#06B6D4",
        "graph.node.identity_mapping.border": "#0891B2",
        "graph.node.initiative": "#6366F1",
        "graph.node.initiative.border": "#4F46E5",
        "graph.node.sprint": "#F97316",
        "graph.node.sprint.border": "#EA580C",
        "graph.node.commit": "#EC4899",
        "graph.node.commit.border": "#DB2777",
        "graph.node.file": "#D946EF",
        "graph.node.file.border": "#C026D3",
        "graph.node.pull_request": "#EAB308",
        "graph.node.pull_request.border": "#CA8A04",
        "graph.node.space": "#0EA5E9",
        "graph.node.space.border": "#0284C7",
        "graph.node.page": "#F43F5E",
        "graph.node.page.border": "#E11D48",
        "graph.node.blogpost": "#A855F7",
        "graph.node.blogpost.border": "#9333EA",
        "graph.edge.default": "#8c9aab",
        "graph.edge.label.font.size": "9",  # edge label font size (px)
        "graph.selection": "#d5deea",

        # Activity Timeline lane accents — kept identical across themes for
        # cross-theme consistency, matching the theme-invariant graph palette.
        "timeline.lane.1": "#3B82F6",
        "timeline.lane.2": "#EF4444",
        "timeline.lane.3": "#8B5CF6",
        "timeline.lane.4": "#10B981",
        "timeline.lane.5": "#F97316",
    }
}


# Structural (non-colour) node geometry for each nodeType. Identical across
# base modes; kept here as the single source of truth for the base shape/size
# that graph-theme overrides merge over (see
# ``domain.graph_theme._base_node_properties``).
NODE_TYPE_BASE_STYLES: dict[str, tuple[str, str, str]] = {
    "default": ("ellipse", "60px", "50px"),
    "project": ("round-rectangle", "70px", "35px"),
    "person": ("octagon", "66px", "56px"),
    "branch": ("diamond", "58px", "50px"),
    "epic": ("hexagon", "66px", "56px"),
    "issue": ("triangle", "58px", "50px"),
    "repository": ("rectangle", "68px", "34px"),
    "team": ("pentagon", "64px", "54px"),
    "identity_mapping": ("tag", "62px", "50px"),
    "initiative": ("round-hexagon", "66px", "54px"),
    "sprint": ("vee", "60px", "48px"),
    "commit": ("rhomboid", "62px", "30px"),
    "file": ("barrel", "64px", "32px"),
    "pull_request": ("ellipse", "66px", "33px"),
    "space": ("cut-rectangle", "70px", "40px"),
    "page": ("bottom-round-rectangle", "64px", "38px"),
    "blogpost": ("round-diamond", "60px", "60px"),
}

# Inject shape/size tokens into each base mode so graph-theme overrides can
# merge over the full node geometry (colour + shape + size) without changing
# the hardcoded visual output when no overrides are present.
for _mode_tokens in THEME_TOKENS.values():
    for _suffix, (_shape, _width, _height) in NODE_TYPE_BASE_STYLES.items():
        _key = f"graph.node.{_suffix}"
        _mode_tokens[f"{_key}.shape"] = _shape
        _mode_tokens[f"{_key}.width"] = _width
        _mode_tokens[f"{_key}.height"] = _height


def get_theme_tokens(theme_name: str = ACTIVE_THEME) -> dict[str, Any]:
    """Return semantic tokens for the requested theme."""
    if theme_name not in THEME_TOKENS:
        available = ", ".join(sorted(THEME_TOKENS.keys()))
        raise ValueError(f"Unknown theme '{theme_name}'. Available themes: {available}")
    return THEME_TOKENS[theme_name]

"""Pure helpers for the Activity Timeline page.

These functions are deliberately free of Dash and network dependencies so they
can be unit-tested directly. UI-1 uses the selection and colour helpers; later
phases extend this module with bucketing/card helpers.
"""

from __future__ import annotations

from typing import Any

# Soft cap on the number of lanes (design decision #4).
MAX_LANES = 5

# Minimum query length accepted by ``GET /api/v1/activity/suggest``. Shorter
# queries are rejected with 422 by the router, so the UI must gate client-side.
MIN_QUERY_LENGTH = 2

# Lane accent token keys, resolved to colours through ``get_theme_tokens(...)``
# at render time (never treated as hex here).
_LANE_TOKEN_KEYS: list[str] = [f"timeline.lane.{index}" for index in range(1, MAX_LANES + 1)]

# Short display labels for the PascalCase ``entity_type`` values the API sends.
# Unmapped types fall back to the raw type string.
_ENTITY_TYPE_LABELS: dict[str, str] = {
    "Person": "Person",
    "PullRequest": "PR",
    "Issue": "Issue",
    "Commit": "Commit",
    "Page": "Page",
    "Epic": "Epic",
    "Repository": "Repository",
    "Branch": "Branch",
    "Project": "Project",
    "Team": "Team",
    "Sprint": "Sprint",
    "File": "File",
    "Space": "Space",
    "Initiative": "Initiative",
    "Blogpost": "Blogpost",
    "IdentityMapping": "Identity",
}

# Font Awesome 6 icon class used when no avatar is available.
_ENTITY_TYPE_ICONS: dict[str, str] = {
    "Person": "fas fa-user",
    "PullRequest": "fas fa-code-pull-request",
    "Issue": "fas fa-circle-exclamation",
    "Commit": "fas fa-code-commit",
    "Page": "fas fa-file-lines",
    "Epic": "fas fa-layer-group",
    "Repository": "fas fa-book",
    "Branch": "fas fa-code-branch",
    "Project": "fas fa-diagram-project",
    "Team": "fas fa-users",
    "Sprint": "fas fa-person-running",
    "File": "fas fa-file",
    "Space": "fas fa-globe",
    "Initiative": "fas fa-bullseye",
    "Blogpost": "fas fa-newspaper",
    "IdentityMapping": "fas fa-id-card",
}

_DEFAULT_ENTITY_ICON = "fas fa-cube"


def assign_lane_colors(count: int) -> list[str]:
    """Return the first ``count`` lane accent token **keys**.

    Colours are assigned by selection order; removing a lane and reassigning
    keeps the surviving lanes' colours distinct. More than :data:`MAX_LANES`
    keys are never returned.
    """
    if count <= 0:
        return []
    return list(_LANE_TOKEN_KEYS[: min(count, MAX_LANES)])


def entity_type_label(entity_type: str) -> str:
    """Return the short display label for an entity type (unknown → raw type)."""
    return _ENTITY_TYPE_LABELS.get(entity_type, entity_type)


def entity_type_icon(entity_type: str) -> str:
    """Return the Font Awesome icon class for an entity type."""
    return _ENTITY_TYPE_ICONS.get(entity_type, _DEFAULT_ENTITY_ICON)


def add_selection(
    selection: list[dict[str, Any]], item: dict[str, Any]
) -> list[dict[str, Any]]:
    """Return ``selection`` with ``item`` appended, idempotently.

    Adding an item whose ``wba_id`` is already selected is a no-op, as is
    adding beyond :data:`MAX_LANES` or adding an item without a ``wba_id``.
    The input list is never mutated.
    """
    wba_id = item.get("wba_id")
    if not wba_id:
        return list(selection)
    if any(existing.get("wba_id") == wba_id for existing in selection):
        return list(selection)
    if len(selection) >= MAX_LANES:
        return list(selection)
    return [*selection, dict(item)]


def remove_selection(
    selection: list[dict[str, Any]], wba_id: str | None
) -> list[dict[str, Any]]:
    """Return ``selection`` without the entry matching ``wba_id``."""
    return [item for item in selection if item.get("wba_id") != wba_id]


def is_full(selection: list[dict[str, Any]]) -> bool:
    """Return whether the selection has reached the soft lane cap."""
    return len(selection) >= MAX_LANES

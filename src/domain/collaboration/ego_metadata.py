"""Collaborator-cap metadata shared by the Analytics card and the ego page.

Two surfaces offer the same choice — the Analytics card's collaborator cap and
the ego page's in-page selector — so the option list is declared once here and
imported by both, and the two cannot drift apart.

This lives in ``domain`` rather than beside ``app/analytics/collaboration/ego.py``
because that module pulls in ``networkx`` (and, through ``algorithm``,
``community_louvain``/``matplotlib``), which the UI runtime must not carry.
"""

from typing import Any, Dict, List

__all__ = ["COLLABORATOR_CAP_OPTIONS", "cap_options_for"]

# Collaborator-cap choices offered by both the Analytics card and the ego page's
# in-page selector, so the two surfaces cannot offer different sets.
COLLABORATOR_CAP_OPTIONS = [10, 25, 50, 100]


def cap_options_for(max_collaborators: int) -> List[Dict[str, Any]]:
    """Return the collaborator-cap choices that ``max_collaborators`` can honour.

    The in-page selector slices an already-fetched element set, so a cap above
    ``max_collaborators`` could never take effect. Offering it would be a dead
    control, so the option list is truncated to the fetched ceiling — which is
    always included, even when it is not one of COLLABORATOR_CAP_OPTIONS (the
    API accepts any value in 1..500, so a hand-edited URL can produce one).

    Args:
        max_collaborators: The cap the current element set was fetched with.

    Returns:
        ``{"label": ..., "value": ...}`` dicts ordered ascending, ready for a
        Dash options prop.
    """
    caps = sorted({*[c for c in COLLABORATOR_CAP_OPTIONS if c <= max_collaborators], max_collaborators})
    return [{"label": f"Top {cap}", "value": cap} for cap in caps]

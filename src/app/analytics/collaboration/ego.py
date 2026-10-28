"""Ego (per-person) collaboration network: a pure star of one Person's collaborators.

Reuses the org collaboration query (filtered by $focus_id) but deliberately does
NOT reuse the Louvain/community pipeline: a star has no communities, and
hub_score (weighted degree over the whole org graph) is meaningless when every
spoke holds exactly one edge.
"""

import math
from typing import Any, Dict, List

import networkx as nx

from app.analytics.collaboration.algorithm import (
    _compact_label,
    _weight_to_hex,
    normalize_edge_weights,
)
from app.runtime_settings import runtime_settings
from domain.collaboration.ego_metadata import (
    COLLABORATOR_CAP_OPTIONS,
    cap_options_for,
)
from domain.person_network_url import DEFAULT_MAX_COLLABORATORS

# ``COLLABORATOR_CAP_OPTIONS`` and ``cap_options_for`` are re-exported here so
# that existing ``from app.analytics.collaboration.ego import ...`` call sites
# keep resolving after they moved to ``domain.collaboration.ego_metadata``.
# The declaration is required by mypy's ``no_implicit_reexport`` (strict).
__all__ = [
    "COLLABORATOR_CAP_OPTIONS",
    "RADIUS_MAX",
    "RADIUS_MIN",
    "TARGET_SPOKE_SEPARATION",
    "build_ego_elements",
    "build_ego_graph",
    "cap_options_for",
    "compute_radial_positions",
]

# Radial ring radii in layout units. The closest collaborator sits at R_IN,
# the weakest at R_OUT.
#
# R_IN is a FLOOR, not the actual innermost radius: with a fixed R_IN the arc
# between angularly-adjacent spokes shrinks as spokes are added, and Person
# nodes (66x56px, see domain/node_size.py) end up overlapping (35.3px apart
# at 25 spokes, 17.2px at 50). The innermost radius is therefore scaled so the
# arc can never fall below TARGET_SPOKE_SEPARATION — see
# compute_radial_positions. Overlap is scale-invariant (cy.fit() zooms
# uniformly), so it cannot be fixed at render time.
RADIUS_MIN = 120.0
RADIUS_MAX = 480.0
TARGET_SPOKE_SEPARATION = 80.0


def build_ego_graph(records: List[Dict[str, Any]], focus_id: str) -> nx.Graph:
    """Build a pure-star graph of ``focus_id`` and its collaborators.

    Only edges incident to the focus are created: a collaborator-to-collaborator
    pair in ``records`` would still be modelled as two independent spokes.

    Args:
        records: Raw rows from the collaboration score Cypher query (already
                 filtered by ``$focus_id``), each with ``person1_wba_id``,
                 ``person2_wba_id``, ``person1``, ``person2`` and
                 ``total_collaboration_score``.
        focus_id: wba_id of the Person at the centre of the star.

    Returns:
        Undirected NetworkX graph whose only hub is ``focus_id``. Every node
        carries a ``display_name`` attribute used for labelling.
    """
    g: nx.Graph = nx.Graph()
    g.add_node(focus_id, display_name=focus_id)

    for record in records:
        p1 = record["person1_wba_id"]
        p2 = record["person2_wba_id"]
        spoke = p2 if p1 == focus_id else p1
        if spoke == focus_id:
            # Defensive: a self-pair would be a self-loop, not a spoke.
            continue

        if p1 == focus_id:
            focus_name = record.get("person1")
            spoke_name = record.get("person2")
        else:
            focus_name = record.get("person2")
            spoke_name = record.get("person1")

        if focus_name:
            g.nodes[focus_id]["display_name"] = focus_name
        if not g.has_node(spoke):
            g.add_node(spoke, display_name=spoke_name or spoke)
        elif spoke_name:
            g.nodes[spoke]["display_name"] = spoke_name

        weight = float(record["total_collaboration_score"])
        if g.has_edge(focus_id, spoke):
            g[focus_id][spoke]["weight"] += weight
        else:
            g.add_edge(focus_id, spoke, weight=weight)

    return g


def _normalized_for(
    focus_id: str,
    spoke: str,
    normalized: Dict[tuple[str, str], float],
) -> float:
    """Look up a spoke's normalized weight regardless of edge key orientation."""
    if (focus_id, spoke) in normalized:
        return normalized[(focus_id, spoke)]
    return normalized.get((spoke, focus_id), 0.0)


def compute_radial_positions(
    focus_id: str,
    spokes_by_weight: List[tuple[str, float]],
    normalized: Dict[tuple[str, str], float],
) -> Dict[str, Dict[str, float]]:
    """Place the focus at the origin and each spoke on a ring by its weight.

    Strongest collaborator -> innermost ring, at max(RADIUS_MIN,
    count * TARGET_SPOKE_SEPARATION / (2*pi)).
    Weakest   collaborator -> outermost ring, one fixed band (RADIUS_MAX -
    RADIUS_MIN) further out.
    Angles are spread evenly, starting at 0 and proceeding clockwise.

    Args:
        focus_id: wba_id of the centre node.
        spokes_by_weight: ``(spoke_id, raw_weight)`` pairs; only the spoke ids
                          are used, ordering comes from ``normalized``.
        normalized: Output of :func:`normalize_edge_weights`.

    Returns:
        Dict mapping node id -> ``{"x": float, "y": float}``. Deterministic for
        identical inputs; an empty spoke list yields just the origin.
    """
    positions: Dict[str, Dict[str, float]] = {focus_id: {"x": 0.0, "y": 0.0}}
    if not spokes_by_weight:
        return positions

    ordered = sorted(
        (spoke for spoke, _ in spokes_by_weight),
        key=lambda spoke: (-_normalized_for(focus_id, spoke, normalized), spoke),
    )

    count = len(ordered)
    # Keep the angular gap between adjacent spokes at or above the target, so a
    # spoke can never sit closer to its neighbour than a node is wide. The chord
    # between adjacent spokes is >= the arc length at the innermost radius, so
    # scaling R_IN by count * TARGET / (2*pi) is a sufficient guarantee; the
    # radial offset only adds to it. R_MAX moves out by the same fixed band, so
    # the ring thickness — and the weight-driven reading of the layout — is
    # unchanged.
    radius_min = max(RADIUS_MIN, count * TARGET_SPOKE_SEPARATION / (2.0 * math.pi))
    radius_max = radius_min + (RADIUS_MAX - RADIUS_MIN)

    for index, spoke in enumerate(ordered):
        ratio = index / (count - 1) if count > 1 else 0.0
        radius = radius_min + (radius_max - radius_min) * ratio
        angle = -2.0 * math.pi * index / count
        positions[spoke] = {
            "x": radius * math.cos(angle),
            "y": radius * math.sin(angle),
        }
    return positions


def build_ego_elements(
    records: List[Dict[str, Any]],
    focus_id: str,
    max_collaborators: int | None = DEFAULT_MAX_COLLABORATORS,
) -> tuple[List[Dict[str, Any]], int, int]:
    """Build Cytoscape elements for the ego star.

    ``normalized_weight`` is scaled over the focus person's FULL collaborator
    set, before the cap is applied, so changing ``max_collaborators`` never
    recolours the graph.

    Args:
        records: Raw rows from the collaboration score Cypher query.
        focus_id: wba_id of the Person at the centre.
        max_collaborators: Keep at most this many collaborators (by raw weight).
                           ``None`` or a value <= 0 keeps all.

    Returns:
        ``(elements, total_collaborators, shown_collaborators)`` where
        ``total_collaborators`` is the count BEFORE the cap and
        ``shown_collaborators`` the count actually emitted. ``elements`` holds
        the focus node first, then the emitted spokes, then the edges.
    """
    g = build_ego_graph(records, focus_id)
    normalized = normalize_edge_weights(g)

    spokes: List[tuple[str, float]] = [
        (spoke, float(data["weight"]))
        for spoke, data in g[focus_id].items()
    ]
    spokes.sort(key=lambda item: (-item[1], item[0]))
    total_collaborators = len(spokes)

    if max_collaborators is not None and max_collaborators > 0:
        spokes = spokes[:max_collaborators]
    shown_collaborators = len(spokes)

    positions = compute_radial_positions(focus_id, spokes, normalized)

    max_label_chars = max(
        4, int(runtime_settings.get_int("GRAPH_UI_MAX_NODE_LABEL_CHARS"))
    )

    focus_name = g.nodes[focus_id].get("display_name", focus_id)
    elements: List[Dict[str, Any]] = [{
        "data": {
            "id": focus_id,
            "wba_id": focus_id,
            "label": focus_name,
            "displayLabel": _compact_label(focus_name, max_label_chars),
            "nodeType": "Person",
            "role": "focus",
            "elementType": "node",
            "total_collaborators": total_collaborators,
            # NOTE: no hub_score — deliberately omitted in this view.
        },
        "classes": "ego-centre",
        "position": positions[focus_id],
    }]

    for spoke, raw_weight in spokes:
        spoke_name = g.nodes[spoke].get("display_name", spoke)
        elements.append({
            "data": {
                "id": spoke,
                "wba_id": spoke,
                "label": spoke_name,
                "displayLabel": _compact_label(spoke_name, max_label_chars),
                "nodeType": "Person",
                "role": "collaborator",
                "elementType": "node",
                "weight": raw_weight,
                "normalized_weight": round(
                    _normalized_for(focus_id, spoke, normalized) * 100, 1
                ),
                # NOTE: no _node_size — node size stays constant in this view.
            },
            "position": positions[spoke],
        })

    for spoke, raw_weight in spokes:
        canonical_source, canonical_target = sorted((focus_id, spoke))
        normalized_0_1 = _normalized_for(focus_id, spoke, normalized)
        elements.append({
            "data": {
                "id": f"collab:{canonical_source}:{canonical_target}",
                "source": canonical_source,
                "target": canonical_target,
                "weight": raw_weight,
                "normalized_weight": round(normalized_0_1 * 100, 1),
                "_edge_line_color": _weight_to_hex(normalized_0_1),
                "relType": "COLLABORATES",
                "elementType": "edge",
            },
            "classes": "collaboration-edge",
        })

    return elements, total_collaborators, shown_collaborators

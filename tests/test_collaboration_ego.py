"""Unit tests for the ego (per-person) collaboration network pipeline.

Tests cover all pure functions in app/analytics/collaboration/ego.py using
small synthetic records — no Neo4j connection required.

The two highest-value tests here are the monotonicity test (heavier ⇒ closer)
and the cap-stability test (capping does not renormalize): they encode design
decisions 4 and 7 of the ego plan and catch the most likely regressions.

Run with: pytest tests/test_collaboration_ego.py -v
"""

import math

import pytest

from app.analytics.collaboration.algorithm import normalize_edge_weights
from app.analytics.collaboration.ego import (
    DEFAULT_MAX_COLLABORATORS,
    RADIUS_MAX,
    RADIUS_MIN,
    build_ego_elements,
    build_ego_graph,
    cap_options_for,
    compute_radial_positions,
)
from app.api.graph.v1.model import EgoNetworkResponse


pytestmark = pytest.mark.unit

FOCUS = "github::Person::focus"

PERSON_NODE_WIDTH_PX = 66.0
"""Rendered width of a Person node — app/common/node_size.py:16."""


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

def _rec(p1: str, p2: str, score: float) -> dict:
    """Build a minimal collaboration record in the query's output format."""
    return {
        "person1": p1,
        "person1_wba_id": f"github::Person::{p1}",
        "person1_props": {"id": f"github::Person::{p1}", "name": p1},
        "person2": p2,
        "person2_wba_id": f"github::Person::{p2}",
        "person2_props": {"id": f"github::Person::{p2}", "name": p2},
        "total_collaboration_score": score,
    }


def _records(*pairs: tuple[str, float]) -> list[dict]:
    """Build records linking FOCUS's short name to each (spoke, score) pair."""
    return [_rec("focus", spoke, score) for spoke, score in pairs]


def _wba(spoke: str) -> str:
    """Return the full node id for a short spoke name."""
    return f"github::Person::{spoke}"


def _spokes(*pairs: tuple[str, float]) -> list[tuple[str, float]]:
    """Return ``(full_wba_id, weight)`` pairs, as ``build_ego_elements`` builds them."""
    return [(_wba(spoke), score) for spoke, score in pairs]


def _nodes(elements: list[dict]) -> list[dict]:
    return [e for e in elements if e.get("data", {}).get("elementType") == "node"]


def _edges(elements: list[dict]) -> list[dict]:
    return [e for e in elements if e.get("data", {}).get("elementType") == "edge"]


# ---------------------------------------------------------------------------
# build_ego_graph
# ---------------------------------------------------------------------------

class TestBuildEgoGraph:
    def test_pure_star_only_focus_incident_edges(self):
        g = build_ego_graph(_records(("a", 10.0), ("b", 5.0)), FOCUS)
        assert g.number_of_nodes() == 3
        assert g.number_of_edges() == 2
        for source, target in g.edges():
            assert FOCUS in (source, target), "every edge must touch the focus"

    def test_no_collaborator_to_collaborator_edges(self):
        """A collaborator pair in records still yields two independent spokes."""
        g = build_ego_graph(_records(("a", 10.0), ("b", 5.0)), FOCUS)
        assert not g.has_edge("github::Person::a", "github::Person::b")

    def test_empty_records_yields_focus_alone(self):
        g = build_ego_graph([], FOCUS)
        assert list(g.nodes()) == [FOCUS]
        assert g.number_of_edges() == 0

    def test_duplicate_pairs_accumulate(self):
        g = build_ego_graph(_records(("a", 10.0), ("a", 4.0)), FOCUS)
        assert g[FOCUS]["github::Person::a"]["weight"] == pytest.approx(14.0)

    def test_focus_seen_as_person2(self):
        """The focus can appear in either column; both produce a spoke."""
        g = build_ego_graph([_rec("a", "focus", 7.0)], FOCUS)
        assert g.has_edge(FOCUS, "github::Person::a")

    def test_display_names_captured(self):
        g = build_ego_graph(_records(("a", 1.0)), FOCUS)
        assert g.nodes[FOCUS]["display_name"] == "focus"
        assert g.nodes["github::Person::a"]["display_name"] == "a"


# ---------------------------------------------------------------------------
# normalize_edge_weights
# ---------------------------------------------------------------------------

class TestNormalizeWeights:
    def test_strongest_collaborator_is_one(self):
        g = build_ego_graph(_records(("a", 10.0), ("b", 5.0)), FOCUS)
        normalized = normalize_edge_weights(g)
        assert max(normalized.values()) == pytest.approx(1.0)

    def test_monotonic_in_raw_weight(self):
        g = build_ego_graph(_records(("a", 10.0), ("b", 5.0), ("c", 1.0)), FOCUS)
        normalized = normalize_edge_weights(g)
        assert normalized[(FOCUS, "github::Person::a")] > normalized[(FOCUS, "github::Person::b")]
        assert normalized[(FOCUS, "github::Person::b")] > normalized[(FOCUS, "github::Person::c")]

    def test_single_collaborator(self):
        g = build_ego_graph(_records(("a", 3.0)), FOCUS)
        normalized = normalize_edge_weights(g)
        assert normalized[(FOCUS, "github::Person::a")] == pytest.approx(1.0)

    def test_empty_graph_returns_empty_dict(self):
        g = build_ego_graph([], FOCUS)
        assert normalize_edge_weights(g) == {}

    def test_all_zero_weights_return_zero_not_raise(self):
        """The ``or 1.0`` guard: log(0 + 1) == 0 must not divide by zero."""
        g = build_ego_graph(_records(("a", 0.0), ("b", 0.0)), FOCUS)
        normalized = normalize_edge_weights(g)
        assert len(normalized) == 2
        assert all(v == 0.0 for v in normalized.values())


# ---------------------------------------------------------------------------
# compute_radial_positions
# ---------------------------------------------------------------------------

class TestComputeRadialPositions:
    def test_focus_at_origin(self):
        spokes = [("github::Person::a", 10.0)]
        g = build_ego_graph(_records(("a", 10.0)), FOCUS)
        positions = compute_radial_positions(FOCUS, spokes, normalize_edge_weights(g))
        assert positions[FOCUS] == {"x": 0.0, "y": 0.0}

    def test_heavier_collaborator_is_closer(self):
        """Core invariant: higher normalized weight ⇒ smaller radius."""
        pairs = [("a", 30.0), ("b", 20.0), ("c", 10.0), ("d", 1.0)]
        g = build_ego_graph(_records(*pairs), FOCUS)
        normalized = normalize_edge_weights(g)
        positions = compute_radial_positions(FOCUS, _spokes(*pairs), normalized)

        def radius(spoke: str) -> float:
            pos = positions[_wba(spoke)]
            return (pos["x"] ** 2 + pos["y"] ** 2) ** 0.5

        assert radius("a") < radius("b") < radius("c") < radius("d")

    def test_radii_bounded_by_constants(self):
        pairs = [("a", 30.0), ("b", 10.0)]
        g = build_ego_graph(_records(*pairs), FOCUS)
        positions = compute_radial_positions(FOCUS, _spokes(*pairs), normalize_edge_weights(g))

        def radius(spoke: str) -> float:
            pos = positions[_wba(spoke)]
            return (pos["x"] ** 2 + pos["y"] ** 2) ** 0.5

        assert radius("a") == pytest.approx(RADIUS_MIN)
        assert radius("b") == pytest.approx(RADIUS_MAX)

    def test_deterministic_across_calls(self):
        pairs = [("a", 30.0), ("b", 20.0), ("c", 10.0)]
        g = build_ego_graph(_records(*pairs), FOCUS)
        normalized = normalize_edge_weights(g)
        assert compute_radial_positions(FOCUS, _spokes(*pairs), normalized) == \
               compute_radial_positions(FOCUS, _spokes(*pairs), normalized)

    def test_n_spokes_spread_evenly(self):
        pairs = [(f"p{i}", float(i + 1)) for i in range(6)]
        g = build_ego_graph(_records(*pairs), FOCUS)
        positions = compute_radial_positions(FOCUS, _spokes(*pairs), normalize_edge_weights(g))
        assert len(positions) == 7  # focus + 6 spokes
        # First spoke starts at angle 0 → x = radius, y = 0 (within float noise).
        first = positions[_wba("p5")]  # heaviest
        assert first["y"] == pytest.approx(0.0, abs=1e-9)
        assert first["x"] > 0

    def test_empty_spokes_yields_origin_only(self):
        positions = compute_radial_positions(FOCUS, [], {})
        assert positions == {FOCUS: {"x": 0.0, "y": 0.0}}

    @pytest.mark.parametrize("count", (2, 5, 9, 10, 13, 14, 17, 25, 50, 100))
    def test_no_two_spokes_overlap_at_any_count(self, count: int):
        """No two spokes may sit closer than a Person node is wide."""
        pairs = [(f"p{i}", float(count - i)) for i in range(count)]
        g = build_ego_graph(_records(*pairs), FOCUS)
        positions = compute_radial_positions(FOCUS, _spokes(*pairs), normalize_edge_weights(g))

        spoke_ids = [_wba(f"p{i}") for i in range(count)]

        def point(spoke: str) -> tuple[float, float]:
            pos = positions[spoke]
            return (pos["x"], pos["y"])

        separation = min(
            math.dist(point(a), point(b))
            for index, a in enumerate(spoke_ids)
            for b in spoke_ids[index + 1:]
        )
        assert separation >= PERSON_NODE_WIDTH_PX, (
            f"{count} spokes: min separation {separation:.1f}px "
            f"< {PERSON_NODE_WIDTH_PX}px node width"
        )

    @pytest.mark.parametrize("count", (2, 5, 9))
    def test_small_star_geometry_is_unchanged(self, count: int):
        """Up to 9 spokes the innermost/outermost rings are the bare constants."""
        pairs = [(f"p{i}", float(count - i)) for i in range(count)]
        g = build_ego_graph(_records(*pairs), FOCUS)
        positions = compute_radial_positions(FOCUS, _spokes(*pairs), normalize_edge_weights(g))

        def radius(spoke: str) -> float:
            pos = positions[_wba(spoke)]
            return (pos["x"] ** 2 + pos["y"] ** 2) ** 0.5

        assert radius("p0") == pytest.approx(RADIUS_MIN)
        assert radius(f"p{count - 1}") == pytest.approx(RADIUS_MAX)

    @pytest.mark.parametrize("count", (10, 25, 50))
    def test_innermost_radius_scales_with_count(self, count: int):
        """Above the floor the innermost ring is scaled by the spoke count."""
        pairs = [(f"p{i}", float(count - i)) for i in range(count)]
        g = build_ego_graph(_records(*pairs), FOCUS)
        positions = compute_radial_positions(FOCUS, _spokes(*pairs), normalize_edge_weights(g))

        pos = positions[_wba("p0")]
        radius = (pos["x"] ** 2 + pos["y"] ** 2) ** 0.5
        assert radius == pytest.approx(count * 80.0 / (2 * math.pi))
        assert radius > RADIUS_MIN


# ---------------------------------------------------------------------------
# Element emission
# ---------------------------------------------------------------------------

class TestBuildEgoElements:
    def test_max_normalized_weight_is_exactly_100(self):
        elements, _, _ = build_ego_elements(_records(("a", 10.0), ("b", 5.0)), FOCUS)
        weights = [e["data"]["normalized_weight"] for e in _edges(elements)]
        assert max(weights) == 100.0

    def test_every_node_carries_non_empty_display_label(self):
        """The stylesheet binds node labels to displayLabel and nothing else."""
        elements, _, _ = build_ego_elements(_records(("a", 10.0)), FOCUS)
        for node in _nodes(elements):
            label = node["data"].get("displayLabel")
            assert isinstance(label, str) and label, f"missing displayLabel on {node['data']['id']}"

    def test_display_label_truncated_to_runtime_setting(self):
        long_name = "A" * 80
        records = [_rec("focus", long_name, 5.0)]
        elements, _, _ = build_ego_elements(records, FOCUS)
        spoke = next(n for n in _nodes(elements) if n["data"]["role"] == "collaborator")
        assert len(spoke["data"]["displayLabel"]) <= 80

    def test_no_node_carries_size_fields(self):
        """Constant-size guarantee: the ego view must not set any size key."""
        elements, _, _ = build_ego_elements(_records(("a", 10.0), ("b", 5.0)), FOCUS)
        for node in _nodes(elements):
            for key in ("_node_size", "_render_width_px", "_render_size_px"):
                assert key not in node["data"], f"{key} must be absent for constant size"

    def test_every_edge_touches_focus(self):
        elements, _, _ = build_ego_elements(_records(("a", 10.0), ("b", 5.0)), FOCUS)
        for edge in _edges(elements):
            assert FOCUS in (edge["data"]["source"], edge["data"]["target"])

    def test_focus_element_role_and_class(self):
        elements, _, _ = build_ego_elements(_records(("a", 10.0)), FOCUS)
        focus = next(n for n in _nodes(elements) if n["data"]["role"] == "focus")
        assert focus["data"]["id"] == FOCUS
        assert focus["classes"] == "ego-centre"
        assert focus["position"] == {"x": 0.0, "y": 0.0}

    def test_spoke_element_class(self):
        elements, _, _ = build_ego_elements(_records(("a", 10.0)), FOCUS)
        spoke = next(n for n in _nodes(elements) if n["data"]["role"] == "collaborator")
        assert spoke["classes"] == "ego-spoke"

    def test_edge_ids_follow_collab_convention(self):
        elements, _, _ = build_ego_elements(_records(("a", 10.0)), FOCUS)
        edge = _edges(elements)[0]
        source, target = sorted((FOCUS, "github::Person::a"))
        assert edge["data"]["id"] == f"collab:{source}:{target}"

    def test_no_hub_score_anywhere(self):
        elements, _, _ = build_ego_elements(_records(("a", 10.0)), FOCUS)
        for element in _nodes(elements):
            assert "hub_score" not in element["data"]

    def test_empty_records_yields_focus_node_only(self):
        elements, total, shown = build_ego_elements([], FOCUS)
        assert total == 0 and shown == 0
        assert len(_nodes(elements)) == 1
        assert _nodes(elements)[0]["data"]["role"] == "focus"
        assert _edges(elements) == []

    def test_deterministic_across_calls(self):
        records = _records(("a", 10.0), ("b", 5.0), ("c", 1.0))
        assert build_ego_elements(records, FOCUS) == build_ego_elements(records, FOCUS)


# ---------------------------------------------------------------------------
# Cap behaviour
# ---------------------------------------------------------------------------

class TestCapBehaviour:
    def test_total_is_pre_cap_shown_is_post_cap(self):
        pairs = [(f"p{i}", float(20 - i)) for i in range(10)]
        elements, total, shown = build_ego_elements(_records(*pairs), FOCUS, max_collaborators=4)
        assert total == 10
        assert shown == 4
        assert len(_edges(elements)) == 4

    def test_capping_does_not_change_surviving_normalized_weights(self):
        """Design decision 4: normalization happens before the cap."""
        pairs = [(f"p{i}", float(20 - i)) for i in range(10)]
        records = _records(*pairs)
        uncapped, _, _ = build_ego_elements(records, FOCUS, max_collaborators=None)
        capped, _, _ = build_ego_elements(records, FOCUS, max_collaborators=4)

        uncapped_by_id = {e["data"]["id"]: e["data"]["normalized_weight"] for e in _edges(uncapped)}
        for edge in _edges(capped):
            assert edge["data"]["normalized_weight"] == uncapped_by_id[edge["data"]["id"]]

    def test_cap_keeps_heaviest_collaborators(self):
        pairs = [("heavy", 100.0), ("light", 1.0)]
        elements, _, shown = build_ego_elements(_records(*pairs), FOCUS, max_collaborators=1)
        assert shown == 1
        kept = _edges(elements)[0]
        assert "heavy" in kept["data"]["id"]

    def test_none_keeps_all(self):
        pairs = [(f"p{i}", float(i + 1)) for i in range(7)]
        _, total, shown = build_ego_elements(_records(*pairs), FOCUS, max_collaborators=None)
        assert total == shown == 7

    def test_default_cap_is_25(self):
        pairs = [(f"p{i}", float(i + 1)) for i in range(30)]
        _, total, shown = build_ego_elements(_records(*pairs), FOCUS)
        assert total == 30
        assert shown == DEFAULT_MAX_COLLABORATORS == 25

    def test_focus_total_collaborators_is_pre_cap(self):
        pairs = [(f"p{i}", float(i + 1)) for i in range(10)]
        elements, _, _ = build_ego_elements(_records(*pairs), FOCUS, max_collaborators=3)
        focus = next(n for n in _nodes(elements) if n["data"]["role"] == "focus")
        assert focus["data"]["total_collaborators"] == 10


# ---------------------------------------------------------------------------
# cap_options_for
# ---------------------------------------------------------------------------

class TestCapOptionsFor:
    @pytest.mark.parametrize("max_collaborators, expected", (
        (25, [10, 25]),
        (100, [10, 25, 50, 100]),
        (30, [10, 25, 30]),
        (1, [1]),
        (500, [10, 25, 50, 100, 500]),
    ))
    def test_offers_only_what_the_fetched_cap_can_honour(
        self, max_collaborators: int, expected: list[int]
    ):
        options = cap_options_for(max_collaborators)
        assert [option["value"] for option in options] == expected

    def test_labels_match_their_values(self):
        for option in cap_options_for(100):
            assert option["label"] == f"Top {option['value']}"


# ---------------------------------------------------------------------------
# EgoNetworkResponse model
# ---------------------------------------------------------------------------

class TestEgoNetworkResponseModel:
    def test_serialises_all_five_fields(self):
        response = EgoNetworkResponse(
            elements=[{"data": {"id": "x"}}],
            focus_person={"id": FOCUS, "label": "Focus"},
            total_collaborators=10,
            shown_collaborators=5,
            config={"lookback_days": 90},
        )
        payload = response.model_dump()
        assert set(payload.keys()) == {
            "elements", "focus_person", "total_collaborators", "shown_collaborators", "config",
        }
        assert payload["total_collaborators"] == 10
        assert payload["shown_collaborators"] == 5

    def test_defaults(self):
        response = EgoNetworkResponse(total_collaborators=0, shown_collaborators=0)
        assert response.elements == []
        assert response.focus_person == {}
        assert response.config == {}

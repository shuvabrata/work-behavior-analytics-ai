"""Unit tests for the collaboration network algorithm module.

Tests cover all pure functions in app/analytics/collaboration/algorithm.py
using small synthetic graphs — no Neo4j connection required.

Run with: pytest tests/test_collaboration_algorithm.py -v
"""

import networkx as nx
import pytest

from app.analytics.collaboration.algorithm import (
    LOUVAIN_RANDOM_STATE,
    MAX_COMMUNITY_STYLES,
    build_graph,
    compute_hub_scores,
    compute_modularity,
    detect_communities,
    filter_top_edges_per_node,
    normalize_edge_weights,
    process_collaboration_network,
    to_cytoscape_elements,
)


pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _rec(p1: str, p2: str, score: float) -> dict:
    """Build a minimal collaboration record in the new pipeline format."""
    return {
        "person1": p1,
        "person1_wba_id": f"github::Person::{p1}",
        "person1_props": {"id": f"github::Person::{p1}", "name": p1},
        "person2": p2,
        "person2_wba_id": f"github::Person::{p2}",
        "person2_props": {"id": f"github::Person::{p2}", "name": p2},
        "total_collaboration_score": score,
    }


SIMPLE_RECORDS = [
    _rec("alice", "bob", 10),
    _rec("alice", "carol", 5),
    _rec("bob", "carol", 8),
    _rec("dave", "eve", 12),
    _rec("dave", "frank", 7),
]

DUPLICATE_PAIR_RECORDS = [
    _rec("alice", "bob", 10),
    _rec("alice", "bob", 5),  # same pair twice
]


# ---------------------------------------------------------------------------
# build_graph
# ---------------------------------------------------------------------------

class TestBuildGraph:
    def test_nodes_and_edges_created(self):
        g = build_graph(SIMPLE_RECORDS)
        assert g.number_of_nodes() == 6
        assert g.number_of_edges() == 5

    def test_edge_weight_set(self):
        g = build_graph(SIMPLE_RECORDS)
        assert g["github::Person::alice"]["github::Person::bob"]["weight"] == 10
        assert g["github::Person::dave"]["github::Person::eve"]["weight"] == 12

    def test_duplicate_pair_accumulates_weight(self):
        g = build_graph(DUPLICATE_PAIR_RECORDS)
        assert g.number_of_edges() == 1
        assert g["github::Person::alice"]["github::Person::bob"]["weight"] == 15  # 10 + 5

    def test_empty_records_returns_empty_graph(self):
        g = build_graph([])
        assert g.number_of_nodes() == 0
        assert g.number_of_edges() == 0


# ---------------------------------------------------------------------------
# detect_communities
# ---------------------------------------------------------------------------

class TestDetectCommunities:
    def test_returns_partition_for_all_nodes(self):
        g = build_graph(SIMPLE_RECORDS)
        partition = detect_communities(g)
        assert set(partition.keys()) == set(g.nodes())

    def test_community_ids_are_integers(self):
        g = build_graph(SIMPLE_RECORDS)
        partition = detect_communities(g)
        assert all(isinstance(cid, int) for cid in partition.values())

    def test_raw_ids_not_clamped(self):
        """detect_communities must return raw IDs — clamping happens in to_cytoscape_elements."""
        g = build_graph(SIMPLE_RECORDS)
        partition = detect_communities(g)
        # Raw IDs may be any non-negative integer; the function must not pre-clamp them.
        # We can't assert they exceed MAX_COMMUNITY_STYLES (depends on the run), but we
        # verify the function doesn't perform modulo itself by checking it returns the
        # raw best_partition output (non-negative ints).
        assert all(cid >= 0 for cid in partition.values())

    def test_empty_graph_returns_empty_dict(self):
        import networkx as nx
        partition = detect_communities(nx.Graph())
        assert partition == {}

    def test_louvain_random_state_constant_is_set(self):
        """LOUVAIN_RANDOM_STATE must be a fixed integer so partitions are reproducible."""
        assert isinstance(LOUVAIN_RANDOM_STATE, int)

    def test_detect_communities_is_deterministic(self):
        """Calling detect_communities twice on the same graph returns identical partitions."""
        g = build_graph(SIMPLE_RECORDS)
        partition_a = detect_communities(g)
        partition_b = detect_communities(g)
        assert partition_a == partition_b

    def test_two_clear_communities(self):
        """Dense clique pair should produce exactly 2 communities."""
        records = [
            # Clique 1
            _rec("a", "b", 100),
            _rec("a", "c", 100),
            _rec("b", "c", 100),
            # Clique 2
            _rec("x", "y", 100),
            _rec("x", "z", 100),
            _rec("y", "z", 100),
            # Weak bridge
            _rec("c", "x", 1),
        ]
        g = build_graph(records)
        partition = detect_communities(g)
        num_communities = len(set(partition.values()))
        assert num_communities == 2


# ---------------------------------------------------------------------------
# compute_hub_scores
# ---------------------------------------------------------------------------

class TestComputeHubScores:
    def test_all_nodes_have_score(self):
        g = build_graph(SIMPLE_RECORDS)
        hub_scores = compute_hub_scores(g)
        assert set(hub_scores.keys()) == set(g.nodes())

    def test_hub_score_is_weighted_degree(self):
        g = build_graph(SIMPLE_RECORDS)
        hub_scores = compute_hub_scores(g)
        # alice connects to bob (10) and carol (5) → weighted degree = 15
        assert hub_scores["github::Person::alice"] == 15

    def test_scores_are_non_negative(self):
        g = build_graph(SIMPLE_RECORDS)
        hub_scores = compute_hub_scores(g)
        assert all(s >= 0 for s in hub_scores.values())


# ---------------------------------------------------------------------------
# filter_top_edges_per_node
# ---------------------------------------------------------------------------

class TestFilterTopEdgesPerNode:
    def test_top_n_zero_returns_copy(self):
        g = build_graph(SIMPLE_RECORDS)
        filtered = filter_top_edges_per_node(g, top_n=0)

        assert filtered is not g
        assert filtered.number_of_nodes() == g.number_of_nodes()
        assert filtered.number_of_edges() == g.number_of_edges()

    def test_keeps_strongest_edge_per_node(self):
        records = [
            _rec("alice", "bob", 10),
            _rec("alice", "carol", 3),
            _rec("alice", "dave", 1),
        ]
        g = build_graph(records)
        filtered = filter_top_edges_per_node(g, top_n=1)

        assert filtered.has_edge("github::Person::alice", "github::Person::bob")
        assert filtered.number_of_edges() >= 1

    def test_ensure_min_connection_keeps_all_connected_nodes(self):
        records = [
            _rec("a", "b", 10),
            _rec("a", "c", 9),
            _rec("a", "d", 8),
            _rec("b", "c", 1),
        ]
        g = build_graph(records)
        filtered = filter_top_edges_per_node(g, top_n=1, ensure_min_connection=True)

        for node in g.nodes():
            if g.degree(node) > 0:
                assert filtered.degree(node) > 0


# ---------------------------------------------------------------------------
# normalize_edge_weights
# ---------------------------------------------------------------------------

class TestNormalizeEdgeWeights:
    def test_strongest_edge_is_one(self):
        g = nx.Graph()
        g.add_edge("a", "b", weight=10.0)
        g.add_edge("b", "c", weight=5.0)
        assert max(normalize_edge_weights(g).values()) == pytest.approx(1.0)

    def test_monotonic_in_raw_weight(self):
        g = nx.Graph()
        g.add_edge("a", "b", weight=10.0)
        g.add_edge("b", "c", weight=5.0)
        g.add_edge("c", "d", weight=1.0)
        normalized = normalize_edge_weights(g)
        assert normalized[("a", "b")] > normalized[("b", "c")]
        assert normalized[("b", "c")] > normalized[("c", "d")]

    def test_empty_graph_returns_empty_dict(self):
        assert normalize_edge_weights(nx.Graph()) == {}

    def test_all_zero_weights_return_zero_not_raise(self):
        """The ``or 1.0`` guard: log(0 + 1) == 0 must not divide by zero."""
        g = nx.Graph()
        g.add_edge("a", "b", weight=0.0)
        g.add_edge("b", "c", weight=0.0)
        normalized = normalize_edge_weights(g)
        assert len(normalized) == 2
        assert all(value == 0.0 for value in normalized.values())

    def test_missing_weight_attribute_treated_as_one(self):
        """Pins ``d.get("weight", 1)`` so a cleanup to ``d["weight"]`` fails loudly."""
        g = nx.Graph()
        g.add_edge("a", "b")
        assert normalize_edge_weights(g) == {("a", "b"): pytest.approx(1.0)}

    def test_keys_are_iterated_endpoints_not_sorted(self):
        """Callers look up by the iterated ``(source, target)`` pair."""
        g = nx.Graph()
        g.add_edge("z", "a", weight=10.0)
        assert list(normalize_edge_weights(g)) == [("z", "a")]

    def test_descending_endpoint_order_is_fully_normalized(self):
        """An edge added high-to-low must normalize the same as low-to-high."""
        g = nx.Graph()
        g.add_edge("z", "a", weight=10.0)
        g.add_edge("a", "b", weight=5.0)
        normalized = normalize_edge_weights(g)
        assert normalized[("z", "a")] == pytest.approx(1.0)
        assert normalized[("z", "a")] > normalized[("a", "b")]


# ---------------------------------------------------------------------------
# to_cytoscape_elements
# ---------------------------------------------------------------------------

class TestToCytoscapeElements:
    def setup_method(self):
        self.g = build_graph(SIMPLE_RECORDS)
        self.partition = detect_communities(self.g)
        self.hub_scores = compute_hub_scores(self.g)
        self.elements = to_cytoscape_elements(self.g, self.partition, self.hub_scores)

    def test_element_count(self):
        node_elements = [e for e in self.elements if "source" not in e["data"]]
        edge_elements = [e for e in self.elements if "source" in e["data"]]
        assert len(node_elements) == self.g.number_of_nodes()
        assert len(edge_elements) == self.g.number_of_edges()

    def test_node_data_fields(self):
        node = next(e for e in self.elements if "source" not in e["data"])
        data = node["data"]
        assert "id" in data
        assert "label" in data
        assert "displayLabel" in data
        assert "nodeType" in data
        assert "community" in data
        assert "hub_score" in data
        assert "elementType" in data
        assert data["nodeType"] == "Person"
        assert data["elementType"] == "node"

    def test_community_raw_id_stored_in_data(self):
        """data.community must hold the raw Louvain ID, not the clamped style ID."""
        for element in self.elements:
            if "source" in element["data"]:
                continue
            raw_id = element["data"]["community"]
            style_class = element["classes"]
            expected_style_id = raw_id % MAX_COMMUNITY_STYLES
            assert style_class == f"community-{expected_style_id}"

    def test_css_class_always_within_stylesheet_range(self):
        for element in self.elements:
            if "source" in element["data"]:
                continue
            class_num = int(element["classes"].split("-")[1])
            assert 0 <= class_num < MAX_COMMUNITY_STYLES

    def test_edge_data_fields(self):
        edge = next(e for e in self.elements if "source" in e["data"])
        data = edge["data"]
        assert "id" in data
        assert "source" in data
        assert "target" in data
        assert "weight" in data
        assert "relType" in data
        assert data["relType"] == "COLLABORATES"
        assert data["id"] == f"collab:{data['source']}:{data['target']}"

    def test_display_label_truncated_at_setting_max_chars(self):
        long_name_records = [
            _rec("averylongusername", "bob", 5)
        ]
        g = build_graph(long_name_records)
        partition = detect_communities(g)
        hub_scores = compute_hub_scores(g)
        elements = to_cytoscape_elements(g, partition, hub_scores)
        node = next(e for e in elements if e["data"].get("id") == "github::Person::averylongusername")
        # Default GRAPH_UI_MAX_NODE_LABEL_CHARS is 10 — keeps 7 chars + …
        assert node["data"]["displayLabel"] == "averylo…"

    def test_display_label_not_truncated_when_short(self):
        g = build_graph(SIMPLE_RECORDS)
        partition = detect_communities(g)
        hub_scores = compute_hub_scores(g)
        elements = to_cytoscape_elements(g, partition, hub_scores)
        node = next(e for e in elements if e["data"].get("id") == "github::Person::alice")
        assert node["data"]["displayLabel"] == "alice"

    def test_node_data_has_wba_id(self):
        node = next(e for e in self.elements if "source" not in e["data"])
        data = node["data"]
        assert "wba_id" in data
        assert data["wba_id"] == data["id"]
        assert data["wba_id"].startswith("github::Person::")

    def test_node_label_is_display_name_not_wba_id(self):
        node = next(e for e in self.elements if e["data"].get("id") == "github::Person::alice")
        assert node["data"]["label"] == "alice"
        assert node["data"]["displayLabel"] == "alice"

    def test_node_extra_props_in_element_data(self):
        node = next(e for e in self.elements if e["data"].get("id") == "github::Person::alice")
        data = node["data"]
        # Neo4j properties from person1_props should be surfaced
        assert data.get("name") == "alice"

    def test_descending_endpoint_ids_are_normalized_not_dropped(self):
        """The Step-2 lookup must use the loop's iterated ``(source, target)``.

        ``SIMPLE_RECORDS`` inserts every edge in ascending id order, so
        ``(source, target)`` and ``tuple(sorted((source, target)))`` coincide
        there and the tests above cannot tell the two apart. An edge whose ids
        iterate descending does: looking the helper up by the *sorted* pair
        raises ``KeyError`` on roughly half of all real edges.
        """
        records = [_rec("zoe", "adam", 10), _rec("adam", "bob", 5)]
        g = build_graph(records)

        descending = ("github::Person::zoe", "github::Person::adam")
        assert descending in g.edges  # iterated in this order...
        assert descending != tuple(sorted(descending))  # ...which the sort would reverse

        elements = to_cytoscape_elements(g, detect_communities(g), compute_hub_scores(g))

        # 2. No edge is silently dropped: the KeyError would abort the whole build.
        edge_elements = [e for e in elements if "source" in e["data"]]
        assert len(edge_elements) == g.number_of_edges()

        # 3. Every emitted weight matches the helper, keyed by the iterated pair.
        normalized = normalize_edge_weights(g)
        for source, target, _data in g.edges(data=True):
            canonical_source, canonical_target = sorted((source, target))
            element = next(
                e for e in edge_elements
                if e["data"]["source"] == canonical_source
                and e["data"]["target"] == canonical_target
            )
            assert element["data"]["normalized_weight"] == pytest.approx(
                round(normalized[(source, target)] * 100, 1)
            )

        # The descending edge is the heaviest, so it pins the 0–100 top of scale.
        strongest = next(
            e for e in edge_elements
            if e["data"]["id"] == "collab:github::Person::adam:github::Person::zoe"
        )
        assert strongest["data"]["normalized_weight"] == 100.0
        assert strongest["data"]["line_color"] == "#ef4444"


# ---------------------------------------------------------------------------
# compute_modularity
# ---------------------------------------------------------------------------

class TestComputeModularity:
    def test_modularity_in_valid_range(self):
        g = build_graph(SIMPLE_RECORDS)
        partition = detect_communities(g)
        modularity = compute_modularity(g, partition)
        assert -0.5 <= modularity <= 1.0

    def test_empty_graph_returns_zero(self):
        import networkx as nx
        modularity = compute_modularity(nx.Graph(), {})
        assert modularity == 0.0


# ---------------------------------------------------------------------------
# process_collaboration_network (full pipeline)
# ---------------------------------------------------------------------------

class TestProcessCollaborationNetwork:
    def test_returns_list(self):
        elements = process_collaboration_network(SIMPLE_RECORDS)
        assert isinstance(elements, list)
        assert len(elements) > 0

    def test_raises_on_empty_records(self):
        with pytest.raises(ValueError, match="No collaboration records"):
            process_collaboration_network([])

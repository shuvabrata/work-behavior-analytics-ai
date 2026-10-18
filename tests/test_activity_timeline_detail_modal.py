"""Unit tests for the Activity Timeline event detail modal.

Covers the modal's pure pieces, with no network and no Neo4j: the two-branch
node-properties Cypher and its requested-id keying, the ``MAPS_TO`` pairing, the
label-scoped Graph deep link, the shared property-table renderer, the panel
helpers, and the card/modal payload builders.
"""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import parse_qs, unquote

import pytest
from dash import html

from app.dash_app.components.common import (
    build_element_properties_content,
    render_properties_table,
    render_visible_properties,
)
from app.dash_app.pages.graph.utils import neo4j_to_cytoscape
from app.dash_app.pages.timeline import api as timeline_api
from app.dash_app.pages.timeline import callbacks
from app.dash_app.pages.timeline.api import (
    _NODE_PROPERTIES_CYPHER,
    NodePropertiesError,
    _mapping_id_for,
    fetch_node_properties,
)
from app.dash_app.pages.timeline.helpers import (
    _humanize_event_time,
    _node_pattern,
    detail_payload,
    detail_sentence,
    graph_deep_link,
)
from app.dash_app.pages.timeline.layout import build_event_card

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _join_texts(node: Any) -> str:
    """Concatenate every string rendered under *node* (whitespace-trimmed)."""
    if isinstance(node, str):
        return node
    if isinstance(node, (list, tuple)):
        return " ".join(_join_texts(child) for child in node)
    children = getattr(node, "children", None)
    return _join_texts(children) if children is not None else ""


def _column(node: Any) -> list[str]:
    """Return the key text of every ``details-prop-row`` under *node*."""
    rows: list[str] = []

    def walk(current: Any) -> None:
        if isinstance(current, (list, tuple)):
            for child in current:
                walk(child)
            return
        if getattr(current, "className", None) == "details-prop-row":
            tds = current.children
            rows.append(_join_texts(tds[0]).strip())
            return
        children = getattr(current, "children", None)
        if children is not None:
            walk(children)

    walk(node)
    return rows


def _node(wba_id: str, element_id: str, *, label: str = "Person",
          properties: dict[str, Any] | None = None) -> dict[str, Any]:
    """A ``GraphNode``-shaped dict for the API's ``nodes`` list."""
    return {
        "wba_id": wba_id,
        "elementId": element_id,
        "labels": [label],
        "properties": properties or {},
    }


def _rel(rel_id: str, rel_type: str, start: str, end: str) -> dict[str, Any]:
    """A relationship-shaped dict for the API's ``relationships`` list."""
    return {
        "id": rel_id,
        "type": rel_type,
        "startNode": start,
        "endNode": end,
        "properties": {},
    }


def _graph_response(nodes: list[dict[str, Any]],
                    relationships: list[dict[str, Any]]) -> dict[str, Any]:
    """A ``GraphResponse``-shaped dict (the shape the API's JSON parses to)."""
    return {
        "nodes": nodes,
        "relationships": relationships,
        "isGraph": bool(nodes),
        "resultCount": len(nodes),
        "rawResults": [],
    }


class _FakeResponse:
    """Minimal ``requests.Response`` stand-in for the property fetch."""

    def __init__(self, payload: dict[str, Any], status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def json(self) -> dict[str, Any]:
        return self._payload


def _stub_http(monkeypatch: pytest.MonkeyPatch,
               payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Patch ``requests.post`` and record each call's JSON body."""
    calls: list[dict[str, Any]] = []

    def fake_post(_url: str, *, json: dict[str, Any], timeout: int) -> _FakeResponse:
        calls.append(json)
        return _FakeResponse(payload)

    monkeypatch.setattr(timeline_api.requests, "post", fake_post)
    return calls


def _event(**overrides: Any) -> dict[str, Any]:
    """A timeline event dict with sensible defaults, overridable per test."""
    event: dict[str, Any] = {
        "signal_id": "s1",
        "event_time": "2026-03-15T10:00:00+00:00",
        "relationship_type": "CREATED",
        "summary": "event",
        "entity_type": "PullRequest",
        "source": "github",
        "url": None,
        "details": {},
    }
    event.update(overrides)
    return event


# ---------------------------------------------------------------------------
# The properties Cypher
# ---------------------------------------------------------------------------


def test_node_properties_cypher_has_two_branches_single_union() -> None:
    """Both branches must be present, joined by exactly one UNION."""
    assert "IN $ids" in _NODE_PROPERTIES_CYPHER
    assert "IN $mids" in _NODE_PROPERTIES_CYPHER
    assert "MAPS_TO" in _NODE_PROPERTIES_CYPHER
    assert _NODE_PROPERTIES_CYPHER.count("UNION") == 1


def test_mapping_id_for_translates_only_person_ids() -> None:
    """Only ``::Person::`` ids get a mapping id, and it is same-source."""
    assert (
        _mapping_id_for("confluence::Person::557058:abc")
        == "confluence::IdentityMapping::557058:abc"
    )
    assert _mapping_id_for("github::Repository::a/b") is None
    # The mapping keeps the Person's own source segment (not canonicalised).
    assert _mapping_id_for("jira::Person::x") == "jira::IdentityMapping::x"


# ---------------------------------------------------------------------------
# fetch_node_properties — keyed by the id REQUESTED (Decision 9b)
# ---------------------------------------------------------------------------


def test_fetch_keys_by_requested_id_not_returned_wba_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A deduped Person is keyed by the id asked for, not the node's wba_id."""
    payload = _graph_response(
        [
            _node("jira::Person::557058:abc", "e-p", properties={"name": "Alice"}),
            _node("confluence::IdentityMapping::557058:abc", "e-m",
                  label="IdentityMapping"),
        ],
        [_rel("r1", "MAPS_TO", "e-m", "e-p")],
    )
    calls = _stub_http(monkeypatch, payload)

    result = fetch_node_properties(["confluence::Person::557058:abc"])

    assert list(result) == ["confluence::Person::557058:abc"]
    assert result["confluence::Person::557058:abc"]["wba_id"] == "jira::Person::557058:abc"
    # The returned node's own id must NOT be a key.
    assert "jira::Person::557058:abc" not in result
    # The mapping id travels in the one request, not a second round trip.
    assert len(calls) == 1
    assert calls[0]["parameters"]["mids"] == [
        "confluence::IdentityMapping::557058:abc"
    ]


def test_fetch_returns_both_ids_across_both_branches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One call resolves a branch-1 id and a branch-2 (deduped) id together."""
    payload = _graph_response(
        [
            _node("github::Person::alice", "e-a", properties={"name": "Alice"}),
            _node("jira::Person::557058:abc", "e-p"),
            _node("confluence::IdentityMapping::557058:abc", "e-m",
                  label="IdentityMapping"),
        ],
        [_rel("r1", "MAPS_TO", "e-m", "e-p")],
    )
    calls = _stub_http(monkeypatch, payload)

    result = fetch_node_properties(
        ["github::Person::alice", "confluence::Person::557058:abc"]
    )

    assert set(result) == {"github::Person::alice", "confluence::Person::557058:abc"}
    assert result["github::Person::alice"]["wba_id"] == "github::Person::alice"
    assert result["confluence::Person::557058:abc"]["wba_id"] == "jira::Person::557058:abc"
    assert len(calls) == 1


def test_fetch_absent_id_is_simply_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unresolvable id is absent (no KeyError) so the panel shows "not found"."""
    payload = _graph_response(
        [_node("github::Person::alice", "e-a")], []
    )
    _stub_http(monkeypatch, payload)

    result = fetch_node_properties(["github::Person::alice", "github::Person::missing"])

    assert "github::Person::alice" in result
    assert "github::Person::missing" not in result


def test_fetch_pairs_mappings_by_edge_not_by_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Pairing is by the returned MAPS_TO edge, not by list order.

    Two mapping nodes resolve two distinct Persons, and the edges arrive in the
    reverse of the requested order — a positional pairing would mis-assign them.
    """
    payload = _graph_response(
        [
            _node("jira::Person::X", "ep1"),
            _node("jira::Person::Z", "ep2"),
            _node("confluence::IdentityMapping::X", "em1", label="IdentityMapping"),
            _node("github::IdentityMapping::Z", "em2", label="IdentityMapping"),
        ],
        [
            _rel("r2", "MAPS_TO", "em2", "ep2"),
            _rel("r1", "MAPS_TO", "em1", "ep1"),
        ],
    )
    _stub_http(monkeypatch, payload)

    result = fetch_node_properties(["confluence::Person::X", "github::Person::Z"])

    assert set(result) == {"confluence::Person::X", "github::Person::Z"}
    assert result["confluence::Person::X"]["wba_id"] == "jira::Person::X"
    assert result["github::Person::Z"]["wba_id"] == "jira::Person::Z"


def test_fetch_empty_input_returns_empty_without_a_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An empty id list short-circuits and issues no HTTP call."""
    calls = _stub_http(monkeypatch, _graph_response([], []))
    assert fetch_node_properties([]) == {}
    assert calls == []


# ---------------------------------------------------------------------------
# Panel helpers
# ---------------------------------------------------------------------------


def test_detail_panel_carries_class_and_caption() -> None:
    """Every panel goes through ``_detail_panel`` (Decision 16)."""
    panel = callbacks._detail_panel(html.Div("body"))
    assert panel.className == "timeline-detail-panel"
    first = panel.children[0]
    assert first.className == "timeline-detail-caption"
    assert _join_texts(first) == "Current state"


def test_detail_error_neo4j_disabled_copy(monkeypatch: pytest.MonkeyPatch) -> None:
    """With Neo4j disabled the copy reads as a configuration, not a failure."""
    monkeypatch.setattr(callbacks.settings, "NEO4J_ENABLED", False)

    def boom(_ids: list[str]) -> dict[str, dict[str, Any]]:
        raise NodePropertiesError("HTTP 500")

    monkeypatch.setattr(callbacks, "fetch_node_properties", boom)
    out = callbacks.render_detail_panels(
        {"lane_wba_id": "github::Person::a", "related_wba_id": None}
    )
    assert "Neo4j is not available" in _join_texts(out)


def test_detail_error_query_failure_is_not_called_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An HTTP 500 with Neo4j enabled is a query failure, not a config problem.

    The graph API answers 500 for *any* Cypher runtime error, so the identical
    exception text as the disabled case must not render the disabled-graph copy.
    """
    monkeypatch.setattr(callbacks.settings, "NEO4J_ENABLED", True)

    def boom(_ids: list[str]) -> dict[str, dict[str, Any]]:
        raise NodePropertiesError("HTTP 500")

    monkeypatch.setattr(callbacks, "fetch_node_properties", boom)
    out = callbacks.render_detail_panels(
        {"lane_wba_id": "github::Person::a", "related_wba_id": None}
    )
    text = _join_texts(out)
    assert "Could not load properties for this event." in text
    assert "not available" not in text


def test_detail_error_transport_failure_copy(monkeypatch: pytest.MonkeyPatch) -> None:
    """A transport failure (no HTTP status involved) gets the generic message."""
    monkeypatch.setattr(callbacks.settings, "NEO4J_ENABLED", True)

    def boom(_ids: list[str]) -> dict[str, dict[str, Any]]:
        raise NodePropertiesError("request failed: boom")

    monkeypatch.setattr(callbacks, "fetch_node_properties", boom)
    out = callbacks.render_detail_panels(
        {"lane_wba_id": "github::Person::a", "related_wba_id": None}
    )
    assert "Could not load properties for this event." in _join_texts(out)


def test_render_panels_activity_two_panels_with_connector(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Activity scope renders two panels joined by the neutral connector."""
    nodes = {
        "github::Person::a": {"wba_id": "github::Person::a", "name": "Alice"},
        "github::PullRequest::x": {"wba_id": "github::PullRequest::x", "title": "PR"},
    }
    monkeypatch.setattr(callbacks, "fetch_node_properties", lambda _ids: nodes)
    out = callbacks.render_detail_panels(
        {
            "lane_wba_id": "github::Person::a",
            "related_wba_id": "github::PullRequest::x",
            "relationship": "Created",
        }
    )
    assert out.className == "timeline-detail-grid"
    classes = [
        getattr(child, "className", "") for child in out.children
    ]
    assert classes.count("timeline-detail-panel") == 2
    assert classes.count("timeline-detail-connector") == 1
    # The connector is non-directional (a link icon with the relationship title).
    connector = out.children[1]
    icon = connector.children[0]
    assert icon.className == "fas fa-link"
    assert icon.title == "Created"


def test_render_panels_history_single_panel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """History scope has no other side, so exactly one panel is rendered."""
    monkeypatch.setattr(
        callbacks,
        "fetch_node_properties",
        lambda _ids: {"github::Person::a": {"wba_id": "github::Person::a"}},
    )
    out = callbacks.render_detail_panels(
        {"lane_wba_id": "github::Person::a", "related_wba_id": None}
    )
    assert out.className == "timeline-detail-panel"


def test_render_panels_not_found_state(monkeypatch: pytest.MonkeyPatch) -> None:
    """A missing node degrades to the per-panel "not found" note."""
    monkeypatch.setattr(callbacks, "fetch_node_properties", lambda _ids: {})
    out = callbacks.render_detail_panels(
        {"lane_wba_id": "github::Person::missing", "related_wba_id": None}
    )
    assert "Not found in graph" in _join_texts(out)


# ---------------------------------------------------------------------------
# graph_deep_link / _node_pattern
# ---------------------------------------------------------------------------


def test_node_pattern_person_routes_through_mapping_hop() -> None:
    """A Person id resolves via IdentityMapping + one MAPS_TO hop (Decision 9b)."""
    pattern = _node_pattern("b", "confluence::Person::abc")
    assert "(i_b:IdentityMapping {id: 'confluence::IdentityMapping::abc'})" in pattern
    assert "-[:MAPS_TO]-(b:Person)" in pattern


def test_node_pattern_non_person_is_direct() -> None:
    """A non-Person id is matched directly on its own label + id."""
    pattern = _node_pattern("b", "github::Repository::a/b")
    assert "(b:Repository {id: 'github::Repository::a/b'})" in pattern
    assert "MAPS_TO" not in pattern


def test_graph_deep_link_related_pair_is_label_scoped() -> None:
    """Both labels are derived from the passed ids, and both MATCHes are scoped."""
    url = graph_deep_link(
        "github::PullRequest::org/repo#1", "jira::Issue::ABC-1"
    )
    assert url.startswith("/app/graph?cypher=")
    cypher = unquote(url.split("cypher=", 1)[1])
    assert "MATCH (a:PullRequest {id: 'github::PullRequest::org/repo#1'})" in cypher
    assert "MATCH (b:Issue {id: 'jira::Issue::ABC-1'})" in cypher
    assert "MATCH (a)-[r]-(b) RETURN a, r, b LIMIT 50" in cypher
    # The query round-trips through the query string.
    assert parse_qs(url.split("?", 1)[1])["cypher"] == [cypher]


def test_graph_deep_link_history_lane_only() -> None:
    """Without a sibling the query loads only the lane node and its neighbours."""
    url = graph_deep_link("github::Repository::shuvabrata/work", None)
    cypher = unquote(url.split("cypher=", 1)[1])
    assert "(a:Repository {id: 'github::Repository::shuvabrata/work'})" in cypher
    assert "OPTIONAL MATCH (a)-[r]-(b)" in cypher
    # Only the lane is matched — there is no ``b`` node.
    assert "(b:" not in cypher
    assert parse_qs(url.split("?", 1)[1])["cypher"] == [cypher]


def test_graph_deep_link_deduped_person_sibling_uses_hop() -> None:
    """The Graph link for a deduped Person sibling contains the mapping hop.

    This is the pin that keeps the link from opening an empty canvas.
    """
    url = graph_deep_link(
        "confluence::Page::26705923", "confluence::Person::557058:abc"
    )
    cypher = unquote(url.split("cypher=", 1)[1])
    assert "confluence::IdentityMapping::557058:abc" in cypher
    assert "-[:MAPS_TO]-(b:Person)" in cypher


# ---------------------------------------------------------------------------
# Shared table renderer (Decision 5)
# ---------------------------------------------------------------------------


def test_render_properties_table_matches_panel_builder_rows() -> None:
    """The modal's table and the graph panel's table come from the same renderer."""
    data = {
        "elementType": "node",
        "wba_id": "github::Person::alice",
        "id": "e1",
        "label": "Alice Johnson",
        "nodeType": "Person",
        "name": "Alice Johnson",
        "email": None,
        "_display_name": "Alice",
    }
    items = [("id", "github::Person::alice"), ("name", "Alice Johnson")]

    modal_rows = _column(render_properties_table(items))
    panel_rows = _column(build_element_properties_content(data))

    assert modal_rows == panel_rows == ["id", "name"]


def test_render_visible_properties_hides_private_and_none() -> None:
    """Private keys and None values are hidden; an ``id`` row is injected first."""
    rows = _column(
        render_visible_properties(
            {
                "wba_id": "github::Person::alice",
                "name": "Alice Johnson",
                "email": None,
                "_display_name": "Alice",
            }
        )
    )
    assert rows == ["id", "name"]


def test_render_visible_properties_empty_state() -> None:
    """A node with nothing visible (and no id) renders the muted empty state."""
    out = render_visible_properties({"name": None, "_display_name": "x"})
    assert _join_texts(out) == "No properties"


# ---------------------------------------------------------------------------
# detail_sentence
# ---------------------------------------------------------------------------


def test_detail_sentence_subject_relationship_object() -> None:
    """The sentence is subject + humanized relationship + the other side's name."""
    sentence = detail_sentence(
        _event(relationship_type="CREATED", related_name="Fix the bug"),
        "Alice Johnson",
    )
    assert sentence == "Alice Johnson Created Fix the bug"


def test_detail_sentence_falls_back_to_entity_type() -> None:
    """With no relationship the type label stands in for the verb."""
    sentence = detail_sentence(
        {"relationship_type": "", "entity_type": "File", "summary": None},
        "Alice Johnson",
    )
    assert sentence == "Alice Johnson File"


def test_detail_sentence_never_empty() -> None:
    """An information-free event still yields a renderable fragment."""
    assert detail_sentence({}, "") == "Event"


def test_detail_sentence_history_names_lane_once() -> None:
    """History drops the summary fallback so the lane's name is not repeated."""
    sentence = detail_sentence(
        {"relationship_type": "STATE_CHANGE", "summary": "Alice Johnson"},
        "Alice Johnson",
        scope="history",
    )
    assert sentence == "Alice Johnson Updated"
    assert sentence.count("Alice Johnson") == 1


# ---------------------------------------------------------------------------
# detail_payload
# ---------------------------------------------------------------------------


def test_detail_payload_activity_carries_sibling() -> None:
    """Activity scope carries the sibling's canonical id and a Graph link."""
    payload = detail_payload(
        _event(related_wba_id="github::PullRequest::org/repo#1"),
        "Alice Johnson",
        "github::Person::alice",
        "Mar 15, 2026 2:30 PM",
        "activity",
    )
    assert payload["related_wba_id"] == "github::PullRequest::org/repo#1"
    assert payload["lane_wba_id"] == "github::Person::alice"
    assert payload["scope"] == "activity"
    # The lane's own type is NOT a payload key (Decision 7b).
    assert "lane_entity_type" not in payload
    # No nonce (Decision 17) and JSON-serializable.
    assert "nonce" not in payload
    json.dumps(payload)


def test_detail_payload_history_has_no_sibling() -> None:
    """History has no other side, so the sibling id is None."""
    payload = detail_payload(
        {"relationship_type": "STATE_CHANGE", "summary": "Alice Johnson"},
        "Alice Johnson",
        "github::Person::alice",
        "Mar 15, 2026 2:30 PM",
        "history",
    )
    assert payload["related_wba_id"] is None


def test_detail_payload_title_names_the_object() -> None:
    """The header names the object — the modal completes the card's sentence.

    The header's last segment is now a *duration* relative to now, so this test
    asserts on the deterministic prefix rather than the clock-dependent suffix.
    """
    payload = detail_payload(
        _event(relationship_type="CREATED_BY", related_name="Plan document"),
        "Alice Johnson",
        "github::Person::alice",
        "Mar 15, 2026 2:30 PM",
        "activity",
    )
    assert payload["object_name"] == "Plan document"
    assert payload["title"].startswith(
        "Alice Johnson  ·  Created By  ·  Plan document  ·  "
    )
    assert "Mar 15, 2026" not in payload["title"]


def test_detail_payload_history_title_names_the_lane_once() -> None:
    """History's summary is the lane's OWN name, so the object stays empty."""
    payload = detail_payload(
        {"relationship_type": "STATE_CHANGE", "summary": "Alice Johnson"},
        "Alice Johnson",
        "github::Person::alice",
        "Mar 15, 2026 2:30 PM",
        "history",
    )
    assert payload["object_name"] == ""
    assert payload["title"].count("Alice Johnson") == 1
    assert "Mar 15, 2026" not in payload["title"]


def test_detail_payload_title_omits_missing_parts() -> None:
    """An unknown object drops cleanly — no doubled or trailing separator."""
    payload = detail_payload(
        _event(relationship_type="CREATED_BY", summary=""),
        "Alice Johnson",
        "github::Person::alice",
        "Mar 15, 2026 2:30 PM",
        "activity",
    )
    assert payload["object_name"] == ""
    assert payload["title"].startswith("Alice Johnson  ·  Created By  ·  ")
    assert "Mar 15, 2026" not in payload["title"]


def test_detail_payload_exact_time_is_carried_separately() -> None:
    """The exact time the header demotes to small text travels as its own key."""
    payload = detail_payload(
        _event(relationship_type="CREATED_BY", related_name="Plan document"),
        "Alice Johnson",
        "github::Person::alice",
        "Mar 15, 2026 2:30 PM",
        "activity",
    )
    assert payload["datetime_exact"] == "Mar 15, 2026 2:30 PM"
    assert payload["datetime_exact"] == payload["datetime"]


def test_humanize_event_time_handles_bad_input() -> None:
    """Garbage timestamps yield "" so the header omits the duration cleanly."""
    assert _humanize_event_time(None) == ""
    assert _humanize_event_time("") == ""
    assert _humanize_event_time("not-a-date") == ""


def test_detail_payload_identical_events_are_equal() -> None:
    """Two payloads from the same event compare equal (no per-click nonce)."""
    event = _event(related_wba_id="github::PullRequest::x")
    args = ("Alice Johnson", "github::Person::alice", "Mar 15, 2026 2:30 PM", "activity")
    assert detail_payload(event, *args) == detail_payload(event, *args)


# ---------------------------------------------------------------------------
# detail_payload — the narrow mock fallback (Decision 15)
# ---------------------------------------------------------------------------


def test_mock_sibling_is_well_formed_activity() -> None:
    """A mock lane with a sibling type yields the exact three-segment placeholder."""
    payload = detail_payload(
        _event(entity_type="PullRequest", related_wba_id=None),
        "Alice Johnson",
        "mock::Person::alice",
        "Mar 15, 2026 2:30 PM",
        "activity",
    )
    assert payload["related_wba_id"] == "mock::PullRequest::mock-other"


def test_mock_sibling_does_not_fire_in_history() -> None:
    """The mock fallback must not invent a sibling in history scope (Decision 11)."""
    payload = detail_payload(
        _event(entity_type="PullRequest", related_wba_id=None),
        "Alice Johnson",
        "mock::Person::alice",
        "Mar 15, 2026 2:30 PM",
        "history",
    )
    assert payload["related_wba_id"] is None


def test_mock_sibling_does_not_fire_for_real_lanes() -> None:
    """The mock fallback is gated on ``mock::`` and never fires for real data."""
    payload = detail_payload(
        _event(entity_type="PullRequest", related_wba_id=None),
        "Alice Johnson",
        "github::Person::alice",
        "Mar 15, 2026 2:30 PM",
        "activity",
    )
    assert payload["related_wba_id"] is None


# ---------------------------------------------------------------------------
# The card is a keyboard-reachable modal trigger
# ---------------------------------------------------------------------------


def test_build_event_card_is_a_modal_trigger() -> None:
    """The card is a ``role="button"`` div carrying both JSON payloads."""
    card = build_event_card(
        _event(related_wba_id="github::PullRequest::x"),
        "",
        "#3B82F6",
        scope="activity",
        lane_label="Alice Johnson",
        lane_wba_id="github::Person::alice",
    )
    assert isinstance(card, html.Div)
    props = card.to_plotly_json()["props"]
    assert props["role"] == "button"
    assert props["tabIndex"] == 0
    assert "data-timeline-event" in props
    assert "data-timeline-detail" in props
    # Both payloads are valid JSON.
    json.loads(props["data-timeline-event"])
    detail = json.loads(props["data-timeline-detail"])
    assert detail["lane_wba_id"] == "github::Person::alice"


def test_cytoscape_transform_shape_is_what_the_fetch_expects() -> None:
    """Sanity: ``neo4j_to_cytoscape`` yields the node/edge element shape used."""
    elements = neo4j_to_cytoscape(
        _graph_response(
            [_node("github::Person::alice", "e-a")],
            [_rel("r1", "MAPS_TO", "e-a", "e-b")],
        )
    )
    groups = [element["group"] for element in elements]
    assert groups == ["nodes", "edges"]
    assert elements[0]["data"]["wba_id"] == "github::Person::alice"
    assert elements[1]["data"]["relType"] == "MAPS_TO"

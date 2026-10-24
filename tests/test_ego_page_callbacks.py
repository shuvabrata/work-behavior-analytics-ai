"""Tests for the per-person page's URL-driven collaborator cap.

The Analytics card carries a Collaborator Cap; the page must honour it on
navigation without clobbering a choice the user makes in the page's own
selector afterwards.
"""

from __future__ import annotations

from typing import Any

import pytest
from dash import no_update

from app.analytics.collaboration.ego import DEFAULT_MAX_COLLABORATORS
from app.api.graph.v1.model import EgoNetworkResponse
from app.dash_app.pages.collaboration_network_ego.callbacks import filter as ego_filter


pytestmark = pytest.mark.unit

PAGE = "/app/collaboration/person"
PERSON = "github::Person::focus"


class _FakeCtx:
    """Stands in for dash.ctx so the load callback can dispatch on triggered."""

    def __init__(self, prop_ids: list[str]) -> None:
        self.triggered = [{"prop_id": prop_id} for prop_id in prop_ids]


def _response() -> EgoNetworkResponse:
    return EgoNetworkResponse(
        elements=[
            {"data": {"id": PERSON, "elementType": "node", "role": "focus", "label": "Focus"}}
        ],
        focus_person={"id": PERSON, "label": "Focus"},
        total_collaborators=7,
        shown_collaborators=3,
        config={"lookback_days": 90, "enabled_layers": ["reporter_assignee"]},
    )


def _stub_service(monkeypatch) -> dict[str, Any]:
    """Replace the Neo4j-backed service with a recording stub."""
    captured: dict[str, Any] = {}

    def fake_get(focus_id: str, config: Any = None, max_collaborators: Any = None) -> EgoNetworkResponse:
        captured["focus_id"] = focus_id
        captured["max_collaborators"] = max_collaborators
        return _response()

    monkeypatch.setattr(ego_filter, "get_ego_network", fake_get)
    return captured


def test_parse_max_collaborators_defaults_when_absent():
    assert ego_filter._parse_max_collaborators(None) == DEFAULT_MAX_COLLABORATORS
    assert ego_filter._parse_max_collaborators("") == DEFAULT_MAX_COLLABORATORS


def test_parse_max_collaborators_reads_value():
    assert ego_filter._parse_max_collaborators("50") == 50
    assert ego_filter._parse_max_collaborators(" 100 ") == 100


def test_parse_max_collaborators_handles_junk_and_zero():
    assert ego_filter._parse_max_collaborators("not-a-number") == DEFAULT_MAX_COLLABORATORS
    # The API requires >= 1, so clamp rather than send an invalid value.
    assert ego_filter._parse_max_collaborators("0") == 1


def test_url_cap_is_fetched_and_reflected_in_page_selector(monkeypatch):
    captured = _stub_service(monkeypatch)
    monkeypatch.setattr(ego_filter, "ctx", _FakeCtx(["url.search"]))

    result = ego_filter.load_ego_network(PERSON, "?max_collaborators=50", PAGE, 50)

    assert captured["max_collaborators"] == 50
    assert result[-1] == 50, "the page selector should adopt the card's cap"


def test_absent_cap_uses_api_default_and_leaves_selector(monkeypatch):
    captured = _stub_service(monkeypatch)
    monkeypatch.setattr(ego_filter, "ctx", _FakeCtx(["url.search"]))

    result = ego_filter.load_ego_network(PERSON, "", PAGE, DEFAULT_MAX_COLLABORATORS)

    assert captured["max_collaborators"] == DEFAULT_MAX_COLLABORATORS
    assert result[-1] is no_update


def test_person_pick_does_not_override_page_selector(monkeypatch):
    """A person pick still fetches with the URL cap, but must not reset the
    selector the user may have changed on the page."""
    captured = _stub_service(monkeypatch)
    monkeypatch.setattr(
        ego_filter,
        "ctx",
        _FakeCtx(['{"type": "catalog-person-value", "name": "ego_focus"}.data']),
    )

    result = ego_filter.load_ego_network(PERSON, "?max_collaborators=50", PAGE, 25)

    assert captured["max_collaborators"] == 50
    assert result[-1] is no_update


def test_success_path_renders_no_summary_banner(monkeypatch):
    """The per-person page shows no focus/lookback/collaborator summary badge."""
    _stub_service(monkeypatch)
    monkeypatch.setattr(ego_filter, "ctx", _FakeCtx(["url.search"]))

    result = ego_filter.load_ego_network(PERSON, "", PAGE, DEFAULT_MAX_COLLABORATORS)

    banner_children, banner_style = result[2], result[3]
    assert banner_children == []
    assert banner_style["display"] == "none"


def test_error_path_still_renders_an_alert(monkeypatch):
    """Removing the summary must not remove the error feedback region."""
    def boom(*_args: Any, **_kwargs: Any) -> EgoNetworkResponse:
        raise ValueError("No collaborations found for person 'x'.")

    monkeypatch.setattr(ego_filter, "get_ego_network", boom)
    monkeypatch.setattr(ego_filter, "ctx", _FakeCtx(["url.search"]))

    result = ego_filter.load_ego_network(PERSON, "", PAGE, DEFAULT_MAX_COLLABORATORS)

    assert result[2] != [], "an error alert should be rendered"
    assert result[3]["display"] == "block", "the error alert should be visible"


def test_options_only_offer_what_was_fetched(monkeypatch):
    """The selector may not offer a cap the current element set cannot honour."""
    _stub_service(monkeypatch)
    monkeypatch.setattr(ego_filter, "ctx", _FakeCtx(["url.search"]))

    result = ego_filter.load_ego_network(PERSON, "?max_collaborators=25", PAGE, 25)

    offered = {option["value"] for option in result[-2]}
    assert offered == {10, 25}


def test_options_include_a_non_canonical_fetched_cap(monkeypatch):
    """A fetched cap outside COLLABORATOR_CAP_OPTIONS is still offered."""
    _stub_service(monkeypatch)
    monkeypatch.setattr(ego_filter, "ctx", _FakeCtx(["url.search"]))

    result = ego_filter.load_ego_network(PERSON, "?max_collaborators=30", PAGE, 30)

    offered = {option["value"] for option in result[-2]}
    assert offered == {10, 25, 30}


def test_stale_selection_is_clamped_into_range(monkeypatch):
    """A selection above the fetched cap is pulled back into the offered range."""
    _stub_service(monkeypatch)
    monkeypatch.setattr(
        ego_filter,
        "ctx",
        _FakeCtx(['{"type": "catalog-person-value", "name": "ego_focus"}.data']),
    )

    result = ego_filter.load_ego_network(PERSON, "?max_collaborators=10", PAGE, 100)

    assert result[-1] == 10
    assert 10 in {option["value"] for option in result[-2]}


def test_other_routes_are_ignored():
    from dash.exceptions import PreventUpdate

    with pytest.raises(PreventUpdate):
        ego_filter.load_ego_network(PERSON, "", "/app/collaboration", DEFAULT_MAX_COLLABORATORS)

"""Tests for the per-person page's URL-driven collaborator cap.

The Analytics card carries a Collaborator Cap; the page must honour it on
navigation without clobbering a choice the user makes in the page's own
selector afterwards.
"""

from __future__ import annotations

from typing import Any

import pytest
from dash import no_update
from dash.exceptions import PreventUpdate

from app.analytics.collaboration.ego import cap_options_for
from app.api.graph.v1.model import EgoNetworkResponse
from app.common.person_network_url import DEFAULT_MAX_COLLABORATORS
from app.dash_app.pages.collaboration_network_ego.callbacks import filter as ego_filter


pytestmark = pytest.mark.unit

PAGE = "/app/collaboration/person"
PERSON = "github::Person::focus"


def _response() -> EgoNetworkResponse:
    return EgoNetworkResponse(
        elements=[
            {"data": {"id": PERSON, "elementType": "node", "role": "focus", "label": "Focus"}}
        ],
        total_collaborators=7,
        shown_collaborators=3,
        config={"lookback_days": 90, "enabled_layers": ["reporter_assignee"]},
    )


def _cap_options(fetched: int) -> list[dict[str, Any]]:
    """The radio options the page offers for a given fetched cap."""
    return cap_options_for(fetched)


def _star_elements(spokes: int) -> list[dict[str, Any]]:
    """A focus node plus ``spokes`` collaborators of distinct ascending weights."""
    elements: list[dict[str, Any]] = [
        {"data": {"id": PERSON, "elementType": "node", "role": "focus", "label": "Focus"}}
    ]
    for index in range(spokes):
        spoke_id = f"github::Person::spoke{index}"
        elements.append(
            {"data": {"id": spoke_id, "elementType": "node", "role": "collaborator", "label": spoke_id}}
        )
        elements.append(
            {
                "data": {
                    "id": f"edge-{index}",
                    "source": PERSON,
                    "target": spoke_id,
                    "weight": index + 1,
                    "normalized_weight": index + 1,
                }
            }
        )
    return elements


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

    result = ego_filter.load_ego_network(PERSON, "?max_collaborators=50", PAGE, 50, [])

    assert captured["max_collaborators"] == 50
    assert result[-1] == 50, "the page selector should adopt the card's cap"


def test_absent_cap_uses_api_default_and_leaves_selector(monkeypatch):
    captured = _stub_service(monkeypatch)

    result = ego_filter.load_ego_network(
        PERSON, "", PAGE, DEFAULT_MAX_COLLABORATORS, []
    )

    assert captured["max_collaborators"] == DEFAULT_MAX_COLLABORATORS
    assert result[-1] is no_update


def test_person_pick_does_not_override_page_selector(monkeypatch):
    """A person pick still fetches with the URL cap, but must not reset the
    selector the user may have changed on the page."""
    captured = _stub_service(monkeypatch)

    result = ego_filter.load_ego_network(
        PERSON, "?max_collaborators=50", PAGE, 25, [{"data": {"id": "loaded"}}]
    )

    assert captured["max_collaborators"] == 50
    assert result[-1] is no_update


def test_success_path_renders_no_summary_banner(monkeypatch):
    """The per-person page shows no focus/lookback/collaborator summary badge."""
    _stub_service(monkeypatch)

    result = ego_filter.load_ego_network(
        PERSON, "", PAGE, DEFAULT_MAX_COLLABORATORS, []
    )

    banner_children, banner_style = result[2], result[3]
    assert banner_children == []
    assert banner_style["display"] == "none"


def test_error_path_still_renders_an_alert(monkeypatch):
    """Removing the summary must not remove the error feedback region."""
    def boom(*_args: Any, **_kwargs: Any) -> EgoNetworkResponse:
        raise ValueError("No collaborations found for person 'x'.")

    monkeypatch.setattr(ego_filter, "get_ego_network", boom)

    result = ego_filter.load_ego_network(
        PERSON, "", PAGE, DEFAULT_MAX_COLLABORATORS, []
    )

    assert result[2] != [], "an error alert should be rendered"
    assert result[3]["display"] == "block", "the error alert should be visible"


def test_options_only_offer_what_was_fetched(monkeypatch):
    """The selector may not offer a cap the current element set cannot honour."""
    _stub_service(monkeypatch)

    result = ego_filter.load_ego_network(
        PERSON, "?max_collaborators=25", PAGE, 25, []
    )

    offered = {option["value"] for option in result[-2]}
    assert offered == {10, 25}


def test_options_include_a_non_canonical_fetched_cap(monkeypatch):
    """A fetched cap outside COLLABORATOR_CAP_OPTIONS is still offered."""
    _stub_service(monkeypatch)

    result = ego_filter.load_ego_network(
        PERSON, "?max_collaborators=30", PAGE, 30, []
    )

    offered = {option["value"] for option in result[-2]}
    assert offered == {10, 25, 30}


def test_stale_selection_is_clamped_into_range(monkeypatch):
    """A selection above the fetched cap is pulled back into the offered range."""
    _stub_service(monkeypatch)

    result = ego_filter.load_ego_network(
        PERSON, "?max_collaborators=10", PAGE, 100, [{"data": {"id": "loaded"}}]
    )

    assert result[-1] == 10
    assert 10 in {option["value"] for option in result[-2]}


def test_other_routes_are_ignored():
    from dash.exceptions import PreventUpdate

    with pytest.raises(PreventUpdate):
        ego_filter.load_ego_network(
            PERSON, "", "/app/collaboration", DEFAULT_MAX_COLLABORATORS, []
        )


# ---------------------------------------------------------------------------
# Clearing the filters must write a cap the radio actually offers
# ---------------------------------------------------------------------------

def test_reset_cap_uses_default_when_offered():
    """The ordinary case is unchanged: 25 is offered, so 25 is the reset."""
    options = _cap_options(50)
    assert ego_filter._reset_cap(options) == DEFAULT_MAX_COLLABORATORS


@pytest.mark.parametrize("fetched", [10, 30, 137])
def test_reset_cap_falls_back_to_the_fetched_ceiling(fetched):
    """The reset must always be a value the radio offers.

    With 10 collaborators fetched the static default 25 is not on the menu, so
    writing it would leave the radio rendered blank.
    """
    options = _cap_options(fetched)
    offered = {option["value"] for option in options}

    reset = ego_filter._reset_cap(options)

    assert reset in offered, "the reset must be an offered cap"
    if fetched == 10:
        assert reset == 10, "the only legal reset for a fetched 10 is 10"


def test_reset_cap_handles_no_options():
    """Before the first load populates the options, fall back to the default."""
    assert ego_filter._reset_cap(None) == DEFAULT_MAX_COLLABORATORS
    assert ego_filter._reset_cap([]) == DEFAULT_MAX_COLLABORATORS


def test_clear_ego_filters_returns_an_offered_cap():
    """End-to-end through the callback: the reset cap is offered and truthy."""
    options = _cap_options(10)
    offered = {option["value"] for option in options}

    weight, cap = ego_filter.clear_ego_filters(1, options)

    assert weight == 0
    assert cap in offered
    assert cap is not None and cap > 0, "a None/zero cap would disable the filter"


# ---------------------------------------------------------------------------
# The page's first fetch must adopt the URL cap (the elements store is empty)
# ---------------------------------------------------------------------------

def test_first_fetch_adopts_the_url_cap(monkeypatch):
    """The page's first fetch must adopt the card's cap.

    The trigger here is deliberately NON-empty: a real browser sends the person
    picker's store transition on arrival, because the picker seeds its
    ``catalog-person-value`` store as the page mounts and Dash counts that as an
    Input change. An earlier fix keyed on ``not ctx.triggered`` and therefore
    never fired in the browser — this test reproduces the real payload instead of
    the empty-trigger state the app never enters.

    An empty elements store is what identifies the first fetch.
    """
    captured = _stub_service(monkeypatch)

    result = ego_filter.load_ego_network(
        PERSON, "?max_collaborators=50", PAGE, DEFAULT_MAX_COLLABORATORS, []
    )

    assert result[-1] == 50, "the page must open at the cap the card asked for"
    assert captured["max_collaborators"] == 50, "the fetch must use the card's cap"


def test_initial_load_adopts_the_url_cap(monkeypatch):
    """The initial call, with an empty trigger, also adopts the cap."""
    _stub_service(monkeypatch)

    result = ego_filter.load_ego_network(
        PERSON, "?max_collaborators=50", PAGE, DEFAULT_MAX_COLLABORATORS, []
    )

    assert result[-1] == 50, "the page must open at the cap the card asked for"


def test_initial_load_without_a_cap_leaves_the_selector(monkeypatch):
    """An initial load with no cap in the URL must not rewrite the selector."""
    _stub_service(monkeypatch)

    result = ego_filter.load_ego_network(
        PERSON, "", PAGE, DEFAULT_MAX_COLLABORATORS, []
    )

    assert result[-1] is no_update


def test_person_pick_still_does_not_override_page_selector(monkeypatch):
    """A person pick must not clobber the cap, at the URL cap or below it."""
    _stub_service(monkeypatch)
    loaded = [{"data": {"id": "loaded"}}]

    at_url_cap = ego_filter.load_ego_network(
        PERSON, "?max_collaborators=50", PAGE, 50, loaded
    )
    below_it = ego_filter.load_ego_network(
        PERSON, "?max_collaborators=50", PAGE, 10, loaded
    )

    assert at_url_cap[-1] is no_update
    assert below_it[-1] is no_update


# ---------------------------------------------------------------------------
# Clearing the filters redraws the plot with the cap applied
# ---------------------------------------------------------------------------

def test_clearing_filters_redraws_the_plot_with_the_cap_applied():
    """Regression pin: the cap the reset writes is the cap the redraw applies.

    The clear->redraw hand-off is Dash's job (apply_ego_filters takes the cap as
    an Input); the two callbacks are exercised separately here, feeding the
    reset's cap output into the filter's cap input.
    """
    elements = _star_elements(50)
    options = _cap_options(50)

    _, reset_cap = ego_filter.clear_ego_filters(1, options)
    drawn = ego_filter.apply_ego_filters(elements, 0, reset_cap)

    drawn_nodes = [e for e in drawn if e["data"].get("source") is None]
    drawn_spokes = [n for n in drawn_nodes if n["data"].get("role") != "focus"]
    drawn_ids = {n["data"]["id"] for n in drawn_spokes}
    expected = {f"github::Person::spoke{i}" for i in range(25, 50)}

    assert len(drawn_spokes) == 25, "exactly the top-25 spokes should survive"
    assert drawn_ids == expected
    assert any(n["data"].get("role") == "focus" for n in drawn_nodes), "focus retained"


# ---------------------------------------------------------------------------
# Deep linking: ?person=<wba_id> focuses the page on one Person
# ---------------------------------------------------------------------------

def _deep_link(wba_id: str, cap: int | None = None) -> str:
    """Build the documented deep link and return just its query string."""
    from urllib.parse import urlsplit

    from app.common.person_network_url import build_person_network_url

    return "?" + urlsplit(build_person_network_url(wba_id, cap)).query


def test_deep_link_loads_the_named_person_when_the_picker_is_empty(monkeypatch):
    """A component can link straight to one person's network with no picker use."""
    captured = _stub_service(monkeypatch)

    ego_filter.load_ego_network(None, _deep_link(PERSON, 50), PAGE, 50, [])

    assert captured["focus_id"] == PERSON
    assert captured["max_collaborators"] == 50


def test_picker_value_wins_over_a_stale_url(monkeypatch):
    """A user's pick must not be overridden by the person still in the URL."""
    captured = _stub_service(monkeypatch)
    picked = "github::Person::picked"

    ego_filter.load_ego_network(
        {"wba": picked}, _deep_link(PERSON), PAGE, 25, []
    )

    assert captured["focus_id"] == picked


def test_malformed_person_in_url_shows_the_prompt_not_a_query(monkeypatch):
    """A bad deep link must not query with a bad id."""
    captured = _stub_service(monkeypatch)

    result = ego_filter.load_ego_network(None, "?person=not-a-wba-id", PAGE, 25, [])

    assert captured == {}, "no service call for an unparseable person"
    assert result[4]["display"] == "block", "the empty-state prompt is shown"


def test_url_without_a_person_still_prompts(monkeypatch):
    captured = _stub_service(monkeypatch)

    result = ego_filter.load_ego_network(None, "?max_collaborators=50", PAGE, 25, [])

    assert captured == {}
    assert result[4]["display"] == "block"


# ---------------------------------------------------------------------------
# URL sync: the address bar follows the picker
# ---------------------------------------------------------------------------

def test_sync_writes_the_picked_person_into_the_url():
    updated = ego_filter.sync_person_to_url(
        {"wba": PERSON}, "?lookback_days=30", PAGE
    )

    assert PERSON.split("::")[-1] in updated
    assert "lookback_days=30" in updated, "settings must survive the rewrite"


def test_sync_accepts_a_plain_string_value():
    """The shared picker stores a dict, but a bare id must also work."""
    updated = ego_filter.sync_person_to_url(PERSON, "", PAGE)

    assert updated is not None and updated.startswith("?")


def test_sync_removes_the_person_when_the_picker_is_cleared():
    updated = ego_filter.sync_person_to_url(
        None, "?person=github%3A%3APerson%3Aold&lookback_days=30", PAGE
    )

    assert "person" not in updated
    assert "lookback_days=30" in updated


def test_sync_is_a_no_op_when_the_url_already_matches():
    """Emitting an unchanged URL would re-trigger the loader and re-query."""
    already = _deep_link(PERSON)

    assert ego_filter.sync_person_to_url({"wba": PERSON}, already, PAGE) is no_update


def test_sync_ignores_other_pages():
    with pytest.raises(PreventUpdate):
        ego_filter.sync_person_to_url({"wba": PERSON}, "", "/app/graph")


# ---------------------------------------------------------------------------
# Deep-link seeding: the picker reflects the URL on arrival
# ---------------------------------------------------------------------------

def test_seed_renders_the_chip_for_a_deep_linked_person():
    result = ego_filter.seed_person_from_url(_deep_link(PERSON), PAGE, None)

    chip_children, chip_style, search_style, suggestions_style, stored = result
    assert chip_children != []
    assert chip_style["display"] == "flex"
    assert search_style["display"] == "none"
    assert suggestions_style["display"] == "none"
    assert stored == {"wba": PERSON, "display": PERSON.split("::")[-1]}


def test_seed_never_overwrites_an_existing_selection():
    with pytest.raises(PreventUpdate):
        ego_filter.seed_person_from_url(_deep_link(PERSON), PAGE, {"wba": "github::Person::picked"})


def test_seed_ignores_a_url_with_no_person():
    with pytest.raises(PreventUpdate):
        ego_filter.seed_person_from_url("?max_collaborators=50", PAGE, None)


def test_seed_ignores_other_pages():
    with pytest.raises(PreventUpdate):
        ego_filter.seed_person_from_url(_deep_link(PERSON), "/app/graph", None)

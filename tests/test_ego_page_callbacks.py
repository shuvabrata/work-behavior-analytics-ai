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

from domain.collaboration.ego_metadata import cap_options_for
from domain.collaboration.errors import CollaborationDataUnavailable
from app.api.graph.v1.model import EgoNetworkResponse
from domain.person_network_url import DEFAULT_MAX_COLLABORATORS
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
        raise ValueError("some genuinely invalid input")

    monkeypatch.setattr(ego_filter, "get_ego_network", boom)

    result = ego_filter.load_ego_network(
        PERSON, "", PAGE, DEFAULT_MAX_COLLABORATORS, []
    )

    assert result[2] != [], "an error alert should be rendered"
    assert result[3]["display"] == "block", "the error alert should be visible"


def test_no_collaborators_renders_a_warning_not_a_settings_error(monkeypatch):
    """An empty result is a warning about the person, not a settings problem.

    Regression guard: this case used to surface as a ``ValueError`` and be
    rendered by ``describe_config_error``, so a person with no collaborators
    was told "one of the settings in the link is not a valid value". The two
    outcomes are now distinct exception types.
    """
    def no_data(*_args: Any, **_kwargs: Any) -> EgoNetworkResponse:
        raise CollaborationDataUnavailable(
            "No collaborations found for person 'x' in this window."
        )

    monkeypatch.setattr(ego_filter, "get_ego_network", no_data)

    result = ego_filter.load_ego_network(
        PERSON, "", PAGE, DEFAULT_MAX_COLLABORATORS, []
    )

    alerts = result[2]
    assert len(alerts) == 1, "a single warning banner is rendered"
    assert alerts[0].color == "warning", "an empty result is not a danger/error"
    assert result[3]["display"] == "block", "the warning must be visible"

    text = str(alerts[0].children)
    assert "No collaborators found" in text
    assert PERSON in text, "the message names the person"
    assert "90 days" in text, "the active window is named"
    assert "not a valid value" not in text, "the settings text must not appear"
    assert "Please check the numbers" not in text


def test_no_collaborators_keeps_the_picker_prompt_hidden(monkeypatch):
    """A person *is* selected, so the "pick a person" prompt must stay hidden."""
    def no_data(*_args: Any, **_kwargs: Any) -> EgoNetworkResponse:
        raise CollaborationDataUnavailable("none")

    monkeypatch.setattr(ego_filter, "get_ego_network", no_data)

    result = ego_filter.load_ego_network(
        PERSON, "", PAGE, DEFAULT_MAX_COLLABORATORS, []
    )

    assert result[4]["display"] == "none", "the empty-state prompt is not shown"


def test_settings_error_keeps_the_settings_message(monkeypatch):
    """The genuine settings path must keep the config sentence, not the warning.

    Pins the other half of the split: a real ValueError still routes through
    ``describe_config_error``.
    """
    def bad_config(*_args: Any, **_kwargs: Any) -> EgoNetworkResponse:
        raise ValueError("boom")

    monkeypatch.setattr(ego_filter, "get_ego_network", bad_config)

    result = ego_filter.load_ego_network(
        PERSON, "", PAGE, DEFAULT_MAX_COLLABORATORS, []
    )

    alerts = result[2]
    assert len(alerts) == 1
    assert alerts[0].color == "danger", "a settings problem is an error"
    assert "not a valid value" in str(alerts[0].children)


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

    from domain.person_network_url import build_person_network_url

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
    assert result[4]["display"] == "flex", "the empty-state prompt is shown"


def test_url_without_a_person_still_prompts(monkeypatch):
    captured = _stub_service(monkeypatch)

    result = ego_filter.load_ego_network(None, "?max_collaborators=50", PAGE, 25, [])

    assert captured == {}
    assert result[4]["display"] == "flex"


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


# ---------------------------------------------------------------------------
# Layout — the person picker lives in the page header, not the content column
# ---------------------------------------------------------------------------


def _walk_layout(node: Any) -> list[Any]:
    """Recursively collect every Dash component in a layout tree."""
    seen: list[Any] = []

    def walk(curr: Any) -> None:
        if curr is None:
            return
        seen.append(curr)
        children = getattr(curr, "children", None)
        if children is None:
            return
        if isinstance(children, (list, tuple)):
            for child in children:
                walk(child)
        else:
            walk(children)

    walk(node)
    return seen


def _find_by_exact_id(root: Any, component_id: Any) -> Any:
    """Return the component whose ``id`` equals *component_id* exactly.

    Deliberately not a substring check on ``str(layout)``: Dash renders a dict
    id with single quotes, so ``id="ego-header-picker"`` never appears literally
    and a substring assertion would pass vacuously.
    """
    for node in _walk_layout(root):
        if getattr(node, "id", None) == component_id:
            return node
    return None


def _find_by_class(root: Any, class_name: str) -> Any:
    """Return the first component carrying *class_name* in its className."""
    for node in _walk_layout(root):
        classes = str(getattr(node, "className", "") or "").split()
        if class_name in classes:
            return node
    return None


def test_picker_is_rendered_in_the_page_header():
    """The picker must sit inside the header, which is the point of the change."""
    from app.dash_app.pages.collaboration_network_ego.layout import get_layout

    layout = get_layout()
    picker = _find_by_class(layout, "ego-header-picker")
    assert picker is not None, "the header picker wrapper is missing"

    header = layout.children[0]
    assert picker in _walk_layout(header), "the picker is not inside the page header"


def test_picker_is_no_longer_a_sibling_of_the_canvas():
    """Regression guard: the old standalone block above the graph must be gone."""
    from app.dash_app.pages.collaboration_network_ego.layout import get_layout

    layout = get_layout()
    top_level = list(layout.children)
    header = top_level[0]

    for node in top_level[1:]:
        assert _find_by_class(node, "ego-header-picker") is None, (
            "the picker is still rendered outside the header"
        )
    assert _find_by_class(header, "ego-header-picker") is not None


def test_header_picker_keeps_every_id_the_callbacks_match_on():
    """The move must not rename any id — callbacks match on the id family."""
    from app.dash_app.pages.collaboration_network_ego.layout import get_layout

    layout = get_layout()
    for id_type in (
        "catalog-person-input",
        "catalog-person-chip",
        "catalog-person-search-area",
        "catalog-person-suggestions",
        "catalog-person-debounce",
        "catalog-person-value",
    ):
        assert (
            _find_by_exact_id(layout, {"type": id_type, "name": "ego_focus"}) is not None
        ), f"{id_type} for ego_focus is missing after the move"


def test_header_picker_label_is_hidden_not_absent():
    """The header supplies the label; the input keeps an accessible name."""
    from app.dash_app.pages.collaboration_network_ego.layout import get_layout

    layout = get_layout()
    labels = [
        n
        for n in _walk_layout(layout)
        if getattr(n, "className", None) == "catalog-person-label-hidden"
    ]
    assert labels, "no hidden label — the input would have no accessible name"


def test_canvas_height_is_re_derived_for_the_picker_move():
    """The canvas constant must shrink with the removed block, not stay at 200."""
    from app.dash_app.pages.collaboration_network_ego.layout import _CANVAS_HEIGHT

    assert "200px" not in _CANVAS_HEIGHT, (
        "canvas still subtracts the org page's constant, which was sized for a "
        "picker in the content column"
    )
    assert _CANVAS_HEIGHT.startswith("calc(100vh")


def test_empty_state_is_positioned_out_of_flow_over_the_canvas():
    """The prompt must overlay the canvas, not stack below it.

    In flow it added ~178px under a canvas already sized to the viewport, which
    pushed a scrollbar onto a page that should not scroll and left the text
    below the fold, where it went unread.
    """
    from app.dash_app.pages.collaboration_network_ego.layout import (
        _EMPTY_STATE_STYLE,
        get_layout,
    )

    assert _EMPTY_STATE_STYLE["position"] == "absolute", (
        "an in-flow prompt adds height to the column and reintroduces the scrollbar"
    )
    assert _EMPTY_STATE_STYLE["inset"] == 0, "the prompt must cover the canvas box"
    assert _EMPTY_STATE_STYLE["display"] == "flex", "flex is what centers the text"
    assert _EMPTY_STATE_STYLE["pointerEvents"] == "none", (
        "the prompt must not swallow clicks meant for the graph"
    )

    # The element must sit in a positioned ancestor, or absolute resolves against
    # the page and the prompt lands outside the plot area.
    layout = get_layout()
    assert _find_by_exact_id(layout, "ego-empty-state") is not None, (
        "the pre-input prompt is gone entirely"
    )

    def _ancestor_styles(node_id, tree, chain=()):
        for child in getattr(tree, "children", []) or []:
            if not hasattr(child, "children"):
                continue
            style = getattr(child, "style", None) or {}
            found = _ancestor_styles(node_id, child, chain + (style,))
            if getattr(child, "id", None) == node_id:
                return chain + (style,)
            if found:
                return found
        return None

    ancestors = _ancestor_styles("ego-empty-state", layout)
    assert any(a.get("position") == "relative" for a in ancestors), (
        "no positioned ancestor — the prompt would position against the page"
    )
    assert not any("overflowY" in a for a in ancestors), (
        "the prompt must not sit inside a scrolling ancestor"
    )


def test_callback_keeps_the_positioning_on_its_first_fire():
    """The callback replaces the whole style dict, so it must carry the position.

    Asserting on filter.py's imported ``_EMPTY_STATE_STYLE`` would be vacuous:
    ``from ..layout import _EMPTY_STATE_STYLE`` rebinds the same object into that
    namespace, so the identity holds even when the callback builds its own dict.
    Only the returned style proves the positioning survives.
    """
    from app.dash_app.pages.collaboration_network_ego.callbacks import filter as ego_filter

    result = ego_filter.load_ego_network(None, "?max_collaborators=50", PAGE, 25, [])
    returned = result[4]

    assert returned["display"] == "flex", "the prompt must be shown"
    assert returned["position"] == "absolute", (
        "the callback returned a style without the positioning — the prompt would "
        "drop into flow below the canvas and the page would scroll again"
    )
    assert returned["inset"] == 0, "the centering box must survive the callback"


# ---------------------------------------------------------------------------
# Loading overlay — the fetch in flight must be visible
# ---------------------------------------------------------------------------

def _loading_overlay_state(layout: Any) -> Any:
    """The initial ``data`` of the overlay's driving store."""
    store = _find_by_exact_id(layout, "ego-loading-state")
    assert store is not None, "the ego-loading-state store is missing"
    return store.data


def test_loading_store_starts_false_because_no_fetch_happens_on_arrival():
    """Starts down: no fetch happens until a person is picked.

    Seeding it truthy would flash the overlay over the "pick a person" prompt.
    """
    from app.dash_app.pages.collaboration_network_ego.layout import get_layout

    assert _loading_overlay_state(get_layout()) is False


def test_overlay_is_wired_to_the_store_it_reads():
    """The overlay div and its driving store must both exist and stay in sync."""
    from app.dash_app.pages.collaboration_network_ego.layout import get_layout

    layout = get_layout()
    assert _find_by_exact_id(layout, "ego-loading-overlay") is not None, (
        "the overlay div is missing — nothing would render the spinner"
    )
    assert _find_by_exact_id(layout, "ego-loading-state") is not None


def test_fetch_callback_clears_the_overlay_when_it_completes(monkeypatch):
    """Every terminal path must return False, or the overlay would never lift."""
    _stub_service(monkeypatch)

    success = ego_filter.load_ego_network(PERSON, "", PAGE, DEFAULT_MAX_COLLABORATORS, [])
    assert success[5] is False, "a completed fetch must clear the overlay"

    none_picked = ego_filter.load_ego_network(None, "", PAGE, DEFAULT_MAX_COLLABORATORS, [])
    assert none_picked[5] is False, "an empty picker must not leave the overlay up"


def test_fetch_callback_clears_the_overlay_on_error(monkeypatch):
    """An error must lift the overlay too, or it would spin forever."""
    def boom(*_args: Any, **_kwargs: Any) -> EgoNetworkResponse:
        raise ValueError("bad settings")

    monkeypatch.setattr(ego_filter, "get_ego_network", boom)

    result = ego_filter.load_ego_network(PERSON, "", PAGE, DEFAULT_MAX_COLLABORATORS, [])
    assert result[5] is False, "the overlay must clear on a settings error"


def _clientside_writers_of(target: str) -> list[dict[str, Any]]:
    """Registered clientside callbacks that output to *target*.

    Filters on Dash's ``clientside_function`` marker: the server fetch callback
    writes this store too, and counting it would let a deleted trigger pass.
    """
    # Page callbacks register in Dash's global registry, not the app's map.
    from dash._callback import GLOBAL_CALLBACK_LIST  # pylint: disable=protected-access

    matches: list[dict[str, Any]] = []
    for entry in GLOBAL_CALLBACK_LIST:
        if not isinstance(entry, dict) or entry.get("clientside_function") is None:
            continue
        output = str(entry.get("output", ""))
        # Dash suffixes duplicate-output registrations with "@<hash>".
        if output.split("@", 1)[0] == target:
            matches.append(entry)
    return matches


def test_a_clientside_callback_raises_the_overlay_before_the_fetch():
    """A picker-keyed clientside callback must write the store, beside the hider.

    The server fetch callback cannot raise it: it runs synchronously, so a True
    it wrote would never paint ahead of the wait.
    """
    writers = _clientside_writers_of("ego-loading-state.data")
    assert len(writers) >= 2, (
        f"expected the hider and a pre-fetch trigger to write ego-loading-state, "
        f"found {len(writers)} — the overlay would not show on a person switch"
    )

    ids_per_writer = [
        {str(inp.get("id")) for inp in writer.get("inputs", [])} for writer in writers
    ]
    person_key = '{"name":"ego_focus","type":"catalog-person-value"}'
    assert any(person_key in ids for ids in ids_per_writer), (
        "no clientside writer is keyed to the person picker — picking a person "
        "would start a multi-second fetch with no visible feedback"
    )


def test_prefetch_trigger_is_keyed_only_to_the_picker():
    """The picker must be the only Input, matching when the fetch happens.

    A URL input would raise the overlay for a navigation that fetches nothing.
    """
    writers = _clientside_writers_of("ego-loading-state.data")
    person_key = '{"name":"ego_focus","type":"catalog-person-value"}'

    triggers = [
        writer
        for writer in writers
        if {str(inp.get("id")) for inp in writer.get("inputs", [])} == {person_key}
    ]
    assert triggers, (
        "no clientside writer is keyed to the picker alone — the overlay could "
        "be raised without a fetch to clear it, or missed on a person switch"
    )

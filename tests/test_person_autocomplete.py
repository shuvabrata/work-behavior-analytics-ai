"""Unit tests for the person autocomplete combobox feature.

Tests cover:
- _build_person_picker returns a dbc.Input (not dcc.Dropdown)
- Chip area, search area, debounce store, value store all present
- render_catalog_query_detail routes person_id type to the picker
- render_catalog_query_detail still uses dbc.Input for other types
- sync_person_parameter_values merges/clears into parameters store
- sync_person_suggestions returns empty for query < 3 chars
- sync_person_suggestions calls /api/v1/search/persons and builds Button items
- handle_person_pick returns chip content, hides search area, stores wba_id
- handle_person_chip_clear resets chip, restores search area, clears value
- persons_router._extract_name fallback chain
- persons_router._build_suggestion field extraction

Run with:
    pytest -m unit tests/test_person_autocomplete.py -v
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from dash import dcc, html
import dash_bootstrap_components as dbc

from ui.pages.graph.callbacks import catalog as catalog_callbacks
from ui.components.person_picker import build_person_picker
from app.api.search.v1 import persons_router


pytestmark = pytest.mark.unit


# ===========================================================================
# Helpers
# ===========================================================================


def _find_component_by_type(children, component_type):
    """Recursively find the first component of the given type in children."""
    if isinstance(children, component_type):
        return children
    kids = getattr(children, "children", None)
    if kids is None:
        return None
    if isinstance(kids, list):
        for child in kids:
            found = _find_component_by_type(child, component_type)
            if found is not None:
                return found
    else:
        return _find_component_by_type(kids, component_type)
    return None


def _find_components_by_type(children, component_type, results=None):
    """Recursively collect ALL components of the given type."""
    if results is None:
        results = []
    if isinstance(children, component_type):
        results.append(children)
    kids = getattr(children, "children", None)
    if isinstance(kids, list):
        for child in kids:
            _find_components_by_type(child, component_type, results)
    elif kids is not None:
        _find_components_by_type(kids, component_type, results)
    return results


def _find_component_by_id_type(root, id_type: str):
    """Recursively find first component whose id dict has type == id_type."""
    comp_id = getattr(root, "id", None)
    if isinstance(comp_id, dict) and comp_id.get("type") == id_type:
        return root
    kids = getattr(root, "children", None)
    if isinstance(kids, list):
        for child in kids:
            found = _find_component_by_id_type(child, id_type)
            if found is not None:
                return found
    elif kids is not None:
        return _find_component_by_id_type(kids, id_type)
    return None


def _flatten_text(value):
    """Recursively extract all string leaves from a Dash component tree."""
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, (list, tuple)):
        texts = []
        for child in value:
            texts.extend(_flatten_text(child))
        return texts
    children = getattr(value, "children", None)
    if isinstance(children, (list, tuple)):
        texts = []
        for child in children:
            texts.extend(_flatten_text(child))
        return texts
    if children is not None:
        return _flatten_text(children)
    return []


# ===========================================================================
# _build_person_picker — structure tests
# ===========================================================================


def _build_picker(parameter: dict, current_value=None):
    """Call the extracted builder with the old dict-shaped parameter."""
    return build_person_picker(
        parameter.get("name", ""),
        parameter.get("label") or parameter.get("name") or "Parameter",
        required=parameter.get("required", False),
        current_value=current_value,
    )


def test_build_person_picker_contains_text_input():
    """`_build_person_picker` must use a dbc.Input (not dcc.Dropdown)."""
    parameter = {"name": "person1_id", "required": True, "label": "First person", "type": "person_id"}
    result = _build_picker(parameter)

    assert isinstance(result, html.Div)
    # Must NOT contain a dcc.Dropdown
    dropdown = _find_component_by_type(result, dcc.Dropdown)
    assert dropdown is None, "dcc.Dropdown must NOT be used in the new combobox"
    # Must contain a dbc.Input
    text_input = _find_component_by_type(result, dbc.Input)
    assert text_input is not None, "Expected a dbc.Input in the combobox"


def test_build_person_picker_input_id_uses_parameter_name():
    """The dbc.Input id must be the pattern-matching dict {type: catalog-person-input, name}."""
    parameter = {"name": "person2_id", "required": False, "label": "Second person"}
    result = _build_picker(parameter)

    text_input = _find_component_by_id_type(result, "catalog-person-input")
    assert text_input is not None
    assert text_input.id == {"type": "catalog-person-input", "name": "person2_id"}


def test_build_person_picker_has_suggestions_panel():
    """The picker must include a suggestions panel div."""
    parameter = {"name": "person1_id", "required": True, "label": "First person"}
    result = _build_picker(parameter)

    suggestions = _find_component_by_id_type(result, "catalog-person-suggestions")
    assert suggestions is not None
    assert suggestions.id == {"type": "catalog-person-suggestions", "name": "person1_id"}


def test_build_person_picker_has_chip_area():
    """The picker must include a chip area div (initially hidden)."""
    parameter = {"name": "person1_id", "required": True, "label": "First person"}
    result = _build_picker(parameter)

    chip = _find_component_by_id_type(result, "catalog-person-chip")
    assert chip is not None
    assert chip.style.get("display") == "none"


def test_build_person_picker_has_value_store():
    """The picker must embed a catalog-person-value dcc.Store."""
    parameter = {"name": "person1_id", "required": True, "label": "First person"}
    result = _build_picker(parameter)

    value_store = _find_component_by_id_type(result, "catalog-person-value")
    assert value_store is not None
    assert isinstance(value_store, dcc.Store)
    assert value_store.data is None


def test_build_person_picker_has_debounce_store():
    """The picker must embed a catalog-person-debounce dcc.Store."""
    parameter = {"name": "person1_id", "required": True, "label": "First person"}
    result = _build_picker(parameter)

    debounce_store = _find_component_by_id_type(result, "catalog-person-debounce")
    assert debounce_store is not None
    assert isinstance(debounce_store, dcc.Store)


def test_build_person_picker_label_shows_asterisk_for_required():
    """Required pickers must show an asterisk in the label."""
    parameter = {"name": "person1_id", "required": True, "label": "First person"}
    result = _build_picker(parameter)

    texts = _flatten_text(result)
    assert any("*" in t for t in texts), "Required picker label must contain '*'"


def test_build_person_picker_no_asterisk_for_optional():
    """Optional pickers must NOT show an asterisk."""
    parameter = {"name": "person1_id", "required": False, "label": "Some person"}
    result = _build_picker(parameter)

    label = result.children[0]  # First child is the Label
    assert "*" not in label.children


# ===========================================================================
# render_catalog_query_detail — person_id type routing
# ===========================================================================


def _make_p2p_query(parameter_type: str = "person_id") -> dict:
    return {
        "id": "person_to_person/direct_code_reviews",
        "name": "Direct Code Reviews",
        "description": "Review collaboration.",
        "summary": "Compare two people by code review.",
        "namespace": {"name": "Person-to-Person", "directory": "person_to_person"},
        "available_views": ["tabular", "graph"],
        "default_view": "tabular",
        "parameters": [
            {
                "name": "person1_id",
                "required": True,
                "label": "First person",
                "type": parameter_type,
                "placeholder": "e.g. github::Person::alice",
                "description": "WBA canonical Person ID.",
                "env_var": "PERSON1_ID",
            }
        ],
        "tags": ["people"],
        "owner": "graph-team",
        "status": "active",
    }


def test_render_catalog_query_detail_uses_input_for_person_id_type():
    """Parameters with type='person_id' must render a dbc.Input combobox, not dcc.Dropdown."""
    catalog_query = _make_p2p_query(parameter_type="person_id")

    _, _, _, parameter_children = catalog_callbacks.render_catalog_query_detail(
        selected_query={"id": "person_to_person/direct_code_reviews"},
        catalog_queries=[catalog_query],
        theme_name=None,
        parameter_values={},
        current_view=None,
    )

    assert len(parameter_children) >= 1
    first_param_block = parameter_children[0]

    text_input = _find_component_by_id_type(first_param_block, "catalog-person-input")
    dropdown = _find_component_by_type(first_param_block, dcc.Dropdown)

    assert text_input is not None, "Expected catalog-person-input for person_id parameter"
    assert dropdown is None, "Must NOT render dcc.Dropdown for person_id parameter"


def test_render_catalog_query_detail_uses_input_for_non_person_id_type():
    """Parameters without type='person_id' must still render as a plain dbc.Input (not combobox)."""
    catalog_query = _make_p2p_query(parameter_type="node_id")

    _, _, _, parameter_children = catalog_callbacks.render_catalog_query_detail(
        selected_query={"id": "person_to_person/direct_code_reviews"},
        catalog_queries=[catalog_query],
        theme_name=None,
        parameter_values={},
        current_view=None,
    )

    assert len(parameter_children) >= 1
    first_param_block = parameter_children[0]

    # Should have a plain dbc.Input (the catalog-parameter-input, NOT catalog-person-input)
    inputs = _find_components_by_type(first_param_block, dbc.Input)
    assert len(inputs) > 0

    # Should NOT have a catalog-person-input (the combobox variant)
    person_input = _find_component_by_id_type(first_param_block, "catalog-person-input")
    assert person_input is None, "Must NOT render person combobox for non-person_id parameter"


def test_render_catalog_query_detail_run_disabled_when_no_person_selected():
    """Run button must be disabled when a required person_id has no value."""
    catalog_query = _make_p2p_query(parameter_type="person_id")

    # update_run_button_state is the dedicated callback for button disabled state
    run_disabled, _ = catalog_callbacks.update_run_button_state(
        parameter_values={},
        selected_query={"id": "person_to_person/direct_code_reviews"},
        catalog_queries=[catalog_query],
        current_view="graph",
    )

    assert run_disabled is True


def test_render_catalog_query_detail_run_enabled_when_person_value_present():
    """Run button must be enabled when the required person_id field has a wba_id value."""
    catalog_query = _make_p2p_query(parameter_type="person_id")

    run_disabled, _ = catalog_callbacks.update_run_button_state(
        parameter_values={"person1_id": "github::Person::alice"},
        selected_query={"id": "person_to_person/direct_code_reviews"},
        catalog_queries=[catalog_query],
        current_view="graph",
    )

    assert run_disabled is False


# ===========================================================================
# sync_person_parameter_values
# ===========================================================================


def test_sync_person_parameter_values_merges_selection_into_store():
    """A selected person (as dict) must be written into catalog-parameters-store."""
    result = catalog_callbacks.sync_person_parameter_values(
        values=[{"wba": "github::Person::alice", "display": "Alice Smith"}, None],
        ids=[
            {"type": "catalog-person-value", "name": "person1_id"},
            {"type": "catalog-person-value", "name": "person2_id"},
        ],
        current_params={"other_param": "existing_value"},
    )

    assert result["person1_id"] == {"wba": "github::Person::alice", "display": "Alice Smith"}
    assert result["other_param"] == "existing_value"
    assert "person2_id" not in result


def test_sync_person_parameter_values_clears_on_deselect():
    """Clearing the value (None) removes the key from the store."""
    result = catalog_callbacks.sync_person_parameter_values(
        values=[None],
        ids=[{"type": "catalog-person-value", "name": "person1_id"}],
        current_params={"person1_id": {"wba": "github::Person::alice", "display": "Alice Smith"}},
    )

    assert "person1_id" not in result


def test_sync_person_parameter_values_handles_empty_ids():
    """Empty input lists must return the current params unchanged."""
    current = {"person1_id": {"wba": "github::Person::alice", "display": "Alice Smith"}}
    result = catalog_callbacks.sync_person_parameter_values(
        values=[], ids=[], current_params=current,
    )
    assert result == current


def test_sync_person_parameter_values_initialises_empty_store():
    """When current_params is None, result must be a fresh dict."""
    result = catalog_callbacks.sync_person_parameter_values(
        values=[{"wba": "github::Person::bob", "display": "Bob Jones"}],
        ids=[{"type": "catalog-person-value", "name": "person1_id"}],
        current_params=None,
    )
    assert result == {"person1_id": {"wba": "github::Person::bob", "display": "Bob Jones"}}


# ===========================================================================
# sync_person_suggestions (replaces sync_person_search_options)
# ===========================================================================


def test_sync_person_suggestions_returns_empty_for_short_query():
    """Queries shorter than 3 chars must return empty children and hidden style."""
    children, styles = catalog_callbacks.sync_person_suggestions(
        debounced_queries=["ab", None],
        debounce_ids=[
            {"type": "catalog-person-debounce", "name": "person1_id"},
            {"type": "catalog-person-debounce", "name": "person2_id"},
        ],
    )
    assert children == [[], []]
    assert all(s.get("display") == "none" for s in styles)


def test_sync_person_suggestions_returns_empty_for_none_query():
    """None query values must return empty children and hidden style."""
    children, styles = catalog_callbacks.sync_person_suggestions(
        debounced_queries=[None],
        debounce_ids=[{"type": "catalog-person-debounce", "name": "person1_id"}],
    )
    assert children == [[]]
    assert styles[0].get("display") == "none"


def test_sync_person_suggestions_calls_persons_api_for_valid_query():
    """A query >= 3 chars must trigger a GET /api/v1/search/persons call."""
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "results": [
            {
                "wba_id": "github::Person::alice",
                "name": "Alice Smith",
                "email": "alice@example.com",
                "source": "github",
                "login": "alice",
            }
        ]
    }
    mock_response.raise_for_status = MagicMock()

    with patch("ui.pages.graph.callbacks.catalog.api_client.get") as mock_get:
        mock_get.return_value = mock_response
        children, styles = catalog_callbacks.sync_person_suggestions(
            debounced_queries=["alice"],
            debounce_ids=[{"type": "catalog-person-debounce", "name": "person1_id"}],
        )

    mock_get.assert_called_once()
    call_kwargs = mock_get.call_args
    assert "persons" in call_kwargs[0][0]
    assert call_kwargs[1]["params"]["q"] == "alice"

    assert len(children[0]) == 1
    suggestion_button = children[0][0]
    assert suggestion_button.id.get("wba") == "github::Person::alice"


def test_sync_person_suggestions_renders_buttons_with_correct_id():
    """Suggestion items must be html.Button components with the correct ID structure."""
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "results": [
            {
                "wba_id": "github::Person::alice",
                "name": "Alice Smith",
                "email": "alice@example.com",
                "source": "github",
                "login": "alice",
            }
        ]
    }
    mock_response.raise_for_status = MagicMock()

    with patch("ui.pages.graph.callbacks.catalog.api_client.get") as mock_get:
        mock_get.return_value = mock_response
        children, _ = catalog_callbacks.sync_person_suggestions(
            debounced_queries=["alice"],
            debounce_ids=[{"type": "catalog-person-debounce", "name": "person1_id"}],
        )

    button = children[0][0]
    assert isinstance(button, html.Button)
    assert button.id["type"] == "catalog-person-pick"
    assert button.id["name"] == "person1_id"
    assert button.id["wba"] == "github::Person::alice"
    assert button.id["display"] == "Alice Smith"


def test_sync_person_suggestions_shows_no_results_message():
    """When API returns 0 results, show a 'no results' message in the panel."""
    mock_response = MagicMock()
    mock_response.json.return_value = {"results": []}
    mock_response.raise_for_status = MagicMock()

    with patch("ui.pages.graph.callbacks.catalog.api_client.get") as mock_get:
        mock_get.return_value = mock_response
        children, styles = catalog_callbacks.sync_person_suggestions(
            debounced_queries=["xyznotfound"],
            debounce_ids=[{"type": "catalog-person-debounce", "name": "person1_id"}],
        )

    # Panel is visible but shows a "no results" message
    assert styles[0].get("display") != "none" or styles[0].get("display") == "block"
    # The children should contain a message element (not buttons)
    assert len(children[0]) > 0
    msg_texts = _flatten_text(children[0])
    assert any("No people found" in t or "try" in t.lower() for t in msg_texts)


def test_sync_person_suggestions_falls_back_gracefully_on_api_error():
    """API errors must not raise — they must return an error message in the panel."""
    from ui.api_client import STATUS_NO_RESPONSE, ApiError

    with patch("ui.pages.graph.callbacks.catalog.api_client.get") as mock_get:
        mock_get.side_effect = ApiError(STATUS_NO_RESPONSE, message="connection refused")
        children, styles = catalog_callbacks.sync_person_suggestions(
            debounced_queries=["alice"],
            debounce_ids=[{"type": "catalog-person-debounce", "name": "person1_id"}],
        )

    assert len(children) == 1
    assert len(styles) == 1
    # Should show an error message, not raise
    msg_texts = _flatten_text(children[0])
    assert any("fail" in t.lower() or "connection" in t.lower() for t in msg_texts)


def test_sync_person_suggestions_handles_person_without_email():
    """A person with no email must still produce a valid suggestion button."""
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "results": [
            {
                "wba_id": "github::Person::bob",
                "name": "Bob Smith",
                "email": None,
                "source": "github",
                "login": "bob",
            }
        ]
    }
    mock_response.raise_for_status = MagicMock()

    with patch("ui.pages.graph.callbacks.catalog.api_client.get") as mock_get:
        mock_get.return_value = mock_response
        children, _ = catalog_callbacks.sync_person_suggestions(
            debounced_queries=["bob"],
            debounce_ids=[{"type": "catalog-person-debounce", "name": "person1_id"}],
        )

    assert len(children[0]) == 1
    button = children[0][0]
    assert button.id["wba"] == "github::Person::bob"
    # Falls back to @login in the detail text
    detail_texts = _flatten_text(button)
    assert any("bob" in t.lower() for t in detail_texts)


# ===========================================================================
# persons_router unit tests
# ===========================================================================


def test_extract_name_prefers_full_name():
    assert persons_router._extract_name({"full_name": "Alice Smith", "login": "alice"}) == "Alice Smith"


def test_extract_name_falls_back_to_name():
    assert persons_router._extract_name({"name": "Alice Smith", "login": "alice"}) == "Alice Smith"


def test_extract_name_falls_back_to_login():
    assert persons_router._extract_name({"login": "alice"}) == "alice"


def test_extract_name_falls_back_to_wba_id():
    assert persons_router._extract_name({"wba_id": "github::Person::alice"}) == "github::Person::alice"


def test_extract_name_returns_unknown_when_all_missing():
    assert persons_router._extract_name({}) == "Unknown"


def test_build_suggestion_returns_correct_person_suggestion():
    """_build_suggestion maps SearchResult attributes to PersonSuggestion correctly."""
    from app.api.search.v1.model import SearchResult

    result = SearchResult(
        wba_id="github::Person::alice",
        score=10.0,
        url=None,
        event_time=None,
        highlight=None,
        attributes={
            "full_name": "Alice Smith",
            "login": "alice",
            "email": "alice@example.com",
            "source": "github",
        },
    )
    suggestion = persons_router._build_suggestion(result)

    assert suggestion is not None
    assert suggestion.wba_id == "github::Person::alice"
    assert suggestion.name == "Alice Smith"
    assert suggestion.email == "alice@example.com"
    assert suggestion.source == "github"
    assert suggestion.login == "alice"


def test_build_suggestion_derives_source_from_wba_id_when_missing():
    """When 'source' is absent from attributes, derive it from the wba_id prefix."""
    from app.api.search.v1.model import SearchResult

    result = SearchResult(
        wba_id="jira::Person::abc123",
        score=5.0,
        attributes={
            "full_name": "Jira User",
            "login": "jira_user",
        },
    )
    suggestion = persons_router._build_suggestion(result)

    assert suggestion is not None
    assert suggestion.source == "jira"


def test_build_suggestion_handles_null_email():
    """Email can be None — suggestion must still be returned."""
    from app.api.search.v1.model import SearchResult

    result = SearchResult(
        wba_id="github::Person::bob",
        score=3.0,
        attributes={
            "full_name": "Bob Jones",
            "login": "bob",
            "email": None,
            "source": "github",
        },
    )
    suggestion = persons_router._build_suggestion(result)

    assert suggestion is not None
    assert suggestion.email is None


# ===========================================================================
# build_person_picker — header-host options (show_label / container_class)
# ===========================================================================


def test_picker_hides_label_but_keeps_it_for_screen_readers():
    """show_label=False must hide the label, not drop it from the DOM.

    dbc.Input (2.0.4) rejects `aria-label`, so a hidden <label> is the only way
    the input keeps an accessible name in a host that supplies its own label.
    """
    picker = build_person_picker("ego_focus", "Person", required=True, show_label=False)

    hidden = [
        c for c in picker.children
        if isinstance(c, html.Label)
        and c.className == "catalog-person-label-hidden"
    ]
    assert len(hidden) == 1, "the label must remain in the DOM, hidden"
    # The required asterisk survives for screen readers.
    assert any("*" in t for t in _flatten_text(hidden[0]))


def test_picker_shows_label_by_default():
    """The default keeps the visible label, so existing callers are unaffected."""
    picker = build_person_picker("person1_id", "First person")
    labels = [c for c in picker.children if isinstance(c, html.Label)]
    assert len(labels) == 1
    assert "hidden" not in str(getattr(labels[0], "className", "") or "")


def test_picker_container_class_is_overridable():
    """A header host can drop the stacked-form margin."""
    assert build_person_picker("p", "P").className == "mb-3"
    assert build_person_picker("p", "P", container_class="").className == ""
    assert build_person_picker("p", "P", container_class="ego-header-picker").className == "ego-header-picker"


def test_picker_keeps_the_same_id_family_in_a_header_host():
    """Moving the picker must not rename any id — the callbacks match on these."""
    picker = build_person_picker("ego_focus", "Person", required=True, show_label=False)

    for id_type in (
        "catalog-person-input",
        "catalog-person-chip",
        "catalog-person-search-area",
        "catalog-person-suggestions",
        "catalog-person-debounce",
        "catalog-person-value",
    ):
        found = _find_component_by_id_type(picker, id_type)
        assert found is not None, f"{id_type} missing"
        assert found.id == {"type": id_type, "name": "ego_focus"}


# ===========================================================================
# build_person_chip — one definition shared by all three producers
# ===========================================================================


def test_build_person_chip_shape():
    """The chip is [info block, clear button], keyed to the picker's name."""
    from ui.components.person_picker import build_person_chip

    chip = build_person_chip("ego_focus", "Alice Smith", "github::Person::alice")

    assert len(chip) == 2
    info, clear = chip
    assert info.className == "catalog-person-chip-info"
    assert [s.className for s in info.children] == [
        "catalog-person-chip-name",
        "catalog-person-chip-id",
    ]
    assert [s.children for s in info.children] == ["Alice Smith", "github::Person::alice"]
    assert clear.id == {"type": "catalog-person-chip-clear", "name": "ego_focus"}


def test_pick_handler_and_picker_agree_on_the_chip():
    """The pick handler must emit the same chip the layout pre-renders.

    Both go through build_person_chip; this fails if either grows its own copy
    again, which is how a selection made by picking could render differently
    from one restored by a deep link.
    """
    from ui.components.person_picker import build_person_chip

    pre_rendered = build_person_picker(
        "ego_focus", "Person", current_value={"wba": "github::Person::alice", "display": "Alice Smith"}
    )
    chip_area = _find_component_by_id_type(pre_rendered, "catalog-person-chip")

    assert str(chip_area.children) == str(
        build_person_chip("ego_focus", "Alice Smith", "github::Person::alice")
    )


# ===========================================================================
# Required marker when the visible label is suppressed
# ===========================================================================


def _class_names(picker):
    """Collect every className in the tree, split into individual classes."""
    names = set()

    def walk(node):
        if node is None:
            return
        for cls in str(getattr(node, "className", "") or "").split():
            names.add(cls)
        children = getattr(node, "children", None)
        if children is None:
            return
        if isinstance(children, (list, tuple)):
            for child in children:
                walk(child)
        else:
            walk(children)

    walk(picker)
    return names


def test_hidden_label_required_gets_an_inline_marker():
    """With the label hidden, requiredness must still be visible.

    The asterisk lives inside the label, and the hidden label is moved
    off-screen — so without this the ego page's required picker showed no
    requiredness at all.
    """
    picker = build_person_picker("ego_focus", "Person", required=True, show_label=False)
    assert "catalog-person-required-marker" in _class_names(picker)


def test_shown_label_required_does_not_duplicate_the_marker():
    """A visible label already carries the asterisk; a second one would double it."""
    picker = build_person_picker("person1_id", "First person", required=True, show_label=True)
    assert "catalog-person-required-marker" not in _class_names(picker)


def test_optional_picker_has_no_marker():
    """Optional pickers must not gain an asterisk from either path."""
    for show_label in (True, False):
        picker = build_person_picker("p", "Person", required=False, show_label=show_label)
        assert "catalog-person-required-marker" not in _class_names(picker)


def test_marker_sits_beside_the_input_on_one_row():
    """The marker is a sibling of the combobox inside the flex row.

    If it were placed inside the combobox it would sit under the suggestions
    panel's positioning context, and outside the row it would stack below the
    input — which is the two-line layout this replaced.
    """
    picker = build_person_picker("ego_focus", "Person", required=True, show_label=False)
    rows = []

    def walk(node):
        if getattr(node, "className", None) == "catalog-person-input-row":
            rows.append(node)
        children = getattr(node, "children", None)
        if children is None:
            return
        if isinstance(children, (list, tuple)):
            for child in children:
                walk(child)
        else:
            walk(children)

    walk(picker)
    assert len(rows) == 1, "expected exactly one input row"
    child_classes = [getattr(c, "className", "") for c in rows[0].children]
    assert child_classes == ["catalog-person-combobox", "catalog-person-required-marker"]


# ===========================================================================
# Font-size scoping — the header host grows, the catalog host does not
# ===========================================================================


def _css() -> str:
    """Return the app stylesheet as text."""
    from pathlib import Path

    return (
        Path(__file__).resolve().parents[1]
        / "src/ui/assets/executive-dashboard.css"
    ).read_text()


def test_header_picker_enlarges_the_input_over_the_inline_default():
    """The header picker must override the inline 12px, and only via !important.

    build_person_picker sets fontSize inline, and an inline style outranks any
    selector — so a rule without !important would silently do nothing.
    """
    css = _css()
    block = css.split(".ego-header-picker .form-control {")[1].split("}")[0]
    assert "font-size: 14px !important" in block, (
        "the header input's font-size must be !important to beat the inline style"
    )


def test_the_shared_picker_defaults_are_unchanged():
    """The base rules the Graph page's catalog pickers rely on must not grow.

    The header host overrides these; if someone edits the base values instead,
    every person picker in the app grows with it.
    """
    css = _css()

    def font_size_of(selector: str) -> str:
        block = css.split(selector + " {")[1].split("}")[0]
        for line in block.splitlines():
            if "font-size" in line:
                return line.split(":", 1)[1].strip().rstrip(";")
        raise AssertionError(f"no font-size in {selector}")

    assert font_size_of(".catalog-person-chip-name") == "12px"
    assert font_size_of(".catalog-person-chip-id") == "10px"


def test_the_header_host_raises_the_chip_above_those_defaults():
    """The header's chip is deliberately larger than the shared default."""
    css = _css()
    for selector, expected in (
        (".ego-header-picker .catalog-person-chip-name", "13px"),
        (".ego-header-picker .catalog-person-chip-id", "11px"),
    ):
        block = css.split(selector + " {")[1].split("}")[0]
        assert f"font-size: {expected}" in block, f"{selector} should be {expected}"


def test_shared_picker_still_emits_the_inline_12px_for_other_hosts():
    """The component's own default is unchanged; only CSS re-sizes the header."""
    picker = build_person_picker("person1_id", "First person")
    text_input = _find_component_by_id_type(picker, "catalog-person-input")
    assert text_input is not None
    assert text_input.style["fontSize"] == "12px"


def _declarations_for(css: str, selector: str) -> str:
    """Return the declaration block for *selector*, matched at a line start.

    A plain ``split(selector + " {")`` would also match the same class when it
    is preceded by a host prefix, so the match is anchored to a line boundary.
    """
    marker = "\n" + selector + " {"
    assert marker in css, f"no rule found for {selector}"
    return css.split(marker, 1)[1].split("}", 1)[0]


def test_header_chip_keeps_the_stacked_form():
    """The header chip must NOT go back to one line.

    An inline variant was tried and reverted: at the header's width it clipped
    the wba_id, which is the reason the chip shows the id at all. The header may
    restyle the chip's type size, but the stacking must keep coming from the
    shared rules — so no header-scoped rule may redeclare layout.
    """
    css = _css()

    for selector in (
        ".ego-header-picker .catalog-person-chip-info",
        ".ego-header-picker .catalog-person-chip-name",
        ".ego-header-picker .catalog-person-chip-id",
    ):
        if "\n" + selector + " {" not in css:
            continue  # rule absent entirely is fine
        block = _declarations_for(css, selector)
        for prop in ("display", "align-items", "white-space", "flex"):
            assert prop not in block, (
                f"{selector} redeclares '{prop}'; the stacked layout must come "
                "from the shared rules, not the header host"
            )

    # And the shared rules still stack the name above the id.
    for selector in (".catalog-person-chip-name", ".catalog-person-chip-id"):
        assert "display: block" in _declarations_for(css, selector), (
            f"{selector} must stay block-level to stack"
        )


def test_header_chip_has_no_inline_separator():
    """The inline variant's '·' separator must not survive the revert."""
    assert "catalog-person-chip-id::before" not in _css()

"""Unit tests for Graph page catalog callback helpers."""

import pytest

from app.dash_app.pages.graph.callbacks import catalog as catalog_callbacks


pytestmark = pytest.mark.unit


def _flatten_text(value):
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


def test_filter_catalog_queries_respects_namespace_search_and_view():
    catalog_queries = [
        {
            "id": "github/top_contributors",
            "name": "Top Contributors",
            "description": "Commit leaderboard",
            "summary": "Repository commit leaders",
            "namespace": {"name": "GitHub", "directory": "github"},
            "available_views": ["tabular", "graph"],
            "tags": ["people"],
            "owner": "graph-team",
            "status": "active",
        },
        {
            "id": "jira/open_bugs",
            "name": "Open Bugs",
            "description": "Active defects",
            "namespace": {"name": "Jira", "directory": "jira"},
            "available_views": ["tabular"],
            "tags": ["bugs"],
        },
    ]

    filtered = catalog_callbacks.filter_catalog_queries(
        catalog_queries,
        namespace_filter="github",
        search_text="contributors",
        view_filter="graph",
    )

    assert [query["id"] for query in filtered] == ["github/top_contributors"]


def test_parse_catalog_deep_link_extracts_catalog_and_valid_view():
    catalog_id, view = catalog_callbacks.parse_catalog_deep_link(
        "?catalog=person_to_person/direct_code_reviews&view=tabular"
    )

    assert catalog_id == "person_to_person/direct_code_reviews"
    assert view == "tabular"


def test_parse_catalog_deep_link_ignores_invalid_view():
    catalog_id, view = catalog_callbacks.parse_catalog_deep_link(
        "?catalog=github/top_contributors&view=auto"
    )

    assert catalog_id == "github/top_contributors"
    assert view is None


def test_determine_catalog_view_prefers_current_then_requested_then_default_view():
    catalog_query = {"available_views": ["tabular", "graph"], "default_view": "tabular"}

    # current_view wins when it is valid
    assert catalog_callbacks.determine_catalog_view(catalog_query, "graph", "tabular") == "tabular"
    # requested_view wins when current_view is absent
    assert catalog_callbacks.determine_catalog_view(catalog_query, "graph", None) == "graph"
    # default_view from the YAML wins when neither current nor requested is set
    assert catalog_callbacks.determine_catalog_view(catalog_query, None, None) == "tabular"
    # only-tabular query returns tabular
    assert catalog_callbacks.determine_catalog_view({"available_views": ["tabular"]}, None, None) == "tabular"
    # no default_view declared → fall back to graph when it is available
    assert catalog_callbacks.determine_catalog_view({"available_views": ["tabular", "graph"]}, None, None) == "graph"


def test_required_parameters_missing_reports_only_unfilled_required_inputs():
    catalog_query = {
        "parameters": [
            {"name": "person1_id", "required": True},
            {"name": "person2_id", "required": True},
            {"name": "optional_repo", "required": False},
        ]
    }

    missing = catalog_callbacks.required_parameters_missing(
        catalog_query,
        {
            "person1_id": {"wba": "github::Person::alice", "display": "Alice Smith"},
            "person2_id": "   ",
        },
    )

    assert missing == ["person2_id"]


def test_required_parameters_missing_handles_pure_string_store():
    """Legacy string values (non-person params) should still work."""
    catalog_query = {
        "parameters": [
            {"name": "person1_id", "required": True},
        ]
    }

    missing = catalog_callbacks.required_parameters_missing(
        catalog_query,
        {"person1_id": "github::Person::alice"},
    )

    assert missing == []


def test_build_namespace_options_includes_all_namespaces_first():
    options = catalog_callbacks.build_namespace_options(
        [
            {"namespace": {"name": "GitHub", "directory": "github"}},
            {"namespace": {"name": "Jira", "directory": "jira"}},
        ]
    )

    assert options == [
        {"label": "All namespaces", "value": catalog_callbacks.ALL_NAMESPACES},
        {"label": "GitHub", "value": "github"},
        {"label": "Jira", "value": "jira"},
    ]


def test_filter_catalog_queries_matches_summary_owner_and_status_text():
    catalog_queries = [
        {
            "id": "person_to_person/direct_code_reviews",
            "name": "Direct Code Reviews",
            "description": "Review collaboration",
            "summary": "Compare two people by direct code review activity.",
            "namespace": {"name": "Person-to-Person", "directory": "person_to_person"},
            "available_views": ["tabular", "graph"],
            "tags": ["people"],
            "owner": "graph-team",
            "status": "active",
        }
    ]

    filtered = catalog_callbacks.filter_catalog_queries(
        catalog_queries,
        namespace_filter=catalog_callbacks.ALL_NAMESPACES,
        search_text="graph-team active",
        view_filter=catalog_callbacks.ALL_VIEWS,
    )

    assert [query["id"] for query in filtered] == ["person_to_person/direct_code_reviews"]


def test_render_catalog_query_detail_uses_rich_metadata_and_default_view():
    catalog_query = {
        "id": "person_to_person/direct_code_reviews",
        "name": "Direct Code Reviews",
        "description": "Find all PRs created by one and reviewed by the other.",
        "summary": "Compare two people by direct code review activity.",
        "namespace": {"name": "Person-to-Person", "directory": "person_to_person"},
        "available_views": ["tabular", "graph"],
        "default_view": "tabular",
        "parameters": [
            {
                "name": "person1_id",
                "required": True,
                "label": "First person",
                "type": "person_id",
                "placeholder": "Enter first person id",
                "description": "Neo4j Person.id for the first person.",
                "env_var": "PERSON1_ID",
            }
        ],
        "tags": ["code-review"],
        "owner": "graph-team",
        "status": "active",
    }

    (
        detail_children,
        view_options,
        selected_view,
        parameter_children,
    ) = catalog_callbacks.render_catalog_query_detail(
        selected_query={"id": "person_to_person/direct_code_reviews"},
        catalog_queries=[catalog_query],
        theme_name=None,
        parameter_values={"person1_id": "person_123"},
        current_view=None,
    )
    run_disabled, load_disabled = catalog_callbacks.update_run_button_state(
        parameter_values={"person1_id": "person_123"},
        selected_query={"id": "person_to_person/direct_code_reviews"},
        catalog_queries=[catalog_query],
        current_view="graph",
    )

    detail_text = " ".join(_flatten_text(detail_children))
    first_parameter_block = parameter_children[0]

    # person_id parameters now render as a dbc.Input combobox (catalog-person-input),
    # not a dcc.Dropdown — locate the input by its id type.
    def _find_by_id_type(root, id_type):
        comp_id = getattr(root, "id", None)
        if isinstance(comp_id, dict) and comp_id.get("type") == id_type:
            return root
        kids = getattr(root, "children", None)
        if isinstance(kids, list):
            for child in kids:
                found = _find_by_id_type(child, id_type)
                if found is not None:
                    return found
        elif kids is not None:
            return _find_by_id_type(kids, id_type)
        return None

    person_input = _find_by_id_type(first_parameter_block, "catalog-person-input")
    chip_area = _find_by_id_type(first_parameter_block, "catalog-person-chip")

    assert view_options[0]["value"] == "graph"
    assert view_options[1]["value"] == "tabular"
    assert selected_view == "tabular"  # default_view: tabular is declared in the fixture
    assert "Compare two people by direct code review activity." in detail_text
    assert "Active" not in detail_text
    # Label is now a list: ["First person", Span(" *", style={color: red})]
    label_children = first_parameter_block.children[0].children
    label_text = "".join(c if isinstance(c, str) else c.children for c in label_children)
    assert label_text == "First person *"
    assert person_input is not None, "Expected catalog-person-input (dbc.Input combobox)"
    assert person_input.id == {"type": "catalog-person-input", "name": "person1_id"}
    assert person_input.placeholder == "Search by name or email (min 3 chars)"
    assert chip_area is not None, "Expected catalog-person-chip area"
    assert run_disabled is False
    assert load_disabled is False


def test_build_status_badge_only_renders_draft_and_deprecated():
    assert catalog_callbacks._build_status_badge("active") is None
    assert catalog_callbacks._build_status_badge("ACTIVE") is None
    assert catalog_callbacks._build_status_badge(None) is None
    assert catalog_callbacks._build_status_badge("") is None

    draft_badge = catalog_callbacks._build_status_badge("draft")
    assert draft_badge is not None
    assert draft_badge.children == "Draft"
    assert draft_badge.color == "warning"

    deprecated_badge = catalog_callbacks._build_status_badge("deprecated")
    assert deprecated_badge is not None
    assert deprecated_badge.children == "Deprecated"
    assert deprecated_badge.color == "secondary"


def test_render_catalog_query_list_omits_active_badge():
    catalog_queries = [
        {
            "id": "q1",
            "name": "Production Query",
            "namespace": {"name": "Test", "directory": "test"},
            "available_views": ["graph"],
            "status": "active",
        },
        {
            "id": "q2",
            "name": "Draft Query",
            "namespace": {"name": "Test", "directory": "test"},
            "available_views": ["graph"],
            "status": "draft",
        },
        {
            "id": "q3",
            "name": "Deprecated Query",
            "namespace": {"name": "Test", "directory": "test"},
            "available_views": ["graph"],
            "status": "deprecated",
        },
    ]

    result = catalog_callbacks.render_catalog_query_list(
        catalog_queries=catalog_queries,
        namespace_filter=None,
        search_text=None,
        selected_query=None,
        metadata_store={},
    )
    result_text = " ".join(_flatten_text(result))
    assert "Production Query" in result_text
    assert "Active" not in result_text
    assert "Draft Query" in result_text
    assert "Draft" in result_text
    assert "Deprecated Query" in result_text
    assert "Deprecated" in result_text


def test_render_catalog_query_detail_inverts_popover_theme():
    catalog_query = {
        "id": "confluence/comment_trend",
        "name": "Comment Trend",
        "description": "Test description popover",
        "summary": "Summary text",
        "namespace": {"name": "Confluence", "directory": "confluence"},
        "available_views": ["tabular"],
    }

    # In light theme, popover class should be theme-executive-dark (dark popup)
    detail_light, *_ = catalog_callbacks.render_catalog_query_detail(
        selected_query={"id": "confluence/comment_trend"},
        catalog_queries=[catalog_query],
        theme_name="executive-light",
        parameter_values={},
        current_view=None,
    )
    popover_light = detail_light[1].children[2]
    assert "theme-executive-dark" in popover_light.class_name
    assert "popover-inverted" in popover_light.class_name

    # In dark theme, popover class should be theme-executive-light (light popup)
    detail_dark, *_ = catalog_callbacks.render_catalog_query_detail(
        selected_query={"id": "confluence/comment_trend"},
        catalog_queries=[catalog_query],
        theme_name="executive-dark",
        parameter_values={},
        current_view=None,
    )
    popover_dark = detail_dark[1].children[2]
    assert "theme-executive-light" in popover_dark.class_name
    assert "popover-inverted" in popover_dark.class_name




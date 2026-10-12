"""Layout smoke tests for the Phase 2 catalog editor Test buttons + results modal."""

import pytest

from app.dash_app.pages.catalog.editor_layout import get_editor_layout


pytestmark = pytest.mark.unit


def _collect_ids() -> set[str]:
    """Every component id in the rendered editor layout (exact, unquoted)."""
    ids: set[str] = set()

    def walk(component) -> None:
        if component is None:
            return
        component_id = getattr(component, "id", None)
        if component_id is not None:
            ids.add(str(component_id))
        children = getattr(component, "children", None)
        if isinstance(children, (list, tuple)):
            for child in children:
                walk(child)
        elif children is not None:
            walk(children)

    walk(get_editor_layout())
    return ids


def test_quick_test_tabular_button_present():
    assert "editor-quick-test-tabular" in _collect_ids()


def test_quick_test_graph_button_present():
    assert "editor-quick-test-graph" in _collect_ids()


def test_view_test_tabular_button_present():
    assert "editor-view-test-tabular" in _collect_ids()


def test_view_test_graph_button_present():
    assert "editor-view-test-graph" in _collect_ids()


def test_inline_feedback_divs_present():
    ids = _collect_ids()
    assert "editor-quick-test-tabular-feedback" in ids
    assert "editor-quick-test-graph-feedback" in ids


def _collect_loading_child_ids() -> set[str]:
    """Every component id nested inside a dcc.Loading in the rendered layout."""
    from dash import dcc

    ids: set[str] = set()

    def walk(component, inside_loading: bool) -> None:
        if component is None:
            return
        in_loading = inside_loading or isinstance(component, dcc.Loading)
        component_id = getattr(component, "id", None)
        if in_loading and component_id is not None:
            ids.add(str(component_id))
        children = getattr(component, "children", None)
        if isinstance(children, (list, tuple)):
            for child in children:
                walk(child, in_loading)
        elif children is not None:
            walk(children, in_loading)

    walk(get_editor_layout(), False)
    return ids


def test_inline_feedback_divs_are_wrapped_in_loading():
    loading_ids = _collect_loading_child_ids()
    assert "editor-quick-test-tabular-feedback" in loading_ids
    assert "editor-quick-test-graph-feedback" in loading_ids


def test_test_modal_present():
    assert "editor-test-modal" in _collect_ids()


def test_old_test_results_div_gone():
    assert "editor-test-results" not in _collect_ids()

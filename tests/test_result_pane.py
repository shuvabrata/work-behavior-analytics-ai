"""Unit tests for the shared graph/table result-pane builders.

Tests cover app.dash_app.components.result_pane:
  - create_graph_result_container
  - create_table_result_container
  - create_results_empty_state
"""

import pytest
from dash import html

from app.dash_app.components.result_pane import (
    create_graph_result_container,
    create_results_empty_state,
    create_table_result_container,
)

pytestmark = pytest.mark.unit


def _collect_ids(component) -> set:
    """Collect all component IDs recursively."""
    ids: set = set()
    component_id = getattr(component, "id", None)
    if component_id is not None:
        ids.add(str(component_id))
    children = getattr(component, "children", None)
    if children is None:
        return ids
    if not isinstance(children, (list, tuple)):
        children = [children]
    for child in children:
        ids |= _collect_ids(child)
    return ids


def test_create_graph_result_container_default_ids():
    result = create_graph_result_container()
    assert isinstance(result, html.Div)
    ids = _collect_ids(result)
    assert "graph-cytoscape-container" in ids
    assert "graph-cytoscape" in ids


def test_create_table_result_container_default_id():
    result = create_table_result_container()
    assert isinstance(result, html.Div)
    ids = _collect_ids(result)
    assert "graph-table-container" in ids


def test_create_results_empty_state_default_id():
    result = create_results_empty_state()
    assert isinstance(result, html.Div)
    ids = _collect_ids(result)
    assert "graph-results-container" in ids


def test_id_prefix_applied():
    graph_ids = _collect_ids(create_graph_result_container(id_prefix="editor-test"))
    assert "editor-test-cytoscape-container" in graph_ids
    assert "editor-test-cytoscape" in graph_ids

    table_ids = _collect_ids(create_table_result_container(id_prefix="editor-test"))
    assert "editor-test-table-container" in table_ids

    empty_ids = _collect_ids(create_results_empty_state(id_prefix="editor-test"))
    assert "editor-test-results-container" in empty_ids

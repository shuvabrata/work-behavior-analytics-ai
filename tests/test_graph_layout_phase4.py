"""Layout smoke tests for the Phase 4 Graph page workbench."""

import pytest

from ui.pages.graph.layout import get_layout


pytestmark = pytest.mark.unit


def test_graph_layout_includes_catalog_workbench_components():
    layout = get_layout()
    component_ids = set()

    def walk(component):
        if component is None:
            return
        component_id = getattr(component, "id", None)
        if component_id is not None:
            component_ids.add(str(component_id))
        children = getattr(component, "children", None)
        if isinstance(children, (list, tuple)):
            for child in children:
                walk(child)
        elif children is not None:
            walk(children)

    walk(layout)

    # Catalog is now inside the right-panel workbench tab (right-panel-workbench redesign)
    assert "right-tab-catalog-btn" in component_ids
    assert "right-tab-catalog-collapse" in component_ids
    assert "right-panel-active-tab" in component_ids
    # Removed in redesign: graph-catalog-section, catalog-view-filter
    assert "graph-catalog-section" not in component_ids
    assert "catalog-view-filter" not in component_ids
    # View toggle is present inside the catalog tab (needed for graph/tabular selection)
    assert "catalog-query-view-toggle" in component_ids
    # Catalog content IDs still present inside the right panel tab
    assert "query-catalog-store" in component_ids
    assert "selected-catalog-query-store" in component_ids
    assert "catalog-parameters-store" in component_ids
    assert "catalog-namespace-filter" in component_ids
    assert "catalog-search-input" in component_ids
    assert "catalog-query-list" in component_ids
    assert "catalog-query-detail" in component_ids
    assert "catalog-parameter-inputs" in component_ids
    assert "catalog-run-btn" in component_ids
    assert "catalog-load-console-btn" in component_ids


def _find_by_id(component, target_id):
    if component is None:
        return None
    if str(getattr(component, "id", None)) == target_id:
        return component
    children = getattr(component, "children", None)
    if isinstance(children, (list, tuple)):
        for child in children:
            found = _find_by_id(child, target_id)
            if found is not None:
                return found
    elif children is not None:
        return _find_by_id(children, target_id)
    return None


def test_catalog_tab_wraps_content_in_loading_targeting_load_status():
    """The catalog tab shows a spinner while the catalog fetch is in flight.

    The spinner targets ``query-catalog-load-status``, which the catalog load
    callback writes on both success and failure. It cannot target
    ``query-catalog-store``: ``dcc.Loading`` only sees components inside its own
    subtree, and the store is rendered by ``create_stores()`` elsewhere.
    """
    layout = get_layout()
    loading = _find_by_id(layout, "catalog-tab-loading")

    assert loading is not None
    assert loading.target_components == {"query-catalog-load-status": "children"}

    # The targeted status div must be inside the loading subtree, or the
    # spinner never fires.
    assert _find_by_id(loading, "query-catalog-load-status") is not None
    # And the tab content it wraps must be there too.
    assert _find_by_id(loading, "catalog-query-list") is not None


def test_query_catalog_store_starts_unloaded():
    """The catalog store starts as None so 'not fetched' is distinguishable from 'empty'."""
    layout = get_layout()
    store = _find_by_id(layout, "query-catalog-store")

    assert store is not None
    assert store.data is None

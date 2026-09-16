"""Unit tests for the Analytics gallery page collaboration network controls."""

from __future__ import annotations

import pytest
from dash import html
from app.analytics.collaboration.config import (
    DEFAULT_COMMUNITY_GAP_X,
    DEFAULT_COMMUNITY_GAP_Y,
    DEFAULT_EXCLUDE_BOTS,
    DEFAULT_ENSURE_MIN_CONNECTION,
    DEFAULT_LAYER_WEIGHTS,
    DEFAULT_LOOKBACK_DAYS,
    DEFAULT_MIN_PAIR_SCORE,
    DEFAULT_TOP_N_EDGES_PER_NODE,
    LAYER_ORDER,
)
from app.dash_app.pages.analytics import (
    build_collaboration_href,
    get_layout,
    toggle_collaboration_controls,
)


pytestmark = pytest.mark.unit


def _walk_tree(node) -> list:
    """Recursively collect all Dash component nodes in a layout tree."""
    seen = []

    def walk(curr):
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


def test_layout_contains_layer_table_and_components():
    """Verify the layout includes the 3-column layer table and all layer controls."""
    layout = get_layout()
    assert isinstance(layout, html.Div)

    nodes = _walk_tree(layout)
    node_ids = {getattr(n, "id", None) for n in nodes if hasattr(n, "id")}

    # Bulk action buttons should not be present
    assert "collab-layers-all-btn" not in node_ids
    assert "collab-layers-none-btn" not in node_ids
    assert "collab-layers-reset-btn" not in node_ids

    # Check all layer switches and weight inputs exist
    for layer in LAYER_ORDER:
        assert f"collab-layer-enable-{layer}" in node_ids
        assert f"collab-weight-{layer}" in node_ids

    # Check top and bottom Open Visualization buttons exist
    assert "collab-open-btn" in node_ids
    assert "collab-open-btn-bottom" in node_ids
    assert "collab-url-preview" in node_ids


def test_build_collaboration_href_all_enabled():
    """Href builder outputs URLs with all enabled layers and default parameters."""
    n = len(LAYER_ORDER)
    args = (
        [True] * n  # all layers enabled
        + [
            DEFAULT_LOOKBACK_DAYS,
            DEFAULT_MIN_PAIR_SCORE,
            DEFAULT_TOP_N_EDGES_PER_NODE,
            DEFAULT_COMMUNITY_GAP_X,
            DEFAULT_COMMUNITY_GAP_Y,
            DEFAULT_EXCLUDE_BOTS,
            DEFAULT_ENSURE_MIN_CONNECTION,
        ]
        + [DEFAULT_LAYER_WEIGHTS[l] for l in LAYER_ORDER]
    )

    top_href, bottom_href, preview = build_collaboration_href(*args)
    assert top_href == bottom_href
    assert top_href.startswith("/app/collaboration?")
    assert f"URL: {top_href}" == preview

    # Parse query string and verify every single field and layer weight is present
    from urllib.parse import parse_qs
    query_string = top_href.split("?")[1]
    parsed = parse_qs(query_string)

    assert "layers" in parsed
    enabled_layers = parsed["layers"][0].split(",")
    assert enabled_layers == list(LAYER_ORDER)

    assert parsed["lookback_days"] == [str(DEFAULT_LOOKBACK_DAYS)]
    assert parsed["min_pair_score"] == [str(DEFAULT_MIN_PAIR_SCORE)]
    assert parsed["top_n_edges_per_node"] == [str(DEFAULT_TOP_N_EDGES_PER_NODE)]
    assert parsed["community_gap_x"] == [str(DEFAULT_COMMUNITY_GAP_X)]
    assert parsed["community_gap_y"] == [str(DEFAULT_COMMUNITY_GAP_Y)]
    assert parsed["exclude_bots"] == [str(DEFAULT_EXCLUDE_BOTS).lower()]
    assert parsed["ensure_min_connection"] == [str(DEFAULT_ENSURE_MIN_CONNECTION).lower()]

    for layer in LAYER_ORDER:
        assert f"w_{layer}" in parsed
        assert parsed[f"w_{layer}"] == [str(DEFAULT_LAYER_WEIGHTS[layer])]


def test_build_collaboration_href_selective_layers():
    """Disabling layers omits them from the enabled layers query parameter."""
    n = len(LAYER_ORDER)
    enables = [False] * n
    enables[0] = True  # only first layer (reporter_assignee) enabled

    args = (
        enables
        + [
            90,
            1.5,
            10,
            2000.0,
            1500.0,
            True,
            True,
        ]
        + [DEFAULT_LAYER_WEIGHTS[l] for l in LAYER_ORDER]
    )

    top_href, bottom_href, _ = build_collaboration_href(*args)
    assert top_href == bottom_href
    assert "layers=reporter_assignee" in top_href
    assert "pr_reviews" not in top_href.split("layers=")[1].split("&")[0]


def test_build_collaboration_href_all_layers_disabled():
    """Disabling every layer produces an empty enabled-layers query param."""
    n = len(LAYER_ORDER)
    args = (
        [False] * n  # all layers disabled
        + [
            DEFAULT_LOOKBACK_DAYS,
            DEFAULT_MIN_PAIR_SCORE,
            DEFAULT_TOP_N_EDGES_PER_NODE,
            DEFAULT_COMMUNITY_GAP_X,
            DEFAULT_COMMUNITY_GAP_Y,
            DEFAULT_EXCLUDE_BOTS,
            DEFAULT_ENSURE_MIN_CONNECTION,
        ]
        + [DEFAULT_LAYER_WEIGHTS[l] for l in LAYER_ORDER]
    )

    top_href, bottom_href, _ = build_collaboration_href(*args)
    assert top_href == bottom_href
    assert "layers=" in top_href
    # The layers param must be present but empty (no layer names after '=').
    layers_param = top_href.split("layers=")[1].split("&")[0]
    assert layers_param == ""


def test_toggle_collaboration_controls():
    """Toggling collaboration controls changes visibility and button label."""
    is_open, label = toggle_collaboration_controls(1, False)
    assert is_open is True
    assert label == "Hide Options"

    is_open, label = toggle_collaboration_controls(2, True)
    assert is_open is False
    assert label == "Show Options"

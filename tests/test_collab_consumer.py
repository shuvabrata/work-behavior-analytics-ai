"""Unit tests for the collaboration network consumer callback."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from app.analytics.collaboration.config import (
    DEFAULT_LAYER_WEIGHTS,
    LAYER_ORDER,
)
from app.dash_app.pages.collaboration_network.callbacks.filter import (
    load_collaboration_network,
)


pytestmark = pytest.mark.unit


class _FakeResult:
    """Minimal stand-in for the get_collaboration_network return value."""

    def __init__(self, elements, config):
        self.elements = elements
        self.config = config or {}
        self.num_people = 2
        self.num_pairs = 1
        self.num_communities = 1
        self.modularity = 0.5


def _make_search(**params) -> str:
    """Build a URL search string (e.g. '?layers=a,b&w_pr_reviews=4.5')."""
    from urllib.parse import urlencode
    return "?" + urlencode(params)


def test_load_collaboration_network_parses_weights_and_layers():
    """The consumer parses per-layer weights and enabled layers from the URL."""
    search = _make_search(
        layers="pr_reviews,epic_overlap",
        w_pr_reviews="4.5",
        w_epic_overlap="2.0",
        lookback_days="60",
    )
    fake = _FakeResult(elements=[{"data": {"id": "n1"}}], config={})

    with patch(
        "app.dash_app.pages.collaboration_network.callbacks.filter.get_collaboration_network",
        return_value=fake,
    ) as mock_fetch:
        outputs = load_collaboration_network(search, "/app/collaboration")

    # The mock was called with a config carrying the parsed values.
    config = mock_fetch.call_args.kwargs["config"]
    assert config.enabled_layers == ["pr_reviews", "epic_overlap"]
    assert config.weights["pr_reviews"] == 4.5
    assert config.weights["epic_overlap"] == 2.0
    assert config.lookback_days == 60

    # Non-listed layers keep their defaults.
    assert config.weights["reporter_assignee"] == DEFAULT_LAYER_WEIGHTS["reporter_assignee"]

    # Six outputs are returned (store, layout, banner children, banner style,
    # empty-state style, loading-state).
    assert len(outputs) == 6


def test_load_collaboration_network_ignores_other_pathnames():
    """Non-collaboration routes raise PreventUpdate."""
    from dash.exceptions import PreventUpdate

    with pytest.raises(PreventUpdate):
        load_collaboration_network("", "/app/graph")


def test_load_collaboration_network_empty_layers_stays_empty():
    """An explicit empty layers param produces an empty enabled set (post-021)."""
    search = _make_search(layers="")
    fake = _FakeResult(elements=[{"data": {"id": "n1"}}], config={})

    with patch(
        "app.dash_app.pages.collaboration_network.callbacks.filter.get_collaboration_network",
        return_value=fake,
    ) as mock_fetch:
        load_collaboration_network(search, "/app/collaboration")

    config = mock_fetch.call_args.kwargs["config"]
    assert config.enabled_layers == []

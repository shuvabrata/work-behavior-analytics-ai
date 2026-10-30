"""Unit tests for the collaboration network consumer callback."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from domain.collaboration.config import (
    DEFAULT_LAYER_WEIGHTS,
    LAYER_ORDER,
    CollaborationNetworkConfig,
)
from ui.pages.collaboration_network.callbacks.filter import (
    load_collaboration_network,
)


pytestmark = pytest.mark.unit


def _fake_response() -> dict:
    """Minimal stand-in for the collaboration endpoint's JSON body.

    Step 7 of plan 052 swapped the in-process ``get_collaboration_network`` call
    for ``api_client.get_json``, so the callback now consumes a parsed dict
    rather than a response model.
    """
    return {
        "elements": [{"data": {"id": "n1"}}],
        "config": {},
        "num_people": 2,
        "num_pairs": 1,
        "num_communities": 1,
        "modularity": 0.5,
    }


def _config_from(params: dict) -> CollaborationNetworkConfig:
    """Rebuild the config the callback would have sent, from its query params."""
    return CollaborationNetworkConfig.from_query_values(params)


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

    with patch(
        "ui.pages.collaboration_network.callbacks.filter.api_client.get_json",
        return_value=_fake_response(),
    ) as mock_fetch:
        outputs = load_collaboration_network(search, "/app/collaboration")

    # The query params the callback sent carry the parsed values; round-tripping
    # them through the config model is what the endpoint itself does.
    config = _config_from(mock_fetch.call_args.kwargs["params"])
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

    with patch(
        "ui.pages.collaboration_network.callbacks.filter.api_client.get_json",
        return_value=_fake_response(),
    ) as mock_fetch:
        load_collaboration_network(search, "/app/collaboration")

    config = _config_from(mock_fetch.call_args.kwargs["params"])
    assert config.enabled_layers == []

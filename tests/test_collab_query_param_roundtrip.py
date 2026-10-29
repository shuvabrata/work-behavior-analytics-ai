"""Round-trip guard for the collaboration config → query-param serializer.

The UI builds a ``CollaborationNetworkConfig`` and, after Step 7 of plan 052,
sends it to ``/api/v1/graph/collaboration-network[/ego]`` as flat query params
produced by ``ui.collaboration_params.config_to_query_params``. The endpoint
parses those params back with ``CollaborationNetworkConfig.from_query_values``.

A param the serializer forgets to emit silently reverts to the endpoint's
``Query(default=…)`` value, so the graph the user asked for is not the graph they
get. This test is the primary guard on that translation.

This file defines its own ``SEEDED_CONFIGS`` rather than importing the (temporary)
baseline script's copy: ``tests/`` must not import from ``scripts/``, and the two
lists serve different purposes — the script's is sized to keep the live run
cheap, this one is sized to vary every field.
"""

from __future__ import annotations

import pytest

from domain.collaboration.config import (
    DEFAULT_EXCLUDED_FILE_SUFFIXES,
    LAYER_ORDER,
    CollaborationNetworkConfig,
)
from ui.collaboration_params import config_to_query_params

pytestmark = pytest.mark.unit

_WEIGHTS_ALL_ZERO = {layer: 0.0 for layer in LAYER_ORDER}


#: A matrix that varies every serialized field away from its default at least
#: once. ``focus_id`` is deliberately left ``None``: ``from_query_values`` does
#: not read it, so no value there could survive the round-trip (and the org
#: endpoint takes it from the URL, not the config).
SEEDED_CONFIGS: list[CollaborationNetworkConfig] = [
    # Every field at its default — the identity case.
    CollaborationNetworkConfig(),
    # Non-default lookback and Top-N.
    CollaborationNetworkConfig(lookback_days=30, top_n_edges_per_node=5),
    # A layer subset, the minimum pair score, and bot inclusion.
    CollaborationNetworkConfig(
        enabled_layers=["pr_reviews", "shared_file_commits"],
        min_pair_score=0.0,
        exclude_bots=False,
    ),
    # A non-empty suffix list that differs from the default.
    CollaborationNetworkConfig(
        excluded_file_suffixes=[".json", ".md", ".lock", ".yaml", ".min.js"],
    ),
    # Non-default community gaps, both ends of their range.
    CollaborationNetworkConfig(community_gap_x=200.0, community_gap_y=10000.0),
    # The ensure_min_connection off-switch and a high Top-N.
    CollaborationNetworkConfig(ensure_min_connection=False, top_n_edges_per_node=200),
    # All layers off — ``layers=""`` on the wire, which must parse back to [].
    CollaborationNetworkConfig(enabled_layers=[]),
    # Every weight zero except one, so a single dropped ``w_*`` line is a
    # mismatch rather than a silent fall-back to that layer's default.
    CollaborationNetworkConfig(
        weights={**_WEIGHTS_ALL_ZERO, "confluence_mentions": 7.5},
    ),
    # The maximum lookback, at the model's upper bound.
    CollaborationNetworkConfig(lookback_days=365),
]


@pytest.mark.parametrize("config", SEEDED_CONFIGS)
def test_config_to_query_params_round_trips(
    config: CollaborationNetworkConfig,
) -> None:
    """``from_query_values(config_to_query_params(c)) == c`` over a seeded matrix."""
    round_tripped = CollaborationNetworkConfig.from_query_values(
        config_to_query_params(config)
    )
    assert round_tripped == config


@pytest.mark.unit
def test_empty_suffix_list_falls_back_to_defaults() -> None:
    """The one documented lossy edge: an empty suffix list cannot survive.

    ``from_query_values`` reads ``excluded_file_suffixes`` as
    ``excluded_suffixes or list(DEFAULT_EXCLUDED_FILE_SUFFIXES)``
    (``domain/collaboration/config.py``), so an empty list comes back as the
    defaults. Documented here rather than "fixed": every other field round-trips
    exactly, and changing the fallback would change the endpoint's behaviour.
    """
    config = CollaborationNetworkConfig(excluded_file_suffixes=[])
    round_tripped = CollaborationNetworkConfig.from_query_values(
        config_to_query_params(config)
    )
    assert round_tripped.excluded_file_suffixes == list(DEFAULT_EXCLUDED_FILE_SUFFIXES)

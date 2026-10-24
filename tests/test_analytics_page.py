"""Unit tests for the Analytics gallery page collaboration network controls.

Covers both collaboration cards: the org-wide network and the per-person one.
They share one parameterised builder, so most assertions run over both prefixes
to catch any drift between them.
"""

from __future__ import annotations

from urllib.parse import parse_qs

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
from app.analytics.collaboration.ego import COLLABORATOR_CAP_OPTIONS, DEFAULT_MAX_COLLABORATORS
from app.analytics.registry import GRAPH_ANALYTICS
from app.dash_app.pages.analytics import (
    COLLABORATION_CARD_SPEC,
    PER_PERSON_CARD_SPEC,
    _toggle_controls_state,
    build_collaboration_href,
    build_per_person_href,
    get_layout,
)


pytestmark = pytest.mark.unit

COLLAB = COLLABORATION_CARD_SPEC.prefix
EGO = PER_PERSON_CARD_SPEC.prefix


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


def _norm_id(component_id) -> str:
    """Flatten a string or pattern-matching (dict) Dash id to a comparable key."""
    if isinstance(component_id, dict):
        return "|".join(f"{key}={component_id[key]}" for key in sorted(component_id))
    return str(component_id)


def _all_ids(layout) -> set[str]:
    nodes = _walk_tree(layout)
    return {_norm_id(n.id) for n in nodes if getattr(n, "id", None) is not None}


def test_layout_contains_a_card_per_registered_analytic():
    """Every registry analytic renders a card, and both collaboration cards
    carry the full layer table."""
    layout = get_layout()
    assert isinstance(layout, html.Div)
    ids = _all_ids(layout)

    for prefix in (COLLAB, EGO):
        for layer in LAYER_ORDER:
            assert _norm_id({"type": f"{prefix}-layer-enable", "layer": layer}) in ids
            assert _norm_id({"type": f"{prefix}-weight", "layer": layer}) in ids
        assert f"{prefix}-open-btn" in ids
        assert f"{prefix}-open-btn-bottom" in ids
        assert f"{prefix}-url-preview" in ids
        assert f"{prefix}-controls-toggle-btn" in ids


def test_both_collaboration_cards_have_distinct_component_ids():
    """Dash ids are global: rendering the shared builder twice must not collide.

    Counts raw occurrences rather than a de-duplicated set, so a genuine
    duplicate id actually fails this test.
    """
    raw_ids = [
        _norm_id(n.id)
        for n in _walk_tree(get_layout())
        if getattr(n, "id", None) is not None
    ]
    duplicates = sorted({i for i in raw_ids if raw_ids.count(i) > 1})
    assert duplicates == [], f"duplicate component ids: {duplicates}"


def test_org_card_renders_org_only_controls():
    """Community layout and topology pruning belong to the org view only."""
    ids = _all_ids(get_layout())
    assert f"{COLLAB}-community-gap-x" in ids
    assert f"{COLLAB}-community-gap-y" in ids
    assert f"{COLLAB}-top-n-edges" in ids
    assert f"{COLLAB}-ensure-min-connection" in ids
    assert f"{COLLAB}-collaborator-cap" not in ids


def test_ego_card_omits_controls_the_view_ignores():
    """The per-person view has no communities and no org topology pruning, so
    those controls must be absent rather than present-but-inert."""
    ids = _all_ids(get_layout())
    assert f"{EGO}-community-gap-x" not in ids
    assert f"{EGO}-community-gap-y" not in ids
    assert f"{EGO}-top-n-edges" not in ids
    assert f"{EGO}-ensure-min-connection" not in ids


def test_ego_card_renders_collaborator_cap():
    """The per-person card offers a collaborator cap in place of Top-N edges."""
    ids = _all_ids(get_layout())
    assert f"{EGO}-collaborator-cap" in ids


def test_registry_declares_both_collaboration_analytics():
    keys = {analytic.key for analytic in GRAPH_ANALYTICS}
    assert "collaboration_network" in keys
    assert "per_person_collaboration_network" in keys
    # The per-person card launches its own page, not the generic graph page.
    ego_analytic = next(a for a in GRAPH_ANALYTICS if a.key == "per_person_collaboration_network")
    assert ego_analytic.href == "/app/collaboration/person"


def test_layout_has_no_bulk_layer_action_buttons():
    ids = _all_ids(get_layout())
    for prefix in (COLLAB, EGO):
        assert f"{prefix}-layers-all-btn" not in ids
        assert f"{prefix}-layers-none-btn" not in ids
        assert f"{prefix}-layers-reset-btn" not in ids


# ---------------------------------------------------------------------------
# build_collaboration_href (org card)
# ---------------------------------------------------------------------------

def _org_args(
    enables: list[bool] | None = None,
    weights: list[float] | None = None,
    *,
    lookback_days: float = DEFAULT_LOOKBACK_DAYS,
    min_pair_score: float = DEFAULT_MIN_PAIR_SCORE,
    top_n_edges_per_node: float = DEFAULT_TOP_N_EDGES_PER_NODE,
    community_gap_x: float = DEFAULT_COMMUNITY_GAP_X,
    community_gap_y: float = DEFAULT_COMMUNITY_GAP_Y,
    exclude_bots: bool = DEFAULT_EXCLUDE_BOTS,
    ensure_min_connection: bool = DEFAULT_ENSURE_MIN_CONNECTION,
) -> tuple:
    """Positional args matching build_collaboration_href's declared inputs."""
    return (
        enables if enables is not None else [True] * len(LAYER_ORDER),
        lookback_days,
        min_pair_score,
        top_n_edges_per_node,
        community_gap_x,
        community_gap_y,
        exclude_bots,
        ensure_min_connection,
        weights if weights is not None else [DEFAULT_LAYER_WEIGHTS[l] for l in LAYER_ORDER],
    )


def test_build_collaboration_href_all_enabled():
    """Href builder outputs URLs with all enabled layers and default parameters."""
    top_href, bottom_href, preview = build_collaboration_href(*_org_args())
    assert top_href == bottom_href
    assert top_href.startswith("/app/collaboration?")
    assert f"URL: {top_href}" == preview

    parsed = parse_qs(top_href.split("?")[1])
    assert "layers" in parsed
    assert parsed["layers"][0].split(",") == list(LAYER_ORDER)

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
    enables = [False] * len(LAYER_ORDER)
    enables[0] = True  # only the first layer is enabled

    top_href, bottom_href, _ = build_collaboration_href(*_org_args(enables))
    assert top_href == bottom_href
    assert f"layers={LAYER_ORDER[0]}" in top_href
    assert LAYER_ORDER[1] not in top_href.split("layers=")[1].split("&")[0]


def test_build_collaboration_href_all_layers_disabled():
    """Disabling every layer produces an empty enabled-layers query param."""
    top_href, _, _ = build_collaboration_href(*_org_args([False] * len(LAYER_ORDER)))
    assert "layers=" in top_href
    assert top_href.split("layers=")[1].split("&")[0] == ""


def test_build_collaboration_href_uses_layer_order_for_weights():
    """Weights map to layers positionally, so a reordered LAYER_ORDER cannot
    silently attach a weight to the wrong layer."""
    weights = [float(i + 1) for i in range(len(LAYER_ORDER))]
    top_href, _, _ = build_collaboration_href(*_org_args(weights=weights))

    parsed = parse_qs(top_href.split("?")[1])
    for layer, weight in zip(LAYER_ORDER, weights):
        assert parsed[f"w_{layer}"] == [str(weight)]


# ---------------------------------------------------------------------------
# build_per_person_href (ego card)
# ---------------------------------------------------------------------------

def _ego_args(
    enables: list[bool] | None = None,
    weights: list[float] | None = None,
    *,
    lookback_days: float = DEFAULT_LOOKBACK_DAYS,
    min_pair_score: float = DEFAULT_MIN_PAIR_SCORE,
    exclude_bots: bool = DEFAULT_EXCLUDE_BOTS,
    max_collaborators: int = DEFAULT_MAX_COLLABORATORS,
) -> tuple:
    """Positional args matching build_per_person_href's declared inputs."""
    return (
        enables if enables is not None else [True] * len(LAYER_ORDER),
        lookback_days,
        min_pair_score,
        exclude_bots,
        max_collaborators,
        weights if weights is not None else [DEFAULT_LAYER_WEIGHTS[l] for l in LAYER_ORDER],
    )


def test_build_per_person_href_carries_shared_config_and_cap():
    top_href, bottom_href, preview = build_per_person_href(*_ego_args())
    assert top_href == bottom_href
    assert top_href.startswith("/app/collaboration/person?")
    assert f"URL: {top_href}" == preview

    parsed = parse_qs(top_href.split("?")[1])
    assert parsed["layers"][0].split(",") == list(LAYER_ORDER)
    assert parsed["max_collaborators"] == [str(DEFAULT_MAX_COLLABORATORS)]
    assert parsed["exclude_bots"] == [str(DEFAULT_EXCLUDE_BOTS).lower()]
    for layer in LAYER_ORDER:
        assert parsed[f"w_{layer}"] == [str(DEFAULT_LAYER_WEIGHTS[layer])]


def test_build_per_person_href_omits_org_only_params():
    """The ego page ignores community/topology params, so the card must not
    advertise settings it cannot honour."""
    top_href, _, _ = build_per_person_href(*_ego_args())
    parsed = parse_qs(top_href.split("?")[1])
    for absent in ("community_gap_x", "community_gap_y", "top_n_edges_per_node", "ensure_min_connection"):
        assert absent not in parsed


def test_both_cards_share_layer_configuration_keys():
    """Adding a layer must reach both cards: both emit the same w_<layer> set."""
    org_href, _, _ = build_collaboration_href(*_org_args())
    ego_href, _, _ = build_per_person_href(*_ego_args())

    org_params = parse_qs(org_href.split("?")[1])
    ego_params = parse_qs(ego_href.split("?")[1])

    org_weight_keys = {k for k in org_params if k.startswith("w_")}
    ego_weight_keys = {k for k in ego_params if k.startswith("w_")}
    assert org_weight_keys == ego_weight_keys
    assert org_weight_keys == {f"w_{layer}" for layer in LAYER_ORDER}
    assert org_params["layers"] == ego_params["layers"]


def test_collaborator_cap_options_are_offered_by_both_surfaces():
    """The card's cap Select and the page's in-page selector share one source."""
    ids = _all_ids(get_layout())
    assert f"{EGO}-collaborator-cap" in ids
    assert DEFAULT_MAX_COLLABORATORS in COLLABORATOR_CAP_OPTIONS


def test_adding_a_layer_reaches_both_cards():
    """A new layer in config.py must appear on BOTH cards with no edit here.

    This is the guarantee the shared, ``LAYER_ORDER``-driven builder exists to
    provide. The layer is appended in place (the card builders hold the same
    list/dict objects config.py exports) and removed again afterwards.
    """
    from app.analytics.collaboration import config as config_module

    new_layer = "synthetic_19th_layer"
    config_module.LAYER_ORDER.append(new_layer)
    config_module.LAYER_LABELS[new_layer] = "Synthetic 19th Layer"
    config_module.DEFAULT_LAYER_WEIGHTS[new_layer] = 1.5
    try:
        assert len(LAYER_ORDER) == len(config_module.LAYER_ORDER)

        # 1. Both cards render a row for it.
        ids = _all_ids(get_layout())
        for prefix in (COLLAB, EGO):
            assert _norm_id({"type": f"{prefix}-layer-enable", "layer": new_layer}) in ids
            assert _norm_id({"type": f"{prefix}-weight", "layer": new_layer}) in ids

        # 2. Both href builders carry it, at the matching default weight.
        n = len(LAYER_ORDER)
        org_href, _, _ = build_collaboration_href(*_org_args([True] * n))
        ego_href, _, _ = build_per_person_href(*_ego_args([True] * n))

        for href in (org_href, ego_href):
            parsed = parse_qs(href.split("?")[1])
            assert parsed[f"w_{new_layer}"] == ["1.5"]
            assert new_layer in parsed["layers"][0].split(",")
    finally:
        config_module.LAYER_ORDER.remove(new_layer)
        del config_module.LAYER_LABELS[new_layer]
        del config_module.DEFAULT_LAYER_WEIGHTS[new_layer]


def test_renaming_a_layer_label_reaches_both_cards():
    """Renaming a layer's label updates both cards (labels are looked up, not
    duplicated)."""
    from app.analytics.collaboration import config as config_module

    layer = LAYER_ORDER[0]
    original = config_module.LAYER_LABELS[layer]
    config_module.LAYER_LABELS[layer] = "Renamed Label Probe"
    try:
        rendered = str(get_layout())
        assert rendered.count("Renamed Label Probe") == 2, "expected one label per card"
        assert original not in rendered
    finally:
        config_module.LAYER_LABELS[layer] = original


def test_toggle_controls_state():
    """Toggling a controls panel changes visibility and button label."""
    is_open, label, preview_style = _toggle_controls_state(False)
    assert is_open is True
    assert label == "Hide Options"
    assert preview_style["display"] == "block"

    is_open, label, preview_style = _toggle_controls_state(True)
    assert is_open is False
    assert label == "Show Options"
    assert preview_style["display"] == "none"

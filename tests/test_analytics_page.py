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
    CollaborationNetworkConfig,
    DEFAULT_COMMUNITY_GAP_X,
    DEFAULT_COMMUNITY_GAP_Y,
    DEFAULT_EXCLUDE_BOTS,
    DEFAULT_ENSURE_MIN_CONNECTION,
    DEFAULT_LAYER_WEIGHTS,
    DEFAULT_LOOKBACK_DAYS,
    DEFAULT_MIN_PAIR_SCORE,
    DEFAULT_TOP_N_EDGES_PER_NODE,
    LAYER_LABELS,
    LAYER_ORDER,
    SETTING_LABELS,
)
from app.analytics.collaboration.ego import COLLABORATOR_CAP_OPTIONS
from app.analytics.registry import GRAPH_ANALYTICS
from domain.person_network_url import DEFAULT_MAX_COLLABORATORS
from app.dash_app.components.common import describe_config_error
from app.dash_app.pages.analytics import (
    COLLABORATION_CARD_SPEC,
    PER_PERSON_CARD_SPEC,
    _bounds_for,
    _config_alert,
    _config_from_layer_inputs,
    _is_integer_field,
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
    top_href, bottom_href, preview, *_ = build_collaboration_href(*_org_args())
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

    top_href, bottom_href, *_ = build_collaboration_href(*_org_args(enables))
    assert top_href == bottom_href
    assert f"layers={LAYER_ORDER[0]}" in top_href
    assert LAYER_ORDER[1] not in top_href.split("layers=")[1].split("&")[0]


def test_build_collaboration_href_all_layers_disabled():
    """Disabling every layer produces an empty enabled-layers query param."""
    top_href, *_ = build_collaboration_href(*_org_args([False] * len(LAYER_ORDER)))
    assert "layers=" in top_href
    assert top_href.split("layers=")[1].split("&")[0] == ""


def test_build_collaboration_href_uses_layer_order_for_weights():
    """Weights map to layers positionally, so a reordered LAYER_ORDER cannot
    silently attach a weight to the wrong layer."""
    weights = [float(i + 1) for i in range(len(LAYER_ORDER))]
    top_href, *_ = build_collaboration_href(*_org_args(weights=weights))

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
    top_href, bottom_href, preview, *_ = build_per_person_href(*_ego_args())
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
    top_href, *_ = build_per_person_href(*_ego_args())
    parsed = parse_qs(top_href.split("?")[1])
    for absent in ("community_gap_x", "community_gap_y", "top_n_edges_per_node", "ensure_min_connection"):
        assert absent not in parsed


def test_both_cards_share_layer_configuration_keys():
    """Adding a layer must reach both cards: both emit the same w_<layer> set."""
    org_href, *_ = build_collaboration_href(*_org_args())
    ego_href, *_ = build_per_person_href(*_ego_args())

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
        org_href, *_ = build_collaboration_href(*_org_args([True] * n))
        ego_href, *_ = build_per_person_href(*_ego_args([True] * n))

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


# ---------------------------------------------------------------------------
# Out-of-range control values are reported, never rewritten
# ---------------------------------------------------------------------------

def _config_kwargs(**overrides) -> dict:
    """Keyword args for _config_from_layer_inputs with a non-default baseline.

    One layer is enabled with a weight the user changed, and every other control
    differs from the model default, so a discarded configuration is detectable.
    """
    kwargs = {
        "layer_enables": [layer == "pr_reviews" for layer in LAYER_ORDER],
        "layer_weights": [DEFAULT_LAYER_WEIGHTS[layer] for layer in LAYER_ORDER],
        "lookback_days": 30,
        "min_pair_score": 2.0,
        "exclude_bots": False,
        "top_n_edges_per_node": 15,
        "community_gap_x": 2000.0,
        "community_gap_y": 1500.0,
        "ensure_min_connection": False,
    }
    kwargs.update(overrides)
    return kwargs


def test_numeric_inputs_carry_no_html_range_constraints():
    """The card's inputs must not re-add min/max, and must stay step="any".

    min/max make the browser reject a value before Dash sends it, so the callback
    receives None — which the card treats as "cleared box, not an error" and
    silently replaces with a default. Deleting step is NOT enough: HTML's default
    step is 1, so an input with no step attribute still reports stepMismatch for
    2.5 and posts None. Only step="any" disables it. Both halves were the bug plan
    053 fixed: an out-of-range or fractional entry produced no alert and left the
    launch buttons enabled. Validation belongs to _validate_control /
    _validate_weight, which can explain itself in the alert region.
    """
    range_offenders = []
    step_offenders = []
    for node in _walk_tree(get_layout()):
        if getattr(node, "type", None) != "number":
            continue
        node_id = str(getattr(node, "id", "?"))
        for attr in ("min", "max"):
            if getattr(node, attr, None) is not None:
                range_offenders.append((node_id, attr))
        if getattr(node, "step", None) != "any":
            step_offenders.append((node_id, getattr(node, "step", None)))
    assert range_offenders == [], (
        "numeric inputs must not carry min/max: " + repr(range_offenders)
    )
    assert step_offenders == [], (
        'numeric inputs must all be step="any": ' + repr(step_offenders)
    )


@pytest.mark.parametrize("key", sorted(SETTING_LABELS))
def test_card_bounds_follow_the_model(key):
    """A Field bound change must reach the card with no edit to analytics.py."""
    schema = CollaborationNetworkConfig.model_json_schema()["properties"][key]
    assert _bounds_for(key) == (schema.get("minimum"), schema.get("maximum")), key


def test_valid_values_are_untouched():
    """An all-in-range configuration passes through with no problems."""
    config, problems = _config_from_layer_inputs(**_config_kwargs())
    assert problems == []
    assert config.lookback_days == 30
    assert config.min_pair_score == 2.0
    assert config.exclude_bots is False
    assert config.top_n_edges_per_node == 15
    assert (config.community_gap_x, config.community_gap_y) == (2000.0, 1500.0)


def test_out_of_range_lookback_is_reported_not_changed():
    """The bad value is reported as a requirement, never rewritten into range.

    The message states what the range *is* ("must be between 1 and 365") rather
    than what the app did to the value ("was adjusted to 365"). Nothing rewrites
    ``366`` anywhere in the card path.
    """
    weights = [DEFAULT_LAYER_WEIGHTS[layer] for layer in LAYER_ORDER]
    weights[LAYER_ORDER.index("pr_reviews")] = 9.0
    _config, problems = _config_from_layer_inputs(
        **_config_kwargs(lookback_days=366, layer_weights=weights)
    )
    assert [problem.label for problem in problems] == ["Lookback Days"]
    assert "between 1 and 365" in problems[0].message
    assert "must be between" in problems[0].message
    assert "adjusted" not in problems[0].message

    # Contrast: the same inputs with an in-range lookback carry every user
    # setting through untouched and report nothing.
    config, problems = _config_from_layer_inputs(
        **_config_kwargs(lookback_days=30, layer_weights=weights)
    )
    assert problems == []
    assert config.lookback_days == 30
    assert config.enabled_layers == ["pr_reviews"]
    assert config.weights["pr_reviews"] == 9.0
    assert config.min_pair_score == 2.0
    assert config.exclude_bots is False
    assert config.top_n_edges_per_node == 15
    assert (config.community_gap_x, config.community_gap_y) == (2000.0, 1500.0)


@pytest.mark.parametrize("key", sorted(SETTING_LABELS))
def test_each_bounded_field_is_rejected_and_named(key):
    """Every bounded field reports a problem at both ends and names itself."""
    lower, upper = _bounds_for(key)
    label = SETTING_LABELS[key]

    _config, problems = _config_from_layer_inputs(**_config_kwargs(**{key: lower - 1}))
    assert [p.label for p in problems] == [label], key
    assert label in problems[0].message, key

    if upper is not None:
        _config, problems = _config_from_layer_inputs(**_config_kwargs(**{key: upper + 1}))
        assert [p.label for p in problems] == [label], key
        assert label in problems[0].message, key


def test_negative_weight_is_reported_and_named():
    """A negative layer weight is rejected, and the problem names the layer."""
    layer = "pr_reviews"
    weights = [DEFAULT_LAYER_WEIGHTS[other] for other in LAYER_ORDER]
    weights[LAYER_ORDER.index(layer)] = -1.0

    _config, problems = _config_from_layer_inputs(**_config_kwargs(layer_weights=weights))
    assert any(LAYER_LABELS[layer] in problem.label for problem in problems)
    assert any("negative" in problem.message for problem in problems)


def test_fractional_integer_field_is_reported_and_named():
    """A fraction typed into an int field is reported, not silently truncated.

    lookback_days and top_n_edges_per_node are ``int`` on the model, and the card
    posts a float; from_query_values does int(raw), so 2.5 used to become 2 with
    no problem reported (2.5 is inside 1..365, so the bounds check passed).
    """
    for key, label in (("lookback_days", "Lookback Days"),
                       ("top_n_edges_per_node", "Top-N Edges / Node")):
        _config, problems = _config_from_layer_inputs(**_config_kwargs(**{key: 2.5}))
        assert [p.label for p in problems] == [label], key
        assert problems[0].message == f"{label} must be a whole number.", key


def test_whole_number_float_is_not_reported():
    """2.0 is a whole number: a browser can post it for a box holding 2."""
    for key in ("lookback_days", "top_n_edges_per_node"):
        _config, problems = _config_from_layer_inputs(**_config_kwargs(**{key: 2.0}))
        assert problems == [], (key, problems)


@pytest.mark.parametrize("key", sorted(SETTING_LABELS))
def test_float_fields_still_accept_fractions(key):
    """The whole-number rule must not leak onto the float fields."""
    if _is_integer_field(key):
        pytest.skip(f"{key} is an integer field")
    lower, upper = _bounds_for(key)
    # pick a fractional value inside the field's own bounds
    value = (lower if lower is not None else 0) + 0.5
    if upper is not None and value > upper:
        value = upper - 0.5
    _config, problems = _config_from_layer_inputs(**_config_kwargs(**{key: value}))
    assert problems == [], (key, value, problems)


def test_cleared_field_uses_default_without_a_warning():
    """A cleared box is not an error: the model default applies and nothing warns."""
    config, problems = _config_from_layer_inputs(**_config_kwargs(lookback_days=None))
    assert config.lookback_days == DEFAULT_LOOKBACK_DAYS
    assert problems == []


def test_unparseable_value_is_reported():
    """A non-numeric value is reported rather than silently replaced."""
    _config, problems = _config_from_layer_inputs(**_config_kwargs(lookback_days="abc"))
    assert len(problems) == 1
    assert problems[0].label == "Lookback Days"
    assert "must be a number" in problems[0].message


def test_href_callbacks_surface_the_alert_and_disable_the_buttons():
    """Both cards report the problems and disable both launch buttons."""
    _top, _bottom, _preview, alert, style, btn, btn_bottom = build_collaboration_href(
        *_org_args(lookback_days=400)
    )
    assert alert
    assert style == {"display": "block"}
    assert btn is True
    assert btn_bottom is True

    _top, _bottom, _preview, alert, style, btn, btn_bottom = build_collaboration_href(
        *_org_args()
    )
    assert alert == []
    assert style == {"display": "none"}
    assert btn is False
    assert btn_bottom is False

    _top, _bottom, _preview, alert, style, btn, btn_bottom = build_per_person_href(
        *_ego_args()
    )
    assert alert == []
    assert style == {"display": "none"}
    assert btn is False
    assert btn_bottom is False


def test_config_alert_reports_each_problem():
    """One <li> per problem while blocked; an empty, hidden region otherwise."""
    from app.dash_app.pages.analytics import _ControlProblem

    problems = [
        _ControlProblem("Lookback Days", "Lookback Days must be between 1 and 365."),
        _ControlProblem("Min Pair Score", "Min Pair Score must be at least 0."),
    ]
    children, style, blocked = _config_alert(problems)
    assert blocked is True
    assert style == {"display": "block"}
    assert len(children) == 1
    items = [n for n in _walk_tree(children[0]) if isinstance(n, html.Li)]
    assert len(items) == 2
    assert children[0].color == "warning"

    children, style, blocked = _config_alert([])
    assert children == []
    assert style == {"display": "none"}
    assert blocked is False


def test_config_alert_is_not_dismissable():
    """The alert must not be closable: it is the only reason the buttons are dead.

    ``create_alert`` defaults to ``dismissable=True``. Dismissing this alert hid
    the explanation while leaving both launch buttons disabled with no ``href``,
    stranding the user with no way forward and no stated cause. The alert clears
    itself when the values become valid, which is the dismissal that is wanted.
    """
    from app.dash_app.pages.analytics import _ControlProblem

    children, _style, _blocked = _config_alert(
        [_ControlProblem("Lookback Days", "Lookback Days must be between 1 and 365.")]
    )
    assert children[0].dismissable is False


def test_config_alert_region_is_sticky():
    """Both cards' feedback regions carry the sticky class.

    The region sits in the card's normal flow above a ~1800px controls panel, so
    without `position: sticky` it renders off-screen above the user while they
    edit a field near the panel's bottom. The rule itself lives in
    executive-dashboard.css; this pins the class that activates it.
    """
    wanted = {f"{COLLAB}-config-alert", f"{EGO}-config-alert"}
    alerts = {
        node.id: node
        for node in _walk_tree(get_layout())
        if isinstance(getattr(node, "id", None), str) and node.id in wanted
    }
    assert set(alerts) == {f"{COLLAB}-config-alert", f"{EGO}-config-alert"}
    for node_id, node in alerts.items():
        assert "card-config-alert" in (node.className or ""), node_id


@pytest.mark.parametrize(
    "bad",
    [
        {"lookback_days": 366},
        {"lookback_days": 0},
        {"community_gap_x": 50},
        {"top_n_edges_per_node": 500},
        {"w_pr_reviews": -1.0},
        {"lookback_days": "abc"},
    ],
)
def test_describe_config_error_is_readable(bad):
    """Every invalid input yields a plain sentence, with nothing internal leaked.

    Catches both traps: a ``loc[-1]``-only implementation renders the useless
    "weights" label for the negative-weight case, and an unguarded ``errors()``
    call raises AttributeError for the non-numeric value.
    """
    with pytest.raises((ValueError,)) as caught:
        CollaborationNetworkConfig.from_query_values(bad)

    message = describe_config_error(caught.value)
    assert message, bad
    lowered = message.lower()
    for leaked in ("pydantic", "type=", "http", "pr_reviews", "reporter_assignee"):
        assert leaked not in lowered, (bad, message)

    if "w_pr_reviews" in bad:
        # The negative-weight error's ``loc`` is the whole ``weights`` dict, so a
        # ``loc[-1]``-only implementation would render "Weights ..." here. The
        # layer must be named by its human label instead.
        assert LAYER_LABELS["pr_reviews"] in message, message
        assert "weights" not in lowered, message

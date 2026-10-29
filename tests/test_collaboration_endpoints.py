"""Endpoint-surface tests for the collaboration network APIs.

Both endpoints must accept every layer weight in ``LAYER_ORDER``, and the org
endpoint must also accept its two community-gap settings. FastAPI silently drops
any query parameter a route does not declare, and
``CollaborationNetworkConfig.from_query_values`` then falls back to
``DEFAULT_LAYER_WEIGHTS`` — so a missing declaration produces a graph built from
weights the caller never chose, with no error.

These are unit tests: the service is stubbed and ``TestClient`` is used without
its context manager, so no lifespan/startup runs and no database is needed.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

import app.api_main  # noqa: F401  (importing builds the app with every router registered)
from app.api.graph.v1 import router as graph_router
from app.api.graph.v1 import service as graph_service
from app.api.graph.v1.model import CollaborationNetworkResponse, EgoNetworkResponse
from domain.collaboration.config import (
    DEFAULT_COMMUNITY_GAP_X,
    DEFAULT_COMMUNITY_GAP_Y,
    DEFAULT_LAYER_WEIGHTS,
    LAYER_ORDER,
)
from domain.collaboration.errors import CollaborationDataUnavailable

pytestmark = pytest.mark.unit

ORG_PATH = "/graph/collaboration-network"
EGO_PATH = "/graph/collaboration-network/ego"

PROBE_WEIGHT = 7.5
"""No layer's default equals this, so a dropped parameter is unambiguous."""

PROBE_GAP_X = 9999.0
PROBE_GAP_Y = 8888.0

_ROUTES = {
    route.path: route
    for route in graph_router.router.routes
    if "collaboration-network" in getattr(route, "path", "")
}

# Every setting each endpoint is responsible for accepting, with the default it
# must declare. The org view owns the community-gap settings; the per-person view
# has no communities and deliberately omits them.
EXPECTED_DEFAULTS: dict[str, dict[str, Any]] = {
    ORG_PATH: {
        **{f"w_{layer}": DEFAULT_LAYER_WEIGHTS[layer] for layer in LAYER_ORDER},
        "community_gap_x": DEFAULT_COMMUNITY_GAP_X,
        "community_gap_y": DEFAULT_COMMUNITY_GAP_Y,
    },
    EGO_PATH: {f"w_{layer}": DEFAULT_LAYER_WEIGHTS[layer] for layer in LAYER_ORDER},
}


@pytest.fixture
def captured_config(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Stub both services and capture the config each endpoint builds."""
    captured: dict[str, Any] = {}

    def fake_org(config: Any = None) -> CollaborationNetworkResponse:
        captured["config"] = config
        return CollaborationNetworkResponse(
            elements=[], num_people=0, num_pairs=0, num_communities=0, modularity=0.0
        )

    def fake_ego(
        person: str, config: Any = None, max_collaborators: Any = None
    ) -> EgoNetworkResponse:
        captured["config"] = config
        return EgoNetworkResponse(total_collaborators=0, shown_collaborators=0)

    # The router calls these as attributes of the service module, so patching the
    # module attribute is what takes effect.
    monkeypatch.setattr(graph_service, "get_collaboration_network", fake_org)
    monkeypatch.setattr(graph_service, "get_ego_network", fake_ego)
    return captured


@pytest.fixture
def client() -> TestClient:
    """A TestClient with no lifespan, so no database is contacted."""
    return TestClient(app.api_main.app)


def _request_url(path: str) -> str:
    """Build a request setting every probed setting to a distinctive value."""
    query = [f"w_{layer}={PROBE_WEIGHT}" for layer in LAYER_ORDER]
    if path == ORG_PATH:
        query += [f"community_gap_x={PROBE_GAP_X}", f"community_gap_y={PROBE_GAP_Y}"]
    else:
        query.append("person=github::Person::probe")
    return f"/api/v1{path}?{'&'.join(query)}"


@pytest.mark.parametrize("path", [ORG_PATH, EGO_PATH])
def test_probed_settings_reach_the_config(
    client: TestClient, captured_config: dict[str, Any], path: str
) -> None:
    """Every setting the endpoint accepts must arrive in the built config.

    This is the test that fails against the unfixed org endpoint: 8 of the 18
    weights, plus both community-gap settings, never leave FastAPI.
    """
    response = client.get(_request_url(path))
    assert response.status_code == 200, response.text

    weights = captured_config["config"].weights
    dropped = [layer for layer in LAYER_ORDER if weights[layer] != PROBE_WEIGHT]
    assert dropped == [], (
        f"{path} silently ignored the caller's weight for: {dropped}"
    )

    if path == ORG_PATH:
        config = captured_config["config"]
        assert config.community_gap_x == PROBE_GAP_X, "community_gap_x was ignored"
        assert config.community_gap_y == PROBE_GAP_Y, "community_gap_y was ignored"


@pytest.mark.parametrize("path", [ORG_PATH, EGO_PATH])
def test_route_declares_every_setting_with_the_expected_default(path: str) -> None:
    """The declared surface must cover every setting, with defaults that match.

    Presence alone is not enough: a declared parameter whose default has drifted
    from ``DEFAULT_LAYER_WEIGHTS`` is just as silent, because a caller who omits
    it gets the wrong number.
    """
    declared = {
        param.name: param.field_info.default
        for param in _ROUTES[path].dependant.query_params
    }
    expected = EXPECTED_DEFAULTS[path]

    missing = sorted(name for name in expected if name not in declared)
    assert missing == [], f"{path} does not declare: {missing}"

    wrong = {
        name: (declared[name], expected[name])
        for name in expected
        if declared[name] != expected[name]
    }
    assert wrong == {}, f"{path} declares wrong defaults (declared, expected): {wrong}"


# ---------------------------------------------------------------------------
# Empty result vs. invalid settings
# ---------------------------------------------------------------------------
#
# A clean query that matches nothing is a 404, a malformed setting is a 400.
# These were once the same ``ValueError``, and the org route told them apart by
# string-matching the message ("returned no data") — so rewording the exception
# would silently have flipped the status. They are now distinct types; these
# tests pin the mapping.

@pytest.mark.parametrize("path", [ORG_PATH, EGO_PATH])
def test_empty_result_is_404(
    client: TestClient, captured_config: dict[str, Any], monkeypatch, path: str
) -> None:
    """No matching records -> 404, not 400."""
    def no_data(*_args: Any, **_kwargs: Any) -> Any:
        raise CollaborationDataUnavailable("No collaborations found in this window.")

    monkeypatch.setattr(graph_service, "get_collaboration_network", no_data)
    monkeypatch.setattr(graph_service, "get_ego_network", no_data)

    response = client.get(_request_url(path))

    assert response.status_code == 404, response.text
    assert response.json()["detail"]["error"] == "No collaboration data"


@pytest.mark.parametrize("path", [ORG_PATH, EGO_PATH])
def test_invalid_setting_is_400(client: TestClient, monkeypatch, path: str) -> None:
    """A real ValueError stays a 400 (bad configuration / bad focus id)."""
    def bad(*_args: Any, **_kwargs: Any) -> Any:
        raise ValueError("config is wrong")

    monkeypatch.setattr(graph_service, "get_collaboration_network", bad)
    monkeypatch.setattr(graph_service, "get_ego_network", bad)

    response = client.get(_request_url(path))

    assert response.status_code == 400, response.text


def test_data_unavailable_is_not_a_value_error() -> None:
    """The split only works while this holds.

    ``CollaborationDataUnavailable`` must not subclass ``ValueError``: the Dash
    callbacks catch ``ValueError`` for the settings message, so a subclass would
    be silently swallowed there and the misleading text would return.
    """
    assert not issubclass(CollaborationDataUnavailable, ValueError)
    assert issubclass(CollaborationDataUnavailable, LookupError)

"""Config → query-param translation for the collaboration endpoints.

The single source of truth for how a ``CollaborationNetworkConfig`` becomes the
flat query params ``/api/v1/graph/collaboration-network[/ego]`` accept. Both UI
call sites and the Step 7 baseline script use it; the endpoints parse those
params back with ``CollaborationNetworkConfig.from_query_values``.

It lives outside ``pages/`` because both ``pages/collaboration_network/`` and
``pages/collaboration_network_ego/`` import it, and a module inside one page
package cannot be imported by another (importing a page package runs its
``__init__``, which registers that page's callbacks and would be circular).

The module also owns the two collaboration pages' shared HTTP error
translation (:func:`translate_api_error`): the generic client in
``ui.api_client`` raises one transport-level :class:`~ui.api_client.ApiError`,
and each collab call site maps it back to the domain exceptions its ``except``
blocks already catch.
"""

from __future__ import annotations

from domain.collaboration.config import LAYER_ORDER, CollaborationNetworkConfig
from domain.collaboration.errors import CollaborationDataUnavailable
from ui.api_client import ApiError

# The four params the ego endpoint does not accept (router.py:341-372). The org
# endpoint takes all of them; the ego endpoint omits these because a star skips
# the Louvain pipeline entirely. Verified against the ego signature: person,
# layers, max_collaborators, lookback_days, min_pair_score, exclude_bots,
# exclude_suffixes, w_* — and nothing else.
_ORG_ONLY = (
    "top_n_edges_per_node",
    "community_gap_x",
    "community_gap_y",
    "ensure_min_connection",
)

# The ``detail.error`` the org and ego endpoints send with their 404, i.e. the
# "query ran cleanly, nothing to draw" signal. A 404 carrying anything else is a
# wrong URL and must be reported as such, not as an empty collaboration set.
_NO_DATA_ERROR = "No collaboration data"


def config_to_query_params(config: CollaborationNetworkConfig) -> dict[str, str]:
    """Serialize ``config`` to the org endpoint's query params, all explicit.

    Every field is emitted, so the endpoint's own ``Query(default=…)`` values
    never participate and cannot drift from the model's defaults.
    """
    params = {
        "layers": ",".join(config.enabled_layers),
        "lookback_days": str(config.lookback_days),
        "min_pair_score": str(config.min_pair_score),
        "top_n_edges_per_node": str(config.top_n_edges_per_node),
        "community_gap_x": str(config.community_gap_x),
        "community_gap_y": str(config.community_gap_y),
        "ensure_min_connection": str(config.ensure_min_connection).lower(),
        "exclude_bots": str(config.exclude_bots).lower(),
        "exclude_suffixes": ",".join(config.excluded_file_suffixes),
    }
    for layer in LAYER_ORDER:
        params[f"w_{layer}"] = str(config.weights[layer])
    return params


def ego_query_params(
    config: CollaborationNetworkConfig, focus_id: str, max_collaborators: int
) -> dict[str, str]:
    """The ego endpoint's params: the shared subset, plus the focus identity.

    The focus param is named ``person`` on this endpoint, not ``focus_id``
    (``router.py:342``) — that asymmetry is exactly the kind of drift this
    module exists to make impossible to get wrong twice.
    """
    params = {
        key: value
        for key, value in config_to_query_params(config).items()
        if key not in _ORG_ONLY
    }
    params["person"] = focus_id
    params["max_collaborators"] = str(max_collaborators)
    return params


def translate_api_error(exc: ApiError) -> None:
    """Re-raise an ``ApiError`` as the domain error the callbacks catch.

    404 + ``detail.error == "No collaboration data"`` -> ``CollaborationDataUnavailable``
    400                                               -> ``ValueError``
    anything else                                     -> re-raised unchanged

    The mapping is keyed on ``detail.error`` and not on the bare status: a 404
    from a *wrong URL* must not be reported to the user as "you have no
    collaborations" — that is a bug-report generator, not a banner.

    The 400 → ``ValueError`` mapping is what keeps ``describe_config_error(...)``
    working: those handlers read ``.errors()`` off a pydantic ``ValidationError``
    and the API's ``detail.message`` carries that text.
    """
    if exc.status_code == 404 and exc.detail_error == _NO_DATA_ERROR:
        raise CollaborationDataUnavailable(exc.message or str(exc)) from exc
    if exc.status_code == 400:
        raise ValueError(exc.detail_error or exc.message or str(exc)) from exc
    raise exc


__all__ = [
    "config_to_query_params",
    "ego_query_params",
    "translate_api_error",
]

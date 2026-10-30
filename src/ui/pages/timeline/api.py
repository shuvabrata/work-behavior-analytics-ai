"""HTTP access for the Activity Timeline page.

Centralizes the calls to ``GET /api/v1/activity/suggest`` and
``GET /api/v1/activity/timeline``. Both go through ``ui.api_client``, so the
base URL and timeout are owned in one place.
"""

from __future__ import annotations

from typing import Any

from ui import api_client
from ui.api_client import STATUS_NO_RESPONSE, ApiError
from ui.pages.graph.utils import neo4j_to_cytoscape
from ui.pages.timeline.helpers import MIN_QUERY_LENGTH

from common.logger import logger

_DEFAULT_LIMIT = 10


class TimelineFetchError(RuntimeError):
    """Raised when the timeline request fails (non-200 or transport error).

    When the backend rejects a specific WBA id (HTTP 400 with
    ``detail.wba_id``), that key is carried on :attr:`wba_id` so the caller can
    drop the offending lane and retry (belt-and-braces behind client-side
    validation).
    """

    def __init__(self, message: str, *, wba_id: str | None = None) -> None:
        super().__init__(message)
        self.wba_id = wba_id


class SuggestionFetchError(RuntimeError):
    """Raised when the typeahead request fails (non-200 or transport error).

    Distinct from an empty result: an empty list means the search genuinely
    matched nothing, while this signals the suggestions could not be loaded.
    """


class NodePropertiesError(RuntimeError):
    """Raised when the graph property fetch fails (non-200 or transport error)."""


def fetch_suggestions(query: str, limit: int = _DEFAULT_LIMIT) -> list[dict[str, Any]]:
    """Fetch typeahead suggestions for the entity selector.

    Returns the ``results`` list on success, or an empty list **only** for a
    short query or a genuinely empty result. Every other failure (non-200
    response, transport error, malformed JSON) raises
    :class:`SuggestionFetchError`. The router declares ``q`` with
    ``min_length=3``, so a shorter query would otherwise be a 422 — it is gated
    here rather than allowed onto the wire.
    """
    term = (query or "").strip()
    if len(term) < MIN_QUERY_LENGTH:
        return []

    params: dict[str, str | int] = {"q": term, "limit": limit}
    try:
        response = api_client.get("/api/v1/activity/suggest", params=params)
    except ApiError as exc:
        if exc.status_code != STATUS_NO_RESPONSE:
            logger.warning(
                f"[Timeline] suggest returned {exc.status_code} for q={term!r}"
            )
            raise SuggestionFetchError(f"HTTP {exc.status_code}") from exc
        logger.warning(f"[Timeline] suggest request failed for q={term!r}: {exc}")
        raise SuggestionFetchError(f"request failed: {exc}") from exc

    try:
        payload = response.json()
    except ValueError as exc:
        logger.warning(f"[Timeline] suggest returned invalid JSON for q={term!r}: {exc}")
        raise SuggestionFetchError(f"invalid JSON: {exc}") from exc

    results = payload.get("results", []) if isinstance(payload, dict) else []
    return results if isinstance(results, list) else []


def fetch_timeline(
    *,
    wba_ids: list[str],
    scope: str = "activity",
    from_iso: str | None = None,
    to_iso: str | None = None,
    limit: int = 20,
    cursor: str | None = None,
    mock: str | None = None,
) -> dict[str, Any]:
    """Fetch multi-lane timeline data.

    Returns the parsed ``{lanes, meta}`` payload on success. Raises
    :class:`TimelineFetchError` on a non-200 response, a transport error, or
    malformed JSON, so the caller can show a danger alert and keep the last
    good render. ``mock`` is forwarded only when set (dev-only scenario switch).
    """
    params: dict[str, str | int] = {
        "wba_ids": ",".join(wba_ids),
        "scope": scope,
        "limit": limit,
    }
    if from_iso:
        params["from"] = from_iso
    if to_iso:
        params["to"] = to_iso
    if cursor:
        params["cursor"] = cursor
    if mock:
        params["mock"] = mock

    try:
        response = api_client.get("/api/v1/activity/timeline", params=params)
    except ApiError as exc:
        if exc.status_code == STATUS_NO_RESPONSE:
            raise TimelineFetchError(f"request failed: {exc}") from exc
        detail = ""
        bad_wba_id: str | None = None
        raw_detail = exc.detail
        if isinstance(raw_detail, dict):
            detail = f": {raw_detail.get('message', raw_detail)}"
            candidate = raw_detail.get("wba_id")
            if isinstance(candidate, str) and candidate:
                bad_wba_id = candidate
        elif raw_detail:
            detail = f": {raw_detail}"
        raise TimelineFetchError(
            f"HTTP {exc.status_code}{detail}", wba_id=bad_wba_id
        ) from exc

    try:
        payload = response.json()
    except ValueError as exc:
        raise TimelineFetchError(f"invalid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise TimelineFetchError("unexpected response shape")
    return payload


#: One round trip for both sides.  Two branches, one call:
#:
#: * branch 1 — the id **is** a node id (every non-Person entity, and every
#:   Person whose provider identity is its canonical node).  A node that does
#:   not exist is simply absent, which is what lets the UI render a per-panel
#:   "not found" state.
#: * branch 2 — the id is a Person whose provider identity was deduped onto a
#:   *different* provider's canonical Person node, so the id is **not** a node
#:   id (Decision 9b).  ``MAPS_TO`` recovers it.  The mapping node and the
#:   ``MAPS_TO`` edge are returned alongside the Person so the caller can pair
#:   them unambiguously (a Person may have several mappings, so position is not
#:   a safe pairing key).
#:
#: Both branches must alias their columns identically — Cypher rejects a UNION
#: whose branches return different column names ("All sub queries in an UNION
#: must have the same return column names").  The ``null`` placeholders exist
#: only to satisfy that rule.
#:
#: The ``id`` property is indexed per label, so branch 1 is a scan when
#: unlabelled — see the note below.  This is deliberate.
_NODE_PROPERTIES_CYPHER = (
    "MATCH (n) WHERE n.id IN $ids RETURN n AS node, null AS mapping, null AS rel "
    "UNION "
    "MATCH (i:IdentityMapping) WHERE i.id IN $mids "
    "MATCH (i)-[r:MAPS_TO]-(p:Person) RETURN p AS node, i AS mapping, r AS rel"
)


def _mapping_id_for(wba_id: str) -> str | None:
    """Return the ``IdentityMapping`` id matching a Person WBA id, else ``None``.

    ``confluence::Person::557058:abc`` → ``confluence::IdentityMapping::557058:abc``.
    Only Person ids have a mapping branch; every other type returns ``None``.
    """
    if "::Person::" not in wba_id:
        return None
    return wba_id.replace("::Person::", "::IdentityMapping::", 1)


def fetch_node_properties(wba_ids: list[str]) -> dict[str, dict[str, Any]]:
    """Fetch node properties for each WBA id, keyed by the id **requested**.

    Returns ``{}`` for an empty input.  An id that resolves to no node is simply
    absent from the result — callers render a per-node "not found" state.

    The result is keyed by the id the caller asked for, **not** by the node that
    came back: a Person sibling is requested by its provider-scoped id but
    resolves to a canonical Person node whose ``wba_id`` differs (Decision 9b),
    so the ``data`` dict's own ``wba_id`` must not be used as the key.

    Raises :class:`NodePropertiesError` on a transport error or a non-200
    response.
    """
    ids = [str(w) for w in wba_ids if w]
    if not ids:
        return {}
    mids = [mid for mid in (_mapping_id_for(w) for w in ids) if mid]
    try:
        response = api_client.post(
            "/api/v1/graph/execute",
            json={
                "query": _NODE_PROPERTIES_CYPHER,
                "source": "raw",
                "view": "graph",
                "parameters": {"ids": ids, "mids": mids},
            },
        )
    except ApiError as exc:
        if exc.status_code != STATUS_NO_RESPONSE:
            logger.warning(
                f"[Timeline] node properties returned {exc.status_code}"
            )
            raise NodePropertiesError(f"HTTP {exc.status_code}") from exc
        logger.warning(f"[Timeline] node properties request failed: {exc}")
        raise NodePropertiesError(f"request failed: {exc}") from exc

    try:
        payload = response.json()
    except ValueError as exc:
        raise NodePropertiesError(f"invalid JSON: {exc}") from exc

    elements = neo4j_to_cytoscape(payload if isinstance(payload, dict) else {})
    nodes: dict[str, dict[str, Any]] = {}
    element_to_wba: dict[str, str] = {}
    for element in elements:
        if element.get("group") != "nodes":
            continue
        data = element.get("data")
        if not isinstance(data, dict) or not data.get("wba_id"):
            continue
        nodes[str(data["wba_id"])] = data
        if data.get("id"):
            element_to_wba[str(data["id"])] = str(data["wba_id"])

    # Pair each mapping node with the Person it MAPS_TO, via the returned edge.
    # ``mapping_to_person`` is keyed by the *requested* Person id, so branch-2
    # hits land under the key the caller used.
    mapping_to_person: dict[str, dict[str, Any]] = {}
    for element in elements:
        if element.get("group") != "edges":
            continue
        data = element.get("data")
        if not isinstance(data, dict) or data.get("relType") != "MAPS_TO":
            continue
        source = element_to_wba.get(str(data.get("source")))
        target = element_to_wba.get(str(data.get("target")))
        if not source or not target:
            continue
        for a, b in ((source, target), (target, source)):
            if "::IdentityMapping::" in a and "::Person::" in b:
                requested = a.replace("::IdentityMapping::", "::Person::", 1)
                mapping_to_person[requested] = nodes[b]

    result: dict[str, dict[str, Any]] = {}
    for requested in ids:
        data = nodes.get(requested) or mapping_to_person.get(requested)
        if data is not None:
            result[requested] = data
    return result

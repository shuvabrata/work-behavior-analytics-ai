"""HTTP access for the Activity Timeline page.

Centralizes the calls to ``GET /api/v1/activity/suggest`` and
``GET /api/v1/activity/timeline``. Mirrors the synchronous ``requests``
convention used by ``pages/search.py``.
"""

from __future__ import annotations

import os
from typing import Any

import requests

from app.runtime_settings import runtime_settings
from app.dash_app.pages.timeline.helpers import MIN_QUERY_LENGTH

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


def get_api_base_url() -> str:
    """Return the backend API base URL (falls back to localhost for dev)."""
    return os.getenv("API_BASE_URL", "http://localhost:8000")


def fetch_suggestions(query: str, limit: int = _DEFAULT_LIMIT) -> list[dict[str, Any]]:
    """Fetch typeahead suggestions for the entity selector.

    Returns the ``results`` list on success, or an empty list on a short query,
    a non-200 response, or a transport error. The router declares ``q`` with
    ``min_length=2``, so a shorter query would otherwise be a 422 — it is gated
    here rather than allowed onto the wire.
    """
    term = (query or "").strip()
    if len(term) < MIN_QUERY_LENGTH:
        return []

    params: dict[str, str | int] = {"q": term, "limit": limit}
    try:
        # Bandit's B113 only recognises literal timeouts; ours is runtime-configured.
        response = requests.get(  # nosec B113
            f"{get_api_base_url()}/api/v1/activity/suggest",
            params=params,
            timeout=runtime_settings.get_int("HTTP_REQUEST_TIMEOUT"),
        )
    except requests.RequestException as exc:
        logger.warning(f"[Timeline] suggest request failed for q={term!r}: {exc}")
        return []

    if response.status_code != 200:
        logger.warning(
            f"[Timeline] suggest returned {response.status_code} for q={term!r}"
        )
        return []

    try:
        payload = response.json()
    except ValueError as exc:
        logger.warning(f"[Timeline] suggest returned invalid JSON for q={term!r}: {exc}")
        return []

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
        # Bandit's B113 only recognises literal timeouts; ours is runtime-configured.
        response = requests.get(  # nosec B113
            f"{get_api_base_url()}/api/v1/activity/timeline",
            params=params,
            timeout=runtime_settings.get_int("HTTP_REQUEST_TIMEOUT"),
        )
    except requests.RequestException as exc:
        raise TimelineFetchError(f"request failed: {exc}") from exc

    if response.status_code != 200:
        detail = ""
        bad_wba_id: str | None = None
        try:
            body = response.json()
            raw_detail = body.get("detail") if isinstance(body, dict) else None
            if isinstance(raw_detail, dict):
                detail = f": {raw_detail.get('message', raw_detail)}"
                candidate = raw_detail.get("wba_id")
                if isinstance(candidate, str) and candidate:
                    bad_wba_id = candidate
            elif raw_detail:
                detail = f": {raw_detail}"
        except ValueError:
            pass
        raise TimelineFetchError(
            f"HTTP {response.status_code}{detail}", wba_id=bad_wba_id
        )

    try:
        payload = response.json()
    except ValueError as exc:
        raise TimelineFetchError(f"invalid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise TimelineFetchError("unexpected response shape")
    return payload

"""HTTP access for the Activity Timeline page.

Centralizes the calls to ``GET /api/v1/activity/suggest`` (UI-1) and, later,
``GET /api/v1/activity/timeline`` (UI-2). Mirrors the synchronous ``requests``
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
        response = requests.get(
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

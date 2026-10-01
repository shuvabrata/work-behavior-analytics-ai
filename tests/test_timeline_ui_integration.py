"""Integration tests for the Activity Timeline UI against a live app server.

These tests exercise the real HTTP round-trip to the running application
server (``http://localhost:8000`` by default, override with ``API_BASE_URL``).
They require:

* the app server running (``PYTHONPATH=src uvicorn app.main:app --reload``)
* the activity tables populated (run a producer + consumer scan)

Run with:
    pytest -m integration tests/test_timeline_ui_integration.py -v
"""

from __future__ import annotations

import os
from typing import Any

import httpx
import pytest

pytestmark = [pytest.mark.integration]

BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000")
TIMELINE_URL = f"{BASE_URL}/api/v1/activity/timeline"
SUGGEST_URL = f"{BASE_URL}/api/v1/activity/suggest"


def _app_server_reachable() -> bool:
    """Return True if the app server is reachable at the health endpoint."""
    try:
        resp = httpx.get(f"{BASE_URL}/api/health", timeout=3)
        return resp.status_code == 200
    except Exception:  # pylint: disable=broad-except
        return False


_app_available: bool = _app_server_reachable()
_skip_if_app_unavailable = pytest.mark.skipif(
    not _app_available,
    reason=f"App server not reachable at {BASE_URL}",
)


def _first_person_wba_id() -> str | None:
    """Return the first Person WBA ID found via the suggest endpoint."""
    try:
        resp = httpx.get(
            SUGGEST_URL,
            params={"q": "al", "limit": 10},
            timeout=5,
        )
        if resp.status_code != 200:
            return None
        for result in resp.json().get("results", []):
            if result.get("entity_type") == "Person":
                wba_id = result.get("wba_id")
                if isinstance(wba_id, str):
                    return wba_id
    except Exception:  # pylint: disable=broad-except
        return None
    return None


@_skip_if_app_unavailable
class TestTimelineApiReachable:
    """Smoke tests that the timeline API responds with real data."""

    def test_health_endpoint(self) -> None:
        resp = httpx.get(f"{BASE_URL}/api/health", timeout=5)
        assert resp.status_code == 200

    def test_suggest_returns_results(self) -> None:
        resp = httpx.get(SUGGEST_URL, params={"q": "al", "limit": 10}, timeout=5)
        assert resp.status_code == 200
        data = resp.json()
        assert "results" in data

    def test_timeline_with_known_person(self) -> None:
        wba_id = _first_person_wba_id()
        if wba_id is None:
            pytest.skip("No Person suggestions found — is the dataset populated?")
        resp = httpx.get(
            TIMELINE_URL,
            params={"wba_ids": wba_id, "limit": 5},
            timeout=5,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["meta"]["total_lanes"] == 1
        lane = data["lanes"][0]
        assert lane["wba_id"] == wba_id
        assert "events" in lane
        assert "next_cursor" in lane

    def test_timeline_invalid_wba_id_returns_400(self) -> None:
        resp = httpx.get(TIMELINE_URL, params={"wba_ids": "invalid::bad"}, timeout=5)
        assert resp.status_code == 400


@_skip_if_app_unavailable
class TestTimelinePagination:
    """Verify cursor pagination against real data."""

    def test_cursor_pagination_returns_older_events(self) -> None:
        wba_id = _first_person_wba_id()
        if wba_id is None:
            pytest.skip("No Person suggestions found — is the dataset populated?")

        page1 = httpx.get(
            TIMELINE_URL,
            params={"wba_ids": wba_id, "limit": 2},
            timeout=5,
        )
        assert page1.status_code == 200
        lane1 = page1.json()["lanes"][0]
        cursor = lane1.get("next_cursor")
        if not cursor:
            pytest.skip("Fewer than 3 events for this person — nothing to paginate.")

        page2 = httpx.get(
            TIMELINE_URL,
            params={"wba_ids": wba_id, "limit": 2, "cursor": cursor},
            timeout=5,
        )
        assert page2.status_code == 200
        lane2 = page2.json()["lanes"][0]

        times1 = [e["event_time"] for e in lane1["events"]]
        times2 = [e["event_time"] for e in lane2["events"]]
        assert times2, "Second page should have events"
        # Page 2 events are older than page 1 events.
        assert times2[0] < times1[-1]

    def test_time_range_filter(self) -> None:
        wba_id = _first_person_wba_id()
        if wba_id is None:
            pytest.skip("No Person suggestions found — is the dataset populated?")

        resp = httpx.get(
            TIMELINE_URL,
            params={
                "wba_ids": wba_id,
                "limit": 50,
                "from": "2026-01-01T00:00:00Z",
                "to": "2026-01-31T23:59:59Z",
            },
            timeout=5,
        )
        assert resp.status_code == 200
        lane = resp.json()["lanes"][0]
        for event in lane["events"]:
            assert "2026-01-01" <= event["event_time"] <= "2026-01-31"


@_skip_if_app_unavailable
class TestTimelineSuggest:
    """Verify the suggest endpoint returns well-formed suggestions."""

    def test_suggest_short_query_returns_empty(self) -> None:
        # The suggest API requires min 2 chars; a 1-char query is rejected
        # with 422 (FastAPI validation), not an empty result set.
        resp = httpx.get(SUGGEST_URL, params={"q": "a"}, timeout=5)
        assert resp.status_code == 422

    def test_suggest_returns_wba_ids(self) -> None:
        resp = httpx.get(SUGGEST_URL, params={"q": "al", "limit": 10}, timeout=5)
        assert resp.status_code == 200
        for result in resp.json().get("results", []):
            assert "wba_id" in result
            assert "label" in result
            assert "entity_type" in result
            assert "source" in result
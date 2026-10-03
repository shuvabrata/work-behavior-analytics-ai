"""Unit tests for the Activity Timeline dev mock (``mock_data``).

These verify the mock's own contract — every scenario builds, output is
deterministic, events stay inside the requested range, cursors round-trip
through the real service validator, and the activation gate behaves. They do
not exercise HTTP; the endpoints are validated manually.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.api.activity.v1 import mock_data, service
from app.api.activity.v1.model import TimelineRequest
from app.settings import settings

pytestmark = pytest.mark.unit

_END = datetime(2026, 3, 31, 12, 0, tzinfo=timezone.utc)
_START = datetime(2026, 3, 1, 0, 0, tzinfo=timezone.utc)
_LANES = ["mock::Person::alice", "mock::Person::bob", "mock::Person::carol"]


def _request(
    *,
    lanes: list[str] | None = None,
    scope: str = "activity",
    cursor: str | None = None,
    limit: int = 20,
) -> TimelineRequest:
    return TimelineRequest(
        wba_ids=lanes if lanes is not None else list(_LANES),
        scope=scope,  # type: ignore[arg-type]
        from_=_START,
        to=_END,
        cursor=cursor,
        limit=limit,
    )


def test_every_scenario_builds() -> None:
    """Each registered scenario produces one lane per requested wba_id."""
    for scenario in mock_data.MOCK_SCENARIOS:
        if scenario == "error_500":
            continue
        response = mock_data.build_timeline(_request(), scenario)
        assert len(response.lanes) == len(_LANES)
        assert response.meta.total_lanes == len(_LANES)


def test_error_scenario_raises() -> None:
    """The error scenario raises so the real 500 path is exercised."""
    with pytest.raises(RuntimeError):
        mock_data.build_timeline(_request(), "error_500")


def test_output_is_deterministic() -> None:
    """Same scenario + request yields identical signal ids and times."""
    first = mock_data.build_timeline(_request(), "even")
    second = mock_data.build_timeline(_request(), "even")
    assert [[e.signal_id for e in lane.events] for lane in first.lanes] == [
        [e.signal_id for e in lane.events] for lane in second.lanes
    ]


def test_events_stay_within_range() -> None:
    """Materialized events never fall outside [from, to]."""
    for scenario in ("even", "spike_100", "time_edges", "card_variety", "pagination"):
        response = mock_data.build_timeline(_request(), scenario)
        for lane in response.lanes:
            for event in lane.events:
                assert _START <= event.event_time <= _END


def test_empty_range_and_empty_lane() -> None:
    """empty_range drops all events; empty_lane drops only the first lane."""
    empty = mock_data.build_timeline(_request(), "empty_range")
    assert all(lane.events == [] for lane in empty.lanes)

    one_empty = mock_data.build_timeline(_request(), "empty_lane")
    assert one_empty.lanes[0].events == []
    assert one_empty.lanes[1].events != []


def test_history_scope_markers() -> None:
    """scope=history yields STATE_CHANGE events with populated details."""
    response = mock_data.build_timeline(_request(scope="history"), "history")
    events = [event for lane in response.lanes for event in lane.events]
    assert events
    for event in events:
        assert event.relationship_type == "STATE_CHANGE"
        assert event.details  # populated snapshot


def test_pagination_cursor_round_trips() -> None:
    """Mock cursors validate against the real service cursor validator."""
    page1 = mock_data.build_timeline(_request(), "pagination")
    lane0 = page1.lanes[0]
    assert len(lane0.events) == 20
    assert lane0.next_cursor is not None
    service.validate_cursor(lane0.next_cursor)  # must not raise

    page2 = mock_data.build_timeline(_request(cursor=lane0.next_cursor), "pagination")
    page2_ids = {event.signal_id for event in page2.lanes[0].events}
    page1_ids = {event.signal_id for event in lane0.events}
    assert page2_ids.isdisjoint(page1_ids)
    assert len(page2.lanes[0].events) == 20


def test_pagination_optimistic_cursor_lane() -> None:
    """A lane of exactly `limit` events reports a cursor, then an empty page."""
    page1 = mock_data.build_timeline(_request(), "pagination")
    lane1 = page1.lanes[1]
    assert len(lane1.events) == 20
    assert lane1.next_cursor is not None

    page2 = mock_data.build_timeline(_request(cursor=lane1.next_cursor), "pagination")
    assert page2.lanes[1].events == []
    assert page2.lanes[1].next_cursor is None


def test_suggestions_filter_and_empty() -> None:
    """Suggestions filter the catalogue; the literal 'none' returns empty."""
    alice = mock_data.build_suggestions("alice", 10)
    assert [item.wba_id for item in alice] == ["mock::Person::alice"]
    assert mock_data.build_suggestions("none", 10) == []
    assert len(mock_data.build_suggestions("zzz", 10)) > 0  # falls back to catalogue


def test_resolve_scenario_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    """Env must enable mock mode; the override only switches scenario."""
    monkeypatch.setattr(settings, "TIMELINE_MOCK_SCENARIO", "")
    assert mock_data.resolve_scenario(None) is None
    assert mock_data.resolve_scenario("gap_30d") is None  # override alone: off

    monkeypatch.setattr(settings, "TIMELINE_MOCK_SCENARIO", "even")
    assert mock_data.resolve_scenario(None) == "even"
    assert mock_data.resolve_scenario("gap_30d") == "gap_30d"

    monkeypatch.setattr(settings, "TIMELINE_MOCK_SCENARIO", "not_a_scenario")
    with pytest.raises(mock_data.UnknownMockScenarioError):
        mock_data.resolve_scenario(None)
    monkeypatch.setattr(settings, "TIMELINE_MOCK_SCENARIO", "even")
    with pytest.raises(mock_data.UnknownMockScenarioError):
        mock_data.resolve_scenario("bogus")

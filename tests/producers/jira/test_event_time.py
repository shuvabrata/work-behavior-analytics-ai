"""Unit tests for Jira producer event_time logic.

Covers:
- ``_event_time_from``: preferred/fallback/epoch sentinel
- ``_sprint_event_time``: full priority chain (ISO > date-only > epoch)
- ``build_project_signal``: structural anchor → epoch
- ``build_person_signal``: no Jira timestamp → epoch
- ``map_sprint``: raw ISO fields added alongside date-only fields
"""

from datetime import datetime, timezone
import logging

import pytest

from connectors.producers.jira.main import (
    _EPOCH,
    _event_time_from,
    _sprint_event_time,
    build_project_signal,
    build_person_signal,
)
from connectors.producers.jira.map_jira import map_sprint

_UTC = timezone.utc
_BASE_URL = "https://jira.example.com"


# ---------------------------------------------------------------------------
# _event_time_from
# ---------------------------------------------------------------------------


class TestEventTimeFrom:
    def test_uses_updated_at_when_present(self):
        result = _event_time_from("2024-03-15T10:30:00Z", "2023-01-01T00:00:00Z")
        assert result == datetime(2024, 3, 15, 10, 30, 0, tzinfo=_UTC)

    def test_prefers_updated_at_over_created_at(self):
        """updated_at must always win when both are present."""
        result = _event_time_from(
            "2024-06-01T08:00:00Z",
            "2024-01-01T08:00:00Z",
        )
        assert result.year == 2024
        assert result.month == 6

    def test_falls_back_to_created_at_when_updated_is_empty(self):
        result = _event_time_from("", "2023-06-01T08:00:00+00:00")
        assert result == datetime(2023, 6, 1, 8, 0, 0, tzinfo=_UTC)

    def test_falls_back_to_created_at_when_updated_is_none(self):
        # Passing None-coerced-to-empty-string is the actual call pattern
        result = _event_time_from("", "2022-12-31T23:59:59Z")
        assert result.year == 2022

    def test_returns_epoch_when_both_absent(self, caplog):
        with caplog.at_level(logging.WARNING):
            result = _event_time_from("", "", entity_label="Issue/PROJ-123")
        assert result == _EPOCH
        assert "PROJ-123" in caplog.text
        assert "epoch sentinel" in caplog.text

    def test_returns_epoch_when_both_none_string(self, caplog):
        with caplog.at_level(logging.WARNING):
            result = _event_time_from("", "")
        assert result == _EPOCH

    def test_never_returns_now(self):
        """Fallback must be deterministic epoch, never wall-clock time."""
        result = _event_time_from("", "")
        assert result == _EPOCH

    def test_handles_z_suffix(self):
        result = _event_time_from("2025-01-01T12:00:00Z", "")
        assert result.tzinfo is not None
        assert result == datetime(2025, 1, 1, 12, 0, 0, tzinfo=_UTC)

    def test_attaches_utc_when_offset_naive(self):
        # Some Jira instances return naive datetimes without offset
        result = _event_time_from("2024-05-10T09:00:00", "")
        assert result.tzinfo == _UTC

    def test_entity_label_optional(self):
        """No entity_label should still work without error."""
        result = _event_time_from("", "")
        assert result == _EPOCH


# ---------------------------------------------------------------------------
# _sprint_event_time
# ---------------------------------------------------------------------------


class TestSprintEventTime:
    def _sprint(self, **kwargs):
        base = {
            "sprint_id": "1",
            "name": "Sprint 1",
            "goal": "",
            "start_date": "",
            "end_date": "",
            "complete_date": "",
            "start_date_iso": "",
            "end_date_iso": "",
            "complete_date_iso": "",
            "status": "Completed",
            "url": None,
        }
        base.update(kwargs)
        return base

    def test_prefers_complete_date_iso(self):
        sprint = self._sprint(
            complete_date_iso="2024-04-01T15:00:00Z",
            start_date_iso="2024-03-18T09:00:00Z",
            end_date_iso="2024-03-31T18:00:00Z",
        )
        assert _sprint_event_time(sprint) == datetime(2024, 4, 1, 15, 0, 0, tzinfo=_UTC)

    def test_falls_back_to_start_date_iso_when_no_complete(self):
        sprint = self._sprint(start_date_iso="2024-03-18T09:00:00Z")
        assert _sprint_event_time(sprint) == datetime(2024, 3, 18, 9, 0, 0, tzinfo=_UTC)

    def test_falls_back_to_end_date_iso_when_no_complete_or_start(self):
        sprint = self._sprint(end_date_iso="2024-03-31T18:00:00Z")
        assert _sprint_event_time(sprint) == datetime(2024, 3, 31, 18, 0, 0, tzinfo=_UTC)

    def test_falls_back_to_complete_date_only_string(self):
        """Date-only string parsed as midnight UTC."""
        sprint = self._sprint(complete_date="2024-04-01")
        assert _sprint_event_time(sprint) == datetime(2024, 4, 1, 0, 0, 0, tzinfo=_UTC)

    def test_falls_back_to_start_date_only_string(self):
        sprint = self._sprint(start_date="2024-03-18")
        assert _sprint_event_time(sprint) == datetime(2024, 3, 18, 0, 0, 0, tzinfo=_UTC)

    def test_falls_back_to_end_date_only_string(self):
        sprint = self._sprint(end_date="2024-03-31")
        assert _sprint_event_time(sprint) == datetime(2024, 3, 31, 0, 0, 0, tzinfo=_UTC)

    def test_iso_takes_precedence_over_date_only(self):
        """complete_date_iso must win over complete_date."""
        sprint = self._sprint(
            complete_date_iso="2024-04-01T15:30:00Z",
            complete_date="2024-04-01",
        )
        result = _sprint_event_time(sprint)
        assert result.hour == 15  # ISO precision preserved, not midnight

    def test_returns_epoch_and_warns_when_all_absent(self, caplog):
        sprint = self._sprint(name="Sprint X")
        with caplog.at_level(logging.WARNING):
            result = _sprint_event_time(sprint)
        assert result == _EPOCH
        assert "Sprint X" in caplog.text

    def test_never_returns_now(self):
        sprint = self._sprint()
        assert _sprint_event_time(sprint) == _EPOCH


# ---------------------------------------------------------------------------
# build_project_signal — structural anchor uses epoch
# ---------------------------------------------------------------------------


class TestBuildProjectSignalEventTime:
    def _project_data(self, **overrides):
        data = {
            "project_id": "10001",
            "project_key": "PROJ",
            "project_name": "My Project",
            "status": "Active",
            "project_type": "software",
            "url": "https://jira.example.com/browse/PROJ",
        }
        data.update(overrides)
        return data

    def test_event_time_is_epoch(self):
        signal = build_project_signal(self._project_data(), _BASE_URL)
        assert signal is not None
        assert signal.event_time == _EPOCH

    def test_epoch_is_stable_across_calls(self):
        """Two calls must return the same epoch, not two different now() values."""
        s1 = build_project_signal(self._project_data(), _BASE_URL)
        s2 = build_project_signal(self._project_data(project_key="OTHER"), _BASE_URL)
        assert s1 is not None and s2 is not None
        assert s1.event_time == s2.event_time == _EPOCH


# ---------------------------------------------------------------------------
# build_person_signal (Jira) — no API timestamp → epoch
# ---------------------------------------------------------------------------


class TestBuildPersonSignalEventTime:
    def _user_data(self, **overrides):
        data = {
            "account_id": "abc123",
            "display_name": "Alice",
            "email": "alice@example.com",
        }
        data.update(overrides)
        return data

    def test_event_time_is_epoch(self):
        # Jira build_person_signal signature: (user_data, jira_base_url)
        signal = build_person_signal(self._user_data(), _BASE_URL)
        assert signal is not None
        assert signal.event_time == _EPOCH

    def test_epoch_regardless_of_user_content(self):
        """Even a fully populated user should get epoch — no Jira timestamp available."""
        signal = build_person_signal(
            self._user_data(display_name="Bob", email="bob@example.com"),
            _BASE_URL,
        )
        assert signal is not None
        assert signal.event_time == _EPOCH


# ---------------------------------------------------------------------------
# map_sprint — ISO fields present alongside date-only fields
# ---------------------------------------------------------------------------


class TestMapSprintIsoFields:
    def _raw_sprint(self, **overrides):
        data = {
            "id": 42,
            "name": "Sprint 42",
            "state": "closed",
            "goal": "Ship it",
            "startDate": "2024-03-18T09:00:00.000Z",
            "endDate": "2024-03-31T18:00:00.000Z",
            "completeDate": "2024-04-01T15:30:00.123Z",
        }
        data.update(overrides)
        return data

    def test_iso_fields_present_in_output(self):
        result = map_sprint(self._raw_sprint())
        assert "start_date_iso" in result
        assert "end_date_iso" in result
        assert "complete_date_iso" in result

    def test_iso_fields_preserve_full_timestamp(self):
        result = map_sprint(self._raw_sprint())
        assert result["complete_date_iso"] == "2024-04-01T15:30:00.123Z"
        assert result["start_date_iso"] == "2024-03-18T09:00:00.000Z"
        assert result["end_date_iso"] == "2024-03-31T18:00:00.000Z"

    def test_date_only_fields_still_truncated(self):
        """Existing date-only fields must keep YYYY-MM-DD format."""
        result = map_sprint(self._raw_sprint())
        assert result["complete_date"] == "2024-04-01"
        assert result["start_date"] == "2024-03-18"
        assert result["end_date"] == "2024-03-31"

    def test_iso_fields_empty_string_when_date_absent(self):
        result = map_sprint(self._raw_sprint(completeDate=None, startDate=None, endDate=None))
        assert result["complete_date_iso"] == ""
        assert result["start_date_iso"] == ""
        assert result["end_date_iso"] == ""

    def test_sprint_event_time_uses_iso_precision(self):
        """End-to-end: map_sprint output → _sprint_event_time preserves sub-day precision."""
        result = map_sprint(self._raw_sprint())
        event_time = _sprint_event_time(result)
        # Should be 15:30 from ISO, not 00:00 from date-only
        assert event_time == datetime(2024, 4, 1, 15, 30, 0, 123000, tzinfo=_UTC)

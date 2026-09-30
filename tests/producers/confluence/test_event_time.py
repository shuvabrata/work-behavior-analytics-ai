"""Unit tests for Confluence producer event_time logic.

Covers:
- ``_content_event_time``: priority chain (version.when > history.createdDate > updatedAt > epoch)
- ``_space_event_time``: priority chain (updatedAt > lastModificationDate > createdAt > creationDate > epoch)
- ``_comment_timestamp``: priority chain (version.when > history.createdDate > createdAt > epoch)
- ``_content_created_at``: attribute fallback → epoch string
- ``build_person_signal``: no Confluence timestamp → epoch
"""

from datetime import datetime, timezone
import logging

import pytest

from connectors.producers.confluence.main import (
    _EPOCH,
    _content_event_time,
    _space_event_time,
    _comment_timestamp,
    _content_created_at,
    build_person_signal,
)

_UTC = timezone.utc
_BASE_URL = "https://confluence.example.com"


# ---------------------------------------------------------------------------
# _content_event_time
# ---------------------------------------------------------------------------


class TestContentEventTime:
    def test_prefers_version_when(self):
        content = {
            "version": {"when": "2024-05-10T14:30:00Z"},
            "history": {"createdDate": "2023-01-01T00:00:00Z"},
            "updatedAt": "2022-06-15T08:00:00Z",
        }
        result = _content_event_time(content)
        assert result == datetime(2024, 5, 10, 14, 30, 0, tzinfo=_UTC)

    def test_falls_back_to_history_created_date(self):
        content = {"history": {"createdDate": "2023-06-15T08:00:00Z"}}
        result = _content_event_time(content)
        assert result == datetime(2023, 6, 15, 8, 0, 0, tzinfo=_UTC)

    def test_falls_back_to_updated_at(self):
        content = {"updatedAt": "2024-01-20T10:00:00Z"}
        result = _content_event_time(content)
        assert result == datetime(2024, 1, 20, 10, 0, 0, tzinfo=_UTC)

    def test_version_when_wins_over_history(self):
        content = {
            "version": {"when": "2024-08-01T12:00:00Z"},
            "history": {"createdDate": "2024-07-01T12:00:00Z"},
        }
        assert _content_event_time(content).month == 8

    def test_returns_epoch_and_warns_when_all_absent(self, caplog):
        content = {"id": "page-999"}
        with caplog.at_level(logging.WARNING):
            result = _content_event_time(content)
        assert result == _EPOCH
        assert "page-999" in caplog.text
        assert "epoch sentinel" in caplog.text

    def test_returns_epoch_on_empty_content(self, caplog):
        with caplog.at_level(logging.WARNING):
            result = _content_event_time({})
        assert result == _EPOCH

    def test_never_returns_now(self):
        """Fallback must be deterministic epoch, never wall-clock time."""
        result = _content_event_time({})
        assert result == _EPOCH

    def test_attaches_utc_when_offset_naive(self):
        content = {"version": {"when": "2024-05-10T14:30:00"}}
        result = _content_event_time(content)
        assert result.tzinfo == _UTC

    def test_handles_z_suffix(self):
        content = {"updatedAt": "2024-01-01T00:00:00Z"}
        result = _content_event_time(content)
        assert result.tzinfo is not None


# ---------------------------------------------------------------------------
# _space_event_time
# ---------------------------------------------------------------------------


class TestSpaceEventTime:
    def test_prefers_updated_at(self):
        space = {
            "updatedAt": "2024-06-01T12:00:00Z",
            "lastModificationDate": "2023-01-01T00:00:00Z",
            "createdAt": "2020-01-01T00:00:00Z",
            "key": "ENG",
        }
        result = _space_event_time(space)
        assert result == datetime(2024, 6, 1, 12, 0, 0, tzinfo=_UTC)

    def test_falls_back_to_last_modification_date(self):
        space = {"lastModificationDate": "2024-03-20T09:00:00Z", "key": "ENG"}
        result = _space_event_time(space)
        assert result == datetime(2024, 3, 20, 9, 0, 0, tzinfo=_UTC)

    def test_falls_back_to_created_at(self):
        space = {"createdAt": "2021-08-15T07:00:00Z", "key": "ENG"}
        result = _space_event_time(space)
        assert result == datetime(2021, 8, 15, 7, 0, 0, tzinfo=_UTC)

    def test_falls_back_to_creation_date(self):
        space = {"creationDate": "2020-05-10T06:00:00Z", "key": "ENG"}
        result = _space_event_time(space)
        assert result == datetime(2020, 5, 10, 6, 0, 0, tzinfo=_UTC)

    def test_returns_epoch_and_warns_when_all_absent(self, caplog):
        space = {"key": "ENG"}
        with caplog.at_level(logging.WARNING):
            result = _space_event_time(space)
        assert result == _EPOCH
        assert "ENG" in caplog.text
        assert "epoch sentinel" in caplog.text

    def test_returns_epoch_on_empty_space(self, caplog):
        with caplog.at_level(logging.WARNING):
            result = _space_event_time({})
        assert result == _EPOCH

    def test_never_returns_now(self):
        result = _space_event_time({})
        assert result == _EPOCH

    def test_updated_at_wins_over_creation(self):
        """More recent update must take precedence over creation timestamp."""
        space = {
            "updatedAt": "2024-01-01T00:00:00Z",
            "createdAt": "2020-01-01T00:00:00Z",
        }
        result = _space_event_time(space)
        assert result.year == 2024


# ---------------------------------------------------------------------------
# _comment_timestamp
# ---------------------------------------------------------------------------


class TestCommentTimestamp:
    def test_prefers_version_when(self):
        comment = {
            "version": {"when": "2024-07-04T15:00:00Z"},
            "history": {"createdDate": "2023-01-01T00:00:00Z"},
            "id": "cmt-1",
        }
        result = _comment_timestamp(comment)
        assert result == datetime(2024, 7, 4, 15, 0, 0, tzinfo=_UTC)

    def test_falls_back_to_history_created_date(self):
        comment = {"history": {"createdDate": "2023-09-01T10:00:00Z"}, "id": "cmt-2"}
        result = _comment_timestamp(comment)
        assert result == datetime(2023, 9, 1, 10, 0, 0, tzinfo=_UTC)

    def test_falls_back_to_created_at(self):
        comment = {"createdAt": "2022-04-15T08:30:00Z", "id": "cmt-3"}
        result = _comment_timestamp(comment)
        assert result == datetime(2022, 4, 15, 8, 30, 0, tzinfo=_UTC)

    def test_returns_epoch_and_warns_when_absent(self, caplog):
        comment = {"id": "cmt-42"}
        with caplog.at_level(logging.WARNING):
            result = _comment_timestamp(comment)
        assert result == _EPOCH
        assert "cmt-42" in caplog.text

    def test_returns_epoch_on_empty_comment(self, caplog):
        with caplog.at_level(logging.WARNING):
            result = _comment_timestamp({})
        assert result == _EPOCH

    def test_never_returns_now(self):
        result = _comment_timestamp({})
        assert result == _EPOCH


# ---------------------------------------------------------------------------
# _content_created_at (attribute string, not event_time)
# ---------------------------------------------------------------------------


class TestContentCreatedAt:
    def test_prefers_history_created_date(self):
        content = {
            "history": {"createdDate": "2023-03-10T09:00:00Z"},
            "createdAt": "2022-01-01T00:00:00Z",
        }
        result = _content_created_at(content)
        assert result == "2023-03-10T09:00:00Z"

    def test_falls_back_to_created_at(self):
        content = {"createdAt": "2022-06-15T12:00:00Z"}
        result = _content_created_at(content)
        assert result == "2022-06-15T12:00:00Z"

    def test_falls_back_to_version_created_at(self):
        content = {"version": {"createdAt": "2021-11-01T08:00:00Z"}}
        result = _content_created_at(content)
        assert result == "2021-11-01T08:00:00Z"

    def test_returns_epoch_isoformat_and_warns_when_absent(self, caplog):
        content = {"id": "page-007"}
        with caplog.at_level(logging.WARNING):
            result = _content_created_at(content)
        assert result == _EPOCH.isoformat()
        assert "page-007" in caplog.text

    def test_never_returns_now_string(self):
        """Fallback must be epoch ISO string, never a current timestamp."""
        result = _content_created_at({})
        assert result == _EPOCH.isoformat()


# ---------------------------------------------------------------------------
# build_person_signal — no Confluence user timestamp → epoch
# ---------------------------------------------------------------------------


class TestBuildPersonSignalEventTime:
    def test_event_time_is_epoch(self):
        user_data = {"publicName": "Bob", "displayName": "Bob Smith"}
        signal = build_person_signal(user_data, "acc-001", _BASE_URL)
        assert signal is not None
        assert signal.event_time == _EPOCH

    def test_epoch_regardless_of_user_richness(self):
        """Even a fully populated user gets epoch — no Confluence timestamp API."""
        user_data = {
            "publicName": "Alice",
            "displayName": "Alice Wonderland",
            "email": "alice@example.com",
        }
        signal = build_person_signal(user_data, "acc-alice", _BASE_URL)
        assert signal is not None
        assert signal.event_time == _EPOCH

    def test_epoch_is_stable_across_calls(self):
        s1 = build_person_signal({"publicName": "U1"}, "uid-1", _BASE_URL)
        s2 = build_person_signal({"publicName": "U2"}, "uid-2", _BASE_URL)
        assert s1 is not None and s2 is not None
        assert s1.event_time == s2.event_time == _EPOCH

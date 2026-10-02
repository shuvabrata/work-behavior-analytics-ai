"""Unit tests for GitHub producer event_time logic.

Verifies that every signal builder resolves ``event_time`` from meaningful
source timestamps (never ``datetime.now()``) and falls back to the epoch
sentinel (``1970-01-01T00:00:00Z``) with a warning when no timestamp is usable.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

import pytest

from connectors.producers.github.constants import _EPOCH
from connectors.producers.github.build_pull_request_signal import _pr_event_time
from connectors.producers.github.build_issue_signal import _parse_event_time
from connectors.producers.github.build_commit_signal import _commit_event_time
from connectors.producers.github.build_repository_signal import _repo_event_time

_UTC = timezone.utc


class TestPrEventTime:
    def _pr(self, **kwargs):
        base = {
            "number": 42, "state": "open",
            "created_at": "2024-01-10T10:00:00Z",
            "updated_at": "2024-01-15T12:00:00Z",
            "merged_at": None, "closed_at": None,
        }
        base.update(kwargs)
        return base

    @pytest.mark.unit
    def test_merged_pr_uses_merged_at(self):
        pr = self._pr(state="merged", merged_at="2024-01-20T16:00:00Z")
        assert _pr_event_time(pr) == datetime(2024, 1, 20, 16, 0, 0, tzinfo=_UTC)

    @pytest.mark.unit
    def test_closed_pr_uses_closed_at(self):
        pr = self._pr(state="closed", closed_at="2024-01-18T09:00:00Z")
        assert _pr_event_time(pr) == datetime(2024, 1, 18, 9, 0, 0, tzinfo=_UTC)

    @pytest.mark.unit
    def test_open_pr_uses_updated_at(self):
        pr = self._pr(state="open")
        assert _pr_event_time(pr) == datetime(2024, 1, 15, 12, 0, 0, tzinfo=_UTC)

    @pytest.mark.unit
    def test_merged_pr_falls_back_to_updated_when_merged_at_absent(self):
        pr = self._pr(state="merged", merged_at=None)
        assert _pr_event_time(pr) == datetime(2024, 1, 15, 12, 0, 0, tzinfo=_UTC)

    @pytest.mark.unit
    def test_returns_epoch_and_warns_when_all_absent(self, caplog):
        pr = {"number": 99, "state": "open", "updated_at": None, "merged_at": None, "closed_at": None}
        with caplog.at_level(logging.WARNING):
            result = _pr_event_time(pr)
        assert result == _EPOCH
        assert "99" in caplog.text
        assert "epoch sentinel" in caplog.text

    @pytest.mark.unit
    def test_does_not_return_now(self):
        pr = {"number": 1, "state": "merged", "merged_at": None, "closed_at": None, "updated_at": None}
        assert _pr_event_time(pr) == _EPOCH


class TestIssueEventTime:
    @pytest.mark.unit
    def test_prefers_updated_at(self):
        result = _parse_event_time("2024-03-01T10:00:00Z", "2023-01-01T00:00:00Z")
        assert result == datetime(2024, 3, 1, 10, 0, 0, tzinfo=_UTC)

    @pytest.mark.unit
    def test_falls_back_to_created_at(self):
        result = _parse_event_time(None, "2023-05-15T08:00:00Z")
        assert result == datetime(2023, 5, 15, 8, 0, 0, tzinfo=_UTC)

    @pytest.mark.unit
    def test_returns_epoch_and_warns_when_both_absent(self, caplog):
        with caplog.at_level(logging.WARNING):
            result = _parse_event_time(None, None, issue_id="org/repo#42")
        assert result == _EPOCH
        assert "org/repo#42" in caplog.text

    @pytest.mark.unit
    def test_does_not_return_now(self):
        assert _parse_event_time(None, None) == _EPOCH


class TestCommitEventTime:
    @pytest.mark.unit
    def test_parses_author_date(self):
        commit_data = {"sha": "abc123def456", "created_at": "2024-02-14T09:30:00Z"}
        result = _commit_event_time(commit_data)
        assert result == datetime(2024, 2, 14, 9, 30, 0, tzinfo=_UTC)

    @pytest.mark.unit
    def test_returns_epoch_and_warns_when_no_date(self, caplog):
        commit_data = {"sha": "deadbeef1234", "created_at": ""}
        with caplog.at_level(logging.WARNING):
            result = _commit_event_time(commit_data)
        assert result == _EPOCH
        assert "deadbeef" in caplog.text

    @pytest.mark.unit
    def test_does_not_return_now(self):
        assert _commit_event_time({}) == _EPOCH


class TestRepoEventTime:
    @pytest.mark.unit
    def test_parses_created_at(self):
        repo_data = {"full_name": "org/repo", "created_at": "2020-06-01"}
        result = _repo_event_time(repo_data)
        assert result == datetime(2020, 6, 1, 0, 0, 0, tzinfo=_UTC)

    @pytest.mark.unit
    def test_returns_epoch_and_warns_when_absent(self, caplog):
        repo_data = {"full_name": "org/repo", "created_at": ""}
        with caplog.at_level(logging.WARNING):
            result = _repo_event_time(repo_data)
        assert result == _EPOCH
        assert "org/repo" in caplog.text

    @pytest.mark.unit
    def test_does_not_return_now(self):
        assert _repo_event_time({}) == _EPOCH
"""Unit tests for ``activity_writer._compute_display_name``.

Covers the two entity types whose name field the original four-field rule
misses — ``CommitAttributes.message`` and ``PersonAttributes.full_name`` — and
the 512-character clamp that keeps the computed value inside the width of
``activity_events.display_name``.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from common.activity_signal.models import (
    ActivitySignal,
    CommitAttributes,
    PersonAttributes,
)
from connectors.consumers.activity_writer import _compute_display_name

pytestmark = pytest.mark.unit

_EVENT_TIME = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


def _commit_signal(message: str) -> ActivitySignal:
    """Build a Commit signal carrying *message* as its only name field."""
    return ActivitySignal(
        source="github",
        id="abc123",
        source_config="https://github.com",
        connector_url="https://github.com/connector",
        event_time=_EVENT_TIME,
        version="1.0",
        attributes=CommitAttributes(
            sha="abc123",
            message=message,
            author="Alice",
            created_at="2026-01-01T00:00:00Z",
        ),
    )


def _person_signal(full_name: str) -> ActivitySignal:
    """Build a Person signal carrying *full_name* as its only name field."""
    return ActivitySignal(
        source="jira",
        id="557058:abc",
        source_config="https://test.atlassian.net",
        connector_url="https://test.atlassian.net/connector",
        event_time=_EVENT_TIME,
        version="1.0",
        attributes=PersonAttributes(full_name=full_name),
    )


def test_over_long_commit_message_is_clamped_to_512() -> None:
    """A 2000-char commit message yields exactly 512 characters, never raises."""
    signal = _commit_signal("x" * 2000)
    result = _compute_display_name(signal)
    assert len(result) == 512
    assert result == "x" * 512


def test_person_full_name_is_resolved() -> None:
    """A Person's name comes from ``full_name``, not its provider account id."""
    signal = _person_signal("Alice Johnson")
    assert _compute_display_name(signal) == "Alice Johnson"


def test_short_commit_message_is_used_verbatim() -> None:
    """A message under the clamp is returned unchanged."""
    signal = _commit_signal("Fix the timeline card")
    assert _compute_display_name(signal) == "Fix the timeline card"

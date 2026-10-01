"""Unit tests for Activity Timeline API v1 — cursor + WBA ID helpers.

These tests exercise the pure functions in ``service.py`` (cursor
encode/decode round-trip, WBA ID parsing) with no database or network
dependency.

Run with:
    pytest -m unit tests/test_activity_api_unit.py -v
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.api.activity.v1 import service
from app.api.activity.v1.service import (
    InvalidCursorError,
    InvalidWbaIdError,
    _decode_cursor,
    _encode_cursor,
    parse_wba_id,
)

pytestmark = [pytest.mark.unit]


# ---------------------------------------------------------------------------
# WBA ID parsing
# ---------------------------------------------------------------------------


class TestParseWbaId:
    def test_parses_simple_key(self) -> None:
        assert parse_wba_id("github::Person::alice") == ("github", "Person", "alice")

    def test_parses_key_with_colons_in_entity_id(self) -> None:
        # Entity ids may themselves contain "::" — only the first two
        # separators split.
        assert parse_wba_id("jira::Issue::PROJ-1::sub") == (
            "jira",
            "Issue",
            "PROJ-1::sub",
        )

    def test_rejects_too_few_parts(self) -> None:
        with pytest.raises(InvalidWbaIdError):
            parse_wba_id("github::Person")

    def test_rejects_empty_parts(self) -> None:
        with pytest.raises(InvalidWbaIdError):
            parse_wba_id("github::::alice")

    def test_rejects_empty_string(self) -> None:
        with pytest.raises(InvalidWbaIdError):
            parse_wba_id("")


# ---------------------------------------------------------------------------
# Cursor encode / decode
# ---------------------------------------------------------------------------


class TestCursorRoundTrip:
    def test_round_trip_preserves_time_and_id(self) -> None:
        event_time = datetime(2026, 3, 15, 14, 30, 0, tzinfo=timezone.utc)
        cursor = _encode_cursor(event_time, 42)
        decoded_time, decoded_id = _decode_cursor(cursor)
        assert decoded_time == event_time
        assert decoded_id == 42

    def test_round_trip_with_naive_time(self) -> None:
        # Naive datetimes are normalized to UTC on encode.
        event_time = datetime(2026, 3, 15, 14, 30, 0)
        cursor = _encode_cursor(event_time, 7)
        decoded_time, decoded_id = _decode_cursor(cursor)
        assert decoded_time == event_time.replace(tzinfo=timezone.utc)
        assert decoded_id == 7

    def test_cursor_is_opaque_and_urlsafe(self) -> None:
        event_time = datetime(2026, 3, 15, 14, 30, 0, tzinfo=timezone.utc)
        cursor = _encode_cursor(event_time, 42)
        # urlsafe base64 — no +, /, or = padding chars that break URL params.
        assert "+" not in cursor
        assert "/" not in cursor
        assert "=" not in cursor

    def test_different_rows_produce_different_cursors(self) -> None:
        event_time = datetime(2026, 3, 15, 14, 30, 0, tzinfo=timezone.utc)
        assert _encode_cursor(event_time, 1) != _encode_cursor(event_time, 2)

    def test_decode_rejects_garbage(self) -> None:
        with pytest.raises(InvalidCursorError):
            _decode_cursor("not-base64!!!")

    def test_decode_rejects_valid_base64_wrong_shape(self) -> None:
        # Valid base64 but no separator / wrong parts.
        import base64

        bad = base64.urlsafe_b64encode(b"no-separator-here").decode("ascii")
        with pytest.raises(InvalidCursorError):
            _decode_cursor(bad)

    def test_decode_rejects_non_int_row_id(self) -> None:
        import base64

        bad = base64.urlsafe_b64encode(b"2026-03-15T14:30:00+00:00|abc").decode("ascii")
        with pytest.raises(InvalidCursorError):
            _decode_cursor(bad)


# ---------------------------------------------------------------------------
# Service-level helpers
# ---------------------------------------------------------------------------


class TestServiceHelpers:
    def test_encode_cursor_is_exported_for_router_validation(self) -> None:
        # The router validates cursors via service._decode_cursor; ensure the
        # helper remains importable and functional.
        assert callable(service._decode_cursor)  # noqa: SLF001
        assert callable(service._encode_cursor)  # noqa: SLF001
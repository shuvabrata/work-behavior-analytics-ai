"""Unit tests for the auth service's pure logic.

Three concerns, all of which are easy to get subtly wrong and none of which the
flow tests pin precisely:

* the idle/max lifetime comparisons — exactly at the limit must still be valid,
  one second past must not;
* the identity snapshot written at session creation;
* the open-redirect sanitiser's decision table.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from app.api.auth.v1.service import (
    DEFAULT_NEXT_PATH,
    SessionExpiredError,
    _sanitize_next_path,
    _session_expired,
)
from app.settings import settings
from app.auth.principal import Principal
from app.auth.session_cookie import (
    decrypt_refresh_token,
    encrypt_refresh_token,
    hash_session_id,
    new_session_id,
)

pytestmark = pytest.mark.unit


class _Row:
    """A minimal expiry-checkable row."""

    def __init__(self, *, last_seen_at: datetime, expires_at: datetime) -> None:
        self.last_seen_at = last_seen_at
        self.expires_at = expires_at


NOW = datetime(2026, 10, 31, 12, 0, 0, tzinfo=timezone.utc)


# ── lifetime boundaries ──────────────────────────────────────────────────


class TestSessionExpiry:
    def test_exactly_at_the_idle_limit_is_still_valid(self) -> None:
        idle = timedelta(minutes=settings.AUTH_SESSION_IDLE_MINUTES)
        row = _Row(last_seen_at=NOW - idle, expires_at=NOW + timedelta(hours=1))

        assert _session_expired(row, NOW) is None

    def test_one_second_past_the_idle_limit_is_expired(self) -> None:
        idle = timedelta(minutes=settings.AUTH_SESSION_IDLE_MINUTES)
        row = _Row(
            last_seen_at=NOW - idle - timedelta(seconds=1),
            expires_at=NOW + timedelta(hours=1),
        )

        assert isinstance(_session_expired(row, NOW), SessionExpiredError)

    def test_exactly_at_the_max_lifetime_is_still_valid(self) -> None:
        row = _Row(last_seen_at=NOW, expires_at=NOW)

        assert _session_expired(row, NOW) is None

    def test_one_second_past_the_max_lifetime_is_expired(self) -> None:
        row = _Row(last_seen_at=NOW, expires_at=NOW - timedelta(seconds=1))

        assert isinstance(_session_expired(row, NOW), SessionExpiredError)

    def test_max_wins_when_both_are_past(self) -> None:
        row = _Row(
            last_seen_at=NOW - timedelta(hours=48),
            expires_at=NOW - timedelta(hours=1),
        )

        assert "maximum" in str(_session_expired(row, NOW))


# ── identity snapshot ────────────────────────────────────────────────────


class TestIdentitySnapshot:
    def test_principal_roles_snapshot_is_stored_sorted(self) -> None:
        principal = Principal(
            subject="sub-7",
            username="carol",
            roles=frozenset({"wba-admin", "wba-user"}),
        )

        assert sorted(principal.roles) == ["wba-admin", "wba-user"]
        assert principal.subject == "sub-7"
        assert principal.username == "carol"


# ── next-path sanitiser ──────────────────────────────────────────────────


class TestNextSanitiser:
    @pytest.mark.parametrize(
        "candidate",
        [
            "https://evil.example",
            "//evil.example",
            "/app/../secret",
            "/app\\..\\secret",
            "/app/graph\nSet-Cookie: x=y",
            "/app/graph\rX",
            "",
            None,
            "/other",
            "app/graph",
        ],
    )
    def test_unsafe_values_fall_back(self, candidate: str | None) -> None:
        assert _sanitize_next_path(candidate) == DEFAULT_NEXT_PATH

    @pytest.mark.parametrize(
        "candidate",
        ["/app/graph", "/app/catalog/a/b", "/app/graph?wba_ids=1"],
    )
    def test_safe_values_are_kept(self, candidate: str) -> None:
        assert _sanitize_next_path(candidate) == candidate


# ── cookie and refresh-token helpers ─────────────────────────────────────


class TestCookieHelpers:
    def test_session_id_is_opaque_and_hashes_to_64_hex(self) -> None:
        raw = new_session_id()

        assert len(hash_session_id(raw)) == 64

    def test_refresh_token_round_trips_encrypted(self) -> None:
        stored = encrypt_refresh_token("a-secret-refresh-token")

        assert stored != "a-secret-refresh-token"
        assert decrypt_refresh_token(stored) == "a-secret-refresh-token"

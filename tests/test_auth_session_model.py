"""Unit tests for the ``AuthSession`` model.

The model is the server-side session record for the BFF. ``session_id_hash``
holds a SHA-256 hex digest supplied by the login flow; the model itself never
derives it from a plaintext id — the hashing helper is plan 056's.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone

import pytest

from app.db.models.auth_session import AuthSession

pytestmark = [pytest.mark.unit]


def _make_session(**overrides: object) -> AuthSession:
    """Build an AuthSession row (not persisted)."""
    now = datetime.now(timezone.utc)
    defaults: dict[str, object] = {
        "session_id_hash": hashlib.sha256(b"opaque-cookie-id").hexdigest(),
        "subject": "sub-1",
        "username": "alice",
        "roles": ["wba-user"],
        "refresh_token_encrypted": "gAAAAA-fake-fernet-token",
        "expires_at": now + timedelta(hours=8),
        "last_seen_at": now,
    }
    defaults.update(overrides)
    return AuthSession(**defaults)


class TestAuthSessionModel:
    def test_tablename(self) -> None:
        """The table is named ``auth_session``."""
        assert AuthSession.__tablename__ == "auth_session"

    def test_constructs_with_required_fields(self) -> None:
        """A row exposes the identity and timing fields it was built with."""
        row = _make_session()
        assert row.subject == "sub-1"
        assert row.username == "alice"
        assert row.roles == ["wba-user"]
        assert isinstance(row.expires_at, datetime)
        assert isinstance(row.last_seen_at, datetime)

    def test_revoked_at_defaults_to_none(self) -> None:
        """An unrevoked row leaves ``revoked_at`` unset."""
        assert _make_session().revoked_at is None

    def test_revoked_at_can_be_set(self) -> None:
        """A revoked row carries the revocation timestamp."""
        now = datetime.now(timezone.utc)
        assert _make_session(revoked_at=now).revoked_at == now

    def test_session_id_hash_is_unique(self) -> None:
        """``session_id_hash`` carries a unique constraint at the model level."""
        assert AuthSession.__table__.c.session_id_hash.unique is True

    def test_session_id_hash_unique_index(self) -> None:
        """The uniqueness is backed by a unique index on the column."""
        unique_indexes = {
            idx.name
            for idx in AuthSession.__table__.indexes
            if idx.unique and list(idx.columns.keys()) == ["session_id_hash"]
        }
        assert unique_indexes

    def test_subject_is_indexed(self) -> None:
        """``subject`` is indexed for lookup by Keycloak sub."""
        assert AuthSession.__table__.c.subject.index is True

    def test_roles_are_stored_as_given(self) -> None:
        """The roles snapshot is stored verbatim, including multiple roles."""
        row = _make_session(roles=["wba-user", "wba-admin"])
        assert row.roles == ["wba-user", "wba-admin"]

    def test_repr(self) -> None:
        """``__repr__`` exposes the identity fields."""
        text = repr(_make_session())
        assert "AuthSession" in text
        assert "sub-1" in text
        assert "alice" in text

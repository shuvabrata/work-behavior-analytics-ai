"""Unit tests for the ``Principal`` dataclass and its role helpers."""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from app.auth.principal import CredentialType, Principal

pytestmark = [pytest.mark.unit]


def _principal(*roles: str) -> Principal:
    """Build a Principal carrying *roles*."""
    return Principal(subject="sub-1", username="alice", roles=frozenset(roles))


class TestPrincipalRoles:
    def test_admin_is_admin(self) -> None:
        """``admin`` makes ``is_admin`` true."""
        assert _principal("admin").is_admin is True

    def test_user_is_not_admin(self) -> None:
        """``user`` alone is not admin."""
        assert _principal("user").is_admin is False

    def test_service_is_not_admin(self) -> None:
        """``service`` alone is not admin."""
        assert _principal("service").is_admin is False

    def test_empty_roles(self) -> None:
        """An empty role set carries nothing."""
        principal = _principal()
        assert principal.is_admin is False
        assert principal.has_role("user") is False

    def test_has_role_matches(self) -> None:
        """``has_role`` is true only for a carried role."""
        principal = _principal("user")
        assert principal.has_role("user") is True
        assert principal.has_role("admin") is False


class TestPrincipalShape:
    def test_credential_defaults_to_bearer(self) -> None:
        """The default credential type is the bearer."""
        assert _principal("user").credential is CredentialType.BEARER

    def test_credential_can_be_session(self) -> None:
        """A session credential is representable."""
        principal = Principal(
            subject="s",
            username="u",
            roles=frozenset({"user"}),
            credential=CredentialType.SESSION,
        )
        assert principal.credential is CredentialType.SESSION

    def test_is_frozen(self) -> None:
        """The dataclass is frozen — attribute assignment raises."""
        principal = _principal("admin")
        with pytest.raises(FrozenInstanceError):
            principal.subject = "other"  # type: ignore[misc]

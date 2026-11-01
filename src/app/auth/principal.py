"""The single object every credential resolves to.

Every authorization rule is written against this type, so the bearer and the
session credential never need separate rules. ``credential`` exists only so the
two are distinguishable in logs and tests.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass


class CredentialType(str, enum.Enum):
    """How the caller proved identity."""

    BEARER = "bearer"
    SESSION = "session"


@dataclass(frozen=True)
class Principal:
    """An authenticated caller.

    Attributes:
        subject: Keycloak ``sub`` — stable, never reused.
        username: ``preferred_username``, for display and audit.
        roles: Mapped internal roles. Unknown realm roles are dropped; a token
            with no recognised role never reaches construction.
        credential: Which credential type produced this principal.
    """

    subject: str
    username: str
    roles: frozenset[str]
    credential: CredentialType = CredentialType.BEARER

    def has_role(self, role: str) -> bool:
        """Return whether this principal carries *role*."""
        return role in self.roles

    @property
    def is_admin(self) -> bool:
        """Return whether this principal carries ``wba-admin``."""
        return "wba-admin" in self.roles

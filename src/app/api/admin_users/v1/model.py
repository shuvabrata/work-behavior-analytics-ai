"""Pydantic models for the admin user management API.

``ASSIGNABLE_REALM_ROLES`` is the single source of truth for which realm roles
an administrator may grant or revoke through this surface. The UI reads it over
HTTP from ``GET /api/v1/admin/users/roles`` rather than duplicating it.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

ASSIGNABLE_REALM_ROLES: frozenset[str] = frozenset({"wba-admin", "wba-user"})


class UserSummary(BaseModel):
    """A user as the admin surface presents it."""

    id: str
    username: str
    email: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    enabled: bool
    roles: list[str]
    created_timestamp: int | None = None


class UserListResponse(BaseModel):
    """A page of users plus the total count of listable users."""

    users: list[UserSummary]
    total: int
    offset: int
    limit: int


class UserCreatedResponse(UserSummary):
    """A created user, plus any non-fatal warnings from the create."""

    warnings: list[str] = Field(default_factory=list)


class UserCreate(BaseModel):
    """The request body for creating a user."""

    username: str = Field(min_length=1, max_length=255)
    email: str = Field(min_length=3, max_length=255)
    first_name: str | None = None
    last_name: str | None = None
    enabled: bool = True
    roles: list[str] = Field(min_length=1)
    password: str | None = Field(default=None, min_length=8)


class UserUpdate(BaseModel):
    """The request body for updating a user; every field is optional."""

    email: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    enabled: bool | None = None
    roles: list[str] | None = None


class PasswordReset(BaseModel):
    """The request body for resetting a user's password."""

    password: str = Field(min_length=8)
    temporary: bool = True


class AssignableRolesResponse(BaseModel):
    """The realm roles an administrator may assign."""

    roles: list[str]

"""Business logic for the admin user management API.

Owns the rules — role validation, the self-delete and last-admin guards,
service-account protection — and raises plain exceptions the router maps to HTTP
responses. The Keycloak client is synchronous, so every network call is
dispatched through ``asyncio.to_thread`` to keep the event loop free.
"""

from __future__ import annotations

import asyncio

from app.api.admin_users.v1 import query
from app.api.admin_users.v1.model import (
    ASSIGNABLE_REALM_ROLES,
    AssignableRolesResponse,
    UserCreate,
    UserCreatedResponse,
    UserListResponse,
    UserSummary,
    UserUpdate,
)
from app.auth.keycloak_admin import KeycloakNotFoundError, KeycloakPolicyError
from app.auth.principal import Principal
from common.logger import logger


class AdminUserError(Exception):
    """Base class for every admin-users service failure."""


class UserNotFoundError(AdminUserError):
    """The target user does not exist."""


class UserExistsError(AdminUserError):
    """A user with that username or email already exists."""


class LastAdminError(AdminUserError):
    """The operation would remove the last ``wba-admin`` holder."""


class SelfDeleteError(AdminUserError):
    """An administrator may not delete their own account."""


class ServiceAccountError(AdminUserError):
    """A service-account user cannot be managed through this surface."""


class PasswordPolicyError(AdminUserError):
    """Keycloak rejected the password against the realm's policy."""


class InvalidRoleError(AdminUserError):
    """A role outside the assignable set was requested."""


def _validate_roles(role_names: list[str]) -> None:
    invalid = sorted(set(role_names) - ASSIGNABLE_REALM_ROLES)
    if invalid:
        raise InvalidRoleError(f"Role(s) not assignable: {', '.join(invalid)}")


def _translate_not_found(exc: Exception) -> None:
    """Translate a client not-found into ``UserNotFoundError``."""
    if isinstance(exc, KeycloakNotFoundError):
        raise UserNotFoundError(str(exc)) from exc


async def _read_or_not_found(user_id: str) -> dict[str, object]:
    """Read a raw user representation, mapping not-found to ``UserNotFoundError``."""
    try:
        return await asyncio.to_thread(query.get_user_raw, user_id)
    except KeycloakNotFoundError as exc:
        raise UserNotFoundError(str(exc)) from exc


async def list_users(offset: int, limit: int, search: str | None) -> UserListResponse:
    """Return a page of listable users."""
    users, total = await asyncio.to_thread(query.list_users, offset, limit, search)
    return UserListResponse(users=users, total=total, offset=offset, limit=limit)


def list_assignable_roles() -> AssignableRolesResponse:
    """Return the sorted assignable realm roles for the UI's checkbox list."""
    return AssignableRolesResponse(roles=sorted(ASSIGNABLE_REALM_ROLES))


async def get_user(user_id: str) -> UserSummary:
    """Return one user summary, or raise ``UserNotFoundError``."""
    try:
        return await asyncio.to_thread(query.get_user, user_id)
    except KeycloakNotFoundError as exc:
        raise UserNotFoundError(str(exc)) from exc


async def create_user(payload: UserCreate, actor: Principal) -> tuple[UserCreatedResponse, list[str]]:
    """Create a user and any roles; returns the user plus its warnings list."""
    _validate_roles(payload.roles)

    body: dict[str, object] = {
        "username": payload.username,
        "email": payload.email,
        "enabled": payload.enabled,
    }
    if payload.first_name is not None:
        body["firstName"] = payload.first_name
    if payload.last_name is not None:
        body["lastName"] = payload.last_name

    from app.auth.keycloak_admin import KeycloakConflictError  # pylint: disable=import-outside-toplevel

    try:
        user_id = await asyncio.to_thread(query.create_user, body)
    except KeycloakConflictError as exc:
        raise UserExistsError(str(exc)) from exc

    if payload.roles:
        await asyncio.to_thread(query.assign_realm_roles, user_id, list(payload.roles))

    warnings: list[str] = []
    if payload.password:
        try:
            await asyncio.to_thread(query.set_password, user_id, payload.password, True)
        except Exception:  # pylint: disable=broad-except
            logger.error(
                f"User created but password could not be set: user_id={user_id}",
                exc_info=True,
            )
            warnings.append("password_not_set")

    logger.info(
        f"user_created actor={actor.username!r} sub={actor.subject!r} "
        f"target={payload.username!r} user_id={user_id} roles={sorted(payload.roles)}"
    )
    user = await get_user(user_id)
    return UserCreatedResponse(**user.model_dump(), warnings=warnings), warnings


async def _ensure_not_last_admin() -> None:
    """Raise ``LastAdminError`` when removing or disabling would leave no admin."""
    holders = await asyncio.to_thread(query.users_with_role, "wba-admin")
    if len(holders) <= 1:
        raise LastAdminError("Cannot remove or disable the last administrator.")


async def update_user(
    user_id: str, payload: UserUpdate, actor: Principal
) -> tuple[UserSummary, bool]:
    """Update a user; returns the reloaded summary and whether it was disabled now."""
    current = await _read_or_not_found(user_id)

    if query.is_service_account(current):
        raise ServiceAccountError("Service-account users cannot be modified here.")

    if payload.roles is not None:
        _validate_roles(payload.roles)

    was_enabled = bool(current.get("enabled", False))
    disabling_now = payload.enabled is False and was_enabled
    current_roles = await asyncio.to_thread(query.current_roles, user_id)

    removing_admin = (
        payload.roles is not None
        and "wba-admin" in current_roles
        and "wba-admin" not in payload.roles
    )
    if "wba-admin" in current_roles and (disabling_now or removing_admin):
        await _ensure_not_last_admin()

    body: dict[str, object] = {}
    if payload.email is not None:
        body["email"] = payload.email
    if payload.first_name is not None:
        body["firstName"] = payload.first_name
    if payload.last_name is not None:
        body["lastName"] = payload.last_name
    if payload.enabled is not None:
        body["enabled"] = payload.enabled
    if body:
        await asyncio.to_thread(query.update_user, user_id, body)

    if payload.roles is not None:
        desired = set(payload.roles)
        to_add = sorted(desired - current_roles)
        to_remove = sorted(current_roles - desired)
        if to_add:
            await asyncio.to_thread(query.assign_realm_roles, user_id, to_add)
            logger.info(
                f"user_role_granted actor={actor.username!r} sub={actor.subject!r} "
                f"user_id={user_id} roles={to_add}"
            )
        if to_remove:
            await asyncio.to_thread(query.remove_realm_roles, user_id, to_remove)
            logger.info(
                f"user_role_removed actor={actor.username!r} sub={actor.subject!r} "
                f"user_id={user_id} roles={to_remove}"
            )

    if disabling_now:
        logger.info(f"user_disabled actor={actor.username!r} sub={actor.subject!r} user_id={user_id}")

    user = await get_user(user_id)
    return user, disabling_now


async def set_password(user_id: str, password: str, temporary: bool, actor: Principal) -> None:
    """Set a user's password, refusing service accounts and policy failures."""
    current = await _read_or_not_found(user_id)
    if query.is_service_account(current):
        raise ServiceAccountError("Service-account users cannot be modified here.")

    try:
        await asyncio.to_thread(query.set_password, user_id, password, temporary)
    except KeycloakPolicyError as exc:
        raise PasswordPolicyError(str(exc)) from exc
    logger.info(
        f"user_password_reset actor={actor.username!r} sub={actor.subject!r} "
        f"user_id={user_id} temporary={temporary}"
    )


async def delete_user(user_id: str, actor: Principal) -> None:
    """Delete a user, refusing self-delete, service accounts, and last admin."""
    if actor.subject == user_id:
        raise SelfDeleteError("You cannot delete your own account.")

    current = await _read_or_not_found(user_id)
    if query.is_service_account(current):
        raise ServiceAccountError("Service-account users cannot be deleted here.")

    current_roles = await asyncio.to_thread(query.current_roles, user_id)
    if "wba-admin" in current_roles:
        await _ensure_not_last_admin()

    await asyncio.to_thread(query.delete_user, user_id)
    logger.info(
        f"user_deleted actor={actor.username!r} sub={actor.subject!r} user_id={user_id}"
    )

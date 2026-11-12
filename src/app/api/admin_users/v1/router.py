"""FastAPI router for the admin user management API.

Every operation is ``wba-admin``-only; the dependency is supplied at include
time in ``app.api_main``. Mutating handlers also declare
``principal: Principal = Depends(require_admin)`` so the caller reaches the
handler for the audit line and the self-delete guard.
"""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Response

from app.api.admin_users.v1 import cleanup
from app.api.admin_users.v1 import service
from app.api.admin_users.v1.model import (
    AssignableRolesResponse,
    PasswordReset,
    UserCreate,
    UserCreatedResponse,
    UserListResponse,
    UserSummary,
    UserUpdate,
)
from app.auth.dependencies import require_admin
from app.auth.keycloak_admin import (
    KeycloakConflictError,
    KeycloakNotFoundError,
    KeycloakPolicyError,
    KeycloakUnavailableError,
)
from app.auth.principal import Principal

router = APIRouter(prefix="/admin/users", tags=["admin-users"])

_STATUS_BY_ERROR: dict[type[Exception], tuple[int, str]] = {
    service.UserNotFoundError: (404, "user_not_found"),
    KeycloakNotFoundError: (404, "user_not_found"),
    service.UserExistsError: (409, "user_exists"),
    KeycloakConflictError: (409, "user_exists"),
    service.LastAdminError: (409, "last_admin"),
    service.SelfDeleteError: (409, "self_delete"),
    service.ServiceAccountError: (409, "service_account"),
    service.InvalidRoleError: (422, "invalid_role"),
    service.PasswordPolicyError: (422, "password_policy"),
    KeycloakPolicyError: (422, "password_policy"),
    KeycloakUnavailableError: (503, "identity_provider_unavailable"),
}


def _translate(exc: Exception) -> HTTPException:
    status_code, error = _STATUS_BY_ERROR[type(exc)]
    return HTTPException(status_code=status_code, detail={"error": error, "message": str(exc)})


_MAPPED_ERRORS = (
    service.AdminUserError,
    KeycloakNotFoundError,
    KeycloakConflictError,
    KeycloakPolicyError,
    KeycloakUnavailableError,
)


@router.get("/", response_model=UserListResponse)
async def list_users(
    offset: int = Query(0, ge=0),
    limit: int = Query(25, ge=1, le=100),
    search: str | None = None,
) -> UserListResponse:
    """List application users, service accounts excluded."""
    try:
        return await service.list_users(offset, limit, search)
    except KeycloakUnavailableError as exc:
        raise _translate(exc) from exc


@router.post("/", response_model=UserCreatedResponse, status_code=201)
async def create_user(
    payload: UserCreate,
    principal: Principal = Depends(require_admin),
) -> UserCreatedResponse:
    """Create a user and assign initial roles."""
    try:
        created, _warnings = await service.create_user(payload, principal)
    except _MAPPED_ERRORS as exc:
        raise _translate(exc) from exc
    return created


@router.get("/roles", response_model=AssignableRolesResponse)
async def list_assignable_roles() -> AssignableRolesResponse:
    """List the realm roles an administrator may assign."""
    return service.list_assignable_roles()


@router.get("/{user_id}", response_model=UserSummary)
async def get_user(user_id: str) -> UserSummary:
    """Return one user."""
    try:
        return await service.get_user(user_id)
    except _MAPPED_ERRORS as exc:
        raise _translate(exc) from exc


@router.patch("/{user_id}", response_model=UserSummary)
async def update_user(
    user_id: str,
    payload: UserUpdate,
    background: BackgroundTasks,
    principal: Principal = Depends(require_admin),
) -> UserSummary:
    """Update a user; revoke their sessions when the account is disabled."""
    try:
        user, disabled_now = await service.update_user(user_id, payload, principal)
    except _MAPPED_ERRORS as exc:
        raise _translate(exc) from exc
    if disabled_now:
        background.add_task(cleanup.revoke_user_sessions, user_id)
    return user


@router.put("/{user_id}/password", status_code=204)
async def reset_password(
    user_id: str,
    payload: PasswordReset,
    principal: Principal = Depends(require_admin),
) -> Response:
    """Reset a user's password."""
    try:
        await service.set_password(user_id, payload.password, payload.temporary, principal)
    except _MAPPED_ERRORS as exc:
        raise _translate(exc) from exc
    return Response(status_code=204)


@router.delete("/{user_id}", status_code=204)
async def delete_user(
    user_id: str,
    background: BackgroundTasks,
    principal: Principal = Depends(require_admin),
) -> Response:
    """Delete a user and purge their app-owned rows."""
    try:
        await service.delete_user(user_id, principal)
    except _MAPPED_ERRORS as exc:
        raise _translate(exc) from exc
    background.add_task(cleanup.purge_user_data, user_id)
    return Response(status_code=204)

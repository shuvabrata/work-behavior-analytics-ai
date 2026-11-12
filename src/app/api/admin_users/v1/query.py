"""Keycloak-backed data access for the admin user management API.

The only module that imports ``app.auth.keycloak_admin``. It translates Keycloak
user representations into ``UserSummary`` and keeps service-account users out of
the admin surface, which Keycloak itself cannot filter server-side.
"""

from __future__ import annotations

from app.api.admin_users.v1.model import ASSIGNABLE_REALM_ROLES, UserSummary
from app.auth import keycloak_admin

_SERVICE_ACCOUNT_PREFIX = "service-account-"


def is_service_account(user: dict[str, object]) -> bool:
    """Return whether *user* is a client's service account."""
    if user.get("serviceAccountClientId"):
        return True
    return str(user.get("username", "")).startswith(_SERVICE_ACCOUNT_PREFIX)


def _to_summary(user: dict[str, object], roles: list[str]) -> UserSummary:
    """Convert a Keycloak user representation into a ``UserSummary``."""
    created = user.get("createdTimestamp")
    email = user.get("email")
    first_name = user.get("firstName")
    last_name = user.get("lastName")
    return UserSummary(
        id=str(user["id"]),
        username=str(user.get("username", "")),
        email=email if isinstance(email, str) else None,
        first_name=first_name if isinstance(first_name, str) else None,
        last_name=last_name if isinstance(last_name, str) else None,
        enabled=bool(user.get("enabled", False)),
        roles=roles,
        created_timestamp=int(created) if isinstance(created, (int, float)) else None,
    )


def list_users(
    offset: int, limit: int, search: str | None
) -> tuple[list[UserSummary], int]:
    """Return a page of listable users and the count of listable users.

    Keycloak's own count includes service-account users, so ``total`` is
    ``count - service_account_count`` — the count of rows the pager can render.
    """
    raw_users, count = keycloak_admin.list_users(offset, limit, search)
    service_account_count = keycloak_admin.count_users(_SERVICE_ACCOUNT_PREFIX)

    summaries: list[UserSummary] = []
    for user in raw_users:
        if is_service_account(user):
            continue
        roles = keycloak_admin.realm_roles(str(user["id"]))
        summaries.append(
            _to_summary(user, sorted(set(roles) & ASSIGNABLE_REALM_ROLES))
        )
    return summaries, count - service_account_count


def get_user_raw(user_id: str) -> dict[str, object]:
    """Return a user's raw Keycloak representation; 404 propagates as not-found."""
    return keycloak_admin.get_user(user_id)


def get_user(user_id: str) -> UserSummary:
    """Return one user summary; ``KeycloakNotFoundError`` propagates."""
    user = keycloak_admin.get_user(user_id)
    if is_service_account(user):
        roles: list[str] = []
    else:
        roles = sorted(set(keycloak_admin.realm_roles(user_id)) & ASSIGNABLE_REALM_ROLES)
    return _to_summary(user, roles)


def current_roles(user_id: str) -> set[str]:
    """Return the assignable realm roles the user currently holds."""
    return set(keycloak_admin.realm_roles(user_id)) & ASSIGNABLE_REALM_ROLES


def create_user(payload: dict[str, object]) -> str:
    """Create a user and return the new id."""
    return keycloak_admin.create_user(payload)


def update_user(user_id: str, payload: dict[str, object]) -> None:
    """Update a user representation."""
    keycloak_admin.update_user(user_id, payload)


def delete_user(user_id: str) -> None:
    """Delete a user."""
    keycloak_admin.delete_user(user_id)


def set_password(user_id: str, password: str, temporary: bool) -> None:
    """Set a user's password."""
    keycloak_admin.set_password(user_id, password, temporary)


def users_with_role(role_name: str) -> list[dict[str, object]]:
    """Return every user holding *role_name*."""
    return keycloak_admin.users_with_role(role_name)


def assign_realm_roles(user_id: str, role_names: list[str]) -> None:
    """Assign realm roles to a user."""
    keycloak_admin.assign_realm_roles(user_id, role_names)


def remove_realm_roles(user_id: str, role_names: list[str]) -> None:
    """Remove realm roles from a user."""
    keycloak_admin.remove_realm_roles(user_id, role_names)

"""Callbacks for the User Management settings page.

Every API call goes through ``ui.api_client`` with the BFF-minted bearer. The
assignable roles are fetched from the API and rendered into the create/edit
modals rather than hardcoded here, so ``ASSIGNABLE_REALM_ROLES`` stays the single
source of truth.
"""

from __future__ import annotations

from typing import Any

import dash_bootstrap_components as dbc
from dash import (
    ALL,
    Input,
    Output,
    State,
    callback,
    callback_context,
    no_update,
)
from dash.exceptions import PreventUpdate

from ui import api_client
from ui.api_client import ApiError, AuthExpiredError, PermissionDeniedError
from ui.components.common import create_permission_denied_alert
from ui.components.permission_errors import handle_api_error
from ui.pages.settings.user_management.layout import DEFAULT_LIMIT, _role_checkboxes, _render_table
from ui.styles import FONT_SANS, FONT_SIZE_XTINY

_CURRENT_PATH = "/app/settings/user-management"
_ACTION = "manage users"


def _feedback(content: Any, color: str = "info", *, dismissable: bool = True) -> Any:
    return dbc.Alert(
        content,
        color=color,
        dismissable=dismissable,
        style={"fontFamily": FONT_SANS, "fontSize": FONT_SIZE_XTINY},
    )


def _fetch_roles() -> tuple[list[str], Any]:
    """Return ``(roles, error_alert)``; ``error_alert`` is None on success."""
    try:
        roles = api_client.get_json("/api/v1/admin/users/roles").get("roles", [])
        return list(roles), None
    except PermissionDeniedError:
        return [], create_permission_denied_alert(_ACTION)
    except ApiError as exc:
        return [], _feedback(f"Could not load roles: {exc}", "danger")


def render_users_page(
    state: dict[str, Any],
) -> tuple[Any, Any, list[str], Any, Any, bool, bool, str]:
    """Fetch and render one page of users plus the assignable roles.

    Returns ``(table_children, feedback_children, roles, create_roles_children,
    edit_roles_children, prev_disabled, next_disabled, page_label)``. Pure given
    ``api_client``'s transport, so tests drive it directly with a stubbed
    transport.
    """
    offset = int(state.get("offset", 0))
    limit = int(state.get("limit", DEFAULT_LIMIT))
    search = state.get("search", "") or ""

    roles, roles_error = _fetch_roles()
    create_roles = _role_checkboxes(roles, "um-create")
    edit_roles = _role_checkboxes(roles, "um-edit")

    try:
        payload = api_client.get_json(
            "/api/v1/admin/users/",
            params={"offset": offset, "limit": limit, "search": search},
        )
    except AuthExpiredError as exc:
        handle_api_error(exc, _ACTION, current_path=_CURRENT_PATH)
        raise PreventUpdate from exc
    except PermissionDeniedError:
        return (
            no_update,
            create_permission_denied_alert(_ACTION),
            roles,
            create_roles,
            edit_roles,
            True,
            True,
            no_update,
        )
    except ApiError as exc:
        return (
            no_update,
            _feedback(f"Could not load users: {exc}", "danger"),
            roles,
            create_roles,
            edit_roles,
            True,
            True,
            no_update,
        )

    users = payload.get("users", [])
    total = int(payload.get("total", 0))
    table = _render_table(users)
    prev_disabled = offset <= 0
    next_disabled = offset + limit >= total
    page_label = f"Page {offset // limit + 1}"
    feedback = roles_error if roles_error is not None else no_update
    return table, feedback, roles, create_roles, edit_roles, prev_disabled, next_disabled, page_label


@callback(
    Output("um-table", "children"),
    Output("um-feedback", "children"),
    Output("um-roles", "data"),
    Output("um-create-roles-container", "children"),
    Output("um-edit-roles-container", "children", allow_duplicate=True),
    Output("um-prev", "disabled"),
    Output("um-next", "disabled"),
    Output("um-page-indicator", "children"),
    Input("url", "pathname"),
    Input("um-state", "data"),
    Input("um-refresh", "data"),
    prevent_initial_call="initial_duplicate",
)
def load_users_page(
    _pathname: str | None,
    state: dict[str, Any] | None,
    _refresh: int | None,
) -> tuple[Any, Any, list[str], Any, Any, bool, bool, Any]:
    """Load and render the current page of users."""
    if _pathname != _CURRENT_PATH:
        raise PreventUpdate
    return render_users_page(state or {"offset": 0, "limit": DEFAULT_LIMIT, "search": ""})


@callback(
    Output("um-state", "data", allow_duplicate=True),
    Input("um-search", "value"),
    prevent_initial_call=True,
)
def apply_search(value: str | None) -> dict[str, Any]:
    """Reset to the first page when the search term changes."""
    return {"offset": 0, "limit": DEFAULT_LIMIT, "search": value or ""}


@callback(
    Output("um-state", "data", allow_duplicate=True),
    Input("um-prev", "n_clicks"),
    Input("um-next", "n_clicks"),
    State("um-state", "data"),
    prevent_initial_call=True,
)
def paginate(
    _prev: int | None, _next: int | None, state: dict[str, Any] | None
) -> dict[str, Any]:
    """Move to the previous or next page."""
    if not callback_context.triggered:
        raise PreventUpdate
    current = state or {"offset": 0, "limit": DEFAULT_LIMIT, "search": ""}
    offset = int(current.get("offset", 0))
    limit = int(current.get("limit", DEFAULT_LIMIT))
    if callback_context.triggered_id == "um-prev":
        offset = max(0, offset - limit)
    else:
        offset = offset + limit
    return {**current, "offset": offset}


@callback(
    Output("um-create-modal", "is_open", allow_duplicate=True),
    Output("um-feedback", "children", allow_duplicate=True),
    Output("um-refresh", "data", allow_duplicate=True),
    Input("um-create-open", "n_clicks"),
    Input("um-create-save", "n_clicks"),
    State("um-create-username", "value"),
    State("um-create-email", "value"),
    State("um-create-first-name", "value"),
    State("um-create-last-name", "value"),
    State("um-create-enabled", "value"),
    State("um-create-roles", "value"),
    State("um-create-password", "value"),
    State("um-refresh", "data"),
    prevent_initial_call=True,
)
def create_user(
    _open: int | None,
    _save: int | None,
    username: str | None,
    email: str | None,
    first_name: str | None,
    last_name: str | None,
    enabled: list[str] | None,
    roles: list[str] | None,
    password: str | None,
    refresh: int | None,
) -> tuple[Any, Any, Any]:
    """Open the create modal, or create the user on save."""
    if callback_context.triggered_id == "um-create-open":
        return True, no_update, no_update

    body: dict[str, Any] = {
        "username": username or "",
        "email": email or "",
        "first_name": first_name or None,
        "last_name": last_name or None,
        "enabled": "enabled" in (enabled or []),
        "roles": roles or [],
    }
    if password:
        body["password"] = password

    try:
        response = api_client.post_json("/api/v1/admin/users/", body)
    except (AuthExpiredError, PermissionDeniedError) as exc:
        return True, handle_api_error(exc, _ACTION, current_path=_CURRENT_PATH), no_update
    except ApiError as exc:
        if exc.status_code == 409:
            return True, _feedback("A user with that username or email already exists.", "danger"), no_update
        if exc.status_code == 422:
            return True, _feedback(exc.message, "danger"), no_update
        return True, _feedback(f"Create failed: {exc}", "danger"), no_update

    alerts = [_feedback(f"Created user “{response.get('username', '')}”.", "success", dismissable=True)]
    if response.get("warnings"):
        alerts.append(_feedback("The user was created but the password could not be set.", "warning"))
    return False, alerts, (refresh or 0) + 1


@callback(
    Output("um-create-modal", "is_open", allow_duplicate=True),
    Input("um-create-cancel", "n_clicks"),
    prevent_initial_call=True,
)
def cancel_create(_n: int | None) -> bool:
    """Close the create modal without saving."""
    return False


@callback(
    Output("um-edit-modal", "is_open"),
    Output("um-edit-email", "value"),
    Output("um-edit-first-name", "value"),
    Output("um-edit-last-name", "value"),
    Output("um-edit-enabled", "value"),
    Output("um-edit-roles-container", "children"),
    Output("um-edit-target", "data"),
    Input({"type": "um-row", "action": "edit", "user_id": ALL}, "n_clicks"),
    State("um-roles", "data"),
    prevent_initial_call=True,
)
def open_edit_modal(
    _clicks: list[int | None], roles: list[str] | None
) -> tuple[Any, ...]:
    """Load the clicked user into the edit form and open the modal."""
    triggered = callback_context.triggered_id
    if not isinstance(triggered, dict) or not any(n for n in _clicks):
        raise PreventUpdate
    user_id = triggered.get("user_id")

    try:
        user = api_client.get_json(f"/api/v1/admin/users/{user_id}")
    except (AuthExpiredError, PermissionDeniedError) as exc:
        return (
            False,
            no_update,
            no_update,
            no_update,
            no_update,
            no_update,
            handle_api_error(exc, _ACTION, current_path=_CURRENT_PATH),
        )
    except ApiError as exc:
        return (
            False,
            no_update,
            no_update,
            no_update,
            no_update,
            no_update,
            _feedback(f"Could not load user: {exc}", "danger"),
        )

    current_roles = user.get("roles", [])
    checkboxes = _role_checkboxes(list(roles or []), "um-edit")
    if checkboxes:
        checkboxes[0].value = current_roles
    return (
        True,
        user.get("email") or "",
        user.get("first_name") or "",
        user.get("last_name") or "",
        ["enabled"] if user.get("enabled") else [],
        checkboxes,
        {"user_id": user_id, "username": user.get("username", "")},
    )


@callback(
    Output("um-edit-modal", "is_open", allow_duplicate=True),
    Input("um-edit-cancel", "n_clicks"),
    prevent_initial_call=True,
)
def cancel_edit(_n: int | None) -> bool:
    """Close the edit modal without saving."""
    return False


@callback(
    Output("um-edit-modal", "is_open", allow_duplicate=True),
    Output("um-feedback", "children", allow_duplicate=True),
    Output("um-refresh", "data", allow_duplicate=True),
    Input("um-edit-save", "n_clicks"),
    State("um-edit-target", "data"),
    State("um-edit-email", "value"),
    State("um-edit-first-name", "value"),
    State("um-edit-last-name", "value"),
    State("um-edit-enabled", "value"),
    State("um-edit-roles", "value"),
    State("um-refresh", "data"),
    prevent_initial_call=True,
)
def save_edit(
    _save: int | None,
    target: dict[str, Any] | None,
    email: str | None,
    first_name: str | None,
    last_name: str | None,
    enabled: list[str] | None,
    roles: list[str] | None,
    refresh: int | None,
) -> tuple[Any, Any, Any]:
    """Persist edits to the targeted user."""
    if not target or not target.get("user_id"):
        raise PreventUpdate

    body = {
        "email": email or None,
        "first_name": first_name or None,
        "last_name": last_name or None,
        "enabled": "enabled" in (enabled or []),
        "roles": roles or [],
    }
    try:
        api_client.patch(f"/api/v1/admin/users/{target['user_id']}", json=body)
    except (AuthExpiredError, PermissionDeniedError) as exc:
        return True, handle_api_error(exc, _ACTION, current_path=_CURRENT_PATH), no_update
    except ApiError as exc:
        return True, _feedback(f"Update failed: {exc}", "danger"), no_update

    return False, _feedback("User updated.", "success"), (refresh or 0) + 1


@callback(
    Output("um-password-modal", "is_open"),
    Output("um-password-target", "data"),
    Input({"type": "um-row", "action": "password", "user_id": ALL}, "n_clicks"),
    prevent_initial_call=True,
)
def open_password_modal(_clicks: list[int | None]) -> tuple[bool, Any]:
    """Open the password modal for the clicked user."""
    triggered = callback_context.triggered_id
    if not isinstance(triggered, dict) or not any(n for n in _clicks):
        raise PreventUpdate
    return True, {"user_id": triggered.get("user_id")}


@callback(
    Output("um-password-modal", "is_open", allow_duplicate=True),
    Input("um-password-cancel", "n_clicks"),
    prevent_initial_call=True,
)
def cancel_password(_n: int | None) -> bool:
    """Close the password modal without saving."""
    return False


@callback(
    Output("um-password-modal", "is_open", allow_duplicate=True),
    Output("um-feedback", "children", allow_duplicate=True),
    Input("um-password-save", "n_clicks"),
    State("um-password-target", "data"),
    State("um-password-value", "value"),
    State("um-password-temporary", "value"),
    prevent_initial_call=True,
)
def save_password(
    _save: int | None,
    target: dict[str, Any] | None,
    password: str | None,
    temporary: list[str] | None,
) -> tuple[Any, Any]:
    """Reset the targeted user's password."""
    if not target or not target.get("user_id"):
        raise PreventUpdate

    try:
        api_client.put(
            f"/api/v1/admin/users/{target['user_id']}/password",
            json={"password": password or "", "temporary": "temporary" in (temporary or [])},
        )
    except (AuthExpiredError, PermissionDeniedError) as exc:
        return True, handle_api_error(exc, _ACTION, current_path=_CURRENT_PATH)
    except ApiError as exc:
        return True, _feedback(exc.message, "danger")

    return False, _feedback("Password reset.", "success")


@callback(
    Output("um-delete-confirm", "displayed"),
    Output("um-pending-delete", "data"),
    Input({"type": "um-row", "action": "delete", "user_id": ALL}, "n_clicks"),
    prevent_initial_call=True,
)
def confirm_delete(_clicks: list[int | None]) -> tuple[bool, Any]:
    """Show the delete confirmation and record the pending user."""
    triggered = callback_context.triggered_id
    if not isinstance(triggered, dict) or not any(n for n in _clicks):
        raise PreventUpdate

    user_id = triggered.get("user_id")
    try:
        user = api_client.get_json(f"/api/v1/admin/users/{user_id}")
        username = user.get("username", user_id)
    except ApiError:
        username = user_id
    return True, {"user_id": user_id, "username": username}


@callback(
    Output("um-feedback", "children", allow_duplicate=True),
    Output("um-refresh", "data", allow_duplicate=True),
    Output("um-delete-confirm", "displayed", allow_duplicate=True),
    Input("um-delete-confirm", "submit_n_clicks"),
    State("um-pending-delete", "data"),
    State("um-refresh", "data"),
    prevent_initial_call=True,
)
def execute_delete(
    submit_n_clicks: int | None,
    pending: dict[str, Any] | None,
    refresh: int | None,
) -> tuple[Any, Any, Any]:
    """Delete the pending user and refresh the table."""
    if not submit_n_clicks or not pending or not pending.get("user_id"):
        raise PreventUpdate

    try:
        api_client.delete(f"/api/v1/admin/users/{pending['user_id']}")
    except (AuthExpiredError, PermissionDeniedError) as exc:
        return handle_api_error(exc, _ACTION, current_path=_CURRENT_PATH), no_update, False
    except ApiError as exc:
        return _feedback(f"Delete failed: {exc}", "danger"), no_update, False

    return _feedback("User deleted.", "success"), (refresh or 0) + 1, False


__all__ = ["render_users_page"]

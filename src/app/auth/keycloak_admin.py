"""Keycloak Admin REST client for the API runtime.

The API drives Keycloak's admin surface on an administrator's behalf. It uses a
dedicated `wba-admin-api` client (client-credentials) whose service account
holds realm-management roles; that client carries no `wba-*` realm role and its
id is deliberately absent from `app.auth.tokens._service_client_ids()`, so its
tokens can never authenticate an application request.

The base URL is derived from the internal realm URL setting, never from the
public issuer URL: the admin API is not reachable on the public origin (nginx
404s /auth/admin).
"""

from __future__ import annotations

import threading
import time
from typing import Any

import requests

from app.settings import settings
from common.logger import logger

_REFRESH_MARGIN_SECONDS = 60
_FAILURE_BACKOFF_SECONDS = 30


class KeycloakAdminError(Exception):
    """Base class for every Keycloak admin client failure."""


class KeycloakUnavailableError(KeycloakAdminError):
    """Keycloak's admin API could not be reached or refused us.

    Covers transport failures, 5xx, token-fetch failures, and a 401/403 from the
    admin API — a misconfigured client credential is our fault, not the caller's,
    so it must never surface as a 401 to the browser.
    """


class KeycloakNotFoundError(KeycloakAdminError):
    """The requested Keycloak object does not exist (404)."""


class KeycloakConflictError(KeycloakAdminError):
    """The request conflicts with existing state (409)."""


class KeycloakPolicyError(KeycloakAdminError):
    """Keycloak rejected the request body (400), e.g. a password-policy failure."""


class _TokenState:
    """Mutable process-wide admin token cache guarded by ``lock``."""

    def __init__(self) -> None:
        self.access_token: str | None = None
        self.expires_at: float = 0.0
        self.lock: threading.Lock = threading.Lock()


_state = _TokenState()


def admin_base_url() -> str:
    """Return the realm's admin REST base URL derived from the internal URL."""
    internal = settings.KEYCLOAK_INTERNAL_URL
    if "/realms/" not in internal:
        raise KeycloakUnavailableError(
            "KEYCLOAK_INTERNAL_URL does not contain '/realms/'; cannot derive "
            "the admin base URL."
        )
    return internal.replace("/realms/", "/admin/realms/", 1).rstrip("/")


def _cached_token() -> str | None:
    """Return the cached token when it is still outside the refresh margin."""
    if _state.access_token is not None and time.monotonic() < _state.expires_at:
        return _state.access_token
    return None


def _in_failure_backoff() -> bool:
    """Return True while a recent fetch failure is still being backed off."""
    return _state.access_token is None and time.monotonic() < _state.expires_at


def _request_token(realm_url: str, client_id: str, client_secret: str) -> tuple[str, float]:
    """Request a fresh admin token and return ``(access_token, expires_at)``."""
    token_url = f"{realm_url.rstrip('/')}/protocol/openid-connect/token"
    try:
        resp = requests.post(
            token_url,
            data={
                "grant_type": "client_credentials",
                "client_id": client_id,
                "client_secret": client_secret,
            },
            timeout=settings.HTTP_REQUEST_TIMEOUT,
        )
    except requests.exceptions.RequestException as exc:
        raise KeycloakUnavailableError(
            f"admin token request failed ({type(exc).__name__})"
        ) from exc

    if resp.status_code != 200:
        raise KeycloakUnavailableError(
            f"admin token endpoint returned status {resp.status_code}"
        )

    try:
        payload: Any = resp.json()
    except ValueError as exc:
        raise KeycloakUnavailableError("admin token endpoint returned a non-JSON body") from exc

    if not isinstance(payload, dict) or not payload.get("access_token"):
        raise KeycloakUnavailableError("admin token response did not contain an access_token")

    expires_in = payload.get("expires_in")
    if not isinstance(expires_in, (int, float)):
        raise KeycloakUnavailableError("admin token response did not contain a numeric expires_in")

    return (
        str(payload["access_token"]),
        time.monotonic() + float(expires_in) - _REFRESH_MARGIN_SECONDS,
    )


def _admin_token() -> str:
    """Return a cached, unexpired admin access token.

    Raises:
        KeycloakUnavailableError: when no secret is configured, the token
            endpoint fails, or a recent failure is still within its backoff.
    """
    token = _cached_token()
    if token is not None:
        return token
    if _in_failure_backoff():
        raise KeycloakUnavailableError("admin token fetch failed recently; backing off")

    with _state.lock:
        token = _cached_token()
        if token is not None:
            return token
        if _in_failure_backoff():
            raise KeycloakUnavailableError("admin token fetch failed recently; backing off")

        client_id = settings.KEYCLOAK_ADMIN_CLIENT_ID
        client_secret = settings.KEYCLOAK_ADMIN_CLIENT_SECRET
        if not client_secret:
            raise KeycloakUnavailableError(
                f"KEYCLOAK_ADMIN_CLIENT_SECRET is not set for client_id={client_id}"
            )

        try:
            token, expires_at = _request_token(
                settings.KEYCLOAK_INTERNAL_URL, client_id, client_secret
            )
        except KeycloakUnavailableError as exc:
            logger.warning(f"Failed to fetch Keycloak admin token for client_id={client_id}: {exc}")
            _state.access_token = None
            _state.expires_at = time.monotonic() + _FAILURE_BACKOFF_SECONDS
            raise

        _state.access_token = token
        _state.expires_at = expires_at
        return token


def invalidate_admin_token() -> None:
    """Discard the cached token and failure backoff, so the next call re-fetches."""
    with _state.lock:
        _state.access_token = None
        _state.expires_at = 0.0


def _request(
    method: str,
    path: str,
    *,
    params: dict[str, Any] | None = None,
    json_body: Any = None,
) -> requests.Response:
    """Perform one admin REST call, mapping status codes to our exception types."""
    token = _admin_token()
    url = f"{admin_base_url()}{path}"
    logger.info(f"Keycloak admin request method={method} path={path}")

    try:
        resp = requests.request(
            method,
            url,
            params=params,
            json=json_body,
            headers={"Authorization": f"Bearer {token}"},
            timeout=settings.HTTP_REQUEST_TIMEOUT,
        )
    except requests.exceptions.RequestException as exc:
        raise KeycloakUnavailableError(
            f"admin request failed ({type(exc).__name__})"
        ) from exc

    if resp.status_code in (401, 403):
        raise KeycloakUnavailableError(
            f"admin API refused the service account (status {resp.status_code})"
        )
    if resp.status_code == 404:
        raise KeycloakNotFoundError(f"Keycloak returned 404 for {method} {path}")
    if resp.status_code == 409:
        raise KeycloakConflictError(f"Keycloak returned 409 for {method} {path}")
    if resp.status_code == 400:
        raise KeycloakPolicyError(resp.text)
    if resp.status_code >= 500:
        raise KeycloakUnavailableError(
            f"Keycloak returned status {resp.status_code} for {method} {path}"
        )
    if resp.status_code >= 300:
        raise KeycloakAdminError(
            f"Keycloak returned unexpected status {resp.status_code} for {method} {path}"
        )
    return resp


def list_users(offset: int, limit: int, search: str | None) -> tuple[list[dict[str, object]], int]:
    """Return one page of users plus Keycloak's total count for the same filter."""
    params: dict[str, Any] = {
        "first": offset,
        "max": limit,
        "briefRepresentation": "false",
    }
    if search:
        params["search"] = search
    resp = _request("GET", "/users", params=params)
    users = resp.json()

    count_params: dict[str, Any] = {}
    if search:
        count_params["search"] = search
    count_resp = _request("GET", "/users/count", params=count_params or None)
    count = int(count_resp.json())
    return list(users), count


def count_users(search: str | None) -> int:
    """Return Keycloak's user count for *search* (service accounts included)."""
    count_params: dict[str, Any] = {}
    if search:
        count_params["search"] = search
    count_resp = _request("GET", "/users/count", params=count_params or None)
    return int(count_resp.json())


def get_user(user_id: str) -> dict[str, object]:
    """Return one user representation."""
    return dict(_request("GET", f"/users/{user_id}").json())


def create_user(payload: dict[str, object]) -> str:
    """Create a user and return its id parsed from the ``Location`` header."""
    resp = _request("POST", "/users", json_body=payload)
    location = resp.headers.get("Location", "")
    return location.rstrip("/").rsplit("/", 1)[-1]


def update_user(user_id: str, payload: dict[str, object]) -> None:
    """Update a user's representation."""
    _request("PUT", f"/users/{user_id}", json_body=payload)


def delete_user(user_id: str) -> None:
    """Delete a user."""
    _request("DELETE", f"/users/{user_id}")


def set_password(user_id: str, password: str, temporary: bool) -> None:
    """Set a user's password, optionally requiring a change at first login."""
    _request(
        "PUT",
        f"/users/{user_id}/reset-password",
        json_body={"type": "password", "value": password, "temporary": temporary},
    )


def realm_roles(user_id: str) -> list[str]:
    """Return the names of the realm roles assigned to a user."""
    resp = _request("GET", f"/users/{user_id}/role-mappings/realm")
    return [str(role["name"]) for role in resp.json()]


def role_definition(role_name: str) -> dict[str, object]:
    """Return the ``{id, name}`` payload a role-mapping endpoint requires."""
    return dict(_request("GET", f"/roles/{role_name}").json())


def assign_realm_roles(user_id: str, role_names: list[str]) -> None:
    """Assign realm roles (by name) to a user."""
    payload = [role_definition(name) for name in role_names]
    if not payload:
        return
    _request("POST", f"/users/{user_id}/role-mappings/realm", json_body=payload)


def remove_realm_roles(user_id: str, role_names: list[str]) -> None:
    """Remove realm roles (by name) from a user."""
    payload = [role_definition(name) for name in role_names]
    if not payload:
        return
    _request("DELETE", f"/users/{user_id}/role-mappings/realm", json_body=payload)


def users_with_role(role_name: str) -> list[dict[str, object]]:
    """Return every user holding *role_name*."""
    resp = _request("GET", f"/roles/{role_name}/users")
    return list(resp.json())

"""The UI runtime's single HTTP client for the API.

Every UI → API call goes through here, so the UI owns the base URL and the
timeout **once** rather than restating them at each call site:

* the base URL is :attr:`UISettings.API_BASE_URL` (the container-internal
  ``http://api:8000`` after the split), so call sites pass a **path**;
* the timeout is read per call from ``ui.runtime_settings`` — never frozen at
  import, which is the bug class Step 6a fixed across the UI.

On any non-2xx the client raises **one** type, :class:`ApiError`, carrying the
status and the response's parsed ``detail``. It deliberately does **not** raise
domain types: a generic client used by every UI→API call site must not inherit
a taxonomy from one page's domain, and Step 10's single-type contract (the basis
for Plan C's 401-redirect / 403-banner split) requires exactly one exception.
The collaboration pages translate ``ApiError`` into the exceptions their own
``except`` blocks catch — see ``ui.collaboration_params.translate_api_error``.

A request that never reaches the API (connection refused, DNS failure, timeout)
also raises :class:`ApiError`, with ``status_code`` :data:`STATUS_NO_RESPONSE`.
Callers that only display the failure can ignore the distinction; a caller that
needs the HTTP status reads ``exc.status_code``.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import requests
from requests import RequestException as RequestsTransportError

from ui.auth import SessionMissingError, TokenExchangeUnavailableError, get_token
from ui.runtime_settings import runtime_settings
from ui.settings import settings

__all__ = [
    "ApiError",
    "STATUS_NO_RESPONSE",
    "delete",
    "get",
    "get_json",
    "patch",
    "post",
    "post_json",
    "put",
    "set_transport",
]

#: ``ApiError.status_code`` when no HTTP response was received at all (a
#: connection error or a timeout). No real HTTP status is 0, so it cannot be
#: confused with a response from the API.
STATUS_NO_RESPONSE = 0

#: The transport seam's type: ``requests.request``-compatible.
Transport = Callable[..., requests.Response]

_transport: Transport | None = None


class ApiError(Exception):
    """A non-2xx response from the API — the UI client's single error type.

    Args:
        status_code: The HTTP status the API returned, or
            :data:`STATUS_NO_RESPONSE` when the request did not complete.
        detail: The response's parsed ``detail`` field, when it was JSON.
        detail_error: ``detail["error"]`` — the short discriminator a caller
            (e.g. the collaboration pages' translation) switches on.
        message: A human-readable message, from ``detail["message"]`` when
            present, else the raw body.
    """

    def __init__(
        self,
        status_code: int,
        *,
        detail: Any = None,
        detail_error: str | None = None,
        message: str | None = None,
    ) -> None:
        self.status_code = status_code
        self.detail = detail
        self.detail_error = detail_error
        self.message = message or f"API request failed with status {status_code}"
        super().__init__(self.message)


def set_transport(transport: Transport | None) -> None:
    """Install a transport callable, or restore ``requests.request``.

    Tests point this at a stub instead of monkeypatching the ``requests``
    module globally; with 47 test files touching the UI, global patching is how
    stub leaks happen. Pass ``None`` to restore the real transport.
    """
    global _transport  # pylint: disable=global-statement
    _transport = transport


def _describe(response: requests.Response) -> ApiError:
    """Build an :class:`ApiError` from a non-2xx *response*, parsing its detail."""
    try:
        payload = response.json()
    except ValueError:
        payload = None

    detail = payload.get("detail") if isinstance(payload, dict) else None
    if isinstance(detail, dict):
        return ApiError(
            response.status_code,
            detail=detail,
            detail_error=detail.get("error"),
            message=detail.get("message") or response.text,
        )
    # A plain-string ``detail`` is the human-readable reason; prefer it over the
    # raw body so call sites keep the message they showed before the migration.
    if isinstance(detail, str) and detail:
        return ApiError(response.status_code, detail=detail, message=detail)
    # FastAPI's own validation failures carry a *list* detail (422); the body is
    # still worth surfacing, so fall back to the raw text.
    return ApiError(
        response.status_code,
        detail=detail,
        message=response.text or None,
    )


def _call(
    method: str,
    path: str,
    *,
    params: dict[str, Any] | None = None,
    json_body: dict[str, Any] | None = None,
) -> requests.Response:
    """Perform one API request through the current transport.

    *path* is joined onto :attr:`UISettings.API_BASE_URL`; the timeout is read
    from the runtime-settings cache per call, never at import. A transport
    failure (no HTTP response) is raised as an :class:`ApiError` so callers
    have one exception type to catch. Tests swap the transport with
    :func:`set_transport` rather than monkeypatching ``requests`` globally.
    """
    url = settings.API_BASE_URL.rstrip("/") + path
    transport = _transport or requests.request

    headers: dict[str, str] = {}
    try:
        headers["Authorization"] = f"Bearer {get_token()}"
    except (SessionMissingError, TokenExchangeUnavailableError):
        # No session (tests, or an unauthenticated surface) — send without one.
        # Plan 057 makes the API require it; until then this degrades exactly as
        # today, so a missing cookie never masks a real API error.
        pass

    request_kwargs: dict[str, Any] = {
        "params": params,
        "json": json_body,
        "timeout": runtime_settings.get_int("HTTP_REQUEST_TIMEOUT"),
    }
    # Omitting the key entirely when there is no token keeps the request byte-for
    # -byte identical to the pre-auth client on an unauthenticated surface.
    if headers:
        request_kwargs["headers"] = headers

    try:
        return transport(method, url, **request_kwargs)
    except RequestsTransportError as exc:
        raise ApiError(STATUS_NO_RESPONSE, message=str(exc)) from exc


def _request(
    method: str,
    path: str,
    *,
    params: dict[str, Any] | None = None,
    json_body: dict[str, Any] | None = None,
) -> requests.Response:
    """Perform one request and raise :class:`ApiError` on any non-2xx."""
    response = _call(method, path, params=params, json_body=json_body)
    if not response.ok:
        raise _describe(response)
    return response


def get(path: str, *, params: dict[str, Any] | None = None) -> requests.Response:
    """GET *path*; raise :class:`ApiError` on any non-2xx."""
    return _request("GET", path, params=params)


def post(
    path: str,
    *,
    json: dict[str, Any] | None = None,
    params: dict[str, Any] | None = None,
) -> requests.Response:
    """POST *json* to *path*; raise :class:`ApiError` on any non-2xx."""
    return _request("POST", path, params=params, json_body=json)


def put(
    path: str,
    *,
    json: dict[str, Any] | None = None,
    params: dict[str, Any] | None = None,
) -> requests.Response:
    """PUT *json* to *path*; raise :class:`ApiError` on any non-2xx."""
    return _request("PUT", path, params=params, json_body=json)


def patch(
    path: str,
    *,
    json: dict[str, Any] | None = None,
    params: dict[str, Any] | None = None,
) -> requests.Response:
    """PATCH *path* with *json*; raise :class:`ApiError` on any non-2xx."""
    return _request("PATCH", path, params=params, json_body=json)


def delete(path: str, *, params: dict[str, Any] | None = None) -> requests.Response:
    """DELETE *path*; raise :class:`ApiError` on any non-2xx."""
    return _request("DELETE", path, params=params)


def get_json(path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    """GET *path* and return the parsed JSON body.

    Raises:
        ApiError: On any non-2xx response.
    """
    return get(path, params=params).json()


def post_json(path: str, json: dict[str, Any] | None = None) -> dict[str, Any]:
    """POST *json* to *path* and return the parsed JSON body.

    Raises:
        ApiError: On any non-2xx response.
    """
    return post(path, json=json).json()

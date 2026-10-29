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

Extended in Step 10 with the remaining UI→API call sites; Step 7 introduces it
with ``get_json`` / ``post_json`` and the three bypass swaps.
"""

from __future__ import annotations

from typing import Any

import requests

from ui.runtime_settings import runtime_settings
from ui.settings import settings

__all__ = ["ApiError", "get_json", "post_json"]


class ApiError(Exception):
    """A non-2xx response from the API — the UI client's single error type.

    Args:
        status_code: The HTTP status the API returned.
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
    """Perform one API request. The single transport seam — tests replace this.

    *path* is joined onto :attr:`UISettings.API_BASE_URL`; the timeout is read
    from the runtime-settings cache per call, never at import.
    """
    url = settings.API_BASE_URL.rstrip("/") + path
    return requests.request(
        method,
        url,
        params=params,
        json=json_body,
        timeout=runtime_settings.get_int("HTTP_REQUEST_TIMEOUT"),
    )


def get_json(path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    """GET *path* and return the parsed JSON body.

    Raises:
        ApiError: On any non-2xx response.
    """
    response = _call("GET", path, params=params)
    if not response.ok:
        raise _describe(response)
    return response.json()


def post_json(path: str, json: dict[str, Any] | None = None) -> dict[str, Any]:
    """POST *json* to *path* and return the parsed JSON body.

    Raises:
        ApiError: On any non-2xx response.
    """
    response = _call("POST", path, json_body=json)
    if not response.ok:
        raise _describe(response)
    return response.json()

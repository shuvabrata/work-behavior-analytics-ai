"""The UI's session guard — one probed redirect for a dead session.

The API is the authority on whether a session is real. The UI cannot read the
session row, so it asks the API once per page navigation instead:

* cookie **absent** → a document navigation gets a 302 to the login flow; a Dash
  callback gets a 401 JSON body, because Dash parses the response as JSON and an
  HTML login page would surface as an unreadable parse error.
* cookie **present** → the request is let through, except that a document
  navigation first probes ``GET /api/v1/auth/me``. A 401 means the session row is
  gone (revoked, expired, or the token exchange is failing), so the guard clears
  the cookie and 302s to login — the page is never rendered with no identity and
  no way back in. A 403 (a role-less but valid session) and a transport failure
  both let the request through; the latter is what stops an API outage from
  becoming a login loop.

Static assets and the two initial-render endpoints are exempt. Blocking
``/app/_dash-layout`` or ``/app/_dash-dependencies`` yields a blank page rather
than a login redirect, and blocking ``/app/assets/*`` leaves the login page
unstyled.
"""

from __future__ import annotations

from flask import Flask, Response, jsonify, request

from common.logger import logger
from ui import api_client
from ui.auth import SESSION_COOKIE_NAME, current_session_id

#: Paths served before a session exists. ``/app/assets/`` is Dash's static
#: directory; the two ``_dash-*`` endpoints are fetched during initial render.
_EXEMPT_PREFIXES = ("/app/assets/",)

#: Endpoints Dash fetches to build the page. Exempt so a logged-out browser can
#: still render the shell that sits behind the redirect.
_EXEMPT_EXACT = ("/app/_dash-layout", "/app/_dash-dependencies")

#: Where the guard sends a logged-out navigation. The API's login route.
_LOGIN_PATH = "/api/v1/auth/login"

#: The API route the guard probes with the held cookie.
_ME_PATH = "/api/v1/auth/me"


def _is_exempt(path: str) -> bool:
    """Return whether *path* is served without a session."""
    if path.startswith(_EXEMPT_PREFIXES):
        return True
    return path.rstrip("/") in {p.rstrip("/") for p in _EXEMPT_EXACT}


def _is_dash_xhr() -> bool:
    """Return whether this request is a Dash callback rather than a navigation.

    Dash's fetch does not always set ``X-Requested-With``, so a path under
    ``/app/_dash-`` is treated as a callback too. A plain ``GET`` to a page path
    is a browser navigation and must redirect.
    """
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return True
    return request.path.startswith("/app/_dash-")


def _unauthenticated_response() -> Response:
    """Redirect a navigation to login; return a 401 JSON body for a callback."""
    if request.method == "GET" and not _is_dash_xhr():
        target = f"{_LOGIN_PATH}?next={request.path}"
        logger.info(f"Session guard: redirecting logged-out navigation to login (path={request.path!r})")
        return Response(status=302, headers={"Location": target})
    return jsonify({"detail": {"error": "unauthenticated"}}), 401


def _session_is_rejected() -> bool:
    """Return whether the API refuses the cookie we hold.

    Only called when a cookie is present, so the common authenticated path is
    one cheap ``/auth/me`` call per *navigation* — never per asset or callback.

    A 401 is taken as proof the session is gone; a 403 means the session is
    valid but the principal lacks a role, and a transport failure means the API
    could not be reached — neither is proof, so both let the request through.
    """
    try:
        api_client.get(_ME_PATH)
    except api_client.AuthExpiredError:
        return True
    except api_client.ApiError:
        return False
    return False


def _clear_session_cookie(response: Response) -> Response:
    """Expire the ``wba_session`` cookie on *response* so the probe cannot loop."""
    response.delete_cookie(SESSION_COOKIE_NAME, path="/")
    return response


def session_guard() -> Response | None:
    """Return a response when the request has no session, else ``None``.

    Called from the UI's single ``before_request`` hook. Returning ``None`` lets
    Flask continue to the view; returning a response short-circuits it.
    """
    if _is_exempt(request.path):
        return None
    if not current_session_id():
        return _unauthenticated_response()
    if request.method == "GET" and not _is_dash_xhr() and _session_is_rejected():
        logger.info(f"Session guard: the API refused the held cookie (path={request.path!r})")
        return _clear_session_cookie(_unauthenticated_response())
    return None


def register_session_guard(server: Flask) -> None:
    """Install the guard on *server*.

    Kept as its own registration function so the hook can be tested in isolation
    from request logging, but ``request_logging.register_request_logging`` is the
    one caller — a single ``before_request`` is simpler to reason about than two.
    """
    server.before_request(session_guard)


__all__ = ["register_session_guard", "session_guard"]

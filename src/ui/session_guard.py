"""The UI's session guard — stay out of the way of assets, redirect everything else.

The API is the authority on whether a session is real; the UI only knows whether
a ``wba_session`` cookie is *present*. That asymmetry is deliberate and keeps the
guard free of DB access and of any duplicated validation logic:

* cookie **present** → let the request through. If the row is gone, the first
  API call returns 401 and plan 058 turns that into a redirect. Validating here
  would either duplicate the API's rules or require a store the UI does not have.
* cookie **absent** → a document navigation gets a 302 to the login flow; a Dash
  callback gets a 401 JSON body, because Dash parses the response as JSON and an
  HTML login page would surface as an unreadable parse error.

Static assets and the two initial-render endpoints are exempt. Blocking
``/app/_dash-layout`` or ``/app/_dash-dependencies`` yields a blank page rather
than a login redirect, and blocking ``/app/assets/*`` leaves the login page
unstyled.
"""

from __future__ import annotations

from flask import Flask, Response, jsonify, request

from common.logger import logger
from ui.auth import current_session_id

#: Paths served before a session exists. ``/app/assets/`` is Dash's static
#: directory; the two ``_dash-*`` endpoints are fetched during initial render.
_EXEMPT_PREFIXES = ("/app/assets/",)

#: Endpoints Dash fetches to build the page. Exempt so a logged-out browser can
#: still render the shell that sits behind the redirect.
_EXEMPT_EXACT = ("/app/_dash-layout", "/app/_dash-dependencies")

#: Where the guard sends a logged-out navigation. The API's login route.
_LOGIN_PATH = "/api/v1/auth/login"


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


def session_guard() -> Response | None:
    """Return a response when the request has no session, else ``None``.

    Called from the UI's single ``before_request`` hook. Returning ``None`` lets
    Flask continue to the view; returning a response short-circuits it.
    """
    if _is_exempt(request.path):
        return None
    if current_session_id():
        return None
    return _unauthenticated_response()


def register_session_guard(server: Flask) -> None:
    """Install the guard on *server*.

    Kept as its own registration function so the hook can be tested in isolation
    from request logging, but ``request_logging.register_request_logging`` is the
    one caller — a single ``before_request`` is simpler to reason about than two.
    """
    server.before_request(session_guard)


__all__ = ["register_session_guard", "session_guard"]

"""The two auth outcomes a page has to render, and the redirect wiring.

A Dash callback cannot issue an HTTP redirect, and the UI client deliberately
raises one error type (:class:`ui.api_client.ApiError`) so all 49 existing
``ApiError`` handlers keep working. This module is the single place that turns
the two *auth* subclasses into user-visible behaviour:

* :func:`handle_api_error` — what a page's handler calls once it has caught
  ``AuthExpiredError`` / ``PermissionDeniedError``. Anything else is re-raised so
  the page's own ``ApiError`` clause keeps its current message.
* :func:`register_auth_redirect` / :func:`set_auth_redirect` — the callback path
  for a 401. A ``dcc.Store`` write drives a clientside callback that sets a
  ``dcc.Location``'s ``href``, which the browser follows as a top-level
  navigation (needed: the login flow has to reach Keycloak).

**Placement is deliberate — do not move the Dash wiring into ``ui.auth``.**
``ui.auth`` imports no Dash and must not import ``ui.api_client`` (an import
cycle), so a ``clientside_callback`` registration cannot live there. Only the
pure string helper ``ui.auth.login_url`` is shared between the two paths, and
that is where the ``next=`` encoding is owned.
"""

from __future__ import annotations

from typing import Any

from dash import Input, Output, set_props
from dash import no_update
from dash import Dash

from ui.api_client import ApiError, AuthExpiredError, PermissionDeniedError
from ui.auth import login_url
from ui.components.common import create_permission_denied_alert

#: The store a 401 handler writes, and the location the clientside callback
#: moves. Both are mounted once, in ``ui.layout``'s app shell.
AUTH_REDIRECT_STORE_ID = "auth-redirect"
AUTH_REDIRECT_LOCATION_ID = "auth-redirect-location"


def set_auth_redirect(path: str) -> None:
    """Ask the browser to navigate to the login URL for *path*.

    The store write is batched into the callback's response, so this works from
    any callback without the caller having to declare the store as an ``Output``.
    """
    set_props(AUTH_REDIRECT_STORE_ID, {"data": login_url(path)})


def register_auth_redirect(app: Dash) -> None:
    """Wire the redirect store to the location component on *app*."""
    app.clientside_callback(  # type: ignore[no-untyped-call]
        """
        function(target) {
            if (!target) {
                return window.dash_clientside.no_update;
            }
            return target;
        }
        """,
        Output(AUTH_REDIRECT_LOCATION_ID, "href"),
        Input(AUTH_REDIRECT_STORE_ID, "data"),
        prevent_initial_call=True,
    )


def handle_api_error(exc: ApiError, action: str, *, current_path: str | None = None) -> Any:
    """Return the UI element(s) for *exc*, or re-raise for the caller to handle.

    - ``AuthExpiredError`` -> schedule a login redirect, return ``no_update``.
    - ``PermissionDeniedError`` -> the permission alert for *action*.
    - anything else -> re-raise, so the page's existing handler keeps its
      current behaviour.

    The re-raise is the contract: a page opts into the two auth cases without
    losing its own timeout/validation/no-data messages, which stay in its
    ``ApiError`` clause below the new one.

    The caller must map this result into its own return shape — several handlers
    return a tuple of many outputs, and ``no_update`` has to be expanded to every
    slot. See the plan's Part E return-shape rule.
    """
    if isinstance(exc, AuthExpiredError):
        set_auth_redirect(current_path or "/app/")
        return no_update
    if isinstance(exc, PermissionDeniedError):
        return create_permission_denied_alert(action)
    raise exc


__all__ = [
    "AUTH_REDIRECT_LOCATION_ID",
    "AUTH_REDIRECT_STORE_ID",
    "handle_api_error",
    "register_auth_redirect",
    "set_auth_redirect",
]

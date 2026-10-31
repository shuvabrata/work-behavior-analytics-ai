"""The account bar — who is signed in, and a way out.

The browser must not call the API, so the identity is populated by a **Python**
callback that goes through ``ui.api_client`` (and therefore carries the bearer
token the BFF mints from the session cookie). Nothing here reads or renders a
token.

Logout is a plain HTML form POST to ``/api/v1/auth/logout``. That is the
simplest thing that works: the endpoint accepts ``POST`` and answers with a 302
to Keycloak's ``end_session_endpoint``, and a native form submit gives the
top-level navigation that redirect needs — a ``dcc.Location`` update would issue
a ``GET`` the endpoint does not accept. No ``ConfirmDialog``: signing out is not
destructive data loss, so the repo's ConfirmDialog rule does not apply.

A missing account bar is not user-facing breakage: on ``ApiError`` this renders
nothing rather than an error, and the render is driven off the URL so it
reappears on the next navigation once the session is back.
"""

from __future__ import annotations

from typing import Any

import dash_bootstrap_components as dbc
from dash import Input, Output, callback, html

from ui import api_client
from ui.api_client import ApiError
from ui.styles import (
    COLOR_GRAY_MEDIUM,
    FONT_SANS,
    FONT_SIZE_SMALL,
    FONT_SIZE_XSMALL,
    FONT_WEIGHT_MEDIUM,
)

#: The container the callback fills in.
ACCOUNT_BAR_ID = "account-bar"

#: The API route that revokes the session and redirects to Keycloak.
_LOGOUT_URL = "/api/v1/auth/logout"


def get_account_bar_layout() -> html.Div:
    """Return the account-bar container, populated by its callback on navigation."""
    return html.Div(id=ACCOUNT_BAR_ID, style={"display": "flex", "alignItems": "center"})


def _account_children(payload: dict[str, Any]) -> list[Any]:
    """Build the bar's contents from a ``/auth/me`` payload."""
    username = payload.get("username") or ""
    return [
        html.Span(
            username,
            style={
                "fontFamily": FONT_SANS,
                "fontSize": FONT_SIZE_SMALL,
                "fontWeight": FONT_WEIGHT_MEDIUM,
                "color": COLOR_GRAY_MEDIUM,
            },
        ),
        html.Form(
            method="post",
            action=_LOGOUT_URL,
            children=[
                dbc.Button(
                    "Sign out",
                    type="submit",
                    color="light",
                    outline=True,
                    size="sm",
                    className="ms-2",
                    style={"fontFamily": FONT_SANS, "fontSize": FONT_SIZE_XSMALL},
                )
            ],
            style={"margin": 0, "padding": 0},
        ),
    ]


@callback(
    Output(ACCOUNT_BAR_ID, "children"),
    Input("url", "pathname"),
)
def render_account_bar(_pathname: str | None) -> Any:
    """Fetch the caller's identity and render the bar, or nothing on failure."""
    try:
        payload = api_client.get_json("/api/v1/auth/me")
    except ApiError:
        # Unauthenticated or unreachable: render nothing. The account bar is a
        # convenience, never a user-facing error surface.
        return None

    if not isinstance(payload, dict) or not payload.get("username"):
        return None
    return _account_children(payload)


__all__ = ["ACCOUNT_BAR_ID", "get_account_bar_layout", "render_account_bar"]

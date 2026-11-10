"""The account menu — who is signed in, and a way out.

The browser must not call the API, so the identity is populated by a **Python**
callback that goes through ``ui.api_client`` (and therefore carries the bearer
token the BFF mints from the session cookie). Nothing here reads or renders a
token.

The top bar carries a single icon-only trigger rather than a username span plus
a boxed button, so the identity lives one click away instead of occupying
horizontal space. The popup holds the username, the provider's full name when it
supplies one, and **Sign out**.

Logout is a plain HTML form POST to ``/api/v1/auth/logout``. That is the
simplest thing that works: the endpoint accepts ``POST`` and answers with a 302
to Keycloak's ``end_session_endpoint``, and a native form submit gives the
top-level navigation that redirect needs — a ``dcc.Location`` update would issue
a ``GET`` the endpoint does not accept. Because an ``<a>`` can only issue a
``GET``, the menu's logout entry is an ``html.Form`` wrapping a submit button,
not a ``DropdownMenuItem`` carrying ``href``. No ``ConfirmDialog``: signing out
is not destructive data loss, so the repo's ConfirmDialog rule does not apply.

A missing account menu is not user-facing breakage for unrelated failures: a
transport error or a role-less session renders nothing, and the render is driven
off the URL so it reappears on the next navigation once the session is back. A
*dead* session (401) is different — it must offer the way back in, or the user is
left on a rendered page with no identity and no in-app route to login. The
``AuthExpiredError`` branch renders a **Sign in** link in the slot the account
menu occupies.
"""

from __future__ import annotations

from typing import Any

import dash_bootstrap_components as dbc
from dash import Input, Output, callback, html

from ui import api_client
from ui.api_client import ApiError, AuthExpiredError
from ui.auth import login_url
from ui.styles import (
    COLOR_CHARCOAL,
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

#: Scoping class for the menu's theme rules; no other dropdown is affected.
_MENU_CLASS = "account-menu"


def get_account_bar_layout() -> html.Div:
    """Return the account-bar container, populated by its callback on navigation."""
    return html.Div(id=ACCOUNT_BAR_ID, style={"display": "flex", "alignItems": "center"})


def _account_menu(payload: dict[str, Any]) -> Any:
    """Build the account menu from a ``/auth/me`` payload."""
    username = str(payload.get("username") or "")
    full_name = payload.get("full_name")

    identity: list[Any] = [
        html.Div(
            username,
            style={
                "fontFamily": FONT_SANS,
                "fontSize": FONT_SIZE_SMALL,
                "fontWeight": FONT_WEIGHT_MEDIUM,
                "color": COLOR_CHARCOAL,
            },
        )
    ]
    if isinstance(full_name, str) and full_name:
        identity.append(
            html.Div(
                full_name,
                style={
                    "fontFamily": FONT_SANS,
                    "fontSize": FONT_SIZE_XSMALL,
                    "color": COLOR_GRAY_MEDIUM,
                },
            )
        )

    return dbc.DropdownMenu(
        label=html.Div(
            [
                html.I(className="fas fa-user-circle", title="Account menu"),
                html.Span("Account menu", className="visually-hidden"),
            ]
        ),
        caret=False,
        align_end=True,
        class_name=_MENU_CLASS,
        toggle_class_name="account-menu-toggle",
        children=[
            html.Div(identity, className="account-menu-header"),
            dbc.DropdownMenuItem(divider=True),
            html.Form(
                method="post",
                action=_LOGOUT_URL,
                children=[
                    html.Button(
                        "Sign out",
                        type="submit",
                        className="dropdown-item",
                    )
                ],
                style={"margin": 0, "padding": 0},
            ),
        ],
    )


def _account_children(payload: dict[str, Any]) -> list[Any]:
    """Build the bar's contents from a ``/auth/me`` payload."""
    return [_account_menu(payload)]


def _signed_out_children(pathname: str | None) -> list[Any]:
    """Return the Sign in control for a dead session.

    A plain ``<a>`` rather than a ``dcc.Location`` update: the login flow needs
    a top-level navigation to reach Keycloak. Styled from the same tokens as the
    Sign out button so the pair reads as a pair.
    """
    return [
        html.A(
            "Sign in",
            href=login_url(pathname or "/app/"),
            className="ms-2",
            style={
                "fontFamily": FONT_SANS,
                "fontSize": FONT_SIZE_XSMALL,
                "color": COLOR_GRAY_MEDIUM,
            },
        )
    ]


@callback(
    Output(ACCOUNT_BAR_ID, "children"),
    Input("url", "pathname"),
)
def render_account_bar(_pathname: str | None) -> Any:
    """Fetch the caller's identity and render the bar, or nothing on failure."""
    try:
        payload = api_client.get_json("/api/v1/auth/me")
    except AuthExpiredError:
        # The session is gone: offer the way back in, in the slot the Sign out
        # control occupies. Previously this returned nothing, which left no
        # in-app route to login.
        return _signed_out_children(_pathname)
    except ApiError:
        # Unreachable API or any other failure: render nothing, as before. A
        # transport error must not advertise a login the user may not need.
        return None

    if not isinstance(payload, dict) or not payload.get("username"):
        return None
    return _account_children(payload)


__all__ = ["ACCOUNT_BAR_ID", "get_account_bar_layout", "render_account_bar"]

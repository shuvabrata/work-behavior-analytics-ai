"""Pydantic models for the auth API.

The response shapes the browser and the Dash BFF depend on:

* :class:`LoginRedirect` — where to send the browser and what cookie to set.
* :class:`LoginResult` — the outcome of a completed callback.
* :class:`TokenResponse` — the BFF's bearer, minted from the session cookie.
* :class:`MeResponse` — the account bar's identity payload.
"""

from __future__ import annotations

from pydantic import BaseModel


class LoginRedirect(BaseModel):
    """A pending login: where to redirect, and the PKCE cookie to set."""

    authorize_url: str
    pkce_cookie_value: str
    next_path: str


class LoginResult(BaseModel):
    """A completed login: the raw session id and where the browser returns to."""

    session_id: str
    next_path: str


class TokenResponse(BaseModel):
    """The BFF token-exchange response — a bearer the UI uses for one call cycle."""

    access_token: str
    token_type: str = "bearer"
    expires_in: int


class MeResponse(BaseModel):
    """The authenticated caller's identity, for the account bar."""

    subject: str
    username: str
    roles: list[str]


__all__ = [
    "LoginRedirect",
    "LoginResult",
    "MeResponse",
    "TokenResponse",
]

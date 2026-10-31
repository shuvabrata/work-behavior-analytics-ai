"""FastAPI router for the auth API — the BFF login flow and token exchange.

Endpoints:

- ``GET /auth/login`` — public; 302 to Keycloak, sets the PKCE cookie.
- ``GET /auth/callback`` — public; validates state, creates the session, sets
  ``wba_session``, clears the PKCE cookie, 302 to ``next``.
- ``POST /auth/logout`` — session cookie; revokes the row, clears the cookie,
  302 to Keycloak's end-session URL.
- ``POST /auth/token`` — session cookie; the BFF exchange, returns a bearer.
- ``GET /auth/me`` — bearer; returns ``{subject, username, roles}``.

``/auth/login`` and ``/auth/callback`` are the only public routes. Everything
else reads the session **cookie** itself (the two BFF paths, which have no
bearer to check) or, for ``/auth/me``, the bearer via ``require_user``. No other
router gains a dependency here — that is plan 057.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth.v1 import service
from app.api.auth.v1.model import MeResponse, TokenResponse
from app.auth.dependencies import require_user
from app.auth.principal import Principal
from app.auth.session_cookie import (
    PKCE_COOKIE_NAME,
    SESSION_COOKIE_NAME,
    cookie_kwargs,
)
from app.db.session import get_async_db

router = APIRouter(prefix="/auth", tags=["auth"])


def _clear_cookie(response: Response, name: str) -> None:
    """Expire a cookie, mirroring the scope it was set with."""
    response.delete_cookie(name, path="/", httponly=True, samesite="lax")


@router.get("/login")
async def login(
    next_path: str | None = Query(default=None, alias="next"),
) -> Response:
    """Begin the OIDC login: redirect to Keycloak with a PKCE challenge."""
    redirect = service.start_login(next_path)
    response = RedirectResponse(url=redirect.authorize_url, status_code=302)
    response.set_cookie(
        PKCE_COOKIE_NAME, redirect.pkce_cookie_value, **cookie_kwargs()  # type: ignore[arg-type]
    )
    return response


@router.get("/callback")
async def callback(
    request: Request,
    code: str = Query(...),
    state: str = Query(...),
    db: AsyncSession = Depends(get_async_db),
) -> Response:
    """Complete the OIDC login and create the server-side session."""
    pkce_cookie = request.cookies.get(PKCE_COOKIE_NAME, "")
    try:
        result = await service.complete_login(
            db, code=code, state=state, pkce_cookie_value=pkce_cookie
        )
    except service.LoginError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "login_failed", "message": str(exc)},
        ) from exc
    except service.TokenExchangeUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error": "token_exchange_unavailable", "message": str(exc)},
        ) from exc

    response = RedirectResponse(url=result.next_path, status_code=302)
    response.set_cookie(
        SESSION_COOKIE_NAME, result.session_id, **cookie_kwargs()  # type: ignore[arg-type]
    )
    _clear_cookie(response, PKCE_COOKIE_NAME)
    return response


@router.post("/logout")
async def logout(
    request: Request,
    db: AsyncSession = Depends(get_async_db),
) -> Response:
    """Revoke the session and redirect to Keycloak's RP-initiated logout."""
    session_id = request.cookies.get(SESSION_COOKIE_NAME)
    end_session_url = await service.logout(db, session_id=session_id)
    response = RedirectResponse(url=end_session_url, status_code=302)
    _clear_cookie(response, SESSION_COOKIE_NAME)
    return response


@router.post("/token", response_model=TokenResponse)
async def token(
    request: Request,
    db: AsyncSession = Depends(get_async_db),
) -> TokenResponse:
    """Exchange the session cookie for a bearer token — the BFF mechanism."""
    session_id = request.cookies.get(SESSION_COOKIE_NAME)
    try:
        return await service.exchange_token(db, session_id=session_id)
    except service.SessionNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "unauthenticated", "message": str(exc)},
        ) from exc
    except service.SessionExpiredError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "session_expired", "message": str(exc)},
        ) from exc
    except service.TokenExchangeUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error": "token_exchange_unavailable", "message": str(exc)},
        ) from exc


@router.get("/me", response_model=MeResponse)
async def me(principal: Principal = Depends(require_user)) -> MeResponse:
    """Return the authenticated caller's identity and roles."""
    return MeResponse(
        subject=principal.subject,
        username=principal.username,
        roles=sorted(principal.roles),
    )


__all__ = ["router"]

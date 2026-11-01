"""FastAPI dependencies that resolve and check a Principal.

Nothing wires these into a router yet — plan 057 does that. They are defined
and unit-tested here so enforcement is a one-line change per router rather than
a design decision taken during the switch.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from fastapi import Depends, HTTPException, Request, status

from app.auth.principal import Principal
from app.auth.tokens import (
    NoRecognisedRoleError,
    TokenValidationError,
    validate_bearer_token,
)
from common.logger import logger


def _bearer_token(request: Request) -> str | None:
    """Return the bearer token from ``Authorization``, or ``None``."""
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token:
        return None
    return token


async def get_principal(request: Request) -> Principal:
    """Resolve the caller from ``Authorization: Bearer``.

    Raises:
        HTTPException: 401 when the header is missing or the token is invalid;
            403 when the token is valid but carries no recognised role.
    """
    token = _bearer_token(request)
    if token is None:
        logger.warning(f"Missing bearer credential for path={request.url.path!r}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "missing_credentials", "message": "A bearer token is required."},
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        return validate_bearer_token(token)
    except NoRecognisedRoleError as exc:
        logger.warning(f"No recognised role for path={request.url.path!r}")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": "no_recognised_role", "message": str(exc)},
        ) from exc
    except TokenValidationError as exc:
        logger.warning(f"Invalid bearer credential for path={request.url.path!r}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "invalid_token", "message": str(exc)},
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


async def require_user(principal: Principal = Depends(get_principal)) -> Principal:
    """Require any authenticated principal (user, admin, or service)."""
    return principal


def _require_role(principal: Principal, role: str, path: str) -> Principal:
    """Return *principal* if it carries *role*, else raise a logged 403."""
    if not principal.has_role(role):
        logger.warning(
            f"Access denied for sub={principal.subject!r} "
            f"username={principal.username!r}: requires role={role!r} path={path!r}"
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": "insufficient_role", "message": f"Role {role!r} is required."},
        )
    return principal


async def require_admin(
    request: Request, principal: Principal = Depends(get_principal)
) -> Principal:
    """Require ``wba-admin``; 403 otherwise."""
    return _require_role(principal, "wba-admin", request.url.path)


async def require_service(
    request: Request, principal: Principal = Depends(get_principal)
) -> Principal:
    """Require ``wba-service``; 403 otherwise."""
    return _require_role(principal, "wba-service", request.url.path)


def _internal_role(role: str) -> str:
    """Map a short role label (``"admin"``) to its internal name (``"wba-admin"``)."""
    return role if role.startswith("wba-") else f"wba-{role}"


def require_roles(*roles: str) -> Callable[..., Awaitable[Principal]]:
    """Return a dependency requiring at least one of *roles*; 403 otherwise.

    FastAPI runs every declared dependency, so stacking ``require_admin`` and
    ``require_service`` would demand both roles at once. This factory expresses
    the union they cannot.

    It is a factory rather than a bare ``async def`` because ``Depends`` takes a
    callable, not a call: ``Depends(require_roles("admin", "service"))`` must
    produce the dependency, not a coroutine. The returned dependency is named
    ``require_roles`` so the route-enumeration test can identify it.
    """
    internal = [_internal_role(role) for role in roles]

    async def _dependency(
        request: Request, principal: Principal = Depends(get_principal)
    ) -> Principal:
        if not any(principal.has_role(role) for role in internal):
            logger.warning(
                f"Access denied for sub={principal.subject!r} "
                f"username={principal.username!r}: requires one of roles={sorted(roles)!r} "
                f"path={request.url.path!r}"
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "error": "insufficient_role",
                    "message": f"One of roles {sorted(roles)!r} is required.",
                },
            )
        return principal

    _dependency.__name__ = "require_roles"
    return _dependency

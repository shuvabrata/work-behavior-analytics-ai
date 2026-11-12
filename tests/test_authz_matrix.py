"""Route-enumeration test: the live app must match ``AUTHZ_MATRIX``.

FastAPI 0.161.1 does not flatten ``include_router`` into ``app.routes`` —
``app.routes`` holds ``_IncludedRouter`` wrappers, and ``isinstance(r, APIRoute)``
matches nothing. The enumerator below walks ``inc.original_router.routes``
instead and collects dependencies from the two places they can live: the
include-time ``include_context.dependencies`` (router-level) and
``route.dependant.dependencies`` (route-level).
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.routing import APIRoute

from app.api_main import app
from app.auth.matrix import AUTHZ_MATRIX, Grant

pytestmark = pytest.mark.unit

_BEARER_DEPENDENCIES = frozenset(
    {"require_user", "require_admin", "require_service", "require_roles"}
)


def _dependency_name(dep: object) -> str:
    """Return the callable name for either FastAPI dependency shape.

    Router-level dependencies are ``fastapi.params.Depends`` (``.dependency``);
    route-level ones are ``fastapi.dependencies.models.Dependant`` (``.call``).
    """
    call = getattr(dep, "call", None) or getattr(dep, "dependency", None)
    return getattr(call, "__name__", repr(call))


def api_operations(fastapi_app: FastAPI) -> list[tuple[str, str, list[str]]]:
    """Return (method, full_path, dependency_names) for every API operation."""
    out: list[tuple[str, str, list[str]]] = []
    for inc in fastapi_app.routes:
        if type(inc).__name__ != "_IncludedRouter":
            continue
        ctx = inc.include_context
        level = [_dependency_name(d) for d in ctx.dependencies]
        for route in inc.original_router.routes:
            if not isinstance(route, APIRoute):
                continue
            route_level = [_dependency_name(d) for d in route.dependant.dependencies]
            for method in sorted(route.methods or []):
                out.append((method, (ctx.prefix or "") + route.path, level + route_level))
    return out


def _expected_dependency(grant: Grant) -> str | None:
    """Return the dependency name a declared role requires, or ``None`` for none."""
    if grant == "public" or grant == "session":
        return None
    if grant == "user":
        return "require_user"
    if grant == "admin":
        return "require_admin"
    if grant == "service":
        return "require_service"
    return "require_roles"


_STRICTER_THAN_USER = frozenset({"require_admin", "require_service", "require_roles"})


def test_enumeration_is_non_empty() -> None:
    """A FastAPI change that stops exposing routes must fail loudly, not pass."""
    assert len(api_operations(app)) == 65


def test_every_operation_is_declared() -> None:
    """A route added later fails loudly instead of defaulting open."""
    live = {(method, path) for method, path, _ in api_operations(app)}
    missing = sorted(live - set(AUTHZ_MATRIX))
    assert not missing, f"operations missing from AUTHZ_MATRIX: {missing}"


def test_every_matrix_row_is_implemented() -> None:
    """No stale AUTHZ_MATRIX rows pointing at routes that no longer exist."""
    live = {(method, path) for method, path, _ in api_operations(app)}
    stale = sorted(set(AUTHZ_MATRIX) - live)
    assert not stale, f"AUTHZ_MATRIX rows with no live operation: {stale}"


def test_declared_role_matches_effective_dependencies() -> None:
    """Each operation's attached dependencies match its declared role.

    The ``"user"`` exemption is exact, not a lower bound: a route declared
    ``"user"`` must carry ``require_user`` and **no** stricter dependency, so
    loosening a matrix row is caught rather than silently satisfied by the
    router-level default.
    """
    mismatches: list[str] = []
    for method, path, deps in api_operations(app):
        grant = AUTHZ_MATRIX[(method, path)]
        expected = _expected_dependency(grant)
        present = _BEARER_DEPENDENCIES.intersection(deps)
        if expected is None:
            if present:
                mismatches.append(f"{method} {path}: expected no bearer dep, got {sorted(present)}")
        elif expected == "require_user":
            stricter = present & _STRICTER_THAN_USER
            if "require_user" not in deps or stricter:
                mismatches.append(f"{method} {path}: expected require_user alone, got {deps}")
        elif expected not in deps:
            mismatches.append(f"{method} {path}: expected {expected}, got {deps}")
    assert not mismatches, "\n".join(mismatches)


def test_public_paths_are_exactly_the_allowlist() -> None:
    public = {key for key, grant in AUTHZ_MATRIX.items() if grant == "public"}
    assert public == {
        ("GET", "/api/health"),
        ("GET", "/api/v1/auth/login"),
        ("GET", "/api/v1/auth/callback"),
    }


def test_session_paths_are_exactly_the_cookie_flow() -> None:
    session = {key for key, grant in AUTHZ_MATRIX.items() if grant == "session"}
    assert session == {
        ("POST", "/api/v1/auth/token"),
        ("POST", "/api/v1/auth/logout"),
    }

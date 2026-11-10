"""Guard the OpenAPI security scheme that makes Swagger's Authorize box work.

FastAPI emits ``components.securitySchemes`` and a per-operation ``security``
entry only when a route declares a security dependency.  ``get_principal``
declares ``HTTPBearer`` for exactly that reason, so the schema advertises a
bearer credential and ``/docs`` can authenticate its "Try it out" calls.

If a refactor drops that declaration the scheme silently disappears and every
interactive call 401s with no way to supply a token — a failure a unit suite
otherwise would not notice, because enforcement still works.  These tests pin
the schema.
"""

from __future__ import annotations

import pytest

from app.api_main import app
from app.auth.matrix import AUTHZ_MATRIX

pytestmark = pytest.mark.unit

_SCHEME_NAME = "KeycloakBearer"


def _normalise(path: str) -> str:
    """Drop FastAPI's ``:path`` converter suffix so it matches OpenAPI's template.

    ``AUTHZ_MATRIX`` records ``/api/v1/queries/catalog-metadata/{catalog_id:path}``
    while ``app.openapi()`` renders the same route as ``{catalog_id}``.
    """
    return path.replace(":path}", "}")


def test_scheme_is_emitted() -> None:
    """The bearer scheme is present in the generated schema."""
    schemes = app.openapi()["components"]["securitySchemes"]
    assert _SCHEME_NAME in schemes
    scheme = schemes[_SCHEME_NAME]
    assert scheme["type"] == "http"
    assert scheme["scheme"] == "bearer"


def test_every_protected_operation_requires_the_scheme() -> None:
    """Every non-public, non-session operation carries the bearer scheme."""
    spec = app.openapi()
    missing: list[str] = []
    for (method, path), grant in AUTHZ_MATRIX.items():
        if grant == "public" or grant == "session":
            continue
        operation = spec["paths"][_normalise(path)][method.lower()]
        if {"KeycloakBearer": []} not in (operation.get("security") or []):
            missing.append(f"{method} {path}")
    assert not missing, f"operations missing the {_SCHEME_NAME} scheme: {missing}"


def test_health_has_no_security() -> None:
    """``/api/health`` is public — the scheme is per-dependency, not global."""
    operation = app.openapi()["paths"]["/api/health"]["get"]
    assert not operation.get("security")


def test_operation_count_matches_matrix() -> None:
    """The live operation count equals the matrix size — no route silently dropped."""
    spec = app.openapi()
    operations = 0
    for methods in spec["paths"].values():
        operations += sum(
            1
            for method in methods
            if method.lower() in {"get", "post", "put", "patch", "delete", "head", "options"}
        )
    assert operations == len(AUTHZ_MATRIX)

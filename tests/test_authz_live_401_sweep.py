"""Every documented operation must answer ``401`` to an unauthenticated caller.

The route inventory comes from the live ``/openapi.json`` rather than from a
hand-maintained list, so a route added to the app is swept automatically. This is
deliberately stronger than ``tests/test_authz_matrix.py``, which inspects the
*dependencies* attached to each route in-process: a route can carry the right
dependency object and still be reachable if the wiring is defeated at runtime
(a mis-ordered middleware, a route registered directly on ``app``, a dependency
override left installed in a long-lived process). Only a real request proves the
answer.

``/openapi.json`` is the right inventory source precisely because it is generated
from the app's real route table: a route added with ``@app.get`` instead of
``@router.get`` appears here, whereas the ``_IncludedRouter``-walking enumerator
in ``tests/test_authz_matrix.py`` cannot see it.

**The four allowlisted paths are the entire intended unauthenticated surface**:

* ``GET /api/health`` — the liveness probe; must answer without a credential.
* ``GET /api/v1/auth/login`` and ``GET /api/v1/auth/callback`` — the browser
  cannot hold a bearer before these run, so they authenticate by other means
  (the OIDC redirect and the authorization code).
* ``POST /api/v1/auth/logout`` — reads the ``wba_session`` cookie, not a bearer.

They are allowlisted **by path, not by status**: the sweep's job is "901 out of
900 is not 401", and pinning the exact code of each would make this test fail for
reasons unrelated to authorization (a redirect policy change, a Keycloak
restart, a validation-detail change).

**Safety.** While the suite passes it is non-destructive — a ``401`` means the
handler never ran. If a route is ever accidentally opened, the sweep *will*
execute it for real, and two of the operations are destructive
(``POST /api/v1/settings/reset``, ``DELETE /api/v1/connectors/{type}``). That is
why this is ``server``-marked and bound to ``https://localhost``: it is local
Compose traffic, never to be pointed at a shared or production environment.

Reaching the app over HTTPS requires the Compose stack::

    docker compose up -d

Markers: ``integration``, ``server``. Per ``tests/conftest.py``, ``server`` tests
are pointed at the locally issued mkcert CA and **fail rather than skip** when the
stack is down, so a broken proxy is never mistaken for a passing run.

Run with:
    pytest -m "integration and server" tests/test_authz_live_401_sweep.py -v -s
"""

from __future__ import annotations

import re

import httpx
import pytest

pytestmark = [pytest.mark.integration, pytest.mark.server]

BASE_URL = "https://localhost"
TIMEOUT = 20.0

_HTTP_METHODS = frozenset({"get", "post", "put", "patch", "delete"})

#: Operations permitted to answer with something other than 401.
_ALLOWED_WITHOUT_AUTH: frozenset[tuple[str, str]] = frozenset(
    {
        ("GET", "/api/health"),
        ("GET", "/api/v1/auth/login"),
        ("GET", "/api/v1/auth/callback"),
        ("POST", "/api/v1/auth/logout"),
    }
)

#: Path-parameter values, so a templated path becomes a real request. Values are
#: deliberately well-formed but meaningless: authorization runs before any handler
#: would look them up, so a 404 here would itself be a failure worth seeing.
_PARAM_VALUES = {
    "command_id": "00000000-0000-0000-0000-000000000001",
    "item_id": "1",
    "theme_id": "1",
    "connector_type": "github",
    "key": "HTTP_REQUEST_TIMEOUT",
    "namespace": "ns",
    "slug": "slug",
    "catalog_id": "ns/slug",
    "session_id": "probe-session",
}


def _concretise(path_template: str) -> str:
    """Replace ``{param}`` placeholders with concrete values."""
    path = re.sub(r"\{([^}:]+):path\}", r"{\1}", path_template)

    def _substitute(match: re.Match[str]) -> str:
        name = match.group(1)
        return _PARAM_VALUES.get(name, "probe")

    return re.sub(r"\{([^}]+)\}", _substitute, path)


def _openapi_operations() -> list[tuple[str, str]]:
    """Return (method, path template) for every operation in the live app."""
    response = httpx.get(f"{BASE_URL}/openapi.json", timeout=TIMEOUT)
    response.raise_for_status()
    spec = response.json()

    operations: list[tuple[str, str]] = []
    for path, item in spec.get("paths", {}).items():
        for method in item:
            if method.lower() in _HTTP_METHODS:
                operations.append((method.upper(), path))
    return sorted(operations, key=lambda entry: (entry[1], entry[0]))


def test_all_operations_require_authentication(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Every operation except the four known paths answers 401 unauthenticated.

    Prints the full list of non-401 operations before asserting, so a regression
    reports exactly which routes opened rather than only that the set differed.
    """
    operations = _openapi_operations()
    assert operations, "openapi.json exposed no operations — the sweep is vacuous"

    unexpectedly_open: list[tuple[str, str, int]] = []
    for method, path_template in operations:
        if (method, path_template) in _ALLOWED_WITHOUT_AUTH:
            continue
        path = _concretise(path_template)
        response = httpx.request(
            method, f"{BASE_URL}{path}", timeout=TIMEOUT, follow_redirects=False
        )
        if response.status_code != 401:
            unexpectedly_open.append((method, path_template, response.status_code))

    with capsys.disabled():
        print(f"\nSwept {len(operations)} operations from /openapi.json")
        print(f"Allowlisted without authentication: {len(_ALLOWED_WITHOUT_AUTH)}")
        if unexpectedly_open:
            print("\nOPERATIONS NOT RETURNING 401 WITHOUT AUTHENTICATION:")
            for method, path_template, status in unexpectedly_open:
                print(f"   {status}  {method:7} {path_template}")
        else:
            print("All other operations returned 401.")

    detail = "\n".join(
        f"   {status}  {method:7} {path_template}"
        for method, path_template, status in unexpectedly_open
    )
    assert not unexpectedly_open, (
        "These operations answered without a credential. Either they were opened "
        "accidentally, or they belong in _ALLOWED_WITHOUT_AUTH:\n"
        f"{detail}"
    )


def test_the_allowlist_is_exactly_the_declared_surface() -> None:
    """Each allowlisted path is a real operation, so the list cannot go stale."""
    live = set(_openapi_operations())
    stale = sorted(_ALLOWED_WITHOUT_AUTH - live)
    assert not stale, f"allowlisted paths with no live operation: {stale}"


def test_health_is_reachable_without_a_credential() -> None:
    """The liveness probe stays open — a guard cannot require the guard's own auth."""
    response = httpx.get(f"{BASE_URL}/api/health", timeout=TIMEOUT)
    assert response.status_code == 200, (
        f"GET /api/health returned {response.status_code}, not 200. The health "
        f"probe must answer without a credential."
    )

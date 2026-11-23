"""Every GET operation, driven with a real ``app-admin`` and a real ``app-user`` bearer.

The existing live suites each cover one domain (settings, catalog, graph, themes),
and ``tests/test_authz_live_401_sweep.py`` covers who answers ``401`` *without* a
credential. Neither answers the question this file answers: **does a signed-in
administrator actually get a working response from every endpoint the UI needs?**

That question is not academic. A Keycloak patch moved the Admin REST API onto an
audience check supplied by its built-in ``kc-admin-api`` client scope. Nothing in
the realm's role assignments changed — the service account still held
``view-users``/``manage-users``, the token still minted, its claim set was
correct — yet every call to ``/api/v1/admin/users/`` returned ``503``, because
Keycloak answered the underlying admin call with ``401``. The unit suites could
not see it (they stub the Keycloak transport), the ``401`` sweep could not see it
(an endpoint that answers ``401`` to an anonymous caller passes there), and no
live suite touched ``/admin`` at all. One authenticated GET against
``/api/v1/admin/users/`` fails on the spot.

**What is asserted** is the authorization outcome, not the payload, because the
payload depends on what the stack happens to contain:

* No ``401`` for either role, on any route — a minted bearer must be accepted.
* No ``5xx`` for either role — this is exactly how the breakage above surfaced,
  and it is the signature of an upstream dependency failing, not of a request
  being refused.
* ``admin``-granted routes answer ``403`` to ``user``. ``403`` rather than ``401``
  is the point: it distinguishes "the role is enforced" from "the credential was
  rejected", so a regression that broke token validation could not masquerade as
  successful authorization.
* ``user``-granted routes do not answer ``403`` to either role.

A ``404`` or ``422`` from a route whose data does not exist is therefore green: it
still proves the handler was reached and authorized. Two routes are pinned to an
exact ``200`` because they need no id and are the direct regression probes for the
failure above.

**Inventory guard.** ``test_no_get_operation_is_missing_from_this_matrix``
compares the table below against the live ``/openapi.json``, so a newly added GET
operation fails the suite until it appears here with a decided expectation. The
table is hand-written on purpose: the expectation for a new route is a judgement,
not something to be inferred from a schema.

Requires the Compose stack and the ``TEST_SUITE_WBA_*`` credentials::

    docker compose up -d
    pytest -m "integration and server" tests/test_api_get_matrix.py -v

Markers: ``integration``, ``server``, ``authenticated``. Per ``tests/conftest.py``,
``server`` points ``SSL_CERT_FILE`` at the locally issued mkcert CA and the suite
**fails rather than skips** when the stack is down.

**Safety:** every request here is a GET. Nothing in this file mutates state.

**Before blaming this file for a failure:** the suites log in as the seeded
``app-admin`` and ``app-user`` accounts with the ``TEST_SUITE_WBA_*`` values from
``.env``. The realm is imported once, and it renders ``APP_ADMIN_PASSWORD`` /
``APP_USER_PASSWORD`` into the template at that moment as **temporary** first-login
credentials — Keycloak forces a password change the first time each account is used
in a browser, and the new password is never written back to ``.env``. So ``.env``
still holds a password that stopped working the moment someone signed in, which
surfaces here as ``LoginError: Login for 'app-user' did not complete`` and, from
Keycloak, as ``invalid_user_credentials``. Editing ``.env`` after the import does
not reach the realm, and neither restarting Keycloak nor re-seeding is required:
point the account at the current value instead — see the printed note at the start
of this suite's run.
"""

from __future__ import annotations

import httpx
import pytest

from tests.auth_helpers import admin_headers, configured, user_headers

pytestmark = [
    pytest.mark.integration,
    pytest.mark.server,
    pytest.mark.authenticated,
    pytest.mark.skipif(
        not (
            configured("TEST_SUITE_WBA_ADMIN_USERNAME")
            and configured("TEST_SUITE_WBA_ADMIN_PASSWORD")
            and configured("TEST_SUITE_WBA_USER_USERNAME")
            and configured("TEST_SUITE_WBA_USER_PASSWORD")
        ),
        reason="TEST_SUITE_WBA_ADMIN_* / TEST_SUITE_WBA_USER_* are not configured — see INSTALL_GUIDE.md",
    ),
]

BASE_URL = "https://localhost"
TIMEOUT = 30.0

USER_GRANT = "user"
ADMIN_GRANT = "admin"

#: Statuses no route may ever answer, for any authenticated role. ``401`` means a
#: minted bearer was rejected; ``5xx`` means something upstream failed. Neither is
#: an authorization decision, which is what this suite is about.
_NEVER = (401,)

#: Path placeholders, replaced with real ids discovered at session start where a
#: real one is cheap. The fallbacks are what a stack with no data degrades to, and
#: they produce a ``404`` — which every assertion here accepts.
_PARAMS: dict[str, str] = {
    "connector_type": "github",
    "session_id": "probe-session",
    "command_id": "00000000-0000-0000-0000-000000000001",
    "user_id": "probe-user",
    "theme_id": "1",
    "namespace": "github",
    "slug": "probe",
    "catalog_id": "github/probe",
}

#: ``(listing path, path param to fill, field to read off the first listed item)``.
_DISCOVERERS: tuple[tuple[str, str, str], ...] = (
    ("/api/v1/graph-themes/", "theme_id", "id"),
    ("/api/v1/admin/users/", "user_id", "id"),
)

#: Every GET operation the app serves, with its grant copied from
#: ``src/app/auth/matrix.py`` and its required query parameters from the routers.
#: ``/api/health`` and the two ``/auth`` legs are excluded: they are
#: credential-less by design and are covered by ``tests/test_authz_live_401_sweep.py``.
ROUTES: tuple[tuple[str, str, dict[str, str]], ...] = (
    ("/api/v1/activity/suggest", USER_GRANT, {"q": "abc"}),
    ("/api/v1/activity/timeline", USER_GRANT, {"wba_ids": "github::Person::probe"}),
    ("/api/v1/admin/users/", ADMIN_GRANT, {}),
    ("/api/v1/admin/users/roles", ADMIN_GRANT, {}),
    ("/api/v1/admin/users/{user_id}", ADMIN_GRANT, {}),
    ("/api/v1/auth/me", USER_GRANT, {}),
    ("/api/v1/chats/metrics/stream", USER_GRANT, {}),
    ("/api/v1/chats/{session_id}", USER_GRANT, {}),
    ("/api/v1/commands/", USER_GRANT, {}),
    ("/api/v1/commands/{command_id}", USER_GRANT, {}),
    ("/api/v1/connectors/", USER_GRANT, {}),
    ("/api/v1/connectors/{connector_type}", USER_GRANT, {}),
    ("/api/v1/connectors/{connector_type}/configs", USER_GRANT, {}),
    ("/api/v1/graph-themes/", USER_GRANT, {}),
    ("/api/v1/graph-themes/effective", USER_GRANT, {"base_theme": "executive-light"}),
    ("/api/v1/graph-themes/{theme_id}", USER_GRANT, {}),
    ("/api/v1/graph/collaboration-network", USER_GRANT, {}),
    ("/api/v1/graph/collaboration-network/ego", USER_GRANT, {"person": "github::Person::probe"}),
    ("/api/v1/graph/health", USER_GRANT, {}),
    ("/api/v1/queries/catalog", USER_GRANT, {}),
    ("/api/v1/queries/catalog-metadata", USER_GRANT, {}),
    ("/api/v1/queries/catalog-metadata/{catalog_id}", USER_GRANT, {}),
    ("/api/v1/queries/catalog/namespaces", USER_GRANT, {}),
    ("/api/v1/queries/catalog/{namespace}/{slug}", USER_GRANT, {}),
    ("/api/v1/search", USER_GRANT, {}),
    ("/api/v1/search/persons", USER_GRANT, {"q": "a"}),
    ("/api/v1/settings/", USER_GRANT, {}),
    ("/api/v1/settings/runtime-snapshot", USER_GRANT, {}),
)

#: Credential-less by design; swept by ``test_authz_live_401_sweep.py``.
_PUBLIC_PATHS = frozenset({"/api/health", "/api/v1/auth/login", "/api/v1/auth/callback"})

#: Routes pinned to an exact ``200`` for ``admin``. These need no id and no data, so
#: a non-200 is always a real fault — and they are where the Keycloak audience
#: regression landed.
_ADMIN_MUST_BE_200 = frozenset({"/api/v1/admin/users/", "/api/v1/admin/users/roles"})


def _concretise(path_template: str) -> str:
    """Return *path_template* with every ``{param}`` replaced by a real value."""
    path = path_template
    for name, value in _PARAMS.items():
        path = path.replace(f"{{{name}:path}}", value).replace(f"{{{name}}}", value)
    return path


#: The reminder printed once per run, before any request goes out.
_CREDENTIAL_NOTE = """
==============================================================================
 Credentials: this suite logs in as the seeded app-admin and app-user accounts
 using TEST_SUITE_WBA_ADMIN_PASSWORD / TEST_SUITE_WBA_USER_PASSWORD from .env.

 Both accounts are seeded with a TEMPORARY first-login password. The first real
 browser login at https://localhost/app forces a password change, and the new
 password is NOT written back to .env — so .env keeps the superseded seeded
 value and every login here fails with:
     LoginError: Login for 'app-user' did not complete
 and, in Keycloak's log, error="invalid_user_credentials".

 A wrong .env password is by far the most likely cause of a failure in this
 file. Check it before suspecting the app: confirm both TEST_SUITE_WBA_*_PASSWORD
 values match the passwords you chose at first login, and that both accounts
 have been logged into at least once.

 No restart and no re-seed is needed to correct it — the realm is only imported
 on first boot against an empty database, so editing .env never reaches it.
==============================================================================
"""


def _discover(client: httpx.Client, path: str, param: str, field_name: str) -> None:
    """Refine ``_PARAMS[param]`` from the first item of a live listing.

    Best-effort: an empty stack is a legitimate state, and a discovery failure must
    leave the fallback in place rather than raise during fixture setup, which would
    report a data problem as a test error.
    """
    try:
        resp = client.get(path)
        if resp.status_code != 200:
            return
        payload = resp.json()
        items = payload if isinstance(payload, list) else payload.get("users") or []
        first = items[0] if items else None
        if isinstance(first, dict) and first.get(field_name) is not None:
            _PARAMS[param] = str(first[field_name])
    except Exception:  # noqa: BLE001 — discovery must never break the suite
        return


@pytest.fixture(scope="session", autouse=True)
def _resolve_path_params() -> None:
    """Announce the credential prerequisite, then resolve real ids from the stack.

    The note goes to stdout rather than into a failure message because it is most
    useful *before* anything fails — by the time a login error appears, the cause is
    usually already obvious from Keycloak's ``invalid_user_credentials``.
    """
    print(_CREDENTIAL_NOTE, flush=True)
    with httpx.Client(base_url=BASE_URL, timeout=TIMEOUT, headers=admin_headers()) as client:
        for path, param, field_name in _DISCOVERERS:
            _discover(client, path, param, field_name)


@pytest.mark.parametrize(("path", "grant", "params"), ROUTES, ids=[r[0] for r in ROUTES])
def test_admin_bearer_is_accepted(path: str, grant: str, params: dict[str, str]) -> None:
    """``app-admin`` must never be refused or meet a broken upstream.

    A ``401`` means the realm rejected a bearer it just minted; a ``5xx`` means a
    dependency failed. Either breaks the admin UI, and neither is an authorization
    decision. Data-dependent ``404``/``422`` are accepted.
    """
    assert grant in (USER_GRANT, ADMIN_GRANT), f"unknown grant {grant!r} for {path}"
    url = _concretise(path)
    with httpx.Client(base_url=BASE_URL, timeout=TIMEOUT, headers=admin_headers()) as client:
        resp = client.get(url, params=params)

    if path in _ADMIN_MUST_BE_200:
        assert resp.status_code == 200, (
            f"admin GET {url} returned {resp.status_code}, not 200. This route needs no "
            f"data, so a non-200 is a real fault. Body: {resp.text[:300]}"
        )
        return

    assert resp.status_code not in _NEVER, (
        f"admin GET {url} returned {resp.status_code} — a freshly minted admin bearer "
        f"was rejected. Body: {resp.text[:300]}"
    )
    assert resp.status_code < 500, (
        f"admin GET {url} returned {resp.status_code}. A 5xx here is how an upstream "
        f"failure surfaces (a rejected Keycloak admin token becomes 503). "
        f"Body: {resp.text[:300]}"
    )


@pytest.mark.parametrize(("path", "grant", "params"), ROUTES, ids=[r[0] for r in ROUTES])
def test_user_bearer_is_accepted(path: str, grant: str, params: dict[str, str]) -> None:
    """``app-user`` must be accepted by every route, refused only by role.

    On a ``user``-granted route a ``403`` would mean the role model is wrong. On an
    ``admin``-granted route a ``403`` is the correct answer and is asserted to be
    ``403`` specifically — not ``401`` — so an authenticating principal is never
    confused with a rejected one.
    """
    url = _concretise(path)
    with httpx.Client(base_url=BASE_URL, timeout=TIMEOUT, headers=user_headers()) as client:
        resp = client.get(url, params=params)

    assert resp.status_code not in _NEVER, (
        f"user GET {url} returned {resp.status_code} — a freshly minted user bearer was "
        f"rejected. Body: {resp.text[:300]}"
    )
    assert resp.status_code < 500, (
        f"user GET {url} returned {resp.status_code}. Body: {resp.text[:300]}"
    )

    if grant == ADMIN_GRANT:
        assert resp.status_code == 403, (
            f"user GET {url} returned {resp.status_code}, expected 403. An admin-only "
            f"route must refuse a standard user by role (403), not by credential (401) "
            f"or by opening the route. Body: {resp.text[:300]}"
        )
    else:
        assert resp.status_code != 403, (
            f"user GET {url} returned 403 on a route granted '{grant}'. "
            f"Body: {resp.text[:300]}"
        )


def test_admin_users_list_returns_users() -> None:
    """The regression probe, asserted on the payload rather than only the status.

    A ``200`` carrying an empty or malformed body would still leave the page
    broken, so this reads the field the UI renders.
    """
    with httpx.Client(base_url=BASE_URL, timeout=TIMEOUT, headers=admin_headers()) as client:
        resp = client.get("/api/v1/admin/users/")

    assert resp.status_code == 200, (
        f"GET /api/v1/admin/users/ returned {resp.status_code}, not 200. This is the call "
        f"the Settings -> User Management page makes; a 503 here means the Keycloak admin "
        f"token was refused. Body: {resp.text[:300]}"
    )
    payload = resp.json()
    assert "users" in payload, f"no 'users' key in the response: {str(payload)[:300]}"
    assert isinstance(payload["users"], list)
    assert payload["users"], (
        "the users list is empty — the realm should always hold the seeded "
        "app-admin and app-user, so an empty list means the listing is broken"
    )


def test_no_get_operation_is_missing_from_this_matrix() -> None:
    """Fail when the app grows a GET route this file has no expectation for.

    The inventory comes from the live ``/openapi.json``, which is generated from
    the real route table, so a route added with ``@app.get`` is caught too.
    """
    response = httpx.get(f"{BASE_URL}/openapi.json", timeout=TIMEOUT)
    response.raise_for_status()
    spec = response.json()

    live = {
        path
        for path, item in spec.get("paths", {}).items()
        for method in item
        if method.lower() == "get" and path not in _PUBLIC_PATHS
    }
    covered = {path for path, _, _ in ROUTES}

    missing = sorted(live - covered)
    stale = sorted(covered - live)

    assert not missing, (
        "These GET operations are served by the app but absent from ROUTES in this "
        "file. Add each with its grant from src/app/auth/matrix.py:\n"
        + "\n".join(f"   {p}" for p in missing)
    )
    assert not stale, (
        "These entries in ROUTES have no live operation — the route was removed or "
        "renamed, so the table is stale:\n" + "\n".join(f"   {p}" for p in stale)
    )


def test_the_credential_less_paths_are_excluded_deliberately() -> None:
    """Guard the exclusion list: every excluded path must really have no bearer."""
    response = httpx.get(f"{BASE_URL}/openapi.json", timeout=TIMEOUT)
    response.raise_for_status()
    live = set(response.json().get("paths", {}))
    unknown = sorted(_PUBLIC_PATHS - live)
    assert not unknown, f"excluded paths with no live operation: {unknown}"

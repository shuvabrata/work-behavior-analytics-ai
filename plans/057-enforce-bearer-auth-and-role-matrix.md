# Plan 057: Enforce bearer authentication and the role matrix on every `/api/v1` route

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving on. If
> anything in "STOP conditions" occurs, stop and report — do not improvise.
> When done, update the status row in `plans/README.md`.
>
> **Every step ends with a MANUAL GATE.** Hand back to the operator and wait for
> `PASS`. A `FAIL` is a STOP condition.
>
> **Drift check (run first)**: `git diff --stat 225d3639..HEAD -- src/app/api_main.py src/app/api/ </*>/v1/router.py src/app/auth/ tests/conftest.py src/app/api/connectors/v1/service.py`
> Any mismatch against "Current state" is a STOP condition.

## Status

- **Priority**: P1
- **Effort**: L
- **Risk**: HIGH
- **Depends on**: plans/056
- **Category**: security
- **Planned at**: commit `225d3639`, 2026-10-30
- **Design reference**: `docs/design/authn-authz-design.md`, "Endpoint matrix",
  "Enforcement points", "Testing Strategy"
- **This is step 5 of 9** in the Plan C sequence.

## Why this matters

**This is the switch.** Until now the API accepted unauthenticated requests;
after this plan every route under `/api/v1` requires a bearer token carrying a
recognised role, except the two auth-flow endpoints and the health probe. The UI
already sends tokens (plan 056) and the producers already use service tokens
(plan 055), so the switch should be invisible to both — the gate is what proves
it.

Two structural properties make it safe to add a route later:

1. **Authentication is on by default.** Every `/api/v1` router is included with
   a router-level dependency, so a new route is authenticated unless it is
   deliberately exempted.
2. **A central `AUTHZ_MATRIX` table, plus a test that enumerates every route**,
   means a route that declares the wrong role — or no role at all — fails CI.
   The design calls this "the single highest-value test in the change".

What improves when this lands: a forged request from a standard user receives
`403`; an unauthenticated request receives `401`; connector secrets require
`wba-admin`; scans require `wba-admin`; and the categorization is no longer a
convention anyone can forget.

## Current state

**`src/app/api_main.py:180-190`** — routers are included **with no dependency**:

```python
app.include_router(endpoints.router, prefix="/api")
app.include_router(chats_v1_router, prefix="/api/v1")
app.include_router(graph_v1_router, prefix="/api/v1")
app.include_router(connectors_v1_router, prefix="/api/v1")
app.include_router(queries_v1_router, prefix="/api/v1")
app.include_router(search_v1_router, prefix="/api/v1")
app.include_router(persons_v1_router, prefix="/api/v1")
app.include_router(commands_v1_router, prefix="/api/v1")
app.include_router(settings_v1_router, prefix="/api/v1")
app.include_router(graph_themes_v1_router, prefix="/api/v1")
app.include_router(activity_v1_router, prefix="/api/v1")
```

There is an auth router from plan 056 included alongside them.

**`src/app/auth/dependencies.py`** (plan 054) provides `get_principal`,
`require_user`, `require_admin`, `require_service`. The only current consumer is
`/api/v1/auth/me`.

**`src/app/api/connectors/v1/router.py`** — `include_secrets` is a plain query
parameter on two routes. The TODO at `~line 107`:

```python
    # TODO: This should be based on user permissions, not an explicit query parameter.
    include_secrets: bool = False,
```

and the service carries two matching TODOs at `service.py:409-411` and
`:477-479`.

**`src/app/api/settings/v1/router.py`** — `GET /settings/runtime-snapshot` is
currently unrestricted; the design's matrix marks it service-only, which is
**wrong for this codebase** (see the decision table below).

**`tests/conftest.py`** — currently has one autouse fixture (timeline mock) and
a CA helper. There is no principal override.

**`tests/test_activity_api_integration.py:280`** — the repo's established idiom:
`app.dependency_overrides[get_async_db] = ...`.

**Baseline**: `pytest -m unit tests -q` → 2391 passed + plans 054-056's tests.

### Decisions already taken (do not re-litigate)

| Subject | Decision |
|---|---|
| Service role | `wba-service` gets exactly **four** endpoints: `GET /commands/`, `GET /commands/{id}`, `PATCH /commands/{id}/status`, `GET /settings/runtime-snapshot`. Every other row is ✗ for service. |
| Runtime snapshot | **Promoted** from service-only to user+admin+service. The UI needs it to show correct configuration and holds no service credential. |
| `include_secrets` | Keep the query parameter; make it admin-only **at the router**, and delete the three TODOs. |
| Themes | Read = user; authoring and `/set-default` = **admin-only** (the `subject` column is Plan D's). |
| Scans | `POST /commands/` = admin only (a scan writes into the graph). |
| Service accounts | No service role on any read endpoint other than the snapshot. |
| Session-cookie exception | Exactly two paths: `/api/v1/auth/token`, `/api/v1/auth/logout`. |

### Repo conventions that apply

- Router = HTTP only; no business logic.
- `Depends` is the established mechanism; `app.dependency_overrides` is the test idiom.
- Every new function needs full annotations; `mypy src/` is strict.
- Tests carry a marker; unmarked tests are silently skipped.
- Do **not** commit or push unless asked.

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Unit tests | `pytest -m unit tests -q` | ≥ baseline, 0 fail |
| Typecheck | `mypy src/` | exit 0 |
| Lint | `pylint src --score=y` | ≥ 9.0 |
| Security scan | `bandit -c .bandit.yml -r src/ -lll` | exit 0 |
| Rebuild | `docker compose up -d --build api ui signal-consumer` | healthy |
| Unauthenticated call | `curl -s -o /dev/null -w '%{http_code}' https://localhost/api/v1/search?q=x` | `401` |
| Health stays public | `curl -sf https://localhost/api/health` | `{"status":"healthy"}` |
| Route count | `docker compose exec -T api python -c "import json,urllib.request; print(len(json.load(urllib.request.urlopen('http://localhost:8000/openapi.json'))['paths']))"` | the pre-plan count **plus** the auth routes |

## Scope

**In scope**:
- `src/app/auth/matrix.py` (create) — `AUTHZ_MATRIX` and the `guard(...)` helper.
- `src/app/api_main.py` — router-level dependencies and per-router role wiring.
- Every `src/app/api/*/v1/router.py` — add role dependencies per the matrix.
- `src/app/api/connectors/v1/router.py` + `service.py` — gate `include_secrets`, delete three TODOs.
- `tests/conftest.py` — the autouse principal override.
- `tests/test_authz_matrix.py` (create) — the route-enumeration test.
- `tests/test_authz_enforcement.py` (create) — per-role enforcement for representative routes.
- `tests/test_auth_allowlist.py` (create) — the two cookie paths are exactly two.
- `tests/test_connectors_secrets_gating.py` (create)

**Out of scope** (do NOT touch):
- Per-user ownership of chats and favourites — that is plan **058**, which
  follows this one.
- UI 401/403 behaviour — plan 059.
- `graph_themes` schema — Plan D.
- The `/auth/*` handlers themselves (plan 056) except to confirm their
  exemption.
- `/api/health` — stays public.
- API docs routes — deliberately public (decision below).

## Steps

### Step 1: The declarative authorization matrix

Create `src/app/auth/matrix.py`. A single table is the one place the whole
authorization model is readable, and the test asserts the implementation matches
it.

Shape (adapt names, keep the semantics):

```python
"""The single declarative authorization table for the API.

Every route's required role is declared here and applied by ``guard``. The
route-enumeration test asserts each (method, path) in ``app.routes`` appears in
this table with the declared role actually attached, so a new route without a
declaration fails CI rather than defaulting open.
"""

from __future__ import annotations

from typing import Literal

from fastapi import Depends

from app.auth.dependencies import require_admin, require_service, require_user

Role = Literal["user", "admin", "service", "public"]

# (http method, path template) -> required role.
AUTHZ_MATRIX: dict[tuple[str, str], Role] = {
    # ── public ──────────────────────────────────────────────────────────
    ("GET", "/api/health"): "public",
    ("GET", "/api/v1/auth/login"): "public",
    ("GET", "/api/v1/auth/callback"): "public",
    # ── session-cookie authenticated (the two exceptions) ───────────────
    ("POST", "/api/v1/auth/logout"): "user",
    ("POST", "/api/v1/auth/token"): "user",
    # ── any authenticated principal ──────────────────────────────────────
    ("GET", "/api/v1/auth/me"): "user",
    # search
    ("GET", "/api/v1/search"): "user",
    ("POST", "/api/v1/search/scoped"): "user",
    ("GET", "/api/v1/search/persons"): "user",
    # ... one entry per route, for every router ...
    # ── admin-only ───────────────────────────────────────────────────────
    ("POST", "/api/v1/commands/"): "admin",
    # ── service ──────────────────────────────────────────────────────────
    ("GET", "/api/v1/commands/"): "service",
    ("GET", "/api/v1/commands/{command_id}"): "service",
    ("PATCH", "/api/v1/commands/{command_id}/status"): "service",
    ("GET", "/api/v1/settings/runtime-snapshot"): "service",
}


def guard(method: str, path: str) -> list[Depends]:
    """Return the dependency list for one route, from ``AUTHZ_MATRIX``."""
    ...
```

**A route may carry more than one role.** `POST /commands/` is admin **and**
service (the producer's scan trigger does not exist today, but the matrix grants
service on the four listed routes only — reconcile against the real call sites
in Step 4, do not guess). Model this as `Role | frozenset[Role]`, and make
`guard` return the matching `require_*` dependencies. If a route allows several
roles, the simplest correct shape is a `require_any(*roles)` dependency —
**create it in `dependencies.py`** rather than stacking two `require_*` (stacking
requires *both*).

**Generate the table from the code, then review it.** After Step 2, run the
enumeration script in Step 3; it will list every route. Fill the table from
that list, then classify each entry against the design's matrix. This ordering
prevents missing a route.

**Verify**: `PYTHONPATH=src python -c "from app.auth.matrix import AUTHZ_MATRIX; print(len(AUTHZ_MATRIX))"` → a number > 0
**Verify**: `mypy src/app/auth/` → exit 0

> ### 🚦 MANUAL GATE 1 — matrix
>
> Operator reads the table and confirms each row against the design's endpoint
> matrix, and that the four service rows are exactly the four call sites.
> Wait for `PASS`.

---

### Step 2: Apply router-level authentication and per-route roles

Two changes, in this order.

**2a — default authentication per router.** In `src/app/api_main.py`, give every
`/api/v1` router that is not public a router-level dependency. The clean way is
to change the `include_router` calls:

```python
app.include_router(chats_v1_router, prefix="/api/v1", dependencies=[Depends(require_user)])
```

Do this for `chats`, `graph`, `connectors`, `queries`, `search`, `persons`,
`commands`, `settings`, `graph_themes`, `activity`. **Not** for the auth router
(it declares its own per-route roles) and **not** for `endpoints` (`/api/health`
is public).

**2b — narrower roles per route.** Router-level `require_user` authenticates
every request; a route that needs more declares an additional dependency in its
own decorator, e.g.

```python
@router.post("/", dependencies=[Depends(require_admin)], response_model=...)
```

**The `dependencies=[...]` form is required** — it keeps the router HTTP-only and
avoids adding unused parameters to handler signatures. Do **not** thread
`principal: Principal = Depends(...)` into handlers that do not use it; that
fails pylint and adds noise.

Apply, per the decision table:

| Router | Router-level | Per-route extra |
|---|---|---|
| `chats` | `require_user` | none |
| `graph` | `require_user` | none |
| `search` | `require_user` | none |
| `persons` | `require_user` | none |
| `activity` | `require_user` | none |
| `queries` | `require_user` | `PUT/DELETE /catalog/{ns}/{slug}` → `require_admin`; `PUT /catalog-metadata/{id}` stays user (own rows — enforced in plan 058) |
| `graph_themes` | `require_user` | all writes, `/clone`, `/set-default` → `require_admin` |
| `connectors` | `require_user` | all writes, `/test`, and `include_secrets=true` → `require_admin` |
| `settings` | `require_user` | all PATCH/POST → `require_admin`; runtime-snapshot → see Step 4 |
| `commands` | `require_user` | `POST /` → `require_admin`; the four service routes → `require_any("service", "admin")` |

**Verify**: `grep -c "dependencies=\[Depends(require_user)\]" src/app/api_main.py` → `10`
**Verify**: `grep -rn "Depends(require_" src/app/api/*/v1/router.py | wc -l` → matches the table (record the number)
**Verify**: `mypy src/` → exit 0
**Verify**: `pylint src --score=y` → ≥ 9.0

> ### 🚦 MANUAL GATE 2 — wiring
>
> Operator confirms every router is authenticated by default and that the
> per-route extras match the decision table.
> Wait for `PASS`.

---

### Step 3: The route-enumeration test (the highest-value test)

Create `tests/test_authz_matrix.py` (`pytestmark = pytest.mark.unit`). It must:

1. Enumerate `app.routes`, keep only `APIRoute` entries whose path starts with
   `/api`, and build `(method, path)` pairs (expanding FastAPI's `methods` set).
2. **Fail for any route absent from `AUTHZ_MATRIX`**, printing the missing
   `(method, path)` — the "a route added later fails loudly" property.
3. **Fail for any matrix entry that no route implements** (a stale entry).
4. **Fail when a route's attached dependencies do not match its declared role.**
   Inspect `route.dependant.dependencies` (FastAPI exposes it) for the
   `require_*` callables and compare with `AUTHZ_MATRIX`. Handle router-level and
   route-level dependencies uniformly (both appear in `dependant.dependencies`).
5. Assert the **public** set is exactly `{GET /api/health, GET
   /api/v1/auth/login, GET /api/v1/auth/callback}` plus the docs routes if
   FastAPI's defaults are in `app.routes`.

If introspection proves awkward for (4), the acceptable fallback is to assert
that each route **has at least one** `require_*` dependency (except public
ones), and to test the specific role assignments for a representative subset in
`tests/test_authz_enforcement.py`. **Do not** drop the "route absent from the
matrix fails" assertion — that is the property that matters most.

**Verify**: `pytest -m unit tests/test_authz_matrix.py -q` → passes
**Verify**: deliberately add a throwaway route to a router, run the test, see it
fail, then **remove the route** → proves the test is not vacuous

> ### 🚦 MANUAL GATE 3 — matrix test
>
> Operator confirms the executor performed the deliberate-break check above and
> that the test fails on a new undeclared route.
> Wait for `PASS`.

---

### Step 4: Two overrides to the matrix

**4a — runtime snapshot becomes user-readable.** It is currently service-only in
the design. Change it to allow `user`, `admin`, and `service`
(`require_any("user", "admin", "service")` at the route, or simply move it under
the settings router's `require_user` and **also** accept a service token — the
service token's principal carries `wba-service`, which `require_user` does
**not** accept). Use `require_any` and make the matrix entry reflect it.

**4b — `include_secrets` becomes admin-only.** In
`src/app/api/connectors/v1/router.py`, both routes that take `include_secrets`
must reject `true` for a non-admin. Because it is a query parameter and not a
separate route, implement it as an explicit check, not a dependency:

```python
async def _reject_secret_exposure_for_non_admin(
    include_secrets: bool,
    principal: Principal = Depends(require_user),
) -> None:
    """403 when a non-admin asks for connector secrets."""
    if include_secrets and not principal.is_admin:
        logger.warning(
            "403 denied: connector secrets requested by non-admin "
            f"subject={principal.subject} username={principal.username} path={request.url.path}"
        )
        raise HTTPException(status_code=403, detail={"error": "forbidden",
            "message": "Exposing connector secrets requires the wba-admin role."})
```

Add it as a route dependency. **Delete** the three TODOs
(`service.py:409-411`, `service.py:477-479`, `router.py:107`) — they are now
satisfied, and leaving them is a lie in the code.

**Verify**: `curl -s -o /dev/null -w '%{http_code}' 'https://localhost/api/v1/connectors/github/configs?include_secrets=true'` → `401` unauthenticated (proves auth) — then with a user token `403` and an admin token `200` in Gate 6
**Verify**: `grep -c "TODO.*include_secrets\|include_secrets.*TODO" src/app/api/connectors/v1/service.py src/app/api/connectors/v1/router.py` → `0`
**Verify**: `grep -c "This should be based on user permissions" src/app/api/connectors/v1/router.py` → `0`
**Verify**: `mypy src/` → exit 0

> ### 🚦 MANUAL GATE 4 — overrides
>
> Operator confirms the snapshot is readable by all three roles and that the
> three TODOs are gone (not merely edited).
> Wait for `PASS`.

---

### Step 5: The autouse principal override in `tests/conftest.py`

Add to `tests/conftest.py`:

```python
@pytest.fixture(autouse=True)
def _admin_principal_by_default():
    """Authenticate every API test as an admin unless it opts out.

    Enforcement lives in FastAPI dependencies, so one override covers the ~22
    files that drive the real app through httpx.ASGITransport. Auth-specific
    tests remove this override and sign real tokens instead (see
    tests/test_authz_enforcement.py).
    """
    from app.api_main import app
    from app.auth.dependencies import get_principal
    from app.auth.principal import Principal

    app.dependency_overrides[get_principal] = lambda: Principal(
        subject="test-admin", username="test-admin",
        roles=frozenset({"wba-admin", "wba-user"}),
    )
    yield
    app.dependency_overrides.pop(get_principal, None)
```

**Critical**: tests that assert 401/403 must **clear this override** in the test
body (`app.dependency_overrides.clear()` or `pop`). Add a helper fixture
`unauthenticated` for that, so the pattern is obvious and repeated correctly.

**Important**: the override replaces `get_principal`, so `require_user`,
`require_admin`, and `require_service` all see the same principal. A test that
needs a *user* principal must override `get_principal` to a user, not merely
leave the default (which is an admin and would pass an admin check).

**Verify**: `pytest -m unit tests -q` → ≥ baseline, 0 fail (the override is what
keeps existing API tests green)
**Verify**: `grep -c "_admin_principal_by_default" tests/conftest.py` → `1`

> ### 🚦 MANUAL GATE 5 — test fixture
>
> Operator confirms no existing test file was edited to make it pass — the
> override alone covers them. If a test had to change, that is a signal to
> investigate, not a normal edit.
> Wait for `PASS`.

---

### Step 6: Enforcement tests for each role

Create `tests/test_authz_enforcement.py` (`pytestmark = pytest.mark.unit`).
Drive the real `app` through `httpx.ASGITransport`, clearing the autouse
override and overriding `get_principal` per case.

Parametrized cases, for representative routes (at least one per router):

| Route | none | user | admin | service |
|---|---|---|---|---|
| `GET /api/v1/search?q=x` | 401 | 200 | 200 | **403** |
| `GET /api/v1/settings/` | 401 | 200 | 200 | 403 |
| `PATCH /api/v1/settings/{key}` | 401 | **403** | 200 | 403 |
| `POST /api/v1/commands/` | 401 | **403** | 201 | 403 |
| `GET /api/v1/commands/` | 401 | 403 | 200 | **200** |
| `PATCH /api/v1/commands/{id}/status` | 401 | 403 | 200 | **200** |
| `GET /api/v1/settings/runtime-snapshot` | 401 | **200** | 200 | **200** |
| `GET /api/v1/connectors/github/configs?include_secrets=true` | 401 | **403** | 200 | 403 |
| `PUT /api/v1/queries/catalog/{ns}/{slug}` | 401 | **403** | 200 | 403 |
| `POST /api/v1/graph_themes/{id}/set-default` | 401 | **403** | 200 | 403 |
| `GET /api/health` | **200** | 200 | 200 | 200 |

Use a valid-but-fake UUID where a path takes one. Where a `200`/`201` would
depend on data, assert **not 401/403** instead of a specific success status, and
stub the DB with `get_async_db` overrides as the existing tests do.

Create `tests/test_auth_allowlist.py`:
- Enumerate every path under `/api`, and assert the set of paths that can be
  reached **without** a bearer is exactly
  `{/api/health, /api/v1/auth/login, /api/v1/auth/callback}`.
- Assert the set of paths that read the `wba_session` cookie is exactly
  `{/api/v1/auth/token, /api/v1/auth/logout}`. Implement the check by grepping
  the source for `wba_session` under `src/app/api/` and asserting the file/set —
  a static assertion is acceptable and honest here, but say so in a docstring.

Create `tests/test_connectors_secrets_gating.py`:
- admin token + `include_secrets=true` → the response includes secret material
  (assert the field differs from the masked value `_mask_secret_ui` produces).
- user token + `include_secrets=true` → 403 and the log line names the subject.
- user token + no parameter → 200 and no secret material.

**Verify**: `pytest -m unit tests/test_authz_enforcement.py tests/test_auth_allowlist.py tests/test_connectors_secrets_gating.py -q` → all pass
**Verify**: `pytest -m unit tests -q` → ≥ baseline + new, 0 fail
**Verify**: `mypy src/` and `pylint src --score=y` and `bandit -c .bandit.yml -r src/ -lll` → all clean

> ### 🚦 MANUAL GATE 6 — enforcement matrix
>
> Operator confirms the table above passes **row by row**, and that a
> deliberately wrong matrix entry (e.g. mark `POST /commands/` as `user`) makes
> a test fail — then restore it.
> Wait for `PASS`.

---

### Step 7: Full-stack smoke — the switch is invisible to legitimate callers

Rebuild and run the real services. This is where a missed router or a service
token that is not attached shows up as a broken page.

**Verify**:
```bash
docker compose up -d --build api ui signal-consumer github-producer
docker compose run --rm github-producer || true   # one-shot; capture output
```
→ the producer logs a successful `GET /api/v1/commands/` (no 401), and a scan
command can be created as an admin.

**Verify**: `curl -s -o /dev/null -w '%{http_code}' https://localhost/api/v1/search?q=x` → `401`
**Verify**: `curl -sf https://localhost/api/health` → healthy

> ### 🚦 MANUAL GATE 7 — live switch (browser + producers, mandatory)
>
> Operator verifies:
> 1. **Every page works when logged in as `dev-user`**: Chat, Search, Graph,
>    Timeline, Analytics, Catalog, Connectors (read), Settings (read),
>    Collaboration Network (org + ego). A `403` on a read page is a mis-wiring.
> 2. **Chat streams** word by word (the service token path and the stream proxy
>    both still work).
> 3. **As `dev-admin`**, a connector config save, a settings save, and a scan
>    trigger all succeed.
> 4. **As `dev-user`**, the same three actions show the page's *ordinary* error
>    (403 surfaces as an error today; plan 059 makes it a clear banner). The
>    refusal must not look like a crash.
> 5. **A producer scan completes** and Recent Actions shows its status — proves
>    the service token reaches `PATCH /commands/{id}/status`.
> Wait for `PASS`.

---

## Test plan

Covered in Steps 3, 5, and 6. Priority order:

1. **Route enumeration** (Step 3) — an undeclared route fails CI.
2. **The role matrix table** (Step 6) — each row is a concrete assertion.
3. **The allowlist** — exactly two cookie paths, exactly three public paths.
4. **Secrets gating** — the single most sensitive read.

## Done criteria

- [ ] `pytest -m unit tests -q` exits 0, ≥ baseline + new
- [ ] `mypy src/` exits 0; `pylint src --score=y` ≥ 9.0; `bandit` exits 0
- [ ] `curl -s -o /dev/null -w '%{http_code}' https://localhost/api/v1/search?q=x` → `401`
- [ ] `curl -sf https://localhost/api/health` → healthy with no credential
- [ ] `/api/v1/auth/login` and `/api/v1/auth/callback` remain reachable without a token
- [ ] `grep -rc "TODO" src/app/api/connectors/v1/service.py` → `0` (the three TODOs are deleted; if other unrelated TODOs exist, confirm these three specifically)
- [ ] Every router in `api_main.py` under `/api/v1` has a router-level dependency except the auth router
- [ ] A scan triggered as admin reaches `completed`, and its status appears in Recent Actions
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report if:

- An existing API test fails and cannot be fixed by the conftest override alone
  (that means a route reads the principal directly and the override is bypassed).
- FastAPI's route introspection does not expose attached dependencies, so the
  matrix test cannot be written as specified — report before falling back.
- A UI page breaks for a legitimate logged-in user and the cause is a
  mis-classified role (rather than missing data) — that is a matrix decision,
  not an executor call.
- The runtime-snapshot endpoint cannot accept both a user session and a service
  token without splitting it into two routes — report rather than duplicating it.
- In-scope files have drifted.

## Maintenance notes

- **Adding a route now requires a matrix entry.** That is the point. The
  enumeration test prints exactly what is missing.
- **`require_user` accepts user, admin, and service.** If that ever needs to
  change, every router-level `require_user` changes with it — which is why the
  role semantics live in one function.
- **The docs routes stay publicly reachable by design** (decision below). A
  future hardening pass would set `docs_url=None` and rewrite
  `tests/test_nginx_docs_routes.py` and `tests/test_docs_endpoints_server.py`.
- **Plan D** moves theme writes from admin-only to owner-scoped. When that lands,
  the `graph_themes` row in this matrix changes and the enforcement test with it.

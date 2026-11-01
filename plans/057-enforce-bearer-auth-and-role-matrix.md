# Plan 057: Enforce bearer authentication and the role matrix on every `/api/v1` route

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving on. If
> anything in "STOP conditions" occurs, stop and report — do not improvise.
> When done, update the status row in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 61988094..HEAD -- src/app/api_main.py src/app/api src/app/auth tests/conftest.py`
> These paths **have** changed since the plan was written — that is 054/055/056's
> work, not drift. Do **not** expect an empty diff. Instead: open the "Current
> state" excerpts below and confirm each still matches the live code. A mismatch
> on an excerpt (not merely a non-empty diff) is a STOP condition.
>
> **One MANUAL GATE, at the end.** Steps 1–3 are source edits with automated
> verification; step 4 is the running-system gate. Do not hand back between
> steps 1 and 3 — that is deliberate (see "Why this plan has one gate").

## Execution record

**Steps 1–3 executed 2026-11-01** from `fd4c28e8` on `feature/plan-c-keycloak`,
uncommitted. All automated gates pass: **2586 unit passed / 0 failed / 2 skipped**
(delta **+67** over the 2519 baseline), mypy exit 0, pylint 9.69, bandit exit 0
(High: 0), `len(AUTHZ_MATRIX) == 58`, enumerator finds 58.

### Two plan-text defects found during execution (both were wrong in *this file*, not in the code)

1. **`require_roles` cannot be the literal `async def` this plan specifies.**
   `Depends(require_roles("admin", "service"))` calls the function at import
   time; on an `async def` that produces a coroutine, and FastAPI asserts
   *"A parameter-less dependency must have a callable dependency"* (plus
   `RuntimeWarning: coroutine 'require_roles' was never awaited`). It is
   implemented as a **factory** returning an inner async dependency named
   `require_roles`, which preserves every call site in step 2b verbatim.
   Semantics, 403 detail shape and log shape are as specified.

2. **The enumerator's `d.call` is wrong for router-level dependencies.** On
   FastAPI 0.161.1, `include_context.dependencies` holds `fastapi.params.Depends`
   objects (attribute `.dependency`), while `route.dependant.dependencies` holds
   `Dependant` (attribute `.call`). The recipe above only appeared to work
   because **every router-level dependency list was empty before this plan's
   wiring** — the bug was invisible until step 2 attached one. The test's
   `_dependency_name` handles both shapes. The enumerator still yields exactly 58.

Neither was catchable by the plan's own automated gates, and the 58-row matrix in
step 1a was nonetheless **correct** — verified by diffing it against the live app
before dispatch.

### One deviation in `tests/conftest.py`, judged and approved

The plan's literal fixture overrides `get_principal` with an admin principal
unconditionally. That broke two **pre-existing** tests —
`tests/test_auth_flow.py::TestMe::test_bogus_cookie_is_401` and
`::test_valid_bearer_returns_identity` — which deliberately assert the *real*
verifier on `/api/v1/auth/me`, and editing them is forbidden by this plan's STOP
conditions. The fixture therefore delegates to the real `get_principal` when a
request carries its own `Authorization` header or `wba_session` cookie, and
supplies the admin default otherwise. No other test in the repo sends either.
`Request` is imported at module scope, not in the fixture body: under
`from __future__ import annotations` FastAPI's `get_type_hints` cannot resolve a
function-local import and turns the dependency into a required query parameter
(`422: {"loc": ["query", "request"]}`).

### Anti-vacuity, both probes

- **Probe 1** (throwaway `@router.get("/__matrix_probe")`): three assertions fail,
  naming `('GET', '/api/v1/chats/__matrix_probe')`. Reverted.
- **Probe 2** (`("POST", "/api/v1/commands/")` set to `"user"`): fails with
  `expected require_user alone, got ['require_user', 're...']`. Reverted. Note the
  `"user"` check is deliberately **exact** (presents `require_user` and no
  stricter dependency): written as plain containment it *passed* probe 2, because
  the router-level `require_user` is always present — a genuine vacuity, now closed.
- **Wiring non-vacuity**, re-verified by the reviewer: stripping the router-level
  dependency from `settings` flips `GET /api/v1/settings/` from `401` to `500`
  (the handler's stubbed DB), proving the 401 is the dependency and not a 404 or a
  DB error. Restoration returns it to `401`. The executor observed the same 500;
  the strip must also invalidate `_IncludedRouter._effective_candidates`, because
  FastAPI rebuilds and caches the effective routes at match time
  (`routing.py:1544` merges `include_context.dependencies`).

## Status


- **Priority**: P1
- **Effort**: L
- **Risk**: HIGH
- **Depends on**: plans/056 (and 062, which unblocks 056)
- **Category**: security
- **Planned at**: commit `61988094`, 2026-11-01
- **Design reference**: `docs/design/authn-authz-design.md`, "Endpoint matrix",
  "Enforcement points", "Testing Strategy"
- **This is step 5 of 9** in the Plan C sequence.
- **Status**: steps 1–3 DONE 2026-11-01 (see "Execution record" below); **step 4
  (the live switch) PENDING** — it needs a stack rebuild and the operator checklist.

## Why this matters

**This is the switch.** Until now the API accepted unauthenticated requests;
after this plan every route under `/api/v1` requires a bearer token carrying a
recognised role, except the two auth-flow endpoints and the health probe. The UI
already sends tokens (plan 056) and the producers already use service tokens
(plan 055), so the switch should be invisible to both — the live gate is what
proves it.

Two structural properties make it safe to add a route later:

1. **Authentication is on by default.** Every `/api/v1` router is included with
   a router-level dependency, so a new route is authenticated unless it is
   deliberately exempted.
2. **A central `AUTHZ_MATRIX` table, plus a test that enumerates every route**,
   means a route that declares the wrong role — or no role at all — fails CI.

What improves when this lands: a forged request from a standard user receives
`403`; an unauthenticated request receives `401`; connector secrets require
`wba-admin` or `wba-service`; scans require `wba-admin` or `wba-service`; and
the categorization is no longer a convention anyone can forget.

## Why this plan has one gate

The earlier draft of this plan split the work into six steps with six manual
gates. It was wrong to, for three reasons:

1. **No step before the last needs a running system.** Steps 1–3 are source and
   test edits; their "gates" were an operator reading a diff, which the automated
   commands already do better.
2. **The real dependencies run *through* the steps, not between them.** The
   matrix (step 1) can only be filled from the enumeration (step 3), and the
   enumeration test cannot run until the wiring (step 2) exists. Splitting them
   created a numbered order that does not match the order the work happens in.
3. **The pieces are one compile unit.** The `conftest` override (step 2) must
   land in the same change as the router wiring, or the ~15 API-driving test
   files go red in between. There is no safe intermediate state to gate on.

So: **three implementation steps, one automated-verification step, one manual
gate.** The anti-vacuity checks that used to be manual gates are now scripted
sub-steps of step 3 — stronger, because the output is pasted as evidence rather
than described.

## Current state

**`src/app/api_main.py:181-192`** — routers are included **with no dependency**:

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
app.include_router(auth_v1_router, prefix="/api/v1")
```

**`src/app/auth/dependencies.py`** (plan 054) provides `get_principal`,
`require_user`, `require_admin`, `require_service`. The only current consumer is
`/api/v1/auth/me`. There is **no** `require_roles` / `require_any` — you create
it (step 1).

`require_user`'s exact semantics matter and are already pinned by a test
(`tests/test_auth_dependencies.py:114-123`, `TestRequireUser::test_accepts_every_role`,
parametrized over all three roles):

```python
def require_user(principal: Principal = Depends(get_principal)) -> Principal:
    """Require any authenticated principal (user, admin, or service)."""
    return principal
```

It accepts **all three** roles — which is what makes the router-level wiring
below correct.

**`src/app/auth/tokens.py:114-129`** — the validator is hard-coded to the
interactive client:

```python
        claims: dict[str, object] = jwt.decode(
            token,
            signing_key.key,
            algorithms=_ALGORITHMS,
            issuer=settings.KEYCLOAK_ISSUER,
            audience=settings.KEYCLOAK_CLIENT_ID,     # == "wba-web"
            leeway=30,
            options={"require": ["exp", "iss", "aud", "sub"]},
        )
    ...
    if claims.get("azp") != settings.KEYCLOAK_CLIENT_ID:   # == "wba-web"
        raise TokenValidationError("Bearer token azp does not match the expected client")
```

`settings.KEYCLOAK_SERVICE_CLIENT_ID` (`"wba-internal"`) exists and is unused
here. Plan 055 gave `wba-internal` its own audience, so a real service token
carries `aud=["wba-internal"]`, `azp="wba-internal"` — **rejected by the code
above**. Fixing this is this plan's job (see "Decisions", row 2).

**`src/app/api/connectors/v1/router.py`** — `include_secrets` is a plain query
parameter on **two** routes (`get_connector` at `:63-72`, `list_config_items` at
`:104-114`). The TODO at `:107`:

```python
    # TODO: This should be based on user permissions, not an explicit query parameter.
    include_secrets: bool = False,
```

and the service carries two matching TODOs at `service.py:409-411` and
`:477-479` (identical text, both starting `# TODO: The 'include_secrets' flag is
a temporary measure.`).

**`src/app/api/settings/v1/router.py:40`** — `GET /settings/runtime-snapshot` is
currently unrestricted; the design's matrix marks it service-only, which is
**wrong for this codebase** (see the decision table).

**`tests/conftest.py`** — has one autouse fixture (`_disable_timeline_mock`) and
a CA helper (`_resolve_local_ca` / `pytest_runtest_setup`). There is no principal
override.

**`tests/test_activity_api_integration.py:280`** — the repo's established idiom:
`app.dependency_overrides[get_async_db] = ...`.

**Verified route inventory (58 operations)** — see step 1's matrix, which is
generated from the live app by the script in step 1. Do not hand-transcribe it.

**Baseline (re-verify, do not trust this line)**: at commit `61988094`,
`pytest -m unit tests -q` should report **2519 passed / 0 failed / 2 skipped** —
the figure recorded in `plans/README.md` after plan 056. Run the command in step
3 and **use the number you actually observe**; if it differs from 2519, that is a
STOP condition (something else changed).

### A hard constraint on the enumeration test (read before writing it)

**FastAPI 0.161.1 does not flatten `include_router` into `app.routes`.**
Measured on this repo's app:

```
Counter({'_IncludedRouter': 12, 'Route': 4})   # APIRoute count: 0
```

`isinstance(route, APIRoute)` matches **zero** routes, and
`route.dependant.dependencies` therefore never sees a router's routes. An
enumeration written the obvious way silently checks nothing.

Two functional facts you must build on, both verified in this environment:

1. Each `include_router` call produces one `_IncludedRouter` in `app.routes`.
   Its real routes live at **`inc.original_router.routes`** (a list of
   `APIRoute`), where `route.path` already contains the router's own prefix
   (`/chats`, `/settings`, …).
2. The include-time prefix and router-level dependencies live at
   **`inc.include_context.prefix`** and **`inc.include_context.dependencies`**.
   Route-level dependencies live at `route.dependant.dependencies`. **They are
   two different places** — collect both.

Working enumerator (verified to yield all 58 operations on this app):

```python
from fastapi.routing import APIRoute

def api_operations(app: FastAPI) -> list[tuple[str, str, list[str]]]:
    """Return (method, full_path, dependency_names) for every API operation."""
    out: list[tuple[str, str, list[str]]] = []
    for inc in app.routes:
        if type(inc).__name__ != "_IncludedRouter":
            continue
        ctx = inc.include_context
        level = [d.call.__name__ for d in ctx.dependencies]
        for route in inc.original_router.routes:
            if not isinstance(route, APIRoute):
                continue
            route_level = [d.call.__name__ for d in route.dependant.dependencies]
            for method in sorted(route.methods or []):
                out.append((method, (ctx.prefix or "") + route.path, level + route_level))
    return out
```

This walks only included routers, so `/docs`, `/redoc` and `/openapi.json`
(FastAPI's own `Route` objects, deliberately public) never appear. That is
correct: the matrix covers `/api` operations only.

### Decisions already taken (do not re-litigate)

| # | Subject | Decision |
|---|---|---|
| 1 | **Service role scope** | **`wba-service` is a broad reader, not a four-endpoint principal.** Router-level `require_user` accepts it, so a service token reaches every read on all ten routers. It is granted **nothing** beyond what `require_user` allows, plus three explicit grants (rows 3–5: the connector-secrets read, the scan trigger, and the command-status write). This **supersedes** the earlier "exactly four endpoints" decision and the design doc's service-✗ rows for `chats`, `connectors`-status, and `settings` reads. Rationale: the producers only ever call five things, so the extra reach is unused exposure on a read-only credential already trusted with graph-writing scans; matching the design doc's ✓ rows costs no extra mechanism. |
| 2 | **Service-token audience** | `tokens.py` must accept a token whose `aud` matches **either** `KEYCLOAK_CLIENT_ID` or `KEYCLOAK_SERVICE_CLIENT_ID`, with `azp` equal to the client that matched. Rejecting an `aud`-less token stays correct. This discharges 055's recorded obligation (`plans/055:133`, `plans/README.md:154-158`). |
| 3 | **`include_secrets`** | Keep the query parameter; make it admin **or service**. Not admin-only: all three producers fetch `GET /connectors/{type}/configs?include_secrets=true` with a service token (`producers/*/[github|jira|confluence]_config.py`), and `CONFIGURATION_SOURCE=SERVER` is the shipped default (`.env.example:108`). Admin-only would break every scan. Delete the three TODOs. |
| 4 | **Scan trigger** | `POST /commands/` = admin **or service** (design matrix: user ✗, admin ✓, service ✓). |
| 5 | **Command status write** | `PATCH /commands/{id}/status` = **service only** (design matrix: user ✗, admin ✗, service ✓). The producer callback is the only caller. |
| 6 | **Runtime snapshot** | **Promoted** from service-only to user+admin+service. The UI needs it to show correct configuration (`src/ui/runtime_settings.py:109` calls it through `api_client`, i.e. as a *user*) and holds no service credential. With decision 1, plain `require_user` gives exactly this set. |
| 7 | **Themes** | Read = user; authoring, `/clone`, `/set-default` = admin-only. The per-user `subject` column is Plan D's. |
| 8 | **Chats** | All five routes = user (design matrix ✓). Note decision 1 means a service token can also read them; that is accepted exposure, not a grant. |
| 9 | **Session-cookie exception** | Exactly two paths, `/api/v1/auth/token` and `/api/v1/auth/logout`. They carry **no bearer dependency** — they read the `wba_session` cookie in the handler and raise `401` themselves. They are not "public" (they *do* authenticate) and not "bearer user" (they never see a bearer). Model this as its own role value, `"session"` (step 1). |
| 10 | **Docs routes** | `/docs`, `/redoc`, `/openapi.json` stay public and out of the matrix (they are not `/api/*`). Guarded already by `tests/test_nginx_docs_routes.py`, `tests/test_docs_endpoints_server.py`. |

### Repo conventions that apply

- Router = HTTP only; no business logic.
- `Depends` is the established mechanism; `app.dependency_overrides` is the test idiom.
- Every new function needs full annotations; `mypy src/` is strict
  (`disallow_untyped_defs`, `disallow_untyped_calls`).
- Tests carry a marker; unmarked tests are silently skipped by `pytest -m unit`.
- pylint import order matters; the repo-wide score must stay ≥ 9.0.
- No comments except to explain a non-obvious "why".
- Do **not** commit or push unless asked.

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Unit tests | `pytest -m unit tests -q` | ≥ 2519 passed + new, 0 failed |
| One test file | `pytest -m unit tests/test_authz_matrix.py -q` | all pass |
| Typecheck | `mypy src/` | exit 0 |
| Lint | `pylint src --score=y` | ≥ 9.0 |
| Security scan | `bandit -c .bandit.yml -r src/ -lll` | exit 0 |
| Count routes | save the enumerator from "A hard constraint" as `/tmp/count_ops.py` and run `PYTHONPATH=src python /tmp/count_ops.py` | 58 |
| Rebuild | `docker compose up -d --build api ui signal-consumer` | all healthy |
| Unauthenticated call | `curl -s -o /dev/null -w '%{http_code}' https://localhost/api/v1/search?q=x` | `401` |
| Health stays public | `curl -sf https://localhost/api/health` | `{"status":"healthy"}` |

## Scope

**In scope** (the only files you should modify or create):

- `src/app/auth/matrix.py` (create) — `AUTHZ_MATRIX`.
- `src/app/auth/dependencies.py` — add `require_roles`.
- `src/app/auth/tokens.py` — dual-client `aud`/`azp` acceptance (decision 2).
- `src/app/api_main.py` — router-level dependencies.
- `src/app/api/*/v1/router.py` **including `src/app/api/search/v1/persons_router.py`**
  — per-route role dependencies; connector secrets gating; delete three TODOs.
- `src/app/api/connectors/v1/service.py` — delete the two TODOs (no logic change).
- `tests/conftest.py` — the autouse principal override + an `unauthenticated` helper.
- `tests/test_authz_matrix.py` (create) — route-enumeration test.
- `tests/test_authz_enforcement.py` (create) — per-role enforcement, representative routes.
- `tests/test_auth_allowlist.py` (create) — exactly two cookie paths, exactly three public paths.
- `tests/test_connectors_secrets_gating.py` (create)
- `tests/test_auth_tokens.py` — add the service-token audience cases.

**Out of scope** (do NOT touch, even though they look related):

- Per-user ownership of chats and favourites — that is plan **058**.
  In particular `PUT /queries/catalog-metadata/{id}` stays at `require_user`
  here; 058 makes it own-rows-only.
- UI 401/403 behaviour — plan 059.
- `graph_themes` schema — Plan D.
- The `/auth/*` handler bodies (056) — you only add/confirm their role rows.
- `/api/health` — stays public.
- API docs routes — deliberately public (decision 10).
- The producers and consumer. They already send service tokens (055); if you
  find yourself editing `src/connectors/`, STOP — that means decision 1 or 2 is
  not actually satisfied by your change.

## Steps

---

### Step 1: Build the authorization layer

Three files. Do them in this order.

#### 1a — the declarative matrix, `src/app/auth/matrix.py` (create)

A single table is the one place the whole authorization model is readable, and
the enumeration test asserts the implementation matches it.

The `Role` vocabulary has five values plus one composite. Use exactly these:

```python
"""The single declarative authorization table for the API.

Every route's required role is declared here and applied at include time or in
the route decorator. ``tests/test_authz_matrix.py`` enumerates the live app and
asserts that every operation appears here with the declared dependency actually
attached, so a new route without a declaration fails CI rather than defaulting
open.
"""

from __future__ import annotations

from typing import Literal

Role = Literal["public", "session", "user", "admin", "service"]
Grant = Role | frozenset[Role]

#: (http method, full path template) -> required authorization.
#: - "public"  : no dependency at all; deliberately open.
#: - "session" : no bearer dependency; the handler validates the wba_session cookie.
#: - "user"    : require_user  — wba-user, wba-admin *and* wba-service.
#: - "admin"   : require_admin — wba-admin only.
#: - "service" : require_service — wba-service only.
#: - a frozenset: require_roles(*grant) — any one of the listed roles.
AUTHZ_MATRIX: dict[tuple[str, str], Grant] = { ... }
```

Then fill the dict with these **58** entries. This is the reviewed result — do
not add, drop, or re-classify a row without recording why:

```python
    # ── public ───────────────────────────────────────────────────────────
    ("GET", "/api/health"): "public",
    ("GET", "/api/v1/auth/login"): "public",
    ("GET", "/api/v1/auth/callback"): "public",
    # ── session cookie (no bearer; the handler authenticates) ────────────
    ("POST", "/api/v1/auth/logout"): "session",
    ("POST", "/api/v1/auth/token"): "session",
    # ── any authenticated principal ──────────────────────────────────────
    ("GET", "/api/v1/auth/me"): "user",
    # activity
    ("GET", "/api/v1/activity/suggest"): "user",
    ("GET", "/api/v1/activity/timeline"): "user",
    # chats
    ("POST", "/api/v1/chats/"): "user",
    ("GET", "/api/v1/chats/{session_id}"): "user",
    ("POST", "/api/v1/chats/{session_id}/stream"): "user",
    ("GET", "/api/v1/chats/metrics/stream"): "user",
    ("DELETE", "/api/v1/chats/{session_id}"): "user",
    # commands
    ("GET", "/api/v1/commands/"): "user",
    ("GET", "/api/v1/commands/{command_id}"): "user",
    ("POST", "/api/v1/commands/"): frozenset({"admin", "service"}),
    ("PATCH", "/api/v1/commands/{command_id}/status"): "service",
    # connectors — reads are user; writes and /test are admin
    ("GET", "/api/v1/connectors/"): "user",
    ("GET", "/api/v1/connectors/{connector_type}"): "user",
    ("GET", "/api/v1/connectors/{connector_type}/configs"): "user",
    ("PATCH", "/api/v1/connectors/{connector_type}"): "admin",
    ("DELETE", "/api/v1/connectors/{connector_type}/config"): "admin",
    ("POST", "/api/v1/connectors/{connector_type}/configs"): "admin",
    ("PUT", "/api/v1/connectors/{connector_type}/configs/{item_id}"): "admin",
    ("PATCH", "/api/v1/connectors/{connector_type}/configs/{item_id}/status"): "admin",
    ("DELETE", "/api/v1/connectors/{connector_type}/configs/{item_id}"): "admin",
    ("DELETE", "/api/v1/connectors/{connector_type}"): "admin",
    ("POST", "/api/v1/connectors/{connector_type}/test"): "admin",
    # graph
    ("POST", "/api/v1/graph/execute"): "user",
    ("POST", "/api/v1/graph/expand"): "user",
    ("GET", "/api/v1/graph/collaboration-network"): "user",
    ("GET", "/api/v1/graph/collaboration-network/ego"): "user",
    ("GET", "/api/v1/graph/health"): "user",
    # graph-themes — reads user; authoring and /set-default admin (Plan D owns the rest)
    ("GET", "/api/v1/graph-themes/"): "user",
    ("GET", "/api/v1/graph-themes/effective"): "user",
    ("GET", "/api/v1/graph-themes/{theme_id}"): "user",
    ("POST", "/api/v1/graph-themes/"): "admin",
    ("PATCH", "/api/v1/graph-themes/{theme_id}"): "admin",
    ("DELETE", "/api/v1/graph-themes/{theme_id}"): "admin",
    ("POST", "/api/v1/graph-themes/{theme_id}/clone"): "admin",
    ("POST", "/api/v1/graph-themes/{theme_id}/set-default"): "admin",
    # queries — browse user; catalog authoring admin; favourites user (058 scopes to own rows)
    ("GET", "/api/v1/queries/catalog"): "user",
    ("GET", "/api/v1/queries/catalog/namespaces"): "user",
    ("GET", "/api/v1/queries/catalog/{namespace}/{slug}"): "user",
    ("PUT", "/api/v1/queries/catalog/{namespace}/{slug}"): "admin",
    ("DELETE", "/api/v1/queries/catalog/{namespace}/{slug}"): "admin",
    ("GET", "/api/v1/queries/catalog-metadata"): "user",
    ("GET", "/api/v1/queries/catalog-metadata/{catalog_id:path}"): "user",
    ("PUT", "/api/v1/queries/catalog-metadata/{catalog_id:path}"): "user",
    # search
    ("GET", "/api/v1/search"): "user",
    ("POST", "/api/v1/search/scoped"): "user",
    ("GET", "/api/v1/search/persons"): "user",
    # settings — reads user (incl. the snapshot); writes admin
    ("GET", "/api/v1/settings/"): "user",
    ("GET", "/api/v1/settings/runtime-snapshot"): "user",
    ("PATCH", "/api/v1/settings/"): "admin",
    ("PATCH", "/api/v1/settings/{key}"): "admin",
    ("POST", "/api/v1/settings/reset"): "admin",
    ("POST", "/api/v1/settings/{key}/reset"): "admin",
```

Note the exact path spellings: the search routers register `""` and the persons
router registers `""` under its own `/search/persons` prefix, so the paths are
`/api/v1/search` and `/api/v1/search/persons` — **no trailing slash**. The
commands, connectors, settings and chats routers register `"/"`, so those **do**
carry a trailing slash. Generate-and-diff against the step-3 enumerator rather
than eyeballing.

#### 1b — `require_roles` in `src/app/auth/dependencies.py`

Decision 1 leaves only two call sites that need a *union excluding* `wba-user`:
`POST /commands/` and the `include_secrets` gate. Both are admin-or-service.
Everything else is a single role or plain `require_user`.

Name the helper **`require_roles`**, not `require_any`. `require_any` reads as
"any authenticated principal" — which is exactly what `require_user` already
does — and invites the misreading that it admits `wba-user`. It does not.

```python
async def require_roles(
    request: Request,
    *roles: str,
    principal: Principal = Depends(get_principal),
) -> Principal:
    """Require the principal to carry at least one of *roles*; 403 otherwise."""
```

Semantics and contract, matching `_require_role`'s existing shape:

- Passes when **any** role in `*roles` is present (`principal.has_role`).
- Rejected → `403` with
  `detail={"error": "insufficient_role", "message": f"One of roles {sorted(roles)!r} is required."}`.
- Logs the denial through `common.logger.logger` at warning level, naming
  `subject`, `username`, the roles, and `request.url.path` — the same shape as
  `_require_role` (`dependencies.py:68-79`).
- Never raises `401`; `get_principal` already does that.

Do **not** implement it by stacking `require_admin` and `require_service` as two
dependencies — FastAPI requires **all** declared dependencies to pass, so that
stack demands both roles at once and never succeeds. That is the trap this
helper exists to avoid.

#### 1c — dual-client audience in `src/app/auth/tokens.py` (decision 2)

A real `wba-internal` token is rejected by the current code, which would `401`
every producer and the consumer the moment enforcement lands.

Replace the single-client check with a matched-pair check:

```python
_SERVICE_CLIENT_IDS = frozenset(
    {settings.KEYCLOAK_CLIENT_ID, settings.KEYCLOAK_SERVICE_CLIENT_ID}
)
```

- `jwt.decode(..., audience=...)` accepts a **list**, so pass
  `audience=sorted(_SERVICE_CLIENT_IDS)`. PyJWT passes when the token `aud`
  intersects the list.
- Then require `claims["azp"]` to be one of `_SERVICE_CLIENT_IDS` **and** to
  appear in the token's `aud`. The pairing is the point: a token minted for
  `wba-web` must not be acceptable merely because it was somehow signed for
  `wba-internal`.

Keep everything else — algorithm allowlist, `leeway=30`,
`options={"require": ["exp", "iss", "aud", "sub"]}`, issuer check,
`NoRecognisedRoleError`, and the existing `Principal` construction — unchanged.
An `aud`-less token must still be rejected (055's decision), so do not remove
`"aud"` from `require`.

**Note**: `settings.KEYCLOAK_SERVICE_CLIENT_ID` defaults to `"wba-internal"` in
`.env.example:189` and is loaded from `.env`. Read it from the `settings`
singleton. If it is empty in the test environment, `_SERVICE_CLIENT_IDS` is a
set of one; the tests below set it explicitly via `monkeypatch`.

#### 1d — verify the layer

**Verify**:
`PYTHONPATH=src python -c "from app.auth.matrix import AUTHZ_MATRIX; print(len(AUTHZ_MATRIX))"`
→ `58`

**Verify**: `mypy src/app/auth/` → exit 0

**Verify**: `pytest -m unit tests/test_auth_tokens.py -q` → all pass (the
existing single-client cases must still hold; you will add the service cases in
step 3).

**Verify**: the enumerator from "A hard constraint" prints 58 operations. Save it
as a scratch file and run it once now — it is what step 3's test is built on, and
a mismatch here (e.g. a trailing slash you guessed wrong) is cheapest to fix now.

---

### Step 2: Wire enforcement

#### 2a — router-level authentication in `src/app/api_main.py`

Add `Depends(require_user)` to every `/api/v1` router **except the auth router**:

```python
from fastapi import Depends

from app.auth.dependencies import require_user

app.include_router(chats_v1_router, prefix="/api/v1", dependencies=[Depends(require_user)])
app.include_router(graph_v1_router, prefix="/api/v1", dependencies=[Depends(require_user)])
app.include_router(connectors_v1_router, prefix="/api/v1", dependencies=[Depends(require_user)])
app.include_router(queries_v1_router, prefix="/api/v1", dependencies=[Depends(require_user)])
app.include_router(search_v1_router, prefix="/api/v1", dependencies=[Depends(require_user)])
app.include_router(persons_v1_router, prefix="/api/v1", dependencies=[Depends(require_user)])
app.include_router(commands_v1_router, prefix="/api/v1", dependencies=[Depends(require_user)])
app.include_router(settings_v1_router, prefix="/api/v1", dependencies=[Depends(require_user)])
app.include_router(graph_themes_v1_router, prefix="/api/v1", dependencies=[Depends(require_user)])
app.include_router(activity_v1_router, prefix="/api/v1", dependencies=[Depends(require_user)])
app.include_router(auth_v1_router, prefix="/api/v1")          # declares its own per-route roles
app.include_router(endpoints.router, prefix="/api")           # /api/health is public
```

That is **10** routers with the dependency. `endpoints` and `auth` get none.

#### 2b — per-route extras

Add a route-level dependency **only** where the matrix row is narrower than
`require_user`. Use the `dependencies=[...]` form on the decorator — it keeps the
router HTTP-only and avoids adding an unused `principal` parameter to handlers
that do not read it (pylint flags unused arguments).

Do **not** thread `principal: Principal = Depends(...)` into a handler unless the
handler's body uses the principal. The only handler that legitimately needs it is
the secrets gate in 2c.

| Router | Router-level | Per-route extra |
|---|---|---|
| `chats` | `require_user` | none |
| `graph` | `require_user` | none |
| `activity` | `require_user` | none |
| `persons` (`search/v1/persons_router.py`) | `require_user` | none |
| `search` | `require_user` | none |
| `connectors` | `require_user` | `PATCH /{type}`, `DELETE /{type}`, `DELETE /{type}/config`, `POST /{type}/configs`, `PUT /{type}/configs/{item_id}`, `PATCH /{type}/configs/{item_id}/status`, `DELETE /{type}/configs/{item_id}`, `POST /{type}/test` → `require_admin` |
| `queries` | `require_user` | `PUT /catalog/{ns}/{slug}`, `DELETE /catalog/{ns}/{slug}` → `require_admin` |
| `graph_themes` | `require_user` | `POST /`, `PATCH /{id}`, `DELETE /{id}`, `POST /{id}/clone`, `POST /{id}/set-default` → `require_admin` |
| `settings` | `require_user` | `PATCH /`, `PATCH /{key}`, `POST /reset`, `POST /{key}/reset` → `require_admin` |
| `commands` | `require_user` | `POST /` → `require_roles("admin", "service")`; `PATCH /{id}/status` → `require_service` |
| `auth` | none | `/me` already has `require_user`; leave `login`/`callback`/`logout`/`token` alone |

Example of the form:

```python
@router.post("/", dependencies=[Depends(require_roles("admin", "service"))],
             response_model=CommandResponse, status_code=201)
async def create_command(...) -> CommandResponse:
```

**Important on the auth router**: `logout` and `token` must **not** gain a bearer
dependency. They have no bearer — the browser calls them with only the
`wba_session` cookie — and adding `require_user` would `401` every logout and
every token exchange. Their row is `"session"` precisely to record this.

#### 2c — the connector secrets gate

Two routes take `include_secrets`: `get_connector` (`router.py:63`) and
`list_config_items` (`router.py:104`). Both must reject `true` unless the caller
is admin **or service** (decision 3).

Because it is a query parameter and not a separate route, implement it as a
route-level dependency that reads the parameter. Put it in
`src/app/api/connectors/v1/router.py`:

```python
async def _require_secret_privilege(
    request: Request,
    include_secrets: bool = False,
    principal: Principal = Depends(require_user),
) -> None:
    """403 when a caller without admin or service asks for connector secrets."""
    if include_secrets and not (
        principal.has_role("wba-admin") or principal.has_role("wba-service")
    ):
        logger.warning(
            f"403 denied: connector secrets requested without privilege "
            f"subject={principal.subject!r} username={principal.username!r} "
            f"path={request.url.path!r}"
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": "forbidden",
                "message": "Exposing connector secrets requires the wba-admin or wba-service role.",
            },
        )
```

FastAPI injects `include_secrets` into this dependency because its name matches
the route's query parameter, so attaching it as a route dependency needs no
change to the handler signature:

```python
@router.get("/{connector_type}", response_model=ConnectorStatus,
            dependencies=[Depends(_require_secret_privilege)])
```

Why a hand-written check rather than `require_roles("admin", "service")`: a route
dependency runs unconditionally and cannot see the query value. `require_roles`
would reject a plain `wba-user` reading `GET /{type}` *without* the parameter,
which the matrix allows.

Then **delete** the three TODOs — they are now satisfied, and leaving them is a
lie in the code:

- `src/app/api/connectors/v1/router.py:107` (the two-line block above `include_secrets`)
- `src/app/api/connectors/v1/service.py:409-411`
- `src/app/api/connectors/v1/service.py:477-479`

Delete only the comment lines. Do not change any signature or logic in
`service.py` — `include_secrets` keeps working exactly as it does today.

#### 2d — the autouse principal override in `tests/conftest.py`

Add:

```python
@pytest.fixture(autouse=True)
def _admin_principal_by_default() -> Iterator[None]:
    """Authenticate every API test as an admin unless it opts out.

    Enforcement lives in FastAPI dependencies, so one override covers the ~15
    files that drive the real app through httpx.ASGITransport. Auth-specific
    tests clear it and set their own principal (see
    tests/test_authz_enforcement.py), which is why the fixture also provides the
    `unauthenticated` helper below.
    """
    from app.api_main import app
    from app.auth.dependencies import get_principal
    from app.auth.principal import Principal

    app.dependency_overrides[get_principal] = lambda: Principal(
        subject="test-admin",
        username="test-admin",
        roles=frozenset({"wba-admin", "wba-user"}),
    )
    yield
    app.dependency_overrides.pop(get_principal, None)
```

Add an explicit opt-out fixture beside it, so the 401/403 tests follow one
obvious pattern instead of each inventing its own:

```python
@pytest.fixture
def unauthenticated() -> Iterator[None]:
    """Clear the principal override so requests reach get_principal for real."""
    from app.api_main import app
    from app.auth.dependencies import get_principal

    app.dependency_overrides.pop(get_principal, None)
    yield
```

Three things an executor must get right here:

- **The override replaces `get_principal`**, so `require_user`, `require_admin`,
  `require_service` and `require_roles` all see the same principal. A test that
  needs a *user* principal must override `get_principal` with a user principal,
  not merely leave the default — the default is an admin and passes admin checks.
- **The fixture must be import-safe.** Import inside the fixture body (as above)
  so `tests/conftest.py` does not import `app.api_main` at collection time for
  suites that never touch the API — importing it constructs the LLM provider and
  reads settings.
- **Do not "fix" a failing existing test by editing that test.** See STOP
  conditions.

**Verify**: `grep -c "dependencies=\[Depends(require_user)\]" src/app/api_main.py` → `10`

**Verify**: `pytest -m unit tests -q` → **≥ 2519 passed, 0 failed**. The
override is what keeps the existing API tests green. If any existing test fails,
that is a STOP condition — do not edit the test.

---

### Step 3: Tests, then automated verification

#### 3a — the enumeration test, `tests/test_authz_matrix.py` (create)

`pytestmark = pytest.mark.unit`. Use the enumerator from "A hard constraint" —
**not** `[r for r in app.routes if isinstance(r, APIRoute)]`, which matches
nothing on FastAPI 0.161.1.

Five assertions:

1. Every operation in `api_operations(app)` appears in `AUTHZ_MATRIX`. On failure,
   print the missing `(method, path)` pairs — this is the property that matters
   most: a route added later fails loudly instead of defaulting open.
2. Every `AUTHZ_MATRIX` key is implemented by a live operation (no stale rows).
3. For each operation, the **effective dependency set** (router-level from
   `include_context.dependencies` + route-level from
   `route.dependant.dependencies`) matches the declared role:

   | Declared | Required dependency names |
   |---|---|
   | `"public"` | none of `require_user`/`require_admin`/`require_service`/`require_roles` |
   | `"session"` | none of those four (the handler validates the cookie) |
   | `"user"` | `require_user` present (router-level counts) |
   | `"admin"` | `require_admin` present |
   | `"service"` | `require_service` present |
   | `frozenset` | `require_roles` present |

4. The set of `"public"` paths is exactly
   `{("GET", "/api/health"), ("GET", "/api/v1/auth/login"), ("GET", "/api/v1/auth/callback")}`.
5. The set of `"session"` paths is exactly
   `{("POST", "/api/v1/auth/token"), ("POST", "/api/v1/auth/logout")}`.

**Anti-vacuity (mandatory, and it is a scripted sub-step — paste the output)**:

- Temporarily add a throwaway route to any router (e.g.
  `@router.get("/__matrix_probe")` in `chats`), run the test, **confirm it fails**
  naming that route, then remove the route and confirm the test passes again.
- Temporarily change one matrix row's role (e.g. mark `("POST", "/api/v1/commands/")`
  as `"user"`), run the test, **confirm it fails**, then restore.
- Assert the enumerator is non-empty inside the test itself:
  `assert len(api_operations(app)) == 58` — so a future FastAPI change that stops
  exposing routes fails the test loudly instead of passing it silently.

#### 3b — `tests/test_authz_enforcement.py` (create)

`pytestmark = [pytest.mark.unit, pytest.mark.asyncio]`. Drive the real `app`
through `httpx.ASGITransport` (pattern: `tests/test_auth_flow.py`), clearing the
autouse override and overriding `get_principal` per case.

Parametrize over these routes. Statuses are the reviewed expectations:

| Route | none | user | admin | service |
|---|---|---|---|---|
| `GET /api/health` | **200** | 200 | 200 | 200 |
| `GET /api/v1/search?q=x` | 401 | 200 | 200 | **200** |
| `GET /api/v1/settings/` | 401 | 200 | 200 | 200 |
| `GET /api/v1/chats/` (GET one) | 401 | 200 | 200 | 200 |
| `PATCH /api/v1/settings/{key}` | 401 | **403** | 200 | 403 |
| `POST /api/v1/commands/` | 401 | **403** | 200 | **200** |
| `GET /api/v1/commands/` | 401 | 200 | 200 | **200** |
| `PATCH /api/v1/commands/{id}/status` | 401 | 403 | **403** | 200 |
| `GET /api/v1/settings/runtime-snapshot` | 401 | 200 | 200 | 200 |
| `GET /api/v1/connectors/github/configs?include_secrets=true` | 401 | **403** | 200 | **200** |
| `GET /api/v1/connectors/github/configs` (no param) | 401 | 200 | 200 | 200 |
| `PUT /api/v1/queries/catalog/{ns}/{slug}` | 401 | **403** | 200 | 403 |
| `POST /api/v1/graph-themes/{id}/set-default` | 401 | **403** | 200 | 403 |
| `GET /api/health` with no credential | **200** | — | — | — |

Use a valid-but-fake UUID where a path takes one. Where a `200`/`201` would
depend on data, assert **not in (401, 403)** rather than a specific success
status, and stub the DB with `get_async_db` overrides as
`tests/test_activity_api_integration.py:280` does.

Bold cells are the ones this plan's decisions changed from the earlier draft —
read them against the decision table, not against the design doc's service-✗
rows.

#### 3c — `tests/test_auth_allowlist.py` (create)

- Assert the set of paths reachable **without** a bearer is exactly
  `{/api/health, /api/v1/auth/login, /api/v1/auth/callback}`.
- Assert the set of paths that read the `wba_session` cookie is exactly
  `{/api/v1/auth/token, /api/v1/auth/logout}`. Implement this by scanning
  `src/app/api/` for `SESSION_COOKIE_NAME` / `wba_session` and asserting the
  file set. A static assertion is acceptable and honest here; **say so in the
  docstring** so a future reader does not mistake it for a behavioural test.

#### 3d — `tests/test_connectors_secrets_gating.py` (create)

- admin + `include_secrets=true` → response contains secret material (assert a
  sensitive field differs from the masked value the service produces — the
  helper is **`_mask`** at `src/app/api/connectors/v1/service.py:141`, not
  `_mask_secret_ui`).
- **service + `include_secrets=true` → 200** (decision 3 — this is the case that
  protects the producers).
- user + `include_secrets=true` → 403, and the log line names the subject.
- user + no parameter → 200 with no secret material.

#### 3e — extend `tests/test_auth_tokens.py`

`tests/test_auth_tokens.py` already signs tokens with a `_sign(...)` helper
taking `aud`/`azp`/`include_aud` (around `:118-141`) and has a
`TestRealmShapedToken` class pinning the `wba-web` claim shape. Add a sibling
class pinning the service shape:

- `aud=["wba-internal"]`, `azp="wba-internal"` → **accepted**, `Principal` built.
- `aud=["wba-web"]`, `azp="wba-internal"` (mismatched pair) → **rejected**.
- `aud` absent → **rejected** (already covered; keep it passing).

Set `settings.KEYCLOAK_SERVICE_CLIENT_ID` with `monkeypatch` so the test does not
depend on the ambient `.env`.

#### 3f — run the automated gates and paste the evidence

Record the actual command output for each:

**Verify**: `pytest -m unit tests/test_authz_matrix.py tests/test_authz_enforcement.py tests/test_auth_allowlist.py tests/test_connectors_secrets_gating.py tests/test_auth_tokens.py -q`
→ all pass

**Verify**: `pytest -m unit tests -q` → **≥ 2519 passed, 0 failed**. State the
exact number you observed and the delta over 2519.

**Verify**: `mypy src/` → exit 0

**Verify**: `pylint src --score=y` → ≥ 9.0

**Verify**: `bandit -c .bandit.yml -r src/ -lll` → exit 0

**Verify**: the two anti-vacuity probes from 3a produce the expected failures,
and both throwaway edits are reverted (`git diff` shows no `__matrix_probe` and
the original `POST /api/v1/commands/` row).

**Verify**: `grep -rn "TODO" src/app/api/connectors/v1/service.py src/app/api/connectors/v1/router.py`
→ the three `include_secrets` TODOs are gone (other unrelated TODOs may remain;
confirm these three specifically).

---

### Step 4: 🚦 THE MANUAL GATE — the live switch

Everything before this is source edits verified by commands. This is the only
step that needs a running system, and it is where a missed router or an unattached
service token shows up as a broken page.

Rebuild and run the real services:

```bash
docker compose up -d --build api ui signal-consumer
docker compose run --rm github-producer
```

**Automated pre-checks** (run these first; paste the output):

- `curl -s -o /dev/null -w '%{http_code}' https://localhost/api/v1/search?q=x` → `401`
- `curl -sf https://localhost/api/health` → `{"status":"healthy"}`
- `curl -s -o /dev/null -w '%{http_code}' https://localhost/api/v1/auth/login` → `302`
- Producer logs show a successful `GET /api/v1/connectors/github/configs?include_secrets=true`
  (**not 403**) and `GET /api/v1/commands/` (no 401). This is the check that
  proves decision 2 and decision 3 together — it is easy to omit and it is the
  one that catches a broken service token.

**Operator checklist** (this is what the hand-back is for):

1. **Every page works logged in as `dev-user`**: Chat, Search, Graph, Timeline,
   Analytics, Catalog, Connectors (read **including Recent Actions**), Settings
   (read), Collaboration Network (org + ego). A `403` on a read page is a
   mis-wiring.
2. **Chat streams** word by word — the SSE proxy and the stream routes still work
   under a router-level dependency.
3. **As `dev-admin`**: a connector config save, a settings save, and a scan
   trigger all succeed.
4. **As `dev-user`**: the same three actions show the page's *ordinary* error
   (plan 059 makes it a clear banner later). A refusal must not look like a crash.
5. **A producer scan completes** and Recent Actions shows its status — proves the
   service token reaches `PATCH /commands/{id}/status` (decision 5).
6. **`include_secrets` is invisible to the page**: the Connectors page renders
   normally for `dev-user` without the parameter (decision 3 did not break the
   masked view).

A `FAIL` here is a STOP condition. Hand back to the operator and wait for `PASS`.

---

## Test plan

Priority order (highest value first):

1. **Route enumeration** (3a) — an undeclared route fails CI, and a future
   FastAPI change fails loudly instead of vacuously passing.
2. **The role matrix table** (3b) — each row is a concrete assertion; the four
   bold cells encode this plan's decisions.
3. **The allowlist** (3c) — exactly two cookie paths, exactly three public paths.
4. **Secrets gating** (3d) — the single most sensitive read, and the case that
   keeps the producers alive.
5. **Token audience** (3e) — the case that keeps the producers alive.

Structural patterns to model on:

- `tests/test_auth_dependencies.py` — throwaway app, `ASGITransport`, stubbed
  verifier, 401-vs-403 contract. Use its `TestRequireUser` shape for
  `require_roles`.
- `tests/test_auth_flow.py` — driving the **real** `app` through `ASGITransport`
  with `dependency_overrides`, which is what 3b and 3d need.
- `tests/test_activity_api_integration.py:280` — the `get_async_db` override idiom.

## Done criteria

ALL must hold:

- [ ] `pytest -m unit tests -q` exits 0, **≥ 2519 passed, 0 failed** (state the number)
- [ ] `mypy src/` exits 0; `pylint src --score=y` ≥ 9.0; `bandit -c .bandit.yml -r src/ -lll` exits 0
- [ ] `len(AUTHZ_MATRIX) == 58` and the enumerator finds 58 operations
- [ ] Both anti-vacuity probes (undeclared route; wrong matrix row) were run, failed as expected, and were reverted
- [ ] No existing test file was edited to make it pass (only `tests/conftest.py` gained fixtures, and `tests/test_auth_tokens.py` gained cases)
- [ ] `curl -s -o /dev/null -w '%{http_code}' https://localhost/api/v1/search?q=x` → `401`
- [ ] `curl -sf https://localhost/api/health` → healthy with no credential
- [ ] `/api/v1/auth/login` and `/api/v1/auth/callback` reachable without a token
- [ ] The producer's connector-config fetch returns **not 403**, and a scan completes
- [ ] The three `include_secrets` TODOs are deleted (not edited)
- [ ] Every `/api/v1` router in `api_main.py` has `Depends(require_user)` except the auth router (count: 10)
- [ ] No files outside the Scope list are modified (`git status`)
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report if:

- **An existing API test fails and the `conftest` override alone does not fix
  it.** That means a route reads the principal directly (not through a
  dependency) and the override is bypassed. Do **not** edit the failing test to
  make it pass — report which test and which route.
- **The enumerator cannot see router-level dependencies.** The recipe in "A hard
  constraint" is verified for FastAPI 0.161.1; if `_IncludedRouter` or
  `include_context` is absent (a FastAPI upgrade landed), report rather than
  falling back to `app.routes` — that fallback silently checks nothing.
- **The producer's connector-config fetch still returns 403** after decisions 2
  and 3 are implemented. That means the service token is failing earlier than
  the role check (audience, `azp`, or no token at all) — a token-plumbing
  problem this plan does not own. Report with the API log line.
- **A UI page breaks for a legitimate logged-in user and the cause is a
  mis-classified role** (rather than missing data). That is a matrix decision,
  not an executor call.
- **You find yourself needing to edit `src/connectors/`.** The producers already
  send service tokens; if they need changing, decision 1 or 2 is not satisfied.
- **The live tree does not match a "Current state" excerpt** — check each excerpt,
  not the diff stat (see the drift-check note in the header).
- **`pytest -m unit tests -q` does not report 2519 passed / 0 failed / 2 skipped
  before you start.** Something other than this plan changed the baseline.

## Maintenance notes

- **Adding a route now requires a matrix entry.** That is the point. The
  enumeration test prints exactly what is missing, and `assert len(...) == 58`
  makes a silent enumeration failure loud.
- **The 58 is a tripwire, not a fact.** When a route is legitimately added,
  update both the matrix and that constant in the same change.
- **`require_user` accepts user, admin, and service.** That single fact is what
  makes the router-level wiring grant service broad read access (decision 1). If
  the service role ever needs narrowing, every router-level `require_user`
  changes with it — which is why the role semantics live in one function.
- **`require_roles` is for unions that exclude `wba-user`.** If you find yourself
  reaching for it to mean "any authenticated caller", you want `require_user`.
- **The docs routes stay publicly reachable by design** (decision 10). A future
  hardening pass would set `docs_url=None` and rewrite
  `tests/test_nginx_docs_routes.py` and `tests/test_docs_endpoints_server.py`.
- **Plan D** moves theme writes from admin-only to owner-scoped, and plan **058**
  moves favourites and chats to owner-scoped. When either lands, the
  corresponding matrix rows change and `tests/test_authz_enforcement.py` with
  them.
- **Decision 1 is a deliberate widening beyond the design doc** for `chats`,
  connector-status, and settings reads. `docs/design/authn-authz-design.md`'s
  endpoint matrix still shows service ✗ on those rows; plan 061 corrects the doc.
  A reviewer should confirm the widening is understood, not accidental.

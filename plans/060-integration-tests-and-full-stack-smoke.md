# Plan 060: Prove the whole auth flow end to end against live Keycloak

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving on. If
> anything in "STOP conditions" occurs, stop and report — do not improvise.
> When done, update the status row in `plans/README.md`.
>
> **Every step ends with a MANUAL GATE.** Hand back to the operator and wait for
> `PASS`. A `FAIL` is a STOP condition.
>
> **Drift check (run first)**: `git diff --stat 225d3639..HEAD -- tests/ src/app/api/auth/ src/app/auth/ deploy/keycloak/`
> Any mismatch against "Current state" is a STOP condition.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: LOW
- **Depends on**: plans/059
- **Category**: tests | security
- **Planned at**: commit `225d3639`, 2026-10-30
- **Design reference**: `docs/design/authn-authz-design.md`, "Testing Strategy"
- **This is step 8 of 9** in the Plan C sequence.

## Why this matters

Plans 053-059 are each verified in isolation with stubbed Keycloak calls. This
plan adds the one thing none of them can prove: that the **real** redirect,
code exchange, PKCE verification, cookie, token exchange, refresh rotation, and
logout sequence works against a **real** Keycloak.

It also adds the full-stack smoke that catches the class of failure that
curl-only checks miss — plan 051's execution found exactly such a regression
(nginx's body-size limit silently broke a page while every curl check passed).
The browser checklist here is the Plan C equivalent.

These tests are `integration`-marked and **never run in CI** (CI runs `-m unit`
only). That is deliberate and mirrors the existing integration suites. Their
value is local and pre-merge.

What improves when this lands: a regression in the login sequence is caught by a
test rather than by a user, and there is a repeatable answer to "does auth
actually work?" after any Keycloak or compose change.

## Current state

**`pytest.ini`** declares these markers: `unit`, `integration`, `server`,
`neo4j`, `rabbitmq`, `elasticsearch`. CI runs `pytest -q -m unit tests --cov=src`
only.

**`tests/conftest.py`** provides:
- `_disable_timeline_mock` (autouse),
- `_resolve_local_ca()` and an `SSL_CERT_FILE` setup for `server`-marked tests,
  which reach the app at `https://localhost` through nginx. **Reuse this** — the
  integration tests here also speak TLS.

**Existing integration example**: `tests/test_activity_api_integration.py`
(drives the real app; its `:280` shows the `app.dependency_overrides[get_async_db]`
idiom). Use it as the structural model for HTTP-level tests.

**Live services**: `docker compose up -d` must be healthy; `keycloak`, `api`,
`ui`, `nginx` are all required by this plan.

**Dev users** (from plan 053's realm template): `dev-admin` (roles `wba-admin`,
`wba-user`) and `dev-user` (`wba-user`), passwords from `DEV_WBA_ADMIN_PASSWORD` /
`DEV_WBA_USER_PASSWORD` in `.env` (defaults `admin` / `user` if unset).

**Baseline**: `pytest -m unit tests -q` → 2391 passed + plans 054-059's tests.
That number must not change: **this plan adds no unit tests**.

### Repo conventions that apply

- Integration tests carry `@pytest.mark.integration` (module-level
  `pytestmark = [pytest.mark.integration]` is fine).
- Do **not** add a reachability pre-check that turns a failure into a skip — the
  existing `server` tests deliberately **fail** when the stack is down, so a
  broken environment is visible.
- Credentials come from the environment, never hard-coded in the test. Read
  `DEV_WBA_ADMIN_PASSWORD` / `DEV_WBA_USER_PASSWORD` with the compose defaults.
- Do **not** commit or push unless asked.

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Bring up the stack | `docker compose up -d` | all healthy |
| Integration tests | `pytest -m integration tests/test_auth_integration.py -q` | all pass |
| Unit baseline | `pytest -m unit tests -q` | unchanged count, 0 fail |
| Typecheck | `mypy src/` | exit 0 |
| Lint | `pylint src --score=y` | ≥ 9.0 |
| Keycloak health | `docker compose ps keycloak` | `healthy` |

**TLS note**: `httpx` verifies against `certifi`, not the system store, so the
mkcert CA must be supplied. `tests/conftest.py` already does this for
`server`-marked tests; extend that mechanism to `integration` tests rather than
duplicating it.

## Scope

**In scope**:
- `tests/test_auth_integration.py` (create)
- `tests/conftest.py` — extend the CA setup to `integration` tests if needed.
- `docs/design/authn-authz-design.md` — add a "How to run" note for this suite
  (one short paragraph; the rest of the docs work is plan 061).

**Out of scope** (do NOT touch):
- Any production code. If a test reveals a defect, **STOP and report**; the fix
  belongs in the plan that owns that code.
- Unit tests — none are added here.
- CI configuration. These tests stay out of CI by design.
- The browser checklist is manual; do not attempt to automate it with Playwright.

## Steps

### Step 1: Make TLS trust work for `integration` tests

Read the existing `_resolve_local_ca` / `SSL_CERT_FILE` handling in
`tests/conftest.py`. If it is gated on `server`-marked tests only, extend the
condition so `integration` tests also get the CA. Keep the existing behaviour for
`server` tests byte-identical.

Confirm by running a trivially TLS-touching integration test.

**Verify**: `pytest -m integration tests/test_activity_api_integration.py -q` (if
that file has integration-marked tests) → does not fail on
`CERTIFICATE_VERIFY_FAILED`

> ### 🚦 MANUAL GATE 1 — TLS
>
> Operator confirms no `CERTIFICATE_VERIFY_FAILED` appears and that the `server`
> path is unchanged.
> Wait for `PASS`.

---

### Step 2: Drive the real login sequence with `httpx`

Create `tests/test_auth_integration.py` with
`pytestmark = pytest.mark.integration`.

Use `httpx.Client(follow_redirects=False)` so each hop is observable. The
sequence:

1. `GET https://localhost/api/v1/auth/login?next=/app/graph` → `302` to Keycloak;
   capture the `wba_oidc` cookie and the `state`/`code_challenge` from the
   redirect's query.
2. Follow to Keycloak's login page, extract the form action and any hidden
   inputs (`execution`, `session_code`, `client_id`, `tab_id`). **This is real
   HTML scraping and it is the point** — it proves the exact Keycloak form works.
   Assert the form posts back to a URL under `/auth/realms/wba/`.
3. POST the credentials for `dev-user`, following redirects **manually, one hop
   at a time**, until a `302` targets
   `https://localhost/api/v1/auth/callback?code=...&state=...`.
4. `GET` the callback with the `wba_oidc` cookie → assert:
   - status `302` to `/app/graph`;
   - `Set-Cookie: wba_session=...` with `HttpOnly`, `Secure`, `SameSite=Lax`,
     `Path=/`;
   - the `wba_oidc` cookie is cleared.
5. `POST /api/v1/auth/token` with only the `wba_session` cookie → `200` with
   `access_token`, `token_type == "bearer"`, and a positive `expires_in`.
6. `GET /api/v1/auth/me` with `Authorization: Bearer <token>` → `200`,
   `username == "dev-user"`, roles contains `wba-user`.
7. `GET /api/v1/search?q=x` with the bearer → not `401`/`403`.
8. `GET /api/v1/search?q=x` **without** the bearer → `401`.

If the login form's field names differ from the expectation, inspect the real
HTML and adapt — **the scraping is what the test is for**, so do not fall back
to the `directAccessGrantsEnabled` grant (it is disabled on `wba-web` by design
in plan 053).

**Verify**: `pytest -m integration tests/test_auth_integration.py -q` → all pass

> ### 🚦 MANUAL GATE 2 — real login
>
> Operator confirms the test logs in through the actual Keycloak form (not a
> backdoor grant) and asserts the cookie flags.
> Wait for `PASS`.

---

### Step 3: Refresh rotation and logout

Add to the same file:

**Rotation**:
1. Obtain a session (reuse a fixture from Step 2).
2. Call `/api/v1/auth/token` twice, capturing the `access_token` each time.
3. Assert the two access tokens **differ** (a refresh happened).
4. Query the row and assert `refresh_token_encrypted` **changed** between the
   calls. Read it through the API's own DB connection in the test, or via
   `docker compose exec` — choose the least fragile and say which.
5. Call it a **third** time and assert it still succeeds — the specific failure
   this catches is Keycloak invalidating a reused refresh token, which presents
   as a logout after ~30 minutes.

**Logout**:
1. Record the session id (from the cookie).
2. `POST /api/v1/auth/logout` with the cookie → `302` toward Keycloak's
   `end_session_endpoint`, and the cookie is cleared.
3. `POST /api/v1/auth/token` with the now-revoked cookie → `401`.
4. Assert the row's `revoked_at` is set.

**Keycloak-down resilience** (the design's explicit promise):
1. With an unexpired cached token, `GET /api/v1/search` with the bearer still
   succeeds while Keycloak is stopped (`docker compose stop keycloak`).
2. A `/auth/token` call that must refresh returns **503**, and the row is **not**
   revoked.
3. Start Keycloak again (`docker compose start keycloak`) and confirm refresh
   works.

Marking (3) carefully: stopping a service mid-test is disruptive. Put this case
in its own test, make it clearly named, and **restore Keycloak in a `finally`**.

**Verify**: `pytest -m integration tests/test_auth_integration.py -q` → all pass
**Verify**: `docker compose ps keycloak` → `healthy` after the run (the
`finally` restored it)

> ### 🚦 MANUAL GATE 3 — rotation and resilience
>
> Operator confirms the triple-refresh test exists (the specific
> invalid_grant-on-reuse case), and that Keycloak is healthy after the suite.
> Wait for `PASS`.

---

### Step 4: Wrong-role and cross-user integration cases

Still in the same file, against real Keycloak:

1. **Admin vs user on a real admin endpoint.** Log in as `dev-user`, call
   `PATCH /api/v1/settings/HTTP_REQUEST_TIMEOUT` → `403`. Log in as `dev-admin`,
   same call → `200`. **Restore the original value afterwards** — this touches
   real configuration and must not leave the app changed. Record the restore in
   a `finally`.
2. **Connector secrets.** `dev-user` + `include_secrets=true` → `403`;
   `dev-admin` → `200`.
3. **Chat ownership.** Create a chat as `dev-user`; request it as `dev-admin` →
   `404`.
4. **Service role.** Obtain a `wba-internal` token with the client-credentials
   grant directly from Keycloak; call `GET /api/v1/commands/` → `200`, and
   `GET /api/v1/search?q=x` → `403`.

**The settings restore in (1) is mandatory.** The repo has a memory'd precedent:
a settings write smoke once left the real database changed. Assert the restored
value matches what was read before the write.

**Verify**: `pytest -m integration tests/test_auth_integration.py -q` → all pass
**Verify**: `curl -s https://localhost/api/v1/settings/` with an admin bearer →
`HTTP_REQUEST_TIMEOUT` has its original value

> ### 🚦 MANUAL GATE 4 — roles
>
> Operator confirms the integration suite restored the setting it changed.
> Wait for `PASS`.

---

### Step 5: The full-stack browser smoke checklist

Write the checklist **into this plan's gate record** as you execute it. This is
the Plan C equivalent of plan 051's Gate 8 — the check that finds what curl
cannot.

**Verify (automated prelude)**:
```bash
docker compose up -d
docker compose ps                       # every service healthy
pytest -m unit tests -q                 # unchanged baseline
pytest -m integration tests/test_auth_integration.py -q
curl -sf https://localhost/api/health
```

> ### 🚦 MANUAL GATE 5 — full-stack browser smoke (mandatory)
>
> Execute every line and record PASS/FAIL plus what you saw:
>
> **Logged out**
> 1. `https://localhost/app` → Keycloak login page.
> 2. `https://localhost/api/health` → healthy (public).
> 3. `https://localhost/app/assets/executive-dashboard.css` → 200 (assets are
>    not guarded).
> 4. `https://localhost/auth/admin/` → **404** (admin console not proxied).
> 5. `http://127.0.0.1:8080/auth/admin/` → the console loads (loopback only).
>
> **As `dev-user`**
> 6. Every sidebar page loads with real data: Chat, Search, Graph, Timeline,
>    Analytics, Connectors, Settings.
> 7. Deep links work: `/app/catalog/<ns>/<slug>`, `/app/connectors/github`,
>    the Collaboration Network link from Analytics (org and ego), and a
>    Timeline deep link into Graph.
> 8. Chat: send a message. It **streams word by word**. DevTools shows
>    `POST /app/stream/<id>` and **no** `/api/v1/chats/...` request.
> 9. Admin-only actions render a **warning** alert naming the action: save a
>    connector config; save a runtime setting; save a catalog override.
> 10. The account bar shows the username and a `User` badge.
>
> **As `dev-admin`**
> 11. The three actions in (9) now succeed.
> 12. Connector configs show secret fields (admin exposure works).
> 13. Trigger a scan from Connectors; it reaches a terminal state and appears in
>     Recent Actions (proves the service token path).
> 14. The account bar shows an `Admin` badge.
>
> **Session lifecycle**
> 15. Log out → Keycloak login page. Log back in → lands on the page you were
>     on, not the app root.
> 16. Revoke the row in the DB (`UPDATE auth_session SET revoked_at = now()`),
>     then trigger a page callback → redirected to login, and after signing in
>     returns to the same page.
> 17. Stop Keycloak (`docker compose stop keycloak`), then browse a page that
>     only needs a cached token → still works. `docker compose start keycloak`.
>
> Wait for `PASS` before starting the next step.

---

## Test plan

A single new integration file plus the manual checklist. Priorities:

1. **Real redirect + form login + callback** (Step 2) — nothing stubs Keycloak.
2. **Triple refresh** (Step 3) — catches refresh rotation not persisting.
3. **503 not 401 when Keycloak is down** (Step 3) — the design's stated promise.
4. **The browser checklist** (Step 5) — the failure class curl cannot see.

## Done criteria

- [ ] `pytest -m integration tests/test_auth_integration.py -q` exits 0
- [ ] `pytest -m unit tests -q` is **unchanged** (this plan adds no unit tests)
- [ ] `docker compose ps` shows every service healthy after the suite
- [ ] `HTTP_REQUEST_TIMEOUT` has its pre-test value
- [ ] `mypy src/` exits 0; `pylint src --score=y` ≥ 9.0
- [ ] The Gate 5 checklist is recorded with an observed result per line
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report if:

- The Keycloak login form has no discoverable form action / hidden inputs, so a
  real login cannot be automated.
- A test in this plan reveals a **production** defect. Do not fix it here —
  report which plan owns the code.
- Stopping Keycloak for the resilience test leaves the stack unhealthy after the
  `finally` restores it.
- Restoring `HTTP_REQUEST_TIMEOUT` fails; report the value found and the value
  restored.
- Any unit test count changes.

## Maintenance notes

- **This suite needs a running stack and real Keycloak.** It is not in CI by
  design; a reviewer should not ask for it there without also deciding how CI
  would run Keycloak.
- **The login-form scraping is version-coupled** to Keycloak's login theme. A
  Keycloak upgrade may change `execution`/`session_code` names; that is a test
  update, not a product defect.
- **The settings write in Step 4 mutates real configuration.** Any future test
  added here that writes must restore in a `finally` — this is the known trap.
- **`dev-*` passwords** come from the environment; if they change, the suite
  needs no edit.

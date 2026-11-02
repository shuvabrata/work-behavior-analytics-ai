# Plan 060: Prove the whole auth flow end to end against live Keycloak

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving on. If
> anything in "STOP conditions" occurs, stop and report — do not improvise.
> When done, update the status row in `plans/README.md`.
>
> **Every step ends with a MANUAL GATE.** Hand back to the operator and wait for
> `PASS`. A `FAIL` is a STOP condition.
>
> **Drift check (run first)**: `git diff --stat b73c97c6..HEAD -- tests/ docs/design/authn-authz-design.md`
> Any mismatch against "Current state" is a STOP condition.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: LOW
- **Depends on**: plans/059
- **Category**: tests | security
- **Planned at**: commit `b73c97c6`, 2026-11-02 (re-stamped; originally written
  against `225d3639`, which is the tip of `feature/plan-b-dash-api-sep-for-auth`
  and **not** an ancestor of this branch — the original drift check fired on 51
  changed files before the executor could start)
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

**Plan C has already landed.** The auth work (plans 053-059) was merged as
`7698f1e7 Feature/plan-c-keycloak (#362)`, which is how `tests/auth_helpers.py`,
`tests/test_auth_flow.py`, `tests/test_authz_live_401_sweep.py` and the other
auth test files came to exist. Plan 060 is executable now; plan 059 is DONE
(committed `0ebb241d`).

**`pytest.ini`** declares these markers: `unit`, `integration`, `server`,
`neo4j`, `rabbitmq`, `elasticsearch`, `authenticated`. CI runs
`pytest -q -m unit tests --cov=src` only.

**`tests/conftest.py`** provides:
- `_disable_timeline_mock` (autouse),
- `_resolve_local_ca()` and an `SSL_CERT_FILE` setup driven by
  `pytest_runtest_setup`, which keys on `item.get_closest_marker("server")` —
  **`server`-marked tests only**. The tests here reach the app over HTTPS through
  nginx, so they must be `server`-marked to inherit it (see Scope).

**`tests/auth_helpers.py` already implements the real login flow** — this is the
most important fact in this plan. `credentials(role)` / `admin_headers()` /
`user_headers()` / `service_headers()` / `session_cookies(role)` return live
tokens for `admin` (`dev-admin`), `user` (`dev-user`) and `service`
(`wba-internal` client-credentials). Internally it drives `GET
/api/v1/auth/login` → scrapes Keycloak's login form (`_parse_login_form`) →
posts credentials → follows to `/api/v1/auth/callback` → exchanges the session
cookie at `/api/v1/auth/token`. Tokens are cached process-wide with a refresh
margin. **Read this file first and build on it** rather than re-implementing the
flow; four sibling suites already use it:
`tests/test_settings_api.py`, `tests/test_graph_themes_api.py`,
`tests/test_catalog_metadata_api.py`, `tests/test_settings_ui_integration.py` —
all `pytestmark = [pytest.mark.integration, pytest.mark.server, pytest.mark.authenticated]`.

**Existing integration example**: `tests/test_settings_ui_integration.py` is the
closest model (it uses `auth_helpers` + `session_cookies()` for a page request).
`tests/test_activity_api_integration.py` is *not* a model for this plan — it is
`pytestmark = [pytest.mark.unit, pytest.mark.asyncio]` and drives the app through
`httpx.ASGITransport` in-process, so it never touches nginx or Keycloak.

**Live services**: `docker compose up -d` must be healthy; `keycloak`, `api`,
`ui`, `nginx` are all required by this plan.

**Dev users** (from plan 053's realm template): `dev-admin` (roles `wba-admin`,
`wba-user`) and `dev-user` (`wba-user`), passwords from `DEV_WBA_ADMIN_PASSWORD` /
`DEV_WBA_USER_PASSWORD` in `.env` (defaults `admin` / `user` if unset).

**Baseline at HEAD**: `pytest -m unit tests -q` → **2621 passed, 2 skipped,
753 deselected**. That number must not change: **this plan adds no unit tests**.
Measured on 2026-11-02; recompute it before dispatching and treat any delta as a
defect, not as drift.

### Repo conventions that apply

- Integration tests carry `@pytest.mark.integration`. New suites here must carry
  **`pytestmark = [pytest.mark.integration, pytest.mark.server]`** — the `server`
  marker is not cosmetic: it is what makes `tests/conftest.py`'s
  `pytest_runtest_setup` inject the mkcert CA into `SSL_CERT_FILE`. With
  `integration` alone, every `https://localhost` request dies with
  `CERTIFICATE_VERIFY_FAILED`. Adding `pytest.mark.authenticated` where a test
  needs the admin bearer auto-attached is optional but matches the sibling suites.
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
| Unit baseline | `pytest -m unit tests -q` | `2621 passed, 2 skipped`, 0 fail |
| Typecheck | `mypy src/` | exit 0 |
| Lint | `pylint src --score=y` | ≥ 9.0 |
| Keycloak health | `docker compose ps keycloak` | `healthy` |

**TLS note**: `httpx` verifies against `certifi`, not the system store, so the
mkcert CA must be supplied. `tests/conftest.py` already does this for
`server`-marked tests. Carry the `server` marker on the new file and the existing
mechanism applies unchanged — **no `tests/conftest.py` edit is needed**, which is
why that file is not in Scope.

## Scope

**Already landed (added 2026-11-01 during plan 057's execution — do NOT re-create)**:
- `tests/test_authz_live_401_sweep.py` — sweeps every operation in the live
  `/openapi.json` with no credential and asserts only the four intended paths
  answer something other than `401` (`/api/health`, `/api/v1/auth/login`,
  `/api/v1/auth/callback`, `/api/v1/auth/logout`, allowlisted **by path, not
  status**). It prints the full list of non-401 operations before asserting.
  Three tests: the sweep, an allowlist-staleness guard, and a direct
  `/api/health` 200 check. Non-vacuity proven by adding an unauthenticated
  `@app.get` probe route to a scratch copy of the app: the sweep reported 59
  operations and failed, naming the probe. **`/openapi.json` is the inventory
  source deliberately** — it is generated from the app's real route table, so a
  route registered directly on `app` is visible to it, whereas the
  `_IncludedRouter`-walking enumerator in `tests/test_authz_matrix.py` cannot see
  such a route (measured: adding one leaves that enumerator's count unchanged).
  This overlaps Step 1.5 below only in spirit; the sweep covers *authentication*,
  Step 1.5 covers *authorization* per role. **Do not duplicate the sweep in
  `test_auth_integration.py`.**

**In scope**:
- `tests/test_auth_integration.py` (create)
- `docs/design/authn-authz-design.md` — add a "How to run" note for this suite
  (one short paragraph; the rest of the docs work is plan 061).

**Not in scope, and no edit is needed**: `tests/conftest.py`.
`tests/test_authz_live_401_sweep.py` already carries `server` and inherited the
existing CA handling with no conftest change; carrying `server` on the new file
does the same.

**Out of scope** (do NOT touch):
- Any production code. If a test reveals a defect, **STOP and report**; the fix
  belongs in the plan that owns that code.
- Unit tests — none are added here.
- CI configuration. These tests stay out of CI by design.
- The browser checklist is manual; do not attempt to automate it with Playwright.

## Steps

### Step 1: Drive the real auth flow end to end against live Keycloak

Everything below goes in **one new file**, `tests/test_auth_integration.py`,
starting with:

```python
pytestmark = [pytest.mark.integration, pytest.mark.server]
```

The `server` marker is load-bearing (see "TLS note"): it is what injects the
mkcert CA.

**Do not put `pytest.mark.authenticated` in the module-level `pytestmark`.** It
is not a harmless extra: `tests/conftest.py::_bearer_for_authenticated_tests`
monkeypatches `httpx.Client.send` / `AsyncClient.send` for the whole test node
and attaches an admin bearer to every request to the app's own origin. Steps 1.1
(8) and 1.5 need requests that genuinely carry **no** credential — under that
marker they would silently gain one and the `401`s would never be observed. Add
it only to the specific tests that want the bearer auto-attached (e.g. a plain
authenticated read), never at module level.

**Build on `tests/auth_helpers.py`.** It already drives the real flow —
`credentials(role)`, `admin_headers()`, `user_headers()`, `service_headers()`,
`session_cookies(role)` — and four sibling suites use it. Do not re-implement the
login; `tests/test_settings_ui_integration.py` is the closest structural model.

The file must leave the system exactly as it found it (see the restore rules in
1.4 and 1.5), and the whole file must pass before the gate — there is one gate
for the file, not one per case.

**1.1 — The real login sequence.** Use `httpx.Client(follow_redirects=False)` so
each hop is observable:

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

**1.2 — Refresh rotation.** Obtain a session, then call `/api/v1/auth/token`
**three** times:

1. Assert the access tokens **differ** between calls (a refresh happened).
2. Assert `refresh_token_encrypted` **changed**. Read the row through the API's
   own DB connection in the test, or via `docker compose exec` — choose the least
   fragile and say which. Note: `refresh_token_encrypted` is Fernet ciphertext,
   so comparing the *stored* values for inequality is the signal; do not compare
   plaintext (the API never exposes it).
3. Assert the **third** call still succeeds. The specific failure this catches is
   Keycloak invalidating a reused refresh token, which presents as a logout after
   ~30 minutes.

`tests/test_auth_flow.py::TestRotation::test_rotation_persists_each_new_refresh_token`
already covers rotation against a *stubbed* Keycloak. The value added here is
only that it is the real one — keep this test about the live sequence, not a
duplicate of that unit case.

**1.3 — Logout.**

1. Record the session id (from the cookie).
2. `POST /api/v1/auth/logout` with the cookie → `302` toward Keycloak's
   `end_session_endpoint`, and the cookie is cleared.
3. `POST /api/v1/auth/token` with the now-revoked cookie → `401`.
4. Assert the row's `revoked_at` is set.

**1.4 — Keycloak-down resilience** (the design's explicit promise):

1. With an unexpired cached token, `GET /api/v1/search` with the bearer still
   succeeds while Keycloak is stopped (`docker compose stop keycloak`).
2. A `/auth/token` call that must refresh returns **503**, and the row is **not**
   revoked.
3. Start Keycloak again (`docker compose start keycloak`) and confirm refresh
   works.

Put this case in its **own clearly named test** and **restore Keycloak in a
`finally`** — stopping a service mid-suite is disruptive, and a leaked stop
breaks every later test.

**1.5 — Wrong-role and cross-user cases**, against real Keycloak:

1. **Admin vs user on a real admin endpoint.** As `dev-user`, `PATCH
   /api/v1/settings/HTTP_REQUEST_TIMEOUT` → `403`. As `dev-admin`, the same call
   → `200`. **Restore the original value in a `finally`** — this writes real
   configuration.
2. **Connector secrets.** `dev-user` + `include_secrets=true` → `403`;
   `dev-admin` → `200`.
3. **Chat ownership.** Create a chat as `dev-user`; request it as `dev-admin` →
   `404` (never `403` — the response must not confirm the id exists).
4. **Service role.** Obtain a `wba-internal` token with the client-credentials
   grant directly from Keycloak (`service_headers()` in `auth_helpers` does
   this). Assert `GET /api/v1/commands/` → not `401`/`403`, and
   `PATCH /api/v1/settings/HTTP_REQUEST_TIMEOUT` → `403`.
   **Do not assert `403` on `GET /api/v1/search`** — the role matrix makes search
   `"user"`, which *includes* `wba-service` (`src/app/auth/matrix.py:20,85`).
   `tests/test_authz_enforcement.py:87-89` pins that cell as `"service":
   "allowed"`; asserting `403` there would fail against a correct system.

**The settings restore in 1.5(1) is mandatory.** The repo has a memory'd
precedent: a settings write smoke once left the real database changed. Assert the
restored value matches what was read before the write.

**Verify**: `pytest -m integration tests/test_auth_integration.py -q` → all pass
**Verify**: `docker compose ps keycloak` → `healthy` after the run (the `finally`
restored it)
**Verify**: `curl -s https://localhost/api/v1/settings/` with an admin bearer →
`HTTP_REQUEST_TIMEOUT` has its original value

> ### 🚦 MANUAL GATE 1 — the live auth flow
>
> Operator confirms all four, from the test source and the run output:
> 1. the login goes through the **actual Keycloak form**, not a backdoor grant,
>    and the cookie flags are asserted;
> 2. the **triple-refresh** test exists (the invalid_grant-on-reuse case);
> 3. Keycloak is **healthy after the suite** — nothing was left stopped;
> 4. the suite **restored `HTTP_REQUEST_TIMEOUT`** to the value it read.
>
> Wait for `PASS`.

---

### Step 2: The full-stack browser smoke checklist

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

> ### 🚦 MANUAL GATE 2 — full-stack browser smoke (mandatory)
>
> Execute every line and record PASS/FAIL plus what you saw.
>
> **Prerequisite for line 5 only.** Keycloak publishes **no host port** by
> default (`docker-compose.yml`'s `keycloak` service has no `ports:` key), so
> `http://127.0.0.1:8080` is connection-refused until you enable it. Per
> `ADMIN_GUIDE.md:33-48`, add to that service, directly under the
> `# Admin console not published.` comment:
>
> ```yaml
>     ports:
>       - "127.0.0.1:8080:8080"
> ```
>
> then `docker compose up -d keycloak`. **After line 5, remove those lines again
> and recreate the service** (`docker compose up -d keycloak`) — the loopback
> console is a debugging affordance, not the shipped default, and leaving it
> behind is a change to the working tree. `127.0.0.1:` is required; `"8080:8080"`
> would publish the console on every interface.
>
> **Logged out**
> 1. `https://localhost/app` → Keycloak login page.
> 2. `https://localhost/api/health` → healthy (public).
> 3. `https://localhost/app/assets/executive-dashboard.css` → 200 (assets are
>    not guarded). The file is `src/ui/assets/executive-dashboard.css`.
> 4. `https://localhost/auth/admin/` → **404** (admin console not proxied). This
>    check works on a stock stack and is independent of the line-5 prerequisite.
> 5. `http://127.0.0.1:8080/auth/admin/` → the console loads (loopback only) —
>    **only after** the prerequisite above; remove the port again afterwards.
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

### Gate 1 record — 2026-11-02 (Step 1)

Executed in the **current working tree** on `feature/connector-page-render`, left
**uncommitted** (no commit/branch/worktree). `HEAD` moved mid-run: the operator
committed the six pre-existing uncommitted files as `ae40dc93`; the drift check
was therefore judged by content, not by emptiness (see the stamp note above).

**Deliverables**: `tests/test_auth_integration.py` (new, 8 tests),
`docs/design/authn-authz-design.md` (+8 lines — one "How to run" paragraph under
Testing Strategy item 3). No other file modified. `docker-compose.yml` untouched.
`plans/README.md` not edited by the executor.

**Reviewer re-ran every criterion in the live tree** (not the executor's report):

| Criterion | Command | Observed |
|---|---|---|
| Suite passes | `pytest -m integration tests/test_auth_integration.py -q` | **8 passed**, exit 0 |
| Unit baseline unchanged | `pytest -m unit tests -q` | **2627 passed, 2 skipped, 0 failed** — matches the corrected baseline |
| New file excluded from unit runs | `pytest -m unit tests/test_auth_integration.py --collect-only` | No tests collected (markers correct) |
| Typecheck | `mypy src/` | No issues found, exit 0 |
| Lint | `pylint src --score=y` | **9.69** (≥ 9.0) |
| Style | `flake8 tests/test_auth_integration.py` | clean |
| Stack healthy after suite | `docker compose ps` | all 13 services healthy; Keycloak `Up (healthy)` |
| Settings restored | `psycopg2` on `127.0.0.1:5432` | `HTTP_REQUEST_TIMEOUT` `value IS NULL`; **0** non-null override rows |
| Compose unchanged | `git diff --stat -- docker-compose.yml` | empty |

**MANUAL GATE 1 evidence:**

1. **The login goes through the actual Keycloak form** — `_submit_credentials`
   calls `tests/auth_helpers.py::_parse_login_form` and asserts the scraped
   `action` is under `/auth/realms/wba/`; the test additionally asserts
   `'<form' in page.text`. No direct-access grant
   (`directAccessGrantsEnabled` is disabled on `wba-web` by design).
   Cookie flags asserted from the callback's raw `Set-Cookie` list: `HttpOnly`,
   `Secure`, `SameSite=Lax`, `Path=/`, plus the PKCE cookie cleared with
   `Max-Age=0`. **PASS**
2. **The triple-refresh test exists** —
   `TestRefreshRotation::test_triple_refresh_rotates_and_persists` posts
   `/api/v1/auth/token` three times, asserts the three access tokens are
   pairwise distinct, and asserts `refresh_token_encrypted` changed after each
   refresh (read via `psycopg2`, comparing ciphertext for inequality). This is
   the invalid_grant-on-reuse case that would otherwise present as a logout after
   ~30 minutes. **PASS**
3. **Keycloak is healthy after the suite** — `TestKeycloakDownResilience` is
   defined last and restores in a `finally`
   (`docker compose start keycloak` + poll `docker inspect` until `healthy`);
   `docker compose ps keycloak` → `Up 2 minutes (healthy)`. Nothing was left
   stopped. **PASS**
4. **The suite restored `HTTP_REQUEST_TIMEOUT`** — the test prints
   `before: value=None source='env' effective_value=60` and
   `after: value=None source='env' effective_value=60`, takes the restore path
   for a `None` original (`POST /settings/HTTP_REQUEST_TIMEOUT/reset`, not a
   PATCH-back), and asserts `value`/`effective_value` unchanged and
   `source != "db"`. Independently confirmed in the DB: `value IS NULL`, 0
   override rows. **PASS**

**Non-vacuity of the credential-less assertions.** The module carries
`pytestmark = [pytest.mark.integration, pytest.mark.server]` with **no**
`authenticated` marker — the correct choice, and there is no class- or
function-level override either (verified by reading the file). Had
`authenticated` been present anywhere on the 401-asserting test,
`tests/conftest.py::_bearer_for_authenticated_tests` would monkeypatch
`httpx.Client.send` and attach an admin bearer, silently erasing the `401`. Run
in isolation, `TestRealLoginSequence::test_login_form_callback_and_token_exchange`
still **1 passed**, so the `401` on the credential-less `/api/v1/search` call is
observed for real, not inferred.

**Plan errors corrected at dispatch** (reality, not drift):
`TestRotation` does not exist (it is
`TestTokenExchange::test_rotation_persists_each_new_refresh_token`,
`tests/test_auth_flow.py:303`); the unit baseline was `2627`, not `2621`;
`HTTP_REQUEST_TIMEOUT` had no DB override, so restore is a **reset**, not a
PATCH-back; the host cannot resolve the compose service name `postgres`, so the
DB read goes through `psycopg2` on `127.0.0.1:5432`.

**Known deviation, judged on merit:** the executor imported
`app.auth.session_cookie` at module scope, which `mypy` (strict) cannot resolve
for a `tests/` file — 2 errors, in a file outside CI's `mypy src/` gate, which is
clean. Accepted; `flake8` is clean and no `src/` file is affected.

**Operator verdict on Gate 1: PASS** on all four items (2026-11-02).

**Comment revision (operator-requested).** The first submission was rejected on
comment hygiene: the module docstring opened with `Plans 053-059 …` and the five
section banners carried `1.1`–`1.5` step numbers. Both are process narration that
rots — plan numbers mean nothing outside `plans/`, and step numbers mean nothing
once the plan is deleted. The executor reworded the docstring to state the
durable invariant ("unit suites stub Keycloak, so nothing there can prove the
real sequence; this file is that proof") and reduced the banners to plain titles.
No test logic, assertion or behaviour changed; the suite still passes 8/8 and
`flake8` is clean. Verified by `grep -nE "plan|Plan|1\.[1-5]"` → no hits.

**Pre-existing plan references left alone (reported, not edited):**
`docs/design/authn-authz-design.md` carries many `Plan A`–`Plan F` references and
one `Plan C (053)` at line 254. Those are the design document's own vocabulary and
predate this plan; the executor's added "How to run" paragraph contains none.

### Gate 2 record — full-stack browser smoke, 2026-11-02

Executed by the operator against the live stack. **All 17 lines PASS.**

| # | Check | Result |
|---|---|---|
| 1 | `https://localhost/app` → Keycloak login page | PASS |
| 2 | `https://localhost/api/health` → healthy (public) | PASS |
| 3 | `https://localhost/app/assets/executive-dashboard.css` → 200 | PASS |
| 4 | `https://localhost/auth/admin/` → 404 (console not proxied) | PASS |
| 5 | `http://127.0.0.1:8080/auth/admin/` → console loads | PASS |
| 6 | All sidebar pages load with real data (Chat, Search, Graph, Timeline, Analytics, Connectors, Settings) | PASS |
| 7 | Deep links work (catalog, connectors, Collaboration Network org + ego, Timeline→Graph) | PASS |
| 8 | Chat streams word by word; `POST /app/stream/<id>` present, no `/api/v1/chats/...` | PASS |
| 9 | Admin-only actions render a warning alert naming the action | PASS |
| 10 | Account bar shows username + `User` badge | PASS |
| 11 | The three admin actions succeed as `dev-admin` | PASS |
| 12 | Connector configs show secret fields | PASS |
| 13 | Scan reaches a terminal state and appears in Recent Actions | PASS |
| 14 | Account bar shows `Admin` badge | PASS |
| 15 | Log out → login page; log back in → returns to the same page | PASS |
| 16 | Revoked row → redirect to login → returns to the same page after signing in | PASS |
| 17 | Keycloak stopped → cached-token page still works; restarted | PASS |

**Line 5 prerequisite, applied and reverted.** The operator added
`ports: ["127.0.0.1:8080:8080"]` under the `keycloak:` service, recreated the
container, ran line 5, then removed the lines and recreated again. Verified after
the fact: `git diff --stat docker-compose.yml` is **empty** and
`docker inspect` reports `"8080/tcp": null` — the console is unpublished again.
The `127.0.0.1:` prefix was used, so it was never exposed on other interfaces.

**Transient failure during review, not a defect.** A reviewer re-run of the suite
immediately after the container recreate produced 8 × `502 Bad Gateway` from
nginx. Cause: Keycloak was still `health: starting` (40s old) and nginx had no
healthy upstream. Once Keycloak reached `healthy` the suite passed 8/8. Worth
knowing for future runs: **recreating Keycloak requires waiting for `healthy`
before any suite that logs in** — a 502 here is readiness, not a broken proxy.

## Test plan

A single new integration file plus the manual checklist. Priorities:

1. **Real redirect + form login + callback** (Step 1.1) — nothing stubs Keycloak.
2. **Triple refresh** (Step 1.2) — catches refresh rotation not persisting.
3. **503 not 401 when Keycloak is down** (Step 1.4) — the design's stated promise.
4. **The browser checklist** (Step 2) — the failure class curl cannot see.

Rotation and the Keycloak-500→503 path already have unit coverage against a
stubbed Keycloak (`tests/test_auth_flow.py::TestRotation`, and the
`test_keycloak_500_is_503_and_preserves_the_row` case). What this file adds is
that the same sequence holds against the **real** Keycloak — write these as live
sequence tests, not restatements of the unit cases.

## Done criteria

- [ ] `pytest -m integration tests/test_auth_integration.py -q` exits 0
- [ ] `pytest -m unit tests -q` → `2627 passed, 2 skipped`, i.e. **unchanged**
      (this plan adds no unit tests; `2621` as originally written was stale — it
      predated plan 064's `tests/test_connectors_toggle.py`)
- [ ] `docker compose ps` shows every service healthy after the suite
- [ ] `HTTP_REQUEST_TIMEOUT` has its pre-test value
- [ ] No `ports:` entry for Keycloak remains in `docker-compose.yml` (`git diff docker-compose.yml` is empty after Gate 2)
- [ ] `mypy src/` exits 0; `pylint src --score=y` ≥ 9.0
- [ ] The Gate 2 checklist is recorded with an observed result per line
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report if:

- The Keycloak login form has no discoverable form action / hidden inputs, so a
  real login cannot be automated.
- A test in this plan reveals a **production** defect. Do not fix it here —
  report which plan owns the code. This includes a role assertion in Step 1.5
  disagreeing with `src/app/auth/matrix.py` — report the mismatch, do not edit
  the matrix.
- Stopping Keycloak for the resilience test leaves the stack unhealthy after the
  `finally` restores it.
- Restoring `HTTP_REQUEST_TIMEOUT` fails; report the value found and the value
  restored.
- Any unit test count changes.
- The Keycloak admin-console port from Gate 2's prerequisite cannot be removed
  again, or `docker-compose.yml` still differs afterwards.

## Maintenance notes

- **This suite needs a running stack and real Keycloak.** It is not in CI by
  design; a reviewer should not ask for it there without also deciding how CI
  would run Keycloak.
- **The login-form scraping is version-coupled** to Keycloak's login theme. A
  Keycloak upgrade may change `execution`/`session_code` names; that is a test
  update, not a product defect. `tests/auth_helpers.py::_parse_login_form`
  carries the same coupling and four suites depend on it — a theme change
  surfaces there first.
- **The settings write in Step 1.5 mutates real configuration.** Any future test
  added here that writes must restore in a `finally` — this is the known trap.
- **The service role is deliberately not a "denied everywhere" role.** It is
  `require_user`-equivalent on reads and denied on admin/session routes; see the
  endpoint matrix in `docs/design/authn-authz-design.md`. A future test asserting
  the service role gets `403` on a read endpoint will be wrong.
- **`dev-*` passwords** come from the environment; if they change, the suite
  needs no edit.

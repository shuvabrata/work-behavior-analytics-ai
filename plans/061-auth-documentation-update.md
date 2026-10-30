# Plan 061: Bring the documentation in line with what Plans C1–C8 built

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving on. If
> anything in "STOP conditions" occurs, stop and report — do not improvise.
> When done, update the status row in `plans/README.md`.
>
> **Every step ends with a MANUAL GATE.** Hand back to the operator and wait for
> `PASS`. A `FAIL` is a STOP condition.
>
> **Drift check (run first)**: `git diff --stat 225d3639..HEAD -- docs/design/authn-authz-design.md CLAUDE.md .env.example DEVELOPER_QUICK_START.md src/ui/pages/settings`
> Any mismatch against "Current state" is a STOP condition.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: LOW
- **Depends on**: plans/060
- **Category**: docs
- **Planned at**: commit `225d3639`, 2026-10-30
- **Design reference**: `docs/design/authn-authz-design.md` (the whole document)
- **This is step 9 of 9** — the final step of the Plan C sequence.

## Why this matters

Plans 051 and 052 both shipped code and left documentation stale; each time that
cost a follow-up. The authn/authz design doc is the canonical description of
this programme and is now **wrong in at least eight specific places**, because
decisions taken while planning and building Plan C overrode it. A developer
reading it today would implement the wrong thing.

This step corrects those sections in place (this repo's convention is one design
doc per programme, updated — not a second as-built document), adds the new
environment variables to `.env.example`, documents the Keycloak database
bootstrap, and registers the design doc in `CLAUDE.md` so an agent working on
authentication finds it.

What improves when this lands: the design doc describes the system that exists,
a new developer's first `docker compose up` works from the quick start, and the
authorization model has one readable description that matches the code's
`AUTHZ_MATRIX`.

## Current state

**`docs/design/authn-authz-design.md`** — 898 lines, 9 sections. The **stale**
parts, each corrected by a step below:

1. **"Configuration" table** lists `KEYCLOAK_ISSUER`, `KEYCLOAK_REALM`,
   `KEYCLOAK_CLIENT_ID`, `KEYCLOAK_CLIENT_SECRET`,
   `KEYCLOAK_SERVICE_CLIENT_ID`/`_SECRET`, `AUTH_COOKIE_SECURE`,
   `AUTH_SESSION_IDLE_MINUTES`, `AUTH_SESSION_MAX_HOURS`, `EXTERNAL_BASE_URL`. It
   also omits `APP_PUBLIC_BASE_URL`, added by plan 053 for the auth origin and
   its issuer-consistency validator.
   It does **not** list `KEYCLOAK_INTERNAL_URL`, which plan 053 introduced.
   (Its "Issuer URL" open item was already rewritten by plan 053 Step 7; verify
   that and do not redo it.)
2. **"Roles" table** says `wba-service` is "Exactly four endpoints, no more", but
   the **endpoint matrix** grants service ✓ on eleven rows. Plan 057 implemented
   the **four**.
3. **Endpoint matrix, `Runtime snapshot` row** is `✗ / ✗ / ✓` (service-only).
   Plan 057 promotes it to user + admin + service.
4. **Endpoint matrix, `Theme authoring`** marks user ✓ *(own themes)*. Plan C
   implemented **admin-only** until Plan D adds the `subject` column.
5. **Endpoint matrix, `Favourite toggle`** says user ✓ *(own rows)*. Plan 058
   made that true; the matrix should say so plainly and note the migration.
6. **"Session Management"** claims "a revoked or deleted row ends access
   immediately". Plan C accepted a **bounded 15-minute** lag for an
   already-issued bearer, with immediate revocation of the *cookie and refresh
   path*. This must be stated honestly.
7. **"Enforcement points"** says enforcement is only via FastAPI dependencies.
   Plan 056 added the **BFF token exchange** (`/api/v1/auth/token`) and
   `/auth/logout` as **cookie-authenticated** endpoints — a documented exception
   to "bearer only", bounded to exactly two paths by a test.
8. **"Non-API Surfaces §5"** says "Plan C must revisit" the public docs routes.
   Plan C **revisited and kept them public**; that section must become a record
   of a reviewed decision, not an open item.

**`CLAUDE.md`** — the canonical project guide (`.github/copilot-instructions.md`
is a symlink to it; `AGENTS.md` points to it). It has a "Reference documents"
table listing design docs with a "When" column. **The authn/authz design doc is
not in it.** The design doc's own "Documentation changes required in C" section
says to add it.

**`.env.example`** — plan 053 added a Keycloak section. Verify it is complete
and correct; the gap to look for is variables added by later plans and not
mirrored (`AUTH_*` bounds, `KEYCLOAK_INTERNAL_URL`).

**`DEVELOPER_QUICK_START.md`** — plan 053 added the existing-database bootstrap
snippet. It does **not** yet explain that the app now requires a login, how to
sign in (`dev-admin` / `dev-user`), or how to reach the Keycloak admin console.

### Repo conventions that apply

- `CLAUDE.md` is the **single source of truth**; `.github/copilot-instructions.md`
  is a symlink to it — edit `CLAUDE.md` only, never create a separate Copilot file.
- The design doc's prose style is direct, evidence-based, and cites `file:line`.
  Match it.
- Commit messages are plain imperative sentences.
- Do **not** commit or push unless asked.

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Unit tests | `pytest -m unit tests -q` | unchanged, 0 fail |
| Typecheck | `mypy src/` | exit 0 |
| Env parses | `python -c "import sys; sys.path.insert(0,'src'); from domain.settings import UISettings; UISettings(_env_file='.env.example'); print('ok')"` | `ok` |
| Design doc length | `wc -l docs/design/authn-authz-design.md` | reported, not asserted |
| Symlink intact | `ls -l .github/copilot-instructions.md` | shows `-> ../CLAUDE.md` (or equivalent) |

## Scope

**In scope**:
- `docs/design/authn-authz-design.md` — the eight corrections above.
- `CLAUDE.md` — the Reference documents row, and the "Environment
  configuration" section's key-variable list.
- `.env.example` — completeness of the Keycloak/Auth section.
- `DEVELOPER_QUICK_START.md` — sign-in, console access, and the auth env vars.

**Out of scope** (do NOT touch):
- Any source code. If a doc and the code disagree and the **code** is wrong,
  STOP and report — the fix belongs to the plan that owns it.
- Creating a new design document.
- `.github/copilot-instructions.md` — it is a symlink; editing it is editing
  `CLAUDE.md` twice.
- README badges, CI config, release notes.

## Steps

### Step 1: Correct the design doc's authorization model

Make these edits to `docs/design/authn-authz-design.md`:

**1a — the `wba-service` contradiction.** In the Roles table, keep "exactly four
endpoints". In the **endpoint matrix**, change every service ✓ to ✗ **except**
these four:

- `GET /api/v1/commands/`
- `GET /api/v1/commands/{id}`
- `PATCH /api/v1/commands/{id}/status`
- `GET /api/v1/settings/runtime-snapshot`

Add one sentence under the matrix: *"The service role is exactly these four
endpoints. Any other service ✓ in an earlier revision of this table was an error
that contradicted the Roles table; the implementation follows the Roles table."*

**1b — runtime snapshot.** Change its row to `✓ / ✓ / ✓` and add: *"The UI
reads this endpoint on its own session; it holds no service credential."*

**1c — theme authoring.** Change the user column to `✗` and the note to: *"Theme
writes are **admin-only** in Plan C. Plan D adds nullable `subject` ownership;
until it lands, 'own themes' does not exist and a standard user may not change
the theme everyone sees. `/set-default` stays admin-only regardless."*

**1d — favourites.** Change the note to: *"Per-user since Plan C: `subject` is a
column, unique on `(catalog_id, subject)`. Pre-existing global rows were deleted
by the migration."*

**1e — revocation honesty.** Replace the sentence in "Session Management" that
promises immediate revocation with a paragraph stating the bound: logout revokes
the row and clears the cookie and the UI's cached token at once, so no new token
can be minted; a bearer already issued remains valid until it expires, **at most
15 minutes**. State that this bound is deliberate and why (shortening it would
need a session id mapped into the token plus a DB read on every request).

**1f — the cookie exception.** In "Enforcement points", add a subsection:

> **The two cookie-authenticated endpoints.** `/api/v1/auth/token` and
> `/api/v1/auth/logout` read the session cookie, because the BFF must turn a
> cookie into a bearer and Keycloak must be told about logout. This is the only
> exception to "bearer only", it is bounded to exactly these two paths, and a
> unit test fails if a third appears.

**Verify**: `grep -c "exactly four" docs/design/authn-authz-design.md` → `1`
**Verify**: `grep -n "at most 15 minutes\|15-minute" docs/design/authn-authz-design.md` → present
**Verify**: `grep -c "theme writes stay admin-only\|Theme writes are \*\*admin-only\*\*" docs/design/authn-authz-design.md` → at least `1`
**Verify**: `grep -n "/api/v1/auth/token" docs/design/authn-authz-design.md` → present in the enforcement section

> ### 🚦 MANUAL GATE 1 — authorization model corrected
>
> Operator reads the edited sections and confirms each matches
> `src/app/auth/matrix.py`. A disagreement is a STOP.
> Wait for `PASS`.

---

### Step 2: Complete the configuration section and close the docs-routes item

**2a0 — add `APP_PUBLIC_BASE_URL`** to the "Configuration" table (startup-only,
required): *"Public origin of this deployment. Builds the OAuth `redirect_uri`
and, via the realm template, the realm's `redirectUris`/`webOrigins`. A startup
validator requires it to be a prefix of `KEYCLOAK_ISSUER`, so a production
domain is configured without touching code or the realm JSON."*

**2a — add `KEYCLOAK_INTERNAL_URL`** to the "Configuration" table with kind
"startup-only" and the purpose: *"Realm URL the API container uses for
discovery, token and JWKS over the Docker network. Deliberately different from
`KEYCLOAK_ISSUER`, which is the public URL used for exact `iss` matching."*

**2b — edit only the "Configuration" table.** Do **not** touch the "Issuer URL"
section if plan 053 already rewrote it. Verify with
`grep -c "KEYCLOAK_INTERNAL_URL" docs/design/authn-authz-design.md` — it should
appear in both the Issuer URL section and the Configuration table after this
step.

**2c — the public docs routes.** Rewrite the bullet under "Non-API Surfaces §5"
that begins **"Plan C must revisit it"** to record the decision:

> **Reviewed under Plan C, kept public.** Once Keycloak was in place these routes
> were reconsidered and deliberately left unauthenticated. They expose the API
> schema, not data: every operation still requires a bearer, and the schema
> reveals no credential. They are developer-local tooling and the only
> browser-based way to exercise a bearer-only API. `tests/test_nginx_docs_routes.py`
> and `tests/test_docs_endpoints_server.py` continue to guard them.

Also update that section's heading text if it reads as an open exposure.

**Verify**: `grep -c "Reviewed under Plan C, kept public" docs/design/authn-authz-design.md` → `1`
**Verify**: `grep -c "Plan C must revisit" docs/design/authn-authz-design.md` → `0`
**Verify**: `grep -c "KEYCLOAK_INTERNAL_URL" docs/design/authn-authz-design.md` → at least `2`

> ### 🚦 MANUAL GATE 2 — configuration and docs routes
>
> Operator confirms the docs-routes section reads as a decision with its
> reasoning, not a TODO.
> Wait for `PASS`.

---

### Step 3: Register the design doc in `CLAUDE.md`

Two edits to `CLAUDE.md`.

**3a — the Reference documents table.** Add a row, in the table's existing style:

```markdown
| `docs/design/authn-authz-design.md` | Authentication/authorization work — Keycloak realm, roles (`wba-admin`/`wba-user`/`wba-service`), the bearer-only API, the Dash BFF session, and the endpoint matrix |
```

Place it near the other security/architecture docs (e.g. after
`docs/design/high-level-design.md`).

**3b — the "Environment configuration" section.** Add a **Keycloak / auth**
paragraph listing `KEYCLOAK_ISSUER`, `KEYCLOAK_INTERNAL_URL`, `KEYCLOAK_REALM`,
`KEYCLOAK_CLIENT_ID`/`_SECRET`, `KEYCLOAK_SERVICE_CLIENT_ID`/`_SECRET`,
`AUTH_COOKIE_SECURE`, `AUTH_SESSION_IDLE_MINUTES`, `AUTH_SESSION_MAX_HOURS`, and
the dev seed passwords `DEV_ADMIN_PASSWORD` / `DEV_USER_PASSWORD` — with one
sentence on the `KEYCLOAK_ISSUER` vs `KEYCLOAK_INTERNAL_URL` distinction, since
that is the single most error-prone setting.

Also add, under "Repo conventions" or the Architecture section, a short note:

> **`/api/v1` requires a bearer token.** Exactly two endpoints accept the session
> cookie instead (`/api/v1/auth/token`, `/api/v1/auth/logout`); `/api/health`,
> `/api/v1/auth/login` and `/api/v1/auth/callback` are public. Every route's
> required role is declared in `src/app/auth/matrix.py`, and
> `tests/test_authz_matrix.py` fails if a route is missing from it.

**Verify**: `grep -c "authn-authz-design.md" CLAUDE.md` → `1`
**Verify**: `grep -c "KEYCLOAK_INTERNAL_URL" CLAUDE.md` → at least `1`
**Verify**: `grep -c "src/app/auth/matrix.py" CLAUDE.md` → `1`
**Verify**: `ls -l .github/copilot-instructions.md` → still a symlink (not edited)

> ### 🚦 MANUAL GATE 3 — CLAUDE.md
>
> Operator confirms the symlink is untouched and the new guidance is where an
> agent working on auth would look.
> Wait for `PASS`.

---

### Step 4: Complete `.env.example`

Read the Keycloak section plan 053 added. It must contain **all ten** variables
plus the two dev passwords, with the `KEYCLOAK_ISSUER` vs
`KEYCLOAK_INTERNAL_URL` distinction commented as plan 053 wrote it.

Add any that are missing. Do **not** change existing values or reorder unrelated
sections. Every secret-shaped value stays `FIXME`.

Then prove the file still parses as a settings source — this is the check plan
051's execution noted was missing for `EXTERNAL_BASE_URL`:

**Verify**: `python -c "import sys; sys.path.insert(0,'src'); from domain.settings import UISettings; s=UISettings(_env_file='.env.example'); print(s.KEYCLOAK_ISSUER, s.KEYCLOAK_INTERNAL_URL, s.AUTH_SESSION_MAX_HOURS)"` → `https://localhost/auth/realms/wba http://keycloak:8080/auth/realms/wba 8`
**Verify**: `grep -cE '^(KEYCLOAK_|AUTH_|DEV_)' .env.example` → at least `12`
**Verify**: `grep -n 'KEYCLOAK_CLIENT_SECRET\|KEYCLOAK_SERVICE_CLIENT_SECRET' .env.example | grep -c FIXME` → `2`

> ### 🚦 MANUAL GATE 4 — env template
>
> Operator confirms no real credential is present and the settings load from the
> template.
> Wait for `PASS`.

---

### Step 5: Update the developer quick start

In `DEVELOPER_QUICK_START.md`, add a short **"Signing in"** subsection near the
setup/first-run material:

- `docker compose up -d` brings up Keycloak with the `wba` realm.
- Sign in at `https://localhost/app` as `dev-admin` (administrator) or
  `dev-user` (standard user); the passwords come from `DEV_ADMIN_PASSWORD` /
  `DEV_USER_PASSWORD` in `.env`.
- The standard user can read everything except connector secrets and cannot
  save shared configuration; the admin can.
- The Keycloak admin console is at **`http://127.0.0.1:8080/auth/admin/`** —
  loopback only, deliberately not proxied through nginx (so it is unreachable
  from the network).
- If Keycloak fails to start with a database error on an **existing** volume,
  run the bootstrap snippet in the database section (plan 053 added it).

Keep it to roughly 10–15 lines and match the file's existing heading and list
style. Do not restructure the document.

**Verify**: `grep -c "dev-admin" DEVELOPER_QUICK_START.md` → at least `1`
**Verify**: `grep -c "127.0.0.1:8080/auth/admin" DEVELOPER_QUICK_START.md` → `1`

> ### 🚦 MANUAL GATE 5 — quick start
>
> Operator follows the section from a fresh shell and reports whether it is
> sufficient to log in.
> Wait for `PASS`.

---

### Step 6: Final consistency sweep and full regression

**Verify**: `pytest -m unit tests -q` → **unchanged** count, 0 fail
**Verify**: `mypy src/` → exit 0
**Verify**: `pylint src --score=y` → ≥ 9.0
**Verify**: `bandit -c .bandit.yml -r src/ -lll` → exit 0
**Verify**: `grep -rn "authn-authnz" docs/ CLAUDE.md plans/ | wc -l` → `0` (the
typo does not exist anywhere)
**Verify**: `python - <<'PY'
import re, pathlib
doc = pathlib.Path('docs/design/authn-authz-design.md').read_text()
matrix = pathlib.Path('src/app/auth/matrix.py').read_text()
# every path mentioned in the doc's endpoint matrix must appear in the code table
paths = set(re.findall(r'`(/api/[^`\s?]+)', doc))
missing = sorted(p for p in paths if p not in matrix and '/auth/' not in p)
print('missing from matrix:', missing)
PY` → prints only paths that are intentionally public or explicitly out of the matrix; investigate each.

> ### 🚦 MANUAL GATE 6 — consistency
>
> Operator reviews any path reported "missing from matrix" and confirms it is
> intentional (public, or a doc example), not a real gap.
> Wait for `PASS`.

---

## Test plan

Documentation only — no new tests. The verification is the grep set above plus
the full regression suite, which proves no code changed.

## Done criteria

- [ ] The eight stale sections listed in "Current state" are corrected
- [ ] `grep -c "Plan C must revisit" docs/design/authn-authz-design.md` → `0`
- [ ] `grep -c "authn-authz-design.md" CLAUDE.md` → `1`
- [ ] `grep -cE '^(KEYCLOAK_|AUTH_|DEV_)' .env.example` → at least `12`
- [ ] `UISettings(_env_file='.env.example')` loads and returns the expected three values
- [ ] `.github/copilot-instructions.md` is still a symlink
- [ ] `pytest -m unit tests -q` unchanged, 0 fail
- [ ] `mypy src/` exits 0; `pylint src --score=y` ≥ 9.0; `bandit` exits 0
- [ ] No source file was modified: `git status --short` shows only docs and `plans/`
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report if:

- The design doc and `src/app/auth/matrix.py` disagree on a role, and the code
  appears to be the wrong side. Doc changes must not paper over a code defect.
- `UISettings(_env_file='.env.example')` fails to parse — an env-var shape
  problem that will bite a new developer.
- `CLAUDE.md` has drifted such that the sections named here do not exist.
- `.github/copilot-instructions.md` is **not** a symlink (someone replaced it) —
  that is a repo-convention violation, not a doc edit.
- The consistency sweep finds a documented endpoint that does not exist.

## Maintenance notes

- **`CLAUDE.md` is the single source of truth**; never create a separate Copilot
  file.
- **The endpoint matrix in the design doc is a copy of `src/app/auth/matrix.py`.**
  When a route's role changes, both change. The `test_authz_matrix.py` test
  guards the code side; nothing guards the doc side, which is why this step's
  consistency sweep exists.
- **Plan D** will change three things documented here: theme authoring moves
  from admin-only to owner-scoped, the theme rows in the matrix change, and a
  `user_preferences` table appears. Update this doc when it lands.
- **Plan E** changes the availability posture of the backing stores; the
  Non-API Surfaces section's inventory should be revisited then.
- **A reviewer should scrutinize**: that the revocation bound and the two
  cookie-authenticated endpoints are stated honestly, not glossed.

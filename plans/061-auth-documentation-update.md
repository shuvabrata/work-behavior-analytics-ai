# Plan 061: Bring the documentation in line with what Plans C1–C8 built

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving on. If
> anything in "STOP conditions" occurs, stop and report — do not improvise.
> When done, update the status row in `plans/README.md`.
>
> **Each step ends with a MANUAL GATE.** Hand back to the operator and wait for
> `PASS`. A `FAIL` is a STOP condition.
>
> **Drift check (run first)**: `git diff --stat 225d3639..HEAD -- docs/design/authn-authz-design.md CLAUDE.md .env.example DEVELOPER_QUICK_START.md`
> Any mismatch against "Current state" is a STOP condition.
>
> **Reconciled 2026-11-02 at `8395a9e5`, re-verified at `b13c2c42`.** The drift
> check always fires: every `Planned at` stamp in `plans/` was recorded on a
> feature branch, so the stamp is not an ancestor of `main` and the diff is
> non-empty even on a healthy tree. Judge drift by opening the "Current state"
> excerpts against the live files, not by the diff being empty. The documentation
> staleness this plan targets is still present. Several excerpts did move and are
> corrected inline below: the doc is **985 lines** (the plan originally cited 898),
> the Roles table no longer contains "exactly four endpoints" (plan 057 superseded
> that decision), and `ADMIN_GUIDE.md` was renamed to `IAM_ADMIN_GUIDE.md`.
> `src/ui/pages/settings/` is **no longer in scope** and has been dropped from the
> drift check.

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

**`docs/design/authn-authz-design.md`** — **985 lines** (it was 898 when this
plan was written), 18 `##` sections. The **stale** parts, each corrected in
Step 1:

1. **"Configuration" table** lists `KEYCLOAK_ISSUER`, `KEYCLOAK_REALM`,
   `KEYCLOAK_CLIENT_ID`, `KEYCLOAK_CLIENT_SECRET`,
   `KEYCLOAK_SERVICE_CLIENT_ID`/`_SECRET`, `AUTH_COOKIE_SECURE`,
   `AUTH_SESSION_IDLE_MINUTES`, `AUTH_SESSION_MAX_HOURS`, `EXTERNAL_BASE_URL`. It
   also omits `APP_PUBLIC_BASE_URL`, added by plan 053 for the auth origin and
   its issuer-consistency validator.
   It does **not** list `KEYCLOAK_INTERNAL_URL`, which plan 053 introduced.
   (Its "Issuer URL" open item was already rewritten by plan 053 Step 7; verify
   that and do not redo it.)
2. **"Roles" table** and the **endpoint matrix service column** are **already
   correct**. The plan originally claimed a contradiction ("exactly four
   endpoints"); plan 057 superseded that decision (`plans/057:285`) and the live
   doc no longer contains the phrase. Verified against `src/app/auth/matrix.py`:
   every `"user"` route accepts a service token. Only a reconciling sentence is
   missing (Step 1a).
3. **Endpoint matrix, `Runtime snapshot` row** already reads `✓ / ✓ / ✓` and
   matches `matrix.py:90`. No cell edit needed (Step 1b).
4. **Endpoint matrix, `Theme authoring`** marks user ✓ *(own themes)*. Plan C
   implemented **admin-only** until Plan D adds the `subject` column.
5. **Favourites are out of scope.** The plan originally said to document them as
   per-user; that is false (`catalog_metadata.py:29-39` has no `subject` column,
   `plans/README.md:37` shows 065 still TODO). Leave the row alone (Step 1d).
6. **Header, Overview and "Current State"** (`:6`, `:12`, `:101-104`) still say
   the system has no authentication at all — false since `src/app/auth/` landed.
   The largest staleness in the document, and not in the original list (Step 1g).
7. **Theme endpoint paths** (`:333`, `:335`, `:756`) write `/api/v1/graph_themes/`
   with an underscore; the router serves `/graph-themes` (Step 1h).
8. **"Session Management"** claims "a revoked or deleted row ends access
   immediately". Plan C accepted a **bounded 15-minute** lag for an
   already-issued bearer, with immediate revocation of the *cookie and refresh
   path*. This must be stated honestly.
9. **"Enforcement points"** says enforcement is only via FastAPI dependencies.
   Plan 056 added the **BFF token exchange** (`/api/v1/auth/token`) and
   `/auth/logout` as **cookie-authenticated** endpoints — a documented exception
   to "bearer only", bounded to exactly two paths by a test.
10. **"Non-API Surfaces §5"** says "Plan C must revisit" the public docs routes.
    Plan C **revisited and kept them public**; that section must become a record
    of a reviewed decision, not an open item.
11. **Dangling guide references.** `ADMIN_GUIDE.md` was renamed to
    `IAM_ADMIN_GUIDE.md`; three references still point at the old name (one in
    the design doc's production checklist at `:734`, one in
    `DEVELOPER_QUICK_START.md:20`). Step 1k.

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
- `docs/design/authn-authz-design.md` — the corrections listed in "Current state"
  (items 1–8), including the theme-path fix (1h) and the configuration table (1i).
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

### Step 1: Make all the documentation edits

All edits below are independent — no ordering between them, and nothing breaks
between them (this plan touches no code). Make them all, then run the single
verification block at the end of this step.

Start with `docs/design/authn-authz-design.md`:

**1a — the `wba-service` scope.** **Do not change any service-column cell in the
endpoint matrix.** Those cells are already correct: they match
`src/app/auth/matrix.py`, where every route declared `"user"` also accepts a
service token (`matrix.py:20` — *"require_user — wba-user, wba-admin **and**
wba-service"*). An earlier draft of this plan said to flip them to ✗ and to keep
"exactly four endpoints" in the Roles table; **that instruction was wrong** —
the "exactly four endpoints" decision was superseded by
`plans/057-enforce-bearer-auth-and-role-matrix.md:285`, and the live Roles table
no longer contains that phrase (`grep -c "exactly four"` returns `0`).

The Roles table's current `wba-service` wording is correct as written. Only add
one reconciling sentence under the matrix:

> *"`wba-service` is a broad reader: every route declared `require_user` also
> accepts a service token. It is granted nothing beyond that, plus three explicit
> grants — the connector-secrets read, the scan trigger, and the command-status
> write."*

**1b — runtime snapshot.** The row already reads `✓ / ✓ / ✓` and matches the
code (`matrix.py:90`). Verify it; add only: *"The UI reads this endpoint on its
own session; it holds no service credential."* Do not edit the cells.

**1c — theme authoring.** Change the user column to `✗` and the note to: *"Theme
writes are **admin-only** in Plan C. Plan D adds nullable `subject` ownership;
until it lands, 'own themes' does not exist and a standard user may not change
the theme everyone sees. `/set-default` stays admin-only regardless."*

**1d — favourites.** **Do not document anything about per-user favourites.** The
feature does not exist: `src/app/db/models/catalog_metadata.py:29-39` has no
`subject` column, no migration adds one, and `plans/README.md:37` records that
`plans/065-per-user-catalog-favourites.md` is still TODO ("no `subject` column on
`CatalogMetadata`, `upsert` still keyed on `catalog_id` alone"). Leave the
existing row's text untouched — replacing it with a per-user claim would put a
falsehood in the doc. This is plan 065's concern, not this plan's.

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

**1g — the document's self-description.** The header and opening sections still
claim the system is unbuilt, which is false and is the first thing a reader sees:

- `docs/design/authn-authz-design.md:6` — *"**Status:** Design agreed;
  implementation plans not yet executed."* → *"**Status:** Implemented in Plan C;
  this document describes the system as built."*
- `:12` — *"This application currently has **no authentication and no
  authorization on any surface**."* → rewrite in past tense as the pre-Plan-C
  starting point.
- `:101-104` — the heading *"### There is no authentication anywhere"* and its
  "greps return **no matches**" evidence are now false: `src/app/auth/` exists
  (`dependencies.py`, `matrix.py`, `principal.py`, `session_cookie.py`,
  `tokens.py`). Retitle the section as a record of the earlier state, e.g.
  *"### Before Plan C: no authentication existed"*, and mark the greps as the
  state observed at design time. Keep the evidence — it explains why the design
  exists — but do not let it read as current.

**1h — correct the theme endpoint paths.** The doc writes them with an
underscore; the live router uses a hyphen. `src/app/api/graph_themes/v1/router.py:39`
is `APIRouter(prefix="/graph-themes", ...)` and `src/app/auth/matrix.py:67-74`
declares `/api/v1/graph-themes/...`, so the documented URL `404`s. Fix the two
matrix rows (`docs/design/authn-authz-design.md:333,335`) and the Plan-D prose
mention at `:756` to `/api/v1/graph-themes/`. Leave the *table name*
`graph_themes` alone where it refers to the database table (lines 351, 756).

**1i — correct the configuration table.** Add these two rows to the
"Configuration" table (`docs/design/authn-authz-design.md:610-625`); neither is
currently listed:

**1i-1 — `APP_PUBLIC_BASE_URL`** (startup-only, required): *"Public origin of this
deployment. Builds the OAuth `redirect_uri` and, via the realm template, the
realm's `redirectUris`/`webOrigins`. A startup validator requires it to be a
prefix of `KEYCLOAK_ISSUER`, so a production domain is configured without
touching code or the realm JSON."*

**1i-2 — `KEYCLOAK_INTERNAL_URL`** (startup-only): *"Realm URL the API container
uses for discovery, token and JWKS over the Docker network. Deliberately
different from `KEYCLOAK_ISSUER`, which is the public URL used for exact `iss`
matching."*

Edit **only** the Configuration table — the "Issuer URL" section (`:256-282`) was
already rewritten by plan 053 and is correct.

**1j — the public docs routes.** `docs/design/authn-authz-design.md:592-601`
still carries the stale bullet *"**Plan C must revisit it**…"*. Rewrite it to
record the decision that was actually taken:

> **Reviewed under Plan C, kept public.** Once Keycloak was in place these routes
> were reconsidered and deliberately left unauthenticated. They expose the API
> schema, not data: every operation still requires a bearer, and the schema
> reveals no credential. They are developer-local tooling and the only
> browser-based way to exercise a bearer-only API. `tests/test_nginx_docs_routes.py`
> and `tests/test_docs_endpoints_server.py` continue to guard them.

Also fix the stale guide filename in that file's production-checklist table
(`:734`): `ADMIN_GUIDE.md` no longer exists — it is `IAM_ADMIN_GUIDE.md`.

**1k — fix the dangling guide reference in the quick start.** In
`DEVELOPER_QUICK_START.md:20`, `ADMIN_GUIDE.md` → `IAM_ADMIN_GUIDE.md`. (The rest
of the quick start is Step 1m.)

**1l — register the design doc in `CLAUDE.md`.** Three edits:

**1l-1 — the Reference documents table** (`CLAUDE.md:244-263`). Add a row in the
table's existing style, after `docs/design/high-level-design.md`:

```markdown
| `docs/design/authn-authz-design.md` | Authentication/authorization work — Keycloak realm, roles (`wba-admin`/`wba-user`/`wba-service`), the bearer-only API, the Dash BFF session, and the endpoint matrix |
```

**1l-2 — the "Environment configuration" section.** Add a **Keycloak / auth**
paragraph listing `KEYCLOAK_ISSUER`, `KEYCLOAK_INTERNAL_URL`, `KEYCLOAK_REALM`,
`KEYCLOAK_CLIENT_ID`/`_SECRET`, `KEYCLOAK_SERVICE_CLIENT_ID`/`_SECRET`,
`APP_PUBLIC_BASE_URL`, `AUTH_COOKIE_SECURE`, `AUTH_SESSION_IDLE_MINUTES`,
`AUTH_SESSION_MAX_HOURS`, and the dev seed passwords
`DEV_WBA_ADMIN_PASSWORD` / `DEV_WBA_USER_PASSWORD` — with one sentence on the
`KEYCLOAK_ISSUER` vs `KEYCLOAK_INTERNAL_URL` distinction, since that is the
single most error-prone setting.

State which settings class owns each variable, because the split is deliberate
and non-obvious: `KEYCLOAK_CLIENT_SECRET` and `KEYCLOAK_SERVICE_CLIENT_SECRET`
are on **`ApiSettings`** (`src/app/settings.py:69-70`); every other `KEYCLOAK_*` /
`AUTH_*` / `APP_PUBLIC_BASE_URL` field is on **`UISettings`**
(`src/domain/settings.py:43-81`), which the UI runtime instantiates bare. The
secrets are API-only because no UI-side code ever exchanges them — the browser
client's token exchange is an API endpoint, and producers read the service secret
from the environment.

The `DEV_*` variables are on **neither** settings class, and must not be
presented as app settings: `grep -c "DEV_" src/domain/settings.py` returns `0`.
They are consumed at container start by `deploy/keycloak/entrypoint.sh:10-11` and
`deploy/keycloak/realm-wba.json.template:94,112`, and generated by
`scripts/setup.sh:332-333`. List them as seeded Keycloak credentials.

**1l-3 — the bearer rule.** Add under "Repo conventions" or the Architecture
section:

> **`/api/v1` requires a bearer token.** Exactly two endpoints accept the session
> cookie instead (`/api/v1/auth/token`, `/api/v1/auth/logout`); `/api/health`,
> `/api/v1/auth/login` and `/api/v1/auth/callback` are public. Every route's
> required role is declared in `src/app/auth/matrix.py`, and
> `tests/test_authz_matrix.py` fails if a route is missing from it.

**1m — complete `.env.example` and the quick start.**

Read the Keycloak section of `.env.example` (lines ~175-216). It must contain
**all ten** variables plus the dev passwords, with the `KEYCLOAK_ISSUER` vs
`KEYCLOAK_INTERNAL_URL` distinction commented. It currently **already satisfies
this** — verify, and add nothing unless something is in fact missing. Do **not**
change existing values or reorder unrelated sections. Every secret-shaped value
stays `FIXME`.

In `DEVELOPER_QUICK_START.md`, add a short **"Signing in"** subsection near the
setup/first-run material (roughly 10–15 lines, matching the file's existing
heading and list style; do not restructure the document):

- `docker compose up -d` brings up Keycloak with the `wba` realm.
- Sign in at `https://localhost/app` as `dev-admin` (administrator) or
  `dev-user` (standard user); the passwords come from `DEV_WBA_ADMIN_PASSWORD` /
  `DEV_WBA_USER_PASSWORD` in `.env`.
- The standard user can read everything except connector secrets and cannot
  save shared configuration; the admin can.
- The Keycloak admin console is at **`http://127.0.0.1:8080/auth/admin/`** —
  loopback only, deliberately not proxied through nginx (so it is unreachable
  from the network). `IAM_ADMIN_GUIDE.md` has the operator steps.
- If Keycloak fails to start with a database error on an **existing** volume,
  run the bootstrap snippet in the database section (plan 053 added it).

**Verify** (all of the above, in one pass):

```
grep -c "exactly four"           docs/design/authn-authz-design.md   # → 0
grep -c "Theme writes are \*\*admin-only\*\*" docs/design/authn-authz-design.md  # → 1
awk -F'|' '/^\| Theme authoring/{print $4}' docs/design/authn-authz-design.md | grep -c '✓'  # → 0 (user column cleared)
grep -c "ends access immediately" docs/design/authn-authz-design.md  # → 0 (stale claim removed; it is at line 440 today)
grep -c "at most 15 minutes"     docs/design/authn-authz-design.md   # → ≥1
grep -c "/api/v1/auth/token"     docs/design/authn-authz-design.md   # → ≥1 (enforcement section)
grep -c "no authentication anywhere"          docs/design/authn-authz-design.md  # → 0
grep -c "implementation plans not yet executed" docs/design/authn-authz-design.md # → 0
grep -c "graph_themes/"          docs/design/authn-authz-design.md   # → 0
grep -c "graph-themes"           docs/design/authn-authz-design.md   # → ≥3
grep -c "Plan C must revisit"    docs/design/authn-authz-design.md   # → 0
grep -c "Reviewed under Plan C, kept public" docs/design/authn-authz-design.md # → 1
grep -c "KEYCLOAK_INTERNAL_URL"  docs/design/authn-authz-design.md   # → ≥3 (Issuer URL, table, checklist)
grep -c "APP_PUBLIC_BASE_URL"    docs/design/authn-authz-design.md   # → ≥2
grep -c "ADMIN_GUIDE.md"         docs/design/authn-authz-design.md DEVELOPER_QUICK_START.md  # → 0
grep -c 'docs/design/authn-authz-design.md` |' CLAUDE.md             # → 1 (Reference-documents row)
grep -c "authn-authz-design.md"  CLAUDE.md                           # → 2 (row + API-documentation paragraph)
grep -c "KEYCLOAK_INTERNAL_URL"  CLAUDE.md                           # → ≥1
grep -c "src/app/auth/matrix.py" CLAUDE.md                           # → 1
grep -c "dev-admin"              DEVELOPER_QUICK_START.md            # → ≥1
grep -c "127.0.0.1:8080/auth/admin" DEVELOPER_QUICK_START.md         # → 1
grep -cE '^(KEYCLOAK_|AUTH_|DEV_)' .env.example                      # → ≥12
```

Plus the settings parse check:

```
python -c "import sys; sys.path.insert(0,'src'); from domain.settings import UISettings; s=UISettings(_env_file='.env.example'); print(s.KEYCLOAK_ISSUER, s.KEYCLOAK_INTERNAL_URL, s.AUTH_SESSION_MAX_HOURS)"
→ https://localhost/auth/realms/wba http://keycloak:8080/auth/realms/wba 8
```

and `grep -n 'KEYCLOAK_CLIENT_SECRET\|KEYCLOAK_SERVICE_CLIENT_SECRET' .env.example | grep -c FIXME` → `2`.

Note on `1a`/`1b`: the "no-op" instructions there are deliberate. The live matrix's
service column is already correct, so the correct outcome is **no cell changes** —
if you find yourself editing service cells, stop; you are re-introducing a
superseded decision.

> ### 🚦 MANUAL GATE 1 — all edits made
>
> Operator reads the edited sections and confirms the design doc's endpoint matrix
> matches `src/app/auth/matrix.py` (a disagreement is a STOP), that the
> docs-routes section reads as a decision rather than a TODO, and that
> `CLAUDE.md`'s new guidance is where an agent working on auth would look. Confirm
> `.github/copilot-instructions.md` is still a symlink.
> Wait for `PASS`.

---

### Step 2: Final consistency sweep and full regression

**Verify**: `pytest -m unit tests -q` → **unchanged** count, 0 fail
**Verify**: `mypy src/` → exit 0
**Verify**: `pylint src --score=y` → ≥ 9.0
**Verify**: `bandit -c .bandit.yml -r src/ -lll` → exit 0
**Verify**: `grep -rn "authn-authnz" docs/ CLAUDE.md plans/ | wc -l` → `0` (the
typo does not exist anywhere)
**Verify**: the doc↔code endpoint sweep below.

The sweep must find the paths **inside the matrix table cells**, which begin with
an HTTP method. A naive `` `(/api/…) `` pattern only matches a backtick
immediately before `/api` and catches 5 of the doc's 28 paths — it would miss
every row this plan edits. Run exactly this:

```bash
python - <<'PY'
import re, pathlib

doc = pathlib.Path('docs/design/authn-authz-design.md').read_text()
matrix = pathlib.Path('src/app/auth/matrix.py').read_text()

def norm(p: str) -> str:
    p = re.sub(r'\{[^}]+\}', '{x}', p)   # {id} / {session_id} placeholders
    p = re.sub(r'\[[^\]]*\]', '', p)     # [/ego] shorthand in a cell
    return p.rstrip('*').rstrip('/')

raw = set(re.findall(r'`(?:\w+\s+)?(/api/[^`\s?,]+)', doc))
candidates = {p for p in raw if p.count('/') >= 3
              and '*' not in re.sub(r'\[[^\]]*\]', '', p)}
matrix_norm = {norm(p) for p in re.findall(r'"(/api/[^"]+)"', matrix)}

missing = sorted(p for p in candidates
                 if norm(p) not in matrix_norm and '/auth/' not in p)
print('missing from matrix:', missing)
assert not missing, f'documented paths absent from matrix.py: {missing}'
PY
```

→ prints `missing from matrix: []` and exits 0. The two filters
(`count('/') >= 3`, no bare `*`) drop `/api/*` and the bare `/api/v1` prefix,
which are prose, not endpoints; the `norm` helper reconciles `{id}` vs
`{session_id}` and the `[/ego]` shorthand, which are naming variants, not
mismatches.

**Before Step 1h this sweep reports exactly two paths** —
`/api/v1/graph_themes/` and `/api/v1/graph_themes/{id}/set-default`. That is the
`graph_themes` defect, and it is the proof the sweep is not vacuous. After the
fix it must be empty. A non-empty list afterwards is a STOP condition: the doc
documents an endpoint that does not exist.

> ### 🚦 MANUAL GATE 2 — consistency
>
> Operator confirms the sweep is empty and that nothing was changed outside the
> documents listed in Scope.
> Wait for `PASS`.

---

## Test plan

Documentation only — no new tests. The verification is the grep set in Step 1,
the endpoint sweep in Step 2, and the full regression suite, which proves no code
changed. There is **no behavioural test for any of this**: the doc has no
executable check against the code beyond the Step 2 sweep, so the sweep is the
plan's only real guard. Treat a non-empty sweep as a genuine failure.

## Done criteria

- [ ] Every correction listed in "Current state" (items 1–8) is present
- [ ] `grep -c "no authentication anywhere" docs/design/authn-authz-design.md` → `0`
- [ ] `grep -c "implementation plans not yet executed" docs/design/authn-authz-design.md` → `0`
- [ ] `grep -c "graph_themes/" docs/design/authn-authz-design.md` → `0`; `grep -c "graph-themes"` → ≥ 3
- [ ] `grep -c "Plan C must revisit" docs/design/authn-authz-design.md` → `0`
- [ ] `grep -c "Reviewed under Plan C, kept public" docs/design/authn-authz-design.md` → `1`
- [ ] No service-column cell in the endpoint matrix was changed
      (`git diff docs/design/authn-authz-design.md` shows no `✓ → ✗` in column 4)
- [ ] `grep -c 'docs/design/authn-authz-design.md` |' CLAUDE.md` → `1`
- [ ] `grep -cE '^(KEYCLOAK_|AUTH_|DEV_)' .env.example` → at least `12`
- [ ] `UISettings(_env_file='.env.example')` loads and returns the expected three values
- [ ] `.github/copilot-instructions.md` is still a symlink
- [ ] The Step 2 endpoint sweep prints `missing from matrix: []`
- [ ] `pytest -m unit tests -q` unchanged, 0 fail
- [ ] `mypy src/` exits 0; `pylint src --score=y` ≥ 9.0; `bandit` exits 0
- [ ] No source file was modified: `git status --short` shows only docs and `plans/`
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report if:

- The design doc and `src/app/auth/matrix.py` disagree on a role, and the code
  appears to be the wrong side. Doc changes must not paper over a code defect.
  **This includes the service column**: if implementing Step 1a seems to require
  changing service cells, stop — the plan is telling you not to, and editing them
  re-introduces a superseded decision.
- `UISettings(_env_file='.env.example')` fails to parse — an env-var shape
  problem that will bite a new developer.
- `CLAUDE.md` has drifted such that the sections named here do not exist.
- `.github/copilot-instructions.md` is **not** a symlink (someone replaced it) —
  that is a repo-convention violation, not a doc edit.
- The Step 2 consistency sweep reports a documented endpoint that does not exist
  in `src/app/auth/matrix.py` (and is not under `/api/v1/auth/`).

## Maintenance notes

- **`CLAUDE.md` is the single source of truth**; never create a separate Copilot
  file.
- **The endpoint matrix in the design doc is a copy of `src/app/auth/matrix.py`.**
  When a route's role changes, both change. The `test_authz_matrix.py` test
  guards the code side; nothing guards the doc side, which is why Step 2's
  consistency sweep exists. The sweep went blind for a long time — its original
  regex only matched a backtick immediately before `/api` and so skipped every
  table cell; keep the method-prefix-tolerant version from Step 2.
- **`graph_themes` vs `graph-themes`**: the Python module and DB table use the
  underscore, the HTTP path uses the hyphen. The doc had them confused; anyone
  adding a theme endpoint should check `src/app/api/graph_themes/v1/router.py`'s
  prefix rather than copying an existing row.
- **Plan D** will change three things documented here: theme authoring moves
  from admin-only to owner-scoped, the theme rows in the matrix change, and a
  `user_preferences` table appears. Update this doc when it lands.
- **Plan E** changes the availability posture of the backing stores; the
  Non-API Surfaces section's inventory should be revisited then.
- **A reviewer should scrutinize**: that the revocation bound and the two
  cookie-authenticated endpoints are stated honestly, not glossed.

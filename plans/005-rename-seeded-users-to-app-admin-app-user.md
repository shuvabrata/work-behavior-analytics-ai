# Plan 005: Rename the seeded users to `app-admin` / `app-user` and take every username from the environment

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan in
> `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git status --porcelain` and then
> `grep -nE "DEV_WBA_(ADMIN|USER)_BOOTSTRAP_PASSWORD|dev-admin|dev-user" .env.example deploy/keycloak/realm-wba.json.template deploy/keycloak/entrypoint.sh docker-compose.yml scripts/setup.sh`
>
> **This plan builds on uncommitted work.** Plans 001–004 are DONE, but plan
> 004's changes are **uncommitted in the working tree** at the time this plan was
> written (`HEAD` is still `bfa5d8f0`). The excerpts below describe the working
> tree *after* plan 004, not the last commit. If the grep above returns nothing,
> the working tree has been reset and you are looking at pre-004 code — STOP.

## Execution record — 2026-11-13

Steps 1–6 and 8 were executed in the working tree on `feature/bootstrap-pwds`;
all changes are uncommitted. Step 7 (the `.env` rename, the GitHub repository
variables, and the Keycloak re-seed) is operator work and was not performed.

### Verification evidence

Re-run by the reviewer, not taken from the executor's report:

- Realm template renders as JSON with `usernames: ['app-admin', 'app-user',
  'service-account-internal', 'service-account-admin-api']`, `unsubstituted: []`,
  and `temporary` flags `[('app-admin', True), ('app-user', True)]`;
  `"temporary": true` appears exactly twice.
- `APP_ADMIN_PASSWORD`, `APP_USER_PASSWORD` and `KEYCLOAK_CONSOLE_ADMIN_PASSWORD`
  are wired through `entrypoint.sh`, `docker-compose.yml` and `scripts/setup.sh`;
  `docker compose config -q` exits 0.
- `realm_username()` has no fallback: unset and literal `FIXME` both raise
  `RuntimeError` naming `TEST_SUITE_WBA_USER_USERNAME`; a real value is returned.
- No `DEV_WBA` / `DEV_KEYCLOAK` variable and no `dev-admin` / `dev-user` string
  survives outside `plans/` and `docs/project-plan/`; no `"app-admin"` /
  `"app-user"` literal exists in `tests/`, `.github/`, `scripts/` or `src/`.
- `pytest -m unit tests -q` with the two usernames in the environment →
  `2765 passed, 2 skipped`. `mypy src/` clean; `pylint src` 10.00/10; scoped
  `flake8` exit 0.
- Plan 004's skip behaviour is intact: `tests/test_auth_integration.py` →
  `1 passed, 7 skipped`; `tests/test_settings_api.py` → `16 skipped`.
- Fenced files are untouched: `plans/001`, `plans/002` (still the pre-existing
  38-line diff), `docs/project-plan/`, and `.env`. No `src/` change comes from
  this plan.

### Plan correction found during review

The Step 4 verify `git grep -nE '"username"[:=] *"[a-z-]+"' -- tests/` does not
return "only `stub-owner`/`stub-foreign`". It also matches unrelated pre-existing
stub payloads in out-of-scope modules (`test_auth_flow.py` `bob`,
`test_auth_session_model.py` `alice`, `test_settings_user_management_page.py`
`alice`, create-user payloads in `test_admin_users_api.py`). Those are arbitrary
fixtures for accounts that are not seeded, and none is passed to `Principal` as a
seeded username. The criterion is corrected in Step 4 below; the governing check
is the `"app-admin"` / `"app-user"` absence grep, which passes.

### Operator actions still outstanding

1. Rename the three variables in `.env` and add
   `TEST_SUITE_WBA_ADMIN_USERNAME=app-admin` / `TEST_SUITE_WBA_USER_USERNAME=app-user`.
   (**Done 2026-11-13** — the `.env` keys are `APP_ADMIN_PASSWORD`,
   `APP_USER_PASSWORD`, `KEYCLOAK_CONSOLE_ADMIN_PASSWORD`, and both usernames are
   set.)
2. Create GitHub repository variables `TEST_SUITE_WBA_ADMIN_USERNAME` and
   `TEST_SUITE_WBA_USER_USERNAME`. Until they exist the `pytest-unit` job fails at
   collection. (**Outstanding** — the workflow now references these exact names.)
3. Re-seed Keycloak so the renamed users exist — this also completes plan 004's
   pending Step 6, so both plans land on one re-seed. (**Done 2026-11-13**, with
   plan 006's `requiredActions` fix; `app-admin` was forced to change its
   password and `app-user`'s action is pending its first login.)

## Status

- **Priority**: P2
- **Effort**: M
- **Risk**: MED
- **Depends on**: plan 004 (DONE in the working tree, uncommitted). This plan
  renames names that 004 introduced; it must land after 004.
- **Category**: tech-debt
- **Planned at**: working tree on top of commit `bfa5d8f0`, 2026-11-13

## Why this matters

The two seeded application users are named `dev-admin` and `dev-user`, and three
environment variables carry the `DEV_` prefix. Nothing about either account is a
development artefact: they are the default application logins of the realm, they
exist in every environment that imports the realm template, and one of them holds
`admin`. Calling them "dev" invites the reading that they are a local-only
convenience and safe to keep at their seeded passwords.

The rename to `app-admin` / `app-user` also removes a naming collision. Keycloak
already calls the **master-realm console** account its "bootstrap admin"
(`KC_BOOTSTRAP_ADMIN_USERNAME` in `docker-compose.yml`, and `kc.sh bootstrap-admin`
in `IAM_ADMIN_GUIDE.md`). Plan 004 introduced `DEV_WBA_*_BOOTSTRAP_PASSWORD` for
the *application* users, so two unrelated credentials both read as "bootstrap".
This plan gives the application users an unambiguous name and renames the console
variable to the un-ambiguous `KEYCLOAK_CONSOLE_ADMIN_PASSWORD`.

The second half of the plan removes the last hardcoded copy of the usernames.
After plan 004 the usernames were deleted from `src/common/auth/pkce_login.py`,
but `tests/` still hardcodes them in seven `unit` modules and the live suite still
holds them in constants. This plan makes every test read the username from the
environment, so a future rename touches the realm template and `.env` only.

## Current state

### The seeded users — `deploy/keycloak/realm-wba.json.template`

The `"users"` array starts at line 92 and seeds four users. The first two are the
application users; the last two are `service-account-*` and carry no
`credentials` block. Lines 92–131 today:

```json
  "users": [
    {
      "username": "dev-admin",
      "enabled": true,
      "emailVerified": true,
      "email": "dev-admin@wba.invalid",
      "firstName": "Dev",
      "lastName": "Admin",
      "realmRoles": [
        "admin",
        "user"
      ],
      "credentials": [
        {
          "type": "password",
          "value": "${DEV_WBA_ADMIN_BOOTSTRAP_PASSWORD}",
          "temporary": true
        }
      ]
    },
    {
      "username": "dev-user",
      "enabled": true,
      "emailVerified": true,
      "email": "dev-user@wba.invalid",
      "firstName": "Dev",
      "lastName": "User",
      "realmRoles": [
        "user"
      ],
      "credentials": [
        {
          "type": "password",
          "value": "${DEV_WBA_USER_BOOTSTRAP_PASSWORD}",
          "temporary": true
        }
      ]
    },
```

`"temporary": true` is plan 004's work and **must not change** — this plan only
renames the identifiers around it. The `service-account-*` users are untouched.

### The renderer — `deploy/keycloak/entrypoint.sh`

Lines 12–13 are the presence guards; lines 19–22 the substitution loop:

```bash
: "${DEV_WBA_ADMIN_BOOTSTRAP_PASSWORD:?DEV_WBA_ADMIN_BOOTSTRAP_PASSWORD must be set}"
: "${DEV_WBA_USER_BOOTSTRAP_PASSWORD:?DEV_WBA_USER_BOOTSTRAP_PASSWORD must be set}"
```

```bash
for name in APP_PUBLIC_BASE_URL KEYCLOAK_CLIENT_SECRET \
            KEYCLOAK_SERVICE_CLIENT_SECRET KEYCLOAK_ADMIN_CLIENT_ID \
            KEYCLOAK_ADMIN_CLIENT_SECRET DEV_WBA_ADMIN_BOOTSTRAP_PASSWORD \
            DEV_WBA_USER_BOOTSTRAP_PASSWORD; do
```

The `case` guard immediately below aborts the container if any `${...}` survives,
so a renamed variable missing from this loop fails at startup instead of
importing a literal placeholder. That guard is what makes the rename safe.

### The compose service — `docker-compose.yml` lines 43–46

```yaml
      KC_BOOTSTRAP_ADMIN_USERNAME: admin
      KC_BOOTSTRAP_ADMIN_PASSWORD: ${DEV_KEYCLOAK_ADMIN_PASSWORD}
      DEV_WBA_ADMIN_BOOTSTRAP_PASSWORD: ${DEV_WBA_ADMIN_BOOTSTRAP_PASSWORD}
      DEV_WBA_USER_BOOTSTRAP_PASSWORD: ${DEV_WBA_USER_BOOTSTRAP_PASSWORD}
```

Note the second line: `KC_BOOTSTRAP_ADMIN_PASSWORD` is Keycloak's **master-realm
console** account and is a different credential from the two application users.

### The generator — `scripts/setup.sh` lines 326–336

```bash
KEYCLOAK_SECRET_KEYS=(
    "KEYCLOAK_DB_PASSWORD"
    "KEYCLOAK_CLIENT_SECRET"
    "KEYCLOAK_SERVICE_CLIENT_SECRET"
    "KEYCLOAK_ADMIN_CLIENT_SECRET"
    "DEV_WBA_ADMIN_BOOTSTRAP_PASSWORD"
    "DEV_WBA_USER_BOOTSTRAP_PASSWORD"
    "DEV_KEYCLOAK_ADMIN_PASSWORD"
)
```

`setup.sh` creates `.env` by copying `.env.example` (line 112) and then fills any
`FIXME`-or-empty value in this array with a generated secret. **`TEST_SUITE_*`
must stay out of this array** — plan 004's maintenance notes explain why (a
generated value is set-but-wrong, which the suites read as configured).

### The env template — `.env.example` lines 210–228

```
# First-login bootstrap passwords for the two `wba`-realm APPLICATION users,
# rendered into the realm by entrypoint.sh. dev-admin (roles admin + user) and
# dev-user (role user) are seeded with these as TEMPORARY credentials: Keycloak
# forces a password change at first login and the changed value is not written
# back here. The live test suites use their own credentials below instead.
DEV_WBA_ADMIN_BOOTSTRAP_PASSWORD=FIXME
DEV_WBA_USER_BOOTSTRAP_PASSWORD=FIXME
# Credentials for the `admin` and `user` accounts the live test suites log in
# as. Leave at FIXME to skip those suites; set to real credentials to run them.
TEST_SUITE_WBA_ADMIN_USERNAME=FIXME
TEST_SUITE_WBA_ADMIN_PASSWORD=FIXME
TEST_SUITE_WBA_USER_USERNAME=FIXME
TEST_SUITE_WBA_USER_PASSWORD=FIXME
# Password for the Keycloak master-realm bootstrap admin (username is the
# literal `admin`). This is the ADMIN CONSOLE account — it is NOT an
# application login and has no wba-realm roles. Created only on the first boot
# against an empty Keycloak database; see IAM_ADMIN_GUIDE.md for the recovery
# command if it is missing.
DEV_KEYCLOAK_ADMIN_PASSWORD=FIXME
```

### The nine hardcoded usernames in `tests/`

Plan 004 deleted the role→username binding from `src/` and from
`tests/auth_helpers.py` / `tests/test_auth_integration.py`, but left these:

| File | Lines | Form |
|---|---|---|
| `tests/test_admin_users_api.py` | 26–27 | `Principal(subject=..., username="dev-admin"/"dev-user")` |
| `tests/test_authz_enforcement.py` | 34–35 | same, in a `_PRINCIPALS` dict |
| `tests/test_connectors_secrets_gating.py` | 35–36, 141 | same; line 141 asserts `"dev-user" in caplog.text` |
| `tests/test_auth_tokens.py` | 310, 318, 332 | `_sign(username="dev-user")` and a `principal.username == "dev-user"` assert |
| `tests/test_chat_ownership.py` | 28–31 | `Principal(... username="dev-owner"/"dev-foreign"/"dev-admin")` |
| `tests/test_ui_account_bar_signed_out.py` | 127–170 | stub JSON `{"username": "dev-user", "full_name": "Dev User"}` |
| `tests/test_ui_session_guard_stale.py` | 96, 193, 199 | stub JSON `{"username": "dev-user"}` |
| `tests/test_catalog_metadata_api.py` | 19 | docstring only (`a ``dev-user`` row`) |

Every one of these is a `unit`-marked module except
`tests/test_catalog_metadata_api.py`, which is `integration`/`server`-marked and
already imports `env_value`. None of them contacts Keycloak: the strings are
fixture data.

### Which environment variables exist today

| Variable | Holds | Renamed to |
|---|---|---|
| `DEV_WBA_ADMIN_BOOTSTRAP_PASSWORD` | `dev-admin`'s first-login password | `APP_ADMIN_PASSWORD` |
| `DEV_WBA_USER_BOOTSTRAP_PASSWORD` | `dev-user`'s first-login password | `APP_USER_PASSWORD` |
| `DEV_KEYCLOAK_ADMIN_PASSWORD` | the **master-realm console** admin password | `KEYCLOAK_CONSOLE_ADMIN_PASSWORD` |
| `TEST_SUITE_WBA_ADMIN_USERNAME` | the admin test account's username | unchanged (now carries a real value) |
| `TEST_SUITE_WBA_USER_USERNAME` | the user test account's username | unchanged (now carries a real value) |
| `TEST_SUITE_WBA_ADMIN_PASSWORD` | the admin test account's password | unchanged, stays `FIXME` |
| `TEST_SUITE_WBA_USER_PASSWORD` | the user test account's password | unchanged, stays `FIXME` |

**Usernames are not secrets.** They are already committed in the realm template.
Passwords are, and every password variable keeps `FIXME` in `.env.example`.

### The CI unit job — `.github/workflows/pr_checks.yml` lines 8–17

```yaml
jobs:
  pytest-unit:
    runs-on: ubuntu-latest
    env:
      PYTHONPATH: ${{ github.workspace }}:${{ github.workspace }}/src
      DATABASE_URL: postgresql+asyncpg://username:pwd@localhost:5432/postgres
      OPENAI_API_KEY: "sk-test-dummy-key-for-ci"
      LLM_MODEL: "gpt-4o"
      GITHUB_MCP_ENABLED: "false"
```

CI checks out the repository fresh: **there is no `.env`**, so every variable
must come from the job's `env:` block. The repository does not use
`${{ vars.* }}` anywhere today.

### Repo conventions that apply

- Type hints on every parameter and return; `X | None`; built-in generics.
- Default to no comments. Never narrate the change.
- `from common.logger import logger`; never `print()`.
- **Code must not contain a username literal.** A username lives in the realm
  template (which defines the account) and in `.env` (which the tests read). Test
  modules, fixtures and helpers read it through `tests/auth_helpers.py`.
- Never commit, push, or create a branch.

## Commands you will need

Run from the repository root with the virtualenv active (`source .venv/bin/activate`).

| Purpose | Command | Expected on success |
|---|---|---|
| Unit tests | `PYTHONPATH=src pytest -m unit tests -q` | exit 0 |
| Typecheck | `mypy src/` | exit 0, `Success: no issues found` |
| Lint | `pylint src --score=y` | `10.00/10` |
| Style (touched files) | `.venv/bin/flake8 src/common/auth/__init__.py` | exit 0 |
| Template still valid JSON | see Step 1 | `rendered JSON parses; 0 unsubstituted placeholders` |
| Compose still valid | `docker compose config -q` | exit 0 (warnings about unset vars are expected) |

`flake8` is scoped to the one `src/` file this plan touches. **Bare `flake8` does
not exit 0 on this tree** — it carries ~1500 pre-existing findings outside its
`.flake8` exclude list (`.flake8` sets `extend-exclude = .venv,tests`). It is not
a CI gate. Do not reflow unrelated files to make it pass.

## Scope

**In scope** (the only files you may modify):

- `deploy/keycloak/realm-wba.json.template` — usernames, emails, `firstName`,
  and the two password placeholders
- `deploy/keycloak/entrypoint.sh` — guards and substitution loop
- `docker-compose.yml` — the three environment keys and their values (lines 44–46)
- `.env.example` — the three renamed variables, the four `TEST_SUITE_*` values,
  and their comments
- `scripts/setup.sh` — the `KEYCLOAK_SECRET_KEYS` array
- `.github/workflows/pr_checks.yml` — the `pytest-unit` `env:` block
- `tests/auth_helpers.py` — add `realm_username()`
- `tests/test_admin_users_api.py`
- `tests/test_authz_enforcement.py`
- `tests/test_connectors_secrets_gating.py`
- `tests/test_auth_tokens.py`
- `tests/test_chat_ownership.py`
- `tests/test_ui_account_bar_signed_out.py`
- `tests/test_ui_session_guard_stale.py`
- `tests/test_catalog_metadata_api.py` — the docstring only
- `INSTALL_GUIDE.md`, `DEVELOPER_QUICK_START.md`, `IAM_ADMIN_GUIDE.md`, `CLAUDE.md`
- `docs/design/authn-authz-design.md`
- `plans/README.md` — status row only

**Out of scope** (do NOT touch, even though they look related):

- `plans/001-admin-user-management.md`,
  `plans/002-rename-realm-roles-and-clients.md`,
  `plans/004-one-time-bootstrap-passwords.md` — DONE plans. They cite the old
  usernames as evidence of what was verified at a past date. Editing them makes a
  historical record claim a name that did not exist then. Leave them
  byte-identical.
- `docs/project-plan/` (including `completed/`) — same reason.
- `src/common/auth/pkce_login.py`, `tests/auth_helpers.py`'s existing
  `_TEST_ROLES`/`configured`/`credentials` — plan 004 already removed the
  hardcoded usernames from them; only the new `realm_username()` is added.
- `tests/test_auth_integration.py` — plan 004 already made it read
  `TEST_SUITE_WBA_*`; it needs no change for this plan.
- `tests/conftest.py` — its autouse bearer fixture reads no username.
- `docs/design/activity-timeline-design.md` and every other "dev" mention that is
  **not** one of the two seeded users (dev-only mock mode, "local dev stack",
  `start-dev`, `/dev/null`). Those are correct uses of the word. Do not touch
  them. In particular `deploy/keycloak/entrypoint.sh` contains
  `kc.sh start-dev --import-realm` and `docker-compose.yml` contains
  `command: ["start-dev", ...]` — leave both.
- `docs/design/authn-authz-design.md` line 150 says `| Dev users |`. Rename the
  row label to `Application users`; do not restructure the table.
- Any `.env` file (gitignored) — Step 7 is an operator action.

## Git workflow

- Work in the current working tree, on the current branch. Do NOT create a
  branch or worktree, and do NOT commit.
- Do NOT run `git commit`, `git push`, `git checkout`, `git stash`,
  `git restore`, `git reset`, or `git clean`.
- Do NOT run any `docker compose` command that starts, stops, builds or recreates
  a container. `docker compose config -q` is allowed (read-only).
- Do not edit `.env`, `.env.fixme-*`, or `.env.last_good`.

## Implementation

### Step 1 — rename the seeded users in the realm template

In `deploy/keycloak/realm-wba.json.template`, change six strings and two
placeholders. Change nothing else.

| Line | From | To |
|---|---|---|
| 94 | `"username": "dev-admin",` | `"username": "app-admin",` |
| 97 | `"email": "dev-admin@wba.invalid",` | `"email": "app-admin@wba.invalid",` |
| 98 | `"firstName": "Dev",` | `"firstName": "Application",` |
| 107 | `"value": "${DEV_WBA_ADMIN_BOOTSTRAP_PASSWORD}",` | `"value": "${APP_ADMIN_PASSWORD}",` |
| 113 | `"username": "dev-user",` | `"username": "app-user",` |
| 116 | `"email": "dev-user@wba.invalid",` | `"email": "app-user@wba.invalid",` |
| 117 | `"firstName": "Dev",` | `"firstName": "Application",` |
| 125 | `"value": "${DEV_WBA_USER_BOOTSTRAP_PASSWORD}",` | `"value": "${APP_USER_PASSWORD}",` |

Both `"temporary": true` flags stay exactly as they are. `"lastName"` stays
`"Admin"` / `"User"`. The `service-account-*` users are untouched.

**Verify** — render the template with dummy values and parse it:

```bash
PYTHONPATH=src .venv/bin/python - <<'PY'
import json, re, pathlib
tpl = pathlib.Path("deploy/keycloak/realm-wba.json.template").read_text()
names = ["APP_PUBLIC_BASE_URL","KEYCLOAK_CLIENT_SECRET","KEYCLOAK_SERVICE_CLIENT_SECRET",
         "KEYCLOAK_ADMIN_CLIENT_ID","KEYCLOAK_ADMIN_CLIENT_SECRET",
         "APP_ADMIN_PASSWORD","APP_USER_PASSWORD"]
out = tpl
for n in names:
    out = out.replace("${%s}" % n, "dummy")
print("unsubstituted:", re.findall(r"\$\{[A-Z_]+\}", out))
doc = json.loads(out)
print("usernames:", [u["username"] for u in doc["users"]])
print("temporary flags:", [(u["username"], c["temporary"]) for u in doc["users"] for c in u.get("credentials", [])])
PY
```

Expected:

```
unsubstituted: []
usernames: ['app-admin', 'app-user', 'service-account-internal', 'service-account-admin-api']
temporary flags: [('app-admin', True), ('app-user', True)]
```

### Step 2 — rename in the renderer, compose, generator and env template

**`deploy/keycloak/entrypoint.sh`** — rename both guards and both names in the
substitution loop:

```bash
: "${APP_ADMIN_PASSWORD:?APP_ADMIN_PASSWORD must be set}"
: "${APP_USER_PASSWORD:?APP_USER_PASSWORD must be set}"
```

```bash
for name in APP_PUBLIC_BASE_URL KEYCLOAK_CLIENT_SECRET \
            KEYCLOAK_SERVICE_CLIENT_SECRET KEYCLOAK_ADMIN_CLIENT_ID \
            KEYCLOAK_ADMIN_CLIENT_SECRET APP_ADMIN_PASSWORD \
            APP_USER_PASSWORD; do
```

**`docker-compose.yml`** — lines 44–46, both the keys and their `${...}` values:

```yaml
      KC_BOOTSTRAP_ADMIN_PASSWORD: ${KEYCLOAK_CONSOLE_ADMIN_PASSWORD}
      APP_ADMIN_PASSWORD: ${APP_ADMIN_PASSWORD}
      APP_USER_PASSWORD: ${APP_USER_PASSWORD}
```

`KC_BOOTSTRAP_ADMIN_USERNAME: admin` on line 43 is Keycloak's own console
command and does **not** change.

**`scripts/setup.sh`** — line 318's comment says "All six are generated" but the
array holds seven. Update it to "All seven" while you are in the block. The
`KEYCLOAK_SECRET_KEYS` array becomes:

```bash
KEYCLOAK_SECRET_KEYS=(
    "KEYCLOAK_DB_PASSWORD"
    "KEYCLOAK_CLIENT_SECRET"
    "KEYCLOAK_SERVICE_CLIENT_SECRET"
    "KEYCLOAK_ADMIN_CLIENT_SECRET"
    "APP_ADMIN_PASSWORD"
    "APP_USER_PASSWORD"
    "KEYCLOAK_CONSOLE_ADMIN_PASSWORD"
)
```

Do not add `TEST_SUITE_*` or any `*_USERNAME` entry to this array.

**`.env.example`** — replace lines 210–228 with:

```
# First-login passwords for the two `wba`-realm APPLICATION users, rendered into
# the realm by entrypoint.sh. app-admin (roles admin + user) and app-user (role
# user) are seeded with these as TEMPORARY credentials: Keycloak forces a
# password change at first login and the changed value is not written back here.
# The live test suites use their own credentials below instead.
APP_ADMIN_PASSWORD=FIXME
APP_USER_PASSWORD=FIXME
# Usernames of the two seeded application users, and the passwords the live
# `server`-marked suites log in with. The usernames are not secrets — they are
# defined by deploy/keycloak/realm-wba.json.template. Leave a password at FIXME
# and the suites skip.
TEST_SUITE_WBA_ADMIN_USERNAME=app-admin
TEST_SUITE_WBA_ADMIN_PASSWORD=FIXME
TEST_SUITE_WBA_USER_USERNAME=app-user
TEST_SUITE_WBA_USER_PASSWORD=FIXME
# Password for the Keycloak master-realm CONSOLE admin (username is the literal
# `admin`). This is the ADMIN CONSOLE account — it is NOT an application login
# and has no wba-realm roles. Created only on the first boot against an empty
# Keycloak database; see IAM_ADMIN_GUIDE.md for the recovery command if it is
# missing.
KEYCLOAK_CONSOLE_ADMIN_PASSWORD=FIXME
```

**Verify**:

- `grep -c "DEV_WBA\|DEV_KEYCLOAK" .env.example deploy/keycloak/entrypoint.sh docker-compose.yml scripts/setup.sh` → `0` for every file
- `grep -n "APP_ADMIN_PASSWORD\|APP_USER_PASSWORD\|KEYCLOAK_CONSOLE_ADMIN_PASSWORD" .env.example` → 3 lines, then the four `TEST_SUITE_*` lines
- `grep -c "TEST_SUITE" scripts/setup.sh` → `0`
- `docker compose config -q` → exit 0

> `docker compose config` prints warnings that `APP_ADMIN_PASSWORD`,
> `APP_USER_PASSWORD` and `KEYCLOAK_CONSOLE_ADMIN_PASSWORD` are unset. That is
> expected: the live `.env` still holds the old names until Step 7, which is
> operator work. Do not edit `.env` to silence the warnings.

### Step 3 — add `realm_username()` to `tests/auth_helpers.py`

Add one function beside the existing `configured()`. It reads the username from
the environment and **fails loudly** when unset — there is no default, because a
default would be the hardcoded username this plan exists to remove.

```python
def realm_username(role: str) -> str:
    """Return the configured realm username for *role*, from the environment only."""
    var = _TEST_ROLES[role][0]
    value = env_value(var).strip()
    if not configured(var):
        raise RuntimeError(
            f"{var} is unset or still FIXME — set it in .env (see .env.example)."
        )
    return value
```

`_TEST_ROLES` already maps `"admin"` → `("TEST_SUITE_WBA_ADMIN_USERNAME", ...)`
and `"user"` → `("TEST_SUITE_WBA_USER_USERNAME", ...)` (plan 004). Do not
duplicate that mapping.

**Do not name this function `test_username`.** Pytest collects every callable
whose name starts with `test_` from a module's namespace — including one
imported into a test module — and would then run it as a test, failing with
`fixture 'role' not found`. Verified: importing a `test_username(role)` into a
`test_*.py` module yields `ERROR ...::test_username`. `realm_username` is not
collected.

Do **not** make this function return a fallback. Do **not** put a username
literal in this file or in any test module.

**Verify**: `grep -n "def realm_username" tests/auth_helpers.py` → one match, and
`grep -cE "dev-admin|dev-user" tests/auth_helpers.py` → `0`.

### Step 4 — make the seven `unit` modules read the username

Each module below currently builds a `Principal` (or stub JSON) with a literal
username at **module import time**. Replace the literal with
`realm_username("<role>")`, importing it from `tests.auth_helpers`.

The module-level call is deliberate: these modules have no fixture that could
supply the value, and a missing variable should fail immediately and name the
variable — not silently produce `username=""` and fail an unrelated assertion
later. CI sets the variables (Step 5) and a local `.env` sets them (Step 2), so
the call always resolves in a configured tree.

**`tests/test_admin_users_api.py`** lines 26–27:

```python
ADMIN = Principal(subject="a-1", username=realm_username("admin"), roles=frozenset({"admin"}))
USER = Principal(subject="u-1", username=realm_username("user"), roles=frozenset({"user"}))
```

Add `from tests.auth_helpers import realm_username` to the import block.

**`tests/test_authz_enforcement.py`** lines 34–35 — same substitution inside the
`_PRINCIPALS` dict, same import.

**`tests/test_connectors_secrets_gating.py`** lines 35–36 — same substitution in
`_PRINCIPALS`. Additionally line 141 asserts a log message contains the username:

```python
assert "u-1" in caplog.text or realm_username("user") in caplog.text
```

**`tests/test_auth_tokens.py`** — three sites. Where a token is signed, use
`username=realm_username("user")`; where the assertion compares it back, compare
against the same call:

```python
        username = realm_username("user")
        token = _sign(private_pem, sub="kc-user-id", username=username, roles=("user",), ...)
        ...
        assert principal.username == username
```

Add the import. Do not change `sub`, `roles`, `aud`, `azp` or `iss`.

**`tests/test_chat_ownership.py`** lines 28–31 — three principals. `dev-admin`
becomes `realm_username("admin")`. `dev-owner` and `dev-foreign` are **not**
seeded accounts; they are arbitrary stubs, so rename them to `stub-owner` and
`stub-foreign` (a plain string is correct here — no environment variable is
needed for a fixture that models "some other user"). Add the `realm_username`
import.

**`tests/test_ui_account_bar_signed_out.py`** — every stub payload's
`"username": "dev-user"` becomes `realm_username("user")`, and every
`assert "dev-user" in texts` becomes `assert realm_username("user") in texts`.
Line 141's `"full_name": "Dev User"` becomes `"full_name": "App User"`, and
lines 147's `assert "Dev User" in texts` becomes `assert "App User" in texts`.
Add the import.

**`tests/test_ui_session_guard_stale.py`** lines 96, 193, 199 — the stub JSON
`{"username": "dev-user"}` becomes `{"username": realm_username("user")}`. Add the
import.

**`tests/test_catalog_metadata_api.py`** line 19 — the docstring sentence
`a ``dev-user`` row is invisible to an admin read` becomes
`an ``app-user`` row is invisible to an admin read`. This module already imports
`env_value` and needs no code change; the usernames it logs in with come from
`tests/auth_helpers.py` already.

**Verify**:

- `git grep -nE "dev-admin|dev-user|dev-owner|dev-foreign" -- tests/` → no output
- `git grep -nE '"username"[:=] *"[a-z-]+"' -- tests/` → only `stub-owner`/`stub-foreign` and `"a-1"`-style subjects if any; **no username literal passed to `Principal`**
- With the variables present in the environment:
  `TEST_SUITE_WBA_ADMIN_USERNAME=app-admin TEST_SUITE_WBA_USER_USERNAME=app-user PYTHONPATH=src pytest -m unit tests/test_admin_users_api.py tests/test_authz_enforcement.py tests/test_connectors_secrets_gating.py tests/test_auth_tokens.py tests/test_chat_ownership.py tests/test_ui_account_bar_signed_out.py tests/test_ui_session_guard_stale.py -q`
  → all pass.

### Step 5 — supply the usernames in CI

The `pytest-unit` job checks out a tree with no `.env`, so the two username
variables must come from the job environment. Add them to the existing `env:`
block (`.github/workflows/pr_checks.yml` lines 12–17), **referencing repository
variables — never a literal**.

Use **one name for both layers**: the repository variable and the job environment
variable are spelled identically, so `TEST_SUITE_WBA_ADMIN_USERNAME` is the repo
variable's name *and* the variable name the Python code reads. This keeps the
`${{ vars.X }}` lookup and the `env:` key from drifting apart, and means whoever
sets the repository variable types exactly the name `tests/auth_helpers.py`
already uses.

```yaml
    env:
      PYTHONPATH: ${{ github.workspace }}:${{ github.workspace }}/src
      DATABASE_URL: postgresql+asyncpg://username:pwd@localhost:5432/postgres
      OPENAI_API_KEY: "sk-test-dummy-key-for-ci"
      LLM_MODEL: "gpt-4o"
      GITHUB_MCP_ENABLED: "false"
      TEST_SUITE_WBA_ADMIN_USERNAME: ${{ vars.TEST_SUITE_WBA_ADMIN_USERNAME }}
      TEST_SUITE_WBA_USER_USERNAME: ${{ vars.TEST_SUITE_WBA_USER_USERNAME }}
```

The repository settings must define `TEST_SUITE_WBA_ADMIN_USERNAME` and
`TEST_SUITE_WBA_USER_USERNAME` (Settings → Secrets and variables → Actions →
Variables). **This is an operator action you cannot perform from this tree** — see
Step 7.

`${{ vars.X }}` resolves against a repository variable named exactly `X`; a
mismatch yields an empty string, which makes `realm_username()` raise at
collection — the failure this step exists to prevent. There is no longer a
short-name/long-name mapping to get wrong.

**Verify**: `grep -n "vars\.TEST_SUITE_WBA_" .github/workflows/pr_checks.yml` →
the two new lines. `git grep -nE '"app-admin"|"app-user"' -- tests/ .github/` →
no output (the literal must not appear in code or CI config).

### Step 6 — update the documentation

Every change below replaces "dev" naming for the two seeded users. **Do not
touch "dev" where it means something else** (dev-only mock mode, "local dev
stack", `start-dev`, `/dev/null`, "developer").

- `INSTALL_GUIDE.md`
  - Lines 115–116: the two table rows become `APP_ADMIN_PASSWORD` / `APP_USER_PASSWORD`, described as first-login passwords for the seeded `app-admin` / `app-user` application logins.
  - Line 117: `DEV_KEYCLOAK_ADMIN_PASSWORD` → `KEYCLOAK_CONSOLE_ADMIN_PASSWORD`.
  - Line 119: "Sign in as `dev-admin` or `dev-user`" → "`app-admin` or `app-user`".
  - Line 127: `DEV_KEYCLOAK_ADMIN_PASSWORD` → `KEYCLOAK_CONSOLE_ADMIN_PASSWORD`.
  - Line 108 says "The wizard generates six credentials" and the table lists six rows, but `scripts/setup.sh` generates **seven** (`KEYCLOAK_ADMIN_CLIENT_SECRET` is missing from the table). Change "six" to "seven" and add the missing row: `` | `KEYCLOAK_ADMIN_CLIENT_SECRET` | Secret for the `admin-api` client (the API's Keycloak admin token) | ``. This is a pre-existing inaccuracy in the table you are already editing; fix it in the same edit.
- `DEVELOPER_QUICK_START.md` lines 59–61: as `app-admin` / `app-user`; the bootstrap variables become `APP_ADMIN_PASSWORD` / `APP_USER_PASSWORD`. Keep the existing note that Keycloak forces a change at first login and that the suites skip while `TEST_SUITE_*` passwords are `FIXME`.
- `IAM_ADMIN_GUIDE.md`
  - Line 57, 62: `DEV_KEYCLOAK_ADMIN_PASSWORD` → `KEYCLOAK_CONSOLE_ADMIN_PASSWORD`.
  - Line 65, 67: same rename; line 67's contrast is now against `APP_ADMIN_PASSWORD`.
  - Line 68: `dev-admin` → `app-admin`.
  - Line 72 callout heading and lines 75–76: `dev-admin` / `dev-user` → `app-admin` / `app-user`.
  - Line 135, 149: `DEV_KEYCLOAK_ADMIN_PASSWORD` → `KEYCLOAK_CONSOLE_ADMIN_PASSWORD`.
  - Line 175: the glob `dev-*` users → `app-*` users.
  - Line 260: "seeded dev users" → "seeded application users".
- `CLAUDE.md` line 238: rename the three variables and the two usernames in the trailing note. Keep the sentence's substance: they are on neither settings class, they are consumed by `entrypoint.sh` and `setup.sh`, they are rendered as one-time first-login credentials, and the suites read `TEST_SUITE_WBA_*` from `.env`.
- `docs/design/authn-authz-design.md`
  - Line 150: the row label `| Dev users |` → `| Application users |`, and the usernames to `app-admin` / `app-user`.
  - Line 156: "The dev users' seeded passwords" → "The application users' seeded passwords".
  - Line 610: the production checklist names `app-admin` / `app-user` and the `APP_*_PASSWORD` values; keep the sentence's meaning.

**Verify**:

- `git grep -nE "dev-admin|dev-user" -- . ':!plans' ':!docs/project-plan'` → no output
- `git grep -nE "DEV_WBA|DEV_KEYCLOAK" -- . ':!plans'` → no output
- `grep -rn "application login\|application user" INSTALL_GUIDE.md IAM_ADMIN_GUIDE.md | head` → the new wording present

### Step 7 — operator actions (do NOT perform; report them)

These change untracked state and a live GitHub setting. Do not attempt them.
Report that they are required:

1. **`.env` (gitignored).** Rename the three variables and add the two
   usernames:
   ```
   APP_ADMIN_PASSWORD=<existing DEV_WBA_ADMIN_BOOTSTRAP_PASSWORD value>
   APP_USER_PASSWORD=<existing DEV_WBA_USER_BOOTSTRAP_PASSWORD value>
   KEYCLOAK_CONSOLE_ADMIN_PASSWORD=<existing DEV_KEYCLOAK_ADMIN_PASSWORD value>
   TEST_SUITE_WBA_ADMIN_USERNAME=app-admin
   TEST_SUITE_WBA_USER_USERNAME=app-user
   ```
   Until this is done, `entrypoint.sh`'s `:?` guards abort Keycloak on its next
   recreate because the new names are absent.
2. **GitHub repository variables** `TEST_SUITE_WBA_ADMIN_USERNAME=app-admin` and
   `TEST_SUITE_WBA_USER_USERNAME=app-user` (Settings → Secrets and variables →
   Actions → **Variables**, not Secrets — `${{ vars.* }}` does not read secrets).
   The repository-variable name and the job environment-variable name are the
   same string, so the value the code reads is exactly the name you type. Until
   these exist, the `pytest-unit` job fails at collection with
   `TEST_SUITE_WBA_ADMIN_USERNAME is unset or still FIXME`.
3. **Re-seed Keycloak** so the renamed users exist. `--import-realm` is
   create-only, so an existing realm keeps `dev-admin` / `dev-user` forever
   until the database is dropped. Follow `IAM_ADMIN_GUIDE.md`'s "The normal
   path: re-seed the realm". This creates fresh login sessions and discards the
   old users; it also satisfies plan 004's pending Step 6.

### Step 8 — final verification

- `PYTHONPATH=src pytest -m unit tests -q` → all pass. If the two username
  variables are not in the environment, run it as
  `TEST_SUITE_WBA_ADMIN_USERNAME=app-admin TEST_SUITE_WBA_USER_USERNAME=app-user PYTHONPATH=src pytest -m unit tests -q`
  and report which form you used.
- `mypy src/` → `Success: no issues found`
- `pylint src --score=y` → `10.00/10`
- `.venv/bin/flake8 src/common/auth/__init__.py` → exit 0 (no `src/` file is
  actually modified by this plan; this confirms the gate the CI runs)
- `docker compose config -q` → exit 0
- `git status --porcelain` → only the in-scope files, plus plan 004's own
  already-modified files and `plans/004-*` untracked

## Test plan

This plan changes no behaviour, so it adds no test. Its correctness is proven by
the existing `unit` suite passing with the usernames supplied from the
environment, and by these negative checks, which are the ones a regression would
break:

| Check | Command | Why it matters |
|---|---|---|
| No username literal in code | `git grep -nE '"app-admin"|"app-user"|"dev-admin"|"dev-user"' -- tests/ .github/ scripts/ src/` → no output | The whole point of the plan: a username lives only in `.env` and the realm template |
| The helper refuses an unset variable | `PYTHONPATH=src .venv/bin/python -c "from tests.auth_helpers import realm_username; realm_username('user')"` with the variable unset → `RuntimeError` naming `TEST_SUITE_WBA_USER_USERNAME` | Proves there is no hidden fallback |
| The helper reads a set variable | `TEST_SUITE_WBA_USER_USERNAME=someone PYTHONPATH=src .venv/bin/python -c "from tests.auth_helpers import realm_username; print(realm_username('user'))"` → `someone` | Proves it is wired to the environment |
| `FIXME` is refused | `TEST_SUITE_WBA_USER_USERNAME=FIXME PYTHONPATH=src .venv/bin/python -c "from tests.auth_helpers import realm_username; realm_username('user')"` → `RuntimeError` | `FIXME` is truthy; a bare truthiness check would accept it |

Report the actual output of each.

## Done criteria

All must hold:

- [ ] `grep -c '"temporary": true' deploy/keycloak/realm-wba.json.template` → `2` (unchanged from plan 004)
- [ ] The rendered template parses as JSON with usernames `app-admin`, `app-user` and no `dev-` users (Step 1 command)
- [ ] `git grep -nE "DEV_WBA|DEV_KEYCLOAK" -- . ':!plans'` → no output
- [ ] `git grep -nE "dev-admin|dev-user" -- . ':!plans' ':!docs/project-plan'` → no output
- [ ] `git grep -nE '"app-admin"|"app-user"' -- tests/ .github/ scripts/ src/` → no output
- [ ] `grep -c "TEST_SUITE" scripts/setup.sh` → `0`
- [ ] `grep -n "vars.WBA_" .github/workflows/pr_checks.yml` → the two lines
- [ ] `tests/auth_helpers.py` defines `realm_username` and raises rather than returning a fallback
- [ ] `pytest -m unit tests -q` exits 0 with the two username variables supplied
- [ ] `mypy src/` exits 0
- [ ] `pylint src --score=y` → `10.00/10`
- [ ] `docker compose config -q` exits 0
- [ ] `plans/001-*`, `plans/002-*`, `plans/004-*` and `docs/project-plan/` are byte-identical to how you found them
- [ ] No `.env` file was edited and no `docker compose` state-changing command was run
- [ ] Step 7's three operator actions are reported

## STOP conditions

Stop and report (do not improvise) if:

- The drift check shows the working tree lacks plan 004's changes (no
  `DEV_WBA_*_BOOTSTRAP_PASSWORD` in `.env.example`) — this plan was written
  against the post-004 working tree.
- `deploy/keycloak/realm-wba.json.template` does not contain `"temporary": true`
  on both application users, or does not have the four users in the order shown.
- A renamed variable would be needed by a file outside the in-scope list.
  Specifically: if anything in `src/app/`, `src/domain/` or `src/connectors/`
  reads one of the three renamed variables, STOP — the premise that these are
  consumed only by `entrypoint.sh`, `setup.sh` and compose is false.
- A test module turns out to need the username **inside a helper function that
  runs before collection**, so `realm_username()` cannot be satisfied by the CI
  `env:` block. CI supplies the variables, so this should not occur; if it does,
  report it rather than adding a fallback.
- Making the `unit` suite pass appears to require putting a username literal
  anywhere in `tests/`, `scripts/` or `src/`. That is the one thing this plan
  exists to prevent — report instead.
- The `docs/project-plan/` or DONE-plan files appear to need an edit to satisfy
  a grep. They do not: every done-criteria grep excludes them.
- Any command would create a branch, a commit, or change container state.
- The operator actions in Step 7 cannot be described accurately because the
  environment differs from what is recorded here.

## Maintenance notes

- **A username belongs in exactly two places: the realm template that defines
  it, and `.env` that the tests read.** Never in `src/`, `tests/`, `scripts/` or
  CI YAML. If a new test needs the username, call
  `tests.auth_helpers.realm_username(role)`. If a new script needs it, read the
  environment.
- **The repository variables are now a CI dependency.** `WBA_ADMIN_USERNAME` and
  `WBA_USER_USERNAME` must exist in GitHub settings, or the `pytest-unit` job
  fails at collection. A fork or a fresh clone without them will fail the same
  way. That is the deliberate cost of having no fallback; if it proves too
  brittle, the alternative is a `skipif` on the seven modules when the variables
  are unset — a decision to revisit, not to make silently.
- **`KEYCLOAK_CONSOLE_ADMIN_PASSWORD` is not an application credential.** It is
  the `master`-realm console account. It was renamed here only to remove the
  `DEV_` prefix; it has no relationship to `app-admin` beyond the word "admin".
  Keep the distinction in `INSTALL_GUIDE.md` and `IAM_ADMIN_GUIDE.md` visible.
- **A reviewer should scrutinize** that no `dev-admin`/`dev-user` string survives
  outside the historical records, that the four `temporary`/`roles` fields in the
  template are untouched, and that the CI variables are `${{ vars.* }}` rather
  than literals.
- **Plan 004's skip behaviour is preserved.** `configured()` requires both the
  username and the password, and the four `TEST_SUITE_*_PASSWORD` values stay
  `FIXME`, so the live `server` suites still skip until an operator records real
  credentials. Do not populate those passwords in `.env.example`.
- **Deliberately deferred**: rewriting the DONE plans (001, 002, 004) and
  `docs/project-plan/completed/`. They are historical records; a future reader
  should understand that `dev-admin` was the name of what is now `app-admin`.
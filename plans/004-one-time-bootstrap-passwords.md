# Plan 004: Make the seeded dev passwords one-time, and give the live suites their own credentials

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan in
> `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff bfa5d8f0 -- deploy/keycloak src/common/auth scripts/get_token.py tests/auth_helpers.py tests/test_auth_integration.py .env.example docker-compose.yml`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Execution record — 2026-11-13

Steps 1–5, 8 and 9 were executed in the working tree on
`feature/bootstrap-pwds`; all changes are uncommitted. Steps 6 and 7 (the re-seed
and its observations) are operator actions and were not run.

### Plan errors found and corrected before dispatch

Verified against the live tree at `bfa5d8f0` and passed to the executor as plan
errors, so the repository was not bent to match them:

1. Step 5a's `grep -c "TEST_SUITE_WBA" tests/auth_helpers.py` → `4` is a wrong
   expectation: `grep -c` counts lines, and the two-line mapping holds two
   occurrences per line, so it prints `2` (`grep -o … | wc -l` gives `4`).
2. The Done criterion "old names gone" was **structurally unsatisfiable**: this
   plan file quotes both names ~20×, so any repo-wide grep including `plans/`
   matches its own text. Replaced with
   `git grep -nE "DEV_WBA_(ADMIN|USER)_PASSWORD" -- . ':!plans'`.
3. `flake8` → exit 0 is unachievable on this tree: bare `flake8` exits 1 with
   ~1500 pre-existing findings (`.flake8` excludes only `.venv,tests`; the
   `alembic/versions/` and `simulation/` trees carry long-standing debt) and
   flake8 is not a CI gate here. Replaced with a run scoped to the touched
   `src/` and `scripts/` files.
4. Step 5c-i claims all five modules already import from `tests.auth_helpers`.
   `tests/test_graph_router.py` imports it nowhere and needed a new import line,
   not an extension of an existing one.

### Verification evidence

The reviewer re-ran the done criteria rather than reading the executor's report:
`1 passed, 7 skipped` on `tests/test_auth_integration.py` with the pass being
`TestWrongRoleAndCrossUser::test_service_role_is_reader_not_admin`; the five
module-level skips firing at collection (38 skipped in 0.24s, no login attempt);
`configured()` returning False for `FIXME`, unset and blank, and True for a real
value; the rendered realm template parsing as JSON with exactly two
`"temporary": true` credentials on the two dev users and none on the service
accounts; `docker compose config` valid; `mypy src/` clean in 340 files;
`pylint src` 10.00/10; `2765 passed, 2 skipped` on `-m unit`; scoped flake8 exit
0; `get_token.py` failing cleanly on the no-TTY path and minting a 943-byte
service token with no prompt.

### DEFECT — the core premise is false (found 2026-11-13, after the re-seed)

**`"temporary": true` is ignored on Keycloak's realm *import* path.** The plan's
"Why this matters" states the flag "attaches Keycloak's `UPDATE_PASSWORD` required
action". On `--import-realm` it does not. Measured on the live stack
(Keycloak 26.8.1):

- `user_required_action` held **0 rows** after a clean re-seed, for both seeded
  users.
- `required_action_provider` had `Update Password` **enabled** for the `wba`
  realm, so the provider was not the problem.
- The container's rendered
  `/opt/keycloak/data/import/realm-wba.json` **did** carry
  `app-admin [('password', True)]`, so the template and the renderer were both
  correct.
- A four-cell probe in throwaway realms (since deleted) isolated it:
  the **admin-API** path honours `temporary: true`; the **realm-import** path
  does not. Explicitly adding `requiredActions: ["UPDATE_PASSWORD"]` works on
  both.

Consequence: a user signing in as `app-admin` is **not** prompted to change the
password. The bootstrap value stays valid indefinitely, which is the exact
inverse of this plan's goal. Plan 005's docs ("Keycloak forces a password change
at first login") are true only once the fix lands.

**The fix is plan 006.** It adds `"requiredActions": ["UPDATE_PASSWORD"]` to both
seeded users in the realm template. It requires one more re-seed, because
`--import-realm` is create-only. **Resolved 2026-11-13**: the re-seed was run and
`app-admin` was forced to change its password in the browser; `app-user`'s action
remains pending its first login. This plan's Step 6 and the first Step 7
observation are therefore satisfied — by plan 006's mechanism, not by this
plan's.

**The "observed shape" in "Why the test suites cannot use the bootstrap pair"
cannot have been observed.** It claims `status: 200 / location: None / no
wba_session` was "verified against the live stack at `bfa5d8f0`". With no
required action ever attached, that interstitial could never render from this
template. The `pkce_login.py` message change it motivates is still an
improvement, but treat the quoted observation as unverified.

### Two findings for Step 6, neither a defect in this change

- **`.env` carries only the old names.** The live `.env` defines
  `DEV_WBA_ADMIN_PASSWORD` / `DEV_WBA_USER_PASSWORD` and no
  `DEV_WBA_*_BOOTSTRAP_*` key, so forwarding the renamed key yields an empty value
  and `entrypoint.sh`'s `:?` guard **aborts Keycloak startup** on the next
  recreate. The four `.env` edits Step 6.1 describes are mandatory, not optional —
  and the four `TEST_SUITE_*` values must be set to real suite credentials there
  too, since `.env` has none and the suites read `TEST_SUITE_*` from it, not from
  `.env.example`.
- **A `setup.sh` re-run rotates the bootstrap passwords.** `is_placeholder` treats
  an empty value as unset, and the renamed keys are absent from `.env`, so
  re-running the wizard generates fresh values for both. Step 6.2's re-seed then
  imports those, and Step 7 must use the values in `.env` afterwards.

### Not done, by instruction

The two `configured()` unit tests in the Test plan were not added. No
`unit`-marked module imports `tests.auth_helpers`, so a module whose only subject
is a test helper is exactly the file the plan says not to create; the predicate
was verified directly instead. The Test plan permits this and asks for it to be
reported.

## Status

- **Priority**: P2
- **Effort**: M
- **Risk**: MED
- **Depends on**: none. Plan 002 is DONE and committed (`bfa5d8f0`); this plan
  touches lines 002 explicitly left unchanged, so it must land after it.
- **Category**: security
- **Planned at**: commit `bfa5d8f0`, 2026-11-13

## Why this matters

`DEV_WBA_ADMIN_PASSWORD` / `DEV_WBA_USER_PASSWORD` are generated by
`scripts/setup.sh` into `.env`, rendered into the seeded Keycloak users, and
written with `"temporary": false`. They never expire, never change, and are the
same two strings on every dev stack — so a credential that is printed in the
install guide and committed to nobody's memory is, in practice, a permanent
shared password for an account holding `admin`.

This plan makes them one-time:

1. Rename them to `DEV_WBA_ADMIN_BOOTSTRAP_PASSWORD` /
   `DEV_WBA_USER_BOOTSTRAP_PASSWORD`, so the name states the contract.
2. Flip the seeded credentials to `"temporary": true`, which attaches Keycloak's
   `UPDATE_PASSWORD` required action. Keycloak then refuses to issue an auth code
   until the human sets a password of their own; the bootstrap value is dead from
   that moment.
3. Give the live test suites their **own** credentials, separate from the
   bootstrap pair, so the test path does not depend on a credential that is
   designed to stop working.

The cost is inherent to the feature, not to this implementation: the live suites
can no longer authenticate out of the box on a fresh stack. They skip until an
operator completes first login and records the resulting credentials.

### Why the test suites cannot use the bootstrap pair

`tests/auth_helpers.py` and `tests/test_auth_integration.py` authenticate by
posting the real Keycloak login form. With `temporary: true`, that post is
answered by the update-password interstitial instead of a redirect to
`/api/v1/auth/callback`. The observed shape (verified against the live stack at
`bfa5d8f0`) is:

```
status: 200
location: None
set-cookie wba_session: False
```

`login()` discards that body and raises `Login for 'dev-admin' completed but set
no wba_session cookie`, which reads as a wrong password and sends the reader
after a secret that is in fact correct. The fix is a generic, honest message —
not detection, and not an automated password change.

### The bootstrap value is not consumed by a failed attempt

Worth stating because it is the obvious objection: posting the bootstrap password
to a login that ends at the interstitial does **not** spend it. Keycloak stores
passwords as a hash in its `credential` table; `temporary: true` adds a row to
`user_required_action`, which gates the *auth code*, not the password check. The
same bootstrap value therefore keeps working for the browser login as many times
as needed until the change is actually completed. Only completing the change
replaces the hash.

## Current state

### The seeded users — `deploy/keycloak/realm-wba.json.template`

The `"users"` array begins at line 92 and seeds four users; the two dev users are
the first two entries (`dev-admin` at 94, `dev-user` at 113). Each ends with:

```json
      "credentials": [
        {
          "type": "password",
          "value": "${DEV_WBA_ADMIN_PASSWORD}",
          "temporary": false
        }
      ]
```

(`dev-user` is identical with `${DEV_WBA_USER_PASSWORD}`.) `"temporary": false`
is the only thing this plan changes in this file.

### The renderer — `deploy/keycloak/entrypoint.sh`

Lines 12–13 are the presence guards, and lines 19–23 the substitution loop:

```bash
: "${DEV_WBA_ADMIN_PASSWORD:?DEV_WBA_ADMIN_PASSWORD must be set}"
: "${DEV_WBA_USER_PASSWORD:?DEV_WBA_USER_PASSWORD must be set}"
```

```bash
for name in APP_PUBLIC_BASE_URL KEYCLOAK_CLIENT_SECRET \
            KEYCLOAK_SERVICE_CLIENT_SECRET KEYCLOAK_ADMIN_CLIENT_ID \
            KEYCLOAK_ADMIN_CLIENT_SECRET DEV_WBA_ADMIN_PASSWORD DEV_WBA_USER_PASSWORD; do
  rendered=${rendered//"\${$name}"/"${!name}"}
done
```

The `case` guard immediately below aborts if any `${...}` survives, so a renamed
variable that is not added to this loop fails the container at startup rather
than importing a literal placeholder as a password. That guard is what makes the
rename safe.

### The login helper — `src/common/auth/pkce_login.py`

Lines 45–49:

```python
#: role -> (realm username, env var holding that user's password)
_PASSWORD_ROLES: dict[str, tuple[str, str]] = {
    "admin": ("dev-admin", "DEV_WBA_ADMIN_PASSWORD"),
    "user": ("dev-user", "DEV_WBA_USER_PASSWORD"),
}
```

The failure to fix is in `login()`. After posting the credentials:

```python
        response = _follow_to_callback(client, client.post(action_url, data=fields))
        if response.status_code >= 400:
            raise LoginError(
                f"Login for {username!r} failed with {response.status_code}: "
                f"{response.text[:200]!r}"
            )

        session_id = client.cookies.get("wba_session", "")
        if not session_id:
            raise LoginError(
                f"Login for {username!r} completed but set no wba_session cookie"
            )
```

The interstitial is a `200`, so it passes the status check and trips the
`session_id` branch.

`credentials()` (lines 263–291) dispatches on role: `service` →
`_credentials_via_client_credentials`, otherwise `_PASSWORD_ROLES[role]` →
`login(...)`, else `ValueError`. After this plan,
`_credentials_via_client_credentials` is the only branch anything reaches.

### The test wrapper — `tests/auth_helpers.py`

Lines 58–62 duplicate the same mapping, and line 40–42 import the shared
helpers:

```python
#: role -> (realm username, env var holding that user's password)
_PASSWORD_ROLES: dict[str, tuple[str, str]] = {
    "admin": ("dev-admin", "DEV_WBA_ADMIN_PASSWORD"),
    "user": ("dev-user", "DEV_WBA_USER_PASSWORD"),
}
```

`credentials(role)` (from line 93) caches per role and calls `_shared_login`, or
`_shared_credentials("service", ...)` for the service role.

### The integration suite — `tests/test_auth_integration.py`

Lines 61–64 hold the third copy of the binding:

```python
ADMIN_USERNAME = "dev-admin"
USER_USERNAME = "dev-user"
ADMIN_PASSWORD_VAR = "DEV_WBA_ADMIN_PASSWORD"
USER_PASSWORD_VAR = "DEV_WBA_USER_PASSWORD"
```

`_password(role)` (lines 127–133) reads the var and asserts it is set.

### The CLI — `scripts/get_token.py`

Lines 34 and 18–19:

```python
_DEV_USERS = {"admin": "dev-admin", "user": "dev-user"}
```

```python
DEV_WBA_ADMIN_PASSWORD        Password for the ``admin`` dev user.
DEV_WBA_USER_PASSWORD         Password for the ``user`` dev user.
```

`_parse_args` takes `--role`, `--json`, `--base-url`; `main()` calls
`credentials(args.role, ...)`. There is no `--username` and no password input.

### Every reference to the two variable names

Verified exhaustive at `bfa5d8f0` (excluding `.git/`, `.venv/`, `__pycache__/`,
and generated test-report artifacts):

| File | Lines | Nature |
|---|---|---|
| `deploy/keycloak/realm-wba.json.template` | 107, 125 | placeholder + `temporary` |
| `deploy/keycloak/entrypoint.sh` | 12, 13, 21 | guards + substitution loop |
| `docker-compose.yml` | 45, 46 | `keycloak` service env passthrough |
| `.env` | 213, 214 | live values (gitignored) |
| `.env.example` | 213, 214 | `FIXME` placeholders |
| `scripts/setup.sh` | 333, 334 | `KEYCLOAK_SECRET_KEYS` generation array |
| `src/common/auth/pkce_login.py` | 47, 48 | `_PASSWORD_ROLES` (deleted) |
| `tests/auth_helpers.py` | 60, 61 | duplicate map (deleted) |
| `tests/test_auth_integration.py` | 63, 64 | third copy (deleted) |
| `scripts/get_token.py` | 18, 19 | module docstring |
| `INSTALL_GUIDE.md` | 115, 116 | credential table |
| `DEVELOPER_QUICK_START.md` | 60 | "Signing in" note |
| `IAM_ADMIN_GUIDE.md` | 67 | contrast with the console credential |
| `CLAUDE.md` | 238 | settings-class note |
| `plans/002-rename-realm-roles-and-clients.md` | 291 | *historical* — do not edit |

### Who needs a human password credential

Derived from the markers and imports of every `server`-marked module. This table
is the whole justification for the skip list below.

| Module | Needs | Why |
|---|---|---|
| `tests/test_graph_themes_api.py` | admin | `admin_headers()` |
| `tests/test_graph_router.py` | admin | `authenticated`; the conftest fixture attaches the bearer |
| `tests/test_settings_api.py` | admin | `admin_headers()` |
| `tests/test_settings_ui_integration.py` | admin | `admin_headers()`, `session_cookies()` (defaults to admin) |
| `tests/test_catalog_metadata_api.py` | admin **and** user | `admin_headers()` and `user_headers()` both used |
| `tests/test_auth_integration.py` | admin **and** user, except one test | `_live_session("admin"/"user")`, `_password(role)` |
| `tests/producers/test_daemon_integration.py` | none | `authenticated(role="service")` — client credentials, no password |
| `tests/test_connectors_api.py` | none | bare `httpx`, no auth headers |
| `tests/test_authz_live_401_sweep.py` | none | deliberately credential-less by design |
| `tests/test_docs_endpoints_server.py` | none | docs routes are public by design |

The `test_auth_integration.py` row is the one that does not collapse to a single
answer: seven of its eight tests need a human password, and
`test_service_role_is_reader_not_admin` needs none. It carries no
`authenticated` marker precisely so that credential-less tests like that one can
run, so its skip is applied per test rather than per module — Step 5c-ii.

Every other row is uniform within its module, because those modules do carry the
`authenticated` marker and the autouse bearer fixture therefore fetches a
credential for every test in the file. That fixture is also why
`test_health_check_reports_healthy` in `test_graph_router.py` counts as needing
the credential despite setting no header of its own.

### Repo conventions that apply

- Type hints on all parameters and returns; `X | None`, built-in generics.
- Default to no comments. Do not add comments narrating the change.
- `from common.logger import logger`; never `print()` — except in
  `scripts/get_token.py`, whose stdout is its product.
- `tests/auth_helpers.py:40` imports are grouped one-symbol-per-line; keep that.
- Never commit, push, or create a branch.

## Commands you will need

Run from the repository root with the virtualenv active (`source .venv/bin/activate`).

| Purpose | Command | Expected on success |
|---|---|---|
| Unit tests | `PYTHONPATH=src pytest -m unit tests -q` | exit 0, all pass |
| Typecheck | `mypy src/` | exit 0, no errors |
| Lint | `pylint src --score=y` | score 10.00 |
| Style | `flake8` | exit 0 |
| Old names gone | `grep -rn "DEV_WBA_ADMIN_PASSWORD\|DEV_WBA_USER_PASSWORD" --include='*' . \| grep -v '\.git/\|\.venv/\|__pycache__\|plans/002\|_results'` | no output outside `plans/002` |

## Scope

**In scope** (the only files you may modify):

- `deploy/keycloak/realm-wba.json.template` — the two `temporary` flags and the
  two placeholders
- `deploy/keycloak/entrypoint.sh` — guards and substitution loop
- `docker-compose.yml` — the two `keycloak` service env entries
- `.env.example` — the two renamed `FIXME` placeholders, plus four new
  `TEST_SUITE_WBA_*` entries
- `scripts/setup.sh` — the `KEYCLOAK_SECRET_KEYS` array
- `src/common/auth/pkce_login.py` — delete `_PASSWORD_ROLES`, delete the password
  branch of `credentials()`, delete `bearer()`, generic `LoginError` message
- `src/common/auth/__init__.py` — drop the `bearer` re-export, keep `__all__` and
  the import list in agreement
- `tests/auth_helpers.py` — new `TEST_SUITE_*` lookup, no hardcoded usernames
- `tests/test_auth_integration.py` — same, plus the module skip
- `scripts/get_token.py` — `--username`, password via env or prompt, generic error
- `INSTALL_GUIDE.md`, `DEVELOPER_QUICK_START.md`, `IAM_ADMIN_GUIDE.md`,
  `CLAUDE.md` — the four prose references
- `docs/design/authn-authz-design.md` — the dev-users row in the realm table
  (line 150) and the credential description
- `plans/README.md` — status row only

**Out of scope** (do NOT touch, even though they look related):

- `plans/002-rename-realm-roles-and-clients.md` — a DONE plan whose line 291
  names the old variables under "Deliberately unchanged". It is a historical
  record of what 002 decided. Leave it byte-identical.
- `tests/conftest.py` — `service_token_env()` already handles the service path
  and reads no password. No change is needed.
- `tests/producers/test_daemon_integration.py`,
  `tests/test_connectors_api.py`, `tests/test_authz_live_401_sweep.py`,
  `tests/test_docs_endpoints_server.py` — need no human password (see the table
  above). Do not add skips to them.
- `src/common/auth/pkce_login.py`'s `service` path,
  `_credentials_via_client_credentials`, `absolute`, `parse_login_form`,
  `env_value`, `resolve_ca_bundle`, `Credentials`, `LoginError` — all still used.
- `src/common/auth/service_token.py` and everything under `src/connectors/` —
  service tokens are client-credentials and never touch a password.
- Any attempt to detect the update-password interstitial by parsing the HTML, or
  to drive the change form from code. Explicitly rejected — see below.
- Any mechanism that re-arms the seeded passwords automatically, or that
  regenerates `.env` when a suite fails. Explicitly rejected — see below.

## Git workflow

- **Work in the current working tree, on the current branch. Do NOT create a
  branch, worktree, or commit.** Leave every change uncommitted.
- Do NOT run `git commit`, `git push`, `git checkout`, `git stash`,
  `git restore`, `git reset`, or `git clean`.
- `.env` is gitignored. Step 6 edits it, but nothing is committed from it.
- `git status` at the end must show modifications to exactly the in-scope files,
  plus cache churn.

## Implementation

There is one manual gate: **Step 6** (the re-seed), which is an operator action.
Everything else is confirmable by a command.

### Step 1 — rename in the realm template and its renderer

In `deploy/keycloak/realm-wba.json.template`, apply four edits:

1. Line 107: `"value": "${DEV_WBA_ADMIN_PASSWORD}"` →
   `"value": "${DEV_WBA_ADMIN_BOOTSTRAP_PASSWORD}"`
2. Line 108 (the `dev-admin` credential): `"temporary": false` → `"temporary": true`
3. Line 125: `"value": "${DEV_WBA_USER_PASSWORD}"` →
   `"value": "${DEV_WBA_USER_BOOTSTRAP_PASSWORD}"`
4. Line 126 (the `dev-user` credential): `"temporary": false` → `"temporary": true`

Change nothing else in the file. The `service-account-*` users carry no
`credentials` block and must stay as they are.

In `deploy/keycloak/entrypoint.sh`, rename both guards and both names in the
substitution loop. The loop must list the new names or the `case` guard aborts
the container.

In `docker-compose.yml`, rename the two `keycloak` service env keys **and** their
`${...}` values (lines 45–46). A key renamed without its value leaves the
container with an empty variable and the guard fires.

In `scripts/setup.sh`, rename both entries in `KEYCLOAK_SECRET_KEYS`. The
surrounding idempotence comment already explains why a re-run must not rotate
them; it needs no edit.

In `.env.example`, rename both `FIXME` placeholders.

**Verify**:
- `grep -c "BOOTSTRAP_PASSWORD" deploy/keycloak/realm-wba.json.template` → `2`
- `grep -c '"temporary": true' deploy/keycloak/realm-wba.json.template` → `2`
- `grep -c "DEV_WBA_ADMIN_PASSWORD\|DEV_WBA_USER_PASSWORD" deploy/keycloak/entrypoint.sh docker-compose.yml scripts/setup.sh .env.example` → every file reports `0`

### Step 2 — add the test-suite variables to `.env.example`

Add four entries beside the Keycloak block, all `FIXME`:

```
TEST_SUITE_WBA_ADMIN_USERNAME=FIXME
TEST_SUITE_WBA_ADMIN_PASSWORD=FIXME
TEST_SUITE_WBA_USER_USERNAME=FIXME
TEST_SUITE_WBA_USER_PASSWORD=FIXME
```

Add them as **plain commented-in `FIXME` lines**, not to `setup.sh`'s
`KEYCLOAK_SECRET_KEYS`. This is load-bearing: a generated random value would be
a variable that is *set but wrong*, which the suites would treat as configured
and fail on — the opposite of the intended skip. `setup.sh` must know nothing
about these four names.

**Verify**: `grep -c "TEST_SUITE_WBA" .env.example` → `4`, and
`grep -c "TEST_SUITE" scripts/setup.sh` → `0`.

### Step 3 — make `pkce_login.py` require explicit credentials

Do all five edits in this file.

**3a. Delete `_PASSWORD_ROLES`** (lines 46–49) and its comment.

**3b. Delete `bearer()`** (lines 293–301). It has no caller anywhere: `grep -rn
"\bbearer(" src/ tests/ scripts/` returns only `pkce_login.py`'s own definition
and `tests/auth_helpers.py`'s unrelated local `bearer()`, which wraps
`credentials()` in this module rather than calling it.

**3c. Reduce `credentials()` to the service branch.** It becomes:

```python
def credentials(
    *,
    base_url: str,
    ca_bundle: str | None = None,
    timeout: float = _TIMEOUT_SECONDS,
) -> Credentials:
    """Fetch a ``service`` bearer with the ``internal`` client grant.

    Raises:
        LoginError: when the client-credentials grant does not complete.
    """
    return _credentials_via_client_credentials(
        base_url=base_url, ca_bundle=ca_bundle, timeout=timeout
    )
```

The `role` parameter goes away with the branch that read it. Note the signature
change: `role` was the first positional argument. Two callers exist —
`tests/auth_helpers.py` (Step 5a) and `scripts/get_token.py` (Step 5d) — and both
are updated to pass no `role`; the latter only reaches this branch for
`--role service`.

**3d. Replace the misleading failure.** In `login()`, the `session_id` branch
becomes:

```python
        session_id = client.cookies.get("wba_session", "")
        if not session_id:
            raise LoginError(
                f"Login for {username!r} did not complete. The password may be wrong, "
                f"or the account may require a password change — sign in at /app to "
                f"complete it first."
            )
```

This is deliberately generic. Do **not** add detection that distinguishes a
wrong password from a required action, and do **not** drive the update-password
form. Both were considered and rejected: this module serves development and
debugging, the discrimination requires sniffing Keycloak's rendered form, and
`get_token.py` is explicitly allowed to fail for a temporary credential.

**3e. Update the module docstring.** It currently says "Credentials come from the
environment, falling back to `.env` — never hard-coded." That remains true of
`env_value`, but the file no longer resolves a role to a credential. Adjust the
sentence to describe what the module now does; do not add a change-log line.

**Verify**: `grep -c "_PASSWORD_ROLES\|def bearer(" src/common/auth/pkce_login.py`
→ `0`.

### Step 4 — update the `common.auth` re-exports

In `src/common/auth/__init__.py`, remove `"bearer"` from `__all__` and the
matching name from the `from common.auth.pkce_login import (...)` block. mypy
strict treats a plain re-export as private, so `__all__` and the import list must
stay in agreement. Change nothing else in this file.

**Verify**: `grep -c "bearer," src/common/auth/__init__.py` → `0`, and
`PYTHONPATH=src python -c "import common.auth; print('bearer' in common.auth.__all__)"`
→ `False`.

### Step 5 — rework the credential consumers (the live suites and `get_token.py`)

**5a. `tests/auth_helpers.py`.** Replace `_PASSWORD_ROLES` with a mapping from
role to the username/password **variable names**, and read both from the
environment with no fallback:

```python
#: role -> (env var holding the realm username, env var holding its password)
_TEST_ROLES: dict[str, tuple[str, str]] = {
    "admin": ("TEST_SUITE_WBA_ADMIN_USERNAME", "TEST_SUITE_WBA_ADMIN_PASSWORD"),
    "user": ("TEST_SUITE_WBA_USER_USERNAME", "TEST_SUITE_WBA_USER_PASSWORD"),
}
```

Then change `credentials()`'s password branch to read both vars and raise
`AssertionError` naming whichever is missing. Keep the existing per-role cache
and the `service` path unchanged except for the Step 3c signature (pass no
`role`).

Add one helper the skip list needs — a placeholder-aware test, matching
`scripts/setup.sh`'s `is_placeholder`:

```python
def configured(var: str) -> bool:
    """Return True when *var* holds a real value, not an unset or FIXME placeholder."""
    value = env_value(var).strip()
    return bool(value) and "FIXME" not in value.upper()
```

The `FIXME` test is required, not defensive: `env_value` returns the literal
string `"FIXME"` from a fresh `.env`, which is truthy, so a bare truthiness check
would run the suites against the username `FIXME`.

Do **not** delete `env_value`, `Bearer`-header helpers, `session_cookies`,
`subject`, or `service_token_env` — all have callers.

`subject()`'s docstring (around line 171) explains that the dev users' subjects
cannot be hard-coded, naming `dev-admin` / `dev-user` as examples. The reasoning
still holds — Keycloak assigns the UUID at import — but the names are no longer
fixed, so restate it without them ("the configured test accounts' subjects are
assigned by Keycloak at realm import"). This is the only remaining mention of
those names in the file, and it is why the Done-criteria grep covers it.

**5b. `tests/test_auth_integration.py`.** Replace the four constants with the
four variable names, resolved through `env_value` at use time. `_password(role)`
keeps its assertion but reads the `TEST_SUITE_*` var. `ADMIN_USERNAME` /
`USER_USERNAME` become functions or are resolved inside `_live_session` — either
is fine, but the hardcoded `"dev-admin"` / `"dev-user"` strings must be gone.

**5c. Add the skip, at the level that matches the need.** The skip belongs on
whatever actually requires the credential — never on a module that contains a
test which does not.

Every module below must import `configured` from `tests.auth_helpers` alongside
its existing imports. Each of the five modules in 5c-i and
`tests/test_auth_integration.py` already imports specific names from that module;
add `configured` to the same `from tests.auth_helpers import (...)` block. Miss
it and the `pytestmark` evaluates at import time, so the module errors at
collection rather than skipping — a failure that looks like a broken test file
rather than a missing import.

**5c-i — module-level**, for the five modules where *every* test needs it. Each
of these carries a module-level `authenticated` marker, so
`tests/conftest.py`'s autouse `_bearer_for_authenticated_tests` fetches a bearer
at setup for every test in the file — including tests that set no header
themselves, such as `test_health_check_reports_healthy`. They all therefore need
the credential, and a module-level skip is exact:

| Module | Skip when |
|---|---|
| `tests/test_graph_themes_api.py` | admin pair not configured |
| `tests/test_graph_router.py` | admin pair not configured |
| `tests/test_settings_api.py` | admin pair not configured |
| `tests/test_settings_ui_integration.py` | admin pair not configured |
| `tests/test_catalog_metadata_api.py` | admin **or** user pair not configured |

Form, extending the existing list:

```python
pytestmark = [
    pytest.mark.integration,
    pytest.mark.server,
    pytest.mark.authenticated,
    pytest.mark.skipif(
        not (configured("TEST_SUITE_WBA_ADMIN_USERNAME") and configured("TEST_SUITE_WBA_ADMIN_PASSWORD")),
        reason="TEST_SUITE_WBA_ADMIN_* is not configured — see INSTALL_GUIDE.md",
    ),
]
```

A module-level `skipif` is deliberate here: it skips before fixture setup, so the
autouse bearer fixture never runs and cannot fail on a missing credential. Do
**not** convert these to runtime `pytest.skip()` calls.

**5c-ii — per test and per class**, for `tests/test_auth_integration.py`. This
module carries **no** `authenticated` marker — deliberately, so that
credential-less observations stay real — and its eight tests do not share one
requirement. A module-level skip would hide
`test_service_role_is_reader_not_admin`, which authenticates with
`service_headers()` (client credentials) and needs no password. It must keep
running on a fresh, unconfigured stack.

**Do not move that test to another file.** It belongs with the cross-role tests
that give it meaning, and a module created to hold one test is worse than a
decorator.

Define the predicates in this module and decorate the tests that need them:

```python
_USER_READY = configured("TEST_SUITE_WBA_USER_USERNAME") and configured(
    "TEST_SUITE_WBA_USER_PASSWORD"
)
_ADMIN_READY = configured("TEST_SUITE_WBA_ADMIN_USERNAME") and configured(
    "TEST_SUITE_WBA_ADMIN_PASSWORD"
)

needs_user = pytest.mark.skipif(
    not _USER_READY,
    reason="TEST_SUITE_WBA_USER_* is not configured — see INSTALL_GUIDE.md",
)
needs_admin_and_user = pytest.mark.skipif(
    not (_ADMIN_READY and _USER_READY),
    reason="TEST_SUITE_WBA_ADMIN_* and TEST_SUITE_WBA_USER_* are both required",
)
```

Then apply:

| Test | Decorator |
|---|---|
| `TestRealLoginSequence` (class) | `@needs_user` |
| `TestRefreshRotation` (class) | `@needs_user` |
| `TestLogout` (class) | `@needs_user` |
| `TestKeycloakDownResilience` (class) | `@needs_user` |
| `TestWrongRoleAndCrossUser.test_admin_only_setting_write_denies_user` | `@needs_admin_and_user` |
| `TestWrongRoleAndCrossUser.test_connector_secrets_deny_user_allow_admin` | `@needs_admin_and_user` |
| `TestWrongRoleAndCrossUser.test_chat_is_not_visible_across_users` | `@needs_admin_and_user` |
| `TestWrongRoleAndCrossUser.test_service_role_is_reader_not_admin` | **none — it must not skip** |

The module-level `pytestmark = [pytest.mark.integration, pytest.mark.server]`
stays as it is. `TestKeycloakDownResilience` must remain the last class in the
file — its docstring explains why, and decorating it does not change that.

The general rule, for any module touched by this plan: **a skip is attached to
the thing that needs the credential.** A test that needs nothing is never
skipped.

**Verify**:
- `grep -rn "dev-admin\|dev-user" tests/auth_helpers.py tests/test_auth_integration.py`
  → no output
- `grep -c "TEST_SUITE_WBA" tests/auth_helpers.py` → `4`
- With `.env`'s `TEST_SUITE_*` still at `FIXME`:
  `PYTHONPATH=src pytest -m "integration and server" tests/test_settings_api.py -q`
  → every test skipped, `0 passed`, `0 failed`, and no Keycloak login attempt
  (the module-level skip fires at collection, before any fixture)
- With `.env`'s `TEST_SUITE_*` still at `FIXME`, the credential-free test must
  still **run and pass**:
  `PYTHONPATH=src pytest -m "integration and server" tests/test_auth_integration.py -q -k service_role`
  → `1 passed, 7 deselected`, and then the whole file:
  `PYTHONPATH=src pytest -m "integration and server" tests/test_auth_integration.py -q`
  → `1 passed, 7 skipped`

This last pair is the check that the over-skip is gone. If it reports
`8 skipped`, the decorators were applied too broadly.

**5c-iii — no skip at all**, for the modules whose tests need no password:

- `tests/producers/test_daemon_integration.py` — `authenticated(role="service")`,
  client credentials
- `tests/test_connectors_api.py` — bare `httpx`, no auth headers
- `tests/test_authz_live_401_sweep.py` — deliberately credential-less
- `tests/test_docs_endpoints_server.py` — docs routes are public by design

Add no skip to these. In particular the `401` sweep and the docs checks are the
ones whose value is that they observe unauthenticated behaviour, and they would
disappear silently — no failure, just fewer tests — if a marker meant for the
credential-requiring modules were applied by pattern rather than by need.

**5d. `scripts/get_token.py`.** The CLI stops resolving a credential from a role,
and stops knowing any username.

- Add `--username`, required for `--role admin` and `--role user`, with **no
  default** and **no fallback**. `_DEV_USERS` is deleted outright.
- Read the password from a fixed environment variable (`WBA_TOKEN_PASSWORD`),
  and otherwise prompt with `getpass.getpass`. No `--password` flag: an argument
  is visible in the process list, which is exactly the wrong place for a
  credential.
- When stdin is not a TTY and the variable is unset, fail with a clear message
  rather than blocking on a prompt that can never be answered.
- For `--role service`, keep today's behaviour: no username, no password,
  `credentials()` called with no `role` argument (Step 3c's signature).
- The module docstring's environment-variable section drops the two
  `DEV_WBA_*` entries and documents the two new inputs.
- Keep the existing contract: stdout carries only the token (or the `--json`
  object) and every diagnostic goes to stderr. The `LoginError` message from Step
  3d prints through the existing `except LoginError` branch — do not add handling
  for a temporary credential. Failing is the specified behaviour.

**Verify**:
- `grep -c "_DEV_USERS\|DEV_WBA" scripts/get_token.py` → `0`
- `PYTHONPATH=src python scripts/get_token.py --role user </dev/null; echo "exit=$?"`
  → exit 1 with a clear error, no traceback, and no hang. This exercises the
  no-TTY path without contacting Keycloak.
- `PYTHONPATH=src python scripts/get_token.py --role service --json` → a token on
  stdout, no prompt

### Step 6 — re-seed the realm (manual gate: operator action, confirm first)

**Before starting: confirm with the operator.** This destroys the realm
database, every Keycloak session, every refresh token, and every role assignment
made through the User Management page since the last re-seed. Safe only on a dev
stack. `--import-realm` is create-only, so editing the template has no effect
until the realm is dropped.

1. **Update `.env`** — gitignored, so the `.env.example` edits do not reach it.
   Rename both bootstrap variables and add the four `TEST_SUITE_*` entries with
   the credentials the operator intends to use for the suites.

2. **Re-seed:**
   ```bash
   docker compose stop keycloak
   docker compose exec postgres psql -U postgres -c 'DROP DATABASE IF EXISTS keycloak WITH (FORCE);'
   docker compose exec postgres psql -U postgres -c 'CREATE DATABASE keycloak OWNER keycloak;'
   docker compose up -d --force-recreate keycloak
   docker compose logs -f keycloak   # wait for "Importing realm" then successful startup
   ```

3. **Flush the stale session rows:**
   ```bash
   docker compose exec postgres psql -U postgres -d postgres -c 'TRUNCATE auth_session;'
   ```
   Expected: `TRUNCATE TABLE`.

4. **Recreate every service that reads a realm variable.** The producer and
   consumer images copy `src/common/` at build time with no bind-mount, so a
   `--force-recreate` alone serves the old code:
   ```bash
   docker compose build api ui github-producer jira-producer confluence-producer signal-consumer
   docker compose up -d --force-recreate
   ```

### Step 7 — prove the one-time behaviour (operator action, after Step 6)

1. **The bootstrap credential is required at first login.** Open
   `https://localhost/app` in a private window and sign in as `dev-admin` with
   `DEV_WBA_ADMIN_BOOTSTRAP_PASSWORD`. Keycloak must present the update-password
   form, not the application. Set a password of your own. You are then returned
   to the app.
2. **The bootstrap credential is now dead.** Sign out, and sign in again with the
   bootstrap value → Keycloak rejects it. Sign in with the new value → succeeds.
3. **`get_token.py` fails cleanly against a temporary credential.** The `dev-user`
   account is still untouched at this point:
   ```bash
   PYTHONPATH=src python scripts/get_token.py --role user --username dev-user
   ```
   Enter `DEV_WBA_USER_BOOTSTRAP_PASSWORD` at the prompt. Expect exit 1 and
   `error: Login for 'dev-user' did not complete. The password may be wrong, or
   the account may require a password change — sign in at /app to complete it
   first.` It must **not** fail with a Keycloak-unreachable error, a traceback, or
   the old "set no wba_session cookie" wording.
4. **`get_token.py` succeeds at a normal password.** Complete `dev-user`'s first
   login in the browser, then repeat the command with the new password → it
   prints a token on stdout and the diagnostic on stderr.
   ```bash
   PYTHONPATH=src python scripts/get_token.py --role user --username dev-user --json
   ```
   → valid JSON with `access_token`, `role`, `subject`, `expires_in`.
5. **The service role is untouched.** `--role service` mints a token with no
   username and no prompt.
6. **The suites run once configured.** With the four `TEST_SUITE_*` values set to
   real credentials in `.env`:
   ```bash
   PYTHONPATH=src pytest -m "integration and server" tests/test_auth_integration.py tests/test_settings_api.py -q
   ```
   → passes. With those four vars set back to `FIXME` → the same modules report
   skips and the other server modules still run.

**Verify**: all six observations hold.

### Step 8 — update the docs

Update, in each case to state the one-time contract:

- `INSTALL_GUIDE.md` lines 115–116: the two table rows, and the surrounding
  "Sign in as `dev-admin` or `dev-user` with the value in `.env`" paragraph, which
  becomes false after first login. State that the value is a first-login
  bootstrap credential, that Keycloak forces a change, and that the changed
  password is not written back to `.env`.
- `DEVELOPER_QUICK_START.md` line 60: the "Signing in" note.
- `IAM_ADMIN_GUIDE.md` line 67: the contrast sentence with the console credential.
- `CLAUDE.md` line 238: the trailing note about the dev seed passwords.
- `docs/design/authn-authz-design.md`: the realm table's "Dev users" row (line
  150), which says the seeded users make `docker compose up` yield "a working
  login immediately" — now a first-login-with-mandatory-change. Also state that
  the live suites use their own `TEST_SUITE_*` credentials. Add the four new
  variables to the design's change-to-production checklist area if the doc has
  one for dev-only settings; if it does not, do not invent a section.

Do not restate the old variable names anywhere except as required to explain the
rename in `INSTALL_GUIDE.md`'s own context. Never paste a real credential into a
tracked file.

**Verify**: `grep -rn "DEV_WBA_ADMIN_PASSWORD\|DEV_WBA_USER_PASSWORD" INSTALL_GUIDE.md DEVELOPER_QUICK_START.md IAM_ADMIN_GUIDE.md CLAUDE.md docs/` → no output.

### Step 9 — final verification

Run the whole gate set and paste each result:

- `PYTHONPATH=src pytest -m unit tests -q` → all pass
- `mypy src/` → `Success: no issues found`
- `pylint src --score=y` → `10.00/10`
- `flake8` → exit 0
- `git status --porcelain` → only the in-scope files modified (plus ignored churn)
- The Step 1 and Step 8 greps → as stated

## Test plan

This plan adds no new test file. The behaviour it changes is exercised by the
existing suites and by Step 7's operator observations. Two unit-level checks are
still worth adding, because they are the ones a regression would silently break:

| Test | File | Covers |
|---|---|---|
| `test_configured_treats_fixme_as_unset` | `tests/auth_helpers.py` consumers — extend an existing auth test module | the skip predicate; a bare truthiness check would pass `FIXME` through and run the suites against it |
| `test_configured_true_for_real_value` | same | the positive case |

`tests/auth_helpers.py` is itself imported by suite modules rather than tested
directly. Put these two wherever `auth_helpers` is already imported in a
`unit`-marked module; if no such module exists, they belong in the plan's own
review rather than in a new file, since adding a `unit`-marked module whose only
subject is a test helper would be a file created to hold two trivial assertions.
Report which you did.

Structural pattern to follow: the existing unit tests around
`tests/auth_helpers.py`'s helpers, if any; otherwise mirror
`scripts/setup.sh`'s `is_placeholder` semantics exactly.

## Done criteria

All must hold:

- [ ] `grep -rn "DEV_WBA_ADMIN_PASSWORD\|DEV_WBA_USER_PASSWORD" --include='*' .`
      returns nothing outside `plans/002-*` and generated artifacts
- [ ] `grep -c '"temporary": true' deploy/keycloak/realm-wba.json.template` → `2`
- [ ] `grep -c "_PASSWORD_ROLES\|def bearer(" src/common/auth/pkce_login.py` → `0`
- [ ] `grep -n "dev-admin\|dev-user" tests/auth_helpers.py tests/test_auth_integration.py scripts/get_token.py`
      → no output. This grep is scoped to the three files in Step 5 on purpose:
      `dev-admin` / `dev-user` also appear as `Principal(...)` usernames and stub
      payloads in roughly a dozen unrelated test modules
      (`test_admin_users_api.py`, `test_authz_enforcement.py`,
      `test_ui_account_bar_signed_out.py` and others). Those are fixture strings,
      not live logins, and **must not be changed** — a repo-wide grep-and-replace
      on these two names would corrupt them.
- [ ] `grep -c "TEST_SUITE" scripts/setup.sh` → `0` (they must not be generated)
- [ ] The five modules in Step 5c-i carry a module-level skip;
      `tests/test_auth_integration.py` carries per-test and per-class skips per
      Step 5c-ii; the four modules in Step 5c-iii carry none
- [ ] With `TEST_SUITE_*` unconfigured,
      `pytest -m "integration and server" tests/test_auth_integration.py -q`
      reports `1 passed, 7 skipped` — `test_service_role_is_reader_not_admin` ran
      and passed, not skipped
- [ ] `PYTHONPATH=src pytest -m unit tests -q` exits 0
- [ ] `mypy src/` exits 0 with `Success: no issues found`
- [ ] `pylint src --score=y` reports `10.00/10`
- [ ] `flake8` exits 0
- [ ] Step 7's six observations were performed and reported
- [ ] `git status --porcelain` lists only in-scope files; no branch, nothing committed
- [ ] `plans/002-rename-realm-roles-and-clients.md` is byte-identical to how you found it

## STOP conditions

Stop and report (do not improvise) if:

- The drift check prints a diff, or the code at the cited lines does not match
  the "Current state" excerpts.
- `scripts/get_token.py` appears to need the update-password form driven, or any
  other handling of a temporary credential beyond failing cleanly. It does not:
  failing is the specified behaviour.
- A test module cannot be skipped with a `skipif` marker — module-level or
  decorator — without a fixture running first. Every skip in this plan must be a
  `pytest.mark.skipif`, never a runtime `pytest.skip()` inside a fixture or a
  test body. Those differ in a way that matters here: a `skipif` is evaluated
  before fixture setup, so the autouse bearer fixture cannot fail on a missing
  credential, while a runtime skip is reached only *through* that fixture.
  Report any module that seems to need the runtime form.
- A skip cannot be placed on the thing that needs the credential — for instance
  `TestWrongRoleAndCrossUser` cannot take a single class-level decorator, because
  one of its four tests needs no password. Decorate the three methods and leave
  `test_service_role_is_reader_not_admin` bare. Do not move the test to another
  file to make a coarser decorator possible.
- `tests/conftest.py` turns out to need a change. It should not — the service
  path reads no password — but if it does, that means the skips are not firing
  early enough, which is a defect in the approach worth reporting rather than
  patching around.
- The re-seed (Step 6) is reached without an explicit operator go-ahead.
- Renaming a variable appears to require editing a file outside the in-scope
  list. In particular: if anything in `src/app/` or `src/domain/` reads one of
  these names, STOP — `CLAUDE.md` states they are on neither settings class, and
  a discovery to the contrary invalidates the rename's premise.
- Any command would create a branch or a commit.

## Maintenance notes

- **The three-copy problem is gone; keep it gone.** The role→credential binding
  previously lived in three places (`pkce_login.py`, `tests/auth_helpers.py`,
  `tests/test_auth_integration.py`). After this plan the usernames and passwords
  are operator-supplied data in `.env`, read directly at each use. Do not
  reintroduce a hardcoded username or a default in any of them.
- **`TEST_SUITE_*` must never be generated by `setup.sh`.** A generated value is
  set-but-wrong, which the suites read as configured and fail on. If someone
  later "helpfully" adds them to a generation array, the skip stops working in
  the most confusing way: a fresh checkout fails instead of skipping.
- **The skip predicate must treat `FIXME` as unset.** `env_value` returns the
  literal string from `.env.example`. This is the single most likely regression
  in the plan, and it is why the two `configured()` tests exist.
- **The skip must never outrun the need.** The rule is: a skip is attached to
  the thing that requires the credential, and a test requiring nothing is never
  skipped. Two failure modes to check for, in opposite directions:
  - *Too broad* — a module-level skip on `tests/test_auth_integration.py` would
    hide `test_service_role_is_reader_not_admin`, which needs no password. It
    sits between three tests that do, so the module looks uniform and is not.
  - *Applied by pattern* — a marker added to everything `server`-marked would
    silently stop running the `401` sweep, the docs checks, the connectors API
    tests and the producer daemon end-to-end tests. Those need no password, so
    nothing would fail; there would simply be fewer tests. This is the more
    dangerous of the two, because its only symptom is a smaller number.
- **A reviewer should scrutinize** that the five module-level skips in Step 5c-i
  fire before fixture setup (so the autouse bearer fixture cannot fail on a
  missing credential), and that `tests/test_auth_integration.py` reports
  `1 passed, 7 skipped` when unconfigured.
- **The generic error message is a deliberate downgrade from a specific one.**
  It cannot say which of the two causes applies, because both render the same
  Keycloak form. If a future reader wants that discrimination, it requires
  parsing the update-password page, and the trade-off is recorded in Step 3d.
- **Plan 002 is DONE and its line 291 is now historically wrong** — it lists the
  old variable names under "Deliberately unchanged". That is an accurate record
  of what 002 decided at the time; do not edit it.
- **Deliberately deferred, do not add on top of this plan**:
  - *Driving the update-password form from `get_token.py`* so a fresh stack needs
    no browser. Rejected: a second interactive flow in a module that serves
    development and debugging, and the CLI is explicitly permitted to fail for a
    temporary credential.
  - *Automatically re-arming the seeded passwords* via the `admin-api` client's
    `set_password`. Rejected: it would make a genuine password mismatch
    indistinguishable from a normal first-login consumption, so the mechanism
    would clobber the account of a user who had legitimately just changed their
    password.
  - *Dedicated seeded Keycloak users for the test suites*, instead of operator-
    supplied `TEST_SUITE_*` values. Rejected for now: it adds two realm users and
    two more env vars to a dev-only concern, and the operator-supplied pair keeps
    the realm template unchanged.
  - *Removing `env_value`'s `.env` fallback.* It is still used by `get_token.py`
    for `APP_PUBLIC_BASE_URL` and by the service-token path.

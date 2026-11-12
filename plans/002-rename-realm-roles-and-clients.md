# Plan 002: Rename the realm roles and Keycloak client ids (drop the `wba-` prefix)

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat c390367c..HEAD -- src/app/auth src/app/api src/common/auth src/connectors/producers/daemon_common.py src/domain/settings.py src/ui deploy/keycloak .env.example docker-compose.yml docker-compose.keycloak.yml docs/design/authn-authz-design.md CLAUDE.md INSTALL_GUIDE.md tests/`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: M
- **Risk**: MED
- **Depends on**: none (plan 001 is DONE; this supersedes its realm-template naming only)
- **Category**: tech-debt
- **Planned at**: commit `c390367c`, 2026-11-12

## Why this matters

The realm's three roles are named `wba-admin`, `wba-user`, `wba-service`, and its three
clients `wba-web`, `wba-internal`, `wba-admin-api`, while the realm itself is already called
`wba` and the product is called WBA. The prefix therefore carries no information — it repeats
the realm name inside the realm. Worse, it creates a vocabulary split the code has to
compensate for: `src/app/auth/matrix.py` declares grants as `"admin"`/`"user"`/`"service"`,
and `src/app/auth/dependencies.py` contains `_internal_role()` whose only job is to add the
`wba-` prefix back. After this change there is one vocabulary end to end — the grant label and
the realm role name are the same string — and `_internal_role()` is deleted as dead code.

The cost is a destructive realm re-seed on the dev stack: `--import-realm` is create-only, so
renaming a role or client in the template has no effect on a realm that already exists. Every
Keycloak session, refresh token and role assignment is destroyed by the re-seed, so this is a
hard cut with no dual-name acceptance window.

## Current state

### Where the role names live

`src/app/auth/tokens.py:21` — the allowlist that gates every request. A realm role outside this
set is silently dropped, so a mismatch between this set and the realm means every token is
rejected as unrecognised:

```python
_MAPPED_ROLES = frozenset({"wba-admin", "wba-user", "wba-service"})
```

`src/app/auth/dependencies.py:112-128` — the two role dependencies and the prefix helper:

```python
async def require_admin(
    request: Request, principal: Principal = Depends(get_principal)
) -> Principal:
    """Require ``wba-admin``; 403 otherwise."""
    return _require_role(principal, "wba-admin", request.url.path)


async def require_service(
    request: Request, principal: Principal = Depends(get_principal)
) -> Principal:
    """Require ``wba-service``; 403 otherwise."""
    return _require_role(principal, "wba-service", request.url.path)


def _internal_role(role: str) -> str:
    """Map a short role label (``"admin"``) to its internal name (``"wba-admin"``)."""
    return role if role.startswith("wba-") else f"wba-{role}"
```

`_internal_role` is called from exactly one place, `require_roles` at
`src/app/auth/dependencies.py:143`:

```python
    internal = [_internal_role(role) for role in roles]
```

Every current caller passes an already-prefixed name, so the helper is a pass-through today:
`src/app/api/commands/v1/router.py:32` calls
`require_roles("wba-admin", "wba-service")`. **After the rename, leaving this helper in place
is an active bug**: `require_roles("admin", "service")` would be rewritten to
`("wba-admin", "wba-service")` and every scan-command POST would silently 403.

`src/app/auth/principal.py:46-49` — convenience property:

```python
    @property
    def is_admin(self) -> bool:
        """Return whether this principal carries ``wba-admin``."""
        return "wba-admin" in self.roles
```

`src/app/api/admin_users/v1/model.py:12` — the assignable-role subset:

```python
ASSIGNABLE_REALM_ROLES: frozenset[str] = frozenset({"wba-admin", "wba-user"})
```

`src/app/api/admin_users/v1/service.py` — the last-admin guard, at lines 41, 144, 167-170.
Line 144 is representative:

```python
    holders = await asyncio.to_thread(query.users_with_role, "wba-admin")
```

`src/app/api/connectors/v1/router.py:49` — an inline privilege check, plus the user-facing
message at line 60:

```python
        principal.has_role("wba-admin") or principal.has_role("wba-service")
```

`src/app/auth/matrix.py:20-22,34` — the grant semantics documented in a comment block, and one
section header comment, name the roles. These are comments; the surrounding `AUTHZ_MATRIX`
values are the grant labels (`"user"`, `"admin"`, `"service"`) and do **not** change.

Occurrences in these two files are **comments/docstrings only** and must be updated for
accuracy but carry no runtime behaviour:
- `src/app/api/admin_users/v1/router.py:3`
- `src/app/auth/keycloak_admin.py:5`

`src/domain/settings.py:54-67` — client id settings with doc comments:

```python
# `wba-web` — the confidential browser client used by the BFF.
KEYCLOAK_CLIENT_ID: str = "wba-web"

# `wba-internal` — the service-account client used by producers and the
KEYCLOAK_SERVICE_CLIENT_ID: str = "wba-internal"

# `wba-admin-api` — the confidential client the API exchanges for a Keycloak
KEYCLOAK_ADMIN_CLIENT_ID: str = "wba-admin-api"
```

`src/ui/pages/settings/user_management/layout.py:31-36` — user-facing help text shown from the
Roles label's info hint:

```python
#: Explains the two assignable realm roles, shown from the Roles label's (i) hint.
_ROLES_HELP = (
    "**wba-admin** — everything a standard user can do, plus shared "
    "configuration, connector secrets, and user management.\n\n"
    "**wba-user** — standard user. Reads everything except connector secrets, "
    "and manages their own chat sessions and catalog favourites."
)
```

### Where the client ids live

`deploy/keycloak/realm-wba.json.template` — the realm-as-code. Three client ids, plus
**audience protocol mappers whose `included.client.audience` must equal the client id**, plus
the two service-account usernames Keycloak derives from client ids:

```json
      "clientId": "wba-web",
...
          "name": "wba-web-audience",
          "config": {
            "included.client.audience": "wba-web",
...
      "clientId": "wba-internal",
...
          "name": "wba-internal-audience",
          "config": {
            "included.client.audience": "wba-internal",
...
      "username": "service-account-wba-internal",
      "serviceAccountClientId": "wba-internal",
...
      "username": "service-account-wba-admin-api",
      "serviceAccountClientId": "wba-admin-api",
```

The audience mapper is load-bearing: `src/app/auth/tokens.py:137` decodes with
`audience=sorted(client_ids)` where `client_ids` is
`frozenset({settings.KEYCLOAK_CLIENT_ID, settings.KEYCLOAK_SERVICE_CLIENT_ID})`
(`tokens.py:97-103`), and `tokens.py:154` independently requires `azp` to be in both
`client_ids` and the token's `aud`. A client id renamed in the template but not in `.env`
(or a mapper left pointing at the old id) rejects every bearer token.

The realm roles are declared at `deploy/keycloak/realm-wba.json.template:8-14`, and the seeded
users' role arrays at lines 100-103 and 119-121:

```json
  "roles": {
    "realm": [
      { "name": "wba-admin", "description": "Full administrative access to WBA" },
      { "name": "wba-user", "description": "Standard authenticated WBA user" },
      { "name": "wba-service", "description": "Machine-to-machine service account role" }
    ]
  },
```

`src/common/auth/service_token.py:26` and `src/connectors/producers/daemon_common.py:207` —
the connector runtime's own copy of the default client id:

```python
_DEFAULT_CLIENT_ID = "wba-internal"
```
```python
        client_id = os.environ.get("KEYCLOAK_SERVICE_CLIENT_ID", "wba-internal")
```

`docker-compose.yml` lines 310, 335, 360, 389 — the same default repeated in four producer /
consumer service blocks, e.g.:

```yaml
      KEYCLOAK_SERVICE_CLIENT_ID: ${KEYCLOAK_SERVICE_CLIENT_ID:-wba-internal}
```

`.env` (gitignored) and `.env.example` lines 188-190 hold the three client ids. `.env` must
be edited by hand as part of Step 2 — it is not in git and `.env.example` changes do not
propagate to it.

### The trap: an unrelated `wba` namespace

`wba` is **also** a person-identifier dict key throughout the UI, with no relation to Keycloak.
It is the WBA person id stored by the person pickers:

- `src/ui/components/person_picker.py:79,90,109` — `{"wba": "...", "display": "..."}`
- `src/ui/pages/graph/callbacks/catalog.py:168,173,907,931,945,953`
- `src/ui/pages/graph/callbacks/query.py:37,45`
- `src/ui/pages/graph/utils/cypher_substitution.py:36,42,63`
- `src/ui/pages/collaboration_network_ego/callbacks/filter.py:140,322,348,359`

**These must not be touched.** Any unanchored find-and-replace on the string `wba` corrupts
the graph page's person round-tripping. Every substitution in this plan is anchored to a
full literal (`wba-admin`, `wba-user`, `wba-service`, `wba-web`, `wba-internal`,
`wba-admin-api`), never to bare `wba`.

### Deliberately unchanged

These carry a `wba` prefix but are **out of scope** by decision:

- The realm name `wba` — `KEYCLOAK_REALM`, `KEYCLOAK_ISSUER`, `KEYCLOAK_INTERNAL_URL`
  (`src/domain/settings.py:44-52`), `src/common/auth/service_token.py:25`,
  `src/common/auth/pkce_login.py:238`, the `iss` match at `tokens.py:55-64`.
- The `wba_session` and `wba_oidc` cookie names
  (`src/app/auth/session_cookie.py:33,37`, `src/ui/auth.py:35`, `src/common/auth/pkce_login.py:203`).
- `DEV_WBA_ADMIN_PASSWORD` / `DEV_WBA_USER_PASSWORD` (consumed by
  `deploy/keycloak/entrypoint.sh:12-13,21` and generated by `scripts/setup.sh`).
- The seeded usernames `dev-admin` / `dev-user`, and `_DEV_USERS` in `scripts/get_token.py:34`.
- The Compose container/network names `wba-ai-*` (`docker-compose.yml`).
- `tests/neo4j_queries/results/*.json` and `logs/` — generated artifacts, gitignored or
  historical. Do not edit them; the Done-criteria greps exclude them.

### Repo conventions that apply

- Type hints on all parameters and returns; `X | None`, built-in generics.
- Default to no comments. The comment edits in this plan are corrections to existing
  comments that name a role or client id — do not add new ones.
- Changing an existing function to add annotations must be non-destructive. Here that
  principle extends to `_internal_role`: it is **deleted**, which is a deliberate,
  in-scope behavior change, not a drive-by refactor. Its single caller is updated in the
  same step.
- Commit messages are plain imperative sentences, e.g.
  `Activity timeline backend (#323)`. Example from `git log`: `Info tooltip`.

## Commands you will need

Run from the repository root with the virtualenv active (`source .venv/bin/activate`).

| Purpose | Command | Expected on success |
|---|---|---|
| Unit tests | `pytest -m unit tests -q` | exit 0, all pass |
| Typecheck | `mypy src/` | exit 0, no errors |
| Lint | `pylint src --score=y` | score 10.00 |
| Style | `flake8` | exit 0 |
| Security scan | `bandit -c .bandit.yml -r src/ -lll` | no High severity |
| Old role literals gone | `grep -rn "wba-admin\|wba-user\|wba-service" src/ tests/ --include="*.py"` | no output |
| Old client ids gone | `grep -rn "wba-web\|wba-internal\|wba-admin-api" src/ tests/ deploy/ .env.example docker-compose.yml` | no output |
| Person-id key intact | `grep -rn '"wba"' src/ui/ --include="*.py"` | 10+ matches, unchanged |

## Scope

**In scope** (the only files you should modify):

Source:
- `src/app/auth/tokens.py`
- `src/app/auth/dependencies.py`
- `src/app/auth/principal.py`
- `src/app/auth/matrix.py`
- `src/app/auth/keycloak_admin.py` (docstring only)
- `src/app/api/commands/v1/router.py`
- `src/app/api/connectors/v1/router.py`
- `src/app/api/admin_users/v1/model.py`
- `src/app/api/admin_users/v1/service.py`
- `src/app/api/admin_users/v1/router.py` (docstring only)
- `src/common/auth/pkce_login.py` (docstrings and one log/error message; see Step 1)
- `src/common/auth/service_token.py`
- `src/connectors/producers/daemon_common.py`
- `src/domain/settings.py`
- `src/ui/pages/settings/user_management/layout.py`

Deployment and config:
- `deploy/keycloak/realm-wba.json.template`
- `docker-compose.yml` (four `KEYCLOAK_SERVICE_CLIENT_ID` defaults only)
- `.env.example`
- `.env` (Step 2 only — operator step, gitignored, not committed)

Docs:
- `docs/design/authn-authz-design.md`
- `CLAUDE.md`
- `INSTALL_GUIDE.md`

Tests:
- `tests/auth_helpers.py`
- `tests/conftest.py`
- `tests/test_admin_users_api.py`
- `tests/test_admin_users_service.py`
- `tests/test_auth_dependencies.py`
- `tests/test_auth_flow.py`
- `tests/test_auth_integration.py`
- `tests/test_auth_principal.py`
- `tests/test_auth_session_model.py`
- `tests/test_auth_session_service.py`
- `tests/test_auth_tokens.py`
- `tests/test_authz_enforcement.py`
- `tests/test_catalog_metadata_api.py`
- `tests/test_chat_ownership.py`
- `tests/test_connectors_secrets_gating.py`
- `tests/test_connectors_toggle.py`
- `tests/test_keycloak_admin_client.py`
- `tests/test_settings_user_management_page.py`
- `tests/test_ui_account_bar_signed_out.py`
- `tests/test_daemon_common_auth.py`
- `tests/test_service_token.py`

Index:
- `plans/README.md` (status row only)

**Out of scope** (do NOT touch, even though they look related):

- Any bare `"wba"` person-id dict key in `src/ui/` — see *The trap* above.
- The realm name `wba` in `KEYCLOAK_REALM` / `KEYCLOAK_ISSUER` / `KEYCLOAK_INTERNAL_URL`.
- The `wba_session` / `wba_oidc` cookie names.
- `DEV_WBA_*` env var names; `deploy/keycloak/entrypoint.sh` and `scripts/setup.sh`.
- The seeded usernames `dev-admin` / `dev-user`; `scripts/get_token.py`.
- `wba-ai-*` Compose container and network names.
- `tests/neo4j_queries/results/` and `logs/` — generated artifacts.
- `deploy/postgres/init-keycloak.sh` — creates a database literally named `keycloak`, which
  is not a client id and does not change.
- Adding a shared roles module or otherwise restructuring the constants. Two named sets
  (`_MAPPED_ROLES`, `ASSIGNABLE_REALM_ROLES`) stay where they are; this plan renames their
  contents only.
- Adding an Alembic migration. `auth_session.roles` is a write-only snapshot (see below); no
  schema change is needed.

## Git workflow

- Branch: `feature/rename-realm-roles-and-clients`
- Commit once at the end of Step 1, after all gates pass. Message style is a plain imperative
  sentence, matching `git log` — e.g.
  `Rename realm roles and Keycloak client ids`.
- Do NOT push or open a PR unless the operator instructed it.
- `.env` is gitignored (`.gitignore:139`); Step 2 edits it but nothing is committed from it.

## Steps

### Step 1: Rename every role literal and client id in code, tests and docs

**Substitution table.** Apply these exact replacements. Order matters where one literal is a
prefix of another — listed longest-first here, so apply in this order:

| # | Old | New | Note |
|---|---|---|---|
| 1 | `wba-admin-api` | `admin-api` | Longest, and contains `wba-admin` |
| 2 | `wba-internal-audience` | `internal-audience` | Contains `wba-internal` |
| 3 | `wba-internal` | `internal` | |
| 4 | `wba-web-audience` | `web-audience` | Contains `wba-web` |
| 5 | `wba-web` | `web` | |
| 6 | `wba-admin` | `admin` | |
| 7 | `wba-user` | `standard-user` | |
| 8 | `wba-service` | `service` | |

Do not run a single unanchored `sed` across the tree. Edit file by file, and for each file read
the surrounding line before substituting so you are matching the intended occurrence.

**Also rename these Keycloak-derived usernames** in `deploy/keycloak/realm-wba.json.template`,
which follow from the client ids and are not covered by the table (row 3 and row 1 collapse
them, but confirm the result reads `service-account-internal` and
`service-account-admin-api`):

- `"username": "service-account-wba-internal"` → `"service-account-internal"`
- `"username": "service-account-wba-admin-api"` → `"service-account-admin-api"`

**Delete `_internal_role` and its call.** In `src/app/auth/dependencies.py`:

- Delete the function `_internal_role` (lines 126-128) entirely.
- Change `require_roles` so the internal list is the role names verbatim. Replace:
  ```python
      internal = [_internal_role(role) for role in roles]
  ```
  with:
  ```python
      internal = list(roles)
  ```
- Leave the rest of `require_roles` — the closure, `_dependency.__name__ = "require_roles"`,
  the 403 shape — unchanged. `tests/test_authz_matrix.py:23,67` matches the dependency by the
  name `"require_roles"`, so that assignment is load-bearing.
- Update the `require_roles` docstring line that reads
  `It is a factory rather than a bare ``async def`` because ...` — it stays correct. Do not
  otherwise rewrite the docstring.

**Update the four call sites that pass a prefixed role name** so they pass the new name:

- `src/app/api/commands/v1/router.py:32`:
  `require_roles("wba-admin", "wba-service")` → `require_roles("admin", "service")`
- `src/app/api/connectors/v1/router.py:49` and its message at line 60.
- `src/app/api/admin_users/v1/service.py` — lines 41 (docstring), 144, 167, 168, 170.
- `src/app/auth/principal.py:49`.

**`src/common/auth/pkce_login.py`.** Rows 3 and 5 of the table cover the client ids in its
docstring (`wba-web`, `wba-internal`). Separately, line 227's docstring says
``Fetch a ``wba-service`` bearer`` — row 8 makes that ``service``. The `_PASSWORD_ROLES` dict
and `credentials()` dispatch key off the **grant labels** `admin` / `user` / `service`
(already unprefixed) and **do not change**; only the surrounding prose does. Verify by reading
`credentials()`'s `role == "service"` branch and `_PASSWORD_ROLES` keys — if either now reads
`standard-user`, you have over-applied row 7 and must revert it.

**`src/app/auth/tokens.py:33` and `tokens.py:123,166`.** The `NoRecognisedRoleError` class
docstring (line 33) says "no wba-* realm role", the `validate_bearer_token` docstring (line
123) says "no mapped ``wba-*`` role", and the log message at line 166 says "no recognised
wba-* role". Update this prose to refer to a recognised realm role without the `wba-*` prefix,
but do not change the class name or the message contract — `tests/test_auth_dependencies.py`
asserts the `no_recognised_role` error code that `src/app/auth/dependencies.py:82` emits.

**Tests.** Mechanical substitutions per the table. Two tests assert user-visible strings and
need their expectation updated with the code, not just the literal:

- `tests/test_connectors_toggle.py:162` — stubs
  `PermissionDeniedError(403, message="Role 'wba-admin' is required.")`. The real message is
  produced by `_require_role` in `dependencies.py:107` as
  `f"Role {role!r} is required."`, so it becomes `Role 'admin' is required.` Update the stub
  to match.
- `tests/test_settings_user_management_page.py:164-169` — asserts `"wba-admin" in _ROLES_HELP`
  and `"wba-user" in _ROLES_HELP` and `"wba-service" not in _ROLES_HELP`. After the rename the
  assertions become `"admin" in _ROLES_HELP`, `"standard-user" in _ROLES_HELP`. **Note the
  substring hazard**: `"standard-user"` contains `"user"`, and the third assertion checks
  `"service" not in _ROLES_HELP`. Keep that third assertion meaningful by asserting on the
  full word — check that `"service"` does not appear — which still holds because the help text
  never names it. If the substitution makes the third assertion ambiguous, replace it with
  `_ROLES_HELP.count("**") == 4` — today's value, since each of the two roles is wrapped in a
  `**bold**` pair — which asserts that exactly two roles are described without depending on
  substring overlap.

**Docs.** Apply the table, then fix the prose that no longer reads correctly:

- `docs/design/authn-authz-design.md` — 16 role references and 6 client-id references across
  the decision summary (rows 6, 7), the Keycloak table (lines 143-146), the enterprise-SSO
  paragraph (line 214), the Roles table (236-238), the Grants table (249-250), the
  user-administration section (339, 361), the re-seed note (398) and the settings table
  (501-506). Row 6's Decision cell currently reads "Realm roles `wba-admin`, `wba-user`,
  `wba-service`" and becomes "Realm roles `admin`, `standard-user`, `service`".
- **Do not add plan references, stage letters, or file:line citations to this doc.** It is a
  long-term reference; describe the end state only.
- `CLAUDE.md:238` — the Keycloak/auth environment bullet; it names `wba-admin-api` twice.
  `CLAUDE.md:254` — the reference-documents table row, which names the three roles.
- `INSTALL_GUIDE.md:113-116` — the credentials table: client-id descriptions on 113-114, role
  names on 115-116. The `DEV_WBA_*` env var names on those rows do **not** change.
- `.env.example:188-190` (the three client-id values), `:203,205,207` (comments), `:212`
  (the comment naming `wba-admin + wba-user` and `wba-user`).

**Verify**:
```
grep -rn "wba-admin\|wba-user\|wba-service" src/ tests/ --include="*.py"
grep -rn "wba-web\|wba-internal\|wba-admin-api" src/ tests/ deploy/ .env.example docker-compose.yml
grep -rn "wba-admin\|wba-user\|wba-service\|wba-web\|wba-internal\|wba-admin-api" docs/design/authn-authz-design.md CLAUDE.md INSTALL_GUIDE.md
```
All three → no output.

```
grep -rn '"wba"' src/ui/ --include="*.py"
```
→ at least 10 matches, in `person_picker.py`, `graph/callbacks/catalog.py`,
`graph/callbacks/query.py`, `graph/utils/cypher_substitution.py`,
`collaboration_network_ego/callbacks/filter.py`. If this returns nothing, you have corrupted
the person-id key — revert and restart.

```
grep -n "_internal_role" src/ tests/
```
→ no output.

```
grep -n "wba-service\|wba-internal\|wba-web" deploy/keycloak/realm-wba.json.template
```
→ no output. And `python -c "import json;json.load(open('deploy/keycloak/realm-wba.json.template'))"`
→ exit 0 (the template is valid JSON despite its `${...}` placeholders, which are inside
string values; if this fails, the template was already invalid and the failure is not yours).

Then the full gate set:

```
pytest -m unit tests -q
mypy src/
pylint src --score=y
flake8
bandit -c .bandit.yml -r src/ -lll
```

All must pass. `mypy` is strict — if `internal = list(roles)` in `require_roles` infers
`list[str]` correctly no annotation is needed, but if `mypy` complains, annotate it
`internal: list[str] = list(roles)`.

**Commit** the Step 1 changes as one commit. Do not commit `.env`.

### Step 2: Manual re-seed and end-to-end verification (human step — do not run this as part of code work)

This step is for the operator. It requires the Compose stack, destroys the Keycloak realm
database, and flushes the application's session table. Safe only on a dev stack.

**Before starting: confirm with the operator.** This destroys every Keycloak session, every
refresh token, and every role assignment made through the User Management page since the last
re-seed. Get an explicit go.

1. **Update `.env`** — this is not in git, so the `.env.example` edit in Step 1 does not
   reach it. Set:
   ```
   KEYCLOAK_CLIENT_ID=web
   KEYCLOAK_SERVICE_CLIENT_ID=internal
   KEYCLOAK_ADMIN_CLIENT_ID=admin-api
   ```
   Leave `KEYCLOAK_ISSUER`, `KEYCLOAK_INTERNAL_URL` and `KEYCLOAK_REALM` unchanged (the realm
   is still `wba`). Leave `KEYCLOAK_*_SECRET` values unchanged — only the ids change.

2. **Re-seed the realm.** `--import-realm` is create-only, so the realm must not exist at
   import time:
   ```bash
   docker compose stop keycloak
   docker compose exec postgres psql -U postgres -c 'DROP DATABASE IF EXISTS keycloak WITH (FORCE);'
   docker compose exec postgres psql -U postgres -c 'CREATE DATABASE keycloak OWNER keycloak;'
   docker compose up -d --force-recreate keycloak
   docker compose logs -f keycloak   # wait for "Importing realm" then successful startup
   ```

3. **Flush the stale session rows.** `auth_session.roles` holds a JSONB snapshot written at
   login and refresh (`src/app/api/auth/v1/service.py:248,355`) and never read for
   authorization — `Principal` is always rebuilt from the token
   (`src/app/auth/tokens.py:174`, the only `Principal(...)` construction in `src/`). The
   re-seed has already invalidated every one of these sessions at Keycloak, so the rows are
   dead; deleting them keeps the audit trail free of role names that no longer exist.
   ```bash
   docker compose exec postgres psql -U postgres -d postgres -c 'TRUNCATE auth_session;'
   ```
   Expected: `TRUNCATE TABLE`.

4. **Rebuild and recreate every service that reads a client id.** The producer and consumer
   images copy `src/common/` and `src/connectors/` at build time with no source bind-mount, so
   a `--force-recreate` alone serves the old default client id:
   ```bash
   docker compose build api ui github-producer jira-producer confluence-producer signal-consumer
   docker compose up -d --force-recreate
   docker compose logs api | tail -20
   ```
   Note that `ui` must be rebuilt too — `src/domain/settings.py`'s `UISettings` carries
   `KEYCLOAK_CLIENT_ID`.

5. **Prove the roles are live.** Mint an admin bearer and check the claims:
   ```bash
   PYTHONPATH=src python scripts/get_token.py --role admin --json
   ```
   Decode the `access_token`'s `realm_access.roles` and confirm it contains `admin` and
   `standard-user`, and **not** `wba-admin` or `wba-user`.
   ```bash
   curl -sk -H "Authorization: Bearer <admin token>" https://localhost/api/v1/auth/me
   ```
   → `roles` is `["admin", "standard-user"]`.
   ```bash
   curl -sk -H "Authorization: Bearer <admin token>" https://localhost/api/v1/admin/users/
   ```
   → contains `dev-admin` and `dev-user`, no `service-account-*` entry.
   With a `--role user` token against that same URL → `403`. With no token → `401`.

6. **Prove the downgrade path still works.** The `_internal_role` deletion is the highest-risk
   change in this plan, so exercise the route that depends on `require_roles`:
   ```bash
   curl -sk -X POST -H "Authorization: Bearer <admin token>" \
     -H 'Content-Type: application/json' -d '{"command_type":"scan","target":"github"}' \
     https://localhost/api/v1/commands/
   ```
   → not `403`. Repeat with the `--role service` token → not `403`. Repeat with the
   `--role user` token → `403` with `insufficient_role`.

7. **Prove the UI.** Open `https://localhost/app/settings`, click **User Management**. The
   Roles info hint must read `admin` and `standard-user`. Create a test user with role
   `standard-user`, sign in as them in a private window, and confirm Settings → User
   Management gives the permission-denied message. Then, as `dev-admin`, promote them to
   `admin` and confirm the change takes effect. Delete the test user when done.

8. **Prove a producer still authenticates** (this is the path a missed client-id edit breaks
   silently, with no CI gate):
   ```bash
   docker compose run --rm github-producer
   docker compose logs github-producer | tail -30
   ```
   → no `401`/`403` from the API and no Keycloak `invalid_client` error.

**Verify**: Steps 5-8 all produce the stated results, and
`docker compose exec postgres psql -U postgres -d postgres -c 'SELECT count(*) FROM auth_session;'`
→ `0` immediately after step 3.

## Test plan

- **No new test files.** This plan renames identifiers; the existing suite is the regression
  gate, and it covers the behavior that could break:
  - `tests/test_auth_dependencies.py` — pins that `require_admin` accepts `admin` and rejects
    `standard-user` with `insufficient_role`, and that an unrecognised role yields 403
    `no_recognised_role`. The parametrize list at line 115 must carry all three new names.
  - `tests/test_auth_tokens.py` — pins that exactly the roles in `_MAPPED_ROLES` survive
    filtering and unknown ones are dropped.
  - `tests/test_authz_matrix.py` — pins the route→grant table against the live app, which is
    what catches a `require_roles` broken by the `_internal_role` deletion at the router
    level.
  - `tests/test_admin_users_service.py` (21 references) — pins the last-admin guard, the
    single heaviest user of the role strings.
- **One assertion needs a deliberate rewrite rather than a substitution**:
  `tests/test_settings_user_management_page.py:164-169`, per Step 1, because
  `"standard-user"` contains `"user"` and the existing `"wba-service" not in` assertion
  depends on non-overlapping substrings.
- Structural pattern for a new test, if the executor judges one is needed: the existing
  `tests/test_auth_dependencies.py` `_stub_valid` + `httpx.ASGITransport` idiom. Do not invent
  a new test style.
- Verification: `pytest -m unit tests -q` → all pass, same test count as before the change
  (no tests added or removed).

## Done criteria

ALL must hold:

- [ ] `pytest -m unit tests -q` exits 0
- [ ] `mypy src/` exits 0
- [ ] `pylint src --score=y` reports 10.00
- [ ] `flake8` exits 0
- [ ] `bandit -c .bandit.yml -r src/ -lll` reports no High severity
- [ ] `grep -rn "wba-admin\|wba-user\|wba-service" src/ tests/ --include="*.py"` → no output
- [ ] `grep -rn "wba-web\|wba-internal\|wba-admin-api" src/ tests/ deploy/ .env.example docker-compose.yml` → no output
- [ ] `grep -n "_internal_role" src/ tests/` → no output
- [ ] `grep -rn '"wba"' src/ui/ --include="*.py"` → still 10+ matches (person-id key untouched)
- [ ] `grep -rn "wba-admin\|wba-user\|wba-service\|wba-web\|wba-internal\|wba-admin-api" docs/ CLAUDE.md INSTALL_GUIDE.md` → no output
- [ ] `git status` shows no modified files outside the Scope list
- [ ] `.env` is not committed
- [ ] `plans/README.md` status row for 002 updated

## STOP conditions

Stop and report back (do not improvise) if:

- Any "Current state" excerpt does not match the live file — the codebase has drifted.
- `_internal_role` has a caller other than the one line in `require_roles`. The plan assumes a
  single caller; a second one means the deletion is not self-contained and the executor must
  report rather than guess.
- `require_roles` is called anywhere with a **short** label (e.g. `require_roles("admin")` with
  no prefix) in the pre-change code. That would mean `_internal_role` was load-bearing today,
  not a pass-through, and the analysis in "Why this matters" is wrong.
- A gate fails twice after a reasonable fix attempt.
- A grep in the Done criteria returns matches in a file **not** listed in the Scope section.
  That is a real occurrence of a literal the plan did not anticipate — report the path and line
  rather than adding it to scope yourself.
- `deploy/keycloak/realm-wba.json.template` renders to invalid JSON after the edits.
- Step 2's re-seed fails and the operator cannot reach a clean Keycloak — a half-imported realm
  is worse than the old one, and recovery is an operator decision.
- You conclude a producer image needs a source change not listed in Scope in order to
  authenticate after the rename.

## Maintenance notes

- **The realm rename path is now unblocked.** The realm kept the name `wba` in this change; if
  it is ever renamed, `KEYCLOAK_ISSUER`, `KEYCLOAK_INTERNAL_URL`, `KEYCLOAK_REALM`, the
  discovery `iss` match in `src/app/auth/tokens.py`, `src/common/auth/service_token.py`'s
  `_DEFAULT_REALM_URL`, and `src/common/auth/pkce_login.py`'s hardcoded
  `/auth/realms/wba` must all move together, and every existing token's `iss` changes.
- **`_internal_role` must not come back.** Its absence is what makes `require_roles` and
  `AUTHZ_MATRIX` share one vocabulary. A future change that reintroduces a prefix difference
  between grant labels and realm role names will need the same helper again — and will
  reintroduce the silent-403 trap the moment a caller passes a short label.
- **A reviewer should scrutinize**: the `deploy/keycloak/realm-wba.json.template` diff, because
  the audience mappers (`included.client.audience`) are easy to miss and their mismatch
  rejects every token with a confusing `azt/aud` error; and the `require_roles` edit, because
  a wrong `internal` assignment 403s command creation without failing any unit test that
  stubs the dependency.
- **Deferred, deliberately**: `auth_session.roles` keeps no historical mapping. The rows are
  truncated during the re-seed rather than migrated, because the column is a write-only
  snapshot and the re-seed destroys the sessions it describes. If the column ever becomes
  read for authorization, this decision must be revisited.
- **Deferred, deliberately**: no `wba-` prefix remains on the `wba_session` cookie, the
  `DEV_WBA_*` env vars, the `dev-admin`/`dev-user` usernames, or the `wba-ai-*` Compose names.
  These were considered and excluded as a scope decision, so a future reader should not read
  their survival as an oversight.

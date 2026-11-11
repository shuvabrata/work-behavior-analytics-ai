# Plan 001: Admin user management in the app (Keycloak Admin API + Settings page)

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat f40514db..HEAD -- src/app/auth src/app/api src/app/api_main.py src/app/settings.py src/domain/settings.py src/ui .env.example scripts/setup.sh deploy/keycloak docs/design/authn-authz-design.md CLAUDE.md tests/test_authz_matrix.py`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: L
- **Risk**: MED
- **Depends on**: none
- **Category**: direction
- **Planned at**: commit `f40514db`, 2026-11-11

## Why this matters

Today the only way to create a user, assign `wba-admin`/`wba-user`, reset a
password or disable an account is the Keycloak admin console, which is
deliberately unpublished and reachable only through a manual loopback port
change. That makes ordinary user administration an operator task requiring
shell access to the stack.

This plan adds a `wba-admin`-only user-management surface to the app: a new
`/api/v1/admin/users` API that drives the Keycloak Admin REST API on the
admin's behalf, and a **User Management** card on the Settings hub leading to a
sub-page with list/search/create/edit/password/delete.

The API stays the single enforcement point (`wba-admin`), the UI stays
credential-free (it calls the API with a BFF-minted bearer like every other
page), and the Keycloak admin surface stays unpublished. Deleting a user also
cleans up that subject's app-owned rows (`auth_session`, `catalog_metadata`) in
a fire-and-forget background task, so offboarding leaves nothing behind.

## Current state

Read these before starting; each is load-bearing.

### Auth stack

- `src/app/auth/dependencies.py` — `require_admin`, `require_user`,
  `require_service`, `require_roles(*roles)`. `require_admin` raises `403`
  `{"error": "insufficient_role", "message": ...}`. Use `require_admin`.
- `src/app/auth/tokens.py` — JWKS bearer validation. Not modified by this plan.
- `src/app/auth/principal.py` — `Principal(subject, username, roles, full_name,
  credential)`. `principal.subject` is the Keycloak `sub`, which **equals the
  Keycloak user id**.
- `src/app/auth/matrix.py` — the declarative grant table. Every route must have
  a row or CI fails.
- `src/common/auth/service_token.py` — existing cached client-credentials token
  helper. **Do not modify it and do not reuse it.** It is connector-runtime code
  that reads `os.environ` and is hardcoded to the `wba-internal` client. The new
  client is separate (Step 3).

### Router wiring

`src/app/api_main.py` includes every router at `/api/v1`. Current shape:

```python
app.include_router(settings_v1_router, prefix="/api/v1", dependencies=[Depends(require_user)])
...
app.include_router(auth_v1_router, prefix="/api/v1")
```

The new router is included with `dependencies=[Depends(require_admin)]` so every
operation it exposes is admin-only, matching `AUTHZ_MATRIX` rows of `"admin"`.

### Persistence

- `src/app/db/session.py` — `ASYNC_SESSION_LOCAL` is an `async_sessionmaker`;
  `get_async_db` is the request-scoped dependency. The background cleanup task
  must open its **own** session via `ASYNC_SESSION_LOCAL()`, never reuse the
  request's.
- `src/app/db/models/auth_session.py` — table `auth_session`, column
  `subject: Mapped[str]` (indexed), `revoked_at: Mapped[datetime | None]`.
- `src/app/db/models/catalog_metadata.py` — table `catalog_metadata`, column
  `subject: Mapped[str]` (indexed), unique `(catalog_id, subject)`.
- Chat sessions are **not** database rows — they live in an in-process dict in
  `app/ai_agent`. Do not attempt to clean them up.

### Settings split (must be preserved)

- `src/domain/settings.py` — `UISettings`: non-secret config, instantiated bare
  by the UI runtime. Client **ids** live here (`KEYCLOAK_CLIENT_ID`,
  `KEYCLOAK_SERVICE_CLIENT_ID`).
- `src/app/settings.py` — `ApiSettings(UISettings)`: everything only the API may
  hold. Client **secrets** live here (`KEYCLOAK_CLIENT_SECRET`,
  `KEYCLOAK_SERVICE_CLIENT_SECRET`).

### Keycloak deployment

- `deploy/keycloak/realm-wba.json.template` — realm-as-code, rendered by
  `deploy/keycloak/entrypoint.sh`, imported on first boot with `--import-realm`.
- `deploy/keycloak/entrypoint.sh` — performs bash substitution of a fixed list of
  `${NAME}` placeholders and fatals on a leftover `${`.
- `docker-compose.yml` `keycloak` service uses `KC_HOSTNAME_ADMIN` on a loopback
  origin; `/auth/admin` is **404 through nginx**. The Admin REST API is
  reachable only over the Docker network at
  `KEYCLOAK_INTERNAL_URL`'s origin.
- The design doc states `--import-realm` is **create-only**: editing the
  template has no effect on an existing realm. Step 8 (manual) is the re-seed
  the user runs.

### UI conventions

- `src/ui/pages/settings/layout.py` — the hub: three `hub_card(...)` calls.
- `src/ui/pages/settings/__init__.py` — re-exports each sub-page's layout
  function and imports `.callbacks` for registration.
- `src/ui/layout.py` — `display_page` matches a `routes` dict; unknown paths fall
  through to the Graph page, so a new route needs an explicit entry.
- `src/ui/components/hub_card.py` — `hub_card(card_id, title, icon,
  description, *, href=None, coming_soon=False, card_type)`.
- `src/ui/components/common.py` — `create_page_header`, `create_alert`,
  `create_permission_denied_alert`, `handle_api_error`.
- `src/ui/api_client.py` — `get_json`, `post_json`, `put`, `patch`, `delete`;
  `ApiError` with subclasses `AuthExpiredError` (401) and
  `PermissionDeniedError` (403). All calls go through here.
- `src/ui/pages/settings/graph_styling/` is the exemplar package for a settings
  sub-page: `__init__.py` (imports callbacks), `layout.py`, `callbacks.py`,
  `components.py`.
- `src/ui/pages/settings/graph_styling/callbacks.py` shows the mandatory
  two-stage `dcc.ConfirmDialog` pattern (`click → store pending id`,
  `Input("...-confirm", "submit_n_clicks") → act`).

### Repo rules that apply

- `PYTHONPATH=src` for anything importing app code (pytest.ini sets it for
  tests).
- Every new function needs full annotations — mypy is strict on `src/`.
- pylint score must stay ≥ 10.0; flake8 max-line-length 120.
- No comments that narrate what code does. Comments explain **why** only.
- Never log a password, token, or client secret.
- Tests must carry a marker (`pytestmark = pytest.mark.unit`).

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Unit tests | `source .venv/bin/activate && pytest -m unit tests -q` | all pass |
| One module | `pytest -m unit tests/test_admin_users_service.py -q` | all pass |
| Matrix test | `pytest -m unit tests/test_authz_matrix.py -q` | all pass |
| Typecheck | `PYTHONPATH=src mypy src/` | exit 0 |
| Lint | `PYTHONPATH=src pylint src --score=y` | score 10.00/10 |
| Style | `flake8` | exit 0 |
| Security scan | `bandit -c .bandit.yml -r src/ -lll` | exit 0 |

## Scope

**In scope** (the only files to create/modify):

- `src/app/auth/keycloak_admin.py` (create)
- `src/app/api/admin_users/__init__.py` (create)
- `src/app/api/admin_users/v1/__init__.py` (create)
- `src/app/api/admin_users/v1/model.py` (create)
- `src/app/api/admin_users/v1/router.py` (create)
- `src/app/api/admin_users/v1/service.py` (create)
- `src/app/api/admin_users/v1/query.py` (create)
- `src/app/api/admin_users/v1/cleanup.py` (create)
- `src/app/api_main.py` (add one import + one `include_router`)
- `src/app/auth/matrix.py` (add six rows)
- `src/app/settings.py` (add one secret field)
- `src/domain/settings.py` (add one client-id field)
- `src/ui/pages/settings/layout.py` (add card + card→route mapping)
- `src/ui/pages/settings/callbacks.py` (generalise click routing)
- `src/ui/pages/settings/__init__.py` (export the new layout)
- `src/ui/pages/settings/user_management/__init__.py` (create)
- `src/ui/pages/settings/user_management/layout.py` (create)
- `src/ui/pages/settings/user_management/callbacks.py` (create)
- `src/ui/layout.py` (add one route)
- `.env.example` (document two new variables)
- `scripts/setup.sh` (generate the new secret)
- `deploy/keycloak/realm-wba.json.template` (new client + service account)
- `deploy/keycloak/entrypoint.sh` (substitute the new secret placeholder)
- `docs/design/authn-authz-design.md` (document the feature)
- `CLAUDE.md` (env vars + route group)
- `plans/README.md` (index)
- Tests (create): `tests/test_keycloak_admin_client.py`,
  `tests/test_admin_users_service.py`, `tests/test_admin_users_cleanup.py`,
  `tests/test_admin_users_api.py`, `tests/test_settings_user_management_page.py`
- Tests (modify): `tests/test_authz_matrix.py` (new rows and the operation
  count), `tests/test_authz_enforcement.py` (representative admin-only cases)

**Out of scope** (do NOT touch):

- `src/common/auth/service_token.py` — connector runtime; do not parameterise it.
- `src/app/auth/tokens.py`, `src/app/api/auth/v1/*` — login/session flow is
  unchanged.
- `IAM_ADMIN_GUIDE.md` — the operator updates it separately; do not edit.
- `src/app/api/chats/**` — chat sessions are in-process and not part of cleanup.
- Group management, identity-provider links, user sessions/force-logout, email
  actions, custom attributes — deferred, not part of iteration 1.
- Any migration — this plan adds no database columns or tables.

## Background: Keycloak Admin REST endpoints used

All calls use `Authorization: Bearer <admin-client token>` and a base URL
derived by replacing `/realms/` with `/admin/realms/` in
`KEYCLOAK_INTERNAL_URL` (e.g. `http://keycloak:8080/auth/realms/wba` →
`http://keycloak:8080/auth/admin/realms/wba`). **Never derive from
`KEYCLOAK_ISSUER`** — that is the browser URL and `/auth/admin` is 404 there.

| Operation | Request | Success |
|---|---|---|
| Token | `POST {realm}/protocol/openid-connect/token`, `grant_type=client_credentials` | 200 `{access_token, expires_in}` |
| List users | `GET {admin}/users?first=&max=&search=&briefRepresentation=false` | 200 `[user...]` |
| Count users | `GET {admin}/users/count?search=` | 200 integer |
| Get user | `GET {admin}/users/{id}` | 200 user / 404 |
| Create user | `POST {admin}/users` | 201 + `Location` header ending in the new id |
| Update user | `PUT {admin}/users/{id}` | 204 |
| Delete user | `DELETE {admin}/users/{id}` | 204 |
| Reset password | `PUT {admin}/users/{id}/reset-password`, body `{"type":"password","value":...,"temporary":true}` | 204 / 400 (policy) |
| Realm role mappings | `GET {admin}/users/{id}/role-mappings/realm` | 200 `[{id,name}, ...]` |
| Role definition | `GET {admin}/roles/{role-name}` | 200 `{id,name,...}` |
| Assign roles | `POST {admin}/users/{id}/role-mappings/realm`, body `[{id,name}, ...]` | 204 |
| Remove roles | `DELETE {admin}/users/{id}/role-mappings/realm`, body `[{id,name}, ...]` | 204 |
| Users with a role | `GET {admin}/roles/{role-name}/users` | 200 `[user...]` |

A user representation from `GET /users` carries `id`, `username`, `email`,
`firstName`, `lastName`, `enabled`, `createdTimestamp`, and — for a service
account with `briefRepresentation=false` — a non-empty `serviceAccountClientId`.

## Steps

### Step 1: Settings — client id and secret

`src/domain/settings.py`, in the Authentication block next to
`KEYCLOAK_SERVICE_CLIENT_ID`:

```python
    KEYCLOAK_ADMIN_CLIENT_ID: str = "wba-admin-api"
```

`src/app/settings.py`, next to `KEYCLOAK_SERVICE_CLIENT_SECRET`:

```python
    KEYCLOAK_ADMIN_CLIENT_SECRET: str = ""
```

The id goes on `UISettings` (non-secret, same placement as the other ids); the
secret on `ApiSettings` (secret, API-only). This preserves the documented split.

**Verify**: `PYTHONPATH=src python -c "from app.settings import settings; print(settings.KEYCLOAK_ADMIN_CLIENT_ID, repr(settings.KEYCLOAK_ADMIN_CLIENT_SECRET))"` → prints `wba-admin-api ''` (or the `.env` value if one is set).

### Step 2: `.env.example` and `scripts/setup.sh`

`.env.example`, in the "Keycloak / authentication" block after
`KEYCLOAK_SERVICE_CLIENT_ID`:

```
KEYCLOAK_ADMIN_CLIENT_ID=wba-admin-api
```

In the "Keycloak credentials — no defaults" block after
`KEYCLOAK_SERVICE_CLIENT_SECRET`, add a `FIXME` placeholder for
`KEYCLOAK_ADMIN_CLIENT_SECRET` with a comment naming it the secret for the
`wba-admin-api` client (which the API exchanges for a Keycloak admin token).

`scripts/setup.sh`: add `"KEYCLOAK_ADMIN_CLIENT_SECRET"` to the
`KEYCLOAK_SECRET_KEYS` array. Do not add the client id — it is not a secret.

**Verify**: `grep -n "KEYCLOAK_ADMIN_CLIENT" .env.example scripts/setup.sh` → two matches in `.env.example` (id + secret), one in `scripts/setup.sh`.

### Step 3: `src/app/auth/keycloak_admin.py`

Create the admin HTTP client. Shape:

```python
"""Keycloak Admin REST client for the API runtime.

The API drives Keycloak's admin surface on an administrator's behalf. It uses a
dedicated `wba-admin-api` client (client-credentials) whose service account
holds realm-management roles; that client carries no `wba-*` realm role and its
id is deliberately absent from `app.auth.tokens._service_client_ids()`, so its
tokens can never authenticate an application request.

The base URL is derived from KEYCLOAK_INTERNAL_URL, never from KEYCLOAK_ISSUER:
the admin API is not reachable on the public origin (nginx 404s /auth/admin).
"""
```

Public surface (all functions typed; use `requests` — already a dependency):

- `class KeycloakAdminError(Exception)` — base.
- `class KeycloakUnavailableError(KeycloakAdminError)` — transport failure, 5xx,
  token fetch failure, or **401 from the admin API** (a misconfigured client
  secret is our fault, not the caller's).
- `class KeycloakNotFoundError(KeycloakAdminError)`.
- `class KeycloakConflictError(KeycloakAdminError)`.
- `class KeycloakPolicyError(KeycloakAdminError)` — carries Keycloak's message.
- `admin_base_url() -> str` — `settings.KEYCLOAK_INTERNAL_URL` with
  `/realms/` replaced by `/admin/realms/`; raise `KeycloakUnavailableError` if
  the substring is absent.
- `_admin_token() -> str` — module-level cache `(token, expires_at_monotonic)`
  guarded by `threading.Lock`, refresh margin 60 s, failure backoff 30 s, mirroring
  `common/auth/service_token.py` but reading `app.settings`. If
  `KEYCLOAK_ADMIN_CLIENT_SECRET` is empty, raise `KeycloakUnavailableError`
  with a message naming the setting.
- `_request(method, path, *, params=None, json_body=None) -> requests.Response`
  — attaches the bearer, timeout `settings.HTTP_REQUEST_TIMEOUT`, maps status:
  `401`/`403` → `KeycloakUnavailableError`, `404` → `KeycloakNotFoundError`,
  `409` → `KeycloakConflictError`, `400` → `KeycloakPolicyError(response text)`,
  `5xx`/transport → `KeycloakUnavailableError`.
- `list_users(offset, limit, search) -> tuple[list[dict[str, object]], int]` —
  the page plus the count from `GET /users/count`.
- `get_user(user_id) -> dict[str, object]`.
- `create_user(payload) -> str` — returns the id parsed from `Location`.
- `update_user(user_id, payload) -> None`.
- `delete_user(user_id) -> None`.
- `set_password(user_id, password, temporary) -> None`.
- `realm_roles(user_id) -> list[str]` — names only.
- `role_definition(role_name) -> dict[str, object]` — the `{id,name}` payload
  required by the role-mapping endpoints.
- `assign_realm_roles(user_id, role_names) -> None`.
- `remove_realm_roles(user_id, role_names) -> None`.
- `users_with_role(role_name) -> list[dict[str, object]]`.

Never log a token. It is fine to log the admin REST method and path.

**Verify**: `PYTHONPATH=src python -c "from app.auth import keycloak_admin as k; print(k.admin_base_url())"` → prints the internal admin realm URL (e.g. `http://keycloak:8080/auth/admin/realms/wba`).

### Step 4: The API package — models and query layer

Create `src/app/api/admin_users/v1/model.py`:

```python
from pydantic import BaseModel, Field

ASSIGNABLE_REALM_ROLES: frozenset[str] = frozenset({"wba-admin", "wba-user"})

class UserSummary(BaseModel):
    id: str
    username: str
    email: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    enabled: bool
    roles: list[str]
    created_timestamp: int | None = None

class UserListResponse(BaseModel):
    users: list[UserSummary]
    total: int
    offset: int
    limit: int

class UserCreatedResponse(UserSummary):
    warnings: list[str] = Field(default_factory=list)

class UserCreate(BaseModel):
    username: str = Field(min_length=1, max_length=255)
    email: str = Field(min_length=3, max_length=255)
    first_name: str | None = None
    last_name: str | None = None
    enabled: bool = True
    roles: list[str] = Field(min_length=1)
    password: str | None = Field(default=None, min_length=8)

class UserUpdate(BaseModel):
    email: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    enabled: bool | None = None
    roles: list[str] | None = None

class PasswordReset(BaseModel):
    password: str = Field(min_length=8)
    temporary: bool = True
```

Create `src/app/api/admin_users/v1/query.py` — the only module that imports
`app.auth.keycloak_admin`. It translates Keycloak user representations into
`UserSummary` and exposes:

- `list_users(offset, limit, search) -> tuple[list[UserSummary], int]` — calls
  `keycloak_admin.list_users`, then for each non-service-account user calls
  `realm_roles(user["id"])` and intersects with `ASSIGNABLE_REALM_ROLES`.
  Filter out users whose representation has a non-empty
  `serviceAccountClientId`, **or** whose username starts with
  `service-account-` (belt and braces; Keycloak has no server-side filter).
- `get_user(user_id) -> UserSummary` — `KeycloakNotFoundError` propagates.
- `is_service_account(user) -> bool`.
- `create_user(payload) -> str`, `update_user(...)`, `delete_user(...)`,
  `set_password(...)` — thin pass-throughs.
- `current_roles(user_id) -> set[str]` — intersect with the assignable set.
- `users_with_role(role_name) -> list[dict[str, object]]`.

Do not add pagination logic of our own — pass `first`/`max`/`search` straight
through. The filter happens after the page is fetched; a page of 25 may render
24 rows.

**Verify**: `PYTHONPATH=src python -c "from app.api.admin_users.v1.model import ASSIGNABLE_REALM_ROLES as r; print(sorted(r))"` → `['wba-admin', 'wba-user']`.

### Step 5: Service layer

Create `src/app/api/admin_users/v1/service.py`. It owns the rules, and raises
plain exceptions the router maps (matching `app/api/settings/v1/service.py`'s
`ConflictError` style):

- `UserNotFoundError`, `UserExistsError`, `LastAdminError`, `SelfDeleteError`,
  `ServiceAccountError`, `IdentityProviderUnavailableError`,
  `PasswordPolicyError`, `InvalidRoleError`.

Functions (all `async` where they touch the network — the client is sync, so
call it via `asyncio.to_thread` to keep the event loop free, matching
`app/api/queries/v1/router.py`'s use of `asyncio.to_thread`):

- `list_users(offset, limit, search) -> UserListResponse`
- `get_user(user_id) -> UserSummary`
- `create_user(payload) -> UserSummary`
  - Reject any role outside `ASSIGNABLE_REALM_ROLES` with `InvalidRoleError`.
  - Keycloak `409` → `UserExistsError`.
  - After create, if `payload.password` is set call `set_password(..., temporary=True)`.
    If that fails, log and still return the created user (the account exists);
    the router adds `"warnings": ["password_not_set"]` to the response.
- `update_user(user_id, payload) -> UserSummary`
  - Read the current user first (gives `enabled` transition and service-account
    detection).
  - `enabled: false` on a service account → `ServiceAccountError`.
  - **Last-admin guard**: if `enabled is False` and the target currently holds
    `wba-admin`, or if `roles` would remove `wba-admin`, call
    `query.users_with_role("wba-admin")`; if the target is the only holder,
    raise `LastAdminError`.
  - Role diff: add roles in `payload.roles` not currently held, remove assignable
    roles currently held but absent from `payload.roles`. Never touch roles
    outside the assignable set.
  - Return the reloaded user.
- `set_password(user_id, payload) -> None` — service account → `ServiceAccountError`;
  Keycloak `400` → `PasswordPolicyError`.
- `delete_user(user_id, actor) -> None`
  - `actor.subject == user_id` → `SelfDeleteError`.
  - Service account → `ServiceAccountError`.
  - Only admin → `LastAdminError`.
  - `KeycloakNotFoundError` → `UserNotFoundError`.

The router, not the service, schedules cleanup (Step 7): the service returns
normally only after Keycloak has accepted the change, which is the ordering
guarantee the background task depends on.

Every mutating operation logs one structured line at `info` with actor
`sub`/username, target id, and the operation name. Role changes log role names;
password operations log **never** the password. Reads are not logged.

**Verify**: `PYTHONPATH=src python -c "import app.api.admin_users.v1.service"` → exit 0.

### Step 6: Cleanup module

Create `src/app/api/admin_users/v1/cleanup.py`. This is the dedicated, extensible
home for per-user data cleanup.

```python
"""Per-subject cleanup of application rows after a user is deleted or disabled.

Each step is an isolated unit: one step raising must not prevent the next from
running, because leaving a live session behind is worse than leaving a favourite
behind. The whole job is fire-and-forget — the router schedules it only after
Keycloak has accepted the delete/disable — so failures are logged, never raised.
"""

CleanupStep = Callable[[AsyncSession, str], Awaitable[int]]

async def _purge_auth_sessions(session: AsyncSession, subject: str) -> int
async def _purge_catalog_metadata(session: AsyncSession, subject: str) -> int
async def _revoke_auth_sessions(session: AsyncSession, subject: str) -> int

_PURGE_STEPS: tuple[CleanupStep, ...] = (_purge_auth_sessions, _purge_catalog_metadata)
_REVOKE_STEPS: tuple[CleanupStep, ...] = (_revoke_auth_sessions,)

async def purge_user_data(subject: str) -> None
async def revoke_user_sessions(subject: str) -> None
```

- `_purge_auth_sessions`: `delete(AuthSession).where(AuthSession.subject == subject)`.
- `_purge_catalog_metadata`: `delete(CatalogMetadata).where(CatalogMetadata.subject == subject)`.
- `_revoke_auth_sessions`: `update(AuthSession).where(AuthSession.subject == subject,
  AuthSession.revoked_at.is_(None)).values(revoked_at=func.now())`.
- `_run(steps, subject)`: `async with ASYNC_SESSION_LOCAL() as session:`; for each
  step, `try: count = await step(...); await session.commit(); logger.info(...)`
  `except Exception: await session.rollback(); logger.error(..., exc_info=True)`.
  Never re-raise.
- `purge_user_data` / `revoke_user_sessions` are thin wrappers over `_run`.

Future per-user data is added by appending a step to the tuple — the docstring
says so.

**Verify**: `PYTHONPATH=src python -c "import app.api.admin_users.v1.cleanup as c; print(len(c._PURGE_STEPS), len(c._REVOKE_STEPS))"` → `2 1`.

### Step 7: Router, matrix, mount

Create `src/app/api/admin_users/v1/router.py`:

```python
router = APIRouter(prefix="/admin/users", tags=["admin-users"])
```

Routes (all admin — the dependency is supplied at include time):

- `GET "/"` → `UserListResponse`; query params `offset: int = Query(0, ge=0)`,
  `limit: int = Query(25, ge=1, le=100)`, `search: str | None = None`.
- `POST "/"` → `201`, body `UserCreate`, response `UserCreatedResponse`. When the
  account was created but the password could not be set, return
  `warnings: ["password_not_set"]`; otherwise an empty list.
- `GET "/{user_id}"` → `UserSummary`.
- `PATCH "/{user_id}"` → `UserSummary`, body `UserUpdate`.
- `PUT "/{user_id}/password"` → `204`, body `PasswordReset`.
- `DELETE "/{user_id}"` → `204`. Signature includes
  `background: BackgroundTasks` (import from `fastapi`). After
  `await service.delete_user(...)` returns successfully, call
  `background.add_task(cleanup.purge_user_data, user_id)`. Nothing is scheduled
  when the service raises.
- `PATCH "/{user_id}"` schedules `background.add_task(cleanup.revoke_user_sessions,
  user_id)` **only** when the update transitions `enabled` from `True` to
  `False`.

The router maps service exceptions to HTTP responses:

| Exception | Status | `detail.error` |
|---|---|---|
| `UserNotFoundError` | 404 | `user_not_found` |
| `UserExistsError` | 409 | `user_exists` |
| `LastAdminError` | 409 | `last_admin` |
| `SelfDeleteError` | 409 | `self_delete` |
| `ServiceAccountError` | 409 | `service_account` |
| `InvalidRoleError` | 422 | `invalid_role` |
| `PasswordPolicyError` | 422 | `password_policy` |
| `IdentityProviderUnavailableError` / `KeycloakUnavailableError` | 503 | `identity_provider_unavailable` |

Use `detail={"error": ..., "message": ...}` — the UI's `api_client` reads
`detail["error"]` and `detail["message"]`.

Then:

1. `src/app/api/admin_users/__init__.py` and `src/app/api/admin_users/v1/__init__.py`
   — module docstrings only.
2. `src/app/api_main.py` — import the router and include it:
   ```python
   app.include_router(admin_users_v1_router, prefix="/api/v1", dependencies=[Depends(require_admin)])
   ```
   Import `require_admin` alongside the existing `require_user` import.
3. `src/app/auth/matrix.py` — add six rows under a new `# admin users` comment.
   Note the **trailing slash** on the collection routes: the router declares
   `@router.get("/")` / `@router.post("/")` under `prefix="/admin/users"`, so the
   live path templates end in `/`, exactly as `("/api/v1/settings/", ...)` does
   under `prefix="/settings"`:
   ```python
   ("GET", "/api/v1/admin/users/"): "admin",
   ("POST", "/api/v1/admin/users/"): "admin",
   ("GET", "/api/v1/admin/users/{user_id}"): "admin",
   ("PATCH", "/api/v1/admin/users/{user_id}"): "admin",
   ("PUT", "/api/v1/admin/users/{user_id}/password"): "admin",
   ("DELETE", "/api/v1/admin/users/{user_id}"): "admin",
   ```
4. `tests/test_authz_matrix.py` — `test_enumeration_is_non_empty` asserts the
   exact operation count. It is **58** today; adding six routes makes it **64**.
   Update the number and its docstring if it mentions one.

**Verify**: `pytest -m unit tests/test_authz_matrix.py -q` → all pass.

### Step 8: Realm template and entrypoint

`deploy/keycloak/realm-wba.json.template` — add to `clients`:

```json
    {
      "clientId": "${KEYCLOAK_ADMIN_CLIENT_ID}",
      "name": "WBA Admin API (user management)",
      "enabled": true,
      "protocol": "openid-connect",
      "publicClient": false,
      "bearerOnly": false,
      "standardFlowEnabled": false,
      "implicitFlowEnabled": false,
      "directAccessGrantsEnabled": false,
      "serviceAccountsEnabled": true,
      "secret": "${KEYCLOAK_ADMIN_CLIENT_SECRET}"
    }
```

and to `users`:

```json
    {
      "username": "service-account-wba-admin-api",
      "enabled": true,
      "serviceAccountClientId": "wba-admin-api",
      "clientRoles": {
        "realm-management": ["view-users", "query-users", "manage-users", "view-realm"]
      }
    }
```

`view-users`/`query-users` cover reads and search; `manage-users` covers create,
update, delete, password and role mappings; `view-realm` lets it read role
definitions.

`deploy/keycloak/entrypoint.sh`:

- Add `KEYCLOAK_ADMIN_CLIENT_ID` and `KEYCLOAK_ADMIN_CLIENT_SECRET` to the
  required-variable checks (`: "${...:?}"`).
- Add both names to the substitution `for name in ...` list.
- The existing leftover-`${` check then covers a misspelling.

`docker-compose.yml` `keycloak` service already receives `APP_PUBLIC_BASE_URL`,
`KEYCLOAK_CLIENT_SECRET`, `KEYCLOAK_SERVICE_CLIENT_SECRET` and the dev
passwords as environment; add `KEYCLOAK_ADMIN_CLIENT_ID:
${KEYCLOAK_ADMIN_CLIENT_ID}` and `KEYCLOAK_ADMIN_CLIENT_SECRET:
${KEYCLOAK_ADMIN_CLIENT_SECRET}` next to them. (The `api` service mounts `.env`
read-only, so `ApiSettings` picks the secret up with no compose change.)

**Verify**: `grep -n "KEYCLOAK_ADMIN_CLIENT" deploy/keycloak/entrypoint.sh docker-compose.yml deploy/keycloak/realm-wba.json.template` → matches in all three.

### Step 9: Unit tests — backend

All tests are `pytestmark = pytest.mark.unit`, no live services, Keycloak stubbed.

**`tests/test_keycloak_admin_client.py`** — stub `requests.request`/`requests.post`
via monkeypatch. Cases:

- `admin_base_url()` rewrites `/realms/` → `/admin/realms/`, and raises when the
  substring is absent.
- Token is cached: two calls, one token POST.
- A `401` from the admin API raises `KeycloakUnavailableError`, **not** a 401
  through to the caller.
- `404` → `KeycloakNotFoundError`; `409` → `KeycloakConflictError`; `400` →
  `KeycloakPolicyError`.
- `create_user` parses the id from the `Location` header.
- `set_password` posts `{"type": "password", "value": ..., "temporary": ...}`.

**`tests/test_admin_users_service.py`** — stub the `query` module's functions
(monkeypatch attributes on `app.api.admin_users.v1.service.query` or on the
`keycloak_admin` module) so no HTTP happens. Cases:

- create rejects a role outside the assignable set (`InvalidRoleError`).
- create maps Keycloak conflict to `UserExistsError`.
- create with a password calls `set_password(..., temporary=True)`.
- update: removing `wba-admin` when the target is the only admin raises
  `LastAdminError`.
- update: disabling the only admin raises `LastAdminError`.
- update: disabling a non-admin does not.
- update: role diff assigns added and removes dropped assignable roles and leaves
  non-assignable roles alone.
- delete: self-delete raises `SelfDeleteError`.
- delete: service account raises `ServiceAccountError`.
- delete: the only admin raises `LastAdminError`.
- list: service accounts are filtered out.

**`tests/test_admin_users_cleanup.py`** — fake `AsyncSession` recording
`execute`/`commit`/`rollback`. Cases:

- `purge_user_data` invokes both purge steps with the subject.
- a step raising does not prevent the next from running, and the error is logged.
- `revoke_user_sessions` invokes the revoke step.
- no exception escapes `purge_user_data`.

**`tests/test_admin_users_api.py`** — drive `app.api_main.app` through
`httpx.ASGITransport` with the real dependencies, clearing the conftest admin
override via the `unauthenticated` fixture and installing a principal, following
`tests/test_authz_enforcement.py`. Cases:

- no bearer → 401 on every new route.
- `wba-user` bearer → 403 on every new route.
- `wba-admin` bearer with `service`/`query` stubbed → `DELETE` schedules cleanup
  exactly once with the target id.
- a Keycloak failure during delete schedules **no** cleanup.
- a `KeycloakUnavailableError` maps to 503 `identity_provider_unavailable`.

**Verify**: `pytest -m unit tests/test_keycloak_admin_client.py tests/test_admin_users_service.py tests/test_admin_users_cleanup.py tests/test_admin_users_api.py -q` → all pass.

### Step 10: UI page package

Create `src/ui/pages/settings/user_management/` mirroring
`settings/graph_styling/`.

`__init__.py`:

```python
"""User Management settings page package."""

from .layout import get_layout

# pylint: disable=unused-import
from . import callbacks  # noqa: F401

__all__ = ["get_layout"]
```

`layout.py` — `get_layout() -> html.Div` containing:

- `create_page_header([("Settings", "/app/settings"), ("User Management", None)], "<description>")`.
- A feedback region `html.Div(id="um-feedback")` at the top of the section.
- A search input `dcc.Input(id="um-search", debounce=True)` and a
  `dbc.Button(id="um-create-open", color="primary", outline=True)` "New user".
- A paged table rendered by a helper `_render_table(users)` as a `dbc.Table`
  with columns: Username, Name, Email, Roles, Enabled, Actions. Actions per row
  are pattern-matching buttons keyed `{"type": "um-row", "action": "edit"|"password"|"delete", "user_id": <id>}`.
- Prev/Next buttons `um-prev` / `um-next` and a hidden `dcc.Store(id="um-state",
  data={"offset": 0, "limit": 25, "search": ""})`.
- `dbc.Modal` components: `um-create-modal`, `um-edit-modal`,
  `um-password-modal`, each with the fields described below and save/cancel
  buttons.
- `dcc.ConfirmDialog(id="um-delete-confirm", message=...)`.
- `dcc.Store(id="um-pending-delete", data=None)` holding the pending user id +
  username.

Follow the design-system tokens from `ui/styles.py` (`COLOR_*`, `FONT_*`,
`SPACING_*`, `CARD_CONTAINER_STYLE`); do not invent sizes or colors.

Form fields:

| Form | Fields |
|---|---|
| Create | username*, email*, first name, last name, enabled checkbox, role checkboxes (`wba-user` checked by default), optional temporary password |
| Edit | email, first name, last name, enabled checkbox, role checkboxes |
| Password | password*, "Require change on first login" checkbox (checked) |

Role checkboxes are built from a module constant
`ASSIGNABLE_ROLES = ("wba-admin", "wba-user")` — `wba-service` must never appear.

`callbacks.py`:

- **Load/refresh**: listens to `url` pathname, `um-state.data`, search submit,
  prev/next and a `um-refresh` trigger store. Calls
  `api_client.get_json("/api/v1/admin/users/", params={...})`, renders the table
  and pagination; a `PermissionDeniedError` renders
  `create_permission_denied_alert("manage users")` in `um-feedback`; any other
  `ApiError` renders a danger alert with the message.
- **Create**: open modal → on save `api_client.post_json("/api/v1/admin/users/",
  {...})` → close, refresh, success alert. A `409` shows
  "A user with that username or email already exists." A `422` shows the
  Keycloak policy message.
- **Edit**: the row's edit button loads `GET /api/v1/admin/users/{id}` into the
  form, then save calls `api_client.patch(...)`.
- **Password**: `api_client.put(f"/api/v1/admin/users/{id}/password", json={...})`.
- **Delete**: the row's delete button writes `{"user_id": ..., "username": ...}`
  to `um-pending-delete` and sets `um-delete-confirm.displayed = True`; the
  confirm callback (`Input("um-delete-confirm", "submit_n_clicks")`) calls
  `api_client.delete(f"/api/v1/admin/users/{id}")` then refreshes. This is the
  mandatory two-stage destructive pattern.
- All auth errors go through `handle_api_error(exc, "manage users", current_path="/app/settings/user-management")`,
  expanding `no_update` across every output slot.

**Verify**: `PYTHONPATH=src python -c "from ui.pages.settings.user_management import get_layout; print(type(get_layout()).__name__)"` → `Div`.

### Step 11: Hub card, click routing, and the route

`src/ui/pages/settings/layout.py`:

- Add a module constant and the fourth card:
  ```python
  SETTINGS_CARD_ROUTES: dict[str, str] = {
      "runtime": "/app/settings/runtime",
      "graph-styling": "/app/settings/graph-styling",
      "user-management": "/app/settings/user-management",
  }
  ```
- `hub_card(card_id="user-management", title="User Management", icon="fa-solid fa-users",
  description="Create, edit, and remove application users.", href="/app/settings/user-management",
  card_type=SETTINGS_CARD_TYPE)`.

`src/ui/pages/settings/callbacks.py` — replace the hardcoded `if card_id == ...`
chain with a lookup into `SETTINGS_CARD_ROUTES`, importing the constant from
`.layout`. An unknown card id keeps raising `PreventUpdate`.

`src/ui/pages/settings/__init__.py` — import and export the new layout:

```python
from .user_management import get_layout as get_user_management_layout
...
__all__ = [..., "get_user_management_layout"]
```

`src/ui/layout.py` — add `"/app/settings/user-management": settings.get_user_management_layout`
to the `routes` dict.

**Verify**:

```bash
PYTHONPATH=src python -c "
from ui.pages.settings.layout import SETTINGS_CARD_ROUTES, get_layout
def walk(n):
    yield n
    ch = getattr(n, 'children', None)
    if ch is None: return
    for c in (ch if isinstance(ch, (list, tuple)) else [ch]):
        yield from walk(c)
print(sorted(SETTINGS_CARD_ROUTES))
print([n.id for n in walk(get_layout()) if isinstance(getattr(n, 'id', None), dict)])
"
```
→ three route keys and four card ids, including `{'type': 'settings-card', 'card_id': 'user-management'}`.

### Step 12: UI tests

**`tests/test_settings_user_management_page.py`** — follow `tests/test_developer_page.py`
and `tests/test_settings_ui.py`:

- the hub renders a card with `{"type": SETTINGS_CARD_TYPE, "card_id": "user-management"}`;
- `SETTINGS_CARD_ROUTES["user-management"] == "/app/settings/user-management"`;
- the registered nav callback listens on `SETTINGS_CARD_TYPE`
  (`_registered_nav_card_types()` helper, copied from `tests/test_developer_page.py`);
- `display_page("/app/settings/user-management")` returns the page layout
  (call the callback from `create_dash_app()` with the pathname, or import
  `get_layout` and assert the header text);
- the role checkbox list contains `wba-admin` and `wba-user` and **not**
  `wba-service` (walk the component tree);
- the feedback region renders `create_permission_denied_alert(...)` content for a
  `PermissionDeniedError` — call the page's pure render helper directly with a
  stubbed `api_client.set_transport` raising the error, do not hand-build a ctx.

**`tests/test_authz_enforcement.py`** — add two cases to `CASES`/`EXPECTED`:
`("GET", "/api/v1/admin/users/", {})` and
`("DELETE", "/api/v1/admin/users/abc", {})`, both
`{"none": "401", "user": "403", "admin": "allowed", "service": "403"}`.

The "allowed" cells execute the handler, which would otherwise make a real HTTP
call to `keycloak:8080` (a multi-second hang or a confusing DNS error). Add an
autouse fixture to that module patching
`app.auth.keycloak_admin._request` to raise `KeycloakUnavailableError` — the
handler then answers `503`, which is neither `401` nor `403`, so the "allowed"
assertion holds without any network traffic. Do the same in
`tests/test_admin_users_api.py` for cases that are not specifically about
Keycloak behaviour.

**Verify**: `pytest -m unit tests/test_settings_user_management_page.py tests/test_authz_enforcement.py tests/test_authz_matrix.py -q` → all pass.

### Step 13: Documentation

`docs/design/authn-authz-design.md`:

- **Decision Summary**: add a row for in-app user management — the API is the
  enforcement point, Keycloak remains the identity source, and the console stays
  the break-glass path.
- **Keycloak → Realm as code** table: add the `wba-admin-api` client row
  (confidential, service account, client-credentials, no `wba-*` realm role,
  realm-management roles `view-users`/`query-users`/`manage-users`/`view-realm`).
- **New section "User administration"**: the `/api/v1/admin/users` surface, the
  `admin` grant on every operation, service accounts filtered out and rejected on
  write, the guards (self-delete, last-admin, service-account), the error shapes
  including `503 identity_provider_unavailable` for a Keycloak or admin-credential
  failure (explicitly **not** `401`), and cleanup-on-delete/revoke-on-disable.
- **Session Management**: state that disable revokes session rows while role
  changes rely on the existing ≤15-minute refresh.
- **Audit Logging**: name the new events (`user_created`, `user_deleted`,
  `user_role_granted`/`removed`, `user_password_reset`, `user_disabled`,
  `user_cleanup_completed`).
- Correct the sentence that role assignment is done in the console: it is now
  available in-app; the console remains the break-glass path.
- Note that `--import-realm` is create-only, so adding the client requires a
  re-seed (Step 14).

`CLAUDE.md`:

- **Environment configuration → Keycloak / auth**: add
  `KEYCLOAK_ADMIN_CLIENT_ID` and `KEYCLOAK_ADMIN_CLIENT_SECRET`, noting the
  secret is API-only and the id is derivable.
- **Repo conventions**: mention the `/api/v1/admin/*` group is admin-only and
  governed by `src/app/auth/matrix.py`.

**Verify**: `grep -n "wba-admin-api\|admin/users" docs/design/authn-authz-design.md CLAUDE.md` → several matches in both.

### Step 14: Manual verification (human step — do not run this as part of code work)

This step is for the operator. It requires the Compose stack and destroys the
Keycloak realm database, which is safe only on a dev stack.

1. **Add the secret to `.env`** (or let `scripts/setup.sh` generate it):
   `KEYCLOAK_ADMIN_CLIENT_ID=wba-admin-api` and a
   `KEYCLOAK_ADMIN_CLIENT_SECRET` value (`openssl rand -base64 24`).
   The entrypoint fatals without it.
2. **Re-seed the realm** (destructive; the imported realm is replaced):
   ```bash
   docker compose stop keycloak
   docker compose exec postgres psql -U postgres -c 'DROP DATABASE IF EXISTS keycloak WITH (FORCE);'
   docker compose exec postgres psql -U postgres -c 'CREATE DATABASE keycloak OWNER keycloak;'
   docker compose up -d --force-recreate keycloak
   docker compose logs -f keycloak   # wait for "Importing realm" / startup
   ```
3. **Rebuild and start the API** so it picks up the new code:
   ```bash
   docker compose build api && docker compose up -d --force-recreate api
   docker compose logs api | tail -20
   ```
4. **Prove the API**: mint an admin bearer with
   `PYTHONPATH=src python scripts/get_token.py --role admin`, then:
   ```bash
   curl -sk -H "Authorization: Bearer <token>" https://localhost/api/v1/admin/users/
   ```
   Expect `dev-admin` and `dev-user`, and **no** `service-account-*` entry.
   Then with a `wba-user` token expect `403`, and with no token `401`.
5. **Prove the UI**: open `https://localhost/app/settings`, click **User
   Management**.
   - Create `test-manager` with email, role `wba-user`, and a temporary password.
   - Log in as `test-manager` in a private window: it should reach the app and
     be asked to change the password; opening Settings → User Management gives
     the permission-denied message.
   - As `dev-admin`, promote `test-manager` to `wba-admin`; reload and confirm
     the Admin badge.
   - Reset `test-manager`'s password from the page; confirm the new password
     works.
   - Delete `test-manager`; confirm it disappears from the list.
   - Confirm cleanup: `docker compose exec postgres psql -U postgres -d postgres
     -c "SELECT count(*) FROM auth_session WHERE subject='<deleted-sub>';"` → 0.
     Find the sub beforehand with
     `curl -sk -H "Authorization: Bearer <admin token>" https://localhost/api/v1/admin/users/`
     (the `id` field).
   - Confirm the guards: deleting `dev-admin` while it is the only admin is
     refused with "last administrator"; an admin deleting itself is refused.

## Test plan

- New unit tests: the four backend modules listed in Step 9 and the UI module in
  Step 12 — all `pytest.mark.unit`, all with Keycloak and the API stubbed.
- Structural pattern for the API tests: `tests/test_authz_enforcement.py` (the
  `unauthenticated` fixture + `httpx.ASGITransport` + an installed principal).
- Structural pattern for the UI tests: `tests/test_developer_page.py`
  (`_iter_components`, `_registered_nav_card_types`) and
  `tests/test_settings_ui.py` (pure render helpers called directly).
- **No automated test creates, updates or deletes a real Keycloak user.** That
  is Step 14, run by hand.
- Verification: `pytest -m unit tests -q` → all pass, including the new modules.

## Done criteria

ALL must hold:

- [ ] `pytest -m unit tests -q` exits 0; the five new test modules are collected
      and pass.
- [ ] `pytest -m unit tests/test_authz_matrix.py -q` passes with the operation
      count updated to 64.
- [ ] `PYTHONPATH=src mypy src/` exits 0.
- [ ] `PYTHONPATH=src pylint src --score=y` reports 10.00/10.
- [ ] `flake8` exits 0.
- [ ] `bandit -c .bandit.yml -r src/ -lll` exits 0.
- [ ] `grep -rn "KEYCLOAK_ISSUER" src/app/auth/keycloak_admin.py` returns no
      match (the admin client must never derive from the public issuer).
- [ ] `grep -rn "wba-service" src/ui/pages/settings/user_management/` returns no
      match (it is never assignable).
- [ ] `git status --porcelain` shows no file outside the Scope list.
- [ ] `plans/README.md` status row updated.
- [ ] Step 14 left for the operator (it is not run by the executor).

## STOP conditions

Stop and report back (do not improvise) if:

- `test_authz_matrix.py`'s operation count is not 58 before your change (the
  codebase has drifted; re-derive it, do not guess).
- Keycloak's admin API returns a response shape the plan's table does not
  describe (e.g. `POST /users` returns no `Location` header). Report the actual
  body/headers instead of guessing a fallback.
- `deploy/keycloak/entrypoint.sh`'s substitution list or required-variable block
  does not match the description (the file may have been reworked).
- The `api` service turns out not to mount `.env` (then the secret reaches
  `ApiSettings` by another route and compose needs a different change).
- Any guard requires a database table or column that does not exist.
- A test needs a live Keycloak to pass (it must not — that is a design error in
  the test, not a licence to run against the stack).

## Maintenance notes

- **Adding per-user data later** (e.g. saved searches): append a step to
  `_PURGE_STEPS` (and `_REVOKE_STEPS` if it holds session-like state) in
  `cleanup.py`. Do not add logic to the router.
- **Role model changes**: `ASSIGNABLE_REALM_ROLES` in `model.py` is the only
  place the UI's checkbox list and the API's validation derive from. Adding a
  role means adding it there, to the realm template's role list, and to
  `_MAPPED_ROLES` in `src/app/auth/tokens.py`.
- **Scaling the list**: each row costs one `role-mappings/realm` call
  (≈26 Keycloak round trips per page). If the realm grows large, replace that
  with `GET /roles/{role}/users` and membership lookup, or drop roles from the
  list and show them only in the detail view.
- **Cleanup is at-most-once.** If the API process dies between the Keycloak
  delete and the background task finishing, the rows are orphaned with no
  retry. A durable cleanup queue is the follow-up if that becomes real.
- **A reviewer should scrutinize**: that no code path lets an admin delete or
  demote the last admin or themselves; that `401` from Keycloak never becomes a
  `401` to the browser; that no password or secret is logged or echoed; and that
  the cleanup is scheduled only after the Keycloak call succeeds.
- **Deferred**: groups, identity-provider links, session inspection/force
  logout, email-driven invites, custom user attributes, and role filtering in
  the list.

# Plan 054: Add the `Principal`, JWT validation, and the `auth_session` table

> **Executor instructions**: This plan is **one step with one manual gate**.
> Work through the ordered parts (A–F) below in order, running each part's
> verification commands and confirming the expected result as you go. When every
> part is done and the full evidence block at the end of the step passes, stop
> and hand back to the operator. Do not commit, push, or open a PR.
>
> If anything in the "STOP conditions" section occurs, stop and report — do not
> improvise. When done, update the status row for this plan in `plans/README.md`
> — unless a reviewer dispatched you and told you they maintain the index.
>
> **Drift check (run first)**: `git diff --stat 225d3639..HEAD -- src/app/api_main.py src/app/settings.py src/app/db/models/ src/app/alembic/versions/ requirements.api.txt`
> Any mismatch against the "Current state" excerpts is a STOP condition **except**
> the one expected, pre-verified drift below.
>
> *Expected drift (not a STOP)*: since `225d3639`, `src/app/settings.py` gained
> `KEYCLOAK_CLIENT_SECRET: str = ""` and `KEYCLOAK_SERVICE_CLIENT_SECRET: str = ""`
> (+7 lines, plan 053). Nothing else in the drift-check path changed. Those are
> **client secrets minted in plan 056**, and this plan reads neither. Verify the
> drift is *only* that, then proceed.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: MED
- **Depends on**: plans/053 (Keycloak running with realm `wba`)
- **Category**: security
- **Planned at**: commit `225d3639`, 2026-10-30
- **Design reference**: `docs/design/authn-authz-design.md`, "The principal",
  "Session Management", "Testing Strategy"
- **This is step 2 of 9** in the Plan C sequence.

## Why this matters

This step builds the two objects every later step depends on: the **`Principal`**
(every credential resolves to one object, so authorization rules are written
once) and the **`auth_session`** table (the server-side record that makes the
BFF possible and lets the API mint a bearer token from a cookie).

**No route is protected after this step.** `get_principal` and its role
dependencies exist and are unit-tested, but nothing is wired into a router yet.
That is deliberate: the enforcement switch is plan 057, and it must come *after*
the UI can send a bearer (plan 056). This step is provable on its own with
real signed tokens and no Keycloak.

What improves when this lands: real JWT verification against a cached JWKS with
exact `iss`/`aud`/`exp` checks, role mapping that drops unknown roles and never
downgrades, and a migrated table ready to hold sessions.

## Current state

**`src/app/api_main.py`** — the API entrypoint. Router wiring is at lines
180-190:

```python
app.include_router(endpoints.router, prefix="/api")
app.include_router(chats_v1_router, prefix="/api/v1")
app.include_router(graph_v1_router, prefix="/api/v1")
...
app.include_router(activity_v1_router, prefix="/api/v1")
```

`app = FastAPI(lifespan=lifespan)` at line 152. There is **no** `Depends(...)`
anywhere except `get_async_db`, and no auth module.

**`src/app/db/models/__init__.py`** — every model is imported here so Alembic
autogenerate sees it. Current contents are ten model imports plus the eight
`connector_configs` classes. A new model **must** be added here or
`alembic revision --autogenerate` emits an empty migration.

**Alembic** — `src/app/alembic/env.py:24` sets `target_metadata =
Base.metadata`. The current head is revision `b3f7c1a9d204`
(`2026_10_26_1200-b3f7c1a9d204_drop_projects_table.py`). Migrations live in
`src/app/alembic/versions/` and are run with `cd src/app && alembic upgrade
head`.

**`src/app/common/encryption.py`** — Fernet helpers keyed by
`CONNECTOR_ENCRYPTION_KEY`:

```python
def encrypt(value: str) -> str:   # returns a Fernet token string
def decrypt(value: str) -> str:   # raises ValueError("Invalid encryption token")
```

**`requirements.api.txt`** — pinned dependency list for the API image. It does
**not** contain `pyjwt`. `cryptography==50.0.2` is present and is what the tests
will use to generate RSA keys.

**Baseline**: `pytest -m unit tests -q` → **2391 passed, 0 failed, 2 skipped**.

### Repo conventions that apply

- Type hints on every parameter and return; `mypy src/` is **strict**
  (`disallow_untyped_defs`, `disallow_untyped_calls`).
- `from common.logger import logger` — never `print()`.
- Built-in generics (`list[str]`, `dict[str, int]`), `X | None` — never
  `typing.List` / `Optional`.
- Every test carries a marker: `pytestmark = pytest.mark.unit` at module level.
  Unmarked tests are **silently skipped** by `pytest -m unit tests`.
- Tests import app code via `PYTHONPATH` from `pytest.ini` (`pythonpath = src . tests`).
- Package `__init__.py` re-exports must declare `__all__`.
- Do **not** commit, push, or open a PR unless explicitly asked.

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Unit tests | `pytest -m unit tests -q` | ≥ **2391** pass, 0 fail, exit 0 |
| Single file | `pytest -m unit tests/test_auth_principal.py -q` | all pass |
| Typecheck | `mypy src/` | exit 0 |
| Lint | `pylint src --score=y` | ≥ 9.0 |
| Security scan | `bandit -c .bandit.yml -r src/ -lll` | exit 0 |
| Migration | `cd src/app && alembic upgrade head` | exit 0 |
| Migration SQL preview | `cd src/app && alembic upgrade head --sql` | DDL printed, exit 0 |

Run with the virtualenv active (`source .venv/bin/activate`).

## Scope

**In scope**:
- `src/app/auth/__init__.py` (create)
- `src/app/auth/principal.py` (create) — the `Principal` dataclass.
- `src/app/auth/tokens.py` (create) — JWKS cache, JWT verification, role mapping.
- `src/app/auth/dependencies.py` (create) — `get_principal`, `require_user`,
  `require_admin`, `require_service`. **Defined, not yet wired.**
- `src/app/db/models/auth_session.py` (create)
- `src/app/db/models/__init__.py` — import the new model.
- `src/app/alembic/versions/<new>_add_auth_session.py` (create via autogenerate)
- `requirements.api.txt` — add `pyjwt[crypto]`.
- `tests/test_auth_principal.py` (create)
- `tests/test_auth_tokens.py` (create)
- `tests/test_auth_session_model.py` (create)
- `tests/test_auth_dependencies.py` (create)

**Out of scope** (do NOT touch):
- `src/app/api_main.py` — no router is wired to a dependency in this step.
- `src/app/api/**/router.py` — every route stays public.
- `src/app/api/auth/` — the login/callback/token endpoints are plan 056.
- `src/ui/` — the UI is untouched until plan 056.
- `src/common/` — service tokens are plan 055.
- Any `catalog_metadata` / `graph_theme` change — ownership is plan 057.

## Step 1: Build the `Principal`, token verification, dependencies, `auth_session`, and their tests

One step, done in the six ordered parts below. Each part builds on the previous,
but **do not hand back between parts** — work straight through to the single
manual gate at the end of this step.

### Part A — Add `pyjwt[crypto]` to the API runtime

In `requirements.api.txt`, add, keeping the file's grouping:

```
pyjwt[crypto]==2.15.1
```

Do **not** add it to `requirements.ui.txt` — the UI never validates a token.

**Why 2.15.1 and not an older pin.** This is a *security* dependency and the
version is not a free choice. PyJWT 2.13.0 and 2.14.0 carry GitHub Security
Advisories that touch exactly the code this plan relies on:

| Release | Advisory | Relevance here |
|---|---|---|
| 2.13.0 | `GHSA-jq35-7prp-9v3f` | binds the JWT header `alg` to `PyJWK.algorithm_name` during verification — an algorithm-allowlist bypass |
| 2.13.0 | `GHSA-993g-76c3-p5m4` | rejects non-`http(s)` URI schemes in `PyJWKClient` |
| 2.13.0 | `GHSA-fhv5-28vv-h8m8` | preserves the cached JWK Set on fetch errors |
| 2.14.0 | `GHSA-9v7f-9g4p-ffgj` | rejects automatic redirects when `PyJWKClient` fetches a JWKS |
| 2.14.0 | `GHSA-2gx3-rcp4-g85q` | limits repeated JWKS refreshes triggered by unknown key IDs |
| 2.14.0 | `GHSA-hxm8-2xgr-2p9m`, `GHSA-gvp8-978c-rx2q` | compact-JWS encoding rules; stops mutating the caller's `options` during decode |

Pinning below 2.13.0 would ship a verifier with known advisories against its own
JWKS path; pinning 2.13.0 would miss the 2.14.0 JWKS redirect and refresh-limit
fixes. **2.15.1 is also what the API image already resolves to transitively**
(`mcp[cli]==1.30.0` → `pyjwt[crypto]>=2.10.1`), so this pin makes an accidental
cap on a security dependency explicit. Neither `mcp` nor `PyGithub` caps the
upper bound.

**Verify**: `grep -n '^pyjwt' requirements.api.txt` → the line
**Verify**: `grep -c 'pyjwt' requirements.ui.txt` → `0`
**Verify**: `python -c "import jwt; print(jwt.__version__)"` → prints the pinned
version (the environment already has it; do **not** run a bare
`pip install -r requirements.api.txt` — it would churn the shared venv for no
gain, and `docker compose build api` is out of scope for this plan)

### Part B — Create the `Principal`

Create `src/app/auth/__init__.py`:

```python
"""Authentication and authorization for the API runtime."""

from app.auth.principal import Principal

__all__ = ["Principal"]
```

Create `src/app/auth/principal.py`:

```python
"""The single object every credential resolves to.

Every authorization rule is written against this type, so the bearer and the
session credential never need separate rules. ``credential`` exists only so the
two are distinguishable in logs and tests.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass


class CredentialType(str, enum.Enum):
    """How the caller proved identity."""

    BEARER = "bearer"
    SESSION = "session"


@dataclass(frozen=True)
class Principal:
    """An authenticated caller.

    Attributes:
        subject: Keycloak ``sub`` — stable, never reused.
        username: ``preferred_username``, for display and audit.
        roles: Mapped internal roles. Unknown realm roles are dropped; a token
            with no recognised role never reaches construction.
        credential: Which credential type produced this principal.
    """

    subject: str
    username: str
    roles: frozenset[str]
    credential: CredentialType = CredentialType.BEARER

    def has_role(self, role: str) -> bool:
        """Return whether this principal carries *role*."""
        return role in self.roles

    @property
    def is_admin(self) -> bool:
        """Return whether this principal carries ``wba-admin``."""
        return "wba-admin" in self.roles
```

**Verify**: `PYTHONPATH=src python -c "from app.auth import Principal; p=Principal('s','u',frozenset({'wba-admin'})); print(p.is_admin, p.has_role('wba-user'))"` → `True False`
**Verify**: `mypy src/app/auth/` → exit 0

### Part C — Implement JWKS-backed token verification and role mapping

Create `src/app/auth/tokens.py`. It must:

1. Fetch discovery from **`KEYCLOAK_INTERNAL_URL`** + `/.well-known/openid-configuration`,
   and **assert** `discovery["issuer"] == settings.KEYCLOAK_ISSUER`. On mismatch,
   log **one** ERROR line naming both strings and raise — a mismatch must never
   be silently tolerated.
2. Build a `jwt.PyJWKClient` from the realm's **internal** JWKS URL. Do **not**
   use the discovery document's `jwks_uri` directly: Keycloak builds it from
   `KC_HOSTNAME`, which `docker-compose.yml` sets to the **public** origin
   (`https://localhost/auth`), so discovery returns
   `https://localhost/auth/realms/wba/protocol/openid-connect/certs`. Inside the
   API container `localhost` is the API container itself, and the public URL is
   answered only by the `nginx` service — a `PyJWKClient` pointed at it fails
   every fetch (`ConnectionRefusedError`) and rejects every bearer token.
   Derive the internal URL instead: take the discovery document's `jwks_uri` and
   replace its origin with `KEYCLOAK_INTERNAL_URL`'s.

   ```python
   from urllib.parse import urlsplit, urlunsplit

   internal = urlsplit(settings.KEYCLOAK_INTERNAL_URL)   # http://keycloak:8080/auth/realms/wba
   public = urlsplit(discovery["jwks_uri"])              # https://localhost/auth/realms/wba/...
   jwks_uri = urlunsplit((internal.scheme, internal.netloc, public.path, "", ""))
   # → http://keycloak:8080/auth/realms/wba/protocol/openid-connect/certs
   ```

   This is the same public-vs-internal split the design records for the issuer
   (`docs/design/authn-authz-design.md`, "Issuer URL"), applied to the one other
   URL Keycloak hands back. PyJWKClient caches keys and refreshes on an unknown
   `kid`, so key rotation needs no restart. Use a bounded `cache_keys=True`
   client; construct it lazily on first use (so a Keycloak that is down at API
   startup does not block boot — the design requires Keycloak's availability to
   affect only new logins).
3. Verify with an **explicit algorithm allowlist** (`["RS256"]`), plus
   `issuer=settings.KEYCLOAK_ISSUER`, `audience=settings.KEYCLOAK_CLIENT_ID`,
   `options={"require": ["exp", "iss", "aud", "sub"]}`.
4. Map roles from **`realm_access.roles`**, intersecting with
   `{"wba-admin", "wba-user", "wba-service"}`. Unknown roles are dropped. If the
   intersection is empty, raise a dedicated `NoRecognisedRoleError` — never
   downgrade to `wba-user`.
5. Build and return a `Principal(subject=claims["sub"],
   username=claims.get("preferred_username", claims["sub"]), roles=frozenset(...),
   credential=CredentialType.BEARER)`.

Target shape (adapt names; keep the behaviour and the error types):

```python
class TokenValidationError(Exception):
    """A bearer token was missing, malformed, expired, or failed a claim check."""

class NoRecognisedRoleError(TokenValidationError):
    """The token carried no wba-* realm role — rejected, never downgraded."""

def validate_bearer_token(token: str) -> Principal:
    """Verify *token* against the realm's JWKS and map it to a Principal."""
```

Requirements that are easy to get wrong and that the tests check:

- **`aud` and `azp`.** PyJWT's `audience=` checks `aud`. Keycloak puts the
  client id in `azp`; when `aud` is an array containing other values, verify
  `azp == settings.KEYCLOAK_CLIENT_ID` explicitly as well. Accept a valid token
  whose `azp` matches and reject one whose only matching claim is `aud`.
- **Never log the token.** Log `sub`, `username`, and the resolved roles only.
  `bandit` and the design's audit rules both require this.
- **Clock skew**: pass `leeway=30` (seconds). Token lifetimes are 15 min, so 30s
  is safe and prevents spurious expiry failures between containers.

**Verify**: `PYTHONPATH=src python -c "import app.auth.tokens"` → no error
**Verify**: `mypy src/app/auth/` → exit 0
**Verify**: `bandit -c .bandit.yml -r src/app/auth/ -lll` → exit 0
**Verify** (live, against the running stack): from **inside the API container**,
the internal JWKS URL actually resolves. This is the check that catches the
`jwks_uri` host bug above:

```bash
docker compose exec -T api python -c "
import json, urllib.request
from app.settings import settings
from app.auth.tokens import _internal_jwks_uri  # or however you named it
d = json.load(urllib.request.urlopen(
    settings.KEYCLOAK_INTERNAL_URL + '/.well-known/openid-configuration', timeout=10))
uri = _internal_jwks_uri(d)
print(uri)
print(len(json.load(urllib.request.urlopen(uri, timeout=10))['keys']), 'keys')
"
```

→ prints an `http://keycloak:8080/...` URL and `2 keys`. A `https://localhost/...`
URL, or a `ConnectionRefusedError`, means step 2 was not applied. If running the
stack is not possible, substitute a unit test that asserts
`_internal_jwks_uri({"jwks_uri": "https://localhost/auth/realms/wba/protocol/openid-connect/certs"})`
returns the `http://keycloak:8080/...` form — but prefer the live check.

### Part D — Create the role dependencies (defined, not yet wired)

Create `src/app/auth/dependencies.py`:

```python
"""FastAPI dependencies that resolve and check a Principal.

Nothing wires these into a router yet — plan 057 does that. They are defined
and unit-tested here so enforcement is a one-line change per router rather than
a design decision taken during the switch.
"""

from __future__ import annotations

from fastapi import Depends, HTTPException, Request, status

from app.auth.principal import CredentialType, Principal
from app.auth.tokens import NoRecognisedRoleError, TokenValidationError, validate_bearer_token
from common.logger import logger


def _bearer_token(request: Request) -> str | None:
    """Return the bearer token from ``Authorization``, or ``None``."""
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token:
        return None
    return token


async def get_principal(request: Request) -> Principal:
    """Resolve the caller from ``Authorization: Bearer``.

    Raises:
        HTTPException: 401 when the header is missing or the token is invalid;
            403 when the token is valid but carries no recognised role.
    """
    ...


async def require_user(principal: Principal = Depends(get_principal)) -> Principal:
    """Require any authenticated principal (user, admin, or service)."""
    ...


async def require_admin(principal: Principal = Depends(get_principal)) -> Principal:
    """Require ``wba-admin``; 403 otherwise."""
    ...


async def require_service(principal: Principal = Depends(get_principal)) -> Principal:
    """Require ``wba-service``; 403 otherwise."""
    ...
```

Behavioural contract the tests enforce:

- Missing/malformed/invalid token → **401** with body
  `{"detail": {"error": "...", "message": "..."}}` and
  `WWW-Authenticate: Bearer`.
- Valid token, no recognised role → **403**, never 401.
- `require_admin` / `require_service` are **unhappy with the wrong role even if
  the caller is otherwise valid** → 403, and the log line names the required role
  and the path (the design's audit requirement).
- `require_user` accepts `wba-user`, `wba-admin`, and `wba-service`.

**Verify**: `PYTHONPATH=src python -c "from app.auth.dependencies import get_principal, require_user, require_admin, require_service; print('ok')"` → `ok`
**Verify**: `mypy src/app/auth/` → exit 0

### Part E — Add the `auth_session` model and migration

Create `src/app/db/models/auth_session.py`. Follow the style of
`src/app/db/models/catalog_metadata.py` exactly (`Mapped` / `mapped_column`,
`datetime` with `timezone=True`, `server_default=func.now()` with
`# pylint: disable=not-callable`).

Columns (all non-null unless stated):

| Column | Type | Notes |
|---|---|---|
| `id` | int PK | |
| `session_id_hash` | String(64), unique, indexed | SHA-256 hex of the opaque cookie id. **The raw id is never stored.** |
| `subject` | String(255), indexed | Keycloak `sub` |
| `username` | String(255) | display/audit |
| `roles` | JSONB | roles snapshot at login |
| `refresh_token_encrypted` | Text | Fernet ciphertext |
| `created_at` | DateTime(tz) | server default now() |
| `expires_at` | DateTime(tz) | absolute cap |
| `last_seen_at` | DateTime(tz) | idle clock |
| `revoked_at` | DateTime(tz), nullable | set on logout |

Add `from app.db.models.auth_session import AuthSession` to
`src/app/db/models/__init__.py`, **alphabetically among the others**.

Generate the migration:
```bash
cd src/app && alembic revision --autogenerate -m "add auth_session"
```
Read the generated file. It must contain a `create_table('auth_session', ...)`
with the unique constraint on `session_id_hash` and an index on `subject`.
**If it is empty, the model was not imported in `__init__.py`** — fix that and
regenerate rather than hand-writing the table.

Then:
```bash
cd src/app && alembic upgrade head
```

**Verify**: `cd src/app && alembic heads` → exactly one head, the new revision
**Verify**: `cd src/app && alembic upgrade head --sql | grep -c 'CREATE TABLE auth_session'` → `1`
**Verify**: `grep -c "AuthSession" src/app/db/models/__init__.py` → `1`

### Part F — Write the tests with real signed tokens

Four new unit-test files. **No Keycloak, no mocks of signature validation** —
generate an RSA keypair with `cryptography`, sign real JWTs, and point the JWKS
client at the test key. This is what makes the absence of an `AUTH_ENABLED`
switch tolerable.

**`tests/test_auth_principal.py`** — `pytestmark = pytest.mark.unit`
- `is_admin` / `has_role` for admin, user, service, empty.
- The dataclass is frozen (assigning raises `FrozenInstanceError`).

**`tests/test_auth_tokens.py`** — `pytestmark = pytest.mark.unit`
Build a fixture that (a) generates an RSA keypair, (b) exposes it as a fake
`PyJWKClient`/JWKS, and (c) signs tokens. Cover:
- valid token → returns a `Principal` with the mapped roles.
- expired token → `TokenValidationError`.
- wrong `iss` → rejected.
- `aud`/`azp` for a different client → rejected.
- unknown realm roles only (e.g. `offline_access`) → `NoRecognisedRoleError`.
- token with `wba-user` **and** `wba-admin` → both roles present; `is_admin`
  true.
- discovery `issuer` != `KEYCLOAK_ISSUER` → raises, and the assertion is the
  thing that fails (not a downstream signature error).
- a token signed by a **different** key → rejected.

Use `monkeypatch`/dependency injection for the JWKS client; do not perform
network I/O in a unit test.

**`tests/test_auth_session_model.py`** — `pytestmark = pytest.mark.unit`
- construct an `AuthSession` and assert defaults/types.
- assert `session_id_hash` is not derived from a plaintext id by the model
  (the hashing helper lives elsewhere and is tested in plan 056).

**`tests/test_auth_dependencies.py`** — `pytestmark = pytest.mark.unit`
- missing header → 401
- invalid token → 401
- valid token, no role → 403
- `require_admin` with a `wba-user` principal → 403
- `require_service` with a `wba-user` principal → 403
- `require_user` with each of the three roles → allowed

Drive these through a tiny `FastAPI()` app built **in the test file** with one
route per dependency, using `httpx.ASGITransport`. Do **not** touch
`app.api_main` to make these pass.

**Verify**: `pytest -m unit tests/test_auth_principal.py tests/test_auth_tokens.py tests/test_auth_session_model.py tests/test_auth_dependencies.py -q` → all pass

### Step 1 evidence — run every line and paste the output into your report

```bash
grep -n '^pyjwt' requirements.api.txt
grep -c 'pyjwt' requirements.ui.txt
PYTHONPATH=src python -c "from app.auth.dependencies import get_principal, require_user, require_admin, require_service; print('ok')"
cd src/app && alembic heads && cd -
cd src/app && alembic upgrade head --sql | grep -c 'CREATE TABLE auth_session' && cd -
grep -c "AuthSession" src/app/db/models/__init__.py
pytest -m unit tests/test_auth_principal.py tests/test_auth_tokens.py tests/test_auth_session_model.py tests/test_auth_dependencies.py -q
pytest -m unit tests -q
mypy src/
pylint src --score=y
bandit -c .bandit.yml -r src/ -lll
grep -rn "Depends(require_" src/app/ || echo "no matches (expected)"
grep -rn "logger.*token" src/app/auth/ || echo "no token logging (expected)"
```

Expected: `pyjwt` line present; `0`; `ok`; one head; `1`; `1`; the four auth
files all pass; ≥ **2391 + N** passed/0 failed; mypy exit 0; pylint ≥ 9.0;
bandit exit 0; no `Depends(require_` matches; no token in a log statement.

> ### 🚦 MANUAL GATE — the whole step
>
> Operator reviews the evidence block above plus the full `git diff`, and
> confirms all of the following. Reply `PASS` to accept the step, or `FAIL`
> (a STOP condition) with the specific item that failed.
>
> **Dependency**
> - `pyjwt[crypto]` is in `requirements.api.txt` only, and `cryptography` is
>   still pinned (it is `pyjwt[crypto]`'s backend).
>
> **Principal**
> - The dataclass is frozen, has all four attributes, and `is_admin` is
>   derived rather than stored.
>
> **Token verification**
> - The issuer assertion is present; algorithms are an explicit allowlist (not
>   derived from the token header); unknown roles are dropped; an empty role
>   set raises rather than downgrading to `wba-user`.
> - No token value reaches a log statement.
>
> **Dependencies**
> - 401 vs 403 are not conflated; a no-role token is 403; every denial logs the
>   required role and path.
>
> **Migration**
> - `docker compose exec -T postgres sh -c 'psql -U "$POSTGRES_USER" -d
>   "$POSTGRES_DB" -c "\d auth_session"'` shows every column in the table above,
>   the unique index on `session_id_hash`, and no existing table changed. (The
>   `sh -c` wrapper matters: `POSTGRES_USER` exists inside the `postgres`
>   container, not in your shell — an unwrapped `-U "$POSTGRES_USER"` expands to
>   empty and fails with `role does not exist`.)
>
> **Tests and blast radius**
> - The auth tests use real signed tokens (no `jwt.decode` monkeypatching).
> - `pytest -m unit tests -q` did not drop any existing test (≥ 2391 + N).
> - No route in `app.api_main` changed — every route is still public.

---

## Test plan

Covered in Part F above. The critical properties, in order of value:

1. **Real signature verification** with a test keypair — the tests fail if
   verification is stubbed.
2. **Exact `iss`** — a token with a different issuer is rejected.
3. **`aud`/`azp`** — a token minted for another client is rejected.
4. **No downgrade** — a roleless token is 403, not a `wba-user` principal.
5. **401 vs 403** — authentication failures and authorization failures stay
   distinct.

## Done criteria

- [ ] `pytest -m unit tests -q` exits 0, ≥ 2391 + N passed
- [ ] `mypy src/` exits 0
- [ ] `pylint src --score=y` ≥ 9.0
- [ ] `bandit -c .bandit.yml -r src/ -lll` exits 0
- [ ] `alembic heads` shows exactly one head
- [ ] `grep -rn "Depends(require_" src/app/` → no matches (nothing wired yet)
- [ ] `curl -sf https://localhost/api/health` still returns healthy with no `Authorization` header (the API is still open)
- [ ] The JWKS client is pointed at the **internal** URL. Read every
      `logger.` call in `src/app/auth/` and confirm none interpolates the token,
      an `Authorization` header, or a raw claim dict; allowed fields are `sub`,
      `username`, the resolved roles, and the path. (`grep -c "logger.*token"`
      will legitimately be ≥ 1 — a single `logger.error(...)` without a token
      argument is correct — so read the lines rather than trusting the count.)
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report (do not improvise) if:

- The Keycloak discovery document's `issuer` does not equal
  `settings.KEYCLOAK_ISSUER` (plan 053's Gate 6 would also have caught this).
- `alembic autogenerate` produces an empty migration even after the model is
  imported in `__init__.py`.
- PyJWT's `audience` handling cannot express the `azp` check you need without
  a custom decode — report rather than weakening the check.
- The `wba-internal` (service-account) token's `aud` claim does not carry
  `wba-web`. The realm template
  (`deploy/keycloak/realm-wba.json.template`) declares no audience mapper on
  either client, so this is **expected** — do **not** "fix" it by adding a
  mapper or by loosening `audience=` to unverified. Record the observed `aud`
  and `azp` values in your report and continue: plan 055 decides how the service
  token is accepted. This plan's own tests mint tokens with `aud="wba-web"`, so
  they pass regardless.
- Any existing unit test starts failing. Nothing in this step changes a route,
  so a failure means a shared import (e.g. `db/models/__init__.py`) broke.
- An in-scope file has drifted from "Current state".

## Maintenance notes

- **`get_principal` never reads a cookie.** Plan 058 adds a *separate*
  session-credential resolver used by exactly two auth endpoints; the allowlist
  test in plan 057 keeps it bounded. Do not make `get_principal` fall back to
  the cookie.
- **Adding a role** means touching `_MAPPED_ROLES` in `tokens.py`, the realm
  template, and the `AUTHZ_MATRIX` in plan 057. Three places — a test in 057
  asserts the matrix covers every route, but it cannot know about a new role's
  semantics; update the design doc too.
- **JWKS caching** is the reason a Keycloak restart does not evict sessions.
  A reviewer should confirm the client is created lazily and that an unknown
  `kid` triggers a refresh rather than a permanent failure.
- **`refresh_token_encrypted`** is written by plan 056 using
  `app.common.encryption`. If that key rotates, all sessions become
  unrefreshable — a deliberate, documented coupling.

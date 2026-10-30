# Plan 053: Run Keycloak in the Compose stack with realm `wba` checked in as code

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Every step ends with a MANUAL GATE.** After completing the step's automated
> verification, stop and hand back to the operator for a human check. Do not
> begin the next step until the operator replies `PASS`. If they reply `FAIL`,
> treat it as a STOP condition.
>
> **Drift check (run first)**: `git diff --stat 225d3639..HEAD -- docker-compose.yml deploy/nginx/nginx.conf src/domain/settings.py src/app/settings.py .env.example`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding. Any
> mismatch is a STOP condition.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: MED
- **Depends on**: plans/052 (complete), plans/051 (complete)
- **Category**: security
- **Planned at**: commit `225d3639`, 2026-10-30
- **Design reference**: `docs/design/authn-authz-design.md`, "Keycloak" section
- **This is step 1 of 9** in the Plan C sequence (053 → 061). No later step may
  start until this one's gate has passed.

## Why this matters

Plan C makes the API an authenticated product. That requires an identity
provider, and the design runs **Keycloak inside this repository's own Compose
stack** with the realm checked in as code, so `docker compose up` yields a
working login with no manual console setup.

This step creates the identity provider and nothing else. **The application's
behaviour does not change**: it still has no authentication, and every page and
endpoint still works unauthenticated. That is deliberate — later steps build on
a provider that is already running and proven, rather than diagnosing a broken
login at the same time as broken authorization.

What improves when this lands: a reachable Keycloak with the `wba` realm, the
three roles, the two clients, the configured token lifetimes, a seeded
`dev-admin` and `dev-user`, and a `keycloak` database on the existing Postgres
server — all reproducible from a clean checkout.

## Current state

Read these before editing. Each line is a fact as of the plan's commit.

**`docker-compose.yml`** — the stack. Service `postgres` (lines 2-21) has no
init scripts and one named volume:

```yaml
  postgres:
    image: postgres:17
    volumes:
      - pgdata:/var/lib/postgresql/data
    ports:
      - "5432:5432"
```

There is **no `keycloak` service**. There is no `deploy/postgres/` directory —
`deploy/` currently contains only `certs/` and `nginx/`.

**`deploy/nginx/nginx.conf`** — TLS terminator in front of the stack. It ends
with a block that was **reserved for this plan** (verbatim, including the
comment):

```nginx
        # ── RESERVED: /auth for Keycloak (Plan C) ───────────────────────
        # Path reserved; do not serve app routes under /auth.
        # Plan C enables this block and adds the keycloak service. Keycloak
        # will require KC_HTTP_RELATIVE_PATH=/auth and
        # KC_PROXY_HEADERS=xforwarded so it generates correct URLs behind
        # this proxy.
        #
        # location /auth {
        #     proxy_pass http://keycloak:8080;
        #     proxy_set_header Host              $host;
        #     proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
        #     proxy_set_header X-Forwarded-Proto $scheme;
        #     proxy_set_header X-Forwarded-Host  $host;
        # }
```

`deploy/nginx/nginx.conf` depends on the container network being
`wba-ai-network`; every service joins it.

**`src/domain/settings.py`** — `UISettings`, the credential-free settings base
that **both** runtimes use. Its first field group already carries the
proxy-aware URLs and a comment naming the OAuth `redirect_uri` as a Plan C
consumer:

```python
    EXTERNAL_BASE_URL: str = "https://localhost"
    API_BASE_URL: str = "http://localhost:8000"
```

`src/app/settings.py` defines `ApiSettings(UISettings)`, which adds every
credential. `DATABASE_URL` deliberately has no default.

**`.env.example`** — 195 lines of documented variables. `EXTERNAL_BASE_URL`
is at line 88, `API_BASE_URL` at line 94, `CONNECTOR_ENCRYPTION_KEY` at line
29. **There is no `KEYCLOAK_*` or `AUTH_*` variable of any kind.**

### Repo conventions that apply

- Compose services pin a **minor-version tag with a comment**, never `latest`.
  `nginx` is pinned as `1.30-alpine` with a comment explaining the drift. Match
  that.
- Every service declares `networks: - wba-ai-network`, `restart:
  unless-stopped`, and a `healthcheck` with `interval`/`timeout`/`retries`.
  Copy the shape from the `postgres` and `api` services.
- **No secret value may be committed.** `.env` is gitignored; `.env.example`
  carries `FIXME` placeholders.
- Do **not** commit, push, or open a PR unless the operator explicitly asks.

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Compose syntax | `docker compose config -q` | exit 0 |
| Start services | `docker compose up -d postgres keycloak nginx` | all healthy / running |
| Nginx syntax | `docker run --rm --network work-behavior-analytics-ai_wba-ai-network -v "$PWD/deploy/nginx/nginx.conf:/etc/nginx/nginx.conf:ro" -v "$PWD/deploy/certs:/etc/nginx/certs:ro" nginx:1.30-alpine nginx -t` | `syntax is ok`, `test is successful` |
| Realm discovery (through nginx) | `curl -sf https://localhost/auth/realms/wba/.well-known/openid-configuration` | JSON containing `"issuer":"https://localhost/auth/realms/wba"` |
| Admin console (loopback) | `curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8080/auth/admin/` | `200` or `303` (see Step 5) |
| Keycloak DB exists | `docker compose exec -T postgres psql -U "$POSTGRES_USER" -lqt \| cut -d'\|' -f1 \| grep -cw keycloak` | `1` |

**Network name**: the project directory is `work-behavior-analytics-ai`, so the
network is `work-behavior-analytics-ai_wba-ai-network`. If
`docker network ls` shows a different name, substitute it in the nginx
syntax command above.

**`curl`**: use the **no-`-k`** form — the mkcert CA is in the Linux trust
store on any machine that ran `mkcert -install`.

## Scope

**In scope** (the only files you should create or modify):

- `docker-compose.yml` — add the `keycloak` service and the keycloak-DB bootstrap.
- `deploy/keycloak/realm-wba.json.template` (create) — the realm as code.
- `deploy/keycloak/entrypoint.sh` (create) — renders the template, then starts Keycloak.
- `deploy/keycloak/keycloak.env.example` (create) — documents `DEV_ADMIN_PASSWORD` / `DEV_USER_PASSWORD`.
- `deploy/postgres/init-keycloak.sql` (create) — creates the `keycloak` role + DB on a **fresh** volume.
- `deploy/nginx/nginx.conf` — replace the reserved block with the real one.
- `src/domain/settings.py` — add the non-secret `KEYCLOAK_*` and `AUTH_*` settings
  fields (including both client **IDs**).
- `src/app/settings.py` — add the two client **secrets** to `ApiSettings`.
- `.env.example` — document the new variables.
- `docs/design/authn-authz-design.md` — **only** the "Issuer URL" open item
  (Step 7) and the "Production checklist" subsection (Step 8).

**Out of scope** (do NOT touch, even though they look related):

- Any Python that validates a token, creates a session, or enforces a role. That
  is plan **054** onwards. This plan adds settings fields only; nothing reads them yet.
- `src/app/api_main.py`, `src/ui/`, and every router. The application is
  unauthenticated before and after this plan, by design.
- The `/api`, `/app`, `/docs` nginx location blocks. Only the reserved `/auth`
  block changes.
- `Dockerfile.api` / `Dockerfile.ui`. No Python dependency is added in this plan.

## Steps

### Step 1: Add the `KEYCLOAK_*` and `AUTH_*` settings fields

In `src/domain/settings.py`, add this block **after** the existing
`EXTERNAL_BASE_URL` / `API_BASE_URL` group and before the logging group. These
go on `UISettings` because **both** runtimes read them: the UI builds the login
URL and cookie flags, and the API validates tokens.

```python
    # ── Authentication (Keycloak / OIDC) ────────────────────────────────
    # The PUBLIC realm URL. This exact string must equal the `iss` claim of
    # every token: validation is an exact string match, so any scheme, host,
    # port, trailing-slash or case difference rejects every token. It is the
    # URL the BROWSER uses, not the URL the API container fetches from —
    # see KEYCLOAK_INTERNAL_URL.
    KEYCLOAK_ISSUER: str = "https://localhost/auth/realms/wba"

    # The realm URL the API container itself uses for discovery, the token
    # endpoint and JWKS. Inside a container `localhost` is the container
    # itself, so this must be the compose service name. Plain HTTP inside the
    # Docker network. Deliberately NOT the same value as KEYCLOAK_ISSUER.
    KEYCLOAK_INTERNAL_URL: str = "http://keycloak:8080/auth/realms/wba"

    KEYCLOAK_REALM: str = "wba"

    # `wba-web` — the confidential browser client used by the BFF.
    # The ID is not a secret and is safe on the UI runtime; the SECRET is not
    # here — it lives on `ApiSettings` in `src/app/settings.py`. See the note
    # below the block.
    KEYCLOAK_CLIENT_ID: str = "wba-web"

    # `wba-internal` — the service-account client used by producers and the
    # signal consumer (client-credentials grant). Plan 055 consumes these.
    # Same split as above: the ID is here, the SECRET is on `ApiSettings`.
    KEYCLOAK_SERVICE_CLIENT_ID: str = "wba-internal"

    # `Secure` flag on the session cookie. MUST be true wherever TLS
    # terminates (it does: nginx). Set false ONLY for a plain-HTTP local run.
    AUTH_COOKIE_SECURE: bool = True

    # Application-enforced session bounds. The auth_session row is the
    # authority; Keycloak's SSO timers are the outer bound. Runtime-tunable.
    AUTH_SESSION_IDLE_MINUTES: int = 60
    AUTH_SESSION_MAX_HOURS: int = 8
```

Use `Field(default=..., ge=...)` if a bound is natural; the repo already imports
`Field` in this module for `RECENT_ACTIONS_LIMIT`.

**The two client secrets go on `ApiSettings`, not here.** Add them to
`src/app/settings.py` in the `ApiSettings` body, next to `CONNECTOR_ENCRYPTION_KEY`:

```python
    # Keycloak client secrets. Confidential-client credentials: only the API
    # runtime exchanges them for tokens (plans 054/056). They must never sit on
    # ``UISettings``, which ``src/ui/settings.py`` instantiates bare — a secret
    # there would be resident in the UI process's memory for no purpose.
    KEYCLOAK_CLIENT_SECRET: str = ""
    KEYCLOAK_SERVICE_CLIENT_SECRET: str = ""
```

This is the operator's decision, and it follows `src/ui/settings.py`'s own
docstring ("Anything the UI needs that is not on `UISettings` must come from the
API over HTTP, not from here"). It is safe because **no UI-side code reads either
secret**: the browser client's token exchange is an API endpoint (plan 056's
`complete_login` / refresh, both in `src/app/api/auth/v1/service.py`), plan 055
reads the service secret from `os.environ` rather than from settings, and plan
056's UI guard explicitly does not validate the session. The client **IDs** stay
on `UISettings` — they are not secrets, and plan 054 needs `KEYCLOAK_CLIENT_ID`
for the audience check.

Consequence to be aware of: `KEYCLOAK_CLIENT_SECRET` and
`KEYCLOAK_SERVICE_CLIENT_SECRET` are then reachable only as
`app.settings.settings.<NAME>`, never `ui.settings.settings.<NAME>`.

Add one more field, so the issuer is never silently inconsistent with the app's
own public URL:

```python
    # The public origin this deployment is served from (scheme + host, no
    # trailing slash). Used to build the OAuth redirect_uri and the realm
    # template's redirectUris/webOrigins.
    #
    # It MUST equal the origin of KEYCLOAK_ISSUER. They are two settings rather
    # than one because KEYCLOAK_ISSUER carries the /auth/realms/<realm> suffix
    # and must match the `iss` claim byte-for-byte, while this is the app origin.
    # A validator below enforces that they agree.
    APP_PUBLIC_BASE_URL: str = "https://localhost"
```

And a validator that fails fast on a mismatch (this is the mechanism that makes
a production deploy safe rather than a convention):

```python
    @model_validator(mode="after")
    def _issuer_must_match_public_url(self) -> "UISettings":
        issuer = self.KEYCLOAK_ISSUER
        base = self.APP_PUBLIC_BASE_URL.rstrip("/")
        if not issuer.startswith(f"{base}/"):
            raise ValueError(
                f"KEYCLOAK_ISSUER ({issuer}) must start with "
                f"APP_PUBLIC_BASE_URL ({base}) + '/'. A mismatch means the "
                "realm's issuer and the app's public origin disagree, which "
                "makes every redirect and token validation fail."
            )
        return self
```

Import `model_validator` from `pydantic`. This is a **startup** check — it fails
the process rather than failing a login later, and it fails identically in dev
and production.

Note: `EXTERNAL_BASE_URL` and `APP_PUBLIC_BASE_URL` now express almost the same
thing. Keep both: `EXTERNAL_BASE_URL` is Plan A's established setting consumed by
nginx/proxy-awareness, and `APP_PUBLIC_BASE_URL` is the auth-specific origin with
the issuer invariant attached. In practice a deployment sets
`APP_PUBLIC_BASE_URL` to the same value; the validator catches it when it drifts.

**Verify**: `python -c "import sys; sys.path.insert(0,'src'); from domain.settings import UISettings; s=UISettings(); print(s.KEYCLOAK_ISSUER, s.KEYCLOAK_INTERNAL_URL, s.AUTH_COOKIE_SECURE, s.APP_PUBLIC_BASE_URL)"` → prints `https://localhost/auth/realms/wba http://keycloak:8080/auth/realms/wba True https://localhost`
**Verify** (mismatch is rejected): `python -c "import sys; sys.path.insert(0,'src'); from domain.settings import UISettings; UISettings(APP_PUBLIC_BASE_URL='https://prod.example.com')"` → raises `ValidationError` mentioning `KEYCLOAK_ISSUER`
**Verify** (a matched production pair is accepted): `python -c "import sys; sys.path.insert(0,'src'); from domain.settings import UISettings; s=UISettings(APP_PUBLIC_BASE_URL='https://wba.example.com', KEYCLOAK_ISSUER='https://wba.example.com/auth/realms/wba', AUTH_COOKIE_SECURE=True); print('ok')"` → `ok`
**Verify** (the secrets are NOT on the UI runtime):
```bash
PYTHONPATH=src python -c "
from domain.settings import UISettings
from app.settings import ApiSettings
for name in ('KEYCLOAK_CLIENT_SECRET', 'KEYCLOAK_SERVICE_CLIENT_SECRET'):
    assert name not in UISettings.model_fields, name
    assert name in ApiSettings.model_fields, name
for name in ('KEYCLOAK_CLIENT_ID', 'KEYCLOAK_SERVICE_CLIENT_ID', 'KEYCLOAK_ISSUER',
             'KEYCLOAK_INTERNAL_URL', 'APP_PUBLIC_BASE_URL', 'AUTH_COOKIE_SECURE'):
    assert name in UISettings.model_fields, name
print('ok')"
```
→ prints `ok`. This is the check that makes the secret split enforced rather than
a convention: it fails if either secret is ever re-added to `UISettings`.

**Verify** (the UI runtime constructs cleanly without a database):
`PYTHONPATH=src python -c "from ui.settings import settings; print('ui ok')"` → `ui ok`
**Verify**: `mypy src/domain/settings.py src/app/settings.py` → exit 0
**Verify**: `pytest -m unit tests -q` → same pass count as before this step

> ### 🚦 MANUAL GATE 1 — settings
>
> Operator verifies: the three values print as above, the non-secret fields are on
> `UISettings` (so the API inherits them without duplication), and **the two client
> secrets are on `ApiSettings` only** — never on `UISettings`.
> Wait for `PASS`.

#### Gate 1 record — 2026-10-30 — AWAITING OPERATOR PASS

Executed in the live working tree on `feature/plan-c-keycloak`, uncommitted.

Diff: `src/domain/settings.py` **+59 / −1** (the one deletion is the `from pydantic
import ...` line gaining `model_validator`) and `src/app/settings.py` **+7 / −0**.
Purely additive; no existing field, value or behaviour changed.

| Check | Command | Observed |
|---|---|---|
| V1 defaults | `python -c "... UISettings() ..."` | `https://localhost/auth/realms/wba http://keycloak:8080/auth/realms/wba True https://localhost` — exact match |
| V2 mismatch rejected | `UISettings(APP_PUBLIC_BASE_URL='https://prod.example.com')` | `ValidationError`; message contains `KEYCLOAK_ISSUER` |
| V3 matched prod pair | `UISettings(APP_PUBLIC_BASE_URL='https://wba.example.com', KEYCLOAK_ISSUER='https://wba.example.com/auth/realms/wba')` | `ok` |
| V4 typecheck | `mypy src/domain/settings.py src/app/settings.py` | `Success: no issues found in 2 source files` (exit 0) |
| V5 regression | `pytest -m unit tests -q` | **2391 passed, 2 skipped, 750 deselected** (exit 0) — unchanged from the planning-time count |
| **V6 secret split** | assert both secrets absent from `UISettings.model_fields` and present on `ApiSettings.model_fields`; six ID/URL fields present on `UISettings` | `ok` |
| V7 UI runtime | `from ui.settings import settings` | `ui ok` — constructs with no database, no secret |
| V8 API runtime | `ApiSettings().KEYCLOAK_CLIENT_SECRET == ''` | `True` |
| Validator edges (reviewer probes) | matched-but-different origin (`https://localhost.evil.com` pair) | accepted — a legitimately different deployment origin, not a spoof |
| | `APP_PUBLIC_BASE_URL='https://local'` (prefix spoof) | rejected |
| | scheme downgrade (`http://localhost` + `https://…` issuer) | rejected |
| | trailing slash on the base (`https://localhost/`) | accepted — `rstrip("/")` handles it |
| Independent consumer sweep | `grep -rn 'KEYCLOAK_CLIENT_SECRET\|KEYCLOAK_SERVICE_CLIENT_SECRET' src/ tests/ scripts/` | only the two field **declarations** in `src/app/settings.py:69-70`; no code reads them from `ui.settings` |

**Secret split (operator decision, 2026-10-30).** `KEYCLOAK_CLIENT_SECRET` and
`KEYCLOAK_SERVICE_CLIENT_SECRET` are on `ApiSettings` only. The client **IDs**
stay on `UISettings` (not secrets; plan 054 needs `KEYCLOAK_CLIENT_ID` for the
audience check). Verified safe because no UI-side code exchanges either secret:
plan 056's `client_secret` reads are both in API service functions, its UI guard
explicitly does not validate the session, and plan 055 reads the service secret
from `os.environ`.

**Scope**: `git status --porcelain` shows ` M src/domain/settings.py` and
` M src/app/settings.py` from this step. (The ` M docs/design/...` and
` M plans/...` entries are the reviewer's own plan/doc edits, not the executor's.)
Nothing committed. No file outside Step 1's in-scope list was touched.

---

### Step 2: Create the Keycloak database bootstrap

The design reuses the existing Postgres server with a **separate database**.
Postgres runs `/docker-entrypoint-initdb.d/*` **only when the data directory is
empty**, so this file serves fresh installs and Step 3 handles existing ones.

Create `deploy/postgres/init-keycloak.sql`:

```sql
-- Creates the separate database Keycloak uses. Runs ONLY on a fresh pgdata
-- volume (Postgres executes /docker-entrypoint-initdb.d once). On an existing
-- volume this file is skipped, and the operator runs the idempotent snippet in
-- DEVELOPER_QUICK_START.md instead. Schemas never mix: the application stays in
-- POSTGRES_DB, Keycloak lives in `keycloak`.
CREATE ROLE keycloak WITH LOGIN PASSWORD 'keycloak';
CREATE DATABASE keycloak OWNER keycloak;
```

**The password here is a dev-only default**, matching the `guest`/`guest`
RabbitMQ default this repo already tolerates. If you are uncomfortable with a
literal, the operator decision recorded for this plan is: keep it, because the
Keycloak container publishes no reachable port except a loopback one, and the
database is not host-exposed beyond the existing `5432` mapping (Plan E owns
that). **Do not** put a real credential here.

Mount it in `docker-compose.yml` on the `postgres` service's `volumes` list,
**before** the `pgdata` line:

```yaml
    volumes:
      - ./deploy/postgres/init-keycloak.sql:/docker-entrypoint-initdb.d/10-keycloak.sql:ro
      - pgdata:/var/lib/postgresql/data
```

**Verify**: `docker compose config -q` → exit 0
**Verify**: `test -f deploy/postgres/init-keycloak.sql && echo present` → `present`

> ### 🚦 MANUAL GATE 2 — bootstrap file
>
> Operator verifies the mount line is present and read-only (`:ro`), and that no
> existing volume path was changed or removed.
> Wait for `PASS`.

---

### Step 3: Create `keycloak` role and database on an EXISTING volume

Fresh installs get the database from Step 2. **An existing `pgdata` volume will
not**, and Keycloak fails to boot with a connection error. Make this an explicit
step rather than a documented footnote, so it is not discovered as a mystery.

Add a short section to `DEVELOPER_QUICK_START.md` (find the database/setup
section; keep its heading style) containing this idempotent snippet:

```bash
# Existing databases only (a fresh `docker compose down -v` gets this
# automatically from deploy/postgres/init-keycloak.sql).
docker compose exec -T postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" <<'SQL'
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'keycloak') THEN
    CREATE ROLE keycloak WITH LOGIN PASSWORD 'keycloak';
  END IF;
END $$;
SQL
docker compose exec -T postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
  -tc "SELECT 1 FROM pg_database WHERE datname = 'keycloak'" | grep -q 1 || \
  docker compose exec -T postgres createdb -U "$POSTGRES_USER" -O keycloak keycloak
docker compose exec -T postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c '\q'
```

Then run it once yourself against the operator's running stack.

**Verify**: `docker compose exec -T postgres psql -U "$POSTGRES_USER" -lqt | cut -d'|' -f1 | grep -cw keycloak` → `1`
**Verify**: re-running the same snippet does not error → exit 0 (idempotent)

> ### 🚦 MANUAL GATE 3 — database exists
>
> Operator verifies `\l` in psql lists a `keycloak` database owned by `keycloak`,
> and that the application database and its tables are untouched.
> Wait for `PASS`.

---

### Step 4: Write the realm as code (template + renderer)

The realm is checked in as a **template**, rendered to the import directory at
container start. This avoids depending on Keycloak's version-specific
`${...}` substitution behaviour, which is not verifiable from this repo.

Create `deploy/keycloak/realm-wba.json.template`. It must contain these
elements exactly (shape, not every line — keep it valid JSON):

- `"realm": "wba"`, `"enabled": true`
- `"sslRequired": "external"` — TLS terminates at nginx; do not force HTTPS
  inside the network.
- Realm roles: `wba-admin`, `wba-user`, `wba-service` (plain
  `"roles": { "realm": [ {"name": "..."} ] }`).
- Access token lifespan **900** seconds; SSO session idle **3600**; SSO
  session max **28800**.
- `"clients"`:
  - `wba-web` — `"publicClient": false`, `"standardFlowEnabled": true`,
    `"directAccessGrantsEnabled": false`, `"serviceAccountsEnabled": false`,
    `"attributes": { "pkce.code.challenge.method": "S256" }`, `"secret":
    "${KEYCLOAK_CLIENT_SECRET}"`, and
    `"redirectUris": ["${APP_PUBLIC_BASE_URL}/api/v1/auth/callback"]` plus
    `"webOrigins": ["${APP_PUBLIC_BASE_URL}"]`.

    **`APP_PUBLIC_BASE_URL` is a template variable, never a literal.** It is
    rendered from `EXTERNAL_BASE_URL`, so one realm template serves
    `https://localhost` in development and `https://wba.example.com` in
    production with no edit. A literal `https://localhost` here is a production
    defect: Keycloak rejects the callback with a `redirect_uri` mismatch and
    **login fails entirely**. Do not "simplify" it to a literal.
  - `wba-internal` — `"publicClient": false`, `"standardFlowEnabled": false`,
    `"directAccessGrantsEnabled": false`, `"serviceAccountsEnabled": true`,
    `"secret": "${KEYCLOAK_SERVICE_CLIENT_SECRET}"`.
- Two users, each with `"emailVerified": true`, `"enabled": true`, and a
  `"credentials": [ { "type": "password", "value": "${DEV_ADMIN_PASSWORD}" } ]`:
  - `dev-admin` — `"realmRoles": ["wba-admin", "wba-user"]`
  - `dev-user`  — `"realmRoles": ["wba-user"]`
- The `wba-internal` service account must carry `wba-service`. Do that with a
  `"serviceAccountClientRoles"`-style assignment if the template shape supports
  it; if it is easier and verifiable, add the role mapping in the
  `users`/`serviceAccount` object. **The gate checks that the service account
  actually has `wba-service`**, so verify it, do not assume the JSON shape worked.

Create `deploy/keycloak/entrypoint.sh`:

```bash
#!/bin/bash
set -e
# Render the realm template with the dev passwords from the environment.
# envsubst is used rather than Keycloak's own substitution because the latter's
# syntax varies by version.
: "${DEV_ADMIN_PASSWORD:?DEV_ADMIN_PASSWORD must be set}"
: "${DEV_USER_PASSWORD:?DEV_USER_PASSWORD must be set}"
: "${KEYCLOAK_CLIENT_SECRET:?KEYCLOAK_CLIENT_SECRET must be set}"
: "${KEYCLOAK_SERVICE_CLIENT_SECRET:?KEYCLOAK_SERVICE_CLIENT_SECRET must be set}"
# The public origin this app is served from. Derived from EXTERNAL_BASE_URL so
# the same image works in development and production. The realm template's
# redirectUris/webOrigins are built from it — a wrong value makes every login
# fail with a redirect_uri mismatch.
: "${APP_PUBLIC_BASE_URL:?APP_PUBLIC_BASE_URL must be set (e.g. https://wba.example.com)}"

mkdir -p /opt/keycloak/data/import
# Keycloak imports EVERY json under this directory, so clear it first.
rm -f /opt/keycloak/data/import/*.json
envsubst < /opt/keycloak/realm-wba.json.template \
  > /opt/keycloak/data/import/realm-wba.json

exec /opt/keycloak/bin/kc.sh start-dev --import-realm --http-relative-path=/auth
```

`chmod +x deploy/keycloak/entrypoint.sh`.

`envsubst` only substitutes variables present in the environment; because the
template also contains `${...}` inside strings you intend to substitute, this is
the desired behaviour. If `envsubst` is absent from the image, **STOP** — do not
substitute a different templating mechanism without reporting.

Create `deploy/keycloak/keycloak.env.example` documenting the four variables
and their dev defaults (`DEV_ADMIN_PASSWORD=FIXME`, etc.). **No real values.**

**Verify**: `python -c "import json,re,os,sys; t=open('deploy/keycloak/realm-wba.json.template').read(); r=re.sub(r'\\$\\{[A-Z_]+\\}','x',t); json.loads(r); print('valid')"` → `valid`
**Verify**: `test -x deploy/keycloak/entrypoint.sh && echo executable` → `executable`
**Verify**: `grep -c 'wba-admin\|wba-user\|wba-service' deploy/keycloak/realm-wba.json.template` → at least `3`
**Verify** (no hardcoded public origin): `grep -c 'localhost' deploy/keycloak/realm-wba.json.template` → **`0`**. The template must contain `${APP_PUBLIC_BASE_URL}` for both `redirectUris` and `webOrigins`. A literal here is a production-blocking defect, not a style issue.
**Verify** (renders correctly for a non-localhost host):
```bash
APP_PUBLIC_BASE_URL=https://wba.example.com KEYCLOAK_CLIENT_SECRET=x \
KEYCLOAK_SERVICE_CLIENT_SECRET=x DEV_ADMIN_PASSWORD=x DEV_USER_PASSWORD=x \
  envsubst < deploy/keycloak/realm-wba.json.template | grep -o 'https://wba.example.com[^"]*' | sort -u
```
→ prints `https://wba.example.com` and `https://wba.example.com/api/v1/auth/callback` — proving the template is host-agnostic.

> ### 🚦 MANUAL GATE 4 — realm content
>
> Operator reads the template and confirms: the three roles exist; `wba-web` is
> confidential with PKCE S256 and the **templated** `redirectUris` (no literal
> host); `wba-internal` has service accounts enabled; the two dev users carry
> the right roles; no real password is committed.
> Wait for `PASS`.

---

### Step 5: Add the `keycloak` compose service and enable the nginx `/auth` block

Add this service to `docker-compose.yml`, after `postgres` and before `api`:

```yaml
  keycloak:
    # Pinned to the current stable line (26.x) — a minor tag, not a digest, so
    # pulls can drift inside 26.x. Match this repo's nginx pinning convention.
    image: quay.io/keycloak/keycloak:26.4
    container_name: wba-ai-keycloak
    restart: unless-stopped
    # start-dev (not `start`) because this is a dev/CI identity provider:
    # it needs no external TLS and allows the loopback admin console below.
    command: ["start-dev", "--import-realm"]
    entrypoint: ["/opt/keycloak/entrypoint.sh"]
    environment:
      KC_DB: postgres
      KC_DB_URL: jdbc:postgresql://postgres:5432/keycloak
      KC_DB_USERNAME: keycloak
      KC_DB_PASSWORD: keycloak
      # The public frontend URL. Pinning it keeps `iss` identical no matter how
      # the request reached Keycloak, which exact `iss` matching requires.
      KC_HOSTNAME: ${EXTERNAL_BASE_URL:-https://localhost}/auth
      # The public origin, passed to the realm template so redirectUris and
      # webOrigins track EXTERNAL_BASE_URL instead of being hardcoded.
      APP_PUBLIC_BASE_URL: ${EXTERNAL_BASE_URL:-https://localhost}
      # Dev only: allow the loopback admin console to answer on the requested
      # host instead of redirecting to KC_HOSTNAME. See Step 5 notes.
      KC_HOSTNAME_STRICT: "false"
      # Derive scheme/host from nginx's X-Forwarded-* headers.
      KC_PROXY_HEADERS: xforwarded
      KC_HTTP_ENABLED: "true"
      KC_HTTP_RELATIVE_PATH: /auth
      # Dev passwords, rendered into the realm by entrypoint.sh. No real
      # credential is committed; the template holds ${...} placeholders.
      DEV_ADMIN_PASSWORD: ${DEV_ADMIN_PASSWORD:-admin}
      DEV_USER_PASSWORD: ${DEV_USER_PASSWORD:-user}
      KEYCLOAK_CLIENT_SECRET: ${KEYCLOAK_CLIENT_SECRET:-dev-web-secret}
      KEYCLOAK_SERVICE_CLIENT_SECRET: ${KEYCLOAK_SERVICE_CLIENT_SECRET:-dev-internal-secret}
    volumes:
      - ./deploy/keycloak/realm-wba.json.template:/opt/keycloak/realm-wba.json.template:ro
      - ./deploy/keycloak/entrypoint.sh:/opt/keycloak/entrypoint.sh:ro
    # Loopback only: the admin console is for the operator on this host.
    # 127.0.0.1 binding means it is NOT reachable from the network. There is
    # deliberately no `8080:8080` mapping.
    ports:
      - "127.0.0.1:8080:8080"
    networks:
      - wba-ai-network
    healthcheck:
      # The realm endpoint answers only after the realm is imported.
      test: ["CMD-SHELL", "exec 3<>/dev/tcp/127.0.0.1/8080 && echo -e 'GET /auth/realms/wba/.well-known/openid-configuration HTTP/1.0\\r\\n\\r\\n' >&3 && head -1 <&3 | grep -q '200'"]
      interval: 10s
      timeout: 5s
      retries: 30
      start_period: 60s
    depends_on:
      postgres:
        condition: service_healthy
```

Notes you must understand before editing:

- **`--http-relative-path=/auth` is passed both as a `command` flag and as
  `KC_HTTP_RELATIVE_PATH`.** That is deliberate belt-and-braces; if Keycloak
  warns about a duplicate, keep the env var and drop the flag, and record it.
- **`KC_HOSTNAME_STRICT=false` is dev-only** and exists so
  `http://127.0.0.1:8080/auth/admin` serves instead of redirecting to
  `https://localhost/auth/admin` (which nginx does not proxy). If the pinned
  image rejects the flag, **STOP** — the documented fallback is a second nginx
  listener bound to `127.0.0.1`, which is an operator decision, not something to
  improvise.
- The `healthcheck` uses bash `/dev/tcp` because the image may not ship `curl`.

Replace the reserved nginx block with **only the realm subtree**:

```nginx
        # ── Keycloak OIDC realm endpoints (Plan C) ───────────────────────
        # ONLY /auth/realms/* is proxied. The admin console and admin REST
        # (/auth/admin*) are deliberately NOT routed: they are the highest-
        # privilege surface in the stack, and nothing in the app needs them
        # from a browser. The operator reaches the console on the loopback
        # port 127.0.0.1:8080 published by the keycloak service.
        location /auth/realms/ {
            proxy_pass http://keycloak:8080;
            proxy_set_header Host              $host;
            proxy_set_header X-Real-IP         $remote_addr;
            proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;
            proxy_set_header X-Forwarded-Host  $host;
        }

        # Anything else under /auth (including /auth/admin) is explicitly
        # refused rather than falling through to an upstream.
        location /auth {
            return 404;
        }
```

**Verify**: `docker compose config -q` → exit 0
**Verify**: `docker run --rm --network work-behavior-analytics-ai_wba-ai-network -v "$PWD/deploy/nginx/nginx.conf:/etc/nginx/nginx.conf:ro" -v "$PWD/deploy/certs:/etc/nginx/certs:ro" nginx:1.30-alpine nginx -t` → `syntax is ok` / `test is successful`
**Verify**: `grep -c 'location /auth' deploy/nginx/nginx.conf` → `2` (the prefix location and the catch-all)
**Verify**: `docker compose up -d postgres keycloak` then `docker compose ps keycloak` → `healthy`

> ### 🚦 MANUAL GATE 5 — stack up
>
> Operator verifies in a browser:
> 1. `http://127.0.0.1:8080/auth/admin/` loads the console login page.
> 2. Signing in as the Keycloak bootstrap admin (`KC_BOOTSTRAP_ADMIN_USERNAME`/
>    `_PASSWORD` if configured, otherwise the image's documented default) shows
>    realm `wba`, the three roles, and both clients.
> 3. `https://localhost/auth/admin/` returns **404** — the admin surface is not
>    proxied.
> 4. Signing in as `dev-admin` at `http://127.0.0.1:8080/auth/realms/wba/account`
>    works, and the token shown there (Account → Personal info → or the account
>    console's token viewer) lists `wba-admin`.
> Wait for `PASS`.

---

### Step 6: Document the variables and verify the issuer is exact

Add a section to `.env.example` (follow the file's existing comment style):

```
# ── Keycloak / authentication ────────────────────────────────────────────
# Public realm URL. Must equal the `iss` claim EXACTLY — scheme, host, port,
# trailing slash and case all matter — so the API rejects every token if it
# differs. This is the BROWSER-facing URL.
KEYCLOAK_ISSUER=https://localhost/auth/realms/wba
# Realm URL the API container uses for discovery/token/JWKS. Service name,
# plain HTTP: `localhost` inside a container is the container itself.
KEYCLOAK_INTERNAL_URL=http://keycloak:8080/auth/realms/wba
KEYCLOAK_REALM=wba
# Public origin of THIS app (scheme + host, no trailing slash). Must agree with
# the origin of KEYCLOAK_ISSUER — startup fails otherwise. Used to build the
# realm's redirectUris/webOrigins through the Keycloak template.
APP_PUBLIC_BASE_URL=https://localhost
KEYCLOAK_CLIENT_ID=wba-web
KEYCLOAK_CLIENT_SECRET=FIXME
KEYCLOAK_SERVICE_CLIENT_ID=wba-internal
KEYCLOAK_SERVICE_CLIENT_SECRET=FIXME
AUTH_COOKIE_SECURE=true
AUTH_SESSION_IDLE_MINUTES=60
AUTH_SESSION_MAX_HOURS=8
# Dev-only Keycloak seed passwords (realm template). Never real credentials.
DEV_ADMIN_PASSWORD=FIXME
DEV_USER_PASSWORD=FIXME
```

Then prove the issuer matches the public URL exactly, from **inside** the API
container (the only place the app will see it):

**Verify**:
```bash
docker compose exec -T keycloak sh -c \
  'curl -sf http://127.0.0.1:8080/auth/realms/wba/.well-known/openid-configuration' \
  | python -c "import json,sys; d=json.load(sys.stdin); print(d['issuer'])"
```
→ `https://localhost/auth/realms/wba`
**Verify**: `curl -sf https://localhost/auth/realms/wba/.well-known/openid-configuration | grep -o '"issuer":"[^"]*"'` → `"issuer":"https://localhost/auth/realms/wba"` **from both** the host and the container (the container command above). If the two differ, **STOP** — that is the exact failure this plan exists to prevent.

> ### 🚦 MANUAL GATE 6 — issuer is stable
>
> Operator verifies both invocations print the **identical** issuer string, and
> that `.env.example` documents all ten variables with no real secrets.
> Wait for `PASS`.

---

### Step 7: Correct the design doc's "Issuer URL" open item

In `docs/design/authn-authz-design.md`, replace the "Issuer URL" section's open
item paragraph (it begins **"Open item for Plan C:"**) with the settled design:

- Two settings: `KEYCLOAK_ISSUER` (public, exact `iss`) and
  `KEYCLOAK_INTERNAL_URL` (API-side discovery/token/JWKS over the Docker
  network). Rationale: inside a container `localhost` is the container, so one
  URL cannot serve both.
- At first use the API asserts that the discovery document's `issuer` equals
  `KEYCLOAK_ISSUER`, so a mismatch is one clear log line rather than every
  request failing.
- The image is pinned (minor tag) because the hostname env var differs between
  Quarkus and legacy WildFly images.
- nginx exposes **only** `/auth/realms/*`; the admin console and admin REST are
  not proxied and are reached only on the loopback port.

**Verify**: `grep -c "Open item for Plan C" docs/design/authn-authz-design.md` → `0`
**Verify**: `grep -c "KEYCLOAK_INTERNAL_URL" docs/design/authn-authz-design.md` → at least `1`

> ### 🚦 MANUAL GATE 7 — docs
>
> Operator reads the rewritten section and confirms it describes what was built.
> Wait for `PASS`.

---

### Step 8: Record what production changes (no code, one doc section)

Nothing in this plan is localhost-only by construction, but several settings are
**dev conveniences that must change for a real domain**. Write them down so a
deployment does not rely on someone remembering. Add a short
**"Production checklist"** subsection at the end of the design doc's
"Deployment Topologies" section:

| Setting / item | Dev value | Production |
|---|---|---|
| `APP_PUBLIC_BASE_URL` | `https://localhost` | the real origin, e.g. `https://wba.example.com` |
| `KEYCLOAK_ISSUER` | `https://localhost/auth/realms/wba` | `<APP_PUBLIC_BASE_URL>/auth/realms/wba` (startup validator enforces the prefix) |
| Realm `redirectUris` / `webOrigins` | templated from `APP_PUBLIC_BASE_URL` | same template, different value — **no realm edit** |
| `KC_HOSTNAME_STRICT` | `"false"` | **removed** (defaults to strict) |
| Keycloak loopback port `127.0.0.1:8080` | admin console access | **removed**; no admin surface published |
| `deploy/certs/*` (mkcert) | local CA | a real certificate, or TLS terminated at a load balancer / API Gateway |
| `AUTH_COOKIE_SECURE` | `true` | `true` (never false behind HTTPS) |
| Keycloak DB password (`keycloak`) | dev default | a secret-store value (Plan E owns broader credential handling) |
| Compose vs ECS | Compose | Plan A's proxy-awareness means this is configuration, not code — see the AWS section |

Add one sentence to the table's note: *"No application code branches on host or
scheme. `nginx server_name` is the only remaining literal hostname in the
repository's deployment config, and it is the sole `listen 443` server, so it
answers any Host header; parameterise it when a second vhost is added."*

**Verify**: `grep -c "Production checklist" docs/design/authn-authz-design.md` → `1`
**Verify**: `grep -n "KC_HOSTNAME_STRICT" docs/design/authn-authz-design.md` → present in the checklist

> ### 🚦 MANUAL GATE 8 — production readiness
>
> Operator confirms the checklist names every dev-only setting and that no item
> requires a code change.
> Wait for `PASS`.

---

## Test plan

This step adds **no Python behaviour**, so it adds **no unit tests**. Its
verification is configuration plus the live checks in Steps 5 and 6. Do not
invent tests that assert settings defaults — a test that only re-states
`KEYCLOAK_ISSUER="https://localhost/auth/realms/wba"` proves nothing and will
rot.

The substantive proof is Gate 5 (console loads, admin surface 404, dev login
works) and Gate 6 (issuer identical from host and container).

**Regression check**: `pytest -m unit tests -q` must be unchanged. This plan
touches `src/domain/settings.py`, which every unit test imports, so a typo in
the settings block fails the whole suite loudly.

## Done criteria

- [ ] `docker compose config -q` exits 0
- [ ] `docker compose ps` shows `keycloak` as `healthy`
- [ ] `curl -sf https://localhost/auth/realms/wba/.well-known/openid-configuration` returns a document whose `issuer` is exactly `https://localhost/auth/realms/wba`
- [ ] `curl -s -o /dev/null -w '%{http_code}' https://localhost/auth/admin/` prints `404`
- [ ] `docker compose exec -T postgres psql -U "$POSTGRES_USER" -lqt | cut -d'|' -f1 | grep -cw keycloak` prints `1`
- [ ] `pytest -m unit tests -q` exits 0 with the same pass count as before this plan
- [ ] `mypy src/` exits 0
- [ ] No `KEYCLOAK_*` / `AUTH_*` value in `.env.example` is a real credential (`grep -n 'FIXME' .env.example` shows them)
- [ ] The application is **still unauthenticated**: `curl -sf https://localhost/api/health` returns `{"status":"healthy"}` with no `Authorization` header
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report (do not improvise) if:

- The image rejects `KC_HOSTNAME_STRICT` or `--http-relative-path` in a way the
  notes above do not cover.
- The `issuer` differs between the host and the container in Step 6.
- `envsubst` is missing from the Keycloak image.
- The service account `wba-internal` cannot be given `wba-service` with the
  template shape you wrote.
- Keycloak cannot connect to the `keycloak` database after Step 3 (the role/DB
  creation failed, or the volume was not the one in use).
- Any in-scope file has drifted from the "Current state" excerpts.

## Maintenance notes

- **`KC_HOSTNAME_STRICT=false` is dev-only.** A real deployment must remove it
  and front the console differently. The AWS topology in the design doc removes
  nginx entirely, at which point the admin console must not be published at all.
- **The `keycloak` database password is a dev default.** A real deployment takes
  it from a secret store; Plan E owns host-exposed Postgres hardening.
- **Changing `KC_HTTP_RELATIVE_PATH` changes `iss`**, and every token becomes
  invalid until sessions are recreated. Treat it as a breaking change.
- **Adding a client** (e.g. for MCP, per the design's Future Considerations) means
  a new template entry, a new secret variable, and a re-import — but realm
  re-import in `start-dev` only applies on first boot against an empty realm
  table, so document the reset path.
- **A reviewer should scrutinize**: that `/auth/admin` is genuinely not routed,
  that no secret value is committed, and that the issuer string is written in
  exactly one place per runtime.

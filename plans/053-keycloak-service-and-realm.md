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

### Execution progress — RESUME AT STEP 5 (re-run; five decisions now settled)

Session paused **2026-10-30** after Gate 4, resumed **2026-10-31**.
Steps 1–4 are all **committed** on `feature/plan-c-keycloak`; HEAD is
`64bc5f2a` (`Step 4: Write the realm as code`). The working tree had been clean
before Step 5 — the earlier note that Step 4's files were "still untracked" was
written mid-session and is stale.

| Step | State |
|---|---|
| 1 — settings fields | ✅ **PASS** (operator). Committed as `0baf39d5`. |
| 2 — DB bootstrap | ✅ **PASS** (operator). Committed as `4257ad65`. |
| 3 — existing-volume role/DB | ✅ **PASS** (operator). Committed as `96217cae`. |
| 4 — realm as code | ✅ **PASS** (operator). Committed as `64bc5f2a`. |
| 5 — compose service + nginx | ⛔ **STOPPED 2026-10-31**, then **re-scoped 2026-10-31** with five operator decisions (below). Edits are in the tree and correct; one re-run needed to apply the amended service block and verify. |
| 5b — admin guide | ✅ **DONE 2026-10-31** — `ADMIN_GUIDE.md` written; all four Step 5b verify commands pass. The recovery command was tested verbatim against the real 26.8.1 image (`Created temporary admin user with username admin`, exit 0). Also deleted `deploy/keycloak/keycloak.env.example` (decision 8). |
| 6–8 | ⬜ Not started. |

**Five decisions taken on 2026-10-31 that amend Step 5** (all operator-approved):

| # | Decision | Detail |
|---|---|---|
| 1 | **Healthcheck fix approved** | `echo -e` → `printf`, plus an explicit `Host: localhost` header. Verified `PROBE_OK` on both 26.4.7 and 26.8.1. |
| 2 | **Pin `26.8`, not `26.4`** | Registry evidence: 26.4 is 12 minors behind; **26.8.1** is current stable. The floating `26.4` tag had silently resolved to 26.4.7. |
| 3 | **Console on, via `KC_HOSTNAME_ADMIN`** | The plan's `KC_HOSTNAME_STRICT="false"` was the wrong lever (it is a no-op when `KC_HOSTNAME` is set). `KC_HOSTNAME_ADMIN=http://127.0.0.1:8080/auth` gives the loopback console a working URL while the public issuer is unchanged. |
| 4 | **Console port OFF by default; toggle documented in `ADMIN_GUIDE.md`** | No second compose file (operator: "hard to maintain"). Base `docker-compose.yml` publishes **no** console port; the toggle is a manual documented edit to the port to `127.0.0.1:8080:8080` + `docker compose up -d keycloak`. |
| 5 | **Bootstrap admin: both vars added, generated** | `start-dev` creates **no** admin user without them (verified: grant → `401`). `KC_BOOTSTRAP_ADMIN_USERNAME` is a **literal** `admin` (an identifier, like the `keycloak` DB role name — not a secret); `KC_BOOTSTRAP_ADMIN_PASSWORD` is a generated `${VAR}` with no default. Takes the credential count from five to six. |
| 6 | **Rename the app seed passwords (done 2026-10-31)** | `DEV_ADMIN_PASSWORD` → `DEV_WBA_ADMIN_PASSWORD`, `DEV_USER_PASSWORD` → `DEV_WBA_USER_PASSWORD`. Rationale: with `DEV_KEYCLOAK_ADMIN_PASSWORD` added (decision 5) there were two "admin" passwords meaning different things — the **wba-realm application** user vs the **Keycloak console** account. The `DEV_WBA_*` prefix makes the pairing explicit. **No migration script** — greenfield, operator's call; see the note below. |
| 7 | **Recreate the `keycloak` database so the bootstrap admin actually seeds** | The existing Keycloak DB predates the bootstrap vars, so they would never take effect here and the console would stay unloggable-into. The DB is 100% template-derived (verified), so dropping and recreating it loses nothing and exercises the real fresh-clone path. See the caveat section above. |
| 8 | **Delete `deploy/keycloak/keycloak.env.example` (done 2026-10-31)** | It was created in Step 4, when `.env.example` held no Keycloak variables at all. Step 6 closed that gap, making it a second source of truth — and it drifted immediately: it lists five of the six credentials, missing `DEV_KEYCLOAK_ADMIN_PASSWORD`. Nothing loads it (the `keycloak` service declares no `env_file`; it uses explicit `environment:` entries). `.env.example` is canonical because `setup.sh` copies *it* to build `.env`, and it documents the non-secret `KEYCLOAK_ISSUER`/`AUTH_*` settings too. Removing the duplicate also matches the repo's pattern — `deploy/postgres/` has no parallel file for `init-keycloak.sh`. |

**Decision 6 needs no migration — this is a greenfield project (operator,
2026-10-31).** The rename is a pure source-level change: nothing has been
deployed and the rename is not applied anywhere, so there is no existing `.env`
key to carry across and no migration script should exist. Do **not** add one.

The only consequence is that a developer whose local `.env` still holds the old
names will get **new** values for the two seed passwords on the next
`./scripts/setup.sh` (the loop generates any key whose value is a placeholder,
and `get_env_value` on an absent key returns empty). That is acceptable and
self-healing: it just re-seeds `dev-admin` / `dev-user`, and the realm is
re-imported from the template with the new values. There is no database to stay
in sync with, because the realm is imported from the template on each fresh boot.

**A reviewer should not "helpfully" reintroduce a migration script here.** Its
absence is the decision, not an oversight.

**Step 5 (first attempt) outcomes — all three defects found and now fixed in-plan:**
- ✅ The `keycloak` service was added and runs; the realm imported into the real
  stack; `issuer` = `https://localhost/auth/realms/wba`.
- ✅ The nginx `/auth` block was written correctly and passes `nginx -t`.
- ⛔ **The healthcheck YAML was defective** — no `Host` header → HTTP 500 on every
  probe → permanently `unhealthy` while Keycloak itself was fine. Fixed (decision 1).
- ⛔ **The running nginx serves a stale config** (bind-mount inode staleness) — no
  `https://localhost/auth/...` check is meaningful until
  `docker compose up -d --force-recreate nginx`. Amended into the step.
- ⛔ **`KC_HOSTNAME_STRICT="false"` is a no-op** — fixed by decision 3.

**Two earlier decisions (Steps 1–2) that still stand:**
1. The two client secrets live on `ApiSettings`, not `UISettings`.
2. No Keycloak credential is committed — every one is `${VAR}` with no default
   (or a non-secret literal identifier), generated by `scripts/setup.sh`.

**One item deferred, not forgotten:** the four connector services declare
`env_file: - .env`, so they receive every Keycloak credential. Pre-existing, out
of scope, belongs to **Plan E**.
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

  **Credential policy for this plan (operator decision, 2026-10-30).** Every
  Keycloak credential is a `${VAR}` reference with **no default**, and `FIXME` in
  `.env.example`:

  | Variable | Where |
  |---|---|
  | `KEYCLOAK_DB_PASSWORD` | `.env` only; postgres service + Keycloak's `KC_DB_PASSWORD` |
  | `KEYCLOAK_CLIENT_SECRET` | `.env` only; `wba-web` confidential client |
  | `KEYCLOAK_SERVICE_CLIENT_SECRET` | `.env` only; `wba-internal` service account |
  | `DEV_WBA_ADMIN_PASSWORD` | `.env` only; realm template seed |
  | `DEV_WBA_USER_PASSWORD` | `.env` only; realm template seed |
  | `DEV_KEYCLOAK_ADMIN_PASSWORD` | `.env` only; `KC_BOOTSTRAP_ADMIN_PASSWORD` (added 2026-10-31, decision 5) |

  **Six credentials** as of 2026-10-31 (was five; the bootstrap admin password
  was added when it turned out `start-dev` creates no admin user without it).

  This matches the repo's existing convention for `POSTGRES_PASSWORD`, which also
  has no default. **Do not reintroduce `:-something` defaults.**

  **Non-secret literals that are deliberately NOT variables** (do not "fix" these
  into `.env` entries): `KC_DB_USERNAME: keycloak`, the Postgres role name
  `keycloak`, and `KC_BOOTSTRAP_ADMIN_USERNAME: admin`. These are identifiers,
  not credentials — an identifier in `.env` buys no secrecy and costs a variable.

  **`scripts/setup.sh` generates all five**, following the exact pattern it
  already uses for `CONNECTOR_ENCRYPTION_KEY`: `is_placeholder` → generate →
  `set_env_value`, so a re-run preserves rather than rotates. Add a
  `generate_secret()` helper preferring `openssl rand -base64 24`, falling back
  to `python3 -c "import secrets,base64..."`, then `/dev/urandom`. This keeps the
  "zero manual setup" property *and* keeps every credential out of git — the
  wizard is the intended path, and the manual snippet in `USER_GUIDE.md` is the
  fallback for someone who skipped it.

  Rotating on re-run would be a defect, not a convenience:
  `KEYCLOAK_DB_PASSWORD` is the password of an already-created Postgres role,
  and the client secrets are baked into the imported realm. Changing them in
  `.env` alone desyncs the database and the realm from the file.

  Note the related literal that is **not** a credential: `KC_DB_USERNAME:
  keycloak` and the role name `keycloak` are identifiers, not secrets, and stay
  as literals.
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
- `.env.example` — the Keycloak credential block and the `AUTH_*` settings.
  (`deploy/keycloak/keycloak.env.example` was deleted: `.env.example` is the
  single source of truth and the duplicate had already drifted.)
- `deploy/postgres/init-keycloak.sh` (create) — creates the `keycloak` role + DB on a **fresh** volume, reading the password from `$KEYCLOAK_DB_PASSWORD`.
- `DEVELOPER_QUICK_START.md` — the Keycloak credential note and the idempotent
  existing-volume snippet (Step 3).
- `scripts/setup.sh` — generate the five Keycloak credentials (Step 2).
- `USER_GUIDE.md` — the *Keycloak credentials* subsection (Step 2).
- `deploy/nginx/nginx.conf` — replace the reserved block with the real one.
- `ADMIN_GUIDE.md` (create) — the console toggle, the bootstrap credential, and
  the `kc.sh bootstrap-admin user` recovery (Step 5b).
- `src/domain/settings.py` — add the non-secret `KEYCLOAK_*` and `AUTH_*` settings
  fields (including both client **IDs**).
- `src/app/settings.py` — add the two client **secrets** to `ApiSettings`.
- `.env.example` — document the new variables, including
  `DEV_KEYCLOAK_ADMIN_PASSWORD=FIXME` (Step 6).
- `scripts/setup.sh` — generate `DEV_KEYCLOAK_ADMIN_PASSWORD` alongside the
  existing five (Step 6).
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

#### Gate 1 record — 2026-10-30 — ✅ PASS (operator, 2026-10-30)

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

**This is a `.sh` script, not a `.sql` file — deliberately.** The postgres
image's entrypoint runs `*.sh` files as executables (with the container's
environment in scope) and `*.sql` files through `psql -f`. Only the shell form
can read a password from the environment; a `.sql` file would force the
credential to be written as a literal in a committed file. Do not "simplify"
this to `.sql`.

Create `deploy/postgres/init-keycloak.sh`:

```bash
#!/bin/bash
# Creates the separate database Keycloak uses. Runs ONLY on a fresh pgdata
# volume (Postgres executes /docker-entrypoint-initdb.d once). On an existing
# volume this file is skipped, and the operator runs the idempotent snippet in
# DEVELOPER_QUICK_START.md instead. Schemas never mix: the application stays in
# POSTGRES_DB, Keycloak lives in `keycloak`.
#
# Shell rather than SQL so the password comes from the environment: a committed
# .sql file cannot read a variable and would force the literal into git.
set -euo pipefail

: "${KEYCLOAK_DB_PASSWORD:?KEYCLOAK_DB_PASSWORD must be set (see .env.example)}"

psql -v ON_ERROR_STOP=1 \
     --username "$POSTGRES_USER" \
     --dbname "$POSTGRES_DB" <<EOSQL
CREATE ROLE keycloak WITH LOGIN PASSWORD '${KEYCLOAK_DB_PASSWORD}';
CREATE DATABASE keycloak OWNER keycloak;
EOSQL
```

`chmod +x deploy/postgres/init-keycloak.sh`. The `-x` bit matters: the entrypoint
runs an executable `.sh` and *sources* a non-executable one; both work, but the
executable form is the intended usage and gives a clean failure if `set -e` trips.

Then add the variable to the `postgres` service in `docker-compose.yml` (in its
`environment:` block, beside `POSTGRES_DB`):

```yaml
      KEYCLOAK_DB_PASSWORD: ${KEYCLOAK_DB_PASSWORD}
```

and mount the script on the `postgres` service's `volumes` list, **before** the
`pgdata` line:

```yaml
    volumes:
      - ./deploy/postgres/init-keycloak.sh:/docker-entrypoint-initdb.d/10-keycloak.sh:ro
      - pgdata:/var/lib/postgresql/data
```

**No default on `KEYCLOAK_DB_PASSWORD`** — `docker compose up` fails loudly if it
is unset, matching `POSTGRES_PASSWORD` (which also has no default). This is the
repo's convention for a credential the running system uses, and it is what keeps
the value out of git. See the credential policy note in "Repo conventions" above.

Then teach `scripts/setup.sh` to generate all five credentials, so the operator
never hand-writes one and the "zero manual setup" property survives:

1. Add a `generate_secret()` helper beside `generate_fernet_key()`. It prefers
   `openssl rand -base64 24`, falls back to
   `python3 -c "import secrets,base64; print(base64.b64encode(secrets.token_bytes(24)).decode())"`,
   then to `head -c 24 /dev/urandom | base64`. Print the value; return non-zero
   if all three fail.
2. Add a loop over `KEYCLOAK_DB_PASSWORD`, `KEYCLOAK_CLIENT_SECRET`,
   `KEYCLOAK_SERVICE_CLIENT_SECRET`, `DEV_WBA_ADMIN_PASSWORD`, `DEV_WBA_USER_PASSWORD`
   that mirrors the `CONNECTOR_ENCRYPTION_KEY` block exactly: if
   `is_placeholder "$(get_env_value "$KEY" "$ENV_FILE")"`, generate and
   `set_env_value`; otherwise `info "${KEY} already set — preserving it"`.
   Place it after the encryption-key block and before "Optional settings".
3. Mention it in the summary block, beside `Encryption key: auto-generated`.

**The idempotency is load-bearing, not a nicety.** Rotating
`KEYCLOAK_DB_PASSWORD` on a re-run would desync `.env` from the Postgres role
that already exists; rotating the client secrets would desync it from the
imported realm. Do not "improve" this to always-regenerate.

**Verify** (wizard syntax): `bash -n scripts/setup.sh` → exit 0
**Verify** (generator works): `bash -c 'source <(sed -n "/^generate_secret()/,/^}/p" scripts/setup.sh); v=$(generate_secret); echo "len=${#v}"'` → `len=32`
**Verify** (idempotent, without touching the real `.env`): copy the loop into a
scratch file in `/tmp` with a scratch `.env` containing one `KEYCLOAK_DB_PASSWORD=FIXME`
line, run it twice, and confirm: run 1 generates all five, run 2 preserves all
five, `grep -oE '^[A-Z_]+' .env | sort | uniq -d` is empty, and the five values
are distinct.

**Verify**: `docker compose config -q` → exit 0 **with `KEYCLOAK_DB_PASSWORD` set
in `.env`**. (Without it, compose warns and substitutes an empty string; the
container then fails at startup on the `:?` guard, which is the intended
fail-fast. Do not add a default to silence the warning.)
**Verify**: `test -x deploy/postgres/init-keycloak.sh && echo executable` → `executable`
**Verify** (no literal credential in the committed file):
`grep -cE "PASSWORD[[:space:]]*'[^\$]" deploy/postgres/init-keycloak.sh` → `0`.
This matches a quoted password that does **not** start with `$` — i.e. a literal.
(The earlier form of this check, `PASSWORD [a-z]`, was wrong: it also matches the
words "must be set" inside the plan-mandated `:?` guard, so it can never return 0.
Do not restore it.)

**Verify** (the variable is genuinely the source of the password):
`grep -c "'\${KEYCLOAK_DB_PASSWORD}'" deploy/postgres/init-keycloak.sh` → `1`

> ### 🚦 MANUAL GATE 2 — bootstrap file
>
> Operator verifies the mount line is present and read-only (`:ro`), that no
> existing volume path was changed or removed, and that **no credential literal
> appears in the committed script** — the password must be read from
> `$KEYCLOAK_DB_PASSWORD`.
> Wait for `PASS`.

#### Gate 2 record — 2026-10-30 — ✅ PASS (operator, 2026-10-30) (revised after credential rework)

Executed in the live working tree on `feature/plan-c-keycloak`, uncommitted.

**First attempt was rejected by the operator** for committing a credential
literal (`CREATE ROLE keycloak WITH LOGIN PASSWORD 'keycloak'`). The step was
reworked to a shell init script reading `$KEYCLOAK_DB_PASSWORD`, and the
credential policy was extended to all five Keycloak secrets. A second executor
run then STOPPED on a tool-permission block (see below) and the operator chose
to resolve it by documenting the variables and having `scripts/setup.sh`
generate them.

Diff (final):
- `deploy/postgres/init-keycloak.sh` — **created**, chmod 755, no literal
- `deploy/postgres/init-keycloak.sql` — **deleted** (the rejected literal version)
- `docker-compose.yml` — **+2**: `KEYCLOAK_DB_PASSWORD: ${KEYCLOAK_DB_PASSWORD}`
  in the postgres `environment:` block, and the volumes mount changed `.sql` → `.sh`
- `scripts/setup.sh` — `generate_secret()` helper + a five-key generation loop
- `USER_GUIDE.md` — *Keycloak credentials* subsection
- `DEVELOPER_QUICK_START.md` — credential note + the existing-volume snippet

| Check | Command | Observed |
|---|---|---|
| Compose syntax | `docker compose config -q` | exit 0. Warns `KEYCLOAK_DB_PASSWORD is not set` — **expected**, since the operator has not yet run the wizard or added the variables |
| Script executable | `test -x deploy/postgres/init-keycloak.sh` | executable |
| Old SQL file gone | `test ! -f deploy/postgres/init-keycloak.sql` | gone |
| No literal credential | `grep -cE "PASSWORD[[:space:]]*'[^\$]" deploy/postgres/init-keycloak.sh` | `0` |
| Variable is the source | `grep -c "'\${KEYCLOAK_DB_PASSWORD}'" deploy/postgres/init-keycloak.sh` | `1` |
| No default in compose | `grep -cE 'KEYCLOAK_DB_PASSWORD: \$\{[A-Z_]+\}$' docker-compose.yml` | `1` (the other four arrive in Step 5) |
| Diff size | `git diff --stat docker-compose.yml` | `1 file changed, 2 insertions(+)` |
| Mount is read-only | `docker compose config` | `target: /docker-entrypoint-initdb.d/10-keycloak.sh`, `read_only: true` |
| `pgdata` preserved | `docker compose config` | `source: pgdata` → `/var/lib/postgresql/data`, unmodified |
| Live volume intact | `docker volume ls` | `work-behavior-analytics-ai_pgdata` still exists |
| Stack undisturbed | `docker inspect wba-ai-postgres` | running, no recreate |
| Wizard syntax | `bash -n scripts/setup.sh` | exit 0 |
| Wizard generator | `generate_secret()` in isolation | returns a 32-char value |
| Wizard idempotency | the generation loop against a scratch `.env` in `/tmp` | run 1 generates all five; run 2 preserves all five; 0 duplicate keys; 0 FIXME left; 5 distinct values |

**RESOLVED.** The executor was denied the write to `.env` by the harness
classifier (`[Credential Materialization]`) and correctly stopped rather than
routing around it. The operator then ran `./scripts/setup.sh`, which generated
all five. Verified after the fact (names and shape only — no value was read):

| Check | Observed |
|---|---|
| All five present in `.env` | `KEYCLOAK_DB_PASSWORD`, `KEYCLOAK_CLIENT_SECRET`, `KEYCLOAK_SERVICE_CLIENT_SECRET`, `DEV_WBA_ADMIN_PASSWORD`, `DEV_WBA_USER_PASSWORD` — each exactly once |
| None left as placeholder | 0 of the five contain `FIXME` |
| Distinct values | 5 of 5 |
| No duplicate keys | none (a `NEO`/`PERSON` reading was a reviewer grep bug — `[A-Z_]` drops the `4` in `NEO4J`) |
| Compose resolves it | `docker compose config` → `non-empty`; the earlier `KEYCLOAK_DB_PASSWORD is not set` warning is **gone** |

This also validates the `scripts/setup.sh` change end-to-end: the wizard
generated real values on first run and preserved them on the operator's
subsequent run.

**Fresh-clone path tested live (reviewer, in a throwaway container).** The
`.sh` init script was exercised through the real postgres entrypoint against an
empty volume, with a temporary container and volume that were removed afterwards.
The operator's stack was not touched.

| Check | Observed |
|---|---|
| Entrypoint runs the script | `running /docker-entrypoint-initdb.d/10-keycloak.sh` |
| It creates the objects | `CREATE ROLE` / `CREATE DATABASE` |
| The role authenticates | `keycloak/keycloak` |
| Password is a real hash, not a literal | `rolpassword` matches `SCRAM-SHA-256$%` — a quoted-heredoc bug would have stored the literal text `${KEYCLOAK_DB_PASSWORD}` |
| The `:?` guard fires | with the variable unset: `KEYCLOAK_DB_PASSWORD must be set (see .env.example)` |

**Not proven — negative control.** The intent was to confirm a *wrong* password
is rejected. Three attempts were blocked by the harness classifier
(`[Credential Materialization]`, `[Remote Shell Writes]`) and were not worked
around. Residual risk is judged low: a stored SCRAM hash rules out the
quoted-heredoc failure mode, which is the only realistic one here. To close it:

```bash
docker run --rm -e PGPASSWORD=wrong -e POSTGRES_HOST_AUTH_METHOD=scram-sha-256 postgres:17 \
  psql "postgresql://keycloak:wrong@127.0.0.1:5432/keycloak" -c 'select 1'
```

**Pre-existing finding, recorded not fixed (out of this plan's scope).** The four
connector services (`github-producer`, `jira-producer`, `confluence-producer`,
`signal-consumer`) declare `env_file: - .env` (`docker-compose.yml:260,283,306,330`
— present in `HEAD`, not introduced here). Every variable in `.env` is therefore
injected into those containers, so all five Keycloak credentials now appear in
them too — including `DEV_WBA_ADMIN_PASSWORD` / `DEV_WBA_USER_PASSWORD`, which they have
no use for. The `api` service does **not** do this; it lists explicit
`environment:` entries, which is why it correctly receives none of them. This is
unnecessary credential spread inside one trust boundary rather than a boundary
violation, and it predates Plan C. **Plan E** (infrastructure surface hardening)
is its natural home; it should not be fixed inside 053.

**Three bugs in this plan's own verification commands**, found by the executor
and fixed in Step 2 above:
1. `grep -cE "PASSWORD *'|PASSWORD [a-z]"` could never return `0` — it also
   matches "must be set" in the mandated `:?` guard. Replaced with a check for a
   quoted non-`$` value.
2. `grep -n 'init-keycloak' docker-compose.yml` was expected to return two lines;
   the env line does not contain that string, so it returns one. Corrected.
3. `awk '... print ($2=="" ? ...)'` misreads a quoted empty value — the resolved
   line is `KEYCLOAK_DB_PASSWORD: ""`, so `$2` is the two-character `""`, not an
   empty field. The correct test compares against `"\"\""`.

**Not yet in effect — expected.** The container has not been recreated, so
`/docker-entrypoint-initdb.d/` is not yet mounted inside the running Postgres.
A mount change only applies on recreate, and this step deliberately does not
restart the stack. **Step 3 is what actually creates the role and database on
this existing volume.**

**Scope**: `git status --porcelain` shows ` M docker-compose.yml`,
`?? deploy/postgres/`, plus the reviewer's own doc/plan edits
(`USER_GUIDE.md`, `DEVELOPER_QUICK_START.md`, `scripts/setup.sh`, `plans/053-...`).
Nothing committed.

---

### Step 3: Create `keycloak` role and database on an EXISTING volume

Fresh installs get the database from Step 2. **An existing `pgdata` volume will
not**, and Keycloak fails to boot with a connection error. Make this an explicit
step rather than a documented footnote, so it is not discovered as a mystery.

Add a short section to `DEVELOPER_QUICK_START.md` (find the database/setup
section; keep its heading style) containing this idempotent snippet:

```bash
# Existing databases only (a fresh `docker compose down -v` gets this
# automatically from deploy/postgres/init-keycloak.sh).
# KEYCLOAK_DB_PASSWORD is read from the environment — never write it inline.
docker compose exec -T postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" <<SQL
DO \$\$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'keycloak') THEN
    CREATE ROLE keycloak WITH LOGIN PASSWORD '${KEYCLOAK_DB_PASSWORD}';
  END IF;
END \$\$;
SQL
docker compose exec -T postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
  -tc "SELECT 1 FROM pg_database WHERE datname = 'keycloak'" | grep -q 1 || \
  docker compose exec -T postgres createdb -U "$POSTGRES_USER" -O keycloak keycloak
docker compose exec -T postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c '\q'
```

Note the unquoted `<<SQL` heredoc delimiter: it is what lets the shell expand
`${KEYCLOAK_DB_PASSWORD}`. A quoted `<<'SQL'` would pass the literal text
`${KEYCLOAK_DB_PASSWORD}` to Postgres as the password. The `\$\$` escapes are
required for the same reason — dollar-quoting must reach Postgres intact.

The operator runs this with `KEYCLOAK_DB_PASSWORD` exported (or sourced from
`.env`) in their shell.

Then run it once yourself against the operator's running stack.

**Verify**: `docker compose exec -T postgres psql -U "$POSTGRES_USER" -lqt | cut -d'|' -f1 | grep -cw keycloak` → `1`
**Verify**: re-running the same snippet does not error → exit 0 (idempotent)
**Verify** (the role can actually authenticate with the env password):
`docker compose exec -T postgres psql "postgresql://keycloak:${KEYCLOAK_DB_PASSWORD}@localhost:5432/keycloak" -c 'select 1'` → prints `1`. This catches the case where the role was created with the literal text `${KEYCLOAK_DB_PASSWORD}` as its password — the exact failure a quoted heredoc produces.
**Verify** (no literal in the doc): `grep -c "PASSWORD 'keycloak'" DEVELOPER_QUICK_START.md` → `0`

> ### 🚦 MANUAL GATE 3 — database exists
>
> Operator verifies `\l` in psql lists a `keycloak` database owned by `keycloak`,
> and that the application database and its tables are untouched.
> Wait for `PASS`.

#### Gate 3 record — 2026-10-30 — ✅ PASS (operator, 2026-10-30)

The role/database snippet had already been committed to
`DEVELOPER_QUICK_START.md` by Step 2's commit `4257ad65`. **A security-relevant
bug was found in it and fixed before it was ever run** (see below).

**THE BUG (found by the reviewer, not by execution).** The committed snippet
began:

```bash
set -a; . ./.env; set +a
```

Sourcing `.env` **fails**: `./.env:171: parse error near '\n'`. Line 171
(`PERSON2_ID`) holds an unquoted `<...>` value — the neo4j test-catalog ids — which
is not valid shell syntax. `KEYCLOAK_DB_PASSWORD` is at line 173, so sourcing dies
*before* reaching it.

The failure is **silent and unsafe**: the heredoc's `${KEYCLOAK_DB_PASSWORD}`
then expands to an empty string, and Postgres runs
`CREATE ROLE keycloak WITH LOGIN PASSWORD ''` without error — a passwordless role
that Keycloak would nonetheless connect with. Verified by simulation:
`RESULT: var UNSET -> heredoc expands to EMPTY password`.

**Fix applied to `DEVELOPER_QUICK_START.md`** (uncommitted): read only the one
value using the idiom `scripts/setup.sh:146` already uses, guard it with `:?`,
and use `-v ON_ERROR_STOP=1`. The `set -a; . ./.env` line is gone.

**Verification of the fix** (extracted from the doc's own fenced block and run):

| Check | Observed |
|---|---|
| Doc snippet syntax | `bash -n` → SYNTAX OK |
| Dry-run with `docker` stubbed | SQL contains the real 32-char value; no `${KEYCLOAK_DB_PASSWORD}` leak; `$$` dollar-quoting intact |
| Guard aborts on empty value | `KEYCLOAK_DB_PASSWORD: KEYCLOAK_DB_PASSWORD missing from .env`, **zero** docker calls reached |
| Role exists | count = 1 |
| Database exists + owner | `keycloak owner=keycloak` |
| **Password is set (not the passwordless path)** | `role_requires_password = t` — the bug did **not** bite, because the corrected command was used |
| Application tables unchanged | **18** before, **18** after |
| Idempotent — role branch | `IF NOT EXISTS` no-ops (role present) |
| Idempotent — database branch | `SELECT 1 … \| grep -q 1` succeeds, so `createdb` is skipped |

**Why the password-hash check is a boolean.** The direct query was blocked twice
by the harness classifier as credential material; the reviewer did not work
around it. `rolpassword IS NOT NULL AND <> ''` answers the question that matters
(a passwordless role) while revealing nothing about the value.

**Scope**: `DEVELOPER_QUICK_START.md` (uncommitted, the fix above). The database
change is the operator's, applied by them to their own Postgres.

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
  `"credentials": [ { "type": "password", "value": "${DEV_WBA_ADMIN_PASSWORD}" } ]`:
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
set -euo pipefail

# Render the realm template, then start Keycloak.
# Pure bash substitution, not envsubst (absent from this image) and not sed
# (mangles a `&` in a password).
: "${APP_PUBLIC_BASE_URL:?APP_PUBLIC_BASE_URL must be set (e.g. https://wba.example.com)}"
: "${KEYCLOAK_CLIENT_SECRET:?KEYCLOAK_CLIENT_SECRET must be set}"
: "${KEYCLOAK_SERVICE_CLIENT_SECRET:?KEYCLOAK_SERVICE_CLIENT_SECRET must be set}"
: "${DEV_WBA_ADMIN_PASSWORD:?DEV_WBA_ADMIN_PASSWORD must be set}"
: "${DEV_WBA_USER_PASSWORD:?DEV_WBA_USER_PASSWORD must be set}"

mkdir -p /opt/keycloak/data/import
rm -f /opt/keycloak/data/import/*.json

rendered=$(<"/opt/keycloak/realm-wba.json.template")
for name in APP_PUBLIC_BASE_URL KEYCLOAK_CLIENT_SECRET \
            KEYCLOAK_SERVICE_CLIENT_SECRET DEV_WBA_ADMIN_PASSWORD DEV_WBA_USER_PASSWORD; do
  rendered=${rendered//"\${$name}"/"${!name}"}
done

# A surviving placeholder means a name above is misspelled; importing it would
# set a client secret to the literal string.
case "$rendered" in
  *'${'*) echo "FATAL: unsubstituted placeholder remains in realm template" >&2; exit 1 ;;
esac
printf '%s\n' "$rendered" > /opt/keycloak/data/import/realm-wba.json

exec /opt/keycloak/bin/kc.sh start-dev --import-realm --http-relative-path=/auth
```

`chmod +x deploy/keycloak/entrypoint.sh`.

The template contains exactly five `${...}` placeholders, all intended for
substitution — enumerated and confirmed. Do **not** add a Keycloak-native
`${...}` expression to the template without extending the loop, or the guard
above will abort the container (which is the intended failure, not a bug).

Document the five variables `entrypoint.sh` requires — `DEV_WBA_ADMIN_PASSWORD`,
`DEV_WBA_USER_PASSWORD`, `KEYCLOAK_CLIENT_SECRET`,
`KEYCLOAK_SERVICE_CLIENT_SECRET`, `KEYCLOAK_DB_PASSWORD` — in the **existing**
`.env.example` Keycloak block (Step 6), not in a separate file. Each stays a
`FIXME` placeholder with a one-line note. **No real values, and no example
values either** — `admin`/`user`/`dev-web-secret` must not appear, since an
example is what people copy. A duplicate `deploy/keycloak/keycloak.env.example`
was tried and deleted: it drifted within hours of being written.

**Verify**: `python -c "import json,re,os,sys; t=open('deploy/keycloak/realm-wba.json.template').read(); r=re.sub(r'\\$\\{[A-Z_]+\\}','x',t); json.loads(r); print('valid')"` → `valid`
**Verify**: `test -x deploy/keycloak/entrypoint.sh && echo executable` → `executable`
**Verify**: `grep -c 'wba-admin\|wba-user\|wba-service' deploy/keycloak/realm-wba.json.template` → at least `3`
**Verify** (no hardcoded public origin): `grep -c 'localhost' deploy/keycloak/realm-wba.json.template` → **`0`**. The template must contain `${APP_PUBLIC_BASE_URL}` for both `redirectUris` and `webOrigins`. A literal here is a production-blocking defect, not a style issue.
**Verify** (renders correctly for a non-localhost host). Use the same pure-bash
renderer the entrypoint uses, so this tests the shipped mechanism, not a
different one:
```bash
bash -c 'export APP_PUBLIC_BASE_URL=https://wba.example.com KEYCLOAK_CLIENT_SECRET=x \
  KEYCLOAK_SERVICE_CLIENT_SECRET=x DEV_WBA_ADMIN_PASSWORD=x DEV_WBA_USER_PASSWORD=x
  out=$(<deploy/keycloak/realm-wba.json.template)
  for n in APP_PUBLIC_BASE_URL KEYCLOAK_CLIENT_SECRET KEYCLOAK_SERVICE_CLIENT_SECRET DEV_WBA_ADMIN_PASSWORD DEV_WBA_USER_PASSWORD; do
    out=${out//"\${$n}"/"${!n}"}
  done
  printf "%s" "$out" | grep -o "https://wba.example.com[^\"]*" | sort -u'
```
→ prints `https://wba.example.com` and `https://wba.example.com/api/v1/auth/callback` — proving the template is host-agnostic.
**Verify** (renderer survives meta-characters — the `sed` trap):
```bash
bash -c 'export APP_PUBLIC_BASE_URL=https://h.example KEYCLOAK_CLIENT_SECRET="a&b" \
  KEYCLOAK_SERVICE_CLIENT_SECRET="c|d" DEV_WBA_ADMIN_PASSWORD="e/f=g" DEV_WBA_USER_PASSWORD="h+i"
  out=$(<deploy/keycloak/realm-wba.json.template)
  for n in APP_PUBLIC_BASE_URL KEYCLOAK_CLIENT_SECRET KEYCLOAK_SERVICE_CLIENT_SECRET DEV_WBA_ADMIN_PASSWORD DEV_WBA_USER_PASSWORD; do
    out=${out//"\${$n}"/"${!n}"}
  done
  printf "%s" "$out" | grep -o "\"secret\": \"[^\"]*\""'
```
→ prints both secrets **intact** (`"a&b"`, `"c|d"`). A `sed`-based renderer
returns `"a__PLACEHOLDER__b"` here.
**Verify** (`envsubst` is genuinely absent, so this is not a gratuitous rewrite):
`docker run --rm --entrypoint /bin/sh quay.io/keycloak/keycloak:26.4 -c 'command -v envsubst || echo ABSENT'` → `ABSENT`

> ### 🚦 MANUAL GATE 4 — realm content
>
> Operator reads the template and confirms: the three roles exist; `wba-web` is
> confidential with PKCE S256 and the **templated** `redirectUris` (no literal
> host); `wba-internal` has service accounts enabled; the two dev users carry
> the right roles; no real password is committed.
> Wait for `PASS`.

#### Gate 4 record — 2026-10-30 — ✅ PASS (operator, 2026-10-30) — blocker resolved

The three files were created correctly and the realm was **proven to import and
work end-to-end**. But the renderer mechanism fails: **`envsubst` does not exist
in `quay.io/keycloak/keycloak:26.4`.** This must be resolved before Step 5, or
the `keycloak` container will crash on start.

**THE BLOCKER (confirmed by the reviewer).** The image ships no gettext at all:

```
$ docker run --rm --entrypoint /bin/sh quay.io/keycloak/keycloak:26.4 -c 'command -v envsubst'
NOT FOUND
```

Available in the image: `bash`, `sh`, `sed`, `java`. **Absent:** `envsubst`,
`awk`, `python3`, `perl`. The plan's STOP condition fired exactly as written, and
the executor correctly did not substitute a different mechanism unilaterally.

**Fix APPLIED to `deploy/keycloak/entrypoint.sh`** (uncommitted), and to Step 4's
instructions so the plan and the file agree. `bash` is present in the image, and
pure bash is *safer* than `sed`:

| Renderer | `a/b+c=d` | `a&b` | `` `id` `` |
|---|---|---|---|
| `envsubst` | ok | ok | ok |
| `sed "s\|K\|V\|"` | ok | **BROKEN** → `a__K__b` | ok |
| **pure bash `${s//K/V}`** | ok | ok | ok |

`sed` corrupts any value containing `&` (a legal base64 character is not, but a
future operator-chosen password could contain it). Pure bash substitutes
literally and was tested inside the real image with adversarial values
(`/+abc=def`, `x&y\|z`, `p/w=d+f`) — output byte-identical to `envsubst` apart
from a trailing newline. Verified with:

```bash
out=$(<"/opt/keycloak/realm-wba.json.template")
for n in APP_PUBLIC_BASE_URL KEYCLOAK_CLIENT_SECRET KEYCLOAK_SERVICE_CLIENT_SECRET \
         DEV_WBA_ADMIN_PASSWORD DEV_WBA_USER_PASSWORD; do
  out=${out//"\${$n}"/"${!n}"}
done
printf '%s\n' "$out" > /opt/keycloak/data/import/realm-wba.json
```

**Templates contain exactly five `${...}` placeholders**, all intended for
substitution — confirmed by enumeration, so a positional loop cannot accidentally
touch a Keycloak-native `${...}`.

**Verification of the realm itself (reviewer, in a throwaway container).** The
rendered realm was imported into a temporary Keycloak 26.4 on loopback :8899 with
an H2 store; the operating stack was never touched and the probe was removed.

| Check | Observed |
|---|---|
| Template valid JSON after substitution | `valid` |
| Rendered output valid JSON | `valid`, `realm= wba` |
| Import succeeds | `Realm 'wba' imported` / `Import finished successfully` |
| Exactly the three roles exist | `wba-admin`, `wba-service`, `wba-user` (plus Keycloak's built-ins) |
| **Service account carries `wba-service`** | `users/…/role-mappings/realm` → `['wba-service']` |
| **Client-credentials grant works** | HTTP 200, `expires_in=900`, `realm_access.roles=['wba-service']` |
| `dev-admin` password login | OK, `expires_in=900`, roles `['wba-admin','wba-user']` |
| `dev-user` password login | OK, `expires_in=900`, roles `['wba-user']` |
| `wba-web` refuses direct grants | `unauthorized_client: Client not allowed for direct access grants` — correct, it is BFF-only |
| No `localhost` literal | `0` |
| No credential literal | `0` |
| `entrypoint.sh` executable | yes |
| **Renderer fixed: no live `envsubst` call** | `grep -n '^[^#]*envsubst'` → no matches (the word survives only in the comment explaining its absence) |
| **Render test, adversarial values, in the real image** | JSON parses (`realm= wba`); secrets intact as `a&b/base64+val=` and `c\|d&e` — no mangling, proving bash beats `sed` here |
| **Placeholder guard aborts** | with the variables unset: exits 1 on the first `:?` guard, before rendering |

The plan has **no** `grep -c envsubst` gate, so the comment text naming
`envsubst` is harmless. A future gate must match non-comment lines
(`grep -n '^[^#]*envsubst'`), not the bare word.

The login tests required a temporary direct-grant client (`tmp-pwtest`), created
**only inside the throwaway probe** and destroyed with it — `wba-internal`
correctly refuses password grants, so it could not be used for this.

**Justified deviation from the plan, accepted.** The executor added
`firstName` / `lastName` to both dev users. The plan's user spec omitted them.
Without them Keycloak 26.4 rejects the password grant with HTTP 400
`invalid_grant` / "Account is not fully set up", so Gate 5's dev-login check
could not have passed. The reviewer confirmed both logins succeed **with** these
fields present. This is a documented, meritorious adaptation.

**Service-account mapping shape — the plan's flagged uncertainty, resolved.**
The full-export form is correct: a third `users[]` entry with
`"username": "service-account-wba-internal"`, `"serviceAccountClientId":
"wba-internal"`, `"realmRoles": ["wba-service"]`. Proven by reading the mapping
back from the imported realm **and** by a real client-credentials token.

**Scope**: three new files under `deploy/keycloak/` (untracked). Nothing
committed. No other file touched.

---

### Step 5: Add the `keycloak` compose service and enable the nginx `/auth` block

Add this service to `docker-compose.yml`, after `postgres` and before `api`:

```yaml
  keycloak:
    image: quay.io/keycloak/keycloak:26.8
    container_name: wba-ai-keycloak
    restart: unless-stopped
    command: ["start-dev", "--import-realm"]
    entrypoint: ["/opt/keycloak/entrypoint.sh"]
    environment:
      KC_DB: postgres
      KC_DB_URL: jdbc:postgresql://postgres:5432/keycloak
      KC_DB_USERNAME: keycloak
      KC_DB_PASSWORD: ${KEYCLOAK_DB_PASSWORD}
      KC_HOSTNAME: ${EXTERNAL_BASE_URL:-https://localhost}/auth
      KC_HOSTNAME_ADMIN: http://127.0.0.1:8080/auth
      APP_PUBLIC_BASE_URL: ${EXTERNAL_BASE_URL:-https://localhost}
      KC_PROXY_HEADERS: xforwarded
      KC_HTTP_ENABLED: "true"
      KC_HTTP_RELATIVE_PATH: /auth
      KC_BOOTSTRAP_ADMIN_USERNAME: admin
      KC_BOOTSTRAP_ADMIN_PASSWORD: ${DEV_KEYCLOAK_ADMIN_PASSWORD}
      DEV_WBA_ADMIN_PASSWORD: ${DEV_WBA_ADMIN_PASSWORD}
      DEV_WBA_USER_PASSWORD: ${DEV_WBA_USER_PASSWORD}
      KEYCLOAK_CLIENT_SECRET: ${KEYCLOAK_CLIENT_SECRET}
      KEYCLOAK_SERVICE_CLIENT_SECRET: ${KEYCLOAK_SERVICE_CLIENT_SECRET}
    volumes:
      - ./deploy/keycloak/realm-wba.json.template:/opt/keycloak/realm-wba.json.template:ro
      - ./deploy/keycloak/entrypoint.sh:/opt/keycloak/entrypoint.sh:ro
    # Admin console not published. See ADMIN_GUIDE.md to enable on 127.0.0.1:8080.
    networks:
      - wba-ai-network
    healthcheck:
      test: ["CMD-SHELL", "exec 3<>/dev/tcp/127.0.0.1/8080 && printf 'GET /auth/realms/wba/.well-known/openid-configuration HTTP/1.0\\r\\nHost: localhost\\r\\n\\r\\n' >&3 && head -1 <&3 | grep -q '200'"]
      interval: 10s
      timeout: 5s
      retries: 30
      start_period: 60s
    depends_on:
      postgres:
        condition: service_healthy
```

Notes you must understand before editing:

- ~~`--http-relative-path=/auth` is passed both as a `command` flag and as
  `KC_HTTP_RELATIVE_PATH`.~~ **Superseded 2026-10-31.** The flag was never
  actually in the `command` list, so there was nothing to deduplicate and Keycloak
  emitted no warning. Only `KC_HTTP_RELATIVE_PATH` is set. Do not add the flag.
- ~~`KC_HOSTNAME_STRICT=false` is dev-only…~~ **Superseded 2026-10-31 —
  replaced by `KC_HOSTNAME_ADMIN`.** The original text is kept here only so the
  old reasoning is traceable: it was wrong on two counts. `KC_HOSTNAME_STRICT` is
  a **documented no-op on 26.x whenever `KC_HOSTNAME` is set** (the startup log
  says so), and the "second nginx listener" fallback it names turned out to be
  unnecessary — `KC_HOSTNAME_ADMIN` solves it on the same loopback port. See the
  service block's `KC_HOSTNAME_ADMIN` comment.
- The `healthcheck` uses bash `/dev/tcp` because the image may not ship `curl`.
- **The healthcheck MUST send a `Host:` header, and MUST use `printf`, not
  `echo -e`.** Found the hard way on 2026-10-31 (see the Gate 5 record): the
  original `echo -e '…HTTP/1.0\r\n\r\n'` produced a request with no `Host`, and
  Keycloak's `RealmsResource.checkSsl` → `UriInfoImpl.getBaseUri` throws
  `java.net.URISyntaxException: Expected authority at index 7: http://` →
  **HTTP 500 on every probe**, so the container sat `unhealthy` forever while
  Keycloak itself was perfectly healthy. `printf` with an explicit
  `Host: localhost` returns `200`. Verified verbatim under `/bin/sh -c` (the
  shell `CMD-SHELL` uses; the image's `/bin/sh` has `printf`) on both 26.4.7 and
  26.8.1.
- **There is no `ports:` block, and that is the decision — do not add one.**
  The console port is off by default; `ADMIN_GUIDE.md` documents the toggle.
  Tempting alternatives that were **tested and rejected**: a `${ADMIN_BIND}`
  env var does **not** work (an empty value falls back to the default, so
  `ADMIN_BIND= docker compose config` still publishes the port), and a compose
  overlay with `ports: []` does **not** either (compose merges lists). Only
  `!reset []` removes it, which needs a second compose file the operator
  explicitly rejected.
- **`KC_HOSTNAME_ADMIN` is what makes the console work** — not
  `KC_HOSTNAME_STRICT`. Do not "simplify" by removing it: without it the console
  redirects to `https://localhost/auth/admin/...`, which nginx 404s. And do not
  set `KC_HOSTNAME_STRICT=false` (as the original plan did) — on 26.x it is a
  documented no-op whenever `KC_HOSTNAME` is set.

Replace the reserved nginx block with **only the realm subtree**:

```nginx
        # ── Keycloak OIDC realm endpoints (Plan C) ───────────────────────
        # Only /auth/realms/* and /auth/resources/* are proxied. The admin
        # console and admin REST (/auth/admin*) are deliberately NOT routed:
        # they are the highest-privilege surface in the stack, and nothing in
        # the app needs them from a browser. The operator reaches the console
        # on the loopback port 127.0.0.1:8080 published by the keycloak service.
        location /auth/realms/ {
            proxy_pass http://keycloak:8080;
            proxy_set_header Host              $host;
            proxy_set_header X-Real-IP         $remote_addr;
            proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;
            proxy_set_header X-Forwarded-Host  $host;
        }

        # Keycloak theme assets (login page, account console). Their CSS/JS
        # live here, not under /auth/realms/. Longest-prefix match keeps this
        # ahead of the /auth catch-all below.
        location /auth/resources/ {
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

**`/auth/resources/` is not optional — this plan originally omitted it and that
was a defect.** Found 2026-10-31: the account console and the **login page** both
load their HTML from `/auth/realms/...` but fetch every CSS/JS/image from
`/auth/resources/...`. With only `/auth/realms/` proxied, those 404 through nginx
(they return `200` direct from Keycloak), so the pages render a bare shell —
"Loading the Account Console" forever, and an unstyled login form. That would
have broken Plan 056's login flow. Verified before/after with:

```bash
curl -s https://localhost/auth/realms/wba/account | grep -oE '(src|href)="/[^"]+"' \
  | sed 's/.*="//; s/"//' \
  | while read -r p; do printf '%s -> %s\n' "$p" "$(curl -s -o /dev/null -w '%{http_code}' "https://localhost$p")"; done
```

Every asset must be `200`. `/auth/js/`, `/auth/welcome` and `/auth/robots.txt` do
**not** exist in Keycloak 26 (they 404 at Keycloak itself), so do not proxy them
"for completeness".

**Verify**: `docker compose config -q` → exit 0
**Verify**: `docker run --rm --network work-behavior-analytics-ai_wba-ai-network -v "$PWD/deploy/nginx/nginx.conf:/etc/nginx/nginx.conf:ro" -v "$PWD/deploy/certs:/etc/nginx/certs:ro" nginx:1.30-alpine nginx -t` → `syntax is ok` / `test is successful`
**Verify**: `grep -c 'location /auth' deploy/nginx/nginx.conf` → `2` (the prefix location and the catch-all)
**Verify**: `docker compose up -d --force-recreate nginx keycloak` then `docker compose ps keycloak` → `healthy`

**You MUST `--force-recreate nginx` as well, and here is why.** A running nginx
mounts `deploy/nginx/nginx.conf` read-only. Editing the file on the host replaces
its inode, but the **container keeps the old inode open and serves the old
config** — see the inode-staleness trap recorded in the Gate 5 record. A plain
`docker compose up -d nginx` will silently do nothing. Until nginx is recreated,
`https://localhost/auth/realms/wba/...` returns **404** (the old reserved block
is still commented out) and every `https://localhost/...` check below is testing
a stale proxy. Run:

```bash
docker compose up -d --force-recreate nginx
docker exec wba-ai-nginx grep -c 'location /auth' /etc/nginx/nginx.conf   # → 2
docker exec wba-ai-nginx grep -c 'RESERVED' /etc/nginx/nginx.conf         # → 0
```

Only when that in-container grep shows `2` and `0` is the new upstream in effect.

**Do NOT name `postgres` in this command.** Step 5 does not change the postgres
service, and the first attempt's `docker compose up -d postgres keycloak`
unnecessarily recreated the Postgres container. Only `nginx` (stale config) and
`keycloak` (the new service) need recreating.

**ORDERING DEPENDENCY — the operator must run `./scripts/setup.sh` before the
service is recreated.** The compose file names three variables that are not yet
in `.env` under their final names: `DEV_KEYCLOAK_ADMIN_PASSWORD` (new) and the two
renamed `DEV_WBA_*` keys. Each has no default, so compose would substitute an
empty string and Keycloak would start with blank passwords. The order is:

1. **Operator runs `./scripts/setup.sh`** — generates
   `DEV_KEYCLOAK_ADMIN_PASSWORD` (genuinely new) plus fresh values for the two
   renamed seed keys, and preserves the rest. No migration step is needed: this
   is a greenfield project, so the old key names simply cease to exist.
2. Then `docker compose up -d --force-recreate nginx keycloak`.

An executor must NOT run `setup.sh` — it writes credentials into `.env`, which is
blocked by the harness classifier as `[Credential Materialization]` and is the
operator's step, exactly as in Step 2. If the executor reaches step 2 and any of
the three variables is still absent from `.env`, **STOP and report** — do not
invent a value and do not add a `:-default` to route around it.

**Verify** (the new image actually landed): `docker inspect wba-ai-keycloak --format '{{.Config.Image}}'` → `quay.io/keycloak/keycloak:26.8` and
`docker exec wba-ai-keycloak /opt/keycloak/bin/kc.sh --version` → `Keycloak 26.8.1`
**Verify** (no console port published): `docker compose config 2>/dev/null | grep -c 'target: 8080'` → `0`
**Verify** (the console responds on loopback via KC_HOSTNAME_ADMIN, once the port is enabled):
`docker compose exec -T keycloak bash -c "curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8080/auth/admin/master/console/"` → `200`.
Note this works **from inside the container regardless of the port mapping** — the
`ports:` block only affects the host. If `curl` is absent, use the `/dev/tcp` form
with a `Host` header.

### Step 5b: Document the console toggle in `ADMIN_GUIDE.md`

Create `ADMIN_GUIDE.md` at the repo root (operator decision 4: a doc, not a second
compose file). Match the tone and heading style of `DEVELOPER_QUICK_START.md`.
It must cover, and only cover:

1. **What the Keycloak admin console is** and that it is **off by default** —
   the `keycloak` service publishes no port, deliberately.
2. **How to enable it** — the exact two lines to add to the `keycloak` service's
   comment block in `docker-compose.yml`, then `docker compose up -d keycloak`,
   then browse to `http://127.0.0.1:8080/auth/admin/`. State the `127.0.0.1`
   binding is required and that `"8080:8080"` must never be used.
3. **How to disable it again** — remove those lines and `docker compose up -d
   keycloak`.
4. **Signing in** — username `admin`; the password is
   `DEV_KEYCLOAK_ADMIN_PASSWORD` in `.env`. **Do not print a value.** (An
   earlier draft of this step said `KC_BOOTSTRAP_ADMIN_PASSWORD` — that is the
   name *inside the container*, which compose fills from
   `DEV_KEYCLOAK_ADMIN_PASSWORD`. `.env` holds the latter.)
5. **The bootstrap caveat, prominently.** The bootstrap admin is created **only
   on the first boot against an empty Keycloak database**. This repository's
   Keycloak DB was initialised on 2026-10-31, so the bootstrap will **not** run
   again here. If the console cannot be logged into, the recovery is:

   ```bash
   docker compose exec keycloak /opt/keycloak/bin/kc.sh bootstrap-admin user \
     --username admin --password:env KC_BOOTSTRAP_ADMIN_PASSWORD --no-prompt
   ```

   Verified available on 26.8.1 (`kc.sh bootstrap-admin user` is a real
   subcommand). Never write a literal password into the guide.
6. **A note that the console is never reachable through nginx** — only
   `/auth/realms/*` is proxied and `/auth/admin*` is refused with 404.

**Verify**: `test -f ADMIN_GUIDE.md && echo exists` → `exists`
**Verify** (no credential literal): `grep -cE '(PASSWORD|SECRET)[^=]*[:=] *["'"'"']?[A-Za-z0-9]' ADMIN_GUIDE.md` → `0`
**Verify** (the toggle is documented): `grep -c '127.0.0.1:8080:8080' ADMIN_GUIDE.md` → at least `1`
**Verify** (the recovery is documented): `grep -c 'bootstrap-admin' ADMIN_GUIDE.md` → at least `1`

> ### 🚦 MANUAL GATE 5 — stack up
>
> Operator verifies in a browser:
> 1. Add the two `ports:` lines per `ADMIN_GUIDE.md`, `docker compose up -d keycloak`,
>    and `http://127.0.0.1:8080/auth/admin/` **loads the console login page**.
> 2. Signing in as `admin` (password = `DEV_KEYCLOAK_ADMIN_PASSWORD` in `.env`)
>    shows realm `wba`, the three roles, and both clients.
> 3. `https://localhost/auth/admin/` returns **404** — the admin surface is not
>    proxied.
> 4. Signing in as `dev-admin` at `https://localhost/auth/realms/wba/account`
>    works, and the token shown there lists `wba-admin`.
> 5. Then **remove the port lines again** and `docker compose up -d keycloak`,
>    confirming `docker compose config | grep -c 'target: 8080'` → `0`.
> Wait for `PASS`.

#### Gate 5 record — 2026-10-31 — ✅ PASS (operator validated) — originally ⛔ STOPPED

**Final outcome: all checks pass.** The operator ran the full runbook (`.env`
populated by `setup.sh`, keycloak DB dropped and recreated, `nginx` + `keycloak`
force-recreated) and every check passed. One apparent failure — `dev-admin`
login — was **operator error, not a defect**: it was attempted at the *admin*
console (`/auth/admin/`), which authenticates against the **`master`** realm,
where `dev-admin` does not exist. The correct URL, per Gate 5 check 4, is the
*account* console at `/auth/realms/wba/account`. Verified directly against the
live stack (password expanded from the container's own env; no value printed):

| Test | Result |
|---|---|
| `dev-admin` + `DEV_WBA_ADMIN_PASSWORD` → realm `wba` | **token issued** ✅ |
| `dev-user` + `DEV_WBA_USER_PASSWORD` → realm `wba` | **token issued** ✅ |
| `dev-admin` → realm `master` (the admin console's realm) | `invalid_grant` — correct, not present there |
| Realm membership, all users | `master`: `admin` only. `wba`: `dev-admin`, `dev-user`, `service-account-wba-internal` |
| `dev-admin` required actions / enabled / verified | none / `true` / `true` — nothing blocking |

`ADMIN_GUIDE.md` now carries an explicit callout so this trap does not recur.

**KNOWN LIMITATION, unresolved — the account console's data calls return `401`.**
Found 2026-10-31 while validating Gate 5, and deliberately **not** blocking the
gate. Signing in succeeds and the SPA renders, but its API calls fail:

```
GET /auth/realms/wba/account/supportedLocales           401  {"error":"HTTP 401 Unauthorized"}
GET /auth/realms/wba/account/?userProfileMetadata=true  401
```

Diagnosis (all reproduced against Keycloak 26.8.1, both through nginx and
against `keycloak:8080` directly from inside the container, so nginx is not
involved):

- The request carries a valid `Authorization: Bearer` header; the token decodes
  with the correct `iss` and is not expired.
- The differentiator is **`Content-Type: application/json` on the GET**, which
  routes it to the account REST API instead of the HTML shell. Without that
  header the same URL returns `200` — but that is the *public SPA shell*, not
  data, so a `200` there proves nothing. **This misled the reviewer for several
  exchanges; do not repeat the mistake.**
- The token has **no `aud` claim**, and realm `wba` has **no audience mapper**.
  Verified the Keycloak-created `master` realm has none either, so this is **not**
  caused by importing `realm-wba.json.template`.
- **Root cause not established.** Candidate fix, unproven: an
  `oidc-audience-mapper` (included client audience `account`) on the
  `account-console` client in the realm template.

**Why this does not block Gate 5:** nothing in the repo calls
`/realms/wba/account`. The application's login is Plan 056's BFF flow. The
account console is a Keycloak developer UI used here only to eyeball a session;
that is now done via the admin console and by decoding a token instead.
Recorded in `ADMIN_GUIDE.md` as a known limitation.

**A second trap, found the same way: the account console must NOT be opened on
the loopback port.** This plan's Gate 5 check 4 originally said
`http://127.0.0.1:8080/auth/realms/wba/account`; that URL loads, then fails in
the browser with *"Timeout when waiting for 3rd party check iframe message"*.
The reason is the `KC_HOSTNAME` / `KC_HOSTNAME_ADMIN` split: the **account**
console is served on the public origin (`KC_HOSTNAME` = `https://localhost/auth`)
and builds its 3rd-party-cookie iframe from that origin, while the **admin**
console is the only thing on the loopback origin (`KC_HOSTNAME_ADMIN`). Opening
the account console on the loopback port puts the page and its iframe on
different origins, so the `postMessage` handshake never completes. Verified: the
account console HTML references `https://localhost/auth` four times **however it
is fetched**. Corrected to `https://localhost/auth/realms/wba/account`, which
returns `200` (`<title>Account Management</title>`) and needs **no published
port** — nginx proxies `/auth/realms/*`. All occurrences of the old URL in this
plan were replaced. **The loopback port is for the admin console only.**

**A third defect, found the same way: nginx did not proxy `/auth/resources/`.**
The plan's nginx block proxied only `/auth/realms/` and 404'd everything else
under `/auth`. Keycloak serves **all theme static assets** — the login page's and
the account console's CSS/JS/images — from `/auth/resources/`, so both pages
loaded their HTML and then never initialised: the account console showed
*"Loading the Account Console"* forever, and the login form rendered unstyled.
The assets return `200` direct from Keycloak, confirming nginx was the problem.

Blast radius was larger than the symptom: **the login page was broken too**, and
plans 056/057 depend on it. Caught here rather than three steps later.

Fixed by adding a `location /auth/resources/` block (12 lines) after the
`/auth/realms/` block in `deploy/nginx/nginx.conf`; longest-prefix matching keeps
it ahead of the `location /auth { return 404; }` catch-all, so `/auth/admin*`
stays refused. Verified after `--force-recreate nginx` (the stale-inode trap
again — a plain `up -d` would not have picked it up):

| Check | Before | After |
|---|---|---|
| Account console assets (`.js`, `.css`, `.svg`) | `404` | **`200`** |
| Login page assets (patternfly, theme css/js) | `404` | **`200`** |
| `/auth/admin/` | `404` | `404` ✅ still refused |
| `/auth/admin/realms/wba/users` | `404` | `404` ✅ still refused |
| `issuer` | correct | correct, unchanged |
| `/api/health` | `200` | `200` — app still unauthenticated |

`ADMIN_GUIDE.md`, this plan's Step 5 and Step 7 text, and plan 056 were all
corrected; none of them had said `/auth/resources/` must be proxied.

**The two-origin rule, stated once and for all** (this is the model that makes
the whole design work):

| Surface | Origin | URL | Port needed |
|---|---|---|---|
| Admin console | `KC_HOSTNAME_ADMIN` | `http://127.0.0.1:8080/auth/admin/` | yes |
| Account console, login, token, JWKS | `KC_HOSTNAME` | `https://localhost/auth/...` | no (nginx) |
| `/auth/admin` on the public origin | — | `https://localhost/auth/admin/` → `404` | n/a (refused) |

**Earlier in the same run (superseded): STOPPED (executor)** — the three defects
below, all since fixed and re-verified.

Executor dispatched in the **live working tree** on `feature/plan-c-keycloak`
(no worktree — the operator's standing instruction), Step 5 only, no commit.
Base was `64bc5f2a`, which already contains Steps 1–4 (the earlier "Step 4 files
untracked" note in this plan's progress block was stale — `deploy/keycloak/` is
tracked at `64bc5f2a`).

**Both in-scope edits were made and are verbatim correct.** `git diff --stat` →
`docker-compose.yml` **+60 / −0** (the `keycloak` service, exactly as specified,
between `postgres` and `api`) and `deploy/nginx/nginx.conf` **+20 / −14** (the
RESERVED block replaced by the `/auth/realms/` + catch-all pair). No file outside
Step 5's scope was touched; the tree had been clean beforehand.

**STOP condition fired: "the `keycloak` service fails to become healthy."** The
container reports `unhealthy` with `FailingStreak` climbing past 60. The
executor correctly did not improvise a fix.

**Root cause — the plan's own healthcheck YAML was defective.** Its `echo -e
'…HTTP/1.0\r\n\r\n'` sent a request with **no `Host` header**. Keycloak's
`RealmsResource.checkSsl` → `UriInfoImpl.getBaseUri` → `LocationUtil.getUri`
parses the request base URI and throws
`java.net.URISyntaxException: Expected authority at index 7: http://` →
**HTTP 500 on every probe**, so `grep -q '200'` always failed. Reproduced
independently by the reviewer, inside the container:

| Probe (via `/dev/tcp` on 127.0.0.1:8080) | Observed |
|---|---|
| No `Host` — exactly the plan's original request | `HTTP/1.0 500 Internal Server Error` |
| With `Host: localhost` | `HTTP/1.0 200 OK` |
| Proposed fix, run verbatim under `/bin/sh -c` | `PROBE_OK` |

`Keycloak 26.4.7` is otherwise healthy — the only error in its log is this one
trace, once per 10s probe (timestamps line up exactly with the healthchecks).

**Second, independent defect found by the executor: the running nginx serves a
stale config.** `wba-ai-nginx` mounts `deploy/nginx/nginx.conf` read-only; the
host edit changed the inode (host `176885`/6232 bytes vs container `82362`/5912
bytes), so the container kept the **old** file — in-container
`grep -c 'location /auth'` = **1** and `RESERVED` is still present at line 122,
while the host file has **2**. Consequence: **every `https://localhost/auth/...`
check in this plan passes or fails for the wrong reason until nginx is
recreated**, and Gate 6's issuer comparison is meaningless against it. A plain
`docker compose up -d nginx` is not enough — it must be `--force-recreate`.
Step 5's instructions have been amended above to include this.

**What is already proven about Keycloak itself** (reviewer-verified, read-only):

| Check | Observed |
|---|---|
| Realm import | `Realm 'wba' imported` / `Import finished successfully` |
| Started | `Keycloak 26.4.7 on JVM (powered by Quarkus 3.27.1)`, listening on `http://0.0.0.0:8080` |
| No DB problem | no `connection refused` / `could not connect` in the log |
| `issuer` | `https://localhost/auth/realms/wba` — matches `KC_HOSTNAME`, exactly what Step 6 asserts |
| `https://localhost/auth/admin/` | `404` (deliberate; see the third defect below) |
| Loopback admin | `302 → https://localhost/auth/admin/master/console/` |
| No duplicate relative-path warning | none emitted; the step's prose warning about a duplicate flag does not apply (the YAML never put the flag in `command`) |
| Stack otherwise undisturbed | api/ui/neo4j/rabbitmq/elasticsearch/github-mcp/producers/consumer all Up |

**Third defect: `KC_HOSTNAME_STRICT="false"` is a no-op on this image**, so the
browser admin console is unreachable by design of the plan's own nginx block.
The log states it: `HostnameV2ProviderFactory: If hostname is specified,
hostname-strict is effectively ignored`. The plan predicted `200 or 303` for the
loopback console; the actual `302 → https://localhost/...` (which nginx 404s) is
the correct behaviour of the wrong assumption. MANUAL GATE 5 above now records
this and lays out the three operator options.

**All decisions RESOLVED on 2026-10-31** — see the "Five decisions" table in the
progress block. The plan's Step 5 has been rewritten to carry them, and the three
mechanisms were re-verified on the **26.8.1** image in throwaway containers
(no credentials, H2 store, all removed afterwards; the operator's stack was not
touched):

| Mechanism | Verified on 26.8.1 |
|---|---|
| `KC_HOSTNAME_ADMIN` console routing | `/auth/admin/` → `302` → `/auth/admin/master/console/` → **`200`**, `<title>Keycloak Administration Console</title>` |
| Public issuer unaffected | `issuer` = `https://localhost/auth/realms/master` while `KC_HOSTNAME_ADMIN` points at loopback |
| Bootstrap admin usable | password grant as the bootstrap user → **`200`** (vs `401` with no bootstrap vars) |
| Healthcheck fix | `printf` + `Host: localhost` → **`PROBE_OK`** |

**Version evidence (decision 2).** `quay.io` registry tag listing for
`keycloak/keycloak` shows `26.4.0 … 26.4.7` then `26.5.* … 26.7.*` then
**`26.8.0`, `26.8.1`** — `26.8.1` is the highest release tag, and
`keycloak.org/downloads` confirms it. The pin `26.4` had silently floated to
**26.4.7**, i.e. 12 minors behind. `26.4.3` does not exist, so minor tags do not
map cleanly onto patch sequences and the drift is real. The image was bumped to
`26.8` (operator chose a minor tag over a patch pin, matching the repo's nginx
convention).

**Bootstrap-admin caveat — and the operator's resolution (decision 7).** This
repository's Keycloak DB was **already initialised** on 2026-10-31
(`master` and `wba` realms exist in the `keycloak` database, 3 users). The
`KC_BOOTSTRAP_ADMIN_*` bootstrap therefore **will not run** on this volume — it
only fires against an empty Keycloak DB.

**Resolution: drop and recreate the `keycloak` database.** Verified safe because
that database is **100% reproducible from the templates in this repo**: it holds
only `master` (Keycloak's built-in realm) and `wba` (imported from
`deploy/keycloak/realm-wba.json.template`), its 3 users are exactly the three
template entries (`dev-admin`, `dev-user`, `service-account-wba-internal`), and
all 89 tables are Keycloak's own schema. Nothing hand-made lives there, so
nothing is lost. The operator runs:

```bash
docker compose stop keycloak
docker compose exec -T postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
  -c 'DROP DATABASE keycloak;'
docker compose exec -T postgres createdb -U "$POSTGRES_USER" -O keycloak keycloak
docker compose up -d keycloak   # bootstrap admin seeds; realm re-imports
```

This touches **only the `keycloak` database**. The application database
(`POSTGRES_DB` in `pgdata`) is untouched — different database, same server.

**Why not the `kc.sh` recovery?** `docker compose exec keycloak
/opt/keycloak/bin/kc.sh bootstrap-admin user …` also works (verified present in
26.8.1) and remains documented in `ADMIN_GUIDE.md` as the recovery path for
someone whose console login is missing. But it would leave the bootstrap
variables **untested**, so a fresh clone could still be broken in a way this
environment never caught. Recreating the DB exercises the real seeded path, which
is what a fresh clone does.

**Also worth recording:** the plan's Step 5 verify command
`docker compose up -d postgres keycloak` **recreated the `postgres` container**
(the volume was preserved, postgres is `healthy`). That contradicts this run's
brief, which had fenced `postgres` off. The plan's own command was followed over
the brief; harmless here, but the plan should not name `postgres` in a step that
does not change it. Amended above to `--force-recreate postgres keycloak` only
because it is in the same command; **neither service actually needs recreating**
— `postgres` is untouched by Step 5 and `keycloak` is new.

**Scope**: ` M docker-compose.yml`, ` M deploy/nginx/nginx.conf`. Nothing
committed. Nothing untracked.

---

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
KEYCLOAK_SERVICE_CLIENT_ID=wba-internal
AUTH_COOKIE_SECURE=true
AUTH_SESSION_IDLE_MINUTES=60
AUTH_SESSION_MAX_HOURS=8

# ── Keycloak credentials — no defaults, populate before `docker compose up` ──
# Every one of these is REQUIRED. They have no fallback in docker-compose.yml
# on purpose: a committed default would put the credential in git. Generate
# each with `openssl rand -base64 24`. Never commit real values.
# Password for the `keycloak` Postgres role created by
# deploy/postgres/init-keycloak.sh (fresh volumes) or Step 3 (existing ones).
# Must match Keycloak's KC_DB_PASSWORD — both read this variable.
KEYCLOAK_DB_PASSWORD=FIXME
# Secret for the `wba-web` confidential browser client (BFF token exchange).
KEYCLOAK_CLIENT_SECRET=FIXME
# Secret for the `wba-internal` service-account client (producers/consumer).
KEYCLOAK_SERVICE_CLIENT_SECRET=FIXME
# Seed passwords for the two realm users, rendered in by entrypoint.sh.
DEV_WBA_ADMIN_PASSWORD=FIXME
DEV_WBA_USER_PASSWORD=FIXME
# Password for the Keycloak master-realm bootstrap admin (username is the
# literal `admin`). Created ONLY on the first boot against an empty Keycloak
# database; see ADMIN_GUIDE.md for the recovery command if it is missing.
DEV_KEYCLOAK_ADMIN_PASSWORD=FIXME
```

Then add `DEV_KEYCLOAK_ADMIN_PASSWORD` to the `scripts/setup.sh` generation loop,
so it joins the other secrets and is generated on first run and preserved on
re-run (the same `is_placeholder` → generate → `set_env_value` pattern). The loop
becomes six keys, not five.

Note `KEYCLOAK_ISSUER`, `KEYCLOAK_INTERNAL_URL`, `APP_PUBLIC_BASE_URL` and the
`AUTH_*` values keep real defaults — they are configuration, not credentials, and
a wrong value fails loudly via the Step 1 validator.

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
- nginx exposes **only** `/auth/realms/*` and `/auth/resources/*` (the latter is
  the theme/console static assets — without it the login page and account console
  load but never initialise); the admin console and admin REST are not proxied
  and are reached only on the loopback port.

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
| `KC_HOSTNAME_ADMIN` | `http://127.0.0.1:8080/auth` | **removed**; the console is not published at all |
| Keycloak loopback port `127.0.0.1:8080` | off in the repo; the operator enables it per `ADMIN_GUIDE.md` | **removed**; no admin surface published |
| `KC_BOOTSTRAP_ADMIN_USERNAME` / `_PASSWORD` | literal `admin` / `${DEV_KEYCLOAK_ADMIN_PASSWORD}` | **removed**; bind to an external IdP or an operator-managed admin, never a seeded one |
| `deploy/certs/*` (mkcert) | local CA | a real certificate, or TLS terminated at a load balancer / API Gateway |
| `AUTH_COOKIE_SECURE` | `true` | `true` (never false behind HTTPS) |
| Keycloak DB password (`keycloak`) | dev default | a secret-store value (Plan E owns broader credential handling) |
| Compose vs ECS | Compose | Plan A's proxy-awareness means this is configuration, not code — see the AWS section |

Add one sentence to the table's note: *"No application code branches on host or
scheme. `nginx server_name` is the only remaining literal hostname in the
repository's deployment config, and it is the sole `listen 443` server, so it
answers any Host header; parameterise it when a second vhost is added."*

**Verify**: `grep -c "Production checklist" docs/design/authn-authz-design.md` → `1`
**Verify**: `grep -n "KC_HOSTNAME_ADMIN" docs/design/authn-authz-design.md` → present in the checklist

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
- [ ] `docker inspect wba-ai-keycloak --format '{{.Config.Image}}'` prints `quay.io/keycloak/keycloak:26.8`; `docker exec wba-ai-keycloak /opt/keycloak/bin/kc.sh --version` prints `Keycloak 26.8.1`
- [ ] `docker compose config 2>/dev/null | grep -c 'target: 8080'` prints `0` — **the console port is off by default**
- [ ] `curl -sf https://localhost/auth/realms/wba/.well-known/openid-configuration` returns a document whose `issuer` is exactly `https://localhost/auth/realms/wba` (issuer unchanged by `KC_HOSTNAME_ADMIN`)
- [ ] `curl -s -o /dev/null -w '%{http_code}' https://localhost/auth/admin/` prints `404`
- [ ] `docker compose exec -T postgres psql -U "$POSTGRES_USER" -lqt | cut -d'|' -f1 | grep -cw keycloak` prints `1`
- [ ] `test -f ADMIN_GUIDE.md && grep -c '127.0.0.1:8080:8080' ADMIN_GUIDE.md` ≥ `1`, and `grep -c 'bootstrap-admin' ADMIN_GUIDE.md` ≥ `1`
- [ ] `pytest -m unit tests -q` exits 0 with the same pass count as before this plan
- [ ] `mypy src/` exits 0
- [ ] No `KEYCLOAK_*` / `AUTH_*` value in `.env.example` is a real credential (`grep -n 'FIXME' .env.example` shows them)
- [ ] **No credential literal anywhere in committed files.** `grep -rnE "(PASSWORD|SECRET)[^=]*[:=] *['\"]?[A-Za-z0-9]" docker-compose.yml deploy/ ADMIN_GUIDE.md` returns **only** `${VAR}` references and `FIXME` placeholders. `KC_BOOTSTRAP_ADMIN_USERNAME: admin` is expected and correct — the username is an identifier, not a secret
- [ ] All **six** credentials have **no default** in `docker-compose.yml`: `grep -cE '(KEYCLOAK_DB_PASSWORD|KEYCLOAK_CLIENT_SECRET|KEYCLOAK_SERVICE_CLIENT_SECRET|DEV_WBA_ADMIN_PASSWORD|DEV_WBA_USER_PASSWORD|DEV_KEYCLOAK_ADMIN_PASSWORD): \$\{[A-Z_]+\}$' docker-compose.yml` → `6` (each matched line ends at `}` with no `:-`)
- [ ] The application is **still unauthenticated**: `curl -sf https://localhost/api/health` returns `{"status":"healthy"}` with no `Authorization` header
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report (do not improvise) if:

- ~~The image rejects `KC_HOSTNAME_STRICT` or `--http-relative-path`.~~
  **RESOLVED 2026-10-31** — `KC_HOSTNAME_STRICT` is gone and `KC_HOSTNAME_ADMIN`
  replaces it; `--http-relative-path` was never actually passed as a CLI flag.
- The 26.8 image behaves differently from 26.4 for `KC_HOSTNAME_ADMIN`. It was
  pre-verified working on 26.8.1, so a failure here means something else changed
  — report rather than patching around it.
- The `issuer` differs between the host and the container in Step 6.
- ~~`envsubst` is missing from the Keycloak image.~~ **RESOLVED — it is missing,
  confirmed on 2026-10-30, and Step 4 now uses a pure-bash renderer instead.** Do
  not reintroduce `envsubst`.
- A credential has to be written as a literal to make something work. Stop and
  report instead — the policy is that every Keycloak credential is a `${VAR}`
  with no default, and reintroducing a literal defeats the point of this plan.
  (The two declared exceptions are the non-secret identifiers
  `KC_DB_USERNAME: keycloak` and `KC_BOOTSTRAP_ADMIN_USERNAME: admin`.)
- You feel the need to add a `ports:` block to make the healthcheck or a verify
  command pass. The console port is off by default **by decision**; the
  healthcheck runs inside the container and needs no published port.
- The service account `wba-internal` cannot be given `wba-service` with the
  template shape you wrote.
- Keycloak cannot connect to the `keycloak` database after Step 3 (the role/DB
  creation failed, or the volume was not the one in use).
- Any in-scope file has drifted from the "Current state" excerpts.

## Maintenance notes

- **`KC_HOSTNAME_ADMIN` is the console mechanism, not `KC_HOSTNAME_STRICT`.**
  Do not revert to `KC_HOSTNAME_STRICT=false` — on 26.x it is a documented no-op
  whenever `KC_HOSTNAME` is set, and it was the original plan's bug. A real
  deployment removes `KC_HOSTNAME_ADMIN` and does not publish the console at all.
- **The console port is off by default and toggled by hand.** The operator
  explicitly rejected a second compose file / override as hard to maintain, so
  the toggle is a documented edit to `docker-compose.yml` per `ADMIN_GUIDE.md`.
  Tested and rejected alternatives: an `${ADMIN_BIND}` env var (empty falls back
  to the default, so it cannot disable a mapping) and a compose overlay with
  `ports: []` (compose merges lists; only `!reset []` removes it, which needs the
  second file the operator rejected).
- **`KC_BOOTSTRAP_ADMIN_*` runs only against an empty Keycloak database.** It is
  a one-shot seed, not an idempotent reconciler. Changing
  `DEV_KEYCLOAK_ADMIN_PASSWORD` in `.env` later does **not** change the existing
  admin's password — use `kc.sh bootstrap-admin user` (or the console). Any
  reviewer who assumes this is declarative config will be wrong. To re-seed from
  the variable, drop and recreate the `keycloak` database (decision 7); that is
  safe only because the DB is entirely template-derived. **If a future change
  makes that database hold non-reproducible state, this shortcut stops being
  safe** — at that point export the realm first.
- **No Keycloak credential is committed, including in development.** All five are
  `${VAR}` references with no default, populated in the gitignored `.env`. This
  deliberately costs the "zero manual setup" property: a fresh clone must set
  them before `docker compose up` produces a working login. A real deployment
  takes them from a secret store; Plan E owns host-exposed Postgres hardening.
  If you find yourself adding `:-somedefault` to make a command easier, that is
  the defect this policy exists to prevent — add the value to `.env` instead.
- **The postgres init script is `.sh`, not `.sql`**, for the credential reason
  above. Converting it back to `.sql` reintroduces a committed literal.
- **Changing `KC_HTTP_RELATIVE_PATH` changes `iss`**, and every token becomes
  invalid until sessions are recreated. Treat it as a breaking change.
- **Adding a client** (e.g. for MCP, per the design's Future Considerations) means
  a new template entry, a new secret variable, and a re-import — but realm
  re-import in `start-dev` only applies on first boot against an empty realm
  table, so document the reset path.
- **A reviewer should scrutinize**: that `/auth/admin` is genuinely not routed,
  that no secret value is committed, and that the issuer string is written in
  exactly one place per runtime.

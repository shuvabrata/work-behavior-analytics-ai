# Plan 051: Serve the app over HTTPS behind nginx, and make it proxy-aware

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Every step ends with a MANUAL GATE.** After completing a step's automated
> verification, stop and hand back to the operator for a human check. Do not
> begin the next step until the operator replies `PASS`. If they reply `FAIL`,
> treat it as a STOP condition. Record each gate's outcome in the Progress
> tracker below before continuing.
>
> **Drift check (run first)**: `git diff --stat 6f1eb0e..HEAD -- docker-compose.yml src/app/entrypoint.sh src/app/settings.py src/app/main.py src/app/dash_app/pages src/app/dash_app/components scripts/setup.sh CLAUDE.md DEVELOPER_QUICK_START.md USER_GUIDE.md`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding.
>
> **Benign drift** — do not stop for these, they do not touch any step:
> - `CLAUDE.md` shows a one-line deletion near the "Repo conventions" list
>   (a removed deployment-model bullet). The lines this plan edits are 15 and
>   143, which are unaffected.
> - `src/app/main.py` shows a diff around the projects router. Nothing in this
>   plan edits `main.py`; it is listed only so the line citations (195/168/176)
>   can be re-checked. If those three citations no longer match, adjust the
>   line numbers in your reading — **do not edit `main.py`**.
>
> Any other mismatch is a STOP condition.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: MED
- **Depends on**: none
- **Category**: security | dx
- **Planned at**: commit `6f1eb0e`, 2026-10-26

### Progress tracker

Mark each cell as you go. `⬜` not started · `🔄` in progress · `✅` passed ·
`❌` failed (stop and report). **Do not start a step whose gate is not `✅`.**

| Step | What it changes | Automated verify | Manual gate | Status |
|------|-----------------|------------------|-------------|--------|
| 1  | TLS certificate generated | cert files exist, not git-tracked | Operator confirms cert trusted in browser | ⬜ |
| 2  | nginx config written | `nginx -t` passes | Operator reviews config content | ⬜ |
| 3  | nginx in Compose, port 8000 unpublished | `docker compose config -q` | Operator confirms `:8000` refused, `:443` answers | ⬜ |
| 4  | uvicorn trusts proxy headers | grep gates | Operator confirms app still healthy | ⬜ |
| 5  | `EXTERNAL_BASE_URL` / `API_BASE_URL` settings | grep gates, `mypy` | Operator reviews the diff | ⬜ |
| 6  | proxy-awareness unit test | `pytest` file passes | Operator reviews test asserts real behaviour | ⬜ |
| 7  | setup script + docs URLs (may be deferred) | grep gates | Operator confirms wording reads correctly | ⬜ |
| 8  | full stack smoke test | the 9-check table | **Operator performs all 9 checks** | ⬜ |
| 9  | CI gates | all five commands exit 0 | Operator reviews output | ⬜ |
| 10 | `USER_GUIDE.md` new-machine setup | grep gates | Operator walks the guide | ⬜ |
| 11 | `docs/design/nginx-tls-design.md` written | file + section greps | Operator reviews design doc | ⬜ |

## Why this matters

The application currently serves plaintext HTTP on host port 8000 with no TLS
termination and no proxy in front of it. Plan C of
`docs/design/authn-authz-design.md` adds Keycloak-based authentication with an
HttpOnly session cookie, and that work is **incorrect without HTTPS**: the
cookie cannot carry `Secure`, Keycloak's production mode requires TLS, and the
OAuth `redirect_uri` must be built from the external URL rather than the
container's own bind address.

This plan puts nginx in front of the app to terminate TLS, and — critically —
makes the application *proxy-aware* so it never derives its external scheme or
host from its own listener. That second half is what lets the same code run
behind nginx today and behind AWS API Gateway later as a configuration change
rather than a rewrite.

Two things improve immediately, before any auth exists: browser traffic to the
app is encrypted, and FastAPI's unauthenticated `/docs`, `/redoc` and
`/openapi.json` endpoints stop being reachable from outside the Docker network
(they are not routed by nginx). Formal hardening of those endpoints remains
Plan E's job.

## Current state

### Files involved

- `docker-compose.yml` — Compose stack; `app` service at lines 23–97, publishes
  `8000:8000` at lines 68–69, healthcheck at lines 81–86, `networks` at 292–294
- `src/app/entrypoint.sh` — container startup; ends with the `uvicorn` invocation
  at line 34
- `src/app/settings.py` — pydantic-settings `Settings` class (126 lines)
- `src/app/main.py` — FastAPI app; mounts Dash at line 197
- The nine `API_BASE_URL` call sites (listed in Step 5)
- `scripts/setup.sh` — dev bootstrap; polls app health at line 384, prints the
  app URL at lines 362, 388, 403
- `CLAUDE.md`, `DEVELOPER_QUICK_START.md`, `USER_GUIDE.md` — documented URLs
- `.gitignore` — has **no** entry for certs or a deploy directory

### Verified facts about the current code

**No proxy exists.** There is no nginx, caddy, or traefik configuration anywhere
in the repository, and no `.conf` files outside `.venv`.

**The app is not proxy-aware.** `src/app/entrypoint.sh:34` is:

```bash
cd /app && uvicorn app.main:app --host 0.0.0.0 --port 8000
```

No `--forwarded-allow-ips` is passed. Note that `--proxy-headers` is **already
true by default** in uvicorn 0.54.0, and uvicorn applies its own
`ProxyHeadersMiddleware` at server startup — so the machinery exists but trusts
only `127.0.0.1,::1`, which does not include nginx's container IP. The missing
piece is the trusted-peer configuration, not the middleware itself.

A grep for `X-Forwarded` across `src/` returns no matches, and nothing in
`src/app/` constructs an absolute URL from the request (the only `request.url`
uses are `path`-only, for logging, at `src/app/main.py:168` and `:176`).

**`app` publishes port 8000 to the host.** `docker-compose.yml:68-69`:

```yaml
    ports:
      - "8000:8000"
```

**The healthcheck and dev script assume that published port.**
`docker-compose.yml:81-86` runs `curl -f http://localhost:8000/api/health`
inside the container; `scripts/setup.sh:384` polls
`curl -sf http://localhost:8000/api/health` from the host.

**`API_BASE_URL` is read with a hardcoded default at nine sites, and is not a
`Settings` field.** All nine use the identical expression
`os.getenv("API_BASE_URL", "http://localhost:8000")`. Three are module-level
constants evaluated at import time; six are inside functions:

| Site | Form |
|---|---|
| `src/app/dash_app/pages/settings/runtime.py:60` | module-level (`API_BASE`) |
| `src/app/dash_app/pages/settings/graph_styling/callbacks.py:43` | module-level (`API_BASE`) |
| `src/app/dash_app/components/setup_banner.py:20` | module-level (`SETTINGS_API`, appends `/api/v1/settings/`) |
| `src/app/dash_app/pages/search.py:125` | in-function |
| `src/app/dash_app/pages/catalog/_utils.py:10` | in-function (`get_api_base_url`) |
| `src/app/dash_app/pages/chat.py:162` | in-function |
| `src/app/dash_app/pages/timeline/api.py:52` | in-function |
| `src/app/dash_app/pages/connectors/callbacks.py:49` | in-function (`_get_api_base_url`) |
| `src/app/dash_app/pages/graph/utils/graph_operations.py:26` | in-function |

This value is **container-internal**. The Dash code runs inside the `app`
container and calls the API on the same host, so it stays `http://localhost:8000`
even after TLS is added at the edge. It is deliberately **not**
`EXTERNAL_BASE_URL`.

**Producers and the consumer use a different variable for the same purpose.**
They read `API_SERVER`, defaulting to `http://app:8000/`
(`src/connectors/producers/daemon_common.py:176`,
`src/connectors/consumers/main.py:206`). **Do not change these** — see Scope.

**Dash's URL prefix is already correct for this topology.**
`src/app/dash_app/layout.py:27` sets `requests_pathname_prefix="/app/"`, and
`src/app/main.py:195` mounts the WSGI app at `/app`. Because nginx will proxy
`/app` at the same path depth, no `X-Forwarded-Prefix` handling is required and
Dash's generated URLs stay valid.

**The SSE stream is called directly from the browser.**
`src/app/dash_app/assets/stream-bridge.js:215` fetches
`/api/v1/chats/{sessionId}/stream` via `fetch`. The endpoint
(`src/app/api/chats/v1/router.py:39-72`) returns a `StreamingResponse` with
`media_type="text/event-stream"`. This request will pass through nginx, and
nginx's default `proxy_buffering on` would hold the stream back.

**The app has no `/` route.** Root returns 404. The paths it actually serves are
`/app/*` (Dash UI and its assets), `/api/health`, `/api/v1/*`, and FastAPI's
defaults `/docs`, `/redoc`, `/openapi.json`.

### Repo conventions that apply

- **Settings** are declared as fields on the `Settings` class in
  `src/app/settings.py`, with a sensible default and a comment. Infrastructure
  values with no default (`DATABASE_URL`, line 8) are the exception; prefer
  providing one. Match the existing grouped-with-comment style, e.g.:

  ```python
  # UI Configuration
  TIMEZONE: str = Field(default="UTC", validation_alias=AliasChoices("TIMEZONE", "TZ"))
  ```

- **Never `print()`** — use `from common.logger import logger`.
- **Type hints on all parameters and returns.** Built-in generics
  (`dict[str, str]`), `X | None`. `mypy src/` runs strict.
- **Tests** carry a marker. At module level: `pytestmark = pytest.mark.unit`.
  There is no root `conftest.py`; `tests/conftest.py` holds shared fixtures and
  an autouse fixture that disables a dev-only mock. Tests import app code via
  `PYTHONPATH` set in `pytest.ini` (`pythonpath = src . tests`).
- **Commit messages** are plain imperative sentences, e.g.
  `Activity timeline backend (#323)`. Not conventional-commit style (that is
  only used for Dependabot bumps).
- **Do not commit, push, or open a PR** unless explicitly asked.

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Unit tests (CI gate) | `pytest -m unit tests -q` | all pass, exit 0 |
| Single test file | `pytest -m unit tests/test_proxy_awareness.py -q` | all pass |
| Typecheck (CI gate) | `mypy src/` | no errors, exit 0 |
| Lint (CI gate) | `pylint src --score=y` | score ≥ 9.0 |
| Security scan (CI gate) | `bandit -c .bandit.yml -r src/ -lll` | no High severity, exit 0 |
| Style (local only — **not** a CI gate) | `flake8` | exit 0 |
| Config syntax | `docker compose config -q` | exit 0, no output |
| Full stack | `docker compose up -d` | all services healthy |

Run the Python commands with the virtualenv active (`source .venv/bin/activate`)
and `PYTHONPATH=src` where importing app code outside pytest.

## Scope

**In scope** (the only files you should modify or create):

- `deploy/nginx/nginx.conf` (create)
- `deploy/certs/.gitkeep` (create) — certs themselves are generated, not committed
- `docker-compose.yml`
- `.gitignore`
- `src/app/entrypoint.sh`
- `src/app/settings.py`
- The nine `API_BASE_URL` call sites in the table above (edit in place; do **not**
  create a shared helper module — Plan B's HTTP client subsumes them)
- `tests/test_proxy_awareness.py` (create)
- `scripts/setup.sh` — health poll and printed URLs only
- `CLAUDE.md` — URL references and the Compose services table only
- `DEVELOPER_QUICK_START.md` — add the cert prerequisite and an HTTPS access
  line to Option 1, and label Option 2's `http://localhost:8000` lines as the
  local-uvicorn workflow. **Option 2's URLs stay HTTP** — see Step 7.
- `USER_GUIDE.md` — URL references in Step 7 **and** the new-machine setup
  rewrite in Step 10 (prerequisites, cert generation, WSL2 CA import,
  troubleshooting, Quick Reference table)
- `docs/design/nginx-tls-design.md` (create) — Step 11
- `plans/README.md` — status row

**Out of scope** (do NOT touch, even though they look related):

- **`API_SERVER` in the producers, consumer, and their config modules.** Nine
  files reference it (`daemon_common.py:176`, `consumers/main.py:206`, and the
  `*_config.py` / `main.py` / `constants.py` files under
  `src/connectors/producers/`). They call the API over the Docker network at
  `http://app:8000/` and are unaffected by edge TLS. Changing them is Plan B's
  job (machine credentials), not this plan's.
- **`AUTH_COOKIE_SECURE`, `AUTH_SESSION_*`, `KEYCLOAK_*`.** These are Plan C's.
  Do not add them here. See Maintenance notes for the coupling.
- **The Keycloak `/auth` location block.** Write it **commented out** and
  reserve the path (Step 3). Do not create a Keycloak service.
- **Any Dash call site's `requests` plumbing or `HTTP_REQUEST_TIMEOUT` usage.**
  Plan 051 changes only the base-URL *value* expression. Consolidating the
  request plumbing is Plan B's shared HTTP client
  (`docs/design/authn-authz-design.md`, Plan B).
- **FastAPI's `/docs`, `/redoc`, `/openapi.json` settings.** They become
  unreachable as a side effect of nginx routing, which is fine. Do not add
  `docs_url=None` — that is Plan E's decision.
- **`src/app/main.py`.** No application routing changes are needed.
- **TLS for container-to-container traffic.** Decided against: internal traffic
  stays plain HTTP on the Docker bridge. Do not add certs or CA bundles to the
  `app`, producer, or consumer images.

## Git workflow

- Branch: `feat/tls-reverse-proxy` (repo has no formal prefix convention; recent
  branches include `feature/timeline-onclick`)
- Commit per step or per logical unit. Message style — plain imperative
  sentences matching `git log`, e.g. `Serve app over HTTPS behind nginx`.
  Suggested split: infrastructure (Steps 1–3), proxy-awareness (Steps 4–6),
  docs (Steps 7 + 10).
- Do **not** push or open a PR unless the operator instructed it.

## Steps

### Step 1: Generate the TLS certificate

Decide the external hostname for the certificate. Use `localhost` — the nginx
config hardcodes `server_name localhost;` (Step 2), so the cert and the config
must agree. Changing the hostname later means editing both (see Maintenance
notes).

Install and run [mkcert](https://github.com/FiloSottile/mkcert):

```bash
# In WSL2 — installs the mkcert binary if absent
sudo apt install -y libnss3-tools
curl -JLO "https://dl.filippo.io/mkcert/latest?for=linux/amd64"
chmod +x mkcert-v*-linux-amd64
sudo mv mkcert-v*-linux-amd64 /usr/local/bin/mkcert

# Create a local CA and install it (browser trust)
mkcert -install

# Issue a cert for the app hostname
mkdir -p deploy/certs
mkcert -cert-file deploy/certs/wba.pem -key-file deploy/certs/wba-key.pem localhost 127.0.0.1
```

**WSL2 + Windows browser caveat:** if the browser runs on Windows, `mkcert
-install` inside WSL installs the CA into the *Linux* trust store, which the
Windows browser does not read. To silent the warning, import the CA into
Windows. Find it with `mkcert -CAROOT`, then import `rootCA.pem` on the Windows
side (PowerShell as admin):

```powershell
Import-Certificate -FilePath "\\wsl$\<distro>\<path-to>\rootCA.pem" -CertStoreLocation Cert:\LocalMachine\Root
```

This is a **one-time manual step per developer machine** and cannot be
automated from the repo. Record it in the plan's output notes (Step 8).

Add a gitignore entry so certs are never committed:

```
# Local TLS certificates (generated by mkcert; never commit)
deploy/certs/*
!deploy/certs/.gitkeep
```

Then create the placeholder file: `touch deploy/certs/.gitkeep`.

**Verify**: `ls deploy/certs/` → shows `wba.pem`, `wba-key.pem`, `.gitkeep`
**Verify**: `git status --short` → shows `.gitignore` as modified and
`?? deploy/certs/.gitkeep`; no `.pem` file appears anywhere

> ### 🚦 MANUAL GATE 1 — operator check
>
> **Report to the operator:**
> - Output of `ls -la deploy/certs/`
> - Output of `mkcert -CAROOT`
> - Whether the Windows-side CA import was performed (WSL2 users only)
>
> **Operator verifies:**
> 1. `deploy/certs/wba.pem` and `deploy/certs/wba-key.pem` exist and are non-empty.
> 2. No `.pem` or `.key` file appears in `git status`.
> 3. The certificate subject covers `localhost` — check with
>    `openssl x509 -in deploy/certs/wba.pem -noout -text | grep -A1 "Subject Alternative Name"`.
> 4. For WSL2: the CA is imported into the **Windows** certificate store, so the
>    browser will trust it later. Confirm the import succeeded, or explicitly
>    accept that the browser will warn until it is done.
>
> Wait for `PASS` before starting Step 2. A missing or untrusted cert makes
> every later gate fail for reasons unrelated to nginx.

### Step 2: Write the nginx configuration

Create `deploy/nginx/nginx.conf`. Requirements, in order of importance:

1. **TLS on 443** with the cert from Step 1, and HTTP/2.
2. **`/api/v1/chats/` → `proxy_buffering off`**, plus a long `proxy_read_timeout`.
   This is the SSE stream. Without it the chat response is buffered or cut off.
   This block must come **before** the general `/api` block — nginx matches
   prefix locations by longest match, so `/api/v1/chats/` wins naturally, but
   keep them adjacent and ordered for readability.
3. **`/app` → `app:8000`**, preserving the path (no trailing slash on
   `proxy_pass`, so `/app/foo` maps to `/app/foo`).
4. **`/api` → `app:8000`**, for both `/api/health` and `/api/v1/*`.
5. **`location = /` → 302 to `/app`**, so the root is useful rather than a 404.
6. **Forwarded headers** on every proxied location:
   `Host`, `X-Real-IP`, `X-Forwarded-For`, `X-Forwarded-Proto`,
   `X-Forwarded-Host`.
7. **A commented-out `/auth` block** reserving the path for Keycloak (Plan C),
   with the directives Plan C will need.

Target shape — this is a **complete `nginx.conf`**, not a fragment. It must
contain the top-level `events {}` and `http {}` blocks, because it is mounted
directly at `/etc/nginx/nginx.conf` (Step 3) and replaces the image's default
file. Omitting either wrapper fails `nginx -t` with
`"upstream" directive is not allowed here`:

```nginx
events {}

http {
    include       /etc/nginx/mime.types;
    default_type  application/octet-stream;

    # Upstream is the compose service name; resolved on the wba-ai-network.
    upstream wba_app {
        server app:8000;
    }

    server {
        listen 80;
        # Redirect plaintext to TLS rather than serving anything.
        return 301 https://$host$request_uri;
    }

    server {
        listen 443 ssl;
        http2 on;

        server_name localhost;

        ssl_certificate     /etc/nginx/certs/wba.pem;
        ssl_certificate_key /etc/nginx/certs/wba-key.pem;
        ssl_protocols       TLSv1.2 TLSv1.3;

        # ── SSE stream: never buffer, never time out early ──────────────
        # The browser calls this directly (dash_app/assets/stream-bridge.js).
        # With buffering on, nginx holds the response and the user sees
        # nothing until it completes. Longest-prefix match means this wins
        # over `location /api` below regardless of file order.
        location /api/v1/chats/ {
            proxy_pass http://wba_app;
            proxy_buffering off;
            proxy_cache off;
            proxy_read_timeout 3600s;
            proxy_set_header Host              $host;
            proxy_set_header X-Real-IP         $remote_addr;
            proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;
            proxy_set_header X-Forwarded-Host  $host;
        }

        # ── API ─────────────────────────────────────────────────────────
        location /api {
            proxy_pass http://wba_app;
            proxy_set_header Host              $host;
            proxy_set_header X-Real-IP         $remote_addr;
            proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;
            proxy_set_header X-Forwarded-Host  $host;
        }

        # ── Dash UI (extends to /app/assets/*, /app/_dash-*) ─────────────
        # No trailing slash on proxy_pass: the /app prefix is preserved,
        # which is what requests_pathname_prefix="/app/" in
        # dash_app/layout.py expects.
        location /app {
            proxy_pass http://wba_app;
            proxy_set_header Host              $host;
            proxy_set_header X-Real-IP         $remote_addr;
            proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;
            proxy_set_header X-Forwarded-Host  $host;
        }

        location = / {
            return 302 /app;
        }

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
    }
}
```

**Hardcode `server_name localhost;`** as shown. Do not use nginx's
`envsubst` templating mechanism (files mounted into `/etc/nginx/templates/`)
— it adds a moving part for one variable that changes rarely, and it only
works if the file is mounted to the *templates* directory rather than directly
at `/etc/nginx/nginx.conf`. If the file is mounted at `/etc/nginx/nginx.conf`
while still containing `${NGINX_SERVER_NAME}`, the placeholder is left literal
and `nginx -t` **still reports success** — a silent misconfiguration. Since
Step 3 mounts the file at `/etc/nginx/nginx.conf`, there must be no `${...}`
placeholders in it at all.

Changing the hostname later is a one-line edit to `server_name` plus reissuing
the cert (see Maintenance notes).

**Verify** — this command needs both `--add-host` (so the `app` upstream
resolves; it exists only on the compose network) and the certs mounted, or it
fails for reasons unrelated to your config:

```bash
docker run --rm \
  --add-host app:127.0.0.1 \
  -v "$PWD/deploy/nginx/nginx.conf:/etc/nginx/nginx.conf:ro" \
  -v "$PWD/deploy/certs:/etc/nginx/certs:ro" \
  nginx:1.30-alpine nginx -t
```
→ `syntax is ok` and `test is successful`

Without `--add-host` you get
`[emerg] host not found in upstream "app:8000"`, and without the certs mount you
get `cannot load certificate "/etc/nginx/certs/wba.pem"`. Both are expected
consequences of testing outside the compose network, **not** config errors —
do not "fix" the config in response to either. The authoritative check is
`docker compose up` in Step 8, where `app` resolves for real.

> ### 🚦 MANUAL GATE 2 — operator check
>
> **Report to the operator:**
> - Output of the `nginx -t` command above
> - The full contents of `deploy/nginx/nginx.conf`
>
> **Operator verifies:**
> 1. `nginx -t` reports `syntax is ok` **and** `test is successful`.
> 2. The file starts with `events {}` and wraps everything in `http { }` —
>    a bare `upstream`/`server` fragment is not a valid `nginx.conf`.
> 3. There is a `location /api/v1/chats/` block containing
>    `proxy_buffering off;` — this is the SSE stream, and without it chat
>    output will be buffered.
> 4. `location /app` and `location /api` both `proxy_pass` to the same upstream,
>    and neither has a trailing slash on `proxy_pass` (which would strip the
>    `/app` prefix Dash depends on).
> 5. `http2 on;` appears inside the 443 server block.
> 6. No `${...}` placeholder appears anywhere in the file.
>
> Wait for `PASS` before starting Step 3.

### Step 3: Add nginx to Compose and unpublish the app port

In `docker-compose.yml`:

1. **Remove `8000:8000`** from the `app` service's `ports:` (lines 68–69). The
   `app` service should have no `ports:` key at all afterwards. This is what
   makes TLS enforced rather than optional.

2. **Fix the `app` healthcheck.** It currently curls
   `http://localhost:8000/api/health`, which still works *inside* the container
   (the app still listens on 8000 there) — so this line may be left unchanged.
   Confirm by reading it; if it uses `localhost` inside the container, it is
   fine. Do not repoint it at nginx.

3. **Add the nginx service:**

```yaml
  nginx:
    # Pinned to the current stable branch (1.30.x, currently 1.30.6). This is
    # a minor-version tag, not a digest — pulls can drift inside 1.30.x. Pin
    # to a digest if you need byte-identical reproducibility.
    image: nginx:1.30-alpine
    container_name: wba-ai-nginx
    restart: unless-stopped
    ports:
      - "443:443"
      # Port 80 serves ONLY a 301 redirect to HTTPS (see the `listen 80`
      # server block). Publish it so a browser hitting http:// is upgraded
      # rather than timing out — it never serves application content.
      - "80:80"
    volumes:
      - ./deploy/nginx/nginx.conf:/etc/nginx/nginx.conf:ro
      - ./deploy/certs:/etc/nginx/certs:ro
    networks:
      - wba-ai-network
    depends_on:
      app:
        condition: service_healthy
```

4. **`app` depends on nothing new**, but confirm the `app` service remains
   reachable by service name `app` on `wba-ai-network` — it is, via the existing
   `networks: - wba-ai-network` entry.

**Verify**: `docker compose config -q` → exit 0, no output
**Verify**: `grep -n "8000:8000" docker-compose.yml` → no matches
**Verify**: `grep -n "443:443" docker-compose.yml` → one match, under `nginx`

> ### 🚦 MANUAL GATE 3 — operator check (first end-to-end TLS check)
>
> This is the first gate where the stack is actually reachable. Bring it up:
>
> ```bash
> docker compose up -d
> docker compose ps          # app must reach "healthy"; nginx running
> ```
>
> **Report to the operator:** the output of every command below, plus the
> contents of `docker compose ps`.
>
> **Operator verifies:**
> 1. `curl -skI https://localhost/` → `HTTP/2 302` with `location: /app`.
> 2. `curl -sk https://localhost/api/health` → `{"status":"healthy"}`.
> 3. `curl -s -m 5 http://localhost:8000/api/health` → **connection refused**.
>    This is the point of the step: the app is no longer reachable on 8000.
> 4. `docker compose ps` shows `app` as `healthy` — proving the in-container
>    healthcheck still works after the host port was removed.
> 5. No service is stuck in a restart loop.
>
> **If check 3 still returns a response**, the `8000:8000` mapping was not fully
> removed — stop and report rather than continuing.
> **If `docker compose up` fails with `bind: address already in use`**, see STOP
> conditions — do not remap the port.
>
> Wait for `PASS` before starting Step 4. Steps 4–6 change code and tests; they
> should not begin until the infrastructure layer is confirmed working.

### Step 4: Make uvicorn trust the proxy's forwarded headers

Edit `src/app/entrypoint.sh` line 34. Change:

```bash
cd /app && uvicorn app.main:app --host 0.0.0.0 --port 8000
```

to:

```bash
# --forwarded-allow-ips tells uvicorn which peers may set X-Forwarded-Proto /
# X-Forwarded-For. uvicorn's ProxyHeadersMiddleware honours those headers only
# from trusted hosts, and the default is "127.0.0.1,::1" — which does NOT
# include nginx's container IP, so the external scheme would be lost.
cd /app && uvicorn app.main:app --host 0.0.0.0 --port 8000 \
    --forwarded-allow-ips="*"
```

**Read this before changing the flag set.** Two facts about uvicorn 0.54.0 that
shape this step, both verified against the installed package:

1. **`--proxy-headers` is already `True` by default** (`uvicorn/main.py:234`),
   so adding it is a no-op. The flag that actually changes behaviour is
   `--forwarded-allow-ips`, whose default comes from
   `os.environ.get("FORWARDED_ALLOW_IPS", "127.0.0.1,::1")`
   (`uvicorn/config.py:361-363`). Do **not** add `--proxy-headers` — it adds a
   line that implies it is doing the work.

2. **The middleware is uvicorn's, not Starlette's.** uvicorn wraps the app at
   server startup: `if self.proxy_headers: self.loaded_app =
   ProxyHeadersMiddleware(self.loaded_app, trusted_hosts=self.forwarded_allow_ips)`
   (`uvicorn/config.py:543-544`). This means the wrapped app is **not**
   `app.main.app` — the middleware exists only in the running server. Any test
   driving `app.main.app` through `httpx.ASGITransport` bypasses it entirely.
   This is why Step 6 must build its own middleware stack.

**Use `--forwarded-allow-ips="*"` — do not substitute a subnet.** The literal
`*` means "trust any peer" (`uvicorn/middleware/proxy_headers.py`,
`_TrustedHosts.__init__` sets `always_trust` when
`trusted_hosts in ("*", ["*"])`). A hardcoded subnet such as `172.16.0.0/12` is
a trap: Docker assigns compose bridge subnets from a pool, and if the assigned
subnet falls outside whatever you hardcode, nginx's forwarded headers are
silently ignored — with no test in this plan that would catch it. `*` is
acceptable **here and only here** because Step 3 removes the app's host port,
so the only reachable peers are nginx and the other compose services. Add a
comment in the file saying exactly that. Note `*` does **not** by itself
restrict anything; the restriction is the unpublished port — which is why the
comment must state the coupling, so re-publishing a port is obviously wrong.

**Verify**: `grep -n "forwarded-allow-ips" src/app/entrypoint.sh` → one match
**Verify**: `grep -c "proxy-headers" src/app/entrypoint.sh` → 0

> ### 🚦 MANUAL GATE 4 — operator check
>
> The change is inside the container image, so it only takes effect after a
> rebuild:
>
> ```bash
> docker compose up -d --build app
> docker compose ps
> ```
>
> **Report to the operator:** both grep outputs, the tail of
> `docker compose logs --tail 20 app`, and `docker compose ps`.
>
> **Operator verifies:**
> 1. `grep -n "forwarded-allow-ips" src/app/entrypoint.sh` → exactly one match,
>    and it reads `--forwarded-allow-ips="*"`.
> 2. `grep -c "proxy-headers" src/app/entrypoint.sh` → `0`. The flag must **not**
>    be present — it is already uvicorn's default, and adding it implies it is
>    doing work it is not.
> 3. `docker compose ps` → `app` returns to `healthy` after the rebuild.
> 4. `docker compose logs app --tail 20` shows no startup error or traceback.
> 5. `curl -sk https://localhost/api/health` still returns `{"status":"healthy"}`
>    — the rebuild did not break the stack.
>
> Wait for `PASS` before starting Step 5.

### Step 5: Add the two settings and consolidate API_BASE_URL

In `src/app/settings.py`, add a new group. Place it **immediately after the
RabbitMQ block and before the Elasticsearch block** (i.e. after the
`RABBITMQ_URL` line, before `ELASTICSEARCH_AI_LOOKUP_ENABLED`), matching the
file's grouped-with-comment style:

```python
    # ── External URL / reverse proxy ────────────────────────────────────
    # The URL the BROWSER uses to reach this application. nginx terminates
    # TLS and forwards plain HTTP to this container, so the app must never
    # derive its external scheme or host from its own listener. Anything
    # that needs an absolute, browser-facing URL (e.g. an OAuth redirect_uri
    # in Plan C) must build it from this value.
    EXTERNAL_BASE_URL: str = "https://localhost"

    # The URL the Dash code uses to call the API from INSIDE this container.
    # The Dash callbacks run in this same process and call the API over the
    # Docker network, so this stays plain HTTP even though the browser
    # speaks HTTPS. Deliberately NOT the same value as EXTERNAL_BASE_URL.
    API_BASE_URL: str = "http://localhost:8000"
```

Then replace all nine occurrences of:

```python
os.getenv("API_BASE_URL", "http://localhost:8000")
```

with a read of the settings singleton. For the three module-level constants,
add the import at the top of the file (`from app.settings import settings`) and
assign `settings.API_BASE_URL` directly. For the six in-function sites, the same
expression works.

**Import-cycle check:** `src/app/settings.py` imports nothing from `app.dash_app`,
so `from app.settings import settings` inside dash modules is safe.

**Only one of the nine files already imports it** — `pages/chat.py:11` has
`from app.settings import settings`. Add the import to the other eight. In
`pages/chat.py`, reuse the existing import; do not add a duplicate.

**Watch the `os` import.** All nine files currently `import os`, and in at least
some of them the `os.getenv("API_BASE_URL", ...)` call is the *only* use of `os`.
After the swap, remove the now-unused `import os` in any such file — `pylint`
runs at ≥ 9.0 and flags unused imports. Check per file rather than assuming;
some may use `os` elsewhere (e.g. for `os.environ` or path handling).

**Verify**: `grep -rn "os.getenv(\"API_BASE_URL\"" src/` → no matches
**Verify**: `grep -c "API_BASE_URL" src/app/settings.py` → 1 match (the field declaration; the surrounding comment describes the value but does not repeat the literal name)
**Verify**: `mypy src/` → exit 0

> ### 🚦 MANUAL GATE 5 — operator check
>
> **Report to the operator:**
> - All three verify outputs
> - `git diff --stat` (should be nine Dash files + `settings.py`)
> - `git diff src/app/settings.py`
>
> **Operator verifies:**
> 1. `settings.py` declares **two** fields with the **two different** default
>    values — `EXTERNAL_BASE_URL = "https://localhost"` and
>    `API_BASE_URL = "http://localhost:8000"`. They must not share a value.
> 2. `git diff --stat` touches nine Dash files plus `settings.py` and nothing
>    else.
> 3. No Dash file still imports `os` without using it (a `pylint` failure would
>    surface in Step 9, but catching it now is cheaper).
> 4. There is no new shared helper module — the edits are in place, since Plan B
>    introduces the real HTTP client.
>
> Wait for `PASS` before starting Step 6.

### Step 6: Add the proxy-awareness unit test

Create `tests/test_proxy_awareness.py`. Follow the structural pattern of
`tests/test_timezone_settings.py` (module-level `pytestmark = pytest.mark.unit`,
a `_build_settings(**kwargs)` helper that passes `_env_file=None`).

The test must cover:

1. **`EXTERNAL_BASE_URL` defaults to `https://localhost`** and is overridable
   through `Settings(...)`.
2. **`API_BASE_URL` defaults to `http://localhost:8000`** and is overridable.
3. **The two are independent** — setting one must not affect the other. This is
   the regression guard for the most likely future mistake (someone "fixing"
   the duplicate by pointing `API_BASE_URL` at `EXTERNAL_BASE_URL`, which would
   break every Dash callback by sending them through TLS to the public host).
4. **Forwarded-header trust works.** Build a minimal FastAPI app with
   `ProxyHeadersMiddleware`, or use `app.main.app` via
   `httpx.ASGITransport` with a `X-Forwarded-Proto: https` header, and assert
   that `request.url.scheme == "https"`. Note that
   `httpx.ASGITransport` does **not** run the app's lifespan — that is expected
   and is the pattern the existing suite uses
   (`tests/test_activity_api_integration.py:283-285`).

For case 4, build a throwaway ASGI app and wrap it with the middleware
explicitly. **The import path is `uvicorn.middleware.proxy_headers`, not
`starlette.middleware.proxy_headers`** — verified: `ProxyHeadersMiddleware`
lives in uvicorn (`uvicorn/middleware/proxy_headers.py:9`), and Starlette
1.8.0 ships no such module at all (`starlette/middleware/` has no
`proxy_headers.py`; a grep for `ProxyHeaders` across the installed Starlette
package returns zero matches). uvicorn wraps the app only at server startup
(`uvicorn/config.py:543-544`), so a test that drives `app.main.app` directly
never sees the middleware and must wrap it manually:

```python
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware


async def _echo_scheme(request: Request) -> JSONResponse:
    return JSONResponse({"scheme": request.url.scheme})


def _build_proxied_app() -> ProxyHeadersMiddleware:
    """A minimal app wrapped the way uvicorn wraps the real one."""
    inner = Starlette(routes=[Route("/scheme", _echo_scheme)])
    return ProxyHeadersMiddleware(inner, trusted_hosts="*")  # type: ignore[return-value]
```

Drive it with `httpx.AsyncClient(transport=httpx.ASGITransport(app=...))`,
sending `X-Forwarded-Proto: https`, and assert the response body is
`{"scheme": "https"}`. Two details that make this work: `httpx.ASGITransport`
supplies a client address of `127.0.0.1` by default
(`httpx/_transports/asgi.py:92`), which is already inside uvicorn's default
trusted set, so `trusted_hosts` could be omitted; and the mechanism sets
`scope["scheme"]` from an accepted `x-forwarded-proto` value in
`{http, https, ws, wss}` (`uvicorn/middleware/proxy_headers.py:46-52`).

Importing the real `uvicorn` class (rather than hand-rolling a middleware) is
what keeps the test honest about production behaviour.

**Verify**: `pytest -m unit tests/test_proxy_awareness.py -q` → all pass
**Verify**: `pytest -m unit tests -q` → all pass (no regressions)

> ### 🚦 MANUAL GATE 6 — operator check
>
> **Report to the operator:**
> - `pytest -m unit tests/test_proxy_awareness.py -v` output (test names visible)
> - The full contents of `tests/test_proxy_awareness.py`
>
> **Operator verifies:**
> 1. **Test 4 actually exercises the middleware.** Ask yourself: if someone
>    deleted `--forwarded-allow-ips` from `entrypoint.sh`, would this test fail?
>    It should be answerable in the assert — the test must drive an app wrapped
>    in `uvicorn.middleware.proxy_headers.ProxyHeadersMiddleware` and assert the
>    response reflects `X-Forwarded-Proto`, not merely that a header was sent.
> 2. The import is `from uvicorn.middleware.proxy_headers import
>    ProxyHeadersMiddleware`. `starlette.middleware.proxy_headers` does not
>    exist and must not appear.
> 3. The three settings assertions cover the **independence** case (changing one
>    does not change the other) — this is the guard for the most likely future
>    mistake.
> 4. `pytest -m unit tests -q` shows no pre-existing test newly failing.
>
> Wait for `PASS` before starting Step 7.


### Step 7: Update the dev bootstrap script and the docs

`scripts/setup.sh`:

- Line 384 polls `curl -sf http://localhost:8000/api/health`. Follow the
  plaintext redirect or point it at nginx — either
  `curl -sfk https://localhost/api/health` (the `-k` tolerates an untrusted cert
  on a machine that has not run the mkcert Windows import) or follow the
  redirect. Prefer `https://localhost/api/health` so the script validates the
  TLS path.
- Lines 362, 388, 403 print `http://localhost:8000/app`. Change to
  `https://localhost/app`.

`CLAUDE.md`:

- Line 15: the "Run app (API + UI)" row says
  `PYTHONPATH=src uvicorn app.main:app --reload` → UI at `http://localhost:8000/app`.
  Keep the local-uvicorn instruction (it does not use nginx) but note the
  compose URL. Add a row or note that the Compose stack serves at
  `https://localhost/app`.
- Line 143 mentions `os.getenv("API_BASE_URL", "http://localhost:8000")`. Update
  to reference `settings.API_BASE_URL`.
- In the "Docker Compose services" table, add the `nginx` row on port 443 and
  remove the `8000` entry from the `app` row.

`USER_GUIDE.md` (lines 42–43): change `http://localhost:8000/...` to
`https://localhost/...`. Those lines describe the **Compose** workflow, which
now runs behind nginx.

`DEVELOPER_QUICK_START.md` — **do not change lines 92–93 to HTTPS.** Read the
structure first: those lines sit under *"## Option 2: PostgreSQL Only (For Local
Development)"*, alongside "Then run the app locally: `uvicorn app.main:app
--reload`". In that workflow there is **no nginx** — `uvicorn` runs natively on
the host and serves plain HTTP on 8000. Changing them to `https://localhost`
would document a URL that does not exist in that workflow.

What this file actually needs:

1. **Lines 92–93 stay as `http://localhost:8000`** but must be made
   unambiguous — they currently read as if they are the general access URLs.
   Prefix them so the reader knows which workflow they belong to, e.g.
   *"Access the services (Option 2 — app running locally, plain HTTP):"*.
2. **Add an access line to Option 1** (the Compose workflow, currently lines
   58–78), which today says only "Start both PostgreSQL and the application
   together" and never states a URL. Add that the stack is reached at
   `https://localhost/app` via nginx, and that `:8000` is no longer published.
3. **Add the certificate prerequisite** near the top, where the file lists
   "First time dev setup" (lines 3–15). A developer following this file on a
   fresh machine will otherwise run `docker compose up` and get a 443 bind
   failure or an untrusted-certificate warning, with nothing here explaining
   either. Point at Step 1 of this plan / `USER_GUIDE.md` for the mkcert
   commands rather than duplicating them.

**Verify**: `grep -n "localhost:8000" USER_GUIDE.md` → no matches

**Verify**: `grep -n "localhost:8000" DEVELOPER_QUICK_START.md` → matches
remain **only** at lines 92–93 (Option 2, local uvicorn), each now clearly
labelled as the local workflow

**Verify**: `grep -n "https://localhost" DEVELOPER_QUICK_START.md` → at least
one match, in Option 1

**Verify**: `grep -rn "localhost:8000" CLAUDE.md scripts/setup.sh` → no matches
(except any line documenting the container-internal `API_BASE_URL` value, which
legitimately stays `http://localhost:8000`)

Do not delete the Option 2 instructions to force a zero-match grep. That
workflow is unaffected by this plan — nginx only sits in front of the Compose
stack.

> ### 🚦 MANUAL GATE 7 — operator check
>
> **Report to the operator:** the four verify outputs, plus `git diff` for
> `scripts/setup.sh`, `CLAUDE.md`, `DEVELOPER_QUICK_START.md`, `USER_GUIDE.md`.
>
> **Operator verifies:**
> 1. `USER_GUIDE.md` no longer mentions `localhost:8000` anywhere.
> 2. `DEVELOPER_QUICK_START.md` **still contains** `http://localhost:8000` at its
>    Option 2 lines, now labelled as the local-uvicorn workflow. If those were
>    changed to HTTPS, the change is wrong — Option 2 has no nginx.
> 3. Option 1 in `DEVELOPER_QUICK_START.md` now states the `https://localhost/app`
>    access URL (it previously stated none at all).
> 4. `CLAUDE.md`'s Compose services table lists `nginx` on 443 and no longer
>    lists `8000` for `app`.
> 5. `scripts/setup.sh`'s health poll targets HTTPS.
>
> **Optional — this gate may be deferred.** If you would rather do all
> documentation at the end, reply `DEFER` instead of `PASS`. The executor then
> skips Step 7 in the tracker (mark it `⏸️ deferred`) and proceeds to Step 8,
> returning to Step 7 after Step 10. Do not defer if you want doc regressions
> caught early.
>
> Wait for `PASS` (or `DEFER`) before starting Step 8.

### Step 8: Run the full stack and the manual smoke test

This step cannot be automated. It needs three things the plan cannot supply:

- A **populated `.env`** (copy `.env.example` and fill it — it is 5.5 KB and has many
  required `FIXME` placeholders).
- A **working LLM credential**, because check 7 exercises the chat stream, which
  calls the LLM provider. With an absent or invalid key the stream yields no
  tokens — which looks *identical* to the nginx buffering problem check 7 exists
  to detect. Confirm the provider works before running check 7 (e.g. by testing
  the chat stream against the container directly, without nginx, first). If you
  skip this, you will misdiagnose a missing API key as a proxy fault.
- A **browser** on the machine that trusts the mkcert CA (Step 1).

```bash
docker compose up -d --build
docker compose ps
```

`docker compose ps` will show **ten** services: `postgres`, `app`, `nginx`,
`github-mcp`, `neo4j`, `rabbitmq`, `elasticsearch`, `github-producer`,
`jira-producer`, `confluence-producer`, `signal-consumer`. The three producers
and the consumer are defined without `profiles:`, so `up` starts them too — that
is expected, not a regression. What matters for this plan is that `app` reaches
healthy and `nginx` is running.

If `up` fails with `bind: address already in use` on `443` (or `80`), something
else on the host holds the port — see STOP conditions. Do not remap the port
without reporting it, since the URL in every doc change assumes 443.

Work through every check and record the observed result:

| # | Check | Command / action | Expected |
|---|---|---|---|
| 1 | nginx serves TLS | `curl -skI https://localhost/` | `HTTP/2 302`, `location: /app` |
| 2 | Health over TLS | `curl -sk https://localhost/api/health` | `{"status":"healthy"}` |
| 3 | Node 8000 is closed | `curl -s -m 5 http://localhost:8000/api/health` | connection refused / no response |
| 4 | UI loads | browse `https://localhost/app` | Graph page renders, styled (CSS loaded from `/app/assets/`) |
| 5 | Dash callbacks work | click through to Search, run a query | results render — proves `/app/_dash-update-component` is proxied |
| 6 | API through the proxy | browse `https://localhost/api/v1/connectors/` | JSON connector list |
| 7 | **SSE stream** | open Chat, send a message | **tokens appear progressively**, not all at once at the end |
| 8 | Docs unreachable | `curl -skI https://localhost/docs` | 404 (not routed) |
| 9 | Certificate trusted | browse `https://localhost/app` | no browser warning (requires Step 1's Windows import) |

Check 7 is the one most likely to fail and the reason Step 2 exists. If tokens
arrive all at once, `proxy_buffering off` is not taking effect — verify the
`location /api/v1/chats/` block is present and that nginx reloaded
(`docker compose restart nginx`).

**Verify**: all nine checks pass; paste observed outputs into the completion note

> ### 🚦 MANUAL GATE 8 — operator sign-off (the largest gate)
>
> Step 8 *is* the human test, so this gate is your own sign-off rather than a
> hand-off. Work the nine-check table yourself; the executor supplies the stack
> and the commands, but the observations are yours.
>
> **Record in the plan or a scratch note, for each of the nine checks, the
> command and its observed output.** Do not accept "looks fine" — check 7 in
> particular requires actually watching tokens arrive.
>
> **Sign-off criteria:**
> 1. All nine checks pass.
> 2. Check 7 (SSE) showed tokens **progressively**. If they arrived in one burst,
>    `proxy_buffering off` is not effective — do not sign off, even if the chat
>    eventually completes.
> 3. Check 9 showed **no** browser certificate warning, which confirms Step 1's
>    Windows import worked.
> 4. The UI rendered **with styling** (check 4) — an unstyled page means
>    `/app/assets/*` is not being proxied.
>
> Reply `PASS` to proceed to Step 9, or `FAIL` with the check number that failed.

### Step 9: Run every CI gate

```bash
pytest -m unit tests -q
mypy src/
pylint src --score=y
bandit -c .bandit.yml -r src/ -lll
flake8
```

**Verify**: each exits 0; `pylint` reports ≥ 9.0

> ### 🚦 MANUAL GATE 9 — operator check
>
> **Report to the operator:** the full output of all five commands, including
> the `pylint` score line and the `pytest` summary line.
>
> **Operator verifies:**
> 1. All five exit 0. `pylint` shows a score of at least `9.0`.
> 2. The `pytest` summary shows the new tests in
>    `tests/test_proxy_awareness.py` ran (not skipped) and passed.
> 3. `mypy` reports no errors — in particular no new error in `settings.py` or
>    the nine Dash files.
> 4. `bandit` reports no High-severity issue.
> 5. `flake8` is clean. It is **not** a CI gate, but a failure here usually
>    means an unused `import os` survived Step 5.
>
> Wait for `PASS` before starting Step 10.

### Step 10: Document new-machine setup in `USER_GUIDE.md`

Do this **last**, after every check in Step 8 and Step 9 passes. Documenting
first risks writing instructions for a flow that then changes.

`USER_GUIDE.md` currently describes a new-machine setup that no longer works
once this plan lands. Three specific statements are now false, and each will
actively mislead someone following the guide:

- **Line 39**: *"Application starts and listens on port 8000"* — the app no
  longer publishes 8000; only nginx on 443 does.
- **Lines 42–43**: `http://localhost:8000/api/health` and
  `http://localhost:8000/app` — both now HTTPS on 443, without the port.
- **Line 159**: *"Port conflicts: Ensure ports 5432 and 8000 are not in use"* —
  should refer to 80/443, since those are what nginx now binds.

Rewrite the "First-Time Setup" and "Access the application" sections so a
person on a **fresh machine** can follow them end to end. Cover, in this order:

1. **Updated prerequisites** (replacing the current three-item list). Docker and
   Docker Compose; Python 3; **`mkcert`**; **`openssl`** (present by default on
   most Linux distributions — mention it only as a fallback note for generating
   a temporary cert if `mkcert` is unavailable); and, **for WSL2 users, access
   to the Windows certificate store** for the one-time CA import.

2. **Generate the TLS certificate** — the exact commands from Step 1, presented
   as a copy-paste block, with a plain-language explanation of *why* (nginx
   serves HTTPS, and the browser needs to trust the cert or it warns). Keep the
   WSL2 caveat prominent and non-negotiable: it is the single step most likely
   to be skipped, and skipping it produces a scary browser warning that looks
   like the deployment is broken.

3. **The `.env` step** — point at `./scripts/setup.sh` as the happy path
   (it is idempotent and already documented), and note that
   `EXTERNAL_BASE_URL=https://localhost` should be set. It has a working
   default, so the guide should say it is defaulted and only needs changing for
   a non-`localhost` hostname.

4. **Start the stack and open the app** — `docker compose up -d`, then
   `https://localhost/app`. State explicitly that `http://localhost:8000` is
   **expected to fail** — this is the deliberate consequence of removing the
   published port, and a reader will otherwise treat it as a fault to fix.

5. **A short troubleshooting subsection** for the failures a new machine
   actually hits, each with symptom → cause → fix:
   - Browser warns about the certificate → the Windows-side CA import was
     skipped (Step 1).
   - `docker compose up` fails with `bind: address already in use` on 80/443 →
     another process holds the port.
   - `https://localhost/app` returns 502 → the `app` container is not healthy;
     check `docker compose logs app`.
   - `deploy/certs/` is empty → `mkcert` was never run, or it was run from a
     different working directory than the repo root.

6. **Update the Quick Reference table** (lines 199–209) so its "Start services"
   and access rows reflect HTTPS, and add a row for regenerating the
   certificate.

**Constraints on this edit:**

- Do **not** rewrite unrelated sections (logs, stopping, container access,
  file locations). They are still accurate.
- Do **not** document a self-signed-certificate fallback as an equal
  alternative to `mkcert`. If you mention it, frame it as a last resort — it
  changes the trust story and the plan deliberately chose `mkcert` for that
  reason.
- Do **not** add runnable cert-generation to `scripts/setup.sh`. That script is
  idempotent and non-interactive-friendly; silently issuing certificates on
  every run is out of scope here. Documentation only.
- Keep the existing tone and heading style — second person, `###` subsections,
  fenced `bash` blocks. Match the surrounding file.

**Verify**: `grep -n "localhost:8000" USER_GUIDE.md` → no matches

**Verify**: a person following only the rewritten section, on a machine with
Docker installed and nothing else configured, reaches a working
`https://localhost/app`. If you cannot test that literally, walk the steps
yourself in order and confirm each command's output matches what the guide
claims — and say in the completion note that the fresh-machine path was
walked, not just written.

> ### 🚦 MANUAL GATE 10 — operator check (final)
>
> **Report to the operator:** the two verify outputs and `git diff USER_GUIDE.md`.
>
> **Operator verifies:**
> 1. `grep -n "localhost:8000" USER_GUIDE.md` → no matches.
> 2. The rewritten guide covers, in order: prerequisites (including mkcert and
>    the WSL2 caveat), cert generation, the `.env` step, starting the stack, and
>    troubleshooting.
> 3. The guide **explicitly states** that `http://localhost:8000` is expected to
>    fail — otherwise a new reader treats the removed port as a bug.
> 4. The Quick Reference table reflects HTTPS.
> 5. **Walk the guide as a new user would.** If you have a second machine or a
>    clean container, use it. If not, follow the steps literally in a fresh
>    shell and confirm each command's output matches what the guide claims.
> 6. No self-signed-certificate alternative is presented as an equal option to
>    `mkcert`.
>
> Wait for `PASS` before starting Step 11.

### Step 11: Write the nginx / TLS design document

Create `docs/design/nginx-tls-design.md`.

This plan's work is currently recorded only as a plan, and plans are deleted
when they land (see `plans/README.md`: "an absent plan number means the work
shipped"). Without a design document, the reasoning behind the whole TLS and
proxy arrangement disappears at merge time, leaving only the config files. Plan
C (Keycloak) also depends on decisions recorded here — particularly the
`/auth` path reservation and the `EXTERNAL_BASE_URL` contract.

**Follow the house style of `docs/design/scan-scheduler-design.md`** — read it
first. Structure to match:

- `# <Title>` (H1), then `## Overview` — prose, no bullets, explaining what
  exists and why.
- `## Design Decisions` — a table with columns
  `| # | Decision | Choice | Rationale |`. This is the file's core; each row is
  one decision someone might otherwise relitigate.
- Then `##` sections for the workings (topology, routing, lifetime, etc.).
- Mermaid is used elsewhere in `docs/design/` for diagrams; use it if a diagram
  helps, but do not add one purely for decoration.

**Content the document must cover.** Every item below is a decision this plan
made, with its justification — do not invent new decisions:

1. **Why a reverse proxy at all.** TLS terminates at nginx; the application
   serves plain HTTP internally. The alternative (app handles TLS directly) was
   rejected because it couples certificate management to the app image and
   because the AWS target terminates TLS at API Gateway, not in the app.

2. **URL topology.** Single host, path-based: `/app` → Dash UI, `/api` → API,
   `/` → 302 to `/app`. State that this keeps UI and API on one origin, so no
   CORS is ever required, and one stable origin simplifies Plan C's
   `redirect_uri`.

3. **Why the app must be proxy-aware.** The app never derives its external
   scheme or host from its own listener. `EXTERNAL_BASE_URL` is the
   browser-facing URL; `API_BASE_URL` is the container-internal one. Explain
   that these are deliberately different values and why conflating them breaks
   every Dash callback. This contract is what Plan C builds `redirect_uri` from.

4. **`X-Forwarded-*` handling and uvicorn flags.** nginx sets
   `X-Forwarded-Proto`/`Host`/`For`; uvicorn consumes them via
   `ProxyHeadersMiddleware`, which is **on by default** — the flag that matters
   is `--forwarded-allow-ips`. Record the coupling: `*` is safe only because the
   app publishes no host port.

5. **The SSE stream exception.** `/api/v1/chats/` requires
   `proxy_buffering off`, and why (a POST SSE stream called directly from the
   browser via `stream-bridge.js`). Note that any future streaming endpoint must
   be added to this location.

6. **Reserved `/auth` path.** Reserved for Keycloak (Plan C), currently
   commented out, with the forwarding directives Plan C will need. Note
   Keycloak's `KC_HTTP_RELATIVE_PATH=/auth` and `KC_PROXY_HEADERS` requirements.

7. **Port exposure.** Only nginx publishes 443 (and 80, for the redirect).
   The app publishes nothing. This is what makes TLS enforced rather than
   advisory. Note the healthcheck still runs in-container on 8000.

8. **Certificate policy.** mkcert for local development, certs in
   `deploy/certs/`, gitignored, never committed. The WSL2/Windows trust-store
   split and the one-time import step. State plainly that this is a **local-dev**
   mechanism and that a real deployment needs a real certificate — do not imply
   mkcert is production-appropriate.

9. **Internal traffic stays plain HTTP.** Decided deliberately: TLS terminates
   at the edge, and container-to-container traffic uses the Docker bridge. Record
   it as a decision so it is not mistaken for an oversight, and note what would
   have to change to reverse it.

10. **AWS API Gateway relationship.** The same code runs behind API Gateway,
    which also terminates TLS and forwards plain HTTP. This works *because* the
    app derives nothing from its listener. Note the ~29–30s API Gateway
    integration timeout as a known constraint on the SSE stream.

**Constraints:**

- **Do not duplicate `docs/design/authn-authz-design.md`.** That document owns
  authentication, sessions, cookies, and Keycloak's realm. This one owns the
  transport layer: proxy, TLS, paths, and the external-URL contract. Cross-
  reference it for Plan C rather than restating it.
- **Do not document the rollout plan, step ordering, or manual gates** — that is
  the plan's job, and it will be deleted. This document describes the end state.
- **No secret values, no certificate contents, no key material.** Paths and
  credential *types* only.
- Record actual values (port numbers, header names, env var names, paths), not
  placeholders — a reader should not need the config files to follow it.

**Verify**: `test -f docs/design/nginx-tls-design.md` → exit 0
**Verify**: `grep -c "^## " docs/design/nginx-tls-design.md` → at least 3 top-level sections
**Verify**: `grep -q "Design Decisions" docs/design/nginx-tls-design.md` → exit 0
**Verify**: `grep -n "EXTERNAL_BASE_URL\|API_BASE_URL\|proxy_buffering\|/auth\|443" docs/design/nginx-tls-design.md` → all of these terms appear

> ### 🚦 MANUAL GATE 11 — operator check (final)
>
> **Report to the operator:** `git status --short docs/design/`, the file's
> section headings (`grep -n "^## " docs/design/nginx-tls-design.md`), and the
> full text.
>
> **Operator verifies:**
> 1. The document reads as an **end-state design**, not a plan: no step numbers,
>    no gates, no "Step N" references.
> 2. All ten content points above are addressed.
> 3. It does not restate auth/session/Keycloak detail — it cross-references
>    `docs/design/authn-authz-design.md` instead.
> 4. `EXTERNAL_BASE_URL` vs `API_BASE_URL` is explicitly called out as a
>    deliberate distinction, since conflating them is the most likely future
>    regression.
> 5. Internal plain-HTTP traffic is recorded as a decision, not omitted.
> 6. No certificate contents, keys, or secret values appear.
> 7. A new engineer could read only this document and understand why the proxy
>    exists and how to add a route to it.
>
> Reply `PASS` to close the plan, then update the Progress tracker and
> `plans/README.md`.

## Test plan

- **New tests**: `tests/test_proxy_awareness.py`, module-level
  `pytestmark = pytest.mark.unit`, covering the four cases in Step 6.
  Structural pattern: `tests/test_timezone_settings.py`.
- **Regression**: the existing suite must pass unchanged. The nine
  `API_BASE_URL` edits change only where the value comes from, not its default,
  so no existing test should be affected. If a test breaks, it is because a
  module-level constant was previously evaluated before an env override — treat
  that as a real finding and report it rather than adjusting the test.
- **Verification**: `pytest -m unit tests -q` → all pass, including the 4+ new
  tests.

## Done criteria

ALL must hold:

- [ ] `docker compose config -q` exits 0
- [ ] `grep -n "8000:8000" docker-compose.yml` → no matches
- [ ] `grep -c "443:443" docker-compose.yml` → 1
- [ ] `grep -rn 'os.getenv("API_BASE_URL"' src/` → no matches
- [ ] `grep -c "proxy-headers" src/app/entrypoint.sh` → **0** (the flag is a
      no-op default; only `--forwarded-allow-ips` is added)
- [ ] `grep -n "forwarded-allow-ips" src/app/entrypoint.sh` → 1 match
- [ ] `pytest -m unit tests -q` exits 0, including new tests in `tests/test_proxy_awareness.py`
- [ ] `mypy src/` exits 0
- [ ] `pylint src --score=y` reports ≥ 9.0
- [ ] `bandit -c .bandit.yml -r src/ -lll` exits 0
- [ ] `flake8` exits 0
- [ ] `git status --short` does **not** list any `.pem` file anywhere
- [ ] The nine manual smoke checks in Step 8 all recorded as passing
- [ ] `grep -n "localhost:8000" USER_GUIDE.md` → no matches (Step 10)
- [ ] `USER_GUIDE.md` documents mkcert, the WSL2 CA import, `https://localhost/app`,
      and the expectation that `:8000` fails
- [ ] `grep -n "localhost:8000" DEVELOPER_QUICK_START.md` → matches only in
      Option 2 (local uvicorn), each labelled as such
- [ ] `grep -n "https://localhost" DEVELOPER_QUICK_START.md` → Option 1 states
      the HTTPS URL
- [ ] `grep -rn "localhost:8000" CLAUDE.md scripts/setup.sh` → no matches
- [ ] No files outside the Scope list are modified (`git status`)
- [ ] **All 11 manual gates recorded `✅` in the Progress tracker**
- [ ] `docs/design/nginx-tls-design.md` exists and is non-empty (Step 11)
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report back (do not improvise) if:

- The code at the locations in "Current state" does not match the excerpts —
  in particular if `docker-compose.yml` no longer publishes `8000:8000` at
  lines 68–69, or if `entrypoint.sh`'s uvicorn line has already been changed.
- More or fewer than nine `os.getenv("API_BASE_URL", ...)` sites exist. The
  count is load-bearing; report the actual list rather than adapting silently.
- `uvicorn.middleware.proxy_headers.ProxyHeadersMiddleware` is not importable.
  (It is expected to be importable in uvicorn 0.54.0 — if it is not, the
  installed version differs from the plan's assumption.)
- `docker compose up` fails with `bind: address already in use` on port 80 or
  443. Something else on the host holds the port. Do **not** silently remap the
  published port — every URL change in Step 7 assumes 443, so remapping would
  make the docs wrong. Report which process holds the port and stop.
- Step 1's `mkcert -install` cannot write to a trust store, or the Windows-side
  CA import is unavailable. Report it; do not fall back to a self-signed cert,
  because that changes the trust story the plan documents.
- The SSE smoke check (Step 8, check 7) fails after one attempt at fixing the
  buffering block.
- Any Step 8 check reveals a regression in an existing feature — e.g. the
  collaboration pages fail to render. Those pages call the graph service
  in-process today (`docs/design/authn-authz-design.md`, "Non-API Surfaces"),
  so they should be unaffected by this plan; a failure there means an
  assumption here is wrong.
- A change appears to require touching an out-of-scope file — in particular
  anything under `src/connectors/`, or adding `AUTH_*` / `KEYCLOAK_*` settings.
- `mkcert` cannot be installed in the target environment.

## Maintenance notes

**What future changes interact with this:**

- **Plan B** (`docs/design/authn-authz-design.md`) replaces the nine
  `API_BASE_URL` call sites with a shared HTTP client that attaches a bearer
  token. The `settings.API_BASE_URL` field added in Step 5 is the value that
  client should use. Do not re-introduce per-site reads.
- **Plan C** adds Keycloak. Two couplings this plan creates:
  1. It must set `AUTH_COOKIE_SECURE=true`. Now that TLS terminates at nginx,
     a cookie without `Secure` would be sent over any plaintext request — and
     this plan deliberately left that setting out, so there is no guard yet.
     Derive it from `EXTERNAL_BASE_URL`'s scheme rather than hardcoding.
  2. It enables the commented `/auth` block in `deploy/nginx/nginx.conf` and
     must configure Keycloak with `KC_HTTP_RELATIVE_PATH=/auth` and
     `KC_PROXY_HEADERS=xforwarded`, or Keycloak will emit URLs that do not
     match this path layout.
- **Any new streaming endpoint** must be added to the `proxy_buffering off`
  location, or it will exhibit the same silent buffering problem as the chat
  stream.
- **A real hostname or domain**: change `server_name` in the nginx config, add
  the name to the `mkcert` invocation in Step 1, reissue the cert, and update
  `EXTERNAL_BASE_URL`. The original `deploy/certs/*.pem` must be regenerated,
  not reused — a cert issued only for `localhost` will be rejected for a real
  hostname.
- **AWS API Gateway migration**: because the app derives nothing from its own
  listener, this becomes configuration. API Gateway terminates TLS and forwards
  plain HTTP, matching what nginx does here. Two differences to plan for:
  API Gateway's integration timeout is ~29–30s (see the design doc — this will
  affect the SSE stream, which is why the nginx `proxy_read_timeout` here is
  deliberately long), and nginx's `X-Forwarded-*` headers must be reproduced by
  the gateway's configuration.
- **Certificate expiry**: mkcert certs default to ~2 years. When they expire the
  browser shows a warning and `curl` without `-k` fails. Re-run the mkcert
  commands from Step 1.

**What a reviewer should scrutinize:**

- That `8000:8000` is genuinely gone from `docker-compose.yml` — this is the
  single line that makes TLS enforced rather than advisory.
- That the SSE location block (`/api/v1/chats/`) sets `proxy_buffering off` and
  `proxy_cache off`. Its file position relative to the general `/api` block is
  irrelevant — nginx uses longest-prefix match — so do not spend review time on
  ordering.
- That `--forwarded-allow-ips="*"` is paired with the unpublished port (the
  justification only holds if the app has no host port).
- That no `AUTH_*` or `KEYCLOAK_*` settings were added — those are Plan C.
- That the nine `API_BASE_URL` sites kept their **default value**; only the
  source of the value changed.
- That no `.pem` file is committed.

**Explicitly deferred out of this plan:**

- `AUTH_COOKIE_SECURE` and session settings — Plan C, per the decision to avoid
  dead config that nothing reads.
- TLS for container-to-container traffic — deliberately excluded. Internal
  traffic stays plain HTTP on the Docker bridge. If that changes, every
  `API_BASE_URL` site, the producers' `API_SERVER`, and a CA bundle mounted into
  every service image are all in scope.
- Hiding FastAPI's `/docs`, `/redoc`, `/openapi.json` — they become unreachable
  from outside the Docker network as a side effect, but formally disabling them
  is Plan E.
- Consolidating request plumbing and timeouts into a shared client — Plan B.

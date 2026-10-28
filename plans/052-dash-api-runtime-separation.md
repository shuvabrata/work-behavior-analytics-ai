# Plan 052: Separate the Dash UI and the API into independent runtimes

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
> **Drift check (run first)**: `git diff --stat 5210f00..HEAD -- src/app/main.py src/app/entrypoint.sh src/app/settings.py src/app/runtime_settings.py src/app/dash_app src/common src/connectors Dockerfile.app requirements.app.txt docker-compose.yml deploy/nginx/nginx.conf tests/conftest.py .github/workflows/pr_checks.yml`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding.
>
> **Benign drift** — do not stop for these, they do not touch any step:
> - `CLAUDE.md` shows an uncommitted change to the "Integration tests" row and
>   a new `server`-marked-tests paragraph. This is a Plan 051 follow-up, not
>   part of this plan. The lines this plan edits are in the Commands table
>   (the "Run app" row) and the Compose services table.
> - Any change under `src/app/dash_app/pages/` that is not an import line.
> - The drift check names `Dockerfile.app` and `requirements.app.txt`, which
>   exist. `Dockerfile.api`, `Dockerfile.ui`, `requirements.api.txt` and
>   `requirements.ui.txt` do **not** exist at drift-check time — Step 11 creates
>   them by rename and new file. Do not treat their absence as a mismatch, and
>   do not create them early.
>
> Any other mismatch is a STOP condition.

## Status

- **Priority**: P1
- **Effort**: XL (largest plan in the AuthN/AuthZ programme — ~1.5–2× Plan 051)
- **Risk**: HIGH
- **Depends on**: Plan 051 (TLS + proxy-awareness) — merged as `5210f00`
- **Category**: architecture | security
- **Planned at**: commit `5210f00`, 2026-10-28
- **Design reference**: `docs/design/authn-authz-design.md`, "Plan B Scope"
- **Executed**: not yet

## Why this matters

Today a single FastAPI process owns both the `/api/v1` surface and the Dash UI
(`src/app/main.py:195` mounts `WSGIMiddleware(dash_app.server)` at `/app`). That
makes "the API is the product" a convention rather than a property: nothing
structurally prevents a Dash callback from reaching Neo4j directly, and three
of them do.

Plan C locks `/api/v1` behind Keycloak. **Locking it down while any component
still reaches a database directly would either break that component or leave an
unauthenticated path to the data stores.** Plan B is what makes Plan C safe to
attempt.

Two properties are delivered, and they are **not the same property**:

1. **Isolation** — the UI runtime cannot reach a database at all. It holds no
   database driver, no data-store credentials, and no LLM/provider key. The
   container split provides this.
2. **Adequacy** — the API exposes every capability the UI needs, so a different
   frontend could be built against it today. The API-completeness audit
   (Step 15) provides this.

The container split alone does **not** deliver (2), and neither property
authenticates anyone — Plan C remains independently necessary.

### Explicit non-goals

- **The container split is not a substitute for authorizing the API.**
- **Renaming the `src/app/` package to `src/api/`** — deliberately deferred to a
  separate follow-on plan. It is cosmetic (238 files import `app.*`), carries no
  isolation gain, and this plan's test fallout is already its largest risk.
- **Per-user configuration, per-person data scoping, Keycloak, infrastructure
  hardening** — Plans D, F, C, E.

## Current state — verified at `5210f00`

Everything in this section was measured against the live tree. Where a design-doc
figure disagrees, the measured figure is used and the discrepancy is noted.

### The single-runtime coupling

`src/app/main.py` (195 lines) builds one `FastAPI(lifespan=lifespan)` that:

- starts `scheduler_loop` (`:120`)
- opens a RabbitMQ connection and starts the runtime-settings listener
- loads DB overrides via `load_db_overrides_from_session` (`:47`)
- closes the Neo4j driver on shutdown
- includes 11 routers under `/api` and `/api/v1` (`:166-176`)
- mounts Dash at `/app` (`:195`)

`add_request_context` (`:161-181`) wraps **every** request, including all Dash
traffic, injecting `X-Request-ID` and a `LogContext`.

### The Dash layer is already DB-free

A grep across `src/app/dash_app/` for `sqlalchemy`, `AsyncSession`,
`ASYNC_SESSION_LOCAL`, `GraphDatabase`, `get_driver`, `Elasticsearch(`, `pika.`,
`app.db`, `alembic` returns **no matches**. The isolation is real at the code
level; it is simply not *enforced*, because the container can still reach
Postgres and Neo4j. This is what makes the plan tractable.

`dash_app/` is 82 files / ~26,000 LOC. **35 files (~20,800 LOC) import something
outside `app.dash_app`.** (The design doc says 30 files / ~19,000 LOC; the
measured figures are used here.)

| Imported module | UI files | Import sites (all of `src/` + `tests/`) |
|---|---|---|
| `app.settings` | 15 | 59 |
| `app.runtime_settings` | 13 | 24 |
| `app.common.timezone` | 8 | 9 |
| `app.analytics.collaboration.config` | 6 | 19 (whole `app.analytics.*`) |
| `app.common.person_network_url` | 3 | — |
| `app.common.graph_theme` | 3 | 10 |
| `app.analytics.collaboration.ego` | 3 | — |
| `app.api.graph.v1.service` | 2 | 2 |
| `app.api.connectors.v1.registry` | 2 | 6 |
| `app.analytics.collaboration.errors` | 2 | — |
| `app.scripts.create_es_indexes` | 1 | 4 |
| `app.common.node_size` | 1 | — |
| `app.api.search.v1.service` | 1 | 1 |
| `app.api.search.v1.model` | 1 | — |
| `app.analytics.registry` | 1 | — |

### The three in-process bypasses

A request to the unauthenticated `POST /app/_dash-update-component` reaches these
without touching `/api/v1`. **Securing the API alone would leave them open.**

| Callback | Import | Reaches | Endpoint to use instead |
|---|---|---|---|
| `pages/collaboration_network/callbacks/filter.py:12` | `get_collaboration_network` | Neo4j | `GET /api/v1/graph/collaboration-network` |
| `pages/collaboration_network_ego/callbacks/filter.py:13` | `get_ego_network` | Neo4j | `GET /api/v1/graph/collaboration-network/ego` |
| `pages/graph/callbacks/spotlight.py:14` | `search_in_graph` | Elasticsearch | `GET /api/v1/search` — **needs an `ids` param, see Step 10** |

### The API imports the UI (a backwards edge)

`src/app/api/graph_themes/v1/service.py:28` imports
`from app.dash_app.styles import get_theme_tokens`. This is the **only** real
API→UI import (two others at `app/common/graph_theme.py:5,35` and
`app/db/models/graph_theme.py:5` are docstrings).

`get_theme_tokens` is load-bearing for all of `styles.py`: it is defined at
`styles.py:288`, immediately called at `:296` (`TOKENS = get_theme_tokens()`),
and everything below derives from it. It is **not** a function that can be lifted
without moving `THEME_TOKENS` too.

After the split, leaving this in place would force `Dockerfile.api` to ship
`src/app/dash_app/styles.py` — dragging the UI package into the API image.

### A real secret is read by the UI layer

`pages/connectors/layout.py:966-978` renders a three-row env table by reading
`settings.GITHUB_MCP_ENABLED`, `settings.GITHUB_MCP_SERVER_URL` and
`settings.GITHUB_MCP_TOKEN` directly from the UI process's environment.

`_mask_secret_ui` (`layout.py:790-792`) returns a fixed `"••••••••"` and never
any part of the value, so the token is **not** currently displayed. The defect is
that keeping this page working requires passing a GitHub PAT into the UI
container's `environment:` — contradicting this plan's stated purpose.

**A safe path already exists.** `GITHUB_MCP_TOKEN` is a DB-backed
`application_settings` row with `is_sensitive = true`
(`alembic/versions/2026_08_10_0800-3f1a2b4c5d6e:47`). `GET /api/v1/settings/`
already returns it with `value: "*******"`, `is_sensitive: true` and
`is_configured: true|false` (`api/settings/v1/service.py:236-247`).
`_env_row` only ever uses `bool(current)` and the masked display, so
`is_configured` is exactly the fact it needs.

Also: `pages/graph/utils/data_transform.py:176` interpolates
`settings.NEO4J_URI` into a user-facing error message, exposing internal
topology to the browser.

### 12 module-level constants freeze runtime settings at import

| File | Line | Expression |
|---|---|---|
| `pages/chat.py` | 37 | `TIMEOUT_SECONDS = runtime_settings.get_int("HTTP_REQUEST_TIMEOUT")` |
| `pages/connectors/callbacks.py` | 42 | same |
| `pages/catalog/callbacks.py` | 20 | same |
| `pages/catalog/editor_callbacks.py` | 28 | same |
| `pages/catalog/editor_test_callbacks.py` | 31 | same |
| `pages/graph/callbacks/catalog.py` | 31 | same |
| `pages/graph/callbacks/context_menu.py` | 24 | same |
| `pages/graph/callbacks/expansion.py` | 21 | same |
| `pages/graph/callbacks/query.py` | 31 | same |
| `pages/settings/runtime.py` | 60 | `API_BASE = settings.API_BASE_URL` |
| `pages/settings/graph_styling/callbacks.py` | 43 | `API_BASE = settings.API_BASE_URL` |
| `components/setup_banner.py` | 20 | `SETTINGS_API = settings.API_BASE_URL + "/api/v1/settings/"` |

**This is a real, pre-existing bug, verified empirically.** After
`runtime_settings.refresh(RuntimeConfig(HTTP_REQUEST_TIMEOUT=999))`, the cache
reads `999` while `chat.TIMEOUT_SECONDS` still reads `60`. Editing
`HTTP_REQUEST_TIMEOUT` in the Settings UI has never taken effect in those nine
modules.

**It gets worse after the split.** The UI's cache will be seeded from
`RuntimeConfig()` *code defaults* (env-fallback only), so those constants may
freeze to `60` even when `.env` says otherwise.

The codebase already has 41 function-local reads, which is the correct pattern.

### Dash's pathname contract

Verified at runtime: `type(dash_app) == dash.Dash`, `dash_app.server` is a
`flask.app.Flask`, `requests_pathname_prefix == "/app/"`, and
`routes_pathname_prefix` defaults to **`"/"`** (not to
`requests_pathname_prefix`). Dash registers its Flask handlers at the root, and
the `/app` mount is what makes them browser-visible.

Dash's registered Flask routes today: `/static/<path:filename>`,
`/assets/<path:filename>`, `/_dash-component-suites/...`, `/_dash-layout`,
`/_dash-dependencies`, `/_dash-update-component`, `/_reload-hash`,
`/_favicon.ico`, `/`, `/<path:path>`.

**Verified fix for standalone serving:** constructing
`dash.Dash(requests_pathname_prefix='/app/', routes_pathname_prefix='/app/')`
registers handlers natively at `/app/_dash-layout`,
`/app/_dash-update-component`, `/app/`, `/app/<path:path>`, etc. No `a2wsgi`, no
mount semantics, no `X-Forwarded-Prefix`.

`display_page` (`layout.py:139-176`) matches **18 hardcoded `/app/...` route
strings**, and the UI contains **69 hardcoded `/app/` literals**. All keep
working under a `/app`-rooted standalone Dash served behind an nginx
`location /app` with no trailing slash on `proxy_pass`.

### The spotlight regression is real, not theoretical

`search_in_graph` (`api/search/v1/service.py:194-250`) is explicitly **not**
equivalent to `search`. Its own docstring (`:200-203`) says it "eliminates the
top-N clipping problem": scoped, `body["size"] = len(graph_wba_ids)` (`:223`) and
all matches return in one request. Unscoped `search` uses `page_size` (`:150`)
under an `_ES_MAX_RESULT_WINDOW` cap (`:144`).

Verified live against the populated stack:

| Call | Result |
|---|---|
| `GET /api/v1/search?q=review` | `total = 22`, `page_size = 20`, returned 20 |
| Canvas node count (from the collab response) | 223 |

So a literal swap to the unscoped endpoint **would** change which nodes
highlight. Step 10 adds an `ids` param instead.

### Live stack facts (used for gate expectations)

The stack is populated: `GET /api/v1/graph/collaboration-network?lookback_days=90`
returns `num_people = 223`, `num_pairs = 4818`, `num_communities = 23`,
`modularity = 0.2382`, `elements = 5041`, in a **1.67 MB** response. That size
matters for the concurrency gate (Step 16) — it is why Plan 051's
`client_max_body_size` defect bit.

**The OpenAPI schema is not reachable over TLS.** `GET https://localhost/openapi.json`
→ **404** (Plan 051's deliberate consequence). It **is** reachable
container-internally: `docker exec wba-ai-app python -c "...urllib...'http://localhost:8000/openapi.json'"`
→ 39 paths. The audit step (Step 15) must run inside the API container.

### Compose wiring that the rename touches

`app: service_healthy` appears in **5 `depends_on` blocks**:
`nginx` (`:116`), `github-producer` (`:227`), `jira-producer` (`:250`),
`confluence-producer` (`:273`), `signal-consumer` (`:304`).

`API_SERVER=http://app:8000/` appears in **4 compose `environment:` blocks**
(`:218`, `:241`, `:264`, `:288`) plus defaults in `.env.example:106`,
`common/runtime_settings/config.py:77`, `app/settings.py:85`,
`api/settings/v1/models.py:116`, and `consumers/main.py:206`.

**Precedence trap:** `_resolve_source` (`api/settings/v1/service.py:108`) is
**DB override > env value > code default**. `API_SERVER` is also a DB-backed
`application_settings` row (`alembic/versions/.../3f1a2b4c5d6e:109`), so a
persisted row beats any env change. Step 12 must check whether a row exists and
state which wins, rather than assuming the env edit takes effect.

**Failure mode is silent.** `fetch_runtime_snapshot` already degrades to
env/defaults on any failure (`common/runtime_settings/client.py:55-63`), so a
missed rename surfaces as a scan quietly using stale settings, not an error.

### `common/runtime_settings` is pure by accident

I verified that `import common.runtime_settings` does **not** pull `aio_pika` —
its `__init__.py` imports only `cache`, `client` and `config`. But `events.py`
sits in the same package and **does** import `aio_pika`, and is imported by 5
files: `connectors/producers/daemon_common.py:50`,
`connectors/consumers/main.py:56`, `app/main.py:29`,
`app/api/settings/v1/service.py:19`, `tests/test_settings_rabbitmq.py:37`.

Its two symbols are `publish_settings_changed` and `listen_for_settings_changed`.

### Test landscape

Baseline: **`pytest -m unit tests -q` → 2340 passed, 0 failed, 2 skipped.**

Import fallout from the moves in this plan:

| Import group | Test files |
|---|---|
| `app.dash_app.*` (deep paths) | 43 |
| `app.common.*` | 12 |
| `app.analytics.*` | 9 |
| `app.scripts.*` | 5 |
| `app.runtime_settings` | 3 |

Deep paths that change: `pages.connectors.callbacks` (15),
`pages.settings.graph_styling` (14), `styles` (11),
`pages.settings.graph_styling.components` (11), `pages.chat` (10),
`pages.collaboration_network_ego.layout` (9), …

`tests/` has 156 `test_*.py` files: 131 flat plus subdirectories `tests/app/`,
`tests/neo4j_queries/`, `tests/producers/`, `tests/property_validation/`,
`tests/z_collab_validation/`. Three subdirectories carry their own `conftest.py`.

### CI and requirements

`.github/workflows/pr_checks.yml` installs
`-r requirements.app.txt -r requirements.github-producer.txt -r requirements.jira-producer.txt -r requirements.confluence-producer.txt -r requirements_dev.txt`
in the `pytest-unit` (`:31`), `pylint` (`:86`) and `mypy` (`:114`) jobs.

`requirements.app.txt` currently includes `neo4j`, `elasticsearch`,
`sqlalchemy[asyncio]`, `asyncpg`, `openai`, `langchain*`, `mcp[cli]`, `aio-pika`,
`a2wsgi`, `cryptography`, `networkx`, `python-louvain`, `matplotlib`, `tiktoken`
— none of which the UI runtime may hold.

`gunicorn` is **not installed** anywhere (`grep` across `requirements*.txt` and
`Dockerfile*` → empty).

### Local dev

Two documents instruct developers to run one process:
`CLAUDE.md:15` (`PYTHONPATH=src uvicorn app.main:app --reload`) and
`DEVELOPER_QUICK_START.md:106,134`. After Step 6, `app.main` no longer exists as
a single mount point.

`scripts/setup.sh` polls `https://localhost/api/health` (`:384`) and its failure
message says `docker compose logs app` (`:400`).

## Decisions taken during planning

Recorded so they are decisions rather than omissions. Each was resolved by the
operator during a structured interview.

| # | Decision | Choice |
|---|---|---|
| 1 | Container strategy | **Two images** (`Dockerfile.api`, `Dockerfile.ui`). A shared image leaves the UI holding `neo4j`/`openai`/DB passwords, so the boundary stays conventional |
| 2 | The UI runtime | **Pure WSGI** — `create_dash_app()` → `dash_app.server` (Flask) behind **gunicorn**. No FastAPI, no `a2wsgi` in the UI. Textbook separation; Plan C's middleware section is revised accordingly |
| 3 | Shared settings | **`UISettings`** in `src/domain/settings.py`; **`ApiSettings(UISettings)`** in `src/app/settings.py`. The type system enforces the boundary — `ApiSettings` cannot be built without `DATABASE_URL`, `UISettings` has no secret field |
| 4 | Shared package | **`src/domain/`** — a top-level peer of `app/`, `common/`, `connectors/`, not a child of `common/` |
| 4b | `runtime_settings.events` | **Evict to `common/messaging/settings_events.py`**, making `common/runtime_settings` pure structurally rather than by `__init__` discipline |
| 5 | Connectors env table | **Source from `GET /api/v1/settings/`**; `is_configured` gives the Set/Not-set fact with no secret. The `NEO4J_URI` message fix rides along |
| 6 | Package layout | **Move `dash_app/` → `src/ui/`**; `get_theme_tokens` → `src/domain/`. The `app/`→`api/` rename is **deferred to a separate plan** |
| 7 | UI runtime config | `API_BASE_URL=http://api:8000` in the UI service env; both services bind **8000**; gunicorn `--worker-class gthread --workers 4 --threads 8 --preload`, hardcoded with a tuning comment |
| 8 | Import-time constants | **All 12 become function-local reads**, with a test that a post-import cache refresh changes behaviour |
| 9 | UI request logging | Port `add_request_context` to Flask `before_request`/`after_request`, **INFO for everything** |
| 10 | Service rename | `app` → `api`, with an **`app` network alias** kept for one step, then dropped |
| 11 | Shared HTTP client | **All 56 sites** through `api_client.py`, as **its own step after the split is verified** |
| 12 | Collaboration bypasses | Swap cleanly; **before/after baseline script** captured and run in the same step. Spotlight needs an **optional `ids` param** on `/search`, gated on empirical equivalence |
| 13 | Test fallout | **Atomic per-module steps** — code moved, src and test importers rewritten, suite green, no stale path, all in one step. No sweep, no shims |
| 14 | Local dev | **Two documented commands**, no `dev.sh` (deferred as out of scope) |
| 15 | Compose graph | `ui: depends_on: api: service_healthy`; `nginx: depends_on: {api, ui}: service_healthy`. UI healthcheck probes its own `/app/`, not the API |
| 16 | Audit artifact | A **step in this plan**, not a long-lived doc. Three-way comparison, **discarded** once it passes |
| 17 | Design doc | **Edit `authn-authz-design.md` in this plan** (4 sections), so Plan C is not written against a stale premise |
| 18 | Requirements | Rename to match the image names; each file carries only what its runtime needs; **CI installs multiple**. No automated dependency-absence check |

## Repo conventions that apply

- **Settings** are fields on the `Settings` class in `src/app/settings.py`, with a
  sensible default and a comment. `DATABASE_URL` (line 8) has **no default** —
  that is deliberate and is what makes `ApiSettings` unconstructable in the UI.
- **Never `print()`** — use `from common.logger import logger`.
- **Type hints on all parameters and returns.** Built-in generics
  (`list[str]`, `dict[str, int]`), `X | None`. `mypy src/` runs **strict**.
- **Tests carry a marker.** `pytestmark = pytest.mark.unit` at module level, or a
  per-test decorator. Unmarked tests are **silently skipped** by `pytest -m unit tests`.
- **Commit messages** are plain imperative sentences, e.g.
  `Separate Dash and API into independent runtimes`. Not conventional-commit
  style (that is only for Dependabot bumps).
- **Do not commit, push, or open a PR** unless explicitly asked.
- Package `__init__.py` re-exports must be declared with `__all__` (mypy strict
  treats plain re-exports as private).

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Unit tests (CI gate) | `pytest -m unit tests -q` | 2340+ pass, 0 fail, exit 0 |
| Single test file | `pytest -m unit tests/test_<name>.py -q` | all pass |
| Typecheck (CI gate) | `mypy src/` | no errors, exit 0 |
| Lint (CI gate) | `pylint src --score=y` | score ≥ 9.0 |
| Security scan (CI gate) | `bandit -c .bandit.yml -r src/ -lll` | exit 0 |
| Compose config syntax | `docker compose config -q` | exit 0 |
| Nginx config syntax | `docker run --rm -v "$PWD/deploy/nginx/nginx.conf:/etc/nginx/nginx.conf:ro" -v "$PWD/deploy/certs:/etc/nginx/certs:ro" nginx:1.30-alpine nginx -t` | `syntax is ok`, `test is successful` |
| Full stack | `docker compose up -d` | all services healthy |
| Health over TLS | `curl -sf https://localhost/api/health` | `{"status":"healthy"}` |
| UI over TLS | `curl -sf -o /dev/null -w '%{http_code}' https://localhost/app/` | `200` |
| OpenAPI (container-internal only) | `docker exec wba-ai-api python -c "import json,urllib.request; print(len(json.load(urllib.request.urlopen('http://localhost:8000/openapi.json'))['paths']))"` | `39` |

**Container names change mid-plan.** The API container is `wba-ai-app` until
Step 12 renames it to `wba-ai-api`. Commands in Steps 1–11 must use
`wba-ai-app`; Steps 12–18 use `wba-ai-api`. Where a command appears in this table
without a step context, use `docker compose exec api …` (service name), which
resolves correctly on both sides of the rename because Step 12 keeps the `app`
network alias through Step 13.

**Note on `curl`:** use the **no-`-k`** form. Plan 051 established that the
mkcert CA is in the Linux trust store, so strict TLS works on any machine that
ran `mkcert -install`. The `-k` form is blocked by the sandbox classifier in
some harnesses.

Run Python commands with the virtualenv active (`source .venv/bin/activate`) and
`PYTHONPATH=src` where importing app code outside pytest.

## Scope

**In scope:**

- `src/domain/` (create) — pure shared code
- `src/ui/` (create, moved from `src/app/dash_app/`)
- `src/ui_main.py`, `src/app/api_main.py` (create); `src/app/main.py` (delete after Step 6)
- `src/common/runtime_settings/events.py` → `src/common/messaging/settings_events.py`
- `src/app/settings.py` (split into `UISettings` base + `ApiSettings`)
- `src/app/api/search/v1/` (add the optional `ids` param)
- **The three bypass callbacks** (§Current state) and any call site whose
  imported path moves
- `Dockerfile.api`, `Dockerfile.ui`, `requirements.api.txt`, `requirements.ui.txt`
- `docker-compose.yml`
- `deploy/nginx/nginx.conf` (upstream split only)
- `src/app/entrypoint.sh` → API entrypoint; a new UI entrypoint
- `scripts/setup.sh` — health poll and failure-message service name only
- `scripts/capture_collab_baseline.py` (create, **temporary** — deleted in Step 9)
- `CLAUDE.md`, `DEVELOPER_QUICK_START.md`, `USER_GUIDE.md`, `.env.example`
- `docs/design/authn-authz-design.md` — the four sections in Step 17 only
- `.github/workflows/pr_checks.yml` — the install lines for the three jobs
- `plans/README.md` — status row

**Out of scope** (do NOT touch, even though they look related):

- **Renaming `src/app/` → `src/api/`.** Its own follow-on plan. Every `app.*`
  import stays as-is except where a module physically moves.
- **Keycloak, `authn_session`, `AUTH_*` / `KEYCLOAK_*` settings, bearer tokens,
  the `/app/stream/<id>` proxy route.** Plan C's. This plan carries **no
  credentials** in `api_client.py` — Plan C teaches it to attach a token, which
  is why the two plans are not merged.
- **`API_SERVER` semantics beyond the rename.** The producers'/consumer's use of
  it is unchanged; only the service name in the value changes.
- **FastAPI's `/docs`, `/redoc`, `/openapi.json` settings.** Unreachable over TLS
  as a Plan 051 side effect. `docs_url=None` is Plan E's decision.
- **`scripts/temp_stream_server.py`.** Plan E.
- **TLS for container-to-container traffic.** Internal traffic stays plain HTTP
  on the Docker bridge.
- **A `scripts/dev.sh`.** Considered and deferred (Decision 14). Two documented
  commands instead.
- **`get_theme_tokens`'s behaviour.** It moves; it does not change.

## Git workflow

- Branch: `feat/dash-api-runtime-separation` (repo has no formal prefix
  convention; recent branches include `feat/tls-reverse-proxy`)
- Commit per step. Suggested grouping: Phase 1 moves (Steps 1–4), the structural
  split (Steps 5–10), packaging (Steps 11–13), client/audit/docs (Steps 14–18).
- Do **not** push or open a PR unless the operator instructed it.

---

## Steps

### Phase 1 — Pure moves (no behaviour change)

**Steps 1–4 are pure refactors. The application still runs as one process
throughout. A green suite after a pure rename is what proves the rename is
correct — so if observable behaviour changes in any of these steps, that is a
STOP condition, not an acceptable adaptation.**

---

### Step 1: Create `src/domain/` and move the pure `app.common.*` helpers

Create `src/domain/__init__.py` with a module docstring stating the package
contract:

```python
"""Shared, transport-free domain logic.

Modules here must not import aio_pika, neo4j, elasticsearch, sqlalchemy,
asyncpg, openai, langchain, mcp, matplotlib, or community — they are shared
by the API runtime, the UI runtime, and the connector runtimes.
"""
```

Move these, updating **every** importer in `src/` and `tests/` in this same step:

| From | To |
|---|---|
| `src/app/common/graph_theme.py` | `src/domain/graph_theme.py` |
| `src/app/common/node_size.py` | `src/domain/node_size.py` |
| `src/app/common/person_network_url.py` | `src/domain/person_network_url.py` |

**Also extract the theme tokens — and the node-geometry injection loop with them.**
`ACTIVE_THEME`, `THEME_TOKENS`, `NODE_TYPE_BASE_STYLES`, the injection loop, and
`get_theme_tokens` move out of `src/app/dash_app/styles.py` into
`src/domain/theme_tokens.py`.

**Why the loop must move too (this is the load-bearing part of Step 1).**
`THEME_TOKENS` (`styles.py:49`) does **not** literally contain the node geometry.
The `graph.node.<type>.shape/.width/.height` keys are **injected at import time**
by a mutation loop at `styles.py:280-285`, which reads `NODE_TYPE_BASE_STYLES`
(`styles.py:257`):

```python
for _mode_tokens in THEME_TOKENS.values():
    for _suffix, (_shape, _width, _height) in NODE_TYPE_BASE_STYLES.items():
        _key = f"graph.node.{_suffix}"
        _mode_tokens[f"{_key}.shape"] = _shape
        _mode_tokens[f"{_key}.width"] = _width
        _mode_tokens[f"{_key}.height"] = _height
```

There are **zero** literal `graph.node.*.shape` keys in the dict body, and
`NODE_TYPE_BASE_STYLES` has **no consumer other than this loop** (verified:
`grep -rn "NODE_TYPE_BASE_STYLES" src/ tests/` → `styles.py:257`, `styles.py:281`).

The API depends on the injected keys. `app/common/graph_theme.py:286-288`
resolves shape/size as `base_tokens.get(f"graph.node.{token_key}.shape", "ellipse")`,
and its docstring at `:269-270` states the contract explicitly: *"Shape and size
come from the `graph.node.<key>.shape/.width/.height` tokens so the effective base
matches the hardcoded stylesheet exactly (no drift)."* The API reaches
`get_theme_tokens` at `api/graph_themes/v1/service.py:100,123,342` — that is
`GET /api/v1/graph-themes/effective`, which the UI fetches at
`pages/graph/utils/graph_operations.py:29-47` and feeds into
`build_cytoscape_stylesheet` for the Graph, Timeline, and **both** Collaboration
Network pages.

**Measured consequence of moving the registry without the loop.** Simulating the
post-split API process (registry copied, injected keys absent):

```
LIVE   Person -> {'width': '66px', 'height': '56px', 'shape': 'octagon', ...}
SPLIT  Person -> {'width': '60px', 'height': '50px', 'shape': 'ellipse', ...}

node types whose shape changes: 15
{'Person': ('octagon','ellipse'), 'Project': ('round-rectangle','ellipse'),
 'Issue': ('triangle','ellipse'), 'Epic': ('hexagon','ellipse'), ...}
```

After the split the API process no longer imports the UI package, so the loop
never runs there and every typed node renders as an `ellipse` at 60×50. **Step 1
is a pure refactor, so this is invisible at its own gate** — one process, the
loop still runs, the suite stays green — and it surfaces only at Step 12/18 as a
browser-visible styling regression with no failing test pointing at the cause.
Moving the loop makes the registry self-contained and identical in both
processes, which is the only form in which the extraction is behaviour-preserving.

Mechanically:

- `ACTIVE_THEME` (`styles.py:44`), `THEME_TOKENS` (`:49`),
  `NODE_TYPE_BASE_STYLES` (`:257`), the injection loop (`:280-285`), and
  `get_theme_tokens` (`:288`) all move to `src/domain/theme_tokens.py`.
- `styles.py` imports them back — `from domain.theme_tokens import ACTIVE_THEME,
  NODE_TYPE_BASE_STYLES, THEME_TOKENS, get_theme_tokens` — and keeps deriving
  `COLOR_*`, `_token()`, `TOKENS = get_theme_tokens()` (`:296`) exactly as now.
  `ACTIVE_THEME` is re-exported rather than redefined, so
  `graph_styles.py:18`'s `from app.dash_app.styles import ACTIVE_THEME` keeps
  resolving and there is **one** definition of the active theme, not two.
- **Declare `__all__` in `styles.py` for the re-exported names.** `mypy.ini` sets
  `strict = True`, which enables `no_implicit_reexport`: a plain re-export makes
  `from app.dash_app.styles import ACTIVE_THEME` fail in `graph_styles.py:18`
  with `Module "app.dash_app.styles" does not explicitly export attribute
  "ACTIVE_THEME"  [attr-defined]`. Verified in a scratch package. This is the
  repo convention already recorded for package `__init__.py` files, applied to a
  module. `get_theme_tokens` is the one name that stays genuinely defined in
  `styles.py`'s own surface — but **5 files** import it from
  `app.dash_app.styles` (measured: `api/graph_themes/v1/service.py` — which this
  step repoints to `domain.theme_tokens` — plus
  `tests/test_graph_theme.py`, `tests/test_search_node_color_consistency.py`,
  `tests/test_collab_network_controls.py`,
  `tests/test_activity_timeline_edge_cases.py`), so list it in `__all__` too if
  you keep importing it from `domain` rather than redefining it. After the edit,
  `mypy src/` exiting 0 is the proof the re-export is explicit.
- The moved `get_theme_tokens` keeps its signature and default
  (`theme_name: str = ACTIVE_THEME`) and its `ValueError` on an unknown theme.
  Its behaviour must not change.
- `src/app/api/graph_themes/v1/service.py:28` changes its import from
  `app.dash_app.styles` to `domain.theme_tokens`.
- `NODE_TYPE_BASE_STYLES` is **not** UI-only geometry despite living in a UI file:
  it is the source of the shape/size the API resolves. It belongs in `domain/`.

**This is what breaks the API→UI edge.** Verify it directly:

```bash
grep -rn "app\.dash_app" src/app/api/ src/app/db/ src/app/common/
```
→ no matches (two docstring mentions in `app/common/graph_theme.py:5,35` and
`app/db/models/graph_theme.py:5` must have their prose updated to name the new
path, since a stale docstring naming a removed path is a defect).

**Leave `app/common/timezone.py` where it is for now.** It is *not* DB-free: it
reads `runtime_settings.get("TIMEZONE")` (`timezone.py:13`) and follows the
snapshot route in Step 7, not the pure-move route.

**Verify**: `pytest -m unit tests -q` → 2340+ passed, 0 failed
**Verify**: `grep -rn "from app\.common\.\(graph_theme\|node_size\|person_network_url\)" src/ tests/` → no matches
**Verify**: `grep -rn "app\.dash_app\.styles import get_theme_tokens" src/` → no matches
**Verify** — the geometry survives the move **without `styles.py` being imported**.
This is the check that catches the injection-loop omission; run it exactly as
written, in a fresh interpreter:
```bash
PYTHONPATH=src python -c "
import sys
from domain.theme_tokens import get_theme_tokens
leaked = [m for m in sys.modules if m.endswith('.styles') or m == 'styles']
assert not leaked, f'styles.py was imported ({leaked}) — the check is void'
t = get_theme_tokens('executive-light')
assert t.get('graph.node.person.shape') == 'octagon', t.get('graph.node.person.shape')
assert t.get('graph.node.person.width') == '66px', t.get('graph.node.person.width')
assert t.get('graph.node.person.height') == '56px', t.get('graph.node.person.height')
assert sum(1 for k in t if k.endswith('.shape')) == 17, 'geometry not injected for all node types'
print('geometry OK')
"
```
→ `geometry OK`. A `KeyError`-free but wrong answer (e.g. `ellipse`) is the
failure this guards against, so the assertions compare **values**, not presence.
**Verify**: `mypy src/` → exit 0

> ### 🚦 MANUAL GATE 1 — operator check
>
> **Report to the operator:** all five verify outputs (including `geometry OK`),
> `git diff --stat`, and `git status --short`.
>
> **Operator verifies:**
> 1. `src/domain/` exists with a docstring stating the transport-free contract.
> 2. The three modules moved and **nothing else changed** — `git diff` on the
>    moved files should be empty apart from import lines.
> 3. `src/app/api/graph_themes/v1/service.py` no longer imports from
>    `app.dash_app`. This is the backwards edge; confirm it is genuinely gone.
> 4. `styles.py` still works — a green suite is the evidence, but check that
>    `TOKENS = get_theme_tokens()` is still there and still derived.
> 5. **The node geometry moved with the registry.** Read
>    `src/domain/theme_tokens.py` and confirm it contains `NODE_TYPE_BASE_STYLES`
>    *and* the `for _mode_tokens in THEME_TOKENS.values():` injection loop — not
>    just the `THEME_TOKENS` dict. Then confirm the `geometry OK` verify printed
>    `geometry OK` **and** that its `styles.py was imported` assertion did not
>    trip. A registry moved without its loop passes every other check in this
>    gate and silently flattens all 15 typed node shapes to `ellipse` at 60×50 in
>    the API's `/graph-themes/effective` response. This is the single most
>    important check in Gate 1.
> 6. **`ACTIVE_THEME` is defined once.** Confirm `styles.py` re-exports it from
>    `domain.theme_tokens` rather than redefining it, so `graph_styles.py:18`'s
>    `from app.dash_app.styles import ACTIVE_THEME` resolves to the same object.
>    Confirm `styles.py` declares `__all__` naming the re-exports — without it
>    `mypy` (strict, `no_implicit_reexport`) rejects that import.
> 7. The test count did not drop. A rename that silently skips tests is worse
>    than one that fails.
>
> Wait for `PASS` before starting Step 2.

---

### Step 2: Move collaboration metadata to `src/domain/collaboration/`

The UI and the API need **different halves** of `app.analytics`:

- The **UI** uses only metadata and validation: `config.py`
  (`CollaborationNetworkConfig`, `LAYER_ORDER`, `LAYER_LABELS`, `SETTING_LABELS`),
  `errors.py`, and two symbols from `ego.py` (`COLLABORATOR_CAP_OPTIONS`,
  `cap_options_for`).
- **`algorithm.py`** — which pulls `networkx`, `community_louvain`, `matplotlib`
  — is imported only by `api/graph/v1/service.py:9`, `ego.py:14` and
  `tune.py:34`. The UI never touches it.

So this step moves the metadata, **not** the algorithm:

| From | To |
|---|---|
| `src/app/analytics/collaboration/config.py` | `src/domain/collaboration/config.py` |
| `src/app/analytics/collaboration/errors.py` | `src/domain/collaboration/errors.py` |
| `COLLABORATOR_CAP_OPTIONS`, `cap_options_for` (in `ego.py`) | `src/domain/collaboration/ego_metadata.py` |

`algorithm.py`, `tune.py` and the remaining `ego.py` stay in `app/`.
`ego.py` imports the two symbols back from `domain.collaboration.ego_metadata`,
so the API keeps its current behaviour.

Update every importer in `src/` and `tests/` (19 sites for `app.analytics.*`,
of which the `config`/`errors`/`ego`-metadata subset is the ones that move).

**Verify**: `pytest -m unit tests -q` → 2340+ passed, 0 failed
**Verify**: `grep -rn "from app\.analytics\.collaboration\.\(config\|errors\)" src/ tests/` → no matches
**Verify**: `grep -rn "app\.analytics\|app\.common\|app\.api\|app\.db" src/domain/` → no matches
**Verify**: `mypy src/` → exit 0

> ### 🚦 MANUAL GATE 2 — operator check
>
> **Report to the operator:** the four verify outputs and `git diff --stat`.
>
> **Operator verifies:**
> 1. `src/domain/collaboration/` contains `config.py`, `errors.py`,
>    `ego_metadata.py`.
> 2. **`algorithm.py` did NOT move.** Confirm it is still at
>    `src/app/analytics/collaboration/algorithm.py` — moving it would drag
>    `networkx`, `community_louvain` and `matplotlib` into the UI container.
> 3. `src/domain/` imports nothing from `app.*` — that is the whole point of the
>    package. Check with the third verify command.
> 4. The UI's imports of `LAYER_ORDER`, `CollaborationNetworkConfig`,
>    `COLLABORATOR_CAP_OPTIONS` all resolve.
>
> Wait for `PASS` before starting Step 3.

---

### Step 3: Move the metadata singletons to `src/domain/`

| From | To | Sites |
|---|---|---|
| `src/app/analytics/registry.py` | `src/domain/analytics_registry.py` | — |
| `CONNECTOR_REGISTRY` (in `api/connectors/v1/registry.py`) | `src/domain/connector_registry.py` | 6 |
| `MANAGED_INDEXES` (in `scripts/create_es_indexes.py`) | `src/domain/es_indexes.py` | 4 |

`CONNECTOR_REGISTRY` is a hardcoded dict, not a data path — the design doc
already classifies it as "a coupling to note rather than a bypass to close". The
API package imports it back so existing call sites are unchanged.

`MANAGED_INDEXES` is shared metadata describing index/entity pairs; both sides
import it from the new location.

Update every importer in `src/` and `tests/`.

**Verify**: `pytest -m unit tests -q` → 2340+ passed, 0 failed
**Verify**: `grep -rn "from app\.api\.connectors\.v1\.registry import CONNECTOR_REGISTRY" src/ tests/` → no matches outside `src/app/api/connectors/`
**Verify**: `grep -rn "app\.analytics\.registry\|app\.scripts\.create_es_indexes import MANAGED_INDEXES" src/domain/` → no matches
**Verify**: `mypy src/` → exit 0

> ### 🚦 MANUAL GATE 3 — operator check
>
> **Report to the operator:** the four verify outputs and `git diff --stat`.
>
> **Operator verifies:**
> 1. `CONNECTOR_REGISTRY` and `MANAGED_INDEXES` are importable from
>    `src/domain/`, and their contents are **byte-identical** to before (a
>    dict literal that loses an entry is a silent data bug).
> 2. `src/domain/` still imports nothing from `app.*`.
> 3. Phase 1 is complete: no pure module that both runtimes need still lives
>    under `app/`.
>
> Wait for `PASS` before starting Step 4.

---

### Step 4: Evict `events.py` to `common/messaging/settings_events.py`

Move `src/common/runtime_settings/events.py` →
`src/common/messaging/settings_events.py`. Same two symbols,
`publish_settings_changed` and `listen_for_settings_changed`.

Update the **5** importer lines:

| File | Line |
|---|---|
| `src/connectors/producers/daemon_common.py` | 50 |
| `src/connectors/consumers/main.py` | 56 |
| `src/app/main.py` | 29 |
| `src/app/api/settings/v1/service.py` | 19 |
| `tests/test_settings_rabbitmq.py` | 37 |

Then update `common/runtime_settings/__init__.py`'s docstring if it mentions the
RabbitMQ listener.

**Why:** this makes `common/runtime_settings/` pure **structurally** rather than
by `__init__` discipline. After it, `import common.runtime_settings` cannot pull
`aio_pika` even by accident, and the UI's import rule has no per-package
exception to encode.

**Verify**: `pytest -m unit tests -q` → 2340+ passed, 0 failed
**Verify**: `grep -rn "runtime_settings.events" src/ tests/` → no matches
**Verify** — the point of the step:
```bash
PYTHONPATH=src python -c "
import sys, common.runtime_settings
assert not any(m.startswith('aio_pika') for m in sys.modules), 'aio_pika leaked'
print('pure OK')
"
```
**Verify**: `mypy src/` → exit 0

> ### 🚦 MANUAL GATE 4 — operator check
>
> **Report to the operator:** the four verify outputs and `git diff --stat`.
>
> **Operator verifies:**
> 1. `src/common/messaging/settings_events.py` exists;
>    `src/common/runtime_settings/events.py` is gone.
> 2. The `aio_pika`-leak check prints `pure OK`. This is the gate that makes the
>    UI's import rule statable without exceptions.
> 3. `common/runtime_settings/__init__.py` still exports `RuntimeConfig`,
>    `RuntimeConfigCache`, `fetch_runtime_snapshot` — the pure trio — and the
>    producers'/consumer's package-level imports still resolve.
> 4. **Phase 1 is complete.** The app still runs as a single process; the suite is
>    green; no behaviour changed.
>
> Wait for `PASS` before starting Step 5.

---

### Phase 2 — The structural split

---

### Step 5: Move `src/app/dash_app/` → `src/ui/`

Move the whole package. Also create `src/ui_main.py` exposing the WSGI callable
(the entrypoint itself is Step 6, but the package must be importable here so the
suite can run).

**Set `routes_pathname_prefix`.** In `src/ui/layout.py`, `create_dash_app()`
(`:23-34`) currently sets only `requests_pathname_prefix="/app/"`. Add:

```python
app = dash.Dash(
    __name__,
    requests_pathname_prefix="/app/",
    routes_pathname_prefix="/app/",
    ...
)
```

**This is load-bearing.** Verified: with both prefixes set to `/app/`, Dash
registers its Flask handlers natively at `/app/_dash-layout`,
`/app/_dash-update-component`, `/app/`, `/app/<path:path>`, and no mount,
`a2wsgi`, or `X-Forwarded-Prefix` handling is required. Without it, Dash
registers at `/` and the split cannot serve the UI.

**Everything else in the UI is unchanged.** In particular `display_page`'s 18
hardcoded `/app/...` route strings (`layout.py:139-176`) and the 69 hardcoded
`/app/` literals keep working, because the path Dash sees is the same.

Rewrite **98 import sites**: 55 in `src/` plus 43 test files. The four
non-`dash_app` src files that reference it:

- `src/app/main.py:24` — `from app.dash_app.layout import create_dash_app` (this
  becomes `src/ui_main.py`'s import in Step 6; update it here)
- `src/app/api/graph_themes/v1/service.py` — should already be gone (Step 1)
- `src/app/common/graph_theme.py`, `src/app/db/models/graph_theme.py` — docstrings

**Do not move `assets/`.** `src/ui/assets/` stays exactly where it is relative to
`layout.py`, so Dash's asset discovery is unchanged.

**Verify**: `pytest -m unit tests -q` → 2340+ passed, 0 failed
**Verify**: `grep -rn "app\.dash_app" src/ tests/` → no matches
**Verify**: `ls src/ui/assets/` → the four existing asset files
**Verify**: `mypy src/` → exit 0

> ### 🚦 MANUAL GATE 5 — operator check
>
> **Report to the operator:** the four verify outputs, `git diff --stat`, and
> `git status --short` (expect many renames).
>
> **Operator verifies:**
> 1. `src/ui/` exists and `src/app/dash_app/` does not.
> 2. `routes_pathname_prefix="/app/"` is present in `create_dash_app()`. Ask
>    directly: *if this were removed, would the UI still serve at `/app`?* The
>    answer must be no — that is what makes it load-bearing rather than decorative.
> 3. Meta-files whose names would move silently, `dash_app/styles.py` → `src/ui/styles.py`,
>    `pages/**` → `src/ui/pages/**`.
> 4. The test count did **not** drop. Compare against the 2340 baseline.
> 5. **No behaviour changed.** The app is still one process at this point and
>    `docker compose up -d` still serves the UI at the old URL. Verify that
>    before moving on — a broken Step 5 before Step 6 removes the ability to tell
>    a move bug from a split bug.
>
> Wait for `PASS` before starting Step 6.

---

### Step 6: Split `main.py` into an API entrypoint and a UI entrypoint

Create `src/app/api_main.py` from `src/app/main.py`, **minus** the Dash mount and
the `create_dash_app` import. Everything else stays: the lifespan, the RabbitMQ
connection, `add_request_context`, the 11 routers.

Create `src/ui_main.py`:

```python
"""WSGI entrypoint for the Dash UI runtime.

The UI is a standalone service: it holds no database driver, no data-store
credentials and no LLM provider key. Every piece of data it renders arrives
over HTTP from the API (see ``src/ui/api_client.py``).
"""
from ui.layout import create_dash_app

app = create_dash_app()
server = app.server  # Flask — served by gunicorn
```

**Port the request logging to Flask.** `add_request_context`
(`main.py:161-181`) currently instruments every Dash request because the UI is
mounted inside FastAPI. After the split that middleware is API-only, and Plan C's
audit-logging section requires correlating auth events with the HTTP access log
via "the request id already injected by `add_request_context`".

Add to `src/ui_main.py` (or a small `src/ui/request_logging.py`):

- `@server.before_request` — read `X-Request-Id` or mint a `uuid4`, stash it and
  `time.perf_counter()` on `flask.g`, enter a `LogContext`.
- `@server.after_request` — log `[HTTP] request_complete` with the **same field
  names** as the API (`method`, `path`, `status`, `duration_ms`), set
  `X-Request-ID` on the response, exit the `LogContext`.
- `@server.teardown_request` — handle the exception path, mirroring the API's
  `[HTTP] request_failed`.

**Log at INFO for everything, including `/_dash-*` paths.** That matches the
API's current behaviour and the operator's decision.

Delete `src/app/main.py`.

**Repoint every test that imported it, in this same step.** Measured: **11 test
files** import `app.main` (26 mention it). They build the app via
`httpx.ASGITransport(app=app.main.app)` or `TestClient(app.main.app)`, and after
this step that import fails at collection time — which surfaces as a *collection
error*, not a test failure, so the suite does not merely go red, it fails to run.

| File | Form |
|---|---|
| `tests/test_activity_api_integration.py` | `from app.main import app` |
| `tests/test_persons_search_api.py` | `from app.main import app` |
| `tests/test_graph_execute_api.py` | `from app.main import app` |
| `tests/test_collaboration_endpoints.py` | `import app.main` + `TestClient(app.main.app)` |
| `tests/test_spotlight_wiring.py` | `import app.main` |
| `tests/test_stream_endpoint.py` | `from app.main import app` (×8, in-function) |
| `tests/test_chat_mcp_integration.py` | contains `app.main` |
| `tests/test_search_api.py` | contains `app.main` |
| `tests/test_jira_mention_comments_fetch.py` | contains `app.main` |
| `tests/test_graph_execute_api_integration.py` | contains `app.main` |
| `tests/test_query_catalog_api_integration.py` | contains `app.main` |

Repoint each to `app.api_main`. The semantics are unchanged — `api_main.app` is
the same FastAPI object minus the Dash mount, and these tests exercise API routes
only.

**One file needs more than a rename: `tests/test_proxy_awareness.py`.** It does
not import `app.main` — it mentions it only in prose (line 14, explaining why a
test that drives `app.main.app` never sees uvicorn's middleware). Update that
prose to name `app.api_main`, or it becomes a docstring referencing a module that
no longer exists. Plan 051's Gate 6 already recorded this file as having a known
test-depth gap; do not change its behaviour while editing its comment.

**Do NOT update `src/app/entrypoint.sh` in this step.** It still runs
`uvicorn app.main:app` (line 45), which this step just deleted — that is
deliberate and is **not** an oversight to fix here. Step 6 is a pure refactor
and its gate requires the app to keep running as one process; the entrypoint is
repointed in Step 11, which owns all packaging work and is the step where the
container is next rebuilt. Editing it now would break the invariant that Steps
1–7 change no behaviour.

**Step 11 must not forget this.** See that step's "Repoint the API entrypoint"
instruction — it is the single most load-bearing line in the packaging phase,
because if it is missed the API container fails to start and every gate from
Step 12 onward is blocked.

**Verify**: `pytest -m unit tests -q` → 2340+ passed, 0 failed
**Verify**: `grep -rln "app\.main" tests/ | wc -l` → 0
**Verify**: `PYTHONPATH=src python -c "import app.api_main; print('api OK')"`
**Verify**: `PYTHONPATH=src python -c "import ui_main; print('ui OK', type(ui_main.server))"`
**Verify**: `grep -rn "WSGIMiddleware\|a2wsgi" src/app/ src/ui/ src/ui_main.py` → no matches
**Verify**: `mypy src/` → exit 0

> ### 🚦 MANUAL GATE 6 — operator check
>
> **Report to the operator:** the six verify outputs and `git diff --stat`.
>
> **Operator verifies:**
> 1. `src/app/api_main.py` and `src/ui_main.py` both exist; `src/app/main.py` is gone.
> 2. `src/ui_main.py` imports **no** FastAPI, no `a2wsgi`, no `app.db`, no
>    scheduler, no `aio_pika`. This is the isolation property — check it by
>    reading the file's imports, not by trusting the suite.
> 3. `ui_main.server` is a Flask app (the verify prints the type).
> 4. The Flask logging hooks exist and use the same field names as
>    `api_main.py`'s `add_request_context`.
> 5. **`pytest -m unit tests -q` did not regress, and collection succeeded.**
>    All 11 test files that imported `app.main` were repointed to `app.api_main`
>    in this step. Check `grep -rln "app\.main" tests/` → 0. If any remain the
>    suite fails at **collection**, not at a test — verify the run actually
>    executed 2340+ tests rather than erroring out.
> 6. **Step 5's invariant still holds.** The app is still one process here and
>    `docker compose up -d` still serves the UI. Step 6 changed no runtime
>    behaviour; only the module layout.
>
> Wait for `PASS` before starting Step 7.

---

### Step 7: Convert the 12 import-time constants to function-local reads

**This fixes a verified pre-existing bug.** See "Current state" — after a cache
refresh, `chat.TIMEOUT_SECONDS` still returns the import-time value.

Convert each of the 12 module-level constants to a read at its use site:

| File | Line | Now | Becomes (at each use site) |
|---|---|---|---|
| `src/ui/pages/chat.py` | 37 | `TIMEOUT_SECONDS = runtime_settings.get_int("HTTP_REQUEST_TIMEOUT")` | `runtime_settings.get_int("HTTP_REQUEST_TIMEOUT")` |
| `src/ui/pages/connectors/callbacks.py` | 42 | same | same |
| `src/ui/pages/catalog/callbacks.py` | 20 | same | same |
| `src/ui/pages/catalog/editor_callbacks.py` | 28 | same | same |
| `src/ui/pages/catalog/editor_test_callbacks.py` | 31 | same | same |
| `src/ui/pages/graph/callbacks/catalog.py` | 31 | same | same |
| `src/ui/pages/graph/callbacks/context_menu.py` | 24 | same | same |
| `src/ui/pages/graph/callbacks/expansion.py` | 21 | same | same |
| `src/ui/pages/graph/callbacks/query.py` | 31 | same | same |
| `src/ui/pages/settings/runtime.py` | 60 | `API_BASE = settings.API_BASE_URL` | local read of `UISettings` |
| `src/ui/pages/settings/graph_styling/callbacks.py` | 43 | same | same |
| `src/ui/components/setup_banner.py` | 20 | `SETTINGS_API = settings.API_BASE_URL + "/api/v1/settings/"` | same |

The three `API_BASE` cases are **not** runtime-tunable (`API_BASE_URL` is
startup-only), so they become local reads of `UISettings` rather than cache
reads. They still move inside the function so the UI's config story is uniform.

**Add the test that makes this stick.** Without it a future contributor
reintroduces a module-level read and nothing catches it:

```python
@pytest.mark.unit
def test_runtime_setting_is_read_per_call_not_at_import(monkeypatch):
    """Changing the cache after import must change the callback's behaviour.

    Regression guard: 12 module-level ``TIMEOUT_SECONDS``/``API_BASE``
    constants froze these values at import, so editing
    HTTP_REQUEST_TIMEOUT in the Settings UI never took effect.
    """
    from common.runtime_settings.config import RuntimeConfig
    from app.runtime_settings import runtime_settings
    runtime_settings.refresh(RuntimeConfig(HTTP_REQUEST_TIMEOUT=123))
    # ... assert the consuming function observes 123, not the import-time value
```

The assertion must observe the value **through the consuming function**, not by
reading the cache — otherwise it tests the cache, which was never broken.

**Verify**: `pytest -m unit tests -q` → 2340+ passed, 0 failed, **including the new test**
**Verify**: the new test **fails** if you revert one constant to module level (run this mutation; do not skip it)
**Verify**: `grep -rn "^[A-Z_]* *= *\(runtime_settings\|settings\)\." src/ui/` → no matches
**Verify**: `mypy src/` → exit 0

> ### 🚦 MANUAL GATE 7 — operator check
>
> **Report to the operator:** the four verify outputs and the new test's name.
>
> **Operator verifies:**
> 1. The new test exists and asserts through the **consuming function**, not
>    through the cache.
> 2. **The mutation was run.** Reverting one constant to module level must make
>    the test fail. A test that passes both ways is vacuous — this is the single
>    most important check in this gate.
> 3. All 12 sites are converted; the grep finds none remaining.
> 4. No `TIMEOUT_SECONDS` is left referenced by a name that no longer exists.
>
> Wait for `PASS` before starting Step 8.

---

### Step 8: Source the MCP env table from the settings API

`src/ui/pages/connectors/layout.py:966-978` reads three settings from the UI
process's environment. Replace the direct reads with a fetch from
`GET /api/v1/settings/` (which the UI already calls at
`components/setup_banner.py:43`).

- Filter the response to `GITHUB_MCP_ENABLED`, `GITHUB_MCP_SERVER_URL`,
  `GITHUB_MCP_TOKEN`.
- Use `is_configured` for the Set/Not-set indicator.
- Use the returned (already masked) `value` for display. `_mask_secret_ui`
  (`layout.py:790-792`) then becomes redundant for the token row — remove it if
  it has no other caller.
- `GITHUB_MCP_SERVER_URL` is not sensitive and is returned in plaintext.

**Also fix `src/ui/pages/graph/utils/data_transform.py:176**`, which interpolates
`settings.NEO4J_URI` into a user-facing error message — internal topology shown
to the browser. Replace with a message that does not name the endpoint.

**No new endpoint is needed.** `GET /api/v1/settings/` already returns
`is_configured` computed on the **raw** value before masking
(`api/settings/v1/service.py:231-247`), so a standard user learns *whether* the
token is set without learning the token. This is also why the row survives Plan
C's admin-only secret rule unchanged.

**Verify**: `grep -rn "settings\.GITHUB_MCP\|settings\.NEO4J_URI" src/ui/` → no matches
**Verify**: `grep -n "GITHUB_MCP" docker-compose.yml` → no `ui` service block matches (the API keeps them)
**Verify**: `pytest -m unit tests -q` → all pass
**Verify**: `mypy src/` → exit 0

> ### 🚦 MANUAL GATE 8 — operator check
>
> **Report to the operator:** the four verify outputs.
>
> **Operator verifies:**
> 1. The UI reads none of `GITHUB_MCP_ENABLED`, `GITHUB_MCP_SERVER_URL`,
>    `GITHUB_MCP_TOKEN`, or `NEO4J_URI` from its own environment.
> 2. The Connectors page's env table still renders all three rows with correct
>    Set/Not-set indicators. **This is a browser check** — the whole point is that
>    the page is unchanged for the user while the secret stopped being present in
>    the UI process.
> 3. The Neo4j error message no longer names `settings.NEO4J_URI`.
> 4. The settings API's masking is what supplies the display value — confirm
>    nothing in the UI computes a mask of its own for the token.
>
> Wait for `PASS` before starting Step 9.

---

### Step 9: Absorb the collaboration and ego bypasses — with a before/after baseline

**Run the baseline capture FIRST, in this step, before editing any call site.** A
baseline captured after the swap proves nothing.

**9a. Write and run the temporary baseline script.**

Create `scripts/capture_collab_baseline.py` (temporary; deleted at the end of this
step). It must:

1. Choose a **fixed, seeded** set of configs — not random, not the current URL's
   values, since URL state varies between runs.
2. Call **both** paths for each config: the in-process
   `get_collaboration_network(config=...)` / `get_ego_network(...)` **and** the
   HTTP endpoints `GET /api/v1/graph/collaboration-network` /
   `.../ego`.
3. Dump a canonical, order-independent summary to JSON: element count, node id
   set, edge (source,target,weight) set, and the summary stats
   (`num_people`, `num_pairs`, `num_communities`, `modularity`).

Run it **before** the swap and save the output. The live stack has 223 people /
4818 pairs / 5041 elements, so the comparison is against real data.

**9b. Swap the two call sites.**

| File | Now | Becomes |
|---|---|---|
| `src/ui/pages/collaboration_network/callbacks/filter.py:88` | `data = get_collaboration_network(config=config)` | HTTP `GET /api/v1/graph/collaboration-network?…` |
| `src/ui/pages/collaboration_network_ego/callbacks/filter.py:201` | `data = get_ego_network(focus_id, config=…, max_collaborators=…)` | HTTP `GET /api/v1/graph/collaboration-network/ego?…` |

**The real work is parameter translation.** The UI builds a
`CollaborationNetworkConfig` via `from_query_values` and passes a *model*; the
endpoint takes **30+ flat query params** (`api/graph/v1/router.py:200-227` for
org, `:341-368` for ego) and independently calls `from_query_values({...})` on
them (`:250-262`). Two parsers, two field lists, no link between them.

So the call site must serialize the config to query params. **The endpoint's
param names and defaults must exactly match what `from_query_values` expects, or
the two drift silently.**

**9c. Re-run the baseline script and compare.**

The comparison must be **exact** for the canonical sets. A mismatch is a STOP
condition — it means the translation is lossy, and the fix is to correct the
param mapping, never to relax the comparison.

**Watch ego's bounds specifically.** `max_collaborators` has
`ge=MIN_MAX_COLLABORATORS, le=MAX_MAX_COLLABORATORS` in the endpoint
(`router.py:345-349`) while the UI has its own `cap_options_for` — two bound
definitions that can disagree. Include a config at each boundary.

**9d. Delete the script.** `git rm scripts/capture_collab_baseline.py`. Also
delete the now-unused imports of `get_collaboration_network` /
`get_ego_network` / `CollaborationDataUnavailable` if nothing else uses them.

**Verify**: the before/after JSON summaries are **identical** (operator-run;
paste both)
**Verify**: `grep -rn "from app\.api\.graph\.v1\.service" src/ui/` → no matches
**Verify**: `pytest -m unit tests -q` → all pass
**Verify**: `mypy src/` → exit 0
**Verify**: `git status --short scripts/` → the capture script is gone

> ### 🚦 MANUAL GATE 9 — operator check
>
> **Report to the operator:** both baseline JSON summaries, the diff between
> them, and the five verify outputs.
>
> **Operator verifies:**
> 1. **The baseline was captured before the swap.** Confirm the script ran
>    against the pre-change tree — check the git state at capture time, not the
>    executor's word.
> 2. The two summaries are **identical**, not merely "close". Same node ids, same
>    edge set, same stats.
> 3. If they differ, the number of differing elements is reported. **Do not
>    accept "the difference is small"** — a lossy param translation is exactly
>    the bug this gate exists to catch.
> 4. The two collaboration pages render in the browser (see Step 12's full sweep;
>    a spot check here is enough).
> 5. `scripts/capture_collab_baseline.py` is deleted.
>
> Wait for `PASS` before starting Step 10.

---

### Step 10: Add an optional `ids` param to `/search` and move spotlight to HTTP

**This step exists because the obvious swap is wrong.** Verified live:

| Call | Result |
|---|---|
| `GET /api/v1/search?q=review` | `total = 22`, `page_size = 20`, 20 returned |
| Canvas node count | 223 |

`search_in_graph`'s docstring (`api/search/v1/service.py:200-203`) states it
"eliminates the top-N clipping problem": it sets `body["size"] = len(graph_wba_ids)`
(`:223`) so every loaded node is a candidate. A literal swap to the unscoped
endpoint would silently stop highlighting nodes.

**10a. Add an optional `ids` query param** to `GET /api/v1/search`
(`api/search/v1/router.py:17`). When present, constrain the ES query to documents
whose `wba_id` is in the list, and set `size = len(ids)` — mirroring
`search_in_graph`'s scoping **exactly**. When absent, behaviour is unchanged.

Keep the existing `search_in_graph` function or express it in terms of the new
param — but the endpoint's scoped path must reproduce its result set.

**10b. Swap the spotlight call site.**
`src/ui/pages/graph/callbacks/spotlight.py:118` currently calls
`search_in_graph(SearchRequest(q=q), graph_wba_ids)`. It becomes an HTTP call
with `q` and `ids`.

**10c. Verify empirically.** The gate is a **comparison of matched-ID sets** on
the populated 223-node canvas, in-process vs HTTP, for several queries. The
client-side intersection at `spotlight.py:122-131` must produce the same
highlighting.

**Verify**: the matched-ID sets are identical (operator-run; paste both)
**Verify**: `GET /api/v1/search?q=review` **without** `ids` still returns 20 of 22 (no regression)
**Verify**: `grep -rn "from app\.api\.search\.v1\.service\|from app\.api\.search\.v1\.model" src/ui/` → no matches
**Verify**: `pytest -m unit tests -q` → all pass
**Verify**: `mypy src/` → exit 0

> ### 🚦 MANUAL GATE 10 — operator check
>
> **Report to the operator:** both matched-ID sets, the unscoped-`search` result
> count, and the five verify outputs.
>
> **Operator verifies:**
> 1. **The `ids` param is genuinely scoped**, not merely accepted and ignored.
>    Ask: *if `ids` were dropped from the ES body, would the comparison still
>    pass?* It must not — otherwise the param is decorative.
> 2. Unscoped `/search` is unchanged: still 20 of 22 for `q=review`.
> 3. The matched-ID sets are identical for at least three different queries,
>    including one that matches more than 20 canvas nodes (which is the case the
>    old in-process call handled and a naive swap would not).
> 4. The Graph page's spotlight search works in the browser.
>
> Wait for `PASS` before starting Step 11.

---

### Phase 3 — Packaging and runtime

---

### Step 11: Split the images and requirements

**Rename the requirements file to match the service name.**

| Now | Becomes | Contents |
|---|---|---|
| `requirements.app.txt` | `requirements.api.txt` | unchanged — the API's existing set |
| `Dockerfile.app` | `Dockerfile.api` | unchanged build, plus the entrypoint rename below |
| — | `requirements.ui.txt` | **new** |
| — | `Dockerfile.ui` | **new** |

**`requirements.ui.txt` carries only what the UI needs:**

```
dash
dash-bootstrap-components
dash-cytoscape
dash-extensions
requests
pydantic-settings
gunicorn
```

Pin exact versions (`==`) copied from `requirements.api.txt` where the package
appears there, and resolve `plotly` explicitly (it is currently a Dash
transitive dependency — pinning it avoids a silent drift in the graph rendering).

**`Dockerfile.ui` must NOT install:** `neo4j`, `elasticsearch`, `sqlalchemy`,
`asyncpg`, `openai`, `langchain*`, `mcp[cli]`, `aio-pika`, `a2wsgi`,
`cryptography`, `networkx`, `python-louvain`, `matplotlib`, `tiktoken`, `alembic`,
`psycopg2-binary`.

**`Dockerfile.ui` needs no catalog mount and no migration tooling.** Verified: the
UI does not read `queries_catalog/` from disk, does not import `alembic` or
`app.db`, and reaches the catalog through the API.

Copy into the UI image: `src/ui/`, `src/domain/`, `src/common/` (logger and the
pure runtime-settings client — **not** `common/messaging/`, which needs
`aio_pika`).

**Repoint the API entrypoint — this is the load-bearing edit of the whole
packaging phase.** `src/app/entrypoint.sh` keeps its startup sequence (Postgres
wait → `alembic upgrade head` → `init_rabbitmq.py` → `create_neo4j_indexes.py` →
`create_es_indexes.py` → uvicorn) unchanged, **except line 45**, which still
names the module Step 6 deleted:

```bash
# BEFORE (broken after Step 6 — app.main no longer exists)
cd /app && uvicorn app.main:app --host 0.0.0.0 --port 8000 \
    --forwarded-allow-ips="*"

# AFTER
cd /app && uvicorn app.api_main:app --host 0.0.0.0 --port 8000 \
    --forwarded-allow-ips="*"
```

Change **only** the module path. Everything else on that line and in the file
stays:

- `--host 0.0.0.0 --port 8000` unchanged.
- **`--forwarded-allow-ips="*"` unchanged, and its comment block at lines 35–44
  preserved verbatim.** That comment is the recorded justification from Plan 051's
  Gate 4: `*` is safe *only* because the service publishes no host port. Plan 052
  keeps that true for the API (port 8000 unpublishes in Step 12), and the UI's
  8000 is also unpublished — so the rationale still holds. **Do not rewrite,
  shorten, or "improve" that comment.** It is a security rationale, and an
  executor who retypes the line without it silently deletes the reasoning that
  keeps the flag defensible. If the container is ever re-published, the comment
  is the only thing that says why that is wrong.
- The migration/index bootstrap steps stay: they are the API's, and removing them
  would leave the database un-migrated.

**If this edit is missed, the API container fails to start with
`ModuleNotFoundError: No module named 'app.main'`, and every gate from Step 12
onward is blocked.**

The UI needs a new, much smaller entrypoint:

```bash
#!/bin/bash
set -e
# No migrations, no index creation, no RabbitMQ initialisation: the UI holds no
# database driver and no transport. It serves Dash and calls the API over HTTP.
cd /app && exec gunicorn ui_main:server \
    --bind 0.0.0.0:8000 \
    --worker-class gthread \
    --workers 4 \
    --threads 8 \
    --preload
```

**Add the tuning comment.** The worker/thread values are a judgement for a
developer workstation, not a derived value:

```bash
# Tuning: --worker-class gthread + --threads is deliberate. Dash callbacks are
# synchronous `requests` calls, and gunicorn's default `sync` worker with 1
# thread would SERIALIZE every callback in a worker — a real behaviour change
# from the Starlette threadpool (~40 threads) that served these callbacks
# before the split. Raise --workers/--threads for a larger host; the concurrency
# gate in this plan's Step 16 is what verifies they are not serializing.
```

**CI must install the UI requirements** so `mypy`/`pylint`/`pytest` cover
`src/ui/`. Update the three install lines in
`.github/workflows/pr_checks.yml` (`:31`, `:86`, `:114`) to include
`-r requirements.ui.txt`.

**Update `Dockerfile.api`'s `COPY` lines** to include `src/domain/`. Keep the
`requirements.api.txt` filename reference in step with the rename. Also check
**`ENTRYPOINT ["app/entrypoint.sh"]`** still resolves — the file keeps its path
and name, so this line should be unchanged, but confirm rather than assume.

**Verify**: `docker build -f Dockerfile.api -t wba-api-test .` → succeeds
**Verify**: `docker build -f Dockerfile.ui -t wba-ui-test .` → succeeds
**Verify**: `grep -n "app\.main:app" src/app/entrypoint.sh` → **no matches**
**Verify**: `grep -n "api_main:app" src/app/entrypoint.sh` → 1 match
**Verify**: `grep -c "forwarded-allow-ips" src/app/entrypoint.sh` → 2 (the comment plus the invocation, exactly as before this plan)
**Verify**: `docker run --rm wba-api-test pip list 2>/dev/null | grep -ci "^dash "` → `0`
**Verify**: `docker run --rm wba-ui-test pip list 2>/dev/null | grep -ciE "neo4j|elasticsearch|sqlalchemy|asyncpg|openai|langchain|matplotlib"` → `0`
**Verify**: `grep -n "requirements.ui.txt" .github/workflows/pr_checks.yml` → 3 matches
**Verify**: `bash -n <the new UI entrypoint>` → exit 0

> ### 🚦 MANUAL GATE 11 — operator check
>
> **Report to the operator:** the nine verify outputs and the new files' contents.
>
> **Operator verifies:**
> 1. **Both images build.** This is the first gate that can fail for packaging
>    reasons unrelated to code.
> 2. The UI image contains **none** of the data-store or LLM packages. The grep
>    must print `0`. This is the isolation property made physical — it is the
>    whole reason for two images rather than two entrypoints.
> 3. The API image contains no `dash`.
> 4. `requirements.ui.txt` pins exact versions and includes `gunicorn`.
> 5. **The UI entrypoint runs no migrations, no index creation, no RabbitMQ
>    init.** Read it; confirm. A UI container that runs `alembic upgrade head`
>    would need a database connection and defeat the split.
> 6. The gunicorn invocation is `gthread` with `--threads`, **not** the default
>    `sync`. Check the flags are actually in the file.
> 7. CI installs the UI requirements in all three jobs that need them.
> 8. **`src/app/entrypoint.sh` names `app.api_main:app`, not `app.main:app`.**
>    This is the check that Step 6 forward-declared. If it still says
>    `app.main`, the API container will not start and Step 12 cannot pass — stop
>    and report rather than proceeding to the compose step to "see what happens".
> 9. **The `--forwarded-allow-ips` comment block (lines 35–44) is intact and
>    verbatim.** Compare it against the plan's baseline commit:
>    `git diff 5210f00 -- src/app/entrypoint.sh`. The only diff must be the
>    module path on line 45 — one hunk, one changed line. A lost security
>    rationale is invisible in every test and every gate; this is the only place
>    it is checked.
>
> Wait for `PASS` before starting Step 12.

---

### Step 12: Rewire Compose and nginx

**12a. Split the nginx upstream.** `deploy/nginx/nginx.conf` currently has one
upstream (`:11-13`) used by four locations. Replace with two:

```nginx
upstream wba_api {
    server api:8000;
}
upstream wba_ui {
    server ui:8000;
}
```

Repoint: `/api/v1/chats/` (`:37`) → `wba_api`; `/api` (`:50`) → `wba_api`;
`/app` (`:63`) → `wba_ui`. `/` (`:71`) still 302s to `/app`.

**Keep `client_max_body_size 50m`** (`:8`) — Plan 051 added it because the
collaboration callbacks exceed 1 MiB, and the UI still POSTs those payloads.

**The `/app` location must have no trailing slash on `proxy_pass`** — that is
what preserves the `/app` prefix Dash expects.

**The SSE block stays pointed at the API.** The browser-direct
`/api/v1/chats/{id}/stream` call is the API's, not the UI's.

**12b. Compose.** In `docker-compose.yml`:

1. Rename the `app` service to `api` (`:23`), `container_name: wba-ai-api`.
2. **Keep an `app` network alias** on the `api` service for one step:

```yaml
    networks:
      wba-ai-network:
        aliases:
          - app
```

3. Add the `ui` service: build `Dockerfile.ui`, `container_name: wba-ai-ui`,
   port 8000 **not published** (nginx fronts it), the UI entrypoint, and a
   narrowed `environment:` block containing **only**: `API_BASE_URL=http://api:8000`,
   `UI_DATE_FORMAT`, `UI_DATETIME_FORMAT`, `TIMEZONE`, the `LOG_*` values, and
   `GRAPH_UI_*`. **No `DATABASE_URL`, no `OPENAI_API_KEY`, no `NEO4J_*`,
   no `ELASTICSEARCH_*`, no `GITHUB_MCP_*`, no `RABBITMQ_URL`,
   no `CONNECTOR_ENCRYPTION_KEY`.**
4. `ui: depends_on: api: service_healthy`.
5. `nginx: depends_on: {api: service_healthy, ui: service_healthy}` — replaces
   the current `app: service_healthy` (`:116`).
6. Update the four `API_SERVER: http://app:8000/` values (`:218`, `:241`, `:264`,
   `:288`) to `http://api:8000/`.
7. Update the five `depends_on: app:` blocks (`:116`, `:227`, `:250`, `:273`,
   `:304`) to `api`.
8. **UI healthcheck probes its own liveness**, not the API:

```yaml
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/app/"]
      interval: 10s
      timeout: 5s
      retries: 5
      start_period: 10s
```

The UI must not go unhealthy when the API restarts — otherwise nginx's
`depends_on` semantics cascade.

**12c. Handle the `API_SERVER` precedence trap.** `_resolve_source`
(`api/settings/v1/service.py:108`) is **DB override > env value > code default**,
and `API_SERVER` is a DB-backed row
(`alembic/versions/2026_08_10_0800-3f1a2b4c5d6e:109`). So a persisted row saying
`http://app:8000/` **beats** the env change.

Check for the row and record the answer before deciding:

```bash
docker exec wba-ai-postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
  -c "SELECT key, value FROM application_settings WHERE key = 'API_SERVER';"
```

If a row exists, set it to `http://api:8000/` **and** remove it (env should be the
source for an infrastructure address, not a DB row). State which you did and why.

**12d. Update the code defaults.** `common/runtime_settings/config.py:77`,
`app/settings.py:85`, `api/settings/v1/models.py:116`, `consumers/main.py:206`
and `.env.example:106` all default to `http://app:8000/` — update to
`http://api:8000/`. Within this step the alias keeps the old name working, so a
missed site is not yet fatal — Step 13 is what proves they were all caught.

**Verify**: `docker compose config -q` → exit 0
**Verify**: `nginx -t` (via the `docker run` form in Commands) → `test is successful`
**Verify**: `docker compose up -d --build` → all healthy
**Verify**: `curl -sf https://localhost/api/health` → `{"status":"healthy"}`
**Verify**: `curl -sf -o /dev/null -w '%{http_code}' https://localhost/app/` → `200`
**Verify**: `docker compose exec api env | grep -c GITHUB_MCP_TOKEN` → `0`
**Verify**: `docker compose exec ui env | grep -cE "DATABASE_URL|OPENAI_API_KEY|NEO4J_PASSWORD"` → `0`

> ### 🚦 MANUAL GATE 12 — operator check (the largest gate)
>
> This is the first gate where the split is actually running. Work the checks
> yourself; the executor supplies the stack, but the observations are yours.
>
> **Operator verifies:**
> 1. **Cold start works.** `docker compose down && docker compose up -d`, then
>    immediately browse `https://localhost/app`. No 502, no unstyled page. This
>    is what `depends_on` (i)+(A) exists to guarantee — if there is a 502 window,
>    the dependency graph is wrong.
> 2. **The UI loads and is styled** — CSS from `/app/assets/` is served by the
>    **UI** container, not the API. Confirm in DevTools that `/app/assets/*`
>    responses come from the `ui` service.
> 3. **Dash callbacks work.** `/app/_dash-update-component` is served by the UI.
>    Run a Search, and check the network panel shows the callback POST going to
>    `/app/...` and an internal API call succeeding.
> 4. **The API works through the same proxy.** `https://localhost/api/v1/connectors/`
>    → JSON.
> 5. **The UI container holds no secrets.** `docker compose exec ui env` — no
>    `DATABASE_URL`, `OPENAI_API_KEY`, `NEO4J_PASSWORD`, `GITHUB_MCP_TOKEN`,
>    `CONNECTOR_ENCRYPTION_KEY`.
> 6. **The API container holds no dash.** `docker compose exec api pip list | grep dash`
>    → empty.
> 7. **Producers still fetch the runtime snapshot.** Check the producer logs for
>    `Fetched runtime settings snapshot` — **not** the fallback warning
>    (`Runtime settings API unreachable`). This is the gate for the rename; the
>    failure mode is silent degradation, so the log line is the evidence.
> 8. **Collaboration Network renders** (org and ego) — this is the page Plan 051
>    broke with `client_max_body_size`, and it is the page most sensitive to the
>    proxy split.
> 9. **Chat streams progressively** — tokens arrive as they are generated, not in
>    one burst.
> 10. `docker compose ps` shows no restart loops after 2 minutes.
>
> Reply `PASS` to proceed to Step 13, or `FAIL` with the check number.

---

### Step 13: Drop the `app` network alias

Only proceed once Step 12's gate confirmed the producers and consumer fetch the
snapshot successfully.

Remove the alias from the `api` service. Any remaining `app:8000` reference now
fails loudly at the DNS layer rather than silently degrading.

**Verify**: `docker compose config -q` → exit 0
**Verify**: `grep -rn "app:8000" docker-compose.yml src/ .env.example` → no matches
**Verify**: `docker compose up -d` → all healthy
**Verify**: producer logs still show `Fetched runtime settings snapshot`

> ### 🚦 MANUAL GATE 13 — operator check
>
> **Report to the operator:** the four verify outputs and the producer log lines.
>
> **Operator verifies:**
> 1. The alias is gone from `docker-compose.yml`.
> 2. **Producers and the consumer still work.** The snapshot fetch must succeed
>    under the new name. If it silently fell back to defaults, the grep passed but
>    the rename is incomplete — the log line is the proof, not the grep.
> 3. No `app:8000` remains anywhere in the tracked tree.
> 4. All services healthy, no restart loops.
>
> Wait for `PASS` before starting Step 14.

---

### Phase 4 — Client, audit, docs

---

### Step 14: Introduce `src/ui/api_client.py` and migrate all 56 call sites

**In this plan the client carries no credentials.** Plan C teaches it to attach a
bearer token — which is why the two plans are not merged.

**Build the client** as the single chokepoint for UI→API calls:

- Owns the base URL (from `UISettings.API_BASE_URL`) and the timeout (from the
  runtime-settings cache, read **per call** — see Step 7).
- Exposes `get`/`post`/`put`/`patch`/`delete` with a consistent signature.
- Defines **one exception type** carrying `status_code`, so Plan C's
  401-redirect / 403-banner split becomes a property of this module.
- **Accepts an injectable transport** (a `requests.Session` or a callable) so
  tests can stub the API without monkeypatching `requests` globally. With 43 test
  files touching the UI, that matters.

**Migrate all 56 sites across 13 files.** Head-weighted:

| File | Sites |
|---|---|
| `pages/connectors/callbacks.py` | 17 |
| `pages/catalog/editor_callbacks.py` | 8 |
| `pages/settings/runtime.py` | 7 |
| `pages/settings/graph_styling/callbacks.py` | 5 |
| `pages/graph/callbacks/catalog.py` | 4 |
| `pages/timeline/api.py` | 3 |
| `pages/search.py` | 3 |
| `pages/graph/utils/graph_operations.py` | 2 |
| `pages/chat.py` | 2 |
| `pages/catalog/callbacks.py` | 2 |
| `pages/graph/callbacks/query.py` | 1 |
| `pages/catalog/editor_test_callbacks.py` | 1 |
| `components/setup_banner.py` | 1 |

**Note the `# nosec B113` comments** in `timeline/api.py:72,130,225` — the client
must preserve whatever those were suppressing (a missing timeout), by always
passing one.

**Verify**: `grep -rn "requests\.\(get\|post\|put\|patch\|delete\)" src/ui/` → no matches
**Verify**: `grep -rln "api_client" src/ui/ | wc -l` → 13 or more
**Verify**: `pytest -m unit tests -q` → all pass
**Verify**: `mypy src/` → exit 0
**Verify**: `pylint src --score=y` → ≥ 9.0

> ### 🚦 MANUAL GATE 14 — operator check
>
> **Report to the operator:** the five verify outputs and `git diff --stat`.
>
> **Operator verifies:**
> 1. **Zero** raw `requests.*` calls remain in `src/ui/`. The grep is the gate.
> 2. The client carries **no** credentials — no `Authorization` header, no token
>    parameter, no `KEYCLOAK_*`/`AUTH_*` reference. Confirm this explicitly; it is
>    the boundary between this plan and Plan C.
> 3. One exception type carrying `status_code`, not per-call `raise_for_status`.
> 4. The transport is injectable, so tests do not monkeypatch the `requests`
>    module globally.
> 5. Timeouts are read **per call**, not captured at import (Step 7's bug class).
> 6. **A browser sweep of every page**: Chat, Search, Graph, Timeline, Analytics,
>    Catalog, Connectors, Settings, Collaboration Network (org + ego). A missed
>    call site is a runtime error on a rarely-exercised page — this is the check
>    that finds it.
>
> Wait for `PASS` before starting Step 15.

---

### Step 15: API-completeness audit (regression check, discarded afterwards)

**This is a regression gate, not a long-lived document.** Its purpose is to
verify this plan did not break anything. The artifact is discarded once it passes.

**Run it after Step 14**, when all UI→API calls have one chokepoint to enumerate.

**The three-way comparison:**

| Set | Source |
|---|---|
| **A** — endpoints the UI calls | the `api_client.py` call sites |
| **B** — endpoints the schema exposes | `GET /openapi.json` |
| **C** — `A ⊆ B` | every UI-called path resolves to a real route |

**B must be read container-internally.** Verified: `https://localhost/openapi.json`
→ **404** (Plan 051's deliberate consequence). Use:

```bash
docker exec wba-ai-api python -c "
import json, urllib.request
print(len(json.load(urllib.request.urlopen('http://localhost:8000/openapi.json'))['paths']))
"
```
→ `39` (baseline; a different number is fine if routes were legitimately added).

**Plus two checks the comparison implies:**

1. **Response-shape** — for each of the ~24 UI-called endpoints, the UI's parsing
   matches the endpoint's `response_model`. This is where Step 9's collab
   round-trip and Step 10's `ids` scoping surface.
2. **Orphans** — endpoints in B that no UI path uses. Those are **fine** (the API
   is allowed to be broader than Dash); listing them is what demonstrates the API
   is not Dash-shaped.

**Baseline for set A** (24 distinct paths, measured):

```
/api/v1/settings/                                    (and /reset, /{key}/reset)
/api/v1/graph-themes/                                (+ /effective, /{id}, /{id}/set-default)
/api/v1/search                                       (/search/persons)
/api/v1/chats                                        (/chats/{session_id})
/api/v1/commands/
/api/v1/connectors/                                  (+ /{type}, /{type}/configs,
                                                      /{type}/configs/{id},
                                                      /{type}/configs/{id}/status,
                                                      /{type}/test)
/api/v1/graph/execute                                (/graph/expand)
/api/v1/queries/catalog                              (/catalog-metadata,
                                                      /catalog-metadata/{id},
                                                      /catalog/namespaces,
                                                      /catalog/{namespace}/{slug})
/api/v1/activity/timeline                            (/activity/suggest)
```

**Discard the table after it passes.** Leave no artifact — the plan's step record
is the only place it appears.

**Verify**: every path in A resolves in B
**Verify**: response shapes match for all A endpoints
**Verify**: orphans listed and reviewed (not necessarily zero)
**Verify**: `pytest -m unit tests -q` → all pass

> ### 🚦 MANUAL GATE 15 — operator check
>
> **Report to the operator:** the count of paths in A and B, the mismatch list
> (empty if clean), and the orphan list.
>
> **Operator verifies:**
> 1. **`A ⊆ B` holds** — every endpoint the UI calls is a real route. A single
>    miss is a broken page.
> 2. Response shapes match. Spot-check the two most complex: the collaboration
>    network and the search response.
> 3. Orphans were reviewed and are genuinely not-needed by the UI. An orphan that
>    *should* be used means a call site was missed in Step 14.
> 4. No artifact was left behind.
>
> Wait for `PASS` before starting Step 16.

---

### Step 16: gunicorn concurrency gate

**This exists because the split can silently serialize every callback.**

Before the split, Starlette ran sync Dash callbacks in a threadpool (~40
threads), so concurrent callbacks did not block each other. Gunicorn's default
worker is `sync` with one thread, which **would** serialize them. Step 11 pins
`--worker-class gthread --workers 4 --threads 8`, but that is an assumption about
flags, not a measurement.

**Measure it.** Fire N concurrent Dash callback POSTs at
`https://localhost/app/_dash-update-component` and confirm they overlap in time.

Use a payload that takes measurable time — the collaboration network response is
**1.67 MB** and exercises the slow path (Neo4j + Louvain). `client_max_body_size
50m` is already set, so payload size is not the limit.

**The gate:** N concurrent requests complete in materially less than N ×
(single-request duration). If they serialize, total time ≈ N × single.

Suggested N = 4 (matching `--workers 4`), and repeat at N = 12 to exercise the
threads within a worker.

**Verify**: 4 concurrent requests complete in < 2× the single-request duration
**Verify**: 12 concurrent requests complete in < 4× the single-request duration
**Verify**: the timings and the single-request baseline are recorded

> ### 🚦 MANUAL GATE 16 — operator check
>
> **Report to the operator:** the single-request baseline, the 4-concurrent and
> 12-concurrent timings, and the concurrency mechanism used.
>
> **Operator verifies:**
> 1. **The timings show overlap, not serialization.** If 4 concurrent requests
>    take ≈4× the single-request time, the callbacks are serializing — the flags
>    are wrong or the worker class is not `gthread`.
> 2. The measurement used a **real slow callback**, not a trivial one. A fast
>    endpoint cannot distinguish serialization from parallelism.
> 3. Confirm in the UI container that the running process is
>    `gunicorn --worker-class gthread` — check the process args, not the file.
> 4. If serialization is observed, the fix is to correct the flags and re-measure.
>    **Do not accept the flags as verified because they are present in the file.**
>
> Wait for `PASS` before starting Step 17.

---

### Step 17: Update the documentation

Four categories, all of which are now false or incomplete.

**17a. `CLAUDE.md`**

- Line 15, the "Run app (API + UI)" row: replace the single `uvicorn app.main:app --reload`
  with **two commands**, per Decision 14:
  - API: `PYTHONPATH=src uvicorn app.api_main:app --reload` → `http://127.0.0.1:8000/api/health`
  - UI: `PYTHONPATH=src gunicorn ui_main:server --bind 127.0.0.1:8001 --reload` →
    `http://127.0.0.1:8001/app` (with `API_BASE_URL=http://127.0.0.1:8000` set).
  State plainly that local dev needs **both** processes, and that the Compose
  stack remains the supported path.
- The "Docker Compose services" table: replace the `app` row with `api` and add
  a `ui` row. Neither publishes a host port.
- The architecture section: `src/ui/` and `src/domain/` are new top-level
  packages; update the three-layer diagram to four.
- The import-convention examples: add `from domain.graph_theme import …`.

**17b. `DEVELOPER_QUICK_START.md`** — Option 2 (`:106`, `:134`) currently says
`uvicorn app.main:app --reload`. Update to the two-process flow, and label it
clearly (Option 1, the Compose path, is unchanged and still recommended).

**17c. `USER_GUIDE.md`** — the container/logs sections reference the `app`
service. Update `docker compose logs app` → `logs api`, and note that `ui` is a
separate service.

**17d. `scripts/setup.sh`** — the failure message at `:400` says
`docker compose logs app`; change to `api`. The health poll at `:384` still
targets `https://localhost/api/health`, which is correct. Consider adding a UI
readiness check.

**17e. `.env.example`** — `API_SERVER=http://app:8000/` (`:106`) → `http://api:8000/`.

**17f. `docs/design/authn-authz-design.md`** — **four sections** now state
mechanisms this plan made impossible. Edit them so Plan C is not written against
a stale premise:

1. **Enforcement points** — "ASGI middleware is the only mechanism that can guard
   a mounted WSGI application" is **false**. The UI is a Flask/WSGI service. The
   replacement is Flask `before_request` (redirect to login when no session
   cookie) plus `stream_with_context` for the SSE proxy.
2. **The `/app/stream/<session_id>` proxy route** — its justification referenced
   the `a2wsgi` mount and the `routes_pathname_prefix` asymmetry. It is now a
   plain Flask route on `ui_main:server`.
3. **Deployment Topologies** — "Two containers: the UI runtime and the API
   runtime… They are separated by Plan B" becomes present tense, and the UI
   container's contents listed there are now literally true.
4. **Non-API Surfaces → "Application-internal bypasses → Plan B"** — the three
   in-process callbacks are resolved. Update the table to say so.

**Do not rewrite the rest of that document.** It owns authn/authz; this plan
only corrects what it invalidated.

**Verify**: `grep -rn "uvicorn app.main" CLAUDE.md DEVELOPER_QUICK_START.md` → no matches
**Verify**: `grep -rn "app\.main:app" CLAUDE.md DEVELOPER_QUICK_START.md` → no matches
**Verify**: `grep -n "docker compose logs app" USER_GUIDE.md scripts/setup.sh` → no matches
**Verify**: `grep -n "app:8000" .env.example CLAUDE.md` → no matches
**Verify**: `grep -n "ASGI middleware is the only mechanism" docs/design/authn-authz-design.md` → no matches
**Verify**: `bash -n scripts/setup.sh` → exit 0

> ### 🚦 MANUAL GATE 17 — operator check
>
> **Report to the operator:** the six verify outputs and `git diff` for each file.
>
> **Operator verifies:**
> 1. **The local-dev story is actually followable.** Walk it: start the API in
>    one terminal, the UI in another, and confirm `http://127.0.0.1:8001/app`
>    loads and its callbacks reach the API. `CLAUDE.md` is what every future
>    agent reads — if these two commands are wrong, every subsequent task is
>    misled.
> 2. The Compose services table matches `docker-compose.yml` exactly.
> 3. `authn-authz-design.md` no longer claims an ASGI-mount mechanism for the UI.
>    Read the four edited sections.
> 4. **The doc edits did not stray.** Only the four specified sections changed.
>
> Wait for `PASS` before starting Step 18.

---

### Step 18: Final CI gates and full-stack smoke

```bash
pytest -m unit tests -q
mypy src/
pylint src --score=y
bandit -c .bandit.yml -r src/ -lll
docker compose config -q
```

**Plus the full page sweep**, since this is the last gate:

| Page | Check |
|---|---|
| Chat | streams progressively; sessions list; create/delete |
| Search | query returns results; person search |
| Graph | query executes; spotlight highlights (Step 10's `ids`) |
| Timeline | renders; deep-link to Graph works |
| Analytics | gallery renders; both collaboration cards launch |
| Collaboration Network (org) | plots; filters apply |
| Collaboration Network (ego) | plots; person picker; collaborator cap |
| Catalog | browse; editor loads; favourite toggle |
| Connectors | list; env table renders (Step 8); scan status |
| Settings | runtime settings load; a write round-trips |

**Verify**: all five commands exit 0; `pylint` ≥ 9.0
**Verify**: every page in the sweep renders and its primary action works
**Verify**: `git status --short` shows no files outside the Scope list
**Verify**: `git diff --stat` touches no file under `src/connectors/` (except the zero expected)

> ### 🚦 MANUAL GATE 18 — operator check (final)
>
> **Report to the operator:** all five command outputs, the page-sweep table, and
> `git status --short`.
>
> **Operator verifies:**
> 1. All five gates pass. `pylint` ≥ 9.0.
> 2. `pytest -m unit tests -q` shows **no fewer** tests than the 2340 baseline +
>    this plan's additions. A drop means tests were skipped, not fixed.
> 3. The page sweep is complete. **Do not accept "the main pages work"** — this
>    is the gate that catches a missed call site from Step 14 and a missed import
>    from Steps 1–5.
> 4. No file outside the Scope list was modified.
> 5. The audit's conclusion (Step 15) is reflected: no capability reachable only
>    in the UI layer.
>
> Reply `PASS` to close the plan, then update the Progress tracker and
> `plans/README.md`.

---

### Progress tracker

Mark each cell as you go. `⬜` not started · `🔄` in progress · `✅` passed ·
`❌` failed (stop and report). **Do not start a step whose gate is not `✅`.**

**Phase 1 — pure moves (no behaviour change; the app still runs as one process)**

| Step | What it changes | Automated verify | Manual gate | Status |
|------|-----------------|------------------|-------------|--------|
| 1  | `src/domain/` created; `graph_theme`/`node_size`/`person_network_url` moved; `theme_tokens.py` extracted **with `NODE_TYPE_BASE_STYLES` and the injection loop**, breaking the API→UI edge | suite green, grep gates, `geometry OK` (loop ran without `styles.py`), `mypy` | Operator confirms nothing else changed, backwards edge gone, **geometry moved with the registry** | ✅ passed — plus `COPY src/domain/` added to `Dockerfile.app` (see Maintenance notes) |
| 2  | Collaboration metadata → `src/domain/collaboration/` | suite green, `domain` imports nothing from `app.*`, `mypy` | Operator confirms `algorithm.py` did **not** move | 🔄 automated verify passed — awaiting MANUAL GATE 2 |
| 3  | `analytics/registry.py`, `CONNECTOR_REGISTRY`, `MANAGED_INDEXES` → `src/domain/` | suite green, grep gates, `mypy` | Operator confirms registry contents unchanged | ⬜ |
| 4  | `events.py` → `common/messaging/settings_events.py` | suite green, `aio_pika`-leak check, `mypy` | Operator confirms `common.runtime_settings` is now pure | ⬜ |

**Phase 2 — the structural split**

| Step | What it changes | Automated verify | Manual gate | Status |
|------|-----------------|------------------|-------------|--------|
| 5  | `src/app/dash_app/` → `src/ui/`; `routes_pathname_prefix="/app/"` added | suite green, no `app.dash_app` remains, `mypy` | Operator confirms both prefixes set; app still runs as one process | ⬜ |
| 6  | `main.py` → `api_main.py` + `ui_main.py`; Flask request logging ported | both import; no `a2wsgi`; suite green | Operator confirms `ui_main` imports no FastAPI/DB/transport | ⬜ |
| 7  | 12 import-time constants → function-local reads + regression test | new test passes **and fails on mutation**; grep | Operator **runs the mutation**; test must not be vacuous | ⬜ |
| 8  | MCP env table from `GET /api/v1/settings/`; `NEO4J_URI` message fixed | grep gates, suite green | Operator confirms Connectors page unchanged in browser | ⬜ |
| 9  | Collab + ego bypasses → HTTP, **baseline captured before the swap** | before/after summaries identical; script deleted | Operator confirms baseline was taken pre-swap and sets match exactly | ⬜ |
| 10 | Optional `ids` param on `/search`; spotlight → HTTP | matched-ID sets identical; unscoped unchanged | Operator confirms `ids` is genuinely scoped, not ignored | ⬜ |

**Phase 3 — packaging and runtime**

| Step | What it changes | Automated verify | Manual gate | Status |
|------|-----------------|------------------|-------------|--------|
| 11 | `Dockerfile.api`/`requirements.api.txt`; new `Dockerfile.ui`/`requirements.ui.txt`; UI entrypoint; CI install lines | both images build; UI image free of DB/LLM packages | Operator confirms no migrations in the UI entrypoint; `gthread` flags present | ⬜ |
| 12 | Compose `app`→`api` + new `ui`; nginx upstream split; `depends_on`; healthchecks; `API_SERVER` | compose config, `nginx -t`, both URLs 200, env checks | **Operator runs all 10 checks, including a cold start** | ⬜ |
| 13 | Drop the `app` network alias | grep clean; all healthy | Producer **logs** show the snapshot fetch succeeding | ⬜ |

**Phase 4 — client, audit, docs**

| Step | What it changes | Automated verify | Manual gate | Status |
|------|-----------------|------------------|-------------|--------|
| 14 | `src/ui/api_client.py` created; all 56 call sites migrated | zero raw `requests.*`; suite/`mypy`/`pylint` | Operator confirms no credentials; **full page sweep** | ⬜ |
| 15 | API-completeness audit (`A ⊆ B`, response shapes, orphans) | comparison passes; artifact discarded | Operator reviews mismatch and orphan lists | ⬜ |
| 16 | gunicorn concurrency gate | 4 and 12 concurrent requests overlap | Operator confirms overlap, not serialization | ⬜ |
| 17 | Docs: `CLAUDE.md`, `DEVELOPER_QUICK_START.md`, `USER_GUIDE.md`, `setup.sh`, `.env.example`, `authn-authz-design.md` | six grep gates | Operator **walks the two-process local dev flow** | ⬜ |
| 18 | Full CI gates + full-stack smoke | all five gates; every page renders | Operator signs off the complete page sweep | ⬜ |

---

## Test plan

**New tests:**

- `tests/test_runtime_settings_per_call.py` — Step 7's regression guard. Must
  assert **through the consuming function**, and must fail if a constant is
  reverted to module level. This is the single most important new test.
- `tests/test_domain_purity.py` — asserts `import domain` pulls none of
  `aio_pika`, `neo4j`, `elasticsearch`, `sqlalchemy`, `asyncpg`, `openai`,
  `langchain`, `mcp`, `matplotlib`, `community`. Guards Decision 4 structurally.
- `tests/test_collab_query_param_roundtrip.py` — Step 9's param translation: for
  every `CollaborationNetworkConfig` field, assert the endpoint's query-param name
  and default match what the UI sends. Catches drift between the two
  `from_query_values` callers.
- `tests/test_search_ids_scope.py` — Step 10's `ids` param scopes the ES query and
  sets `size = len(ids)`; absent `ids` leaves behaviour unchanged.

**Regression:** `pytest -m unit tests -q` must hold at **2340 passed, 2 skipped**
or better at every step. A drop in the count is a STOP condition — it means tests
were silently skipped by a missing marker or a broken import.

**Mutations to run (not optional):**

1. Step 7 — revert one constant to module level; the new test must fail.
2. Step 10 — drop `ids` from the ES body; the comparison must fail.
3. Step 5 — remove `routes_pathname_prefix="/app/"`; the UI must stop serving at
   `/app`.
4. Step 12 — remove the `ui` healthcheck; the cold-start check must 502.

## Done criteria

ALL must hold:

- [ ] `pytest -m unit tests -q` exits 0, with ≥ 2340 passed and **0 failed**
- [ ] `mypy src/` exits 0
- [ ] `pylint src --score=y` reports ≥ 9.0
- [ ] `bandit -c .bandit.yml -r src/ -lll` exits 0
- [ ] `docker compose config -q` exits 0
- [ ] `nginx -t` passes
- [ ] `grep -rn "app\.dash_app" src/ tests/` → no matches
- [ ] `grep -rn "from app\.api\.\(graph\|search\)\.v1\.service" src/ui/` → no matches
- [ ] `grep -rn "requests\.\(get\|post\|put\|patch\|delete\)" src/ui/` → no matches
- [ ] `grep -rn "^[A-Z_]* *= *\(runtime_settings\|settings\)\." src/ui/` → no matches
- [ ] `grep -rn "app\.common\.\(graph_theme\|node_size\|person_network_url\)" src/ tests/` → no matches
- [ ] `grep -rn "runtime_settings.events" src/ tests/` → no matches
- [ ] `grep -rn "app:8000" docker-compose.yml src/ .env.example` → no matches
- [ ] `grep -n "app\.main:app" src/app/entrypoint.sh` → **no matches**; it names `app.api_main:app`
- [ ] `grep -c "forwarded-allow-ips" src/app/entrypoint.sh` → 2 (comment + invocation), and the comment block is byte-identical to `git show 5210f00:src/app/entrypoint.sh`
- [ ] `PYTHONPATH=src python -c "import sys, common.runtime_settings; assert not any(m.startswith('aio_pika') for m in sys.modules)"` → exit 0
- [ ] `grep -rn "app\.dash_app" src/app/api/ src/app/db/ src/app/common/` → no matches (the backwards edge is gone)
- [ ] `src/domain/` imports nothing from `app.*`
- [ ] The UI image contains no `neo4j`/`elasticsearch`/`sqlalchemy`/`asyncpg`/`openai`/`langchain`/`matplotlib`
- [ ] The API image contains no `dash`
- [ ] `docker compose exec ui env` shows no `DATABASE_URL`/`OPENAI_API_KEY`/`NEO4J_PASSWORD`/`GITHUB_MCP_TOKEN`/`CONNECTOR_ENCRYPTION_KEY`
- [ ] Producer logs show the snapshot fetch **succeeding** (not the fallback warning)
- [ ] Step 9's before/after collab summaries are **identical**
- [ ] Step 10's matched-ID sets are **identical**
- [ ] Step 16's concurrency measurements show overlap
- [ ] `scripts/capture_collab_baseline.py` is deleted
- [ ] `docs/design/authn-authz-design.md` no longer claims an ASGI-mount mechanism for the UI
- [ ] No files outside the Scope list are modified (`git status`)
- [ ] **All 18 manual gates recorded `✅` in the Progress tracker**
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report back (do not improvise) if:

- **Any of Steps 1–7 changes observable behaviour.** They are pure refactors. The
  app must still run as one process and the suite must be green with the same
  test count.
- **More or fewer than 12 module-level constants** exist in `src/ui/` (Step 7).
  The count is load-bearing; report the actual list.
- **More or fewer than 56 `requests.*` call sites** exist in `src/ui/` (Step 14).
- **The Step 9 before/after baselines differ.** Do not relax the comparison. Fix
  the param mapping, re-run, and report.
- **The Step 10 matched-ID sets differ.** Same.
- **`get_theme_tokens` cannot be extracted without changing `styles.py`'s
  behaviour** (Step 1). The extraction *does* require moving `NODE_TYPE_BASE_STYLES`
  and the `THEME_TOKENS` injection loop (`styles.py:257,280-285`) into
  `domain/theme_tokens.py` — that is a move, not a restructure, and is expected.
  Restructuring `styles.py`'s remaining derivation of `COLOR_*` / `_token()` /
  `TOKENS` is what must not happen: if the extraction appears to need that, stop
  and report instead.
- **`domain.theme_tokens.get_theme_tokens(...)` returns a node type without a
  `.shape` / `.width` / `.height` key, or returns `ellipse`/`60px` for a typed
  node** (Step 1). The injection loop did not move with the registry. Do not
  patch the values in — move the loop. See Gate 1 check 5.
- **`common.runtime_settings` still imports `aio_pika` after Step 4.** The eviction
  was incomplete.
- **A test count drops** at any step, rather than a test failing. A silently
  skipped test is worse than a failing one.
- **`docker compose up` fails with `bind: address already in use` on 80/443.**
  Report which process holds the port; do not remap.
- **Step 12's cold start shows a persistent 502 on `/app`.** The `depends_on`
  graph is wrong; report the observed sequence rather than adding sleeps.
- **Producers fall back to default runtime settings** after Step 12 or 13. Check
  the logs for `Runtime settings API unreachable` — that is the silent-degradation
  failure mode, and it means the rename is incomplete.
- **Any Step 18 page fails to render or its primary action errors.**
- **A change appears to require touching an out-of-scope file** — in particular
  anything under `src/connectors/`, or adding `AUTH_*` / `KEYCLOAK_*` settings.
- **`gunicorn` cannot be installed or the UI image build fails on it.**

## Maintenance notes

**What future changes interact with this:**

- **Plan C (Keycloak)** builds directly on this. It:
  1. Teaches `src/ui/api_client.py` to attach `Authorization: Bearer` — the
     client's single chokepoint is what makes that a one-file change.
  2. Adds Flask `before_request` auth to the UI (not ASGI middleware — see the
     revised `authn-authz-design.md`).
  3. Adds the `/app/stream/<session_id>` SSE proxy as a Flask route.
  4. Sets `AUTH_COOKIE_SECURE` derived from `EXTERNAL_BASE_URL`'s scheme.
- **The `src/app/` → `src/api/` rename** is deferred to its own plan (Decision 6).
  It is cosmetic: 238 files import `app.*`, no isolation gain. Do it when this
  plan and Plan C have both settled.
- **`scripts/dev.sh`** was considered and deferred (Decision 14). If local-dev
  friction becomes a real complaint, that is the shape to add.
- **A new UI→API call** must go through `api_client.py`. A raw `requests` call
  reintroduces the per-site timeout bug Step 7 fixed and the auth gap Plan C will
  close. The `grep` in the done criteria is the guard.
- **A new pure shared module** belongs in `src/domain/`, and must keep the
  package's transport-free property (`tests/test_domain_purity.py`).
- **A new service** must not be named `app`. The alias is gone; the name is
  retired.
- **Adding a provider or a streaming endpoint** may need the nginx upstream and
  `proxy_buffering off` revisited — see `docs/design/nginx-tls-design.md`.

**What a reviewer should scrutinize:**

- **`src/ui_main.py` imports no FastAPI, no `a2wsgi`, no `app.db`, no
  `aio_pika`.** This is the isolation property; reading its imports is the check.
- **`domain/theme_tokens.py` owns the geometry injection loop, not just the
  `THEME_TOKENS` dict.** `graph.node.<type>.shape/.width/.height` are computed at
  import by a loop over `NODE_TYPE_BASE_STYLES` (`styles.py:280-285`), not
  written literally in the registry. The API resolves node shapes from those
  keys (`app/common/graph_theme.py:286-288`), and after the split the API process
  no longer imports `styles.py` — so a registry moved without its loop degrades
  every typed node to an `ellipse` at 60×50 on Graph, Timeline and both
  Collaboration Network pages, with a green suite and no failing test.
- **`routes_pathname_prefix="/app/"`** is present in `create_dash_app()`. Without
  it the split cannot serve the UI, and its absence would fail loudly — but a
  partial value (one prefix set, not both) fails confusingly.
- **`requirements.ui.txt` includes `gunicorn` and excludes the data-store/LLM
  packages.** The exclusion list is the enforcement of Decision 1.
- **`client_max_body_size 50m` survives the nginx edit.** It is a Plan 051 fix and
  the collaboration pages depend on it.
- **The `/app` location has no trailing slash on `proxy_pass`.**
- **`api_client.py` carries no credentials.** That is the Plan B / Plan C boundary.
- **The UI healthcheck probes `/app/`, not the API.** Otherwise the UI flaps when
  the API restarts.
- **Steps 1–7 are behaviour-preserving.** A reviewer should be able to read each
  one's diff and see only moved code and rewritten imports.
- **`docs/design/authn-authz-design.md` was edited in exactly four places.**

**Explicitly deferred out of this plan:**

- The `src/app/` → `src/api/` package rename — its own plan.
- `scripts/dev.sh` — two documented commands instead.
- Any credential handling in `api_client.py` — Plan C.
- The `/app/stream/<id>` SSE proxy route — Plan C.
- `AUTH_*`, `KEYCLOAK_*`, per-user ownership, the `auth_session` table — Plan C.
- FastAPI's `/docs`, `/redoc`, `/openapi.json` — Plan E.
- Per-person data scoping — Plan F.

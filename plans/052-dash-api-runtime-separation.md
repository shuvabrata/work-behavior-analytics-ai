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
> **Every step ends at a stable state — the stable-state rule.** After each
> step, `docker compose up -d --build` must come up healthy and the UI must be
> browsable at `https://localhost/app`. The operator rebuilds the stack after
> every step, so a step that leaves it unable to start is a defect in the step,
> not something to work around by running a stale image. Concretely: **a step may
> only remove something when the same step makes its replacement real.** This is
> why `src/app/main.py` survives Step 5 as a temporary composition and is deleted
> in Step 8, in the same step that gives the UI its own container.
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
>   `requirements.ui.txt` do **not** exist at drift-check time — Step 8 creates
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
   (Step 11) provides this.

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

**Three rows above are container-fatal once the images split, and they are the
first thing Step 6b fixes.** The UI image ships no database driver and gets no
`DATABASE_URL`, so each of these raises at import time in its own way:

| Module | UI files | Why the UI container cannot import it |
|---|---|---|
| `app.runtime_settings` | 13 | its module body imports `sqlalchemy.ext.asyncio.AsyncSession` (`runtime_settings.py:21`) |
| `app.common.timezone` | 8 | imports `app.runtime_settings` (`timezone.py:11`), inheriting the `sqlalchemy` import |
| `app.settings` | 15 | `Settings()` requires `DATABASE_URL`, which the UI service is deliberately not given, and the UI image ships no `.env` |

Measured under simulated UI-container conditions (the package absent from the
path): `import app.common.timezone` → `ModuleNotFoundError: No module named
'sqlalchemy'`; `from app.settings import Settings` → `ValidationError:
DATABASE_URL Field required`.

The bare counts understate this. `app.common.timezone` is imported by
`chat.py` and `search.py` — sidebar pages — so this fails on the **first page
load**, and `create_dash_app()` pulls the whole `pages/` tree, so `ui_main.py`
importing cleanly proves nothing about its transitive imports. Step 6b covers the
fix; Step 6b-v builds the test that catches it locally rather than as a Step 8
crash.

### The three in-process bypasses

A request to the unauthenticated `POST /app/_dash-update-component` reaches these
without touching `/api/v1`. **Securing the API alone would leave them open.**

| Callback | Import | Reaches | Endpoint to use instead |
|---|---|---|---|
| `pages/collaboration_network/callbacks/filter.py:12` | `get_collaboration_network` | Neo4j | `GET /api/v1/graph/collaboration-network` |
| `pages/collaboration_network_ego/callbacks/filter.py:13` | `get_ego_network` | Neo4j | `GET /api/v1/graph/collaboration-network/ego` |
| `pages/graph/callbacks/spotlight.py:14` | `search_in_graph` | Elasticsearch | `GET /api/v1/search` — **needs an `ids` param, see Step 7** |

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

**This fix applies only once the app is *standalone* — it is Step 8's edit, not
Step 5's.** While the app is still mounted at `/app` via `WSGIMiddleware`
(Steps 5–7), the mount strips `/app` before Flask sees the request, so the
handlers must stay registered at `/`. Setting `routes_pathname_prefix='/app/'`
in that state 404s every UI route. Step 5a records the full reasoning; the short
version is that **the mount and this prefix are mutually exclusive**, and
whichever step changes one must change the other.

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
highlight. Step 7 adds an `ids` param instead.

### Live stack facts (used for gate expectations)

The stack is populated: `GET /api/v1/graph/collaboration-network?lookback_days=90`
returns `num_people = 223`, `num_pairs = 4818`, `num_communities = 23`,
`modularity = 0.2382`, `elements = 5041`, in a **1.67 MB** response. That size
matters for the concurrency gate (Step 12) — it is why Plan 051's
`client_max_body_size` defect bit.

**The OpenAPI schema is not reachable over TLS.** `GET https://localhost/openapi.json`
→ **404** (Plan 051's deliberate consequence). It **is** reachable
container-internally: `docker exec wba-ai-app python -c "...urllib...'http://localhost:8000/openapi.json'"`
→ 39 paths. The audit step (Step 11) must run inside the API container.

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
persisted row beats any env change. Step 8 must check whether a row exists and
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
`DEVELOPER_QUICK_START.md:106,134`. After Step 8, `app.main` no longer exists as
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
| 12 | Collaboration bypasses | Swap cleanly; **before/after baseline script** captured and run in the same step, over a **shared** config→query-param serializer so the re-run exercises the swapped code (a script-private serializer would make the gate vacuous). A permanent round-trip unit test carries the guard after the script is deleted. Spotlight needs an **optional `ids` param** on `/search`, gated on empirical equivalence |
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
Step 8 renames it to `wba-ai-api`. Commands in Steps 1–7 must use
`wba-ai-app`; Steps 8–14 use `wba-ai-api`. Where a command appears in this table
without a step context, use `docker compose exec api …` (service name), which
resolves correctly on both sides of the rename because Step 8 keeps the `app`
network alias through Step 9.

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
- `src/ui_main.py`, `src/app/api_main.py` (create); `src/app/main.py` (delete in Step 8)
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
- `scripts/capture_ui_baseline.py` (create, **temporary** — deleted in Step 7)
- `src/ui/collaboration_params.py` + `tests/test_collab_query_param_roundtrip.py`
  (create, **permanent** — Step 7's shared config→query-param serializer)
- `src/ui/api_client.py` (create in Step 7 with `get_json` + the status→exception
  mapping; **extended** in Step 10) + `tests/test_ui_api_client_status_mapping.py`
  (create, **permanent** — guards the mapping that keeps the collaboration
  empty/invalid banners working)
- `src/domain/settings.py` (create in Step 6b — `UISettings`, the credential-free
  base `ApiSettings` extends), `src/domain/timezone.py` (moved from
  `src/app/common/timezone.py` in Step 6b)
- `src/ui/runtime_settings.py`, `src/ui/settings.py` (create in Step 6b — the
  UI's DB-free replacements) + `tests/test_ui_isolation.py` (create,
  **permanent** — imports every `src/ui/**` module with the DB/LLM packages
  blocked, so the boot-time `ModuleNotFoundError` fails locally instead of as a
  Step 8 502)
- `CLAUDE.md`, `DEVELOPER_QUICK_START.md`, `USER_GUIDE.md`, `.env.example`
- `docs/design/authn-authz-design.md` — the four sections in Step 13 only
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
  split (Steps 5–7), go live (Steps 8–9), client/audit/docs (Steps 10–14).
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
loop still runs, the suite stays green — and it surfaces only at Step 8/14 as a
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
snapshot route in Step 6, not the pure-move route.

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

**One rule governs this phase: a step may only remove something when the same
step makes its replacement real.** The UI stays part of a single running process
all the way through Step 7; the split goes live in Step 8, in the same step that
adds the compose service which runs the UI. That is why Step 8 is the largest
step in the plan — merging is driven by stability, not by size.

**Every step ends with a stack you can rebuild and browse.**
`docker compose up -d --build` comes up healthy, `pytest -m unit tests -q` is
green, and the UI is browsable at `https://localhost/app`. A step that leaves the
stack unable to start is not "in progress" — it is a STOP condition.

---

### Step 5: Move `src/app/dash_app/` → `src/ui/` and create the two entrypoints

**This step ends with the app still running as one process, and that is the
point.** It moves the UI package and creates both future entrypoints, but the API
process keeps serving the UI through a small temporary composition module
(`src/app/main.py`, reduced to a few lines). Nothing is taken away here, which is
what lets Steps 6 and 7 be verified against a working UI.

**5a. Move the package.**

**Leave `create_dash_app()`'s prefixes exactly as they are.** In
`src/ui/layout.py`, `create_dash_app()` (`:23-34`) sets only
`requests_pathname_prefix="/app/"`, and **it must still set only that after this
step**. `routes_pathname_prefix` is added in **Step 8**, in the same step that
removes the mount.

**Why it cannot move here, and this is the trap.** These two are mutually
exclusive, and the wrong one silently 404s the entire UI:

| Serving mode | `routes_pathname_prefix` | Dash registers at |
|---|---|---|
| Mounted (`WSGIMiddleware` at `/app`) — **Steps 5–7** | `"/"` (the default — set nothing) | `/`, `/_dash-layout`, … |
| Standalone (gunicorn, nginx `location /app`) — **Step 8+** | `"/app/"` | `/app/`, `/app/_dash-layout`, … |

`Starlette`'s `Mount` **strips** the mount path before handing the request to the
WSGI app, so a browser request for `/app/_dash-update-component` arrives at Flask
as `/_dash-update-component`. Today's root-registered handlers match it. Add
`routes_pathname_prefix="/app/"` while the mount is still there and the handlers
move to `/app/_dash-update-component` — which nothing ever reaches, because the
mount already ate the `/app`. Every UI route 404s, and only the doubled path
`/app/app/_dash-layout` answers.

Verified by simulation against this repo's real `create_dash_app()`, mounted
exactly as 5d specifies:

```
routes_pathname_prefix="/app/" set, still mounted at /app:
  /app/                          404
  /app/chat                      404
  /app/_dash-layout              404
  /app/_dash-update-component    404

unchanged (requests_pathname_prefix only), still mounted at /app:
  /app/                          200
  /app/chat                      200
  /app/_dash-layout              200
  /app/_dash-update-component    200
```

The "verified fix for standalone serving" in "Current state" (`:228-232`) is
correct — **for Step 8**, where nothing mounts the app and nginx preserves the
full `/app/...` URI. Applying it at Step 5 breaks the stable-state rule at the
first structural step, right after the rename and its 204 test-file rewrites.

**Everything else in the UI is unchanged.** In particular `display_page`'s 18
hardcoded `/app/...` route strings (`layout.py:139-176`) and the 69 hardcoded
`/app/` literals keep working in both modes, because the path Dash *sees* is
`/app/...` either way — via the mount in Steps 5–7, natively from Step 8.

**Rewrite every absolute `app.dash_app.*` reference.** Relative imports *inside*
the package (`from ..layout import ...`) stay valid across the move and must be
left alone. Measured on the current tree — the earlier "98 sites" figure predates
Phase 1, which moved the modules that used to be the outside-`src/` referrers:

| | Files | Sites |
|---|---|---|
| `src/` | 53 | 117 |
| `tests/` | 43 | 204 |

Of the 117 in `src/`, **115 are inside the package itself** (`app.dash_app.styles`
→ `ui.styles`, and so on). Only **two** are outside it, and only one is a real
import:

- `src/app/main.py:24` — `from app.dash_app.layout import create_dash_app` →
  `from ui.layout import create_dash_app`. **This import stays**; `main.py` keeps
  the Dash mount until Step 8.
- `src/domain/graph_theme.py:35` — a comment naming `app.dash_app.graph_styles`.
  Update the prose.

**Three more prose mentions use the slash form (`app/dash_app/...`), so the
`app\.dash_app` grep will not catch them.** They are comments pointing at paths
that are about to stop existing; update them in this step or they become
misleading:

- `src/domain/node_size.py:5` — `(app/dash_app/...)`
- `src/domain/node_size.py:13` — `# app/dash_app/graph_styles.py :: build_cytoscape_stylesheet.`
- `src/domain/es_indexes.py:8` — ```app/dash_app/pages/search.py```

**Do not move `assets/`.** `src/ui/assets/` stays exactly where it is relative to
`layout.py`, so Dash's asset discovery is unchanged.

**Verify**: `pytest -m unit tests -q` → 2340+ passed, 0 failed
**Verify**: `grep -rn "app\.dash_app" src/ tests/` → no matches
**Verify**: `ls src/ui/assets/` → the four existing asset files
**Verify**: `mypy src/` → exit 0

**5b. Create `src/app/api_main.py`.**

Copy `src/app/main.py` **minus** the Dash mount and the `create_dash_app` import.
Everything else stays: the lifespan, the RabbitMQ connection,
`add_request_context`, the 11 routers. This is the API process exactly as it will
run after the split. It exists from here on for two reasons: the test suite gets
a Dash-free app to import (5e), and Step 8 has a module to point the API
entrypoint at.

**5c. Create `src/ui_main.py`.**

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

**Expected and transient: `/app` requests are logged twice between now and
Step 8.** Once 5d mounts `ui_main.server`, FastAPI's `add_request_context` still
wraps the whole app — including the mounted WSGI path — so each page load emits
both an API-side `[HTTP] request_complete` and a Flask-side one. That duplication
is a consequence of one process serving both, and it disappears at Step 8 when
the mount does. **Do not "fix" it by removing either hook.** Note it in the gate
report so the operator does not read it as a defect.

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

**5d. Reduce `src/app/main.py` to a temporary composition. Do not delete it.**

Replace the whole file with:

```python
"""Temporary single-process entrypoint — deleted in Step 8.

The UI and the API share one process until Step 8, which gives the UI its own
container and entrypoint. Deleting this module before then would leave
``entrypoint.sh`` (still running ``uvicorn app.main:app``) pointing at nothing,
and the stack could not be rebuilt.
"""
from a2wsgi import WSGIMiddleware

from app.api_main import app
from ui_main import server

app.mount("/app", WSGIMiddleware(server))  # type: ignore[arg-type]
```

**Mount `ui_main.server`, not a fresh `create_dash_app()`.** This matters: a fresh
call would build a *second* Dash/Flask instance, so the `ui_main` request-logging
hooks written in 5c would be dead code until Step 8 and would first execute in
production. Mounting `ui_main.server` means the object running traffic from this
step onward is the same one Step 8 serves, so the hooks are exercised by every
page you browse in Steps 5–7.

**One thing *does* change at Step 8**: `ui_main.server`'s Dash instance was built
by `create_dash_app()`, and 8a-ii edits that function to add
`routes_pathname_prefix="/app/"`. So Step 8 is not only a packaging change — it is
also the step where the UI's handler registration moves to `/app`. That is
deliberate and is why 8a-ii and 8c must land together; nothing else about
`ui_main.py` changes.

**Why a composition and not a copy.** This module is deliberately *not* a second
copy of `api_main`'s lifespan and router list. It **is** `api_main`, with the Dash
mount re-attached. A copy would drift while Steps 6 and 7 edit call sites, and
the drift would be invisible until Step 8.

**Why not delete it and repoint the entrypoint now.** Because there is nothing to
run the UI in yet: the `ui` service does not exist in `docker-compose.yml` until
Step 8. Repointing the API entrypoint to `api_main` now would drop the Dash mount
with no replacement, and Steps 6–7 could not be browsed at all. This is the
stable-state rule from the top of the phase, applied concretely.

**5e. Repoint every test that imported `app.main`.** Measured: **11 test files**
import `app.main` (26 mention it). They build the app via
`httpx.ASGITransport(app=app.main.app)` or `TestClient(app.main.app)`. Point them
at `app.api_main` — they exercise API routes only, and the API app is identical
minus a mount they never touch. (The composition module still exists, so leaving
them on `app.main` would also work; repoint anyway, so the tests do not depend on
a module Step 8 deletes.)

**Repoint every test that imported it, in this same step.** Measured: **11 test
files** import `app.main` (26 mention it). They build the app via
`httpx.ASGITransport(app=app.main.app)` or `TestClient(app.main.app)`.

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

**One file needs more than a rename: `tests/test_proxy_awareness.py`.** It does
not import `app.main` — it mentions it only in prose (line 14, explaining why a
test that drives `app.main.app` never sees uvicorn's middleware). Update that
prose to name `app.api_main`, or it becomes a docstring referencing a module that
no longer exists. Plan 051's Gate 6 already recorded this file as having a known
test-depth gap; do not change its behaviour while editing its comment.

**`src/app/entrypoint.sh` is deliberately left alone — and this time it is not
broken.** It still runs `uvicorn app.main:app` (line 45), and `main.py` still
exists and still mounts Dash, so the entrypoint remains correct. It is repointed
to `app.api_main:app` in Step 8, in the same step that removes the mount.

**Step 8 must not forget it.** See that step's "Repoint the API entrypoint"
instruction — it is the single most load-bearing line in the packaging phase,
because if it is missed the API container fails to start and every gate from
Step 8 onward is blocked.

**Verify**: `pytest -m unit tests -q` → 2340+ passed, 0 failed
**Verify**: `grep -rn "app\.dash_app" src/ tests/` → no matches
**Verify**: `grep -rln "app\.main" tests/ | wc -l` → 0
**Verify**: `PYTHONPATH=src python -c "import app.api_main; print('api OK')"`
**Verify**: `PYTHONPATH=src python -c "import ui_main; print('ui OK', type(ui_main.server))"`
**Verify**: `PYTHONPATH=src python -c "import app.main; print('composition OK')"`
**Verify**: `grep -rn "WSGIMiddleware\|a2wsgi" src/app/api_main.py src/ui/ src/ui_main.py` → no matches
**Verify**: `grep -n "routes_pathname_prefix" src/ui/layout.py` → **no matches** (the prefix is Step 8's edit, not this step's; see 5a)
**Verify**: `docker compose up -d --build` → healthy; `curl -sf -o /dev/null -w '%{http_code}' https://localhost/app/` → `200`
**Verify**: `curl -sf -o /dev/null -w '%{http_code}' https://localhost/app/chat` → `200` (a real Dash route, not just the index — this is what catches a prefix/mount mismatch)
**Verify**: `mypy src/` → exit 0

> ### 🚦 MANUAL GATE 5 — operator check
>
> **Report to the operator:** the verify outputs, `git diff --stat`, and
> `git status --short` (expect many renames).
>
> **Operator verifies:**
> 1. `src/ui/` exists and `src/app/dash_app/` does not.
> 2. **`routes_pathname_prefix` is ABSENT from `create_dash_app()` in
>    `src/ui/layout.py`.** This is deliberately the opposite of what an earlier
>    draft of this plan said, so check it explicitly rather than by expectation.
>    The UI is still *mounted* at `/app` in this step, and mounting strips the
>    prefix; a `/app/`-rooted handler registration would therefore 404 every UI
>    route. The prefix lands in Step 8, where the mount goes away. Confirm the
>    UI actually serves: `/app/` **and** `/app/chat` both return `200`.
> 3. Meta-files whose names would move silently, `dash_app/styles.py` → `src/ui/styles.py`,
>    `pages/**` → `src/ui/pages/**`.
> 4. `src/app/api_main.py` and `src/ui_main.py` both exist, and `src/app/main.py`
>    **still exists** as the temporary composition. It must not be deleted in this
>    step — Step 8 deletes it.
> 5. `src/ui_main.py` imports **no** FastAPI, no `a2wsgi`, no `app.db`, no
>    scheduler, no `aio_pika`. This is the isolation property — check it by
>    reading the file's imports, not by trusting the suite.
> 6. `ui_main.server` is a Flask app (the verify prints the type).
> 7. The Flask logging hooks exist and use the same field names as
>    `api_main.py`'s `add_request_context`.
> 8. **`grep -rn "WSGIMiddleware\|a2wsgi" src/app/api_main.py src/ui/ src/ui_main.py`
>    is empty.** `src/app/main.py` is the only remaining user, and that is the
>    temporary composition. If `api_main.py` still mounts Dash, the split did not
>    happen.
> 9. The test count did **not** drop (2340 baseline), and all 11 test files that
>    imported `app.main` were repointed to `app.api_main`
>    (`grep -rln "app\.main" tests/` → 0).
> 10. **The stack still runs, and this is the check that matters.**
>     `docker compose up -d --build` comes up healthy and `https://localhost/app`
>     renders. Nothing user-visible changed in this step; if the UI is gone, the
>     composition module is wrong.
> 11. **`main.py` mounts `ui_main.server`, not a fresh `create_dash_app()`.**
>     Read the file. A fresh call would leave the 5c hooks dead until Step 8.
> 12. **Both log hooks are live.** Load a page and confirm the container logs show
>     a Flask-side `[HTTP] request_complete` alongside the API-side one. Two lines
>     per `/app` request is expected here and is documented in 5c — it is not a
>     defect, and it ends at Step 8.
>
> Wait for `PASS` before starting Step 6.

---

### Step 6: Stop the UI reading the API's configuration

Three leaks, one step. All are the same class of defect: the UI holds a copy of
configuration it should be asking for, and the copy goes stale, leaks a secret,
or drags a database driver into a container that must not have one. None needs
the split to be real — all three are fixable, and verifiable, while the UI is
still part of the one process.

**Order matters: 6a → 6b → 6c.** 6b restructures the UI's access to every
setting, and 6a's conversions and 6c's fetches both land on top of it. Doing 6c
before 6b, or 6b after 6c, means redoing work.

**6b is the one that must not be skipped, and it is the one whose absence is
silent until the split.** It is not a tidiness pass: without it the UI container
cannot start at all (see below). 6a and 6c are correctness fixes that would be
worth doing on their own merits.

**6a. Convert the 12 import-time constants to function-local reads.**

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

**Verify (6a)**: `pytest -m unit tests -q` → 2340+ passed, 0 failed, **including the new test**
**Verify (6a)**: the new test **fails** if you revert one constant to module level (run this mutation; do not skip it)
**Verify (6a)**: `grep -rn "^[A-Z_]* *= *\(runtime_settings\|settings\)\." src/ui/` → no matches

---

**6b. Give the UI DB-free replacements for `app.runtime_settings`,
`app.common.timezone` and `app.settings`.**

**This is the step that decides whether the split works at all.** Skip it and the
UI container crash-loops on boot in Step 8 with `ModuleNotFoundError` — and every
gate before Step 8's cold-start check passes anyway. Do it here, not at Step 8:
it is the same class of leak this step exists to close, it needs no container to
fix or verify, and it is a 21-file import rewrite that must not be bolted onto
Step 8's packaging change.

**The problem, measured.** Three modules the UI imports reach a dependency the UI
image does not have. Each was confirmed on the live tree under simulated
UI-container conditions (the package absent from the path):

| UI imports (files) | Via | Reaches | Fails in the UI image |
|---|---|---|---|
| `app.runtime_settings` (13) | — | `sqlalchemy.ext.asyncio.AsyncSession` (`runtime_settings.py:21`) | `ModuleNotFoundError: No module named 'sqlalchemy'` |
| `app.common.timezone` (8) | `from app.runtime_settings import runtime_settings` (`timezone.py:11`) | the same `sqlalchemy` import | same |
| `app.settings` (13) | — | `Settings()` needs `DATABASE_URL`, which the UI service deliberately does not get, and `.env` is not shipped to the UI image | `ValidationError: DATABASE_URL Field required` |

`app.common.timezone` is the sharpest of the three because the UI has no
alternative: `to_app_timezone` / `humanize_duration` are imported by 8 files
including `chat.py` and `search.py` — sidebar pages, so this fails on the **first
page load**, not in a corner.

**Why Step 6a does not cover this.** 6a changes *when* the settings are read, not
*who* is imported. Every one of these `from … import …` statements stays at the top
of its file, so the module body still executes. 6a's own verify passes with all
21 files untouched — it greps for module-level *assignments*
(`^[A-Z_]* *= *…`), never for import statements.

**6b-i. Create the shared, DB-free settings base.**

Create `src/domain/settings.py` holding the fields **both** runtimes need and
**no** credential field. This is Decision 3, and Step 6 is where it is built —
without it, `ApiSettings` has nothing to extend and `UISettings` does not exist:

```python
"""Settings shared by the API runtime and the UI runtime.

Fields here must be safe for the UI container, which holds no database driver,
no data-store credentials and no LLM provider key. Anything secret or
DB-adjacent belongs on ``ApiSettings`` in ``src/app/settings.py``, not here.
"""
```

- Move the UI-relevant fields (`API_BASE_URL`, `EXTERNAL_BASE_URL`, `TIMEZONE`,
  `UI_DATE_FORMAT`, `UI_DATETIME_FORMAT`, the `LOG_*` values,
  `GRAPH_UI_*`, `HTTP_REQUEST_TIMEOUT`, `UI_*`) onto `UISettings`.
- `UISettings` must carry **no** `DATABASE_URL`, `NEO4J_*`, `ELASTICSEARCH_*`,
  `OPENAI_API_KEY`, `CUSTOM_API_TOKEN`, `GITHUB_MCP_TOKEN`,
  `ATLASSIAN_MCP_TOKEN`, `RABBITMQ_URL` or `CONNECTOR_ENCRYPTION_KEY`.
- In `src/app/settings.py`, `class ApiSettings(UISettings)` adds those back.
  Keeping `DATABASE_URL` with no default is what makes `ApiSettings`
  unconstructable in the UI — that is the type-level enforcement Decision 3
  specifies, and it is only real once `UISettings` exists.

**6b-ii. Create `src/ui/runtime_settings.py` — the UI's cache.**

The UI keeps the **same surface** (`get_int`/`get`/`refresh`) so the 13 call
sites change only their import line, not their bodies:

```python
"""The UI runtime's runtime-settings cache.

Same interface as ``app.runtime_settings``, but sourced from the API over HTTP
instead of from the database — the UI holds no driver and no DB credentials. The
snapshot endpoint (``GET /api/v1/settings/runtime-snapshot``) is the same one the
producer daemons and the signal consumer already use.
"""
```

- Seed it from `UISettings` at import (env-configured values available
  immediately, mirroring `app/runtime_settings.py:86-88`).
- Refresh it with `common.runtime_settings.client.fetch_runtime_snapshot`
  (**pure** since Step 4 evicted `events.py`, and already used by
  `connectors/producers/daemon_common.py:137` and
  `connectors/consumers/main.py:207` — reuse this, do not invent a second
  snapshot path).
- Refresh on startup and on each use for a long-lived process, or lazily with a
  short TTL. `fetch_runtime_snapshot` already degrades to env/defaults on
  failure (`client.py:55-63`), so an unreachable API degrades rather than
  crashes — acceptable, but **log at the same level the producers do**, because
  silent degradation is the failure mode this plan already flags.
- Do **not** add a RabbitMQ listener here. `common/messaging/settings_events.py`
  needs `aio_pika`, which the UI image does not carry (that is exactly why
  Step 4 made `common/runtime_settings` structurally pure). Poll or refresh per
  request; do not import the events module.

**6b-iii. Move the timezone helpers to `src/domain/timezone.py`.**

`get_app_timezone`, `to_app_timezone`, `now_in_app_timezone`,
`humanize_duration` move from `src/app/common/timezone.py` to
`src/domain/timezone.py`. Verified: the **only** importers are the 8 UI files and
`tests/test_timezone_settings.py:7` — no API, scheduler, connector or consumer
module imports it, so this is a clean move with no API-side caller to preserve.

The functions are pure `zoneinfo` arithmetic; only the *source* of the timezone
string was DB-adjacent. Point `get_app_timezone` at the UI's cache:

```python
from ui.runtime_settings import runtime_settings   # or an injected getter
```

**One wrinkle to handle, not to gloss over.** `src/domain/` must not import from
`ui.*` — the package contract from Step 1 forbids it (the API cannot depend on
the UI). So `domain.timezone` must **not** hard-import `ui.runtime_settings`.
Two acceptable shapes; pick one and say which in the gate report:

1. `domain.timezone.get_app_timezone()` reads the **shared** cache object, which
   each runtime populates at startup — the domain module owns the cache, and
   `app/runtime_settings.py` and `ui/runtime_settings.py` are thin bindings that
   point at it.
2. The timezone source is **injected** once at startup, with a module-level
   default of `UTC`.

Shape 1 keeps every call site's signature unchanged, which is what makes the
8 UI files a pure import-line edit. Prefer it unless it drags a second cache
into existence — in which case say so and take shape 2.

**6b-iv. Repoint the importers.**

Update **every** importer in `src/` and `tests/`. The three renames:

| Now | Becomes | UI files | Other importers |
|---|---|---|---|
| `from app.runtime_settings import runtime_settings` | `from ui.runtime_settings import runtime_settings` | 13 | — |
| `from app.settings import settings` | `from ui.settings import UISettings` (or a `ui.settings.settings` singleton) | 13 | API keeps `app.settings` |
| `from app.common.timezone import …` | `from domain.timezone import …` | 8 | `tests/test_timezone_settings.py` |

The 13 `app.settings` files are the subtle ones: most read only
`API_BASE_URL`, `UI_*`, `TIMEZONE` or `GRAPH_UI_*` — all on `UISettings`. Check
each rather than assuming: any file reading a **credential** field is a Step 6c
case (the MCP table) or a UI→API call that has not been made yet, and is a STOP
condition to report rather than paper over.

**6b-v. Add the verify that actually catches this.**

Every existing check in this plan is blind to this defect — the suite runs where
`sqlalchemy` **is** installed, the Dockerfile copies files without importing
them, and Gate 5 checks the imports of `ui_main.py` alone while `create_dash_app()`
pulls the entire `pages/` tree transitively. So add a real one: a test that
imports every `src/ui/**` module in a process where the DB/LLM packages are
absent. `tests/test_ui_isolation.py`, `pytestmark = pytest.mark.unit`:

```python
def test_ui_modules_import_without_db_or_llm_packages():
    """Every src/ui/** module must import with no database driver present.

    Regression guard: 21 UI files imported app.runtime_settings /
    app.common.timezone / app.settings, each of which pulls sqlalchemy or
    requires DATABASE_URL. The UI image ships neither, so the container
    crash-looped at boot with ModuleNotFoundError while every other gate
    passed.
    """
```

Block the packages the way `Dockerfile.ui`'s exclusion list names them
(`sqlalchemy`, `asyncpg`, `neo4j`, `elasticsearch`, `openai`, `aio_pika`, …) with
a `sys.meta_path` finder that raises `ModuleNotFoundError`, then import each
module under `src/ui/` by walking the package. This is the one check that fails
**fast and locally** instead of as a 502 in Step 8.

**The approach is verified, not assumed — including that it fails on the
current tree.** Run against today's unfixed code, importing
`app.dash_app.pages.chat` with those packages blocked produces exactly the
chain this defect is:

```
File "src/app/dash_app/pages/chat.py", line 8, in <module>
    from app.common.timezone import now_in_app_timezone, humanize_duration
File "src/app/common/timezone.py", line 8, in <module>
    from app.runtime_settings import runtime_settings
File "src/app/runtime_settings.py", line 21, in <module>
    from sqlalchemy.ext.asyncio import AsyncSession
ModuleNotFoundError: No module named 'sqlalchemy' (UI image)
```

So the test is non-vacuous by construction: it fails before Step 6b and passes
after. Two details that make it real rather than decorative — **assert the
blocker is effective** (import `sqlalchemy` normally first, then confirm it
raises once the finder is installed), because a finder that matches nothing
makes the test pass for the wrong reason; and **walk the package with
`pkgutil.walk_packages`** so a newly added UI module is covered without anyone
remembering to list it.

**Verify (6b)**: `grep -rn "from app\.runtime_settings import\|from app\.common\.timezone import\|from app\.settings import" src/ui/` → **no matches**
**Verify (6b)**: `PYTHONPATH=src python -c "import domain.settings, domain.timezone; print('domain OK')"` → `domain OK`, and `grep -rn "app\.\|ui\." src/domain/settings.py src/domain/timezone.py` shows no forbidden import
**Verify (6b)**: `PYTHONPATH=src python -c "from ui.runtime_settings import runtime_settings; print(runtime_settings.get_int('HTTP_REQUEST_TIMEOUT'))"` → an integer, no traceback
**Verify (6b)**: `pytest tests/test_ui_isolation.py -q` → all pass, **and it fails when you re-add one `from app.runtime_settings import runtime_settings` to any `src/ui/` module** (run this mutation; a test that passes both ways is vacuous)
**Verify (6b)**: `pytest -m unit tests -q` → all pass (the 21 repointed files and `tests/test_timezone_settings.py` included)
**Verify (6b)**: `mypy src/` → exit 0
**Verify (6b)**: `docker compose up -d --build` → healthy; `curl -sf -o /dev/null -w '%{http_code}' https://localhost/app/` → `200`, and `https://localhost/app/chat` → `200` (Chat imports the timezone helpers — it is the page that proves this landed)

---

**6c. Source the MCP env table from the settings API.**

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

**Verify (6c)**: `grep -rn "settings\.GITHUB_MCP\|settings\.NEO4J_URI" src/ui/` → no matches
**Verify (6c)**: `grep -n "GITHUB_MCP" docker-compose.yml` → no `ui` service block matches (the `ui` service does not exist until Step 8; the API keeps them)
**Verify (6c)**: `pytest -m unit tests -q` → all pass
**Verify**: `mypy src/` → exit 0
**Verify**: `docker compose up -d --build` → healthy; `curl -sf -o /dev/null -w '%{http_code}' https://localhost/app/` → `200`

> ### 🚦 MANUAL GATE 6 — operator check
>
> **Report to the operator:** the verify outputs and the two new test names.
>
> **6a — the import-time constants:**
>
> 1. The new test exists and asserts through the **consuming function**, not
>    through the cache.
> 2. **The mutation was run.** Reverting one constant to module level must make
>    the test fail. A test that passes both ways is vacuous.
> 3. All 12 sites are converted; the grep finds none remaining.
> 4. No `TIMEOUT_SECONDS` is left referenced by a name that no longer exists.
>
> **6b — the isolation fix. This is the most important part of this gate, because
> it is the only thing standing between the UI container and a boot-time crash at
> Step 8.**
>
> 5. **`src/domain/settings.py` exists, `UISettings` is there, and it carries no
>    credential field.** Read it. Confirm there is no `DATABASE_URL`, no
>    `NEO4J_*`, no `ELASTICSEARCH_*`, no `OPENAI_API_KEY`, no `GITHUB_MCP_TOKEN`,
>    no `RABBITMQ_URL`, no `CONNECTOR_ENCRYPTION_KEY`. Then confirm
>    `ApiSettings(UISettings)` in `src/app/settings.py` adds them back.
> 6. **The UI imports none of the three old modules.** Run
>    `grep -rn "from app\.runtime_settings import\|from app\.common\.timezone import\|from app\.settings import" src/ui/`
>    → no matches. This is the check whose absence let the defect through in the
>    first place: Step 6a's grep looks only at module-level *assignments*, so all
>    21 files passed it while still importing `sqlalchemy` transitively.
> 7. **`tests/test_ui_isolation.py` exists, passes, and is non-vacuous.** Run the
>    mutation: re-add `from app.runtime_settings import runtime_settings` to any
>    `src/ui/` module and confirm the test **fails**. Confirm it blocks the real
>    package names (`sqlalchemy`, `asyncpg`, `neo4j`, `elasticsearch`, `openai`,
>    `aio_pika`) — a test that blocks nothing passes trivially.
> 8. **`ui.runtime_settings` reuses the existing snapshot client.** Confirm it
>    calls `common.runtime_settings.client.fetch_runtime_snapshot` rather than a
>    second hand-rolled HTTP path, and that it does **not** import
>    `common.messaging.settings_events` (which needs `aio_pika`). Both are read
>    from the file.
> 9. **`domain.timezone` does not import `ui.*`.** It must not — the API cannot
>    depend on the UI. Confirm the timezone-source shape chosen (shared cache vs
>    injected) and that `domain/` still imports nothing from `app.*` or `ui.*`.
> 10. **The server runs and Chat renders.** `https://localhost/app/chat` → `200`
>     in the browser, with timestamps formatted correctly. Chat imports the
>     timezone helpers, so it is the page that proves the move worked.
>
> **6c — the secret and the topology leak:**
>
> 11. The UI **code** reads none of `GITHUB_MCP_ENABLED`, `GITHUB_MCP_SERVER_URL`,
>     `GITHUB_MCP_TOKEN`, or `NEO4J_URI`. Note the wording: the UI is still part
>     of the one process here, so this is a **code-level grep, not a
>     process-level check**. The process-level check
>     (`docker compose exec ui env`) only becomes possible at Step 8, and is run
>     there.
> 12. The Connectors page's env table still renders all three rows with correct
>     Set/Not-set indicators. **This is a browser check** — the page must look
>     unchanged for the user while the secret stopped being read directly.
> 13. The Neo4j error message no longer names `settings.NEO4J_URI`.
> 14. The settings API's masking is what supplies the display value — confirm
>     nothing in the UI computes a mask of its own for the token.
>
> Wait for `PASS` before starting Step 7.

---

### Step 7: Stop the UI importing the API's services

**This step merges the three remaining in-process bypasses into one, because they
are one problem solved three times.** The UI reaches into the API's Python for
the collaboration network, the ego star, and the spotlight search
(`src/ui/pages/graph/callbacks/spotlight.py:118`, plus the two `filter.py` call
sites below). Each must become an HTTP call, and each needs the same evidence: a
before/after comparison proving the HTTP path returns exactly what the in-process
call returned. One baseline script covers all three.

**The real work is parameter translation.** The UI builds a
`CollaborationNetworkConfig` via `from_query_values` and passes a *model*; the org
endpoint takes **30+ flat query params** (`api/graph/v1/router.py:200-227`) and
the ego endpoint a slightly smaller set (`:341-372`), each independently calling
`from_query_values({...})` on them (`:250-262`, `:397-423`). Two parsers, two
field lists, no link between them.

**Why a baseline script is not enough on its own.** The swaps (7d) edit only the
call sites; the in-process functions and the endpoints are both untouched. A
script that built its *own* query string would therefore contain a **third**,
independent translation — the before/after re-run would compare the script
against itself, exercise none of the code the swaps changed, and pass while a
lossy mapping in the UI's call site shipped. So 7a extracts **one** serializer,
and 7c and 7d both call it. The re-run then genuinely exercises the swapped
translation, which is what makes Gate 7 mean anything.

**Order: 7a → 7b → 7c → 7d → 7e → 7f.** The baseline is captured before any call
site is edited. A baseline captured after a swap proves nothing.

**7a. Extract the shared serializer, and the round-trip test that guards it.**

Create `src/ui/collaboration_params.py`. It lives **outside** `pages/` because
both `pages/collaboration_network/` and `pages/collaboration_network_ego/` import
it, and a module inside one page package cannot be imported by another (its
`__init__` runs `.layout`/`.callbacks` → circular). Import it absolutely:
`from ui.collaboration_params import config_to_query_params`.

```python
"""Config → query-param translation for the collaboration endpoints.

The single source of truth for how a ``CollaborationNetworkConfig`` becomes the
flat query params ``/api/v1/graph/collaboration-network[/ego]`` accept. Both UI
call sites and the Step 7 baseline script use it; the endpoints parse those
params back with ``CollaborationNetworkConfig.from_query_values``.
"""
from domain.collaboration.config import LAYER_ORDER, CollaborationNetworkConfig

# The four params the ego endpoint does not accept (router.py:341-372). The org
# endpoint takes all of them; the ego endpoint omits these because a star skips
# the Louvain pipeline entirely. Verified against the ego signature: person,
# layers, max_collaborators, lookback_days, min_pair_score, exclude_bots,
# exclude_suffixes, w_* — and nothing else.
_ORG_ONLY = (
    "top_n_edges_per_node",
    "community_gap_x",
    "community_gap_y",
    "ensure_min_connection",
)


def config_to_query_params(config: CollaborationNetworkConfig) -> dict[str, str]:
    """Serialize ``config`` to the org endpoint's query params, all explicit.

    Every field is emitted, so the endpoint's own ``Query(default=…)`` values
    never participate and cannot drift from the model's defaults.
    """
    params = {
        "layers": ",".join(config.enabled_layers),
        "lookback_days": str(config.lookback_days),
        "min_pair_score": str(config.min_pair_score),
        "top_n_edges_per_node": str(config.top_n_edges_per_node),
        "community_gap_x": str(config.community_gap_x),
        "community_gap_y": str(config.community_gap_y),
        "ensure_min_connection": str(config.ensure_min_connection).lower(),
        "exclude_bots": str(config.exclude_bots).lower(),
        "exclude_suffixes": ",".join(config.excluded_file_suffixes),
    }
    for layer in LAYER_ORDER:
        params[f"w_{layer}"] = str(config.weights[layer])
    return params


def ego_query_params(
    config: CollaborationNetworkConfig, focus_id: str, max_collaborators: int
) -> dict[str, str]:
    """The ego endpoint's params: the shared subset, plus the focus identity.

    The focus param is named ``person`` on this endpoint, not ``focus_id``
    (``router.py:342``) — that asymmetry is exactly the kind of drift this
    module exists to make impossible to get wrong twice.
    """
    params = {
        key: value
        for key, value in config_to_query_params(config).items()
        if key not in _ORG_ONLY
    }
    params["person"] = focus_id
    params["max_collaborators"] = str(max_collaborators)
    return params
```

**The param names are not free-hand.** They are exactly the keys the org endpoint
passes to `from_query_values` (`router.py:250-262`) and the names the UI already
reads out of the URL today (`pages/collaboration_network/callbacks/filter.py:71-85`).
The serializer is the inverse of that existing block; if the two disagree, the
org round-trip test below fails.

`_ORG_ONLY` is faithful to the page, not a shortcut: the ego page's own
`_ego_query_dict` (`pages/collaboration_network_ego/callbacks/filter.py:44-56`)
already reads only layers, lookback_days, min_pair_score, exclude_bots,
exclude_suffixes and the weights out of the URL. So the ego config the page
builds already carries defaults for those four fields, and dropping them from the
wire loses nothing.

**Add the round-trip test** — `tests/test_collab_query_param_roundtrip.py`, with
`pytestmark = pytest.mark.unit` at module level:

```python
@pytest.mark.parametrize("config", SEEDED_CONFIGS)
def test_config_to_query_params_round_trips(config):
    """from_query_values(config_to_query_params(c)) == c over a seeded matrix."""
    round_tripped = CollaborationNetworkConfig.from_query_values(
        config_to_query_params(config)
    )
    assert round_tripped == config
```

The test defines its own `SEEDED_CONFIGS` — a matrix that varies **every** field
away from its default, so the round-trip covers the whole surface. Do not import
the script's copy: `tests/` must not import from `scripts/`, and the two lists
serve different purposes (the script's is sized to keep the live run cheap, the
test's to be exhaustive). **This test is the primary guard; 7c/7e is the
end-to-end confirmation.** The ego path has no round-trip equivalent — the ego
endpoint omits `_ORG_ONLY` fields, so a non-default value there cannot survive
the trip by construction; only send **default-valued** ego configs in 7c, and
rely on the live comparison for ego.

**One known lossy edge, and it is not the serializer's fault.**
`from_query_values` reads `excluded_file_suffixes` as
`excluded_suffixes or list(DEFAULT_EXCLUDED_FILE_SUFFIXES)` (`config.py:235`), so
an **empty** suffix list cannot survive the round-trip — it returns the defaults.
Keep a non-empty `excluded_file_suffixes` in the seeded matrix (or assert the
documented fallback for that one case). Do not "fix" this in the serializer;
every other field round-trips exactly.

**Verify (7a)**: `pytest tests/test_collab_query_param_roundtrip.py -q` → all pass
**Verify (7a)**: mutation check — delete the `w_confluence_mentions` line from
`config_to_query_params` and confirm the round-trip test **fails**. A test that
passes both ways is vacuous; do not skip this.

**7b. Add the optional `ids` param to `GET /api/v1/search`.**

**This part exists because the obvious swap is wrong.** Verified live:

| Call | Result |
|---|---|
| `GET /api/v1/search?q=review` | `total = 22`, `page_size = 20`, 20 returned |
| Canvas node count | 223 |

`search_in_graph`'s docstring (`api/search/v1/service.py:200-203`) says it
"eliminates the top-N clipping problem": it sets `body["size"] = len(graph_wba_ids)`
(`:223`) so every loaded node is a candidate. A literal swap to the unscoped
endpoint would silently stop highlighting nodes.

Add `ids: str | None = Query(default=None)` to the `GET /api/v1/search` route
(`api/search/v1/router.py:17`) — **comma-separated**, matching the existing
`layers` / `exclude_suffixes` convention on the graph router rather than
repeat-key style. When present, constrain the ES query to documents whose
`wba_id` is in the list, and set `size = len(ids)` — mirroring `search_in_graph`'s
scoping **exactly**. When absent, behaviour is unchanged.

Keep `search_in_graph` or express it in terms of the new param — but the
endpoint's scoped path must reproduce its result set. 7c/7e is what proves it
does; do not assume it.

**Verify (7b)**: `curl -s 'https://localhost/api/v1/search?q=review' | python -c "import json,sys; d=json.load(sys.stdin); print(d['total'], len(d['results']))"` → `22 20` (unscoped is unchanged)

**7c. Write and run the temporary baseline script.**

Create `scripts/capture_ui_baseline.py` (temporary; deleted in 7f). Run it
with the venv active and `PYTHONPATH=src`. `get_collaboration_network`,
`get_ego_network` and `search_in_graph` are all **synchronous**
(`api/graph/v1/service.py:347,442`, `api/search/v1/service.py:194`) and acquire
their clients lazily, so the script needs no explicit init and no asyncio wrapper
— only `.env` for `NEO4J_*` and the search index.

```python
"""Temporary before/after fidelity check for the Step 7 swaps."""

from __future__ import annotations

import json
import os
import sys

import requests

from app.api.graph.v1.service import get_collaboration_network, get_ego_network
from app.api.search.v1.model import SearchRequest
from app.api.search.v1.service import search_in_graph
from domain.collaboration.config import LAYER_ORDER, CollaborationNetworkConfig
from ui.collaboration_params import config_to_query_params, ego_query_params

# The Compose stack publishes no host port for the app — the API is reached
# through nginx at https://localhost. Override for the local-uvicorn workflow.
API = os.environ.get("API_BASE_URL", "https://localhost")
OUT = "scripts/ui_baseline.json"

_WEIGHTS_ALL_ZERO = {layer: 0.0 for layer in LAYER_ORDER}

# Fixed, seeded, and identical across the two runs. Not random, and not the
# current URL's values — URL state varies between runs.
SEEDED_CONFIGS: list[CollaborationNetworkConfig] = [
    CollaborationNetworkConfig(),                                        # all defaults
    CollaborationNetworkConfig(lookback_days=30, top_n_edges_per_node=5),
    CollaborationNetworkConfig(enabled_layers=["pr_reviews"], min_pair_score=0.0),
    CollaborationNetworkConfig(
        exclude_bots=False,
        excluded_file_suffixes=[".json", ".md", ".lock", ".yaml"],
    ),
    CollaborationNetworkConfig(weights={**_WEIGHTS_ALL_ZERO, "pr_reviews": 7.5}),
    CollaborationNetworkConfig(community_gap_x=200.0, community_gap_y=10000.0),
    CollaborationNetworkConfig(ensure_min_connection=False, top_n_edges_per_node=200),
    # The EMPTY-RESULT path. Every config above returns data, so without this
    # one the comparison never exercises the branch the swaps can silently
    # break (see 7d-i): the API answers 404 here, the in-process call raises
    # CollaborationDataUnavailable, and both must keep producing the same
    # *kind* of outcome. lookback_days=1 is the cheapest way to guarantee no
    # records on a stack whose data is older than a day.
    CollaborationNetworkConfig(lookback_days=1),
]

# The INVALID-CONFIG path: the API answers 400, the in-process call raises
# ValidationError/ValueError, and the UI renders describe_config_error(). A
# naive swap turns this into "An unexpected error occurred.". Sent as raw query
# values, not through the serializer, because from_query_values would reject it
# before it left the client — and the point is to reach the server with it.
INVALID_ORG_PARAMS = {"lookback_days": "0", "min_pair_score": "-1"}

# Ego boundaries only. max_collaborators is ge=1/le=500 in the endpoint
# (router.py:345-349) while the UI has its own cap_options_for — two bound
# definitions that can disagree, so probe both ends. Default-valued configs
# only: the ego endpoint does not accept the org-only fields (see 7a).
EGO_MAX_COLLABORATORS = [1, 25, 500]

# Spotlight queries. At least one must match more than 20 canvas nodes: that is
# the case the in-process call handled and a naive unscoped swap would silently
# drop. The 7c verify block asserts the >20 case actually occurs — without it the
# comparison cannot distinguish scoped from unscoped, and the leg proves nothing.
SPOTLIGHT_QUERIES = ["review", "issue", "urgent", "a"]


def canonical(payload: dict) -> dict:
    """Order-independent summary: sorted node ids, sorted (src, tgt, weight) edges."""
    elements = payload["elements"]
    nodes = sorted(e["data"]["id"] for e in elements if "source" not in e["data"])
    edges = sorted(
        (
            e["data"]["source"],
            e["data"]["target"],
            round(float(e["data"].get("weight", 0.0)), 6),
        )
        for e in elements
        if "source" in e["data"]
    )
    stats = {k: v for k, v in payload.items() if k not in ("elements", "config")}
    return {
        "element_count": len(elements),
        "node_ids": nodes,
        "edges": edges,
        "stats": stats,
    }


def spotlight_ids(query: str, graph_wba_ids: list[str]) -> dict:
    """Matched wba_id set for one query, in-process vs HTTP."""
    in_proc = search_in_graph(SearchRequest(q=query), graph_wba_ids)
    http = requests.get(
        f"{API}/api/v1/search",
        params={"q": query, "ids": ",".join(graph_wba_ids)},
        timeout=300,
    ).json()
    return {
        "in_process": sorted(record.wba_id for record in in_proc.results),
        "http": sorted(record["wba_id"] for record in http["results"]),
    }


def in_process_outcome(fn, *args, **kwargs) -> dict:
    """Call an in-process function, summarising a raised exception as data.

    The empty and invalid legs raise rather than return, so capturing the
    exception *type* is what makes them comparable at all. Recording only the
    type — never the traceback or message — keeps the summary stable across
    runs, which the before/after diff requires.
    """
    try:
        return {"kind": "data", "payload": canonical(fn(*args, **kwargs).model_dump())}
    except Exception as exc:  # pylint: disable=broad-except
        return {"kind": "error", "exc_type": type(exc).__name__}


def http_outcome(url: str, params: dict) -> dict:
    """GET *url*, summarising the response as data or an error kind."""
    response = requests.get(url, params=params, timeout=300)
    if response.ok:
        return {"kind": "data", "payload": canonical(response.json())}
    return {"kind": "error", "status": response.status_code}


def main() -> int:
    results: dict[str, dict] = {}

    for index, config in enumerate(SEEDED_CONFIGS):
        params = config_to_query_params(config)
        results[f"org_{index}"] = {
            "in_process": in_process_outcome(get_collaboration_network, config=config),
            "http": http_outcome(f"{API}/api/v1/graph/collaboration-network", params),
        }

    # The invalid-config leg. Raw params, not the serializer's output (see
    # INVALID_ORG_PARAMS). The in-process side is fed the same values through
    # from_query_values so both legs see identical input.
    results["org_invalid"] = {
        "in_process": in_process_outcome(
            get_collaboration_network,
            config=CollaborationNetworkConfig.from_query_values(INVALID_ORG_PARAMS),
        ),
        "http": http_outcome(f"{API}/api/v1/graph/collaboration-network", INVALID_ORG_PARAMS),
    }

    # A real Person wba_id, and the graph's node set, both derived from the
    # default org run so every run of this script picks the same ones. Hardcoded
    # ids rot; and the spotlight canvas *is* this node set, which is what makes
    # the spotlight leg comparable without a browser.
    graph_wba_ids = results["org_0"]["in_process"]["payload"]["node_ids"]
    focus_id = graph_wba_ids[0]

    for cap in EGO_MAX_COLLABORATORS:
        config = CollaborationNetworkConfig()
        results[f"ego_{cap}"] = {
            "in_process": in_process_outcome(
                get_ego_network, focus_id, config=config, max_collaborators=cap
            ),
            "http": http_outcome(
                f"{API}/api/v1/graph/collaboration-network/ego",
                ego_query_params(config, focus_id, cap),
            ),
        }

    # The ego empty path: a well-formed Person id that has no collaborators.
    # This is the case whose banner the ego callback's own comment says was
    # once misleading — 7d-i is what keeps it correct after the swap.
    for name, person in [
        ("ego_unknown_person", "person:does-not-exist-00000000"),
    ]:
        config = CollaborationNetworkConfig()
        results[name] = {
            "in_process": in_process_outcome(get_ego_network, person, config=config),
            "http": http_outcome(
                f"{API}/api/v1/graph/collaboration-network/ego",
                ego_query_params(config, person, 25),
            ),
        }

    for query in SPOTLIGHT_QUERIES:
        results[f"spotlight_{query}"] = spotlight_ids(query, graph_wba_ids)

    with open(OUT, "w") as handle:
        json.dump(results, handle, indent=2, sort_keys=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

**The failure legs are the point of this revision.** Before the swap,
`org_7` (empty) and `ego_unknown_person` must read
`{"kind": "error", "exc_type": "CollaborationDataUnavailable"}` in-process and
`{"kind": "error", "status": 404}` over HTTP; `org_invalid` must read
`ValidationError`/`ValueError` in-process and `400` over HTTP. **They are not
identical in form, and must not be compared as if they were** — the two legs
legitimately express the same outcome differently (a raised type vs a status
code).

**What these legs do and do not prove.** They establish the *contract 7d-i
targets*: that the endpoint really does answer 404 where the in-process function
raises `CollaborationDataUnavailable`, and 400 where it raises a validation error.
Without that, the mapping in 7d-i would be guessing at status codes.

They do **not** test the mapping itself. This script calls the in-process
functions directly for its `in_process` leg — it never goes through
`api_client.get_json` — so it cannot observe whether the UI's new status→exception
translation works, and its `before == after` diff is unchanged by 7d-i by
construction. **The guard for the mapping is the unit test in 7d-iii below**,
which stubs the transport and asserts the exception type directly.

**Sanity-check the numbers before trusting the file.** On the live stack
`org_0.in_process.payload` must show `element_count` **5041**,
`stats["num_people"]` **223**, `stats["num_pairs"]` **4818**. `element_count` is
nodes **plus** edges — it is *not* `num_people`. If the counts are far off, the
script is wrong and the comparison would prove nothing.

**Sanity-check the failure legs too, or 7d-i's whole reason for existing goes
unchecked.** `org_7`, `org_invalid` and `ego_unknown_person` must each read
`kind == "error"` on **both** sides — with `in_process.exc_type` of
`CollaborationDataUnavailable`, `ValidationError` (or `ValueError`), and
`CollaborationDataUnavailable` respectively. If any of them reports
`kind == "data"`, the leg is not exercising the failure path you think it is,
and the swap's most dangerous change would ship unverified.

Run it **before** any swap and keep the output:

```bash
# `requests` verifies against certifi, not the system store, so point it at the
# mkcert CA — same reason tests/conftest.py sets SSL_CERT_FILE for `server` tests.
export SSL_CERT_FILE="$(mkcert -CAROOT)/rootCA.pem"
PYTHONPATH=src python scripts/capture_ui_baseline.py
cp scripts/ui_baseline.json scripts/ui_baseline.before.json
```

The stack must be **up and built from the current working tree**
(`docker compose up -d --build`). By this point Step 5 has changed the module
layout, so a pre-plan image is no longer what the in-process leg runs against.
Re-run `docker compose ps` and confirm `neo4j` is healthy first, or the sanity
numbers below will be off for a reason unrelated to the swap.

**Verify (7c)**: `PYTHONPATH=src python scripts/capture_ui_baseline.py` → exit 0
**Verify (7c)**: `python -c "import json;d=json.load(open('scripts/ui_baseline.json'));p=d['org_0']['in_process']['payload'];print(p['element_count'], p['stats']['num_people'])"` → `5041 223`
**Verify (7c)**: `python -c "import json;d=json.load(open('scripts/ui_baseline.json'));m=max(len(v['in_process']) for k,v in d.items() if k.startswith('spotlight_'));assert m>20, f'no spotlight query matched >20 canvas nodes (max {m})'"` → exit 0. Without a >20-match query the spotlight leg cannot distinguish scoped from unscoped, so it proves nothing — pick different queries rather than proceeding.
**Verify (7c)**: the three failure legs actually exercised the failure path:
`python -c "import json;d=json.load(open('scripts/ui_baseline.json'));legs={'org_7':'CollaborationDataUnavailable','ego_unknown_person':'CollaborationDataUnavailable','org_invalid':None};[__import__('sys').exit(f'{k}: in_process={d[k][\"in_process\"]}') for k in legs if d[k]['in_process']['kind']!='error']"` → exit 0, and each `http` side reads `{'kind': 'error', 'status': 404}` (org_7, ego_unknown_person) or `400` (org_invalid).
**Verify (7c)**: the **data** legs agree across the two implementations, and the **error** legs express the same outcome in their own form:
```bash
python -c "
import json
d = json.load(open('scripts/ui_baseline.json'))
# Data legs: the two implementations must agree exactly.
for k, v in d.items():
    if k.startswith('spotlight_'):
        continue
    if v['in_process']['kind'] == 'data':
        assert v['http']['kind'] == 'data', f'{k}: HTTP errored where in-process returned data'
        assert v['in_process']['payload'] == v['http']['payload'], f'{k}: payloads disagree BEFORE the swap'
# Error legs: same outcome, different form (raised type vs status code).
EXPECTED = {'org_7': 404, 'ego_unknown_person': 404, 'org_invalid': 400}
for k, status in EXPECTED.items():
    assert d[k]['in_process']['kind'] == 'error', f'{k}: in-process did not error — the leg is vacuous'
    assert d[k]['http'] == {'kind': 'error', 'status': status}, f'{k}: expected HTTP {status}, got {d[k][\"http\"]}'
print('outcomes agree')
"
```
→ `outcomes agree`. This must **already hold before any swap**: it proves the endpoints and the in-process functions agree on both paths, so a later difference is attributable to the swap rather than pre-existing.

**7d. Swap the three call sites.**

**The success path is mechanical; the failure path is not, and it is the part
that breaks silently if you treat this as a rename.** Read 7d-i before editing.

**7d-i. The two collab call sites must map HTTP status back to the exceptions
they already catch.**

Today both services signal "the query ran cleanly but there is nothing to draw"
by raising `CollaborationDataUnavailable`
(`api/graph/v1/service.py:389` and `:484`), and both callbacks catch it **by
type** to render a specific banner:

```
src/ui/pages/collaboration_network/callbacks/filter.py:123
    except CollaborationDataUnavailable as exc:
        # Query ran cleanly but there is nothing to draw. Distinct from the
        # ValueError branch below, which is a genuine settings problem.
        return [], _COLLABORATION_LAYOUT, [_data_unavailable_banner(config)], ...

src/ui/pages/collaboration_network_ego/callbacks/filter.py:221
    except CollaborationDataUnavailable as exc:
        # A clean query with an empty result: the person exists but has no
        # collaborators in this window. This is NOT a settings problem...
```

A raw `requests.get(...)` **never** raises that. It returns a `Response`. The API
maps the exception to **404** (`router.py:300-308`, `:442-450`), so a naive swap
makes those two handlers **dead code**; the next line (`data.elements` on a dict)
then raises `AttributeError` and falls through to the trailing
`except Exception`, which renders `"An unexpected error occurred."`

**The user-visible regression: "No collaborations in this window — try widening
the lookback" becomes "An unexpected error occurred."** The page looks broken
rather than empty — precisely the misleading behaviour the ego branch's comment
records having already fixed once. The same class of loss applies to the **400**
path (`router.py:314`), where a config error currently reaches
`describe_config_error(...)` and would instead hit the generic handler.

So the swap is **not** `.json()` replacing attribute access on the happy path
only. Both collab sites must:

1. Read the timeout per call — `runtime_settings.get_int("HTTP_REQUEST_TIMEOUT")`,
   never a module-level constant (Step 6's bug class).
2. Inspect `response.status_code` **before** parsing, and translate:
   - **404 with `detail.error == "No collaboration data"`** →
     `raise CollaborationDataUnavailable(<the API's `detail.message`>)`. Discriminate
     on the body, not the bare status: a 404 from a *wrong URL* must not be
     reported to the user as "you have no collaborations".
   - **400** → `raise ValueError(<the API's `detail.message`>)`, so the existing
     `except ValueError` branch still renders `describe_config_error(...)`.
   - **any other non-2xx** → `raise_for_status()` into the generic handler.
3. Leave the existing `except` blocks exactly as they are. They are correct; the
   swap's job is to keep feeding them the exception types they expect.

`CollaborationDataUnavailable` already lives in the **pure**
`src/domain/collaboration/errors.py` and is already imported by both files
(`filter.py:11`, `:12`), so this mapping needs no new UI→API import.

**Put this in `src/ui/api_client.py`, created here — minimally — rather than in a
throwaway local helper.** Step 10 grows this same module into the full client
(other verbs, injectable transport, one exception type). Creating it now resolves
the ordering tension between Decision 11 and this step: an executor facing both
"put it in `api_client.py`" and "`api_client.py` is Step 10" would otherwise
guess. The Step 7 version needs only `get_json(url, params, timeout) -> dict` plus
the status mapping above. Step 10 extends the surface; it does not replace it.

**7d-ii. The three swaps.**

| File | Now | Becomes |
|---|---|---|
| `src/ui/pages/collaboration_network/callbacks/filter.py:88` | `data = get_collaboration_network(config=config)` | `data = api_client.get_json(f"{API_BASE}/api/v1/graph/collaboration-network", params=config_to_query_params(config))` |
| `src/ui/pages/collaboration_network_ego/callbacks/filter.py:201` | `data = get_ego_network(focus_id, config=config, max_collaborators=max_collaborators)` | `data = api_client.get_json(f"{API_BASE}/api/v1/graph/collaboration-network/ego", params=ego_query_params(config, focus_id, max_collaborators))` |
| `src/ui/pages/graph/callbacks/spotlight.py:118` | `search_in_graph(SearchRequest(q=q), graph_wba_ids)` | `data = api_client.get_json(f"{API_BASE}/api/v1/search", params={"q": q, "ids": ",".join(graph_wba_ids)})` |

**Do not inline the param dicts at the call sites.** A hand-built dict is a
second translation and reintroduces exactly the drift 7a exists to prevent.

`get_json` returns the parsed body as a `dict`, so `.json()` is absorbed inside
the client and each call site destructures it. The collab bodies are the same
`CollaborationNetworkResponse` / `EgoNetworkResponse` shape, so every consumer of
`data["elements"]` / `data["num_people"]` / `data["config"]` is otherwise
unchanged. The spotlight body is the same `SearchResponse` shape, so
`spotlight.py:122-131`'s client-side intersection and its
`"{match_count} of {node_count} nodes match"` text are unchanged.

**The spotlight site has no typed-exception contract to preserve** — it already
wraps its call in a bare `except Exception` (`spotlight.py:119-121`) and raises
`PreventUpdate`, so a failed search degrades to "no highlight" either way. Only
the two collab sites need the mapping in 7d-i.

**7d-iii. Guard the mapping with a unit test.**

The baseline script cannot cover 7d-i (see 7c), so this test is the **only**
automated guard on the status→exception translation. Add
`tests/test_ui_api_client_status_mapping.py` with
`pytestmark = pytest.mark.unit` at module level. It stubs the transport — using
the injectable one `api_client` exposes — so it needs no server and no Neo4j:

```python
@pytest.mark.parametrize(
    ("status", "body", "expected"),
    [
        (404, {"detail": {"error": "No collaboration data", "message": "no data"}},
         CollaborationDataUnavailable),
        (400, {"detail": {"error": "Invalid collaboration configuration", "message": "bad"}},
         ValueError),
        (500, {"detail": {"error": "Internal server error"}}, None),  # generic path
    ],
)
def test_get_json_maps_status_to_exception(status, body, expected):
    """A non-2xx response raises the type the collab callbacks catch.

    Regression guard: a raw ``requests.get`` returns a Response, so the
    ``except CollaborationDataUnavailable`` branch went dead and the page
    rendered "An unexpected error occurred." instead of the real banner.
    """
```

Three things this test must get right, or it is vacuous:

1. **It must assert the exception *type*, not merely that something raised.** A
   bare `pytest.raises(Exception)` passes for `AttributeError` — which is
   exactly the bug.
2. **Include a 404 that is *not* the collaboration error** (a wrong URL, or a
   body whose `detail.error` differs) and assert it does **not** become
   `CollaborationDataUnavailable`. This is the discrimination 7d-i requires; a
   mapping keyed on the bare status passes the first case and fails the user.
3. **Mutation-check it**: delete the 404 branch from `get_json` and confirm the
   first case fails. Same discipline as 7a's mutation.

**Verify (7d-iii)**: `pytest -m unit tests/test_ui_api_client_status_mapping.py -q` → all pass
**Verify (7d-iii)**: mutation — remove the 404→`CollaborationDataUnavailable`
branch; the first parametrised case must **fail**.

**7e. Re-run the baseline script and compare.**

```bash
PYTHONPATH=src python scripts/capture_ui_baseline.py
diff <(python -m json.tool scripts/ui_baseline.before.json) \
     <(python -m json.tool scripts/ui_baseline.json)
```

Two conditions, both **exact**, both STOP conditions:

1. `before == after` — the swaps changed no output, for all three bypasses.
2. For every case, in *both* files, the two legs express the **same outcome**:
   where `in_process.kind == "data"`, the payloads are byte-identical to the
   `http` payload; where `in_process.kind == "error"`, the `http` side carries
   the matching status (`404` for `CollaborationDataUnavailable`, `400` for a
   validation error). The two legs are **not** compared as whole dicts — a
   raised exception type and an HTTP status code are different vocabulary for
   the same fact, and the 7c verify block above is the command that checks this
   correctly.

A mismatch means a translation is lossy. The fix is to correct
`collaboration_params.py` (or the `ids` handling, for spotlight), **never** to
relax the comparison. Watch ego's bounds specifically: `max_collaborators` is
`ge=1 / le=500` in the endpoint (`router.py:345-349`) while the UI has its own
`cap_options_for` — the boundary cases (`1`, `500`) are what catch a disagreement.

**This comparison constrains 7d-i; it does not verify it.** The script's
`in_process` leg calls the services directly and never passes through
`api_client.get_json`, so the `diff` above is identical whether or not 7d-i's
mapping was implemented — or implemented wrongly. `before == after` holding is
necessary but nowhere near sufficient here. **7d-iii's unit test is the
verification for the mapping; run it before accepting this gate.**

**7f. Delete the script, keep the serializer.**
`git rm scripts/capture_ui_baseline.py scripts/ui_baseline.json
scripts/ui_baseline.before.json`. Keep `src/ui/collaboration_params.py`,
`tests/test_collab_query_param_roundtrip.py` and
`tests/test_ui_api_client_status_mapping.py` — they are permanent, and they are
what keeps these regressions fixed after the plan is done.

Then delete the now-unused imports: `get_collaboration_network`,
`get_ego_network`, `search_in_graph` and `SearchRequest` are no longer called
from `src/ui/`, so those four go. **`CollaborationDataUnavailable` stays** — it
is not an API-service import (it lives in the pure
`src/domain/collaboration/errors.py`) and 7d-i's status mapping raises it. Every
one of these four must be gone:

```
src/ui/pages/collaboration_network/callbacks/filter.py:12   from app.api.graph.v1.service import get_collaboration_network
src/ui/pages/collaboration_network_ego/callbacks/filter.py:13  from app.api.graph.v1.service import get_ego_network
src/ui/pages/graph/callbacks/spotlight.py:13               from app.api.search.v1.model import SearchRequest
src/ui/pages/graph/callbacks/spotlight.py:14               from app.api.search.v1.service import search_in_graph
```

**Verify (7d–7f)**: `diff` from 7e prints nothing
**Verify**: `grep -rn "from app\.api\.graph\.v1\.service\|from app\.api\.search\.v1\.service\|from app\.api\.search\.v1\.model" src/ui/` → no matches
**Verify**: `grep -rn "CollaborationDataUnavailable" src/ui/` → **3 matches or more** (both `filter.py` imports plus the `raise` sites 7d-i adds) — if it is absent, the mapping was skipped and the banners are broken
**Verify**: `pytest tests/test_collab_query_param_roundtrip.py tests/test_ui_api_client_status_mapping.py -q` → all pass
**Verify**: `pytest -m unit tests -q` → all pass
**Verify**: `mypy src/` → exit 0
**Verify**: `docker compose up -d --build` → healthy; `curl -sf -o /dev/null -w '%{http_code}' https://localhost/app/` → `200`
**Verify**: `git status --short scripts/` → the capture script and both JSON files are gone

> ### 🚦 MANUAL GATE 7 — operator check
>
> **Report to the operator:** `scripts/ui_baseline.before.json`,
> `scripts/ui_baseline.json`, the `diff` output between them, and the verify
> outputs.
>
> **Operator verifies:**
> 1. **The baseline was captured before the swaps.** Confirm the script ran
>    against the pre-swap tree — check the git state at capture time, not the
>    executor's word.
> 2. **The script calls `collaboration_params.py`, not a private param dict.**
>    Read the script's imports. If it builds its own query string, the re-run
>    compares two copies of the script and this gate is vacuous — reject it
>    regardless of how the summaries look.
> 3. **The two legs agreed in the *before* file too**, not just after — on the
>    data legs as identical payloads, and on the error legs as matching
>    outcome-and-status (see the 7c verify block; do **not** compare whole
>    dicts, since a raised exception type and a status code are different
>    vocabulary). If they did not agree before, an endpoint and its in-process
>    function already disagreed, and the before/after comparison is meaningless.
> 4. The two summaries are **identical**, not merely "close" — same node ids, same
>    edge set, same stats, same element count, same matched-ID sets. The sanity
>    numbers are `5041` elements / `223` people / `4818` pairs for `org_0`.
> 5. If they differ, the number of differing elements is reported. **Do not accept
>    "the difference is small"** — a lossy param translation is exactly the bug
>    this gate exists to catch.
> 6. **The failure legs were actually exercised.** `org_7`,
>    `ego_unknown_person` and `org_invalid` must each read `kind == "error"` on
>    both sides. A leg that quietly returned `kind == "data"` is not testing the
>    branch — and that branch is where the swap's most damaging regression lives
>    (see 7d-i).
> 7. **The status→exception mapping is verified by its own test, not by this
>    gate.** Confirm the executor ran
>    `pytest -m unit tests/test_ui_api_client_status_mapping.py -q` **and** the
>    7d-iii mutation: removing the 404→`CollaborationDataUnavailable` branch must
>    make it fail. Reason: this script's `in_process` leg bypasses `api_client`
>    entirely, so the `before == after` diff is **identical whether or not 7d-i
>    was implemented**. Do not accept the diff as evidence for the mapping.
> 8. **The empty-result banner still renders in the browser.** Load the org
>    Collaboration page with a 1-day lookback (or the epoch window) and the ego
>    page for a person with no collaborators. Each must show its *specific*
>    "no data" banner — not "An unexpected error occurred." This is the
>    user-visible symptom 7d-i exists to prevent, and it is the one check that
>    observes the whole path end to end.
> 9. **The spotlight leg is not vacuous.** At least one query matched **more than
>    20** canvas nodes (the 7c verify asserts this). A query set that only ever
>    matches a handful cannot tell scoped from unscoped, and would pass even if
>    `ids` were ignored entirely.
> 10. **The `ids` param is genuinely scoped**, not merely accepted and ignored.
>     Ask: *if `ids` were dropped from the ES body, would the comparison still
>     pass?* It must not — otherwise the param is decorative. That mutation is
>     listed in "Done criteria".
> 11. Unscoped `/search` is unchanged: still 20 of 22 for `q=review`.
> 12. **The round-trip unit test exists and is non-vacuous** — the mutation in 7a
>     (dropping one `w_*` line) made it fail.
> 13. The two collaboration pages and the Graph page's spotlight all render and
>     work in the browser (see the full sweep in Step 14; a spot check here is
>     enough).
> 14. `scripts/capture_ui_baseline.py` and both JSON files are deleted;
>     `src/ui/collaboration_params.py`, its test, **and
>     `tests/test_ui_api_client_status_mapping.py`** are **kept**.
>
> Wait for `PASS` before starting Step 8.

---

### Phase 3 — Go live (the split becomes real)

---

### Step 8: Go live — split the images, the entrypoints and the compose topology

**This step is deliberately atomic, and it is the largest in the plan.** It is the
moment the UI stops being part of the API process: the API entrypoint drops the
Dash mount, the `ui` container appears to serve it, and `src/app/main.py` — the
temporary composition from Step 5 — is deleted. Doing any one of those without
the others leaves a step where nothing serves `/app`, which is exactly what the
stable-state rule forbids. So they ship together.

**8a. Split the images and requirements.**

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
`create_es_indexes.py` → uvicorn) unchanged, **except line 45**, which names
`app.main` — the composition module 8c deletes:

```bash
# BEFORE
cd /app && uvicorn app.main:app --host 0.0.0.0 --port 8000 \
    --forwarded-allow-ips="*"

# AFTER
cd /app && uvicorn app.api_main:app --host 0.0.0.0 --port 8000 \
    --forwarded-allow-ips="*"
```

Change **only** the module path. Everything else on that line and in the file
stays:

- `--host 0.0.0.0 --port 8000` unchanged.
- **`--forwarded-allow-ips="*"` unchanged, and its comment block at lines 34–44
  preserved verbatim.** That comment is the recorded justification from Plan 051's
  Gate 4: `*` is safe *only* because the service publishes no host port. Plan 052
  keeps that true for the API (port 8000 is unpublished in 8e), and the UI's
  8000 is also unpublished — so the rationale still holds. **Do not rewrite,
  shorten, or "improve" that comment.** It is a security rationale, and an
  executor who retypes the line without it silently deletes the reasoning that
  keeps the flag defensible. If the container is ever re-published, the comment
  is the only thing that says why that is wrong.
- The migration/index bootstrap steps stay: they are the API's, and removing them
  would leave the database un-migrated.

**If this edit is missed, the API container fails to start with
`ModuleNotFoundError: No module named 'app.main'` once 8c deletes it, and every
gate from this step onward is blocked.**

**8a-ii. Make the UI standalone — add `routes_pathname_prefix="/app/"`.**

This is the edit Step 5 deliberately deferred, and this is the step where it
becomes correct. In `src/ui/layout.py`, `create_dash_app()` (`:23-34`) currently
sets only `requests_pathname_prefix="/app/"`. Change it to set both:

```python
app = dash.Dash(
    __name__,
    requests_pathname_prefix="/app/",
    routes_pathname_prefix="/app/",
    ...
)
```

**Why it is correct here and nowhere earlier.** In Steps 5–7 the app was reached
through `WSGIMiddleware` mounted at `/app`, and a mount *strips* its prefix before
the WSGI app sees the request — so Dash's handlers had to stay registered at `/`.
This step removes the mount: gunicorn serves `ui_main.server` directly, and nginx's
`location /app { proxy_pass http://wba_ui; }` (**no trailing slash** — see 8d)
forwards the full `/app/...` URI intact. So Dash must now own the `/app` prefix
itself, and registering it natively at `/app/_dash-layout`,
`/app/_dash-update-component`, `/app/`, `/app/<path:path>` is what makes the UI
serve with no mount, no `a2wsgi`, and no `X-Forwarded-Prefix` handling.

Verified against this repo's real `create_dash_app()` with the prefix added and
the app served standalone (Flask test client, real `/app/...` URLs — the same
shape nginx produces):

```
/app/                          200
/app/chat                      200
/app/_dash-layout              200
/app/_dash-update-component    200
/app/assets/executive-dashboard.css  200
```

**This edit and 8c's deletion of `src/app/main.py` are one change, not two.**
With the prefix set, the mount cannot serve the UI; with the mount present, the
prefix breaks it. They must land in the same commit — which they do, since 8 is
atomic by construction.

**The `curl https://localhost/app/` → `200` verify at 8e is the check that this
landed.** If the UI 404s after this step, the prefix is missing; if it 404s *at
`/app/app/`*, the prefix was added without 8c removing the mount.

**8b. Create the UI entrypoint.** It needs a new, much smaller one:

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
# gate in this plan's Step 12 is what verifies they are not serializing.
```

**CI must install the UI requirements** so `mypy`/`pylint`/`pytest` cover
`src/ui/`. Update the three install lines in
`.github/workflows/pr_checks.yml` (`:31`, `:86`, `:114`) to include
`-r requirements.ui.txt`.

**Update `Dockerfile.api`'s `COPY` lines** to include `src/domain/`. Keep the
`requirements.api.txt` filename reference in step with the rename. Also check
**`ENTRYPOINT ["app/entrypoint.sh"]`** still resolves — the file keeps its path
and name, so this line should be unchanged, but confirm rather than assume.

**8c. Delete `src/app/main.py`.**

`git rm src/app/main.py`. The composition module from Step 5 has no remaining
purpose: the API runs `api_main`, and the UI runs `ui_main` in its own container.
Deleting it here — and not earlier — is what keeps every intermediate step
runnable. Afterwards there must be no import of `app.main` anywhere in the tree.

**Verify (8a)**: `docker build -f Dockerfile.api -t wba-api-test .` → succeeds
**Verify (8a)**: `docker build -f Dockerfile.ui -t wba-ui-test .` → succeeds
**Verify (8b)**: `grep -n "app\.main:app" src/app/entrypoint.sh` → **no matches**
**Verify (8b)**: `grep -n "api_main:app" src/app/entrypoint.sh` → 1 match
**Verify (8b)**: `grep -c "forwarded-allow-ips" src/app/entrypoint.sh` → 2 (the comment plus the invocation, exactly as before this plan)
**Verify (8b)**: `bash -n <the new UI entrypoint>` → exit 0
**Verify (8a)**: `docker run --rm wba-api-test pip list 2>/dev/null | grep -ci "^dash "` → `0`
**Verify (8a)**: `docker run --rm wba-ui-test pip list 2>/dev/null | grep -ciE "neo4j|elasticsearch|sqlalchemy|asyncpg|openai|langchain|matplotlib"` → `0`
**Verify (8a)**: `grep -n "requirements.ui.txt" .github/workflows/pr_checks.yml` → 3 matches
**Verify (8c)**: `grep -rn "app\.main" src/ tests/` → no matches

**8d. Split the nginx upstream.** `deploy/nginx/nginx.conf` currently has one
upstream (`:11-13`, named `wba_app`) used by four locations. Replace with two:

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

**8e. Compose.** In `docker-compose.yml`:

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

**8f. Handle the `API_SERVER` precedence trap.** `_resolve_source`
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

**8g. Update the code defaults.** `common/runtime_settings/config.py:77`,
`app/settings.py:85`, `api/settings/v1/models.py:116`, `consumers/main.py:206`
and `.env.example:106` all default to `http://app:8000/` — update to
`http://api:8000/`. Within this step the alias keeps the old name working, so a
missed site is not yet fatal — Step 9 is what proves they were all caught.

**Verify (8e–8g)**: `docker compose config -q` → exit 0
**Verify (8d)**: `nginx -t` (via the `docker run` form in Commands) → `test is successful`
**Verify (8e)**: `docker compose up -d --build` → all healthy
**Verify (8e)**: `curl -sf https://localhost/api/health` → `{"status":"healthy"}`
**Verify (8e)**: `curl -sf -o /dev/null -w '%{http_code}' https://localhost/app/` → `200`
**Verify (8a-ii)**: `grep -n "routes_pathname_prefix" src/ui/layout.py` → 1 match, value `"/app/"`
**Verify (8a-ii)**: `curl -sf -o /dev/null -w '%{http_code}' https://localhost/app/chat` → `200` (a real Dash route; the index alone can be served by a fallback and would not catch a registration mismatch)
**Verify (8a-ii)**: `curl -sf -o /dev/null -w '%{http_code}' https://localhost/app/app/_dash-layout` → `404` (the doubled path the mount produced in Steps 5–7 must be gone — if this is `200`, the mount is still in the path)
**Verify (8e)**: `docker compose exec api env | grep -c GITHUB_MCP_TOKEN` → `0`
**Verify (8e)**: `docker compose exec ui env | grep -cE "DATABASE_URL|OPENAI_API_KEY|NEO4J_PASSWORD"` → `0`
**Verify (8e)**: `docker compose exec ui python -c "import ui_main; print('ui imports OK')"` → `ui imports OK`. **This is the boot-time check for Step 6b.** The UI image has no `sqlalchemy` and no `DATABASE_URL`, so if any `src/ui/` module still imports `app.runtime_settings`, `app.common.timezone` or `app.settings`, this fails **here** with `ModuleNotFoundError` instead of surfacing as an unexplained 502.

> ### 🚦 MANUAL GATE 8 — operator check (the largest gate)
>
> **This is the first gate where the split is actually running, and the first
> where both images and the compose topology are in play.** Work the checks
> yourself; the executor supplies the stack, but the observations are yours.
>
> **Packaging (8a–8c):**
>
> 1. **Both images build.** This is the first gate that can fail for packaging
>    reasons unrelated to code.
> 2. The UI image contains **none** of the data-store or LLM packages. The grep
>    must print `0`. This is the isolation property made physical — the whole
>    reason for two images rather than two entrypoints.
> 3. The API image contains no `dash`.
> 4. `requirements.ui.txt` pins exact versions and includes `gunicorn`.
> 5. **The UI entrypoint runs no migrations, no index creation, no RabbitMQ
>    init.** Read it; confirm. A UI container that runs `alembic upgrade head`
>    would need a database connection and defeat the split.
> 6. The gunicorn invocation is `gthread` with `--threads`, **not** the default
>    `sync`. Check the flags are actually in the file.
> 7. CI installs the UI requirements in all three jobs that need them.
> 8. **`src/app/entrypoint.sh` names `app.api_main:app`, not `app.main:app`.**
>    This is the edit Step 5 forward-declared. If it still says `app.main`, the
>    API container will not start — stop and report rather than proceeding to
>    "see what happens".
> 9. **`src/app/main.py` is gone**, and `grep -rn "app\.main" src/ tests/` finds
>    nothing. If the composition module survives, the API process still mounts
>    Dash and the isolation property is not real.
> 10. **`routes_pathname_prefix="/app/"` is now present in
>     `src/ui/layout.py`'s `create_dash_app()`** — it was deliberately absent at
>     Step 5 (see 8a-ii). Two requests prove it landed correctly rather than
>     being added early or not at all:
>     `https://localhost/app/chat` → **`200`**, and
>     `https://localhost/app/app/_dash-layout` → **`404`**. The second is the
>     one that matters: a non-404 there means the app is still mounted and the
>     UI is being served through the doubled path, which looks fine on the index
>     page and breaks every callback.
> 11. **The `--forwarded-allow-ips` comment block (lines 34–44) is intact and
>     verbatim.** Compare it against the plan's baseline commit:
>     `git diff 5210f00 -- src/app/entrypoint.sh`. The only diff must be the
>     module path on line 45 — one hunk, one changed line. A lost security
>     rationale is invisible in every test and every gate; this is the only place
>     it is checked.
>
> **Running split (8d–8g):**
>
> 12. **Cold start works.** `docker compose down && docker compose up -d`, then
>     immediately browse `https://localhost/app`. No 502, no unstyled page. This
>     is what `depends_on` exists to guarantee — if there is a 502 window, the
>     dependency graph is wrong.
> 13. **The UI loads and is styled** — CSS from `/app/assets/` is served by the
>     **UI** container, not the API. Confirm in DevTools that `/app/assets/*`
>     responses come from the `ui` service.
> 14. **Dash callbacks work.** `/app/_dash-update-component` is served by the UI.
>     Run a Search, and check the network panel shows the callback POST going to
>     `/app/...` and an internal API call succeeding.
> 15. **The API works through the same proxy.** `https://localhost/api/v1/connectors/`
>     → JSON.
> 16. **The UI container holds no secrets.** `docker compose exec ui env` — no
>     `DATABASE_URL`, `OPENAI_API_KEY`, `NEO4J_PASSWORD`, `GITHUB_MCP_TOKEN`,
>     `CONNECTOR_ENCRYPTION_KEY`. This is the process-level version of Step 6's
>     code-level grep, and it is only possible now.
> 17. **The API container holds no dash.** `docker compose exec api pip list | grep dash`
>    → empty.
> 18. **Producers still fetch the runtime snapshot.** Check the producer logs for
>     `Fetched runtime settings snapshot` — **not** the fallback warning
>     (`Runtime settings API unreachable`). This is the gate for the rename; the
>     failure mode is silent degradation, so the log line is the evidence.
> 19. **Collaboration Network renders** (org and ego) — this is the page Plan 051
>     broke with `client_max_body_size`, and it is the page most sensitive to the
>     proxy split. Its two call sites went over HTTP in Step 7, so this is also
>     the end-to-end check for that step against two real processes.
> 20. **Spotlight still highlights** on the Graph page — Step 7's third swap, and
>     the one whose `ids` param only matters once the UI and API are separate.
> 21. **Chat streams progressively** — tokens arrive as they are generated, not in
>     one burst.
> 22. `docker compose ps` shows no restart loops after 2 minutes.
>
> Wait for `PASS` before starting Step 9, or `FAIL` with the check number.

---

### Step 9: Drop the `app` network alias

Only proceed once Step 8's gate confirmed the producers and consumer fetch the
snapshot successfully.

Remove the alias from the `api` service. Any remaining `app:8000` reference now
fails loudly at the DNS layer rather than silently degrading.

**Verify**: `docker compose config -q` → exit 0
**Verify**: `grep -rn "app:8000" docker-compose.yml src/ .env.example` → no matches
**Verify**: `docker compose up -d` → all healthy
**Verify**: producer logs still show `Fetched runtime settings snapshot`

> ### 🚦 MANUAL GATE 9 — operator check
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
> Wait for `PASS` before starting Step 10.

---

### Phase 4 — Client, audit, docs

---

### Step 10: Grow `src/ui/api_client.py` and migrate all 56 call sites

**In this plan the client carries no credentials.** Plan C teaches it to attach a
bearer token — which is why the two plans are not merged.

**`api_client.py` already exists — Step 7 created it** (7d-i) with
`get_json(url, params, timeout) -> dict` and the status→exception mapping that
keeps the collaboration banners working. This step **extends** that module; it
does not create it, and it must not replace or re-implement the mapping. Keep
7d-i's behaviour intact: the status translation is load-bearing for
`pages/collaboration_network/` and `pages/collaboration_network_ego/`, and
`tests/test_ui_api_client_status_mapping.py` guards it.

**Grow the client** into the single chokepoint for UI→API calls:

- Owns the base URL (from `UISettings.API_BASE_URL`) and the timeout (from the
  runtime-settings cache, read **per call** — see Step 6).
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

> ### 🚦 MANUAL GATE 10 — operator check
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
> 5. Timeouts are read **per call**, not captured at import (Step 6's bug class).
> 6. **A browser sweep of every page**: Chat, Search, Graph, Timeline, Analytics,
>    Catalog, Connectors, Settings, Collaboration Network (org + ego). A missed
>    call site is a runtime error on a rarely-exercised page — this is the check
>    that finds it.
>
> Wait for `PASS` before starting Step 11.

---

### Step 11: API-completeness audit (regression check, discarded afterwards)

**This is a regression gate, not a long-lived document.** Its purpose is to
verify this plan did not break anything. The artifact is discarded once it passes.

**Run it after Step 10**, when all UI→API calls have one chokepoint to enumerate.

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
   matches the endpoint's `response_model`. This is where Step 7's collab
   round-trip comparison and its `ids` scoping both surface.
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

> ### 🚦 MANUAL GATE 11 — operator check
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
>    *should* be used means a call site was missed in Step 10.
> 4. No artifact was left behind.
>
> Wait for `PASS` before starting Step 12.

---

### Step 12: gunicorn concurrency gate

**This exists because the split can silently serialize every callback.**

Before the split, Starlette ran sync Dash callbacks in a threadpool (~40
threads), so concurrent callbacks did not block each other. Gunicorn's default
worker is `sync` with one thread, which **would** serialize them. Step 8 pins
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

> ### 🚦 MANUAL GATE 12 — operator check
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
> Wait for `PASS` before starting Step 13.

---

### Step 13: Update the documentation

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

> ### 🚦 MANUAL GATE 13 — operator check
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
> Wait for `PASS` before starting Step 14.

---

### Step 14: Final CI gates and full-stack smoke

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
| Graph | query executes; spotlight highlights (Step 7's `ids`) |
| Timeline | renders; deep-link to Graph works |
| Analytics | gallery renders; both collaboration cards launch |
| Collaboration Network (org) | plots; filters apply |
| Collaboration Network (ego) | plots; person picker; collaborator cap |
| Catalog | browse; editor loads; favourite toggle |
| Connectors | list; env table renders (Step 6); scan status |
| Settings | runtime settings load; a write round-trips |

**Verify**: all five commands exit 0; `pylint` ≥ 9.0
**Verify**: every page in the sweep renders and its primary action works
**Verify**: `git status --short` shows no files outside the Scope list
**Verify**: `git diff --stat` touches no file under `src/connectors/` (except the zero expected)

> ### 🚦 MANUAL GATE 14 — operator check (final)
>
> **Report to the operator:** all five command outputs, the page-sweep table, and
> `git status --short`.
>
> **Operator verifies:**
> 1. All five gates pass. `pylint` ≥ 9.0.
> 2. `pytest -m unit tests -q` shows **no fewer** tests than the 2340 baseline +
>    this plan's additions. A drop means tests were skipped, not fixed.
> 3. The page sweep is complete. **Do not accept "the main pages work"** — this
>    is the gate that catches a missed call site from Step 10 and a missed import
>    from Steps 1–5.
> 4. No file outside the Scope list was modified.
> 5. The audit's conclusion (Step 11) is reflected: no capability reachable only
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
| 2  | Collaboration metadata → `src/domain/collaboration/` | suite green, `domain` imports nothing from `app.*`, `mypy` | Operator confirms `algorithm.py` did **not** move | ✅ passed |
| 3  | `analytics/registry.py`, `CONNECTOR_REGISTRY`, `MANAGED_INDEXES` → `src/domain/` | suite green, grep gates, `mypy` | Operator confirms registry contents unchanged | ✅ passed — plus `ENV PYTHONPATH=/app` added to `Dockerfile.app` (see Maintenance notes addendum) |
| 4  | `events.py` → `common/messaging/settings_events.py` | suite green, `aio_pika`-leak check, `mypy` | Operator confirms `common.runtime_settings` is now pure | ✅ passed — Phase 1 complete; operator confirmed rebuild + full suite + browser eyeball |

**Phase 2 — the structural split (every step ends with the stack still runnable)**

| Step | What it changes | Automated verify | Manual gate | Status |
|------|-----------------|------------------|-------------|--------|
| 5  | `src/app/dash_app/` → `src/ui/`; `api_main.py` + `ui_main.py` created; Flask request logging ported; `main.py` reduced to a **temporary composition**. `routes_pathname_prefix` stays **unset** — Step 8's edit | suite green, no `app.dash_app` remains, no `a2wsgi` outside `main.py`, `main.py` still imports, no `routes_pathname_prefix`, `/app/` **and** `/app/chat` both `200`, `mypy` | Operator confirms the prefix is **absent** (the mount strips `/app`), `main.py` **not** deleted, `ui_main` imports no FastAPI/DB/transport, and the rebuilt stack still serves `/app` | ⬜ |
| 6  | 12 import-time constants → function-local reads + regression test; **DB-free `UISettings` / `ui.runtime_settings` / `domain.timezone` so the UI stops importing `app.runtime_settings`, `app.common.timezone` and `app.settings`** (21 files — without this the UI container cannot boot); MCP env table from `GET /api/v1/settings/`; `NEO4J_URI` message fixed | both new tests pass **and fail on mutation**; the three old imports gone from `src/ui/`; grep gates | Operator **runs both mutations**; `test_ui_isolation.py` blocks real package names; `domain/` imports nothing from `app.*`/`ui.*`; `/app/chat` renders (it uses the timezone helpers) | ⬜ |
| 7  | Collab + ego + spotlight bypasses → HTTP, **one baseline captured before any swap**; optional `ids` param on `/search`; `src/ui/api_client.py` created with the status→exception mapping (7d-i) so the collab empty/invalid banners survive | before/after identities hold, **including the empty-result and invalid-config legs**; status-mapping unit test passes **and fails on mutation**; `ids` proved non-decorative; script deleted, both permanent tests kept | Operator confirms the baseline predates every swap, every data leg matches exactly, every error leg errored on both sides, and the no-data banners still render in the browser | ⬜ |

**Phase 3 — go live**

| Step | What it changes | Automated verify | Manual gate | Status |
|------|-----------------|------------------|-------------|--------|
| 8  | **The split goes live, atomically:** `Dockerfile.api`/`requirements.api.txt`; new `Dockerfile.ui`/`requirements.ui.txt`; both entrypoints; **`main.py` deleted**; compose `app`→`api` + new `ui`; nginx upstream split; `depends_on`; healthchecks; `API_SERVER` | both images build; UI image free of DB/LLM packages; `compose config`, `nginx -t`, both URLs 200, env checks | **Operator runs every check, including a cold start** | ⬜ |
| 9  | Drop the `app` network alias | grep clean; all healthy | Producer **logs** show the snapshot fetch succeeding | ⬜ |

**Phase 4 — client, audit, docs**

| Step | What it changes | Automated verify | Manual gate | Status |
|------|-----------------|------------------|-------------|--------|
| 10 | `src/ui/api_client.py` created; all 56 call sites migrated | zero raw `requests.*`; suite/`mypy`/`pylint` | Operator confirms no credentials; **full page sweep** | ⬜ |
| 11 | API-completeness audit (`A ⊆ B`, response shapes, orphans) | comparison passes; artifact discarded | Operator reviews mismatch and orphan lists | ⬜ |
| 12 | gunicorn concurrency gate | 4 and 12 concurrent requests overlap | Operator confirms overlap, not serialization | ⬜ |
| 13 | Docs: `CLAUDE.md`, `DEVELOPER_QUICK_START.md`, `USER_GUIDE.md`, `setup.sh`, `.env.example`, `authn-authz-design.md` | six grep gates | Operator **walks the two-process local dev flow** | ⬜ |
| 14 | Full CI gates + full-stack smoke | all five gates; every page renders | Operator signs off the complete page sweep | ⬜ |

---

## Test plan

**New tests:**

- `tests/test_runtime_settings_per_call.py` — Step 6's regression guard. Must
  assert **through the consuming function**, and must fail if a constant is
  reverted to module level. This is the single most important new test.
- `tests/test_domain_purity.py` — asserts `import domain` pulls none of
  `aio_pika`, `neo4j`, `elasticsearch`, `sqlalchemy`, `asyncpg`, `openai`,
  `langchain`, `mcp`, `matplotlib`, `community`. Guards Decision 4 structurally.
- `tests/test_collab_query_param_roundtrip.py` — Step 7's param translation, and
  the test that keeps Gate 7 honest after the baseline script is deleted. Over a
  seeded config matrix, assert
  `from_query_values(config_to_query_params(c)) == c`, i.e. the UI's serializer
  round-trips through the endpoint's own parser. Must be mutation-checked
  (dropping one `w_*` line makes it fail) — a round-trip test that passes both
  ways guards nothing. The ego path is covered end-to-end by Step 7c's live
  comparison instead, because the ego endpoint legitimately omits the org-only
  fields.
- `tests/test_search_ids_scope.py` — Step 7's `ids` param scopes the ES query and
  sets `size = len(ids)`; absent `ids` leaves behaviour unchanged. This is the
  cheap guard that the spotlight baseline cannot give you: it fails if `ids` is
  accepted and ignored.

**Regression:** `pytest -m unit tests -q` must hold at **2340 passed, 2 skipped**
or better at every step. A drop in the count is a STOP condition — it means tests
were silently skipped by a missing marker or a broken import.

**Mutations to run (not optional):**

1. Step 6 (6a) — revert one constant to module level; the new test must fail.
2. Step 6 (6b-v) — re-add `from app.runtime_settings import runtime_settings`
   to any `src/ui/` module; `tests/test_ui_isolation.py` must fail. This is the
   non-vacuity check for the only test that catches the UI container's boot-time
   `ModuleNotFoundError`, and it is the one a stub-both-ways implementation would
   pass silently. Also confirm the finder blocks the **real** package names
   (`sqlalchemy`, `asyncpg`, `neo4j`, `openai`, `aio_pika`) — a finder that
   blocks nothing makes the test pass for the wrong reason.
3. Step 7 — drop `ids` from the ES body; the comparison must fail.
4. Step 7 (7d-iii) — remove the 404→`CollaborationDataUnavailable` branch from
   `api_client.get_json`; `tests/test_ui_api_client_status_mapping.py` must fail.
   Without this the mapping — the only thing keeping the collaboration
   empty/invalid banners correct — rests on a test nobody proved non-vacuous.
   Note the baseline script **cannot** detect this mutation (its `in_process`
   leg bypasses `api_client`), which is exactly why the unit test exists.
5. Step 8 — remove `routes_pathname_prefix="/app/"` from `create_dash_app()`;
   the UI must stop serving at `/app`. **Not** a Step 5 mutation: at Step 5 the
   prefix must be *absent*, and adding it there is itself the failure this
   mutation exists to detect.
6. Step 8 — remove the `ui` healthcheck; the cold-start check must 502.
7. Step 5 — delete `src/app/main.py` early; the stack must fail to start. This is
   the mutation that proves the stable-state rule is load-bearing rather than
   ceremonial.

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
- [ ] `grep -rn "from app\.runtime_settings import\|from app\.common\.timezone import\|from app\.settings import" src/ui/` → no matches (the UI imports only its own DB-free replacements)
- [ ] `src/domain/settings.py` defines `UISettings` with **no** credential field, and `ApiSettings(UISettings)` adds them back
- [ ] `src/domain/` imports nothing from `app.*` or `ui.*`
- [ ] `tests/test_ui_isolation.py` passes **and fails when any `src/ui/` module re-imports `app.runtime_settings`**
- [ ] `docker compose exec ui python -c "import ui_main"` succeeds — the UI boots with no `sqlalchemy` and no `DATABASE_URL`
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
- [ ] `grep -rn "app\.main" src/ tests/` → no matches (`main.py` is gone)
- [ ] Step 7's before/after summaries are **identical** — collab org, ego and spotlight alike
- [ ] Step 7's baseline script called `src/ui/collaboration_params.py` (not a private param dict), so the re-run exercised the swapped translation
- [ ] `tests/test_collab_query_param_roundtrip.py` passes **and fails when one `w_*` line is dropped** from `config_to_query_params`
- [ ] Step 7's matched-ID sets are **identical**, and at least one spotlight query matched **>20** canvas nodes (otherwise the leg cannot tell scoped from unscoped)
- [ ] Step 7's empty-result and invalid-config legs (`org_7`, `org_invalid`, `ego_unknown_person`) each read `kind == "error"` on **both** sides — the legs are not vacuous
- [ ] `src/ui/api_client.py` maps status → exception: 404 to `CollaborationDataUnavailable` and 400 to a validation error, so the collab callbacks' existing `except` blocks still fire
- [ ] `tests/test_ui_api_client_status_mapping.py` passes **and fails when the 404 branch is removed** from `get_json`
- [ ] A 404 that is *not* the collaboration error does **not** become `CollaborationDataUnavailable` (the mapping discriminates on the body, not the bare status)
- [ ] Both collaboration pages still show their specific "no data" banner rather than "An unexpected error occurred." (browser check)
- [ ] `grep -rn "CollaborationDataUnavailable" src/ui/` → present in both `filter.py` files (the mapping was not deleted as "unused")
- [ ] Step 12's concurrency measurements show overlap
- [ ] `scripts/capture_ui_baseline.py` and its two JSON files are deleted; `src/ui/collaboration_params.py` is kept
- [ ] `docs/design/authn-authz-design.md` no longer claims an ASGI-mount mechanism for the UI
- [ ] No files outside the Scope list are modified (`git status`)
- [ ] **All 14 manual gates recorded `✅` in the Progress tracker**
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report back (do not improvise) if:

- **Any of Steps 1–5 changes observable behaviour.** They are pure refactors. The
  app must still run as one process and the suite must be green with the same
  test count. (Steps 6 and 7 change behaviour deliberately; their gates are what
  authorise that.)
- **Any step leaves `docker compose up -d --build` unable to reach `https://localhost/app`.**
  This is the stable-state rule. A step that removes something before its
  replacement exists is a defect in the step, not a reason to run the container
  from a stale image.
- **More or fewer than 12 module-level constants** exist in `src/ui/` (Step 6).
  The count is load-bearing; report the actual list.
- **More or fewer than 56 `requests.*` call sites** exist in `src/ui/` (Step 10).
- **The Step 7 before/after baselines differ.** Do not relax the comparison. Fix
  the param mapping, re-run, and report.
- **The Step 7 matched-ID sets differ.** Same.
- **No spotlight query matches more than 20 canvas nodes** (Step 7c's verify).
  The comparison cannot distinguish scoped from unscoped, so it proves nothing.
  Pick different queries; do not proceed.
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
- **Step 8's cold start shows a persistent 502 on `/app`.** The `depends_on`
  graph is wrong; report the observed sequence rather than adding sleeps.
- **Producers fall back to default runtime settings** after Step 8 or 9. Check
  the logs for `Runtime settings API unreachable` — that is the silent-degradation
  failure mode, and it means the rename is incomplete.
- **Any Step 14 page fails to render or its primary action errors.**
- **A change appears to require touching an out-of-scope file** — in particular
  anything under `src/connectors/`, or adding `AUTH_*` / `KEYCLOAK_*` settings.
- **`gunicorn` cannot be installed or the UI image build fails on it.**

## Maintenance notes

### Addendum — two packaging defects found during Phase 1 execution

Both broke the Compose stack while every CI gate stayed green, because pytest,
`mypy`, `pylint`, `bandit` and CI all run on the host with `src` on `sys.path`
and none of them builds the image. **Step 8 rewrites `Dockerfile.app` and must
carry both fixes forward.**

1. **`Dockerfile.app` did not copy `src/domain/`.** The plan's Scope lists
   `Dockerfile.api` for Step 8 but never adds the `COPY` for the new shared
   package, so as written Step 8 would have shipped an API image whose every
   entry path fails at import. Fixed in Step 1:
   `COPY src/domain/ ./domain/`.
2. **`Dockerfile.app` never set `PYTHONPATH`** — the only one of the five images
   that didn't (`Dockerfile.{github,jira,confluence}-producer` and
   `Dockerfile.signal-consumer` all set `ENV PYTHONPATH=/app`). Latent until
   Step 3 gave `app/scripts/create_es_indexes.py` its first first-party import.
   `src/app/entrypoint.sh:30` runs `python app/scripts/create_es_indexes.py`,
   and `python <script>.py` puts the *script's* directory on `sys.path[0]`, not
   the CWD — so `app`, `common` and `domain` were all unimportable from the
   entrypoint's one-shot scripts. `uvicorn app.main:app` masked it (uvicorn
   inserts the CWD). Fixed in Step 3: `ENV PYTHONPATH=/app`.

The generalisable rule for Step 8: **any `python <path>/<script>.py` invocation
in an entrypoint needs its package root on `PYTHONPATH` or must be run as
`python -m package.module`.** `alembic.ini` is unaffected — it already sets
`prepend_sys_path = ..`.

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
  reintroduces the per-site timeout bug Step 6 fixed and the auth gap Plan C will
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
- **The prefix and the mount never coexist.** `routes_pathname_prefix` is
  **absent** through Steps 5–7 (the UI is mounted, and the mount strips `/app`)
  and **present** from Step 8 (the UI is standalone and owns the prefix). Each
  state is correct only in its own half: get it wrong at Step 5 and every UI
  route 404s in the first structural step; get it wrong at Step 8 and every
  callback 404s while the index page still looks fine.
- **`requirements.ui.txt` includes `gunicorn` and excludes the data-store/LLM
  packages.** The exclusion list is the enforcement of Decision 1.
- **`client_max_body_size 50m` survives the nginx edit.** It is a Plan 051 fix and
  the collaboration pages depend on it.
- **The `/app` location has no trailing slash on `proxy_pass`.**
- **`api_client.py` carries no credentials.** That is the Plan B / Plan C boundary.
- **The UI healthcheck probes `/app/`, not the API.** Otherwise the UI flaps when
  the API restarts.
- **Steps 1–5 are behaviour-preserving.** A reviewer should be able to read each
  one's diff and see only moved code and rewritten imports. Steps 6 and 7 change
  behaviour on purpose, each behind a before/after comparison.
- **`docs/design/authn-authz-design.md` was edited in exactly four places.**

**Explicitly deferred out of this plan:**

- The `src/app/` → `src/api/` package rename — its own plan.
- `scripts/dev.sh` — two documented commands instead.
- Any credential handling in `api_client.py` — Plan C.
- The `/app/stream/<id>` SSE proxy route — Plan C.
- `AUTH_*`, `KEYCLOAK_*`, per-user ownership, the `auth_session` table — Plan C.
- FastAPI's `/docs`, `/redoc`, `/openapi.json` — Plan E.
- Per-person data scoping — Plan F.

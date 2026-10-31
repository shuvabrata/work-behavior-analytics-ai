# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

> **Single source of truth.** This file is the canonical project guide. `.github/copilot-instructions.md` is a **symlink to this file**, and the root `AGENTS.md` points here, so GitHub Copilot and other agents read exactly this content. Edit here only — never re-create a separate Copilot file. Deeper design docs live in `docs/design/`.

## Commands

Activate the virtualenv first (`source .venv/bin/activate`). Code lives in `src/` but is imported as top-level packages, so **`PYTHONPATH=src` is required** for any command that imports app code (pytest.ini sets it for tests; Docker and CI set it too).

| Task | Command |
|---|---|
| Backing services | `docker compose up -d postgres neo4j rabbitmq` |
| Migrations | `cd src/app && alembic upgrade head` (Alembic config is `src/app/alembic.ini`) |
| Run app (local dev) | Start the **API** and the **UI** as two processes — see *Local development* below. Both are required; the Compose stack remains the supported path |
| Compose stack (API + UI) | `docker compose up -d` → UI at `https://localhost/app` via nginx, health at `https://localhost/api/health`. Port `8000` is not published to the host |
| Unit tests (regression gate) | `pytest -m unit tests -q` |
| Single test | `pytest tests/test_analytics_page.py::test_layout_contains_layer_table_and_components -q` |
| Single module | `pytest -m unit tests/test_activity_api_unit.py -q` |
| Integration tests | `docker compose up -d` (the tests reach the app over HTTPS via nginx), then `pytest -m "integration and server" tests -q` |
| Neo4j tests | `pytest -m neo4j tests -q` |
| Typecheck | `mypy src/` |
| Lint | `pylint src --score=y` |
| Style | `flake8` (max-line-length 120; `.pylintrc` allows 150) |
| Security scan | `bandit -c .bandit.yml -r src/ -lll` |
| Regenerate activity spec | `PYTHONPATH=src python scripts/generate_signal_activity_spec.py` |

Full stack: `docker compose up -d`. One-shot producers/sync services are run manually: `docker compose run --rm github-producer` (or `jira-producer`, `confluence-producer`).

Shell/git/project commands in this repo are wrapped by the `rtk` token-optimizing proxy in harnesses that use it (e.g. `rtk git status`). Claude Code applies the rewrite automatically via a hook — there, do not hand-prefix.

### Local development

The API and the UI are separate services, so local dev needs **both** processes running. Start the API first — the UI fetches its runtime-settings snapshot from it:

```bash
# Terminal 1 — API. Start this FIRST.
PYTHONPATH=src uvicorn app.api_main:app --reload            # → http://127.0.0.1:8000/api/health  → 200

# Terminal 2 — UI. Needs the API's URL; the UI is a Flask/WSGI service.
API_BASE_URL=http://127.0.0.1:8000 PYTHONPATH=src \
  gunicorn ui_main:server --bind 127.0.0.1:8001 --reload    # → http://127.0.0.1:8001/app         → 200
```

`gunicorn --reload` works with the default `sync` worker and with `--worker-class gthread`. `gunicorn` is in `requirements.ui.txt`, not `requirements_dev.txt` — installing all `requirements*.txt` per `DEVELOPER_QUICK_START.md`'s setup loop provides it. The Compose stack (`docker compose up -d`) remains the supported path for day-to-day work.

### Docker Compose services

| Service | Purpose | Port(s) |
|---|---|---|
| `api` | FastAPI API only (internal only; no published host port) | 8000 |
| `ui` | Dash UI served by Flask/gunicorn (internal only; no published host port) | 8000 |
| `nginx` | TLS termination + reverse proxy in front of the api and ui services | 443, 80 (301 redirect to HTTPS) |
| `postgres` | Primary database | 5432 |
| `neo4j` | Graph database | 7474, 7687 |
| `rabbitmq` | Message queue for producers/consumer | 5672, 15672 (mgmt UI) |
| `elasticsearch` | Search / log analytics | 9200 |
| `github-mcp` | GitHub MCP server | 8082 |
| `github-producer`, `jira-producer`, `confluence-producer` | Fetch source APIs → RabbitMQ (one-shot) | — |
| `signal-consumer` | Consume ActivitySignals from RabbitMQ → Neo4j | — |

### CI gates (`.github/workflows/pr_checks.yml`) — a PR fails if any fails

- `pytest -q -m unit tests --cov=src`
- `mypy src/` — **strict** (`disallow_untyped_defs`, `disallow_untyped_calls`). Only `ui.*` relaxes `return-value, index, union-attr`. Every new function needs full annotations.
- `pylint src` — the repo-wide score must stay **≥ 9.0**
- `bandit -c .bandit.yml -r src/ -lll` — fails on High severity
- **Spec freshness** — CI regenerates `docs/design/spec-activity-signal.md` and fails if the committed file differs. After changing ActivitySignal models, run the generator above and leave the regenerated doc in the working tree; it must ship in the same change as the model update or CI fails.

## Import convention

Code lives in `src/` but is imported as top-level packages (`PYTHONPATH=src`). Never use relative imports across package boundaries and never `sys.path.insert(...)`.

```python
from common.logger import logger          # cross-service shared code → src/common/
from app.settings import settings         # the API → src/app/
from app.ai_agent.providers import get_provider
from domain.graph_theme import ...        # pure shared domain logic → src/domain/
```

When a package `__init__.py` re-exports a symbol, declare it with `__all__` (mypy strict treats plain re-exports as private):

```python
__all__ = ["get_layout"]
from .layout import get_layout
```

## Architecture

Four separately-containerized layers share `src/common/` (logger, `activity_signal/` schema, `messaging/`, `command_n_control/`, `runtime_settings/`), plus `src/domain/` for pure shared logic:

```
src/ui/          Dash UI served by Flask/gunicorn (imported as ui.*)
src/app/         FastAPI API (imported as app.*)
src/connectors/  Producer/consumer services (imported as connectors.*) — own Dockerfiles
src/common/      Cross-service shared code (imported as common.*)
src/domain/      Pure shared domain logic (imported as domain.*) — no I/O, no service deps
```

### Data pipeline (connectors)

```
GitHub/Jira/Confluence APIs
   → producers/       fetch + publish ActivitySignal JSON to RabbitMQ
   → consumers/       long-running service reads RabbitMQ, routes via sinks/neo4j_sink.py
   → modules/         per-entity Neo4j write logic (github/, jira/)
   → Neo4j
```

The `ActivitySignal` JSON schema (`docs/design/spec-activity-signal.md`, models in `src/common/activity_signal/`) is the contract: **all producers must emit it and all sinks must consume it.** Producers are one-shot; the consumer is long-running. Shared connector utilities (identity resolution, person cache) live in `connectors/commons/`. Producer scheduling/scan design is in `docs/design/scan-scheduler-design.md` and `src/app/scheduler.py`.

### Backend API layering (`src/app/api/<domain>/v1/`)

Strict separation — routers do HTTP only, services hold business logic, queries do DB access:

```
model.py    Pydantic request/response models
router.py   FastAPI routes, wired in src/app/api_main.py with prefix="/api/v1"
service.py  business logic (manages transaction boundaries)
query.py    SQLAlchemy / database access
```

All endpoints are under `/api/v1/`. All DB work is `async`/`await` with SQLAlchemy 2.0 `Mapped`/`mapped_column`. Migrations go through Alembic (`src/app/alembic/versions/`).

### AI agent pipeline (`src/app/ai_agent/`)

User messages are augmented before hitting the LLM:

1. `ai_agent.py` calls `augment_message_stream()` in `chains/chains.py`
2. `chains.py` fans out to active chains (Neo4j, MCP) per feature flags in settings
3. each chain yields a context envelope `{"source": ..., "context": ...}`
4. envelopes are composed into one bounded prompt block
5. the augmented message streams to the LLM provider

**Always obtain an LLM through the factory**, never construct a provider directly:

```python
from app.ai_agent.providers import get_provider
provider = get_provider()   # reads LLM_PROVIDER, returns a cached singleton
```

To add a provider, implement `LLMProvider` in `providers/` and register it in `factory.py`. To add an augmentation chain, add a file under `chains/` yielding context envelopes and register it in `chains.py` behind a feature flag.

The `mcp_integration/` layer is the *application's own* outbound MCP client (`client_manager.py`, `tool_executor.py`, `mcp_chain.py`), flagged by `GITHUB_MCP_ENABLED` / `ATLASSIAN_MCP_ENABLED`. This is app runtime code — write code for it, don't invoke it as a tool.

### Dash UI (`src/ui/`)

Created by `create_dash_app()` in `ui/layout.py` and served by gunicorn as a standalone Flask app from `src/ui_main.py`. It owns the `/app/*` paths; the API owns `/api/*`. One page is rendered at a time into `#page-content` by the `display_page` callback matching `dcc.Location` `pathname`.

- Pages live in `pages/<name>/` as a package: `layout.py` (view builders), `callbacks.py` (Dash callbacks), plus helpers.
- **A page package's `__init__.py` must `from . import callbacks  # noqa: F401`** — module-level `@callback`s register only on import, and `suppress_callback_exceptions=True` means a missing import fails *silently* (page renders, interactions do nothing). Existing examples: `pages/collaboration_network/__init__.py`, `pages/connectors/__init__.py`.
- **Shared Dash code must live outside `pages/`.** Importing any submodule of a page package runs its `__init__` (which imports `.layout`/`.callbacks`), so a module inside `pages/<name>/` cannot be imported by a different page without a circular import. Put cross-page modules at `ui/` (e.g. `ui/graph_styles.py`) or in the shared `ui/components/` package (e.g. `components/result_pane.py`), and import them absolutely (`from ui.graph_styles import …`). When a second page needs something that currently lives in a page package, move it out rather than importing across pages.
- `display_page` falls through to the chat page for unknown paths — add an explicit branch for each new route.
- Styling constants (`COLOR_*`, `FONT_*`, `SPACING_*`) come from `styles.py`; theme rules live in `assets/executive-dashboard.css` scoped under `.theme-executive-light` / `.theme-executive-dark`. The theme is a CSS class on `#app-shell` (plus `document.body` for portals); **`get_theme_tokens()` with no argument returns the static `ACTIVE_THEME` ("executive-light"), so pass the active theme explicitly if you need runtime-theme-correct colors.**
- Sidebar pages: Chat, Search, Graph, Analytics, Connectors, Settings. Collaboration Network is reached by deep-link from Analytics, not the sidebar.

### Runtime-mutable settings

Two layers, both important — these are **API-side**:

- `app.settings.settings` — pydantic-settings from `.env` (startup config).
- `app.runtime_settings.runtime_settings` — DB-backed overrides editable at runtime via the Settings UI (`/api/v1/settings`), e.g. `runtime_settings.get_int("HTTP_REQUEST_TIMEOUT")`, `runtime_settings.get("UI_DATETIME_FORMAT")`. Prefer these over hardcoding when a value is user-tunable. Design: `docs/design/runtime-settings-design.md`.

The UI holds neither. It reads `ui.settings` (a credential-free `UISettings`) and `ui.runtime_settings` (fetched from the API's runtime-snapshot endpoint), so the same page code calls `runtime_settings.get_int(...)` with the value sourced over HTTP rather than from a database.

Dash pages call the backend API over HTTP through the single client in `src/ui/api_client.py` — it owns the base URL (`UISettings.API_BASE_URL`, the container-internal `http://api:8000`, distinct from `EXTERNAL_BASE_URL`, the browser-facing `https://localhost`) and reads the timeout per call.

## Testing

Tests are in `tests/`. Markers (`pytest.ini`): `unit`, `integration`, `server`, `neo4j`, `rabbitmq`, `elasticsearch`.

**Always add the marker decorator** (e.g. `@pytest.mark.unit`) or a module-level `pytestmark = pytest.mark.unit`. Unmarked tests are silently skipped by `pytest -m unit tests`. There is no root `conftest.py`; tests import app code via `PYTHONPATH` from `pytest.ini` (`pythonpath = src . tests`).

**`server`-marked tests run against the Compose stack over HTTPS**, not a local uvicorn. Start it with `docker compose up -d` first; they reach the app at `https://localhost` through the nginx TLS proxy and have no reachability pre-check, so they **fail** (rather than skip) when the stack is down. `tests/conftest.py` points `SSL_CERT_FILE` at the local mkcert CA for these tests only — `httpx` verifies against `certifi` rather than the system store, so without it every request fails with `CERTIFICATE_VERIFY_FAILED`. If no CA can be found they fail with a message naming `mkcert -install`.

### Dedicated test suites with HTML reports

Some suites (e.g. connector validation) live in their own `tests/<suite>/` directory and emit self-contained HTML + JSON reports on every run. To add one:

1. Create `tests/<suite_name>/` with `__init__.py`, `conftest.py`, and `results/`.
2. Add `tests/<suite_name>/results/` to `.gitignore` (keep `results/.gitkeep` tracked).
3. In `conftest.py`, implement a `pytest_sessionfinish` hook writing timestamped `test_results_<timestamp>.html` / `.json` plus `latest.html` / `latest.json` into `results/`.
4. Provide a `track_result` fixture that tests call to register result dicts into the session-scoped list consumed by the hook.
5. Gate tests on the relevant service flag (`NEO4J_AI_LOOKUP_ENABLED`, …) via `@pytest.mark.skipif` — no extra opt-in env vars.
6. Run directly: `pytest tests/<suite_name>/ -v`.

## Code style

- **Type hints on all parameters and returns.** Built-in generics (`list[str]`, `dict[str, int]`) and `X | None`, not `typing.List`/`Optional`. Avoid `Any` unless unavoidable. Use `collections.abc.Callable` / `Iterable` / `Sequence` where it keeps signatures flexible. Third-party types where apt (`pydantic.BaseModel`, `pandas.DataFrame`).
- `from common.logger import logger` — never `print()`.
- f-strings for interpolation; PEP 8; mind pylint import order.
- Default to NO comments in the code.
- Write self-documenting code. Never add comments that describe "what" the code does or narrate the process.
- Only use comments to explain the "why" (e.g., non-obvious constraints, critical workarounds, or hidden gotchas).
- Absolutely no change-logs, narration, or past-tense comments (e.g., "Added feature X"). 
- Note: changing an existing function to add annotations must be **non-destructive** — no behavior, name, or logic changes.

## UI design standards (mandatory, not suggestions)

- **Destructive buttons**: `color="outline-danger"` only (never solid `danger`), and every destructive action needs a `dcc.ConfirmDialog` via the 2-stage callback (click → show dialog; `submit_n_clicks` → act). Message includes the scope and "This cannot be undone." Canonical example: "Reset All to Default" in `pages/settings/runtime.py`.
- **Alerts**: dedicated feedback region near the top of the active section; `dismissable=True` by default; error alerts persist, only transient successes auto-dismiss. Semantic colors: success = completed, danger = failure, warning = recoverable, info = neutral. Numeric settings on the Analytics cards are validated, never rewritten: an out-of-range value stays as typed, is reported in the card's alert region (which sits outside the collapsed controls panel so it is always visible), and disables the card's launch buttons until it is fixed. The bounds those cards validate against are read from the config model's `Field` constraints, never restated in the UI — change `ge`/`le` on `CollaborationNetworkConfig` and the card's validation and message follow. The card's numeric inputs deliberately carry no `min`/`max` and are `step="any"`: the browser would otherwise reject an out-of-range entry before Dash could send it, leaving the callback a `None` that reads as "cleared box". Note that removing `step` is not equivalent to `step="any"` — the HTML default is `1`, which still rejects `2.5`. Integer fields (`lookback_days`, `top_n_edges_per_node`) additionally reject a fractional value, because the model would otherwise truncate it silently.
- **Collapsible section headers**: text-only disclosure using the shared `collapse-toggle-subtle` class in `executive-dashboard.css` (no boxed chrome); keep the chevron as the affordance.
- Typography/spacing from `styles.py` tokens — no ad-hoc inline sizes or mixed `mb-*`/`mt-*`.

## Repo conventions

- **Never commit, push, open a PR, or rewrite history unless the user explicitly asks in that turn.** Leave changes in the working tree and report them. An earlier request does not authorize later commits.
- API endpoints: `/api/v1/` prefix; add a router module and include it in `src/app/api_main.py`.
- Alembic for every schema change; import new models in `src/app/db/models/__init__.py`.
- `queries_catalog/` (top level) holds the Cypher query catalog by domain; `src/app/query_catalog/` loads it. Neo4j uses a single **undirected** edge per relationship — do not add bidirectional edges (see `docs/design/RELATIONSHIPS_DESIGN.md`).
- `plans/` holds advisor-generated implementation plans with an index at `plans/README.md`; check it before starting sizable work.
- Commit messages are plain imperative sentences (e.g. "Activity timeline backend (#323)"); dependency bumps use Conventional Commit style from Dependabot.

## Common tasks

- **Add an API endpoint** — define Pydantic models in `src/app/api/<domain>/v1/model.py`, DB access in `query.py`, business logic in `service.py`, routes in `router.py`; include the router in `src/app/api_main.py`.
- **Add a DB model** — create it in `src/app/db/models/`, import it in `src/app/db/models/__init__.py`, then `cd src/app && alembic revision --autogenerate -m "description"` and `alembic upgrade head`.
- **Add an augmentation chain** — add a file under `ai_agent/chains/` yielding context envelopes `{"source": ..., "context": ...}`, then register it in `chains.py`'s `augment_message_stream()` behind a settings feature flag.
- **Add a UI page** — create the package in `ui/pages/`, add the nav link and route branch in `ui/layout.py`, and import `callbacks` from the page's `__init__.py`.

## Environment configuration

Loaded from `.env` (see `.env.example`) via `app.settings`. Key variables:

**Core** — `DATABASE_URL` (required), `LLM_PROVIDER` (`openai`\|`custom`, default `openai`), `LLM_MODEL` (default `gpt-5`), `OPENAI_API_KEY`, `CUSTOM_API_TOKEN`, `CUSTOM_API_URL`, `MAX_TOKENS` (chat history limit, default `16000`).

**Neo4j** — `NEO4J_AI_LOOKUP_ENABLED` (default `true` — controls AI agent lookups only; Neo4j is always required), `NEO4J_URI` (`bolt://localhost:7687`), `NEO4J_USERNAME`, `NEO4J_PASSWORD`, `FF_NEO4J_USE_PROVIDER_PIPELINE` (default `false`), `NEO4J_QUERY_TIMEOUT` (default `10`).

**Elasticsearch** — `ELASTICSEARCH_AI_LOOKUP_ENABLED` (default `true` — controls AI agent lookups only; the consumer sink and the search API are always active and Elasticsearch is always required), `ELASTICSEARCH_URL` (`http://localhost:9200`), `ELASTIC_PASSWORD`.

**MCP** — `GITHUB_MCP_ENABLED` / `ATLASSIAN_MCP_ENABLED` (default `false`), `MAX_MCP_ITERATIONS` (default `3`), `GITHUB_MCP_TOKEN`, `GITHUB_MCP_SERVER_URL` (`http://github-mcp:8082/mcp`), `ATLASSIAN_MCP_SERVER_URL`.

**Infrastructure & UI** — `RABBITMQ_URL`, `CONNECTOR_ENCRYPTION_KEY` (Fernet key for connector secrets, required), `HTTP_REQUEST_TIMEOUT` (default `60`), `TIMEZONE` (IANA name, default `UTC`), `UI_DATETIME_FORMAT` (`%b %d, %Y %I:%M %p`), `UI_DATE_FORMAT` (`%b %d, %Y`), `GRAPH_UI_MAX_NODES_TO_EXPAND` (default `20`), `GRAPH_UI_MAX_NODE_LABEL_CHARS` (default `10`).

**External URL / reverse proxy** — `EXTERNAL_BASE_URL` (default `https://localhost`) is the URL the *browser* uses; `API_BASE_URL` (default `http://localhost:8000`) is the URL the UI code uses to call the API from *inside* the container. They are deliberately different values and must stay that way — conflating them sends every UI callback through TLS to the public host and breaks the UI. Anything needing an absolute, browser-facing URL (an OAuth `redirect_uri`, for example) must build it from `EXTERNAL_BASE_URL`, never from the request's own scheme or host. The Compose stack terminates TLS at the `nginx` service; neither the `api` nor the `ui` service publishes a host port.

**API documentation** — `https://localhost/docs` (Swagger UI), `/redoc` and `/openapi.json`, proxied by nginx to the API, **deliberately unauthenticated**. Rationale and consequences: `docs/design/authn-authz-design.md`, "Non-API Surfaces §5". Guarded by `tests/test_nginx_docs_routes.py` and `tests/test_docs_endpoints_server.py`.

Note on the two `*_AI_LOOKUP_ENABLED` flags: the augmentation chains read them from the
`app.settings` singleton (`.env` at startup), not from `runtime_settings`. Editing them in
the Settings UI persists the value but does not change chain behaviour until the app is
restarted.

## Reference documents

Consult these before working in the area; they define patterns that must be followed.

| Document | When |
|---|---|
| `docs/design/high-level-design.md` | System architecture overview — start here |
| `docs/design/design-system.md` | Any UI work — canonical tokens; do not invent styles |
| `docs/design/frontend-design-skill.md` | UI work — "Executive Dashboard" aesthetic (Cormorant Garamond + Inter, navy/charcoal, 2px radius) |
| `docs/design/spec-activity-signal.md` | Connector/producer/sync work — canonical `ActivitySignal` schema |
| `docs/design/activity-timeline-design.md` | Activity Timeline work — history store, `/api/v1/activity` API, page deep-link URL contract, dev-only mock catalog |
| `docs/design/query-catalog-editor-design.md` | Query catalog work — user-defined override layer, Catalog listing/editor, the `origin` taxonomy |
| `docs/design/collaboration-network-design.md` | Collaboration Network work — scoring layers, community detection pipeline, org-wide and per-person views |
| `docs/design/producer-development-guide.md` | Writing or changing a producer |
| `docs/design/consumer-development-guide.md` | Changing the consumer service or adding a sink |
| `docs/design/rabbitmq-design.md` | RabbitMQ topology, routing keys, bindings |
| `docs/design/graph-db-high-level-design.md` | Neo4j schema, labels, property conventions |
| `docs/design/RELATIONSHIPS_DESIGN.md` | Neo4j schema / Cypher — undirected single-edge design |
| `docs/design/INDEX_STRATEGY.md` | Neo4j indexes — consult before adding node lookups |
| `docs/design/github-api-optimization.md` | GitHub producer/sync — incremental sync via `_last_synced_at` / `fully_synced` |
| `docs/design/runtime-settings-design.md` | Runtime-mutable settings and the Settings UI |

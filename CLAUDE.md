# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

> **Single source of truth.** This file is the canonical project guide. `.github/copilot-instructions.md` is a **symlink to this file**, and the root `AGENTS.md` points here, so GitHub Copilot and other agents read exactly this content. Edit here only — never re-create a separate Copilot file. Deeper design docs live in `docs/design/`.

## Commands

Activate the virtualenv first (`source .venv/bin/activate`). Code lives in `src/` but is imported as top-level packages, so **`PYTHONPATH=src` is required** for any command that imports app code (pytest.ini sets it for tests; Docker and CI set it too).

| Task | Command |
|---|---|
| Backing services | `docker compose up -d postgres neo4j rabbitmq` |
| Migrations | `cd src/app && alembic upgrade head` (Alembic config is `src/app/alembic.ini`) |
| Run app (API + UI) | `PYTHONPATH=src uvicorn app.main:app --reload` → UI at `http://localhost:8000/app`, health at `/api/health` |
| Unit tests (regression gate) | `pytest -m unit tests -q` |
| Single test | `pytest tests/test_analytics_page.py::test_layout_contains_layer_table_and_components -q` |
| Single module | `pytest -m unit tests/test_activity_api_unit.py -q` |
| Integration tests | `PYTHONPATH=src uvicorn app.main:app --reload` in one terminal, then `pytest -m "integration and server" tests -q` |
| Neo4j tests | `pytest -m neo4j tests -q` |
| Typecheck | `mypy src/` |
| Lint | `pylint src --score=y` |
| Style | `flake8` (max-line-length 120; `.pylintrc` allows 150) |
| Security scan | `bandit -c .bandit.yml -r src/ -lll` |
| Regenerate activity spec | `PYTHONPATH=src python scripts/generate_signal_activity_spec.py` |

Full stack: `docker compose up -d`. One-shot producers/sync services are run manually: `docker compose run --rm github-producer` (or `jira-producer`, `confluence-producer`).

Shell/git/project commands in this repo are wrapped by the `rtk` token-optimizing proxy in harnesses that use it (e.g. `rtk git status`). Claude Code applies the rewrite automatically via a hook — there, do not hand-prefix.

### Docker Compose services

| Service | Purpose | Port(s) |
|---|---|---|
| `app` | FastAPI + Dash | 8000 |
| `postgres` | Primary database | 5432 |
| `neo4j` | Graph database | 7474, 7687 |
| `rabbitmq` | Message queue for producers/consumer | 5672, 15672 (mgmt UI) |
| `elasticsearch` | Search / log analytics | 9200 |
| `github-mcp` | GitHub MCP server | 8082 |
| `github-producer`, `jira-producer`, `confluence-producer` | Fetch source APIs → RabbitMQ (one-shot) | — |
| `signal-consumer` | Consume ActivitySignals from RabbitMQ → Neo4j | — |

### CI gates (`.github/workflows/pr_checks.yml`) — a PR fails if any fails

- `pytest -q -m unit tests --cov=src`
- `mypy src/` — **strict** (`disallow_untyped_defs`, `disallow_untyped_calls`). Only `app.dash_app.*` relaxes `return-value, index, union-attr`. Every new function needs full annotations.
- `pylint src` — the repo-wide score must stay **≥ 9.0**
- `bandit -c .bandit.yml -r src/ -lll` — fails on High severity
- **Spec freshness** — CI regenerates `docs/design/spec-activity-signal.md` and fails if the committed file differs. After changing ActivitySignal models, run the generator above and commit the regenerated doc.

## Import convention

Code lives in `src/` but is imported as top-level packages (`PYTHONPATH=src`). Never use relative imports across package boundaries and never `sys.path.insert(...)`.

```python
from common.logger import logger          # cross-service shared code → src/common/
from app.settings import settings         # the app → src/app/
from app.ai_agent.providers import get_provider
```

When a package `__init__.py` re-exports a symbol, declare it with `__all__` (mypy strict treats plain re-exports as private):

```python
__all__ = ["get_layout"]
from .layout import get_layout
```

## Architecture

Three separately-containerized layers share `src/common/` (logger, `activity_signal/` schema, `messaging/`, `command_n_control/`, `runtime_settings/`):

```
src/app/         FastAPI + Dash application (imported as app.*)
src/connectors/  Producer/consumer services (imported as connectors.*) — own Dockerfiles
src/common/      Cross-service shared code (imported as common.*)
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
router.py   FastAPI routes, wired in src/app/main.py with prefix="/api/v1"
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

### Dash UI (`src/app/dash_app/`)

Created by `create_dash_app()` in `layout.py` and mounted onto FastAPI at `/app` via `a2wsgi` `WSGIMiddleware`. One page is rendered at a time into `#page-content` by the `display_page` callback matching `dcc.Location` `pathname`.

- Pages live in `pages/<name>/` as a package: `layout.py` (view builders), `callbacks.py` (Dash callbacks), plus helpers.
- **A page package's `__init__.py` must `from . import callbacks  # noqa: F401`** — module-level `@callback`s register only on import, and `suppress_callback_exceptions=True` means a missing import fails *silently* (page renders, interactions do nothing). Existing examples: `pages/collaboration_network/__init__.py`, `pages/connectors/__init__.py`.
- `display_page` falls through to the chat page for unknown paths — add an explicit branch for each new route.
- Styling constants (`COLOR_*`, `FONT_*`, `SPACING_*`) come from `styles.py`; theme rules live in `assets/executive-dashboard.css` scoped under `.theme-executive-light` / `.theme-executive-dark`. The theme is a CSS class on `#app-shell` (plus `document.body` for portals); **`get_theme_tokens()` with no argument returns the static `ACTIVE_THEME` ("executive-light"), so pass the active theme explicitly if you need runtime-theme-correct colors.**
- Sidebar pages: Chat, Search, Graph, Analytics, Connectors, Settings. Collaboration Network is reached by deep-link from Analytics, not the sidebar.

### Runtime-mutable settings

Two layers, both important:

- `app.settings.settings` — pydantic-settings from `.env` (startup config).
- `app.runtime_settings.runtime_settings` — DB-backed overrides editable at runtime via the Settings UI (`/api/v1/settings`), e.g. `runtime_settings.get_int("HTTP_REQUEST_TIMEOUT")`, `runtime_settings.get("UI_DATETIME_FORMAT")`. Prefer these over hardcoding when a value is user-tunable. Design: `docs/design/runtime-settings-design.md`.

Dash pages call the backend API over HTTP with sync `requests` (e.g. `pages/search.py`), using `os.getenv("API_BASE_URL", "http://localhost:8000")` and `runtime_settings.get_int("HTTP_REQUEST_TIMEOUT")`.

## Testing

Tests are in `tests/`. Markers (`pytest.ini`): `unit`, `integration`, `server`, `neo4j`, `rabbitmq`, `elasticsearch`.

**Always add the marker decorator** (e.g. `@pytest.mark.unit`) or a module-level `pytestmark = pytest.mark.unit`. Unmarked tests are silently skipped by `pytest -m unit tests`. There is no root `conftest.py`; tests import app code via `PYTHONPATH` from `pytest.ini` (`pythonpath = src . tests`).

### Dedicated test suites with HTML reports

Some suites (e.g. connector validation) live in their own `tests/<suite>/` directory and emit self-contained HTML + JSON reports on every run. To add one:

1. Create `tests/<suite_name>/` with `__init__.py`, `conftest.py`, and `results/`.
2. Add `tests/<suite_name>/results/` to `.gitignore` (keep `results/.gitkeep` tracked).
3. In `conftest.py`, implement a `pytest_sessionfinish` hook writing timestamped `test_results_<timestamp>.html` / `.json` plus `latest.html` / `latest.json` into `results/`.
4. Provide a `track_result` fixture that tests call to register result dicts into the session-scoped list consumed by the hook.
5. Gate tests on the relevant service flag (`NEO4J_ENABLED`, …) via `@pytest.mark.skipif` — no extra opt-in env vars.
6. Run directly: `pytest tests/<suite_name>/ -v`.

## Code style

- **Type hints on all parameters and returns.** Built-in generics (`list[str]`, `dict[str, int]`) and `X | None`, not `typing.List`/`Optional`. Avoid `Any` unless unavoidable. Use `collections.abc.Callable` / `Iterable` / `Sequence` where it keeps signatures flexible. Third-party types where apt (`pydantic.BaseModel`, `pandas.DataFrame`).
- `from common.logger import logger` — never `print()`.
- f-strings for interpolation; PEP 8; mind pylint import order.
- Docstrings on modules, classes, and public functions.
- Note: changing an existing function to add annotations must be **non-destructive** — no behavior, name, or logic changes.

## UI design standards (mandatory, not suggestions)

- **Destructive buttons**: `color="outline-danger"` only (never solid `danger`), and every destructive action needs a `dcc.ConfirmDialog` via the 2-stage callback (click → show dialog; `submit_n_clicks` → act). Message includes the scope and "This cannot be undone." Canonical example: "Reset All to Default" in `pages/settings/runtime.py`.
- **Alerts**: dedicated feedback region near the top of the active section; `dismissable=True` by default; error alerts persist, only transient successes auto-dismiss. Semantic colors: success = completed, danger = failure, warning = recoverable, info = neutral.
- **Collapsible section headers**: text-only disclosure using the shared `collapse-toggle-subtle` class in `executive-dashboard.css` (no boxed chrome); keep the chevron as the affordance.
- Typography/spacing from `styles.py` tokens — no ad-hoc inline sizes or mixed `mb-*`/`mt-*`.

## Repo conventions

- API endpoints: `/api/v1/` prefix; add a router module and include it in `src/app/main.py`.
- Alembic for every schema change; import new models in `src/app/db/models/__init__.py`.
- `queries_catalog/` (top level) holds the Cypher query catalog by domain; `src/app/query_catalog/` loads it. Neo4j uses a single **undirected** edge per relationship — do not add bidirectional edges (see `docs/design/RELATIONSHIPS_DESIGN.md`).
- `plans/` holds advisor-generated implementation plans with an index at `plans/README.md`; check it before starting sizable work.
- **Deployment model: single-user, self-hosted, trusted local environment.** Authentication and multi-tenancy are explicitly out of scope — do not add auth layers or tenant scoping.
- Commit messages are plain imperative sentences (e.g. "Activity timeline backend (#323)"); dependency bumps use Conventional Commit style from Dependabot.

## Common tasks

- **Add an API endpoint** — define Pydantic models in `src/app/api/<domain>/v1/model.py`, DB access in `query.py`, business logic in `service.py`, routes in `router.py`; include the router in `src/app/main.py`.
- **Add a DB model** — create it in `src/app/db/models/`, import it in `src/app/db/models/__init__.py`, then `cd src/app && alembic revision --autogenerate -m "description"` and `alembic upgrade head`.
- **Add an augmentation chain** — add a file under `ai_agent/chains/` yielding context envelopes `{"source": ..., "context": ...}`, then register it in `chains.py`'s `augment_message_stream()` behind a settings feature flag.
- **Add a UI page** — create the package in `dash_app/pages/`, add the nav link and route branch in `dash_app/layout.py`, and import `callbacks` from the page's `__init__.py`.

## Environment configuration

Loaded from `.env` (see `.env.example`) via `app.settings`. Key variables:

**Core** — `DATABASE_URL` (required), `LLM_PROVIDER` (`openai`\|`custom`, default `openai`), `LLM_MODEL` (default `gpt-5`), `OPENAI_API_KEY`, `CUSTOM_API_TOKEN`, `CUSTOM_API_URL`, `MAX_TOKENS` (chat history limit, default `16000`).

**Neo4j** — `NEO4J_ENABLED` (default `false`), `NEO4J_URI` (`bolt://localhost:7687`), `NEO4J_USERNAME`, `NEO4J_PASSWORD`, `FF_NEO4J_USE_PROVIDER_PIPELINE` (default `false`), `NEO4J_QUERY_TIMEOUT` (default `10`).

**MCP** — `GITHUB_MCP_ENABLED` / `ATLASSIAN_MCP_ENABLED` (default `false`), `MAX_MCP_ITERATIONS` (default `3`), `GITHUB_MCP_TOKEN`, `GITHUB_MCP_SERVER_URL` (`http://github-mcp:8082/mcp`), `ATLASSIAN_MCP_SERVER_URL`.

**Infrastructure & UI** — `RABBITMQ_URL`, `CONNECTOR_ENCRYPTION_KEY` (Fernet key for connector secrets, required), `HTTP_REQUEST_TIMEOUT` (default `60`), `TIMEZONE` (IANA name, default `UTC`), `UI_DATETIME_FORMAT` (`%b %d, %Y %I:%M %p`), `UI_DATE_FORMAT` (`%b %d, %Y`), `GRAPH_UI_MAX_NODES_TO_EXPAND` (default `20`), `GRAPH_UI_MAX_NODE_LABEL_CHARS` (default `10`).

## Reference documents

Consult these before working in the area; they define patterns that must be followed.

| Document | When |
|---|---|
| `docs/design/high-level-design.md` | System architecture overview — start here |
| `docs/design/design-system.md` | Any UI work — canonical tokens; do not invent styles |
| `docs/design/frontend-design-skill.md` | UI work — "Executive Dashboard" aesthetic (Cormorant Garamond + Inter, navy/charcoal, 2px radius) |
| `docs/design/spec-activity-signal.md` | Connector/producer/sync work — canonical `ActivitySignal` schema |
| `docs/design/producer-development-guide.md` | Writing or changing a producer |
| `docs/design/consumer-development-guide.md` | Changing the consumer service or adding a sink |
| `docs/design/rabbitmq-design.md` | RabbitMQ topology, routing keys, bindings |
| `docs/design/graph-db-high-level-design.md` | Neo4j schema, labels, property conventions |
| `docs/design/RELATIONSHIPS_DESIGN.md` | Neo4j schema / Cypher — undirected single-edge design |
| `docs/design/INDEX_STRATEGY.md` | Neo4j indexes — consult before adding node lookups |
| `docs/design/github-api-optimization.md` | GitHub producer/sync — incremental sync via `_last_synced_at` / `fully_synced` |
| `docs/design/runtime-settings-design.md` | Runtime-mutable settings and the Settings UI |

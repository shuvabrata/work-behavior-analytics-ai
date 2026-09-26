# Plan 021: Query Catalog Editor — user-defined query overrides, Library listing, and editor UI

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**:
> `git diff --stat 6e620e0..HEAD -- src/app/query_catalog src/app/api/queries src/app/api/graph/v1 src/app/dash_app/layout.py src/app/dash_app/pages`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.
>
> `src/app/api/graph/v1` is included in the drift check because this plan
> depends on `validate_read_only_query` (in `query.py`) and the
> `POST /graph/execute` endpoint (in `router.py`). If either changes, the
> excerpts in "Current state" must be re-verified — but do NOT modify any
> file under `graph/v1`.

## Status

- **Priority**: P2
- **Effort**: L
- **Risk**: MED
- **Depends on**: none
- **Category**: direction
- **Planned at**: commit `6e620e0`, 2026-09-26
- **Issue**: (none)

## Why this matters

Today the query catalog is read-only: users can browse and favourite the 140
system queries but cannot edit them, add their own, or test a Cypher variant
without leaving the app. This plan adds a **user-defined override layer** on
top of the YAML catalog — users can edit an existing query, create new ones in
existing or custom namespaces, and reset any override back to the factory
version. The merge happens at load time in `loader.py`, so every existing
consumer (API, graph execute, Dash pages) picks up user edits automatically
with no per-consumer changes. The UI adds a "Library" page (listing + filter +
search) and a full editor (metadata, tabular/graph Cypher, parameters, save /
save-as / test / reset).

## Current state

The facts the executor needs, inlined. All excerpts verified against commit
`6e620e0`.

### The catalog loader — `src/app/query_catalog/loader.py`

This is the single merge point. `load_catalog()` iterates namespaces and loads
each `*.yaml`, then sorts. `load_namespaces()` reads the master `catalog.yaml`.
Both must gain user-defined handling.

```python
def load_namespaces(catalog_dir=None) -> list[CatalogNamespace]:
    base_dir = (...).resolve()
    catalog_file = base_dir / "catalog.yaml"
    data = _load_yaml_mapping(catalog_file)
    raw_namespaces = data.get("namespaces")
    if not isinstance(raw_namespaces, list) or not raw_namespaces:
        raise CatalogLoadError(f"{catalog_file} must define a non-empty namespaces list")
    ...
    for order, raw_namespace in enumerate(raw_namespaces):
        ...
        namespaces.append(namespace)
    return namespaces
```

```python
def load_catalog(catalog_dir=None, *, validate_cypher: bool = True) -> list[CatalogQuery]:
    base_dir = (...).resolve()
    namespaces = load_namespaces(base_dir)
    queries: list[CatalogQuery] = []
    seen_ids: set[str] = set()
    for namespace in namespaces:
        namespace_dir = base_dir / namespace.directory
        if not namespace_dir.is_dir():
            raise CatalogLoadError(f"Namespace directory does not exist: {namespace_dir}")
        for query_file in sorted(namespace_dir.glob("*.yaml")):
            query = _load_query_file(query_file=query_file, namespace=namespace,
                                     base_dir=base_dir, validate_cypher=validate_cypher)
            if query.id in seen_ids:
                raise CatalogLoadError(f"Duplicate catalog query id: {query.id}")
            seen_ids.add(query.id)
            queries.append(query)
    return sorted(queries, key=lambda query: (query.namespace.order, query.name.lower()))
```

Key facts:
- `_load_query_file` derives `slug = query_file.stem`, `catalog_id = f"{namespace.directory}/{slug}"`, and `source_path = str(query_file.relative_to(base_dir.parent))`. So a user file at `queries_catalog/user_defined/hall_of_fame/top_n_committers.yaml` yields `source_path = "queries_catalog/user_defined/hall_of_fame/top_n_committers.yaml"` — this is what the UI checks to decide whether "Reset to factory" is shown.
- `_SAFE_ID_SEGMENT = re.compile(r"^[a-z0-9][a-z0-9_]*$")` (module-level) validates slugs and namespace directories. **Note**: this regex is also defined in `model.py:10` — always import it from `loader.py`, not `model.py`, to avoid circular imports.
- `_load_query_file` calls `validate_read_only_query(query_text)` from `app.api.graph.v1.query` when `validate_cypher=True`. Reuse this for PUT validation.
- `load_namespaces` **raises** if the namespaces list is empty — the user-defined merge must not trip this path (see Step 1).

### The model — `src/app/query_catalog/model.py`

`CatalogQuery` has `model_config = ConfigDict(extra="forbid")` and **requires**
`id`, `slug`, `namespace`, `available_views`, `source_path` — all derived or
read-only. **It cannot be reused as the PUT request body.** A dedicated write
model is required (Step 3). `CatalogParameter` fields: `name` (required),
`env_var`, `required` (required bool), `label`, `type`, `placeholder`,
`description`. `CatalogStatus = Literal["active", "draft", "deprecated"]`.
`CatalogView = Literal["tabular", "graph"]`.

### The API layer — `src/app/api/queries/v1/`

- `router.py` — `APIRouter(prefix="/queries", tags=["queries"])`. Existing
  routes: `GET /catalog`, `GET /catalog/namespaces`, `GET /catalog/{namespace}/{slug}`,
  plus `catalog-metadata` routes. **No PUT/DELETE on `/catalog/{namespace}/{slug}` yet.**
- `service.py` — read-only. `list_catalog_queries()`, `get_catalog_query(namespace, slug)`
  (builds `catalog_id = f"{namespace}/{slug}"` and scans `query.list_catalog_queries()`),
  `list_namespaces()`. All delegate to `query.py` → `loader.py`.
- `query.py` — thin: `list_catalog_queries()` → `load_catalog()`,
  `list_catalog_namespaces()` → `load_namespaces()`.

Because the service/query layers already funnel through `load_catalog()`, the
merge logic in `loader.py` propagates automatically — **no changes needed in
`service.py` or `query.py`** for reads.

### The graph execute endpoint (used by the editor "Test" button)

- `POST /api/v1/graph/execute` — `src/app/api/graph/v1/router.py:23`. Request
  model `GraphExecuteRequest` (`src/app/api/graph/v1/model.py`): `source`
  (`"raw"|"catalog"`, default `"raw"`), `query`, `catalog_id`, `view`
  (`"auto"|"graph"|"tabular"`), `parameters`. `source="raw"` requires `query`
  (model validator raises `ValueError` → router maps to **400**, not 422).
- `validate_read_only_query(query)` — `src/app/api/graph/v1/query.py:92`.
  Returns `True` if read-only, `False` if it contains write keywords
  (`CREATE`, `MERGE`, `DELETE`, `DETACH`, `SET`, `REMOVE`, `DROP`, `FOREACH`,
  `APOC.CYPHER.*`, `APOC.PERIODIC.ITERATE`).
- **The "Test" button requires a live Neo4j** — `execute_and_format_query`
  runs the Cypher. UI tests must mock the endpoint (Step 7).

### The Dash app — `src/app/dash_app/layout.py`

- `requests_pathname_prefix="/app/"` (line 27).
- Sidebar nav links are `dbc.NavLink` with `fas fa-*` icons. Analytics is line
  43 (`fas fa-chart-pie`), Connectors is line 44 (`fas fa-plug`). The Library
  link goes **between** them.
- `display_page(pathname)` (lines 137–160) dispatches on exact pathname
  matches, plus one prefix match: `if pathname and pathname.startswith("/app/connectors/"):`
  (line 144). The editor routes must follow this prefix pattern.
- Page packages live in `src/app/dash_app/pages/`. The `connectors/` package
  is the exemplar for a multi-file page package:

```python
# src/app/dash_app/pages/connectors/__init__.py
"""Connectors pages."""
__all__ = ["get_detail_layout", "get_layout"]
from .layout import get_detail_layout
from .layout import get_layout
# Import callbacks to register them with Dash
# pylint: disable=unused-import
from . import callbacks  # noqa: F401
```

  Match this: `__all__` for re-exports (mypy strict), and import callbacks
  modules for their registration side effects.

### Repo conventions to follow

- **Imports**: absolute, top-level packages via `PYTHONPATH=src`. Never
  relative imports across package boundaries. See `.github/copilot-instructions.md`.
- **Type hints**: built-in generics (`list[str]`), pipe unions (`str | None`),
  no `Any` unless unavoidable. All functions annotated.
- **Logging**: `from common.logger import logger` — never `print()`.
- **Destructive buttons**: `color="outline-danger"` (never solid `danger`),
  always behind a `dcc.ConfirmDialog` with the phrase "This cannot be undone."
  Canonical example: "Reset All to Default" in
  `src/app/dash_app/pages/settings/runtime.py`.
- **Collapsible headers**: text-only, class `collapse-toggle-subtle` from
  `src/app/dash_app/assets/executive-dashboard.css`.
- **Tests**: every test function MUST carry a custom marker
  (`@pytest.mark.unit` / `@pytest.mark.integration`). See `pytest.ini`.

## Commands you will need

| Purpose   | Command | Expected on success |
|-----------|---------|---------------------|
| Unit tests | `source .venv/bin/activate && PYTHONPATH=src pytest -m unit tests/test_query_catalog_merge.py tests/test_library_callbacks.py tests/test_library_editor_callbacks.py -q` | all pass |
| Full unit suite | `source .venv/bin/activate && PYTHONPATH=src pytest -m unit tests -q` | all pass (no regressions) |
| Typecheck | `source .venv/bin/activate && mypy src/app/query_catalog src/app/api/queries src/app/dash_app/pages/library` | exit 0, no errors |
| Lint | `source .venv/bin/activate && pylint src/app/query_catalog/loader.py src/app/api/queries/v1/user_defined_service.py src/app/api/queries/v1/router.py src/app/dash_app/pages/library` | exit 0 |
| Integration (optional, needs running app) | `PYTHONPATH=src uvicorn app.main:app --reload` then `pytest -m "integration and server" tests/test_query_catalog_api_integration.py -q` | all pass |

## Suggested executor toolkit

- Read `.github/copilot-instructions.md` before starting — it defines the
  import convention, type-hint rules, and UI design standards this plan relies on.
- Read `docs/design/design-system.md` and `docs/design/frontend-design-skill.md`
  before any UI work — the Library pages must match the Executive Dashboard
  aesthetic (Cormorant Garamond + Inter, navy/charcoal, 2px radius).

## Scope

**In scope** (the only files you should modify or create):
- `src/app/query_catalog/loader.py` — merge logic + `load_namespaces` changes
- `src/app/query_catalog/model.py` — add `CatalogQueryWrite` (and any write-side helpers)
- `src/app/query_catalog/__init__.py` — export `CatalogQueryWrite`
- `src/app/api/queries/v1/user_defined_service.py` — NEW: file I/O for writes/deletes
- `src/app/api/queries/v1/router.py` — add PUT + DELETE routes
- `src/app/dash_app/pages/library/` — NEW package (layout, editor_layout, callbacks, editor_callbacks, `__init__.py`)
- `src/app/dash_app/layout.py` — Library nav link + routing
- `.gitignore` — add `queries_catalog/user_defined/` entry
- `tests/test_query_catalog_merge.py` — NEW
- `tests/test_library_callbacks.py` — NEW
- `tests/test_library_editor_callbacks.py` — NEW
- `tests/test_query_catalog_api_integration.py` — extend (PUT/DELETE cases)
- `tests/test_query_catalog_api.py` — extend (PUT/DELETE cases)
- `plans/README.md` — status row update

**Out of scope** (do NOT touch, even though they look related):
- `src/app/api/queries/v1/service.py` and `query.py` — reads already funnel
  through `load_catalog()`; no changes needed. If you find yourself editing
  them, STOP.
- `src/app/api/graph/v1/*` — the execute endpoint already exists; do not modify it.
- `src/app/dash_app/pages/graph/` — the existing graph console is untouched.
- Any change to the read response shape of `GET /catalog` — clients depend on it.
- The `catalog-metadata` (favourites) feature — unrelated, leave alone.

## Git workflow

- Branch: `feature/query-editor` (already checked out).
- Stop short of committing to git.
- Do NOT push or open a PR unless the operator instructed it.

## Steps

### Step 1: Add user-defined merge logic to `loader.py`

Modify `src/app/query_catalog/loader.py`:

1. Add a module constant `USER_DEFINED_DIR = "user_defined"`.
2. In `load_namespaces()`, after the existing loop builds `namespaces` from the
   system `catalog.yaml`, check for `base_dir / USER_DEFINED_DIR / "catalog.yaml"`.
   If it exists, load it with `_load_yaml_mapping`, read its `namespaces` list,
   and append each as a `CatalogNamespace` with `order` continuing from the
   current `len(namespaces)`. Reuse the same duplicate-directory check. If the
   user `catalog.yaml` references a directory that does not exist under
   `user_defined/`, raise `CatalogLoadError` with a clear message (edge case EC1).
   If `user_defined/` does not exist at all, return system namespaces unchanged.
3. In `load_catalog()`, after loading system queries, load user queries:
   - If `base_dir / USER_DEFINED_DIR` does not exist or is empty, return the
     system list unchanged (tests B1, B2).
   - Otherwise, iterate the **user** namespaces (from the merged
     `load_namespaces` result, filtered to those whose directory lives under
     `user_defined/`), load each `*.yaml` via `_load_query_file` with
     `base_dir` still the catalog root (so `source_path` becomes
     `queries_catalog/user_defined/{ns}/{slug}.yaml`).
   - Merge: build a dict keyed by `query.id` from the system queries. For each
     user query, if the id exists in the dict, **replace** that entry; if new,
     **append**. Detect duplicate ids *within* the user set and raise
     `CatalogLoadError` (tests B7, EC2).
   - Return the merged list **sorted exactly as today**:
     `sorted(queries, key=lambda q: (q.namespace.order, q.name.lower()))`.
     Do NOT try to force user queries to the end of their namespace — the
     existing sort interleaves by name, and that is the accepted behavior.

**Verify**:
- `source .venv/bin/activate && PYTHONPATH=src python -c "from app.query_catalog import load_catalog, load_namespaces; print(len(load_catalog()), len(load_namespaces()))"`
  → `140 9` (no `user_defined/` dir exists yet, so counts are unchanged).

### Step 2: Add `CatalogQueryWrite` to `model.py`

Add to `src/app/query_catalog/model.py` a write-side model that the PUT body
can deserialize into. It must NOT reuse `CatalogQuery` (which requires derived
fields and forbids extras). Fields:

- `name: str` (min_length 1)
- `description: str` (min_length 1)
- `summary: str | None`
- `queries: dict[CatalogView, str]` — at least one non-empty variant
- `parameters: list[CatalogParameter]` (default `[]`)
- `tags: list[str]` (default `[]`)
- `owner: str | None`
- `status: CatalogStatus | None`
- `default_view: CatalogView | None`

Add a `model_validator(mode="after")` that: (a) rejects an empty `queries`
dict, (b) rejects empty/whitespace query text, (c) if `default_view` is set,
requires it to be a key in `queries`. Use `ConfigDict(extra="forbid")`.

After creating the model, update `src/app/query_catalog/__init__.py` to export
it. Add `CatalogQueryWrite` to the import from `.model` and to `__all__`:

```python
from .model import CatalogNamespace, CatalogParameter, CatalogQuery, CatalogQueryWrite

__all__ = [
    "CatalogLoadError",
    "CatalogNamespace",
    "CatalogParameter",
    "CatalogQuery",
    "CatalogQueryWrite",
    ...
]
```

**Verify**:
- `source .venv/bin/activate && PYTHONPATH=src python -c "from app.query_catalog.model import CatalogQueryWrite; print(CatalogQueryWrite(name='x', description='y', queries={'tabular':'MATCH (n) RETURN n'}).name)"`
  → `x`

### Step 3: Create `user_defined_service.py`

Create `src/app/api/queries/v1/user_defined_service.py`. It owns all file I/O
for the `user_defined/` tree. Functions (all synchronous, called from the async
router via `asyncio.to_thread` — match the graph router's pattern):

- `save_query(namespace: str, slug: str, payload: CatalogQueryWrite) -> CatalogQuery`
  - Validate `namespace` and `slug` against `_SAFE_ID_SEGMENT` (import from
    `app.query_catalog.loader`); on failure raise `ValueError` with message
    `f"Invalid namespace or slug: {namespace}/{slug}"` (→ 422).
  - Validate every query variant with `validate_read_only_query` (import from
    `app.api.graph.v1.query`); on failure raise `ValueError` with message
    `f"{view} query contains write operations"` (→ 422).
  - Build the target path `queries_catalog/user_defined/{namespace}/{slug}.yaml`
    (resolve the catalog root via `get_default_catalog_dir()` from `loader.py`).
  - Serialize the payload to YAML using `yaml.dump()` with
    `default_flow_style=False` and `sort_keys=False`. Write only: name,
    description, summary, queries, parameters, tags, owner, status,
    default_view. Do NOT write `id`, `slug`, `namespace`, `available_views`,
    or `source_path` — the loader derives them.
  - Determine whether `namespace` is a system namespace: call
    `load_namespaces()` and check if any system namespace has
    `directory == namespace`. A namespace is "system" if it appears in the
    system `catalog.yaml` (not under `user_defined/`). If `namespace` is NOT
    a system namespace, ensure `queries_catalog/user_defined/catalog.yaml`
    exists and contains the namespace entry (append if missing), then write
    the updated `catalog.yaml`.
  - Write the query file (create parent dirs). Return the merged `CatalogQuery`
    by calling `get_catalog_query(f"{namespace}/{slug}")` from
    `app.query_catalog` (imported as `from app.query_catalog import get_catalog_query`).
- `delete_query(namespace: str, slug: str) -> bool`
  - Delete `queries_catalog/user_defined/{namespace}/{slug}.yaml` if it exists.
  - Return `True` if a file was deleted, `False` if no override existed.
  - Note: deleting the last query in a custom namespace does NOT remove the
    namespace entry from `user_defined/catalog.yaml`. This is deferred — an
    empty namespace is harmless (it produces zero queries at load time).

Use `from common.logger import logger` for logging. Do not touch `service.py`
or `query.py`.

Also add `queries_catalog/user_defined/` to `.gitignore` so user overrides are
never committed. Append this line to `.gitignore`:

```
# User-defined query catalog overrides (local only)
queries_catalog/user_defined/
```

**Verify**:
- `source .venv/bin/activate && PYTHONPATH=src python -c "from app.api.queries.v1.user_defined_service import save_query, delete_query; print(callable(save_query), callable(delete_query))"`
  → `True True`
- `source .venv/bin/activate && PYTHONPATH=src python -c "
from app.api.queries.v1.user_defined_service import save_query, delete_query
from app.query_catalog.model import CatalogQueryWrite
from app.query_catalog import get_default_catalog_dir
import tempfile, os
# Create a temp catalog dir with a minimal system catalog
# save a query, verify it appears in load_catalog(), delete it, verify it's gone
print('ok')"`
  → `ok` (no import errors; the module is structurally sound)

### Step 4: Register PUT and DELETE routes in `router.py`

Add to `src/app/api/queries/v1/router.py`:

- `async def put_catalog_query(namespace: str, slug: str, payload: CatalogQueryWrite) -> CatalogQuery`
  — `PUT /catalog/{namespace}/{slug}`. Call
  `await asyncio.to_thread(user_defined_service.save_query, namespace, slug, payload)`.
  Map `ValueError` → `HTTPException(422, detail=str(exc))`. Return the saved
  `CatalogQuery` (200).
- `async def delete_catalog_query(namespace: str, slug: str) -> dict | Response`
  — `DELETE /catalog/{namespace}/{slug}`. Call
  `await asyncio.to_thread(user_defined_service.delete_query, namespace, slug)`.
  If `True`, return `{"message": "Query override deleted"}` (200); if `False`,
  return `Response(status_code=204)`.

Import `asyncio` (already used elsewhere in the codebase for `to_thread`).
Keep the existing read routes untouched.

**Verify**:
- `source .venv/bin/activate && PYTHONPATH=src python -c "from app.api.queries.v1.router import router; print([r.path for r in router.routes if r.path.startswith('/catalog/')])"`
  → includes `/catalog/{namespace}/{slug}` for GET, PUT, and DELETE.

### Step 5: Merge + API tests

Create `tests/test_query_catalog_merge.py` (marker `@pytest.mark.unit`). Use
`tmp_path` to build synthetic catalogs — model the structure on
`tests/test_query_catalog_loader.py` (which uses the real `CATALOG_DIR`), but
construct a minimal system catalog in `tmp_path` with a `catalog.yaml` and one
or two namespace dirs. Cover B1–B10 from the design doc (see Test plan below).

Extend `tests/test_query_catalog_api.py` and
`tests/test_query_catalog_api_integration.py` with PUT/DELETE cases (C1–C9).
**Important**: the integration tests run against the real `queries_catalog/`.
They must write only under `user_defined/` and clean up after themselves
(delete the files they create) so the hardcoded `count == 140` assertions in
the existing tests stay valid. Add a note to
`test_catalog_list_endpoint_returns_normalized_catalog` and
`test_load_catalog_normalizes_all_existing_entries` that the count may change
when user-defined queries exist.

**Verify**:
- `source .venv/bin/activate && PYTHONPATH=src pytest -m unit tests/test_query_catalog_merge.py -q` → all pass
- `source .venv/bin/activate && PYTHONPATH=src pytest -m unit tests/test_query_catalog_api.py -q` → all pass

### Step 6: Library listing page (`/app/library`)

Create `src/app/dash_app/pages/library/` with `__init__.py`, `layout.py`,
`callbacks.py`. Model the package on `src/app/dash_app/pages/connectors/`.

The `__init__.py` must export both layout functions and import callbacks for
side effects:

```python
# src/app/dash_app/pages/library/__init__.py
"""Library pages — query catalog browser and editor."""
__all__ = ["get_editor_layout", "get_layout"]
from .layout import get_layout
from .editor_layout import get_editor_layout
# Import callbacks to register them with Dash
# pylint: disable=unused-import
from . import callbacks  # noqa: F401
from . import editor_callbacks  # noqa: F401
```

- `layout.py` — `get_layout()` returns the listing page: top bar with "New
  Query" button, namespace dropdown, search input; a table with columns Name,
  Namespace, Tags (chips), Status (badge), Views (tabular/graph icons); per-row
  "Edit" and "Reset to factory" buttons. "Reset to factory" is only rendered
  when the row's `source_path` contains `user_defined/`.
- `callbacks.py` — register with Dash:
  - `dcc.Location` pathname == `/app/library` → fetch `GET /api/v1/queries/catalog`
    and `GET /api/v1/queries/catalog/namespaces`, render table + dropdown.
  - Namespace dropdown change → client-side filter rows.
  - Search input change → client-side filter by name/tags/id.
  - "Edit" click → `window.open("/app/library/edit/{ns}/{slug}")` (clientside).
  - "New Query" click → `window.open("/app/library/new")` (clientside).
  - "Reset to factory" click → `dcc.ConfirmDialog` (message: "Are you sure you
    want to reset '{name}' to factory defaults? This will discard all user
    edits for this query. This cannot be undone.") → on confirm, `DELETE
    /api/v1/queries/catalog/{ns}/{slug}` → refresh table → success alert.

Use the `collapse-toggle-subtle` class for any collapsible filter section, and
the design tokens from `src/app/dash_app/styles.py`.

**Verify**:
- `source .venv/bin/activate && mypy src/app/dash_app/pages/library` → exit 0

### Step 7: Library editor page (`/app/library/edit/{ns}/{slug}` and `/app/library/new`)

Create `editor_layout.py` and `editor_callbacks.py` in the same package.

- `editor_layout.py` — `get_editor_layout()` returns the shared editor form:
  read-only info bar (id, namespace), editable metadata fields (name,
  description, summary, owner, status dropdown, tags), two monospace
  `dbc.Textarea` editors ("Tabular Query" / "Graph Query"), a parameter list
  (rows of name/label/type/required/placeholder/description/env_var with
  Add/Remove), default-view radio (only views with non-empty Cypher), and
  action buttons: Save, Save As, Test, Reset to Factory.
- `editor_callbacks.py`:
  - On mount, parse `{namespace}/{slug}` from the pathname
    (`pathname.split("/app/library/edit/")[-1]`), `GET
    /api/v1/queries/catalog/{ns}/{slug}`, populate the form. For `/app/library/new`,
    leave fields blank and make slug/namespace editable.
  - **Save** → `PUT /api/v1/queries/catalog/{ns}/{slug}` with the form data →
    success alert.
  - **Save As** → modal with a namespace dropdown (populated from
    `GET /api/v1/queries/catalog/namespaces`) plus a "+ New namespace…" option
    that reveals a custom text input, and a slug input. On submit, `PUT` to the
    new id → success.
  - **Test** → `POST /api/v1/graph/execute` with `{"source": "raw", "query":
    <Cypher from the currently selected view's Textarea>, "view": "auto"}`.
    The "currently selected view" is the one chosen in the default-view radio
    group — if the user has "Graph" selected, test the Graph Query textarea;
    if "Tabular", test the Tabular Query textarea. Render results in an inline
    pane. Note: the endpoint returns **400** (not 422) for validation errors —
    handle both statuses and display the error message.
  - **Reset to Factory** → `dcc.ConfirmDialog` (message: "Reset '{name}' to
    factory defaults? All user edits will be lost. This cannot be undone.") →
    `DELETE` → reload the form with system data.

**Verify**:
- `source .venv/bin/activate && mypy src/app/dash_app/pages/library` → exit 0

### Step 8: Sidebar nav + routing in `layout.py`

In `src/app/dash_app/layout.py`:

1. Add a `dbc.NavLink` between the Analytics (line 43) and Connectors (line 44)
   entries: `fas fa-book` icon, "Library" label, `href="/app/library"`,
   `active="exact"`, `id="nav-library"`, same `executive-nav-link` classes.
2. In `display_page(pathname)`, add before the connectors branch:
   - `if pathname in ("/app/library", "/app/library/"): return library.get_layout()`
   - `if pathname and pathname.startswith("/app/library/"): return library.get_editor_layout()`
     (this catches `/app/library/edit/...` and `/app/library/new`).
3. Import the `library` package at the top of `layout.py`.

**Verify**:
- `source .venv/bin/activate && mypy src/app/dash_app/layout.py` → exit 0
- `source .venv/bin/activate && PYTHONPATH=src python -c "from app.dash_app.layout import create_dash_app; print('ok')"` → `ok`

### Step 9: UI callback tests

Create `tests/test_library_callbacks.py` and
`tests/test_library_editor_callbacks.py` (marker `@pytest.mark.unit`). Mock the
HTTP calls (model on `tests/test_graph_callbacks_regression.py`, which asserts
on `post_fake.calls[0]["url"]` and payload). Cover D1–D7 and E1–E6 from the
design doc (see Test plan below). For the "Test" cases (E4, E5), mock
`POST /api/v1/graph/execute` — do not require a live Neo4j.

**Verify**:
- `source .venv/bin/activate && PYTHONPATH=src pytest -m unit tests/test_library_callbacks.py tests/test_library_editor_callbacks.py -q` → all pass

### Step 10: Full regression check

**Verify**:
- `source .venv/bin/activate && PYTHONPATH=src pytest -m unit tests -q` → all pass (no regressions)
- `source .venv/bin/activate && mypy src/app/query_catalog src/app/api/queries src/app/dash_app/pages/library src/app/dash_app/layout.py` → exit 0
- `source .venv/bin/activate && pylint src/app/query_catalog/loader.py src/app/api/queries/v1/user_defined_service.py src/app/api/queries/v1/router.py src/app/dash_app/pages/library` → exit 0

## Test plan

New test files (all `@pytest.mark.unit` unless noted):

- `tests/test_query_catalog_merge.py` — B1 no user dir; B2 empty user dir;
  B3 override existing system query (assert user data + `source_path` contains
  `user_defined/`, system version excluded); B4 new query in existing namespace
  (assert count = system count + 1, **not** a hardcoded 141); B5 new query in
  custom namespace (assert namespace count = system + 1, **not** hardcoded 10);
  B6 multiple overrides across namespaces; B7 duplicate slug in user set →
  `CatalogLoadError`; B10 namespace listing includes custom user ns with correct
  `order`.
- `tests/test_query_catalog_api.py` (extend) — C1 PUT creates user file; C2 PUT
  overwrites; C3 PUT new query; C4 PUT with write Cypher → 422; C5 PUT missing
  required fields → 422; C6 DELETE removes file then GET shows system version;
  C7 DELETE non-existent → 204; C8 GET merged catalog after override; C9 GET
  namespaces includes custom user ns.
- `tests/test_query_catalog_api_integration.py` (extend) — same C-cases against
  the real catalog, with cleanup so `count == 140` stays valid.
- `tests/test_library_callbacks.py` — D1 table renders; D2 namespace filter;
  D3 search filter; D4 Edit fires `window.open` with correct URL; D5 New Query
  fires `window.open` to `/app/library/new`; D6 Reset button only when
  `source_path` contains `user_defined/`; D7 Reset → ConfirmDialog → DELETE →
  success alert.
- `tests/test_library_editor_callbacks.py` — E1 editor loads query; E2 Save →
  PUT; E3 Save As → PUT to new id; E4 Test → POST execute → results pane; E5
  Test with write Cypher → error displayed; E6 Reset → DELETE → form reloads.

Structural pattern: `tests/test_query_catalog_loader.py` for loader tests,
`tests/test_graph_callbacks_regression.py` for callback tests (mock HTTP and
assert on URL + payload).

## Done criteria

Machine-checkable. ALL must hold:

- [ ] `source .venv/bin/activate && PYTHONPATH=src pytest -m unit tests/test_query_catalog_merge.py tests/test_library_callbacks.py tests/test_library_editor_callbacks.py -q` exits 0
- [ ] `source .venv/bin/activate && PYTHONPATH=src pytest -m unit tests -q` exits 0 (no regressions)
- [ ] `source .venv/bin/activate && mypy src/app/query_catalog src/app/api/queries src/app/dash_app/pages/library src/app/dash_app/layout.py` exits 0
- [ ] `source .venv/bin/activate && pylint src/app/query_catalog/loader.py src/app/api/queries/v1/user_defined_service.py src/app/api/queries/v1/router.py src/app/dash_app/pages/library` exits 0
- [ ] `grep -rn "user_defined" src/app/query_catalog/loader.py` returns matches (merge logic present)
- [ ] `grep -rn "def save_query\|def delete_query" src/app/api/queries/v1/user_defined_service.py` returns matches
- [ ] `grep -rn "nav-library\|/app/library" src/app/dash_app/layout.py` returns matches
- [ ] `grep -rn "CatalogQueryWrite" src/app/query_catalog/__init__.py` returns matches (exported)
- [ ] `grep -rn "queries_catalog/user_defined" .gitignore` returns matches (gitignored)
- [ ] No files outside the in-scope list are modified (`git status`)
- [ ] `plans/README.md` status row for 021 updated

## STOP conditions

Stop and report back (do not improvise) if:

- The code at the locations in "Current state" doesn't match the excerpts
  (the codebase has drifted since this plan was written).
- A step's verification fails twice after a reasonable fix attempt.
- The fix appears to require touching an out-of-scope file (especially
  `service.py`, `query.py`, or `src/app/api/graph/v1/*`).
- You discover the assumption that reads funnel through `load_catalog()` is
  false (i.e. some consumer reads the catalog another way).
- The `user_defined/` directory already exists in `queries_catalog/` with
  content — reconcile with the merge logic before proceeding.

## Maintenance notes

- The merge in `loader.py` is the single source of truth for user overrides.
  Any future consumer that reads the catalog gets user edits for free — but any
  consumer that reads YAML files directly (bypassing `load_catalog()`) will
  NOT. Watch for that in review.
- The hardcoded `count == 140` assertions in
  `test_catalog_list_endpoint_returns_normalized_catalog` and
  `test_load_catalog_normalizes_all_existing_entries` will break if a
  `user_defined/` override exists at test time. The integration tests must
  clean up after themselves; the unit test uses `tmp_path` so it is safe.
- The editor "Test" button depends on live Neo4j at runtime. If Neo4j is down,
  the button surfaces a 400/500 — the UI should show a clear error, not crash.
- `save_query` writes files synchronously. If concurrency is ever added to the
  API, the last-write-wins filesystem behavior (edge case EC4) must be
  revisited — consider a lock or optimistic concurrency check.
- Deleting the last query in a custom namespace leaves an orphaned namespace
  entry in `user_defined/catalog.yaml`. This is harmless (zero queries at load
  time) but may accumulate over time. A future cleanup task could prune empty
  user namespaces.
- A reviewer should scrutinize: the PUT body model (must not reuse
  `CatalogQuery`), the `source_path` convention for user files, and that the
  editor's pathname parsing handles both `/app/library/edit/{ns}/{slug}` and
  `/app/library/new`.
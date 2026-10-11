# Plan 023: Catalog Editor — Quick Test & View Test Buttons

> **Executor instructions**: Follow this plan phase by phase. Run every
> verification command and confirm the expected result before moving to the
> next phase. Mark each task `[x]` as you complete it and update the progress
> tracker table at the bottom. If anything in the "STOP conditions" section
> occurs, stop and report — do not improvise. When done, update the status row
> for this plan in `plans/README.md` — unless a reviewer dispatched you and
> told you they maintain the index.
>
> **Drift check (run first)**:
> ```
> git diff --stat a7ce365..HEAD -- \
>   src/app/dash_app/pages/catalog/editor_layout.py \
>   src/app/dash_app/pages/catalog/editor_callbacks.py \
>   src/app/dash_app/pages/catalog/__init__.py \
>   src/app/dash_app/pages/graph/layout.py \
>   src/app/dash_app/components/ \
>   tests/test_catalog_editor_callbacks.py \
>   docs/design/query-catalog-editor-design.md
> ```
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts below against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: MED
- **Depends on**: none
- **Category**: dx
- **Planned at**: commit `a7ce365`, 2026-10-11

## Why this matters

The query editor's only way to test a query today is one "Test Tabular" / "Test
Graph" button per column that renders into a **single shared pane**,
`#editor-test-results`, placed below the parameters section — so it is off-screen
while you are editing the query, and both columns contend for the same output
(`editor_layout.py:279-286`, `299-306`, `508-516`). Worse, `_run_test` can only
ever return a table or a message (`editor_callbacks.py:767-775`), so a graph
query's result is shown as a table — there is no way to *see* the graph you just
wrote.

After this plan each column has its own **Quick Test** (a compact inline badge,
`✔ N rows` / `✘ error`, right under the textarea it belongs to) and **View Test**
(an `xl` modal that draws the real `cyto.Cytoscape` graph or the data table using
the graph page's own renderers). The shared bottom pane is removed entirely.

## Current state

The facts you need, inlined.

**`src/app/dash_app/pages/catalog/editor_layout.py`** (608 lines) — builds the
editor form. `get_editor_layout()` is at line 74; it calls `_render_test_results()`
at line 98. Inside `_render_queries_section()` (lines 256-347):

```python
# lines 279-286 — tabular column
dbc.Button(
    "Test Tabular",
    id="editor-test-tabular",
    color="secondary", outline=True, size="sm",
    className="btn-subtle-action mt-2",
),
# lines 299-306 — graph column
dbc.Button(
    "Test Graph",
    id="editor-test-graph",
    color="secondary", outline=True, size="sm",
    className="btn-subtle-action mt-2",
),
```

```python
# lines 508-516 — the section to delete
def _render_test_results() -> html.Div:
    """Inline pane for Test Tabular / Test Graph results."""
    return html.Div(
        [
            html.H6("Test Results", className="mt-3"),
            html.Div(id="editor-test-results"),
        ],
        style={"fontFamily": FONT_SANS, "fontSize": FONT_SIZE_SMALL},
    )
```

The file already imports `dcc`, `html` (line 5) and `dbc` (line 6), and defines
`_render_save_as_modal()` / `_render_factory_diff_modal()` (both `dbc.Modal`,
lines 434-505) as the modal pattern to copy.

**`src/app/dash_app/pages/catalog/editor_callbacks.py`** (1043 lines) — imports
`create_error_alert, create_table_display` from `app.dash_app.pages.graph.utils`
at lines 24-27, and `get_api_base_url` from `._utils` at line 29;
`TIMEOUT_SECONDS = runtime_settings.get_int("HTTP_REQUEST_TIMEOUT")` at line 32.

```python
# lines 732-777
def _run_test(query_text: str | None) -> Any:
    """Execute a raw Cypher query and render the results pane."""
    if not query_text or not query_text.strip():
        return create_alert("Enter a query before testing.", ...)
    payload = {"source": "raw", "query": query_text.strip(), "view": "auto"}
    api_base = get_api_base_url()
    try:
        resp = requests.post(f"{api_base}/api/v1/graph/execute", json=payload,
                             timeout=TIMEOUT_SECONDS)
        if resp.status_code not in (200, 400, 422, 500):
            resp.raise_for_status()
        if resp.status_code != 200:
            error_data = resp.json()
            return create_error_alert(error_data.get("detail", {}).get("message", ...), ...)
        data = resp.json()
        if data.get("isGraph"):
            return create_alert(f"Graph result: {data.get('resultCount', 0)} records.", ...)
        return create_table_display(data.get("rawResults") or [])
    except requests.exceptions.RequestException as exc:
        return create_alert(f"Test failed: {exc}", ...)

# lines 780-790 → writes to Output("editor-test-results", "children")
def test_tabular(n_clicks, query_text): ...
# lines 793-803 → same Output with allow_duplicate=True
def test_graph(n_clicks, query_text): ...
```

**`src/app/dash_app/pages/graph/layout.py`** (685 lines) — the three builders to
move live at lines 46-114 and are called only at lines 525-527:

```python
# lines 46-71
def create_graph_container() -> html.Div:
    return html.Div(
        id="graph-cytoscape-container",
        style={"display": "none"},
        children=[
            cyto.Cytoscape(
                id="graph-cytoscape", elements=[],
                layout={'name': 'circle', 'animate': True},
                style=GRAPH_CYTOSCAPE_STYLE, stylesheet=CYTOSCAPE_STYLESHEET,
                userZoomingEnabled=True, userPanningEnabled=True,
                wheelSensitivity=0.3, minZoom=0.05, maxZoom=3,
            )
        ],
    )

# lines 74-83
def create_table_container() -> html.Div:
    return html.Div(id="graph-table-container", style={"display": "none"})

# lines 86-114
def create_empty_state() -> html.Div:
    return html.Div(
        id="graph-results-container",
        style={"minHeight": "calc(75vh)", "padding": "16px"},
        children=[html.Div([
            html.Div("◆", style=GRAPH_EMPTY_STATE_ICON_STYLE),
            html.P("No results to display. Execute a query to visualize network relationships.",
                   style=GRAPH_EMPTY_STATE_TEXT_STYLE),
        ], className="text-center", style={"marginTop": "80px"})],
    )
```

Nothing outside `graph/layout.py` imports these three functions (verified — the
only other `create_empty_state` in the tree is the unrelated one below).

**`src/app/dash_app/components/common.py:246`** already defines
`create_empty_state(message: str, icon: str = "📭") -> html.Div` — a *different*
function. Do not touch it (see Scope).

**API response fields** for `POST /api/v1/graph/execute`
(`src/app/api/graph/v1/model.py:115-150`): `isGraph: bool`, `nodes: list`,
`relationships: list`, `rawResults: list`, `resultCount: int | None`. For a
graph query `resultCount == len(nodes' source records)`; for a tabular query
`rawResults` holds the rows and `resultCount == len(rawResults)`.

### Conventions to follow

- **Tests are flat modules in `tests/`**, marked with a module-level
  `pytestmark = pytest.mark.unit`, and they call the module's functions directly
  (no Dash app boot). Two exact precedents:
  - `tests/test_shared_graph_components.py` — walks a component tree to assert
    ids (the model for the `result_pane` tests).
  - `tests/test_graph_layout_phase4.py` — renders a layout and walks it (the
    model for the editor-layout tests).
- To stub a callback context in a unit test, the repo uses a tiny class:
  ```python
  class _FakeContext:
      triggered = True
      triggered_id = "editor-quick-test-tabular"
  monkeypatch.setattr(<module>, "ctx", _FakeContext())
  ```
  (live example: `tests/test_catalog_editor_callbacks.py:378-382`, which stubs
  `callback_context` the same way).
- **To test the `RequestException` path, patch the *attribute*, never the whole
  module.** `_run_test` ends with `except requests.exceptions.RequestException
  as exc:` (copied verbatim from `editor_callbacks.py:776`). If you replace the
  module global with a fake — `monkeypatch.setattr(editor_test_callbacks,
  "requests", fake)` — then when the fake raises, Python evaluates
  `requests.exceptions.RequestException` against the *fake*, and a fake without
  an `exceptions` attribute (like the `_FakeRequests` at
  `tests/test_catalog_editor_callbacks.py:42-70`) produces `AttributeError`
  instead of the expected error badge. Instead do:
  ```python
  import requests as requests_lib

  def _failing_post(url, json, timeout):
      raise requests_lib.exceptions.ConnectionError("Connection refused")

  monkeypatch.setattr(editor_test_callbacks.requests, "post", _failing_post)
  ```
  This is the repo's established pattern — see
  `tests/test_catalog_editor_callbacks.py:791-807`
  (`test_e1d_load_query_request_exception_shows_error`), whose docstring
  explains exactly this trap. The wholesale replacement form is *only* safe for
  tests that never trigger the `except` clause (it is fine for the migrated
  E4–E7, none of which raise).
- Style constants come from `app/dash_app/styles.py`; buttons use the shared
  `btn-subtle-action` class (see `editor_layout.py:285`). Add no new CSS.
- Every new function needs full type annotations — `mypy src/` runs **strict**
  (`disallow_untyped_defs`, `disallow_untyped_calls`); only
  `return-value, index, union-attr` are relaxed for `app.dash_app.*`.

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Backing services (manual checks only) | `docker compose up -d postgres neo4j rabbitmq` | exit 0 |
| Unit tests — **the gate CI runs** | `pytest -m unit tests -q` | all pass |
| One module | `pytest -m unit tests/test_result_pane.py -q` | all pass |
| Ad-hoc import check | `PYTHONPATH=src python - <<'EOF' …` | prints `All IDs OK` |
| Typecheck (CI gate) | `mypy src/` | exit 0, no errors |
| Lint (CI gate, ≥ 9.0) | `pylint src --score=y` | score ≥ 9.0 |
| Security scan (CI gate) | `bandit -c .bandit.yml -r src/ -lll` | no High severity |

Do **not** run bare `pytest tests/` — 22 modules under `tests/` are marked
`integration`/`neo4j`/`rabbitmq`/`elasticsearch`/`server` and need live services
(e.g. `tests/test_graph_query_integration.py:13`). `PYTHONPATH=src` is required
for ad-hoc commands that import app code (`pytest.ini` sets it for pytest only).

## Scope

**In scope** (the only files you may create or modify):

- `src/app/dash_app/components/result_pane.py` (create)
- `src/app/dash_app/pages/catalog/editor_test_callbacks.py` (create)
- `src/app/dash_app/pages/catalog/editor_layout.py`
- `src/app/dash_app/pages/catalog/editor_callbacks.py`
- `src/app/dash_app/pages/catalog/__init__.py`
- `src/app/dash_app/pages/graph/layout.py` (import the moved builders; ids unchanged)
- `tests/test_result_pane.py` (create)
- `tests/test_catalog_editor_layout.py` (create)
- `tests/test_catalog_editor_test_callbacks.py` (create)
- `tests/test_catalog_editor_callbacks.py` (modify — migrate E4–E7 only)
- `docs/design/query-catalog-editor-design.md` (update the two passages that
  describe the removed Test buttons — see Phase 5)

**Out of scope** (do NOT touch, even though they look related):

- `src/app/dash_app/pages/graph/callbacks/**` — Phase 1 is a **pure move**. Every
  `graph-*` component id must stay byte-identical, and no graph callback may be
  edited. (**As executed:** the operator-approved stylesheet move repointed one
  import line in `callbacks/display.py`; nothing else in that tree changed.)
- `src/app/dash_app/components/common.py` — it already has an unrelated
  `create_empty_state(message, icon)` at line 246; do not modify, rename, or
  reuse it.
- `src/app/api/graph/v1/**` — the execute endpoint is consumed unchanged.
- `src/app/dash_app/assets/executive-dashboard.css` — reuse the existing
  `btn-subtle-action` class; add no CSS.
- `plans/021-query-catalog-editor.md` — a completed historical plan that also
  names the old `Test Tabular` / `Test Graph` buttons. It is a record of past
  work, not live documentation; do **not** edit it.
- Any component id beginning with `graph-` is frozen.

## Git workflow

- Branch: `advisor/023-catalog-editor-test-buttons`
- Do **not** commit, push, or open a PR unless the operator instructs it. If
  instructed, use plain imperative commit subjects matching repo style, e.g.
  `Catalog editor quick/view test buttons`.
- Update the 023 row in `plans/README.md` when done — unless the dispatcher said
  they maintain the index.

## Decisions log

| Decision | Agreed answer |
|---|---|
| UX model | Two buttons per column: **Quick Test** (inline badge) + **View Test** (modal) |
| Inline feedback | `dbc.Alert` (small, dismissible) immediately below each textarea |
| Modal | One shared `xl` modal; title reflects which query type was tested |
| Graph in modal | Same stylesheet/theme as the graph page; wheel-zoom + drag-pan (already enabled by the container); a single **Fit** button. No filter or details panel |
| Shared components | Extract 3 builders into `app/dash_app/components/result_pane.py`, named `create_graph_result_container` / `create_table_result_container` / `create_results_empty_state` (the `*_container` names avoid colliding with `components/common.py`'s `create_empty_state`) |
| New callbacks location | `src/app/dash_app/pages/catalog/editor_test_callbacks.py` |
| API endpoint | Same `POST /api/v1/graph/execute` as the graph page |
| `_run_test` | Moved to `editor_test_callbacks.py`; refactored to return a raw `dict` |
| Old code removed | `_render_test_results()`, `#editor-test-results`, both old callbacks, and the two now-unused graph-utils imports |
| Test coverage | `result_pane` builders + `_run_test` mock + `quick_test` + `view_test` callbacks; existing E4–E7 tests migrated |

## STOP conditions

Stop and report (do not improvise) if:

- After Phase 3, **more** tests fail than the four E4–E7 tests in
  `tests/test_catalog_editor_callbacks.py` that this plan migrates — the
  deletions were broader than intended.
- The graph page (`/app/graph`) fails to render after Phase 1, or any `graph-*`
  component id changed.
- `grep -rn 'editor-test-results"' src/` still returns results after Phase 5.
- A step's verification fails twice after a reasonable fix attempt.
- A step appears to require touching an out-of-scope file.

---

## Phase 1 — Extract shared result-pane builders

> **Goal:** Create `result_pane.py` with the three builders and update
> `graph/layout.py` to use them. **Zero functional change** — the graph page must
> behave identically after this phase, with every id unchanged.

### ✅ Executed 2026-10-11 — with one approved deviation

Implemented on `feature/editor-test-buttons` (committed by the operator as
`bf0a851`, with the plan-doc updates in `44ac24c`). All Phase 1 done
criteria pass: `pytest -m unit tests -q` → 1820 passed; `mypy src/` clean;
`pylint src` 9.68/10; `bandit … -lll` exit 0; the rendered `graph-*` id set is
**byte-identical** to `a7ce365` (24 ids, compared against `git archive a7ce365`).
**Operator-verified manually 2026-10-11** — graph page empty state, graph and
tabular queries against live Neo4j, graph interactions, theme round-trip, and
the collaboration-network page all behaved unchanged.

**Deviation (operator-approved):** the plan's claim that `pages.graph.styles` is
"a leaf module" was **wrong**. Importing *any* submodule of `pages.graph` runs
`pages/graph/__init__.py`, which does `from .layout import get_layout` — so
`result_pane → pages.graph.styles → pages.graph.__init__ → layout → result_pane`
is a genuine circular import (reproduced in a fresh interpreter). The first
execution worked around it with a function-local import in `layout.py`; the
operator rejected that. Instead, `src/app/dash_app/pages/graph/styles.py` was
**moved** to `src/app/dash_app/graph_styles.py` (body byte-identical; docstring
extended) and its seven importers were repointed. `layout.py` therefore takes a
plain **module-level** import of `result_pane` — no lazy import anywhere.

The move also fixes a pre-existing misplacement: that stylesheet module was
already consumed by the graph page, the collaboration-network page, and now the
shared result pane, yet lived inside one page's package. It sits next to the
design-token module (`app/dash_app/styles.py`) by operator choice, **not** in
`components/` as this plan's maintenance note originally suggested.

This expands the plan's file scope; see the File change summary for the exact
list. `pages/graph/callbacks/**` was otherwise untouched: the only change there
is one repointed import line in `callbacks/display.py`.

### Tasks

- [x] Create `src/app/dash_app/components/result_pane.py`:

  ```python
  """Shared graph/table result-pane builders.

  Used by the graph page and the catalog editor's View Test modal. The module is
  graph-page-flavoured (it needs that page's Cytoscape stylesheet) but lives in
  the shared components package because two pages use it.
  """

  from dash import html
  import dash_cytoscape as cyto

  from app.dash_app.pages.graph.styles import CYTOSCAPE_STYLESHEET
  from app.dash_app.styles import (
      GRAPH_CYTOSCAPE_STYLE,
      GRAPH_EMPTY_STATE_ICON_STYLE,
      GRAPH_EMPTY_STATE_TEXT_STYLE,
  )
  ```

  Copy the three function bodies from `graph/layout.py:46-114` **verbatim**,
  replacing only the hard-coded ids with `f`-strings built from a new
  `id_prefix: str = "graph"` parameter:

  - `def create_graph_result_container(id_prefix: str = "graph") -> html.Div:`
    — outer id `f"{id_prefix}-cytoscape-container"`, inner `cyto.Cytoscape` id
    `f"{id_prefix}-cytoscape"`. Every Cytoscape prop (`layout`, `style`,
    `stylesheet`, `userZoomingEnabled`, `userPanningEnabled`, `wheelSensitivity`,
    `minZoom`, `maxZoom`) and the outer `style={"display": "none"}` stay
    identical.
  - `def create_table_result_container(id_prefix: str = "graph") -> html.Div:`
    — id `f"{id_prefix}-table-container"`, `style={"display": "none"}`.
  - `def create_results_empty_state(id_prefix: str = "graph") -> html.Div:`
    — id `f"{id_prefix}-results-container"`, same style and children.

- [x] Update `src/app/dash_app/pages/graph/layout.py`:
  - Add `from app.dash_app.components.result_pane import (create_graph_result_container, create_table_result_container, create_results_empty_state)`.
  - Delete the three local definitions (lines 46-114) and change the call sites
    at lines 525-527 to the new names, each with `id_prefix="graph"`.
  - **Remove the now-unused imports** (verified: each has exactly one use in this
    file, all inside the moved bodies, so all five would trip pylint `W0611`):
    - `import dash_cytoscape as cyto` (line 9)
    - `CYTOSCAPE_STYLESHEET` from `.styles` (line 11)
    - `GRAPH_CYTOSCAPE_STYLE`, `GRAPH_EMPTY_STATE_ICON_STYLE`,
      `GRAPH_EMPTY_STATE_TEXT_STYLE` from `app.dash_app.styles` (lines 28-30)
    - Leave every other `GRAPH_*` / `FONT_*` / `COLOR_*` import alone.

### Tests to add (Phase 1)

New file `tests/test_result_pane.py`, modeled on `tests/test_shared_graph_components.py`
(module-level `pytestmark = pytest.mark.unit`; walk the component tree):

- `test_create_graph_result_container_default_ids` — returned `html.Div` has
  `id="graph-cytoscape-container"` and contains a child with `id="graph-cytoscape"`.
- `test_create_table_result_container_default_id` — `id="graph-table-container"`.
- `test_create_results_empty_state_default_id` — `id="graph-results-container"`.
- `test_id_prefix_applied` — call each with `id_prefix="editor-test"` and assert
  the ids carry that prefix.

### Verification (Phase 1)

```bash
pytest -m unit tests/test_result_pane.py -q          # all pass
pytest -m unit tests -q                              # no new failures

grep -n "def create_graph_container\|def create_table_container\|def create_empty_state" \
  src/app/dash_app/pages/graph/layout.py
# Expected: no output

mypy src/ && pylint src --score=y
# Expected: mypy exit 0; pylint score >= 9.0
```

---

## Phase 2 — Update editor layout (buttons + modal shell)

> **Goal:** Swap in the four-button layout, add the two inline feedback divs and
> the shared modal shell, and delete the old test-results section. No callbacks
> are wired yet — the buttons are inert.

### ✅ Executed 2026-10-11

Two files: `editor_layout.py` modified, `tests/test_catalog_editor_layout.py`
created (7 tests, all exact-id tree walks). Verified: 1827 unit tests pass
(+7), mypy clean, pylint 9.68, the 14 required ids all present by independent
tree walk, `editor-test-results` and both old buttons absent, and
`import app.main` + `create_dash_app()` still succeed with the old callbacks
dangling (safe because `suppress_callback_exceptions=True`). `editor_callbacks.py`
is untouched, as the phase boundary requires. **Operator-verified manually
2026-10-11** — button pairs render as expected, the old bottom results pane is
gone, all four buttons are inert with a clean console, and Save / Save As /
Compare to Factory / Add Parameter still work.

### Tasks

- [x] Edit `src/app/dash_app/pages/catalog/editor_layout.py`.

  **In `_render_queries_section()`**, replace the "Test Tabular" block
  (lines 279-286) with:

  ```python
  html.Div([
      dbc.Button("Quick Test", id="editor-quick-test-tabular",
                 color="secondary", outline=True, size="sm",
                 className="btn-subtle-action me-1 mt-2"),
      dbc.Button("View Test", id="editor-view-test-tabular",
                 color="secondary", outline=True, size="sm",
                 className="btn-subtle-action mt-2"),
  ], className="d-flex"),
  html.Div(id="editor-quick-test-tabular-feedback", className="mt-1"),
  ```

  and replace the "Test Graph" block (lines 299-306) with the same shape using
  `editor-quick-test-graph` / `editor-view-test-graph` /
  `editor-quick-test-graph-feedback`.

  **Delete** the `_render_test_results()` function (lines 508-516) and its call
  in `get_editor_layout()` (line 98).

- [x] Add `_render_test_results_modal()` to `editor_layout.py`, and call it from
  `get_editor_layout()` right after `_render_factory_diff_modal()` (line 97).
  Use a module-level import of the Phase 1 builders (no import cycle — verified):

  ```python
  def _render_test_results_modal() -> dbc.Modal:
      """Shared xl modal for View Test results (tabular and graph)."""
      return dbc.Modal(
          [
              dbc.ModalHeader(dbc.ModalTitle("", id="editor-test-modal-title")),
              dbc.ModalBody(
                  dcc.Loading(
                      type="circle",
                      children=[
                          html.Div(
                              dbc.Button("Fit", id="editor-test-fit",
                                         color="secondary", outline=True, size="sm",
                                         className="btn-subtle-action mb-2"),
                              className="d-flex justify-content-end",
                          ),
                          create_graph_result_container(id_prefix="editor-test"),
                          create_table_result_container(id_prefix="editor-test"),
                          create_results_empty_state(id_prefix="editor-test"),
                      ],
                  )
              ),
              dbc.ModalFooter(
                  dbc.Button("Close", id="editor-test-modal-close",
                             color="secondary", size="sm")
              ),
          ],
          id="editor-test-modal",
          size="xl",
          scrollable=True,
          is_open=False,
      )
  ```

  Add `from app.dash_app.components.result_pane import (create_graph_result_container, create_results_empty_state, create_table_result_container)` to the module's imports.

- [x] **Do not** add any `dcc.Store` — no callback in this plan needs one.

### Tests to add (Phase 2)

New file `tests/test_catalog_editor_layout.py`, modeled on
`tests/test_graph_layout_phase4.py` (render `get_editor_layout()` and walk the
component tree), with `pytestmark = pytest.mark.unit`.

Write one module-level helper and use it in every test — **do not**
substring-match `str(get_editor_layout())`. Dash renders ids with **single**
quotes (`Textarea(id='editor-query-tabular')`), so any `'id="…"'` check on the
rendered string is always true and proves nothing. Walk the tree for exact ids,
copying `tests/test_graph_layout_phase4.py:13-28`:

```python
def _collect_ids() -> set[str]:
    """Every component id in the rendered editor layout (exact, unquoted)."""
    ids: set[str] = set()

    def walk(component) -> None:
        if component is None:
            return
        component_id = getattr(component, "id", None)
        if component_id is not None:
            ids.add(str(component_id))
        children = getattr(component, "children", None)
        if isinstance(children, (list, tuple)):
            for child in children:
                walk(child)
        elif children is not None:
            walk(children)

    walk(get_editor_layout())
    return ids
```

- `test_quick_test_tabular_button_present` — `"editor-quick-test-tabular"` in ids
- `test_quick_test_graph_button_present` — `"editor-quick-test-graph"` in ids
- `test_view_test_tabular_button_present` — `"editor-view-test-tabular"` in ids
- `test_view_test_graph_button_present` — `"editor-view-test-graph"` in ids
- `test_inline_feedback_divs_present` — both `editor-quick-test-{tabular,graph}-feedback` in ids
- `test_test_modal_present` — `"editor-test-modal"` in ids
- `test_old_test_results_div_gone` — `assert "editor-test-results" not in _collect_ids()`.
  Because the check is on the **exact** id, the new
  `editor-test-results-container` (a different id) does not collide — no quote
  anchor is needed or wanted.

### Verification (Phase 2)

```bash
pytest -m unit tests/test_catalog_editor_layout.py -q

PYTHONPATH=src python - <<'EOF'
from app.dash_app.pages.catalog.editor_layout import get_editor_layout

ids = set()

def walk(component):
    if component is None:
        return
    cid = getattr(component, "id", None)
    if cid is not None:
        ids.add(str(cid))
    children = getattr(component, "children", None)
    if isinstance(children, (list, tuple)):
        for child in children:
            walk(child)
    elif children is not None:
        walk(children)

walk(get_editor_layout())
required = [
    "editor-quick-test-tabular", "editor-view-test-tabular",
    "editor-quick-test-graph",   "editor-view-test-graph",
    "editor-quick-test-tabular-feedback",
    "editor-quick-test-graph-feedback",
    "editor-test-modal", "editor-test-modal-title",
    "editor-test-modal-close", "editor-test-fit",
    "editor-test-cytoscape-container", "editor-test-cytoscape",
    "editor-test-table-container", "editor-test-results-container",
]
for id_ in required:
    assert id_ in ids, f"MISSING: {id_}"
assert "editor-test-results" not in ids, "OLD ID STILL PRESENT"
print("All IDs OK")
EOF
```

Expected: `All IDs OK`; all tests pass. (Collect **exact** ids by walking the
tree — `str(get_editor_layout())` renders ids with single quotes, so a
`'id="editor-test-results"'` string check is always true and would not catch the
old pane.)

---

## Phase 3 — Wire Quick Test callbacks

> **Goal:** Both Quick Test buttons call the API and render an inline badge.
> Delete the old `_run_test`, `test_tabular`, and `test_graph` from
> `editor_callbacks.py` and migrate the tests that call them.

### ✅ Executed 2026-10-11

Five files: `editor_test_callbacks.py` + `tests/test_catalog_editor_test_callbacks.py`
created; `editor_callbacks.py` (−78 lines), `catalog/__init__.py`, and the
E4–E7 block of `tests/test_catalog_editor_callbacks.py` modified. Verified: 1831
unit tests pass (+4 net), mypy clean (277 files), pylint 9.68, no
`editor-test-results` / `_run_test` / `test_tabular` / `test_graph` /
`create_error_alert` / `create_table_display` left in `editor_callbacks.py`, and
`import app.main` + `create_dash_app()` still succeed.

The E5 migration asserts on **`result[1]`**, per the correction above — the
graph trigger returns `(no_update, badge)`. The raised-exception test patches
`editor_test_callbacks.requests.post` (the attribute), not the module, so the
source's `except requests.exceptions.RequestException` resolves against the real
`requests`; the four migrated E4–E7 tests keep the whole-module fake, which is
safe only because none of them raises inside `_run_test`.

**Follow-up fix (operator-reported, 2026-10-11):** the first cut's `_BADGE_STYLE`
inline padding (`3px 8px` at 11px) shrank the alert to ~22px while Bootstrap's
`.alert-dismissible .btn-close` keeps its box anchored at the alert's **top**
with `padding: 1.25rem 1rem` (~51px tall) — so the × rendered *below* the badge.
Fixed by dropping the inline style and adding a shared unscoped
`.alert-inline-badge` class to `assets/executive-dashboard.css` that re-anchors
the close button to the alert's vertical centre (`top: 50%` +
`translateY(-50%)`) and reserves `22px` of right padding for it. **This amends
this plan's earlier "add no new CSS" instruction** — the badge class follows the
same pattern as `btn-subtle-action` / `collapse-toggle-subtle`. Note the defect
was specific to this badge: no other `create_alert(...)` caller overrides
padding.

### Tasks

- [x] Create `src/app/dash_app/pages/catalog/editor_test_callbacks.py` with a
  complete import block:

  ```python
  """Callbacks for the catalog editor's Quick Test / View Test buttons."""

  from __future__ import annotations

  from typing import Any

  import requests
  import dash_bootstrap_components as dbc
  from dash import Input, Output, State, callback, ctx, no_update

  from app.runtime_settings import runtime_settings
  from ._utils import get_api_base_url

  TIMEOUT_SECONDS = runtime_settings.get_int("HTTP_REQUEST_TIMEOUT")
  ```

  **`_run_test`** — moved here from `editor_callbacks.py` and refactored to return
  a raw `dict` instead of rendered components:

  ```python
  def _run_test(query_text: str | None) -> dict[str, Any]:
      """Execute a raw Cypher query and return the raw API response.

      Returns a dict with keys:
        - "ok":    bool
        - "data":  dict | None  (full API JSON on success)
        - "error": str  | None  (user-facing message on failure)
      """
      if not query_text or not query_text.strip():
          return {"ok": False, "data": None,
                  "error": "Enter a query before testing."}
      payload = {"source": "raw", "query": query_text.strip(), "view": "auto"}
      api_base = get_api_base_url()
      try:
          resp = requests.post(
              f"{api_base}/api/v1/graph/execute",
              json=payload, timeout=TIMEOUT_SECONDS,
          )
          if resp.status_code != 200:
              try:
                  detail = resp.json().get("detail", {})
                  msg = (detail.get("message", "Query execution failed.")
                         if isinstance(detail, dict) else str(detail))
              except ValueError:
                  msg = "Query execution failed."
              return {"ok": False, "data": None, "error": msg}
          return {"ok": True, "data": resp.json(), "error": None}
      except requests.exceptions.RequestException as exc:
          return {"ok": False, "data": None, "error": str(exc)}
  ```

  **`quick_test`** — one callback serving both buttons:

  ```python
  _BADGE_STYLE = {"fontSize": "11px", "padding": "3px 8px", "marginBottom": "0"}


  @callback(
      Output("editor-quick-test-tabular-feedback", "children"),
      Output("editor-quick-test-graph-feedback",   "children"),
      Input("editor-quick-test-tabular", "n_clicks"),
      Input("editor-quick-test-graph",   "n_clicks"),
      State("editor-query-tabular", "value"),
      State("editor-query-graph",   "value"),
      prevent_initial_call=True,
  )
  def quick_test(
      tab_clicks: int | None,
      graph_clicks: int | None,
      tab_query: str | None,
      graph_query: str | None,
  ) -> tuple[Any, Any]:
      """Render an inline result badge for whichever Quick Test button fired."""
      triggered = ctx.triggered_id
      query = tab_query if triggered == "editor-quick-test-tabular" else graph_query
      result = _run_test(query)

      if result["ok"]:
          data = result["data"]
          if data.get("isGraph"):
              n, r = len(data.get("nodes", [])), len(data.get("relationships", []))
              badge = dbc.Alert(f"✔ Graph: {n} nodes, {r} relationships",
                                color="success", dismissable=True, style=_BADGE_STYLE)
          else:
              count = data.get("resultCount", 0)
              badge = dbc.Alert(f"✔ {count} row(s) returned",
                                color="success", dismissable=True, style=_BADGE_STYLE)
      else:
          badge = dbc.Alert(f"✘ {result['error']}",
                            color="danger", dismissable=True, style=_BADGE_STYLE)

      if triggered == "editor-quick-test-tabular":
          return badge, no_update
      return no_update, badge
  ```

- [x] Delete from `editor_callbacks.py`:
  - `_run_test` (lines 732-777), `test_tabular` (lines 780-790), `test_graph`
    (lines 793-803).
  - The now-unused imports at lines 24-27: **both** `create_error_alert` (used
    only at line 762) and `create_table_display` (used only at line 775). If that
    empties the multi-line import statement, delete the statement.
  - Keep `create_alert`, `COLOR_GRAY_MEDIUM`, `get_api_base_url`,
    `TIMEOUT_SECONDS`, and everything else.

- [x] Migrate the four tests that call the deleted functions —
  `tests/test_catalog_editor_callbacks.py`, section "E4/E5: Test Tabular / Test
  Graph" (lines 564-625). They are the only pin on the request payload, the
  write-Cypher 400 path, and the empty-query path, so **rewrite** rather than
  delete. Three mechanical changes are easy to miss:

  1. **Import the new module.** The file currently aliases only the old one
     (`tests/test_catalog_editor_callbacks.py:12`). Add, next to it:
     ```python
     from app.dash_app.pages.catalog import editor_test_callbacks
     ```
  2. **Retarget the fake HTTP layer.** `_run_test` now lives in
     `editor_test_callbacks`, so its `requests.post` resolves in *that* module.
     Every migrated test must patch the new module, not the old one:
     `monkeypatch.setattr(editor_test_callbacks, "requests", fake)` (replacing the
     existing `monkeypatch.setattr(editor, "requests", fake)`, e.g. line 572). If
     you leave it patching `editor`, the test issues a **real** POST to
     `http://localhost:8000` and the assertions fail for the wrong reason.
     The wholesale replacement is safe **for E4–E7 only** because none of them
     raises inside `_run_test`, so the `except requests.exceptions.RequestException`
     clause is never evaluated. Any test that *does* raise must patch
     `editor_test_callbacks.requests.post` instead — see the `RequestException`
     bullet under "Conventions to follow".
  3. **Index the returned tuple.** `quick_test` returns `(badge, no_update)`, so
     assert on `result[0]`.

  Rewrites:
  - `test_e4_test_tabular_posts_execute` (line 567) → call
    `editor_test_callbacks.quick_test(1, None, "MATCH (n) RETURN n LIMIT 10", None)`
    with `monkeypatch.setattr(editor_test_callbacks, "ctx", <ctx with triggered_id="editor-quick-test-tabular">)`;
    keep the `/api/v1/graph/execute` URL and payload assertions; assert the
    returned tabular badge (`result[0]`) contains `✔`. (E4's fake response is
    `{"isGraph": False, "rawResults": [{"n": 1}]}`, so the badge reads
    `✔ 0 row(s) returned`.)
  - `test_e5_test_graph_posts_execute` (line 585) → same, `triggered_id="editor-quick-test-graph"`,
    assert **`result[1]`** contains `✔ Graph:` (and `result[0] is no_update`).
    **Correction:** an earlier revision of this plan said `result[0]` — that was
    wrong. `quick_test` returns `(badge, no_update)` for a *tabular* trigger and
    `(no_update, badge)` for a *graph* trigger, so the graph badge is output
    index 1. (E5's fake is `{"isGraph": True, "resultCount": 3}` — no `nodes`,
    so the badge reads `✔ Graph: 0 nodes, 0 relationships`; the `"✔ Graph:"`
    prefix still holds.)
  - `test_e6_test_with_write_cypher_shows_error` (line 599) → assert the badge
    contains `✘` and `"write operations"`.
  - `test_e7_test_button_disabled_when_empty` (line 617) → assert no HTTP call
    and the badge contains `Enter a query`.
  - The rest of the file must keep passing unchanged.

- [x] Register the new module in `src/app/dash_app/pages/catalog/__init__.py`:

  ```python
  from . import editor_test_callbacks  # noqa: F401
  ```

### Tests to add (Phase 3)

New file `tests/test_catalog_editor_test_callbacks.py` (module-level
`pytestmark = pytest.mark.unit`), covering `_run_test` and `quick_test` in
isolation (the E4–E7 assertions live in the migrated file above):

- tabular 200 → tabular feedback contains `✔` and the row count; graph feedback
  is `no_update`.
- graph 200 → graph feedback contains `✔ Graph:` with node/rel counts; tabular
  feedback is `no_update`.
- HTTP 400 → the triggered feedback contains `✘`.
- `requests.post` raising → feedback contains `✘`. Raise via a patched
  **attribute**, not a replaced module — `monkeypatch.setattr(
  editor_test_callbacks.requests, "post", _failing_post)` where `_failing_post`
  raises `requests_lib.exceptions.ConnectionError("Connection refused")`. See
  the `RequestException` bullet under "Conventions to follow" for why the
  wholesale `setattr(module, "requests", fake)` form fails here with
  `AttributeError`.
- Each of the four tests above needs `ctx` stubbed —
  `monkeypatch.setattr(editor_test_callbacks, "ctx", <ctx with
  triggered_id="editor-quick-test-tabular" or "editor-quick-test-graph">)` —
  because `quick_test` dispatches on `ctx.triggered_id`, not on the click
  arguments.

### Verification (Phase 3)

```bash
pytest -m unit tests -q

grep -n "editor-test-results\|def _run_test\|def test_tabular\|def test_graph" \
  src/app/dash_app/pages/catalog/editor_callbacks.py
# Expected: no output

mypy src/ && pylint src --score=y
# Expected: mypy exit 0; pylint score >= 9.0
```

---

## Phase 4 — Wire the View Test modal callback

> **Goal:** Both View Test buttons open the shared modal with full results —
> Cytoscape for graph queries, a data table for tabular — using the same
> utilities as the graph page, plus a Fit button.

### ✅ Executed 2026-10-11

Two files: `editor_test_callbacks.py` (+82) and
`tests/test_catalog_editor_test_callbacks.py` (+86, 4 new tests). Verified: 1835
unit tests pass (+4), mypy clean, pylint 9.68, `import app.main` +
`create_dash_app()` OK, and the Fit JS targets `editor-test-cytoscape`.

Independently re-verified against the **live** API (`localhost:8000`, real Neo4j):
graph → open, title `Test Results — Graph`, **51** real elements, cytoscape
`block` / table `none`; tabular → open, cytoscape `none` / table `block`;
close → `False` with the other 7 outputs `no_update`; write-Cypher and empty
inputs → open with an `html.Div` error at index 6.

Note the operator committed Phases 1–3 and the badge fix; this phase's two files
are the only dirty ones.

### Tasks

- [x] Add to `editor_test_callbacks.py`:

  ```python
  from app.dash_app.pages.graph.utils import (
      create_error_alert,
      create_table_display,
      neo4j_to_cytoscape,
  )
  ```

  **`view_test`** — one callback serving both View Test buttons and the close
  button (8 outputs):

  ```python
  @callback(
      Output("editor-test-modal",               "is_open"),
      Output("editor-test-modal-title",         "children"),
      Output("editor-test-cytoscape",           "elements"),
      Output("editor-test-cytoscape-container", "style"),
      Output("editor-test-table-container",     "children"),
      Output("editor-test-table-container",     "style"),
      Output("editor-test-results-container",   "children"),
      Output("editor-test-results-container",   "style"),
      Input("editor-view-test-tabular", "n_clicks"),
      Input("editor-view-test-graph",   "n_clicks"),
      Input("editor-test-modal-close",  "n_clicks"),
      State("editor-query-tabular", "value"),
      State("editor-query-graph",   "value"),
      prevent_initial_call=True,
  )
  def view_test(
      tab_clicks: int | None,
      graph_clicks: int | None,
      close_clicks: int | None,
      tab_query: str | None,
      graph_query: str | None,
  ) -> tuple[Any, ...]:
      """Open the shared modal with tabular or graph results."""
      hide = {"display": "none"}
      show = {"display": "block"}
      empty_show = {"minHeight": "300px", "padding": "16px"}

      if ctx.triggered_id == "editor-test-modal-close":
          return (False,) + (no_update,) * 7

      if ctx.triggered_id == "editor-view-test-tabular":
          query, label = tab_query,   "Test Results — Tabular"
      else:
          query, label = graph_query, "Test Results — Graph"

      result = _run_test(query)

      if not result["ok"]:
          error = create_error_alert(result["error"], heading="Query Failed")
          return True, label, [], hide, None, hide, error, empty_show

      data = result["data"]
      if data.get("isGraph"):
          elements = neo4j_to_cytoscape(data)
          return True, label, elements, show, None, hide, None, hide
      table = create_table_display(data.get("rawResults") or [])
      return True, label, [], hide, table, show, None, hide
  ```

- [x] Add a **Fit** clientside callback, mirroring the graph page's fit handler
  (`src/app/dash_app/pages/graph/callbacks/navigation.py:12-29`) but targeting the
  modal's Cytoscape — note the id inside the JS string is `editor-test-cytoscape`:

  ```python
  from dash import clientside_callback

  clientside_callback(
      """
      function(n_clicks) {
          if (n_clicks) {
              const elem = document.getElementById('editor-test-cytoscape');
              if (elem && elem._cyreg && elem._cyreg.cy) {
                  elem._cyreg.cy.fit(null, 30);
              }
          }
          return window.dash_clientside.no_update;
      }
      """,
      Output("editor-test-fit", "className"),   # dummy output
      Input("editor-test-fit", "n_clicks"),
      prevent_initial_call=True,
  )
  ```

  No zoom-in/zoom-out buttons are needed: the container enables wheel-zoom and
  drag-pan via `userZoomingEnabled` / `userPanningEnabled` (`result_pane.py`).

### Tests to add (Phase 4)

Extend `tests/test_catalog_editor_test_callbacks.py`. `view_test` returns an
8-tuple matching its Outputs — index it positionally:
`(is_open, title, elements, cytoscape_style, table_children, table_style,
results_children, results_style)`.

**A graph fake must carry real node dicts.** `neo4j_to_cytoscape` subscripts
`node['elementId']` and `node['wba_id']` directly
(`src/app/dash_app/pages/graph/utils/data_transform.py:79-80`), and iterates
`graph_response.get("nodes", [])`. E5's existing fake
(`{"isGraph": True, "resultCount": 3}`) has **no** `nodes`, so reusing it makes
`elements == []` and the "non-empty" assertion fail even though the callback is
correct; a node without those two keys raises `KeyError`. Use this module-level
fixture (verified to produce exactly one element):

```python
_GRAPH_PAYLOAD = {
    "isGraph": True,
    "nodes": [{
        "elementId": "n1",
        "wba_id": "wba::Person::alice",
        "labels": ["Person"],
        "properties": {"name": "Alice"},
    }],
    "relationships": [],
    "rawResults": [],
    "resultCount": 1,
}
```

- tabular 200 → `result[0]` (`is_open`) is `True`, `result[1]` contains
  `"Tabular"`, `result[3] == {"display": "none"}` (cytoscape hidden),
  `result[5] == {"display": "block"}` (table visible), `result[2] == []`.
- graph 200 (`_GRAPH_PAYLOAD`) → `result[0]` is `True`, `result[1]` contains
  `"Graph"`, `result[3] == {"display": "block"}`, `result[2]` is non-empty,
  `result[5] == {"display": "none"}`.
- close button triggered (`triggered_id="editor-test-modal-close"`) →
  `result[0]` is `False`.
- error response → `result[0]` is `True`, `result[6]` (results-container
  children) contains the error display.

### Verification (Phase 4)

```bash
pytest -m unit tests -q
```

Manual (`PYTHONPATH=src uvicorn app.main:app --reload`, UI at
`http://localhost:8000/app/catalog/edit/github/top_committers` — the editor
route is `/app/catalog/edit/{namespace}/{slug}`; a single-segment path parses as
`("edit", None, None)` and renders a **blank** form with no query loaded, since
`_parse_route` requires two segments after `edit/`,
`editor_callbacks.py:57-60`):

1. **View Test** under Tabular Query → modal opens "Test Results — Tabular"; the
   table renders.
2. Close → modal dismisses.
3. **View Test** under Graph Query → modal opens "Test Results — Graph";
   Cytoscape renders; wheel-zoom and drag-pan work; **Fit** re-frames the graph.
4. An invalid query → the error is shown inside the open modal.

---

## Phase 5 — Cleanup, polish & regression

### Tasks

- [ ] Confirm no dangling references (note the trailing `"` on the first grep —
      it anchors to the retired id's closing quote, so it does not match the new
      `editor-test-results-container`):

  ```bash
  grep -rn 'editor-test-results"' src/
  # Expected: no output

  grep -n "_render_test_results(" src/app/dash_app/pages/catalog/editor_layout.py
  # Expected: no output (the new function is _render_test_results_modal — no match)

  grep -n "def create_graph_container\|def create_table_container\|def create_empty_state" \
    src/app/dash_app/pages/graph/layout.py
  # Expected: no output
  ```

- [ ] Update `docs/design/query-catalog-editor-design.md` so it describes the new
      affordances. Two passages name the removed buttons:

  - **lines 424-429** (the "Queries section" bullet) — replace
    ```
    each with its **own** Test button (`Test Tabular`,
    `Test Graph`) so there is never ambiguity about which variant is being
    exercised.
    ```
    with a description of the two button pairs, e.g. "each with its **own**
    **Quick Test** button (renders a compact inline `✔ N rows` / `✘ error` badge
    directly under that textarea) and **View Test** button (opens a shared `xl`
    results modal, so there is never ambiguity about which variant is being
    exercised)."
  - **lines 447-453** (the `### Testing a query` section) — replace
    ```
    `Test Tabular` / `Test Graph` POST the textarea's Cypher to
    `/api/v1/graph/execute` as `source="raw"`, `view="auto"` and render the result
    in an inline pane: a table for tabular results, a summary alert for graph
    results.
    ```
    with a description matching the new behavior: **Quick Test** POSTs and shows
    the inline badge; **View Test** POSTs and renders the full result in a shared
    `xl` modal — a `cyto.Cytoscape` graph for graph results, a data table for
    tabular results. Keep the existing "This requires a live Neo4j; a down or
    unreachable graph surfaces as an error alert, not a crash." sentence.

  Do **not** renumber or restructure the surrounding doc.

- [ ] Run the gate with coverage, plus the other CI gates:

  ```bash
  pytest -m unit tests -q --cov=src --cov-report=term-missing
  mypy src/
  pylint src --score=y
  bandit -c .bandit.yml -r src/ -lll
  ```
  Expected: all tests pass; new modules ≥ 90% coverage; mypy exit 0; pylint ≥ 9.0;
  no High-severity bandit findings.

- [ ] Manual regression — graph page (`/app/graph`): a graph query renders and
  node expansion, filters, and the details panel still work; a tabular query
  renders a table.

- [ ] Manual regression — catalog editor: Save, Save As, Compare to Factory, and
  the parameter rows still work; Quick Test shows an inline badge; View Test
  opens the modal with the right content.

---

## File change summary

| Action | File |
|---|---|
| **New** | `src/app/dash_app/components/result_pane.py` |
| **Moved** | `src/app/dash_app/pages/graph/styles.py` → `src/app/dash_app/graph_styles.py` (Phase 1 deviation; body byte-identical) |
| **New** | `src/app/dash_app/pages/catalog/editor_test_callbacks.py` |
| **New** | `tests/test_result_pane.py` |
| **New** | `tests/test_catalog_editor_layout.py` |
| **New** | `tests/test_catalog_editor_test_callbacks.py` |
| **Modified** | `src/app/dash_app/pages/graph/layout.py` — use `result_pane`; remove 3 local builders + 5 now-unused imports |
| **Modified** | Repointed to `app.dash_app.graph_styles`: `pages/graph/callbacks/display.py`, `pages/graph/utils/ui_components.py`, `pages/collaboration_network/layout.py`, `pages/collaboration_network/callbacks/display.py`, `common/graph_theme.py`, `common/node_size.py`, `tests/test_graph_theme.py`, `tests/test_search_node_color_consistency.py`, `docs/design/graph-themes-design.md` (Phase 1 deviation) |
| **Modified** | `src/app/dash_app/pages/catalog/editor_layout.py` — 4 buttons, 2 feedback divs, modal, delete `_render_test_results` |
| **Modified** | `src/app/dash_app/pages/catalog/editor_callbacks.py` — delete `_run_test`, `test_tabular`, `test_graph`, and the 2 unused graph-utils imports |
| **Modified** | `src/app/dash_app/pages/catalog/__init__.py` — register `editor_test_callbacks` |
| **Modified** | `src/app/dash_app/assets/executive-dashboard.css` — shared `.alert-inline-badge` class (Phase 3 follow-up fix, see Phase 3) |
| **Modified** | `tests/test_catalog_editor_callbacks.py` — migrate tests E4–E7 |
| **Modified** | `docs/design/query-catalog-editor-design.md` — rewrite the two passages that name the old Test buttons |

## Done criteria

ALL must hold:

- [ ] `pytest -m unit tests -q` exits 0, including the new test modules
- [ ] `mypy src/` exits 0
- [ ] `pylint src --score=y` reports ≥ 9.0
- [ ] `bandit -c .bandit.yml -r src/ -lll` reports no High severity
- [ ] `grep -rn 'editor-test-results"' src/` returns no matches
- [ ] `grep -n "_render_test_results(" src/app/dash_app/pages/catalog/editor_layout.py` returns no matches
- [ ] `grep -n "Test Tabular\|Test Graph" docs/design/query-catalog-editor-design.md` returns no matches
- [ ] `git status` shows no modified file outside the Scope list
- [ ] Every new test module carries `pytestmark = pytest.mark.unit`
- [ ] `plans/README.md` status row updated

## Maintenance notes

- **The graph page's ids are load-bearing.** `graph/layout.py` moved three
  builders into `result_pane.py`; the graph page's callbacks, clientside
  handlers, and keyboard shortcuts all address `graph-cytoscape`,
  `graph-cytoscape-container`, `graph-table-container`, `graph-results-container`
  by string. Any future change to `id_prefix` handling must keep the
  `id_prefix="graph"` output byte-identical.
- **`result_pane.py` imports the shared stylesheet** from
  `app.dash_app.graph_styles` — the module previously at
  `pages/graph/styles.py`, moved out of the graph page package in Phase 1 to
  break a circular import (see the Phase 1 deviation note). It sits beside the
  design-token module (`app/dash_app/styles.py`). **Do not move it back into
  `pages/graph/`**: importing any submodule of that package runs its `__init__`,
  which imports `.layout`, which imports `result_pane`.
- **Badge semantics are keyed to the execute API response.** `quick_test` reads
  `isGraph` / `nodes` / `relationships` / `resultCount` and `view_test` reads
  `rawResults` (`src/app/api/graph/v1/model.py:115-150`). If that response shape
  changes, both badges and the modal routing must be revisited.
- **`#editor-test-results` is gone.** Any saved deep link, screenshot, or
  runbook that references it must be updated; the replacement inputs are the four
  `editor-{quick,view}-test-{tabular,graph}` buttons.
- **Reviewers should check:** that Phase 1 changed no `graph-*` id (diff the
  rendered graph-page layout if in doubt), that the two inline `dbc.Alert`s are
  the only new feedback surfaces, and that no CSS was added.

## Progress tracker

| Phase | Status | Notes |
|---|---|---|
| Phase 1 — Extract `result_pane.py` | `[x]` | DONE 2026-10-11 + approved stylesheet move; operator-verified; uncommitted on `feature/editor-test-buttons` |
| Phase 2 — Editor layout (buttons + modal shell) | `[x]` | DONE 2026-10-11; operator-verified; buttons inert pending Phase 3 |
| Phase 3 — Quick Test callbacks | `[x]` | DONE 2026-10-11; uncommitted |
| Phase 4 — View Test modal callback | `[x]` | DONE 2026-10-11; uncommitted |
| Phase 5 — Cleanup & regression | `[ ]` | |

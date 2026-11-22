# Plan 012: One table standard — builder, CSS, and per-page migration

> **Executor instructions**: This plan is **eight steps**, each gated by a human
> browser review. Do one step, run its commands, report what you changed and what
> the page now looks like, then **STOP**. The operator opens the page named in the
> step in a browser, in both themes, and replies with feedback. You iterate on
> that same step until they say it is done. **Do not start the next step on your
> own initiative.**
>
> **Gate protocol** (applies to steps 1-7):
>
> 1. Make the step's edits.
> 2. Run the step's command checks. Run the UI rebuild and confirm the new code is
>    live in the container, not just on the host.
> 3. State which page(s) the operator should open, and what should look different.
> 4. State explicitly which of the step's requirements passed and which did not.
> 5. **STOP and wait.** Do not begin the next step. Do not "fix" a failing
>    requirement by changing a value the step does not name — report it instead.
> 6. When the operator replies with feedback, address only that feedback, re-run
>    the checks, and report again. Repeat until they confirm the step.
>
> If anything in "STOP conditions" occurs, stop and report — do not improvise.
> When the whole plan is done, update the status row for this plan in
> `plans/README.md` — unless a reviewer dispatched you and told you they maintain
> the index.
>
> **Why the steps are split by page.** Every step after the foundation changes
> **one page's tables**, so a table that looks wrong can be attributed to a single
> page and reverted without touching the others. The foundation (step 1) touches
> no page, so its gate is the test suite only. The key/value tables are the one
> exception: they are shared code rendered on four pages, so that step lists all
> four routes to eyeball.
>
> **Drift check (run first)**:
> `git diff --stat 8e1d0b5a..HEAD -- src/ui/components/table.py src/ui/components/common.py src/ui/styles.py src/ui/assets/executive-dashboard.css src/ui/pages/catalog src/ui/pages/settings/user_management src/ui/pages/graph src/ui/pages/search.py src/ui/pages/connectors src/ui/pages/timeline src/ui/pages/analytics.py src/ui/pages/chat.py tests/test_settings_user_management_page.py tests/test_activity_timeline_detail_modal.py tests/test_shared_graph_components.py docs/design/design-system.md`
> If any in-scope file changed since `8e1d0b5a`, compare the "Current state"
> excerpts against the live code before proceeding; on a mismatch, treat it as a
> STOP condition.

## Status

- **Priority**: P2
- **Effort**: M (eight gated steps; the operator reviews between each)
- **Risk**: MED
- **Depends on**: none
- **Category**: tech-debt (UI consistency / design tokens)
- **Planned at**: commit `8e1d0b5a`, 2026-11-22

### Progress

| Step | Scope | Status |
|---|---|---|
| 1 | Foundation: `ui/components/table.py`, CSS base + variants, unit tests | TODO |
| 2 | Catalog (Library) table | TODO |
| 3 | Settings → User Management table | TODO |
| 4 | Graph query-results table | TODO |
| 5 | Key/value tables (Graph, Collaboration Network, Ego, Timeline, Search) | TODO |
| 6 | Connectors env-var table | TODO |
| 7 | Chat markdown tables | TODO |
| 8 | Design docs + full CI gate | TODO |

## Why this matters

The app has six independent table implementations and three border treatments.
Two of them share a CSS class name but not its props; two others are near-identical
CSS rulesets under different names; a fourth is a hand-rolled fork of a shared
renderer that has silently drifted. The design system has no table section at all,
so nothing states what "a table" means in this app.

The goal is not uniformity for its own sake. It is that a table reads as the same
component wherever it appears, that a change to the table standard is a change in
one place, and that a page that needs a denser table gets it from the existing
`.dense-page` scope rather than from a fourth bespoke stylesheet.

## Current state

### The six implementations

| # | Table | File | Mechanism |
|---|---|---|---|
| 1 | Library / Catalog | `src/ui/pages/catalog/layout.py` | `dbc.Table` + `.executive-table`, body filled by JS |
| 2 | User Management | `src/ui/pages/settings/user_management/layout.py` | `dbc.Table` + `.executive-table` |
| 3 | Graph query results | `src/ui/pages/graph/utils/ui_components.py` | `dbc.Table` + `.graph-results-table`, `bordered=True, striped=True` |
| 4 | Properties / details | `src/ui/components/common.py` | `html.Table` + inline `DETAILS_TABLE_*` tokens |
| 5 | Search attributes | `src/ui/pages/search.py` | `html.Table` + inline `DETAILS_TABLE_*` tokens — a fork of #4 |
| 6 | Connectors env vars | `src/ui/pages/connectors/layout.py` | `html.Table`, no header, inline styles |

Plus two non-tables that read as tables: the Analytics "layer table" (a CSS grid of
`html.Div`s with switches and number inputs) and chat markdown tables (rendered by
`dcc.Markdown`, so not app-built at all).

### The CSS

`src/ui/assets/executive-dashboard.css` carries two near-duplicate rulesets:

- `.graph-results-table` — background/colour/border, `thead th` uppercase at 12px
  with `letter-spacing: 0.4px`, `tbody td` at 13px, striped and hover rules.
- `.executive-table` — the same declarations, plus `border-collapse: collapse`, a
  `tbody tr:last-child td { border-bottom: none }` rule, and `white-space: nowrap`
  on the header.

The differences are accidental, not designed. `.executive-table` also has a
`.dense-page` override that halves cell padding; `.graph-results-table` has no
dense override.

Chat markdown tables are a third ruleset (`.chat-markdown table`, `th`, `td`) with
`border: 1px solid` on every cell and a 6px/12px padding.

### The props already disagree

| Table | `bordered` | `striped` | `hover` | `responsive` | `size` |
|---|---|---|---|---|---|
| Catalog | `False` | not set | `True` | not set | `sm` |
| User Management | `False` | not set | `True` | `True` | `sm` |
| Graph results | `True` | `True` | `True` | `True` | not set |

Both `executive-table` callers also pass an inline
`style={"fontFamily": FONT_SANS, "fontSize": FONT_SIZE_SMALL}` that the CSS
overrides — the inline size is dead and misleading.

### The key/value fork has drifted

`src/ui/pages/search.py` `_build_attributes_table` re-implements
`src/ui/components/common.py` `render_properties_table`. The fork lacks: clipboard
buttons on every value, URL rendering, and the `_DATE_TIME_KEYS` date heuristic.
It also reads `runtime_settings.get("UI_DATETIME_FORMAT")` where the shared renderer
reads `settings.UI_DATETIME_FORMAT`.

### The key/value tables are shared by four pages

`render_properties_table` is reached through `build_element_properties_content`
(Graph, Collaboration Network, Collaboration Network Ego) and
`render_visible_properties` (Timeline detail modal). Changing it changes four pages
at once.

### The graph results table appears on two pages

`create_table_display` is called by the Graph page's query callback and by the
Catalog editor's View Test modal. A change to it is visible in both places.

### Tests that pin table internals

- `tests/test_settings_user_management_page.py` asserts `"executive-table"` is in
  the rendered table's `className`.
- `tests/test_activity_timeline_detail_modal.py` walks components looking for
  `className == "details-prop-row"` and asserts the modal and the graph panel
  produce the same rows.

## Decisions already taken

These are settled. Do not re-open them while executing.

1. **Abstraction**: a builder module plus CSS, documented in the design system.
2. **Surface**: two builders — `data_table` (columns/rows) and `key_value_table`
   (key/value pairs) — sharing one base class.
3. **Key/value cells**: adopt the shared renderer's full behaviour — date
   formatting, URL rendering, mono for IDs, clipboard on every value. Search gains
   all of it.
4. **Datetime source**: `runtime_settings` in the unified builder.
5. **Borders**: bottom-only row rules everywhere. No outer border, no cell borders.
6. **Header**: 12px, uppercase, `letter-spacing: 0.4px`, semibold.
7. **Prop defaults**: `hover=True`, `responsive=True`, `striped=False`. The
   builder exposes no `bordered` parameter — see step 1a.
8. **Connectors table**: routed through the builder and given a header row.
9. **Analytics layer table**: left as a grid. Its header labels adopt the new type
   scale in step 8's sweep only if the sweep's scope covers it — it does not; the
   layer table is out of scope and stays as it is.
10. **Catalog JS body**: the builder emits the skeleton and header; JS fills the
    body. The builder takes a `body_id`.
11. **Density**: via `.dense-page` on the ancestor. No per-table density argument.
12. **Class names**: `.executive-table` base, `--data` and `--kv` variants.
    `.graph-results-table` is deleted. Key/value cells move from inline tokens to
    CSS classes.
13. **Test strategy**: update the two pinning tests to the new contract.
14. **Module location**: new `src/ui/components/table.py`;
    `render_properties_table` and `render_visible_properties` stay in `common.py`
    as thin wrappers so existing imports keep working.
15. **Chat tables**: CSS declarations aligned; not routed through the builder.
16. **Badges**: keep Bootstrap semantic classes, tokenise their size in CSS.
17. **Typography sweep**: text, badges, icons and code **inside table cells** only.
18. **Graph results border**: `bordered=True` dropped; no `--bordered` modifier.
19. **Dark mode**: every page gate checks both themes.
20. **Docs**: a Tables section in `docs/design/design-system.md`, last step.
21. **Plan number**: 012 (011 is taken).
22. **Metric tooltips**: the `hub_score` / `normalized_weight` (i) popovers in the
    key cell are preserved via `key_value_table`'s `key_renderer` hook, wired to
    `_panel_metric_key_cell` in `common.py`. The tooltip bodies and their unique-id
    generator stay in `common.py`; they are collaboration-domain content, not
    table structure.

## Commands you will need

Run from the repo root. Activate the virtualenv first: `source .venv/bin/activate`.

| Purpose | Command | Expected on success |
|---|---|---|
| Unit tests | `pytest -m unit tests -q` | all pass |
| Targeted tests | `pytest -m unit tests/test_table_builder.py tests/test_settings_user_management_page.py tests/test_activity_timeline_detail_modal.py tests/test_shared_graph_components.py tests/test_result_pane.py -q` | all pass |
| Typecheck | `mypy src/` | exit 0, no errors |
| Lint | `pylint src --score=y` | score ≥ 10.0 |
| Bring the stack up | `docker compose up -d` | all services healthy |
| Rebuild the UI | `docker compose build ui && docker compose up -d --force-recreate ui` | container recreated |
| Confirm the new code is live | `docker compose exec ui grep -c "executive-table--data" /app/ui/components/table.py` | ≥ 1 |

**`docker compose build` alone is not enough** — it leaves the old container
serving the old code. Always follow with `--force-recreate`, and confirm the new
value is live **by reading it out of the container**, not out of the host file.

`flake8` is not a CI gate. Use it only on the lines you touched; your diff should
add no new finding. Do not reflow or reformat unrelated code to satisfy it.

## Suggested executor toolkit

- Measure and screenshot through `https://localhost/app/...`. The Compose stack
  terminates TLS at the `nginx` service; neither the `api` nor the `ui` service
  publishes a host port.
- If the `chrome-devtools` MCP tools are available, `take_snapshot` and
  `evaluate_script` are the cheapest way to confirm a table's computed styles.
  Otherwise drive the Playwright Chromium binary at
  `~/.cache/ms-playwright/chromium-1248/chrome-linux64/chrome` over CDP; the
  `websockets` package is in the venv.
- Switch themes through the app's theme toggle, not by editing classes in the DOM.
  The shell and `document.body` both carry the theme class and manual surgery
  desyncs them.
- Read `docs/design/design-system.md` § Typography and § Spacing System before
  step 1 and again before step 8.

## Scope

**In scope** (the only files you should modify):

- `src/ui/components/table.py` — new module.
- `src/ui/components/common.py` — the key/value wrappers, moved to delegate.
- `src/ui/components/__init__.py` — re-export the builders if you add them to
  `__all__`.
- `src/ui/styles.py` — remove the `DETAILS_TABLE_*` tokens once nothing imports
  them.
- `src/ui/assets/executive-dashboard.css` — consolidate the table rulesets, add
  the variants, align the chat markdown declarations.
- `src/ui/pages/catalog/layout.py` — table skeleton.
- `src/ui/pages/settings/user_management/layout.py` — table.
- `src/ui/pages/graph/utils/ui_components.py` — `create_table_display`.
- `src/ui/pages/search.py` — delete the fork, call the shared renderer.
- `src/ui/pages/connectors/layout.py` — the env table and its row builder.
- `tests/test_table_builder.py` — new.
- `tests/test_settings_user_management_page.py` — update the pinned class
  assertion.
- `tests/test_activity_timeline_detail_modal.py` — update only what the renderer
  change breaks.
- `tests/test_shared_graph_components.py` — **run it; do not weaken it.** Expected
  to pass unchanged (it pins the metric popovers that `key_renderer` preserves).
- `docs/design/design-system.md` — the Tables section.

**Out of scope** (do NOT touch):

- `src/ui/pages/analytics.py` — the layer table stays a grid. It is a control
  surface, not a data table.
- The Catalog table's JS row builder in `src/ui/pages/catalog/callbacks.py` — it
  keeps producing row HTML. Only the table element and its class names change.
- `src/ui/pages/chat.py` — no app-built tables. The chat CSS change is a stylesheet
  edit only.
- `src/ui/pages/timeline/callbacks.py` — it imports the shared renderer; the
  wrapper keeps that import valid. Do not edit it unless an import breaks.
- `src/ui/pages/graph/callbacks/**` and the collaboration-network callbacks — same
  reason.
- `src/ui/components/result_pane.py` — the container builders, not the table.
- Any `plans/` document other than this one and the `README.md` status row.

## Git workflow

- You are on `main`. Create a branch first: `git checkout -b table-consistency`.
- **One commit per step, after that step's gate is confirmed by the operator.**
  Commit messages are plain imperative sentences (e.g. "Consolidate table CSS
  into one base class").
- Leave the working tree clean between steps.

## Steps

### Step 1 — Foundation: the builder module, the CSS base, and its unit tests (TEST GATE)

**No page changes in this step.** The builder and the CSS land inert; nothing
imports them yet. The gate is the test suite, not a browser.

**1a. Create `src/ui/components/table.py`.**

Two public functions, plus the row helper the key/value builder needs.

```python
def data_table(
    columns: Sequence[str],
    rows: Sequence[Sequence[Any]] | None = None,
    *,
    body_id: str | None = None,
    striped: bool = False,
    hover: bool = True,
    responsive: bool = True,
    size: str = "sm",
    table_id: str | None = None,
    className: str | None = None,
) -> dbc.Table:
```

- Emits `.executive-table.executive-table--data`.
- `rows=None` with `body_id` set emits an empty `<tbody id=...>` for a JS body.
  `rows=None` without `body_id` is an error — a table with no body is almost
  always a bug.
- **No `bordered` parameter.** `dbc.Table(bordered=True)` adds Bootstrap's
  `table-bordered`, which in the app's Materia theme borders every cell on all
  four sides — not just the table's edge. Nothing in `executive-dashboard.css`
  neutralizes it (no `table-bordered` rule exists). The builder therefore does not
  expose it: a caller that wants a cell grid is asking for a design change, not a
  flag. The one current caller that passes `bordered=True`
  (`create_table_display`) drops it in step 4a, and passing it is not possible
  afterwards.

```python
def key_value_table(
    items: Sequence[tuple[str, Any]],
    *,
    key_renderer: Callable[[Any], Any] | None = None,
    table_id: str | None = None,
    className: str | None = None,
) -> html.Table:
```

- Emits `.executive-table.executive-table--kv`.
- Each row is `html.Tr(className="details-prop-row")` with two cells:
  `html.Td(className="kv-key")` and `html.Td(className="kv-value")`.
- `key_renderer` renders the key cell's content. When it is `None` the cell holds
  the key text unchanged; when it is given, the cell holds `key_renderer(key)`.
  Import `Callable` from `collections.abc`. This hook exists because the shared
  renderer's key cell is **not** plain text today: `common.py` renders it through
  `_panel_metric_key_cell`, which appends an (i) hover popover for documented
  metrics (`hub_score`, `normalized_weight`). That content and its unique-id
  generator must stay in `common.py`; see step 5a.
- Value-cell content reproduces the current `render_properties_table` behaviour
  exactly: date formatting for `_DATE_TIME_KEYS` and ISO-looking strings, URL
  rendering with the external-link icon, monospace for `id` and long space-free
  tokens, clipboard on every value. **Copy** that value-cell formatting out of
  `render_properties_table` into this module, and leave `common.py` untouched.
  The duplication is deliberate and lasts only until step 5: step 1 must prove the
  builder with zero dependants, so `common.py` has to keep rendering through its
  own code. Step 5 deletes the duplicated block. The key-cell metric tooltip is
  the one piece that never moves — it stays in `common.py` and arrives through
  `key_renderer`.
- One deliberate difference from the copied code: read the format as
  `runtime_settings.get("UI_DATETIME_FORMAT")` (`from ui.runtime_settings import
  runtime_settings`), not `settings.UI_DATETIME_FORMAT`. Decision 4 settles the
  source; wiring it correctly here means step 5 only has to delete the old copy,
  not also change behaviour.

**Keep `details-prop-row` as the row class.** The timeline test walks the tree for
it. The CSS already styles `.details-prop-row:hover .details-prop-icon`; that rule
must keep working.

**1b. CSS.** In `executive-dashboard.css`:

- Replace the `.graph-results-table` ruleset and the `.executive-table` ruleset
  with one base ruleset carrying the union of their declarations, plus two
  variants:
  - `.executive-table` — background, colour, border colour, `border-collapse`,
    `thead th` (12px, uppercase, `0.4px`, semibold, `nowrap`), `tbody td` (13px,
    bottom border), `tbody tr:last-child td` (no border), striped and hover rules.
  - `.executive-table--data` — the data-table variant. It may be empty today; it
    exists so a page can target data tables without repeating the base selector.
  - `.executive-table--kv` — the key/value variant, with `.kv-key` and `.kv-value`
    cell rules reproducing the `DETAILS_TABLE_KEY_STYLE` and
    `DETAILS_TABLE_VALUE_STYLE` declarations, plus `.kv-value code` for the mono
    treatment. Also add `.kv-value a` reproducing `DETAILS_TABLE_LINK_STYLE`
    (`src/ui/styles.py:448-454`): navy, no underline, `cursor: pointer`,
    `word-break: break-all`. Without it, once the inline token is gone, URLs in
    every property table render as default browser links (blue, underlined,
    wrapping differently).
- Add `.executive-table .badge { font-size: 12px; }` so in-cell badges stop
  carrying an inline size.
- Add the dark-mode overrides the base needs. The existing base already uses
  `var(--color-*)` tokens, so most rules need no duplicate; check each one.
- Extend the `.dense-page` block to cover the base selector, not just
  `.executive-table`, so dense pages keep their reduced padding.

  **This gives the graph results table dense padding for the first time.** Today
  the ruleset at `executive-dashboard.css:2533` keys off `.executive-table`, and
  the graph table carries only `.graph-results-table`; that table sets no padding
  of its own, so it currently uses the Bootstrap/Materia default even though the
  Graph page root is `.dense-page` (`src/ui/pages/graph/layout.py:644`). After this
  step it drops to 2px top/bottom. That is intended — the Graph page is a dense
  page and its results table should match — but Gate 4 must confirm it rather than
  treat it as unexpected.

**1c. Unit tests.** New `tests/test_table_builder.py`, marked
`pytestmark = pytest.mark.unit`. Cover:

- `data_table` emits the base and variant classes.
- `data_table` with `body_id` and no rows emits an empty tbody with that id.
- `data_table` with rows renders one `<tr>` per row and one `<th>` per column.
- `data_table` defaults: `hover=True`, `responsive=True`, `striped=False`.
- `data_table` emits no `table-bordered` class (it has no `bordered` parameter).
- `key_value_table` renders one `.details-prop-row` per item, with `.kv-key` and
  `.kv-value` cells.
- `key_value_table` renders the key text unchanged when `key_renderer` is omitted,
  and renders `key_renderer(key)` in the key cell when it is given.
- `key_value_table` renders a URL as an anchor, a long token as `<code>`, and a
  date-like string as a relative-time span with a title.
- `key_value_table` renders a clipboard control on every value.
- `key_value_table` formats a date using a `runtime_settings` `UI_DATETIME_FORMAT`
  override, not the startup `settings` value: patch
  `ui.runtime_settings.runtime_settings.get` to return a distinctive format and
  assert the rendered `title` carries it.

**1d. Do not change any page yet.** `common.py` still uses its own renderer at the
end of this step; the builder is unused. That is deliberate — the gate proves the
builder works before anything depends on it.

The value-cell formatting therefore exists **twice** at the end of this step: once
in `common.py` (live) and once in `table.py` (unused). That duplication is
intentional. Do not "fix" it by making `common.py` delegate now — that would change
four pages before the gate and make "no page opens differently" false. Step 5
removes the `common.py` copy.

**Gate 1**: `pytest -m unit tests -q` passes; `mypy src/` and `pylint src` pass.
No page opens differently. Report the new test count.

### Step 2 — Catalog (Library) table

**Page to eyeball**: `/app/catalog`, light and dark.

**2a.** In `src/ui/pages/catalog/layout.py`, replace the hand-built `dbc.Table`
with `data_table(columns=..., body_id="library-table-body", className="align-middle")`.
The column list is the nine headers already present. **Keep `align-middle`** — the
current table carries `className="align-middle executive-table"` (`layout.py:119`)
and `data_table` emits only its own classes, so it must be passed through or the
cells become top-aligned. Drop the inline `style={"fontFamily": ...,
"fontSize": ...}` — the CSS owns the type scale.

**2b.** Keep `hover=True` and `size="sm"`; `responsive` now defaults to `True`, so
the table gains a responsive wrapper. That is the intended change. There is no
`bordered` argument to pass.

**2c.** Do not touch the JS row builder. It still fills `#library-table-body`. If
the JS sets a class on a row or cell that the new CSS no longer matches, report it
rather than editing the JS.

**Gate 2**: `/app/catalog` renders the same nine columns with the same rows, in
both themes. The header reads uppercase 12px; the rows are 13px; there is no outer
border or cell grid, only bottom row rules. Report the computed header font size and
whether a horizontal scrollbar appears at 1280px width.

### Step 3 — Settings → User Management table

**Page to eyeball**: `/app/settings/user-management`, light and dark.

**3a.** In `src/ui/pages/settings/user_management/layout.py`, replace the
`dbc.Table` in `_render_table` with `data_table(...)`. Keep the empty-state row
(`colSpan=6`) — `data_table` accepts pre-built rows, so pass the empty-state row as
a normal row.

**3b.** Drop the inline `style` on the table. Keep the `size="sm"` and `hover=True`
behaviour; `responsive` is now on by default. **Keep `align-middle`** by passing
`className="align-middle"` — the current table carries
`className="align-middle executive-table"` (`layout.py:124`), and without it the
cells become top-aligned, which visibly shifts the row's Edit/Password/Delete button
group upward relative to the text.

**3c.** Update `tests/test_settings_user_management_page.py` so the assertion
checks the builder's class set: `"executive-table"` and
`"executive-table--data"` both in the className.

**Gate 3**: `/app/settings/user-management` renders the same six columns. Note that
this page is **not** a dense page — its table must keep the roomier padding. Compare
its row height against `/app/catalog`'s and report both numbers. If they are equal,
the `.dense-page` scoping has failed; report it as a STOP condition.

### Step 4 — Graph query-results table

**Pages to eyeball**: `/app/graph` (run a query that returns rows, switch to the
table view) and the Catalog editor's View Test modal, which uses the same builder.

**4a.** In `src/ui/pages/graph/utils/ui_components.py`, replace the `dbc.Table` in
`create_table_display` with `data_table(columns=columns, rows=rows)`. Drop
`bordered=True` and `striped=True`; the base gives hover and bottom-only rows.

**4b.** Delete the `.graph-results-table` CSS ruleset — nothing should reference it
after this step. Grep to confirm.

**4c.** The empty-state message beside the table stays as it is.

**Gate 4**: `/app/graph` shows a result table with no outer border and no cell
grid, in both themes. The Catalog editor's Test modal shows the same. Report whether
any query-result table had relied on the striping to separate wide rows.

Report this as an intended change: the graph results table now takes the dense
2px vertical cell padding, because it carries `.executive-table` on a `.dense-page`
route. Before this step it used the Bootstrap default. Confirm the tightened rows
still look right at this page's canvas height.

### Step 5 — Key/value tables: Graph, Collaboration Network, Ego, Timeline, Search

**Pages to eyeball**: `/app/graph` (select a node — the right-panel properties),
`/app/collaboration` (select a node), `/app/collaboration/person` (select a node),
`/app/analytics/timeline` (open a detail modal), `/app/search` (open a result's
attributes). Both themes.

This is one step because all five routes read the same shared renderer. Changing
it changes all of them; splitting the step would mean five gates over one code
change.

**5a.** In `src/ui/components/common.py`, change `render_properties_table` to
delegate to `key_value_table`, keeping its signature and its docstring's promise.
Pass `key_renderer=_panel_metric_key_cell` so the metric (i) popovers survive.

`_PANEL_METRIC_TOOLTIPS`, `_METRIC_TOOLTIP_IDS` and `_panel_metric_key_cell`
**stay in `common.py`**. They are the one part of the key cell that does not move
into `table.py`: the tooltip bodies are collaboration-domain content, and the id
counter must keep producing a fresh id per render (two property tables can be
rendered for one selection). The value-cell logic (dates, URLs, mono, clipboard)
that step 1 copied into `table.py` is now the only copy: deleting the block from
`common.py` is what makes the delegation real, and the four pages that reach this
renderer start using the builder at this step.

**Do not delete or weaken `tests/test_shared_graph_components.py`.** Its three
tooltip tests (`test_node_hub_score_has_tooltip`,
`test_edge_normalized_weight_has_tooltip`,
`test_tooltip_icon_ids_are_unique_across_renders`) must still pass after the
delegation. If one fails, the `key_renderer` wiring is wrong — fix the wiring,
do not edit the test.

**5b.** In `src/ui/pages/search.py`, delete `_build_attributes_table` and call
`render_properties_table` instead. Search gains clipboard controls, URL rendering
and the `_DATE_TIME_KEYS` heuristic.

Then make the shared renderer honour Decision 4: in the module that holds the
formatting after step 1 (`src/ui/components/table.py`), change the format lookup
from `settings.UI_DATETIME_FORMAT` to
`runtime_settings.get("UI_DATETIME_FORMAT")`, importing `runtime_settings` from
`ui.runtime_settings`.

This is an intended behaviour change, not a refactor: property tables on Graph,
Collaboration Network, Ego and Timeline switch from the startup env value to the
runtime-editable one, so a format changed in the Settings UI now applies to them
too, and Search's attributes table and its card-header timestamp finally agree.
Report it as a behaviour change in the gate text.

**5c.** Update `tests/test_activity_timeline_detail_modal.py` if the row class or
structure changed. The row class stays `details-prop-row`, so the tree-walker should
keep working; update only what actually breaks.

**5d.** Remove the `DETAILS_TABLE_*` imports from `common.py` and `search.py` once
nothing uses them. Do not delete the tokens from `styles.py` yet — check for other
importers first.

**Gate 5**: all five routes show key/value tables with the same type scale as the
data tables, bottom-only row rules, and working clipboard buttons. Search's attribute
table now has clipboard buttons and renders URLs as links — confirm that is what you
see. Report whether any page's key/value table now overflows its panel because the
cells moved from inline styles to CSS.

Report as a behaviour change: property tables now format datetimes from
`runtime_settings`, so a format edited in the Settings UI applies to them. On
`/app/search`, the result card's header timestamp and its attributes table must now
use the same format.

### Step 6 — Connectors env-var table

**Page to eyeball**: `/app/connectors/github_mcp` — the MCP configuration section.
This is the manual-setup connector page that renders the env table. Both themes.

**6a.** In `src/ui/pages/connectors/layout.py`, rebuild `_env_row` to return row
cells for `data_table`, or give it a header and route the whole table through
`data_table`. Add a header row: `Variable`, `Description`, `Status`.

**6b.** The variable cell keeps its `<code>` styling but uses the shared mono stack
(`'SFMono-Regular', 'Consolas', 'Menlo', monospace`) rather than the raw
`"monospace"` string.

The third cell is **one cell, not two**, and it keeps all three of its current parts:
the coloured dot, the "Set"/"Not set" label, and the masked `display_value`
(`"—"` when unset, which today is `layout.py:880`). Do not drop the masked value —
it is the only signal of *which* token is configured. Its `maxWidth: 320px` cap
stays on this same cell. The header for this column is `Status`.

**6c.** Remove the outer `border`/`borderRadius` from the surrounding `html.Div` if
the table's own styling now carries the separation; keep the padding. Do not remove
the section's card styling.

**Gate 6**: `/app/connectors/github_mcp` shows a three-column table with a header,
bottom-only row rules, and no outer border, in both themes. The set/not-set
indicator still reads clearly in both themes, and each configured row still shows its
masked value. Report the table's width, and whether the `Status` column's 320px
`maxWidth` still clips the masked value on the longest row.

### Step 7 — Chat markdown tables

**Page to eyeball**: `/app/chat`, with a message that renders a markdown table.

**7a.** In `executive-dashboard.css`, change `.chat-markdown table`, `th`, `td` to
match the base: `border-collapse: collapse`, header 12px uppercase with `0.4px`
letter-spacing and the light background, cells 13px with bottom-only borders. Remove
the per-cell `border: 1px solid`.

**7b.** Chat is not a dense page. Do not add `.dense-page` to it.

**Gate 7**: a chat message with a markdown table renders with bottom-only row rules
and an uppercase header, in both themes. Report whether the LLM's markdown tables
still read as tables without the cell grid — if they do not, say so and stop; the
fix is a design decision, not a value to tune.

### Step 8 — Design docs and the full CI gate

**8a.** Add a **Tables** section to `docs/design/design-system.md`, after the
Typography/Spacing sections and before or within the component list. It must state:

- The base class and the two variants, with when to use each.
- The header rule (12px, uppercase, `0.4px`, semibold).
- The body rule (13px), the mono rule, the badge rule.
- The border rule: bottom-only, no outer border, no cell grid.
- The density rule: `.dense-page` on the ancestor, and which pages are dense.
- The builder API: `data_table` and `key_value_table`, with the `body_id` skeleton
  pattern for JS-rendered bodies.
- A pointer to the design doc's performance technique for large tables.

Do not restate the builder's source in the doc; name the module and the functions.

**8b.** Update this plan's row in `plans/README.md`.

**8c.** Run the full gate:

| Command | Expected |
|---|---|
| `pytest -q -m unit tests` | all pass |
| `mypy src/` | no issues |
| `pylint src --score=y` | 10.00/10 |
| `bandit -c .bandit.yml -r src/ -lll` | no High severity |

**Gate 8**: the full gate passes. Report the test count, mypy result, pylint score and
bandit result.

## Test plan

- **New**: `tests/test_table_builder.py` — the builder's structure, defaults and
  key/value cell behaviours.
- **Updated**: `tests/test_settings_user_management_page.py` — the class assertion.
- **Updated**: `tests/test_activity_timeline_detail_modal.py` — only what the
  renderer change breaks.
- **Unchanged**: `tests/test_result_pane.py` — the container builders are not
  touched.
- **Manual**: every page gate, in both themes.

## Done criteria

- One base CSS ruleset and two variants; `.graph-results-table` is gone.
- No table carries an inline `fontSize` or `fontFamily`.
- Both migrated `dbc.Table` callers keep `align-middle`; no table relying on it
  becomes top-aligned.
- URLs in property tables render navy and uninlined, not as default browser links.
- Header 12px uppercase in every table, including chat markdown.
- Body 13px; key/value cells use CSS classes, not inline tokens.
- Property tables format datetimes from `runtime_settings`, matching Decision 4,
  and `tests/test_table_builder.py` pins it.
- Bottom-only row rules everywhere; no outer border, no cell grid.
- Dense pages keep their reduced padding; User Management does not.
- Search no longer forks the key/value renderer.
- The `hub_score` and `normalized_weight` (i) popovers still render in the
  properties panel, and `tests/test_shared_graph_components.py` passes unchanged.
- The connectors env table has a header.
- The design system documents the standard.
- The full CI gate passes.

## STOP conditions

Stop and report (do not improvise) if:

- The "Current state" excerpts do not match the live code — the codebase has
  drifted since this plan was written.
- **A step's gate is not yet confirmed by the operator.** Do not proceed.
- A page's table renders **white in dark mode** — a class was dropped during
  migration. This is the failure the User Management test guards against.
- User Management's row height equals Catalog's — the `.dense-page` scoping failed.
- The Catalog table's JS body stops filling after the skeleton change. Report which
  selector the JS targets and what the builder now emits.
- A key/value table overflows its panel because the cells moved from inline styles
  to CSS. Report the panel and the overflow, not a new width.
- A key/value table renders differently on two of the four pages that share the
  renderer. That means a page overrides the shared styles locally; report which.
- The chat markdown table no longer reads as a table without its cell grid. That is
  a design decision, not a value to tune.
- Anything appears to require editing a file in the "Out of scope" list.

## Maintenance notes

- The builder is the single place a table's structure changes. A page that needs a
  new table should call it, not build a `dbc.Table`.
- The key/value builder's cell formatting is the shared property renderer's logic.
  A change to how a date or a URL renders belongs there, not in a page.
- A dense page's table density comes from `.dense-page` on the page root. A page
  that needs a denser table without being dense is a design question, not a new
  modifier.
- The Catalog table's body is JS-rendered for performance. If a future table needs
  the same, `data_table(body_id=...)` is the pattern; do not re-implement the
  skeleton.

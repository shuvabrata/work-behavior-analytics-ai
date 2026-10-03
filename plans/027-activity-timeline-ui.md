# Plan 027: Activity Timeline UI (phases UI-0 … UI-12)

> **Executor instructions**: Follow this plan phase by phase, in order. Run every
> verification command and confirm the expected result before moving to the next
> phase. If any "STOP conditions" item occurs, stop and report — do not improvise.
> Update this plan's status row in `plans/README.md` when a phase completes.
>
> **Drift check (run first)**: `git diff --stat 94f6b7a..HEAD -- src/app/dash_app src/app/analytics src/app/api/activity src/app/dash_app/assets/executive-dashboard.css tests`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts below against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: L (~8.5 focused days; 13 independently reviewable phases)
- **Risk**: MED — large net-new UI. Highest-risk areas: sticky-axis + horizontal
  scroll + hover-popup interaction (UI-2/UI-4), and Dash callback re-render cost (UI-12).
- **Depends on**: `plans/026-activity-timeline-implementation.md` Phases 0–2
  (shipped in commit `7f08656`; `GET /api/v1/activity/timeline` and
  `GET /api/v1/activity/suggest` are live).
- **Category**: direction
- **Planned at**: commit `94f6b7a`, 2026-10-02 (revision commit; in-scope source is
  unchanged as of this commit)
- **Branch**: the repo is currently on `feature/activity-timeline-2` (NOT
  `feature/activity-timeline-ui`, as an earlier draft of this plan stated). Work
  on a new branch cut from the current HEAD — see "Git workflow".

> **Plan provenance**: feature design `plans/activity-timeline-feature.md` (decisions log) ·
> superseded backend UI phase in `plans/026-activity-timeline-implementation.md` ·
> visual reference `plans/timeline-samples/03-swimlane-multi-user.html`
> **Route**: `/app/analytics/timeline`

## Why this matters

The Activity Timeline is the first UI over the timeline backend that shipped in
`7f08656`. It lets a leader select up to five people/objects and compare their
chronological activity (commits, PRs, issue/page changes, state history) side by
side. This plan builds that Dash view on top of the already-live API — **no
backend changes**. Everything here is net-new UI, so the risk is concentrated in
layout/CSS mechanics and Dash state handling, not in data correctness. When this
lands, `/app/analytics/timeline` becomes a reachable, themed, deep-linkable page
launched from the Analytics gallery.

---

## Overview

Build the Dash UI for the Activity Timeline on top of the already-shipped backend
(`GET /api/v1/activity/timeline`, `GET /api/v1/activity/suggest`). The view is a
multi-lane swimlane: one vertical column per selected entity, rows bucketed by
day/week/month, idle periods collapsed into expandable separators, and event cards
that reveal detail on hover and open the Graph page on click.

The work is split into **14 deliberately small phases**: the 13 UI phases
(UI-0 … UI-12) plus a dev-only prep phase **UI-2P** (backend mock scenario
fixtures) that lands before UI-2. Each phase is independently reviewable and
tunable before the next begins, matching the manual review cadence used for
backend Phases 0–2.

---

## Progress Legend

```
[ ] = Not started    [~] = In progress    [x] = Complete
```

---

## Design Decisions (locked)

| # | Area | Decision |
|---|------|----------|
| 1 | Axis model | Vertical timeline; idle gaps **compressed** (non-uniform vertical space) |
| 2 | Section model | **Day-bucketed sections**; **global shared rows** across all lanes |
| 3 | Idle gaps | Collapsed slim full-width bar naming the span (e.g. "Mar 11 – 14 · 3 days no activity"), **clickable to expand/collapse** |
| 4 | Lane types | **Any entity type** (Person + objects); soft cap **5 lanes**; min-width 220px; horizontal scroll beyond |
| 5 | Scope | Global **Activity / History** toggle in the toolbar |
| 6 | Entity search | Live debounced typeahead → `/api/v1/activity/suggest` (min 2 chars, ~300 ms) |
| 7 | Selection UI | **Lane headers are the selection** (avatar/icon + label + type tag + ✕); no chip row; "Clear all" link + max-lane hint in the selector bar; **no event count** |
| 8 | Initial state | Empty state + prompt; `?wba_ids=` deep link pre-loads lanes |
| 9 | Toolbar | Range (7/30/90/Custom, default **30**) + Group by (Day/Week/Month, default **Day**) + Scope; **no zoom** |
| 10 | Group by | Sets row granularity + idle-separator unit; **client-side re-bucket, no refetch**. Range/scope changes → refetch |
| 11 | Card | 2 lines: `summary` (fallback if null) then `EntityType(colored) · relationship · time`; lane-color left accent |
| 12 | Card interaction | Hover popup (details + "Open source ↗"); click → **`/app/graph` in a new tab** (entity deep-link later) |
| 13 | Empty cells | Faint dashed lane guide; wholly-empty lane → "No activity in this range" note |
| 14 | Overflow | Cap ~3 cards/cell + **"+N more"** revealing *already-loaded* events only |
| 15 | Pagination | Global **"Load more"** advancing all lanes via per-lane single-lane requests |
| 16 | Loading / errors | Overlay spinner; danger alert preserving last good render |
| 17 | Scroll | Page scrolls; lane headers sticky-top; time axis sticky-left |
| 18 | Theme | Token-driven light/dark via `executive-dashboard.css` |
| 19 | Entry | Analytics gallery card + "Open Visualization" + "Show Options" presets encoded in URL |
| 20 | Deep links | **Inbound only** (`wba_ids`, `range`, `group`, `scope`, `from`, `to`); outbound "View Timeline" buttons deferred |
| 21 | In-day order | Newest-first |
| 22 | Verification | Unit-test pure helpers in pytest; manual-validate visuals per phase |

**Minor defaults (tunable during review):** cell cap **N=3**; lane colors assigned by
selection order from a 5-color palette; unknown entity types → neutral gray; short
type labels (PR / Issue / Commit / Page / Person / …); relationship labels humanized
(`CREATED`→"Created", `STATE_CHANGE`→"Updated"); times rendered in `settings.TIMEZONE`
via the UI formats; the sample's decorative "🏊 swimlane" banner is omitted.

---

## Current state — verified API contract (no backend changes required)

The UI talks to two live endpoints (registered in `src/app/main.py:195`,
`prefix="/api/v1"`). The models below are inlined verbatim from
`src/app/api/activity/v1/model.py`; **use these exact field names** — the UI
helpers and card builders depend on them.

### `GET /api/v1/activity/timeline`

Query params (router `src/app/api/activity/v1/router.py:25-56`):

| Param | Type | Default | Notes |
|-------|------|---------|-------|
| `wba_ids` | str, **required** | — | Comma-separated `{source}::{entity_type}::{id}`, one per lane |
| `scope` | `"activity"` \| `"history"` | `activity` | invalid value → 400 |
| `from` | ISO 8601 datetime | `None` | query alias for `from_` |
| `to` | ISO 8601 datetime | `None` | |
| `cursor` | str | `None` | opaque; applies to **every** lane in the request |
| `limit` | int 1–100 | `20` | events **per lane** |

Response shape (`model.py:50-112`):

```python
class TimelineEvent:
    signal_id: str            # UUID string
    event_time: datetime
    relationship_type: str    # e.g. "CREATED", "REVIEWED"; "STATE_CHANGE" for history
    summary: str | None       # may be None → card must fall back
    entity_type: str          # the *other* side (activity) / own type (history)
    source: str               # "github" | "jira" | "confluence"
    url: str | None           # source-system link
    details: dict             # {} for scope=activity; attribute snapshot for history

class TimelineLane:
    wba_id: str
    entity_type: str
    label: str                # pre-computed display name or raw id
    avatar_url: str | None    # Person only
    events: list[TimelineEvent]
    next_cursor: str | None

class TimelineMeta:
    time_range: {"from": datetime | None, "to": datetime | None}
    total_lanes: int

class TimelineResponse:
    lanes: list[TimelineLane]
    meta: TimelineMeta
```

### `GET /api/v1/activity/suggest`

Query params: `q` (str, **min_length=2**, required), `limit` (int 1–20, default 10).
Response: `{"results": [{wba_id, label, entity_type, source, avatar_url}]}`
(`model.py:115-127`). Suggestions are backed by Elasticsearch. Because `q` is declared
with `min_length=2` at the router (`router.py:132-136`), a query shorter than 2 chars
is rejected with **422** before it reaches the service — the service's own
short-query `[]` guard (`service.py:341-342`) is therefore unreachable over HTTP.
When ES is disabled, the result is an empty `results` list. → The selector must gate
at ≥2 chars client-side (decision #6, and this is *required*, not cosmetic); a 422 on
this call is a client bug, not a transient API failure.

### Constraints the UI must honor (all verified)

1. **Activity-scope events carry no related-entity id.** `TimelineEvent` exposes
   `entity_type` (the *other* side) but not its id; `details` is `{}` for
   `scope=activity` (populated snapshot only for `scope=history`). → Card shows
   `summary`, not "PR #142". (`service.py:158-185`)
2. **No per-lane event count.** `TimelineLane` has no `total_count`. → Lane headers
   show no event count.
3. **Cursor is per-lane, not global.** The request accepts *one* `cursor` that is
   applied to *all* lanes (`service.py:232-247`), while each lane returns its own
   `next_cursor` (`service.py:290-292`). Because the cursor encodes a specific
   lane's `(event_time, row_id)`, a shared cursor across lanes is semantically
   wrong. → Pagination must issue **one single-lane request per lane**, each with its
   own `cursor`. This is the workaround, not an optimization.
4. **`next_cursor` is a may-exist signal, not a has-more signal.** It is emitted
   whenever a lane returned exactly `limit` events (`service.py:291`), even if the
   table has no more rows. A subsequent "Load more" can therefore return zero events;
   the UI must clear that lane's cursor when it gets an empty page (UI-12 edge case).
5. **One invalid `wba_id` fails the whole request.** The router validates every id
   up front and returns **400** with `detail.wba_id` set to the offending key
   (`router.py:69-88`); the service's per-lane skip is unreachable over HTTP. → The
   selector must validate the `{source}::{type}::{id}` shape client-side before
   fetching, and treat a 400 as "drop the named lane, retry once" (UI-11).
6. **History scope** yields synthetic `STATE_CHANGE` events with
   `summary = display_name`, `entity_type` = the lane entity's own type, `url`
   extracted from `attributes.url`, and a populated `details` snapshot
   (`service.py:188-210`).

---

## Global conventions

- **API access:** synchronous `requests.get` inside Dash callbacks, mirroring
  `pages/search.py`. Base URL from `os.getenv("API_BASE_URL", "http://localhost:8000")`;
  timeout from `runtime_settings.get_int("HTTP_REQUEST_TIMEOUT")`. A small
  `pages/timeline/api.py` wrapper centralizes the two calls.
- **Datetime rendering:** `to_app_timezone(dt)` from `app.common.timezone`
  (`src/app/common/timezone.py:16`), then format with
  `runtime_settings.get("UI_DATETIME_FORMAT")` / `get("UI_DATE_FORMAT")` so runtime
  overrides are honored (defaults: `src/app/settings.py:102-103`). Footer shows
  **time only**; popup shows the **full datetime**. Reference pattern:
  `src/app/dash_app/pages/search.py:202`.
- **Colors/typography:** import static styling constants from `app.dash_app.styles`
  (`COLOR_*`/`FONT_*`/`SPACING_*`, e.g. `COLOR_BORDER`, `COLOR_BACKGROUND_WHITE` —
  these are backed by `var(--color-*)` CSS variables, so they follow the runtime theme
  automatically). Entity-type colors reuse the graph-node tokens in `THEME_TOKENS` —
  `graph.node.person`, `graph.node.pull_request`, `graph.node.issue`,
  `graph.node.commit`, `graph.node.page`, `graph.node.epic`, `graph.node.repository`,
  `graph.node.branch`, `graph.node.sprint`, … — with the neutral fallback
  `graph.node.default`. The API sends PascalCase `entity_type` values (`PullRequest`,
  `Page`, `Person`); the token keys are snake_case, so add the explicit mapping helper
  in UI-3. Timeline-specific *rules* live in `executive-dashboard.css` using
  `var(--color-*)` tokens. No hardcoded hex in components.
- **Entity-type / lane color resolution (mirror `pages/search.py` — do not use the
  static token snapshot).** Resolve colors from the **effective graph theme** — base
  tokens ⊕ the operator's Graph-Styling overrides from `/api/v1/graph-themes/effective`
  — not from a static token dict. `get_theme_tokens()` with no argument returns the
  `ACTIVE_THEME = "executive-light"` snapshot (`styles.py:44, 272-277`), which sees
  neither the runtime theme (a CSS class on `#app-shell`, `layout.py:130`) nor
  Graph-Styling overrides. Follow `pages/search.py` instead: a page-level
  `dcc.Store(id="timeline-theme-store")` is populated by a callback
  `Input("theme-store", "data") → fetch_effective_theme(active_theme)`
  (import `fetch_effective_theme` from `app.dash_app.pages.graph.utils`; see
  `search.py:24, 976-986`). The card-render callback takes both
  `Input("theme-store", "data")` and `Input("timeline-theme-store", "data")`. The
  effective doc has shape
  `{"nodes": {<NodeType>: {"background-color": ...}, "default": {...}}, ...}`, keyed by
  the same PascalCase `entity_type` the API sends; look the entity-type color up there
  and **fall back to the base token** (`get_theme_tokens(active_theme)` via
  `entity_type_token`) when the store is `None` — see `search.py:160-177, 1023-1040`.
  The five `timeline.lane.*` lane-accent tokens are not part of the effective doc, so
  resolve those directly from `get_theme_tokens(active_theme)`. Do **not** use the
  module-level `TOKENS` snapshot for per-entity or lane colors. Without this, colors
  are stale after a dark-mode toggle *and* diverge from the Graph and Search pages
  whenever Graph-Styling overrides are set.
- **Lane palette:** the five lane-accent tokens `timeline.lane.1` … `timeline.lane.5`
  are added to `THEME_TOKENS` (both themes) in **UI-1**, not UI-10; UI-10 only
  calibrates dark-theme variants. `assign_lane_colors(n)` returns token **keys**,
  resolved to colors through the active-theme mechanism above. The graph palette is
  deliberately theme-invariant (`styles.py:191`), so lane values may be shared across
  themes — but the tokens must still live in `THEME_TOKENS` to satisfy the
  no-hardcoded-hex criterion.
- **Typing:** CI runs `mypy src/` in strict mode. Annotate every function's parameters
  and return type; start each module with `from __future__ import annotations`.
  Heterogeneous Dash callback signatures follow the existing `Any` convention (see
  `pages/analytics.py:451-495`).
- **Dark theme mechanism:** the shell element carries `theme-executive-light` /
  `theme-executive-dark` classes (`layout.py:130`); dark overrides in
  `executive-dashboard.css` are scoped under `.theme-executive-dark` (see the
  `:root[data-theme="executive-light"]` / `.theme-executive-dark` blocks at
  `executive-dashboard.css:6` and `:83`). Write timeline dark rules the same way —
  do **not** invent a new theme switch.
- **State:** `dcc.Store` components (prefixed `timeline-`) hold selection, params,
  fetched lanes/cursors, expansion state, and the effective-theme payload
  (`timeline-theme-store`). No URL writes in v1.
- **IDs:** all timeline components prefixed `timeline-` to avoid collisions in the
  single-page Dash app.
- **Naming:** page package `src/app/dash_app/pages/timeline/` with `layout.py`
  (view builders), `callbacks.py` (Dash callbacks), `helpers.py` (pure, unit-testable
  functions), `api.py` (HTTP wrapper), `__init__.py`.

---

## Commands you will need

Run all commands from the repo root with the virtualenv active
(`source .venv/bin/activate`). **Never start the app server yourself** — the app
runs via Docker and is owned by the operator.

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Unit tests (this plan) | `pytest -m unit tests/test_activity_timeline_ui_helpers.py -q` | exit 0, all pass |
| All unit tests (regression) | `pytest -m unit tests -q` | exit 0, no new failures |
| Typecheck | `mypy src/` | exit 0, no errors |
| Lint (repo gate) | `pylint src --score=y` | repo score ≥ 9.0 (not lower than before) |
| Security scan | `bandit -c .bandit.yml -r src/ -lll` | no High-severity findings |
| Run the app | **ask the operator to (re)start the Docker stack** (`docker compose up -d`) — do not run `uvicorn` yourself | UI served at http://localhost:8000/app |
| Open the page | http://localhost:8000/app/analytics/timeline | timeline page renders |

`.github/workflows/pr_checks.yml` runs four blocking jobs on every PR: `pytest -m unit
tests`, `mypy src/`, `pylint src` (fails below a repo score of 9.0), and bandit (fails
on High severity). `mypy.ini` is `strict = True` with `disallow_untyped_defs` /
`disallow_untyped_calls`; the only relaxation covering this tree is
`[mypy-app.dash_app.*]` disabling `return-value, index, union-attr`. **Every new
function must be fully annotated** or CI fails. Backend migrations are **not** part of
this plan.

## Per-phase verification convention

Every phase below lists **Unit tests** (pure helper tests) and **Manual validation**
(visual acceptance). Apply this convention to each phase:

- Put every phase's unit tests in `tests/test_activity_timeline_ui_helpers.py`, with
  `pytestmark = pytest.mark.unit` at module top (model after `tests/test_analytics_page.py`).
  Helper modules are importable in tests because `pytest.ini` sets
  `pythonpath = src . tests` — e.g. `from app.dash_app.pages.timeline.helpers import bucket_by_period`.
- Verify each phase with `pytest -m unit tests/test_activity_timeline_ui_helpers.py -q`;
  expected: all collected pass, 0 failures. A phase is **not done** until its unit
  tests pass and its `V*` items are manually confirmed with the app running — ask
  the operator to restart it via Docker first; never launch the server yourself.
- If a phase adds no pure helper (e.g. UI-0), its manual `V*` items are the gate.

## Scope

**In scope** — exactly these files:

- **New:** `src/app/dash_app/pages/timeline/{__init__,layout,callbacks,helpers,api}.py`,
  `tests/test_activity_timeline_ui_helpers.py`.
- **New (UI-2P, dev-only):** `src/app/api/activity/v1/mock_data.py`,
  `tests/test_activity_timeline_mock.py`.
- **Modified:** `src/app/analytics/registry.py`, `src/app/dash_app/layout.py`,
  `src/app/dash_app/pages/analytics.py`,
  `src/app/dash_app/assets/executive-dashboard.css`,
  `src/app/dash_app/styles.py` (lane palette tokens in UI-1; dark variants in UI-10).
- **Modified (UI-2P, dev-only):** `src/app/api/activity/v1/service.py`,
  `src/app/api/activity/v1/router.py`, `src/app/settings.py`, `.env.example`.

**Out of scope** — do NOT touch, even if related:

- **Backend data/logic code** — with ONE exception: the dev-only mock in phase
  **UI-2P** may add `src/app/api/activity/v1/mock_data.py` and thread an optional
  `?mock=` switch through `service.py` / `router.py` (+ its settings/env entries).
  Nothing else under `src/app/api/**`, `src/app/db/**`, or migrations may change; the
  API's response contract stays frozen and the mock is default-off.
- `src/app/dash_app/pages/graph/**`, `pages/search.py`, `pages/collaboration_network/**`
  — other pages stay untouched beyond adding the gallery card/route wiring.
- Outbound deep-links from other pages ("View Timeline" buttons) and any Playwright/e2e
  suite — deferred (see "Deferred").

## Git workflow

- Branch: create `feat/activity-timeline-ui` from the current HEAD
  (`git switch -c feat/activity-timeline-ui`). Do not work directly on
  `feature/activity-timeline-2` or `main`.
- Commit per phase using short imperative subjects, matching recent history
  (e.g. `Activity timeline UI-0: scaffold, route & gallery entry`). Recent subjects
  are plain imperative sentences — not Conventional Commits.
- Do **not** push or open a PR unless the operator instructs it.

## Global done criteria (ALL must hold when the whole plan lands)

- [ ] `pytest -m unit tests -q` exits 0 with the new helper tests passing.
- [ ] `mypy src/` exits 0; `pylint src --score=y` reports a score ≥ 9.0 and not lower
      than before the change.
- [ ] `/app/analytics/timeline` renders from the Analytics gallery card and via the
      direct route; every `V*` item for every executed phase was manually checked.
- [ ] Toggling the topbar theme re-renders entity-type and lane colors (no stale
      light-theme hex remains on cards in dark mode).
- [ ] `git status` shows no files modified outside the Scope list.
- [ ] No hardcoded hex in timeline components:
      `grep -rnE '#[0-9a-fA-F]{6}' src/app/dash_app/pages/timeline/` returns nothing.
- [ ] `plans/README.md` status row for plan 027 updated.

## STOP conditions

Stop and report back (do not improvise) if:

- The live API response does not match the "Current state" contract (e.g. a field is
  renamed or `next_cursor` semantics differ) — the codebase has drifted.
- `dash_clientside.set_props` is unavailable in the installed Dash version
  (`requirements.app.txt` pins `dash==4.4.1`; `set_props` needs ≥ 2.16). **Report the
  constraint** — do not fall back to a CSS-clipped popup and do **not** add
  `overflow: visible` to lane cells (it breaks horizontal scroll) or remove horizontal
  scroll.
- A phase appears to require a backend change or a file outside the Scope list.
  (The only sanctioned backend change is the dev-only mock in phase **UI-2P** — see Scope.)
- A step's verification fails twice after a reasonable fix attempt.

## Maintenance notes

- **Pagination coupling:** UI-9 depends on the per-lane cursor workaround. If the
  backend later adds a true multi-lane cursor (deferred), replace the per-lane loop in
  `callbacks.py` and delete the "one request per lane" comment.
- **`next_cursor` is optimistic:** a lane can report a cursor when no further rows
  exist. UI-12 handles the empty-page case; any future pager must too.
- **Entity-type colors** are keyed by PascalCase API values mapped to snake_case
  tokens in UI-3's helper. Adding a new entity type means adding a mapping entry;
  unmapped types intentionally fall back to `graph.node.default`.
- **Reviewer focus:** verify the sticky axis/header does not clip the hover popup, that
  keyboard focus opens the popup, and that "Load more" issues per-lane requests (not a
  single multi-lane request).

---

## Phases

### UI-0 — Page scaffold, route & gallery entry (est. 0.5 day)

**Objective:** A reachable, empty page. No data fetching.

**Progress:** [x] Complete

#### Files

| File | Action | Purpose |
|------|--------|---------|
| `src/app/dash_app/pages/timeline/__init__.py` | Create | Re-export `get_layout` + import `callbacks` to register them |
| `src/app/dash_app/pages/timeline/callbacks.py` | Create | Docstring-only stub (filled in UI-1); `__init__` import target |
| `src/app/dash_app/pages/timeline/layout.py` | Create | Header + empty state + placeholder stores |
| `src/app/analytics/registry.py` | Modify | Add `TimelineAnalytic` dataclass + `TIMELINE_ANALYTIC` |
| `src/app/dash_app/layout.py` | Modify | Route `/app/analytics/timeline` |
| `src/app/dash_app/pages/analytics.py` | Modify | Render timeline card + `_create_timeline_controls()` |

#### Tasks

- [x] **1.** Create the package files. `src/app/dash_app/pages/timeline/callbacks.py`
      is a **docstring-only stub** at this phase (UI-1 fills it in); it must exist so
      the package imports cleanly. `src/app/dash_app/pages/timeline/__init__.py`:

      ```python
      """Activity Timeline page package.

      Exposes get_layout() and registers all Dash callbacks on import.
      """

      __all__ = ["get_layout"]

      from app.dash_app.pages.timeline.layout import get_layout
      from app.dash_app.pages.timeline import callbacks  # noqa: F401
      ```

      The `callbacks` import is **required**: module-level `@callback`s in
      `callbacks.py` register only when that module is imported (repo convention —
      see `pages/collaboration_network/__init__.py:13`,
      `pages/connectors/__init__.py:10`). Without it the page still renders (because
      `suppress_callback_exceptions=True`) but **every interaction silently does
      nothing**. `layout.py` must **not** import `callbacks` (circular import — same
      rationale as `pages/collaboration_network/layout.py:1-5`).
- [x] **2.** Create `TimelineAnalytic` in `src/app/analytics/registry.py` — do **not**
      reuse `GraphAnalytic` (its `.href` property generates `/app/graph?mode=<key>`,
      which is wrong for this page — see `registry.py:19-22`). Add exactly:

      ```python
      @dataclass(frozen=True)
      class TimelineAnalytic:
          """Metadata for the activity timeline visualization."""
          key: str
          title: str
          description: str
          icon: str

          @property
          def href(self) -> str:
              return "/app/analytics/timeline"

      TIMELINE_ANALYTIC = TimelineAnalytic(
          key="activity_timeline",
          title="Activity Timeline",
          description=(
              "Visualize the chronological activity of persons and objects "
              "across GitHub, Jira, and Confluence in a side-by-side swimlane view."
          ),
          icon="fas fa-timeline",
      )
      ```

      Do **not** append `TIMELINE_ANALYTIC` to `GRAPH_ANALYTICS` (that list drives
      graph-mode analytics, `registry.py:36-38`); render it separately (Task 5).
- [x] **3.** In `layout.py`, add `timeline` to the **existing top-level page import**
      (`layout.py:10`) so its callbacks register at app startup — the file imports
      every other page this way, and a deferred import would register the timeline
      `@callback`s only on first navigation (exactly the silent-no-op failure mode
      that `suppress_callback_exceptions=True` hides):
      ```python
      from app.dash_app.pages import analytics, chat, collaboration_network, connectors, graph, search, settings, timeline
      ```
      Then add the route branch:
      ```python
      if pathname == "/app/analytics/timeline":
          return timeline.get_layout()
      ```
- [x] **4.** `get_layout()` returns: `create_page_header([("Analytics", "/app/analytics"), ("Timeline", None)], …)`, a selector bar placeholder, and an empty state via `create_empty_state("Add people or objects to compare their activity.")`.
- [x] **5.** In `analytics.py`, render `TIMELINE_ANALYTIC` alongside `GRAPH_ANALYTICS`.
      **Do not append it to `GRAPH_ANALYTICS`** — that list feeds
      `GRAPH_ANALYTICS_BY_KEY` (`registry.py:41`) and graph-mode routing. Instead make
      three explicit changes to `pages/analytics.py`:
      - first, add the symbol to the existing registry import at
        `analytics.py:21` — change
        `from app.analytics.registry import GRAPH_ANALYTICS` to
        `from app.analytics.registry import GRAPH_ANALYTICS, TIMELINE_ANALYTIC`.
        (Without this, `TIMELINE_ANALYTIC` is a `NameError` at import and the whole
        app fails to start.) Verify with
        `PYTHONPATH=src python -c "import app.dash_app.pages.analytics"` → exit 0.
      - change the gallery loop in `get_layout()` (`analytics.py:59`) to iterate the
        concatenation:
        ```python
        for analytic in [*GRAPH_ANALYTICS, TIMELINE_ANALYTIC]:
        ```
      - expand the two-branch ternary in `_create_analytic_card`
        (`analytics.py:70-77`) into an if/elif/else:
        ```python
        if analytic.key == "collaboration_network":
            footer = _create_collaboration_controls()
        elif analytic.key == "activity_timeline":
            footer = _create_timeline_controls()
        else:
            footer = dbc.Button("Open Visualization", href=analytic.href, color="primary", size="sm")
        ```
- [x] **6.** `_create_timeline_controls()` mirrors `_create_collaboration_controls()`:
      "Open Visualization" (href `/app/analytics/timeline`) + "Show Options" collapse
      containing Default Range / Group by / View selects. Use `timeline-`-prefixed ids
      (e.g. `timeline-open-btn`, `timeline-controls-toggle-btn`,
      `timeline-controls-collapse`) — the gallery renders every card on one page, so
      ids must not collide with the `collab-*` controls. A callback builds the href
      with `urlencode({"range": …, "group": …, "scope": …})`. (URL is consumed in
      UI-11; until then it simply navigates.)

#### Unit tests

- [x] `test_timeline_analytic_href` — `TIMELINE_ANALYTIC.href == "/app/analytics/timeline"`.
- [x] `test_timeline_layout_renders` — `get_layout()` returns an `html.Div` without error.

#### Manual validation

- [x] **V0.1** `/app/analytics` shows the "Activity Timeline" card next to "Collaboration Network".
- [x] **V0.2** "Show Options" expands with Range/Group/View selects.
- [x] **V0.3** "Open Visualization" navigates to `/app/analytics/timeline` and renders the header + empty state.
- [x] **V0.4** The timeline package imports cleanly (no `ModuleNotFoundError` for
      `callbacks`) and the page loads with no browser-console error. From UI-1 onward,
      also confirm `timeline-`-prefixed callbacks are registered (see the UI-1 unit
      test `test_timeline_callbacks_registered`).

---

### UI-1 — Entity selector (search box) & lane headers (est. 1 day)

**Objective:** Add/remove entities; lanes render as empty columns. No events yet.

**Progress:** [x] Complete

#### Files

| File | Action | Purpose |
|------|--------|---------|
| `src/app/dash_app/pages/timeline/api.py` | Create | `fetch_suggestions(q)` |
| `src/app/dash_app/pages/timeline/helpers.py` | Create | `assign_lane_colors`, `entity_type_label`, dedup/add/remove helpers |
| `src/app/dash_app/pages/timeline/layout.py` | Modify | Selector bar + lane-header row |
| `src/app/dash_app/pages/timeline/callbacks.py` | Modify | Fill the UI-0 stub: typeahead, add/remove, clear-all, max-lane hint |
| `src/app/dash_app/styles.py` | Modify | Add `timeline.lane.1`–`.5` tokens to `THEME_TOKENS` (both themes) |

#### Tasks

- [x] **1. Selector bar:** `dbc.Input(id="timeline-search-input")` + a results
      dropdown container. Debounce ~300 ms via `dcc.Store` + a clientside callback that
      returns `no_update` until idle (mirror `graph` spotlight debounce), min 2 chars.
      The ≥2-char gate is **required**, not cosmetic: `/api/v1/activity/suggest`
      declares `q` with `min_length=2` (`router.py:132-136`), so a shorter query
      returns **422**, not an empty result.
- [x] **2. Suggestions:** on debounced input → `fetch_suggestions(q)` →
      `GET /api/v1/activity/suggest?q=…` → render up to 10 rows (avatar/type icon +
      label + type tag + source). Click adds; Enter adds the top result.
- [x] **3. Selection store:** `timeline-selected-store` = ordered list of
      `{wba_id, label, entity_type, source, avatar_url}`. Adding is idempotent.
- [x] **4. Lane headers:** render one header per selected entity —
      avatar (`avatar_url`) or entity-type `fas` icon, label, type tag, ✕ remove.
      Left column of fixed width for the time-axis label. Headers **are** the
      selection; no chip row.
- [x] **5. Limits:** soft cap 5; at 5 disable the input and show the inline hint
      "🔒 Maximum 5 lanes — remove one first". "Clear all" text link appears when ≥1 lane.
- [x] **6. Colors:** add five lane-accent tokens `timeline.lane.1` … `timeline.lane.5`
      to `THEME_TOKENS` in `src/app/dash_app/styles.py`, for **both** themes (values may
      be shared across themes — the graph palette is deliberately theme-invariant,
      `styles.py:191`). `assign_lane_colors(n)` returns the first *n* token **keys**
      (not hex), reassigned on removal so colors stay distinct; resolve them to colors
      via the active-theme mechanism in "Global conventions".

#### Unit tests

- [x] `test_assign_lane_colors_distinct` — no duplicate colors up to 5.
- [x] `test_entity_type_label_mapping` — `PullRequest→"PR"`, unknown→raw type.
- [x] `test_selection_add_remove_dedup` — re-adding the same `wba_id` is a no-op; remove drops it.
- [x] `test_timeline_callbacks_registered` — after importing
      `app.dash_app.pages.timeline`, assert
      `any("timeline-" in key for key in dash._callback.GLOBAL_CALLBACK_MAP)`
      (guards the UI-0 `__init__` → `callbacks` import). Module-level
      `@callback`/`clientside_callback` registrations land in
      `dash._callback.GLOBAL_CALLBACK_MAP` in the pinned `dash==4.4.1`;
      **`dash.callback_map` does not exist** (it raises `AttributeError`/`ImportError`).
      Reading `create_dash_app().callback_map` is the alternative but pulls in app
      settings/env — prefer the global map.

#### Manual validation

- [x] **V1.1** Typing ≥2 chars shows suggestions; clicking adds a lane header.
- [x] **V1.2** Adding a 6th is blocked with the inline hint.
- [x] **V1.3** ✕ removes a lane; "Clear all" empties the view back to the empty state.
- [x] **V1.4** Lane headers show avatar/icon + label + type tag; no count.

**Additional manual checks (added during implementation, verified by operator):**

- [x] **V1.5** Arrow Up/Down move a highlight through the suggestions and Enter adds
      the highlighted entity (the row the user sees selected, consistently).
- [x] **V1.6** Only the active suggestion row's background changes; other rows are
      unaffected.
- [x] **V1.7** Escape clears the search text and dismisses the dropdown immediately.

> Implementation note: keyboard navigation, Escape-to-clear, and the highlight are
> driven by a single install-once clientside `keydown` listener (Dash cannot bind
> callbacks to DOM key events). The active row is tracked by element reference and
> reset on any list re-render via a `MutationObserver`; `Enter` clicks that exact
> element rather than an index. The input's `n_submit` is deliberately *not* a
> server trigger, so there is no dual-trigger race. A hand-rolled list was used
> (rather than `dcc.Dropdown`) to keep the server-side `/activity/suggest`
> typeahead and custom rows; the keyboard/ARIA layer is ours to maintain.

---

### UI-2P — Backend mock scenario fixtures (dev-only prep) (est. 0.5 day)

**Objective:** A default-off, deterministic mock served by the *real* activity API
so manual QA can reproduce activity shapes that real data will not contain
(30-day gaps, 100-event spikes, empty lanes, non-aligned gaps, pagination,
failures).

**Progress:** [~] In progress (implementation + unit tests done; manual V2P pending)

**Depends on:** nothing (may land before UI-2). **Unblocks:** manual validation for
UI-2 / UI-5 / UI-8 / UI-9 / UI-12.

#### Files

| File | Action | Purpose |
|------|--------|---------|
| `src/app/api/activity/v1/mock_data.py` | Create | Scenario registry + deterministic generators |
| `tests/test_activity_timeline_mock.py` | Create | Unit tests for the mock contract |
| `src/app/api/activity/v1/service.py` | Modify | Gate `get_timeline` / `get_suggestions` on the scenario |
| `src/app/api/activity/v1/router.py` | Modify | Optional `?mock=<scenario>` switch on both endpoints |
| `src/app/settings.py` | Modify | `TIMELINE_MOCK_SCENARIO: str = ""` |
| `.env.example` | Modify | Documented, commented-out `TIMELINE_MOCK_SCENARIO` |

#### Tasks

- [x] **1. Activation (default-off).** Blank `TIMELINE_MOCK_SCENARIO` ⇒ mock mode
      OFF (real data, unchanged). Set to a registered scenario ⇒ ON. `?mock=<scenario>`
      may *switch* the scenario per request but can never enable mock mode on its own.
      Unknown names raise a clear error (surfaced as 500).
- [x] **2. Scenario catalog (15).** `even`, `empty_range`, `empty_lane`, `gaps_small`,
      `gaps_global`, `gap_30d`, `gaps_staggered`, `spike_100`, `cell_boundary`,
      `time_edges`, `card_variety`, `history`, `pagination`, `error_500`,
      `suggest_variants`.
- [x] **3. Determinism.** Stable UUID5 `signal_id`s; times are offsets from the range
      end, clamped to `[from, to]`; the same scenario + request is byte-identical.
- [x] **4. Contract fidelity.** Returns real `TimelineResponse` / `SuggestResponse`
      models, so serialization matches the live API. `scope=history` yields
      `STATE_CHANGE` events with populated `details`. `error_500` raises inside the
      service so the router's real 500 path runs. Events newest-first.
- [x] **5. Pagination.** `pagination` gives lane 0 three pages, lane 1 exactly `limit`
      events (the *optimistic cursor* trap: a full page emits `next_cursor`, the next
      request returns an empty page and clears it), lane 2 a short page. Cursor format
      matches `service._encode_cursor`, so `service.validate_cursor` accepts it.
- [x] **6. Suggestions.** `suggest_variants` returns a fixed catalogue (Person with and
      without avatar, PullRequest, Issue, Page), filtered by query substring; the
      literal query `none` returns `[]`.
- [x] **7. Safety.** Startup `logger.warning` when mock mode is active; every mocked
      response logs its scenario. No production guard (operator decision) — the flag
      must never be set in a real deployment.

#### Unit tests

`tests/test_activity_timeline_mock.py` (`pytestmark = pytest.mark.unit`):

- [x] `test_every_scenario_builds` — one lane per requested `wba_id`, all 15 scenarios.
- [x] `test_error_scenario_raises` — `error_500` raises.
- [x] `test_output_is_deterministic` — identical signal ids across two builds.
- [x] `test_events_stay_within_range`.
- [x] `test_empty_range_and_empty_lane`.
- [x] `test_history_scope_markers`.
- [x] `test_pagination_cursor_round_trips` — mock cursors pass `service.validate_cursor`.
- [x] `test_pagination_optimistic_cursor_lane`.
- [x] `test_suggestions_filter_and_empty`.
- [x] `test_resolve_scenario_gate` — env enables; override only switches.

#### Manual validation

- [ ] **V2P.1** With `TIMELINE_MOCK_SCENARIO` unset, `/api/v1/activity/timeline`
      behaves exactly as before (real data).
- [ ] **V2P.2** With `TIMELINE_MOCK_SCENARIO=even` and the app restarted, the timeline
      UI renders the scenario's lanes for the selected entities.
- [ ] **V2P.3** `?mock=gap_30d` shows a 30-day gap; `?mock=error_500` returns HTTP 500
      (and the UI shows the danger alert without losing the last good render).
- [ ] **V2P.4** Existing unit/integration suites are unaffected (default off).

> Scenarios are anchored to the selected range: `gap_30d` needs **Last 90 days**;
> `spike_100` / `cell_boundary` need a per-lane `limit` ≥ 20. The `?mock=` switch is
> reachable from the UI only once UI-2 forwards it from the page URL (UI-2 task 8);
> until then use it directly against the API.

---

### UI-2 — Data fetch, day bucketing & swimlane skeleton (est. 1 day)

**Objective:** Fetch events for all lanes, bucket by day, render the shared-row grid
with placeholder cards. Loading + error handling.

**Progress:** [ ] Not started

#### Files

| File | Action | Purpose |
|------|--------|---------|
| `src/app/dash_app/pages/timeline/api.py` | Modify | `fetch_timeline(wba_ids, scope, from, to, limit)` |
| `src/app/dash_app/pages/timeline/helpers.py` | Modify | `bucket_by_period`, `find_idle_runs`, `build_grid` |
| `src/app/dash_app/pages/timeline/layout.py` | Modify | Grid containers, loading overlay, alert slot |
| `src/app/dash_app/pages/timeline/callbacks.py` | Modify | Fetch on selection change |

#### Tasks

- [ ] **1.** `fetch_timeline` calls `GET /api/v1/activity/timeline?wba_ids=…&scope=…&from=…&to=…&limit=20`;
      returns parsed `lanes` + `meta`. Default range = last 30 days, scope = activity.
- [ ] **2.** Store `timeline-data-store`: `{lanes: [{wba_id, label, avatar_url, entity_type, events, next_cursor}], params, time_range}`.
- [ ] **3.** `bucket_by_period(lanes, granularity)` → ordered list of *period rows*
      (union of all lanes' buckets), each row = `{period_key, label, cells: {wba_id: [events]}}`.
      Rows sorted newest-first; events newest-first within a cell.
- [ ] **4.** `find_idle_runs(rows, granularity)` → maximal runs of periods with no
      events in any lane (used in UI-5; skeleton can render them as plain rows first).
- [ ] **5.** Render the grid: fixed-width left time-axis column with period labels;
      one fluid lane column per entity (min-width 220px; horizontal scroll when
      exceeded). Lane-header row sticky-top; time-axis sticky-left.
- [ ] **6.** Render placeholder card boxes (summary text only) to validate layout.
- [ ] **7.** Loading overlay via `create_loading_overlay_container` +
      `register_loading_overlay_hider`; on API error show `create_alert(..., "danger")`
      above the grid and keep the last good render.
- [ ] **8. Mock passthrough (QA convenience).** Read the page URL
      (`Input("url", "search")`), extract a `mock=<scenario>` value, and forward it as
      the `mock` query param on `fetch_timeline` (and `fetch_suggestions`). This makes
      `?mock=gap_30d` switch mock scenarios live for visual QA without a restart.
      No-op when the param is absent or when the server's mock mode is off. This is
      the minimal hook UI-11 later generalises into full deep-link parsing.

#### Unit tests

- [ ] `test_bucket_by_period_day` — events map to the correct calendar day (window timezone).
- [ ] `test_build_grid_union_rows` — rows are the union across lanes; empty cells present.
- [ ] `test_find_idle_runs` — maximal runs detected, boundary days excluded.
- [ ] `test_event_order_newest_first` — events within a cell sorted descending.

#### Manual validation

- [ ] **V2.1** Adding two people renders two aligned columns of day rows.
- [ ] **V2.2** A day active for one lane and idle for another shows an empty cell (not a missing row).
- [ ] **V2.3** Header row stays pinned while scrolling down; time axis pinned while scrolling right (≥6 lanes → horizontal scroll).
- [ ] **V2.4** API failure shows the danger alert and preserves the previous grid.

---

### UI-3 — Event card design (est. 1 day)

**Objective:** The real 2-line card with colors, formatting, and truncation.

**Progress:** [ ] Not started

#### Files

| File | Action | Purpose |
|------|--------|---------|
| `src/app/dash_app/pages/timeline/layout.py` | Modify | `_event_card(event, lane_color)` |
| `src/app/dash_app/pages/timeline/helpers.py` | Modify | `humanize_relationship`, `card_summary`, `entity_type_token` |
| `src/app/dash_app/assets/executive-dashboard.css` | Modify | `.timeline-card*` rules |

#### Tasks

- [ ] **1.** Card: left accent border in the **lane color**; line 1 = `summary`,
      one line, ellipsised; fallback when null = humanized relationship + entity type.
- [ ] **2.** Line 2 = `<EntityType (colored)> · <relationship> · <time>` — e.g.
      `PR · Created · 2:30 PM`. Color the type via a new pure helper
      `entity_type_token(entity_type) -> str`: lower-case and snake_case the PascalCase
      API value (`PullRequest`→`graph.node.pull_request`, `Page`→`graph.node.page`,
      `Person`→`graph.node.person`, `Issue`→`graph.node.issue`, `Commit`→
      `graph.node.commit`, `Epic`→`graph.node.epic`, `Repository`→
      `graph.node.repository`), and return `graph.node.default` for anything unmapped.
      `entity_type_token` returns the base token **key**, used only as the fallback.
      Resolve the actual color from the effective theme store, mirroring
      `search.py:160-177`: look up
      `effective["nodes"][entity_type]["background-color"]` (the API's PascalCase
      `entity_type` is the effective-doc key), and only when the store is `None` or
      that type is absent fall back to
      `get_theme_tokens(active_theme)[entity_type_token(entity_type)]`. The
      card-rendering callback takes `Input("theme-store", "data")` and
      `Input("timeline-theme-store", "data")` (see "Global conventions → Entity-type /
      lane color resolution"). Do **not** call `get_theme_tokens()` with no argument —
      it returns the static light-theme snapshot and will not follow a dark-mode toggle
      or Graph-Styling overrides. Relationship humanized to Title Case via
      `humanize_relationship` (`relationship_type` is the API field name).
- [ ] **3.** Time rendered from `event_time` via `to_app_timezone` + `UI_DATE_FORMAT`-time
      (time only). Full datetime reserved for the popup.
- [ ] **4.** Fixed/semi-fixed card height; `text-overflow: ellipsis` on the summary;
      tooltip via `title` as a fallback when hover popup is unavailable (touch).

#### Unit tests

- [ ] `test_humanize_relationship` — `CREATED→"Created"`, `STATE_CHANGE→"Updated"`.
- [ ] `test_card_summary_fallback` — null summary falls back to relationship + type.
- [ ] `test_entity_type_token_mapping` — `PullRequest→"graph.node.pull_request"`,
      `Page→"graph.node.page"`; an unknown type returns `"graph.node.default"`.

#### Manual validation

- [ ] **V3.1** Cards show summary + colored type + relationship + time.
- [ ] **V3.2** Long summaries truncate with an ellipsis; no overflow.
- [ ] **V3.3** Lane accent matches the lane header color; type colors are distinct (PR/Issue/Commit/Page).
- [ ] **V3.4** `scope=history` cards read "Updated" (STATE_CHANGE) with the lane's own type.

---

### UI-4 — Hover popup & click-to-Graph (est. 0.5 day)

**Objective:** Detail popup on hover/focus; click opens the Graph page.

**Progress:** [ ] Not started

#### Files

| File | Action | Purpose |
|------|--------|---------|
| `src/app/dash_app/pages/timeline/layout.py` | Modify | Card anchor; popup portal + data attributes |
| `src/app/dash_app/pages/timeline/helpers.py` | Modify | `popup_fields(event)` |
| `src/app/dash_app/assets/executive-dashboard.css` | Modify | `.timeline-popup-portal` styles |

#### Tasks

- [ ] **1.** Wrap each card in `html.A(href="/app/graph", target="_blank", rel="noopener noreferrer")` — whole card clickable to Graph, new tab.
- [ ] **2.** Popup content: `summary`, humanized relationship, entity type, source,
      full datetime (`UI_DATETIME_FORMAT`), and an "Open source ↗" link to `event.url`
      (rendered only when `url` is present). `scope=activity` detail is limited (no
      attributes); `scope=history` may show key attributes from `details`.
- [ ] **3. Popup placement (do NOT use a CSS-only clipping workaround).** The lane grid
      scrolls horizontally (`overflow-x: auto`), which clips any popup rendered inside
      a cell — and CSS `:hover` cannot know a card's viewport position, so a
      `bottom:100%`/`top:100%` "flip" rule is not implementable in CSS. Instead:
      - Render **one** popup portal `html.Div(id="timeline-popup-portal")` as a direct
        child of the page root, **outside** the scrolling grid.
      - Give each card its detail payload via a data attribute, e.g.
        `html.A(..., **{"data-timeline-event": json.dumps(popup_fields(...))})`.
      - **Mechanism (Dash cannot bind a callback to a DOM event, so install the
        listeners once and drive the portal imperatively).** Register one
        `clientside_callback` with a dummy `Output` and
        `prevent_initial_call=False`; its JS runs on page load and installs a single
        set of delegated listeners on `document` (`mouseover`, `focusin`, `mouseout`,
        `focusout`, `scroll`, `resize`, and `keydown` for Escape), guarded by a
        `window.__timelinePopupWired` flag so a re-render does not attach duplicates.
        The `mouseover`/`focusin` handler reads `data-timeline-event` off the closest
        card to the event target, then calls
        `window.dash_clientside.set_props("timeline-popup-portal", {children: …,
        style: …})` — `set_props` (Dash ≥ 2.16; this repo pins `dash==4.4.1`) is how
        the portal is filled, positioned, and hidden without an `Input`. Position
        `position: fixed` from `target.getBoundingClientRect()`, choosing above/below
        by which half of the viewport the card occupies. Hide via `set_props` on
        `mouseout`/`focusout`, `scroll`, `resize`, and Escape.
      - The portal sits at a high `z-index` at page level, so it is never clipped by
        the grid. Do **not** add `overflow: visible` to lane cells (it would break
        horizontal scroll).
- [ ] **4.** "Open source ↗" is an `<a href="{event.url}">` inside the portal; it must
      not trigger the card's Graph navigation (the card anchor is the click target and
      the portal is outside it, so propagation is naturally isolated — verify this
      holds).
- [ ] **5. Safety & robustness (do not skip).** Build the portal's contents with
      `document.createElement` + `textContent` — **never `innerHTML`** — because
      `summary`, `label`, and `url` originate from ingested source data and would be an
      injection vector if interpolated into markup. Hide the portal on the grid's
      `scroll` event and on window `resize` (a `position: fixed` popup does not follow
      its target when the scroll container moves). Give the portal `role="tooltip"`
      and set/remove `aria-describedby` on the hovered card so screen readers announce
      it; `Escape` hides it.

#### Unit tests

- [ ] `test_popup_fields_from_event` — popup builder includes source link only when url present.

The portal's listener/`set_props` JS is vanilla DOM code and is **not unit-testable**;
UI-4 is verified by the `V4.*` items only.

#### Manual validation

- [ ] **V4.1** Hovering a card shows the popup with full details; it is not clipped by neighbours.
- [ ] **V4.2** Clicking a card opens `/app/graph` in a new tab.
- [ ] **V4.3** "Open source ↗" opens the event URL instead of Graph.
- [ ] **V4.4** Tab-focusing a card shows the popup (keyboard).

---

### UI-5 — Empty cells, empty lanes & idle separators (est. 1 day)

**Objective:** The idle/emptiness language: dashed guides, empty-lane note, expandable gaps.

**Progress:** [ ] Not started

#### Files

| File | Action | Purpose |
|------|--------|---------|
| `src/app/dash_app/pages/timeline/helpers.py` | Modify | idle-run span labels, expansion state merge |
| `src/app/dash_app/pages/timeline/layout.py` | Modify | Idle bar, dashed guide, empty-lane note |
| `src/app/dash_app/pages/timeline/callbacks.py` | Modify | Toggle idle-run expansion |

#### Tasks

- [ ] **1.** Empty cell: blank cell with a faint **dashed vertical guide line**
      continuing the lane column through the gap.
- [ ] **2.** Wholly-empty lane: centered faint note "No activity in this range"
      aligned to the top of the column; header still renders.
- [ ] **3.** Idle run: slim full-width bar spanning all lanes with a centered label
      naming the span (e.g. `· Mar 11 – 14 · 3 days no activity ·`) and a ⌄ affordance.
      Label unit follows the current Group by (days / weeks / months).
- [ ] **4.** Click toggles expansion: expanded runs render as normal (empty) period
      rows; state held in `timeline-expanded-runs-store` (set of run keys) so it
      survives re-renders. Default collapsed.
- [ ] **5.** Runs are computed only over periods currently loaded; expanding a run
      does not fetch from the server (that remains "Load more").

#### Unit tests

- [ ] `test_idle_run_label_days_weeks_months` — correct unit + count per granularity.
- [ ] `test_idle_expansion_toggle` — toggling a run key expands only that run.

#### Manual validation

- [ ] **V5.1** A multi-day gap collapses to a slim bar naming the date span.
- [ ] **V5.2** Clicking the bar expands the hidden days as empty rows; clicking again collapses.
- [ ] **V5.3** An entity selected with no activity in range shows the "No activity in this range" note.
- [ ] **V5.4** Idle gaps in only one lane do **not** collapse the row (they show as empty cells with guides).

---

### UI-6 — Toolbar: time range & scope (est. 0.5 day)

**Objective:** Range presets + custom picker; Activity/History scope; refetch semantics.

**Progress:** [ ] Not started

#### Files

| File | Action | Purpose |
|------|--------|---------|
| `src/app/dash_app/pages/timeline/layout.py` | Modify | Toolbar row |
| `src/app/dash_app/pages/timeline/callbacks.py` | Modify | Range/scope change → refetch |
| `src/app/dash_app/pages/timeline/helpers.py` | Modify | `resolve_range(preset, custom_from, custom_to)` |

#### Tasks

- [ ] **1.** Toolbar: `dbc.Select` Time Range (Last 7 / 30 / 90 days, Custom…) +
      `dcc.DatePickerRange` revealed only for Custom; a segmented Activity/History control.
- [ ] **2.** `resolve_range` maps presets to `(from, to)` ending at Now; Custom yields
      the picked dates (validated: start ≤ end).
- [ ] **3.** Changing range or scope resets pagination cursors and refetches all lanes
      with `from`/`to`/`scope`. First page only.
- [ ] **4.** Group by (UI-7) is **not** wired here; keep it a client-side concern.

#### Unit tests

- [ ] `test_resolve_range_presets` — 7/30/90 produce windows ending at Now.
- [ ] `test_resolve_range_custom` — explicit from/to passed through; invalid reversed range rejected.

#### Manual validation

- [ ] **V6.1** Switching to "Last 7 days" refetches and hides older rows.
- [ ] **V6.2** Custom reveals date pickers; picking a range refetches.
- [ ] **V6.3** Toggling Activity/History re-renders cards (History cards show STATE_CHANGE/"Updated").
- [ ] **V6.4** Changing range/scope resets "Load more" back to the first page.

---

### UI-7 — Group by: Day / Week / Month (est. 0.5 day)

**Objective:** Client-side re-bucketing and relabeling without refetch.

**Progress:** [ ] Not started

#### Files

| File | Action | Purpose |
|------|--------|---------|
| `src/app/dash_app/pages/timeline/helpers.py` | Modify | `period_key(date, granularity)`, `period_label` |
| `src/app/dash_app/pages/timeline/callbacks.py` | Modify | Rebuild grid from `timeline-data-store` |
| `src/app/dash_app/pages/timeline/layout.py` | Modify | Toolbar Group by select |

#### Tasks

- [ ] **1.** `period_key`/`period_label` for Day (`Mar 15`), Week (ISO, `Mar 9 – 15`), Month (`March 2026`).
- [ ] **2.** Group by change rebuilds the grid purely from the already-fetched events —
      **no API call**. Idle-run units and labels follow the granularity.
- [ ] **3.** Cards remain newest-first within a period; per-cell overflow (UI-8) re-applies.

#### Unit tests

- [ ] `test_period_key_week_iso` — ISO week boundaries (Mon-start).
- [ ] `test_period_key_month`.
- [ ] `test_regroup_preserves_events` — total event count unchanged across granularities.

#### Manual validation

- [ ] **V7.1** Switching Day→Week→Month relabels rows and regroups cards without a network request.
- [ ] **V7.2** Idle separators change unit ("3 days" → "2 weeks" → "1 month").
- [ ] **V7.3** No data is lost or duplicated when regrouping.

---

### UI-8 — Row overflow: "+N more" per cell (est. 0.5 day)

**Objective:** Cap visible cards per cell; expand loaded events on demand.

**Progress:** [ ] Not started

#### Files

| File | Action | Purpose |
|------|--------|---------|
| `src/app/dash_app/pages/timeline/helpers.py` | Modify | `cap_cell(events, cap)` |
| `src/app/dash_app/pages/timeline/layout.py` | Modify | "+N more" link |
| `src/app/dash_app/pages/timeline/callbacks.py` | Modify | Toggle cell expansion |

#### Tasks

- [ ] **1.** Each cell shows up to **3** cards, then a "+N more ▾" link.
- [ ] **2.** Click expands that cell to show all **already-loaded** events (may grow the row for all lanes); click again collapses.
- [ ] **3.** Expansion state keyed by `(row_key, lane_key)` in
      `timeline-cell-expansion-store`; reset when selection/range/scope changes.
- [ ] **4.** Server paging is **not** triggered here — that stays with global "Load more" (UI-9). Add a subtle note on the link's tooltip: "loaded events".
- [ ] **5.** Do **not** render the link when `len(events) <= 3`.

#### Unit tests

- [ ] `test_cap_cell_hidden_count` — returns (visible=3, hidden=N-3) and the toggle predicate.

#### Manual validation

- [ ] **V8.1** A day with >3 events shows 3 cards + "+N more".
- [ ] **V8.2** Clicking expands that cell only; the row grows while other lanes keep whitespace.
- [ ] **V8.3** Collapsing restores the capped view; state resets on range change.

---

### UI-9 — Pagination: global "Load more" (est. 0.5 day)

**Objective:** Fetch older events for all lanes together via per-lane cursors.

**Progress:** [ ] Not started

#### Files

| File | Action | Purpose |
|------|--------|---------|
| `src/app/dash_app/pages/timeline/api.py` | Modify | single-lane fetch with `cursor` |
| `src/app/dash_app/pages/timeline/helpers.py` | Modify | `merge_lane_page` (dedup by `signal_id`) |
| `src/app/dash_app/pages/timeline/layout.py` | Modify | "Load more events" button |
| `src/app/dash_app/pages/timeline/callbacks.py` | Modify | Load-more handler |

#### Tasks

- [ ] **1.** Button at the bottom of the grid: "▼ Load more events".
- [ ] **2.** On click, for each lane with a non-null `next_cursor`, issue a
      **single-lane** request (`wba_ids=<lane>&cursor=<lane.next_cursor>&from&to&scope&limit`)
      and merge results into that lane. Requests run sequentially (≤5).
- [ ] **3.** `merge_lane_page` appends new events and updates the lane's `next_cursor`,
      de-duplicating by `signal_id`. **If the single-lane response returns an empty
      `events` list, set that lane's `next_cursor = None`** instead of storing the
      cursor the server echoed — the server's `next_cursor` is optimistic (see
      "Current state" constraint 4), and clearing it is what lets Task 4's button
      actually hide.
- [ ] **4.** Button hidden when every lane's `next_cursor` is null; shows a spinner/disabled
      state while requests are in flight.
- [ ] **5.** Range/scope/selection changes reset cursors to the first page.

#### Unit tests

- [ ] `test_merge_lane_page_dedup` — overlapping `signal_id`s are not double-counted.
- [ ] `test_merge_updates_cursor`.
- [ ] `test_load_more_hidden_when_all_exhausted`.

#### Manual validation

- [ ] **V9.1** Clicking "Load more" appends older rows across all lanes; no duplicates.
- [ ] **V9.2** The button disappears once every lane is exhausted.
- [ ] **V9.3** Changing the range resets to page 1.

---

### UI-10 — Theming & dark mode (est. 0.5 day)

**Objective:** Token-driven light/dark across all timeline surfaces.

**Progress:** [ ] Not started

#### Files

| File | Action | Purpose |
|------|--------|---------|
| `src/app/dash_app/assets/executive-dashboard.css` | Modify | `.timeline-*` token-based rules + dark overrides |
| `src/app/dash_app/styles.py` | Modify | Dark-theme/contrast variants for the `timeline.lane.*` tokens (defined in UI-1) |

#### Tasks

- [ ] **1.** Define `.timeline-card`, `.timeline-popup`, `.timeline-idle-bar`,
      `.timeline-guide`, `.timeline-lane-header`, `.timeline-axis` using `var(--color-*)`.
- [ ] **2.** Lane palette: calibrate dark-theme variants / contrast for the
      `timeline.lane.1`–`.5` tokens added in UI-1 (the palette is *defined* in UI-1,
      not here); verify entity-type colors remain legible on dark card backgrounds.
- [ ] **3.** Ensure the popup, sticky headers, and hover states all adapt (no hardcoded hex).

#### Unit tests

- [ ] None (CSS only) — covered by manual validation.

#### Manual validation

- [ ] **V10.1** Toggling the topbar theme switches all timeline surfaces sensibly.
- [ ] **V10.2** Cards, popups, guides, and separators remain readable in dark mode.
- [ ] **V10.3** Lane accent colors stay distinguishable in both themes.

---

### UI-11 — Inbound deep-linking (est. 0.5 day)

**Objective:** Parse and apply URL params on load from the gallery presets and external links.

**Progress:** [ ] Not started

#### Files

| File | Action | Purpose |
|------|--------|---------|
| `src/app/dash_app/pages/timeline/helpers.py` | Modify | `parse_deeplink_params(search)` |
| `src/app/dash_app/pages/timeline/callbacks.py` | Modify | Apply params on first load |

#### Tasks

- [ ] **1.** Read `dcc.Location(id="url").search` (clientside/`Input`) and parse
      `wba_ids` (comma-separated), `range` (`7d|30d|90d|custom`), `group`
      (`day|week|month`), `scope` (`activity|history`), `from`, `to`.
- [ ] **2. Validate `wba_ids` client-side before fetching.** The router rejects the
      **whole** request with HTTP 400 if *any* id is malformed (`router.py:69-88`), so
      "drop only the bad lane" is impossible unless the UI pre-validates. Add a pure
      helper `is_valid_wba_id(wba_id) -> bool` that mirrors `service.parse_wba_id`
      (`service.py:50-67`): `parts = wba_id.split("::", 2)`; valid iff
      `len(parts) == 3` and every part is non-empty. Drop malformed entries from the
      URL with a non-fatal inline warning; load the rest. Unknown/extra params are
      ignored; missing `wba_ids` labels fall back to the raw id.
      **Belt-and-braces:** if a fetch still returns 400, read `detail.wba_id` from the
      response, drop that lane, and retry once; if it fails again, show the danger
      alert preserving the last good render.
- [ ] **3.** Applying params populates the selection store + toolbar controls, then
      triggers the normal fetch. Applies **once** on initial load, guarded by a
      `dcc.Store(id="timeline-deeplink-applied", storage_type="memory")` boolean:
      once it is `True`, the handler raises `PreventUpdate` and does not re-apply.
      This guard is necessary because `url.search` is an `Input` that also fires when
      the global-search box writes it (`layout.py:227-239`) and on any later
      navigation — without it, re-applying would clobber the user's in-page state.
- [ ] **4.** Gallery "Show Options" href (UI-0) uses the same param names.

#### Unit tests

- [ ] `test_parse_deeplink_full` — all params parsed.
- [ ] `test_parse_deeplink_missing_wba` — returns empty selection, no crash.
- [ ] `test_parse_deeplink_bad_range` — unknown preset falls back to default 30d.
- [ ] `test_is_valid_wba_id` — `"jira::Person::x"` valid; `"bad"`, `"a::b"`, and
      `"jira::::x"` invalid (mirrors `service.parse_wba_id`).

#### Manual validation

- [ ] **V11.1** Navigating to `/app/analytics/timeline?wba_ids=jira::Person::…,jira::Person::…` pre-loads those lanes.
- [ ] **V11.2** `?range=7d&group=week&scope=history` applies range, grouping, and scope.
- [ ] **V11.3** A gallery-generated link (Show Options) opens with the chosen presets applied.
- [ ] **V11.4** A bad lane id is dropped with a warning; the rest load.

---

### UI-12 — Polish & cross-cutting review (est. 0.5 day)

**Objective:** Accessibility, performance, and edge-case sweep.

**Progress:** [ ] Not started

#### Tasks

- [ ] **1. Accessibility:** keyboard reachability for cards, expanders, idle bars, and
      lane ✕; `aria-label`s; focus-visible styles; popup on focus-within.
- [ ] **2. Performance:** avoid re-rendering the whole grid on unrelated state changes
      (split callbacks / `prevent_initial_call`); confirm a 5-lane × 20-event render is
      smooth; memoize bucketing per `(data, granularity)`.
- [ ] **3. Edge cases:** single lane; one lane empty; all lanes empty in range; exactly
      5 lanes; custom range with no events; history scope on a Person; a lane whose
      only page is exactly `limit` (so `next_cursor` is set but no more data exists —
      the next "Load more" returns empty and clears the cursor).
- [ ] **4. Copy review:** toolbar labels, hints, idle-bar text, empty-state text.

#### Manual validation

- [ ] **V12.1** Tab through the page: cards, expanders, and remove buttons are reachable and operable.
- [ ] **V12.2** All edge cases above render without errors.
- [ ] **V12.3** Dark mode final pass.

---

## Dependency graph

```
UI-0 scaffold/route/gallery
   │
   ▼
UI-1 selector + lane headers
   │
   ▼
UI-2P backend mock fixtures (dev-only, independent)
   │
   ▼
UI-2 fetch + bucketing + skeleton ────► UI-3 card design
   │                                        │
   │                                        ▼
   │                                   UI-4 hover popup + click→Graph
   ▼
UI-5 empty cells / idle separators
   │
   ├─► UI-6 toolbar: range + scope ─► UI-7 group by
   │
   ├─► UI-8 cell overflow "+N more"
   │
   └─► UI-9 pagination "Load more"

UI-10 theming  ── cross-cutting, after UI-3/UI-5 render for real
UI-11 deep-linking ── depends on UI-1 + UI-6 + UI-7
UI-12 polish ── last
```

- UI-0 → UI-1 → UI-2 are strictly sequential (UI-2P may land any time before UI-2's
  manual validation; it has no code dependency on the UI phases).
- UI-3/UI-4 build directly on UI-2 and can be tuned independently.
- UI-5, UI-6/7, UI-8, UI-9 branch from UI-2 and are largely independent of each other.
- UI-10 and UI-11 come after the structures they theme/populate; UI-12 last.

---

## Files summary

### New files

| # | File | Phase |
|---|------|-------|
| 1 | `src/app/dash_app/pages/timeline/__init__.py` | UI-0 |
| 2 | `src/app/dash_app/pages/timeline/layout.py` | UI-0 |
| 3 | `src/app/dash_app/pages/timeline/callbacks.py` | UI-0 (stub), UI-1+ |
| 4 | `src/app/dash_app/pages/timeline/helpers.py` | UI-1 |
| 5 | `src/app/dash_app/pages/timeline/api.py` | UI-1 |
| 6 | `tests/test_activity_timeline_ui_helpers.py` | UI-1+ |
| 7 | `src/app/api/activity/v1/mock_data.py` | UI-2P (dev-only) |
| 8 | `tests/test_activity_timeline_mock.py` | UI-2P |

### Modified files

| # | File | Phase | Change |
|---|------|-------|--------|
| 1 | `src/app/analytics/registry.py` | UI-0 | `TimelineAnalytic` + `TIMELINE_ANALYTIC` |
| 2 | `src/app/dash_app/layout.py` | UI-0 | `/app/analytics/timeline` route |
| 3 | `src/app/dash_app/pages/analytics.py` | UI-0 | Timeline card + controls |
| 4 | `src/app/dash_app/assets/executive-dashboard.css` | UI-3…UI-10 | Timeline CSS + dark overrides |
| 5 | `src/app/dash_app/styles.py` | UI-1, UI-10 | `timeline.lane.*` tokens (UI-1) + dark variants (UI-10) |
| 6 | `src/app/api/activity/v1/service.py` | UI-2P | Mock gate in `get_timeline` / `get_suggestions` |
| 7 | `src/app/api/activity/v1/router.py` | UI-2P | Optional `?mock=` switch on both endpoints |
| 8 | `src/app/settings.py` | UI-2P | `TIMELINE_MOCK_SCENARIO` |
| 9 | `.env.example` | UI-2P | Documented commented-out env entry |

---

## Deferred (not in this plan)

- Outbound "View Timeline" buttons from Search, Graph, and Collaboration Network
  (plan 026 Phase 4 Task 1–3).
- Entity-specific Graph deep-link from a card click (currently plain `/app/graph`).
- Per-lane event totals in lane headers (needs a backend COUNT query).
- Related-entity id on activity cards (needs an additive API field).
- Real per-lane cursors in a single multi-lane request (backend change).
- Touch/mobile-optimised interactions.

---

## Estimated effort

| Phase | Est. |
|-------|------|
| UI-0 Scaffold & entry | 0.5 d |
| UI-1 Entity selector & lane headers | 1.0 d |
| UI-2P Backend mock fixtures (dev-only) | 0.5 d |
| UI-2 Fetch, bucketing & skeleton | 1.0 d |
| UI-3 Card design | 1.0 d |
| UI-4 Hover popup & click-to-Graph | 0.5 d |
| UI-5 Empty cells & idle separators | 1.0 d |
| UI-6 Toolbar: range & scope | 0.5 d |
| UI-7 Group by | 0.5 d |
| UI-8 Row overflow | 0.5 d |
| UI-9 Pagination | 0.5 d |
| UI-10 Theming | 0.5 d |
| UI-11 Deep-linking | 0.5 d |
| UI-12 Polish | 0.5 d |
| **Total** | **~9.0 d** |
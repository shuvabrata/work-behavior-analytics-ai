# Activity Timeline — UI Implementation Plan

> **Plan:** 027
> **Date:** 2026-10-02
> **Feature design:** `plans/activity-timeline-feature.md`
> **Backend plan:** `plans/026-activity-timeline-implementation.md` (Phases 0–2 complete)
> **Visual reference:** `plans/timeline-samples/03-swimlane-multi-user.html`
> **Branch:** `feature/activity-timeline-ui`
> **Route:** `/app/analytics/timeline`

---

## Overview

Build the Dash UI for the Activity Timeline on top of the already-shipped backend
(`GET /api/v1/activity/timeline`, `GET /api/v1/activity/suggest`). The view is a
multi-lane swimlane: one vertical column per selected entity, rows bucketed by
day/week/month, idle periods collapsed into expandable separators, and event cards
that reveal detail on hover and open the Graph page on click.

The work is split into **13 deliberately small phases (UI-0 … UI-12)**. Each phase is
independently reviewable and tunable before the next begins, matching the manual
review cadence used for backend Phases 0–2.

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

## Backend reality & constraints (no backend changes required)

These were verified against the shipped API and shape the UI design:

1. **Activity-scope events carry no related-entity id.** `TimelineEvent` exposes
   `entity_type` (the *other* side) but not its id; `details` is `{}` for
   `scope=activity` (full attribute snapshot only for `scope=history`). → Card shows
   `summary`, not "PR #142".
2. **No per-lane count.** `TimelineLane` has no `total_count`. → Lane headers show no
   event count.
3. **One global cursor per request.** The router accepts a single `cursor` applied to
   *all* lanes while returning per-lane `next_cursor`. → Pagination issues one
   single-lane request per lane instead of one multi-lane request.
4. **History scope** yields synthetic `STATE_CHANGE` events with `summary =
   display_name`, `entity_type` = the lane entity's own type, and a populated
   `details` snapshot.

---

## Global conventions

- **API access:** synchronous `requests.get` inside Dash callbacks, mirroring
  `pages/search.py`. Base URL from `os.getenv("API_BASE_URL", "http://localhost:8000")`;
  timeout from `runtime_settings.get_int("HTTP_REQUEST_TIMEOUT")`. A small
  `pages/timeline/api.py` wrapper centralizes the two calls.
- **Datetime rendering:** `app.common.timezone.to_app_timezone(dt)` +
  `settings.UI_DATETIME_FORMAT` / `UI_DATE_FORMAT` (see `components/common.py`
  `_panel_properties_table` for the reference pattern). Footer shows **time only**;
  popup shows the **full datetime**.
- **Colors/typography:** import from `app.dash_app.styles`; entity-type colors reuse
  existing graph tokens (`graph.node.pull_request`, `.issue`, `.commit`, `.page`,
  `.person`, `.epic`, `.repository`, …) with a neutral fallback. No hardcoded hex in
  components; timeline-specific rules live in `executive-dashboard.css` using
  `var(--color-*)` tokens.
- **State:** `dcc.Store` components (prefixed `timeline-`) hold selection, params,
  fetched lanes/cursors, expansion state. No URL writes in v1.
- **IDs:** all timeline components prefixed `timeline-` to avoid collisions in the
  single-page Dash app.
- **Naming:** page package `src/app/dash_app/pages/timeline/` with `layout.py`
  (view builders), `callbacks.py` (Dash callbacks), `helpers.py` (pure, unit-testable
  functions), `api.py` (HTTP wrapper), `__init__.py`.

---

## Phases

### UI-0 — Page scaffold, route & gallery entry (est. 0.5 day)

**Objective:** A reachable, empty page. No data fetching.

**Progress:** [ ] Not started

#### Files

| File | Action | Purpose |
|------|--------|---------|
| `src/app/dash_app/pages/timeline/__init__.py` | Create | `__all__ = ["get_layout"]`, re-export |
| `src/app/dash_app/pages/timeline/layout.py` | Create | Header + empty state + placeholder stores |
| `src/app/analytics/registry.py` | Modify | Add `TimelineAnalytic` dataclass + `TIMELINE_ANALYTIC` |
| `src/app/dash_app/layout.py` | Modify | Route `/app/analytics/timeline` |
| `src/app/dash_app/pages/analytics.py` | Modify | Render timeline card + `_create_timeline_controls()` |

#### Tasks

- [ ] **1.** Create `TimelineAnalytic` in `registry.py` — do **not** reuse
      `GraphAnalytic` (its `.href` points at `/app/graph?mode=`). Follow the
      dataclass in plan 026 Phase 3 Task 4, with `key="activity_timeline"`,
      `icon="fas fa-timeline"`.
- [ ] **2.** In `layout.py`, add the route branch:
      ```python
      if pathname == "/app/analytics/timeline":
          from app.dash_app.pages.timeline import get_layout as get_timeline_layout
          return get_timeline_layout()
      ```
- [ ] **3.** `get_layout()` returns: `create_page_header([("Analytics", "/app/analytics"), ("Timeline", None)], …)`, a selector bar placeholder, and an empty state via `create_empty_state("Add people or objects to compare their activity.")`.
- [ ] **4.** In `analytics.py`, render `TIMELINE_ANALYTIC` alongside `GRAPH_ANALYTICS`
      (extend the gallery loop; do **not** append to `GRAPH_ANALYTICS`). Add an
      `elif analytic.key == "activity_timeline"` branch in `_create_analytic_card`
      calling `_create_timeline_controls()`.
- [ ] **5.** `_create_timeline_controls()` mirrors `_create_collaboration_controls()`:
      "Open Visualization" (href `/app/analytics/timeline`) + "Show Options" collapse
      containing Default Range / Group by / View selects. A callback builds the href
      with `urlencode({"range": …, "group": …, "scope": …})`. (URL is consumed in
      UI-11; until then it simply navigates.)

#### Unit tests

- [ ] `test_timeline_analytic_href` — `TIMELINE_ANALYTIC.href == "/app/analytics/timeline"`.
- [ ] `test_timeline_layout_renders` — `get_layout()` returns an `html.Div` without error.

#### Manual validation

- [ ] **V0.1** `/app/analytics` shows the "Activity Timeline" card next to "Collaboration Network".
- [ ] **V0.2** "Show Options" expands with Range/Group/View selects.
- [ ] **V0.3** "Open Visualization" navigates to `/app/analytics/timeline` and renders the header + empty state.

---

### UI-1 — Entity selector (search box) & lane headers (est. 1 day)

**Objective:** Add/remove entities; lanes render as empty columns. No events yet.

**Progress:** [ ] Not started

#### Files

| File | Action | Purpose |
|------|--------|---------|
| `src/app/dash_app/pages/timeline/api.py` | Create | `fetch_suggestions(q)` |
| `src/app/dash_app/pages/timeline/helpers.py` | Create | `assign_lane_colors`, `entity_type_label`, dedup/add/remove helpers |
| `src/app/dash_app/pages/timeline/layout.py` | Modify | Selector bar + lane-header row |
| `src/app/dash_app/pages/timeline/callbacks.py` | Create | Typeahead, add/remove, clear-all, max-lane hint |

#### Tasks

- [ ] **1. Selector bar:** `dbc.Input(id="timeline-search-input")` + a results
      dropdown container. Debounce ~300 ms via `dcc.Store` + a clientside callback that
      returns `no_update` until idle (mirror `graph` spotlight debounce), min 2 chars.
- [ ] **2. Suggestions:** on debounced input → `fetch_suggestions(q)` →
      `GET /api/v1/activity/suggest?q=…` → render up to 10 rows (avatar/type icon +
      label + type tag + source). Click adds; Enter adds the top result.
- [ ] **3. Selection store:** `timeline-selected-store` = ordered list of
      `{wba_id, label, entity_type, source, avatar_url}`. Adding is idempotent.
- [ ] **4. Lane headers:** render one header per selected entity —
      avatar (`avatar_url`) or entity-type `fas` icon, label, type tag, ✕ remove.
      Left column of fixed width for the time-axis label. Headers **are** the
      selection; no chip row.
- [ ] **5. Limits:** soft cap 5; at 5 disable the input and show the inline hint
      "🔒 Maximum 5 lanes — remove one first". "Clear all" text link appears when ≥1 lane.
- [ ] **6. Colors:** `assign_lane_colors(n)` returns the first *n* tokens from a
      5-entry palette (reassigned on removal so colors stay distinct).

#### Unit tests

- [ ] `test_assign_lane_colors_distinct` — no duplicate colors up to 5.
- [ ] `test_entity_type_label_mapping` — `PullRequest→"PR"`, unknown→raw type.
- [ ] `test_selection_add_remove_dedup` — re-adding the same `wba_id` is a no-op; remove drops it.

#### Manual validation

- [ ] **V1.1** Typing ≥2 chars shows suggestions; clicking adds a lane header.
- [ ] **V1.2** Adding a 6th is blocked with the inline hint.
- [ ] **V1.3** ✕ removes a lane; "Clear all" empties the view back to the empty state.
- [ ] **V1.4** Lane headers show avatar/icon + label + type tag; no count.

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
| `src/app/dash_app/pages/timeline/helpers.py` | Modify | `humanize_relationship`, `card_summary` |
| `src/app/dash_app/assets/executive-dashboard.css` | Modify | `.timeline-card*` rules |

#### Tasks

- [ ] **1.** Card: left accent border in the **lane color**; line 1 = `summary`,
      one line, ellipsised; fallback when null = humanized relationship + entity type.
- [ ] **2.** Line 2 = `<EntityType (colored)> · <relationship> · <time>` — e.g.
      `PR · Created · 2:30 PM`. Entity-type token colored via graph node tokens with a
      neutral fallback; relationship humanized to Title Case.
- [ ] **3.** Time rendered from `event_time` via `to_app_timezone` + `UI_DATE_FORMAT`-time
      (time only). Full datetime reserved for the popup.
- [ ] **4.** Fixed/semi-fixed card height; `text-overflow: ellipsis` on the summary;
      tooltip via `title` as a fallback when hover popup is unavailable (touch).

#### Unit tests

- [ ] `test_humanize_relationship` — `CREATED→"Created"`, `STATE_CHANGE→"Updated"`.
- [ ] `test_card_summary_fallback` — null summary falls back to relationship + type.

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
| `src/app/dash_app/pages/timeline/layout.py` | Modify | Wrap card in anchor + popup markup |
| `src/app/dash_app/assets/executive-dashboard.css` | Modify | `.timeline-card:hover .timeline-popup`, flip variants |

#### Tasks

- [ ] **1.** Wrap each card in `html.A(href="/app/graph", target="_blank", rel="noopener noreferrer")` — whole card clickable to Graph, new tab.
- [ ] **2.** Popup content: `summary`, humanized relationship, entity type, source,
      full datetime (`UI_DATETIME_FORMAT`), and an "Open source ↗" link to `event.url`
      (rendered only when `url` is present). `scope=activity` detail is limited (no
      attributes); `scope=history` may show key attributes from `details`.
- [ ] **3.** CSS-only show on `:hover` and `:focus-within` (keyboard); `bottom: 100%`
      for cards in the upper half of the viewport, `top: 100%` for the lower half, to
      avoid clipping. Lane cells set `overflow: visible`; popup `z-index` above
      neighbours.
- [ ] **4.** "Open source ↗" stops propagation so it opens the source URL, not Graph.
      (Render it as the popup's own `<a>`; the card anchor is the click target.)

#### Unit tests

- [ ] `test_popup_fields_from_event` — popup builder includes source link only when url present.

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
      de-duplicating by `signal_id`.
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
| `src/app/dash_app/styles.py` | Modify | Lane palette tokens (optional) |

#### Tasks

- [ ] **1.** Define `.timeline-card`, `.timeline-popup`, `.timeline-idle-bar`,
      `.timeline-guide`, `.timeline-lane-header`, `.timeline-axis` using `var(--color-*)`.
- [ ] **2.** Lane palette: 5 accents with light/dark variants calibrated for contrast;
      verify entity-type colors remain legible on dark card backgrounds.
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
- [ ] **2.** Missing `wba_ids` labels fall back to the raw id; unknown params ignored;
      malformed `wba_ids` surfaces a non-fatal warning and drops only the bad lane.
- [ ] **3.** Applying params populates the selection store + toolbar controls, then
      triggers the normal fetch. Applies **once** on initial load (guard against
      re-applying on later navigation).
- [ ] **4.** Gallery "Show Options" href (UI-0) uses the same param names.

#### Unit tests

- [ ] `test_parse_deeplink_full` — all params parsed.
- [ ] `test_parse_deeplink_missing_wba` — returns empty selection, no crash.
- [ ] `test_parse_deeplink_bad_range` — unknown preset falls back to default 30d.

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

- UI-0 → UI-1 → UI-2 are strictly sequential.
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
| 3 | `src/app/dash_app/pages/timeline/callbacks.py` | UI-1 |
| 4 | `src/app/dash_app/pages/timeline/helpers.py` | UI-1 |
| 5 | `src/app/dash_app/pages/timeline/api.py` | UI-1 |
| 6 | `tests/test_activity_timeline_ui_helpers.py` | UI-1+ |

### Modified files

| # | File | Phase | Change |
|---|------|-------|--------|
| 1 | `src/app/analytics/registry.py` | UI-0 | `TimelineAnalytic` + `TIMELINE_ANALYTIC` |
| 2 | `src/app/dash_app/layout.py` | UI-0 | `/app/analytics/timeline` route |
| 3 | `src/app/dash_app/pages/analytics.py` | UI-0 | Timeline card + controls |
| 4 | `src/app/dash_app/assets/executive-dashboard.css` | UI-3…UI-10 | Timeline CSS + dark overrides |
| 5 | `src/app/dash_app/styles.py` | UI-10 | Lane palette tokens (optional) |

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
| **Total** | **~8.5 d** |
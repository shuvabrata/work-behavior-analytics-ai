# Activity Timeline Design

**Audience:** Developers extending, debugging, or maintaining the Activity Timeline.
**Status:** Implemented and shipped on branch `feature/activity-timeline-2`.
**Related docs:** [`spec-activity-signal.md`](spec-activity-signal.md) (the ingested
contract), [`graph-db-high-level-design.md`](graph-db-high-level-design.md) (Neo4j
state store), [`design-system.md`](design-system.md) (UI tokens).

---

## Table of Contents

1. [Overview](#1-overview)
2. [Architecture](#2-architecture)
3. [Storage design](#3-storage-design)
4. [Ingestion pipeline](#4-ingestion-pipeline)
5. [API design](#5-api-design)
6. [Query parameters & inbound URLs](#6-query-parameters--inbound-urls)
7. [UI design](#7-ui-design)
8. [Key design decisions & rationale](#8-key-design-decisions--rationale)
9. [Mock data (development only)](#9-mock-data-development-only)
10. [Deferred / future work](#10-deferred--future-work)
11. [Source map](#11-source-map)

---

## 1. Overview

Users need to see the **chronological activity of people and objects** across
GitHub, Jira, and Confluence — commits, PRs, issue/page changes, who did what to
which object, and how an object's own state evolved.

The existing Neo4j store cannot serve this. It stores *current state* using
`MERGE` semantics: each new signal overwrites the previous snapshot, so history
is lost by construction. Two questions ("what did Alice do recently?" and "what
happened to Page X over time?") are therefore answered by a new append-only
historical store, not by the graph.

The **Activity Timeline** is a three-part feature:

| Part | What it is |
|------|------------|
| **Timeline store** | Two Postgres tables holding deduplicated, immutable `ActivitySignal` history. |
| **Activity API** | `/api/v1/activity/timeline` (swimlane data) and `/api/v1/activity/suggest` (typeahead). |
| **Timeline page** | `/app/timeline` — a Dash multi-lane swimlane view for comparing entities side by side. |

Design goals: queryable across *any* entity type, cheap to page backward through
history, non-disruptive to the existing pipeline (Neo4j stays the source of
truth), and deep-linkable.

---

## 2. Architecture

```
[GitHub/Jira/Confluence APIs]
        │
        ▼
   [producers] ──ActivitySignal JSON──▶ RabbitMQ
        │                                    │
        ▼                                    ▼
  (unchanged path)                  [signal-consumer]
        │                                    │
        │                          ┌─────────┴──────────┐
        │                          ▼                    ▼
        │                    Neo4j (state)      Postgres timeline (history)
        │                                             ▲
        │                                             │
        │                                     [Activity API  /api/v1/activity]
        │                                             ▲
        │                                             │
        └───────────────────────────────▶ [Dash UI  /app/timeline]
```

Four components, built in that dependency order:

1. **Timeline store** — two Postgres tables (Section 3). Alembic-managed.
2. **Ingestion hook** — a consumer-side writer that copies each signal into
   Postgres after the Neo4j upsert (Section 4).
3. **Activity API** — FastAPI router + service + query layers following the
   repo's `router.py` / `service.py` / `query.py` layering (Section 5).
4. **Timeline page** — a Dash swimlane page under
   `src/app/dash_app/pages/timeline/` (Sections 6–7).

The pipeline never runs backwards: timeline writes are best-effort and never
block or fail the graph pipeline.

---

## 3. Storage design

History is modelled as **two tables** because the two questions above have
different shapes:

- *"Show me the history of object X"* — one row per **meaningfully distinct
  state** of an entity.
- *"Show me everything involving entity Y"* — one row per **relationship**
  (who did what to whom).

### 3.1 `activity_events` — raw deduped signal per entity

One row per distinct state of an entity. Backs `scope=history`.

| Column | Type | Notes |
|--------|------|-------|
| `id` | `BIGSERIAL` PK | Keyset tie-breaker. |
| `signal_id` | `UUID` (unique) | The originating signal. `activity_actions` FKs to this column. |
| `source` | `VARCHAR(32)` | `github` / `jira` / `confluence`. |
| `entity_type` | `VARCHAR(32)` | `Person`, `Issue`, `Page`, `PullRequest`, `Commit`, … |
| `entity_id` | `VARCHAR(255)` | Raw id within the source. |
| `event_time` | `TIMESTAMPTZ` | When the event happened in the source system. |
| `ingestion_time` | `TIMESTAMPTZ` | `DEFAULT NOW()`. |
| `display_name` | `VARCHAR(512)` | Computed at write time (see 4.2). |
| `avatar_url` | `VARCHAR(1024)` | `Person` only, else `NULL`. |
| `attributes` | `JSONB` | Full entity attribute snapshot. |
| `relationships` | `JSONB` | Full relationship array, or `NULL`. |
| `content_hash` | `VARCHAR(64)` | SHA-256 of attributes + relationships. |

Constraints and indexes:

```
UNIQUE (signal_id)                                        -- uq_activity_events_signal_id
UNIQUE (source, entity_type, entity_id, event_time, content_hash)  -- uq_activity_events_dedup
INDEX  idx_activity_events_lookup (source, entity_type, entity_id, event_time DESC)
```

`source` leads the lookup index so a query scoped to a full WBA key
(`source + type + id`) hits one index.

### 3.2 `activity_actions` — normalized relationship rows

One row per relationship observed in a signal. Backs `scope=activity`.

| Column | Type | Notes |
|--------|------|-------|
| `id` | `BIGSERIAL` PK | Keyset tie-breaker. |
| `signal_id` | `UUID` | FK → `activity_events.signal_id` `ON DELETE CASCADE`. |
| `source` | `VARCHAR(32)` | Data integration source. |
| `event_time` | `TIMESTAMPTZ` | Copied from the parent event. |
| `actor_entity_type` / `actor_entity_id` | `VARCHAR` | Who initiated the relationship. |
| `relationship_type` | `VARCHAR(32)` | `CREATED`, `REVIEWED`, `COMMENTED_ON`, … |
| `target_entity_type` / `target_entity_id` | `VARCHAR` | What the action targeted. |
| `summary` | `VARCHAR(512)` | Denormalized context (e.g. PR title) for fast reads. |
| `url` | `VARCHAR(1024)` | Link to the target in the source system. |

Indexes (both lead with `source`):

```
idx_activity_actions_actor  (source, actor_entity_type, actor_entity_id,  event_time DESC)
idx_activity_actions_target (source, target_entity_type, target_entity_id, event_time DESC)
```

**Note:** the `DESC` ordering is injected manually in the Alembic migration via
`op.execute()` — SQLAlchemy autogenerate does not emit descending indexes. See
the migration in `src/app/alembic/versions/`.

### 3.3 Read-time query flow

| Question | Table | Index |
|----------|-------|-------|
| History of Page X | `activity_events` (`source`, `entity_type`, `entity_id`) | `idx_activity_events_lookup` |
| Everything Alice did | `activity_actions` (`actor_*`) | `idx_activity_actions_actor` |
| Everything involving Alice | `activity_actions` (`actor_*` OR `target_*`) | both action indexes |
| Who interacted with Issue Y | `activity_actions` (`target_*`) | `idx_activity_actions_target` |

---

## 4. Ingestion pipeline

### 4.1 Consumer-side hook

The write happens in the **signal-consumer**, not the producers: the consumer is
the one component that already has the validated `ActivitySignal` after a
successful Neo4j upsert. `ActivityWriter`
(`src/connectors/consumers/activity_writer.py`) owns an `asyncio.Queue` and a
background loop:

- Signals are enqueued **after** the Neo4j upsert and after the message ack.
- A batch flushes when it reaches **100 signals** or **5 seconds** of inactivity,
  whichever comes first.
- It uses **`asyncpg` directly** (no SQLAlchemy) because the consumer image does
  not carry the app layer's dependencies.
- `DATABASE_URL`'s SQLAlchemy `+asyncpg` dialect prefix is stripped at
  construction; the same Postgres instance as the app is used.

### 4.2 Write path & dedup

For each signal:

1. Compute `content_hash = SHA-256(json(attributes) + json(relationships))` with
   `sort_keys=True` — stable regardless of dict insertion order.
2. Compute `display_name`: first non-empty of `attributes.name` / `title` /
   `summary` / `key`, else the raw entity `id`. Mirrors
   `GraphNode.display_name()`.
3. Compute `avatar_url`: `attributes.avatar_url` when `entity_type == "Person"`,
   else `NULL`.
4. `INSERT … ON CONFLICT (source, entity_type, entity_id, event_time,
   content_hash) DO NOTHING`.
   - **Never SELECT-then-INSERT.** Concurrency-safe under horizontally scaled
     consumers; a SELECT-then-INSERT is a TOCTOU race. `asyncpg.execute()`
     returns the command tag string (`"INSERT 0 1"` inserted / `"INSERT 0 0"`
     deduped), not an object with `.rowcount`.
   - The unique constraint is the dedup guard; an identical re-scan is a no-op.
5. Only when the event row was actually inserted, decompose
   `signal.relationships[]` into `activity_actions` rows:
   - `actor_*` ← the signal's own `entity_type` / `id`.
   - `relationship_type` ← `rel.type`; `target_*` ← `rel.target`.
   - `summary` ← first non-empty of `attributes.title` / `summary` / `key`.
   - `url` ← `rel.target.url`.

### 4.3 Failure semantics

**Non-fatal.** A timeline write failure logs a warning and continues; the
consumer never nacks a signal because of it. Neo4j remains the source of truth.

### 4.4 Backfill

**None.** The timeline accumulates from the feature's ship date. There is no
replay from JSONL dumps. `activity_events` therefore only contains signals
consumed after deployment.

---

## 5. API design

Two read-only endpoints, registered under `prefix="/api/v1"`. Implementation:
`src/app/api/activity/v1/{router,service,query,model}.py`.

### 5.1 `GET /api/v1/activity/timeline`

Returns swimlane data for one or more entities. Query parameters are fully
documented in [Section 6](#6-query-parameters--inbound-urls).

Response shape (`model.py`):

```python
class TimelineEvent:
    signal_id: str            # UUID string
    event_time: datetime
    relationship_type: str    # "CREATED", "REVIEWED"; "STATE_CHANGE" for history
    summary: str | None
    entity_type: str          # the *other* side (activity) / own type (history)
    source: str               # github | jira | confluence
    url: str | None           # source-system link
    details: dict             # {} for scope=activity; attribute snapshot for history

class TimelineLane:
    wba_id: str
    entity_type: str
    label: str                # pre-computed display_name or raw id
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

### 5.2 `GET /api/v1/activity/suggest`

Typeahead for the entity selector. `q` requires **≥ 3 characters**
(`min_length=3`); `limit` defaults to 10, max 20. Backed by Elasticsearch via
the existing search service. When ES is disabled the result is an empty list.
Response: `{"results": [{wba_id, label, entity_type, source, avatar_url}]}`.

### 5.3 Contract constraints clients must honor

These are deliberate properties of v1, not bugs:

1. **Activity events carry no related-entity id.** `TimelineEvent` exposes the
   *other* side's `entity_type` but not its id; `details` is `{}` for
   `scope=activity`. Cards therefore show `summary`, not "PR #142".
2. **No per-lane event count.** `TimelineLane` has no `total_count`.
3. **The cursor is per-lane, not global.** A request accepts one `cursor`
   applied to *all* lanes, while each lane returns its own `next_cursor`. Because
   the cursor encodes a specific lane's `(event_time, row_id)`, a shared cursor
   across lanes is semantically wrong — pagination issues **one single-lane
   request per lane**.
4. **`next_cursor` is optimistic.** It is emitted whenever a lane returned
   exactly `limit` events, even if no further rows exist. A subsequent "Load
   more" can legitimately return an empty page; the UI clears that lane's cursor
   when it does.
5. **One invalid `wba_id` fails the whole request.** The router validates every
   id up front and returns **400** with `detail.wba_id` for the offending key.
   The UI pre-validates client-side (and drops the named lane on a 400).
6. **History scope** yields synthetic `STATE_CHANGE` events with
   `summary = display_name`, `entity_type` = the lane entity's own type, `url`
   from `attributes.url`, and a populated `details` snapshot.
7. **`from` is optional.** Omitted means "all time" — the query is still
   keyset-bounded to `limit` rows per lane, so paging backward needs no backend
   change.

---

## 6. Query parameters & inbound URLs

There are two distinct surfaces. Keep them straight when writing integrations:

- the **API** (`/api/v1/activity/timeline`) — read by any client, takes datetimes;
- the **page** (`/app/timeline`) — the inbound deep-link contract, takes dates.

### 6.1 API query parameters — `GET /api/v1/activity/timeline`

| Param | Type | Required | Default | Meaning |
|-------|------|----------|---------|---------|
| `wba_ids` | string | ✓ | — | Comma-separated WBA canonical keys, one per lane. |
| `scope` | enum | | `activity` | `activity` = actions involving the entity; `history` = the entity's own state changes. Invalid → 400. |
| `from` | ISO 8601 datetime | | `None` | Range start. Omitted = unbounded (all time). Query alias for `from_`. |
| `to` | ISO 8601 datetime | | `None` | Range end. |
| `cursor` | string | | `None` | Opaque keyset cursor from a previous response; applies to **every** lane. Malformed → 400. |
| `limit` | int 1–100 | | `20` | Events **per lane**. |
| `mock` | string | | `None` | **Dev only** — see [Section 9](#9-mock-data-development-only). Ignored unless mock mode is enabled. |

`GET /api/v1/activity/suggest` takes `q` (required, min 3 chars), `limit`
(1–20, default 10), and the dev-only `mock`.

### 6.2 WBA canonical key

The sole identity used everywhere is the **WBA canonical key**:

```
{source}::{entity_type}::{id}
```

Examples: `github::Person::alice`, `jira::Issue::BTS-15`,
`confluence::Page::123456`.

- Only the **first two** `::` separators split — the id itself may contain `::`
  (some Jira/Jira-style object ids do).
- All three parts must be non-empty, else the key is invalid.
- The id is the **raw id from the source system**, not a display name.

### 6.3 Page deep-link parameters — `/app/timeline`

The page reads its initial state from `dcc.Location.search` and applies it
**once** on load (guarded so later navigations and global-search writes do not
clobber in-page state). Parsing lives in `parse_deeplink_params()`.

| Param | Accepted values | Default | Notes |
|-------|-----------------|---------|-------|
| `wba_ids` | comma-separated WBA keys | *(empty)* | Invalid keys are **dropped** (with a warning); valid keys are kept in order, capped at 5. |
| `scope` | `activity` \| `history` | `activity` | Anything else → `activity`. |
| `group` | `day` \| `week` \| `month` | `day` | Anything else → `day`. |
| `from` | ISO **date** (`YYYY-MM-DD`) | `None` | Must be supplied together with `to`. |
| `to` | ISO **date** (`YYYY-MM-DD`) | `None` | Must be supplied together with `from`. |
| `mock` | a scenario name | `None` | **Dev only**; forwarded to the API. See Section 9. |

**Rules for constructing an inbound URL:**

1. **Route:** use `/app/timeline`. The legacy path `/app/analytics/timeline` is
   kept as an alias so older bookmarks and shared deep links keep resolving.
   A trailing slash is normalized (`/app/timeline/` works).
2. **`wba_ids` is the only required param.** Join keys with commas; do not
   URL-encode the `::` separators (they are valid in a query value).
3. **Numeric keys are safe as-is.** A Jira account id may itself contain `:` —
   that is fine inside the value.
4. **Dates are wall-clock days**, interpreted in the app timezone and converted
   to UTC day bounds by the client (start `00:00:00`, end `23:59:59`). They are
   **not** timestamps: the page contract is `YYYY-MM-DD`.
5. **A partial or reversed date pair is ignored** — the page falls back to
   *All time* rather than erroring. Supply both `from` and `to`, with
   `from ≤ to`, to get a bounded window.
6. **Unknown parameters are ignored.** Query params do not write back: the URL
   is an **inbound-only** contract in v1 — the page never updates it as the user
   changes controls.
7. **Bad lane keys do not fail the page.** Malformed keys are removed before the
   fetch and a non-fatal warning is shown; the remaining lanes load. (Contrast
   the API, where one bad key is a 400 — hence the client-side filter.)

**Examples:**

```
# One lane
/app/timeline?wba_ids=github::Person::alice

# Two lanes compared, history scope, bucketed by week
/app/timeline?wba_ids=github::Person::alice,github::Person::bob&scope=history&group=week

# A single object over a bounded Custom window
/app/timeline?wba_ids=jira::Issue::BTS-15&from=2026-09-01&to=2026-09-30

# Mixed entity types, month buckets, all time (no from/to)
/app/timeline?wba_ids=confluence::Page::123456,github::PullRequest::142&group=month

# Dev-only: force a mock scenario (mock mode must already be enabled)
/app/timeline?wba_ids=mock::Person::alice&mock=gap_30d
```

> **Construct with a URL encoder.** Build the query with
> `urllib.parse.urlencode({"wba_ids": ",".join(keys), ...})` rather than string
> concatenation; the comma-joined `wba_ids` value is the only non-trivial part.

---

## 7. UI design

The page is a **multi-lane vertical swimlane**: one column per selected entity,
rows bucketed by day/week/month, idle periods collapsed into expandable
separators, and event cards that reveal detail on hover and open the Graph page
on click. It is a top-level sidebar item (directly after **Graph**), not an
Analytics sub-page.

### 7.1 Layout model

- **Vertical timeline, compressed idle gaps.** Time flows top (newest) to bottom
  (oldest). Gaps with no activity in any lane collapse to a slim full-width bar
  (e.g. `Mar 11 – 14 · 3 days no activity`) that expands on click.
- **Global shared rows.** Day/week/month buckets are the **union** across all
  lanes, so rows align vertically. A period active for one lane and idle for
  another renders an **empty cell with a dashed guide**, not a missing row.
- **Lanes = any entity type** (Person *and* objects), min-width 220px, soft cap
  **5**. Beyond the viewport width the grid scrolls horizontally.
- **Sticky chrome:** the lane-header row is sticky-top; the time axis is
  sticky-left. The page itself scrolls.
- **Wholly empty lane:** a faint "No activity in this range" note.

### 7.2 Selection

- **Lane headers *are* the selection** — avatar/icon + label + type tag + ✕.
  There is no separate chip row and no per-lane event count.
- A live debounced typeahead (~300 ms, **min 3 characters**) queries
  `/api/v1/activity/suggest`. Suggestions show avatar/type icon, label, type
  tag, and source; click or Enter adds. Arrow keys move a highlight; Escape
  clears.
- Adding is idempotent (duplicate `wba_id` is a no-op). Selecting past 5 lanes
  is blocked with an inline hint; a "Clear all" link appears at ≥ 1 lane.
- Five lane-accent colors are assigned by selection order and reassigned on
  removal so surviving lanes stay distinct.

### 7.3 Toolbar

| Control | Options | Behavior |
|---------|---------|----------|
| **Range** | *All time* (default) / *Custom…* | *All time* sends **no `from`**; Custom reveals From/To date inputs. Changing it **refetches** and resets pagination. |
| **Group by** | Day (default) / Week / Month | Sets row granularity and idle-separator unit. **Client-side re-bucket, no refetch.** |
| **Scope** | Activity / History | Activity = involvement; History = the entity's own state changes. Changing it **refetches**. |

### 7.4 Cards & interaction

- **Two lines:** line 1 = `summary` (ellipsised; fallback = humanized relationship
  + entity type); line 2 = `<EntityType (colored)> · <relationship> · <time>`,
  with a left accent border in the lane color.
- **Cell overflow:** at most **3** cards per cell, then a "+N more ▾" link that
  reveals *already-loaded* events only (never fetches).
- **Hover/focus popup:** a single portal rendered **outside** the scrolling grid
  (`position: fixed`, high `z-index`), filled from a per-card
  `data-timeline-event` JSON attribute with `textContent` (never `innerHTML` —
  summaries/labels/urls are untrusted ingested data). Shows summary, humanized
  relationship, entity type, source, full datetime, and an "Open source ↗" link
  when the event has a URL. It hides on scroll/resize/Escape.
- **Click a card** → `/app/graph` in a new tab.
- **Pagination:** a global **"▼ Load more events"** button. It issues one
  single-lane request per lane (each with its own cursor), dedups by event
  identity, clears a lane's cursor on an empty page, and preserves the reader's
  scroll position. The button hides when every lane is exhausted.

### 7.5 Theming & time

- Colors are **token-driven** through `styles.py` (`COLOR_*` → `var(--color-*)`)
  and rules in `assets/executive-dashboard.css`; no hardcoded hex in components.
  Entity-type colors resolve from the *effective* graph theme (base tokens ⊕
  Graph-Styling overrides) via `timeline-theme-store`, falling back to base
  tokens — so a dark-mode toggle does not leave stale light colors.
- Times render in `settings.TIMEZONE`; footer shows time only, the popup shows
  the full datetime via `UI_DATETIME_FORMAT` / `UI_DATE_FORMAT`.

---

## 8. Key design decisions & rationale

| # | Decision | Why |
|---|----------|-----|
| 1 | **Postgres** for history, not Neo4j | Neo4j `MERGE` overwrites state — history would be impossible without restructuring the graph. Postgres gives cheap append-only writes and time-ordered keyset scans. |
| 2 | **Two tables** (events + actions) | "History of an object" and "everything involving an entity" are different access shapes. Splitting them lets each query hit a purpose-built index and normalizes relationships once, at write time. |
| 3 | **Consumer-side ingestion hook** | The consumer is the first component holding the validated signal after the Neo4j upsert. Producers stay one-shot and unaware of the timeline. |
| 4 | **Content-hash dedup + `ON CONFLICT DO NOTHING`** | Idempotent under re-scans and race-safe across horizontally scaled consumers; no SELECT-then-INSERT TOCTOU window. |
| 5 | **Batched, async, non-fatal writes** | Keeps the critical graph path fast; a Postgres outage degrades history, never ingestion. Neo4j remains the source of truth. |
| 6 | **No backfill** | Deliberate scope cut — the store accumulates from ship date. Avoids a replay mechanism and the ambiguity of reconstructing "meaningful" history from JSONL. |
| 7 | **WBA canonical key is the sole identity** | One opaque string covers every source and entity type, so a single `wba_ids` param drives multi-lane queries; parsing happens server-side. |
| 8 | **Keyset (cursor) pagination, per lane** | `(event_time, id)` keyset is $O(\log n)$ per page regardless of depth, so "walk backward through all history" needs no offset floor. Each lane evolves independently. |
| 9 | **Optimistic `next_cursor`** | Emitting a cursor whenever a page is full avoids a second COUNT query per lane; the client reconciles by clearing the cursor on an empty page. |
| 10 | **Range is a *filter*, not a paging horizon** | A preset like "Last 30 days" would disagree with the visible page (only `limit` events per lane load at first), looking broken. Default *All time* sends no lower bound; only an explicit Custom range bounds the window. |
| 11 | **Group by is client-side; range/scope refetch** | Re-bucketing existing events is instant and lossless; changing the filter or what data is requested must hit the server. |
| 12 | **Soft cap of 5 lanes** | Keeps a comparison readable and bounds the per-lane request fan-out. |
| 13 | **Deep links are inbound-only** | The URL seeds the page but is never rewritten as controls change — no URL/state divergence, and no accidental navigation. |
| 14 | **Default-off, dev-only mock** | Visual QA needs activity shapes real data cannot reliably produce (30-day gaps, 100-event spikes, empty lanes, pagination traps, failures). The mock rides the *real* endpoints so router validation, cursor format, and serialization are all exercised. |
| 15 | **`textContent`-built popup portal** | Summaries, labels, and URLs are untrusted ingested data; building DOM with `textContent` removes the injection vector, and an out-of-grid portal avoids the horizontal-scroll clipping that a CSS-only popup cannot solve. |
| 16 | **`STATE_CHANGE` synthetic marker for history** | The raw signal carries no relationship type for a state snapshot; a synthetic marker gives the UI a uniform card model and a humanized "Updated" label. |

---

## 9. Mock data (development only)

> **Development only.** The mock serves **invented** data through the real
> endpoints. It is **off by default** and must never be enabled in a real
> deployment. When active the service logs a startup warning.

### 9.1 Activation

1. **Turn it on** — set the scenario in `.env` (repo root):

   ```
   TIMELINE_MOCK_SCENARIO=even
   ```

   Blank/unset ⇒ mock **off** (real data). An unknown name raises a 400
   (`Invalid mock scenario`) on every activity request.

2. **Restart the app** so settings reload:

   ```
   docker compose up -d --force-recreate app
   ```

   Startup logs `[Activity][MOCK] Timeline mock mode is ENABLED …`.

3. **Switch scenario without a restart** (while mock mode is on) by appending
   `?mock=<scenario>` to an API request or the page URL. The override can only
   *switch* scenarios while mock mode is on — it can never enable mock mode by
   itself.

4. **Turn it off** — remove/blank `TIMELINE_MOCK_SCENARIO` and restart.

### 9.2 Scenario catalog

All 15 scenarios are registered in `src/app/api/activity/v1/mock_data.py`. The
mock builds a lane for **any** `{source}::{type}::{id}` key passed in
`wba_ids` (it parses the key, it does not check the entity exists), so you can
deep-link arbitrary ids beyond the suggestion catalogue.

| Scenario | Purpose | What it generates (lane 0 unless noted) | Manual-QA target |
|----------|---------|----------------------------------------|------------------|
| `even` | Baseline | Events every 3 days across the range, alternating `CREATED`/`REVIEWED` and `PullRequest`/`Issue`. Default fallback for `history` / `suggest_variants` timelines too. | General layout, cards, popup, click-to-Graph |
| `empty_range` | No data at all | Every lane returns zero events. | All-lanes-empty-in-range, custom range with no events |
| `empty_lane` | One empty lane | Lane 0 empty; other lanes `even`. | "No activity in this range" note |
| `gaps_small` | Single-lane gap | Lane 0 drops days 5–7 (step 2 days); others `even`. | Empty cells with guides; a single-lane gap must **not** collapse the row |
| `gaps_global` | Global gap | All lanes drop days 8–11. | Collapsed idle separator spanning all lanes |
| `gap_30d` | Long dead zone | All lanes drop days 5–35 (uses ≥ 60-day range). | Collapsed 30-day gap (needs a Custom range > 35 days) |
| `gaps_staggered` | Non-aligned gaps | Per-lane gaps: lane 0 days 4–6, lane 1 days 9–12, lane 2 days 2–3; others `even`. | Staggered single-lane gaps |
| `spike_100` | Day spike | Lane 0 emits 100 `COMMITTED`/`Commit` events on day −3; others `even`. | Cell overflow stress (needs per-lane `limit` ≥ 20) |
| `cell_boundary` | Overflow boundaries | Lane 0 has days with 3 / 4 / 20 / 21 events; others `even`. | "+N more" at the cap boundaries |
| `time_edges` | Timestamp boundaries | Lane 0 events at local midnight, 23:59, month start/end, and a duplicate timestamp pair; others `even`. | Bucketing/day boundaries, duplicate-stamp ordering |
| `card_variety` | Card contract edges | Lane 0: null summary, very long summary, no URL, `<script>` string + unknown type + unknown source, non-ASCII text, a `Page`/confluence event. Lane 0 also has no avatar and a long label. | Card fallback, truncation, XSS-safe rendering, theming |
| `history` | State-change scope | Baseline `even` specs, materialized with synthetic `STATE_CHANGE` / populated `details`. | `scope=history` rendering |
| `pagination` | Paging traps | Lane 0 = `3×limit−5` events (≈3 pages); lane 1 = exactly `limit` (full page → **optimistic-cursor trap**: next page is empty); lanes ≥ 2 = 5 events (short page). | Load more, cursor clearing, exhaustion |
| `error_500` | Backend failure | Raises inside the service so the router's real 500 path runs. | Danger alert that preserves the last good render |
| `suggest_variants` | Typeahead | Fixed suggestion catalogue filtered by substring; the literal query `none` returns `[]`. Timeline requests fall back to `even`. | Entity selector, avatar vs icon, no-results state |

**Determinism:** ids are stable UUID5s and times are offsets from the range end,
so the same scenario + request is byte-identical across calls. Events stay
clamped to `[from, to]` and are returned newest-first.

### 9.3 Mock entity catalogue (`/activity/suggest`)

The mocked typeahead returns only these six entities. It filters by query
substring; a query matching nothing returns the whole catalogue, and the literal
query `none` returns `[]`.

| `wba_id` | Label | entity_type | source | avatar |
|----------|-------|-------------|--------|--------|
| `mock::Person::alice` | Alice Johnson | Person | github | yes |
| `mock::Person::bob` | Bob Smith | Person | github | no |
| `mock::Person::carol` | Carol Diaz | Person | jira | yes |
| `mock::PullRequest::142` | PR #142: Refactor scheduler | PullRequest | github | no |
| `mock::Issue::BUG-7` | BUG-7 Login fails | Issue | jira | no |
| `mock::Page::home` | Docs Home | Page | confluence | no |

### 9.4 Direct API examples

```bash
# Force a 30-day gap (mock mode on)
curl "http://localhost:8000/api/v1/activity/timeline?wba_ids=mock::Person::alice,mock::Person::bob&mock=gap_30d" | jq .

# Exercise the optimistic-cursor lane
curl "http://localhost:8000/api/v1/activity/timeline?wba_ids=mock::Person::alice&mock=pagination&limit=20" | jq '.lanes[0].next_cursor'

# Typeahead with no results
curl "http://localhost:8000/api/v1/activity/suggest?q=none&mock=suggest_variants" | jq .
```

---

## 10. Deferred / future work

- Outbound "View Timeline" buttons from Search, Graph, and Collaboration Network.
- Entity-specific Graph deep-link from a card click (currently plain `/app/graph`).
- Per-lane event totals in lane headers (needs a backend COUNT query).
- The related-entity id on activity cards (needs an additive API field).
- A single multi-lane request with real per-lane cursors (backend change).
- Touch/mobile-optimised interactions.
- Timeline backfill / replay.

---

## 11. Source map

| Area | Path |
|------|------|
| DB models | `src/app/db/models/activity_event.py`, `activity_action.py` |
| Migration | `src/app/alembic/versions/` (activity tables) |
| Ingestion writer | `src/connectors/consumers/activity_writer.py` — hook in `src/connectors/consumers/main.py` |
| API router / service / query / models | `src/app/api/activity/v1/{router,service,query,model}.py` |
| Dev mock | `src/app/api/activity/v1/mock_data.py` |
| Dash page | `src/app/dash_app/pages/timeline/{layout,callbacks,helpers,api}.py` |
| Page CSS | `src/app/dash_app/assets/executive-dashboard.css` (`.timeline-*`) |
| Lane tokens | `src/app/dash_app/styles.py` (`timeline.lane.1`–`.5`) |
| Route + sidebar | `src/app/dash_app/layout.py` |
| Tests | `tests/test_activity_api_unit.py`, `tests/test_activity_api_integration.py`, `tests/test_activity_timeline_ui_helpers.py`, `tests/test_activity_timeline_mock.py`, `tests/test_activity_timeline_edge_cases.py` |

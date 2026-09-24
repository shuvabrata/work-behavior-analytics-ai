# Activity Timeline Feature — Implementation Plan

> **Plan:** 026 (following existing plan numbering convention)
> **Date:** 2026-09-24
> **Design reference:** `plans/activity-timeline-feature.md`
> **Branch:** `feature/user-activity-timeline`

---

## Overview

Build a swimlane activity timeline for persons and objects, preserving historical
ActivitySignals with dedup, served via API, and rendered in a Dash swimlane view.

---

## Progress Legend

```
[ ] = Not started    [~] = In progress    [x] = Complete
```

All checkboxes in this plan use the format `- [ ] / - [x]`. Update them as you work.

---

## Phases

### Phase 0: Foundation — DB migration & models (est. 1–2 days)

**Objective:** Create the two Postgres tables and their SQLAlchemy models,
write and apply the Alembic migration.

**Progress:** [ ] Not started

#### Files to create

| File | Purpose | Status |
|------|---------|--------|
| `src/app/db/models/activity_event.py` | SQLAlchemy model for `activity_events` table | [ ] |
| `src/app/db/models/activity_action.py` | SQLAlchemy model for `activity_actions` table | [ ] |

#### Tasks

- [ ] **1. SQLAlchemy model: `ActivityEvent`** (`src/app/db/models/activity_event.py`)
  - `id` (BIGSERIAL PK)
  - `signal_id` (UUID, unique)
  - `source` (VARCHAR 32, not null)
  - `entity_type` (VARCHAR 32, not null)
  - `entity_id` (VARCHAR 255, not null)
  - `event_time` (TIMESTAMPTZ, not null)
  - `ingestion_time` (TIMESTAMPTZ, not null, server_default=func.now())
  - `attributes` (JSONB, not null)
  - `relationships` (JSONB, nullable)
  - `content_hash` (VARCHAR 64, not null)
  - `__table_args__`: `UniqueConstraint('source', 'entity_type', 'entity_id', 'event_time', 'content_hash')`
  - Index: `Index('idx_activity_events_lookup', 'entity_type', 'entity_id', 'event_time'.desc())`

- [ ] **2. SQLAlchemy model: `ActivityAction`** (`src/app/db/models/activity_action.py`)
  - `id` (BIGSERIAL PK)
  - `signal_id` (UUID, FK to `activity_events.signal_id`, not null)
  - `event_time` (TIMESTAMPTZ, not null)
  - `source_entity_type` (VARCHAR 32, not null)
  - `source_entity_id` (VARCHAR 255, not null)
  - `relationship_type` (VARCHAR 32, not null)
  - `target_entity_type` (VARCHAR 32, not null)
  - `target_entity_id` (VARCHAR 255, not null)
  - `summary` (VARCHAR 512, nullable)
  - `url` (VARCHAR 1024, nullable)
  - Index: `idx_activity_actions_source` on `(source_entity_type, source_entity_id, event_time.desc())`
  - Index: `idx_activity_actions_target` on `(target_entity_type, target_entity_id, event_time.desc())`
  - FK constraint with `ON DELETE CASCADE`

- [ ] **3. Register models in** `src/app/db/models/__init__.py`

- [ ] **4. Generate Alembic migration**
  ```bash
  cd src/app && alembic revision --autogenerate -m "add activity_events and activity_actions tables"
  cd ../..
  ```
  Review the generated migration; adjust index definitions if autogenerate
  doesn't capture `desc()` ordering.

- [ ] **5. Apply migration**
  ```bash
  cd src/app && alembic upgrade head && cd ../..
  ```

- [ ] **6. Automated tests:** Write unit tests for model instantiation, constraint enforcement,
  and FK cascade behavior.

#### Manual Validation

- [ ] **V0.1:** Log into Postgres and confirm both tables exist:
  ```bash
  docker compose exec postgres psql -U ${POSTGRES_USER} -d ${POSTGRES_DB} -c "\dt activity_*"
  ```
  Expected output: both `activity_events` and `activity_actions` tables listed.

- [ ] **V0.2:** Verify indexes exist:
  ```bash
  docker compose exec postgres psql -U ${POSTGRES_USER} -d ${POSTGRES_DB} -c "\di idx_activity_*"
  ```
  Expected: `idx_activity_events_lookup`, `idx_activity_actions_source`, `idx_activity_actions_target`.

- [ ] **V0.3:** Verify FK constraint:
  ```bash
  docker compose exec postgres psql -U ${POSTGRES_USER} -d ${POSTGRES_DB} -c "
    INSERT INTO activity_events (signal_id, source, entity_type, entity_id, event_time, attributes, content_hash)
    VALUES ('00000000-0000-0000-0000-000000000001', 'test', 'Person', 'test_user', NOW(), '{}', 'abc');
    INSERT INTO activity_actions (signal_id, event_time, source_entity_type, source_entity_id, relationship_type, target_entity_type, target_entity_id)
    VALUES ('00000000-0000-0000-0000-000000000001', NOW(), 'Person', 'test_user', 'CREATED', 'Issue', 'TEST-1');
    -- Should succeed
    SELECT * FROM activity_actions;
    -- Cleanup
    DELETE FROM activity_events WHERE signal_id = '00000000-0000-0000-0000-000000000001';
    -- Verify cascade: SELECT should return 0 rows
    SELECT count(*) FROM activity_actions WHERE signal_id = '00000000-0000-0000-0000-000000000001';
  "
  ```

---

### Phase 1: Ingestion — Consumer-side hook (est. 2–3 days)

**Objective:** Wire the signal-consumer to write to Postgres after Neo4j upsert,
with hybrid batching, dedup, and non-fatal failure semantics.

**Progress:** [ ] Not started

#### Files to create / modify

| File | Action | Purpose | Status |
|------|--------|---------|--------|
| `src/common/activity_signal/activity_writer.py` | **Create** | Async background writer — connects to Postgres via asyncpg, manages batching queue, performs dedup check + INSERT | [ ] |
| `src/connectors/consumers/main.py` | **Modify** | Add `activity_writer` initialization and hook after Neo4j upsert | [ ] |

#### Tasks

- [ ] **1. Create `activity_writer.py`** in `src/common/activity_signal/`
  - Class `ActivityWriter` using `asyncpg` pool
  - `__init__`: accept DATABASE_URL, create connection pool
  - `enqueue(signal)`: push signal into `asyncio.Queue`
  - Background task `_writer_loop`:
    - Collects signals from queue up to `100` items OR `5` seconds of inactivity
    - For each signal: compute `content_hash = sha256(json(attributes) + json(relationships))`
    - Perform dedup check: `SELECT content_hash FROM activity_events WHERE (source, entity_type, entity_id) = $1, $2, $3 ORDER BY event_time DESC LIMIT 1`
    - If hash differs → `INSERT INTO activity_events ...; decompose relationships into activity_actions rows`
    - If hash matches → skip
    - Wrap in try/except — on failure log warning and continue
  - `close()`: drain queue, close pool
  - Use `asyncpg` (no SQLAlchemy dependency — consumer doesn't have app deps)

- [ ] **2. Content hash calculation** — utility function in `activity_writer.py`:
  ```python
  import hashlib, json
  def _compute_content_hash(signal: ActivitySignal) -> str:
      payload = {
          "attributes": signal.attributes.model_dump(),
          "relationships": [r.model_dump() for r in signal.relationships],
      }
      return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
  ```

- [ ] **3. Relationship decomposition** — utility to flatten `signal.relationships[]` into `activity_actions` rows
               "source_entity_type": signal.entity_type,
               "source_entity_id": signal.id,
               "relationship_type": rel.type,
               "target_entity_type": rel.target.entity_type or "",
               "target_entity_id": rel.target.id or "",
               "summary": ...,  # extract from attributes
               "url": ...,  # extract from attributes
           })
       return actions
   ```

4. **Modify `signal-consumer/main.py`**
   - On startup: initialize `ActivityWriter(pool)`
   - After successful Neo4j upsert (line ~170): `await activity_writer.enqueue(signal)`
   - On shutdown: `await activity_writer.close()`

5. **Environment variable**: `DATABASE_URL` is already available in the consumer container
   (set by docker-compose). No new env vars needed.

- [ ] **6. Automated tests:**
  - Unit tests for content hash consistency (same input → same hash)
  - Unit tests for relationship decomposition
  - Integration test: run consumer with mock signals, verify rows in `activity_events` and `activity_actions`
  - Edge case: duplicate signal with same content_hash → verify no second row inserted
  - Edge case: Postgres connection failure → verify consumer continues (non-fatal)

#### Manual Validation

- [ ] **V1.1:** Deploy consumer with changes. Run a GitHub or Jira producer scan via docker-compose:
  ```bash
  docker compose run --rm github-producer
  ```
  Check consumer logs for `activity_writer` messages confirming writes.

- [ ] **V1.2:** Verify rows appeared in Postgres:
  ```bash
  docker compose exec postgres psql -U ${POSTGRES_USER} -d ${POSTGRES_DB} -c "
    SELECT count(*) FROM activity_events;
    SELECT source, entity_type, count(*) as events FROM activity_events GROUP BY source, entity_type ORDER BY events DESC;
    SELECT count(*) FROM activity_actions;
  "
  ```
  Expected: non-zero counts for both tables, with actions more numerous than events.

- [ ] **V1.3:** Run the same producer scan again. Verify no duplicate rows added:
  ```bash
  docker compose run --rm github-producer
  # Wait for consumer to finish
  docker compose exec postgres psql -U ${POSTGRES_USER} -d ${POSTGRES_DB} -c "
    SELECT 'events count: ' || count(*) FROM activity_events
    UNION ALL
    SELECT 'actions count: ' || count(*) FROM activity_actions;
  "
  ```
  Expected: counts should NOT double from the second scan (dedup working).

- [ ] **V1.4:** Verify an actual meaningful change still gets captured:
  - Create a new issue in Jira or a new PR in GitHub
  - Re-run the producer
  - Verify new rows appear for that entity

---

### Phase 2: API Layer (est. 2–3 days)

**Objective:** Build the FastAPI router, service, and query layers for the
`/api/v1/activity` endpoints.

**Progress:** [ ] Not started

#### Files to create

| File | Purpose | Status |
|------|---------|--------|
| `src/app/api/activity/v1/__init__.py` | Package init | [ ] |
| `src/app/api/activity/v1/model.py` | Pydantic request/response models | [ ] |
| `src/app/api/activity/v1/router.py` | FastAPI route definitions | [ ] |
| `src/app/api/activity/v1/service.py` | Business logic (parse WBA IDs, resolve cursors) | [ ] |
| `src/app/api/activity/v1/query.py` | SQL queries (via SQLAlchemy async) | [ ] |

#### Tasks

- [ ] **1. Model definitions** (`model.py`)
  - `TimelineRequest` — Pydantic model with `wba_ids`, `scope`, `from`, `to`, `cursor`, `limit`
  - `TimelineEvent` — `signal_id`, `event_time`, `relationship_type`, `summary`, `entity_type`, `source`, `url`, `details`
  - `TimelineLane` — `wba_id`, `entity_type`, `label`, `avatar_url`, `events: list[TimelineEvent]`, `total_count`, `next_cursor`
  - `TimelineResponse` — `lanes: list[TimelineLane]`, `meta`
  - `SuggestRequest` / `SuggestResponse` — for typeahead

- [ ] **2. Router** (`router.py`)
  - `GET /api/v1/activity/timeline` → delegates to `service.get_timeline()`
  - `GET /api/v1/activity/suggest?q=...` → delegates to existing search service
  - Register router in `src/app/main.py`

- [ ] **3. Service** (`service.py`)
  - `get_timeline(request)`: parse each WBA ID into `(source, entity_type, entity_id)`, fan out queries
  - `_resolve_display_label(wba_id)`: fetch Person name / Issue title from activity_events or Neo4j
  - `_encode_cursor(event_time, row_id)` / `_decode_cursor(cursor_str)`: base64 encode/decode
  - `_build_suggestions(query)`: delegate to existing search (Elasticsearch or Neo4j)

- [ ] **4. Query** (`query.py`)
  - `fetch_actions_for_entity(source, entity_type, entity_id, from_time, to_time, cursor, limit)`:
    ```sql
    SELECT * FROM activity_actions
    WHERE (
      (source_entity_type = $1 AND source_entity_id = $2)
      OR (target_entity_type = $1 AND target_entity_id = $2)
    )
    AND event_time >= $3 AND event_time <= $4
    AND (event_time, id) < ($5, $6)   -- cursor
    ORDER BY event_time DESC, id DESC
    LIMIT $7;
    ```
  - `fetch_event_history(source, entity_type, entity_id, from_time, to_time, cursor, limit)`:
    ```sql
    SELECT * FROM activity_events
    WHERE entity_type = $1 AND entity_id = $2
    AND event_time >= $3 AND event_time <= $4
    AND (event_time, id) < ($5, $6)
    ORDER BY event_time DESC, id DESC
    LIMIT $7;
    ```
  - Use SQLAlchemy `text()` + async execution (reuse `ASYNC_SESSION_LOCAL`)

- [ ] **5. Automated tests:**
  - Unit tests for cursor encode/decode round-trip
  - Unit tests for WBA ID parsing
  - Integration test: seed activity_actions rows, call API, verify correct lane splitting
  - Integration test: cursor pagination returns correct next pages

#### Manual Validation

- [ ] **V2.1:** Confirm the API responds:
  ```bash
  curl -s "http://localhost:8000/api/v1/activity/timeline?wba_ids=github::Person::alice&limit=5" | jq .
  ```
  Expected: JSON response with `lanes` array, each containing `events`, `total_count`, `next_cursor`.

- [ ] **V2.2:** Test multi-lane query:
  ```bash
  curl -s "http://localhost:8000/api/v1/activity/timeline?wba_ids=github::Person::alice,github::Person::bob&limit=3" | jq '.lanes | length'
  ```
  Expected: `2` lanes returned.

- [ ] **V2.3:** Verify cursor pagination:
  ```bash
  FIRST=$(curl -s "http://localhost:8000/api/v1/activity/timeline?wba_ids=github::Person::alice&limit=2")
  CURSOR=$(echo $FIRST | jq -r '.lanes[0].next_cursor')
  TOTAL=$(echo $FIRST | jq -r '.lanes[0].total_count')
  echo "Total: $TOTAL, Cursor: $CURSOR"
  SECOND=$(curl -s "http://localhost:8000/api/v1/activity/timeline?wba_ids=github::Person::alice&limit=2&cursor=$CURSOR")
  echo $SECOND | jq '.lanes[0].events | length'
  ```
  Expected: second page has 2 events (or fewer if exhausted). Events on page 2 are older than events on page 1.

- [ ] **V2.4:** Test time range filter:
  ```bash
  curl -s "http://localhost:8000/api/v1/activity/timeline?wba_ids=github::Person::alice&from=2026-09-01T00:00:00Z&to=2026-09-07T23:59:59Z" | jq '.lanes[0].total_count'
  ```
  Expected: count matches events within that week.

- [ ] **V2.5:** Test typeahead:
  ```bash
  curl -s "http://localhost:8000/api/v1/activity/suggest?q=ali" | jq .
  ```
  Expected: array of matching WBA IDs with labels.

- [ ] **V2.6:** Test error handling — invalid WBA ID:
  ```bash
  curl -s "http://localhost:8000/api/v1/activity/timeline?wba_ids=invalid::bad" | jq .
  ```
  Expected: graceful 400 with error detail (not a 500).

---

### Phase 3: Dash UI Page (est. 3–4 days)

**Objective:** Build the swimlane timeline page and register it in the Analytics gallery.

**Progress:** [ ] Not started

#### Files to create / modify

| File | Action | Purpose | Status |
|------|--------|---------|--------|
| `src/app/dash_app/pages/timeline/__init__.py` | **Create** | Package init; re-export `get_layout` | [ ] |
| `src/app/dash_app/pages/timeline/layout.py` | **Create** | Main swimlane layout builder | [ ] |
| `src/app/dash_app/pages/timeline/callbacks.py` | **Create** | Dash callbacks (data fetch, time range, pagination, entity selector) | [ ] |
| `src/app/analytics/registry.py` | **Modify** | Add `TimelineAnalytic` entry | [ ] |
| `src/app/dash_app/pages/analytics.py` | **Modify** | Render timeline card + wire callbacks | [ ] |
| `src/app/dash_app/layout.py` | **Modify** | Add route `/app/analytics/timeline` | [ ] |

#### Tasks

- [ ] **1. Create page package** `src/app/dash_app/pages/timeline/`
  - `__init__.py`: `__all__ = ["get_layout"]; from .layout import get_layout`
  - Match the existing page pattern (see `collaboration_network/` as reference)

- [ ] **2. Layout** (`layout.py`)
  - `get_layout() -> html.Div` — the main swimlane container
  - Entity selector bar at top:
    - Search input for typeahead (WBA ID search)
    - Chips/pills for selected entities (person/object avatars + remove button)
    - "Clear All" button
  - Time range controls:
    - Dropdown: Last 7d / 30d / 90d / Custom
    - DatePickerRange for custom
  - Swimlane container:
    - Left: time axis markers
    - Right: one horizontal lane per entity
    - Each lane: event cards positioned by time
    - Cards show: icon, title/name, time, hover popup with full details
  - Loading overlay + empty state

- [ ] **3. Callbacks** (`callbacks.py`)
  - `fetch_timeline_data`: on entity selection change / time range change / pagination
    → calls `fetch("/api/v1/activity/timeline?...")` → updates lane state
  - Clientside callback for infinite scroll: when user scrolls to bottom of a lane,
    fetch next page using `next_cursor` and append events
  - Typeahead: on input → debounced call to `/api/v1/activity/suggest` → show suggestions
  - Entity add/remove: update selected entities list, reload data
  - Theme-aware: lane colors adapt to light/dark theme tokens

- [ ] **4. Register in Analytics gallery**
  - `registry.py`: add `TimelineAnalytic(key="activity_timeline", ...)` alongside `COLLABORATION_NETWORK_ANALYTIC`
  - `analytics.py`:
    - Import `TIMELINE_ANALYTICS` from registry
    - Render card with "Open Visualization" button (`href="/app/analytics/timeline"`)
    - "Show Options" button toggles entity selector and time range controls
    - Reuse the same collapsible pattern from the collab network card

- [ ] **5. Register route** in `layout.py`:
  ```python
  if pathname == "/app/analytics/timeline":
      from app.dash_app.pages.timeline import get_layout as get_timeline_layout
      return get_timeline_layout()
  ```

- [ ] **6. Styling:**
  - Reuse existing CSS tokens from `styles.py` (Executive Dashboard theme)
  - Add lane-specific CSS to `executive-dashboard.css` if needed (`.timeline-lane`, `.timeline-event-card`, `.timeline-hover-popup`)
  - Ensure dark theme support

- [ ] **7. Automated tests:**
  - Unit tests for layout rendering (no crash)
  - Integration test: mock API response → verify cards rendered

#### Manual Validation

- [ ] **V3.1:** Navigate to Analytics gallery at `http://localhost:8000/app/analytics`.
  Expected: "Activity Timeline" card visible next to "Collaboration Network" with icon, description, "Open Visualization" and "Show Options" buttons.

- [ ] **V3.2:** Click "Show Options" on the timeline card.
  Expected: entity selector and time range controls appear below the card (collapsible, same pattern as Collaboration Network).

- [ ] **V3.3:** Click "Open Visualization" (or navigate to `/app/analytics/timeline`).
  Expected: swimlane page loads with vertical time axis on left and empty state ("Add entities to get started").

- [ ] **V3.4:** Type a person's name in the entity search bar. Select from suggestions.
  Expected: WBA ID chip/pill appears. Data loads into a swimlane. Event cards visible with colored dots/lines.

- [ ] **V3.5:** Add a second person/object.
  Expected: a second lane appears side-by-side. Each lane has its own events positioned chronologically.

- [ ] **V3.6:** Hover over an event card in a lane.
  Expected: popup appears with full details (title, time, description, URL).

- [ ] **V3.7:** Scroll down in a lane (or let infinite scroll trigger).
  Expected: more events load. No duplicate events on re-scroll.

- [ ] **V3.8:** Change time range to "Last 7 days".
  Expected: lanes re-render with only events from the past week. Empty lane if no events in that period.

- [ ] **V3.9:** Remove a lane by clicking the "x" on the entity chip.
  Expected: lane disappears, remaining lane(s) re-flow to fill width.

- [ ] **V3.10:** Toggle dark mode from the topbar theme icon.
  Expected: swimlane colors adapt — navy elements become lighter, cards get dark backgrounds, readability maintained.

- [ ] **V3.11:** Navigate to another page and back. Timeline state (selected entities, time range) should persist if using `dcc.Store`, or reset gracefully.

---

### Phase 4: Integration & Polish (est. 1–2 days)

**Objective:** Wire up cross-page deep-linking, performance tuning, and documentation.

**Progress:** [ ] Not started

#### Tasks

- [ ] **1. Deep-linking from Search** — In `src/app/dash_app/pages/search.py`, add "View Timeline" button in person/object result cards. Navigate to `/app/analytics/timeline?wba_ids=github::Person::alice`

- [ ] **2. Deep-linking from Graph** — In node panel, add "View Timeline" button. Pass `wba_id` via URL parameter.

- [ ] **3. Deep-linking from Collaboration Network** — In collab network node hover/popup, add "View Timeline" link.

- [ ] **4. Performance:**
  - Monitor query times for `activity_actions` with large datasets (100K+ rows)
  - Add `EXPLAIN ANALYZE` checks on the index usage
  - Consider connection pooling tuning for asyncpg

- [ ] **5. Docker:** Ensure `DATABASE_URL` env var is passed in the consumer's docker-compose service (verify it's already set from the app service config).

- [ ] **6. Documentation:**
  - Add a note to `USER_GUIDE.md` about the new Activity Timeline feature
  - Update `DEVELOPER_QUICK_START.md` if needed
  - Update the design doc reference in `.github/copilot-instructions.md` if appropriate

#### Manual Validation

- [ ] **V4.1:** Search for a person on the Search page (`/app/search?q=alice`). Click the result. Expected: "View Timeline" button is present in the result card.

- [ ] **V4.2:** Click "View Timeline" from a Search result. Expected: navigates to `/app/analytics/timeline?wba_ids=github::Person::alice` with the person's lane pre-loaded.

- [ ] **V4.3:** In the Graph page, click on a Person node. Expected: the node detail panel has a "View Timeline" button.

- [ ] **V4.4:** Click "View Timeline" from the Graph node panel. Expected: navigates to timeline with that entity pre-loaded.

- [ ] **V4.5:** In Collaboration Network, hover over or click a node. Expected: popup has "View Timeline" link that navigates correctly.

- [ ] **V4.6:** Run a heavy scan (e.g., full GitHub or Jira re-sync). Check API response times:
  ```bash
  time curl -s "http://localhost:8000/api/v1/activity/timeline?wba_ids=github::Person::alice&limit=50" > /dev/null
  ```
  Expected: response in under 500ms even with 100K+ rows in the tables.

---

## Dependency Graph

```
Phase 0 (DB models + migration)
    │
    ▼
Phase 1 (Consumer ingestion) ──→ Phase 2 (API layer)
                                       │
                                       ▼
                                  Phase 3 (Dash UI page)
                                       │
                                       ▼
                                  Phase 4 (Integration + polish)
```

- Phases 0 → 1 → 2 → 3 are strictly sequential.
- Phase 4 can overlap with Phase 3 (deep-linking can be partially built alongside the UI).

## Files Changed Summary

### New files

| # | File | Phase |
|---|------|-------|
| 1 | `src/app/db/models/activity_event.py` | 0 |
| 2 | `src/app/db/models/activity_action.py` | 0 |
| 3 | `src/common/activity_signal/activity_writer.py` | 1 |
| 4 | `src/app/api/activity/v1/__init__.py` | 2 |
| 5 | `src/app/api/activity/v1/model.py` | 2 |
| 6 | `src/app/api/activity/v1/router.py` | 2 |
| 7 | `src/app/api/activity/v1/service.py` | 2 |
| 8 | `src/app/api/activity/v1/query.py` | 2 |
| 9 | `src/app/dash_app/pages/timeline/__init__.py` | 3 |
| 10 | `src/app/dash_app/pages/timeline/layout.py` | 3 |
| 11 | `src/app/dash_app/pages/timeline/callbacks.py` | 3 |

### Modified files

| # | File | Phase | Change |
|---|------|-------|--------|
| 1 | `src/app/db/models/__init__.py` | 0 | Register ActivityEvent + ActivityAction |
| 2 | `src/connectors/consumers/main.py` | 1 | Add ActivityWriter init + enqueue hook + shutdown |
| 3 | `src/app/main.py` | 2 | Register activity_v1 router |
| 4 | `src/app/analytics/registry.py` | 3 | Add TimelineAnalytic |
| 5 | `src/app/dash_app/pages/analytics.py` | 3 | Render timeline card + controls |
| 6 | `src/app/dash_app/layout.py` | 3 | Add `/app/analytics/timeline` route |
| 7 | `src/app/dash_app/pages/search.py` | 4 | Add "View Timeline" button |
| 8 | `src/app/dash_app/pages/graph/utils/data_transform.py` | 4 | Add "View Timeline" to node panel |
| 9 | `src/app/dash_app/pages/collaboration_network/layout.py` | 4 | Add "View Timeline" link |
| 10 | `docker-compose.yml` | 4 | Verify DATABASE_URL passes to consumer (should already be set) |

## Estimated Effort

| Phase | Days | Dependencies |
|-------|------|-------------|
| Phase 0 — Foundation | 1–2 | None |
| Phase 1 — Ingestion | 2–3 | Phase 0 |
| Phase 2 — API | 2–3 | Phase 0 |
| Phase 3 — Dash UI | 3–4 | Phase 2 |
| Phase 4 — Integration | 1–2 | Phase 2 (can overlap w/ Phase 3) |
| **Total** | **9–14** | |
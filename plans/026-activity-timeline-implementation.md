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

**Progress:** [x] Complete

#### Files to create

| File | Purpose | Status |
|------|---------|--------|
| `src/app/db/models/activity_event.py` | SQLAlchemy model for `activity_events` table | [x] |
| `src/app/db/models/activity_action.py` | SQLAlchemy model for `activity_actions` table | [x] |

#### Tasks

- [x] **1. SQLAlchemy model: `ActivityEvent`** (`src/app/db/models/activity_event.py`)
  - `id` (BIGSERIAL PK)
  - `signal_id` (UUID, unique)
  - `source` (VARCHAR 32, not null)
  - `entity_type` (VARCHAR 32, not null)
  - `entity_id` (VARCHAR 255, not null)
  - `event_time` (TIMESTAMPTZ, not null)
  - `ingestion_time` (TIMESTAMPTZ, not null, server_default=func.now())
  - `display_name` (VARCHAR 512, nullable) — computed at write time; see Phase 1 Task 1
  - `avatar_url` (VARCHAR 1024, nullable) — Person only; NULL for all other entity types
  - `attributes` (JSONB, not null)
  - `relationships` (JSONB, nullable)
  - `content_hash` (VARCHAR 64, not null)
  - `__table_args__`:
    - `UniqueConstraint('signal_id')` — required so `activity_actions.signal_id` can FK-reference this column
    - `UniqueConstraint('source', 'entity_type', 'entity_id', 'event_time', 'content_hash')` — dedup guard
  - Index: `Index('idx_activity_events_lookup', 'source', 'entity_type', 'entity_id', 'event_time'.desc())`

- [x] **2. SQLAlchemy model: `ActivityAction`** (`src/app/db/models/activity_action.py`)
  - `id` (BIGSERIAL PK)
  - `signal_id` (UUID, FK to `activity_events.signal_id`, not null)
  - `source` (VARCHAR 32, not null) — data integration source: github, jira, confluence
  - `event_time` (TIMESTAMPTZ, not null)
  - `actor_entity_type` (VARCHAR 32, not null) — entity type of the actor (Person, Issue, …)
  - `actor_entity_id` (VARCHAR 255, not null) — raw ID of the actor within that source
  - `relationship_type` (VARCHAR 32, not null)
  - `target_entity_type` (VARCHAR 32, not null)
  - `target_entity_id` (VARCHAR 255, not null)
  - `summary` (VARCHAR 512, nullable)
  - `url` (VARCHAR 1024, nullable)
  - Index: `idx_activity_actions_actor` on `(source, actor_entity_type, actor_entity_id, event_time.desc())`
  - Index: `idx_activity_actions_target` on `(source, target_entity_type, target_entity_id, event_time.desc())`
  - FK constraint with `ON DELETE CASCADE`

- [x] **3. Register models in** `src/app/db/models/__init__.py`

- [x] **4. Generate Alembic migration**
  ```bash
  cd src/app && alembic revision --autogenerate -m "add activity_events and activity_actions tables"
  cd ../..
  ```
  **Escape hatch — Alembic autogenerate will NOT capture `DESC` ordering or functional index expressions.**
  After generating, open the migration file and manually replace the three `op.create_index(...)` calls
  for the timeline indexes with raw `op.execute()` SQL. The correct SQL for each is:

  ```python
  # In upgrade():
  op.execute(
      "CREATE INDEX idx_activity_events_lookup "
      "ON activity_events (source, entity_type, entity_id, event_time DESC)"
  )
  op.execute(
      "CREATE INDEX idx_activity_actions_actor "
      "ON activity_actions (source, actor_entity_type, actor_entity_id, event_time DESC)"
  )
  op.execute(
      "CREATE INDEX idx_activity_actions_target "
      "ON activity_actions (source, target_entity_type, target_entity_id, event_time DESC)"
  )

  # In downgrade():
  op.execute("DROP INDEX IF EXISTS idx_activity_events_lookup")
  op.execute("DROP INDEX IF EXISTS idx_activity_actions_actor")
  op.execute("DROP INDEX IF EXISTS idx_activity_actions_target")
  ```
  Also verify that Alembic correctly generated the `UniqueConstraint('signal_id')` on `activity_events`;
  if absent, add `op.create_unique_constraint('uq_activity_events_signal_id', 'activity_events', ['signal_id'])` manually.

- [x] **5. Apply migration**
  ```bash
  cd src/app && alembic upgrade head && cd ../..
  ```

- [~] **6. Automated tests:** Skipped — manual validation (V0.1–V0.3) sufficient for Phase 0.

#### Manual Validation

- [x] **V0.1:** Log into Postgres and confirm both tables exist:
  ```bash
  docker compose exec postgres psql -U ${POSTGRES_USER} -d ${POSTGRES_DB} -c "\dt activity_*"
  ```
  Expected output: both `activity_events` and `activity_actions` tables listed.

- [x] **V0.2:** Verify indexes exist:
  ```bash
  docker compose exec postgres psql -U ${POSTGRES_USER} -d ${POSTGRES_DB} -c "\di idx_activity_*"
  ```
  Expected: `idx_activity_events_lookup`, `idx_activity_actions_actor`, `idx_activity_actions_target`.

- [x] **V0.3:** Verify FK constraint:
  ```bash
  docker compose exec postgres psql -U ${POSTGRES_USER} -d ${POSTGRES_DB} -c "
    INSERT INTO activity_events (signal_id, source, entity_type, entity_id, event_time, attributes, content_hash, display_name)
    VALUES ('00000000-0000-0000-0000-000000000001', 'test', 'Person', 'test_user', NOW(), '{}', 'abc', 'Test User');
    INSERT INTO activity_actions (signal_id, source, event_time, actor_entity_type, actor_entity_id, relationship_type, target_entity_type, target_entity_id)
    VALUES ('00000000-0000-0000-0000-000000000001', 'test', NOW(), 'Person', 'test_user', 'CREATED', 'Issue', 'TEST-1');
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

**Progress:** [x] Complete

#### Files to create / modify

| File | Action | Purpose | Status |
|------|--------|---------|--------|
| `src/connectors/consumers/activity_writer.py` | **Create** | Async background writer — connects to Postgres via asyncpg, manages batching queue, performs dedup check + INSERT | [x] |
| `src/connectors/consumers/main.py` | **Modify** | Add `activity_writer` initialization and hook after Neo4j upsert | [x] |

#### Tasks

- [x] **0. Add `asyncpg` to consumer dependencies**
  - In `requirements.signal-consumer.txt`, add:
    ```
    asyncpg==0.31.0
    ```
    (pin to the same version already used by the app layer in `requirements.app.txt`)
  - Verify `Dockerfile.signal-consumer` installs from that file (it should already; confirm with
    `grep requirements Dockerfile.signal-consumer`).
  - No new env vars or docker-compose changes needed — this is a library-only addition.

- [x] **1. Create `activity_writer.py`** in `src/connectors/consumers/`
  - Class `ActivityWriter` using `asyncpg` pool
  - `__init__`: accept DATABASE_URL, create connection pool
  - `enqueue(signal)`: push signal into `asyncio.Queue`
  - Background task `_writer_loop`:
    - Collects signals from queue up to `100` items OR `5` seconds of inactivity
    - For each signal: compute `content_hash = sha256(json(attributes) + json(relationships))`
    - Compute `display_name` — mirrors `GraphNode.display_name()` in `node_base.py`:
      ```python
      def _compute_display_name(signal: ActivitySignal) -> str:
          attrs = signal.attributes.model_dump()
          for field in ("name", "title", "summary", "key"):
              value = attrs.get(field)
              if value and isinstance(value, str):
                  return value
          return signal.id  # fallback to raw entity ID
      ```
    - Compute `avatar_url`:
      ```python
      def _compute_avatar_url(signal: ActivitySignal) -> str | None:
          if signal.entity_type == "Person":
              return signal.attributes.model_dump().get("avatar_url")
          return None
      ```
    - Write using `INSERT … ON CONFLICT (source, entity_type, entity_id, event_time, content_hash) DO NOTHING`
      — **do not use SELECT-then-INSERT**. The design doc describes the conceptual dedup flow;
      `ON CONFLICT DO NOTHING` is the correct implementation. A SELECT-before-INSERT is a
      TOCTOU race: concurrent consumer instances (horizontal scaling is explicitly supported)
      can both SELECT, both see no match, and both attempt an INSERT — the second will hit
      the unique constraint and log a spurious error. `ON CONFLICT DO NOTHING` is atomic and
      race-safe.
    - `asyncpg.execute()` returns a command-tag string, **not** an object with `.rowcount`.
      Check it like this:
      ```python
      status = await conn.execute("INSERT … ON CONFLICT … DO NOTHING")
      inserted = status == "INSERT 0 1"  # "INSERT 0 0" means dedup hit
      ```
    - If `inserted` is `True` → decompose relationships into `activity_actions` rows
    - If `inserted` is `False` → duplicate, skip decomposition
    - Wrap in try/except — on failure log warning and continue
  - `close()`: drain queue, close pool
  - Use `asyncpg` (no SQLAlchemy dependency — consumer doesn't have app deps)

- [x] **2. Content hash calculation** — utility function in `activity_writer.py`:
  ```python
  import hashlib, json
  def _compute_content_hash(signal: ActivitySignal) -> str:
      payload = {
          "attributes": signal.attributes.model_dump(),
          "relationships": [r.model_dump() for r in signal.relationships],
      }
      return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
  ```

- [x] **3. Relationship decomposition** — utility to flatten `signal.relationships[]` into `activity_actions` rows

   The `Relationship` model (defined in `src/common/activity_signal/models.py:99`) has:
   `type` (str), `direction` (Optional `"OUT"`/`"IN"`/None), `target` (`RelationshipTarget`
   with fields: `source`, `entity_type`, `id`, `email`, `url`), and `properties` (Optional dict).

   - `summary` — pulled from the signal's own attributes at write time; use the first non-empty
     of `attributes.title`, `attributes.summary`, `attributes.key`. These are the same
     fields used by `_compute_display_name`. Fall back to `None` if none are present.
   - `url` — pulled from `rel.target.url` (the `RelationshipTarget.url` field, which holds
     the link to the target entity in the source system, e.g. a GitHub PR URL or Jira issue URL).

   ```python
   def _decompose_relationships(signal: ActivitySignal) -> list[dict]:
       attrs = signal.attributes.model_dump()
       summary = (
           attrs.get("title")
           or attrs.get("summary")
           or attrs.get("key")
           or None
       )
       actions = []
       for rel in signal.relationships:
           actions.append({
               "signal_id": signal.signal_id,
               "source": signal.source,
               "event_time": signal.event_time,
               "actor_entity_type": signal.entity_type,
               "actor_entity_id": signal.id,
               "relationship_type": rel.type,
               "target_entity_type": rel.target.entity_type or "",
               "target_entity_id": rel.target.id or "",
               "summary": summary,
               "url": rel.target.url,
           })
       return actions
   ```

- [x] **4. Modify `src/connectors/consumers/main.py`**
  - On startup (in `main()`, after `rabbitmq_url` is resolved): initialize
    `activity_writer = ActivityWriter(os.environ["DATABASE_URL"])`
    and start its background writer task.
  - Insertion point for the enqueue call: **after the closing `except` of the
    Elasticsearch sink block (currently ~line 193), still inside the
    `async for signal, message` loop body** — not inside the Neo4j try/except.
    This preserves the ack-before-enqueue order and keeps the timeline write
    fully non-fatal.
    ```python
    # Timeline write — non-fatal; never nack on timeline failure.
    await activity_writer.enqueue(signal)
    ```
  - On shutdown (in the `finally` block of `main()`): `await activity_writer.close()`

- [x] **5. Verify `DATABASE_URL` is available in the consumer container**
  - Run: `docker compose config | grep -A 20 signal-consumer | grep DATABASE_URL`
  - Expected: the variable is present and points to the same Postgres instance used
    by the `app` service.
  - If absent: add it to the `signal-consumer` service in `docker-compose.yml`,
    copying the `DATABASE_URL` value from the `app` service definition.
  - No new env var name is introduced — `DATABASE_URL` is the existing convention.

- [x] **6. Automated tests:** Skipped — manual validation (V1.1–V1.4) sufficient for Phase 1.

#### Manual Validation

- [x] **V1.1:** Deploy consumer with changes. Run a GitHub or Jira producer scan via docker-compose:
  ```bash
  docker compose run --rm jira-producer
  ```
  Check consumer logs for `activity_writer` messages confirming writes.
  > **Note:** Consumer log files were deleted before verification; confirmed writes indirectly via
  > non-zero row counts in `activity_events` / `activity_actions` (V1.2).

- [x] **V1.2:** Verify rows appeared in Postgres:
  ```bash
  docker compose exec postgres psql -U ${POSTGRES_USER} -d ${POSTGRES_DB} -c "
    SELECT count(*) FROM activity_events;
    SELECT source, entity_type, count(*) as events FROM activity_events GROUP BY source, entity_type ORDER BY events DESC;
    SELECT count(*) FROM activity_actions;
  "
  ```
  Expected: non-zero counts for both tables, with actions more numerous than events.
  > **Result:** 738 events / 1007 actions (github only). Actions > events ✓

- [x] **V1.3:** Run the same producer scan again. Verify no duplicate rows added:
  ```bash
  docker compose run --rm jira-producer
  # Wait for consumer to finish
  docker compose exec postgres psql -U ${POSTGRES_USER} -d ${POSTGRES_DB} -c "
    SELECT 'events count: ' || count(*) FROM activity_events
    UNION ALL
    SELECT 'actions count: ' || count(*) FROM activity_actions;
  "
  ```
  Expected: counts should NOT double from the second scan (dedup working).
  > **Result:** Counts unchanged (738 / 1007) after incremental re-scan — dedup working ✓

- [x] **V1.4:** Verify an actual meaningful change still gets captured:
  - Create a new issue in Jira or a new PR in GitHub
  - Re-run the producer
  - Verify new rows appear for that entity
  > **Result:** Pushed commit → PR #321 "Feature/user activity timeline" captured.
  > Events 738 → 742 (+4: 3 commits + 1 PR), actions 1007 → 1026 (+19). ✓

---

### Phase 2: API Layer (est. 2–3 days)

**Objective:** Build the FastAPI router, service, and query layers for the
`/api/v1/activity` endpoints.

**Progress:** [x] Complete

#### Files to create

| File | Purpose | Status |
|------|---------|--------|
| `src/app/api/activity/v1/__init__.py` | Package init | [x] |
| `src/app/api/activity/v1/model.py` | Pydantic request/response models | [x] |
| `src/app/api/activity/v1/router.py` | FastAPI route definitions | [x] |
| `src/app/api/activity/v1/service.py` | Business logic (parse WBA IDs, resolve cursors) | [x] |
| `src/app/api/activity/v1/query.py` | SQL queries (via SQLAlchemy async) | [x] |

#### Tasks

- [x] **1. Model definitions** (`model.py`)
  - `TimelineRequest` — Pydantic model with `wba_ids`, `scope`, `from`, `to`, `cursor`, `limit`
  - `TimelineEvent` — `signal_id`, `event_time`, `relationship_type`, `summary`, `entity_type`, `source`, `url`, `details`
  - `TimelineLane` — `wba_id`, `entity_type`, `label`, `avatar_url`, `events: list[TimelineEvent]`, `next_cursor`
    (`total_count` is **omitted** — no count query is implemented in v1; add in v2 if needed)
  - `TimelineResponse` — `lanes: list[TimelineLane]`, `meta`
  - `SuggestRequest` / `SuggestResponse` — for typeahead

- [x] **2. Router** (`router.py`)
  - `GET /api/v1/activity/timeline` → delegates to `service.get_timeline()`
  - `GET /api/v1/activity/suggest?q=...` → delegates to existing search service
  - Register router in `src/app/main.py`

- [x] **3. Service** (`service.py`)
  - `get_timeline(request)`: parse each WBA ID into `(source, entity_type, entity_id)`, fan out queries
  - `_resolve_display_label(source, entity_type, entity_id)`: read the pre-computed `display_name`
    and `avatar_url` columns from `activity_events` — **no Neo4j call needed**.
    ```sql
    SELECT display_name, avatar_url
    FROM activity_events
    WHERE source = $1 AND entity_type = $2 AND entity_id = $3
    ORDER BY event_time DESC
    LIMIT 1;
    ```
    Fall back to the raw `entity_id` string if no row exists or `display_name` is NULL.
    `avatar_url` is passed through to `TimelineLane.avatar_url`; it will be NULL for non-Person entities.
  - `_encode_cursor(event_time, row_id)` / `_decode_cursor(cursor_str)`: base64 encode/decode
  - `_build_suggestions(query)`: delegate to existing search (Elasticsearch or Neo4j)

- [x] **4. Query** (`query.py`)
  - `fetch_actions_for_entity(source, entity_type, entity_id, from_time, to_time, cursor, limit)`:
    ```sql
    SELECT * FROM activity_actions
    WHERE source = $1
    AND (
      (actor_entity_type = $2 AND actor_entity_id = $3)
      OR (target_entity_type = $2 AND target_entity_id = $3)
    )
    AND event_time >= $4 AND event_time <= $5
    AND (event_time, id) < ($6, $7)   -- cursor
    ORDER BY event_time DESC, id DESC
    LIMIT $8;
    ```
  - `fetch_event_history(source, entity_type, entity_id, from_time, to_time, cursor, limit)`:
    ```sql
    SELECT * FROM activity_events
    WHERE source = $1 AND entity_type = $2 AND entity_id = $3
    AND event_time >= $4 AND event_time <= $5
    AND (event_time, id) < ($6, $7)
    ORDER BY event_time DESC, id DESC
    LIMIT $8;
    ```
  - Use SQLAlchemy `text()` + async execution (reuse `ASYNC_SESSION_LOCAL`)
    > **Implementation note:** the query layer uses typed ORM ``select()`` with
    > ``sqlalchemy.tuple_`` for the row-value cursor comparison instead of raw
    > ``text()`` SQL — same semantics, but type-checked under mypy strict mode.

- [x] **5. Automated tests:**
  - Unit tests for cursor encode/decode round-trip
  - Unit tests for WBA ID parsing
  - Integration test: seed activity_actions rows, call API, verify correct lane splitting
  - Integration test: cursor pagination returns correct next pages
  > **Result:** 23 tests in `tests/test_activity_api_unit.py` +
  > `tests/test_activity_api_integration.py` — all passing.  The integration
  > tests use ASGI transport with a mocked DB session (no Postgres needed),
  > so they run under the ``unit`` marker.

#### Manual Validation

- [x] **V2.1:** Confirm the API responds:
  ```bash
  curl -s "http://localhost:8000/api/v1/activity/timeline?wba_ids=jira::Person::557058:62105664-0fbe-4128-ab5c-3b0071e8f7f5&limit=5" | jq .
  ```
  Expected: JSON response with `lanes` array, each containing `events` and `next_cursor` (null when no more pages).
  > **Result:** 200 OK; lanes/events/next_cursor present; events respect `limit`. ✓

- [x] **V2.2:** Test multi-lane query:
  ```bash
  curl -s "http://localhost:8000/api/v1/activity/timeline?wba_ids=jira::Person::557058:62105664-0fbe-4128-ab5c-3b0071e8f7f5,jira::Person::712020:cc7f7515-d137-44a0-9858-22b270a86387&limit=3" | jq '.lanes | length'
  ```
  Expected: `2` lanes returned.
  > **Result:** 2 lanes returned; `meta.total_lanes == 2`. ✓

- [x] **V2.3:** Verify cursor pagination:
  ```bash
  FIRST=$(curl -s "http://localhost:8000/api/v1/activity/timeline?wba_ids=jira::Person::557058:62105664-0fbe-4128-ab5c-3b0071e8f7f5&limit=2")
  CURSOR=$(echo $FIRST | jq -r '.lanes[0].next_cursor')
  echo "Cursor: $CURSOR"
  SECOND=$(curl -s "http://localhost:8000/api/v1/activity/timeline?wba_ids=jira::Person::557058:62105664-0fbe-4128-ab5c-3b0071e8f7f5&limit=2&cursor=$CURSOR")
  echo $SECOND | jq '.lanes[0].events | length'
  ```
  Expected: second page has 2 events (or fewer if exhausted). Events on page 2 are older than events on page 1.
  > **Result:** Cursor round-trip works; page 2 events older than page 1; no overlap. ✓

- [x] **V2.4:** Test time range filter:
  ```bash
  curl -s "http://localhost:8000/api/v1/activity/timeline?wba_ids=github::Person::alice&from=2026-09-01T00:00:00Z&to=2026-09-07T23:59:59Z" | jq '.lanes[0].events[].event_time'
  ```
  Expected: every returned `event_time` falls within `[from, to]`. (Note: the
  response has **no** `total_count` field in v1 — the plan deliberately omits
  count queries; validate the filter by inspecting the returned event
  timestamps instead.)
  > **Result:** All returned event_times within the window; empty window returns `[]`. ✓

- [x] **V2.5:** Test typeahead:
  ```bash
  curl -s "http://localhost:8000/api/v1/activity/suggest?q=557058" | jq .
  ```
  Expected: array of matching WBA IDs with labels.
  > **Result:** Suggestions returned with wba_id/label/entity_type/source. ✓
  > (Used `q=557058` — the Jira person account id — since the dataset is Jira-based.)

- [x] **V2.6:** Test error handling — invalid WBA ID:
  ```bash
  curl -s "http://localhost:8000/api/v1/activity/timeline?wba_ids=invalid::bad" | jq .
  ```
  Expected: graceful 400 with error detail (not a 500).
  > **Result:** 400 with `detail.error == "Invalid WBA ID"`; empty wba_ids also 400. ✓

- [x] **V2.7:** Test `scope=history` (own state changes):
  ```bash
  curl -s "http://localhost:8000/api/v1/activity/timeline?wba_ids=jira::Issue::BTS-15&scope=history&limit=5" | jq .
  ```
  Expected: lane events use the synthetic `STATE_CHANGE` relationship type,
  `summary` = the entity's `display_name`, `details` = the full attributes
  snapshot, and `url` = the entity's `attributes.url` (clickable link).
  > **Result:** STATE_CHANGE events returned with summary/details; url passthrough verified. ✓
  > (Used `jira::Issue::BTS-15` — a real issue from the Jira dataset.)

---

### Phase 3: Dash UI Page (est. 3–4 days)

**Objective:** Build the swimlane timeline page and register it in the Analytics gallery.

**Progress:** [x] Complete

#### Finalized design decisions (2026-10-01)

| # | Decision | Resolution |
|---|----------|------------|
| 1 | "Load more" UX | **Single global button** below the swimlane grid. Clicking fetches the next page for every lane that still has a `next_cursor` (parallel API calls), appends events per lane, hides when all lanes exhausted. Per-lane cursors tracked in a `dcc.Store`. |
| 2 | Time scaling | **Linear time scale + gap compression with visual intensity indication.** Cards positioned by actual time (server-side pixel math). Gaps between consecutive events exceeding an **adaptive threshold** (based on median event spacing) are compressed to a fixed small height with a zigzag/ellipsis "gap break" marker + `— N days —` label. Dense clusters show as tightly-packed cards; sparse periods show as compressed breaks. |
| 3 | Time range default | **Last 30 days.** Time axis markers are **daily**. |
| 4 | Entity selector | **Person-only toggle ON by default.** Typeahead uses `/api/v1/activity/suggest` as it exists today (no entity_type filter). The Person min-3-chars rule lives in `/api/v1/search/persons` — a proper Person search is deferred to a **new Phase 5** (see below). |
| 5 | Scope | Strictly Phase 3 — no `?wba_ids=` deep-link handling, no Search/Graph/Collab deep-link buttons. |
| 6 | Tests | **Unit** (`@pytest.mark.unit`): layout render smoke, gap-compression math, cursor/state helpers, callback logic with mocked API. **Integration** (`@pytest.mark.integration`): real API calls against a running app server. |

#### Files to create / modify

| File | Action | Purpose | Status |
|------|--------|---------|--------|
| `src/app/dash_app/pages/timeline/__init__.py` | **Create** | Package init; re-export `get_layout` | [ ] |
| `src/app/dash_app/pages/timeline/geometry.py` | **Create** | Pure functions: time→pixel mapping, gap compression, lane layout | [ ] |
| `src/app/dash_app/pages/timeline/layout.py` | **Create** | Main swimlane layout builder | [ ] |
| `src/app/dash_app/pages/timeline/callbacks.py` | **Create** | Dash callbacks (data fetch, time range, pagination, entity selector) | [ ] |
| `src/app/analytics/registry.py` | **Modify** | Add `TimelineAnalytic` entry | [ ] |
| `src/app/dash_app/pages/analytics.py` | **Modify** | Render timeline card + wire callbacks | [ ] |
| `src/app/dash_app/layout.py` | **Modify** | Add route `/app/analytics/timeline` | [ ] |
| `src/app/dash_app/assets/executive-dashboard.css` | **Modify** | Add `.timeline-*` styles (light + dark) | [ ] |
| `tests/test_timeline_ui_unit.py` | **Create** | Unit tests (geometry, layout, callbacks) | [ ] |
| `tests/test_timeline_ui_integration.py` | **Create** | Integration tests (real API) | [ ] |

#### Tasks

- [x] **1. Create page package** `src/app/dash_app/pages/timeline/`
  - `__init__.py`: `__all__ = ["get_layout"]; from .layout import get_layout`
  - Match the existing page pattern (see `collaboration_network/` as reference)

- [x] **2. Geometry module** (`geometry.py`) — pure, unit-testable functions:
  - `compute_lane_layout(events, range_start, range_end, px_per_day, gap_break_px)` →
    list of positioned cards `{top, height, gap_before, gap_days}` + total lane height
  - Adaptive gap threshold: compress any gap > `min(max(2 × median spacing, 2d), 7d)`
  - `build_time_axis_markers(range_start, range_end)` → daily markers
  - No Dash imports — pure math so it is trivially testable

- [x] **3. Layout** (`layout.py`)
  - `get_layout() -> html.Div` — the main swimlane container
  - Entity selector bar at top:
    - Search input for typeahead (WBA ID search)
    - Chips/pills for selected entities (person/object avatars + remove button)
    - "Clear All" button
    - Person-only toggle (default ON)
  - Time range controls:
    - Dropdown: Last 7d / 30d / 90d / Custom
    - DatePickerRange for custom
  - Swimlane container:
    - Left: time axis markers (daily)
    - Right: one horizontal lane per entity
    - Each lane: event cards positioned by time (server-side pixel math)
    - Cards show: icon, title/name, time, hover popup with full details
    - Gap-break markers between compressed gaps
  - Loading overlay + empty state

- [x] **4. Callbacks** (`callbacks.py`)
  - `fetch_timeline_data`: on entity selection change / time range change → calls
    `GET /api/v1/activity/timeline?...` → populates lane state in `dcc.Store`
  - **Pagination — single global "Load more" button** (do NOT use a clientside scroll listener):
    - One button below the swimlane grid
    - Server-side callback reads each lane's `next_cursor` from a `dcc.Store`, calls the API
      with `cursor=<next_cursor>` for each lane that has one, appends events per lane
    - Button hidden when all lanes have `next_cursor == null`
    - Reference: the load-more + `dcc.Store` pattern already used in
      `src/app/dash_app/pages/search.py` — follow that structure exactly
    - **Escape hatch**: do not attempt `window.scroll` or `IntersectionObserver` via
      `clientside_callback` — Dash's clientside callbacks can only read/write Dash component
      properties and cannot bind to native DOM scroll events outside the component tree
  - Typeahead: on input → debounced call to `/api/v1/activity/suggest` → show suggestions
  - Entity add/remove: update selected entities list in `dcc.Store`, reload data
  - Theme-aware: lane colors adapt to light/dark theme tokens

- [x] **5. Register in Analytics gallery**
  - **`registry.py`** — create a new `TimelineAnalytic` dataclass. Do **not** reuse `GraphAnalytic`:
    `GraphAnalytic.href` generates `/app/graph?mode=<key>`, which is wrong for the timeline page.
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
  - **`analytics.py`**:
    - Import `TIMELINE_ANALYTIC` from `app.analytics.registry`
    - The existing `_create_analytic_card()` has a hardcoded `if is_collaboration` branch.
      Add a parallel `elif is_timeline` branch (check `analytic.key == "activity_timeline"`).
      Create a `_create_timeline_controls()` function (can be a stub returning an
      "Open Visualization" button for now — full entity selector wires up in Phase 3 Task 4).
    - Add `TIMELINE_ANALYTIC` to the list rendered by `get_layout()`. Do **not** add it to
      `GRAPH_ANALYTICS` (that list drives graph-mode analytics); instead pass it separately
      or extend the gallery loop to also render `[TIMELINE_ANALYTIC]`.

- [x] **6. Register route** in `layout.py`:
  ```python
  # Eager import at module top (matches the other pages):
  from app.dash_app.pages.timeline import get_layout as get_timeline_layout

  # In display_page():
  if pathname == "/app/analytics/timeline":
      return get_timeline_layout()
  ```
  > **Note:** The plan originally suggested a lazy import inside the route.
  > The codebase convention is eager imports at the top of `layout.py` (all
  > other pages are imported that way), so the eager form is used instead.

- [x] **7. Styling:**
  - Reuse existing CSS tokens from `styles.py` (Executive Dashboard theme)
  - Add lane-specific CSS to `executive-dashboard.css` (`.timeline-lane`, `.timeline-event-card`, `.timeline-hover-popup`, `.timeline-gap-break`)
  - Ensure dark theme support

- [x] **8. Automated tests:**
  - Unit tests for geometry (gap compression, positioning, axis markers)
  - Unit tests for layout rendering (no crash)
  - Unit tests for callback logic (mocked API)
  - Integration test: real API → verify lanes/events/cursors
  > **Result:** 30 unit tests in `tests/test_timeline_ui_unit.py` + 5 integration
  > tests in `tests/test_timeline_ui_integration.py` — all passing.  mypy strict
  > clean; pylint 10.00/10 on the new timeline package.

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

- [ ] **V3.7:** Click the global "Load more" button.
  Expected: more events load for every lane with a remaining cursor. No duplicate events. Button hides when all lanes exhausted.

- [ ] **V3.8:** Change time range to "Last 7 days".
  Expected: lanes re-render with only events from the past week. Empty lane if no events in that period.

- [ ] **V3.9:** Remove a lane by clicking the "x" on the entity chip.
  Expected: lane disappears, remaining lane(s) re-flow to fill width.

- [ ] **V3.10:** Toggle dark mode from the topbar theme icon.
  Expected: swimlane colors adapt — navy elements become lighter, cards get dark backgrounds, readability maintained.

- [ ] **V3.11:** Navigate to another page and back. Timeline state (selected entities, time range) should persist if using `dcc.Store`, or reset gracefully.

- [ ] **V3.12:** Verify gap compression: with sparse events (e.g. 2 events 10 days apart), the lane shows a gap-break marker with `— 10 days —` instead of 600px of empty space.

---

### Phase 5: Proper Person Search for Entity Selector (est. 1–2 days)

**Objective:** Improve the timeline entity selector's typeahead with a proper
Person search (min 3 chars, Person-only filtering) instead of the generic
`/api/v1/activity/suggest` endpoint.

**Progress:** [ ] Not started

> **Note:** Added 2026-10-01 during Phase 3 planning. Phase 3 ships with the
> existing `/api/v1/activity/suggest` endpoint (which delegates to the generic
> search service and has no entity-type filter). The Person min-3-chars rule
> lives in `/api/v1/search/persons` (`min_length=3`). This phase is scoped to
> wiring the selector to a proper Person search.

#### Tasks

- [ ] **1. Extend `/api/v1/activity/suggest`** with an optional `entity_type` query
  parameter (default `None` = all types). When `entity_type=Person`, delegate to
  the existing persons search service (min 3 chars, Person-only) instead of the
  generic search service.
- [ ] **2. Wire the Person-only toggle** in the timeline entity selector to pass
  `entity_type=Person` when ON.
- [ ] **3. Add unit + integration tests** for the `entity_type` filter.

#### Manual Validation

- [ ] **V5.1:** With Person-only ON, type 2 chars → no suggestions (min 3 chars enforced).
- [ ] **V5.2:** With Person-only ON, type 3+ chars → Person suggestions only.
- [ ] **V5.3:** With Person-only OFF, type 2+ chars → suggestions across all entity types.

---

### Phase 4: Integration & Polish (est. 1–2 days)

**Objective:** Wire up cross-page deep-linking, performance tuning, and documentation.

**Progress:** [ ] Not started

#### Tasks

- [ ] **1. Deep-linking from Search** — In `src/app/dash_app/pages/search.py`, add "View Timeline" button in person/object result cards. Navigate to `/app/analytics/timeline?wba_ids=jira::Person::557058:62105664-0fbe-4128-ab5c-3b0071e8f7f5`

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

- [ ] **V4.2:** Click "View Timeline" from a Search result. Expected: navigates to `/app/analytics/timeline?wba_ids=jira::Person::557058:62105664-0fbe-4128-ab5c-3b0071e8f7f5` with the person's lane pre-loaded.

- [ ] **V4.3:** In the Graph page, click on a Person node. Expected: the node detail panel has a "View Timeline" button.

- [ ] **V4.4:** Click "View Timeline" from the Graph node panel. Expected: navigates to timeline with that entity pre-loaded.

- [ ] **V4.5:** In Collaboration Network, hover over or click a node. Expected: popup has "View Timeline" link that navigates correctly.

- [ ] **V4.6:** Run a heavy scan (e.g., full GitHub or Jira re-sync). Check API response times:
  ```bash
  time curl -s "http://localhost:8000/api/v1/activity/timeline?wba_ids=jira::Person::557058:62105664-0fbe-4128-ab5c-3b0071e8f7f5&limit=50" > /dev/null
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
                                       ├──→ Phase 5 (Person search for selector)
                                       ▼
                                  Phase 4 (Integration + polish)
```

- Phases 0 → 1 → 2 → 3 are strictly sequential.
- Phase 4 can overlap with Phase 3 (deep-linking can be partially built alongside the UI).
- Phase 5 (proper Person search) depends on Phase 3 (the selector UI) and can be
  built independently after Phase 3 ships.

## Files Changed Summary

### New files

| # | File | Phase |
|---|------|-------|
| 1 | `src/app/db/models/activity_event.py` | 0 |
| 2 | `src/app/db/models/activity_action.py` | 0 |
| 3 | `src/connectors/consumers/activity_writer.py` | 1 |
| 4 | `src/app/api/activity/v1/__init__.py` | 2 |
| 5 | `src/app/api/activity/v1/model.py` | 2 |
| 6 | `src/app/api/activity/v1/router.py` | 2 |
| 7 | `src/app/api/activity/v1/service.py` | 2 |
| 8 | `src/app/api/activity/v1/query.py` | 2 |
| 9 | `src/app/dash_app/pages/timeline/__init__.py` | 3 |
| 10 | `src/app/dash_app/pages/timeline/geometry.py` | 3 |
| 11 | `src/app/dash_app/pages/timeline/layout.py` | 3 |
| 12 | `src/app/dash_app/pages/timeline/callbacks.py` | 3 |
| 13 | `tests/test_timeline_ui_unit.py` | 3 |
| 14 | `tests/test_timeline_ui_integration.py` | 3 |

### Modified files

| # | File | Phase | Change |
|---|------|-------|--------|
| 1 | `src/app/db/models/__init__.py` | 0 | Register ActivityEvent + ActivityAction |
| 2 | `src/connectors/consumers/main.py` | 1 | Add ActivityWriter init + enqueue hook + shutdown |
| 3 | `src/app/main.py` | 2 | Register activity_v1 router |
| 4 | `src/app/analytics/registry.py` | 3 | Add TimelineAnalytic |
| 5 | `src/app/dash_app/pages/analytics.py` | 3 | Render timeline card + controls |
| 6 | `src/app/dash_app/layout.py` | 3 | Add `/app/analytics/timeline` route |
| 7 | `src/app/dash_app/assets/executive-dashboard.css` | 3 | Add `.timeline-*` styles (light + dark) |
| 8 | `src/app/dash_app/pages/search.py` | 4 | Add "View Timeline" button |
| 9 | `src/app/dash_app/pages/graph/utils/data_transform.py` | 4 | Add "View Timeline" to node panel |
| 10 | `src/app/dash_app/pages/collaboration_network/layout.py` | 4 | Add "View Timeline" link |
| 11 | `docker-compose.yml` | 4 | Verify DATABASE_URL passes to consumer (should already be set) |
| 12 | `src/app/api/activity/v1/router.py` | 5 | Add `entity_type` filter to suggest |
| 13 | `src/app/api/activity/v1/service.py` | 5 | Person search delegation |

## Estimated Effort

| Phase | Days | Dependencies |
|-------|------|-------------|
| Phase 0 — Foundation | 1–2 | None |
| Phase 1 — Ingestion | 2–3 | Phase 0 |
| Phase 2 — API | 2–3 | Phase 0 |
| Phase 3 — Dash UI | 3–4 | Phase 2 |
| Phase 4 — Integration | 1–2 | Phase 2 (can overlap w/ Phase 3) |
| Phase 5 — Person search | 1–2 | Phase 3 |
| **Total** | **10–16** | |
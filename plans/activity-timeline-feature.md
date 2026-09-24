# Activity Timeline Feature — Design Discussion

> **Status:** ✅ Design complete — all 12 decisions finalized.
> **Date:** 2026-09-24
> **Implementation plan:** `plans/026-activity-timeline-implementation.md`
> **UI samples:** `plans/timeline-samples/03-swimlane-multi-user.html`

## Table of Contents

1. [Problem Statement](#1-problem-statement)
2. [Decisions Log](#2-decisions-log)
3. [Architecture Overview](#3-architecture-overview)
4. [Storage Schema](#4-storage-schema)
5. [API Design](#5-api-design)
6. [UI/UX Design](#6-ux-design)

## 1. Problem Statement

Users need to visualize the chronological activity of persons and objects across
time — commits, PRs, issues created/commented on, pages authored, etc. The current
Neo4j store uses MERGE semantics, overwriting state rather than preserving
history. No timeline-oriented UI exists today.

## 2. Decisions Log

| # | Decision | Status | Notes |
|---|----------|--------|-------|
| 1 | Storage Backend | ✅ **Decided** | **Postgres** with content-hash dedup (`UNIQUE (source, entity_type, entity_id, event_time, content_hash)`). SHA256 of meaningful payload attributes; skip INSERT if hash matches the latest event for that entity. |
| 2 | Ingestion Strategy | ✅ **Decided** | **Consumer-side hook** in `signal-consumer/main.py`. After Neo4j upsert succeeds, write to `activity_events` table via lightweight `asyncpg` pool. Batch writes every N seconds or M signals for throughput. |
| 3 | Schema Granularity | ✅ **Decided** | Two-table model: (1) `activity_events` — raw deduped signal per entity for "history of object X." (2) `activity_actions` — one normalized row per `(entity → relationship → target)` for "activity involving entity Y." Both indexed on `(entity_type, entity_id, event_time DESC)` for universal queryability across any entity type (Person, Page, Issue, PR, etc.). |
| 4 | UI Visualization | ✅ **Decided** | **Swimlane multi-user view (Option 3)** as primary. Side-by-side lanes, one per person/object, with events positioned by time. Hover popups for details. Compare mode is a core requirement. |
| 5 | API Design — Identity | ✅ **Decided** | Use **WBA canonical key** (`{source}::{entity_type}::{id}`) as the sole query parameter. Single `wba_ids` param (comma-separated) for multi-lane. API parses it into source/entity_type/entity_id internally. |
| 6 | API Design — Filters | ✅ **Decided** | **No `relationship_types` filter in v1.** Keep it simple — return all actions for the entity. The UI can filter client-side if needed. |
| 7 | API Routing | ✅ **Decided** | `/api/v1/activity` — new router + service + query layer. Follows the existing pattern: `router.py` (FastAPI), `service.py` (business logic), `query.py` (SQL queries via asyncpg or SQLAlchemy). |
| 8 | Page Location | ✅ **Decided** | **Analytics sub-page.** Route: `/app/analytics/timeline`. Card on the Analytics gallery next to Collaboration Network — with "Open Visualization" + "Show Options" buttons. Uses a `TimelineAnalytic` dataclass alongside `GraphAnalytic` in the registry. |
| 9 | Pagination | ✅ **Decided** | **Cursor-based.** Cursor = base64(event_time + id) tuple. Per-lane `next_cursor` in response enables independent infinite scrolling per swimlane. |
| 10 | Ingestion — Batching | ✅ **Decided** | **Hybrid:** flush 100 signals OR 5 seconds (whichever first). `asyncio.Queue` + background writer task in consumer. |
| 11 | Ingestion — Failures | ✅ **Decided** | **Non-fatal.** Log warning + continue. Neo4j is source of truth; timeline is best-effort. Never nack a signal due to timeline write failure. |
| 12 | Ingestion — Backfill | ✅ **Decided** | **No backfill.** Timeline starts accumulating from feature ship date. No replay from JSONL dumps. |

### Dedup strategy (from decision #1)

```sql
CREATE TABLE activity_events (
    id BIGSERIAL PRIMARY KEY,
    signal_id UUID NOT NULL,
    source VARCHAR(32) NOT NULL,
    entity_type VARCHAR(32) NOT NULL,
    entity_id VARCHAR(255) NOT NULL,
    event_time TIMESTAMPTZ NOT NULL,
    ingestion_time TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    attributes JSONB NOT NULL,
    relationships JSONB,
    content_hash VARCHAR(64) NOT NULL,  -- SHA256 of meaningful payload

    UNIQUE (source, entity_type, entity_id, event_time, content_hash)
);

CREATE INDEX idx_activity_events_lookup
    ON activity_events (entity_type, entity_id, event_time DESC);
```

Write-time dedup flow:
```
signal arrives → compute content_hash from attributes + relationships
              → SELECT content_hash FROM activity_events
                WHERE (source, entity_type, entity_id) = signal's
                ORDER BY event_time DESC LIMIT 1
              → if hash matches → SKIP (no state change, just re-emission)
              → if hash differs → INSERT (state actually changed)
```

## 3. Architecture Overview

```
[Producers] → RabbitMQ → [Consumer] ──→ Neo4j (state)
                                   └──→ Timeline DB (history)
                                              ↑
                                         [API Server]
                                              ↑
                                         [Dash UI /timeline]
```

### Components

1. **Timeline DB** — stores immutable historical ActivitySignal rows
2. **Ingestion hook** — in the signal-consumer, write a copy to Timeline DB
3. **API router** — `/api/v1/activity` — paginated queries by person/entity
4. **Dash page** — `/app/timeline` — interactive multi-lane vertical timeline

## 4. Storage Schema — Two-Table Model

### Table 1: `activity_events` — Raw deduped signal per entity

One row per *meaningfully distinct* state of an entity. Used for "history of this object."

```sql
CREATE TABLE activity_events (
    id BIGSERIAL PRIMARY KEY,
    signal_id UUID NOT NULL,
    source VARCHAR(32) NOT NULL,
    entity_type VARCHAR(32) NOT NULL,      -- Person, Issue, Page, Commit, etc.
    entity_id VARCHAR(255) NOT NULL,       -- raw ID from the source
    event_time TIMESTAMPTZ NOT NULL,       -- when the event happened in source system
    ingestion_time TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    attributes JSONB NOT NULL,             -- full entity attributes snapshot
    relationships JSONB,                   -- full relationships array
    content_hash VARCHAR(64) NOT NULL,     -- SHA256 of attributes + relationships

    UNIQUE (source, entity_type, entity_id, event_time, content_hash)
);

CREATE INDEX idx_activity_events_lookup
    ON activity_events (entity_type, entity_id, event_time DESC);
```

### Table 2: `activity_actions` — Normalized action rows

One row per relationship in a signal. Used for "activity involving entity Y."

```sql
CREATE TABLE activity_actions (
    id BIGSERIAL PRIMARY KEY,
    signal_id UUID NOT NULL,               -- FK to activity_events.signal_id
    event_time TIMESTAMPTZ NOT NULL,

    -- Who/what performed the action
    source_entity_type VARCHAR(32) NOT NULL,
    source_entity_id VARCHAR(255) NOT NULL,

    -- What relationship
    relationship_type VARCHAR(32) NOT NULL, -- CREATED, REVIEWED, COMMENTED_ON, etc.

    -- Who/what the action targeted
    target_entity_type VARCHAR(32) NOT NULL,
    target_entity_id VARCHAR(255) NOT NULL,

    -- Optional context for display (denormalized for fast reads)
    summary VARCHAR(512),                   -- e.g. PR title, page title
    url VARCHAR(1024),                      -- link to the source system

    -- Time-based index for timeline queries
    FOREIGN KEY (signal_id) REFERENCES activity_events(signal_id)
);

CREATE INDEX idx_activity_actions_source
    ON activity_actions (source_entity_type, source_entity_id, event_time DESC);

CREATE INDEX idx_activity_actions_target
    ON activity_actions (target_entity_type, target_entity_id, event_time DESC);
```

### Write-time decomposition flow

```
Signal arrives → compute content_hash from attributes + relationships
               → check activity_events for dedup
               → if new: INSERT activity_events row
                         → decompose relationships[] into N activity_actions rows
               → if duplicate: SKIP (no state change)
```

### Read-time query flow

| Scenario | Query | Index used |
|----------|-------|------------|
| History of Page X | `activity_events WHERE entity_type='Page' AND entity_id='X' ORDER BY event_time DESC` | `idx_activity_events_lookup` |
| Everything Alice did | `activity_actions WHERE source_entity_type='Person' AND source_entity_id='alice' ORDER BY event_time DESC` | `idx_activity_actions_source` |
| Everything involving Alice | `activity_actions WHERE source_entity_type='Person' AND source_entity_id='alice' OR target_entity_type='Person' AND target_entity_id='alice' ORDER BY event_time DESC` | Both source + target indexes |
| Who interacted with Issue Y | `activity_actions WHERE target_entity_type='Issue' AND target_entity_id='Y' ORDER BY event_time DESC` | `idx_activity_actions_target` |

## 5. API Design

### Single endpoint (v1)

```
GET /api/v1/activity/timeline
```

Query parameters:

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `wba_ids` | string | ✓ | Comma-separated WBA keys for multi-lane. e.g. `github::Person::alice,github::Person::bob` |
| `scope` | enum | | `"activity"` (default) — what they did. `"history"` — their own state changes |
| `from` | datetime | | Time range start (ISO 8601) |
| `to` | datetime | | Time range end (ISO 8601) |
| `cursor` | string | | Pagination cursor per lane (base64-encoded offset) |
| `limit` | int | | Events per lane (default 20, max 100) |

Response shape:

```json
{
  "lanes": [
    {
      "wba_id": "github::Person::alice",
      "entity_type": "Person",
      "label": "Alice Johnson",
      "avatar_url": "...",
      "events": [
        {
          "signal_id": "uuid",
          "event_time": "2026-03-15T14:30:00Z",
          "relationship_type": "CREATED",
          "summary": "feat: add user activity timeline API",
          "entity_type": "PullRequest",
          "source": "github",
          "url": "https://github.com/org/repo/pull/142",
          "details": { "lines_added": 342, "files_changed": 12 }
        }
      ],
      "total_count": 142,
      "next_cursor": "base64..."
    }
  ],
  "meta": {
    "time_range": { "from": "...", "to": "..." },
    "total_lanes": 3
  }
}
```

### Typeahead endpoint

```
GET /api/v1/activity/suggest?q=ali
```

Returns matching WBA IDs for the entity selector UI. Reuses the existing Neo4j or Elasticsearch person/entity search.

## 6. UI/UX Design

See swimlane HTML samples in `plans/timeline-samples/03-swimlane-multi-user.html` for the visual reference.
Implementation details in `plans/026-activity-timeline-implementation.md` — Phase 3.
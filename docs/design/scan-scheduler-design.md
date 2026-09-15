# Scan Scheduler Design

## Overview

Producers (`github-producer`, `jira-producer`, `confluence-producer`) fetch data from
external APIs and publish `ActivitySignal` events that keep the Neo4j graph fresh.
Without automation, scans only run when triggered manually (via `docker compose run`
or `POST /api/v1/commands/`).

The scan scheduler is a lightweight asyncio loop that runs inside the existing FastAPI
app process. At a configurable tick interval, it checks each connector that has a scan
interval configured and fires a `scan` command through the same `create_and_publish_command()`
path a manual trigger uses. No new containers or message queues are introduced.

## Design Decisions

| # | Decision | Choice | Rationale |
|---|---|---|---|
| 1 | Scheduler location | asyncio task inside FastAPI `lifespan()` | Zero new infrastructure; reuses the existing RabbitMQ connection |
| 2 | "Due" anchor | `MAX(created_at)` from `command_status` — any status, `command_type='scan'` | Last *attempted* scan resets the clock; failed scans don't compress the schedule |
| 3 | Schedule config storage | `scan_interval_hours` column on the `connectors` table | The schedule is a connector property; it belongs with the connector row |
| 4 | Tick frequency | 10 min default, `SCHEDULER_TICK_MINUTES` env var | Acceptable jitter; configurable for dev/test |
| 5 | Concurrent scans | Fire unconditionally | The producer owns concurrency via `MAX_CONCURRENT_SCANS` |
| 6 | First-run | Natural — no history fires immediately; manual scans reset the clock | Consistent, simple behavior |
| 7 | API surface | Extend `ConnectorStatus` GET + existing `PATCH /connectors/{type}` | No new routes; GET returns what it owns |
| 8 | Non-schedulable connectors | No special logic | Registry lookup naturally skips them |
| 9 | GET computed fields | Only `scan_interval_hours` returned | The UI cross-references the commands API for history |
| 10 | `enabled` flag | Ignored — the scheduler keys only off `scan_interval_hours` | The `enabled` flag is unused in practice; connectors default to `enabled=False` yet still need scheduled scans |
| 11 | Multi-instance safety | `scheduler_lease` table — distributed leader election via Postgres `UPDATE` | Resilient; automatic failover when the leader dies |

## Scheduling Model

### Tick loop

Every `SCHEDULER_TICK_MINUTES` minutes, the scheduler:

1. **Acquires/renews the lease** — a single-row `scheduler_lease` table is used for
   distributed leader election. An instance becomes the leader by atomically claiming
   the row (via a conditional Postgres `UPDATE`). If another instance holds an active
   lease, the tick is skipped. The lease expires after `2 × tick_interval`, so a dead
   leader is automatically replaced within one tick.

2. **Selects schedulable connectors** — connectors with a non-null
   `scan_interval_hours`. The `enabled` flag is not considered.

3. **Determines which are due** — for each connector, the most recent `scan` command
   (any status) is looked up in `command_status`. A connector is due when it has never
   been scanned, or when `now − last_scan_at >= scan_interval_hours`.

4. **Fires scans** — for each due connector, a `scan` command is published to its
   producer container via the standard command path.

### Due determination

A connector is due for a scan when:

- It has never been scanned (`last_scan_at IS NULL`), **or**
- `now − last_scan_at >= scan_interval_hours`

The "due" anchor is the last *attempted* scan (any status), so a failed scan does not
compress the schedule — the clock only resets when a scan is actually attempted.

### Configuration

- **Per-connector interval**: `scan_interval_hours` on the `connectors` table.
  `NULL` disables scheduled scanning for that connector. A value `>= 1` enables it.
- **Global tick**: `SCHEDULER_TICK_MINUTES` (default 10). Controls how often the
  scheduler checks for due connectors; it is not the scan interval itself.

## Data Model

- **`connectors.scan_interval_hours`** — `int | NULL`. The interval between automated
  scans for a connector. `NULL` = no schedule.
- **`scheduler_lease`** — single-row table for leader election. Tracks which instance
  holds the lease and when it expires.

## API Surface

- **`GET /api/v1/connectors/{type}`** returns `scan_interval_hours` in the response.
- **`PATCH /api/v1/connectors/{type}`** accepts `scan_interval_hours` to set or clear
  the schedule (`null` clears it). Values below 1 are rejected.

## UI

The Connector Settings section exposes an "Auto-Scan Interval" number input for
producer-backed connectors. It is populated from `scan_interval_hours` on load and
submitted with the save payload. Leaving it blank disables scheduled scanning.

## Failure & Concurrency Behavior

- **Leader failover**: if the lease-holding instance dies, its lease expires within
  `2 × tick_interval` and another instance takes over automatically.
- **Concurrent scans**: the scheduler fires scans unconditionally; the producer is
  responsible for limiting concurrent scans via `MAX_CONCURRENT_SCANS`.
- **Tick errors**: errors during a tick are caught and logged; the loop never crashes.
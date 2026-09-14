# Plan 020: Per-Connector Scan Scheduler

## Status

- **Priority**: P1 (enables automated ingestion without manual intervention)
- **Effort**: M
- **Risk**: LOW — entirely additive; no changes to existing command or consumer logic
- **Depends on**: None
- **Category**: feature / scheduler
- **Branch**: `feature/scheduler`
- **Planned at**: 2026-09-14
- **Status**: READY

---

## Why this matters

Producers (`github-producer`, `jira-producer`, `confluence-producer`) currently run only
when triggered manually — either via `docker compose run` or by posting to
`POST /api/v1/commands/`. There is no mechanism to keep the Neo4j graph fresh
automatically.

This plan adds a lightweight asyncio scheduler that runs inside the existing FastAPI
app process. At configurable intervals, it checks each enabled connector and fires a
`scan` command via the existing `create_and_publish_command()` path — exactly as a
manual trigger would. No new containers. No new message queues.

---

## Design Decisions

All decisions reached via the grill-me interview process (2026-09-14):

| # | Decision | Choice | Rationale |
|---|---|---|---|
| 1 | Scheduler location | asyncio task inside FastAPI `lifespan()` | Zero new infrastructure; reuses existing RabbitMQ connection |
| 2 | "Due" anchor | `MAX(created_at)` from `command_status` — any status, `command_type='scan'` | Last *attempted* scan resets the clock; failed scans don't compress the schedule |
| 3 | Schedule config storage | New `scan_interval_hours: int | NULL` column on `connectors` table | Schedule is a connector property; belongs with the connector row |
| 4 | Tick frequency | 10 min default, `SCHEDULER_TICK_MINUTES` env var | Acceptable jitter; configurable for dev/test |
| 5 | Concurrent scans | Fire unconditionally | Producer owns concurrency via `MAX_CONCURRENT_SCANS` |
| 6 | First-run | Natural — no history fires immediately; manual scans reset the clock | Consistent, simple behavior |
| 7 | API surface | Extend `ConnectorStatus` GET + existing `PATCH /connectors/{type}` | No new routes; GET returns what it owns |
| 8 | Non-schedulable connectors | No special logic | Registry lookup naturally skips them |
| 9 | GET computed fields | Only `scan_interval_hours` returned | UI cross-references commands API for history |
| 10 | `enabled` flag | Scheduler skips `enabled=False` connectors | Disabling stops all automated activity |
| 11 | Multi-instance safety | `scheduler_lease` table — distributed leader election via Postgres `UPDATE` | Resilient; automatic failover when leader dies |

---

## Tick Logic

```
Every SCHEDULER_TICK_MINUTES minutes:

1. Try to acquire / renew the scheduler lease:
   UPDATE scheduler_lease
      SET held_by   = :instance_id,
          expires_at = NOW() + (2 × tick_interval)
    WHERE expires_at < NOW()
       OR held_by = :instance_id
   rowcount == 0 → another instance is the leader; skip this tick

2. SELECT connector_type, scan_interval_hours
     FROM connectors
    WHERE enabled = TRUE AND scan_interval_hours IS NOT NULL

3. For each connector:
   a. producer_container = CONNECTOR_REGISTRY[connector_type].get("producer_container")
      → if None: skip silently
   b. last_scan_at = SELECT MAX(created_at) FROM command_status
                      WHERE target = producer_container AND command_type = 'scan'
   c. if last_scan_at IS NULL
         OR (now − last_scan_at) >= timedelta(hours=scan_interval_hours):
      → call create_and_publish_command()
         { command_type: "scan", target: producer_container, parameters: None }
```

---

## Progress Tracker

### Phase 1 — Database Schema
- [x] Add `scan_interval_hours` column to `connectors` table
- [x] Create `scheduler_lease` model
- [x] Write Alembic migration (column + table + seed row)
- [x] Run migration locally; verify schema

**→ Gate: Phase 1 tests must pass before starting Phase 2** ✅ PASSED

### Phase 2 — Scheduler Core
- [x] Add `SCHEDULER_TICK_MINUTES` to `settings.py`
- [x] Create `src/app/scheduler.py`
- [x] Wire scheduler into `main.py` lifespan

**→ Gate: Phase 2 tests must pass before starting Phase 3** ✅ PASSED (app starts cleanly, scheduler log confirmed)

### Phase 3 — API Layer
- [ ] Add `scan_interval_hours` to `ConnectorStatus` response model
- [ ] Add `scan_interval_hours` to `ConnectorConfigUpdateRequest`
- [ ] Persist `scan_interval_hours` in `update_connector_config()` service
- [ ] Return `scan_interval_hours` in connector-to-response mapping

**→ Gate: Phase 3 tests must pass before starting Phase 4**

### Phase 4 — UI
- [ ] Add "Auto-Scan Interval" input to Connector Settings section in `layout.py`
- [ ] Populate input on connector detail load (callback)
- [ ] Include `scan_interval_hours` in save callback payload

**→ Gate: Phase 4 manual verification checklist before starting Phase 5**

### Phase 5 — Integration & Final Verification
- [ ] End-to-end test: set interval, wait for tick, verify command in `GET /commands/`
- [ ] Multi-instance test: verify single leader fires scans
- [ ] Update `plans/README.md` status to DONE ✓

---

## Phase 1 — Database Schema

### [NEW] `src/app/db/models/scheduler_lease.py`

Single-row table for distributed leader election. Seed row inserted by migration.

```python
from datetime import datetime
from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base

class SchedulerLease(Base):
    __tablename__ = "scheduler_lease"

    id: Mapped[int] = mapped_column(primary_key=True)
    held_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
```

### [MODIFY] `src/app/db/models/connector.py`

Add after `updated_at`:

```python
scan_interval_hours: Mapped[int | None] = mapped_column(Integer, nullable=True)
```

### [MODIFY] `src/app/db/models/__init__.py`

Add `from app.db.models.scheduler_lease import SchedulerLease` so Alembic picks it up.

### [NEW] Alembic migration

```python
def upgrade() -> None:
    op.add_column("connectors",
        sa.Column("scan_interval_hours", sa.Integer(), nullable=True))
    op.create_table(
        "scheduler_lease",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("held_by", sa.String(64), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    # Seed single row — expired immediately so any instance can claim it
    op.execute(
        "INSERT INTO scheduler_lease (held_by, expires_at) "
        "VALUES (NULL, '1970-01-01 00:00:00+00')"
    )

def downgrade() -> None:
    op.drop_table("scheduler_lease")
    op.drop_column("connectors", "scan_interval_hours")
```

### Phase 1 Gate — Tests & Verification

**Automated:**
```bash
# Migration round-trip
alembic upgrade head
alembic downgrade -1
alembic upgrade head

pytest tests/ -k "migration" -v
```

**Manual spot-checks:**
```bash
psql $DATABASE_URL -c "\d connectors" | grep scan_interval_hours
psql $DATABASE_URL -c "SELECT * FROM scheduler_lease"
# Expected: 1 row, held_by=NULL, expires_at=1970-01-01
```

---

## Phase 2 — Scheduler Core

### [MODIFY] `src/app/settings.py`

```python
SCHEDULER_TICK_MINUTES: int = Field(default=10, ge=1)
```

### [NEW] `src/app/scheduler.py`

Core module — lease acquisition and due-connector logic.

Key behaviors:
- `instance_id` is a UUID generated once at app startup (passed in from `main.py`)
- Lease `expires_at` = `NOW() + 2 × tick_interval` — if leader dies, lease expires and next
  instance takes over within one tick
- All tick errors are caught and logged; the loop never crashes
- `asyncio.CancelledError` propagates cleanly for graceful shutdown

```python
"""Asyncio scheduler loop.

Leader election via scheduler_lease table:
    UPDATE scheduler_lease
       SET held_by = :me, expires_at = NOW() + 2×tick
     WHERE expires_at < NOW() OR held_by = :me
    rowcount == 1 → leader; rowcount == 0 → skip tick.

Due check per connector:
    last_attempted_at = MAX(created_at) from command_status
                        WHERE target = producer_container AND command_type = 'scan'
    due = last_attempted_at IS NULL
          OR (now - last_attempted_at) >= timedelta(hours=scan_interval_hours)
"""

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.commands.v1.models import CreateCommandRequest
from app.api.commands.v1.service import create_and_publish_command
from app.api.connectors.v1.registry import CONNECTOR_REGISTRY
from app.db.models.command_status import CommandStatus
from app.db.models.connector import Connector
from app.db.models.scheduler_lease import SchedulerLease
from app.db.session import ASYNC_SESSION_LOCAL
from app.settings import settings
from common.logger import logger


async def _try_acquire_lease(
    db: AsyncSession, instance_id: str, tick_minutes: int
) -> bool:
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(minutes=tick_minutes * 2)
    result = await db.execute(
        update(SchedulerLease)
        .where(
            (SchedulerLease.expires_at < now)
            | (SchedulerLease.held_by == instance_id)
        )
        .values(held_by=instance_id, expires_at=expires_at)
    )
    await db.commit()
    return result.rowcount > 0


async def _get_due_connectors(
    db: AsyncSession, now: datetime
) -> list[tuple[str, str]]:
    stmt = select(Connector).where(
        Connector.enabled.is_(True),
        Connector.scan_interval_hours.isnot(None),
    )
    connectors = (await db.execute(stmt)).scalars().all()

    due = []
    for connector in connectors:
        producer = CONNECTOR_REGISTRY.get(
            connector.connector_type, {}
        ).get("producer_container")
        if not producer:
            continue

        last_stmt = select(func.max(CommandStatus.created_at)).where(
            CommandStatus.target == producer,
            CommandStatus.command_type == "scan",
        )
        last_scan_at: Optional[datetime] = (
            await db.execute(last_stmt)
        ).scalar_one_or_none()

        interval = timedelta(hours=connector.scan_interval_hours)
        if last_scan_at is None or (now - last_scan_at) >= interval:
            due.append((connector.connector_type, producer))

    return due


async def scheduler_loop(instance_id: str, tick_minutes: int) -> None:
    logger.info(
        "Scheduler started instance_id=%s tick_minutes=%d",
        instance_id, tick_minutes,
    )
    while True:
        await asyncio.sleep(tick_minutes * 60)
        try:
            async with ASYNC_SESSION_LOCAL() as db:
                if not await _try_acquire_lease(db, instance_id, tick_minutes):
                    logger.debug("Scheduler tick skipped — not the lease holder")
                    continue

                now = datetime.now(timezone.utc)
                due = await _get_due_connectors(db, now)

                if not due:
                    logger.debug("Scheduler tick: no connectors due")
                    continue

                for connector_type, producer in due:
                    logger.info(
                        "Scheduler firing scan connector_type=%s target=%s",
                        connector_type, producer,
                    )
                    try:
                        request = CreateCommandRequest(
                            command_type="scan",
                            target=producer,
                            parameters=None,
                        )
                        await create_and_publish_command(request, db)
                    except Exception as exc:  # pylint: disable=broad-except
                        logger.error(
                            "Scheduler failed to fire scan connector_type=%s: %s",
                            connector_type, exc, exc_info=True,
                        )
        except asyncio.CancelledError:
            logger.info("Scheduler loop cancelled — shutting down")
            return
        except Exception as exc:  # pylint: disable=broad-except
            logger.error("Scheduler tick error: %s", exc, exc_info=True)
```

### [MODIFY] `src/app/main.py`

After the RabbitMQ startup block, add:

```python
from uuid import uuid4
from app.scheduler import scheduler_loop

_scheduler_instance_id = str(uuid4())
scheduler_task = asyncio.ensure_future(
    scheduler_loop(_scheduler_instance_id, settings.SCHEDULER_TICK_MINUTES)
)
logger.info("[Startup] Scheduler started instance_id=%s", _scheduler_instance_id)
```

In the shutdown block (alongside `listener_task.cancel()`):

```python
scheduler_task.cancel()
try:
    await scheduler_task
except asyncio.CancelledError:
    pass
logger.info("[Shutdown] Scheduler stopped")
```

### Phase 2 Gate — Tests & Verification

**Automated:**
```bash
pytest tests/app/test_scheduler.py -v
```

Tests to write in `tests/app/test_scheduler.py`:

| Test | Description |
|---|---|
| `test_acquire_lease_expired` | Expired lease → returns `True` |
| `test_acquire_lease_renew_own` | Re-acquire own lease → returns `True` |
| `test_acquire_lease_held_by_other` | Active foreign lease → returns `False` |
| `test_due_no_history` | No scan history → connector is due |
| `test_due_interval_elapsed` | Last scan > interval ago → due |
| `test_due_interval_not_elapsed` | Last scan < interval ago → not due |
| `test_due_skips_disabled` | `enabled=False` → not due |
| `test_due_skips_no_producer` | No `producer_container` → not due |
| `test_due_skips_null_interval` | `scan_interval_hours=NULL` → not due |

**Manual:**
```bash
# Set SCHEDULER_TICK_MINUTES=1 in .env, restart app
docker compose logs -f app | grep -i scheduler
# Expected: "Scheduler started" at boot, "Scheduler tick" every ~60 seconds
```

---

## Phase 3 — API Layer

### [MODIFY] `src/app/api/connectors/v1/model.py`

```python
from pydantic import Field

class ConnectorConfigUpdateRequest(BaseModel):
    config: Optional[Dict[str, Any]] = None
    scan_interval_hours: Optional[int] = Field(None, ge=1)  # ADD

class ConnectorStatus(BaseModel):
    # ... existing fields ...
    scan_interval_hours: Optional[int] = None               # ADD
```

> `ge=1` prevents `scan_interval_hours=0` from being stored, which would cause the
> scheduler to fire on every tick.

### [MODIFY] `src/app/api/connectors/v1/service.py`

In `update_connector_config()`, handle both setting and clearing the interval:

```python
# After existing config handling:
if "scan_interval_hours" in payload.model_fields_set:
    connector.scan_interval_hours = payload.scan_interval_hours
    # None = disable schedule; ge=1 validation already blocks 0
```

In the connector → `ConnectorStatus` mapping:

```python
scan_interval_hours=connector.scan_interval_hours,
```

### Phase 3 Gate — Tests & Verification

**Automated:**
```bash
pytest tests/app/api/test_connectors.py -v -k "schedule or interval"
```

Tests to add:

| Test | Description |
|---|---|
| `test_patch_sets_interval` | PATCH `{scan_interval_hours: 24}` → GET returns 24 |
| `test_patch_clears_interval` | PATCH `{scan_interval_hours: null}` → GET returns null |
| `test_patch_rejects_zero` | PATCH `{scan_interval_hours: 0}` → HTTP 422 |
| `test_patch_rejects_negative` | PATCH `{scan_interval_hours: -1}` → HTTP 422 |
| `test_get_returns_interval` | GET connector → `scan_interval_hours` present in response |

**Manual:**
```bash
curl -sX PATCH http://localhost:8000/api/v1/connectors/github \
  -H "Content-Type: application/json" \
  -d '{"scan_interval_hours": 24}' | jq .scan_interval_hours
# Expected: 24

curl -s http://localhost:8000/api/v1/connectors/github | jq .scan_interval_hours
# Expected: 24
```

---

## Phase 4 — UI

### [MODIFY] `src/app/dash_app/pages/connectors/layout.py`

In `get_detail_layout()`, inside the **"Connector Settings"** section (section 5),
add a "Scan Schedule" sub-section **before** the existing "Save Configuration" button.
Only rendered when `producer_container` is set:

```python
if producer_container:
    schedule_ui = html.Div(
        [
            html.Div(
                "Scan Schedule",
                style={
                    "fontFamily": FONT_SANS,
                    "fontSize": FONT_SIZE_SMALL,
                    "fontWeight": FONT_WEIGHT_SEMIBOLD,
                    "color": COLOR_GRAY_DARK,
                    "marginBottom": SPACING_XSMALL,
                    "marginTop": SPACING_SMALL,
                },
            ),
            html.P(
                "Run a scan automatically at a fixed interval. "
                "Leave blank to disable scheduled scanning.",
                style={
                    "fontFamily": FONT_SANS,
                    "fontSize": FONT_SIZE_SMALL,
                    "color": COLOR_GRAY_MEDIUM,
                    "marginBottom": SPACING_XSMALL,
                },
            ),
            dbc.Row(
                [
                    dbc.Col(
                        dbc.Input(
                            id={
                                "type": "connector-scan-interval-input",
                                "connector_type": connector_type,
                            },
                            type="number",
                            min=1,
                            step=1,
                            placeholder="e.g. 24",
                        ),
                        width=4,
                    ),
                    dbc.Col(
                        html.Span(
                            "hours between scans",
                            style={
                                "lineHeight": "38px",
                                "fontFamily": FONT_SANS,
                                "fontSize": FONT_SIZE_SMALL,
                                "color": COLOR_GRAY_MEDIUM,
                            },
                        ),
                        width="auto",
                    ),
                ],
                align="center",
                className="g-2",
            ),
        ],
        style={"marginBottom": SPACING_SMALL},
    )
else:
    schedule_ui = html.Div()
```

### [MODIFY] `src/app/dash_app/pages/connectors/callbacks.py`

1. **Populate on load** — in the connector detail load callback:
   - Read `scan_interval_hours` from the `ConnectorStatus` GET response
   - Return it as the `value` of `connector-scan-interval-input`

2. **Save** — in the existing save callback:
   - Read `connector-scan-interval-input` value
   - Cast to `int` if non-empty, else `None`
   - Include in PATCH payload as `scan_interval_hours`

### Phase 4 Gate — Manual Verification Checklist

Complete all items before starting Phase 5:

- [ ] GitHub connector detail → "Scan Schedule" section visible with number input
- [ ] Enter `24` → click "Save Configuration" → reload → input shows `24`
- [ ] Clear input → click "Save" → reload → input is blank
- [ ] Jira connector detail → "Scan Schedule" section visible
- [ ] Confluence connector detail → "Scan Schedule" section visible
- [ ] Slack connector detail → "Scan Schedule" section is **NOT visible**
- [ ] Teams connector detail → "Scan Schedule" section is **NOT visible**

---

## Phase 5 — Integration & Final Verification

### End-to-End Test

```bash
# 1. Set tick to 1 minute for the test
echo "SCHEDULER_TICK_MINUTES=1" >> .env

# 2. Start the stack
docker compose up -d app

# 3. Set a 1-hour interval on GitHub (fires immediately — no prior history)
curl -sX PATCH http://localhost:8000/api/v1/connectors/github \
  -H "Content-Type: application/json" \
  -d '{"scan_interval_hours": 1}'

# 4. Wait ~70 seconds, verify a new scan command appeared
sleep 70
curl -s "http://localhost:8000/api/v1/commands/?target=github-producer&limit=5" \
  | jq '[.commands[] | {status, created_at}]'
# Expected: at least one command with created_at within the last 2 minutes
```

### Multi-Instance Leader Election Test

```bash
# Scale to 2 app replicas
docker compose up --scale app=2 -d

# Watch which instance logs "Scheduler firing scan"
docker compose logs -f | grep "Scheduler firing"
# Expected: only ONE instance_id appears consistently

# Verify lease table shows a single holder
psql $DATABASE_URL -c "SELECT held_by, expires_at FROM scheduler_lease"
# Expected: 1 row, expires_at within the last 20 minutes
```

### Final Completion Checklist

- [ ] All Phase 1–3 automated tests pass: `pytest tests/ -v`
- [ ] Phase 4 manual verification checklist complete
- [ ] End-to-end test: scan fires within tick window after interval set
- [ ] Multi-instance test: single `held_by` observed in lease table
- [ ] `SCHEDULER_TICK_MINUTES=1` removed from `.env` (reset to default)
- [ ] `plans/README.md` → Plan 020 status updated to **DONE ✓**
- [ ] Branch `feature/scheduler` merged to main

---

## Files Touched Summary

| File | Change |
|---|---|
| `src/app/db/models/connector.py` | Add `scan_interval_hours` column |
| `src/app/db/models/scheduler_lease.py` | **NEW** — lease table model |
| `src/app/db/models/__init__.py` | Import `SchedulerLease` |
| `src/app/alembic/versions/<ts>_scheduler.py` | **NEW** — migration |
| `src/app/settings.py` | Add `SCHEDULER_TICK_MINUTES` |
| `src/app/scheduler.py` | **NEW** — scheduler loop + lease logic |
| `src/app/main.py` | Wire scheduler into lifespan |
| `src/app/api/connectors/v1/model.py` | Add `scan_interval_hours` to request/response |
| `src/app/api/connectors/v1/service.py` | Persist and return `scan_interval_hours` |
| `src/app/dash_app/pages/connectors/layout.py` | Add interval input to Connector Settings |
| `src/app/dash_app/pages/connectors/callbacks.py` | Populate and save interval input |
| `tests/app/test_scheduler.py` | **NEW** — unit tests for scheduler core |
| `tests/app/api/test_connectors.py` | Extend with schedule API tests |
| `plans/README.md` | Add Plan 020 to execution table |

"""Asyncio scheduler loop for automated connector scans.

Runs as a background task inside the FastAPI app process, started in the
``lifespan()`` context manager in ``main.py``.

Leader Election
---------------
Multiple app instances may run simultaneously (e.g. horizontal scaling or
rolling restarts).  To prevent duplicate scan commands, only one instance
acts as the scheduler leader at a time.  Leadership is claimed via an atomic
``UPDATE`` on the ``scheduler_lease`` table (single row, seeded by migration):

    UPDATE scheduler_lease
       SET held_by   = :instance_id,
           expires_at = NOW() + 2 × tick_interval
     WHERE expires_at < NOW()
        OR held_by = :instance_id

``rowcount == 1``  →  this instance is the leader; proceed with the tick.
``rowcount == 0``  →  another instance holds the lease; skip this tick.

The lease TTL is ``2 × tick_interval``.  If the leader process dies, the lease
expires within one tick period and any surviving instance picks it up.

Due-Check Logic
---------------
For each enabled connector with ``scan_interval_hours IS NOT NULL``:

1. Resolve ``producer_container`` from ``CONNECTOR_REGISTRY``.
   Connectors with no producer (e.g. Slack) are silently skipped.

2. Query ``MAX(created_at)`` from ``command_status`` where
   ``target = producer_container AND command_type = 'scan'`` (any status).
   This is the "last attempted" anchor — a failed scan resets the clock just
   like a successful one, preventing the scheduler from piling up retries.

3. Fire if ``last_scan_at IS NULL`` (never scanned) or
   ``now − last_scan_at >= scan_interval_hours``.

Firing calls ``create_and_publish_command()`` directly (in-process), which
inserts a ``CommandStatus`` row and publishes a ``CommandEnvelope`` to the
``command_n_control`` RabbitMQ exchange — identical to a manual scan trigger.

Error Handling
--------------
All per-connector errors are caught and logged; they never abort the tick.
All tick-level errors are caught so the loop itself never crashes.
``asyncio.CancelledError`` propagates cleanly for graceful shutdown.
"""

from __future__ import annotations

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
from common.logger import logger


async def _try_acquire_lease(
    db: AsyncSession,
    instance_id: str,
    tick_minutes: int,
) -> bool:
    """Atomically claim or renew the scheduler lease.

    Returns ``True`` if this instance is now the leader, ``False`` otherwise.

    The lease expires at ``NOW() + 2 × tick_minutes`` so that if the leader
    dies, the next instance picks up leadership within one full tick period.
    """
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
    db: AsyncSession,
    now: datetime,
) -> list[tuple[str, str]]:
    """Return ``(connector_type, producer_container)`` pairs due for a scan.

    A connector is due when:
    - It has never been scanned (``last_scan_at IS NULL``), OR
    - ``now − last_scan_at >= scan_interval_hours``

    Connectors with no ``producer_container`` in the registry are silently
    skipped — no error, no log noise.
    """
    stmt = select(Connector).where(
        Connector.scan_interval_hours.isnot(None),
    )
    connectors = (await db.execute(stmt)).scalars().all()

    due: list[tuple[str, str]] = []
    for connector in connectors:
        producer = CONNECTOR_REGISTRY.get(
            connector.connector_type, {}
        ).get("producer_container")
        if not producer:
            continue  # no producer for this connector type — skip silently

        # Find the most recent attempted scan (any status).
        last_stmt = select(func.max(CommandStatus.created_at)).where(
            CommandStatus.target == producer,
            CommandStatus.command_type == "scan",
        )
        last_scan_at: Optional[datetime] = (
            await db.execute(last_stmt)
        ).scalar_one_or_none()

        interval = timedelta(hours=connector.scan_interval_hours)  # type: ignore[arg-type]
        if last_scan_at is None or (now - last_scan_at) >= interval:
            due.append((connector.connector_type, producer))  # type: ignore[arg-type]

    return due


async def scheduler_loop(instance_id: str, tick_minutes: int) -> None:
    """Infinite scheduler loop — runs as a background asyncio task.

    Args:
        instance_id: UUID string uniquely identifying this app instance.
            Used as the lease ``held_by`` value.
        tick_minutes: How often (in minutes) to wake up and check for due
            connectors.  Controlled by ``SCHEDULER_TICK_MINUTES`` env var.
    """
    logger.info(f"Scheduler started instance_id={instance_id} tick_minutes={tick_minutes}")

    while True:
        await asyncio.sleep(tick_minutes * 60)

        try:
            async with ASYNC_SESSION_LOCAL() as db:
                is_leader = await _try_acquire_lease(db, instance_id, tick_minutes)
                if not is_leader:
                    logger.debug(f"Scheduler tick skipped — not the lease holder instance_id={instance_id}")
                    continue

                now = datetime.now(timezone.utc)
                due = await _get_due_connectors(db, now)

                if not due:
                    logger.debug(f"Scheduler tick: no connectors due instance_id={instance_id}")
                    continue

                logger.info(f"Scheduler tick: {len(due)} connector(s) due instance_id={instance_id}")

                for connector_type, producer in due:
                    logger.info(f"Scheduler firing scan connector_type={connector_type} target={producer}")
                    try:
                        request = CreateCommandRequest(
                            command_type="scan",
                            target=producer,
                            parameters=None,
                        )
                        await create_and_publish_command(request, db)
                    except Exception as exc:  # pylint: disable=broad-except
                        logger.error(
                            f"Scheduler failed to fire scan connector_type={connector_type} target={producer}: {exc}",
                            exc_info=True,
                        )

        except asyncio.CancelledError:
            logger.info(f"Scheduler loop cancelled — shutting down instance_id={instance_id}")
            return
        except Exception as exc:  # pylint: disable=broad-except
            # Never crash the loop — log and sleep until next tick.
            logger.error(f"Scheduler tick error instance_id={instance_id}: {exc}", exc_info=True)

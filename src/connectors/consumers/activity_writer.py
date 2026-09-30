"""ActivityWriter — async background writer for the activity timeline.

Consumes :class:`ActivitySignal` objects from an ``asyncio.Queue``, batches
them (up to 100 items or 5 s of inactivity), and writes them atomically to
Postgres using ``asyncpg`` directly (no SQLAlchemy — the consumer does not
carry the app layer's dependencies).

Deduplication is done at the database level via
``ON CONFLICT (source, entity_type, entity_id, event_time, content_hash) DO NOTHING``
which is race-safe across horizontally-scaled consumer instances.

Usage::

    writer = ActivityWriter(os.environ["DATABASE_URL"])
    await writer.start()          # starts background loop task
    ...
    await writer.enqueue(signal)  # called for every processed signal
    ...
    await writer.close()          # drains queue, closes pool
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from typing import Optional

import asyncpg

from common.activity_signal.models import ActivitySignal
from common.logger import logger

# Tuning constants
_BATCH_SIZE = 100
_BATCH_TIMEOUT_SECS = 5.0


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _normalize_database_url(url: str) -> str:
    """Strip SQLAlchemy dialect prefixes from DATABASE_URL.

    ``asyncpg`` accepts ``postgresql://`` or ``postgres://`` but not
    ``postgresql+asyncpg://`` (the SQLAlchemy convention used in this project).
    """
    for prefix in ("postgresql+asyncpg://", "postgres+asyncpg://"):
        if url.startswith(prefix):
            return "postgresql://" + url[len(prefix):]
    return url


def _compute_content_hash(signal: ActivitySignal) -> str:
    """SHA-256 of the serialised attributes + relationships payload.

    Stable: ``sort_keys=True`` guarantees dict ordering doesn't affect the
    hash.  Same content → same hash regardless of insertion order.
    """
    payload = {
        "attributes": signal.attributes.model_dump(),
        "relationships": [r.model_dump() for r in signal.relationships],
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=str).encode()
    ).hexdigest()


def _compute_display_name(signal: ActivitySignal) -> str:
    """Mirrors GraphNode.display_name() from node_base.py.

    Tries ``name``, ``title``, ``summary``, ``key`` in order and falls back
    to the raw entity ``id``.
    """
    attrs = signal.attributes.model_dump()
    for field in ("name", "title", "summary", "key"):
        value = attrs.get(field)
        if value and isinstance(value, str):
            return value
    return signal.id


def _compute_avatar_url(signal: ActivitySignal) -> Optional[str]:
    """Return ``avatar_url`` for Person signals; ``None`` for everything else."""
    if signal.entity_type == "Person":
        return signal.attributes.model_dump().get("avatar_url")
    return None


def _decompose_relationships(signal: ActivitySignal) -> list[dict]:
    """Flatten ``signal.relationships`` into ``activity_actions`` row dicts.

    ``summary`` — first non-empty of title / summary / key from attributes,
    or None if none present.

    ``url`` — taken from ``rel.target.url`` (the link to the target entity in
    the source system, e.g. a GitHub PR URL or Jira issue URL).
    """
    attrs = signal.attributes.model_dump()
    summary: Optional[str] = (
        attrs.get("title")
        or attrs.get("summary")
        or attrs.get("key")
        or None
    )
    actions = []
    for rel in signal.relationships:
        actions.append(
            {
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
            }
        )
    return actions


# ---------------------------------------------------------------------------
# ActivityWriter
# ---------------------------------------------------------------------------


class ActivityWriter:
    """Async, non-blocking writer that persists ActivitySignals to Postgres.

    The writer runs a private background task (``_writer_loop``) that collects
    signals from an internal ``asyncio.Queue``, batches them, and issues
    ``INSERT … ON CONFLICT DO NOTHING`` statements.  All failures are caught
    and logged at WARNING level — a Postgres outage never propagates back to
    the consumer loop.

    Args:
        database_url: Postgres connection URL.  SQLAlchemy ``+asyncpg`` dialect
            prefixes are stripped automatically.
    """

    def __init__(self, database_url: str) -> None:
        self._dsn = _normalize_database_url(database_url)
        self._queue: asyncio.Queue[ActivitySignal] = asyncio.Queue()
        self._pool: Optional[asyncpg.Pool] = None
        self._task: Optional[asyncio.Task] = None

    async def start(self) -> None:
        """Create the connection pool and start the background writer loop."""
        self._pool = await asyncpg.create_pool(self._dsn, min_size=1, max_size=3)
        self._task = asyncio.ensure_future(self._writer_loop())
        logger.info("ActivityWriter started — background loop running")

    async def enqueue(self, signal: ActivitySignal) -> None:
        """Push *signal* onto the internal queue (non-blocking)."""
        await self._queue.put(signal)

    async def close(self) -> None:
        """Drain the remaining queue, then close the pool and cancel the loop."""
        logger.info("ActivityWriter closing — draining remaining queue items")
        # Signal the loop to stop after draining.
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        # Flush anything left in the queue synchronously.
        remaining: list[ActivitySignal] = []
        while not self._queue.empty():
            try:
                remaining.append(self._queue.get_nowait())
            except asyncio.QueueEmpty:
                break
        if remaining and self._pool is not None:
            await self._write_batch(remaining)
        if self._pool is not None:
            await self._pool.close()
        logger.info("ActivityWriter closed")

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _writer_loop(self) -> None:
        """Collect signals into batches and write them to Postgres.

        A batch is flushed when either:
        - it reaches ``_BATCH_SIZE`` items, or
        - ``_BATCH_TIMEOUT_SECS`` of inactivity elapses with at least one item.
        """
        batch: list[ActivitySignal] = []
        while True:
            try:
                timeout = _BATCH_TIMEOUT_SECS if batch else None
                signal = await asyncio.wait_for(self._queue.get(), timeout=timeout)
                batch.append(signal)
                if len(batch) >= _BATCH_SIZE:
                    await self._write_batch(batch)
                    batch = []
            except asyncio.TimeoutError:
                # Inactivity timeout — flush whatever we have.
                if batch:
                    await self._write_batch(batch)
                    batch = []
            except asyncio.CancelledError:
                # Graceful shutdown — flush and exit.
                if batch:
                    await self._write_batch(batch)
                raise

    async def _write_batch(self, batch: list[ActivitySignal]) -> None:
        """Write a batch of signals to Postgres.

        For each signal:
        1. INSERT into ``activity_events`` with ON CONFLICT DO NOTHING.
        2. If inserted (not a duplicate), decompose relationships into
           ``activity_actions`` rows.
        """
        if self._pool is None:
            logger.warning("ActivityWriter: pool is None — skipping batch")
            return

        inserted_count = 0
        duplicate_count = 0
        action_count = 0
        for signal in batch:
            try:
                result = await self._write_signal(signal)
                if result is None:
                    duplicate_count += 1
                else:
                    inserted_count += 1
                    action_count += result
            except Exception as exc:  # pylint: disable=broad-except
                logger.warning(
                    "ActivityWriter: failed to write signal_id=%s entity_type=%s id=%s — %s",
                    signal.signal_id,
                    signal.entity_type,
                    signal.id,
                    exc,
                )

        logger.info(
            "Wrote to Postgres batch_size=%d inserted=%d duplicates=%d actions=%d",
            len(batch),
            inserted_count,
            duplicate_count,
            action_count,
        )

    async def _write_signal(self, signal: ActivitySignal) -> Optional[int]:
        """Persist one signal (event row + action rows) within a single connection.

        Returns the number of ``activity_actions`` rows written, or ``None`` if
        the event was a duplicate (skipped).
        """
        content_hash = _compute_content_hash(signal)
        display_name = _compute_display_name(signal)
        avatar_url = _compute_avatar_url(signal)

        assert self._pool is not None
        async with self._pool.acquire() as conn:
            # --- activity_events INSERT (dedup via ON CONFLICT DO NOTHING) ---
            status = await conn.execute(
                """
                INSERT INTO activity_events
                    (signal_id, source, entity_type, entity_id, event_time,
                     display_name, avatar_url, attributes, relationships, content_hash)
                VALUES
                    ($1, $2, $3, $4, $5, $6, $7, $8::jsonb, $9::jsonb, $10)
                ON CONFLICT (source, entity_type, entity_id, event_time, content_hash)
                DO NOTHING
                """,
                signal.signal_id,
                signal.source,
                signal.entity_type,
                signal.id,
                signal.event_time,
                display_name,
                avatar_url,
                json.dumps(signal.attributes.model_dump(), default=str),
                json.dumps([r.model_dump() for r in signal.relationships], default=str),
                content_hash,
            )

            # asyncpg returns the command tag as a string, e.g. "INSERT 0 1"
            inserted = status == "INSERT 0 1"

            if not inserted:
                logger.debug(
                    "ActivityWriter: duplicate skipped signal_id=%s entity_type=%s id=%s",
                    signal.signal_id,
                    signal.entity_type,
                    signal.id,
                )
                return None

            logger.debug(
                "ActivityWriter: inserted event signal_id=%s entity_type=%s id=%s",
                signal.signal_id,
                signal.entity_type,
                signal.id,
            )

            # --- activity_actions INSERT (one row per relationship) ----------
            actions = _decompose_relationships(signal)
            if not actions:
                return 0

            await conn.executemany(
                """
                INSERT INTO activity_actions
                    (signal_id, source, event_time, actor_entity_type, actor_entity_id,
                     relationship_type, target_entity_type, target_entity_id, summary, url)
                VALUES
                    ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                """,
                [
                    (
                        a["signal_id"],
                        a["source"],
                        a["event_time"],
                        a["actor_entity_type"],
                        a["actor_entity_id"],
                        a["relationship_type"],
                        a["target_entity_type"],
                        a["target_entity_id"],
                        a["summary"],
                        a["url"],
                    )
                    for a in actions
                ],
            )
            logger.debug(
                "ActivityWriter: inserted %d action(s) for signal_id=%s entity_type=%s id=%s",
                len(actions),
                signal.signal_id,
                signal.entity_type,
                signal.id,
            )
            return len(actions)

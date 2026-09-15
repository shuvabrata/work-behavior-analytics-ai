"""SQLAlchemy model for the scheduler_lease table.

Single-row table used for distributed scheduler leader election across multiple
app instances.  Each tick, an instance attempts an atomic UPDATE:

    UPDATE scheduler_lease
       SET held_by   = :instance_id,
           expires_at = NOW() + 2 × tick_interval
     WHERE expires_at < NOW()
        OR held_by = :instance_id

``rowcount == 1`` → this instance is the leader and proceeds with the tick.
``rowcount == 0`` → another instance holds the lease; skip this tick.

The single row is seeded by the Alembic migration with ``expires_at`` set to
the epoch so that the first instance to start always wins the initial lease.

If the leader process dies, the lease expires after ``2 × tick_interval`` and
any surviving instance picks it up on the next wakeup.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class SchedulerLease(Base):
    """Distributed scheduler lease — exactly one row, always.

    Attributes:
        id: Primary key (always 1).
        held_by: Instance ID (UUID string) of the current lease holder.
            ``None`` when no instance has claimed the lease yet.
        expires_at: UTC timestamp after which the lease is considered expired
            and any instance may claim it.
    """

    __tablename__ = "scheduler_lease"

    id: Mapped[int] = mapped_column(primary_key=True)
    held_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

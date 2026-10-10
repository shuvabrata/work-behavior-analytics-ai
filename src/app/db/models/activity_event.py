from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base


class ActivityEvent(Base):
    """Historical snapshot of an ActivitySignal written to Postgres.

    Each row represents one unique signal event (source + entity + time + content).
    The ``content_hash`` + composite unique constraint provides dedup at insert time
    via ``ON CONFLICT DO NOTHING``.
    """

    __tablename__ = "activity_events"
    __table_args__ = (
        # Required so activity_actions.signal_id can FK-reference this column.
        UniqueConstraint("signal_id", name="uq_activity_events_signal_id"),
        # Dedup guard — same entity + same content at the same instant is idempotent.
        UniqueConstraint(
            "source",
            "entity_type",
            "entity_id",
            "event_time",
            "content_hash",
            name="uq_activity_events_dedup",
        ),
        # Lookup index — DESC ordering is injected manually in the Alembic migration
        # via op.execute() because SQLAlchemy autogenerate does not emit DESC indexes.
        Index("idx_activity_events_lookup", "source", "entity_type", "entity_id", "event_time"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    signal_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), nullable=False, unique=True
    )
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(32), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(255), nullable=False)
    event_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ingestion_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),  # pylint: disable=not-callable
    )
    # Computed at write time — mirrors GraphNode.display_name(); see activity_writer.py.
    display_name: Mapped[str | None] = mapped_column(String(512), nullable=True)
    # Person avatars only; NULL for all non-Person entity types.
    avatar_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    attributes: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    relationships: Mapped[list[Any] | None] = mapped_column(JSONB, nullable=True)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)

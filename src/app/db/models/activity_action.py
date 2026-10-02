from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ActivityAction(Base):
    """Flattened relationship row derived from an ActivityEvent.

    Each row represents a single relationship edge observed within an ActivitySignal
    (e.g., Person CREATED Issue, Person REVIEWED PullRequest).  Multiple actions can
    belong to the same event (signal_id).

    The FK to ``activity_events.signal_id`` uses ON DELETE CASCADE so that removing
    a parent event atomically removes all its child actions.
    """

    __tablename__ = "activity_actions"
    __table_args__ = (
        # Actor-centric lookup — timeline queries for a given actor.
        # DESC ordering is injected manually in the Alembic migration via op.execute().
        Index(
            "idx_activity_actions_actor",
            "source",
            "actor_entity_type",
            "actor_entity_id",
            "event_time",
        ),
        # Target-centric lookup — timeline queries for a given target object.
        Index(
            "idx_activity_actions_target",
            "source",
            "target_entity_type",
            "target_entity_id",
            "event_time",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    # FK to activity_events.signal_id (not the PK) — ON DELETE CASCADE.
    signal_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("activity_events.signal_id", ondelete="CASCADE"),
        nullable=False,
    )
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    event_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    actor_entity_type: Mapped[str] = mapped_column(String(32), nullable=False)
    actor_entity_id: Mapped[str] = mapped_column(String(255), nullable=False)
    relationship_type: Mapped[str] = mapped_column(String(32), nullable=False)
    target_entity_type: Mapped[str] = mapped_column(String(32), nullable=False)
    target_entity_id: Mapped[str] = mapped_column(String(255), nullable=False)
    summary: Mapped[str | None] = mapped_column(String(512), nullable=True)
    url: Mapped[str | None] = mapped_column(String(1024), nullable=True)

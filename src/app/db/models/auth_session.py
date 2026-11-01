"""SQLAlchemy model for the ``auth_session`` table.

The server-side record that makes the BFF possible: the browser holds an opaque
cookie id, and the API derives its bearer token from the row this table stores.
``session_id_hash`` is the SHA-256 hex of that cookie id — the raw id is never
stored, so a database leak does not hand out usable session cookies.
``refresh_token_encrypted`` is Fernet ciphertext (see ``app.common.encryption``);
if the encryption key rotates, all existing sessions become unrefreshable.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base


class AuthSession(Base):
    """A server-side login session backing the BFF's cookie credential."""

    __tablename__ = "auth_session"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id_hash: Mapped[str] = mapped_column(
        String(64), nullable=False, unique=True, index=True
    )
    subject: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    username: Mapped[str] = mapped_column(String(255), nullable=False)
    roles: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    refresh_token_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False  # pylint: disable=not-callable
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    def __repr__(self) -> str:
        return (
            f"AuthSession(id={self.id}, subject={self.subject!r}, "
            f"username={self.username!r})"
        )

"""SQLAlchemy model for the ``catalog_metadata`` table.

Stores per-query metadata for the Graph page's Query Catalog. Currently the
only metadata is the favourite flag, which lets users surface frequently-run
catalog queries. Rows are created lazily (upsert on toggle) — a row only
exists for queries the user has interacted with.

``catalog_id`` is the stable id of a catalog query (``<namespace.directory>/<slug>``)
as defined by ``app.query_catalog.loader``. ``subject`` is the Keycloak ``sub``
of the user who owns the row. A row is unique per ``(catalog_id, subject)``:
``catalog_id`` is no longer globally unique, so each user keeps their own
favourite state for a query.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base


class CatalogMetadata(Base):
    """Per-query metadata for the query catalog (currently the favourite flag)."""

    __tablename__ = "catalog_metadata"
    __table_args__ = (
        UniqueConstraint(
            "catalog_id", "subject", name="uq_catalog_metadata_catalog_subject"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    catalog_id: Mapped[str] = mapped_column(String(255), nullable=False)
    subject: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    is_favourite: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False  # pylint: disable=not-callable
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),  # pylint: disable=not-callable
        onupdate=func.now(),  # pylint: disable=not-callable
        nullable=False,
    )

    def __init__(  # pylint: disable=useless-parent-delegation
        self,
        *,
        catalog_id: str,
        subject: str,
        is_favourite: bool = False,
        **kwargs: object,
    ) -> None:
        """Construct a row, defaulting ``is_favourite`` to ``False``.

        SQLAlchemy's ``default`` only applies at flush time, so an explicit
        ``__init__`` keeps the default visible at construction time too.
        """
        super().__init__(
            catalog_id=catalog_id,
            subject=subject,
            is_favourite=is_favourite,
            **kwargs,
        )

    def __repr__(self) -> str:
        return (
            f"CatalogMetadata(id={self.id}, catalog_id={self.catalog_id!r}, "
            f"subject={self.subject!r}, is_favourite={self.is_favourite})"
        )
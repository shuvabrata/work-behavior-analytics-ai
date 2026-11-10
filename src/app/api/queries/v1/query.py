"""Query layer for YAML-backed catalog metadata."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import func

from app.db.models.catalog_metadata import CatalogMetadata
from app.query_catalog import (
    CatalogNamespace,
    CatalogQuery,
    load_catalog,
    load_namespaces,
)


def list_catalog_queries(*, include_user_overrides: bool = True) -> list[CatalogQuery]:
    """Return all normalized catalog queries."""
    return load_catalog(include_user_overrides=include_user_overrides)


def list_catalog_namespaces() -> list[CatalogNamespace]:
    """Return catalog namespaces in display order."""
    return load_namespaces()


async def list_catalog_metadata(
    db: AsyncSession, *, subject: str, is_favourite: bool | None = None
) -> list[CatalogMetadata]:
    """Return the caller's catalog metadata rows, optionally filtered."""
    stmt = (
        select(CatalogMetadata)
        .where(CatalogMetadata.subject == subject)
        .order_by(CatalogMetadata.catalog_id)
    )
    if is_favourite is not None:
        stmt = stmt.where(CatalogMetadata.is_favourite.is_(is_favourite))
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def get_catalog_metadata(
    db: AsyncSession, *, subject: str, catalog_id: str
) -> CatalogMetadata | None:
    """Fetch the caller's catalog metadata row for ``catalog_id``.

    Returns ``None`` when the row is absent *or* owned by another subject —
    the two cases are deliberately indistinguishable.
    """
    stmt = select(CatalogMetadata).where(
        CatalogMetadata.catalog_id == catalog_id,
        CatalogMetadata.subject == subject,
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def upsert_catalog_metadata(
    db: AsyncSession, *, subject: str, catalog_id: str, is_favourite: bool
) -> CatalogMetadata:
    """Upsert the caller's catalog metadata row (idempotent).

    Uses ``INSERT ... ON CONFLICT (catalog_id, subject) DO UPDATE`` so repeated
    writes never create duplicate rows for one subject. The caller manages the
    transaction boundary (commit/rollback); the returned row is refreshed so
    the DB-generated ``updated_at`` is populated.
    """
    stmt = (
        pg_insert(CatalogMetadata)
        .values(
            subject=subject,
            catalog_id=catalog_id,
            is_favourite=is_favourite,
        )
        .on_conflict_do_update(
            index_elements=[
                CatalogMetadata.catalog_id,
                CatalogMetadata.subject,
            ],
            set_={
                "is_favourite": is_favourite,
                "updated_at": func.now(),  # pylint: disable=not-callable
            },
        )
        .returning(CatalogMetadata)
    )
    result = await db.execute(stmt)
    row = result.scalar_one()
    await db.refresh(row)
    return row

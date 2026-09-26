"""FastAPI router for YAML-backed query catalog metadata."""

import asyncio
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_async_db
from app.query_catalog import CatalogQuery, CatalogQueryWrite

from . import service
from . import user_defined_service
from .model import (
    CatalogMetadataListResponse,
    CatalogMetadataPatch,
    CatalogMetadataResponse,
    CatalogNamespaceListResponse,
    CatalogQueryListResponse,
)
from .service import CatalogQueryNotFoundError

router = APIRouter(prefix="/queries", tags=["queries"])


@router.get("/catalog", response_model=CatalogQueryListResponse, response_model_exclude_none=True)
async def list_catalog_queries(
    namespace: str | None = Query(default=None, description="Filter by namespace name or directory"),
    tag: str | None = Query(default=None, description="Filter by exact tag"),
    q: str | None = Query(default=None, description="Search query names, descriptions, tags, and ids"),
    view: Literal["graph", "tabular"] | None = Query(default=None, description="Filter by available view"),
) -> CatalogQueryListResponse:
    """List normalized query catalog entries."""
    items = service.list_catalog_queries(namespace=namespace, tag=tag, q=q, view=view)
    return CatalogQueryListResponse(items=items, count=len(items))


@router.get("/catalog/namespaces", response_model=CatalogNamespaceListResponse)
async def list_catalog_namespaces() -> CatalogNamespaceListResponse:
    """List query catalog namespaces in display order."""
    items = service.list_namespaces()
    return CatalogNamespaceListResponse(items=items, count=len(items))


@router.get("/catalog/{namespace}/{slug}", response_model=CatalogQuery, response_model_exclude_none=True)
async def get_catalog_query(namespace: str, slug: str) -> CatalogQuery:
    """Get one normalized query catalog entry."""
    catalog_query = service.get_catalog_query(namespace=namespace, slug=slug)
    if catalog_query is None:
        raise HTTPException(status_code=404, detail="Catalog query not found")
    return catalog_query


@router.put("/catalog/{namespace}/{slug}", response_model=CatalogQuery, response_model_exclude_none=True)
async def put_catalog_query(
    namespace: str, slug: str, payload: CatalogQueryWrite
) -> CatalogQuery:
    """Create or update a user-defined query override."""
    try:
        return await asyncio.to_thread(
            user_defined_service.save_query, namespace, slug, payload
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.delete("/catalog/{namespace}/{slug}", response_model=None)
async def delete_catalog_query(namespace: str, slug: str) -> dict | Response:
    """Delete a user-defined query override, if one exists."""
    deleted = await asyncio.to_thread(
        user_defined_service.delete_query, namespace, slug
    )
    if deleted:
        return {"message": "Query override deleted"}
    return Response(status_code=204)


# ── Catalog metadata (favourites) ─────────────────────────────────────


@router.get("/catalog-metadata", response_model=CatalogMetadataListResponse)
async def list_catalog_metadata(
    is_favourite: bool | None = Query(
        default=None, description="Filter by favourite state"
    ),
    db: AsyncSession = Depends(get_async_db),
) -> CatalogMetadataListResponse:
    """List catalog metadata rows, optionally filtered by favourite state."""
    items = await service.list_catalog_metadata(db, is_favourite=is_favourite)
    return CatalogMetadataListResponse(
        items=[CatalogMetadataResponse.model_validate(item) for item in items],
        count=len(items),
    )


@router.get("/catalog-metadata/{catalog_id:path}", response_model=CatalogMetadataResponse)
async def get_catalog_metadata(
    catalog_id: str,
    db: AsyncSession = Depends(get_async_db),
) -> CatalogMetadataResponse:
    """Fetch a single catalog metadata row by ``catalog_id``."""
    row = await service.get_catalog_metadata(db, catalog_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Catalog metadata not found")
    return CatalogMetadataResponse.model_validate(row)


@router.put("/catalog-metadata/{catalog_id:path}", response_model=CatalogMetadataResponse)
async def set_catalog_metadata(
    catalog_id: str,
    payload: CatalogMetadataPatch,
    db: AsyncSession = Depends(get_async_db),
) -> CatalogMetadataResponse:
    """Upsert a catalog metadata row (idempotent).

    Validates ``catalog_id`` against the YAML catalog (404 if unknown).
    """
    try:
        row = await service.set_catalog_metadata(
            db, catalog_id, payload.is_favourite
        )
    except CatalogQueryNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return CatalogMetadataResponse.model_validate(row)

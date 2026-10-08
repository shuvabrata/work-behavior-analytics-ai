"""FastAPI router for Activity Timeline API v1.

Endpoints:
* ``GET /api/v1/activity/timeline`` — multi-lane swimlane data.
* ``GET /api/v1/activity/suggest`` — typeahead for the entity selector.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_async_db
from common.logger import logger

from . import service
from .model import SuggestResponse, TimelineRequest, TimelineResponse
from .service import InvalidCursorError, InvalidWbaIdError, validate_cursor

router = APIRouter(prefix="/activity", tags=["activity"])


@router.get("/timeline", response_model=TimelineResponse)
async def get_timeline(
    wba_ids: str = Query(
        ...,
        description=(
            "Comma-separated WBA canonical keys, one per lane. "
            "e.g. github::Person::alice,github::Person::bob"
        ),
    ),
    scope: str = Query(
        default="activity",
        description="activity (default) = actions involving the entity; history = own state changes.",
    ),
    from_: datetime | None = Query(
        default=None,
        alias="from",
        description="Time range start (ISO 8601).",
    ),
    to: datetime | None = Query(
        default=None,
        description="Time range end (ISO 8601).",
    ),
    cursor: str | None = Query(
        default=None,
        description="Opaque pagination cursor from a previous response.",
    ),
    limit: int = Query(
        default=20,
        ge=1,
        le=100,
        description="Events per lane. Default 20, max 100.",
    ),
    mock: str | None = Query(
        default=None,
        description=(
            "DEV ONLY: switch the mock scenario for this request. Only takes "
            "effect while TIMELINE_MOCK_SCENARIO mock mode is enabled."
        ),
    ),
    db: AsyncSession = Depends(get_async_db),
) -> TimelineResponse:
    """Return swimlane timeline data for one or more entities."""
    if scope not in ("activity", "history"):
        raise HTTPException(
            status_code=400,
            detail={
                "error": "Invalid scope",
                "message": "scope must be 'activity' or 'history'",
            },
        )

    # Validate every WBA ID up front so a single bad key fails the whole
    # request with a 400 (not a silently-skipped lane).
    wba_id_list = [item.strip() for item in wba_ids.split(",") if item.strip()]
    if not wba_id_list:
        raise HTTPException(
            status_code=400,
            detail={"error": "Invalid wba_ids", "message": "wba_ids must not be empty"},
        )
    for wba_id in wba_id_list:
        try:
            service.parse_wba_id(wba_id)
        except InvalidWbaIdError as exc:
            raise HTTPException(
                status_code=400,
                detail={
                    "error": "Invalid WBA ID",
                    "message": str(exc),
                    "wba_id": wba_id,
                },
            ) from exc

    # Validate the cursor once up front (it applies to all lanes).
    if cursor:
        try:
            validate_cursor(cursor)
        except InvalidCursorError as exc:
            raise HTTPException(
                status_code=400,
                detail={"error": "Invalid cursor", "message": str(exc)},
            ) from exc

    request = TimelineRequest(
        wba_ids=wba_id_list,
        scope=scope,  # type: ignore[arg-type]  # validated above
        from_=from_,
        to=to,
        cursor=cursor,
        limit=limit,
    )

    logger.info(
        f"[Activity] timeline request lanes={len(wba_id_list)} "
        f"scope={scope} from={from_} to={to} limit={limit} cursor={cursor is not None}"
    )

    try:
        response = await service.get_timeline(db, request, mock_scenario=mock)
    except Exception as exc:
        logger.exception(f"[Activity] Unhandled error during timeline fetch: {exc}")
        raise HTTPException(
            status_code=500,
            detail={"error": "Timeline fetch failed", "message": str(exc)},
        ) from exc

    logger.info(
        f"[Activity] timeline response lanes={len(response.lanes)} "
        f"events={sum(len(lane.events) for lane in response.lanes)}"
    )
    return response


@router.get("/suggest", response_model=SuggestResponse)
async def suggest(
    q: str = Query(
        ...,
        min_length=3,
        description="Search term for typeahead (min 3 characters).",
    ),
    limit: int = Query(
        default=10,
        ge=1,
        le=20,
        description="Max suggestions to return. Default 10, max 20.",
    ),
    mock: str | None = Query(
        default=None,
        description=(
            "DEV ONLY: switch the mock scenario for this request. Only takes "
            "effect while TIMELINE_MOCK_SCENARIO mock mode is enabled."
        ),
    ),
    db: AsyncSession = Depends(get_async_db),
) -> SuggestResponse:
    """Typeahead suggestions for the timeline entity selector."""
    logger.info(f"[Activity] suggest q={q!r} limit={limit}")
    try:
        results = await service.get_suggestions(db, q=q, limit=limit, mock_scenario=mock)
    except Exception as exc:
        logger.exception(f"[Activity] Unhandled error during suggest: {exc}")
        raise HTTPException(
            status_code=500,
            detail={"error": "Suggest failed", "message": str(exc)},
        ) from exc
    return SuggestResponse(results=results)

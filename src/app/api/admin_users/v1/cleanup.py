"""Per-subject cleanup of application rows after a user is deleted or disabled.

Each step is an isolated unit: one step raising must not prevent the next from
running, because leaving a live session behind is worse than leaving a favourite
behind. The whole job is fire-and-forget — the router schedules it only after
Keycloak has accepted the delete/disable — so failures are logged, never raised.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, cast

from sqlalchemy import CursorResult, delete, func, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.auth_session import AuthSession
from app.db.models.catalog_metadata import CatalogMetadata
from app.db.session import ASYNC_SESSION_LOCAL
from common.logger import logger

CleanupStep = Callable[[AsyncSession, str], Awaitable[int]]

_CursorResult = CursorResult[Any]


async def _purge_auth_sessions(session: AsyncSession, subject: str) -> int:
    result = cast(
        _CursorResult,
        await session.execute(delete(AuthSession).where(AuthSession.subject == subject)),
    )
    return int(result.rowcount or 0)


async def _purge_catalog_metadata(session: AsyncSession, subject: str) -> int:
    result = cast(
        _CursorResult,
        await session.execute(delete(CatalogMetadata).where(CatalogMetadata.subject == subject)),
    )
    return int(result.rowcount or 0)


async def _revoke_auth_sessions(session: AsyncSession, subject: str) -> int:
    result = cast(
        _CursorResult,
        await session.execute(
            update(AuthSession)
            .where(AuthSession.subject == subject, AuthSession.revoked_at.is_(None))
            .values(revoked_at=func.now())  # pylint: disable=not-callable
        ),
    )
    return int(result.rowcount or 0)


_PURGE_STEPS: tuple[CleanupStep, ...] = (_purge_auth_sessions, _purge_catalog_metadata)
_REVOKE_STEPS: tuple[CleanupStep, ...] = (_revoke_auth_sessions,)


async def _run(steps: tuple[CleanupStep, ...], subject: str) -> None:
    """Run every step in its own transaction; never re-raise."""
    async with ASYNC_SESSION_LOCAL() as session:
        for step in steps:
            try:
                count = await step(session, subject)
                await session.commit()
                logger.info(
                    f"user_cleanup_completed step={step.__name__} subject={subject!r} rows={count}"
                )
            except Exception:  # pylint: disable=broad-except
                await session.rollback()
                logger.error(
                    f"user_cleanup_step_failed step={step.__name__} subject={subject!r}",
                    exc_info=True,
                )


async def purge_user_data(subject: str) -> None:
    """Delete every app-owned row for *subject* (used after account deletion)."""
    await _run(_PURGE_STEPS, subject)


async def revoke_user_sessions(subject: str) -> None:
    """Revoke *subject*'s live sessions (used after the account is disabled)."""
    await _run(_REVOKE_STEPS, subject)

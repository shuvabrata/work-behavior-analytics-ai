"""Database access for the ``auth_session`` table.

Every function takes an ``AsyncSession`` and performs only persistence work —
the transaction boundary (commit/rollback) belongs to the service layer, as in
every other API package. Rows returned here stay attached to the caller's
session.

The table stores only the SHA-256 hash of the session cookie id
(``session_id_hash``) and the Fernet-encrypted refresh token. No access token is
ever written down.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.auth_session import AuthSession

#: Sessions become eligible for purge this long after they ended.
_PURGE_GRACE = timedelta(hours=24)


async def create_session(  # pylint: disable=too-many-arguments
    db: AsyncSession,
    *,
    session_id_hash: str,
    subject: str,
    username: str,
    roles: list[str],
    refresh_token_encrypted: str,
    expires_at: datetime,
) -> AuthSession:
    """Insert a new session row and return it (flushed, not committed)."""
    now = datetime.now(expires_at.tzinfo)
    session = AuthSession(
        session_id_hash=session_id_hash,
        subject=subject,
        username=username,
        roles=roles,
        refresh_token_encrypted=refresh_token_encrypted,
        expires_at=expires_at,
        last_seen_at=now,
    )
    db.add(session)
    await db.flush()
    return session


async def get_active_session(
    db: AsyncSession, session_id_hash: str
) -> AuthSession | None:
    """Return the unrevoked row for *session_id_hash*, or ``None``."""
    stmt = select(AuthSession).where(
        AuthSession.session_id_hash == session_id_hash,
        AuthSession.revoked_at.is_(None),
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def touch_session(
    db: AsyncSession,
    row: AuthSession,
    *,
    last_seen_at: datetime,
    refresh_token_encrypted: str | None = None,
) -> None:
    """Update ``last_seen_at``, and the rotated refresh token when given.

    Keycloak returns a new refresh token on every refresh; persisting it here
    is what keeps the session usable past the first token lifetime.
    """
    values: dict[str, object] = {"last_seen_at": last_seen_at}
    if refresh_token_encrypted is not None:
        values["refresh_token_encrypted"] = refresh_token_encrypted
    await db.execute(
        update(AuthSession).where(AuthSession.id == row.id).values(**values)
    )


async def revoke_session(
    db: AsyncSession, row: AuthSession, *, revoked_at: datetime
) -> None:
    """Mark the row revoked, so it is no longer an active session."""
    await db.execute(
        update(AuthSession)
        .where(AuthSession.id == row.id)
        .values(revoked_at=revoked_at)
    )


async def purge_expired(db: AsyncSession, *, now: datetime) -> int:
    """Delete rows that expired or were revoked long ago; return the count.

    Called opportunistically (never on a request path), so the table cannot
    grow without bound. The 24-hour grace after ``expires_at``/``revoked_at``
    keeps recently-ended sessions visible for a short audit window.
    """
    cutoff = now - _PURGE_GRACE
    stmt = delete(AuthSession).where(
        (AuthSession.expires_at < cutoff)
        | (AuthSession.revoked_at < cutoff)
    )
    result = await db.execute(stmt)
    return int(getattr(result, "rowcount", 0) or 0)


__all__ = [
    "create_session",
    "get_active_session",
    "purge_expired",
    "revoke_session",
    "touch_session",
]

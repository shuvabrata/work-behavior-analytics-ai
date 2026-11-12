"""Unit tests for the admin users cleanup module."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.admin_users.v1 import cleanup

pytestmark = [pytest.mark.unit, pytest.mark.asyncio]


class _FakeSession:
    """A session stub recording executed statements and transaction calls."""

    def __init__(self) -> None:
        self.executed: list[Any] = []
        self.commits = 0
        self.rollbacks = 0

    async def execute(self, statement: Any) -> Any:
        self.executed.append(statement)
        return _FakeResult()

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1


class _FakeResult:
    rowcount = 1


class _SessionFactory:
    def __init__(self, session: _FakeSession) -> None:
        self._session = session

    def __call__(self) -> "_SessionFactory":
        return self

    async def __aenter__(self) -> _FakeSession:
        return self._session

    async def __aexit__(self, *args: object) -> None:
        return None


@pytest.fixture()
def fake_session(monkeypatch: pytest.MonkeyPatch) -> _FakeSession:
    session = _FakeSession()
    monkeypatch.setattr(cleanup, "ASYNC_SESSION_LOCAL", _SessionFactory(session))
    return session


async def test_purge_runs_both_steps(fake_session: _FakeSession) -> None:
    await cleanup.purge_user_data("sub-1")
    assert len(fake_session.executed) == 2
    assert fake_session.commits == 2


async def test_purge_step_failure_does_not_stop_next(
    monkeypatch: pytest.MonkeyPatch, fake_session: _FakeSession
) -> None:
    calls: list[str] = []

    async def _ok(session: AsyncSession, subject: str) -> int:
        calls.append("ok")
        return 1

    async def _boom(session: AsyncSession, subject: str) -> int:
        calls.append("boom")
        raise RuntimeError("nope")

    monkeypatch.setattr(cleanup, "_PURGE_STEPS", (_boom, _ok))
    await cleanup.purge_user_data("sub-1")

    assert calls == ["boom", "ok"]
    assert fake_session.rollbacks == 1


async def test_revoke_runs_revoke_step(fake_session: _FakeSession) -> None:
    await cleanup.revoke_user_sessions("sub-1")
    assert len(fake_session.executed) == 1
    assert fake_session.commits == 1


async def test_no_exception_escapes(monkeypatch: pytest.MonkeyPatch, fake_session: _FakeSession) -> None:
    async def _boom(session: AsyncSession, subject: str) -> int:
        raise RuntimeError("nope")

    monkeypatch.setattr(cleanup, "_PURGE_STEPS", (_boom,))
    await cleanup.purge_user_data("sub-1")

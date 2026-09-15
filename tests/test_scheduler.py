"""Unit tests for the scheduler module (app/scheduler.py).

Tests cover the two core functions:
  - ``_try_acquire_lease``  — distributed leader election via Postgres UPDATE
  - ``_get_due_connectors`` — per-connector due-check logic

All DB interaction is mocked with ``AsyncMock(spec=AsyncSession)`` following
the project convention in ``test_commands_api.py``.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.scheduler import _get_due_connectors, _try_acquire_lease


pytestmark = [pytest.mark.unit]


# ===========================================================================
# Fixtures
# ===========================================================================


@pytest.fixture
def mock_db() -> AsyncMock:
    """Minimal mock of an async SQLAlchemy session."""
    db = AsyncMock(spec=AsyncSession)
    db.execute = AsyncMock()
    db.commit = AsyncMock()
    return db


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _make_connector(
    connector_type: str = "github",
    enabled: bool = True,
    scan_interval_hours: int | None = 24,
) -> MagicMock:
    """Build a mock Connector with the attributes the scheduler reads."""
    c = MagicMock()
    c.connector_type = connector_type
    c.enabled = enabled
    c.scan_interval_hours = scan_interval_hours
    return c


_UNSET = object()


def _execute_result(*, rowcount: int = 0, scalars=None, scalar_one_or_none=_UNSET) -> MagicMock:
    """Build a mock result object returned by ``await db.execute(...)``."""
    result = MagicMock()
    result.rowcount = rowcount
    if scalars is not None:
        result.scalars.return_value.all.return_value = scalars
    if scalar_one_or_none is not _UNSET:
        result.scalar_one_or_none.return_value = scalar_one_or_none
    return result


# ===========================================================================
# _try_acquire_lease
# ===========================================================================


class TestTryAcquireLease:
    """Leader election: the UPDATE rowcount determines who is the leader."""

    @pytest.mark.asyncio
    async def test_expired_lease_grants_leadership(self, mock_db):
        """An expired lease row is claimed — rowcount=1 → returns True."""
        mock_db.execute.return_value = _execute_result(rowcount=1)
        result = await _try_acquire_lease(mock_db, instance_id="inst-A", tick_minutes=10)
        assert result is True
        mock_db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_renew_own_lease_succeeds(self, mock_db):
        """Re-acquiring own active lease → rowcount=1 → returns True."""
        mock_db.execute.return_value = _execute_result(rowcount=1)
        result = await _try_acquire_lease(mock_db, instance_id="inst-A", tick_minutes=10)
        assert result is True

    @pytest.mark.asyncio
    async def test_lease_held_by_other_returns_false(self, mock_db):
        """Active lease held by another instance → rowcount=0 → returns False."""
        mock_db.execute.return_value = _execute_result(rowcount=0)
        result = await _try_acquire_lease(mock_db, instance_id="inst-B", tick_minutes=10)
        assert result is False
        mock_db.commit.assert_awaited_once()  # commit still called

    @pytest.mark.asyncio
    async def test_commit_always_called(self, mock_db):
        """Commit is called regardless of whether lease was acquired."""
        mock_db.execute.return_value = _execute_result(rowcount=0)
        await _try_acquire_lease(mock_db, instance_id="inst-X", tick_minutes=5)
        mock_db.commit.assert_awaited_once()


# ===========================================================================
# _get_due_connectors
# ===========================================================================


REGISTRY_WITH_PRODUCER = {
    "github": {"producer_container": "github-producer"},
    "jira": {"producer_container": "jira-producer"},
    "slack": {},  # no producer_container
}

REGISTRY_NO_PRODUCER = {
    "github": {},  # producer_container missing
}


class TestGetDueConnectors:
    """Due-check logic for each enabled connector with a schedule."""

    @pytest.mark.asyncio
    async def test_no_scan_history_is_due(self, mock_db):
        """Connector with no scan history (last_scan_at=None) is always due."""
        connector = _make_connector(connector_type="github", scan_interval_hours=24)
        # Call 1: SELECT connectors → returns [connector]
        # Call 2: SELECT MAX(created_at) → returns None (no history)
        mock_db.execute.side_effect = [
            _execute_result(scalars=[connector]),
            _execute_result(scalar_one_or_none=None),
        ]
        now = _utc_now()
        with patch("app.scheduler.CONNECTOR_REGISTRY", REGISTRY_WITH_PRODUCER):
            due = await _get_due_connectors(mock_db, now)
        assert due == [("github", "github-producer")]

    @pytest.mark.asyncio
    async def test_elapsed_interval_is_due(self, mock_db):
        """Last scan was longer ago than the interval → connector is due."""
        connector = _make_connector(connector_type="github", scan_interval_hours=24)
        last_scan_at = _utc_now() - timedelta(hours=25)  # 25h ago, interval is 24h
        mock_db.execute.side_effect = [
            _execute_result(scalars=[connector]),
            _execute_result(scalar_one_or_none=last_scan_at),
        ]
        now = _utc_now()
        with patch("app.scheduler.CONNECTOR_REGISTRY", REGISTRY_WITH_PRODUCER):
            due = await _get_due_connectors(mock_db, now)
        assert due == [("github", "github-producer")]

    @pytest.mark.asyncio
    async def test_within_interval_is_not_due(self, mock_db):
        """Last scan was more recent than the interval → connector is NOT due."""
        connector = _make_connector(connector_type="github", scan_interval_hours=24)
        last_scan_at = _utc_now() - timedelta(hours=5)  # 5h ago, interval is 24h
        mock_db.execute.side_effect = [
            _execute_result(scalars=[connector]),
            _execute_result(scalar_one_or_none=last_scan_at),
        ]
        now = _utc_now()
        with patch("app.scheduler.CONNECTOR_REGISTRY", REGISTRY_WITH_PRODUCER):
            due = await _get_due_connectors(mock_db, now)
        assert due == []

    @pytest.mark.asyncio
    async def test_disabled_connector_still_due(self, mock_db):
        """enabled=False does NOT prevent a scan — the enabled flag is ignored.

        The scheduler only keys off ``scan_interval_hours``. A disabled
        connector with an interval and no scan history is still due.
        """
        connector = _make_connector(
            connector_type="github",
            scan_interval_hours=24,
            enabled=False,
        )
        mock_db.execute.side_effect = [
            _execute_result(scalars=[connector]),
            _execute_result(scalar_one_or_none=None),  # no scan history
        ]
        now = _utc_now()
        with patch("app.scheduler.CONNECTOR_REGISTRY", REGISTRY_WITH_PRODUCER):
            due = await _get_due_connectors(mock_db, now)
        assert due == [("github", "github-producer")]

    @pytest.mark.asyncio
    async def test_no_producer_container_skipped(self, mock_db):
        """Connectors with no producer_container in the registry are silently skipped."""
        connector = _make_connector(connector_type="github", scan_interval_hours=24)
        # Registry has no producer_container for github
        mock_db.execute.return_value = _execute_result(scalars=[connector])
        now = _utc_now()
        with patch("app.scheduler.CONNECTOR_REGISTRY", REGISTRY_NO_PRODUCER):
            due = await _get_due_connectors(mock_db, now)
        assert due == []
        # MAX(created_at) query should NOT be called — we skip before that
        assert mock_db.execute.call_count == 1

    @pytest.mark.asyncio
    async def test_null_interval_skipped(self, mock_db):
        """scan_interval_hours=None connectors are excluded by the SQL WHERE clause.

        We simulate this by returning an empty list from the DB query.
        """
        mock_db.execute.return_value = _execute_result(scalars=[])
        now = _utc_now()
        with patch("app.scheduler.CONNECTOR_REGISTRY", REGISTRY_WITH_PRODUCER):
            due = await _get_due_connectors(mock_db, now)
        assert due == []

    @pytest.mark.asyncio
    async def test_multiple_connectors_mixed_due(self, mock_db):
        """Multiple connectors: only those past their interval are returned."""
        github = _make_connector(connector_type="github", scan_interval_hours=24)
        jira = _make_connector(connector_type="jira", scan_interval_hours=12)
        now = _utc_now()
        github_last_scan = now - timedelta(hours=25)  # due
        jira_last_scan = now - timedelta(hours=3)     # not due (12h interval)

        mock_db.execute.side_effect = [
            _execute_result(scalars=[github, jira]),   # connector query
            _execute_result(scalar_one_or_none=github_last_scan),  # github MAX(created_at)
            _execute_result(scalar_one_or_none=jira_last_scan),    # jira MAX(created_at)
        ]
        with patch("app.scheduler.CONNECTOR_REGISTRY", REGISTRY_WITH_PRODUCER):
            due = await _get_due_connectors(mock_db, now)
        assert due == [("github", "github-producer")]
        assert ("jira", "jira-producer") not in due

    @pytest.mark.asyncio
    async def test_exactly_at_interval_boundary_is_due(self, mock_db):
        """A connector scanned exactly interval-hours ago is considered due (>=)."""
        connector = _make_connector(connector_type="github", scan_interval_hours=24)
        now = _utc_now()
        last_scan_at = now - timedelta(hours=24, microseconds=0)
        mock_db.execute.side_effect = [
            _execute_result(scalars=[connector]),
            _execute_result(scalar_one_or_none=last_scan_at),
        ]
        with patch("app.scheduler.CONNECTOR_REGISTRY", REGISTRY_WITH_PRODUCER):
            due = await _get_due_connectors(mock_db, now)
        assert due == [("github", "github-producer")]

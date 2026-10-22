"""Shared fixtures for producer/daemon tests.

The daemon performs HTTP calls to the app API during startup and shutdown
(orphan reconciliation). Tests must never make real network calls, so the
reconciliation helpers are neutralised by default; tests that assert on
reconciliation patch them explicitly.
"""

from __future__ import annotations

import pytest

import connectors.producers.daemon_common as daemon_mod


@pytest.fixture(autouse=True)
def _no_reconciliation_http(monkeypatch: pytest.MonkeyPatch) -> None:
    """Neutralise reconciliation HTTP so tests are hermetic and offline."""
    monkeypatch.setattr(daemon_mod, "_get_command_status", lambda command_id: None)
    monkeypatch.setattr(daemon_mod, "_reconcile_startup_orphans", lambda container_name: None)


@pytest.fixture(autouse=True)
def _reset_daemon_state() -> None:
    """Clear module-level child-tracking state between tests."""
    daemon_mod._children.clear()
    daemon_mod._test_children.clear()
    daemon_mod._exited.clear()

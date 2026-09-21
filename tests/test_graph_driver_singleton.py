"""Tests for Neo4j driver singleton lifecycle and thread-safety."""

import threading
from unittest.mock import MagicMock

import pytest
from app.api.graph.v1.query import _get_driver, close_driver
from app.settings import settings


@pytest.mark.unit
class TestNeo4jDriverSingleton:
    """Verify the Neo4j driver singleton pattern and cleanup."""

    @pytest.fixture(autouse=True)
    def _setup(self, monkeypatch):
        """Enable Neo4j and reset driver state before each test."""
        close_driver()  # ensure clean state from prior tests
        monkeypatch.setattr(settings, "NEO4J_ENABLED", True)
        # Replace GraphDatabase in the query module with a mock class so that
        # _get_driver() hits the mock instead of the real C extension class.
        mock_graph_db = MagicMock()
        monkeypatch.setattr("app.api.graph.v1.query.GraphDatabase", mock_graph_db)
        yield
        # Teardown: close driver and reset singleton state
        close_driver()

    def test_singleton_returns_same_instance(self):
        """Calling _get_driver() twice returns the exact same object."""
        mock_driver = MagicMock()
        mock_driver.verify_connectivity.return_value = None
        import app.api.graph.v1.query as query_mod
        query_mod.GraphDatabase.driver.return_value = mock_driver

        first = _get_driver()
        second = _get_driver()

        assert first is second
        # GraphDatabase.driver should only be called once
        query_mod.GraphDatabase.driver.assert_called_once()

    def test_close_driver_resets_instance(self):
        """After close_driver(), a new _get_driver() call creates a new instance."""
        first_mock = MagicMock()
        first_mock.verify_connectivity.return_value = None
        second_mock = MagicMock()
        second_mock.verify_connectivity.return_value = None
        import app.api.graph.v1.query as query_mod
        query_mod.GraphDatabase.driver.side_effect = [first_mock, second_mock]

        first = _get_driver()
        close_driver()
        second = _get_driver()

        assert first is not second
        # GraphDatabase.driver should be called twice (once per creation)
        assert query_mod.GraphDatabase.driver.call_count == 2
        # The closed driver should have been closed
        first_mock.close.assert_called_once()

    def test_thread_safety(self):
        """Multiple threads calling _get_driver() concurrently all get the same instance."""
        mock_driver = MagicMock()
        mock_driver.verify_connectivity.return_value = None
        import app.api.graph.v1.query as query_mod
        query_mod.GraphDatabase.driver.return_value = mock_driver

        results = []

        def _call_get_driver():
            results.append(_get_driver())

        threads = [threading.Thread(target=_call_get_driver) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # All threads should have the same instance
        assert len(results) == 5
        for result in results:
            assert result is results[0]
        # GraphDatabase.driver should only be called once (singleton)
        query_mod.GraphDatabase.driver.assert_called_once()

    def test_close_driver_idempotent(self):
        """Calling close_driver() multiple times does not raise."""
        mock_driver = MagicMock()
        mock_driver.verify_connectivity.return_value = None
        import app.api.graph.v1.query as query_mod
        query_mod.GraphDatabase.driver.return_value = mock_driver

        # Create the driver first
        _get_driver()

        # Close twice — should not raise
        close_driver()
        close_driver()  # second call is a no-op

        # close() should have been called exactly once
        mock_driver.close.assert_called_once()
"""Shared long-lived Neo4j driver singleton for the app process.

The Neo4j Python driver manages its own connection pool and is designed to be a
process-wide singleton — creating one per request wastes a TCP/TLS handshake and
bypasses pooling. The driver is thread-safe and safe to share across async tasks
(as long as it is not used from the event loop thread directly — call it inside
``asyncio.to_thread``).
"""

from __future__ import annotations

import threading
from typing import Any

from neo4j import GraphDatabase
from neo4j.exceptions import ServiceUnavailable

from app.settings import settings
from common.logger import logger

_driver_lock = threading.Lock()
_driver_instance = None


def get_driver() -> Any:
    """Return the process-wide Neo4j driver, creating it on first call.

    The driver manages its own connection pool and is safe to share across
    threads and async tasks. Do NOT close this driver per-request.

    Returns:
        The shared neo4j.GraphDatabase.driver instance.

    Raises:
        RuntimeError: if the driver cannot be created — not enabled, or the
            initial connection/verification fails.
    """
    global _driver_instance
    if not settings.NEO4J_ENABLED:
        raise RuntimeError("Neo4j is not enabled. Set NEO4J_ENABLED=true in .env")
    if _driver_instance is not None:
        return _driver_instance  # type: ignore[unreachable]
    with _driver_lock:
        if _driver_instance is not None:
            return _driver_instance  # type: ignore[unreachable]
        try:
            _driver_instance = GraphDatabase.driver(
                settings.NEO4J_URI,
                auth=(settings.NEO4J_USERNAME, settings.NEO4J_PASSWORD),
            )
            _driver_instance.verify_connectivity()
            logger.info(f"Neo4j driver singleton created: uri={settings.NEO4J_URI}")
            return _driver_instance
        except (ServiceUnavailable, Exception) as e:
            _driver_instance = None
            logger.error(f"Neo4j driver creation failed: {e}")
            raise RuntimeError(
                f"Unable to connect to Neo4j database: {str(e)}"
            ) from e


def close_driver() -> None:
    """Close the shared Neo4j driver singleton if initialized.

    Safe to call multiple times — subsequent calls are no-ops.
    Intended for application shutdown (FastAPI lifespan teardown).
    """
    global _driver_instance
    with _driver_lock:
        if _driver_instance is not None:
            _driver_instance.close()
            _driver_instance = None
            logger.info("Neo4j driver singleton closed")


# Backwards-compatible alias for internal callers in the graph query layer.
_get_driver = get_driver

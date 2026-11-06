"""REST snapshot client for non-app processes.

Provides ``fetch_runtime_snapshot()`` so that producer daemons and signal
consumers can retrieve the effective runtime settings from the app API
without importing ``src.app`` or requiring a DB connection.
"""

from __future__ import annotations

from typing import Any

import requests

from common.auth import ServiceTokenError, get_service_token  # noqa: F401  # pylint: disable=unused-import
from common.logger import logger
from common.runtime_settings.config import RuntimeConfig

# ── Public API ─────────────────────────────────────────────────────────


def fetch_runtime_snapshot(
    api_base_url: str,
    timeout: int = 10,
) -> RuntimeConfig:
    """Fetch the effective runtime settings snapshot from the app API.

    Calls ``GET <api_base_url>/api/v1/settings/runtime-snapshot`` and
    returns a validated ``RuntimeConfig`` instance.

    Args:
        api_base_url: Base URL of the running app, e.g. ``http://api:8000``.
        timeout: HTTP request timeout in seconds.

    Returns:
        A ``RuntimeConfig`` instance populated from the API snapshot.

    Raises:
        ServiceTokenError: A service credential could not be obtained. This is a
            configuration or availability fault and is never retried unauthenticated.
        requests.exceptions.RequestException: The API was unreachable or returned a
            non-2xx status.
        ValueError: The response body was not a valid ``RuntimeConfig`` payload.
    """
    url = f"{api_base_url.rstrip('/')}/api/v1/settings/runtime-snapshot"
    headers = {"Authorization": f"Bearer {get_service_token()}"}

    resp = requests.get(url, headers=headers, timeout=timeout)
    resp.raise_for_status()
    data: dict[str, Any] = resp.json()
    config = RuntimeConfig(**data)
    logger.info(f"Fetched runtime settings snapshot from {url}")
    return config

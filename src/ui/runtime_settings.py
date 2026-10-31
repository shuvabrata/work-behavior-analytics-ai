"""The UI runtime's runtime-settings cache.

Same interface as ``app.runtime_settings`` (``get`` / ``get_int`` / ``refresh``),
but sourced from the API over HTTP instead of from the database — the UI holds
no driver and no DB credentials. The snapshot endpoint
(``GET /api/v1/settings/runtime-snapshot``) is the same one the producer daemons
and the signal consumer use, but the UI reaches it through :mod:`ui.api_client`
so the call carries the **user's** bearer token: the UI holds no service
credential, so the shared service-token helper would always fail here and, once
the endpoint requires a credential, would silently stop refreshing.

The cache itself is the **shared** object owned by :mod:`domain.timezone`, so a
refresh here is visible to ``domain.timezone.get_app_timezone`` (and vice versa).
``app.runtime_settings`` binds to the same object in the API runtime.

Two rules keep the shared cache honest, and both matter while the UI and the API
still run in one process (Steps 5–7):

* The import-time seed is **non-destructive**. A seed field the shared cache
  already carries a non-default value for is left alone, so the UI's env seed can
  never overwrite the API runtime's configuration.
* :func:`refresh` is driven by a real trigger (the Flask ``before_request`` hook
  in ``ui.request_logging``, at most once per :data:`REFRESH_TTL_SECONDS`), so a
  runtime setting edited in the Settings UI actually reaches the UI.

No RabbitMQ listener lives here: ``common.messaging.settings_events`` needs
``aio_pika``, which the UI image does not carry.
"""

from __future__ import annotations

import threading
import time

from common.logger import logger
from common.runtime_settings import RuntimeConfig
from domain.settings import UISettings
from domain.timezone import runtime_settings
from ui.settings import settings

#: Minimum seconds between two API snapshot fetches from the UI.
#:
#: Bounds :func:`refresh` so a page with many callbacks does not fetch per call.
#: The UI's runtime-tunable values are not latency-critical, so a minute of
#: staleness is an acceptable trade for not hammering the API.
REFRESH_TTL_SECONDS = 60.0

# The runtime-configurable subset of ``UISettings``, used to seed the cache so
# env-configured values are available before the first API snapshot arrives.
_SEED_FIELDS = (
    "HTTP_REQUEST_TIMEOUT",
    "GRAPH_UI_MAX_NODES_TO_EXPAND",
    "GRAPH_UI_MAX_NODE_LABEL_CHARS",
    "CONNECTOR_SCAN_POLL_INTERVAL",
    "RECENT_ACTIONS_LIMIT",
    "TIMEZONE",
    "UI_DATETIME_FORMAT",
    "UI_DATE_FORMAT",
    "LOG_LEVEL",
    "LOG_FORMAT",
    "ENABLE_FILE_LOGGING",
    "LOG_DIR",
    "LOG_SIGNAL_DUMPS",
)


def _seed_config(ui_settings: UISettings, existing: RuntimeConfig) -> RuntimeConfig:
    """Return *existing* with any still-default seed field filled from *ui_settings*.

    **Non-destructive by construction.** ``RuntimeConfigCache.refresh`` replaces
    the snapshot rather than merging, so a naive seed would overwrite the API
    runtime's whole configuration with this 13-field model whenever both runtimes
    share the cache. Filling only fields that still hold their code default makes
    the seed a no-op against a populated cache and a fallback only when there is
    nothing to lose.
    """
    defaults = RuntimeConfig()
    data = existing.model_dump()
    for name in _SEED_FIELDS:
        if getattr(existing, name) == getattr(defaults, name):
            data[name] = getattr(ui_settings, name)
    return RuntimeConfig(**data)


def refresh() -> None:
    """Refresh the shared cache from the API's runtime-snapshot endpoint.

    The fetch goes through ``ui.api_client`` so it rides the user's bearer token
    (``ui.api_client`` attaches one from the session cookie). The shared
    ``common.runtime_settings.client.fetch_runtime_snapshot`` helper is no longer
    used here: it authenticates with a **service** token, and the UI container
    holds no ``KEYCLOAK_*`` environment, so that call would always go out
    unauthenticated — and once plan 057 requires a credential on the snapshot
    route, silently stop refreshing with no error and no broken page.

    This must never raise into the request cycle: ``refresh`` is called from the
    Flask ``before_request`` hook. An ``ApiError`` — including
    :data:`ui.api_client.STATUS_NO_RESPONSE` for a down API — is caught and the
    values the cache already holds are preserved, exactly as the previous
    helper's fallback did.
    """
    # Imported lazily: ui.api_client imports this module at module level, so a
    # top-level import here is a cycle.
    # pylint: disable=import-outside-toplevel
    from ui import api_client
    from ui.api_client import ApiError

    try:
        payload = api_client.get_json("/api/v1/settings/runtime-snapshot")
        snapshot = RuntimeConfig(**payload)
    except ApiError as exc:
        logger.warning(
            f"UI runtime-settings snapshot unavailable (status={exc.status_code}) "
            "— keeping current values"
        )
        return
    except (ValueError, TypeError) as exc:
        logger.warning(
            f"UI runtime-settings snapshot was invalid ({exc}) — keeping current values"
        )
        return

    if snapshot == RuntimeConfig():
        logger.warning(
            "UI runtime-settings snapshot was empty — keeping current values"
        )
        return
    runtime_settings.refresh(snapshot)


# Non-destructive seed of env-configured values into the shared cache.
runtime_settings.refresh(_seed_config(settings, runtime_settings.current()))

_last_refresh: float = 0.0
_refresh_lock = threading.Lock()


def refresh_if_stale(ttl_seconds: float = REFRESH_TTL_SECONDS) -> None:
    """Call :func:`refresh` at most once per *ttl_seconds*.

    This is the trigger the UI actually uses. It is called from the Flask
    ``before_request`` hook (``ui.request_logging.register_request_logging``), so
    a long-lived UI process picks up a ``HTTP_REQUEST_TIMEOUT`` edit made in the
    Settings UI without fetching the snapshot on every callback. A page that
    issues 30 callbacks still costs at most one request per *ttl_seconds*.

    Thread-safe: the gunicorn gthread workers share this module, so the
    timestamp is guarded by a lock. A refresh failure is logged by
    :func:`refresh` itself and leaves the timestamp advanced, so a down API is
    retried once per TTL rather than on every request.
    """
    global _last_refresh  # noqa: PLW0603
    now = time.monotonic()
    with _refresh_lock:
        if now - _last_refresh < ttl_seconds:
            return
        _last_refresh = now
    refresh()


__all__ = [
    "REFRESH_TTL_SECONDS",
    "refresh",
    "refresh_if_stale",
    "runtime_settings",
]

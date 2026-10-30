"""Flask request logging for the Dash UI runtime.

Ports the API's ``add_request_context`` middleware (``app/api_main.py``) onto
the Dash Flask server so UI traffic is instrumented with the same field names
and the same ``X-Request-ID`` header while it is still served in-process.

The UI is mounted at ``/app`` through the ASGI-to-WSGI bridge until Step 8, so
each ``/app`` request is logged twice — once by the API's FastAPI middleware and
once here. That duplication ends when the mount does; it is not a defect.
"""
import time
from contextlib import ExitStack
from uuid import uuid4

from flask import Flask, Response, g, request

from common.logger import LogContext, logger
from ui.runtime_settings import refresh_if_stale


def _request_id() -> str:
    """Return the inbound request id, minting one when absent."""
    return request.headers.get("x-request-id") or str(uuid4())


def register_request_logging(server: Flask) -> None:
    """Attach the before/after/teardown logging hooks to ``server``.

    Logs INFO for every request, including ``/_dash-*`` paths, matching the
    API's current behaviour.
    """

    @server.before_request
    def _before_request() -> None:
        # Drive the UI's runtime-settings refresh from a real request, bounded by
        # a TTL so a page load with many callbacks still costs at most one API
        # fetch per REFRESH_TTL_SECONDS. Without this trigger the UI's cache
        # would only ever hold its import-time env seed, and a runtime setting
        # edited in the Settings UI would never reach the UI.
        refresh_if_stale()

        request_id = _request_id()
        g.request_id = request_id
        g.request_start = time.perf_counter()
        # Entered here and unwound in ``teardown_request`` so the contextvar is
        # reset even when the request raises before ``after_request`` runs.
        stack = ExitStack()
        stack.enter_context(LogContext(request_id=request_id))
        g.log_context_stack = stack

    @server.after_request
    def _after_request(response: Response) -> Response:
        duration_ms = (time.perf_counter() - g.request_start) * 1000
        logger.info(
            "[HTTP] request_complete "
            f"method={request.method} path={request.path} "
            f"status={response.status_code} duration_ms={round(duration_ms, 2)}"
        )
        response.headers["X-Request-ID"] = g.request_id
        return response

    @server.teardown_request
    def _teardown_request(exception: BaseException | None) -> None:
        stack: ExitStack | None = getattr(g, "log_context_stack", None)
        if exception is not None:
            start_time = getattr(g, "request_start", None)
            duration_ms = (
                (time.perf_counter() - start_time) * 1000 if start_time is not None else 0.0
            )
            logger.exception(
                "[HTTP] request_failed "
                f"method={request.method} path={request.path} "
                f"duration_ms={round(duration_ms, 2)}"
            )
        if stack is not None:
            stack.close()

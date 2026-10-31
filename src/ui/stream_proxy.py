"""The Dash SSE proxy — the one browser-facing route that talks to the API.

Chat streaming was the single place where the **browser** called ``/api/v1``
directly (``src/ui/assets/stream-bridge.js``). Under a bearer-only API that call
returns 401, because the browser holds a session cookie and not a token. Rather
than exempting ``/chats/{id}/stream`` from bearer auth — which would make the
cookie a first-class API credential for one endpoint — this route exists to
attach the bearer server-side and stream the response back through.

The route is registered under ``/app/`` explicitly: Dash's
``requests_pathname_prefix`` governs Dash's own routes, not routes added to the
Flask server, so a bare ``/stream/<session_id>`` is answered by Dash's
``/app/<path:path>`` catch-all with a 405.

Two details are load-bearing:

* ``stream=True`` on the upstream request, so ``requests`` does not buffer the
  whole body before returning.
* ``X-Accel-Buffering: no`` on the response. The browser now calls ``/app/...``,
  which nginx buffers by default — the ``proxy_buffering off`` that used to
  apply lives on the ``/api/v1/chats/`` location, which is no longer in the path.
  Without both, chat appears frozen and then dumps the whole answer at once.
"""

from __future__ import annotations

from collections.abc import Iterator

import requests
from flask import Flask, Response, request, stream_with_context

from common.logger import logger
from ui.auth import SessionMissingError, get_token
from ui.settings import settings

#: Upstream read timeout is ``None`` (a stream may legitimately run for minutes);
#: only the connection and response-header wait are bounded.
_CONNECT_TIMEOUT_SECONDS = 10

#: Chunk size for the relay. ``None`` means "whatever arrived", which keeps the
#: token-by-token cadence the browser renders.
_RELAY_CHUNK_SIZE = None


def _upstream_url(session_id: str) -> str:
    """Return the API stream URL for *session_id*."""
    return f"{settings.API_BASE_URL.rstrip('/')}/api/v1/chats/{session_id}/stream"


def _relay(upstream: requests.Response) -> Iterator[bytes]:
    """Yield the upstream body chunk by chunk, always closing the connection."""
    try:
        for chunk in upstream.iter_content(chunk_size=_RELAY_CHUNK_SIZE):
            if chunk:
                yield chunk
    finally:
        upstream.close()


def register_stream_proxy(server: Flask) -> None:
    """Register ``POST /app/stream/<session_id>`` on *server*."""

    @server.route("/app/stream/<session_id>", methods=["POST"])
    def stream_proxy(session_id: str) -> Response:
        """Attach the bearer and relay the API's SSE response to the browser."""
        try:
            token = get_token()
        except SessionMissingError:
            logger.warning(f"Stream proxy called without a session (session_id={session_id!r})")
            return Response(
                '{"detail": {"error": "unauthenticated"}}',
                status=401,
                mimetype="application/json",
            )

        payload = request.get_json(silent=True) or {}
        try:
            upstream = requests.post(
                _upstream_url(session_id),
                json=payload,
                headers={"Authorization": f"Bearer {token}"},
                stream=True,
                timeout=(_CONNECT_TIMEOUT_SECONDS, None),
            )
        except requests.RequestException as exc:
            logger.warning(f"Stream proxy could not reach the API: {type(exc).__name__}")
            return Response(
                '{"detail": {"error": "stream_unavailable"}}',
                status=503,
                mimetype="application/json",
            )

        # Relay an upstream error as JSON rather than as a malformed event stream;
        # the browser's bridge already renders ``HTTP <status>: <body>``.
        if upstream.status_code >= 400:
            body = upstream.text
            upstream.close()
            return Response(body, status=upstream.status_code, mimetype="application/json")

        response = Response(stream_with_context(_relay(upstream)), mimetype="text/event-stream")
        response.headers["X-Accel-Buffering"] = "no"
        response.headers["Cache-Control"] = "no-cache"
        return response


__all__ = ["register_stream_proxy"]

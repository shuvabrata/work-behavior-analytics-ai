"""Unit tests for proxy-awareness: the two base-URL settings and header trust.

Two separate concerns live here, both introduced by the TLS reverse-proxy work
(nginx terminates TLS, the app serves plain HTTP behind it):

1. ``EXTERNAL_BASE_URL`` vs ``API_BASE_URL`` — the browser-facing URL and the
   container-internal one. They are deliberately different values, and the
   independence test is the regression guard for the most likely future
   mistake: "de-duplicating" them by pointing ``API_BASE_URL`` at
   ``EXTERNAL_BASE_URL``, which would send every Dash callback through TLS to
   the public host and break it.

2. Forwarded-header trust. uvicorn wraps the app in its own
   ``ProxyHeadersMiddleware`` only at server startup, so driving ``app.main.app``
   through ``httpx.ASGITransport`` never exercises it. The tests below build a
   throwaway ASGI app and wrap it with the real uvicorn middleware, which is
   what keeps them honest about production behaviour.

Run with:
    pytest -m unit tests/test_proxy_awareness.py -v
"""

from __future__ import annotations

import httpx
import pytest
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from app.settings import Settings


pytestmark = pytest.mark.unit


def _build_settings(**kwargs: str) -> Settings:
    """Build a Settings instance from defaults plus explicit overrides.

    ``_env_file=None`` keeps a developer's local ``.env`` out of the test.
    """
    return Settings(
        DATABASE_URL="postgresql+asyncpg://user:pass@localhost:5432/testdb",
        _env_file=None,
        **kwargs,
    )


# ─────────────────────────────────────────────────────────────────────────────
# EXTERNAL_BASE_URL — the browser-facing URL
# ─────────────────────────────────────────────────────────────────────────────


def test_external_base_url_defaults_to_https_localhost(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("EXTERNAL_BASE_URL", raising=False)

    configured = _build_settings()

    assert configured.EXTERNAL_BASE_URL == "https://localhost"


def test_external_base_url_is_overridable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("EXTERNAL_BASE_URL", raising=False)

    configured = _build_settings(EXTERNAL_BASE_URL="https://wba.example.com")

    assert configured.EXTERNAL_BASE_URL == "https://wba.example.com"


# ─────────────────────────────────────────────────────────────────────────────
# API_BASE_URL — the container-internal URL
# ─────────────────────────────────────────────────────────────────────────────


def test_api_base_url_defaults_to_localhost_8000(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("API_BASE_URL", raising=False)

    configured = _build_settings()

    assert configured.API_BASE_URL == "http://localhost:8000"


def test_api_base_url_is_overridable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("API_BASE_URL", raising=False)

    configured = _build_settings(API_BASE_URL="http://sentinel:9999")

    assert configured.API_BASE_URL == "http://sentinel:9999"


# ─────────────────────────────────────────────────────────────────────────────
# Independence — the two values must never be conflated
# ─────────────────────────────────────────────────────────────────────────────


def test_external_and_api_base_urls_are_independent(monkeypatch: pytest.MonkeyPatch) -> None:
    """Setting one must not change the other in either direction."""
    monkeypatch.delenv("EXTERNAL_BASE_URL", raising=False)
    monkeypatch.delenv("API_BASE_URL", raising=False)

    only_external = _build_settings(EXTERNAL_BASE_URL="https://sentinel.example")
    assert only_external.EXTERNAL_BASE_URL == "https://sentinel.example"
    assert only_external.API_BASE_URL == "http://localhost:8000"

    only_api = _build_settings(API_BASE_URL="http://sentinel:9999")
    assert only_api.API_BASE_URL == "http://sentinel:9999"
    assert only_api.EXTERNAL_BASE_URL == "https://localhost"


# ─────────────────────────────────────────────────────────────────────────────
# Forwarded-header trust — exercises the real uvicorn middleware
# ─────────────────────────────────────────────────────────────────────────────


async def _echo_scheme(request: Request) -> JSONResponse:
    """Report the scheme the application actually sees."""
    return JSONResponse({"scheme": request.url.scheme})


def _build_inner_app() -> Starlette:
    return Starlette(routes=[Route("/scheme", _echo_scheme)])


def _build_proxied_app() -> ProxyHeadersMiddleware:
    """A minimal app wrapped the way uvicorn wraps the real one at startup."""
    inner = _build_inner_app()
    return ProxyHeadersMiddleware(inner, trusted_hosts="*")  # type: ignore[return-value]


async def _request_scheme(app: object, forwarded_proto: str) -> str:
    """Send one request with ``X-Forwarded-Proto`` and return the seen scheme."""
    transport = httpx.ASGITransport(app=app)  # type: ignore[arg-type]
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/scheme", headers={"X-Forwarded-Proto": forwarded_proto})
    return str(response.json()["scheme"])


@pytest.mark.asyncio
async def test_forwarded_proto_is_ignored_without_the_middleware() -> None:
    """Control: the header alone changes nothing.

    This is what makes the assertion below non-vacuous — if the middleware were
    absent (or its trusted-peer set excluded the client), the scheme stays
    ``http`` even though ``X-Forwarded-Proto: https`` was sent.
    """
    scheme = await _request_scheme(_build_inner_app(), "https")

    assert scheme == "http"


@pytest.mark.asyncio
async def test_proxy_headers_middleware_honours_forwarded_proto() -> None:
    """The real uvicorn middleware promotes X-Forwarded-Proto to the scheme.

    Mirrors what ``--forwarded-allow-ips`` enables in ``entrypoint.sh``: with the
    middleware in place and the peer trusted, the app sees ``https`` and can
    build correct external URLs behind nginx.
    """
    scheme = await _request_scheme(_build_proxied_app(), "https")

    assert scheme == "https"


@pytest.mark.asyncio
async def test_proxy_headers_middleware_keeps_plain_http_without_the_header() -> None:
    """No forwarded header means no promotion — the middleware is not a blanket override."""
    transport = httpx.ASGITransport(app=_build_proxied_app())  # type: ignore[arg-type]
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/scheme")

    assert response.json()["scheme"] == "http"

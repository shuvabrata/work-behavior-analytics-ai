"""Integration tests for the API-documentation routes served through nginx.

FastAPI exposes ``/docs`` (Swagger UI), ``/redoc`` and ``/openapi.json`` at the
API's own root. Those paths are outside ``/api`` and ``/app``, so nginx never
routed them until the three ``location`` blocks under "API documentation" in
``deploy/nginx/nginx.conf`` were added. These tests exercise the real TLS entry
point to prove the routes are live end to end — the unit test in
``tests/test_nginx_docs_routes.py`` only proves the config *says* so.

Reaching the app over HTTPS requires the Compose stack::

    docker compose up -d

Markers: ``integration``, ``server``. Per ``tests/conftest.py``, ``server`` tests
are pointed at the locally issued mkcert CA and **fail rather than skip** when
the stack is down, so a broken proxy is never mistaken for a passing run.

Run with:
    pytest -m "integration and server" tests/test_docs_endpoints_server.py -v
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

pytestmark = [pytest.mark.integration, pytest.mark.server]

BASE_URL = "https://localhost"

# Long enough for a cold Swagger CDN fetch, short enough to fail fast if the
# proxy is answering from nowhere.
TIMEOUT = 20.0

# Every route the config is expected to expose.
DOCS_PATHS = ["/docs", "/redoc", "/openapi.json"]


def _get(path: str) -> httpx.Response:
    """GET ``path`` through nginx with TLS verification left on."""
    return httpx.get(f"{BASE_URL}{path}", timeout=TIMEOUT, follow_redirects=False)


@pytest.mark.parametrize("path", DOCS_PATHS)
def test_docs_path_is_reachable_through_nginx(path: str) -> None:
    """Each docs path returns 200 rather than nginx's own 404."""
    response = _get(path)
    assert response.status_code == 200, (
        f"GET {BASE_URL}{path} returned {response.status_code}, not 200. A 404 "
        f"from nginx means no `location` block matched the path; a 404 from the "
        f"API means the route is not registered. Body starts: "
        f"{response.text[:200]!r}"
    )


@pytest.mark.parametrize("path", ["/docs", "/redoc"])
def test_html_docs_pages_render_the_expected_ui(path: str) -> None:
    """The two HTML docs pages serve their UI, not an error page."""
    response = _get(path)
    assert response.status_code == 200
    content_type = response.headers.get("content-type", "")
    assert "text/html" in content_type, (
        f"{path} returned content-type {content_type!r}"
    )
    expected = "swagger" if path == "/docs" else "redoc"
    assert expected in response.text.lower(), (
        f"{path} does not look like the {expected} UI; body starts: "
        f"{response.text[:200]!r}"
    )


def test_swagger_oauth2_redirect_subpath_is_routed() -> None:
    """``/docs/oauth2-redirect`` is reachable.

    This is the check that distinguishes a prefix ``location /docs`` from an
    exact ``location = /docs``: with the exact form, nginx would answer 404 here
    because no other location claims the sub-path.
    """
    response = _get("/docs/oauth2-redirect")
    assert response.status_code == 200, (
        f"/docs/oauth2-redirect returned {response.status_code}; `location /docs` "
        f"must be a prefix match, not an exact one"
    )


def test_openapi_json_is_valid_json_with_paths() -> None:
    """``/openapi.json`` returns a parseable schema that actually describes routes."""
    response = _get("/openapi.json")
    assert response.status_code == 200, (
        f"/openapi.json returned {response.status_code}"
    )
    assert "application/json" in response.headers.get("content-type", ""), (
        f"/openapi.json content-type is "
        f"{response.headers.get('content-type')!r}"
    )
    document: dict[str, Any] = response.json()
    assert "openapi" in document, f"schema has no `openapi` version key: {list(document)}"
    paths = document.get("paths")
    assert isinstance(paths, dict) and paths, (
        f"schema has no non-empty `paths`; got {type(paths).__name__}"
    )


def test_schema_describes_the_real_api() -> None:
    """The proxied schema is the API's own, not an empty shell.

    A proxy that returned a cached or truncated document would still parse; this
    pins it to routes that must exist.
    """
    document = _get("/openapi.json").json()
    paths = document["paths"]
    for expected in ("/api/health", "/api/v1/settings/"):
        assert expected in paths, (
            f"{expected} missing from the proxied schema; a route the UI depends "
            f"on is not advertised. Found {len(paths)} paths"
        )
    assert len(paths) >= 30, (
        f"only {len(paths)} paths in the proxied schema — looks truncated"
    )


def test_schema_server_url_keeps_swagger_requests_same_origin() -> None:
    """Swagger's "Try it out" must call back through this proxy.

    FastAPI omits ``servers`` when no ``root_path`` is set (verified: the key is
    absent, not ``[{"url": "/"}]``). Swagger then resolves request URLs against
    the page origin, so calls land on ``https://localhost/api/v1/...`` and nginx
    proxies them. If ``servers`` ever gains an absolute URL pointing at a
    container-internal host (``http://api:8000``), the browser could not resolve
    it and every "Try it out" would fail.
    """
    servers = _get("/openapi.json").json().get("servers")
    if servers is None:
        return  # FastAPI's default with no root_path — same-origin by definition.
    assert isinstance(servers, list), f"`servers` is {type(servers).__name__}"
    for entry in servers:
        url = entry.get("url", "")
        assert url.startswith("/"), (
            f"schema server url {url!r} is not origin-relative; Swagger's requests "
            f"would not go through the nginx proxy"
        )


def test_unrouted_path_still_404s() -> None:
    """Adding the docs routes did not add a catch-all.

    If a bare ``location /`` had been introduced, every unmatched path would be
    proxied to an upstream instead of 404ing — which would also shadow the Dash
    UI. ``/definitely-not-a-route`` has no location and must 404.
    """
    response = _get("/definitely-not-a-route")
    assert response.status_code == 404, (
        f"/definitely-not-a-route returned {response.status_code}, expected 404 — "
        f"nginx gained a catch-all location"
    )


def test_docs_routes_are_not_served_by_the_ui() -> None:
    """``/docs`` is the API's docs, not a Dash page.

    The UI serves ``/app/*``; a docs route accidentally pointed at the UI
    upstream would return the Dash shell (or its catch-all), not Swagger.
    """
    body = _get("/docs").text.lower()
    assert "dash" not in body, (
        "the /docs response mentions Dash — it may be proxied to the UI upstream "
        "rather than the API"
    )
    assert "openapi.json" in body or "swagger" in body, (
        "the /docs response does not reference the Swagger UI or the schema"
    )

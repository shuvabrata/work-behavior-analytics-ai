"""Unit tests for the API-documentation routes in the nginx config.

``deploy/nginx/nginx.conf`` proxies ``/docs``, ``/redoc`` and ``/openapi.json``
to the API upstream. Nothing else in the suite reads that file, so a future edit
could drop one of those locations and the only symptom would be a 404 in a
browser — no test, no CI gate, no log line would say why.

These assertions are deliberately structural rather than a substring search on
the whole file. A bare ``"/docs" in conf`` check would pass on a commented-out
block, and a whole-file search would pass on a location placed in the plaintext
``listen 80`` server, where ``return 301`` would answer instead of the API. So
each check locates the **TLS** ``server`` block, extracts its ``location``
blocks, and asserts on the spec plus that block's own ``proxy_pass`` target.

Run with:
    pytest -m unit tests/test_nginx_docs_routes.py -v
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[1]
NGINX_CONF = REPO_ROOT / "deploy" / "nginx" / "nginx.conf"

API_UPSTREAM = "http://wba_api"

# Every path FastAPI's defaults expose. The schema path is required by both UIs:
# Swagger UI and ReDoc each fetch it to render, so omitting it yields a page
# that loads its shell and then shows nothing.
DOCS_LOCATIONS = ["/docs", "/redoc", "/openapi.json"]


def _block_at(text: str, open_index: int) -> str:
    """Return ``text`` from ``open_index`` (a ``{``) through its matching ``}``."""
    if text[open_index] != "{":
        raise AssertionError(f"index {open_index} is not an opening brace")
    depth = 0
    for i in range(open_index, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return text[open_index:i + 1]
    raise AssertionError("unbalanced braces in nginx config")


def _server_blocks(config: str) -> list[str]:
    """Return the body of every top-level ``server { ... }`` block."""
    blocks = []
    for match in re.finditer(r"(?m)^\s*server\s*\{", config):
        blocks.append(_block_at(config, config.index("{", match.end() - 1)))
    return blocks


def _tls_server_block(config: str) -> str:
    """Return the ``server`` block that terminates TLS.

    Selecting by ``listen 443`` rather than by position means the port-80
    redirect block cannot satisfy any assertion below by accident.
    """
    for block in _server_blocks(config):
        if re.search(r"(?m)^\s*listen\s+443", block):
            return block
    raise AssertionError("no `listen 443` server block found in nginx.conf")


def _location_blocks(server: str) -> dict[str, str]:
    """Map each ``location`` spec (normalised) to that block's full text."""
    locations: dict[str, str] = {}
    for match in re.finditer(r"(?m)^\s*location\s+([^{]+?)\s*\{", server):
        spec = " ".join(match.group(1).split())
        body = _block_at(server, server.index("{", match.end() - 1))
        locations[spec] = body
    return locations


@pytest.fixture(name="tls_locations", scope="module")
def fixture_tls_locations() -> dict[str, str]:
    """The TLS server's ``location`` blocks, keyed by spec."""
    config = NGINX_CONF.read_text(encoding="utf-8")
    return _location_blocks(_tls_server_block(config))


@pytest.mark.parametrize("path", DOCS_LOCATIONS)
def test_docs_location_is_proxied_to_the_api(
    tls_locations: dict[str, str], path: str
) -> None:
    """Each docs path has a location that proxies to the API upstream."""
    assert path in tls_locations, (
        f"no `location {path}` in the TLS server block of {NGINX_CONF}; "
        f"found: {sorted(tls_locations)}"
    )
    body = tls_locations[path]
    assert f"proxy_pass {API_UPSTREAM};" in body, (
        f"`location {path}` does not proxy to {API_UPSTREAM}; the docs are served "
        f"by the API (src/app/api_main.py), not the UI. Body:\n{body}"
    )


@pytest.mark.parametrize("path", DOCS_LOCATIONS)
def test_docs_location_forwards_proxy_headers(
    tls_locations: dict[str, str], path: str
) -> None:
    """Each docs location forwards the same headers as the /api location.

    The API builds absolute URLs from these, so a docs route that omits them
    behaves differently from every other proxied request.
    """
    body = tls_locations[path]
    for header in ("Host", "X-Real-IP", "X-Forwarded-For", "X-Forwarded-Proto"):
        assert f"proxy_set_header {header} " in body, (
            f"`location {path}` does not set {header}, unlike `location /api`"
        )


def test_docs_route_is_a_prefix_match_for_the_oauth2_redirect(
    tls_locations: dict[str, str],
) -> None:
    """``/docs`` is a prefix, not an exact match.

    Swagger serves its OAuth2 callback at ``/docs/oauth2-redirect``. An exact
    ``location = /docs`` would leave that path unrouted and nginx would answer
    its own 404.
    """
    assert "/docs" in tls_locations, "no `/docs` location found"
    assert "= /docs" not in tls_locations, (
        "`/docs` is an exact match, so /docs/oauth2-redirect will 404"
    )


def test_no_prefix_catch_all_location_was_introduced(
    tls_locations: dict[str, str],
) -> None:
    """The docs routes did not add a bare prefix catch-all.

    A ``location /`` would match every path not claimed by a longer prefix and
    silently route the whole origin to one upstream — shadowing the Dash UI at
    ``/app``. Note the existing ``location = /`` is *exact* and is the intended
    302 to ``/app``, so it must not be flagged here.
    """
    assert "/" not in tls_locations, (
        "nginx.conf gained a bare `location /` prefix block; every route is meant "
        f"to be an explicit prefix. Found: {sorted(tls_locations)}"
    )


def test_openapi_path_is_not_shadowed_by_the_ui(tls_locations: dict[str, str]) -> None:
    """``/openapi.json`` and ``/app`` do not overlap.

    A sanity check on the route set: the API's schema must not resolve to the
    Dash UI upstream, which serves nothing at that path.
    """
    assert "/openapi.json" in tls_locations
    assert API_UPSTREAM in tls_locations["/openapi.json"]
    assert "http://wba_ui" not in tls_locations["/openapi.json"]


def test_config_references_only_real_upstreams(tls_locations: dict[str, str]) -> None:
    """Every proxied docs location names an upstream declared in the file.

    Guards the rename that already happened once: the retired ``app`` service
    (Plan 052) must not reappear as a docs target.
    """
    config = NGINX_CONF.read_text(encoding="utf-8")
    declared = set(re.findall(r"(?m)^\s*upstream\s+(\S+)\s*\{", config))
    assert {"wba_api", "wba_ui"} <= declared, (
        f"expected the wba_api and wba_ui upstreams; found {sorted(declared)}"
    )
    for path in DOCS_LOCATIONS:
        target = re.search(r"proxy_pass\s+(\S+);", tls_locations[path])
        assert target is not None, f"`location {path}` has no proxy_pass"
        upstream = target.group(1).rsplit("//", 1)[-1]
        assert upstream in declared, (
            f"`location {path}` proxies to {target.group(1)}, but `{upstream}` is "
            f"not a declared upstream ({sorted(declared)})"
        )


def test_docs_locations_are_absent_from_the_plaintext_server() -> None:
    """The port-80 block redirects and must not serve the docs.

    If a docs location landed there, ``return 301`` would win and the docs would
    be a redirect loop rather than a page.
    """
    config = NGINX_CONF.read_text(encoding="utf-8")
    for block in _server_blocks(config):
        if re.search(r"(?m)^\s*listen\s+443", block):
            continue
        plaintext_locations = _location_blocks(block)
        assert "/docs" not in plaintext_locations, (
            "`location /docs` was added to the plaintext (port 80) server block"
        )


def test_openapi_schema_is_served_without_a_root_path() -> None:
    """The API must not set ``root_path``, or the proxied schema breaks.

    With no ``root_path`` FastAPI emits ``servers: [{"url": "/"}]``, so Swagger's
    "Try it out" calls back through the same origin (and therefore through these
    nginx locations). A ``root_path`` would rewrite that base and the browser
    would call a path nginx does not proxy.
    """
    api_main = REPO_ROOT / "src" / "app" / "api_main.py"
    source = api_main.read_text(encoding="utf-8")
    assert "root_path" not in source, (
        f"{api_main} sets root_path; the docs schema's server URL would no longer "
        f"be same-origin, so Swagger's requests would miss the nginx routes"
    )


def test_parser_finds_the_expected_routes() -> None:
    """Guard the parser itself, so the checks above cannot pass vacuously.

    ``test_no_prefix_catch_all_location_was_introduced`` asserts the *absence* of
    a spec. If the regex stopped matching (a config reformat, an indentation
    change), it would find no locations and pass while proving nothing. Pin the
    parser against the routes that must always be present.
    """
    assert NGINX_CONF.is_file(), f"{NGINX_CONF} does not exist"
    config = NGINX_CONF.read_text(encoding="utf-8")
    locations = _location_blocks(_tls_server_block(config))
    assert locations, "the location-block parser found nothing — it has gone blind"
    for required in ("/api", "/app", "/docs"):
        assert required in locations, (
            f"parser did not find `location {required}`; parsed: {sorted(locations)}"
        )

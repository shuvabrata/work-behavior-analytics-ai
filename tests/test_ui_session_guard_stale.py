"""Unit tests for the session guard's stale-cookie probe.

A ``wba_session`` cookie can outlive the session row behind it (revoked,
expired, or a failing token exchange). The guard's original check was cookie
*presence* only, so a dead session rendered a full page with no identity and no
way back to login — the operator's reported trap. This file pins the probe that
closes it, and the three cases where it must stay out of the way.
"""

from __future__ import annotations

from typing import Any, Iterator

import pytest
from flask import Flask

from ui import api_client, auth
from ui.session_guard import session_guard

pytestmark = pytest.mark.unit

_SESSION = "a-session-id"

_EXEMPT_PATH = "/app/assets/x.js"
_PAGE_PATH = "/app/search"


class _StubResponse:
    """Minimal ``requests.Response`` stand-in for the transport seam."""

    def __init__(self, status_code: int, payload: Any = None) -> None:
        self.status_code = status_code
        self._payload = payload

    @property
    def ok(self) -> bool:
        return self.status_code < 400

    @property
    def text(self) -> str:
        return ""

    def json(self) -> Any:
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


class _Transport:
    """Records calls and serves a queued/settable response or raises."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.response: _StubResponse | None = None
        self.error: Exception | None = None

    def __call__(self, _method: str, url: str, **_kwargs: Any) -> _StubResponse:
        self.calls.append(url)
        if self.error is not None:
            raise self.error
        assert self.response is not None
        return self.response


class _TokenExchange:
    """Serves the bearer the client needs before it can probe ``/auth/me``."""

    def post(self, url: str, **_kwargs: Any) -> _StubResponse:
        return _StubResponse(200, {"access_token": "tok", "expires_in": 900})


@pytest.fixture(name="app")
def _app() -> Flask:
    return Flask(__name__)


@pytest.fixture(name="transport")
def _transport(monkeypatch: pytest.MonkeyPatch) -> _Transport:
    stub = _Transport()
    monkeypatch.setattr(api_client, "_transport", stub)
    monkeypatch.setattr(auth, "_post", _TokenExchange().post)
    auth.clear_cache()
    yield stub
    auth.clear_cache()


def _request(app: Flask, path: str, *, cookie: bool, method: str = "GET"):
    headers = {"Cookie": f"{auth.SESSION_COOKIE_NAME}={_SESSION}"} if cookie else {}
    return app.test_request_context(path, method=method, headers=headers)


# ── cookie present + live session ────────────────────────────────────────


def test_live_session_passes_through(app: Flask, transport: _Transport) -> None:
    transport.response = _StubResponse(200, {"username": "dev-user"})
    with _request(app, _PAGE_PATH, cookie=True):
        assert session_guard() is None


# ── cookie present + dead session (the operator's bug) ───────────────────


def test_revoked_session_redirects_and_clears_the_cookie(
    app: Flask, transport: _Transport
) -> None:
    transport.response = _StubResponse(401, {"detail": "expired"})
    with _request(app, _PAGE_PATH, cookie=True):
        response = session_guard()

    assert response is not None
    assert response.status_code == 302
    assert response.headers["Location"].startswith("/api/v1/auth/login?next=")
    assert auth.SESSION_COOKIE_NAME in response.headers.get("Set-Cookie", "")


def test_role_less_session_is_not_logged_out(app: Flask, transport: _Transport) -> None:
    transport.response = _StubResponse(403, {"detail": "forbidden"})
    with _request(app, _PAGE_PATH, cookie=True):
        assert session_guard() is None


def test_transport_failure_does_not_loop(app: Flask, transport: _Transport) -> None:
    import requests

    transport.error = requests.exceptions.ConnectionError("refused")
    with _request(app, _PAGE_PATH, cookie=True):
        assert session_guard() is None


# ── cookie absent: unchanged behaviour ───────────────────────────────────


def test_cookie_absent_redirects_a_navigation(app: Flask, transport: _Transport) -> None:
    with _request(app, _PAGE_PATH, cookie=False):
        response = session_guard()

    assert response is not None
    assert response.status_code == 302
    assert transport.calls == []


def test_cookie_absent_returns_401_json_for_a_dash_xhr(
    app: Flask, transport: _Transport
) -> None:
    with _request(app, "/app/_dash-update-component", cookie=False, method="POST"):
        response = session_guard()

    assert response is not None
    status = response[1] if isinstance(response, tuple) else response.status_code
    assert status == 401
    assert transport.calls == []


# ── exempt paths make no probe at all ────────────────────────────────────


def test_exempt_path_makes_no_probe(app: Flask, transport: _Transport) -> None:
    transport.response = _StubResponse(401, {"detail": "expired"})
    with _request(app, _EXEMPT_PATH, cookie=True):
        assert session_guard() is None
    assert transport.calls == []


# ── the app root canonicalises to the Graph page ─────────────────────────


@pytest.mark.parametrize("path", ["/app", "/app/"])
def test_app_root_navigation_redirects_to_graph(app: Flask, path: str) -> None:
    with _request(app, path, cookie=False):
        response = session_guard()

    assert response is not None
    assert response.status_code == 302
    assert response.headers["Location"] == "/app/graph"


def test_app_root_canonicalises_before_the_session_check(
    app: Flask, transport: _Transport
) -> None:
    transport.response = _StubResponse(401, {"detail": "expired"})
    with _request(app, "/app/", cookie=True):
        response = session_guard()

    assert response is not None
    assert response.status_code == 302
    assert response.headers["Location"] == "/app/graph"
    assert transport.calls == []


@pytest.mark.parametrize("path", ["/app/graph", "/app/analytics"])
def test_page_paths_are_not_canonicalised(app: Flask, transport: _Transport, path: str) -> None:
    transport.response = _StubResponse(200, {"username": "dev-user"})
    with _request(app, path, cookie=True):
        assert session_guard() is None


def test_app_root_dash_xhr_is_not_redirected(app: Flask, transport: _Transport) -> None:
    transport.response = _StubResponse(200, {"username": "dev-user"})
    headers = {
        "Cookie": f"{auth.SESSION_COOKIE_NAME}={_SESSION}",
        "X-Requested-With": "XMLHttpRequest",
    }
    with app.test_request_context("/app/", method="GET", headers=headers):
        assert session_guard() is None

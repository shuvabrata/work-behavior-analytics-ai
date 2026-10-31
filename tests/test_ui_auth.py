"""Unit tests for the UI's per-worker token cache.

The cache is what keeps the browser from ever holding a token: one exchange per
60-second margin, per session, per worker. These tests pin the reuse rule, the
renew margin, and the two failure types the client distinguishes.
"""

from __future__ import annotations

from typing import Any, Iterator

import pytest
from flask import Flask

from ui import auth

pytestmark = pytest.mark.unit

_SESSION = "a-session-id"


@pytest.fixture(name="app")
def _app() -> Flask:
    """A minimal Flask app, so a real request context exists for the cookie."""
    flask_app = Flask(__name__)

    @flask_app.get("/probe")
    def _probe() -> str:  # pragma: no cover - never called
        return "ok"

    return flask_app


@pytest.fixture(name="with_session")
def _with_session(app: Flask) -> Iterator[Any]:
    """Yield a test request context carrying a ``wba_session`` cookie."""
    auth.clear_cache()
    with app.test_request_context(
        "/probe", headers={"Cookie": f"{auth.SESSION_COOKIE_NAME}={_SESSION}"}
    ):
        yield
    auth.clear_cache()


class _Response:
    def __init__(self, status_code: int, payload: Any) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self) -> Any:
        return self._payload


class _Exchange:
    """Records exchange calls and serves queued responses."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.responses: list[_Response] = []

    def post(self, url: str, **kwargs: Any) -> _Response:
        self.calls.append({"url": url, **kwargs})
        if self.responses:
            return self.responses.pop(0)
        return _Response(200, {"access_token": "tok", "expires_in": 900})


@pytest.fixture(name="exchange")
def _exchange(monkeypatch: pytest.MonkeyPatch) -> _Exchange:
    """Stub the token-exchange POST and record the calls it received."""
    stub = _Exchange()
    monkeypatch.setattr(auth, "_post", stub.post)
    return stub


# ── the cookie seam ──────────────────────────────────────────────────────


def test_no_cookie_raises_session_missing(app: Flask) -> None:
    auth.clear_cache()
    with app.test_request_context("/probe"):
        with pytest.raises(auth.SessionMissingError):
            auth.get_token()


def test_outside_a_request_context_there_is_no_session(app: Flask) -> None:
    assert auth.current_session_id() is None


# ── caching ──────────────────────────────────────────────────────────────


def test_second_call_reuses_the_cached_token(
    with_session: None, exchange: _Exchange
) -> None:
    first = auth.get_token()
    second = auth.get_token()

    assert first == second == "tok"
    assert len(exchange.calls) == 1


def test_token_inside_the_renew_margin_is_re_fetched(
    with_session: None, exchange: _Exchange
) -> None:
    call = exchange.calls

    def fake_post(url: str, **kwargs: Any) -> Any:
        call.append({"url": url, **kwargs})
        return _Response(200, {"access_token": f"tok-{len(call)}", "expires_in": 30})

    auth._post = fake_post  # type: ignore[assignment]
    first = auth.get_token()
    second = auth.get_token()

    # 30 s of life is inside the 60 s margin, so the second call must re-exchange.
    assert first == "tok-1"
    assert second == "tok-2"
    assert len(call) == 2


def test_invalidate_forces_a_re_fetch(
    with_session: None, exchange: _Exchange
) -> None:
    first = auth.get_token()
    auth.invalidate_token()
    second = auth.get_token()

    assert first == second == "tok"
    assert len(exchange.calls) == 2


# ── failure types ────────────────────────────────────────────────────────


def test_api_401_raises_session_missing(
    with_session: None, exchange: _Exchange, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        auth, "_post", lambda *a, **k: _Response(401, {"detail": "gone"})
    )

    with pytest.raises(auth.SessionMissingError):
        auth.get_token()


def test_api_503_raises_unavailable(
    with_session: None, exchange: _Exchange, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(auth, "_post", lambda *a, **k: _Response(503, {}))

    with pytest.raises(auth.TokenExchangeUnavailableError):
        auth.get_token()


def test_transport_failure_raises_unavailable(
    with_session: None, exchange: _Exchange, monkeypatch: pytest.MonkeyPatch
) -> None:
    import requests

    def boom(*args: Any, **kwargs: Any) -> Any:
        raise requests.exceptions.ConnectionError("refused")

    monkeypatch.setattr(auth, "_post", boom)

    with pytest.raises(auth.TokenExchangeUnavailableError):
        auth.get_token()


def test_exchange_posts_the_cookie_to_the_api(with_session: None, exchange: _Exchange) -> None:
    auth.get_token()

    assert exchange.calls[0]["url"].endswith("/api/v1/auth/token")
    assert exchange.calls[0]["cookies"] == {auth.SESSION_COOKIE_NAME: _SESSION}


# ── the session guard ────────────────────────────────────────────────────


@pytest.fixture(name="guarded_app")
def _guarded_app() -> Flask:
    """A Flask app with the guard registered and one page plus one asset route."""
    from ui.session_guard import register_session_guard

    flask_app = Flask(__name__)

    @flask_app.get("/app/graph")
    def _page() -> str:
        return "page"

    @flask_app.get("/app/assets/app.css")
    def _asset() -> str:
        return "css"

    @flask_app.post("/app/_dash-update-component")
    def _callback() -> str:
        return "cb"

    register_session_guard(flask_app)
    return flask_app


def test_guard_redirects_a_logged_out_navigation(guarded_app: Flask) -> None:
    auth.clear_cache()
    response = guarded_app.test_client().get("/app/graph")

    assert response.status_code == 302
    assert response.headers["Location"] == "/api/v1/auth/login?next=/app/graph"


def test_guard_lets_assets_through(guarded_app: Flask) -> None:
    auth.clear_cache()
    response = guarded_app.test_client().get("/app/assets/app.css")

    assert response.status_code == 200


def test_guard_returns_401_json_for_a_dash_callback(guarded_app: Flask) -> None:
    auth.clear_cache()
    response = guarded_app.test_client().post("/app/_dash-update-component")

    assert response.status_code == 401
    assert response.get_json() == {"detail": {"error": "unauthenticated"}}


def test_guard_allows_a_request_with_a_session_cookie(guarded_app: Flask) -> None:
    auth.clear_cache()
    client = guarded_app.test_client()
    # A bare ``Cookie`` header is not parsed by the test client's cookie jar;
    # ``set_cookie`` is what actually reaches ``request.cookies``.
    client.set_cookie(auth.SESSION_COOKIE_NAME, _SESSION, domain="localhost")
    response = client.get("/app/graph")

    assert response.status_code == 200


def test_guard_lets_the_dash_layout_endpoint_through(guarded_app: Flask) -> None:
    auth.clear_cache()
    from ui.session_guard import _is_exempt

    assert _is_exempt("/app/_dash-layout")
    assert _is_exempt("/app/_dash-dependencies")
    assert not _is_exempt("/app/_dash-update-component")

"""Unit tests for the Dash SSE proxy.

The proxy is the only browser-facing route that calls the API. Two properties
matter and neither is visible from the route existing: the bearer is attached
(so the API accepts the call at all), and ``X-Accel-Buffering: no`` is on the
response (without it nginx holds the whole body and chat appears to freeze then
dump).

The upstream is stubbed by monkeypatching ``ui.stream_proxy.requests.post``
locally, so no test here touches the network.
"""

from __future__ import annotations

from typing import Any, Iterator

import pytest
from flask import Flask

from ui import auth
from ui import stream_proxy

pytestmark = pytest.mark.unit

_SESSION_ID = "chat-123"


class _Upstream:
    """A streamed upstream response stand-in."""

    def __init__(self, status_code: int, chunks: list[bytes] | None = None, text: str = "") -> None:
        self.status_code = status_code
        self._chunks = chunks or []
        self.text = text
        self.closed = False

    def iter_content(self, chunk_size: Any = None) -> Iterator[bytes]:
        _ = chunk_size
        yield from self._chunks

    def close(self) -> None:
        self.closed = True


@pytest.fixture(name="app")
def _app() -> Flask:
    flask_app = Flask(__name__)
    stream_proxy.register_stream_proxy(flask_app)
    return flask_app


@pytest.fixture(name="with_cookie")
def _with_cookie(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make ``get_token`` succeed for the duration of a test."""
    auth.clear_cache()
    monkeypatch.setattr(stream_proxy, "get_token", lambda: "user-bearer")


def test_no_session_is_401_and_upstream_is_not_called(
    app: Flask, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("the upstream must not be called without a session")

    monkeypatch.setattr(stream_proxy.requests, "post", boom)
    monkeypatch.setattr(
        stream_proxy,
        "get_token",
        lambda: (_ for _ in ()).throw(auth.SessionMissingError("no cookie")),
    )

    response = app.test_client().post(f"/app/stream/{_SESSION_ID}", json={"message": "hi"})

    assert response.status_code == 401


def test_upstream_404_is_relayed_as_json(
    app: Flask, with_cookie: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        stream_proxy.requests, "post", lambda *a, **k: _Upstream(404, text="not found")
    )

    response = app.test_client().post(f"/app/stream/{_SESSION_ID}", json={"message": "hi"})

    assert response.status_code == 404
    assert response.get_data(as_text=True) == "not found"


def test_upstream_200_streams_with_no_buffering(
    app: Flask, with_cookie: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    upstream = _Upstream(200, chunks=[b"data: one\n\n", b"data: two\n\n"])
    monkeypatch.setattr(stream_proxy.requests, "post", lambda *a, **k: upstream)

    response = app.test_client().post(f"/app/stream/{_SESSION_ID}", json={"message": "hi"})

    assert response.status_code == 200
    assert response.mimetype == "text/event-stream"
    assert response.headers["X-Accel-Buffering"] == "no"
    assert response.get_data(as_text=True) == "data: one\n\ndata: two\n\n"
    assert upstream.closed is True


def test_bearer_is_attached_and_streaming_requested(
    app: Flask, with_cookie: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, Any] = {}

    def fake_post(url: str, **kwargs: Any) -> _Upstream:
        captured["url"] = url
        captured.update(kwargs)
        return _Upstream(200, chunks=[b"data: x\n\n"])

    monkeypatch.setattr(stream_proxy.requests, "post", fake_post)

    app.test_client().post(f"/app/stream/{_SESSION_ID}", json={"message": "hello"})

    assert captured["url"].endswith(f"/api/v1/chats/{_SESSION_ID}/stream")
    assert captured["headers"] == {"Authorization": "Bearer user-bearer"}
    assert captured["stream"] is True
    assert captured["json"] == {"message": "hello"}
    assert captured["timeout"][0] == 10
    assert captured["timeout"][1] is None

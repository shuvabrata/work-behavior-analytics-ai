"""Unit tests for the account bar's dead-session escape hatch.

The account bar returned ``None`` on any ``ApiError``, so a revoked session
removed the username *and* the only in-app way to sign in or out — leaving
cookie-clearing as the sole recovery. The ``AuthExpiredError`` branch restores a
**Sign in** control in the Sign out button's slot. This file pins that branch and
the two cases that must still render nothing.
"""

from __future__ import annotations

from typing import Any

import pytest
from dash import no_update  # noqa: F401 - documents the callback's vocabulary

from ui import api_client
from ui.components import account_bar

pytestmark = pytest.mark.unit


class _StubResponse:
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


def _install(monkeypatch: pytest.MonkeyPatch, response: Any) -> None:
    def _fake(method: str, url: str, **_kwargs: Any) -> Any:
        if isinstance(response, Exception):
            raise response
        return response

    monkeypatch.setattr(api_client, "_transport", _fake)


def _texts(children: Any) -> list[str]:
    """Flatten a Dash component tree to its string leaves."""
    found: list[str] = []
    stack = [children]
    while stack:
        node = stack.pop()
        if isinstance(node, str):
            found.append(node)
        elif isinstance(node, (list, tuple)):
            stack.extend(node)
        elif hasattr(node, "children"):
            stack.append(node.children)
    return found


def _hrefs(children: Any) -> list[str]:
    found: list[str] = []
    stack = [children]
    while stack:
        node = stack.pop()
        if isinstance(node, (list, tuple)):
            stack.extend(node)
        elif hasattr(node, "children"):
            href = getattr(node, "href", None)
            if href:
                found.append(href)
            stack.append(node.children)
    return found


def test_revoked_session_offers_sign_in(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, _StubResponse(401, {"detail": "expired"}))
    result = account_bar.render_account_bar("/app/graph")

    assert "Sign in" in _texts(result)
    hrefs = _hrefs(result)
    assert any(h.startswith("/api/v1/auth/login?next=") for h in hrefs)


def test_sign_in_returns_to_the_current_page(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, _StubResponse(401, {"detail": "expired"}))
    result = account_bar.render_account_bar("/app/catalog/team/review")

    hrefs = _hrefs(result)
    assert hrefs == ["/api/v1/auth/login?next=%2Fapp%2Fcatalog%2Fteam%2Freview"]


def test_role_less_session_renders_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, _StubResponse(403, {"detail": "forbidden"}))
    assert account_bar.render_account_bar("/app/graph") is None


def test_transport_failure_renders_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    import requests

    _install(monkeypatch, requests.exceptions.ConnectionError("refused"))
    assert account_bar.render_account_bar("/app/graph") is None


def test_live_session_shows_username_and_sign_out(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install(monkeypatch, _StubResponse(200, {"username": "dev-user"}))
    result = account_bar.render_account_bar("/app/graph")

    texts = _texts(result)
    assert "dev-user" in texts
    assert "Sign out" in texts
    assert "Sign in" not in texts

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
from dash import html, no_update  # noqa: F401 - documents the callback's vocabulary

from tests.auth_helpers import realm_username
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


def _nodes(children: Any) -> list[Any]:
    """Flatten a Dash component tree to its component nodes."""
    found: list[Any] = []
    stack = [children]
    while stack:
        node = stack.pop()
        if isinstance(node, (list, tuple)):
            stack.extend(node)
        elif hasattr(node, "children"):
            found.append(node)
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
    _install(monkeypatch, _StubResponse(200, {"username": realm_username("user")}))
    result = account_bar.render_account_bar("/app/graph")

    texts = _texts(result)
    assert realm_username("user") in texts
    assert "Sign out" in texts
    assert "Sign in" not in texts


def test_full_name_rendered_when_present(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(
        monkeypatch,
        _StubResponse(
            200,
            {"username": realm_username("user"), "full_name": "App User", "roles": ["user"]},
        ),
    )
    result = account_bar.render_account_bar("/app/graph")

    texts = _texts(result)
    assert realm_username("user") in texts
    assert "App User" in texts


def test_absent_full_name_renders_no_second_line(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for payload in (
        {"username": realm_username("user"), "roles": ["user"]},
        {"username": realm_username("user"), "full_name": None, "roles": ["user"]},
        {"username": realm_username("user"), "full_name": "", "roles": ["user"]},
    ):
        _install(monkeypatch, _StubResponse(200, payload))
        result = account_bar.render_account_bar("/app/graph")

        texts = _texts(result)
        assert realm_username("user") in texts
        assert "App User" not in texts


def test_logout_form_posts_to_logout_url(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(
        monkeypatch,
        _StubResponse(200, {"username": realm_username("user"), "roles": ["user"]}),
    )
    result = account_bar.render_account_bar("/app/graph")

    forms = [n for n in _nodes(result) if isinstance(n, html.Form)]
    assert forms, "no logout form in the menu"
    form = forms[0]
    assert form.method == "post"
    assert form.action == "/api/v1/auth/logout"
    assert any(
        isinstance(n, html.Button) and n.type == "submit" for n in _nodes(form.children)
    )

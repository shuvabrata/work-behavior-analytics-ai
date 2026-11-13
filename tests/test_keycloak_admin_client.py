"""Unit tests for the Keycloak Admin REST client."""

from __future__ import annotations

from typing import Any

import pytest
import requests

from app.auth import keycloak_admin as k

pytestmark = pytest.mark.unit


class _FakeResponse:
    def __init__(
        self,
        status_code: int,
        *,
        json_body: Any = None,
        text: str = "",
        headers: dict[str, str] | None = None,
    ) -> None:
        self.status_code = status_code
        self._json = json_body
        self.text = text
        self.headers = headers or {}

    def json(self) -> Any:
        if self._json is None:
            raise ValueError("no json")
        return self._json


@pytest.fixture(autouse=True)
def _reset_token() -> None:
    k.invalidate_admin_token()


def _settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(k.settings, "KEYCLOAK_INTERNAL_URL", "http://keycloak:8080/auth/realms/wba")
    monkeypatch.setattr(k.settings, "KEYCLOAK_ADMIN_CLIENT_ID", "admin-api")
    monkeypatch.setattr(k.settings, "KEYCLOAK_ADMIN_CLIENT_SECRET", "s3cret")


def test_admin_base_url_rewrites_realms() -> None:
    assert k.admin_base_url() == "http://keycloak:8080/auth/admin/realms/wba"


def test_admin_base_url_raises_when_substring_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(k.settings, "KEYCLOAK_INTERNAL_URL", "http://keycloak:8080/auth")
    with pytest.raises(k.KeycloakUnavailableError):
        k.admin_base_url()


def test_token_is_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    _settings(monkeypatch)
    calls = {"n": 0}

    def fake_post(url: str, **kwargs: Any) -> _FakeResponse:
        calls["n"] += 1
        return _FakeResponse(200, json_body={"access_token": "tok", "expires_in": 300})

    monkeypatch.setattr(requests, "post", fake_post)

    assert k._admin_token() == "tok"
    assert k._admin_token() == "tok"
    assert calls["n"] == 1


def test_admin_401_becomes_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    _settings(monkeypatch)
    monkeypatch.setattr(
        requests, "post", lambda url, **kw: _FakeResponse(200, json_body={"access_token": "t", "expires_in": 300})
    )
    monkeypatch.setattr(requests, "request", lambda *a, **kw: _FakeResponse(401, text="unauthorized"))

    with pytest.raises(k.KeycloakUnavailableError):
        k.get_user("abc")


def test_admin_401_invalidates_token(monkeypatch: pytest.MonkeyPatch) -> None:
    _settings(monkeypatch)
    posts = {"n": 0}

    def fake_post(url: str, **kwargs: Any) -> _FakeResponse:
        posts["n"] += 1
        return _FakeResponse(200, json_body={"access_token": "t", "expires_in": 300})

    monkeypatch.setattr(requests, "post", fake_post)
    assert k._admin_token() == "t"

    monkeypatch.setattr(requests, "request", lambda *a, **kw: _FakeResponse(401, text="unauthorized"))
    with pytest.raises(k.KeycloakUnavailableError):
        k.get_user("abc")
    assert k._state.access_token is None

    with pytest.raises(k.KeycloakUnavailableError):
        k.get_user("abc")
    assert posts["n"] == 2


def test_admin_403_keeps_token(monkeypatch: pytest.MonkeyPatch) -> None:
    _settings(monkeypatch)
    posts = {"n": 0}

    def fake_post(url: str, **kwargs: Any) -> _FakeResponse:
        posts["n"] += 1
        return _FakeResponse(200, json_body={"access_token": "t", "expires_in": 300})

    monkeypatch.setattr(requests, "post", fake_post)
    assert k._admin_token() == "t"

    monkeypatch.setattr(requests, "request", lambda *a, **kw: _FakeResponse(403, text="forbidden"))
    with pytest.raises(k.KeycloakUnavailableError):
        k.get_user("abc")
    assert k._state.access_token == "t"

    with pytest.raises(k.KeycloakUnavailableError):
        k.get_user("abc")
    assert posts["n"] == 1


def test_status_mapping(monkeypatch: pytest.MonkeyPatch) -> None:
    _settings(monkeypatch)
    monkeypatch.setattr(
        requests, "post", lambda url, **kw: _FakeResponse(200, json_body={"access_token": "t", "expires_in": 300})
    )

    for status, exc in (
        (404, k.KeycloakNotFoundError),
        (409, k.KeycloakConflictError),
        (400, k.KeycloakPolicyError),
    ):
        monkeypatch.setattr(requests, "request", lambda *a, s=status, **kw: _FakeResponse(s, text="body"))
        with pytest.raises(exc):
            k.get_user("abc")


def test_create_user_parses_location(monkeypatch: pytest.MonkeyPatch) -> None:
    _settings(monkeypatch)
    monkeypatch.setattr(
        requests, "post", lambda url, **kw: _FakeResponse(200, json_body={"access_token": "t", "expires_in": 300})
    )
    monkeypatch.setattr(
        requests,
        "request",
        lambda *a, **kw: _FakeResponse(
            201, headers={"Location": "http://keycloak:8080/auth/admin/realms/wba/users/new-id"}
        ),
    )
    assert k.create_user({"username": "x"}) == "new-id"


def test_set_password_body(monkeypatch: pytest.MonkeyPatch) -> None:
    _settings(monkeypatch)
    monkeypatch.setattr(
        requests, "post", lambda url, **kw: _FakeResponse(200, json_body={"access_token": "t", "expires_in": 300})
    )
    captured: dict[str, Any] = {}

    def fake_request(method: str, url: str, **kwargs: Any) -> _FakeResponse:
        captured["method"] = method
        captured["json"] = kwargs.get("json")
        return _FakeResponse(204)

    monkeypatch.setattr(requests, "request", fake_request)
    k.set_password("u1", "hunter2xx", True)

    assert captured["method"] == "PUT"
    assert captured["json"] == {"type": "password", "value": "hunter2xx", "temporary": True}


def test_missing_secret_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    _settings(monkeypatch)
    monkeypatch.setattr(k.settings, "KEYCLOAK_ADMIN_CLIENT_SECRET", "")
    with pytest.raises(k.KeycloakUnavailableError):
        k._admin_token()

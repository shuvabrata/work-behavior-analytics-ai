"""Unit tests for the UI's runtime-snapshot fetch.

The UI's snapshot fetch used to ride a **service** token through
``common.runtime_settings.client.fetch_runtime_snapshot`` — a credential the UI
container cannot obtain, so the request went out unauthenticated. Plan 057 makes
the snapshot route require a credential, at which point that path would fail
*silently*: the helper treats a non-200 as "API unreachable", logs a warning, and
returns bare ``RuntimeConfig()`` defaults, so the UI would quietly stop picking
up runtime-settings edits.

These tests pin the fix in both directions: the call goes through
``ui.api_client`` carrying the bearer, and the shared service-token helper is no
longer called at all. Both assertions are needed — "a header was sent" alone
would still pass if the old path were merely wrapped.
"""

from __future__ import annotations

from typing import Any

import pytest

from common.runtime_settings import RuntimeConfig
from ui import api_client
from ui import runtime_settings as ui_runtime_settings
from ui.api_client import STATUS_NO_RESPONSE, ApiError

pytestmark = pytest.mark.unit


class _StubResponse:
    """Minimal ``requests.Response`` stand-in for the transport seam."""

    def __init__(self, status_code: int, payload: Any = None, text: str = "") -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = text

    @property
    def ok(self) -> bool:
        return self.status_code < 400

    def json(self) -> Any:
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


@pytest.fixture(name="calls")
def _calls(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Install a transport that returns a canned 200 and records the request."""
    recorded: list[dict[str, Any]] = []

    def transport(method: str, url: str, **kwargs: Any) -> _StubResponse:
        recorded.append({"method": method, "url": url, **kwargs})
        return _StubResponse(200, {"HTTP_REQUEST_TIMEOUT": 77, "TIMEZONE": "UTC"})

    monkeypatch.setattr(api_client, "_transport", transport)
    monkeypatch.setattr(api_client, "get_token", lambda: "user-bearer-token")
    return recorded


@pytest.fixture(name="service_token_spy")
def _service_token_spy(monkeypatch: pytest.MonkeyPatch) -> dict[str, int]:
    """Replace the shared helper and count how often it is called."""
    calls = {"count": 0}

    def fake_fetch(*args: Any, **kwargs: Any) -> RuntimeConfig:
        calls["count"] += 1
        return RuntimeConfig()

    monkeypatch.setattr(
        "common.runtime_settings.client.fetch_runtime_snapshot", fake_fetch
    )
    monkeypatch.setattr(
        "common.runtime_settings.fetch_runtime_snapshot", fake_fetch
    )
    return calls


def test_snapshot_goes_through_api_client_with_the_bearer(
    calls: list[dict[str, Any]], service_token_spy: dict[str, int]
) -> None:
    ui_runtime_settings.refresh()

    assert len(calls) == 1
    assert calls[0]["url"] == "http://localhost:8000/api/v1/settings/runtime-snapshot"
    assert calls[0]["headers"] == {"Authorization": "Bearer user-bearer-token"}
    assert service_token_spy["count"] == 0


def test_snapshot_updates_the_cache(
    calls: list[dict[str, Any]], service_token_spy: dict[str, int]
) -> None:
    ui_runtime_settings.refresh()

    assert ui_runtime_settings.runtime_settings.get_int("HTTP_REQUEST_TIMEOUT") == 77


def test_api_error_keeps_current_values_and_does_not_raise(
    monkeypatch: pytest.MonkeyPatch, service_token_spy: dict[str, int]
) -> None:
    ui_runtime_settings.runtime_settings.refresh(RuntimeConfig(HTTP_REQUEST_TIMEOUT=42))

    def transport(method: str, url: str, **kwargs: Any) -> _StubResponse:
        return _StubResponse(401, {"detail": {"error": "unauthenticated"}})

    monkeypatch.setattr(api_client, "_transport", transport)
    monkeypatch.setattr(api_client, "get_token", lambda: "user-bearer-token")

    ui_runtime_settings.refresh()

    assert ui_runtime_settings.runtime_settings.get_int("HTTP_REQUEST_TIMEOUT") == 42


def test_transport_failure_keeps_current_values_and_does_not_raise(
    monkeypatch: pytest.MonkeyPatch, service_token_spy: dict[str, int]
) -> None:
    import requests

    ui_runtime_settings.runtime_settings.refresh(RuntimeConfig(HTTP_REQUEST_TIMEOUT=43))

    def transport(method: str, url: str, **kwargs: Any) -> _StubResponse:
        raise requests.exceptions.ConnectionError("refused")

    monkeypatch.setattr(api_client, "_transport", transport)
    monkeypatch.setattr(api_client, "get_token", lambda: "user-bearer-token")

    ui_runtime_settings.refresh()

    assert ui_runtime_settings.runtime_settings.get_int("HTTP_REQUEST_TIMEOUT") == 43


def test_all_defaults_snapshot_keeps_current_values(
    monkeypatch: pytest.MonkeyPatch, service_token_spy: dict[str, int]
) -> None:
    ui_runtime_settings.runtime_settings.refresh(RuntimeConfig(HTTP_REQUEST_TIMEOUT=88))

    def transport(method: str, url: str, **kwargs: Any) -> _StubResponse:
        return _StubResponse(200, RuntimeConfig().model_dump())

    monkeypatch.setattr(api_client, "_transport", transport)
    monkeypatch.setattr(api_client, "get_token", lambda: "user-bearer-token")

    ui_runtime_settings.refresh()

    assert ui_runtime_settings.runtime_settings.get_int("HTTP_REQUEST_TIMEOUT") == 88


def test_status_no_response_constant_is_used_for_a_down_api() -> None:
    """Guard the constant this module's docstring leans on."""
    assert STATUS_NO_RESPONSE == 0
    assert ApiError(STATUS_NO_RESPONSE).status_code == 0

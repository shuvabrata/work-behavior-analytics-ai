"""Unit tests for the two auth outcomes a page renders.

``handle_api_error`` is the seam a page opts into for the two auth subclasses.
The contract that matters is the *re-raise*: a page must keep its own timeout /
validation / no-data messages for everything else, so this helper only takes over
401 and 403 and hands any other ``ApiError`` back to the caller.
"""

from __future__ import annotations

from typing import Any

import pytest
from dash import no_update

from ui.api_client import ApiError, AuthExpiredError, PermissionDeniedError
from ui.components import permission_errors
from ui.components.permission_errors import handle_api_error

pytestmark = pytest.mark.unit


def _record_redirect(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Record the ``data`` each redirect-store write carries."""
    written: list[str] = []

    def _fake_set_props(_component_id: str, props: dict[str, Any]) -> None:
        written.append(props["data"])

    monkeypatch.setattr(permission_errors, "set_props", _fake_set_props)
    return written


def _alert_text(alert: Any) -> str:
    children = alert.children
    if isinstance(children, str):
        return children
    return " ".join(str(c) for c in children)


def test_403_returns_a_warning_alert() -> None:
    alert = handle_api_error(PermissionDeniedError(403, detail="forbidden"), "save")

    assert alert.color == "warning"
    text = _alert_text(alert).lower()
    assert "permission" in text
    assert "administrator" in text


def test_403_alert_names_the_action() -> None:
    alert = handle_api_error(PermissionDeniedError(403), "delete this connector")
    assert "delete this connector" in _alert_text(alert)


def test_403_alert_is_dismissable() -> None:
    alert = handle_api_error(PermissionDeniedError(403), "save")
    assert alert.dismissable is True


def test_401_schedules_the_redirect_and_returns_no_update(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    written = _record_redirect(monkeypatch)
    result = handle_api_error(AuthExpiredError(401), "save", current_path="/app/graph")

    assert result is no_update
    assert written == ["/api/v1/auth/login?next=%2Fapp%2Fgraph"]


def test_401_without_a_path_defaults_to_the_app_root(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    written = _record_redirect(monkeypatch)
    handle_api_error(AuthExpiredError(401), "save")
    assert written == ["/api/v1/auth/login?next=%2Fapp%2F"]


def test_non_auth_error_re_raises() -> None:
    exc = ApiError(500, detail="boom")
    with pytest.raises(ApiError) as excinfo:
        handle_api_error(exc, "save")
    assert excinfo.value is exc


def test_permission_denied_is_never_treated_as_expired(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A 403 must not log the user out — it is a role refusal, not a dead session."""
    written = _record_redirect(monkeypatch)
    handle_api_error(PermissionDeniedError(403), "save")
    assert written == []

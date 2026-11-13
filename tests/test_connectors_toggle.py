"""Unit tests for the connector item enable/disable toggle.

Tests cover the write-on-render regression fixed in plan 064:

  - ``render_items_list`` performs no API write
  - a render echoing a switch's value back does not write
  - a genuine user toggle still writes exactly once
  - a toggle without a valid store is refused
  - a 403 (``PermissionDeniedError``) shows the alert and reverts the switch
  - any other ``ApiError`` shows the "Failed to update configuration" alert
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from dash import no_update

from ui import api_client
from ui.api_client import STATUS_NO_RESPONSE, ApiError, PermissionDeniedError
from ui.pages.connectors.callbacks import handle_inline_toggle, render_items_list


pytestmark = pytest.mark.unit


def _store(enabled: bool = True) -> dict:
    return {
        "status": "ok",
        "connector_type": "github",
        "items": [
            {"id": "42", "url": "https://github.com/org/repo", "enabled": enabled},
            {"id": "43", "url": "https://github.com/org/other", "enabled": not enabled},
        ],
    }


# ---------------------------------------------------------------------------
# Render performs no write
# ---------------------------------------------------------------------------


class TestRenderPerformsNoWrite:
    """The render path must never reach the API."""

    def test_render_performs_no_write(self) -> None:
        """``render_items_list`` builds cards and calls nothing on ``api_client``.

        Note: ``render_items_list`` does not write in either the fixed or the
        broken code — it is the *toggle* callback that writes. This test pins
        the render's contract; the discriminating regression test is
        ``test_render_echo_performs_no_write`` below.
        """
        with patch("ui.pages.connectors.callbacks.api_client") as mock_client:
            cards = render_items_list(_store())

        assert len(cards) == 2
        mock_client.patch.assert_not_called()
        mock_client.post.assert_not_called()
        mock_client.put.assert_not_called()
        mock_client.delete.assert_not_called()

    def test_render_echo_performs_no_write(self) -> None:
        """A render-driven callback carrying the store's own value must not write.

        This is the plan-064 regression: Dash re-instantiates MATCH-id switches
        on render and fires ``handle_inline_toggle`` with the value the render
        just wrote. The guard must recognise the echo and suppress the PATCH.
        """
        store = _store(enabled=True)

        with patch("ui.pages.connectors.callbacks.callback_context") as mock_ctx, patch.object(
            api_client, "patch"
        ) as mock_patch:
            mock_ctx.triggered_id = {
                "type": "config-enabled-switch",
                "connector_type": "github",
                "config_id": "42",
            }
            result = handle_inline_toggle(True, store)

        assert result == (no_update, no_update, no_update, no_update)
        mock_patch.assert_not_called()


# ---------------------------------------------------------------------------
# A genuine toggle still writes
# ---------------------------------------------------------------------------


class TestGenuineToggleWrites:
    """A real user click must still reach the API."""

    def test_genuine_toggle_writes(self) -> None:
        """A value the store does not hold is a user action → one PATCH."""
        store = _store(enabled=True)

        with patch("ui.pages.connectors.callbacks.callback_context") as mock_ctx, patch.object(
            api_client, "patch"
        ) as mock_patch:
            mock_ctx.triggered_id = {
                "type": "config-enabled-switch",
                "connector_type": "github",
                "config_id": "42",
            }
            _alert, value, label, updated_store = handle_inline_toggle(False, store)

        mock_patch.assert_called_once_with(
            "/api/v1/connectors/github/configs/42/status",
            json={"enabled": False},
        )
        assert value is no_update
        assert label == "Disabled"
        assert updated_store["items"][0]["enabled"] is False
        assert updated_store["items"][1]["enabled"] is False


# ---------------------------------------------------------------------------
# A toggle with no store is refused
# ---------------------------------------------------------------------------


class TestToggleWithoutStoreRefused:
    """Without a valid store the toggle cannot be validated, so it is refused."""

    def test_toggle_without_store_is_refused(self) -> None:
        """``store=None`` → value reverted, label reverted, no API call."""
        with patch("ui.pages.connectors.callbacks.callback_context") as mock_ctx, patch.object(
            api_client, "patch"
        ) as mock_patch:
            mock_ctx.triggered_id = {
                "type": "config-enabled-switch",
                "connector_type": "github",
                "config_id": "42",
            }
            alert, value, label, updated_store = handle_inline_toggle(False, None)

        mock_patch.assert_not_called()
        assert alert is no_update
        assert value is True
        assert label == "Active"
        assert updated_store is no_update


# ---------------------------------------------------------------------------
# A 403 produces the alert
# ---------------------------------------------------------------------------


class TestToggleFailureProducesAlert:
    """Failure paths show an alert and revert the switch."""

    def test_403_produces_alert(self) -> None:
        """``PermissionDeniedError`` → permission alert shown, switch reverted."""
        store = _store(enabled=True)

        with patch("ui.pages.connectors.callbacks.callback_context") as mock_ctx, patch.object(
            api_client,
            "patch",
            side_effect=PermissionDeniedError(
                403, message="Role 'admin' is required."
            ),
        ):
            mock_ctx.triggered_id = {
                "type": "config-enabled-switch",
                "connector_type": "github",
                "config_id": "42",
            }
            alert, value, label, updated_store = handle_inline_toggle(False, store)

        assert alert is not no_update
        assert "permission" in str(alert).lower()
        assert value is True
        assert label == "Active"
        assert updated_store is no_update

    def test_api_error_produces_alert(self) -> None:
        """A non-auth ``ApiError`` → "Failed to update configuration" danger alert."""
        store = _store(enabled=True)

        with patch("ui.pages.connectors.callbacks.callback_context") as mock_ctx, patch.object(
            api_client,
            "patch",
            side_effect=ApiError(STATUS_NO_RESPONSE, message="Connection refused"),
        ):
            mock_ctx.triggered_id = {
                "type": "config-enabled-switch",
                "connector_type": "github",
                "config_id": "42",
            }
            alert, value, label, updated_store = handle_inline_toggle(False, store)

        assert alert is not no_update
        assert "Failed to update configuration" in str(alert)
        assert "Connection refused" in str(alert)
        assert value is True
        assert label == "Active"
        assert updated_store is no_update

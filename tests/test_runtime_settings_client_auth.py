"""Unit tests for the service-token integration in the runtime-settings client."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import requests

import common.auth as auth_mod
from common.auth import ServiceTokenError
from common.runtime_settings import RuntimeConfig
from common.runtime_settings import client as client_mod
from common.runtime_settings.client import fetch_runtime_snapshot

pytestmark = [pytest.mark.unit]

_VALID_PAYLOAD = {"HTTP_REQUEST_TIMEOUT": 42, "TIMEZONE": "UTC"}


class TestFetchRuntimeSnapshotWiring:
    def test_module_binds_the_shared_auth_functions(self) -> None:
        assert client_mod.get_service_token is auth_mod.get_service_token
        assert client_mod.ServiceTokenError is auth_mod.ServiceTokenError


class TestFetchRuntimeSnapshotAuth:
    def test_request_carries_bearer_token(self) -> None:
        with patch("common.runtime_settings.client.requests.get") as mock_get:
            mock_get.return_value = MagicMock(
                status_code=200, json=lambda: _VALID_PAYLOAD
            )
            with patch("common.runtime_settings.client.get_service_token", return_value="tok-abc"):
                config = fetch_runtime_snapshot("http://app:8000")

        assert isinstance(config, RuntimeConfig)
        assert config.HTTP_REQUEST_TIMEOUT == 42
        assert mock_get.call_args[1]["headers"] == {"Authorization": "Bearer tok-abc"}

    def test_token_failure_still_sends_request_without_header(self, caplog: pytest.LogCaptureFixture) -> None:
        with patch("common.runtime_settings.client.get_service_token", side_effect=ServiceTokenError("nope")):
            with patch("common.runtime_settings.client.requests.get") as mock_get:
                mock_get.return_value = MagicMock(
                    status_code=200, json=lambda: _VALID_PAYLOAD
                )
                with caplog.at_level("WARNING"):
                    config = fetch_runtime_snapshot("http://app:8000")

        assert isinstance(config, RuntimeConfig)
        assert config.HTTP_REQUEST_TIMEOUT == 42
        assert mock_get.call_count == 1
        assert "headers" not in mock_get.call_args[1]
        assert "wba-internal" in caplog.text

    def test_unreachable_api_still_degrades(self) -> None:
        with patch("common.runtime_settings.client.get_service_token", return_value="tok-abc"):
            with patch("common.runtime_settings.client.requests.get") as mock_get:
                mock_get.side_effect = requests.exceptions.ConnectionError("refused")
                config = fetch_runtime_snapshot("http://app:8000")

        assert isinstance(config, RuntimeConfig)
        assert config.HTTP_REQUEST_TIMEOUT == 60

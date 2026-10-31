"""Unit tests for the authenticated-request helper in ``daemon_common``."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

import connectors.producers.daemon_common as daemon_mod
import common.auth as auth_mod
from common.auth import ServiceTokenError

pytestmark = [pytest.mark.unit]


class TestAuthWiring:
    def test_module_binds_the_shared_auth_functions(self) -> None:
        assert daemon_mod.get_service_token is auth_mod.get_service_token
        assert daemon_mod.invalidate_service_token is auth_mod.invalidate_service_token
        assert daemon_mod.ServiceTokenError is auth_mod.ServiceTokenError


class TestAuthHeaders:
    def test_returns_bearer_header(self) -> None:
        with patch("connectors.producers.daemon_common.get_service_token", return_value="tok-1"):
            headers = daemon_mod._auth_headers()

        assert headers == {"Authorization": "Bearer tok-1"}

    def test_returns_empty_and_warns_on_failure(self, caplog: pytest.LogCaptureFixture) -> None:
        with patch("connectors.producers.daemon_common.get_service_token", side_effect=ServiceTokenError("nope")):
            with caplog.at_level("WARNING"):
                headers = daemon_mod._auth_headers()

        assert headers == {}
        assert "wba-internal" in caplog.text


class TestApiRequest:
    def _client(self, responses: list[MagicMock]) -> tuple[MagicMock, MagicMock]:
        mock_instance = MagicMock()
        mock_instance.get.side_effect = responses
        mock_client = MagicMock()
        mock_client.return_value.__enter__.return_value = mock_instance
        return mock_client, mock_instance

    def test_401_retries_once_with_fresh_token(self) -> None:
        first = MagicMock(status_code=401)
        second = MagicMock(status_code=200)
        mock_client, mock_instance = self._client([first, second])

        with patch("httpx.Client", mock_client):
            with patch("connectors.producers.daemon_common.get_service_token", return_value="tok-1"):
                with patch("connectors.producers.daemon_common.invalidate_service_token") as mock_invalidate:
                    resp = daemon_mod._api_request("GET", "http://api/x")

        assert resp is second
        assert mock_instance.get.call_count == 2
        mock_invalidate.assert_called_once()

    def test_200_does_not_retry_or_invalidate(self) -> None:
        ok = MagicMock(status_code=200)
        mock_client, mock_instance = self._client([ok])

        with patch("httpx.Client", mock_client):
            with patch("connectors.producers.daemon_common.get_service_token", return_value="tok-1"):
                with patch("connectors.producers.daemon_common.invalidate_service_token") as mock_invalidate:
                    resp = daemon_mod._api_request("GET", "http://api/x")

        assert resp is ok
        assert mock_instance.get.call_count == 1
        mock_invalidate.assert_not_called()

    def test_second_401_is_returned_not_retried_again(self) -> None:
        first = MagicMock(status_code=401)
        second = MagicMock(status_code=401)
        mock_client, mock_instance = self._client([first, second])

        with patch("httpx.Client", mock_client):
            with patch("connectors.producers.daemon_common.get_service_token", return_value="tok-1"):
                with patch("connectors.producers.daemon_common.invalidate_service_token"):
                    resp = daemon_mod._api_request("GET", "http://api/x")

        assert resp is second
        assert mock_instance.get.call_count == 2

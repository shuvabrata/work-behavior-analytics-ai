"""Unit tests for the cached client-credentials service-token helper."""

from __future__ import annotations

import threading
from unittest.mock import MagicMock, patch

import pytest

import common.auth.service_token as token_mod
from common.auth.service_token import (
    ServiceTokenError,
    get_service_token,
    invalidate_service_token,
)

pytestmark = [pytest.mark.unit]

_CLIENT_ID = "wba-internal"
_SECRET_VALUE = "super-secret-value"


@pytest.fixture(autouse=True)
def _reset_token_state(monkeypatch: pytest.MonkeyPatch) -> object:
    """Clear the process-wide cache before and after every test.

    ``get_service_token`` holds a module-level cache, so a token fetched here
    would otherwise leak into other test modules in the same process.
    """
    monkeypatch.setenv("KEYCLOAK_SERVICE_CLIENT_ID", _CLIENT_ID)
    monkeypatch.setenv("KEYCLOAK_SERVICE_CLIENT_SECRET", _SECRET_VALUE)
    monkeypatch.setenv("KEYCLOAK_INTERNAL_URL", "http://keycloak:8080/auth/realms/wba")
    invalidate_service_token()
    yield
    invalidate_service_token()


def _ok_response(access_token: str = "tok-1", expires_in: int = 900) -> MagicMock:
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {"access_token": access_token, "expires_in": expires_in}
    return resp


class TestGetServiceToken:
    def test_first_call_fetches_and_second_reuses_cache(self) -> None:
        with patch.object(token_mod.requests, "post") as mock_post:
            mock_post.return_value = _ok_response()

            first = get_service_token()
            second = get_service_token()

        assert first == "tok-1"
        assert second == "tok-1"
        assert mock_post.call_count == 1

    def test_expiring_token_is_refreshed(self) -> None:
        with patch.object(token_mod.requests, "post") as mock_post:
            mock_post.side_effect = [
                _ok_response("tok-expiring", expires_in=30),
                _ok_response("tok-fresh", expires_in=900),
            ]

            first = get_service_token()
            second = get_service_token()

        assert first == "tok-expiring"
        assert second == "tok-fresh"
        assert mock_post.call_count == 2

    def test_invalidate_forces_refetch(self) -> None:
        with patch.object(token_mod.requests, "post") as mock_post:
            mock_post.return_value = _ok_response()

            get_service_token()
            invalidate_service_token()
            get_service_token()

        assert mock_post.call_count == 2

    def test_non_200_raises_and_never_logs_body_or_secret(self, caplog: pytest.LogCaptureFixture) -> None:
        body_text = "leaked-body-from-keycloak"
        with patch.object(token_mod.requests, "post") as mock_post:
            resp = MagicMock()
            resp.status_code = 401
            resp.text = body_text
            mock_post.return_value = resp

            with caplog.at_level("WARNING"):
                with pytest.raises(ServiceTokenError):
                    get_service_token()

        assert body_text not in caplog.text
        assert _SECRET_VALUE not in caplog.text

    def test_non_json_body_raises(self) -> None:
        with patch.object(token_mod.requests, "post") as mock_post:
            resp = MagicMock()
            resp.status_code = 200
            resp.json.side_effect = ValueError("not json")
            mock_post.return_value = resp

            with pytest.raises(ServiceTokenError):
                get_service_token()

    def test_missing_access_token_raises(self) -> None:
        with patch.object(token_mod.requests, "post") as mock_post:
            resp = MagicMock()
            resp.status_code = 200
            resp.json.return_value = {"expires_in": 900}
            mock_post.return_value = resp

            with pytest.raises(ServiceTokenError):
                get_service_token()

    def test_empty_secret_raises_without_request(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("KEYCLOAK_SERVICE_CLIENT_SECRET", "")
        with patch.object(token_mod.requests, "post") as mock_post:
            with pytest.raises(ServiceTokenError):
                get_service_token()

        mock_post.assert_not_called()

    def test_failure_is_backed_off(self) -> None:
        with patch.object(token_mod.requests, "post") as mock_post:
            resp = MagicMock()
            resp.status_code = 503
            mock_post.return_value = resp

            with pytest.raises(ServiceTokenError):
                get_service_token()
            with pytest.raises(ServiceTokenError):
                get_service_token()

        assert mock_post.call_count == 1

    def test_invalidate_clears_backoff(self) -> None:
        with patch.object(token_mod.requests, "post") as mock_post:
            resp = MagicMock()
            resp.status_code = 503
            mock_post.return_value = resp

            with pytest.raises(ServiceTokenError):
                get_service_token()
            invalidate_service_token()
            with pytest.raises(ServiceTokenError):
                get_service_token()

        assert mock_post.call_count == 2

    def test_concurrent_calls_issue_one_request(self) -> None:
        call_log: list[str] = []

        def _slow_post(*_args: object, **_kwargs: object) -> MagicMock:
            call_log.append("post")
            return _ok_response()

        with patch.object(token_mod.requests, "post", side_effect=_slow_post):
            barrier = threading.Barrier(2)

            def _worker() -> None:
                barrier.wait()
                get_service_token()

            threads = [threading.Thread(target=_worker) for _ in range(2)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()

        assert len(call_log) == 1

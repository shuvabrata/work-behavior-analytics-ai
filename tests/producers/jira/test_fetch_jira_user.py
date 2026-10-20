"""Unit tests for ``fetch_jira.fetch_user`` (single-user lookup by accountId)."""

from unittest.mock import Mock, patch

import pytest
import requests

from connectors.producers.github.retry_with_backoff import WbaRetryTimeoutError
from connectors.producers.jira.fetch_jira import fetch_user

pytestmark = pytest.mark.unit


def test_returns_user_dict_and_calls_expected_endpoint() -> None:
    jira = Mock()
    jira.get.return_value = {"accountId": "acc1", "displayName": "Alice", "emailAddress": "a@example.com"}

    result = fetch_user(jira, "acc1")

    assert result["displayName"] == "Alice"
    assert result["emailAddress"] == "a@example.com"
    jira.get.assert_called_once_with("rest/api/3/user", params={"accountId": "acc1"})


def test_non_dict_response_returns_empty() -> None:
    jira = Mock()
    jira.get.return_value = ["unexpected"]
    assert fetch_user(jira, "acc1") == {}


def test_http_error_returns_empty_without_raising() -> None:
    jira = Mock()
    response = requests.Response()
    response.status_code = 404
    jira.get.side_effect = requests.HTTPError("404 Not Found", response=response)

    assert fetch_user(jira, "acc1") == {}


def test_retry_timeout_is_reraised() -> None:
    jira = Mock()
    with patch(
        "connectors.producers.jira.fetch_jira.retry_with_backoff",
        side_effect=WbaRetryTimeoutError(60, OSError()),
    ):
        with pytest.raises(WbaRetryTimeoutError):
            fetch_user(jira, "acc1")


def test_failure_log_does_not_contain_email(caplog: pytest.LogCaptureFixture) -> None:
    """The warning names the account id only; no emailAddress value is logged."""
    jira = Mock()
    jira.get.side_effect = RuntimeError("boom")

    with caplog.at_level("INFO"):
        assert fetch_user(jira, "acc1") == {}

    assert "acc1" in caplog.text
    assert "@" not in caplog.text

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import pytest
import requests

from connectors.producers.confluence.confluence_config import load_config_from_server
from connectors.producers.confluence.main import (
    _get_test_item_id,
    build_content_signal,
    build_person_signal,
    build_space_signal,
    process_account,
)


pytestmark = pytest.mark.unit


def test_load_config_from_server_success(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("API_SERVER", "http://mock-server:8000")

    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.json.return_value = [
        {
            "id": 7,
            "url": "https://test.atlassian.net",
            "email": "test@example.com",
            "api_token": "token123",
            "include_spaces": ["ENG"],
            "exclude_spaces": ["HR"],
            "enabled": True,
        }
    ]

    with patch(
        "connectors.producers.confluence.confluence_config.requests.get",
        return_value=mock_response,
    ) as mock_get:
        config = load_config_from_server()

    assert config == {
        "account": [
            {
                "id": 7,
                "enabled": True,
                "url": "https://test.atlassian.net",
                "email": "test@example.com",
                "api_token": "token123",
                "include_spaces": ["ENG"],
                "exclude_spaces": ["HR"],
            }
        ]
    }
    mock_get.assert_called_once_with(
        "http://mock-server:8000/api/v1/connectors/confluence/configs",
        params={"include_secrets": "true"},
        headers={},
        timeout=10,
    )


def test_load_config_from_server_http_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("API_SERVER", "http://mock-server:8000")
    with patch("connectors.producers.confluence.confluence_config.requests.get") as mock_get:
        mock_get.side_effect = requests.exceptions.HTTPError("404 Not Found")
        with pytest.raises(requests.exceptions.HTTPError):
            load_config_from_server()


def test_build_space_signal() -> None:
    signal = build_space_signal(
        {
            "key": "eng",
            "name": "Engineering",
            "type": "global",
            "_links": {"webui": "/wiki/spaces/ENG"},
        },
        "https://example.atlassian.net",
    )
    assert signal is not None
    assert signal.source == "confluence"
    assert signal.id == "ENG"
    assert signal.attributes.entity_type == "Space"  # type: ignore[union-attr]


def test_build_person_signal() -> None:
    signal = build_person_signal(
        {"displayName": "Alice Dev", "email": "alice@example.com"},
        "acc123",
        "https://example.atlassian.net",
    )
    assert signal is not None
    assert signal.source == "confluence"
    assert signal.id == "acc123"
    assert signal.attributes.full_name == "Alice Dev"  # type: ignore[union-attr]
    assert signal.attributes.email == "alice@example.com"  # type: ignore[union-attr]


def test_build_content_signal() -> None:
    signal = build_content_signal(
        {
            "id": "2001",
            "type": "page",
            "title": "Design Notes",
            "status": "current",
            "history": {"createdDate": "2026-05-01T10:00:00Z"},
            "version": {"number": 3, "when": "2026-05-02T09:30:00Z"},
            "_links": {"webui": "/wiki/spaces/ENG/pages/2001/Design+Notes"},
        },
        "https://example.atlassian.net",
        [],
    )
    assert signal is not None
    assert signal.id == "2001"
    assert signal.attributes.entity_type == "Page"  # type: ignore[union-attr]
    assert signal.attributes.title == "Design Notes"  # type: ignore[union-attr]


@pytest.mark.asyncio
async def test_process_account_publishes_space_content_and_person_signals(monkeypatch: pytest.MonkeyPatch) -> None:
    from connectors.producers.confluence import main as confluence_main

    publisher = Mock()
    publisher.publish = AsyncMock()
    confluence = Mock()

    monkeypatch.setattr(confluence_main, "get_sync_cursor", AsyncMock(return_value=None))
    monkeypatch.setattr(confluence_main, "set_sync_cursor", AsyncMock())
    monkeypatch.setattr(
        confluence_main,
        "get_spaces",
        AsyncMock(
            return_value=[
                {
                    "key": "ENG",
                    "name": "Engineering",
                    "type": "global",
                    "_links": {"webui": "/wiki/spaces/ENG"},
                }
            ]
        ),
    )
    monkeypatch.setattr(
        confluence_main,
        "get_space_pages",
        AsyncMock(
            return_value=[
                {
                    "id": "2001",
                    "type": "page",
                    "title": "Design Notes",
                    "status": "current",
                    "space": {"key": "ENG"},
                    "history": {
                        "createdDate": "2026-05-01T10:00:00Z",
                        "createdBy": {"accountId": "acc123"},
                    },
                    "version": {
                        "number": 3,
                        "when": "2026-05-02T09:30:00Z",
                        "by": {"accountId": "acc123"},
                    },
                    "_links": {"webui": "/wiki/spaces/ENG/pages/2001/Design+Notes"},
                }
            ]
        ),
    )
    monkeypatch.setattr(confluence_main, "fetch_page_body", Mock(return_value="<p>Hello</p>"))
    monkeypatch.setattr(
        confluence_main,
        "get_comments",
        AsyncMock(
            return_value=[
                {
                    "id": "c1",
                    "body": {"storage": {"value": "<p>@acc123</p>"}},
                    "history": {"createdBy": {"accountId": "acc123"}},
                    "version": {"when": "2026-05-02T11:00:00Z"},
                }
            ]
        ),
    )
    monkeypatch.setattr(
        confluence_main,
        "get_likes",
        AsyncMock(
            return_value=[
                {
                    "accountId": "acc999",
                }
            ]
        ),
    )
    monkeypatch.setattr(
        confluence_main,
        "get_user_details_async",
        AsyncMock(
            return_value={
                "displayName": "Alice Dev",
                "email": "alice@example.com",
                "publicName": "Alice Dev",
            }
        ),
    )

    published = await process_account(
        publisher,
        confluence,
        {
            "id": 7,
            "url": "https://example.atlassian.net",
            "email": "test@example.com",
            "api_token": "token123",
            "include_spaces": [],
            "exclude_spaces": [],
            "enabled": True,
        },
    )

    assert published == 4
    assert publisher.publish.await_count == 4
    assert confluence_main.set_sync_cursor.await_count == 1

    content_signal = publisher.publish.await_args_list[1].args[0]
    relationship_types = {rel.type for rel in content_signal.relationships}
    assert "REACTED_TO" in relationship_types


def _http_error(status: int) -> requests.exceptions.HTTPError:
    response = requests.Response()
    response.status_code = status
    return requests.exceptions.HTTPError(f"HTTP {status}", response=response)


async def _run_account_with_page_error(
    monkeypatch: pytest.MonkeyPatch, error: Exception
) -> tuple[Mock, int]:
    from connectors.producers.confluence import main as confluence_main

    publisher = Mock()
    publisher.publish = AsyncMock()
    monkeypatch.setattr(confluence_main, "get_sync_cursor", AsyncMock(return_value=None))
    monkeypatch.setattr(confluence_main, "set_sync_cursor", AsyncMock())
    monkeypatch.setattr(
        confluence_main,
        "get_spaces",
        AsyncMock(return_value=[{"key": "~BAD", "name": "Gone", "type": "personal"}]),
    )
    monkeypatch.setattr(confluence_main, "get_space_pages", AsyncMock(side_effect=error))
    monkeypatch.setattr(confluence_main, "get_user_details_async", AsyncMock(return_value={}))
    published = await confluence_main.process_account(
        publisher,
        Mock(),
        {"id": 7, "url": "https://example.atlassian.net", "email": "t@example.com",
         "api_token": "x", "include_spaces": [], "exclude_spaces": [], "enabled": True},
    )
    return publisher, published


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [403, 404, 500])
async def test_process_account_skips_inaccessible_space(
    monkeypatch: pytest.MonkeyPatch, status: int
) -> None:
    """Any HTTP failure on one space skips it; the scan still completes."""
    from connectors.producers.confluence import main as confluence_main

    _, published = await _run_account_with_page_error(monkeypatch, _http_error(status))

    assert published == 1  # only the Space signal
    assert confluence_main.set_sync_cursor.await_count == 1


@pytest.mark.asyncio
async def test_process_account_propagates_retry_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    """Retry-budget exhaustion is not skipped, so the cursor is not advanced."""
    from connectors.producers.github.retry_with_backoff import WbaRetryTimeoutError

    with pytest.raises(WbaRetryTimeoutError):
        await _run_account_with_page_error(monkeypatch, WbaRetryTimeoutError(60, OSError("down")))


@pytest.mark.asyncio
async def test_process_account_reports_skipped_space_in_aggregate_warning(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """A skipped space is named in an aggregate WARNING (not just the per-space one)."""
    with caplog.at_level(logging.WARNING):
        _, published = await _run_account_with_page_error(monkeypatch, _http_error(500))

    assert published == 1  # only the Space signal
    assert "Content fetch failed for 1 of 1 space(s)" in caplog.text
    assert "~BAD (HTTP 500)" in caplog.text


@pytest.mark.asyncio
async def test_process_account_summary_reports_skipped_space_count(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """The account summary line carries the skipped-space count."""
    with caplog.at_level(logging.INFO):
        await _run_account_with_page_error(monkeypatch, _http_error(500))

    assert "SpacesSkipped=1" in caplog.text


@pytest.mark.asyncio
async def test_process_account_clean_scan_reports_no_skip(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """A scan with no failing space emits neither the warning nor a non-zero count."""
    from connectors.producers.confluence import main as confluence_main

    publisher = Mock()
    publisher.publish = AsyncMock()
    monkeypatch.setattr(confluence_main, "get_sync_cursor", AsyncMock(return_value=None))
    monkeypatch.setattr(confluence_main, "set_sync_cursor", AsyncMock())
    monkeypatch.setattr(
        confluence_main,
        "get_spaces",
        AsyncMock(
            return_value=[
                {
                    "key": "ENG",
                    "name": "Engineering",
                    "type": "global",
                    "_links": {"webui": "/wiki/spaces/ENG"},
                }
            ]
        ),
    )
    monkeypatch.setattr(confluence_main, "get_space_pages", AsyncMock(return_value=[]))
    monkeypatch.setattr(confluence_main, "get_user_details_async", AsyncMock(return_value={}))

    with caplog.at_level(logging.INFO):
        published = await confluence_main.process_account(
            publisher,
            Mock(),
            {"id": 7, "url": "https://example.atlassian.net", "email": "t@example.com",
             "api_token": "x", "include_spaces": [], "exclude_spaces": [], "enabled": True},
        )

    assert published == 1  # only the Space signal
    assert "Content fetch failed" not in caplog.text
    assert "SpacesSkipped=0" in caplog.text


@pytest.mark.asyncio
async def test_process_account_counts_only_the_failed_space(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """With one good and one failing space, only the failing one is reported."""

    def _pages_for(confluence: Mock, space_key: str, since_date: datetime) -> list[dict[str, object]]:
        if space_key.upper() == "~BAD":
            raise _http_error(403)
        return []

    from connectors.producers.confluence import main as confluence_main

    publisher = Mock()
    publisher.publish = AsyncMock()
    monkeypatch.setattr(confluence_main, "get_sync_cursor", AsyncMock(return_value=None))
    monkeypatch.setattr(confluence_main, "set_sync_cursor", AsyncMock())
    monkeypatch.setattr(
        confluence_main,
        "get_spaces",
        AsyncMock(
            return_value=[
                {"key": "GOOD", "name": "Good", "type": "global"},
                {"key": "~BAD", "name": "Gone", "type": "personal"},
            ]
        ),
    )
    monkeypatch.setattr(confluence_main, "get_space_pages", AsyncMock(side_effect=_pages_for))
    monkeypatch.setattr(confluence_main, "get_user_details_async", AsyncMock(return_value={}))

    with caplog.at_level(logging.INFO):
        published = await confluence_main.process_account(
            publisher,
            Mock(),
            {"id": 7, "url": "https://example.atlassian.net", "email": "t@example.com",
             "api_token": "x", "include_spaces": [], "exclude_spaces": [], "enabled": True},
        )

    assert published == 2  # two Space signals
    assert "Content fetch failed for 1 of 2 space(s)" in caplog.text
    assert "~BAD (HTTP 403)" in caplog.text
    assert "GOOD (HTTP" not in caplog.text
    assert "SpacesSkipped=1" in caplog.text
    assert confluence_main.set_sync_cursor.await_count == 1


# ═══════════════════════════════════════════════════════════════════════════
#  test_connection — connectivity check
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
class TestConfluenceTestConnection:
    """Tests for ``test_connection()`` in ``confluence.main``."""

    @patch.dict(os.environ, {"TEST_ITEM_ID": ""}, clear=True)
    @pytest.mark.asyncio
    async def test_confluence_test_connection_success(self) -> None:
        """Valid credentials → returns (True, "Authenticated as ...")."""
        mock_confluence = Mock()

        with (
            patch(
                "connectors.producers.confluence.main.load_config_from_file",
            ) as mock_load,
            patch(
                "connectors.producers.confluence.main.create_confluence_connection",
                return_value=mock_confluence,
            ),
        ):
            mock_load.return_value = {
                "account": [
                    {
                        "url": "https://test.atlassian.net",
                        "email": "a@b.com",
                        "api_token": "tok",
                        "enabled": True,
                    },
                ]
            }
            from connectors.producers.confluence.main import test_connection
            success, message = await test_connection()

        assert success is True
        assert "Authenticated as a@b.com" in message

    @patch.dict(os.environ, {"TEST_ITEM_ID": ""}, clear=True)
    @pytest.mark.asyncio
    async def test_confluence_test_connection_failure(self) -> None:
        """Invalid credentials → returns (False, "Confluence auth failed ...")."""
        with (
            patch(
                "connectors.producers.confluence.main.load_config_from_file",
            ) as mock_load,
            patch(
                "connectors.producers.confluence.main.create_confluence_connection",
            ) as mock_create,
        ):
            mock_load.return_value = {
                "account": [
                    {
                        "url": "https://test.atlassian.net",
                        "email": "a@b.com",
                        "api_token": "bad_tok",
                        "enabled": True,
                    },
                ]
            }
            mock_create.side_effect = Exception("Invalid credentials")
            from connectors.producers.confluence.main import test_connection
            success, message = await test_connection()

        assert success is False
        assert "Confluence auth failed" in message

    @patch.dict(os.environ, {"TEST_ITEM_ID": "7"}, clear=True)
    @pytest.mark.asyncio
    async def test_confluence_test_connection_with_item_id(self) -> None:
        """Filters to specific item_id, tests only that one."""
        mock_confluence = Mock()

        with (
            patch(
                "connectors.producers.confluence.main.load_config_from_file",
            ) as mock_load,
            patch(
                "connectors.producers.confluence.main.create_confluence_connection",
                return_value=mock_confluence,
            ),
        ):
            mock_load.return_value = {
                "account": [
                    {
                        "id": 7,
                        "url": "https://test.atlassian.net",
                        "email": "a@b.com",
                        "api_token": "tok",
                        "enabled": True,
                    },
                ]
            }
            from connectors.producers.confluence.main import test_connection
            success, message = await test_connection()

        assert success is True
        assert "Authenticated as a@b.com" in message

    @patch.dict(os.environ, {"TEST_ITEM_ID": "999"}, clear=True)
    @pytest.mark.asyncio
    async def test_confluence_test_connection_item_id_not_found(self) -> None:
        """Unknown item_id → returns (False, "No Confluence account config found ...")."""
        with patch(
            "connectors.producers.confluence.main.load_config_from_file",
        ) as mock_load:
            mock_load.return_value = {
                "account": [
                    {
                        "id": 1,
                        "url": "https://test.atlassian.net",
                        "email": "a@b.com",
                        "api_token": "tok",
                        "enabled": True,
                    },
                ]
            }
            from connectors.producers.confluence.main import test_connection
            success, message = await test_connection()

        assert success is False
        assert "No Confluence account config found with id=999" in message

    @patch.dict(os.environ, {"TEST_ITEM_ID": ""}, clear=True)
    @pytest.mark.asyncio
    async def test_confluence_test_connection_no_enabled_configs(self) -> None:
        """No enabled accounts → returns (False, "No enabled Confluence account configurations to test")."""
        with patch(
            "connectors.producers.confluence.main.load_config_from_file",
        ) as mock_load:
            mock_load.return_value = {"account": []}
            from connectors.producers.confluence.main import test_connection
            success, message = await test_connection()

        assert success is False
        assert "No enabled Confluence account configurations" in message


@pytest.mark.unit
class TestConfluenceGetTestItemId:
    """Tests for ``_get_test_item_id()`` in ``confluence.main``."""

    def test_test_item_id_env_var(self) -> None:
        """``TEST_ITEM_ID`` env var parsed correctly."""
        with patch.dict(os.environ, {"TEST_ITEM_ID": "42"}, clear=True):
            assert _get_test_item_id() == 42

    def test_test_item_id_env_var_missing(self) -> None:
        """No env var → returns None."""
        with patch.dict(os.environ, {}, clear=True):
            assert _get_test_item_id() is None

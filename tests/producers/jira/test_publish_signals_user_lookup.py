"""Unit tests for the end-of-scan lookup of mention-only Jira users in ``publish_signals``."""

from __future__ import annotations

import threading
import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from connectors.producers.github.retry_with_backoff import WbaRetryTimeoutError
from connectors.producers.jira.main import publish_signals

pytestmark = pytest.mark.unit

_BASE_URL = "https://jira.example.com"
_MAIN = "connectors.producers.jira.main"


def _mention(account_id: str) -> dict[str, Any]:
    return {"type": "mention", "attrs": {"id": f"accountId:{account_id}"}}


def _issue(mentions: list[str], assignee: dict[str, Any] | None = None, key: str = "PROJ-10") -> dict[str, Any]:
    description = {
        "type": "doc",
        "version": 1,
        "content": [{"type": "paragraph", "content": [_mention(m) for m in mentions]}],
    }
    return {
        "id": "50001",
        "key": key,
        "fields": {
            "summary": "Fix bug",
            "priority": {"name": "High"},
            "status": {"name": "In Progress"},
            "issuetype": {"name": "Story"},
            "created": "2024-03-01T10:00:00",
            "updated": "2024-06-01T10:00:00",
            "assignee": assignee,
            "description": description,
            "issuelinks": [],
        },
    }


async def _run(issue: dict[str, Any], fetch_user_mock: Any) -> tuple[dict[str, int], AsyncMock]:
    publisher = AsyncMock()
    publisher.publish = AsyncMock()
    with (
        patch(f"{_MAIN}.fetch_projects", return_value=[]),
        patch(f"{_MAIN}.fetch_initiatives", return_value=[]),
        patch(f"{_MAIN}.fetch_epics", return_value=[]),
        patch(f"{_MAIN}.fetch_issues", return_value=[issue]),
        patch(f"{_MAIN}.fetch_sprints_by_ids", return_value=[]),
        patch(f"{_MAIN}.fetch_comments", return_value=[]),
        patch(f"{_MAIN}.fetch_user", new=fetch_user_mock),
    ):
        published = await publish_signals(publisher, MagicMock(), _BASE_URL, 90, 100)
    return published, publisher


def _person_signals(publisher: AsyncMock, account_id: str) -> list[Any]:
    return [
        c.args[0]
        for c in publisher.publish.call_args_list
        if c.args[0].entity_type == "Person" and c.args[0].id == account_id
    ]


@pytest.mark.asyncio
async def test_mention_only_user_gets_profile_signal() -> None:
    fetch = MagicMock(return_value={"accountId": "m1", "displayName": "Mia", "emailAddress": "Mia@Example.com"})
    _, publisher = await _run(_issue(["m1"]), fetch)

    sigs = _person_signals(publisher, "m1")
    assert len(sigs) == 2  # stub first, then the profile
    assert sigs[-1].attributes.email == "mia@example.com"
    assert sigs[-1].attributes.full_name == "Mia"


@pytest.mark.asyncio
async def test_user_with_profile_is_not_looked_up() -> None:
    assignee = {"accountId": "a1", "displayName": "Alice", "emailAddress": "alice@example.com"}
    fetch = MagicMock(return_value={})
    await _run(_issue(["a1"], assignee=assignee), fetch)

    fetch.assert_not_called()


@pytest.mark.asyncio
async def test_empty_lookup_leaves_stub_only() -> None:
    fetch = MagicMock(return_value={})
    _, publisher = await _run(_issue(["m1"]), fetch)

    assert len(_person_signals(publisher, "m1")) == 1


@pytest.mark.asyncio
async def test_mismatched_account_id_is_ignored() -> None:
    fetch = MagicMock(return_value={"accountId": "other", "displayName": "Other", "emailAddress": "o@example.com"})
    _, publisher = await _run(_issue(["m1"]), fetch)

    assert len(_person_signals(publisher, "m1")) == 1
    assert _person_signals(publisher, "other") == []


@pytest.mark.asyncio
async def test_name_only_is_published_but_nothing_is_not() -> None:
    fetch = MagicMock(return_value={"accountId": "m1", "displayName": "Mia"})
    _, publisher = await _run(_issue(["m1"]), fetch)
    sigs = _person_signals(publisher, "m1")
    assert len(sigs) == 2
    assert sigs[-1].attributes.full_name == "Mia"

    fetch_none = MagicMock(return_value={"accountId": "m1"})
    _, publisher2 = await _run(_issue(["m1"]), fetch_none)
    assert len(_person_signals(publisher2, "m1")) == 1


@pytest.mark.asyncio
async def test_flag_disabled_skips_lookup() -> None:
    fetch = MagicMock(return_value={"accountId": "m1", "displayName": "Mia"})
    with patch(f"{_MAIN}._JIRA_LOOKUP_STUB_USERS", False):
        await _run(_issue(["m1"]), fetch)

    fetch.assert_not_called()


@pytest.mark.asyncio
async def test_retry_timeout_propagates_after_other_lookups_finish() -> None:
    ids = ["m1", "m2", "m3", "m4"]
    called: list[str] = []
    lock = threading.Lock()

    def fake(_jira: Any, account_id: str) -> dict[str, Any]:
        time.sleep(0.05)
        with lock:
            called.append(account_id)
        if account_id == "m2":
            raise WbaRetryTimeoutError(60, OSError())
        return {"accountId": account_id, "displayName": account_id.upper()}

    with pytest.raises(WbaRetryTimeoutError):
        await _run(_issue(ids), fake)

    assert sorted(called) == ids


@pytest.mark.asyncio
async def test_lookup_concurrency_is_bounded() -> None:
    ids = [f"m{i}" for i in range(10)]
    state = {"current": 0, "max": 0}
    lock = threading.Lock()

    def fake(_jira: Any, account_id: str) -> dict[str, Any]:
        with lock:
            state["current"] += 1
            state["max"] = max(state["max"], state["current"])
        time.sleep(0.05)
        with lock:
            state["current"] -= 1
        return {}

    with patch(f"{_MAIN}._JIRA_USER_LOOKUP_CONCURRENCY", 3):
        await _run(_issue(ids), fake)

    assert 1 < state["max"] <= 3


@pytest.mark.asyncio
async def test_successful_lookup_logs_detail_without_email(caplog: pytest.LogCaptureFixture) -> None:
    fetch = MagicMock(return_value={"accountId": "m1", "displayName": "Mia", "emailAddress": "secret@example.com"})
    with caplog.at_level("INFO"):
        await _run(_issue(["m1"]), fetch)

    assert "Jira user lookup resolved account_id=m1" in caplog.text
    assert "display_name='Mia'" in caplog.text
    assert "email_present=True" in caplog.text
    assert "(1/1)" in caplog.text
    assert "secret@example.com" not in caplog.text


@pytest.mark.asyncio
async def test_empty_lookup_logs_info_line(caplog: pytest.LogCaptureFixture) -> None:
    fetch = MagicMock(return_value={})
    with caplog.at_level("INFO"):
        await _run(_issue(["m1"]), fetch)

    assert "Jira user lookup returned nothing account_id=m1" in caplog.text


@pytest.mark.asyncio
async def test_email_not_logged(caplog: pytest.LogCaptureFixture) -> None:
    fetch = MagicMock(return_value={"accountId": "m1", "displayName": "Mia", "emailAddress": "secret@example.com"})
    with caplog.at_level("INFO"):
        await _run(_issue(["m1"]), fetch)

    assert "secret@example.com" not in caplog.text

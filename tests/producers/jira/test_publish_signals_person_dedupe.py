"""publish_signals Person dedupe: a mention-only stub must not block a later profile."""

from __future__ import annotations

from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from connectors.producers.jira.main import publish_signals

pytestmark = pytest.mark.unit

_BASE_URL = "https://jira.example.com"
_ACC = "712020:abc"


def _mention_doc(account_id: str = _ACC) -> Dict[str, Any]:
    return {
        "type": "doc",
        "version": 1,
        "content": [
            {
                "type": "paragraph",
                "content": [{"type": "mention", "attrs": {"id": account_id}}],
            }
        ],
    }


def _user(account_id: str = _ACC) -> Dict[str, Any]:
    return {"accountId": account_id, "displayName": "Alice Dev", "emailAddress": "alice@example.com"}


def _initiative(eid: str = "20001", **fields: Any) -> Dict[str, Any]:
    base: Dict[str, Any] = {
        "summary": "Initiative",
        "priority": {"name": "High"},
        "status": {"name": "In Progress"},
        "created": "2024-01-01T00:00:00",
        "updated": "2024-06-01T00:00:00",
        "project": {"key": "PROJ"},
        "issuetype": {"name": "Initiative"},
    }
    base.update(fields)
    return {"id": eid, "key": f"PROJ-{eid}", "fields": base}


def _issue(iid: str = "50001", **fields: Any) -> Dict[str, Any]:
    base: Dict[str, Any] = {
        "summary": "Fix bug",
        "priority": {"name": "High"},
        "status": {"name": "In Progress"},
        "issuetype": {"name": "Story"},
        "created": "2024-03-01T10:00:00",
        "updated": "2024-06-01T10:00:00",
        "parent": None,
        "issuelinks": [],
    }
    base.update(fields)
    return {"id": iid, "key": f"PROJ-{iid}", "fields": base}


async def _run(monkeypatch: pytest.MonkeyPatch, initiatives: List[Any], issues: List[Any]) -> List[Any]:
    monkeypatch.setattr("connectors.producers.jira.main._JIRA_FETCH_COMMENTS", True)
    publisher = AsyncMock()
    publisher.publish = AsyncMock()
    with (
        patch("connectors.producers.jira.main.fetch_projects", return_value=[]),
        patch("connectors.producers.jira.main.fetch_initiatives", return_value=initiatives),
        patch("connectors.producers.jira.main.fetch_epics", return_value=[]),
        patch("connectors.producers.jira.main.fetch_issues", return_value=issues),
        patch("connectors.producers.jira.main.fetch_sprints_by_ids", return_value=[]),
        patch("connectors.producers.jira.main.fetch_comments", return_value=[]),
    ):
        await publish_signals(publisher, MagicMock(), _BASE_URL, 90, 100)
    return [
        c.args[0] for c in publisher.publish.await_args_list if c.args[0].entity_type == "Person"
    ]


@pytest.mark.asyncio
async def test_stub_then_profile(monkeypatch: pytest.MonkeyPatch) -> None:
    persons = await _run(
        monkeypatch,
        [_initiative(description=_mention_doc())],
        [_issue(assignee=_user())],
    )
    mine = [p for p in persons if _ACC in p.id]
    assert len(mine) == 2
    assert mine[0].attributes.full_name == _ACC
    assert mine[0].attributes.email is None
    assert mine[1].attributes.full_name == "Alice Dev"
    assert mine[1].attributes.email == "alice@example.com"


@pytest.mark.asyncio
async def test_profile_then_stub(monkeypatch: pytest.MonkeyPatch) -> None:
    persons = await _run(
        monkeypatch,
        [_initiative(assignee=_user(), description=_mention_doc())],
        [],
    )
    assert len(persons) == 1
    assert persons[0].attributes.full_name == "Alice Dev"


@pytest.mark.asyncio
async def test_repeated_stub_sightings(monkeypatch: pytest.MonkeyPatch) -> None:
    persons = await _run(
        monkeypatch,
        [
            _initiative("20001", description=_mention_doc()),
            _initiative("20002", description=_mention_doc()),
        ],
        [],
    )
    assert len(persons) == 1
    assert persons[0].attributes.full_name == _ACC


@pytest.mark.asyncio
async def test_repeated_profile_sightings(monkeypatch: pytest.MonkeyPatch) -> None:
    persons = await _run(
        monkeypatch,
        [],
        [_issue("50001", assignee=_user()), _issue("50002", assignee=_user())],
    )
    assert len(persons) == 1


@pytest.mark.asyncio
async def test_user_without_account_id_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    persons = await _run(
        monkeypatch,
        [],
        [_issue(assignee={"displayName": "No Id"})],
    )
    assert persons == []

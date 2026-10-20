"""Unit tests: GitHub producer Person dedupe via PersonSeenTracker (stub must not block a profile)."""
from __future__ import annotations

import asyncio
import logging
from contextlib import ExitStack
from datetime import datetime, timezone
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from connectors.producers.github.process_issues import process_issues
from connectors.producers.github.process_single_commit import process_single_commit
from connectors.producers.github.process_single_pr import process_single_pr
from connectors.producers.person_tracking import PersonSeenTracker

pytestmark = pytest.mark.unit

_ISSUES = "connectors.producers.github.process_issues"
_PR = "connectors.producers.github.process_single_pr"
_COMMIT = "connectors.producers.github.process_single_commit"
_FULL_NAME = "owner/repo"

_PROFILES: Dict[str, Dict[str, Any]] = {
    "carol": {"login": "carol", "name": "Carol C", "email": "carol@x.com"},
}


def _user_data(user: Any) -> Dict[str, Any]:
    return _PROFILES.get(user.login, {"login": user.login, "name": user.login, "email": ""})


async def _fake_to_thread(func, *args, **kwargs):
    return func(*args, **kwargs)


def _issue(number: int, assignees: List[str] | None = None, commenters: List[str] | None = None) -> MagicMock:
    issue = MagicMock()
    issue.number = number
    issue.state = "open"
    issue.body = ""
    issue.assignees = [MagicMock(login=a) for a in (assignees or [])]
    issue.assignee = None
    issue._commenters = commenters or []
    return issue


def _comments_for(issue: MagicMock) -> List[MagicMock]:
    out = []
    for login in issue._commenters:
        c = MagicMock()
        c.user = MagicMock()
        c.user.login = login
        c.body = ""
        c.created_at = datetime(2026, 1, 3, tzinfo=timezone.utc)
        out.append(c)
    return out


async def _run_issues(
    issues: List[MagicMock], tracker: PersonSeenTracker
) -> tuple[List[Dict[str, Any]], MagicMock]:
    """Run process_issues; return the person_data dicts passed to build_person_signal and the user-fetch mock."""
    built: List[Dict[str, Any]] = []

    def _build_person(pd: Dict[str, Any]) -> MagicMock:
        built.append(pd)
        return MagicMock(_signal_kind="Person")

    fetch_user = MagicMock(side_effect=_user_data)
    with ExitStack() as stack:
        for p in [
            patch(f"{_ISSUES}.os.getenv", return_value="direct"),
            patch(f"{_ISSUES}.resolve_issues_since_date", return_value=datetime(2026, 1, 1, tzinfo=timezone.utc)),
            patch(f"{_ISSUES}.asyncio.to_thread", new=AsyncMock(side_effect=_fake_to_thread)),
            patch(f"{_ISSUES}.fetch_issues_direct", return_value=issues),
            patch(f"{_ISSUES}.fetch_issue_comments", side_effect=_comments_for),
            patch(f"{_ISSUES}.map_issue", side_effect=lambda i, fn: {
                "key": f"{_FULL_NAME}#{i.number}", "number": i.number, "summary": "s", "priority": "None",
                "status": "open", "type": "Issue", "created_at": "2026-01-01T09:00:00+00:00",
                "updated_at": "2026-01-02T12:00:00+00:00", "assignee": None, "reporter": "alice",
                "labels": [], "url": "http://x", "repo_full_name": _FULL_NAME}),
            patch(f"{_ISSUES}.extract_mentions", return_value=[]),
            patch(f"{_ISSUES}.extract_issue_keys", return_value=[]),
            patch(f"{_ISSUES}.extract_github_issue_refs", return_value=[]),
            patch(f"{_ISSUES}.fetch_github_user", new=fetch_user),
            patch(f"{_ISSUES}.build_issue_signal", side_effect=lambda **kw: MagicMock(_signal_kind="Issue")),
            patch(f"{_ISSUES}.build_person_signal", side_effect=_build_person),
        ]:
            stack.enter_context(p)
        repo = MagicMock()
        repo.full_name = _FULL_NAME
        await process_issues(
            repo=repo, repo_data={"name": "repo", "full_name": _FULL_NAME}, repo_owner="owner",
            full_name=_FULL_NAME, last_synced_at=None, published={}, seen_persons=tracker,
            pub_callback=AsyncMock(), github_obj=MagicMock(),
        )
    return [b for b in built if b["login"] == "carol"], fetch_user


@pytest.mark.asyncio
async def test_stub_then_profile_publishes_both():
    carol, _ = await _run_issues(
        [_issue(1, assignees=["carol"]), _issue(2, commenters=["carol"])], PersonSeenTracker()
    )
    assert len(carol) == 2
    assert carol[0]["email"] == ""
    assert carol[1]["name"] == "Carol C" and carol[1]["email"] == "carol@x.com"


@pytest.mark.asyncio
async def test_profile_then_stub_publishes_once():
    carol, _ = await _run_issues(
        [_issue(1, commenters=["carol"]), _issue(2, assignees=["carol"])], PersonSeenTracker()
    )
    assert len(carol) == 1
    assert carol[0]["email"] == "carol@x.com"


@pytest.mark.asyncio
async def test_repeated_stub_and_repeated_profile_publish_once():
    stubs, _ = await _run_issues(
        [_issue(1, assignees=["carol"]), _issue(2, assignees=["carol"])], PersonSeenTracker()
    )
    assert len(stubs) == 1
    profiles, _ = await _run_issues(
        [_issue(1, commenters=["carol"]), _issue(2, commenters=["carol"])], PersonSeenTracker()
    )
    assert len(profiles) == 1


@pytest.mark.asyncio
async def test_no_extra_api_call_once_profile_published():
    _, fetch_user = await _run_issues(
        [_issue(1, commenters=["carol"]), _issue(2, commenters=["carol"])], PersonSeenTracker()
    )
    assert fetch_user.call_count == 1


@pytest.mark.asyncio
async def test_commit_author_profile_not_blocked_by_pr_reviewer_stub():
    tracker = PersonSeenTracker()
    built: List[Dict[str, Any]] = []

    def _build_person(pd: Dict[str, Any]) -> MagicMock:
        built.append(pd)
        return MagicMock()

    async def _pub(_signal: Any) -> None:
        return None

    pr = MagicMock()
    pr.number = 1
    pr.user = MagicMock(login="pr_author")
    pr.title = "T"
    pr.merged_by = None
    pr.requested_reviewers = []
    review = MagicMock()
    review.user = MagicMock(login="carol")
    pr_data = {
        "number": 1, "title": "T", "state": "open", "created_at": "2026-06-20T10:00:00+00:00",
        "updated_at": "2026-06-20T10:00:00+00:00", "commits_count": 0, "additions": 0, "deletions": 0,
        "changed_files": 0, "comments": 0, "review_comments": 0, "head_branch_name": "feat",
        "base_branch_name": "main", "mergeable_state": "clean", "labels": [], "url": "http://x",
        "base_branch_id": "r::main", "head_branch_id": "r::feat",
    }
    repo = MagicMock()
    repo.name = "repo"
    repo.default_branch = "main"

    with ExitStack() as stack:
        for p in [
            patch(f"{_PR}.asyncio.to_thread", new=AsyncMock(side_effect=_fake_to_thread)),
            patch(f"{_PR}.fetch_pr_commits", return_value=[]),
            patch(f"{_PR}.fetch_pr_issue_comments", return_value=[]),
            patch(f"{_PR}.fetch_pr_review_comments", return_value=[]),
            patch(f"{_PR}.fetch_commit_comments", return_value=[]),
            patch(f"{_PR}.fetch_pr_reviews", return_value=[review]),
            patch(f"{_PR}.map_pull_request", return_value=pr_data),
            patch(f"{_PR}.map_pr_reviews", return_value={"carol": "APPROVED"}),
            # reviewer fetch yields a stub for carol (user data unavailable)
            patch(f"{_PR}.fetch_github_user", side_effect=lambda u: {"login": u.login, "name": u.login, "email": ""}),
            patch(f"{_PR}.build_person_signal", side_effect=_build_person),
        ]:
            stack.enter_context(p)
        await process_single_pr(
            pr=pr, repo=repo, repo_data={"name": "repo"}, repo_owner="org",
            seen_commits=set(), published_persons=tracker, _pub=_pub,
        )
    assert [b["email"] for b in built if b["login"] == "carol"] == [""]

    commit = MagicMock()
    commit.sha = "abcdef1234567890"
    with ExitStack() as stack:
        for p in [
            patch(f"{_COMMIT}.asyncio.to_thread", new=AsyncMock(side_effect=_fake_to_thread)),
            patch(f"{_COMMIT}._extract_commit_data",
                  return_value=(_PROFILES["carol"], {"sha": commit.sha}, [])),
            patch(f"{_COMMIT}.retry_with_backoff", side_effect=lambda f: f()),
            patch(f"{_COMMIT}.build_person_signal", side_effect=_build_person),
            patch(f"{_COMMIT}.build_commit_signal", return_value=MagicMock()),
        ]:
            stack.enter_context(p)
        await process_single_commit(
            commit=commit, semaphore=asyncio.Semaphore(1), repo=repo, repo_owner="org",
            published_persons=tracker, seen_commits=set(), pub_callback=AsyncMock(),
        )
    carol_emails = [b["email"] for b in built if b["login"] == "carol"]
    assert carol_emails == ["", "carol@x.com"]


@pytest.mark.asyncio
async def test_person_decisions_are_logged_without_email_value(caplog):
    _PROFILES["carol"] = {"login": "carol", "name": "Carol C", "email": "secret-carol@x.com"}
    try:
        with caplog.at_level(logging.INFO):
            await _run_issues(
                [_issue(1, assignees=["carol"]), _issue(2, commenters=["carol"])], PersonSeenTracker()
            )
    finally:
        _PROFILES["carol"] = {"login": "carol", "name": "Carol C", "email": "carol@x.com"}
    assert "Person published kind=stub login=carol source=issue_related" in caplog.text
    assert "Person published kind=profile login=carol source=issue_related" in caplog.text
    assert "email_present=True" in caplog.text
    assert "secret-carol@x.com" not in caplog.text

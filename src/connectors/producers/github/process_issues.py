"""Orchestrator for GitHub issue signal processing.

Fetches issues for a repository, fetches comments for each issue, parses
@mentions and issue references from the issue body + comment bodies, builds
a single ``ActivitySignal`` per issue (with all relationships), and publishes
it. Also emits Person signals for assignees, commenters, and mentioned users
that haven't been seen yet in this sync run.

Mirrors ``process_prs.py`` / ``process_single_pr.py`` in structure.
"""
from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Dict, List, Optional, Set

from common.activity_signal.models import ActivitySignal
from common.logger import logger

from connectors.producers.github.build_issue_signal import build_issue_signal
from connectors.producers.github.build_person_signal import build_person_signal
from connectors.producers.github.fetch_github import (
    fetch_issue_comments,
    fetch_issues,
    fetch_issues_direct,
    resolve_issues_since_date,
)
from connectors.producers.github.map_github import (
    extract_github_issue_refs,
    extract_issue_keys,
    extract_mentions,
    fetch_github_user,
    map_issue,
)
from connectors.producers.github.retry_with_backoff import WbaRetryTimeoutError


def _resolve_issue_fetch_mode() -> str:
    """Return the issue-fetch strategy from the ``ISSUE_FETCH_MODE`` env var.

    Valid values:
        - ``search``: use the GitHub Search API (``fetch_issues``).
        - ``direct``: use the repository issues endpoint (``fetch_issues_direct``).

    Defaults to ``search``. Any other value logs a warning and falls back to
    ``search``. This replaces the previous automatic search→direct fallback so
    the two implementations are never mixed within a single scan, keeping
    published counts consistent.
    """
    mode = os.getenv("ISSUE_FETCH_MODE", "search").strip().lower()
    if mode not in ("search", "direct"):
        logger.warning(f"Unknown ISSUE_FETCH_MODE={mode!r} — defaulting to 'search'")
        return "search"
    return mode


async def process_issues(
    repo: Any,
    repo_data: Dict[str, Any],
    repo_owner: str,
    full_name: str,
    last_synced_at: Optional[datetime],
    published: Dict[str, int],
    seen_persons: Set[str],
    pub_callback: Callable[[Optional[ActivitySignal]], Awaitable[None]],
    github_obj: Optional[Any] = None,
) -> None:
    """Fetch issues for *repo* and publish Issue and related Person signals.

    Args:
        repo: PyGithub Repository object.
        repo_data: Normalized repo dict (must contain ``full_name``).
        repo_owner: Repository owner string.
        full_name: Repository full name (e.g. ``"owner/repo"``).
        last_synced_at: Last successful sync timestamp, or ``None`` for first run.
        published: Dict tracking published signal counts by entity_type.
        seen_persons: Set of person logins already emitted in this sync run.
        pub_callback: Async callback for publishing signals.
        github_obj: Optional PyGithub ``Github`` client for Search API. If not
            provided, falls back to ``fetch_issues_direct``.
    """
    issue_since = resolve_issues_since_date(last_synced_at)
    fetch_mode = _resolve_issue_fetch_mode()
    logger.info(f"Fetching issues for '{full_name}' (owner={repo_owner}, mode={fetch_mode})...")

    # Fetch issues using the explicitly configured strategy. No automatic
    # fallback between the two implementations — the mode is fixed per scan so
    # published counts stay consistent regardless of transient network errors.
    issues_raw: List[Any] = []
    if fetch_mode == "direct":
        logger.info(f"Using direct issues fetch for '{full_name}' (ISSUE_FETCH_MODE=direct)")
        try:
            issues_raw = list(
                await asyncio.to_thread(fetch_issues_direct, repo, issue_since)
            )
        except WbaRetryTimeoutError:
            logger.debug(
                f"[process_issues] WbaRetryTimeoutError propagating for '{full_name}' (direct fetch) — repo will be "
                f"skipped without cursor advance"
            )
            raise
        except Exception as exc:
            logger.error(f"Failed to fetch issues for '{full_name}': {exc}")
            return
    else:
        # search mode — requires the Search API client
        if github_obj is None:
            logger.error(
                f"ISSUE_FETCH_MODE=search but no github_obj provided for '{full_name}' — cannot use Search API, "
                f"skipping issues"
            )
            return
        try:
            issues_raw = await asyncio.to_thread(
                fetch_issues, github_obj, full_name, issue_since
            )
        except WbaRetryTimeoutError:
            logger.debug(
                f"[process_issues] WbaRetryTimeoutError propagating for '{full_name}' (search fetch) — repo will be "
                f"skipped without cursor advance"
            )
            raise
        except Exception as exc:
            logger.error(f"Search API failed for '{full_name}': {exc}")
            return

    logger.info(f"Fetched {len(issues_raw)} issues for '{full_name}'")

    total = len(issues_raw)
    for idx, issue in enumerate(issues_raw, start=1):
        try:
            issue_number = getattr(issue, "number", "?")
            issue_state = getattr(issue, "state", "?")
            logger.debug(f"Processing issue '{full_name}#{issue_number}' ({issue_state}) [{idx}/{total}]")

            await _process_single_issue(
                issue,
                repo_data=repo_data,
                full_name=full_name,
                seen_persons=seen_persons,
                pub_callback=pub_callback,
            )
        except WbaRetryTimeoutError:
            logger.debug(
                f"[process_issues] WbaRetryTimeoutError propagating for '{full_name}' — repo will be skipped without "
                f"cursor advance"
            )
            raise
        except Exception as exc:
            logger.warning(
                f"Issue skipped: type={type(exc).__name__} exception={exc!r} issue=#{getattr(issue, 'number', '?')}"
            )

    logger.info(f"Issues done ({published.get('Issue', 0)}) for '{full_name}'")


async def _process_single_issue(
    issue: Any,
    repo_data: Dict[str, Any],
    full_name: str,
    seen_persons: Set[str],
    pub_callback: Callable[[Optional[ActivitySignal]], Awaitable[None]],
) -> None:
    """Process a single issue: fetch comments, parse mentions/refs, build, publish."""
    # Map the issue to a normalized dict
    issue_data = await asyncio.to_thread(map_issue, issue, full_name)

    # Fetch comments
    comments_raw = await asyncio.to_thread(fetch_issue_comments, issue)

    # Build comments_data list (login + timestamp) and collect unique commenters
    comments_data: List[Dict[str, Any]] = []
    commenter_users: Dict[str, Any] = {}  # login → user object

    for comment in comments_raw:
        comment_user = getattr(comment, "user", None)
        if not comment_user or not getattr(comment_user, "login", None):
            continue
        login = comment_user.login
        if login not in commenter_users:
            commenter_users[login] = comment_user

        dt = getattr(comment, "created_at", None)
        if dt:
            if not dt.tzinfo:
                dt = dt.replace(tzinfo=timezone.utc)
            ts = dt.isoformat()
        else:
            ts = datetime.now(timezone.utc).isoformat()

        comments_data.append({"login": login, "timestamp": ts})

    # Parse mentions and references from issue body + comment bodies
    issue_body = getattr(issue, "body", "") or ""
    comment_bodies = [getattr(c, "body", "") or "" for c in comments_raw]
    all_text = "\n".join([issue_body] + comment_bodies)

    mention_logins = extract_mentions(all_text)
    jira_keys = extract_issue_keys(all_text)
    github_refs = extract_github_issue_refs(all_text, full_name)

    # Split GitHub refs into cross-repo (REFERENCES) and same-repo (RELATES_TO)
    referenced_github_issue_ids: List[str] = []
    relates_to_ids: List[str] = []
    for ref in github_refs:
        ref_repo = ref.rsplit("#", 1)[0]
        if ref_repo == full_name:
            relates_to_ids.append(ref)
        else:
            referenced_github_issue_ids.append(ref)

    # Collect assignee logins
    assignee_logins: List[str] = []
    assignees = getattr(issue, "assignees", None) or []
    for assignee in assignees:
        login = getattr(assignee, "login", None)
        if login:
            assignee_logins.append(login)
    # Fallback: single assignee
    if not assignee_logins:
        single_assignee = getattr(issue, "assignee", None)
        if single_assignee:
            login = getattr(single_assignee, "login", None)
            if login:
                assignee_logins.append(login)

    # Emit Person signals for unseen users (assignees, commenters, mentioned users)
    all_person_logins: List[str] = []
    all_person_logins.extend(assignee_logins)
    all_person_logins.extend(mention_logins)
    all_person_logins.extend(commenter_users.keys())

    for login in all_person_logins:
        if login in seen_persons:
            logger.debug(f"Person '{login}' already seen, skipping Person signal")
            continue
        seen_persons.add(login)

        # Fetch full user data for the Person signal
        user_obj = commenter_users.get(login)
        if not user_obj:
            # For assignees and mentioned users, we don't have the user object;
            # build a minimal person_data dict
            person_data: Dict[str, Any] = {"login": login, "name": login, "email": ""}
        else:
            person_data = await asyncio.to_thread(fetch_github_user, user_obj)

        logger.debug(
            f"[person:issue_related] login={login!r}  name={person_data.get('name')!r}  email="
            f"{person_data.get('email')!r}  issue=#{getattr(issue, 'number', '?')}"
        )
        await pub_callback(build_person_signal(person_data))

    # Build and publish the Issue signal
    issue_signal = build_issue_signal(
        issue_data=issue_data,
        repo_data=repo_data,
        assignee_logins=assignee_logins,
        mention_logins=mention_logins,
        referenced_jira_keys=jira_keys,
        referenced_github_issue_ids=referenced_github_issue_ids,
        relates_to_ids=relates_to_ids,
        comments_data=comments_data,
    )
    await pub_callback(issue_signal)

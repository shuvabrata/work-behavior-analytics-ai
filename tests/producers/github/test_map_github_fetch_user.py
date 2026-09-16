"""
Tests for fetch_github_user stub handling in map_github.

A PyGithub ``NamedUser`` created from a PR commit's ``author`` may be a stub
with no URL. Accessing ``.login``/``.name``/``.email`` on such a stub raises
``IncompletableObject`` ("Cannot complete object as it contains no URL").
These tests verify that ``fetch_github_user`` degrades gracefully instead of
letting that exception propagate.
"""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock

from connectors.producers.github.map_github import fetch_github_user


class _StubNamedUser:
    """Mimics a PyGithub NamedUser stub with no URL.

    Accessing any attribute raises IncompletableObject, exactly like PyGithub's
    ``_complete()`` does when ``_url`` is None.
    """

    def __getattr__(self, name: str):
        raise Exception("Cannot complete object as it contains no URL: 400")


class _GitAuthor:
    """Mimics a PyGithub GitAuthor (git-embedded metadata, no API call)."""

    def __init__(self, name: str, email: str) -> None:
        self.name = name
        self.email = email


@pytest.mark.unit
def test_fetch_github_user_none():
    result = fetch_github_user(None)
    assert result == {"login": "unknown", "name": "Unknown", "email": ""}


@pytest.mark.unit
def test_fetch_github_user_git_author():
    author = _GitAuthor("Jane Doe", "jane@example.com")
    result = fetch_github_user(author)
    assert result == {"login": "jane", "name": "Jane Doe", "email": "jane@example.com"}


@pytest.mark.unit
def test_fetch_github_user_stub_named_user_falls_back_to_unknown():
    """A NamedUser stub with no URL must not raise; it falls back to unknown."""
    stub = _StubNamedUser()
    result = fetch_github_user(stub)
    assert result == {"login": "unknown", "name": "Unknown", "email": ""}


@pytest.mark.unit
def test_fetch_github_user_named_user_with_login():
    """A normal NamedUser with a login still resolves via the cache path."""
    user = MagicMock()
    user.login = "octocat"
    user.name = "The Octocat"
    user.email = "octo@example.com"
    result = fetch_github_user(user)
    assert result == {"login": "octocat", "name": "The Octocat", "email": "octo@example.com"}

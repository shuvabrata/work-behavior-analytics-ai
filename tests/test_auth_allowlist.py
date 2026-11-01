"""The bearer-free surface is exactly two allowlists and no more.

This file pairs one **behavioural** assertion with one **static** one:

* The public-path set is read from ``AUTHZ_MATRIX`` and checked against the live
  app's dependency wiring, so a new route that skips authentication fails here.
* The session-cookie path set is a **static scan** of ``src/app/api/`` for the
  cookie constant. It is deliberately static — the cookie is read inside handler
  bodies rather than through a dependency, so there is no wiring to observe.
  A future reader should not mistake it for a behavioural test.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.api_main import app
from app.auth.matrix import AUTHZ_MATRIX
from tests.test_authz_matrix import _BEARER_DEPENDENCIES, api_operations

pytestmark = pytest.mark.unit

_API_ROOT = Path(__file__).resolve().parent.parent / "src" / "app" / "api"
_SESSION_COOKIE_MARKERS = ("SESSION_COOKIE_NAME", "wba_session")


def _paths_without_bearer() -> set[tuple[str, str]]:
    """Operations whose effective dependencies carry no bearer check."""
    return {
        (method, path)
        for method, path, deps in api_operations(app)
        if not _BEARER_DEPENDENCIES.intersection(deps)
    }


def _files_reading_the_session_cookie() -> set[str]:
    """API source files that mention the session cookie constant."""
    repo_root = _API_ROOT.parents[2]
    hits: set[str] = set()
    for path in _API_ROOT.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if any(marker in text for marker in _SESSION_COOKIE_MARKERS):
            hits.add(str(path.relative_to(repo_root)))
    return hits


def test_public_paths_are_exactly_three() -> None:
    """Only health, login and callback are reachable without a bearer.

    The session routes carry no bearer either, so the bearer-free set is the
    union of the public and session allowlists.
    """
    expected = {
        ("GET", "/api/health"),
        ("GET", "/api/v1/auth/login"),
        ("GET", "/api/v1/auth/callback"),
    }
    public = {key for key, grant in AUTHZ_MATRIX.items() if grant == "public"}
    assert public == expected

    session = {key for key, grant in AUTHZ_MATRIX.items() if grant == "session"}
    without_bearer = _paths_without_bearer()
    assert without_bearer == expected | session, (
        "operations reachable without a bearer differ from the allowlist: "
        f"{sorted(without_bearer ^ (expected | session))}"
    )


def test_session_cookie_paths_are_exactly_two() -> None:
    """Only the auth router reads ``wba_session``; both BFF paths are there."""
    session = {key for key, grant in AUTHZ_MATRIX.items() if grant == "session"}
    assert session == {
        ("POST", "/api/v1/auth/token"),
        ("POST", "/api/v1/auth/logout"),
    }

    files = _files_reading_the_session_cookie()
    assert files == {"src/app/api/auth/v1/router.py"}, (
        f"unexpected files reading the session cookie: {sorted(files)}"
    )

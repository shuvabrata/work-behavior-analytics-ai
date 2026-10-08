"""Shared pytest configuration for the test suite.

The Activity Timeline API supports a dev-only mock mode controlled by the
``TIMELINE_MOCK_SCENARIO`` env var (used for manual UI QA). It must never leak
into the test suite: a developer who enabled it in their local ``.env`` would
otherwise see invented data satisfy API assertions. Force it off for every
test; tests that need it set override it explicitly with ``monkeypatch``.
"""

from __future__ import annotations

import pytest

from app.settings import settings


@pytest.fixture(autouse=True)
def _disable_timeline_mock(monkeypatch: pytest.MonkeyPatch) -> None:
    """Force the dev-only activity-timeline mock off for all tests."""
    monkeypatch.setattr(settings, "TIMELINE_MOCK_SCENARIO", "")

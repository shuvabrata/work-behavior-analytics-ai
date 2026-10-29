"""Regression guard: UI callbacks read runtime settings per call, not at import.

Twelve module-level ``TIMEOUT_SECONDS`` / ``API_BASE`` constants used to freeze
these values at import time, so editing ``HTTP_REQUEST_TIMEOUT`` in the Settings
UI never took effect in the pages that used them. They are now read from the
cache at each use site.

The assertion below observes the value **through the consuming function**
(``load_library``), not by reading the cache: the cache was never broken, so a
test that only inspected ``runtime_settings`` would prove nothing.
"""

from __future__ import annotations

from typing import Any

import pytest

pytestmark = pytest.mark.unit


def test_runtime_setting_is_read_per_call_not_at_import(monkeypatch: pytest.MonkeyPatch) -> None:
    """Changing the cache after import must change the callback's behaviour."""
    from common.runtime_settings import RuntimeConfig
    from ui.pages.catalog import callbacks as catalog_callbacks

    captured: dict[str, Any] = {}

    class _FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, Any]:
            return {"items": []}

    def _fake_get(url: str, timeout: int | None = None, **kwargs: Any) -> _FakeResponse:
        _ = url, kwargs
        captured["timeout"] = timeout
        return _FakeResponse()

    monkeypatch.setattr(catalog_callbacks.requests, "get", _fake_get)

    previous = catalog_callbacks.runtime_settings.current()
    catalog_callbacks.runtime_settings.refresh(RuntimeConfig(HTTP_REQUEST_TIMEOUT=123))
    try:
        catalog_callbacks.load_library("/app/catalog")
    finally:
        catalog_callbacks.runtime_settings.refresh(previous)

    assert captured.get("timeout") == 123, captured


def test_ui_seed_does_not_clobber_a_populated_shared_cache() -> None:
    """The UI's import-time seed must not overwrite the API runtime's config.

    Regression guard: the UI and the API share one ``RuntimeConfigCache``
    (``domain.timezone.runtime_settings``) until Step 8, and the UI's seed is
    built from a 13-field model. ``RuntimeConfigCache.refresh`` *replaces* the
    snapshot rather than merging, so a naive seed overwrote the API's
    ``LLM_MODEL``, ``GITHUB_MCP_ENABLED``, the day limits and ``API_SERVER``
    with code defaults whenever ``app.main`` imported ``ui_main``.
    """
    from common.runtime_settings import RuntimeConfig
    from ui import runtime_settings as urs

    populated = RuntimeConfig(LLM_MODEL="gpt-5-mini", COMMIT_DAYS_LIMIT=15)
    seed = urs._seed_config(urs.settings, populated)

    assert seed.LLM_MODEL == "gpt-5-mini"
    assert seed.COMMIT_DAYS_LIMIT == 15
    # A field the seed *does* define is filled when the cache had only a default.
    assert seed.HTTP_REQUEST_TIMEOUT == urs.settings.HTTP_REQUEST_TIMEOUT


def test_refresh_is_wired_to_a_real_trigger_and_bounded() -> None:
    """``refresh`` must be reachable, and ``refresh_if_stale`` must rate-limit it.

    ``refresh`` had no caller at Step 6b, so the UI's cache only ever held its
    import-time env seed and a runtime setting edited in the Settings UI never
    reached the UI. The Flask ``before_request`` hook drives it through
    ``refresh_if_stale``; 30 requests inside one TTL must cost one API fetch.
    """
    from unittest.mock import patch

    from common.runtime_settings import RuntimeConfig
    from ui import runtime_settings as urs

    with patch(
        "common.runtime_settings.fetch_runtime_snapshot",
        return_value=RuntimeConfig(HTTP_REQUEST_TIMEOUT=999),
    ):
        urs._last_refresh = 0.0
        calls = {"n": 0}
        original = urs.refresh

        def counted() -> None:
            calls["n"] += 1
            original()

        with patch.object(urs, "refresh", counted):
            for _ in range(30):
                urs.refresh_if_stale()

    assert calls["n"] == 1, calls
    assert urs.runtime_settings.get_int("HTTP_REQUEST_TIMEOUT") == 999

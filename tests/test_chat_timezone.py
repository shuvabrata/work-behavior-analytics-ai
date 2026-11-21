"""Unit tests for chat timestamp timezone handling.

Covers the Python render path in src/ui/pages/chat.py:render_messages —
specifically that a UTC ISO-8601 timestamp (the shape the JS stream bridge
writes) is displayed in the configured app timezone, not in UTC.

The JS side (stream-bridge.js:formatTimestamp) has no harness that executes
JavaScript; see the manual smoke test in the plan for that half.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from common.runtime_settings import RuntimeConfig
from domain.timezone import runtime_settings
from ui.pages.chat import render_messages

pytestmark = pytest.mark.unit

# A UTC timestamp: 03:42:00 UTC == 09:12:00 IST (+05:30).
_UTC_TS = "2026-11-21T03:42:00+00:00"
# The same instant, already expressed in the app timezone.
_IST_TS = "2026-11-21T09:12:00+05:30"


@pytest.fixture
def app_tz_ist():
    """Point the shared runtime-settings snapshot at Asia/Kolkata, then restore.

    The cache is process-wide, so the previous snapshot is captured and put back
    on teardown — a leaked override would change the timezone under every other
    test in the session.
    """
    previous = runtime_settings.current()
    runtime_settings.refresh(previous.model_copy(update={
        "TIMEZONE": "Asia/Kolkata",
        "UI_DATETIME_FORMAT": "%b %d, %Y %I:%M %p",
    }))
    try:
        yield
    finally:
        runtime_settings.refresh(previous)


def _tooltip_span(rendered: list, *, assistant: bool):
    """Return the timestamp ``html.Span`` from a rendered user/assistant message.

    Walks the tree by role rather than by a hard-coded index chain, so a layout
    change that adds a wrapper does not silently assert against the wrong node.
    """
    flex = rendered[0].children[1] if assistant else rendered[0].children[0]
    inner = flex.children[1] if assistant else flex.children[0]
    ts_div = inner.children[1]
    return ts_div.children


def test_utc_timestamp_tooltip_shows_app_timezone(app_tz_ist):
    """A UTC timestamp from the JS bridge renders in the app timezone in the tooltip."""
    rendered = render_messages([{"role": "user", "content": "hi", "timestamp": _UTC_TS}])
    span = _tooltip_span(rendered, assistant=False)

    assert span.title == "Nov 21, 2026 09:12 AM"


def test_app_tz_timestamp_is_not_double_converted(app_tz_ist):
    """A timestamp already in the app timezone must render identically."""
    rendered = render_messages([{"role": "user", "content": "hi", "timestamp": _IST_TS}])
    span = _tooltip_span(rendered, assistant=False)

    assert span.title == "Nov 21, 2026 09:12 AM"


def test_assistant_timestamp_tooltip_uses_app_timezone(app_tz_ist):
    """Assistant messages share the render path and must also use the app timezone."""
    rendered = render_messages([{"role": "assistant", "content": "hello", "timestamp": _UTC_TS}])
    span = _tooltip_span(rendered, assistant=True)

    assert span.title == "Nov 21, 2026 09:12 AM"


def test_render_messages_does_not_mutate_the_settings_snapshot(app_tz_ist):
    """Rendering must not leak a cache refresh back into the shared snapshot."""
    render_messages([{"role": "user", "content": "hi", "timestamp": _UTC_TS}])

    assert runtime_settings.get("TIMEZONE") == "Asia/Kolkata"

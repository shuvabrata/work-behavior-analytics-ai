"""Unit tests for the Activity Timeline UI helpers.

Covers UI-0 (scaffold/route) and UI-1 (selector helpers + callback wiring).
Later phases append their own pure-helper tests here.
"""

from __future__ import annotations

import dash
import pytest
from dash import html

from app.analytics.registry import TIMELINE_ANALYTIC
from app.dash_app.pages.timeline import get_layout
from app.dash_app.pages.timeline.helpers import (
    MAX_LANES,
    add_selection,
    assign_lane_colors,
    entity_type_label,
    remove_selection,
)


pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# UI-0
# ---------------------------------------------------------------------------


def test_timeline_analytic_href() -> None:
    """The timeline analytic points at the dedicated timeline route."""
    assert TIMELINE_ANALYTIC.href == "/app/analytics/timeline"


def test_timeline_layout_renders() -> None:
    """The UI-0 scaffold renders as a Dash Div."""
    layout = get_layout()
    assert isinstance(layout, html.Div)


# ---------------------------------------------------------------------------
# UI-1 — selection helpers
# ---------------------------------------------------------------------------


def test_assign_lane_colors_distinct() -> None:
    """Lane accent tokens are distinct and capped at MAX_LANES."""
    keys = assign_lane_colors(MAX_LANES)
    assert len(keys) == MAX_LANES
    assert len(set(keys)) == MAX_LANES
    assert assign_lane_colors(0) == []
    assert len(assign_lane_colors(MAX_LANES + 3)) == MAX_LANES


def test_entity_type_label_mapping() -> None:
    """Known types map to short labels; unknown types fall back to raw."""
    assert entity_type_label("PullRequest") == "PR"
    assert entity_type_label("Page") == "Page"
    assert entity_type_label("UnknownType") == "UnknownType"


def test_selection_add_remove_dedup() -> None:
    """Adding is idempotent, the cap holds, and remove drops the entry."""
    item = {"wba_id": "jira::Person::1", "label": "Ada"}
    selection = add_selection([], item)
    assert len(selection) == 1

    selection = add_selection(selection, item)
    assert len(selection) == 1

    selection = remove_selection(selection, "jira::Person::1")
    assert selection == []

    full: list[dict[str, object]] = []
    for index in range(MAX_LANES + 2):
        full = add_selection(full, {"wba_id": f"jira::Person::{index}"})
    assert len(full) == MAX_LANES


def test_timeline_callbacks_registered() -> None:
    """Importing the timeline package registers its callbacks.

    Guards the UI-0 ``__init__`` → ``callbacks`` import: without it the page
    renders (suppress_callback_exceptions=True) but interactions silently no-op.
    The package is imported at module top via ``get_layout``, which is what
    registers the callbacks; this asserts they landed in the global map.
    """
    assert any(
        "timeline-" in str(key) for key in dash._callback.GLOBAL_CALLBACK_MAP
    )

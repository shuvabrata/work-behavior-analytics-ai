"""Unit tests for the Activity Timeline UI helpers.

Covers UI-0 (scaffold/route) and UI-1 (selector helpers + callback wiring).
Later phases append their own pure-helper tests here.
"""

from __future__ import annotations

from datetime import date
from zoneinfo import ZoneInfo

import dash
import pytest
from dash import html

from app.analytics.registry import TIMELINE_ANALYTIC
from app.dash_app.pages.timeline import get_layout
from app.dash_app.pages.timeline.helpers import (
    MAX_LANES,
    add_selection,
    assign_lane_colors,
    build_grid,
    bucket_by_period,
    card_summary,
    entity_type_color,
    entity_type_label,
    entity_type_token,
    extract_mock_scenario,
    extract_scope,
    find_idle_runs,
    humanize_relationship,
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


# ---------------------------------------------------------------------------
# UI-2 — bucketing, grid, idle runs, mock param
# ---------------------------------------------------------------------------

_UTC = ZoneInfo("UTC")
_KOLKATA = ZoneInfo("Asia/Kolkata")


def _event(signal_id: str, iso: str, summary: str = "event") -> dict[str, object]:
    return {
        "signal_id": signal_id,
        "event_time": iso,
        "relationship_type": "CREATED",
        "summary": summary,
        "entity_type": "PullRequest",
        "source": "github",
        "url": None,
        "details": {},
    }


def _lane(wba_id: str, events: list[dict[str, object]]) -> dict[str, object]:
    return {
        "wba_id": wba_id,
        "entity_type": "Person",
        "label": wba_id,
        "avatar_url": None,
        "events": events,
        "next_cursor": None,
    }


def test_bucket_by_period_day() -> None:
    """Events map to the correct calendar day in the display timezone."""
    lanes = [
        _lane(
            "a",
            [
                _event("s1", "2026-03-15T10:00:00+00:00"),
                _event("s2", "2026-03-15T23:30:00+00:00"),
                _event("s3", "2026-03-14T01:00:00+00:00"),
            ],
        )
    ]
    rows = bucket_by_period(lanes, "day", _UTC)
    assert [row["period_key"] for row in rows] == ["2026-03-15", "2026-03-14"]
    assert len(rows[0]["cells"]["a"]) == 2

    # 23:30 UTC is already the next calendar day in UTC+05:30.
    shifted = bucket_by_period(
        [_lane("a", [_event("s1", "2026-03-15T23:30:00+00:00")])], "day", _KOLKATA
    )
    assert shifted[0]["period_key"] == "2026-03-16"


def test_build_grid_union_rows() -> None:
    """Rows are the union across lanes and every lane has a cell per row."""
    lanes = [
        _lane("a", [_event("s1", "2026-03-15T10:00:00+00:00")]),
        _lane("b", [_event("s2", "2026-03-14T10:00:00+00:00")]),
    ]
    rows = build_grid(lanes, "day", _UTC)
    assert [row["period_key"] for row in rows] == ["2026-03-15", "2026-03-14"]
    assert rows[0]["cells"]["b"] == []
    assert rows[1]["cells"]["a"] == []


def test_event_order_newest_first() -> None:
    """Events inside a cell are sorted newest-first."""
    lane = _lane(
        "a",
        [
            _event("s1", "2026-03-15T08:00:00+00:00"),
            _event("s2", "2026-03-15T18:00:00+00:00"),
        ],
    )
    rows = bucket_by_period([lane], "day", _UTC)
    assert [event["signal_id"] for event in rows[0]["cells"]["a"]] == ["s2", "s1"]


def test_find_idle_runs() -> None:
    """A gap between present periods yields one run; boundaries excluded."""
    lanes = [
        _lane(
            "a",
            [
                _event("s1", "2026-03-15T10:00:00+00:00"),
                _event("s2", "2026-03-11T10:00:00+00:00"),
            ],
        )
    ]
    rows = build_grid(lanes, "day", _UTC)
    runs = find_idle_runs(rows, "day")
    assert len(runs) == 1
    assert runs[0]["count"] == 3  # Mar 12, 13, 14
    assert runs[0]["start_ordinal"] == date(2026, 3, 12).toordinal()
    assert runs[0]["end_ordinal"] == date(2026, 3, 14).toordinal()


def test_extract_mock_scenario() -> None:
    """The mock scenario is read from the page URL search string."""
    assert extract_mock_scenario(None) is None
    assert extract_mock_scenario("?mock=gap_30d") == "gap_30d"
    assert extract_mock_scenario("?wba_ids=x&mock=even") == "even"
    assert extract_mock_scenario("?q=foo") is None


def test_extract_scope() -> None:
    """The scope is read from the URL, defaulting to activity."""
    assert extract_scope(None) == "activity"
    assert extract_scope("?scope=history") == "history"
    assert extract_scope("?scope=activity&x=1") == "activity"
    assert extract_scope("?scope=bogus") == "activity"


# ---------------------------------------------------------------------------
# UI-3 — card helpers
# ---------------------------------------------------------------------------


def test_humanize_relationship() -> None:
    """Relationships are humanized; STATE_CHANGE reads 'Updated'."""
    assert humanize_relationship("CREATED") == "Created"
    assert humanize_relationship("STATE_CHANGE") == "Updated"
    assert humanize_relationship("") == ""


def test_card_summary_fallback() -> None:
    """A null summary falls back to relationship + entity type."""
    assert card_summary({"summary": "Did a thing"}) == "Did a thing"
    assert (
        card_summary(
            {"summary": None, "relationship_type": "CREATED", "entity_type": "PullRequest"}
        )
        == "Created · PR"
    )
    assert (
        card_summary(
            {"summary": "  ", "relationship_type": "STATE_CHANGE", "entity_type": "Page"}
        )
        == "Updated · Page"
    )


def test_entity_type_token_mapping() -> None:
    """PascalCase entity types map to graph-node token keys; unknown → default."""
    assert entity_type_token("PullRequest") == "graph.node.pull_request"
    assert entity_type_token("Page") == "graph.node.page"
    assert entity_type_token("IdentityMapping") == "graph.node.identity_mapping"
    assert entity_type_token("UnknownThing") == "graph.node.default"


def test_entity_type_color_resolution() -> None:
    """Effective-theme overrides win; otherwise the base token is used."""
    base = {"graph.node.default": "#B8B8B8", "graph.node.page": "#F43F5E"}
    assert entity_type_color("Page", None, base) == "#F43F5E"
    assert (
        entity_type_color("Page", {"Page": {"background-color": "#123456"}}, base)
        == "#123456"
    )
    assert entity_type_color("Nope", None, base) == "#B8B8B8"

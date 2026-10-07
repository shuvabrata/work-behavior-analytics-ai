"""Unit tests for the Activity Timeline UI helpers.

Covers the page scaffold/route and callback wiring, plus the pure helpers:
selection, bucketing, cards, popup payloads, idle runs, cell overflow,
pagination, the time range, grouping, and deep-link parsing.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import dash
import pytest
from dash import html

from app.analytics.registry import TIMELINE_ANALYTIC
from app.dash_app.pages.timeline import get_layout
from app.dash_app.pages.timeline.helpers import (
    ALL_TIME,
    MAX_CELL_CARDS,
    MAX_LANES,
    add_selection,
    assign_lane_colors,
    build_grid,
    bucket_by_period,
    cap_cell,
    card_summary,
    cell_expansion_key,
    entity_type_color,
    entity_type_label,
    entity_type_token,
    extract_from,
    extract_group,
    extract_mock_scenario,
    extract_scope,
    extract_to,
    find_idle_runs,
    has_more,
    humanize_relationship,
    idle_run_key,
    idle_run_label,
    is_valid_wba_id,
    merge_lane_page,
    parse_deeplink_params,
    period_key,
    period_label,
    popup_fields,
    remove_selection,
    resolve_range,
    selection_from_wba_ids,
    toggle_expanded,
)


pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------


def test_timeline_analytic_href() -> None:
    """The timeline analytic points at the dedicated timeline route."""
    assert TIMELINE_ANALYTIC.href == "/app/analytics/timeline"


def test_timeline_layout_renders() -> None:
    """The page scaffold renders as a Dash Div."""
    layout = get_layout()
    assert isinstance(layout, html.Div)


# ---------------------------------------------------------------------------
# selection helpers
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

    Guards the ``__init__`` → ``callbacks`` import: without it the page
    renders (suppress_callback_exceptions=True) but interactions silently no-op.
    The package is imported at module top via ``get_layout``, which is what
    registers the callbacks; this asserts they landed in the global map.
    """
    assert any(
        "timeline-" in str(key) for key in dash._callback.GLOBAL_CALLBACK_MAP
    )


# ---------------------------------------------------------------------------
# bucketing, grid, idle runs, mock param
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


def test_extract_range_and_group() -> None:
    """Date and group URL params validate against their allowed forms."""
    assert extract_from(None) is None
    assert extract_from("?from=2026-03-01") == "2026-03-01"
    assert extract_from("?from=not-a-date") is None
    assert extract_to("?to=2026-03-31") == "2026-03-31"
    assert extract_to("?to=bogus") is None

    assert extract_group(None) is None
    assert extract_group("?group=week") == "week"
    assert extract_group("?group=decade") is None


# ---------------------------------------------------------------------------
# inbound deep-linking
# ---------------------------------------------------------------------------


def test_parse_deeplink_full() -> None:
    """All URL params are parsed; malformed ids are split out, not fatal."""
    search = (
        "?wba_ids=mock::Person::alice,bad,mock::Issue::BUG-7"
        "&group=week&scope=history&from=2026-01-01&to=2026-03-31"
    )
    params = parse_deeplink_params(search)
    assert params["wba_ids"] == ["mock::Person::alice", "mock::Issue::BUG-7"]
    assert params["dropped"] == ["bad"]
    assert params["group"] == "week"
    assert params["scope"] == "history"
    assert params["from"] == "2026-01-01"
    assert params["to"] == "2026-03-31"

    # Unknown params / invalid group / scope fall back to defaults.
    fallback = parse_deeplink_params("?group=decade&scope=bogus&nope=1")
    assert fallback["group"] == "day"
    assert fallback["scope"] == "activity"


def test_parse_deeplink_missing_wba() -> None:
    """No wba_ids yields an empty, non-crashing selection."""
    params = parse_deeplink_params(None)
    assert params["wba_ids"] == []
    assert params["dropped"] == []
    assert selection_from_wba_ids(params["wba_ids"]) == []
    # Ids are deduped and capped through add_selection.
    assert len(selection_from_wba_ids(["mock::Person::alice"] * 3)) == 1


def test_parse_deeplink_custom_dates() -> None:
    """A reversed or partial date pair falls back to All time (no bounds)."""
    reversed_pair = parse_deeplink_params("?from=2026-05-01&to=2026-01-01")
    assert reversed_pair["from"] is None and reversed_pair["to"] is None

    partial = parse_deeplink_params("?from=2026-01-01")
    assert partial["from"] is None and partial["to"] is None


def test_is_valid_wba_id() -> None:
    """Mirrors service.parse_wba_id (first two :: split; all parts non-empty)."""
    assert is_valid_wba_id("jira::Person::x") is True
    assert is_valid_wba_id("github::PullRequest::org/repo#1") is True
    assert is_valid_wba_id("bad") is False
    assert is_valid_wba_id("a::b") is False
    assert is_valid_wba_id("jira::::x") is False
    assert is_valid_wba_id("::Person::x") is False


# ---------------------------------------------------------------------------
# card helpers
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


# ---------------------------------------------------------------------------
# popup payload
# ---------------------------------------------------------------------------


def test_popup_fields_from_event() -> None:
    """The popup payload includes a source link only when the event has a url."""
    with_url = popup_fields(
        {
            "summary": "Reviewed PR",
            "relationship_type": "REVIEWED",
            "entity_type": "PullRequest",
            "source": "github",
            "url": "https://example.com/pr/1",
        },
        "Mar 15, 2026 2:30 PM",
    )
    assert with_url["url"] == "https://example.com/pr/1"
    assert with_url["relationship"] == "Reviewed"
    assert with_url["entity_type"] == "PR"
    assert with_url["datetime"] == "Mar 15, 2026 2:30 PM"

    without_url = popup_fields(
        {"summary": None, "relationship_type": "CREATED", "entity_type": "File"},
        "",
    )
    assert "url" not in without_url
    assert without_url["summary"] == "Created · File"


# ---------------------------------------------------------------------------
# idle runs
# ---------------------------------------------------------------------------


def test_idle_run_label_days_weeks_months() -> None:
    """Idle-run labels use the right unit + count for each granularity."""
    day_run = {
        "count": 3,
        "start_ordinal": date(2026, 3, 12).toordinal(),
        "end_ordinal": date(2026, 3, 14).toordinal(),
        "granularity": "day",
    }
    assert idle_run_label(day_run) == "Mar 12 – 14 · 3 days no activity"

    week_start = date(2026, 3, 9)
    week_start -= timedelta(days=week_start.weekday())
    week0 = week_start.toordinal() // 7
    week_run = {
        "count": 2,
        "start_ordinal": week0,
        "end_ordinal": week0 + 1,
        "granularity": "week",
    }
    assert idle_run_label(week_run).endswith("2 weeks no activity")

    month_run = {
        "count": 1,
        "start_ordinal": 2026 * 12 + 3,
        "end_ordinal": 2026 * 12 + 3,
        "granularity": "month",
    }
    assert idle_run_label(month_run) == "Mar 2026 · 1 month no activity"


def test_idle_expansion_toggle() -> None:
    """Toggling a run key expands only that run and never duplicates keys."""
    key = "day:24313:24315"
    assert toggle_expanded([], key) == [key]
    assert toggle_expanded(["day:1:2"], key) == ["day:1:2", key]
    assert toggle_expanded([key, "day:1:2"], key) == ["day:1:2"]


def test_idle_run_key_is_stable() -> None:
    """A run's key is derived from granularity + span."""
    run = {"granularity": "day", "start_ordinal": 5, "end_ordinal": 9}
    assert idle_run_key(run) == "day:5:9"


# ---------------------------------------------------------------------------
# cell overflow
# ---------------------------------------------------------------------------


def test_cap_cell_hidden_count() -> None:
    """Cells cap at MAX_CELL_CARDS; the toggle predicate keys on (row, lane)."""
    events = [{"signal_id": str(index)} for index in range(21)]
    visible, hidden = cap_cell(events)
    assert len(visible) == MAX_CELL_CARDS
    assert hidden == 21 - MAX_CELL_CARDS
    # Nothing hidden below (and at) the cap.
    assert cap_cell(events[:MAX_CELL_CARDS]) == (events[:MAX_CELL_CARDS], 0)
    assert cap_cell(events[:2])[1] == 0
    # A non-positive cap disables the overflow.
    assert cap_cell(events, 0) == (events, 0)

    key = cell_expansion_key("2026-03-15", "wba-1")
    assert key == "2026-03-15|wba-1"
    assert (key in [key]) is True
    assert (key in [cell_expansion_key("2026-03-15", "wba-2")]) is False


# ---------------------------------------------------------------------------
# pagination
# ---------------------------------------------------------------------------


def test_merge_lane_page_dedup() -> None:
    """Overlapping signal_ids are not double-counted."""
    lane = {"wba_id": "w1", "events": [{"signal_id": "a"}, {"signal_id": "b"}]}
    page = {"events": [{"signal_id": "b"}, {"signal_id": "c"}], "next_cursor": "cur"}
    merged = merge_lane_page(lane, page)
    assert [event["signal_id"] for event in merged["events"]] == ["a", "b", "c"]


def test_merge_updates_cursor() -> None:
    """A non-empty page stores the echoed cursor; an empty page clears it."""
    lane = {"wba_id": "w1", "events": [{"signal_id": "a"}], "next_cursor": "old"}
    full = merge_lane_page(lane, {"events": [{"signal_id": "b"}], "next_cursor": "new"})
    assert full["next_cursor"] == "new"

    # Optimistic-cursor trap: full previous page, but the next page is empty.
    exhausted = merge_lane_page(
        {**lane, "next_cursor": "old"}, {"events": [], "next_cursor": "echo"}
    )
    assert exhausted["next_cursor"] is None
    assert len(exhausted["events"]) == 1


def test_merge_keeps_distinct_events_sharing_signal_id() -> None:
    """One signal can yield several actions for a lane; all must survive a merge.

    Regression for the signal_id-only de-dup key, which treated the second
    action of the same signal as a duplicate and dropped it.
    """
    existing = _event("s1", "2026-03-15T10:00:00+00:00")
    lane = {"wba_id": "mock::Person::alice", "events": [existing]}
    page = {
        "events": [
            {**_event("s1", "2026-03-14T10:00:00+00:00"), "relationship_type": "ASSIGNED"}
        ],
        "next_cursor": "cur",
    }
    merged = merge_lane_page(lane, page)
    assert len(merged["events"]) == 2
    assert {event["signal_id"] for event in merged["events"]} == {"s1"}
    assert {event["relationship_type"] for event in merged["events"]} == {"CREATED", "ASSIGNED"}


def test_merge_keeps_same_signal_split_across_pages() -> None:
    """Two actions of one signal differing only by entity_type both survive."""
    existing = {**_event("s2", "2026-03-15T10:00:00+00:00"), "entity_type": "Issue"}
    lane = {"wba_id": "mock::Person::alice", "events": [existing]}
    page = {
        "events": [
            {**_event("s2", "2026-03-14T10:00:00+00:00"), "entity_type": "PullRequest"}
        ],
        "next_cursor": None,
    }
    merged = merge_lane_page(lane, page)
    assert len(merged["events"]) == 2
    assert {event["entity_type"] for event in merged["events"]} == {"Issue", "PullRequest"}


def test_merge_still_drops_identical_duplicate() -> None:
    """A genuinely repeated row is still collapsed (the reason de-dup exists)."""
    event = _event("s3", "2026-03-15T10:00:00+00:00")
    lane = {"wba_id": "mock::Person::alice", "events": [event]}
    page = {"events": [dict(event)], "next_cursor": "cur"}
    merged = merge_lane_page(lane, page)
    assert len(merged["events"]) == 1


def test_load_more_hidden_when_all_exhausted() -> None:
    """has_more is true while any lane still has a cursor."""
    assert has_more([{"next_cursor": "c"}, {"next_cursor": None}]) is True
    assert has_more([{"next_cursor": None}, {"next_cursor": None}]) is False
    assert has_more([]) is False


# ---------------------------------------------------------------------------
# time range
# ---------------------------------------------------------------------------


def test_resolve_range_all_time() -> None:
    """All time (and any non-custom value) yields no lower bound, ending at ``now``."""
    now = datetime(2026, 3, 31, 12, 0, tzinfo=timezone.utc)
    for value in (ALL_TIME, "bogus", ""):
        start, end = resolve_range(value, now=now)
        assert start is None
        assert end == now


def test_resolve_range_custom() -> None:
    """Custom dates pass through (start 00:00, end 23:59:59 UTC); reversed rejected."""
    start, end = resolve_range("custom", "2026-03-01", "2026-03-15")
    assert start == datetime(2026, 3, 1, 0, 0, 0, tzinfo=timezone.utc)
    assert end == datetime(2026, 3, 15, 23, 59, 59, tzinfo=timezone.utc)

    with pytest.raises(ValueError):
        resolve_range("custom", "2026-03-15", "2026-03-01")
    with pytest.raises(ValueError):
        resolve_range("custom", "2026-03-01", None)


# ---------------------------------------------------------------------------
# group by
# ---------------------------------------------------------------------------


def test_period_key_week_iso() -> None:
    """Weeks use ISO (Monday-start) keys; any day in the week maps to its Monday."""
    some_day = date(2026, 3, 12)
    monday = some_day - timedelta(days=some_day.weekday())
    sunday = monday + timedelta(days=6)
    assert period_key(datetime(monday.year, monday.month, monday.day), "week") == (
        monday.isoformat()
    )
    assert period_key(
        datetime(sunday.year, sunday.month, sunday.day), "week"
    ) == monday.isoformat()


def test_period_key_month() -> None:
    """Month keys are ``YYYY-MM`` and labels are 'Month YYYY'."""
    assert period_key(datetime(2026, 3, 15), "month") == "2026-03"
    assert period_label("2026-03", "month") == "March 2026"


def test_regroup_preserves_events() -> None:
    """Total event count is unchanged across day/week/month regroupings."""
    events = [
        _event(f"s{i}", f"2026-03-{10 + i:02d}T09:00:00+00:00") for i in range(8)
    ]
    lanes = [_lane("a", events)]
    totals = {
        granularity: sum(
            len(cell)
            for row in build_grid(lanes, granularity, _UTC)
            for cell in row["cells"].values()
        )
        for granularity in ("day", "week", "month")
    }
    assert totals == {"day": 8, "week": 8, "month": 8}

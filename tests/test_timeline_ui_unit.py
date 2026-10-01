"""Unit tests for the Activity Timeline UI — geometry, layout, and callbacks.

These tests exercise the pure geometry functions and the static layout with no
network or database dependency.  Callback logic that touches the API is tested
with a mocked ``requests`` layer.

Run with:
    pytest -m unit tests/test_timeline_ui_unit.py -v
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from dash import html

from app.dash_app.pages.timeline import geometry
from app.dash_app.pages.timeline.geometry import (
    DEFAULT_PX_PER_DAY,
    GAP_BREAK_PX,
    MIN_CARD_HEIGHT_PX,
    build_compressed_axis_markers,
    build_time_axis_markers,
    compute_gap_threshold_days,
    compute_lane_layout,
)
from app.dash_app.pages.timeline.layout import (
    DEFAULT_PERSON_ONLY,
    DEFAULT_TIME_RANGE,
    TIME_RANGE_PRESETS,
    get_layout,
)
from app.dash_app.pages.timeline.callbacks import (
    _build_chips,
    _build_event_card,
    _build_lane,
    _build_swimlane,
    _has_more_pages,
    _resolve_time_range,
)

pytestmark = pytest.mark.unit

UTC = timezone.utc


def _dt(day: int, hour: int = 12) -> datetime:
    """Helper: a UTC datetime in March 2026."""
    return datetime(2026, 3, day, hour, 0, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Geometry — gap threshold
# ---------------------------------------------------------------------------


class TestGapThreshold:
    def test_fewer_than_two_events_returns_minimum(self) -> None:
        assert compute_gap_threshold_days([]) == geometry.MIN_GAP_THRESHOLD_DAYS
        assert compute_gap_threshold_days([_dt(1)]) == geometry.MIN_GAP_THRESHOLD_DAYS

    def test_dense_events_use_median_multiplier(self) -> None:
        # 5 events, 1 day apart → median spacing 1 day → threshold 2 days.
        times = [_dt(1 + i) for i in range(5)]
        assert compute_gap_threshold_days(times) == pytest.approx(2.0)

    def test_sparse_events_capped_at_absolute_max(self) -> None:
        # 2 events 10 days apart → median 10 → 2*10=20, capped at 7 days.
        times = [_dt(1), _dt(11)]
        assert compute_gap_threshold_days(times) == pytest.approx(
            geometry.ABSOLUTE_MAX_GAP_DAYS
        )

    def test_naive_datetimes_normalized(self) -> None:
        times = [datetime(2026, 3, 1, 12), datetime(2026, 3, 2, 12)]
        assert compute_gap_threshold_days(times) == pytest.approx(2.0)


# ---------------------------------------------------------------------------
# Geometry — lane layout
# ---------------------------------------------------------------------------


class TestLaneLayout:
    def test_empty_events_produce_empty_layout(self) -> None:
        layout = compute_lane_layout(
            [],
            range_start=_dt(1),
            range_end=_dt(30),
        )
        assert layout.cards == []
        assert layout.total_height == 0.0
        assert layout.gap_breaks == 0

    def test_single_event_positioned_at_offset(self) -> None:
        # Event at day 11 of a 30-day range. The 10-day leading gap exceeds
        # the threshold, so it is compressed: the card sits right after the
        # gap break instead of 10 days (320px) down.
        layout = compute_lane_layout(
            [_dt(11)],
            range_start=_dt(1),
            range_end=_dt(31),
        )
        assert len(layout.cards) == 1
        assert layout.cards[0].gap_before is True
        assert layout.cards[0].gap_days == pytest.approx(10.0)
        assert layout.cards[0].top == pytest.approx(GAP_BREAK_PX)
        assert layout.cards[0].height == MIN_CARD_HEIGHT_PX

    def test_single_event_near_range_start_not_compressed(self) -> None:
        # Event 1 day into the range → leading gap below threshold → no break.
        layout = compute_lane_layout(
            [_dt(2)],
            range_start=_dt(1),
            range_end=_dt(31),
        )
        assert len(layout.cards) == 1
        assert layout.cards[0].gap_before is False
        assert layout.cards[0].top == pytest.approx(DEFAULT_PX_PER_DAY)

    def test_dense_events_no_gap_breaks(self) -> None:
        # 5 events 1 day apart → no compression.
        times = [_dt(1 + i) for i in range(5)]
        layout = compute_lane_layout(
            times,
            range_start=_dt(1),
            range_end=_dt(31),
        )
        assert layout.gap_breaks == 0
        assert len(layout.cards) == 5
        # Cards are strictly increasing in top.
        tops = [c.top for c in layout.cards]
        assert tops == sorted(tops)
        assert all(not c.gap_before for c in layout.cards)

    def test_sparse_events_compressed_with_gap_break(self) -> None:
        # 2 events 10 days apart → gap exceeds threshold → compressed.
        times = [_dt(1), _dt(11)]
        layout = compute_lane_layout(
            times,
            range_start=_dt(1),
            range_end=_dt(31),
        )
        assert layout.gap_breaks == 1
        assert layout.cards[1].gap_before is True
        assert layout.cards[1].gap_days == pytest.approx(10.0)
        # Second card sits right after the gap break, not 10 days down.
        assert layout.cards[1].top == pytest.approx(
            layout.cards[0].top + MIN_CARD_HEIGHT_PX + geometry.CARD_GAP_PX + GAP_BREAK_PX
        )

    def test_total_height_grows_with_events(self) -> None:
        times = [_dt(1 + i) for i in range(3)]
        layout = compute_lane_layout(
            times,
            range_start=_dt(1),
            range_end=_dt(31),
        )
        # 3 cards 1 day apart: tops 0, 72, 144 → total 180.
        assert layout.total_height == pytest.approx(180.0)

    def test_out_of_range_events_clamped_to_edges(self) -> None:
        # Event before range start clamps to top 0. The 30-day gap between the
        # two events exceeds the 7-day absolute cap, so it is compressed: the
        # second card sits right after the gap break (cursor 40 + 28).
        layout = compute_lane_layout(
            [_dt(1), _dt(31)],
            range_start=_dt(5),
            range_end=_dt(25),
        )
        assert layout.cards[0].top == pytest.approx(0.0)
        assert layout.cards[1].gap_before is True
        assert layout.cards[1].top == pytest.approx(
            MIN_CARD_HEIGHT_PX + geometry.CARD_GAP_PX + GAP_BREAK_PX
        )

    def test_events_clustered_late_in_range_compress_leading_gap(self) -> None:
        # All events in the last 3 days of a 30-day window. The 27-day leading
        # gap must be compressed so the lane does not stretch to ~900px.
        times = [_dt(29), _dt(30), _dt(31)]
        layout = compute_lane_layout(
            times,
            range_start=_dt(1),
            range_end=_dt(31),
        )
        assert layout.gap_breaks == 1
        assert layout.cards[0].gap_before is True
        assert layout.cards[0].gap_days == pytest.approx(28.0)
        # First card sits right after the gap break, not 28 days (896px) down.
        assert layout.cards[0].top == pytest.approx(GAP_BREAK_PX)
        # Lane height stays compact (was ~1004px before the leading-gap fix).
        assert layout.total_height < 300.0


# ---------------------------------------------------------------------------
# Geometry — time axis markers
# ---------------------------------------------------------------------------


class TestTimeAxisMarkers:
    def test_daily_markers_within_range(self) -> None:
        markers = build_time_axis_markers(_dt(1), _dt(3))
        assert len(markers) == 3
        assert markers[0].label == "Mar 01"
        assert markers[2].label == "Mar 03"
        assert markers[0].top == pytest.approx(0.0)
        # Range starts at noon; day 2's marker is at midnight = 0.5 days later.
        assert markers[1].top == pytest.approx(0.5 * DEFAULT_PX_PER_DAY)

    def test_markers_align_to_midnight(self) -> None:
        # Range starts mid-day; first marker is at midnight of that day.
        markers = build_time_axis_markers(
            datetime(2026, 3, 1, 14, 0, 0, tzinfo=UTC),
            datetime(2026, 3, 2, 14, 0, 0, tzinfo=UTC),
        )
        assert len(markers) == 2
        assert markers[0].label == "Mar 01"
        assert markers[0].top == pytest.approx(0.0)
        # Day 2's marker at midnight = 10 hours after start = 10/24 * px_per_day.
        assert markers[1].top == pytest.approx((10 / 24) * DEFAULT_PX_PER_DAY)


class TestCompressedAxisMarkers:
    def test_empty_events_produce_no_markers(self) -> None:
        markers = build_compressed_axis_markers(
            [],
            range_start=_dt(1),
            range_end=_dt(31),
        )
        assert markers == []

    def test_markers_only_within_event_span(self) -> None:
        # Events clustered in the last 3 days → only 3 markers, not 31.
        times = [_dt(29), _dt(30), _dt(31)]
        markers = build_compressed_axis_markers(
            times,
            range_start=_dt(1),
            range_end=_dt(31),
        )
        assert len(markers) == 3
        assert [m.label for m in markers] == ["Mar 29", "Mar 30", "Mar 31"]

    def test_markers_handle_newest_first_input(self) -> None:
        # The API returns events newest-first; the builder must sort.
        times = [_dt(31), _dt(30), _dt(29)]
        markers = build_compressed_axis_markers(
            times,
            range_start=_dt(1),
            range_end=_dt(31),
        )
        assert [m.label for m in markers] == ["Mar 29", "Mar 30", "Mar 31"]

    def test_markers_compress_leading_gap(self) -> None:
        # Events 28 days into the range → leading gap compressed, first marker
        # sits right after the gap break.
        times = [_dt(29), _dt(30), _dt(31)]
        markers = build_compressed_axis_markers(
            times,
            range_start=_dt(1),
            range_end=_dt(31),
        )
        assert markers[0].top == pytest.approx(GAP_BREAK_PX)


# ---------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------


def _walk_tree(node: Any) -> list[Any]:
    """Recursively collect all Dash component nodes in a layout tree."""
    seen: list[Any] = []

    def walk(curr: Any) -> None:
        if curr is None:
            return
        seen.append(curr)
        children = getattr(curr, "children", None)
        if children is None:
            return
        if isinstance(children, (list, tuple)):
            for child in children:
                walk(child)
        else:
            walk(children)

    walk(node)
    return seen


class TestLayout:
    def test_layout_renders_without_crash(self) -> None:
        layout = get_layout()
        assert isinstance(layout, html.Div)

    def test_layout_contains_expected_component_ids(self) -> None:
        layout = get_layout()
        nodes = _walk_tree(layout)
        node_ids = {getattr(n, "id", None) for n in nodes if hasattr(n, "id")}

        expected = {
            "timeline-entity-search",
            "timeline-suggestions",
            "timeline-person-only",
            "timeline-selected-chips",
            "timeline-clear-btn",
            "timeline-time-range",
            "timeline-custom-range",
            "timeline-lanes-container",
            "timeline-load-more-btn",
            "timeline-selected-entities",
            "timeline-lane-state",
            "timeline-loading",
            "timeline-last-params",
            "timeline-alert-region",
        }
        assert expected.issubset(node_ids)

    def test_default_time_range_is_30d(self) -> None:
        assert DEFAULT_TIME_RANGE == "30d"
        assert TIME_RANGE_PRESETS["30d"] == 30

    def test_person_only_defaults_on(self) -> None:
        assert DEFAULT_PERSON_ONLY is True


# ---------------------------------------------------------------------------
# Callbacks — pure helpers
# ---------------------------------------------------------------------------


class TestResolveTimeRange:
    def test_preset_returns_window(self) -> None:
        start, end = _resolve_time_range("7d", None)
        assert end > start
        assert (end - start).days == 7

    def test_custom_range_parses_dates(self) -> None:
        start, end = _resolve_time_range(
            "custom",
            ["2026-03-01", "2026-03-10"],
        )
        assert start.year == 2026 and start.month == 3 and start.day == 1
        # End-of-day extension.
        assert end.hour == 23 and end.minute == 59

    def test_custom_range_missing_returns_none(self) -> None:
        assert _resolve_time_range("custom", None) is None
        assert _resolve_time_range("custom", [None, None]) is None

    def test_unknown_preset_falls_back_to_default(self) -> None:
        start, end = _resolve_time_range("bogus", None)
        assert (end - start).days == TIME_RANGE_PRESETS[DEFAULT_TIME_RANGE]


class TestHasMorePages:
    def test_empty_state(self) -> None:
        assert _has_more_pages({}) is False

    def test_all_exhausted(self) -> None:
        state = {
            "a": {"next_cursor": None},
            "b": {"next_cursor": None},
        }
        assert _has_more_pages(state) is False

    def test_any_pending(self) -> None:
        state = {
            "a": {"next_cursor": "abc"},
            "b": {"next_cursor": None},
        }
        assert _has_more_pages(state) is True


class TestBuildChips:
    def test_empty_entities_returns_empty_state(self) -> None:
        chips = _build_chips([])
        assert len(chips) == 1

    def test_chip_contains_remove_button(self) -> None:
        chips = _build_chips(
            [{"wba_id": "github::Person::alice", "label": "Alice Johnson"}]
        )
        assert len(chips) == 1
        nodes = _walk_tree(chips[0])
        ids = [getattr(n, "id", None) for n in nodes if hasattr(n, "id")]
        assert {"type": "timeline-chip-remove", "index": "github::Person::alice"} in ids


class TestBuildEventCard:
    def test_card_has_position_and_popup(self) -> None:
        card = _build_event_card(
            {
                "summary": "feat: add timeline",
                "relationship_type": "CREATED",
                "entity_type": "PullRequest",
                "source": "github",
                "event_time": "2026-03-15T14:30:00Z",
                "url": "https://github.com/org/repo/pull/142",
                "details": {"status": "open"},
            },
            top=10.0,
            height=36.0,
            lane_color="#2c5282",
            gap_before=False,
            gap_days=0.0,
        )
        assert card.style["top"] == "10.0px"
        assert card.style["height"] == "36.0px"
        assert "timeline-event-card" in card.className

    def test_gap_before_adds_class_and_data_attr(self) -> None:
        card = _build_event_card(
            {"summary": "x", "relationship_type": "C", "entity_type": "Issue"},
            top=50.0,
            height=36.0,
            lane_color="#2c5282",
            gap_before=True,
            gap_days=10.0,
        )
        assert "timeline-gap-before" in card.className
        props = card.to_plotly_json()["props"]
        assert props.get("data-gap-days") == "10.0"


class TestBuildLaneAndSwimlane:
    def test_lane_renders_header_and_body(self) -> None:
        lane, body_height = _build_lane(
            "github::Person::alice",
            {
                "events": [
                    {
                        "event_time": "2026-03-15T14:30:00Z",
                        "summary": "feat: add timeline",
                        "relationship_type": "CREATED",
                        "entity_type": "PullRequest",
                        "source": "github",
                    }
                ],
                "next_cursor": None,
                "label": "Alice Johnson",
                "avatar_url": None,
            },
            range_start=_dt(1),
            range_end=_dt(31),
            lane_color="#2c5282",
        )
        assert "timeline-lane" in lane.className
        assert body_height >= 120.0

    def test_empty_lane_renders_compact_state(self) -> None:
        lane, body_height = _build_lane(
            "github::Person::alice",
            {
                "events": [],
                "next_cursor": None,
                "label": "Alice",
                "avatar_url": None,
            },
            range_start=_dt(1),
            range_end=_dt(31),
            lane_color="#2c5282",
        )
        assert "timeline-lane" in lane.className
        # Empty lanes report 0 height so the axis is not stretched.
        assert body_height == 0.0
        nodes = _walk_tree(lane)
        assert any(
            getattr(n, "className", "") == "timeline-lane-empty"
            for n in nodes
        )

    def test_swimlane_empty_state(self) -> None:
        swimlane = _build_swimlane({}, range_start=_dt(1), range_end=_dt(31))
        assert isinstance(swimlane, html.Div)

    def test_swimlane_renders_lane_columns(self) -> None:
        state: dict[str, Any] = {
            "github::Person::alice": {
                "events": [],
                "next_cursor": None,
                "label": "Alice",
                "avatar_url": None,
            },
            "github::Person::bob": {
                "events": [],
                "next_cursor": None,
                "label": "Bob",
                "avatar_url": None,
            },
        }
        swimlane = _build_swimlane(state, range_start=_dt(1), range_end=_dt(31))
        nodes = _walk_tree(swimlane)
        lane_nodes = [
            n for n in nodes
            if getattr(n, "className", "") == "timeline-lane"
        ]
        assert len(lane_nodes) == 2

    def test_swimlane_axis_capped_to_lane_height(self) -> None:
        # Two empty lanes → max body height 0 → no axis markers rendered.
        state: dict[str, Any] = {
            "github::Person::alice": {
                "events": [],
                "next_cursor": None,
                "label": "Alice",
                "avatar_url": None,
            },
        }
        swimlane = _build_swimlane(state, range_start=_dt(1), range_end=_dt(31))
        nodes = _walk_tree(swimlane)
        marker_nodes = [
            n for n in nodes
            if getattr(n, "className", "") == "timeline-time-marker"
        ]
        assert marker_nodes == []
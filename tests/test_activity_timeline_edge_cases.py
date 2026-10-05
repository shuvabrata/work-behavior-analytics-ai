"""UI-12 — edge-case render sweep for the Activity Timeline grid.

Exercises the combinations the plan calls out (single lane, empty lanes, the
5-lane cap, a Custom range with no events, history scope, and the optimistic
cursor) to confirm the grid renders without error and degrades sensibly.
"""

from __future__ import annotations

from typing import Any
from zoneinfo import ZoneInfo

import pytest

from app.dash_app.pages.timeline.helpers import (
    build_grid,
    has_more,
    humanize_relationship,
    merge_lane_page,
)
from app.dash_app.pages.timeline.layout import build_grid_body
from app.dash_app.styles import get_theme_tokens

pytestmark = pytest.mark.unit

_EMPTY_NOTE = "No activity in this range"


def _event(
    signal_id: str, iso: str, *, relationship: str = "CREATED", summary: str = "event"
) -> dict[str, Any]:
    return {
        "signal_id": signal_id,
        "event_time": iso,
        "relationship_type": relationship,
        "summary": summary,
        "entity_type": "Person",
        "source": "github",
        "url": None,
        "details": {},
    }


def _lane(wba_id: str, events: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "wba_id": wba_id,
        "entity_type": "Person",
        "label": wba_id,
        "avatar_url": None,
        "events": events,
        "next_cursor": None,
    }


def _texts(node: Any) -> list[str]:
    """Collect every string rendered anywhere under *node*."""
    if isinstance(node, str):
        return [node]
    if isinstance(node, (list, tuple)):
        return [text for child in node for text in _texts(child)]
    children = getattr(node, "children", None)
    return _texts(children) if children is not None else []


def _render(lanes: list[dict[str, Any]], *, granularity: str = "day") -> list[Any]:
    tokens = get_theme_tokens("executive-light")
    colors = {str(lane["wba_id"]): "#3B82F6" for lane in lanes}
    rows = build_grid(lanes, granularity, ZoneInfo("UTC"))
    return build_grid_body(
        rows, lanes, colors, None, tokens, granularity=granularity
    )


def test_single_lane_renders() -> None:
    """One lane with events renders its cards and no empty note."""
    lanes = [_lane("a", [_event("s1", "2026-03-15T10:00:00+00:00")])]
    texts = _texts(_render(lanes))
    assert _EMPTY_NOTE not in texts


def test_one_lane_empty_shows_note() -> None:
    """A lane with no events gets the empty note; the active lane does not."""
    lanes = [
        _lane("a", [_event("s1", "2026-03-15T10:00:00+00:00")]),
        _lane("b", []),
    ]
    texts = _texts(_render(lanes))
    assert texts.count(_EMPTY_NOTE) == 1


def test_all_lanes_empty_in_range() -> None:
    """No rows at all still renders every lane (with the empty note)."""
    lanes = [_lane("a", []), _lane("b", [])]
    body = _render(lanes)
    assert _texts(body).count(_EMPTY_NOTE) == len(lanes)


def test_five_lanes_render() -> None:
    """The soft cap (5 lanes) renders one cell per lane per row."""
    lanes = [
        _lane(f"lane{index}", [_event(f"s{index}", "2026-03-15T10:00:00+00:00")])
        for index in range(5)
    ]
    body = _render(lanes)
    # One axis cell plus one cell per lane, per single period row.
    assert len(body) == 1 + len(lanes)


def test_custom_range_with_no_events() -> None:
    """An empty window (no events in the range) is the same as an empty grid."""
    body = _render([_lane("a", [])])
    assert _texts(body).count(_EMPTY_NOTE) == 1


def test_history_scope_person_state_change() -> None:
    """History events are STATE_CHANGE and humanize to 'Updated'."""
    assert humanize_relationship("STATE_CHANGE") == "Updated"
    lanes = [
        _lane(
            "a",
            [
                _event(
                    "s1",
                    "2026-03-15T10:00:00+00:00",
                    relationship="STATE_CHANGE",
                    summary="Alice Johnson",
                )
            ],
        )
    ]
    texts = _texts(_render(lanes))
    assert "Alice Johnson" in texts
    assert "Updated" in texts


def test_lane_exactly_limit_clears_cursor_on_empty_page() -> None:
    """A lane whose only page is exactly ``limit`` exposes a cursor; the next
    (empty) page clears it so "Load more" hides."""
    lane = {"wba_id": "a", "events": [{"signal_id": str(i)} for i in range(20)]}
    # Full first page -> server optimistically echoes a cursor.
    assert has_more([{**lane, "next_cursor": "cur"}]) is True
    merged = merge_lane_page(
        {**lane, "next_cursor": "cur"}, {"events": [], "next_cursor": "cur"}
    )
    assert merged["next_cursor"] is None
    assert has_more([merged]) is False

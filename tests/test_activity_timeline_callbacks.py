"""Unit tests for the Activity Timeline page's server callbacks.

These call the ``@callback``-decorated functions in
``app.dash_app.pages.timeline.callbacks`` directly with explicit arguments,
mirroring ``tests/test_collab_network_controls.py``. External collaborators
(``fetch_suggestions``, ``fetch_timeline``, ``fetch_effective_theme``) and the
Dash ``callback_context`` are patched **in the callbacks module's namespace**,
which is where the callbacks actually resolve them.

The clientside (JS) callbacks on the page are not (and cannot be) exercised
here.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest
from dash import no_update
from dash.exceptions import PreventUpdate

from app.dash_app.pages.timeline.api import TimelineFetchError
from app.dash_app.pages.timeline.callbacks import (
    apply_deeplink,
    load_more,
    load_timeline,
    populate_timeline_theme_store,
    render_grid,
    render_lanes,
    render_suggestions,
    reset_cell_expansion,
    toggle_cell,
    toggle_custom_range,
    toggle_idle_run,
    update_selection,
)


pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Fixtures / factories (shape mirrors tests/test_activity_timeline_ui_helpers.py)
# ---------------------------------------------------------------------------

_CB = "app.dash_app.pages.timeline.callbacks"


def _event(signal_id: str, iso: str, summary: str = "event") -> dict[str, Any]:
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


def _lane(wba_id: str, events: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "wba_id": wba_id,
        "entity_type": "Person",
        "label": wba_id,
        "avatar_url": None,
        "events": events,
        "next_cursor": None,
    }


def _selection_item(wba_id: str, label: str | None = None) -> dict[str, Any]:
    return {
        "wba_id": wba_id,
        "label": label or wba_id,
        "entity_type": "Person",
        "avatar_url": None,
    }


_ALICE = _selection_item("mock::Person::alice", "Alice")
_BOB = _selection_item("mock::Person::bob", "Bob")
_ALICE_SUGGESTION = {
    "wba_id": "mock::Person::alice",
    "label": "Alice",
    "entity_type": "Person",
    "source": "github",
    "avatar_url": None,
}


def _has_id(component: Any, target: str) -> bool:
    """Return whether ``target`` is the ``id`` of any node in the tree.

    Only string ids are compared; pattern-matching dict ids (which are
    unhashable) are skipped.
    """
    if getattr(component, "id", None) == target:
        return True
    children = getattr(component, "children", None)
    if children is None:
        return False
    if not isinstance(children, list):
        children = [children]
    return any(_has_id(child, target) for child in children)


# ---------------------------------------------------------------------------
# Step 2 — selection and suggestions
# ---------------------------------------------------------------------------


def test_render_suggestions_short_query_hides() -> None:
    """A sub-minimum query hides the dropdown and returns no rows."""
    children, style, store = render_suggestions("a")
    assert children == []
    assert style["display"] == "none"
    assert store == []


def test_render_suggestions_renders_rows() -> None:
    """Suggestion results render as rows and are echoed into the store."""
    with patch(f"{_CB}.fetch_suggestions", return_value=[_ALICE_SUGGESTION]):
        children, style, store = render_suggestions("alice")
    assert isinstance(children, list) and children
    assert style.get("display") != "none"
    assert store == [_ALICE_SUGGESTION]


def test_update_selection_adds_suggestion() -> None:
    """Clicking a suggestion adds it and clears the search box."""
    with patch(f"{_CB}.ctx") as mock_ctx:
        mock_ctx.triggered = [
            {
                "prop_id": (
                    '{"index": "mock::Person::alice", '
                    '"type": "timeline-suggestion"}.n_clicks'
                ),
                "value": 1,
            }
        ]
        store, input_value, alert = update_selection(
            [1], [], 0, [], [_ALICE_SUGGESTION]
        )
    assert [item["wba_id"] for item in store] == ["mock::Person::alice"]
    assert input_value == ""
    assert alert is None


def test_update_selection_is_idempotent_and_capped() -> None:
    """Re-adding an already-selected lane leaves the store unchanged."""
    existing = [
        {"wba_id": f"mock::Person::p{index}", "label": f"P{index}"}
        for index in range(5)
    ]
    existing[0] = _ALICE
    with patch(f"{_CB}.ctx") as mock_ctx:
        mock_ctx.triggered = [
            {
                "prop_id": (
                    '{"index": "mock::Person::alice", '
                    '"type": "timeline-suggestion"}.n_clicks'
                ),
                "value": 1,
            }
        ]
        first, _, _ = update_selection([1], [], 0, existing, [_ALICE_SUGGESTION])
        second, _, _ = update_selection([1], [], 0, first, [_ALICE_SUGGESTION])
    assert len(first) == 5
    assert len(second) == 5


def test_update_selection_remove_lane() -> None:
    """Removing a lane drops it and leaves the search box untouched."""
    with patch(f"{_CB}.ctx") as mock_ctx:
        mock_ctx.triggered = [
            {
                "prop_id": (
                    '{"index": "mock::Person::alice", '
                    '"type": "timeline-lane-remove"}.n_clicks'
                ),
                "value": 1,
            }
        ]
        store, input_value, alert = update_selection([], [1], 0, [_ALICE, _BOB], [])
    assert [item["wba_id"] for item in store] == ["mock::Person::bob"]
    assert input_value is no_update
    assert alert is None


def test_update_selection_clear_all() -> None:
    """The clear-all control empties the selection store."""
    with patch(f"{_CB}.ctx") as mock_ctx:
        mock_ctx.triggered = [
            {"prop_id": "timeline-clear-all.n_clicks", "value": 1}
        ]
        store, input_value, alert = update_selection([], [], 1, [_ALICE], [])
    assert store == []
    assert input_value is no_update
    assert alert is None


def test_update_selection_no_trigger_raises() -> None:
    """No changed input raises PreventUpdate (not a real interaction)."""
    with patch(f"{_CB}.ctx") as mock_ctx:
        mock_ctx.triggered = []
        with pytest.raises(PreventUpdate):
            update_selection([], [], 0, [_ALICE], [])


# ---------------------------------------------------------------------------
# Step 3 — fetch, paging, deep-link
# ---------------------------------------------------------------------------


def test_load_timeline_empty_selection() -> None:
    """No selected lanes clears the data store and stops the spinner."""
    assert load_timeline([], None, "all", "activity", None, None) == (
        None,
        [],
        False,
        no_update,
    )


def test_load_timeline_success() -> None:
    """A successful fetch stores the lanes, params, and clears the alert slot."""
    lane = _lane("mock::Person::alice", [_event("s1", "2026-03-15T10:00:00+00:00")])
    with patch(
        f"{_CB}.fetch_timeline",
        return_value={"lanes": [lane], "meta": {"time_range": {}}},
    ):
        data, alerts, loading, selection = load_timeline(
            [_ALICE], None, "all", "activity", None, None
        )
    assert [item["wba_id"] for item in data["lanes"]] == ["mock::Person::alice"]
    assert data["params"]["scope"] == "activity"
    assert alerts == []
    assert loading is False
    assert selection is no_update


def test_load_timeline_error_without_wba_id() -> None:
    """A transport error shows a danger alert and leaves the data untouched."""
    with patch(
        f"{_CB}.fetch_timeline", side_effect=TimelineFetchError("boom")
    ):
        data, alerts, loading, selection = load_timeline(
            [_ALICE], None, "all", "activity", None, None
        )
    assert data is no_update
    assert len(alerts) == 1
    assert alerts[0].color == "danger"
    assert selection is no_update


def test_load_timeline_drops_bad_lane() -> None:
    """An error carrying a wba_id (with >1 lane) drops that lane as a warning."""
    with patch(
        f"{_CB}.fetch_timeline",
        side_effect=TimelineFetchError("bad", wba_id="mock::Person::bob"),
    ):
        data, alerts, loading, selection = load_timeline(
            [_ALICE, _BOB], None, "all", "activity", None, None
        )
    assert data is no_update
    assert len(alerts) == 1
    assert alerts[0].color == "warning"
    assert [item["wba_id"] for item in selection] == ["mock::Person::alice"]


def test_load_timeline_missing_custom_dates_is_silent() -> None:
    """Custom selected with no dates yet: no alert, last render kept."""
    data, alerts, loading, selection = load_timeline(
        [_ALICE], None, "custom", "activity", None, None
    )
    assert data is no_update
    assert alerts == []
    assert loading is False
    assert selection is no_update


def test_load_timeline_partial_custom_range_is_silent() -> None:
    """Custom selected with only the start date: no alert until both are set."""
    data, alerts, loading, selection = load_timeline(
        [_ALICE], None, "custom", "activity", "2026-03-15", None
    )
    assert data is no_update
    assert alerts == []
    assert loading is False
    assert selection is no_update


def test_load_timeline_invalid_custom_range_alerts() -> None:
    """A reversed Custom range leaves the data untouched but raises an alert."""
    data, alerts, loading, selection = load_timeline(
        [_ALICE], None, "custom", "activity", "2026-03-15", "2026-03-01"
    )
    assert data is no_update
    assert len(alerts) == 1
    assert alerts[0].color == "danger"
    assert loading is False
    assert selection is no_update


def test_load_more_no_cursor_clears_overlay() -> None:
    """Load more with no lane cursor clears the loading overlay, no fetch."""
    data = {"lanes": [{"next_cursor": None}], "params": {}}
    assert load_more(1, data, [_ALICE], "activity", "all", None, None, None) == (
        no_update,
        no_update,
        False,
    )


def test_load_more_guard_clears_overlay() -> None:
    """Load more with an empty data store clears the overlay rather than wedging."""
    assert load_more(1, None, [_ALICE], "activity", "all", None, None, None) == (
        no_update,
        no_update,
        False,
    )


def test_load_more_merges_page() -> None:
    """A next page is appended to the lane and the alert slot stays empty."""
    lane = {
        **_lane("mock::Person::alice", [_event("s1", "2026-03-15T10:00:00+00:00")]),
        "next_cursor": "c",
    }
    data = {"lanes": [lane], "params": {"limit": 20}}
    page = {
        "lanes": [
            {
                "events": [_event("s2", "2026-03-14T10:00:00+00:00")],
                "next_cursor": "c2",
            }
        ]
    }
    with patch(f"{_CB}.fetch_timeline", return_value=page):
        merged_data, alerts, loading = load_more(
            1, data, [_ALICE], "activity", "all", None, None, None
        )
    assert alerts == []
    assert loading is False
    signal_ids = [
        event["signal_id"] for event in merged_data["lanes"][0]["events"]
    ]
    assert signal_ids == ["s1", "s2"]


def test_load_more_uses_stored_scope_not_live_state() -> None:
    """Paging resumes under the stored query scope/range, not the live toolbar."""
    lane = {
        **_lane("mock::Person::alice", [_event("s1", "2026-03-15T10:00:00+00:00")]),
        "next_cursor": "c",
    }
    data = {
        "lanes": [lane],
        "params": {
            "scope": "history",
            "from": None,
            "to": "2026-03-31T12:00:00+00:00",
            "limit": 20,
        },
    }
    with patch(f"{_CB}.fetch_timeline", return_value={"lanes": []}) as mock_call:
        load_more(1, data, [_ALICE], "activity", "all", None, None, None)
    assert mock_call.call_args.kwargs["scope"] == "history"
    assert mock_call.call_args.kwargs["to_iso"] == "2026-03-31T12:00:00+00:00"


def test_load_more_uses_stored_mock() -> None:
    """The stored mock scenario wins over the live URL query param."""
    lane = {
        **_lane("mock::Person::alice", [_event("s1", "2026-03-15T10:00:00+00:00")]),
        "next_cursor": "c",
    }
    data = {
        "lanes": [lane],
        "params": {
            "scope": "activity",
            "from": None,
            "to": "2026-03-31T12:00:00+00:00",
            "limit": 20,
            "mock": "even",
        },
    }
    with patch(f"{_CB}.fetch_timeline", return_value={"lanes": []}) as mock_call:
        load_more(1, data, [_ALICE], "activity", "all", None, None, "?mock=other")
    assert mock_call.call_args.kwargs["mock"] == "even"


def test_load_timeline_stores_mock_in_params() -> None:
    """load_timeline records the mock scenario in the stored params."""
    with patch(f"{_CB}.fetch_timeline", return_value={"lanes": [], "meta": {}}):
        data, _, _, _ = load_timeline(
            [_ALICE], "?mock=even", "all", "activity", None, None
        )
    assert data["params"]["mock"] == "even"


def test_apply_deeplink_applied_is_noop() -> None:
    """Once applied, a second URL change is ignored."""
    with pytest.raises(PreventUpdate):
        apply_deeplink("?wba_ids=mock::Person::alice", True)


def test_apply_deeplink_seeds_state() -> None:
    """A deep-link seeds the selection and toolbar from the URL."""
    selection, scope, group, range_value, range_from, range_to, applied, alerts = (
        apply_deeplink("?wba_ids=mock::Person::alice&group=week&scope=history", False)
    )
    assert [item["wba_id"] for item in selection] == ["mock::Person::alice"]
    assert scope == "history"
    assert group == "week"
    assert range_value == "all"
    assert range_from is None and range_to is None
    assert applied is True
    assert alerts == []


def test_apply_deeplink_warns_on_dropped_ids() -> None:
    """Malformed ids are dropped and surfaced as a warning alert."""
    selection, *_rest = apply_deeplink("?wba_ids=mock::Person::alice,bad", False)
    alerts = _rest[-1]
    assert len(alerts) == 1
    assert alerts[0].color == "warning"
    assert [item["wba_id"] for item in selection] == ["mock::Person::alice"]


# ---------------------------------------------------------------------------
# Step 4 — grid render, expansion, theme
# ---------------------------------------------------------------------------


def test_render_grid_empty_data() -> None:
    """No stored data yields an empty body."""
    assert render_grid(None, [_ALICE], "executive-light", None, [], [], "day") == []


def test_render_grid_renders_and_shows_load_more() -> None:
    """Two periods render a body, and a live cursor appends the Load more button."""
    lane = {
        **_lane(
            "mock::Person::alice",
            [
                _event("s1", "2026-03-15T10:00:00+00:00"),
                _event("s2", "2026-03-10T10:00:00+00:00"),
            ],
        ),
        "next_cursor": "c",
    }
    data = {"lanes": [lane], "params": {}, "time_range": {}}
    body = render_grid(data, [_ALICE], "executive-light", None, [], [], "day")
    assert isinstance(body, list) and body
    assert any(_has_id(child, "timeline-load-more") for child in body)


def test_toggle_cell() -> None:
    """A cell toggle adds then removes its ``row|lane`` expansion key."""
    prop_id = (
        '{"index": "2026-03-15|mock::Person::alice", '
        '"type": "timeline-cell-toggle"}.n_clicks'
    )
    key = "2026-03-15|mock::Person::alice"
    with patch(f"{_CB}.ctx") as mock_ctx:
        mock_ctx.triggered = [{"prop_id": prop_id, "value": 1}]
        assert toggle_cell([1], []) == [key]
        assert toggle_cell([1], [key]) == []


def test_toggle_idle_run() -> None:
    """An idle-run toggle adds then removes its run key."""
    prop_id = (
        '{"index": "day:1:3", "type": "timeline-idle-toggle"}.n_clicks'
    )
    with patch(f"{_CB}.ctx") as mock_ctx:
        mock_ctx.triggered = [{"prop_id": prop_id, "value": 1}]
        assert toggle_idle_run([1], []) == ["day:1:3"]
        assert toggle_idle_run([1], ["day:1:3"]) == []


def test_reset_cell_expansion_clears() -> None:
    """Any data/group/scope change collapses every expanded cell."""
    assert reset_cell_expansion(1, 2, 3) == []


def test_toggle_custom_range() -> None:
    """Only the Custom range reveals the date pickers."""
    assert toggle_custom_range("custom")["display"] == "flex"
    assert toggle_custom_range("all")["display"] == "none"


def test_render_lanes_headers_and_visibility() -> None:
    """Each selected lane gets a header; visibility tracks the selection."""
    empty_children, empty_state_style, *_rest = render_lanes([], "executive-light")
    assert len(empty_children) == 1  # just the axis corner
    assert empty_state_style == {}  # empty state visible

    children, empty_state_style, hint, full, clear_style, grid_style, _inner = (
        render_lanes([_ALICE], "executive-light")
    )
    assert len(children) == 2  # axis corner + one lane header
    assert empty_state_style == {"display": "none"}
    assert hint == ""
    assert full is False
    assert "display" not in clear_style
    assert "display" not in grid_style


def test_populate_timeline_theme_store() -> None:
    """The effective graph theme is fetched for the active theme name."""
    effective = {"nodes": {"Page": {"background-color": "#123456"}}}
    with patch(f"{_CB}.fetch_effective_theme", return_value=effective):
        assert populate_timeline_theme_store("executive-light") == effective

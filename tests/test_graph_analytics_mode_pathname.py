"""Unit tests for the analytics-mode pathname gate on the graph page."""

from __future__ import annotations

from typing import Any

import pytest

from ui.pages.graph.callbacks.analytics_mode import (
    toggle_query_panel_for_analytics_mode,
)

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("pathname", "search", "expected"),
    [
        ("/app/graph/", None, ({}, {})),
        ("/app/graph/", "?mode=analytics", ({"display": "none"}, {"display": "none"})),
        ("/app/graph", "?mode=analytics", ({"display": "none"}, {"display": "none"})),
        ("/app/graphs", None, ({}, {})),
        ("/app/graph/x", None, ({}, {})),
        (None, None, ({}, {})),
    ],
)
def test_toggle_gate(
    pathname: str | None,
    search: str | None,
    expected: tuple[dict[str, Any], dict[str, Any]],
) -> None:
    result = toggle_query_panel_for_analytics_mode(pathname, search)
    assert result == expected

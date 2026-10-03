"""Unit tests for the Activity Timeline UI-0 scaffold helpers."""

from __future__ import annotations

import pytest
from dash import html

from app.analytics.registry import TIMELINE_ANALYTIC
from app.dash_app.pages.timeline import get_layout


pytestmark = pytest.mark.unit


def test_timeline_analytic_href() -> None:
    """The timeline analytic points at the dedicated timeline route."""
    assert TIMELINE_ANALYTIC.href == "/app/analytics/timeline"


def test_timeline_layout_renders() -> None:
    """The UI-0 scaffold renders as a Dash Div."""
    layout = get_layout()
    assert isinstance(layout, html.Div)

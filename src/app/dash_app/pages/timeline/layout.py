"""Layout scaffold for the Activity Timeline page.

UI-0 renders a reachable but empty page: page header, selector-bar
placeholder, empty state, and placeholder stores. No data fetching happens
here — the selector, fetch, and render behaviour lands in UI-1 onwards.
"""

from __future__ import annotations

from dash import dcc, html

from app.dash_app.components.common import create_empty_state, create_page_header
from app.dash_app.styles import SPACING_SMALL


def get_layout() -> html.Div:
    """Return the empty Activity Timeline page scaffold."""
    return html.Div(
        [
            create_page_header(
                [("Analytics", "/app/analytics"), ("Timeline", None)],
                "Compare the chronological activity of people and objects side by side.",
            ),
            html.Div(
                id="timeline-selector-bar",
                style={"marginBottom": SPACING_SMALL},
            ),
            create_empty_state("Add people or objects to compare their activity."),
            dcc.Store(id="timeline-selected-store", storage_type="memory", data=[]),
            dcc.Store(id="timeline-data-store", storage_type="memory", data=None),
            dcc.Store(id="timeline-theme-store", storage_type="memory", data=None),
            dcc.Store(id="timeline-expanded-runs-store", storage_type="memory", data=[]),
            dcc.Store(id="timeline-cell-expansion-store", storage_type="memory", data=[]),
            dcc.Store(id="timeline-deeplink-applied", storage_type="memory", data=False),
        ]
    )

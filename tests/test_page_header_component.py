"""Unit tests for the compact page header component (create_page_header)."""

from __future__ import annotations

import pytest

from dash import dcc, html

from app.dash_app.components.common import create_page_header
from app.dash_app.styles import (
    COLOR_CHARCOAL_MEDIUM,
    COLOR_GRAY_MEDIUM,
    COLOR_NAVY,
    COMPACT_PAGE_HEADER_STYLE,
)


def _flatten_children(node) -> list:
    """Recursively collect all child nodes into a flat list."""
    seen: list = []

    def walk(item) -> None:
        seen.append(item)
        children = getattr(item, "children", None)
        if children is None:
            return
        if isinstance(children, (list, tuple)):
            for child in children:
                walk(child)
        else:
            walk(children)

    walk(node)
    return seen


@pytest.mark.unit
def test_returns_div_with_compact_style() -> None:
    """The header is an html.Div using the compact page header style."""
    header = create_page_header([("Settings", None)])
    assert isinstance(header, html.Div)
    assert header.style == COMPACT_PAGE_HEADER_STYLE


@pytest.mark.unit
def test_clickable_segment_renders_as_link() -> None:
    """Segments with an href render as clickable dcc.Link in navy."""
    header = create_page_header(
        [("Settings", "/app/settings"), ("Graph Styling", None)]
    )
    nodes = _flatten_children(header)
    links = [n for n in nodes if isinstance(n, dcc.Link)]
    assert len(links) == 1
    assert links[0].children == "Settings"
    assert links[0].href == "/app/settings"
    assert links[0].style["color"] == COLOR_NAVY


@pytest.mark.unit
def test_current_page_segment_renders_as_span() -> None:
    """Segments with href=None render as non-clickable spans in charcoal."""
    header = create_page_header(
        [("Settings", "/app/settings"), ("Graph Styling", None)]
    )
    nodes = _flatten_children(header)
    spans = [n for n in nodes if isinstance(n, html.Span)]
    current = [s for s in spans if s.children == "Graph Styling"]
    assert len(current) == 1
    assert current[0].style["color"] == COLOR_CHARCOAL_MEDIUM


@pytest.mark.unit
def test_description_renders_with_separator() -> None:
    """A description is appended after a '|' separator in gray."""
    header = create_page_header(
        [("Settings", None)], "Customize graph colors."
    )
    nodes = _flatten_children(header)
    spans = [n for n in nodes if isinstance(n, html.Span)]
    separators = [s for s in spans if s.children == " | "]
    assert len(separators) == 1
    description = [s for s in spans if s.children == "Customize graph colors."]
    assert len(description) == 1
    assert description[0].style["color"] == COLOR_GRAY_MEDIUM


@pytest.mark.unit
def test_no_description_omits_separator() -> None:
    """When description is None, no '|' separator is rendered."""
    header = create_page_header([("Settings", None)])
    nodes = _flatten_children(header)
    spans = [n for n in nodes if isinstance(n, html.Span)]
    separators = [s for s in spans if s.children == " | "]
    assert separators == []


@pytest.mark.unit
def test_empty_breadcrumb_renders_description_only() -> None:
    """An empty breadcrumb list renders just the description."""
    header = create_page_header([], "Just a description.")
    nodes = _flatten_children(header)
    spans = [n for n in nodes if isinstance(n, html.Span)]
    description = [s for s in spans if s.children == "Just a description."]
    assert len(description) == 1
    # No breadcrumb segments and no '|' separator.
    separators = [s for s in spans if s.children == " | "]
    assert separators == []

# ===========================================================================
# Trailing slot — a page-level control embedded in the header row
# ===========================================================================


@pytest.mark.unit
def test_trailing_component_is_rendered_in_the_header() -> None:
    """A trailing component appears inside the header, after the description."""
    marker = html.Button("Pick", id="trailing-marker")
    header = create_page_header([("Settings", None)], "A description.", trailing=marker)

    nodes = _flatten_children(header)
    assert marker in nodes


@pytest.mark.unit
def test_trailing_resets_inherited_text_case() -> None:
    """The trailing wrapper must undo the header's uppercase/letter-spacing.

    ``textTransform`` and ``letterSpacing`` both inherit, so a control dropped
    into the header renders its text ALL CAPS at 0.8px tracking without this.
    """
    header = create_page_header(
        [("Settings", None)], "A description.", trailing=html.Button("Pick")
    )
    wrapper = header.children[-1]
    assert wrapper.style["textTransform"] == "none"
    assert wrapper.style["letterSpacing"] == "normal"


@pytest.mark.unit
def test_trailing_enables_wrapping_but_only_when_present() -> None:
    """The row wraps only when a control is embedded, so other pages are unchanged."""
    plain = create_page_header([("Settings", None)], "A description.")
    assert "flexWrap" not in plain.style

    with_trailing = create_page_header(
        [("Settings", None)], "A description.", trailing=html.Button("Pick")
    )
    assert with_trailing.style["flexWrap"] == "wrap"


@pytest.mark.unit
def test_absent_trailing_adds_no_extra_child() -> None:
    """Omitting trailing leaves the header's children exactly as before."""
    header = create_page_header([("Settings", None)], "A description.")
    assert all(not isinstance(c, html.Div) or c.children != [] for c in header.children)
    # Breadcrumb span, separator span, description span — and nothing else.
    assert len(header.children) == 3


@pytest.mark.unit
def test_description_is_shrinkable() -> None:
    """The sentence may shrink so a trailing control keeps its space."""
    header = create_page_header([("Settings", None)], "A description.")
    spans = [n for n in _flatten_children(header) if isinstance(n, html.Span)]
    description = [s for s in spans if s.children == "A description."]
    assert description[0].style["minWidth"] == 0

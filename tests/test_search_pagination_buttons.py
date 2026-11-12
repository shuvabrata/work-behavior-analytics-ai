"""Unit tests for the Search page's pagination controls.

The Prev/Next buttons are ``outline`` secondary buttons, which Bootstrap renders
with its stock ``.btn-outline-secondary`` (#6c757d). The theme stylesheet
documents that colour as failing contrast against both theme backgrounds, and
does not restyle that variant, so ``btn-subtle-action`` supplies the theme-aware
``--color-text-secondary`` token instead.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest

pytestmark = pytest.mark.unit


def _iter_components(node: Any) -> Iterator[Any]:
    """Yield every component in a Dash layout tree, depth-first."""
    yield node
    children = getattr(node, "children", None)
    if children is None:
        return
    if not isinstance(children, (list, tuple)):
        children = [children]
    for child in children:
        yield from _iter_components(child)


def _pagination_buttons() -> dict[str, Any]:
    from ui.pages.search import _build_pagination_row

    return {
        node.id: node
        for node in _iter_components(_build_pagination_row())
        if getattr(node, "id", None) in ("search-prev-btn", "search-next-btn")
    }


def test_pagination_row_has_both_buttons() -> None:
    assert set(_pagination_buttons()) == {"search-prev-btn", "search-next-btn"}


def test_pagination_buttons_use_theme_aware_class() -> None:
    """Without this class the label is unreadable in the light theme."""
    for button_id, node in _pagination_buttons().items():
        props = node.to_plotly_json()["props"]
        assert "btn-subtle-action" in (props.get("className") or ""), f"{button_id} is unstyled"


def test_pagination_buttons_are_outline_secondary() -> None:
    """Pins the variant the styling above is written for."""
    for node in _pagination_buttons().values():
        props = node.to_plotly_json()["props"]
        assert props.get("color") == "secondary"
        assert props.get("outline") is True


def test_pagination_buttons_start_disabled() -> None:
    """Both start disabled; callbacks enable them once results arrive."""
    for node in _pagination_buttons().values():
        assert node.to_plotly_json()["props"].get("disabled") is True

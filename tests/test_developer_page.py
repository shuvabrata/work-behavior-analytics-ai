"""Unit tests for the Developer hub page and its REST API sub-page.

Verifies layout structure without a running server.
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


class TestDeveloperHubLayout:
    def test_hub_has_api_card(self) -> None:
        """Developer hub must include a card with card_id='api'."""
        from ui.pages.developer.layout import get_layout
        layout = get_layout()
        ids = [
            getattr(node, "id", None)
            for node in _iter_components(layout)
        ]
        assert {"type": "settings-card", "card_id": "api"} in ids, (
            "Developer hub is missing a card with card_id='api'"
        )

    def test_hub_has_mcp_card(self) -> None:
        """Developer hub must include a card with card_id='mcp'."""
        from ui.pages.developer.layout import get_layout
        layout = get_layout()
        ids = [getattr(node, "id", None) for node in _iter_components(layout)]
        assert {"type": "settings-card", "card_id": "mcp"} in ids, (
            "Developer hub is missing a card with card_id='mcp'"
        )


class TestApiLayout:
    def test_api_page_contains_docs_link(self) -> None:
        """REST API sub-page must contain a link to /docs."""
        from ui.pages.developer.api_layout import get_api_layout
        layout = get_api_layout()
        hrefs = [
            getattr(node, "href", None)
            for node in _iter_components(layout)
        ]
        assert any("/docs" in str(h) for h in hrefs if h), (
            "REST API page is missing a link to /docs (Swagger UI)"
        )

    def test_api_page_contains_redoc_link(self) -> None:
        """REST API sub-page must contain a link to /redoc."""
        from ui.pages.developer.api_layout import get_api_layout
        layout = get_api_layout()
        hrefs = [
            getattr(node, "href", None)
            for node in _iter_components(layout)
        ]
        assert any("/redoc" in str(h) for h in hrefs if h), (
            "REST API page is missing a link to /redoc (ReDoc)"
        )

    def test_api_links_open_in_new_tab(self) -> None:
        """All external doc links must open in a new browser tab."""
        from ui.pages.developer.api_layout import get_api_layout
        layout = get_api_layout()
        doc_links = [
            node for node in _iter_components(layout)
            if getattr(node, "href", None) and (
                "/docs" in str(node.href) or "/redoc" in str(node.href)
            )
        ]
        assert doc_links, "no doc links found — test is vacuous"
        for link in doc_links:
            assert getattr(link, "target", None) == "_blank", (
                f"Link to {link.href} does not open in a new tab (target='_blank')"
            )


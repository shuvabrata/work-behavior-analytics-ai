"""Unit tests for the Developer hub page and its REST API sub-page.

Verifies layout structure without a running server.
"""

from __future__ import annotations

import json
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


def _registered_nav_card_types() -> set[str]:
    """Return every pattern-match card ``type`` a nav callback listens on.

    Dash stores registered callbacks in ``GLOBAL_CALLBACK_MAP``. A
    pattern-matching ``Input({"type": ..., "card_id": ALL}, ...)`` appears
    there with its component id serialised to a JSON string.
    """
    import dash._callback as dash_callback

    from ui.layout import create_dash_app

    create_dash_app()
    types = set()
    for entry in dash_callback.GLOBAL_CALLBACK_MAP.values():
        if not isinstance(entry, dict) or not entry.get("inputs"):
            continue
        for input_spec in entry["inputs"]:
            if input_spec.get("property") != "n_clicks_timestamp":
                continue
            component_id = input_spec.get("id")
            if not (isinstance(component_id, str) and component_id.startswith("{")):
                continue
            types.add(json.loads(component_id)["type"])
    return types


class TestDeveloperHubLayout:
    def test_hub_has_api_card(self) -> None:
        """Developer hub must include a card with card_id='api'."""
        from ui.pages.developer.layout import DEVELOPER_CARD_TYPE, get_layout
        layout = get_layout()
        ids = [
            getattr(node, "id", None)
            for node in _iter_components(layout)
        ]
        assert {"type": DEVELOPER_CARD_TYPE, "card_id": "api"} in ids, (
            "Developer hub is missing a card with card_id='api'"
        )

    def test_hub_has_mcp_card(self) -> None:
        """Developer hub must include a card with card_id='mcp'."""
        from ui.pages.developer.layout import DEVELOPER_CARD_TYPE, get_layout
        layout = get_layout()
        ids = [getattr(node, "id", None) for node in _iter_components(layout)]
        assert {"type": DEVELOPER_CARD_TYPE, "card_id": "mcp"} in ids, (
            "Developer hub is missing a card with card_id='mcp'"
        )

    def test_hub_cards_do_not_share_the_settings_namespace(self) -> None:
        """Developer cards must not reuse the Settings hub's pattern-match type.

        Both hubs raise ``PreventUpdate`` for card ids they do not own, so a
        shared type works today — but a future ``card_id`` collision across
        hubs would silently route to the wrong page. Distinct types make that
        impossible.
        """
        from ui.pages.developer.layout import DEVELOPER_CARD_TYPE, get_layout
        from ui.pages.settings.layout import SETTINGS_CARD_TYPE

        assert DEVELOPER_CARD_TYPE != SETTINGS_CARD_TYPE

        hub_types = {
            node.id["type"]
            for node in _iter_components(get_layout())
            if isinstance(getattr(node, "id", None), dict) and "type" in node.id
        }
        assert hub_types == {DEVELOPER_CARD_TYPE}, (
            f"Developer hub cards carry unexpected types: {hub_types}"
        )

    def test_callback_listens_on_the_same_type_the_cards_carry(self) -> None:
        """The registered nav callback pattern must match the hub's card ids.

        The card type lives in two places that must agree: ``layout.py``
        (``card_type=``) and ``callbacks.py`` (the pattern-matching ``Input``).
        If they drift, Dash matches no component and the card silently stops
        navigating — the app sets ``suppress_callback_exceptions=True``, so
        nothing is raised at startup or on click. This asserts against the
        pattern Dash actually registered.
        """
        from ui.pages.developer.layout import DEVELOPER_CARD_TYPE

        assert DEVELOPER_CARD_TYPE in _registered_nav_card_types(), (
            "No registered nav callback listens on "
            f"{{'type': {DEVELOPER_CARD_TYPE!r}}} — registered types: "
            f"{sorted(_registered_nav_card_types())}"
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

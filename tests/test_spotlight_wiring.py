"""Wiring tests for the shared graph spotlight search.

Regression guard for a real bug: the "Search nodes..." box is emitted by the
shared ``create_controls_bar`` on every page, but the callbacks that make it work
must be registered by each page separately. A page that forgets renders a dead
input with no visible error, because ``suppress_callback_exceptions=True``. The
per-person page shipped in exactly that state.

These tests assert against Dash's own callback registry, so they fail if a page
stops registering the spotlight rather than merely importing the module.
"""

from __future__ import annotations

import pytest
from dash import _callback

import app.api_main  # noqa: F401  # importing the app registers every page's callbacks
from ui.components import spotlight as shared_spotlight
from ui.pages.collaboration_network_ego.layout import get_layout as ego_layout


pytestmark = pytest.mark.unit

# Every page that renders create_controls_bar's spotlight box.
PREFIXES = ("collab", "ego")


def _ids_for(fragment: str) -> list[str]:
    return [str(key) for key in _callback.GLOBAL_CALLBACK_MAP if fragment in str(key)]


@pytest.mark.parametrize("prefix", PREFIXES)
def test_page_registers_the_spotlight_debounce(prefix: str):
    """The input must be wired to a debounced store, or typing does nothing."""
    assert _ids_for(f"{prefix}-spotlight-debounced-store"), (
        f"{prefix}: no callback writes {prefix}-spotlight-debounced-store — "
        "the search box is inert on this page"
    )


@pytest.mark.parametrize("prefix", PREFIXES)
def test_page_registers_the_spotlight_server_callback(prefix: str):
    """The store must drive this page's own cytoscape, not another page's."""
    callbacks = [key for key in _ids_for(f"{prefix}-spotlight-count") if "elements" in key]
    assert callbacks, f"{prefix}: spotlight server callback not registered"
    assert f"{prefix}-cytoscape.elements" in callbacks[0]


@pytest.mark.parametrize("prefix", PREFIXES)
def test_page_registers_a_spotlight_result_label(prefix: str):
    """Both pages show the '<n> of <m> nodes match' label from the same callback."""
    assert _ids_for(f"{prefix}-spotlight-count.children"), (
        f"{prefix}: no callback updates {prefix}-spotlight-count"
    )


def test_ego_layout_declares_the_debounce_store():
    """The page must own a Store to hold the debounced query."""
    assert "ego-spotlight-debounced-store" in str(ego_layout())


def test_both_pages_share_one_spotlight_implementation():
    """The pages must not carry copies that could drift apart."""
    from ui.pages.collaboration_network.callbacks import spotlight as collab_spotlight

    assert collab_spotlight._apply_spotlight_classes is shared_spotlight.apply_spotlight_classes
    assert collab_spotlight._match_node is shared_spotlight.match_node


def test_shared_spotlight_matches_the_person_display_name():
    """Ego nodes carry only ``label``; that is what the user types."""
    node = {"elementType": "node", "wba_id": "wba::Person::a", "id": "a", "label": "Ibraheem Osama"}
    assert shared_spotlight.match_node(node, "ibraheem")
    assert shared_spotlight.match_node(node, "osama")
    assert not shared_spotlight.match_node(node, "nobody")

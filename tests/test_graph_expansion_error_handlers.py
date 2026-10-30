"""Regression guards on the Graph expansion handlers' error branches.

Plan 052 Step 10 moved ``execute_expansion_and_merge`` onto ``ui.api_client``,
so a transport failure now raises ``ApiError`` instead of
``requests.exceptions.Timeout`` / ``ConnectionError``. The handler ``except``
clauses had to move with it: a leftover ``except requests.exceptions.*`` would
be dead code, and the generic ``except Exception`` beneath it would render the
generic "Expansion error: …" alert instead of the specific "Expansion timed
out" one the user should see.

These tests drive the real callbacks with the helper stubbed to raise
``ApiError`` and assert on the alert text — the only automated proof that the
handlers were converted rather than the greps alone (which cannot see a
dead-but-present clause).
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest

from ui.api_client import STATUS_NO_RESPONSE, ApiError
from ui.pages.graph.callbacks import context_menu, expansion

pytestmark = pytest.mark.unit


def _text(component: Any) -> str:
    """Flatten a Dash component tree (or list) to its concatenated text."""
    if isinstance(component, str):
        return component
    if isinstance(component, (list, tuple)):
        return " ".join(_text(child) for child in component)
    children = getattr(component, "children", None)
    return _text(children) if children is not None else ""


class _Ctx:
    """Minimal stand-in for Dash's ``callback_context``."""

    def __init__(self, triggered_id: Any) -> None:
        self.triggered_id = triggered_id
        self.triggered = [{"prop_id": f"{triggered_id}.n_clicks", "value": 1}]


def _api_timeout() -> ApiError:
    """A transport failure, the shape a client timeout now takes."""
    return ApiError(STATUS_NO_RESPONSE, message="timed out")


def test_doubleclick_expansion_renders_the_timeout_alert() -> None:
    """A client transport failure still renders "Expansion timed out"."""
    with patch.object(
        expansion, "execute_expansion_and_merge", side_effect=_api_timeout()
    ):
        result = expansion.execute_doubleclick_expansion(
            {"node_id": "n1", "timestamp": 10_000},
            [],
            [],
            [],
            {},
            {},
            {},
            "preset",
        )

    # graph-status-strip children is the 6th output (index 5).
    assert "Expansion timed out" in _text(result[5])


def test_modal_expansion_renders_the_timeout_alert() -> None:
    """The modal expansion path renders its own timeout message."""
    with patch.object(
        expansion, "execute_expansion_and_merge", side_effect=_api_timeout()
    ):
        result = expansion.execute_node_expansion(
            1, "n1", "both", 10, False, [], [], [], {}, {}, "preset", 0
        )

    # graph-status-strip children is the 6th output (index 5).
    assert "Request timed out" in _text(result[5])


def test_context_menu_expand_renders_the_timeout_alert() -> None:
    """The right-click quick-expand handler renders "Expansion timed out"."""
    with patch.object(
        context_menu, "execute_expansion_and_merge", side_effect=_api_timeout()
    ), patch.object(
        context_menu, "callback_context", _Ctx("ctx-menu-expand-incoming")
    ):
        result = context_menu.context_menu_quick_expand(
            1,
            None,
            {"node_id": "n1"},
            [],
            [],
            [],
            {},
            {},
            {"display": "block"},
            "preset",
        )

    # graph-status-strip children is the 6th output (index 5).
    assert "Expansion timed out" in _text(result[5])


def test_doubleclick_expansion_never_falls_through_to_the_generic_alert() -> None:
    """The generic branch must not swallow the transport failure.

    A surviving ``except requests.exceptions.Timeout`` would make this the
    rendered message instead — the exact regression Step 10 guards against.
    """
    with patch.object(
        expansion, "execute_expansion_and_merge", side_effect=_api_timeout()
    ):
        result = expansion.execute_doubleclick_expansion(
            {"node_id": "n1", "timestamp": 10_000},
            [],
            [],
            [],
            {},
            {},
            {},
            "preset",
        )

    rendered = _text(result[5])
    assert "Expansion error:" not in rendered

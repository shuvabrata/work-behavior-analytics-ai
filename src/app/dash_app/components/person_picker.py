"""Shared person (Person wba_id) combobox builder.

Extracted from the Graph page's catalog callback module so that any page can
render a person picker without importing a page package (which would run its
``__init__`` and risk a cross-page circular import — see CLAUDE.md).
"""

from typing import Any

import dash_bootstrap_components as dbc
from dash import dcc, html


def build_person_picker(
    name: str,
    label: str,
    *,
    required: bool = False,
    current_value: str | dict[str, Any] | None = None,
) -> html.Div:
    """Build a person combobox.

    Emits the shared ``catalog-person-*`` id family (``{"type": ..., "name": name}``)
    so that the four instance-generic callbacks registered on the Graph page
    (search, suggestion relay, pick, clear) drive this picker with no changes.

    Uses a plain ``dbc.Input`` so the user types directly without any popup
    widget.  Suggestions appear in an absolutely-positioned panel below the
    input.  After a person is selected a chip replaces the search area,
    showing the canonical ``wba_id`` and a clear button.

    When ``current_value`` is a dict ``{"wba": "...", "display": "..."}``
    (i.e. a previously-picked person whose value was preserved in the
    parameter store), the chip is pre-rendered and the hidden
    ``catalog-person-value`` store is seeded so that the clear button
    correctly removes the entry from ``catalog-parameters-store``.

    NOTE: those callbacks live in pages/graph/callbacks/catalog.py. They are
    pattern-matching and therefore page-independent, but they only exist once the
    Graph page package has been imported. See the ego page's __init__.py, which
    imports that package to guarantee registration.
    """
    # Determine whether we have a stored person selection
    stored_wba: str | None = None
    stored_display: str | None = None
    if isinstance(current_value, dict):
        stored_wba = current_value.get("wba")
        stored_display = current_value.get("display") or stored_wba or "Unknown"

    label_children: list[Any] = [label]
    if required:
        label_children.append(
            html.Span(" *", style={"color": "#dc3545", "fontWeight": 700})
        )

    # --- Chip (rendered when a stored value exists) ---
    chip_children: list[Any] = []
    if stored_wba:
        chip_children = [
            html.Div(
                [
                    html.Span(stored_display, className="catalog-person-chip-name"),
                    html.Span(stored_wba, className="catalog-person-chip-id"),
                ],
                className="catalog-person-chip-info",
            ),
            html.Button(
                "×",
                id={"type": "catalog-person-chip-clear", "name": name},
                n_clicks=0,
                className="catalog-person-chip-clear",
                title="Clear selection",
            ),
        ]

    return html.Div(
        [
            html.Label(
                label_children,
                style={"fontSize": "12px", "fontWeight": 600, "marginBottom": "4px"},
            ),
            # --- Chip (visible once a person is selected) ---
            html.Div(
                id={"type": "catalog-person-chip", "name": name},
                children=chip_children,
                style={"display": "flex" if stored_wba else "none"},
                className="catalog-person-chip-area",
            ),
            # --- Search area (visible while searching) ---
            html.Div(
                [
                    html.Div(
                        [
                            dbc.Input(
                                id={"type": "catalog-person-input", "name": name},
                                placeholder="Search by name or email (min 3 chars)",
                                type="text",
                                value="",
                                autocomplete="off",
                                size="sm",
                                style={"fontSize": "12px"},
                                debounce=False,
                            ),
                            html.Div(
                                id={"type": "catalog-person-suggestions", "name": name},
                                children=[],
                                style={"display": "none"},
                                className="catalog-person-suggestions",
                            ),
                        ],
                        className="catalog-person-combobox",
                    ),
                ],
                id={"type": "catalog-person-search-area", "name": name},
                style={"display": "none" if stored_wba else "block"},
            ),
            # --- Hidden stores (self-contained within the picker) ---
            dcc.Store(
                id={"type": "catalog-person-debounce", "name": name},
                storage_type="memory",
                data=None,
            ),
            dcc.Store(
                id={"type": "catalog-person-value", "name": name},
                storage_type="memory",
                data=current_value if isinstance(current_value, dict) else None,
            ),
        ],
        className="mb-3",
    )

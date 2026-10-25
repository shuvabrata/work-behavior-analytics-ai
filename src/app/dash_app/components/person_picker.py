"""Shared person (Person wba_id) combobox builder.

Extracted from the Graph page's catalog callback module so that any page can
render a person picker without importing a page package (which would run its
``__init__`` and risk a cross-page circular import — see CLAUDE.md).
"""

from typing import Any

import dash_bootstrap_components as dbc
from dash import dcc, html

from app.dash_app.styles import COLOR_DESTRUCTIVE

__all__ = ["build_person_chip", "build_person_picker"]


def build_person_chip(name: str, display: str, wba: str) -> list[Any]:
    """Build the selected-person chip contents for one picker.

    The chip is *replaced* wholesale by three producers — this module's own
    ``current_value`` pre-render, the pick handler in
    ``pages/graph/callbacks/catalog.py``, and the ego page's deep-link seeder —
    so the markup is defined once here and they all call it. Two producers that
    disagree would render different chips for the same selection depending on
    how it was made. (The chip-*clear* handler is not a producer: it only hides
    the chip and restores the search area.)

    The returned list is the ``children`` of the picker's
    ``catalog-person-chip`` div, not the div itself: the producers output
    ``children``, so the wrapper (and its id) stays owned by the layout.

    Args:
        name: Picker instance name, used to key the clear button.
        display: Human-readable name to show.
        wba: The person's canonical ``wba_id``.

    Returns:
        list[Any]: The chip's ``info`` block and its clear button.
    """
    return [
        html.Div(
            [
                html.Span(display, className="catalog-person-chip-name"),
                html.Span(wba, className="catalog-person-chip-id"),
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


def build_person_picker(
    name: str,
    label: str,
    *,
    required: bool = False,
    current_value: str | dict[str, Any] | None = None,
    show_label: bool = True,
    container_class: str = "mb-3",
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

    Args:
        name: Picker instance name; becomes the ``name`` of every
            ``catalog-person-*`` id in the emitted family.
        label: Human label for the control.
        required: When True, append a red asterisk to the label.
        current_value: Previously-picked person, as ``{"wba", "display"}``.
        show_label: When False, the label is kept in the DOM but moved
            off-screen, for hosts that supply the label themselves — a page
            header embedding the picker in a sentence, where a floating
            "Person *" would read as an orphan. The input keeps its accessible
            name (see the implementation note on why it is hidden rather than
            replaced with an ``aria-label``).
        container_class: Class on the picker's root div. Defaults to ``"mb-3"``
            (stacked form layout); pass ``""`` in an inline host.

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
            html.Span(" *", style={"color": COLOR_DESTRUCTIVE, "fontWeight": 700})
        )

    # --- Chip (rendered when a stored value exists) ---
    chip_children: list[Any] = []
    if stored_wba:
        chip_children = build_person_chip(name, stored_display or stored_wba, stored_wba)

    children: list[Any] = []
    if show_label:
        children.append(
            html.Label(
                label_children,
                style={"fontSize": "12px", "fontWeight": 600, "marginBottom": "4px"},
            )
        )
    else:
        # Keep the label in the DOM but off-screen rather than dropping it:
        # dbc.Input (2.0.4) rejects `aria-label` — its
        # `_valid_wildcard_attributes` is empty, unlike the html.* components —
        # so a hidden <label> is the only way to give the input an accessible
        # name. It also preserves the required-asterisk text for screen readers.
        children.append(
            html.Label(label_children, className="catalog-person-label-hidden")
        )

    # With the label hidden the asterisk would go off-screen with it, so a
    # required host gets a visible one inline after the box instead. Only the
    # hidden-label case needs it: when the label is shown, its own asterisk
    # already reads correctly on the line above.
    inline_marker: Any = None
    if required and not show_label:
        inline_marker = html.Span(
            "*", className="catalog-person-required-marker", title="Required"
        )

    return html.Div(
        children + [
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
                            inline_marker,
                        ],
                        className="catalog-person-input-row",
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
        className=container_class,
    )

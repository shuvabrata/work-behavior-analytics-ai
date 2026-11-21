"""Shared builder for the app's single-choice dropdown control.

Every single-choice dropdown in the app is a ``dbc.Select`` (native ``<select>``)
so filter bars and form rows agree on height, padding and focus treatment across
pages. See ``docs/design/design-system.md`` for the standard.

Callers pass only what is layout-specific — the width of their slot, and any
state styling such as a disabled opacity. Height, border, radius, focus ring and
font are owned by ``.form-select`` in ``executive-dashboard.css`` and are
deliberately not settable here: an inline override shadows those rules instead
of extending them, and the app's light/dark theming lives in that stylesheet.
"""

from typing import Any

import dash_bootstrap_components as dbc

__all__ = ["SELECT_SIZE", "build_select"]

#: The one control size used app-wide. Native ``<select>`` height otherwise
#: drifts between call sites (34px, 36px, 38px) and the mismatch is visible
#: wherever two selectors sit in the same row.
SELECT_SIZE = "sm"


def build_select(
    input_id: str | dict[str, Any],
    options: list[dict[str, Any]],
    *,
    value: Any = None,
    placeholder: str | None = None,
    disabled: bool = False,
    width: str | None = None,
    size: str | None = SELECT_SIZE,
    style: dict[str, Any] | None = None,
) -> dbc.Select:
    """Build a native ``<select>`` matching the app's form-control standard.

    Args:
        input_id: Component id, or a pattern-matching id dict.
        options: ``{"label", "value"}`` option dicts.
        value: Selected value. Native ``<select>`` has no clearable state, so
            "unset" must be represented as an explicit option carrying ``""``
            or a named sentinel — never as ``None``.
        placeholder: Text shown by the browser when nothing is selected. Only
            has an effect while no option matches ``value``.
        disabled: Render the control non-interactive.
        width: CSS width for the control's layout slot. Omit to let the
            surrounding column size it.
        size: Control size; defaults to :data:`SELECT_SIZE`.
        style: Extra declarations for state the stylesheet cannot express, such
            as the opacity and cursor of a visually-disabled control.

    Returns:
        The configured ``dbc.Select``.
    """
    merged: dict[str, Any] = {}
    if width is not None:
        merged["width"] = width
    if style:
        merged.update(style)
    return dbc.Select(
        id=input_id,
        options=options,
        value=value,
        placeholder=placeholder,
        disabled=disabled,
        size=size,
        style=merged or None,
    )

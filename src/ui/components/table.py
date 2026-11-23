"""The single table standard for the Executive Dashboard.

:func:`data_table` builds a column/row table, optionally with a JS-filled body.
Density comes from the ancestor's ``.dense-page`` class, never from an argument
here. The table's type scale and borders live in ``executive-dashboard.css``.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import dash_bootstrap_components as dbc
from dash import html

__all__ = ["data_table"]

_BASE_CLASS = "executive-table"


def _join_classes(*classes: str | None) -> str:
    """Join the non-empty class names in order."""
    return " ".join(name for name in classes if name)


def data_table(
    columns: Sequence[str],
    rows: Sequence[Sequence[Any] | html.Tr] | None = None,
    *,
    body_id: str | None = None,
    striped: bool = False,
    hover: bool = True,
    responsive: bool = True,
    size: str = "sm",
    table_id: str | None = None,
    className: str | None = None,
) -> dbc.Table:
    """Build a column/row table.

    ``rows=None`` with ``body_id`` set emits an empty ``<tbody>`` for a
    JS-rendered body. ``rows=None`` without ``body_id`` is an error — a table
    with no body is almost always a bug.

    A row that is already an ``html.Tr`` is emitted as-is, so a caller can pass
    an empty-state row carrying a ``colSpan``.
    """
    if rows is None and body_id is None:
        raise ValueError("data_table needs rows or a body_id for a JS-rendered body")

    header = html.Thead(html.Tr([html.Th(column) for column in columns]))
    if rows is None:
        body = html.Tbody(id=body_id)
    else:
        body = html.Tbody(
            [
                row if isinstance(row, html.Tr) else html.Tr([html.Td(cell) for cell in row])
                for row in rows
            ]
        )

    props: dict[str, Any] = {
        "children": [header, body],
        "className": _join_classes(_BASE_CLASS, "executive-table--data", className),
        "size": size,
        "striped": striped,
        "hover": hover,
        "responsive": responsive,
    }
    if table_id is not None:
        props["id"] = table_id
    return dbc.Table(**props)

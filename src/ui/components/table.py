"""The single table standard for the Executive Dashboard.

Two builders share one base class, ``.executive-table``:

* :func:`data_table` — a column/row table, optionally with a JS-filled body.
* :func:`key_value_table` — a two-column key/value table.

Density comes from the ancestor's ``.dense-page`` class, never from an argument
here. The table's type scale and borders live in ``executive-dashboard.css``.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import datetime
from typing import Any

import dash_bootstrap_components as dbc
from dash import dcc, html

from common.logger import logger
from domain.timezone import humanize_duration, to_app_timezone
from ui.runtime_settings import runtime_settings

__all__ = ["data_table", "key_value_table"]

_DATE_TIME_KEYS = {"start_date", "created_at", "updated_at", "due_date"}

_BASE_CLASS = "executive-table"


def _join_classes(*classes: str | None) -> str:
    """Join the non-empty class names in order."""
    return " ".join(name for name in classes if name)


def data_table(
    columns: Sequence[str],
    rows: Sequence[Sequence[Any]] | None = None,
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
    JS-rendered body. ``rows=None`` without ``body_id`` is an error: a table
    with no body is almost always a bug.
    """
    if rows is None and body_id is None:
        raise ValueError("data_table needs rows or a body_id for a JS-rendered body")

    header = html.Thead(html.Tr([html.Th(column) for column in columns]))
    if rows is None:
        body = html.Tbody(id=body_id)
    else:
        body = html.Tbody(
            [html.Tr([html.Td(cell) for cell in row]) for row in rows]
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


def _is_date_like(key: str, value: str) -> bool:
    """Return whether the key or the ISO-looking value marks a datetime."""
    if key in _DATE_TIME_KEYS:
        return True
    return ("T" in value or "Z" in value) and len(value) >= 19


def _format_date_cell(value: str) -> html.Span | None:
    """Render a relative-time span with the full timestamp as its title."""
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        local_dt = to_app_timezone(parsed)
        actual_time = local_dt.strftime(runtime_settings.get("UI_DATETIME_FORMAT"))
        return html.Span(humanize_duration(local_dt), title=actual_time)
    except (ValueError, TypeError) as exc:
        logger.warning(f"Failed to format date {value}: {exc}")
        return None


def _clipboard(value: str) -> dcc.Clipboard:
    """Return the copy control used on every value cell."""
    return dcc.Clipboard(
        content=value,
        className="details-prop-icon details-prop-icon--copy",
        title="Copy",
    )


def _value_cell(key: str, value: Any) -> html.Span:
    """Render one value cell, matching the shared property renderer."""
    text = str(value)
    formatted_date = _format_date_cell(text) if _is_date_like(key, text) else None

    if formatted_date is not None:
        return html.Span(
            [formatted_date, _clipboard(text)],
            className="details-prop-value-wrap",
        )

    if key == "url" or text.startswith(("http://", "https://")):
        return html.Span(
            [
                html.A(
                    text,
                    href=text,
                    target="_blank",
                    rel="noopener noreferrer",
                ),
                html.I(
                    className="fas fa-external-link-alt details-prop-icon details-prop-icon--link",
                ),
                _clipboard(text),
            ],
            className="details-prop-value-wrap",
        )

    is_mono = key in ("id",) or (len(text) > 16 and " " not in text)
    if is_mono:
        return html.Span(
            [html.Code(text), _clipboard(text)],
            className="details-prop-value-wrap",
        )

    return html.Span(
        [html.Span(text), _clipboard(text)],
        className="details-prop-value-wrap",
    )


def key_value_table(
    items: Sequence[tuple[str, Any]],
    *,
    key_renderer: Callable[[Any], Any] | None = None,
    table_id: str | None = None,
    className: str | None = None,
) -> html.Table:
    """Build a two-column key/value table.

    ``key_renderer`` renders the key cell's content; when omitted the key text
    is shown unchanged. The row class stays ``details-prop-row`` so the existing
    hover-icon rule keeps working.
    """
    rows = []
    for key, value in items:
        key_content = key if key_renderer is None else key_renderer(key)
        rows.append(
            html.Tr(
                [
                    html.Td(key_content, className="kv-key"),
                    html.Td(_value_cell(key, value), className="kv-value"),
                ],
                className="details-prop-row",
            )
        )
    props: dict[str, Any] = {
        "children": html.Tbody(rows),
        "className": _join_classes(_BASE_CLASS, "executive-table--kv", className),
    }
    if table_id is not None:
        props["id"] = table_id
    return html.Table(**props)

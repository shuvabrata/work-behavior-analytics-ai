"""Unit tests for the shared table builder in ``ui.components.table``."""

from typing import Any

import pytest
from dash import html

from ui.components.table import data_table, key_value_table

pytestmark = pytest.mark.unit


def _classes(table: Any) -> str:
    return table.to_plotly_json()["props"].get("className") or ""


def _rows(table: Any) -> list[Any]:
    return list(table.children.children)


class TestDataTable:
    def test_emits_base_and_variant_classes(self) -> None:
        table = data_table(["A"], [["1"]])
        classes = _classes(table)
        assert "executive-table" in classes.split()
        assert "executive-table--data" in classes.split()

    def test_body_id_without_rows_emits_empty_tbody(self) -> None:
        table = data_table(["A"], body_id="the-body")
        body = table.children[1]
        assert body.id == "the-body"
        assert not body.children

    def test_rows_without_body_id_is_an_error(self) -> None:
        with pytest.raises(ValueError):
            data_table(["A"])

    def test_renders_one_row_per_row_and_one_th_per_column(self) -> None:
        table = data_table(["A", "B"], [["1", "2"], ["3", "4"]])
        header = table.children[0]
        body = table.children[1]
        assert len(header.children.children) == 2
        assert len(body.children) == 2
        assert len(body.children[0].children) == 2

    def test_defaults(self) -> None:
        props = data_table(["A"], [["1"]]).to_plotly_json()["props"]
        assert props["hover"] is True
        assert props["responsive"] is True
        assert props["striped"] is False

    def test_emits_no_bordered_class(self) -> None:
        table = data_table(["A"], [["1"]])
        props = table.to_plotly_json()["props"]
        assert "table-bordered" not in _classes(table)
        assert props.get("bordered") is not True


class TestKeyValueTable:
    def test_renders_one_row_per_item_with_cells(self) -> None:
        table = key_value_table([("a", 1), ("b", 2)])
        rows = _rows(table)
        assert len(rows) == 2
        for row in rows:
            assert row.className == "details-prop-row"
            assert row.children[0].className == "kv-key"
            assert row.children[1].className == "kv-value"

    def test_emits_base_and_variant_classes(self) -> None:
        classes = _classes(key_value_table([])).split()
        assert "executive-table" in classes
        assert "executive-table--kv" in classes

    def test_key_text_unchanged_without_renderer(self) -> None:
        row = _rows(key_value_table([("hub_score", 1)]))[0]
        assert row.children[0].children == "hub_score"

    def test_key_renderer_replaces_key_content(self) -> None:
        row = _rows(key_value_table([("hub_score", 1)], key_renderer=lambda key: html.B(key)))[0]
        assert isinstance(row.children[0].children, html.B)
        assert row.children[0].children.children == "hub_score"

    def test_url_renders_as_anchor(self) -> None:
        row = _rows(key_value_table([("url", "https://example.com")]))[0]
        value = row.children[1].children
        anchor = value.children[0]
        assert isinstance(anchor, html.A)
        assert anchor.href == "https://example.com"

    def test_long_token_renders_as_code(self) -> None:
        row = _rows(key_value_table([("token", "abcdefghijklmnopqrstuvwxyz")]))[0]
        code = row.children[1].children.children[0]
        assert isinstance(code, html.Code)

    def test_date_like_string_renders_relative_span_with_title(self) -> None:
        row = _rows(key_value_table([("created_at", "2026-01-02T03:04:05Z")]))[0]
        span = row.children[1].children.children[0]
        assert isinstance(span, html.Span)
        assert span.title

    def test_clipboard_on_every_value(self) -> None:
        table = key_value_table(
            [
                ("a", "plain"),
                ("id", "a" * 20),
                ("url", "https://example.com"),
                ("created_at", "2026-01-02T03:04:05Z"),
            ]
        )
        for row in _rows(table):
            wrap = row.children[1].children
            assert any(
                "details-prop-icon--copy" in (getattr(child, "className", "") or "")
                for child in wrap.children
            )

    def test_date_format_comes_from_runtime_settings(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from ui.runtime_settings import runtime_settings

        real_get = runtime_settings.get
        monkeypatch.setattr(
            runtime_settings,
            "get",
            lambda key: "%Y/%m/%d %H:%M" if key == "UI_DATETIME_FORMAT" else real_get(key),
        )
        row = _rows(key_value_table([("created_at", "2026-01-02T03:04:05Z")]))[0]
        span = row.children[1].children.children[0]
        assert "2026/01/02" in span.title

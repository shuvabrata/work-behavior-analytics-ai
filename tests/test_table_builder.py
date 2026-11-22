"""Unit tests for the shared table builder in ``ui.components.table``."""

from typing import Any

import pytest
from dash import html

from ui.components.table import data_table

pytestmark = pytest.mark.unit


def _classes(table: Any) -> str:
    return table.to_plotly_json()["props"].get("className") or ""


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

    def test_prebuilt_tr_row_is_emitted_as_is(self) -> None:
        row = html.Tr(html.Td("empty", colSpan=3))
        table = data_table(["A"], [row])
        body = table.children[1]
        assert body.children[0] is row
        assert body.children[0].children.colSpan == 3

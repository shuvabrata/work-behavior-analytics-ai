"""Tests for the Graph Styling settings page (Plan 017, Phase 4.1)."""

from __future__ import annotations

import pytest

from dash import html

from app.dash_app.pages.settings.graph_styling import get_layout
from app.dash_app.pages.settings.graph_styling import callbacks  # noqa: F401


@pytest.mark.unit
def test_layout_returns_div_shell() -> None:
    """The placeholder layout returns a valid html.Div shell."""
    layout = get_layout()
    assert isinstance(layout, html.Div)


@pytest.mark.unit
def test_layout_contains_header_and_breadcrumb() -> None:
    """The placeholder layout includes a breadcrumb link and page header."""
    layout = get_layout()

    # Traverse all component nodes generically.
    seen: list = []

    def walk(node) -> None:
        seen.append(node)
        children = getattr(node, "children", None)
        if children is None:
            return
        if isinstance(children, (list, tuple)):
            for child in children:
                if hasattr(child, "children") or hasattr(child, "href"):
                    walk(child)
        elif hasattr(children, "children") or hasattr(children, "href"):
            walk(children)

    walk(layout)

    # Breadcrumb "Settings" link present with expected href.
    links = [n for n in seen if getattr(n, "href", None) == "/app/settings"]
    assert len(links) >= 1

    # Page header text "Graph Styling" present.
    texts = [
        getattr(n, "children", "")
        for n in seen
        if isinstance(getattr(n, "children", None), str)
    ]
    assert "Graph Styling" in texts


@pytest.mark.unit
def test_package_import_registers_callbacks_without_error() -> None:
    """Importing the package does not raise and exposes get_layout."""
    from app.dash_app.pages.settings import graph_styling

    assert callable(graph_styling.get_layout)
    assert callable(callbacks) or callbacks is not None


# ── Phase 4.2 — editor layout ──────────────────────────────────────────


def _collect(node):
    """Flatten a Dash component tree into a list of all nested components."""
    results = [node]
    children = getattr(node, "children", None)
    if children is None:
        return results
    if isinstance(children, (list, tuple)):
        for child in children:
            if hasattr(child, "children") or hasattr(child, "id"):
                results.extend(_collect(child))
    elif hasattr(children, "children") or hasattr(children, "id"):
        results.extend(_collect(children))
    return results


@pytest.mark.unit
def test_layout_has_two_base_mode_tabs() -> None:
    """The editor renders base modes as tabs (Light + Dark)."""
    layout = get_layout()
    sections = [
        n for n in _collect(layout)
        if isinstance(getattr(n, "id", None), dict)
        and n.id.get("type") == "gs-base-section"
    ]
    themes = {n.id["base_theme"] for n in sections}
    assert themes == {"executive-light", "executive-dark"}


@pytest.mark.unit
def test_layout_has_node_type_rows_per_section() -> None:
    """The editor body renders a node-type row per type (excluding default)."""
    from app.common.graph_theme import NODE_TYPES
    from app.dash_app.pages.settings.graph_styling.components import (
        build_editor_body,
    )

    expected = {nt for nt in NODE_TYPES if nt != "default"}
    body = build_editor_body("executive-light", {})
    rows = [
        n for n in _collect(body)
        if isinstance(getattr(n, "id", None), dict)
        and n.id.get("type") == "gs-node-row"
    ]
    per_theme = {n.id["node_type"] for n in rows}
    assert per_theme == expected


@pytest.mark.unit
def test_layout_has_edges_and_global_cards() -> None:
    """The editor body includes an Edges card and a Global card."""
    from app.dash_app.pages.settings.graph_styling.components import (
        build_editor_body,
    )

    body = build_editor_body("executive-light", {})
    cards = [
        n for n in _collect(body)
        if isinstance(getattr(n, "id", None), dict)
        and n.id.get("type") in ("gs-edges-card", "gs-global-card")
    ]
    kinds = {n.id["type"] for n in cards}
    assert kinds == {"gs-edges-card", "gs-global-card"}


@pytest.mark.unit
def test_node_row_has_all_six_fields() -> None:
    """Each node-type row exposes fill/border/border-width/shape/width/height."""
    from app.dash_app.pages.settings.graph_styling.components import (
        build_node_type_row,
    )

    row = build_node_type_row("executive-light", "Person")
    fields = [
        n for n in _collect(row)
        if isinstance(getattr(n, "id", None), dict)
        and n.id.get("type") == "gs-node-field"
    ]
    assert {n.id["field"] for n in fields} == {
        "color",
        "border",
        "border_width",
        "shape",
        "width",
        "height",
    }


# ── Phase 4.3 — per-row live preview glyph ─────────────────────────────


@pytest.mark.unit
def test_each_row_has_glyph() -> None:
    """Each node-type row carries an inline preview glyph."""
    from app.common.graph_theme import NODE_TYPES
    from app.dash_app.pages.settings.graph_styling.components import (
        build_editor_body,
    )

    expected = {nt for nt in NODE_TYPES if nt != "default"}
    body = build_editor_body("executive-dark", {})
    glyphs = [
        n for n in _collect(body)
        if isinstance(getattr(n, "id", None), dict)
        and n.id.get("type") == "gs-node-glyph"
    ]
    per_theme = {n.id["node_type"] for n in glyphs}
    assert per_theme == expected


@pytest.mark.unit
def test_glyph_style_reflects_override() -> None:
    """The glyph style reflects fill/border/shape/size."""
    from app.dash_app.pages.settings.graph_styling.callbacks import (
        build_glyph_style,
    )

    style = build_glyph_style(
        fill="#00FF00",
        border="#008800",
        border_width=3,
        shape="diamond",
        width=80,
        height=60,
    )
    assert style["backgroundColor"] == "#00FF00"
    assert "3px solid #008800" in style["border"]
    assert "clipPath" in style  # diamond uses clip-path


@pytest.mark.unit
def test_glyph_style_preserves_aspect_ratio() -> None:
    """Wide nodes render wider; tall nodes render taller (aspect preserved)."""
    from app.dash_app.pages.settings.graph_styling.callbacks import (
        build_glyph_style,
    )

    wide = build_glyph_style("#000000", None, 0, "rectangle", 120, 60)
    tall = build_glyph_style("#000000", None, 0, "rectangle", 60, 120)

    wide_w, wide_h = float(wide["width"].rstrip("px")), float(wide["height"].rstrip("px"))
    tall_w, tall_h = float(tall["width"].rstrip("px")), float(tall["height"].rstrip("px"))

    assert wide_w > wide_h  # wide node is wider than tall
    assert tall_h > tall_w  # tall node is taller than wide
    # Aspect ratios match the input ratio (120:60 == 2:1, 60:120 == 1:2).
    assert abs((wide_w / wide_h) - 2.0) < 0.05
    assert abs((tall_h / tall_w) - 2.0) < 0.05


@pytest.mark.unit
def test_glyph_style_uses_defaults_when_unset() -> None:
    """Unset fields fall back to defaults and never error."""
    from app.dash_app.pages.settings.graph_styling.callbacks import (
        build_glyph_style,
    )

    style = build_glyph_style(None, None, None, None, None, None)
    assert style["backgroundColor"] == "#B8B8B8"
    assert style["width"]  # non-empty string


@pytest.mark.unit
def test_each_row_has_reset_button() -> None:
    """Each node-type row carries a reset button."""
    from app.common.graph_theme import NODE_TYPES
    from app.dash_app.pages.settings.graph_styling.components import (
        build_editor_body,
    )

    expected = {nt for nt in NODE_TYPES if nt != "default"}
    body = build_editor_body("executive-light", {})
    resets = [
        n for n in _collect(body)
        if isinstance(getattr(n, "id", None), dict)
        and n.id.get("type") == "gs-node-reset"
    ]
    per_theme = {n.id["node_type"] for n in resets}
    assert per_theme == expected


@pytest.mark.unit
def test_reset_restores_loaded_values() -> None:
    """The reset callback restores a row's loaded (effective) values."""
    from unittest import mock

    from app.dash_app.pages.settings.graph_styling import callbacks as cb

    loaded = {
        "nodes": {
            "Person": {
                "color": "#3B82F6",
                "border": "#2563EB",
                "border_width": 0,
                "shape": "octagon",
                "width": 66,
                "height": 56,
            }
        }
    }
    fake_ctx = mock.Mock()
    fake_ctx.triggered_id = {"type": "gs-node-reset", "node_type": "Person"}
    with mock.patch.object(cb, "callback_context", fake_ctx):
        result = cb.reset_node_row(1, loaded)

    assert result == ("#3B82F6", "#2563EB", 0, "octagon", 66, 56)


@pytest.mark.unit
def test_reset_missing_node_returns_none() -> None:
    """A reset for an unknown node type yields None fields (no crash)."""
    from unittest import mock

    from app.dash_app.pages.settings.graph_styling import callbacks as cb

    fake_ctx = mock.Mock()
    fake_ctx.triggered_id = {"type": "gs-node-reset", "node_type": "Nope"}
    with mock.patch.object(cb, "callback_context", fake_ctx):
        result = cb.reset_node_row(1, {})

    assert result == (None, None, None, None, None, None)


@pytest.mark.unit
def test_edges_and_global_fields_have_reset_buttons() -> None:
    """Each Edges/Global field carries its own per-field reset button."""
    from app.dash_app.pages.settings.graph_styling.components import (
        build_edges_card,
        build_global_card,
    )

    edge_fields = {"line_color", "width", "arrow_shape", "label_color",
                   "edge_label_font_size"}
    edges_body = build_edges_card("executive-light", {})
    edge_resets = {
        n.id["field"]
        for n in _collect(edges_body)
        if isinstance(getattr(n, "id", None), dict)
        and n.id.get("type") == "gs-edge-reset"
    }
    assert edge_resets == edge_fields

    global_fields = {"node_label_color", "node_label_font_size",
                     "selection_color", "edge_label_background"}
    global_body = build_global_card("executive-light", {})
    global_resets = {
        n.id["field"]
        for n in _collect(global_body)
        if isinstance(getattr(n, "id", None), dict)
        and n.id.get("type") == "gs-global-reset"
    }
    assert global_resets == global_fields


@pytest.mark.unit
def test_reset_edge_field_restores_loaded_value() -> None:
    """The edge reset callback restores a field's loaded (effective) value."""
    from unittest import mock

    from app.dash_app.pages.settings.graph_styling import callbacks as cb

    loaded = {"edges": {"line_color": "#999999", "edge_label_font_size": 14}}
    fake_ctx = mock.Mock()
    fake_ctx.triggered_id = {"type": "gs-edge-reset", "field": "line_color"}
    with mock.patch.object(cb, "callback_context", fake_ctx):
        assert cb.reset_edge_field(1, loaded) == "#999999"

    fake_ctx.triggered_id = {"type": "gs-edge-reset", "field": "edge_label_font_size"}
    with mock.patch.object(cb, "callback_context", fake_ctx):
        assert cb.reset_edge_field(1, loaded) == 14


@pytest.mark.unit
def test_reset_global_field_restores_loaded_value() -> None:
    """The global reset callback restores a field's loaded (effective) value."""
    from unittest import mock

    from app.dash_app.pages.settings.graph_styling import callbacks as cb

    loaded = {"global": {"node_label_color": "#00FF00", "node_label_font_size": 18}}
    fake_ctx = mock.Mock()
    fake_ctx.triggered_id = {"type": "gs-global-reset", "field": "node_label_font_size"}
    with mock.patch.object(cb, "callback_context", fake_ctx):
        assert cb.reset_global_field(1, loaded) == 18


# ── Phase 4.4 — theme management ───────────────────────────────────────


@pytest.mark.unit
def test_section_has_theme_toolbar_and_body() -> None:
    """Each base-mode section has a theme toolbar and an (empty) editor body."""
    from app.dash_app.pages.settings.graph_styling.components import (
        build_base_mode_section,
    )

    section = build_base_mode_section("executive-dark")
    nodes = _collect(section)
    types = {
        n.id["type"]
        for n in nodes
        if isinstance(getattr(n, "id", None), dict)
    }
    assert "gs-theme-toolbar" in types
    assert "gs-editor-body" in types
    assert "gs-theme-store" in types


@pytest.mark.unit
def test_editor_body_prepopulates_overrides() -> None:
    """The editor body pre-populates inputs from a theme's overrides."""
    from app.dash_app.pages.settings.graph_styling.components import (
        build_editor_body,
    )

    overrides = {
        "nodes": {"Person": {"color": "#00FF00", "shape": "diamond"}},
        "edges": {"width": 5},
        "global": {"selection_color": "#FF0000"},
    }
    body = build_editor_body("executive-light", overrides)

    person_color = None
    person_shape = None
    edge_width = None
    global_selection = None
    for n in _collect(body):
        nid = getattr(n, "id", None)
        if not isinstance(nid, dict):
            continue
        if nid.get("type") == "gs-node-field" and nid.get("node_type") == "Person":
            if nid["field"] == "color":
                person_color = getattr(n, "value", None)
            if nid["field"] == "shape":
                person_shape = getattr(n, "value", None)
        if nid.get("type") == "gs-edge-field" and nid["field"] == "width":
            edge_width = getattr(n, "value", None)
        if nid.get("type") == "gs-global-field" and nid["field"] == "selection_color":
            global_selection = getattr(n, "value", None)

    assert person_color == "#00FF00"
    assert person_shape == "diamond"
    assert edge_width == 5
    assert global_selection == "#FF0000"


@pytest.mark.unit
def test_collect_overrides_omits_empty() -> None:
    """_collect_overrides builds a semantic doc and drops empty values."""
    from app.dash_app.pages.settings.graph_styling.callbacks import (
        _collect_overrides,
    )

    node_values = ["#00FF00", None]
    node_ids = [
        {"type": "gs-node-field", "node_type": "Person", "field": "color"},
        {"type": "gs-node-field", "node_type": "Person", "field": "border"},
    ]
    edge_values = [5, None]
    edge_ids = [
        {"type": "gs-edge-field", "field": "width"},
        {"type": "gs-edge-field", "field": "line_color"},
    ]
    global_values = [None]
    global_ids = [{"type": "gs-global-field", "field": "selection_color"}]

    result = _collect_overrides(
        node_values, node_ids, edge_values, edge_ids, global_values, global_ids
    )
    assert result == {
        "nodes": {"Person": {"color": "#00FF00"}},
        "edges": {"width": 5},
        "global": {},
    }


@pytest.mark.unit
def test_theme_label_marks_builtin_and_default() -> None:
    """_theme_label annotates builtin and default themes."""
    from app.dash_app.pages.settings.graph_styling.callbacks import _theme_label

    assert "(builtin)" in _theme_label({"name": "Default", "source": "builtin", "is_default": False})
    assert "\u2605" in _theme_label({"name": "Custom", "source": "user", "is_default": True})
    assert "(builtin)" not in _theme_label({"name": "X", "source": "user", "is_default": False})


@pytest.mark.unit
def test_theme_options_default_first() -> None:
    """_theme_options puts the default theme first, then sorts by name."""
    from app.dash_app.pages.settings.graph_styling.callbacks import _theme_options

    themes = [
        {"id": 1, "name": "Zebra", "is_default": False, "source": "user"},
        {"id": 2, "name": "Default", "is_default": True, "source": "builtin"},
        {"id": 3, "name": "Alpha", "is_default": False, "source": "user"},
    ]
    options = _theme_options(themes)
    values = [o["value"] for o in options]
    assert values[0] == 2  # default first
    # Remaining sorted by name.
    assert values[1:] == [3, 1]  # Alpha, Zebra


@pytest.mark.unit
def test_load_themes_preselects_default_and_omits_placeholder() -> None:
    """load_themes pre-selects the default theme and drops the empty option."""
    from unittest import mock

    from app.dash_app.pages.settings.graph_styling import callbacks as cb

    themes = [
        {"id": 1, "name": "Zebra", "is_default": False, "source": "user"},
        {"id": 2, "name": "Default", "is_default": True, "source": "builtin"},
        {"id": 3, "name": "Alpha", "is_default": False, "source": "user"},
    ]
    with mock.patch.object(cb, "_list_themes", return_value=themes):
        options, by_id, value = cb.load_themes(
            "/app/settings/graph-styling",
            {"type": "gs-theme-select", "base_theme": "executive-light"},
        )

    # No "Select a theme…" placeholder option.
    assert all(o["value"] != "" for o in options)
    # Default theme is pre-selected.
    assert value == 2
    assert str(2) in by_id


@pytest.mark.unit
def test_load_themes_falls_back_to_first_theme_when_no_default() -> None:
    """load_themes pre-selects the first theme when none is marked default."""
    from unittest import mock

    from app.dash_app.pages.settings.graph_styling import callbacks as cb

    themes = [
        {"id": 1, "name": "Zebra", "is_default": False, "source": "user"},
        {"id": 3, "name": "Alpha", "is_default": False, "source": "user"},
    ]
    with mock.patch.object(cb, "_list_themes", return_value=themes):
        options, by_id, value = cb.load_themes(
            "/app/settings/graph-styling",
            {"type": "gs-theme-select", "base_theme": "executive-light"},
        )

    assert value == 1  # first theme
    assert all(o["value"] != "" for o in options)


@pytest.mark.unit
def test_load_themes_returns_none_value_on_request_error() -> None:
    """load_themes returns an empty value on a network error."""
    from unittest import mock

    import requests as requests_lib

    from app.dash_app.pages.settings.graph_styling import callbacks as cb

    with mock.patch.object(
        cb, "_list_themes", side_effect=requests_lib.RequestException
    ):
        options, by_id, value = cb.load_themes(
            "/app/settings/graph-styling",
            {"type": "gs-theme-select", "base_theme": "executive-light"},
        )

    assert options == []
    assert by_id == {}
    assert value is None


# ── Edge preview ───────────────────────────────────────────────────────


@pytest.mark.unit
def test_edges_card_has_preview_glyph() -> None:
    """The Edges card renders an edge preview glyph."""
    from app.dash_app.pages.settings.graph_styling.components import (
        build_editor_body,
    )

    body = build_editor_body("executive-light", {})
    glyphs = [
        n for n in _collect(body)
        if isinstance(getattr(n, "id", None), dict)
        and n.id.get("type") == "gs-edge-glyph"
    ]
    assert len(glyphs) == 1


@pytest.mark.unit
def test_edge_preview_has_cytoscape() -> None:
    """The edge preview uses a Cytoscape component (two nodes + edge)."""
    from app.dash_app.pages.settings.graph_styling.components import (
        build_editor_body,
    )

    body = build_editor_body("executive-light", {})
    cyto_comps = [
        n for n in _collect(body)
        if isinstance(getattr(n, "id", None), dict)
        and n.id.get("type") == "gs-edge-cytoscape"
    ]
    assert len(cyto_comps) == 1
    elements = cyto_comps[0].elements
    assert len(elements) == 3  # two nodes + one edge


@pytest.mark.unit
def test_edge_preview_stylesheet_reflects_fields() -> None:
    """The edge preview stylesheet reflects line colour/width/arrow/label."""
    from app.dash_app.pages.settings.graph_styling.callbacks import (
        build_edge_preview_stylesheet,
    )

    rules = build_edge_preview_stylesheet("#FF0000", 3, "triangle", "#000000")
    edge_rule = next(r for r in rules if r["selector"] == "edge")
    style = edge_rule["style"]
    assert style["line-color"] == "#FF0000"
    assert style["width"] == 3
    assert style["target-arrow-shape"] == "triangle"
    assert style["color"] == "#000000"


@pytest.mark.unit
def test_edge_preview_stylesheet_none_arrow() -> None:
    """An arrow_shape of 'none' sets target-arrow-shape to 'none'."""
    from app.dash_app.pages.settings.graph_styling.callbacks import (
        build_edge_preview_stylesheet,
    )

    rules = build_edge_preview_stylesheet("#FF0000", 2, "none", "#000000")
    edge_rule = next(r for r in rules if r["selector"] == "edge")
    assert edge_rule["style"]["target-arrow-shape"] == "none"


# ── Save As… modal (Plan 019) ──────────────────────────────────────────


@pytest.mark.unit
def test_open_save_as_modal_resets_state() -> None:
    """Opening the Save As modal returns open=True and clears name/error."""
    from app.dash_app.pages.settings.graph_styling.callbacks import (
        open_save_as_modal,
    )

    assert open_save_as_modal(1) == (True, "", "")


@pytest.mark.unit
def test_close_save_as_modal_closes() -> None:
    """Cancelling the Save As modal returns is_open=False."""
    from app.dash_app.pages.settings.graph_styling.callbacks import (
        close_save_as_modal,
    )

    assert close_save_as_modal(1) is False


@pytest.mark.unit
def test_save_as_theme_empty_name() -> None:
    """Save As with an empty name keeps the modal open and shows an error."""
    from unittest import mock

    from dash import no_update

    from app.dash_app.pages.settings.graph_styling import callbacks as cb

    fake_ctx = mock.Mock()
    fake_ctx.triggered_id = {"type": "gs-save-as-confirm", "base_theme": "executive-light"}
    with mock.patch.object(cb, "callback_context", fake_ctx):
        result = cb.save_as_theme(1, "   ", [], [], [], [], [], [])

    assert result[0] is True  # modal stays open
    assert result[1] == "Please enter a theme name."
    assert result[2:] == (no_update, no_update, no_update, no_update)


@pytest.mark.unit
def test_save_as_theme_success() -> None:
    """A successful Save As closes the modal, refreshes options, and selects the new theme."""
    from unittest import mock

    from app.dash_app.pages.settings.graph_styling import callbacks as cb

    fake_ctx = mock.Mock()
    fake_ctx.triggered_id = {"type": "gs-save-as-confirm", "base_theme": "executive-light"}

    created = {"id": 42, "name": "My Theme", "base_theme": "executive-light"}
    post_resp = mock.Mock()
    post_resp.status_code = 201
    post_resp.json.return_value = created

    # _refresh_after_action -> _list_themes -> requests.get
    get_resp = mock.Mock()
    get_resp.json.return_value = [
        {"id": 42, "name": "My Theme", "base_theme": "executive-light",
         "is_default": False, "source": "user"},
    ]

    with mock.patch.object(cb, "callback_context", fake_ctx), \
         mock.patch.object(cb.requests, "post", return_value=post_resp), \
         mock.patch.object(cb.requests, "get", return_value=get_resp):
        result = cb.save_as_theme(1, "My Theme", [], [], [], [], [], [])

    is_open, error, options, by_id, feedback, select_value = result
    assert is_open is False          # modal closes on success
    assert error == ""
    assert select_value == 42        # new theme selected
    assert by_id == {"42": get_resp.json.return_value[0]}
    assert options[0]["value"] == 42


@pytest.mark.unit
def test_save_as_theme_conflict() -> None:
    """A 409 (duplicate name) keeps the modal open and surfaces the API detail."""
    from unittest import mock

    from dash import no_update

    from app.dash_app.pages.settings.graph_styling import callbacks as cb

    fake_ctx = mock.Mock()
    fake_ctx.triggered_id = {"type": "gs-save-as-confirm", "base_theme": "executive-light"}

    post_resp = mock.Mock()
    post_resp.status_code = 409
    post_resp.json.return_value = {"detail": "A theme with this name already exists for this base mode."}

    with mock.patch.object(cb, "callback_context", fake_ctx), \
         mock.patch.object(cb.requests, "post", return_value=post_resp):
        result = cb.save_as_theme(1, "Dup", [], [], [], [], [], [])

    assert result[0] is True
    assert "already exists" in result[1]
    assert result[2:] == (no_update, no_update, no_update, no_update)


@pytest.mark.unit
def test_save_as_theme_request_exception() -> None:
    """A network failure keeps the modal open and shows a Save failed error."""
    from unittest import mock

    import requests as requests_lib
    from dash import no_update

    from app.dash_app.pages.settings.graph_styling import callbacks as cb

    fake_ctx = mock.Mock()
    fake_ctx.triggered_id = {"type": "gs-save-as-confirm", "base_theme": "executive-light"}

    with mock.patch.object(cb, "callback_context", fake_ctx), \
         mock.patch.object(cb.requests, "post", side_effect=requests_lib.RequestException("boom")):
        result = cb.save_as_theme(1, "X", [], [], [], [], [], [])

    assert result[0] is True
    assert result[1].startswith("Save failed:")
    assert result[2:] == (no_update, no_update, no_update, no_update)


@pytest.mark.unit
def test_save_as_modal_has_expected_ids() -> None:
    """The Save As modal exposes name/error/cancel/confirm and starts closed."""
    from app.dash_app.pages.settings.graph_styling.components import (
        build_save_as_modal,
    )

    modal = build_save_as_modal("executive-light")
    assert modal.is_open is False

    ids = {
        n.id["type"]
        for n in _collect(modal)
        if isinstance(getattr(n, "id", None), dict)
    }
    assert {"gs-save-as-name", "gs-save-as-error",
            "gs-save-as-cancel", "gs-save-as-confirm"} <= ids


@pytest.mark.unit
def test_save_theme_refreshes_store() -> None:
    """A successful Save returns a refreshed theme store, not no_update."""
    from unittest import mock

    from app.dash_app.pages.settings.graph_styling import callbacks as cb

    fake_ctx = mock.Mock()
    fake_ctx.triggered_id = {"type": "gs-theme-save", "base_theme": "executive-light"}

    patch_resp = mock.Mock()
    patch_resp.status_code = 200
    patch_resp.json.return_value = {"id": 7, "name": "My Theme"}

    # _refresh_after_action -> _list_themes -> requests.get
    get_resp = mock.Mock()
    get_resp.json.return_value = [
        {"id": 7, "name": "My Theme", "base_theme": "executive-light",
         "is_default": False, "source": "user"},
    ]

    with mock.patch.object(cb, "callback_context", fake_ctx), \
         mock.patch.object(cb.requests, "patch", return_value=patch_resp), \
         mock.patch.object(cb.requests, "get", return_value=get_resp):
        feedback, store = cb.save_theme(1, 7, [], [], [], [], [], [])

    assert store == {"7": get_resp.json.return_value[0]}
    assert "Saved" in feedback[0].children

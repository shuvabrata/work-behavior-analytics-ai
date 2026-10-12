"""Unit tests for the catalog editor Quick Test / View Test callbacks.

These exercise ``_run_test`` / ``quick_test`` in
``app.dash_app.pages.catalog.editor_test_callbacks`` in isolation. The
integration paths (payload shape, write-Cypher 400, empty query) are covered by
the migrated E4–E7 tests in ``test_catalog_editor_callbacks.py``.
"""

import pytest
import requests as requests_lib

from app.dash_app.pages.catalog import editor_test_callbacks


pytestmark = pytest.mark.unit


class _Resp:
    """Minimal requests.Response stand-in."""

    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload


class _FakeContext:
    """Stands in for dash.ctx so quick_test can dispatch on triggered_id."""

    def __init__(self, triggered_id):
        self.triggered_id = triggered_id


_GRAPH_PAYLOAD = {
    "isGraph": True,
    "nodes": [{
        "elementId": "n1",
        "wba_id": "wba::Person::alice",
        "labels": ["Person"],
        "properties": {"name": "Alice"},
    }],
    "relationships": [],
    "rawResults": [],
    "resultCount": 1,
}


def test_quick_test_tabular_success(monkeypatch):
    """A tabular 200 renders a row-count badge in the tabular output."""
    payload = {"isGraph": False, "rawResults": [{"n": 1}], "resultCount": 1}
    monkeypatch.setattr(
        editor_test_callbacks.requests, "post", lambda *a, **k: _Resp(payload)
    )

    result = editor_test_callbacks.quick_test_tabular(
        1, "MATCH (n) RETURN n"
    )

    assert "✔" in str(result)
    assert "1 row(s)" in str(result)


def test_quick_test_graph_success(monkeypatch):
    """A graph 200 renders a node/relationship badge in the graph output."""
    payload = {
        "isGraph": True,
        "nodes": [{"id": "a"}, {"id": "b"}],
        "relationships": [{"id": "r1"}],
        "resultCount": 2,
    }
    monkeypatch.setattr(
        editor_test_callbacks.requests, "post", lambda *a, **k: _Resp(payload)
    )

    result = editor_test_callbacks.quick_test_graph(
        1, "MATCH (a)-[r]-(b) RETURN a, r, b"
    )

    assert "✔ Graph:" in str(result)
    assert "2 nodes" in str(result)


def test_quick_test_http_400_shows_error(monkeypatch):
    """A 400 surfaces the API detail message as an error badge."""
    payload = {"detail": {"message": "Query contains write operations"}}
    monkeypatch.setattr(
        editor_test_callbacks.requests,
        "post",
        lambda *a, **k: _Resp(payload, status_code=400),
    )

    result = editor_test_callbacks.quick_test_tabular(
        1, "MATCH (n) DELETE n"
    )

    assert "✘" in str(result)
    assert "write operations" in str(result)


def test_quick_test_request_exception_shows_error(monkeypatch):
    """A raised RequestException is caught and surfaced as an error badge."""
    def _failing_post(url, json, timeout):
        raise requests_lib.exceptions.ConnectionError("Connection refused")

    monkeypatch.setattr(editor_test_callbacks.requests, "post", _failing_post)

    result = editor_test_callbacks.quick_test_tabular(
        1, "MATCH (n) RETURN n"
    )

    assert "✘" in str(result)
    assert "Connection refused" in str(result)


def test_view_test_tabular_success(monkeypatch):
    """View Test (tabular) fills the table pane and hides the graph pane."""
    payload = {"isGraph": False, "rawResults": [{"name": "Alice"}], "resultCount": 1}
    monkeypatch.setattr(
        editor_test_callbacks.requests, "post", lambda *a, **k: _Resp(payload)
    )
    monkeypatch.setattr(
        editor_test_callbacks, "ctx", _FakeContext("editor-view-test-tabular")
    )

    result = editor_test_callbacks.view_test(
        1, None, "MATCH (p:Person) RETURN p.name AS name", None
    )

    assert result[0] == []
    assert result[1] == {"display": "none"}
    assert result[2] is not None
    assert result[3] == {"display": "block"}


def test_view_test_graph_success(monkeypatch):
    """View Test (graph) fills the Cytoscape elements and shows the graph pane."""
    monkeypatch.setattr(
        editor_test_callbacks.requests, "post", lambda *a, **k: _Resp(_GRAPH_PAYLOAD)
    )
    monkeypatch.setattr(
        editor_test_callbacks, "ctx", _FakeContext("editor-view-test-graph")
    )

    result = editor_test_callbacks.view_test(
        None, 1, None, "MATCH (p:Person)-[r]-(c:Commit) RETURN p, r, c"
    )

    assert result[0]
    assert result[1] == {"display": "block"}
    assert result[3] == {"display": "none"}


def test_toggle_test_modal_close(monkeypatch):
    """Clicking Close (no HTTP call) closes the modal."""
    monkeypatch.setattr(
        editor_test_callbacks, "ctx", _FakeContext("editor-test-modal-close")
    )

    result = editor_test_callbacks.toggle_test_modal(None, None, 1)

    assert result[0] is False


def test_toggle_test_modal_opens_with_title(monkeypatch):
    """Both View Test buttons open the modal with their own title, without HTTP."""
    def _fail_post(*_args, **_kwargs):
        raise AssertionError("toggle_test_modal must not perform HTTP")

    monkeypatch.setattr(editor_test_callbacks.requests, "post", _fail_post)

    monkeypatch.setattr(
        editor_test_callbacks, "ctx", _FakeContext("editor-view-test-tabular")
    )
    tabular = editor_test_callbacks.toggle_test_modal(1, None, None)
    assert tabular[0] is True
    assert "Tabular" in tabular[1]

    monkeypatch.setattr(
        editor_test_callbacks, "ctx", _FakeContext("editor-view-test-graph")
    )
    graph = editor_test_callbacks.toggle_test_modal(None, 1, None)
    assert graph[0] is True
    assert "Graph" in graph[1]


def test_view_test_error_shows_error_display(monkeypatch):
    """A non-200 from the execute endpoint renders an error display pane."""
    payload = {"detail": {"message": "Query contains write operations"}}
    monkeypatch.setattr(
        editor_test_callbacks.requests,
        "post",
        lambda *a, **k: _Resp(payload, status_code=400),
    )
    monkeypatch.setattr(
        editor_test_callbacks, "ctx", _FakeContext("editor-view-test-tabular")
    )

    result = editor_test_callbacks.view_test(
        1, None, "MATCH (n) DELETE n", None
    )

    assert result[1] == {"display": "none"}
    assert "write operations" in str(result[4])


def test_stylesheet_follows_theme(monkeypatch):
    """Regression: the modal palette must track the app theme, not be fixed to light."""
    monkeypatch.setattr(editor_test_callbacks, "fetch_effective_theme", lambda _theme: None)
    light = editor_test_callbacks.update_test_stylesheet("executive-light")
    dark = editor_test_callbacks.update_test_stylesheet("executive-dark")
    assert isinstance(light, list) and isinstance(dark, list)
    assert light != dark


def test_stylesheet_none_theme_falls_back_to_light(monkeypatch):
    """A missing theme-store value must behave as executive-light."""
    monkeypatch.setattr(editor_test_callbacks, "fetch_effective_theme", lambda _theme: None)
    assert editor_test_callbacks.update_test_stylesheet(None) == \
        editor_test_callbacks.update_test_stylesheet("executive-light")


def test_no_callback_owns_both_quick_test_panes():
    """Regression guard: one callback writing both feedback props makes BOTH
    dcc.Loading spinners light up on a single click (Dash marks every output of
    a pending request as loading). Each pane must have its own callback.

    Uses dash's private callback registry, which is stable for the pinned
    dash==4.4.1 (requirements.app.txt).
    """
    from dash import _callback

    panes = {
        ("editor-quick-test-tabular-feedback", "children"),
        ("editor-quick-test-graph-feedback", "children"),
    }

    def parse(sig: str) -> list[tuple[str, str]]:
        """Decode dash's '..a.b...c.d..' multi-output signature."""
        body = sig[2:] if sig.startswith("..") else sig
        body = body[:-2] if body.endswith("..") else body
        out = []
        for chunk in body.split("..."):
            if chunk:
                comp, _, prop = chunk.rpartition(".")
                out.append((comp, prop))
        return out

    for spec in _callback.GLOBAL_CALLBACK_LIST:
        owned = panes & set(parse(spec["output"]))
        assert len(owned) <= 1, (
            f"one callback declares both Quick Test panes as outputs: {sorted(owned)}"
        )

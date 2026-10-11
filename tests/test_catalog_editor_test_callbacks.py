"""Unit tests for the catalog editor Quick Test / View Test callbacks.

These exercise ``_run_test`` / ``quick_test`` in
``app.dash_app.pages.catalog.editor_test_callbacks`` in isolation. The
integration paths (payload shape, write-Cypher 400, empty query) are covered by
the migrated E4–E7 tests in ``test_catalog_editor_callbacks.py``.
"""

import pytest
import requests as requests_lib
from dash import no_update

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


def test_quick_test_tabular_success(monkeypatch):
    """A tabular 200 renders a row-count badge in the tabular output."""
    payload = {"isGraph": False, "rawResults": [{"n": 1}], "resultCount": 1}
    monkeypatch.setattr(
        editor_test_callbacks.requests, "post", lambda *a, **k: _Resp(payload)
    )
    monkeypatch.setattr(
        editor_test_callbacks, "ctx", _FakeContext("editor-quick-test-tabular")
    )

    result = editor_test_callbacks.quick_test(
        1, None, "MATCH (n) RETURN n", None
    )

    assert "✔" in str(result[0])
    assert "1 row(s)" in str(result[0])
    assert result[1] is no_update


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
    monkeypatch.setattr(
        editor_test_callbacks, "ctx", _FakeContext("editor-quick-test-graph")
    )

    result = editor_test_callbacks.quick_test(
        None, 1, None, "MATCH (a)-[r]-(b) RETURN a, r, b"
    )

    assert "✔ Graph:" in str(result[1])
    assert "2 nodes" in str(result[1])
    assert result[0] is no_update


def test_quick_test_http_400_shows_error(monkeypatch):
    """A 400 surfaces the API detail message as an error badge."""
    payload = {"detail": {"message": "Query contains write operations"}}
    monkeypatch.setattr(
        editor_test_callbacks.requests,
        "post",
        lambda *a, **k: _Resp(payload, status_code=400),
    )
    monkeypatch.setattr(
        editor_test_callbacks, "ctx", _FakeContext("editor-quick-test-tabular")
    )

    result = editor_test_callbacks.quick_test(
        1, None, "MATCH (n) DELETE n", None
    )

    assert "✘" in str(result[0])
    assert "write operations" in str(result[0])


def test_quick_test_request_exception_shows_error(monkeypatch):
    """A raised RequestException is caught and surfaced as an error badge."""
    def _failing_post(url, json, timeout):
        raise requests_lib.exceptions.ConnectionError("Connection refused")

    monkeypatch.setattr(editor_test_callbacks.requests, "post", _failing_post)
    monkeypatch.setattr(
        editor_test_callbacks, "ctx", _FakeContext("editor-quick-test-tabular")
    )

    result = editor_test_callbacks.quick_test(
        1, None, "MATCH (n) RETURN n", None
    )

    assert "✘" in str(result[0])
    assert "Connection refused" in str(result[0])

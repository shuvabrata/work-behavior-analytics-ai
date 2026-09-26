"""Unit tests for the Library (query catalog) listing page callbacks.

These tests exercise the callback functions in
``app.dash_app.pages.library.callbacks`` and the pure table-rendering helpers
in ``app.dash_app.pages.library.layout``. HTTP calls are mocked with a fake
``requests`` layer so no live server is required.
"""

from dataclasses import dataclass

import pytest

from app.dash_app.pages.library import callbacks as library_callbacks
from app.dash_app.pages.library.layout import (
    _destructive_label,
    _is_user_row,
    render_library_table,
)


pytestmark = pytest.mark.unit


@dataclass
class _FakeResponse:
    """Minimal requests.Response stand-in for callback tests."""

    payload: dict
    status_code: int = 200

    @property
    def headers(self):
        return {"content-type": "application/json"}

    @property
    def content(self):
        return b"{}"

    def json(self):
        return self.payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise AssertionError(f"Unexpected HTTP {self.status_code}")
        return None


class _FakeRequests:
    """Sequential fake for requests.get/delete returning predefined responses."""

    def __init__(self, responses):
        self._responses = responses
        self._idx = 0
        self.get_calls = []
        self.delete_calls = []

    def get(self, url, timeout):
        self.get_calls.append({"url": url, "timeout": timeout})
        return self._next()

    def delete(self, url, timeout):
        self.delete_calls.append({"url": url, "timeout": timeout})
        return self._next()

    def _next(self):
        if self._idx >= len(self._responses):
            raise AssertionError("Unexpected extra requests call")
        response = self._responses[self._idx]
        self._idx += 1
        return response


def _query(
    query_id: str,
    name: str,
    *,
    source_path: str = "queries_catalog/github/top_committers.yaml",
    tags: list[str] | None = None,
    status: str | None = "active",
    available_views: list[str] | None = None,
) -> dict:
    """Build a minimal catalog query dict as returned by the API."""
    namespace, _, slug = query_id.partition("/")
    return {
        "id": query_id,
        "name": name,
        "namespace": {"directory": namespace},
        "source_path": source_path,
        "tags": tags or [],
        "status": status,
        "available_views": available_views or ["tabular"],
    }


# ── Pure helpers (D6, D7) ──────────────────────────────────────────────


def test_d6_override_row_labeled_reset_to_factory():
    """A user row whose id exists in the system catalog is an override."""
    query = _query(
        "github/top_committers",
        "Top Committers",
        source_path="queries_catalog/user_defined/github/top_committers.yaml",
    )
    assert _is_user_row(query) is True
    assert _destructive_label(query, {"github/top_committers"}) == "Reset to factory"


def test_d7_addition_row_labeled_delete():
    """A user row with a brand-new id is an addition (Delete)."""
    query = _query(
        "github/my_custom",
        "My Custom",
        source_path="queries_catalog/user_defined/github/my_custom.yaml",
    )
    assert _is_user_row(query) is True
    assert _destructive_label(query, {"github/top_committers"}) == "Delete"


def test_d7b_system_row_has_no_destructive_button():
    """A system row (no user_defined source_path) is not a user row."""
    query = _query("github/top_committers", "Top Committers")
    assert _is_user_row(query) is False


def test_d1_table_renders_rows():
    """render_library_table produces a row per query."""
    queries = [
        _query("github/a", "Query A"),
        _query("github/b", "Query B"),
    ]
    table = render_library_table(queries, set())
    rendered = str(table)
    assert "Query A" in rendered
    assert "Query B" in rendered


def test_d1b_table_renders_all_columns_except_description_and_query():
    """The table shows all model columns except Description and the Cypher."""
    query = {
        "id": "github/a",
        "name": "Query A",
        "namespace": {"directory": "github"},
        "source_path": "queries_catalog/user_defined/github/a.yaml",
        "tags": ["urgent"],
        "status": "active",
        "available_views": ["tabular", "graph"],
        "owner": "alice",
        "summary": "A short summary.",
        "default_view": "tabular",
        "parameters": [{"name": "p1"}],
    }
    table = render_library_table([query], set())
    rendered = str(table)

    # Headers present
    for header in (
        "Name",
        "Summary",
        "Tags",
        "Status",
        "Default View",
        "Parameters",
        "Views",
        "Source",
        "Actions",
    ):
        assert header in rendered

    # Row data present
    assert "A short summary." in rendered
    assert "tabular" in rendered
    assert "1" in rendered  # parameter count
    assert "User" in rendered  # source badge for user-defined row

    # Description, the query Cypher, Namespace, and Owner must NOT be columns
    assert "Description" not in rendered
    assert "MATCH" not in rendered
    assert "Namespace" not in rendered
    assert "Owner" not in rendered


def test_d1c_tags_and_status_match_graph_catalog():
    """Tags render as borderless badges; status colors match Graph catalog."""
    from app.dash_app.pages.library.layout import _status_badge, _tag_chips

    # Tags: dbc.Badge with light/dark colors, no border class.
    tags_div = _tag_chips(["urgent", "graph"])
    badges = tags_div.children
    assert len(badges) == 2
    for badge in badges:
        assert badge.color == "light"
        assert badge.text_color == "dark"
        assert "border" not in (badge.className or "")

    # Status: active → success, draft → warning, deprecated → secondary.
    active = str(_status_badge("active"))
    assert "text-bg-success" in active
    draft = str(_status_badge("draft"))
    assert "text-bg-warning" in draft
    deprecated = str(_status_badge("deprecated"))
    assert "text-bg-secondary" in deprecated
    # Unknown/empty status → None (renders as em-dash in the row).
    assert _status_badge(None) is None
    assert _status_badge("unknown") is None


def _table_rows(table):
    """Extract the Tr components from a rendered library table."""
    table_el = table.children[0]
    tbody = table_el.children[1]
    return list(tbody.children)


def _row_search(row) -> str:
    """Read a row's ``data-search`` attribute (hyphenated prop)."""
    return getattr(row, "data-search") or ""


def _row_namespace(row) -> str:
    """Read a row's ``data-namespace`` attribute (hyphenated prop)."""
    return getattr(row, "data-namespace") or ""


def test_d2_namespace_filter_data_attribute():
    """Each row carries a ``data-namespace`` attribute for client-side filter."""
    queries = [
        _query("github/a", "Query A"),
        _query("jira/b", "Query B"),
    ]
    table = render_library_table(queries, set())
    rows = _table_rows(table)
    assert [_row_namespace(row) for row in rows] == ["github", "jira"]


def test_d2b_all_namespaces_shows_all_rows():
    """All rows are rendered; filtering is applied client-side."""
    queries = [
        _query("github/a", "Query A"),
        _query("jira/b", "Query B"),
    ]
    table = render_library_table(queries, set())
    rendered = str(table)
    assert "Query A" in rendered
    assert "Query B" in rendered


def test_d2c_populate_namespace_dropdown_includes_all_default():
    """The namespace filter defaults to ``__all__`` with namespaces listed."""
    namespaces = [
        {"name": "GitHub", "directory": "github", "order": 0},
        {"name": "Jira", "directory": "jira", "order": 1},
    ]
    options, value = library_callbacks.populate_namespace_dropdown(namespaces)
    assert value == "__all__"
    assert options[0] == {"label": "All namespaces", "value": "__all__"}
    assert {"label": "GitHub", "value": "github"} in options
    assert {"label": "Jira", "value": "jira"} in options


def test_d3_search_data_attribute_includes_all_columns():
    """The ``data-search`` attribute covers name, summary, tags, and more."""
    query = {
        "id": "github/a",
        "name": "Query Alpha",
        "namespace": {"directory": "github"},
        "source_path": "queries_catalog/github/a.yaml",
        "tags": ["urgent"],
        "status": "active",
        "available_views": ["tabular"],
        "summary": "Compares comments and reactions across blogposts.",
        "owner": "alice",
        "default_view": "tabular",
    }
    table = render_library_table([query], set())
    row = _table_rows(table)[0]
    search_text = _row_search(row)
    assert "blogposts" in search_text  # summary
    assert "alice" in search_text  # owner
    assert "urgent" in search_text  # tags
    assert "query alpha" in search_text  # name
    assert "system" in search_text  # source


def test_d3b_search_matches_summary_via_data_attribute():
    """Summary text is part of the searchable data attribute."""
    queries = [
        {
            "id": "github/a",
            "name": "Query Alpha",
            "namespace": {"directory": "github"},
            "source_path": "queries_catalog/github/a.yaml",
            "tags": [],
            "status": "active",
            "available_views": ["tabular"],
            "summary": "Compares comments and reactions across blogposts.",
        },
        {
            "id": "github/b",
            "name": "Query Beta",
            "namespace": {"directory": "github"},
            "source_path": "queries_catalog/github/b.yaml",
            "tags": [],
            "status": "active",
            "available_views": ["tabular"],
            "summary": "Lists open pull requests.",
        },
    ]
    table = render_library_table(queries, set())
    rows = _table_rows(table)
    assert "blogposts" in _row_search(rows[0])
    assert "pull requests" in _row_search(rows[1])


# ── Callbacks (D4, D5, D8, D9) ─────────────────────────────────────────


def _patch_callback_context(monkeypatch, triggered_id):
    """Set the dash callback context so ``callback_context`` reads work.

    ``dash.callback_context.triggered``/``triggered_id`` read from a
    ``contextvars.ContextVar`` in ``dash._callback_context``. We set that var
    with a fake object exposing ``triggered_inputs`` so the properties resolve
    outside a real callback.
    """
    import json

    import dash._callback_context as ctx_module

    prop_id = f"{json.dumps(triggered_id, separators=(',', ':'))}.n_clicks"

    class _FakeContext:
        triggered_inputs = [{"prop_id": prop_id, "value": 1}]
        input_values = {}
        state_values = {}

    monkeypatch.setattr(ctx_module, "context_value", ctx_module.context_value)
    ctx_module.context_value.set(_FakeContext())


def test_d4_edit_click_navigates_to_editor(monkeypatch):
    """Edit click sets the url pathname to the editor route."""
    _patch_callback_context(
        monkeypatch, {"type": "library-edit-btn", "id": "github/a"}
    )

    result = library_callbacks.handle_edit_click([1])
    assert result == "/app/library/edit/github/a"


def test_d5_new_query_click_navigates_to_new(monkeypatch):
    """New Query click sets the url pathname to /app/library/new."""
    result = library_callbacks.handle_new_click(1)
    assert result == "/app/library/new"


def test_d8_reset_confirm_deletes_and_refreshes(monkeypatch):
    """Confirming a reset issues DELETE then refreshes the catalog."""
    fake = _FakeRequests(
        [
            _FakeResponse({"message": "Query override deleted"}, 200),
            _FakeResponse({"items": [_query("github/a", "Query A")]}, 200),
        ]
    )
    monkeypatch.setattr(library_callbacks, "requests", fake)

    store, feedback = library_callbacks.confirm_delete(
        1, {"id": "github/a"}
    )
    assert fake.delete_calls[0]["url"].endswith(
        "/api/v1/queries/catalog/github/a"
    )
    assert store == [_query("github/a", "Query A")]
    assert "Query deleted" in str(feedback)


def test_d9_delete_confirm_deletes_and_refreshes(monkeypatch):
    """Confirming a delete issues DELETE then refreshes the catalog."""
    fake = _FakeRequests(
        [
            _FakeResponse({"message": "Query override deleted"}, 200),
            _FakeResponse({"items": []}, 200),
        ]
    )
    monkeypatch.setattr(library_callbacks, "requests", fake)

    store, feedback = library_callbacks.confirm_delete(
        1, {"id": "github/my_custom"}
    )
    assert fake.delete_calls[0]["url"].endswith(
        "/api/v1/queries/catalog/github/my_custom"
    )
    assert store == []
    assert "Query deleted" in str(feedback)


def test_d8b_reset_confirm_dialog_message_override(monkeypatch):
    """Override rows show the reset-to-factory dialog message."""
    queries = [
        _query(
            "github/top_committers",
            "Top Committers",
            source_path="queries_catalog/user_defined/github/top_committers.yaml",
        )
    ]
    system_ids = ["github/top_committers"]
    _patch_callback_context(
        monkeypatch,
        {"type": "library-destructive-btn", "id": "github/top_committers"},
    )

    message, displayed, pending = library_callbacks.handle_destructive_click(
        [1], queries, system_ids
    )
    assert displayed is True
    assert "reset" in message.lower()
    assert "cannot be undone" in message
    assert pending == {"id": "github/top_committers"}


def test_d9b_delete_confirm_dialog_message_addition(monkeypatch):
    """Addition rows show the delete dialog message."""
    queries = [
        _query(
            "github/my_custom",
            "My Custom",
            source_path="queries_catalog/user_defined/github/my_custom.yaml",
        )
    ]
    system_ids: list[str] = []
    _patch_callback_context(
        monkeypatch,
        {"type": "library-destructive-btn", "id": "github/my_custom"},
    )

    message, displayed, pending = library_callbacks.handle_destructive_click(
        [1], queries, system_ids
    )
    assert displayed is True
    assert "delete" in message.lower()
    assert "cannot be undone" in message
    assert pending == {"id": "github/my_custom"}
"""Unit tests for the Library (query catalog) listing page callbacks.

These tests exercise the Python-side callback functions in
``app.dash_app.pages.library.callbacks`` and the static table skeleton in
``app.dash_app.pages.library.layout``. The table body rows are built entirely
in JavaScript (a clientside callback), so row-level rendering is not unit
tested here — the Python tests cover the data flow and the static skeleton.
HTTP calls are mocked with a fake ``requests`` layer so no live server is
required.
"""

from dataclasses import dataclass

import pytest

from app.dash_app.pages.library import callbacks as library_callbacks
from app.dash_app.pages.library.layout import render_library_table


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


def test_system_ids_derived_from_source_path():
    """System ids are derived from the API items without re-parsing YAML."""
    items = [
        {"id": "github/a", "source_path": "queries_catalog/github/a.yaml"},
        {"id": "github/b", "source_path": "queries_catalog/user_defined/github/b.yaml"},
        {"id": "jira/c", "source_path": "queries_catalog/jira/c.yaml"},
    ]
    system_ids = library_callbacks._system_ids_from_items(items)
    assert system_ids == ["github/a", "jira/c"]


# ── Static table skeleton ──────────────────────────────────────────────


def test_table_skeleton_has_headers_and_empty_body():
    """The static skeleton renders headers and an empty tbody for JS to fill."""
    table = render_library_table()
    rendered = str(table)

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

    # The body is populated by JS; the skeleton must expose the tbody id.
    assert "library-table-body" in rendered
    assert "library-empty-row" in rendered


# ── Callbacks (D5, D8, D9) ─────────────────────────────────────────────


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
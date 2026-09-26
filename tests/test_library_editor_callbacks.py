"""Unit tests for the Library query editor callbacks.

These tests exercise the callback functions in
``app.dash_app.pages.library.editor_callbacks``. HTTP calls are mocked with a
fake ``requests`` layer so no live server or Neo4j is required.
"""

from dataclasses import dataclass

import pytest

from app.dash_app.pages.library import editor_callbacks as editor


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
    """Sequential fake for requests.get/put/post/delete."""

    def __init__(self, responses):
        self._responses = responses
        self._idx = 0
        self.get_calls = []
        self.put_calls = []
        self.post_calls = []
        self.delete_calls = []

    def get(self, url, timeout):
        self.get_calls.append({"url": url, "timeout": timeout})
        return self._next()

    def put(self, url, json, timeout):
        self.put_calls.append({"url": url, "json": json, "timeout": timeout})
        return self._next()

    def post(self, url, json, timeout):
        self.post_calls.append({"url": url, "json": json, "timeout": timeout})
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


def _query_payload() -> dict:
    """A catalog query as returned by GET /catalog/{ns}/{slug}."""
    return {
        "id": "github/top_committers",
        "name": "Top Committers",
        "description": "Top committers by count.",
        "summary": None,
        "owner": None,
        "status": "active",
        "tags": ["github"],
        "queries": {"tabular": "MATCH (n) RETURN n LIMIT 10"},
        "default_view": "tabular",
        "parameters": [],
    }


def _form_state(**overrides) -> dict:
    """Default editor form state for save/save-as callbacks."""
    state = {
        "name": "Top Committers",
        "description": "Top committers by count.",
        "summary": None,
        "owner": None,
        "status": "active",
        "tags": "github",
        "tabular_query": "MATCH (n) RETURN n LIMIT 10",
        "graph_query": "",
        "default_view": "tabular",
        "param_count": 0,
        "field_values": [],
    }
    state.update(overrides)
    return state


# ── E1: editor loads query ─────────────────────────────────────────────


def test_e1_editor_loads_query(monkeypatch):
    """An edit route fetches and populates the form from the query."""
    fake = _FakeRequests([_FakeResponse(_query_payload(), 200)])
    monkeypatch.setattr(editor, "requests", fake)

    result = editor.load_query("edit", "/app/library/edit/github/top_committers")

    assert fake.get_calls[0]["url"].endswith(
        "/api/v1/queries/catalog/github/top_committers"
    )
    # (store, id, ns, slug, name, description, summary, owner, status, tags,
    #  tabular, graph, default_view, param_count, params, feedback)
    assert result[0] == {
        "mode": "edit",
        "id": "github/top_committers",
        "namespace": "github",
        "slug": "top_committers",
    }
    assert result[4] == "Top Committers"
    assert result[10] == "MATCH (n) RETURN n LIMIT 10"


def test_e1b_new_route_leaves_form_blank(monkeypatch):
    """The new route leaves the form blank without a GET."""
    fake = _FakeRequests([])
    monkeypatch.setattr(editor, "requests", fake)

    result = editor.load_query("new", "/app/library/new")

    assert fake.get_calls == []
    assert result[0] == {"mode": "new"}
    assert result[4] == ""


# ── E2: Save → PUT ─────────────────────────────────────────────────────


def test_e2_save_puts_to_current_id(monkeypatch):
    """Save issues a PUT to the current namespace/slug."""
    fake = _FakeRequests([_FakeResponse(_query_payload(), 200)])
    monkeypatch.setattr(editor, "requests", fake)

    state = _form_state()
    feedback = editor.save_query(
        1,
        {"mode": "edit", "id": "github/top_committers"},
        "/app/library/edit/github/top_committers",
        state["name"],
        state["description"],
        state["summary"],
        state["owner"],
        state["status"],
        state["tags"],
        state["tabular_query"],
        state["graph_query"],
        state["default_view"],
        state["param_count"],
        state["field_values"],
    )

    assert fake.put_calls[0]["url"].endswith(
        "/api/v1/queries/catalog/github/top_committers"
    )
    assert fake.put_calls[0]["json"]["name"] == "Top Committers"
    assert fake.put_calls[0]["json"]["queries"]["tabular"] == "MATCH (n) RETURN n LIMIT 10"
    assert "Query saved" in str(feedback)


def test_e2b_save_on_new_route_warns(monkeypatch):
    """Save on the new route warns to use Save As instead."""
    fake = _FakeRequests([])
    monkeypatch.setattr(editor, "requests", fake)

    state = _form_state()
    feedback = editor.save_query(
        1,
        {"mode": "new"},
        "/app/library/new",
        state["name"],
        state["description"],
        state["summary"],
        state["owner"],
        state["status"],
        state["tags"],
        state["tabular_query"],
        state["graph_query"],
        state["default_view"],
        state["param_count"],
        state["field_values"],
    )

    assert fake.put_calls == []
    assert "Save As" in str(feedback)


# ── E3: Save As → PUT to new id ────────────────────────────────────────


def test_e3_save_as_puts_to_new_id(monkeypatch):
    """Save As issues a PUT to the chosen namespace/slug."""
    fake = _FakeRequests([_FakeResponse(_query_payload(), 200)])
    monkeypatch.setattr(editor, "requests", fake)

    state = _form_state()
    feedback, is_open = editor.save_as_query(
        1,
        "github",
        None,
        "my_new_query",
        state["name"],
        state["description"],
        state["summary"],
        state["owner"],
        state["status"],
        state["tags"],
        state["tabular_query"],
        state["graph_query"],
        state["default_view"],
        state["param_count"],
        state["field_values"],
    )

    assert fake.put_calls[0]["url"].endswith(
        "/api/v1/queries/catalog/github/my_new_query"
    )
    assert "Saved as" in str(feedback)
    assert is_open is False


def test_e3b_save_as_custom_namespace(monkeypatch):
    """Save As with '+ New namespace…' uses the custom namespace input."""
    fake = _FakeRequests([_FakeResponse(_query_payload(), 200)])
    monkeypatch.setattr(editor, "requests", fake)

    state = _form_state()
    feedback, _ = editor.save_as_query(
        1,
        "__new__",
        "my_queries",
        "custom_query",
        state["name"],
        state["description"],
        state["summary"],
        state["owner"],
        state["status"],
        state["tags"],
        state["tabular_query"],
        state["graph_query"],
        state["default_view"],
        state["param_count"],
        state["field_values"],
    )

    assert fake.put_calls[0]["url"].endswith(
        "/api/v1/queries/catalog/my_queries/custom_query"
    )
    assert "Saved as" in str(feedback)


# ── E4/E5: Test Tabular / Test Graph → POST execute ────────────────────


def test_e4_test_tabular_posts_execute(monkeypatch):
    """Test Tabular posts the tabular query to the execute endpoint."""
    fake = _FakeRequests(
        [_FakeResponse({"isGraph": False, "rawResults": [{"n": 1}]}, 200)]
    )
    monkeypatch.setattr(editor, "requests", fake)

    result = editor.test_tabular(1, "MATCH (n) RETURN n LIMIT 10")

    assert fake.post_calls[0]["url"].endswith("/api/v1/graph/execute")
    assert fake.post_calls[0]["json"] == {
        "source": "raw",
        "query": "MATCH (n) RETURN n LIMIT 10",
        "view": "auto",
    }
    assert result is not None


def test_e5_test_graph_posts_execute(monkeypatch):
    """Test Graph posts the graph query to the execute endpoint."""
    fake = _FakeRequests(
        [_FakeResponse({"isGraph": True, "resultCount": 3}, 200)]
    )
    monkeypatch.setattr(editor, "requests", fake)

    result = editor.test_graph(1, "MATCH (a)-[r]-(b) RETURN a, r, b")

    assert fake.post_calls[0]["url"].endswith("/api/v1/graph/execute")
    assert fake.post_calls[0]["json"]["query"] == "MATCH (a)-[r]-(b) RETURN a, r, b"
    assert "3" in str(result)


def test_e6_test_with_write_cypher_shows_error(monkeypatch):
    """A 400 from the execute endpoint surfaces an error alert."""
    fake = _FakeRequests(
        [
            _FakeResponse(
                {"detail": {"message": "Query contains write operations"}},
                400,
            )
        ]
    )
    monkeypatch.setattr(editor, "requests", fake)

    result = editor.test_tabular(1, "MATCH (n) DELETE n")

    assert fake.post_calls[0]["json"]["query"] == "MATCH (n) DELETE n"
    assert "write operations" in str(result)


def test_e7_test_button_disabled_when_empty(monkeypatch):
    """Testing with an empty textarea warns without an HTTP call."""
    fake = _FakeRequests([])
    monkeypatch.setattr(editor, "requests", fake)

    result = editor.test_tabular(1, "")

    assert fake.post_calls == []
    assert "Enter a query" in str(result)


# ── E8: Reset → DELETE → form reloads ──────────────────────────────────


def test_e8_reset_deletes_and_reloads(monkeypatch):
    """Reset issues DELETE then reloads the form with system data."""
    fake = _FakeRequests(
        [
            _FakeResponse({"message": "Query override deleted"}, 200),
            _FakeResponse(_query_payload(), 200),
        ]
    )
    monkeypatch.setattr(editor, "requests", fake)

    result = editor.reset_query(
        1,
        {"mode": "edit", "id": "github/top_committers"},
        "/app/library/edit/github/top_committers",
    )

    assert fake.delete_calls[0]["url"].endswith(
        "/api/v1/queries/catalog/github/top_committers"
    )
    assert fake.get_calls[0]["url"].endswith(
        "/api/v1/queries/catalog/github/top_committers"
    )
    assert result[4] == "Top Committers"
    assert "reset to factory" in str(result[15]).lower()
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
        "origin": "builtin",
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
        "field_ids": [],
    }
    state.update(overrides)
    return state


def _param_ids(index: int) -> list[dict[str, str]]:
    """The pattern-matched ids produced by ``render_parameter_row``."""
    return [
        {"type": "editor-param-field", "index": str(index), "field": field}
        for field in [
            "name",
            "label",
            "type",
            "required",
            "placeholder",
            "description",
            "env_var",
        ]
    ]


def _extract_field_values(rows: list[Any]) -> dict[tuple[str, str], Any]:
    """Extract ``{(index, field): value}`` from rendered parameter rows.

    Walks the Dash component tree produced by ``render_parameter_row``:
    each row is an ``html.Div`` whose first child is a ``dbc.Row`` of
    ``dbc.Col``s, each containing ``[dbc.Label, control]`` where ``control``
    is a ``dbc.Input`` or ``dcc.Checklist`` carrying the pattern-matched id.
    """
    result: dict[tuple[str, str], Any] = {}
    for row in rows:
        index = row.id["index"]
        fields_row = row.children[0]
        for col in fields_row.children:
            control = col.children[1]
            field = control.id["field"]
            result[(index, field)] = control.value
    return result


# ── _collect_parameters: id-based row assembly ─────────────────────────


def test_collect_parameters_single_row():
    """A single fully-populated row lands every field correctly."""
    ids = _param_ids(0)
    values = ["owner", "Owner", "string", ["required"], "e.g. shuva", "Repo owner", "GH_OWNER"]
    result = editor._collect_parameters(1, values, ids)

    assert result == [
        {
            "name": "owner",
            "label": "Owner",
            "type": "string",
            "required": True,
            "placeholder": "e.g. shuva",
            "description": "Repo owner",
            "env_var": "GH_OWNER",
        }
    ]


def test_collect_parameters_multiple_rows_shuffled():
    """Fields land in the correct row/field regardless of input order."""
    ids = _param_ids(0) + _param_ids(1)
    # Shuffle the (value, id) pairs so the ordering assumption would break.
    pairs = list(zip(
        ["owner", "Owner", "string", ["required"], "e.g. shuva", "Repo owner", "GH_OWNER",
         "repo", "Repo", "string", [], "e.g. shuvabrata", "Repo name", "GH_REPO"],
        ids,
    ))
    pairs = pairs[7:] + pairs[:7]  # row 1 first, then row 0
    values = [v for v, _ in pairs]
    shuffled_ids = [i for _, i in pairs]

    result = editor._collect_parameters(2, values, shuffled_ids)

    assert result == [
        {
            "name": "owner",
            "label": "Owner",
            "type": "string",
            "required": True,
            "placeholder": "e.g. shuva",
            "description": "Repo owner",
            "env_var": "GH_OWNER",
        },
        {
            "name": "repo",
            "label": "Repo",
            "type": "string",
            "required": False,
            "placeholder": "e.g. shuvabrata",
            "description": "Repo name",
            "env_var": "GH_REPO",
        },
    ]


def test_collect_parameters_required_coercion():
    """The checklist value is coerced to a bool."""
    ids = _param_ids(0)
    values = ["owner", "Owner", "string", [], "e.g. shuva", "Repo owner", "GH_OWNER"]
    result = editor._collect_parameters(1, values, ids)

    assert result[0]["required"] is False


def test_collect_parameters_drops_row_without_name():
    """A row with no name is dropped from the result."""
    ids = _param_ids(0) + _param_ids(1)
    values = ["", "Owner", "string", [], "e.g. shuva", "Repo owner", "GH_OWNER",
              "repo", "Repo", "string", [], "e.g. shuvabrata", "Repo name", "GH_REPO"]
    result = editor._collect_parameters(2, values, ids)

    assert result == [
        {
            "name": "repo",
            "label": "Repo",
            "type": "string",
            "required": False,
            "placeholder": "e.g. shuvabrata",
            "description": "Repo name",
            "env_var": "GH_REPO",
        }
    ]


# ── Parameter add/remove: preserve existing row values ────────────────


def test_add_parameter_preserves_existing_row_values():
    """Adding a parameter must not wipe values already typed in other rows.

    Regression guard for the reported bug: after filling parameter 1 and
    clicking "Add parameter", the re-rendered row 0 must retain its values.
    Otherwise ``_collect_parameters`` drops the now-blank row 0 on save and
    only the newly added parameter survives.
    """
    # Simulate: one parameter row already filled by the user.
    count, rows = editor.add_parameter(1, 0, [], [])
    assert count == 1
    values = _extract_field_values(rows)
    values[("0", "name")] = "person1_id"
    values[("0", "label")] = "First person"
    values[("0", "type")] = "person_id"
    values[("0", "required")] = ["required"]
    values[("0", "placeholder")] = "e.g. github::Person::alice"
    values[("0", "description")] = "WBA canonical Person ID"
    values[("0", "env_var")] = "PERSON1_ID"

    # Now the user clicks "Add parameter" again to add a second row.
    # The current field values/ids are passed in so existing rows are preserved.
    field_values = [values[("0", f)] for f in ["name", "label", "type", "required",
                                               "placeholder", "description", "env_var"]]
    field_ids = _param_ids(0)
    count2, rows2 = editor.add_parameter(1, count, field_values, field_ids)

    assert count2 == 2
    extracted = _extract_field_values(rows2)
    # Row 0 must still hold the values the user typed before adding row 1.
    assert extracted[("0", "name")] == "person1_id"
    assert extracted[("0", "label")] == "First person"
    assert extracted[("0", "type")] == "person_id"
    assert extracted[("0", "required")] == ["required"]
    assert extracted[("0", "placeholder")] == "e.g. github::Person::alice"
    assert extracted[("0", "description")] == "WBA canonical Person ID"
    assert extracted[("0", "env_var")] == "PERSON1_ID"
    # The new row is blank.
    assert extracted[("1", "name")] == ""


def test_remove_parameter_preserves_remaining_row_values(monkeypatch):
    """Removing a parameter must not wipe the surviving rows' values.

    Regression guard for the same class of bug as add: ``remove_parameter``
    re-renders the remaining rows, so their typed values must be preserved
    and re-indexed contiguously.
    """
    # Two filled rows.
    count, rows = editor.add_parameter(1, 0, [], [])
    assert count == 1
    values = _extract_field_values(rows)
    values[("0", "name")] = "person1_id"
    values[("0", "label")] = "First person"
    values[("0", "type")] = "person_id"
    values[("0", "required")] = ["required"]
    values[("0", "placeholder")] = "e.g. github::Person::alice"
    values[("0", "description")] = "WBA canonical Person ID"
    values[("0", "env_var")] = "PERSON1_ID"
    field_values = [values[("0", f)] for f in ["name", "label", "type", "required",
                                               "placeholder", "description", "env_var"]]
    field_ids = _param_ids(0)
    count2, rows2 = editor.add_parameter(1, count, field_values, field_ids)
    assert count2 == 2
    values2 = _extract_field_values(rows2)
    values2[("1", "name")] = "person2_id"
    values2[("1", "label")] = "Second person"
    values2[("1", "type")] = "person_id"
    values2[("1", "required")] = ["required"]
    values2[("1", "placeholder")] = "e.g. github::Person::bob"
    values2[("1", "description")] = "WBA canonical Person ID"
    values2[("1", "env_var")] = "PERSON2_ID"
    field_values2 = [values2[("0", f)] for f in ["name", "label", "type", "required",
                                                 "placeholder", "description", "env_var"]]
    field_values2 += [values2[("1", f)] for f in ["name", "label", "type", "required",
                                                  "placeholder", "description", "env_var"]]
    field_ids2 = _param_ids(0) + _param_ids(1)

    # Remove row 0; row 1's values must survive and re-index to row 0.
    class _FakeContext:
        triggered = True
        triggered_id = {"type": "editor-param-remove", "index": "0"}

    monkeypatch.setattr(editor, "callback_context", _FakeContext())
    count3, rows3 = editor.remove_parameter([1, None], count2, field_values2, field_ids2)

    assert count3 == 1
    extracted = _extract_field_values(rows3)
    assert extracted[("0", "name")] == "person2_id"
    assert extracted[("0", "label")] == "Second person"
    assert extracted[("0", "type")] == "person_id"
    assert extracted[("0", "required")] == ["required"]
    assert extracted[("0", "placeholder")] == "e.g. github::Person::bob"
    assert extracted[("0", "description")] == "WBA canonical Person ID"
    assert extracted[("0", "env_var")] == "PERSON2_ID"


# ── E1: editor loads query ─────────────────────────────────────────────


def test_e1_editor_loads_query(monkeypatch):
    """An edit route fetches and populates the form from the query."""
    fake = _FakeRequests([_FakeResponse(_query_payload(), 200)])
    monkeypatch.setattr(editor, "requests", fake)

    result = editor.load_query("edit", "/app/library/edit/github/top_committers")

    assert fake.get_calls[0]["url"].endswith(
        "/api/v1/queries/catalog/github/top_committers"
    )
    # (store, name, description, summary, owner, status, tags,
    #  tabular, graph, default_view, param_count, params, feedback)
    assert result[0] == {
        "mode": "edit",
        "id": "github/top_committers",
        "namespace": "github",
        "slug": "top_committers",
        "origin": "builtin",
    }
    assert result[1] == "Top Committers"
    assert result[7] == "MATCH (n) RETURN n LIMIT 10"


def test_e1b_new_route_leaves_form_blank(monkeypatch):
    """The new route leaves the form blank without a GET."""
    fake = _FakeRequests([])
    monkeypatch.setattr(editor, "requests", fake)

    result = editor.load_query("new", "/app/library/new")

    assert fake.get_calls == []
    assert result[0] == {"mode": "new"}
    assert result[1] == ""


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
        state["field_ids"],
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
        state["field_ids"],
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
        state["field_ids"],
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
        state["field_ids"],
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


# ── E8: Destructive action → DELETE → reset or navigate ───────────────


def test_e8_reset_deletes_and_reloads(monkeypatch):
    """Resetting an override issues DELETE then reloads the form with system data."""
    fake = _FakeRequests(
        [
            _FakeResponse({"message": "Query override deleted"}, 200),
            _FakeResponse(_query_payload(), 200),
        ]
    )
    monkeypatch.setattr(editor, "requests", fake)

    result = editor.destructive_action(
        1,
        {"mode": "edit", "id": "github/top_committers", "origin": "override"},
        "/app/library/edit/github/top_committers",
    )

    assert fake.delete_calls[0]["url"].endswith(
        "/api/v1/queries/catalog/github/top_committers"
    )
    assert fake.get_calls[0]["url"].endswith(
        "/api/v1/queries/catalog/github/top_committers"
    )
    assert result[1] == "Top Committers"
    assert "reset to factory" in str(result[13]).lower()


def test_e8b_override_button_label_and_message():
    """An override shows 'Reset to Factory' with a reset confirmation message."""
    label, style = editor.update_destructive_button(
        {"mode": "edit", "origin": "override"}
    )
    assert label == "Reset to Factory"
    assert style["display"] != "none"

    message, displayed = editor.confirm_destructive(
        1, "Top Committers", {"mode": "edit", "origin": "override"}
    )
    assert displayed is True
    assert "Reset" in message
    assert "cannot be undone" in message


# ── E9: Delete → confirm → DELETE → navigate to Library ───────────────


def test_e9_confirm_delete_shows_dialog():
    """Clicking Delete shows the confirmation dialog with the query name."""
    message, displayed = editor.confirm_destructive(
        1, "Top Committers", {"mode": "edit", "origin": "custom"}
    )
    assert displayed is True
    assert "Top Committers" in message
    assert "cannot be undone" in message


def test_e9b_delete_issues_delete_and_navigates_to_library(monkeypatch):
    """Confirming delete issues DELETE then navigates back to the Library."""
    fake = _FakeRequests([_FakeResponse({"message": "Query override deleted"}, 200)])
    monkeypatch.setattr(editor, "requests", fake)

    result = editor.destructive_action(
        1,
        {"mode": "edit", "id": "github/top_committers", "origin": "custom"},
        "/app/library/edit/github/top_committers",
    )

    assert fake.delete_calls[0]["url"].endswith(
        "/api/v1/queries/catalog/github/top_committers"
    )
    assert result[12] == "/app/library"
    assert result[13] is None or "Delete failed" not in str(result[13])


def test_e9c_delete_failure_shows_error(monkeypatch):
    """A failed delete surfaces an error alert and stays on the editor."""
    fake = _FakeRequests(
        [_FakeResponse({"detail": "Not found"}, 404)]
    )
    monkeypatch.setattr(editor, "requests", fake)

    result = editor.destructive_action(
        1,
        {"mode": "edit", "id": "github/top_committers", "origin": "custom"},
        "/app/library/edit/github/top_committers",
    )

    assert fake.delete_calls[0]["url"].endswith(
        "/api/v1/queries/catalog/github/top_committers"
    )
    assert result[12] is None or result[12] != "/app/library"
    assert "Delete failed" in str(result[13])


def test_e9d_custom_button_label_and_message():
    """A brand-new custom query shows 'Delete' with a delete confirmation message."""
    label, style = editor.update_destructive_button(
        {"mode": "edit", "origin": "custom"}
    )
    assert label == "Delete"
    assert style["display"] != "none"

    message, displayed = editor.confirm_destructive(
        1, "My Query", {"mode": "edit", "origin": "custom"}
    )
    assert displayed is True
    assert "Delete" in message
    assert "cannot be undone" in message


def test_e9e_builtin_hides_destructive_button():
    """A pure built-in shows no destructive button."""
    label, style = editor.update_destructive_button(
        {"mode": "edit", "origin": "builtin"}
    )
    assert style["display"] == "none"
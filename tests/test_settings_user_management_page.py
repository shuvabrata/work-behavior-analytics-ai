"""Unit tests for the User Management settings page."""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import pytest

pytestmark = pytest.mark.unit


def _iter_components(node: Any) -> Iterator[Any]:
    """Yield every component in a Dash layout tree, depth-first."""
    yield node
    children = getattr(node, "children", None)
    if children is None:
        return
    if not isinstance(children, (list, tuple)):
        children = [children]
    for child in children:
        yield from _iter_components(child)


def _registered_nav_card_types() -> set[str]:
    """Return every pattern-match card ``type`` a nav callback listens on."""
    import dash._callback as dash_callback

    from ui.layout import create_dash_app

    create_dash_app()
    types = set()
    for entry in dash_callback.GLOBAL_CALLBACK_MAP.values():
        if not isinstance(entry, dict) or not entry.get("inputs"):
            continue
        for input_spec in entry["inputs"]:
            if input_spec.get("property") != "n_clicks_timestamp":
                continue
            component_id = input_spec.get("id")
            if not (isinstance(component_id, str) and component_id.startswith("{")):
                continue
            types.add(json.loads(component_id)["type"])
    return types


class _Resp:
    """Minimal ``requests.Response`` stand-in."""

    def __init__(self, payload: Any, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code
        self.text = ""

    @property
    def ok(self) -> bool:
        return self.status_code < 400

    def json(self) -> Any:
        return self._payload


def _install_transport(monkeypatch: pytest.MonkeyPatch, handler: Any) -> None:
    from ui import api_client

    monkeypatch.setattr(api_client, "_transport", handler)


class TestHubCard:
    def test_hub_has_user_management_card(self) -> None:
        from ui.pages.settings.layout import SETTINGS_CARD_TYPE, get_layout

        ids = [getattr(node, "id", None) for node in _iter_components(get_layout())]
        assert {"type": SETTINGS_CARD_TYPE, "card_id": "user-management"} in ids

    def test_card_route_mapping(self) -> None:
        from ui.pages.settings.layout import SETTINGS_CARD_ROUTES

        assert SETTINGS_CARD_ROUTES["user-management"] == "/app/settings/user-management"

    def test_nav_callback_listens_on_settings_type(self) -> None:
        from ui.pages.settings.layout import SETTINGS_CARD_TYPE

        assert SETTINGS_CARD_TYPE in _registered_nav_card_types()


class TestRoute:
    def test_display_page_returns_page(self) -> None:
        from ui.layout import create_dash_app
        from ui.pages.settings.user_management.layout import get_layout

        app = create_dash_app()
        callback = app.callback_map["page-content.children"]["callback"].__wrapped__
        rendered = callback("/app/settings/user-management")
        assert repr(rendered) == repr(get_layout())


class TestModalForms:
    """Every modal field needs a visible label, not just a placeholder.

    A placeholder disappears once the field is filled, leaving the form
    unlabeled — which is what an admin sees on the Edit form, where every
    value is pre-populated.
    """

    LABELED_FIELDS = {
        "um-create": [
            "um-create-username",
            "um-create-email",
            "um-create-first-name",
            "um-create-last-name",
            "um-create-password",
        ],
        "um-edit": ["um-edit-email", "um-edit-first-name", "um-edit-last-name"],
        "um-password": ["um-password-value"],
    }

    @pytest.mark.parametrize("field_ids", sorted(LABELED_FIELDS.values()), ids=sorted(LABELED_FIELDS))
    def test_every_field_has_a_label(self, field_ids: list[str]) -> None:
        from ui.pages.settings.user_management.layout import get_layout

        components = list(_iter_components(get_layout()))
        labelled = {
            node.html_for for node in components if type(node).__name__ == "Label"
        }
        for field_id in field_ids:
            assert field_id in labelled, f"{field_id} has no label"

    def test_labels_target_existing_inputs(self) -> None:
        """A label pointing at a non-existent id is as bad as no label."""
        from ui.pages.settings.user_management.layout import get_layout

        components = list(_iter_components(get_layout()))
        input_ids = {
            node.id
            for node in components
            if type(node).__name__ in ("Input", "Checklist") and isinstance(node.id, str)
        }
        for node in components:
            if type(node).__name__ == "Label":
                assert node.html_for in input_ids, f"{node.html_for} is not an input id"

    def test_modal_inputs_are_compact(self) -> None:
        """Modal inputs use ``size="sm"``, matching the rest of the app."""
        from ui.pages.settings.user_management.layout import get_layout

        modal_prefixes = ("um-create-", "um-edit-", "um-password-")
        inputs = [
            node
            for node in _iter_components(get_layout())
            if type(node).__name__ == "Input"
            and isinstance(node.id, str)
            and node.id.startswith(modal_prefixes)
            and node.id != "um-search"
        ]
        assert inputs
        for node in inputs:
            props = node.to_plotly_json()["props"]
            assert props.get("size") == "sm", f"{node.id} is not compact"


class TestLayout:
    def test_roles_store_starts_empty(self) -> None:
        from ui.pages.settings.user_management.layout import get_layout

        stores = {
            node.id: node
            for node in _iter_components(get_layout())
            if isinstance(getattr(node, "id", None), str) and node.id == "um-roles"
        }
        assert stores["um-roles"].data == []

    def test_search_input_uses_theme_aware_class(self) -> None:
        """The search box must carry the styled class, not a bare native input.

        ``dcc.Input`` renders no ``className`` at all, so the dark-theme
        ``.form-control`` rules never reach it and the box stays white in dark
        mode. ``dbc.Input`` with ``catalog-search-input`` picks up the
        theme-aware background (see ``executive-dashboard.css``).
        """
        from ui.pages.settings.user_management.layout import get_layout

        search = next(
            node
            for node in _iter_components(get_layout())
            if getattr(node, "id", None) == "um-search"
        )
        props = search.to_plotly_json()["props"]
        assert props.get("className") == "catalog-search-input"

    def test_pagination_has_page_indicator(self) -> None:
        from ui.pages.settings.user_management.layout import get_layout

        ids = [getattr(node, "id", None) for node in _iter_components(get_layout())]
        for expected in ("um-prev", "um-page-indicator", "um-next"):
            assert expected in ids

    def test_load_callback_allows_initial_duplicate(self) -> None:
        """Guards the empty-on-landing bug.

        The load callback is keyed on ``url.pathname``, but its outputs do not
        exist until the user navigates here, so Dash fires it as an initial call.
        ``prevent_initial_call=True`` would suppress that first fire and leave
        the table permanently empty until the search box changed — the page must
        allow it instead.

        Dash normalises ``"initial_duplicate"`` to ``False`` in the registered
        spec (only ``True`` suppresses), so the assertion is "not True": that is
        exactly the distinction between the fixed page and the bug.
        """
        import dash._callback as dash_callback

        from ui.layout import create_dash_app

        create_dash_app()
        specs = [
            spec
            for spec in dash_callback.GLOBAL_CALLBACK_LIST
            if "um-table.children" in str(spec.get("output", ""))
        ]
        assert len(specs) == 1
        assert specs[0]["prevent_initial_call"] is not True

    def test_table_uses_theme_aware_class(self) -> None:
        """The table must carry ``executive-table`` or it renders white in dark mode.

        That class is the shared themed table (see ``executive-dashboard.css``):
        it drives the header/row backgrounds from theme variables. A bare
        ``dbc.Table`` falls back to Bootstrap's own white background.
        """
        from ui.pages.settings.user_management.layout import _render_table

        table = _render_table([{"id": "u1", "username": "alice", "enabled": True, "roles": []}])
        assert "executive-table" in table.to_plotly_json()["props"].get("className", "")

    def test_delete_button_is_outline_danger(self) -> None:
        """Destructive actions use ``outline-danger`` only (UI standard)."""
        from ui.pages.settings.user_management.layout import _render_table

        table = _render_table([{"id": "u1", "username": "alice", "enabled": True, "roles": []}])
        delete_buttons = [
            node
            for node in _iter_components(table)
            if isinstance(getattr(node, "id", None), dict)
            and node.id.get("action") == "delete"
        ]
        assert delete_buttons
        assert all(btn.color == "outline-danger" for btn in delete_buttons)

    def test_row_action_buttons_use_lined_variants(self) -> None:
        """Edit/Password render as lined buttons, not borderless ``link`` text.

        Matches the row-action pattern in ``connectors/callbacks.py``: solid
        ``secondary`` for non-destructive actions, ``outline-danger`` for the
        destructive one. ``color="link"`` renders borderless text, which is not
        a pattern used for row actions elsewhere in the app.
        """
        from ui.pages.settings.user_management.layout import _render_table

        table = _render_table([{"id": "u1", "username": "alice", "enabled": True, "roles": []}])
        by_action = {
            node.id["action"]: node
            for node in _iter_components(table)
            if isinstance(getattr(node, "id", None), dict) and "action" in node.id
        }
        assert set(by_action) == {"edit", "password", "delete"}
        assert by_action["edit"].color == "secondary"
        assert by_action["password"].color == "secondary"
        assert not any(btn.color == "link" for btn in by_action.values())


class TestRenderUsersPage:
    def test_renders_assignable_roles_not_wba_service(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from ui.pages.settings.user_management.callbacks import render_users_page

        def transport(method: str, url: str, *, params: Any = None, json: Any = None, timeout: Any = None) -> _Resp:
            if url.endswith("/admin/users/roles"):
                return _Resp({"roles": ["wba-admin", "wba-user"]})
            return _Resp({"users": [], "total": 0, "offset": 0, "limit": 25})

        _install_transport(monkeypatch, transport)
        _table, _feedback, roles, create_roles, edit_roles, _prev, _next, _page = render_users_page(
            {"offset": 0, "limit": 25, "search": ""}
        )

        assert roles == ["wba-admin", "wba-user"]
        labels = [
            option["label"]
            for container in create_roles
            for option in container.options
        ]
        assert labels == ["wba-admin", "wba-user"]
        assert "wba-service" not in labels
        edit_labels = [
            option["label"] for container in edit_roles for option in container.options
        ]
        assert "wba-service" not in edit_labels

    def test_permission_denied_renders_alert(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from ui import api_client
        from ui.pages.settings.user_management.callbacks import render_users_page

        def transport(method: str, url: str, *, params: Any = None, json: Any = None, timeout: Any = None) -> _Resp:
            raise api_client.PermissionDeniedError(403, message="forbidden")

        _install_transport(monkeypatch, transport)
        _table, feedback, _roles, _create, _edit, prev_disabled, next_disabled, _page = render_users_page(
            {"offset": 0, "limit": 25, "search": ""}
        )

        assert prev_disabled is True
        assert next_disabled is True
        text = repr(feedback)
        assert "You do not have permission to manage users" in text

    def test_next_disabled_on_last_page(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from ui.pages.settings.user_management.callbacks import render_users_page

        def transport(method: str, url: str, *, params: Any = None, json: Any = None, timeout: Any = None) -> _Resp:
            if url.endswith("/admin/users/roles"):
                return _Resp({"roles": ["wba-admin", "wba-user"]})
            return _Resp({"users": [], "total": 10, "offset": 0, "limit": 25})

        _install_transport(monkeypatch, transport)
        _table, _feedback, _roles, _create, _edit, prev_disabled, next_disabled, page_label = render_users_page(
            {"offset": 0, "limit": 25, "search": ""}
        )
        assert prev_disabled is True
        assert next_disabled is True
        assert page_label == "Page 1"

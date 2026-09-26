"""Callbacks for the Library query editor page."""

from __future__ import annotations

import os
from typing import Any

import requests
from dash import (
    ALL,
    Input,
    Output,
    State,
    callback,
    callback_context,
    no_update,
)
from dash.exceptions import PreventUpdate

from app.runtime_settings import runtime_settings
from app.dash_app.components.common import create_alert
from app.dash_app.pages.graph.utils import (
    create_error_alert,
    create_table_display,
)
from .editor_layout import render_parameter_row

TIMEOUT_SECONDS = runtime_settings.get_int("HTTP_REQUEST_TIMEOUT")


def _get_api_base_url() -> str:
    """Return the configured API base URL (falls back to localhost)."""
    return os.getenv("API_BASE_URL", "http://localhost:8000")


def _parse_route(pathname: str | None) -> tuple[str, str | None, str | None]:
    """Parse the editor route.

    Returns:
        A tuple of ``(mode, namespace, slug)`` where ``mode`` is ``"new"``
        for the new-query route and ``"edit"`` otherwise. For ``"new"`` the
        namespace and slug are ``None``.
    """
    if not pathname:
        return "edit", None, None
    stripped = pathname.rstrip("/")
    if stripped == "/app/library/new":
        return "new", None, None
    if stripped.startswith("/app/library/edit/"):
        remainder = stripped.split("/app/library/edit/")[-1]
        parts = remainder.split("/")
        if len(parts) >= 2:
            return "edit", parts[0], parts[1]
    return "edit", None, None


def _build_payload(
    name: str,
    description: str,
    summary: str | None,
    owner: str | None,
    status: str | None,
    tags: str | None,
    tabular_query: str,
    graph_query: str,
    default_view: str | None,
    parameters: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build the PUT request body from the editor form state."""
    queries: dict[str, str] = {}
    if tabular_query and tabular_query.strip():
        queries["tabular"] = tabular_query.strip()
    if graph_query and graph_query.strip():
        queries["graph"] = graph_query.strip()

    tag_list = [tag.strip() for tag in (tags or "").split(",") if tag.strip()]

    return {
        "name": name,
        "description": description,
        "summary": summary or None,
        "owner": owner or None,
        "status": status or None,
        "tags": tag_list,
        "queries": queries,
        "default_view": default_view or None,
        "parameters": parameters,
    }


def _collect_parameters(
    param_count: int,
    field_values: list[list[str]],
) -> list[dict[str, Any]]:
    """Collect parameter rows from the pattern-matched field inputs.

    Args:
        param_count: Number of parameter rows currently rendered.
        field_values: The ``value`` list from the ALL pattern-matched field
            inputs, ordered by (index, field) as declared in the callback.
    """
    parameters: list[dict[str, Any]] = []
    for index in range(param_count):
        row: dict[str, Any] = {}
        for field_index, field in enumerate(
            ["name", "label", "type", "required", "placeholder", "description", "env_var"]
        ):
            value = field_values[index * 7 + field_index]
            if field == "required":
                row[field] = bool(value)
            elif value:
                row[field] = value
        if row.get("name"):
            parameters.append(row)
    return parameters


@callback(
    Output("editor-route", "data"),
    Output("editor-namespaces-store", "data"),
    Input("url", "pathname"),
)
def init_editor(pathname: str | None) -> tuple[str, Any]:
    """Record the route mode and load namespaces on mount."""
    mode, _, _ = _parse_route(pathname)
    api_base = _get_api_base_url()
    try:
        ns_resp = requests.get(
            f"{api_base}/api/v1/queries/catalog/namespaces", timeout=TIMEOUT_SECONDS
        )
        ns_resp.raise_for_status()
        namespaces = ns_resp.json().get("items", [])
    except requests.exceptions.RequestException:
        namespaces = []
    return mode, namespaces


@callback(
    Output("editor-store", "data"),
    Output("editor-id-display", "children"),
    Output("editor-namespace-display", "children"),
    Output("editor-slug-display", "children"),
    Output("editor-name", "value"),
    Output("editor-description", "value"),
    Output("editor-summary", "value"),
    Output("editor-owner", "value"),
    Output("editor-status", "value"),
    Output("editor-tags", "value"),
    Output("editor-query-tabular", "value"),
    Output("editor-query-graph", "value"),
    Output("editor-default-view", "value"),
    Output("editor-param-count", "data"),
    Output("editor-params-container", "children"),
    Output("editor-feedback", "children", allow_duplicate=True),
    Input("editor-route", "data"),
    State("url", "pathname"),
    prevent_initial_call=True,
)
def load_query(
    mode: str | None,
    pathname: str | None,
) -> tuple[Any, ...]:
    """Populate the editor form on mount.

    For the ``new`` route the form is left blank with editable slug and
    namespace. For an edit route the existing query is fetched and loaded.
    """
    if mode == "new":
        return (
            {"mode": "new"},
            "",
            "",
            "",
            "",
            "",
            None,
            None,
            None,
            "",
            "",
            "",
            None,
            0,
            [],
            no_update,
        )

    _, namespace, slug = _parse_route(pathname)
    if not namespace or not slug:
        return (
            {"mode": "edit"},
            "",
            "",
            "",
            "",
            "",
            None,
            None,
            None,
            "",
            "",
            "",
            None,
            0,
            [],
            create_alert(
                "Could not determine the query to edit.", color="danger", class_name="mb-3"
            ),
        )

    api_base = _get_api_base_url()
    try:
        resp = requests.get(
            f"{api_base}/api/v1/queries/catalog/{namespace}/{slug}",
            timeout=TIMEOUT_SECONDS,
        )
        if resp.status_code != 200:
            detail = resp.json().get("detail", "Unknown error")
            return (
                {"mode": "edit"},
                "",
                "",
                "",
                "",
                "",
                None,
                None,
                None,
                "",
                "",
                "",
                None,
                0,
                [],
                create_alert(
                    f"Failed to load query: {detail}", color="danger", class_name="mb-3"
                ),
            )
        resp.raise_for_status()
        query = resp.json()
    except requests.exceptions.RequestException as exc:
        return (
            {"mode": "edit"},
            "",
            "",
            "",
            "",
            "",
            None,
            None,
            None,
            "",
            "",
            "",
            None,
            0,
            [],
            create_alert(f"Failed to load query: {exc}", color="danger", class_name="mb-3"),
        )

    queries = query.get("queries") or {}
    parameters = query.get("parameters") or []
    param_rows = [render_parameter_row(index, param) for index, param in enumerate(parameters)]

    return (
        {"mode": "edit", "id": query.get("id"), "namespace": namespace, "slug": slug},
        query.get("id") or "",
        namespace,
        slug,
        query.get("name") or "",
        query.get("description") or "",
        query.get("summary"),
        query.get("owner"),
        query.get("status"),
        ", ".join(query.get("tags") or []),
        queries.get("tabular") or "",
        queries.get("graph") or "",
        query.get("default_view"),
        len(parameters),
        param_rows,
        no_update,
    )


@callback(
    Output("editor-param-count", "data", allow_duplicate=True),
    Output("editor-params-container", "children", allow_duplicate=True),
    Input("editor-param-add", "n_clicks"),
    State("editor-param-count", "data"),
    prevent_initial_call=True,
)
def add_parameter(n_clicks: int | None, count: int | None) -> tuple[int, list[Any]]:
    """Append a blank parameter row."""
    if not n_clicks:
        raise PreventUpdate
    new_count = (count or 0) + 1
    rows = [render_parameter_row(index) for index in range(new_count)]
    return new_count, rows


@callback(
    Output("editor-param-count", "data", allow_duplicate=True),
    Output("editor-params-container", "children", allow_duplicate=True),
    Input({"type": "editor-param-remove", "index": ALL}, "n_clicks"),
    State("editor-param-count", "data"),
    prevent_initial_call=True,
)
def remove_parameter(
    n_clicks_list: list[int | None],
    count: int | None,
) -> tuple[int, list[Any]]:
    """Remove the clicked parameter row."""
    if not callback_context.triggered:
        raise PreventUpdate
    if not any(n is not None for n in n_clicks_list):
        raise PreventUpdate
    triggered = callback_context.triggered_id
    if not isinstance(triggered, dict):
        raise PreventUpdate
    index = int(triggered.get("index", -1))
    if index < 0:
        raise PreventUpdate
    new_count = max(0, (count or 0) - 1)
    rows = [render_parameter_row(i) for i in range(new_count)]
    return new_count, rows


@callback(
    Output("editor-feedback", "children", allow_duplicate=True),
    Input("editor-save", "n_clicks"),
    State("editor-route", "data"),
    State("url", "pathname"),
    State("editor-name", "value"),
    State("editor-description", "value"),
    State("editor-summary", "value"),
    State("editor-owner", "value"),
    State("editor-status", "value"),
    State("editor-tags", "value"),
    State("editor-query-tabular", "value"),
    State("editor-query-graph", "value"),
    State("editor-default-view", "value"),
    State("editor-param-count", "data"),
    State({"type": "editor-param-field", "index": ALL, "field": ALL}, "value"),
    prevent_initial_call=True,
)
def save_query(
    n_clicks: int | None,
    route: dict[str, Any] | None,
    pathname: str | None,
    name: str | None,
    description: str | None,
    summary: str | None,
    owner: str | None,
    status: str | None,
    tags: str | None,
    tabular_query: str | None,
    graph_query: str | None,
    default_view: str | None,
    param_count: int | None,
    field_values: list[list[str]],
) -> Any:
    """Save the query via PUT to the current namespace/slug."""
    if not n_clicks:
        raise PreventUpdate

    mode, namespace, slug = _parse_route(pathname)
    if mode == "new":
        return create_alert(
            "Use Save As to create a new query with a namespace and slug.",
            color="warning",
            class_name="mb-3",
        )

    if not namespace or not slug:
        return create_alert(
            "Missing namespace or slug.", color="danger", class_name="mb-3"
        )

    parameters = _collect_parameters(param_count or 0, field_values)
    payload = _build_payload(
        name or "",
        description or "",
        summary,
        owner,
        status,
        tags,
        tabular_query or "",
        graph_query or "",
        default_view,
        parameters,
    )

    api_base = _get_api_base_url()
    try:
        resp = requests.put(
            f"{api_base}/api/v1/queries/catalog/{namespace}/{slug}",
            json=payload,
            timeout=TIMEOUT_SECONDS,
        )
        if resp.status_code not in (200, 201):
            detail = resp.json().get("detail", "Unknown error")
            return create_alert(f"Save failed: {detail}", color="danger", class_name="mb-3")
        resp.raise_for_status()
        return create_alert(
            "Query saved.", color="success", class_name="mb-3", duration=5000
        )
    except requests.exceptions.RequestException as exc:
        return create_alert(f"Save failed: {exc}", color="danger", class_name="mb-3")


@callback(
    Output("editor-save-as-modal", "is_open"),
    Output("editor-save-as-namespace", "options"),
    Output("editor-save-as-open", "data"),
    Input("editor-save-as", "n_clicks"),
    Input("editor-save-as-cancel", "n_clicks"),
    State("editor-namespaces-store", "data"),
    State("editor-save-as-open", "data"),
    prevent_initial_call=True,
)
def toggle_save_as_modal(
    open_clicks: int | None,
    cancel_clicks: int | None,
    namespaces: list[dict[str, Any]] | None,
    is_open: bool | None,
) -> tuple[bool, list[dict[str, str]], bool]:
    """Open/close the Save As modal and populate the namespace dropdown."""
    if not callback_context.triggered:
        raise PreventUpdate
    triggered = callback_context.triggered_id
    if triggered == "editor-save-as":
        options = [
            {"label": ns.get("name") or ns.get("directory"), "value": ns.get("directory")}
            for ns in (namespaces or [])
        ]
        options.append({"label": "+ New namespace…", "value": "__new__"})
        return True, options, True
    if triggered == "editor-save-as-cancel":
        return False, no_update, False
    raise PreventUpdate


@callback(
    Output("editor-save-as-namespace-custom", "style"),
    Input("editor-save-as-namespace", "value"),
    prevent_initial_call=True,
)
def toggle_custom_namespace(namespace_value: str | None) -> dict[str, Any]:
    """Reveal the custom namespace input when '+ New namespace…' is chosen."""
    if namespace_value == "__new__":
        return {"display": "block", "marginTop": "12px"}
    return {"display": "none", "marginTop": "12px"}


@callback(
    Output("editor-feedback", "children", allow_duplicate=True),
    Output("editor-save-as-modal", "is_open", allow_duplicate=True),
    Input("editor-save-as-submit", "n_clicks"),
    State("editor-save-as-namespace", "value"),
    State("editor-save-as-namespace-custom", "value"),
    State("editor-save-as-slug", "value"),
    State("editor-name", "value"),
    State("editor-description", "value"),
    State("editor-summary", "value"),
    State("editor-owner", "value"),
    State("editor-status", "value"),
    State("editor-tags", "value"),
    State("editor-query-tabular", "value"),
    State("editor-query-graph", "value"),
    State("editor-default-view", "value"),
    State("editor-param-count", "data"),
    State({"type": "editor-param-field", "index": ALL, "field": ALL}, "value"),
    prevent_initial_call=True,
)
def save_as_query(
    n_clicks: int | None,
    namespace_value: str | None,
    custom_namespace: str | None,
    slug: str | None,
    name: str | None,
    description: str | None,
    summary: str | None,
    owner: str | None,
    status: str | None,
    tags: str | None,
    tabular_query: str | None,
    graph_query: str | None,
    default_view: str | None,
    param_count: int | None,
    field_values: list[list[str]],
) -> tuple[Any, bool]:
    """Save the query to a new namespace/slug via PUT."""
    if not n_clicks:
        raise PreventUpdate

    if namespace_value == "__new__":
        namespace = (custom_namespace or "").strip()
    else:
        namespace = namespace_value or ""
    slug = (slug or "").strip()

    if not namespace or not slug:
        return (
            create_alert(
                "Namespace and slug are required.", color="warning", class_name="mb-3"
            ),
            True,
        )

    parameters = _collect_parameters(param_count or 0, field_values)
    payload = _build_payload(
        name or "",
        description or "",
        summary,
        owner,
        status,
        tags,
        tabular_query or "",
        graph_query or "",
        default_view,
        parameters,
    )

    api_base = _get_api_base_url()
    try:
        resp = requests.put(
            f"{api_base}/api/v1/queries/catalog/{namespace}/{slug}",
            json=payload,
            timeout=TIMEOUT_SECONDS,
        )
        if resp.status_code not in (200, 201):
            detail = resp.json().get("detail", "Unknown error")
            return (
                create_alert(f"Save failed: {detail}", color="danger", class_name="mb-3"),
                True,
            )
        resp.raise_for_status()
        return (
            create_alert(
                f"Saved as {namespace}/{slug}.",
                color="success",
                class_name="mb-3",
                duration=5000,
            ),
            False,
        )
    except requests.exceptions.RequestException as exc:
        return (
            create_alert(f"Save failed: {exc}", color="danger", class_name="mb-3"),
            True,
        )


def _run_test(query_text: str | None) -> Any:
    """Execute a raw Cypher query and render the results pane.

    Returns:
        The results pane children (an alert on error, a table on success).
    """
    if not query_text or not query_text.strip():
        return create_alert(
            "Enter a query before testing.", color="warning", class_name="mb-3"
        )

    payload = {
        "source": "raw",
        "query": query_text.strip(),
        "view": "auto",
    }
    api_base = _get_api_base_url()
    try:
        resp = requests.post(
            f"{api_base}/api/v1/graph/execute",
            json=payload,
            timeout=TIMEOUT_SECONDS,
        )
        if resp.status_code not in (200, 400, 422, 500):
            resp.raise_for_status()
        if resp.status_code != 200:
            try:
                error_data = resp.json()
            except ValueError:
                error_data = {}
            return create_error_alert(
                error_data.get("detail", {}).get("message", "Query execution failed."),
                alert_type="danger",
                heading="Query Execution Failed",
            )
        data = resp.json()
        if data.get("isGraph"):
            return create_alert(
                f"Graph result: {data.get('resultCount', 0)} records.",
                color="success",
                class_name="mb-3",
                duration=5000,
            )
        return create_table_display(data.get("rawResults") or [])
    except requests.exceptions.RequestException as exc:
        return create_alert(f"Test failed: {exc}", color="danger", class_name="mb-3")


@callback(
    Output("editor-test-results", "children"),
    Input("editor-test-tabular", "n_clicks"),
    State("editor-query-tabular", "value"),
    prevent_initial_call=True,
)
def test_tabular(n_clicks: int | None, query_text: str | None) -> Any:
    """Test the Tabular Query textarea."""
    if not n_clicks:
        raise PreventUpdate
    return _run_test(query_text)


@callback(
    Output("editor-test-results", "children", allow_duplicate=True),
    Input("editor-test-graph", "n_clicks"),
    State("editor-query-graph", "value"),
    prevent_initial_call=True,
)
def test_graph(n_clicks: int | None, query_text: str | None) -> Any:
    """Test the Graph Query textarea."""
    if not n_clicks:
        raise PreventUpdate
    return _run_test(query_text)


@callback(
    Output("editor-reset-confirm", "message"),
    Output("editor-reset-confirm", "displayed"),
    Input("editor-reset", "n_clicks"),
    State("editor-name", "value"),
    State("editor-route", "data"),
    prevent_initial_call=True,
)
def confirm_reset(
    n_clicks: int | None,
    name: str | None,
    route: dict[str, Any] | None,
) -> tuple[str, bool]:
    """Show the reset confirmation dialog."""
    if not n_clicks:
        raise PreventUpdate
    display_name = name or (route or {}).get("id") or "this query"
    return (
        f"Reset '{display_name}' to factory defaults? All user edits will be "
        "lost. This cannot be undone.",
        True,
    )


@callback(
    Output("editor-store", "data", allow_duplicate=True),
    Output("editor-id-display", "children", allow_duplicate=True),
    Output("editor-namespace-display", "children", allow_duplicate=True),
    Output("editor-slug-display", "children", allow_duplicate=True),
    Output("editor-name", "value", allow_duplicate=True),
    Output("editor-description", "value", allow_duplicate=True),
    Output("editor-summary", "value", allow_duplicate=True),
    Output("editor-owner", "value", allow_duplicate=True),
    Output("editor-status", "value", allow_duplicate=True),
    Output("editor-tags", "value", allow_duplicate=True),
    Output("editor-query-tabular", "value", allow_duplicate=True),
    Output("editor-query-graph", "value", allow_duplicate=True),
    Output("editor-default-view", "value", allow_duplicate=True),
    Output("editor-param-count", "data", allow_duplicate=True),
    Output("editor-params-container", "children", allow_duplicate=True),
    Output("editor-feedback", "children", allow_duplicate=True),
    Input("editor-reset-confirm", "submit_n_clicks"),
    State("editor-route", "data"),
    State("url", "pathname"),
    prevent_initial_call=True,
)
def reset_query(
    n_clicks: int | None,
    route: dict[str, Any] | None,
    pathname: str | None,
) -> tuple[Any, ...]:
    """Delete the user override and reload the form with system data."""
    if not n_clicks:
        raise PreventUpdate

    _, namespace, slug = _parse_route(pathname)
    if not namespace or not slug:
        return (
            no_update,
            no_update,
            no_update,
            no_update,
            no_update,
            no_update,
            no_update,
            no_update,
            no_update,
            no_update,
            no_update,
            no_update,
            no_update,
            no_update,
            no_update,
            create_alert(
                "Cannot reset: missing namespace or slug.", color="danger", class_name="mb-3"
            ),
        )

    api_base = _get_api_base_url()
    try:
        resp = requests.delete(
            f"{api_base}/api/v1/queries/catalog/{namespace}/{slug}",
            timeout=TIMEOUT_SECONDS,
        )
        if resp.status_code not in (200, 204):
            detail = resp.json().get("detail", "Unknown error")
            return (
                no_update,
                no_update,
                no_update,
                no_update,
                no_update,
                no_update,
                no_update,
                no_update,
                no_update,
                no_update,
                no_update,
                no_update,
                no_update,
                no_update,
                no_update,
                create_alert(
                    f"Reset failed: {detail}", color="danger", class_name="mb-3"
                ),
            )
    except requests.exceptions.RequestException as exc:
        return (
            no_update,
            no_update,
            no_update,
            no_update,
            no_update,
            no_update,
            no_update,
            no_update,
            no_update,
            no_update,
            no_update,
            no_update,
            no_update,
            no_update,
            no_update,
            create_alert(f"Reset failed: {exc}", color="danger", class_name="mb-3"),
        )

    # Reload the form with system data.
    try:
        get_resp = requests.get(
            f"{api_base}/api/v1/queries/catalog/{namespace}/{slug}",
            timeout=TIMEOUT_SECONDS,
        )
        if get_resp.status_code != 200:
            return (
                no_update,
                no_update,
                no_update,
                no_update,
                no_update,
                no_update,
                no_update,
                no_update,
                no_update,
                no_update,
                no_update,
                no_update,
                no_update,
                no_update,
                no_update,
                create_alert(
                    "Override reset. Reload the page to see factory defaults.",
                    color="success",
                    class_name="mb-3",
                    duration=5000,
                ),
            )
        get_resp.raise_for_status()
        query = get_resp.json()
    except requests.exceptions.RequestException as exc:
        return (
            no_update,
            no_update,
            no_update,
            no_update,
            no_update,
            no_update,
            no_update,
            no_update,
            no_update,
            no_update,
            no_update,
            no_update,
            no_update,
            no_update,
            no_update,
            create_alert(f"Reset failed: {exc}", color="danger", class_name="mb-3"),
        )

    queries = query.get("queries") or {}
    parameters = query.get("parameters") or []
    param_rows = [render_parameter_row(index, param) for index, param in enumerate(parameters)]

    return (
        {"mode": "edit", "id": query.get("id"), "namespace": namespace, "slug": slug},
        query.get("id") or "",
        namespace,
        slug,
        query.get("name") or "",
        query.get("description") or "",
        query.get("summary"),
        query.get("owner"),
        query.get("status"),
        ", ".join(query.get("tags") or []),
        queries.get("tabular") or "",
        queries.get("graph") or "",
        query.get("default_view"),
        len(parameters),
        param_rows,
        create_alert(
            "Query reset to factory defaults.",
            color="success",
            class_name="mb-3",
            duration=5000,
        ),
    )
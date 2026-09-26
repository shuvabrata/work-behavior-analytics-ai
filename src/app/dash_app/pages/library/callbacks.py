"""Callbacks for the Library (query catalog) listing page."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import tempfile
from typing import Any

import requests
from dash import ALL, Input, Output, State, callback, callback_context, html, no_update
from dash.exceptions import PreventUpdate

from app.runtime_settings import runtime_settings
from app.query_catalog import get_default_catalog_dir, load_catalog
from app.dash_app.components.common import create_alert
from .layout import render_library_table

TIMEOUT_SECONDS = runtime_settings.get_int("HTTP_REQUEST_TIMEOUT")


def _get_api_base_url() -> str:
    """Return the configured API base URL (falls back to localhost)."""
    return os.getenv("API_BASE_URL", "http://localhost:8000")


def _load_system_ids() -> set[str]:
    """Return the ids of the system-only catalog (no user overrides).

    Loads the catalog from a temporary directory that has no
    ``user_defined/`` subdirectory, so the merge in :func:`load_catalog`
    never runs. The resulting id set is used to distinguish override rows
    (a user row whose id also exists in the system catalog) from addition
    rows (a user row with a brand-new id).
    """
    catalog_dir = get_default_catalog_dir()
    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        shutil.copy2(catalog_dir / "catalog.yaml", tmp_dir / "catalog.yaml")
        for entry in catalog_dir.iterdir():
            if entry.is_dir() and entry.name != "user_defined":
                (tmp_dir / entry.name).symlink_to(entry, target_is_directory=True)
        system_queries = load_catalog(tmp_dir)
    return {query.id for query in system_queries}


def _parse_id(query_id: str) -> tuple[str, str]:
    """Split a ``namespace/slug`` catalog id into its two segments."""
    namespace, _, slug = query_id.partition("/")
    return namespace, slug


@callback(
    Output("library-store", "data"),
    Output("library-namespaces-store", "data"),
    Output("library-system-ids-store", "data"),
    Input("url", "pathname"),
)
def load_library(pathname: str | None) -> tuple[Any, Any, Any]:
    """Load the catalog, namespaces, and system ids when the page mounts."""
    if pathname not in ("/app/library", "/app/library/"):
        return no_update, no_update, no_update

    api_base = _get_api_base_url()
    try:
        catalog_resp = requests.get(
            f"{api_base}/api/v1/queries/catalog", timeout=TIMEOUT_SECONDS
        )
        catalog_resp.raise_for_status()
        ns_resp = requests.get(
            f"{api_base}/api/v1/queries/catalog/namespaces", timeout=TIMEOUT_SECONDS
        )
        ns_resp.raise_for_status()
        system_ids = sorted(_load_system_ids())
        return (
            catalog_resp.json().get("items", []),
            ns_resp.json().get("items", []),
            system_ids,
        )
    except requests.exceptions.RequestException:
        return [], [], []


@callback(
    Output("library-namespace-filter", "options"),
    Input("library-namespaces-store", "data"),
)
def populate_namespace_dropdown(
    namespaces: list[dict[str, Any]] | None,
) -> list[dict[str, str]]:
    """Populate the namespace filter dropdown from the namespaces store."""
    if not namespaces:
        return []
    options: list[dict[str, str]] = []
    for ns in namespaces:
        directory = ns.get("directory")
        if not isinstance(directory, str):
            continue
        options.append(
            {
                "label": str(ns.get("name") or directory),
                "value": directory,
            }
        )
    return options


@callback(
    Output("library-table-container", "children"),
    Input("library-store", "data"),
    Input("library-namespace-filter", "value"),
    Input("library-search-input", "value"),
    State("library-system-ids-store", "data"),
)
def render_table(
    queries: list[dict[str, Any]] | None,
    namespace: str | None,
    search: str | None,
    system_ids: list[str] | None,
) -> Any:
    """Render the catalog table, applying namespace and search filters."""
    if queries is None:
        return html.Div(
            "Loading catalog…",
            style={"color": "var(--color-gray-medium)", "fontFamily": "'Inter', sans-serif"},
        )
    return render_library_table(
        queries,
        set(system_ids or []),
        namespace=namespace,
        search=search,
    )


@callback(
    Output("url", "pathname", allow_duplicate=True),
    Input({"type": "library-edit-btn", "id": ALL}, "n_clicks"),
    prevent_initial_call=True,
)
def handle_edit_click(n_clicks_list: list[int | None]) -> Any:
    """Navigate to the editor for the clicked query."""
    if not callback_context.triggered:
        raise PreventUpdate
    if not any(n is not None for n in n_clicks_list):
        raise PreventUpdate
    triggered = callback_context.triggered_id
    if not isinstance(triggered, dict):
        raise PreventUpdate
    query_id = triggered.get("id")
    if not query_id:
        raise PreventUpdate
    namespace, slug = _parse_id(query_id)
    return f"/app/library/edit/{namespace}/{slug}"


@callback(
    Output("url", "pathname", allow_duplicate=True),
    Input("library-new-btn", "n_clicks"),
    prevent_initial_call=True,
)
def handle_new_click(n_clicks: int | None) -> Any:
    """Navigate to the new-query editor."""
    if not n_clicks:
        raise PreventUpdate
    return "/app/library/new"


@callback(
    Output("library-delete-confirm", "message"),
    Output("library-delete-confirm", "displayed"),
    Output("library-pending-delete", "data"),
    Input({"type": "library-destructive-btn", "id": ALL}, "n_clicks"),
    State("library-store", "data"),
    State("library-system-ids-store", "data"),
    prevent_initial_call=True,
)
def handle_destructive_click(
    n_clicks_list: list[int | None],
    queries: list[dict[str, Any]] | None,
    system_ids: list[str] | None,
) -> tuple[str, bool, dict[str, str]]:
    """Show the confirm dialog for a destructive action.

    Override rows (id present in the system catalog) reset to factory;
    addition rows (new id) are deleted outright.
    """
    if not callback_context.triggered:
        raise PreventUpdate
    if not any(n is not None for n in n_clicks_list):
        raise PreventUpdate
    triggered = callback_context.triggered_id
    if not isinstance(triggered, dict):
        raise PreventUpdate
    query_id = triggered.get("id")
    if not query_id:
        raise PreventUpdate

    query = next(
        (q for q in (queries or []) if q.get("id") == query_id),
        None,
    )
    if not query:
        raise PreventUpdate

    name = query.get("name") or query_id
    system_ids_set = set(system_ids or [])
    if query_id in system_ids_set:
        message = (
            f"Are you sure you want to reset '{name}' to factory defaults? "
            "This will discard all user edits for this query. This cannot be undone."
        )
    else:
        message = f"Are you sure you want to delete '{name}'? This cannot be undone."

    return message, True, {"id": query_id}


@callback(
    Output("library-store", "data", allow_duplicate=True),
    Output("library-feedback", "children", allow_duplicate=True),
    Input("library-delete-confirm", "submit_n_clicks"),
    State("library-pending-delete", "data"),
    prevent_initial_call=True,
)
def confirm_delete(
    n_clicks: int | None,
    pending: dict[str, str] | None,
) -> tuple[Any, Any]:
    """Execute the DELETE and refresh the table on confirm."""
    if not n_clicks:
        raise PreventUpdate
    if not pending:
        raise PreventUpdate

    query_id = pending.get("id")
    if not query_id:
        raise PreventUpdate
    namespace, slug = _parse_id(query_id)
    api_base = _get_api_base_url()

    try:
        resp = requests.delete(
            f"{api_base}/api/v1/queries/catalog/{namespace}/{slug}",
            timeout=TIMEOUT_SECONDS,
        )
        if resp.status_code not in (200, 204):
            detail = resp.json().get("detail", "Unknown error")
            return no_update, create_alert(
                f"Delete failed: {detail}", color="danger", class_name="mb-3"
            )

        catalog_resp = requests.get(
            f"{api_base}/api/v1/queries/catalog", timeout=TIMEOUT_SECONDS
        )
        catalog_resp.raise_for_status()
        return (
            catalog_resp.json().get("items", []),
            create_alert(
                "Query deleted.", color="success", class_name="mb-3", duration=5000
            ),
        )
    except requests.exceptions.RequestException as exc:
        return no_update, create_alert(
            f"Delete failed: {exc}", color="danger", class_name="mb-3"
        )
"""Callbacks for the Library (query catalog) listing page."""

from __future__ import annotations

import os
from typing import Any

import requests
from dash import (
    Input,
    Output,
    State,
    callback,
    clientside_callback,
    no_update,
)
from dash.exceptions import PreventUpdate

from app.runtime_settings import runtime_settings
from app.dash_app.components.common import create_alert

TIMEOUT_SECONDS = runtime_settings.get_int("HTTP_REQUEST_TIMEOUT")


def _get_api_base_url() -> str:
    """Return the configured API base URL (falls back to localhost)."""
    return os.getenv("API_BASE_URL", "http://localhost:8000")


def _system_ids_from_items(items: list[dict[str, Any]]) -> list[str]:
    """Derive the system-only query ids from the catalog API response.

    A row is user-defined iff its ``source_path`` lives under
    ``user_defined/``. Everything else is a system query. This avoids a
    redundant re-parse of the YAML catalog (which was the source of a
    multi-second page-load delay).
    """
    return sorted(
        item["id"]
        for item in items
        if "user_defined/" not in (item.get("source_path") or "")
    )


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
        items = catalog_resp.json().get("items", [])
        system_ids = _system_ids_from_items(items)
        return (
            items,
            ns_resp.json().get("items", []),
            system_ids,
        )
    except requests.exceptions.RequestException:
        return [], [], []


@callback(
    Output("library-namespace-filter", "options"),
    Output("library-namespace-filter", "value"),
    Input("library-namespaces-store", "data"),
)
def populate_namespace_dropdown(
    namespaces: list[dict[str, Any]] | None,
) -> tuple[list[dict[str, str]], str]:
    """Populate the namespace filter from the namespaces store.

    Mirrors the Graph page's Query Library filter: an "All namespaces"
    (``__all__``) default followed by each namespace, ordered by ``order``.
    """
    options: list[dict[str, str]] = [{"label": "All namespaces", "value": "__all__"}]
    if namespaces:
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
    return options, "__all__"


# Build the table body rows entirely in JavaScript from the raw catalog data.
# This avoids Dash's per-component instantiation cost for 140+ rows (the
# source of the multi-second page-load delay) and keeps search/namespace
# filtering fully client-side and instant.
clientside_callback(
    """
    function(queries, systemIds, searchValue, namespaceValue) {
        var tbody = document.getElementById('library-table-body');
        var empty = document.getElementById('library-empty-row');
        if (!tbody) return window.dash_clientside.no_update;
        var search = (searchValue || '').trim().toLowerCase();
        var namespace = namespaceValue || '__all__';
        var systemSet = {};
        for (var i = 0; i < (systemIds || []).length; i++) systemSet[systemIds[i]] = true;

        function esc(s) {
            return String(s == null ? '' : s)
                .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
                .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
        }
        function searchable(q) {
            var parts = [
                q.name, q.id, q.summary, q.owner, q.status, q.default_view,
                (q.tags || []).join(' '),
                (q.source_path || '').indexOf('user_defined/') !== -1 ? 'User' : 'System'
            ];
            return parts.join(' ').toLowerCase();
        }

        var rows = [];
        var anyVisible = false;
        for (var i = 0; i < (queries || []).length; i++) {
            var q = queries[i];
            var ns = (q.namespace || {}).directory || '';
            var nsMatch = (namespace === '__all__') || (ns === namespace);
            var searchMatch = !search || searchable(q).indexOf(search) !== -1;
            var visible = nsMatch && searchMatch;
            if (visible) anyVisible = true;

            var isUser = (q.source_path || '').indexOf('user_defined/') !== -1;
            var statusColor = {active: 'success', draft: 'warning', deprecated: 'secondary'}[q.status];
            var statusHtml = statusColor
                ? '<span class="badge text-bg-' + statusColor + '" style="font-size:12px">' + esc(q.status) + '</span>'
                : '&mdash;';
            var tagHtml = (q.tags || []).map(function(t) {
                return '<span class="badge text-bg-light me-1" style="font-size:12px">' + esc(t) + '</span>';
            }).join('');
            var viewsHtml = '';
            var views = q.available_views || [];
            if (views.indexOf('tabular') !== -1) viewsHtml += '<i class="fas fa-table me-1" title="Tabular"></i>';
            if (views.indexOf('graph') !== -1) viewsHtml += '<i class="fas fa-project-diagram" title="Graph"></i>';
            if (!viewsHtml) viewsHtml = '&mdash;';
            var paramCount = (q.parameters || []).length;
            var defaultView = q.default_view || '&mdash;';
            var source = isUser ? 'User' : 'System';
            var destructiveLabel = isUser ? (systemSet[q.id] ? 'Reset to factory' : 'Delete') : '';
            var destructiveBtn = destructiveLabel
                ? '<button class="btn btn-outline-danger btn-sm" data-action="destructive" data-id="' + esc(q.id) + '">' + esc(destructiveLabel) + '</button>'
                : '';
            // The Edit button navigates directly via onclick. It is a plain
            // HTML button (not a Dash component), so Dash has no n_clicks for
            // it — relying on a children-input callback would never fire
            // because the table body is set via innerHTML and the children
            // output returns no_update. q.id is a path-safe "namespace/slug",
            // so embedding it in the URL is safe.
            var editBtn = '<button class="btn btn-primary btn-sm me-1" data-action="edit" data-id="' + esc(q.id) + '" onclick="window.location.href=&quot;/app/library/edit/' + q.id + '&quot;">Edit</button>';

            rows.push(
                '<tr data-namespace="' + esc(ns) + '" data-search="' + esc(searchable(q)) + '"' +
                (visible ? '' : ' style="display:none"') + '>' +
                '<td>' + esc(q.name || q.id) + '</td>' +
                '<td>' + esc(q.summary || '&mdash;') + '</td>' +
                '<td>' + tagHtml + '</td>' +
                '<td>' + statusHtml + '</td>' +
                '<td>' + esc(defaultView) + '</td>' +
                '<td>' + paramCount + '</td>' +
                '<td>' + viewsHtml + '</td>' +
                '<td>' + esc(source) + '</td>' +
                '<td>' + editBtn + destructiveBtn + '</td>' +
                '</tr>'
            );
        }
        tbody.innerHTML = rows.join('');
        if (empty) empty.style.display = anyVisible ? 'none' : '';
        return window.dash_clientside.no_update;
    }
    """,
    Output("library-table-container", "children", allow_duplicate=True),
    Input("library-store", "data"),
    Input("library-system-ids-store", "data"),
    Input("library-search-input", "value"),
    Input("library-namespace-filter", "value"),
    prevent_initial_call=True,
)


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


# Destructive button clicks (plain HTML buttons with data-action="destructive").
# Determines override vs addition and shows the confirm dialog.
clientside_callback(
    """
    function(_n, queries, systemIds) {
        var btn = document.querySelector('[data-action="destructive"]');
        if (!btn) return window.dash_clientside.no_update;
        var id = btn.getAttribute('data-id') || '';
        if (!id) return window.dash_clientside.no_update;
        var query = null;
        for (var i = 0; i < (queries || []).length; i++) {
            if (queries[i].id === id) { query = queries[i]; break; }
        }
        if (!query) return window.dash_clientside.no_update;
        var name = query.name || id;
        var systemSet = {};
        for (var j = 0; j < (systemIds || []).length; j++) systemSet[systemIds[j]] = true;
        var message;
        if (systemSet[id]) {
            message = "Are you sure you want to reset '" + name + "' to factory defaults? " +
                "This will discard all user edits for this query. This cannot be undone.";
        } else {
            message = "Are you sure you want to delete '" + name + "'? This cannot be undone.";
        }
        return [message, true, {id: id}];
    }
    """,
    Output("library-delete-confirm", "message"),
    Output("library-delete-confirm", "displayed"),
    Output("library-pending-delete", "data"),
    Input("library-table-container", "children"),
    State("library-store", "data"),
    State("library-system-ids-store", "data"),
    prevent_initial_call=True,
)


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
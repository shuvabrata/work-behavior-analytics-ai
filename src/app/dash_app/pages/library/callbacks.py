"""Callbacks for the Library (query catalog) listing page."""

from __future__ import annotations

from typing import Any

import requests
from dash import (
    Input,
    Output,
    callback,
    clientside_callback,
    no_update,
)
from dash.exceptions import PreventUpdate

from app.runtime_settings import runtime_settings
from ._utils import get_api_base_url

TIMEOUT_SECONDS = runtime_settings.get_int("HTTP_REQUEST_TIMEOUT")


@callback(
    Output("library-store", "data"),
    Output("library-namespaces-store", "data"),
    Input("url", "pathname"),
)
def load_library(pathname: str | None) -> tuple[Any, Any]:
    """Load the catalog and namespaces when the page mounts."""
    if pathname not in ("/app/library", "/app/library/"):
        return no_update, no_update

    api_base = get_api_base_url()
    try:
        catalog_resp = requests.get(
            f"{api_base}/api/v1/queries/catalog", timeout=TIMEOUT_SECONDS
        )
        catalog_resp.raise_for_status()
        ns_resp = requests.get(
            f"{api_base}/api/v1/queries/catalog/namespaces", timeout=TIMEOUT_SECONDS
        )
        ns_resp.raise_for_status()
        return (
            catalog_resp.json().get("items", []),
            ns_resp.json().get("items", []),
        )
    except requests.exceptions.RequestException:
        return [], []


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
    function(queries, searchValue, namespaceValue) {
        var tbody = document.getElementById('library-table-body');
        var empty = document.getElementById('library-empty-row');
        if (!tbody) return window.dash_clientside.no_update;
        var search = (searchValue || '').trim().toLowerCase();
        var namespace = namespaceValue || '__all__';

        function esc(s) {
            return String(s == null ? '' : s)
                .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
                .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
        }
        function searchable(q) {
            var parts = [
                q.name, q.id, q.summary, q.owner, q.status, q.default_view,
                (q.tags || []).join(' '),
                q.origin === 'builtin' ? 'Built-in' : (q.origin === 'override' ? 'Overridden' : 'Custom')
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

            // "active" is the common/default status, so it stays as plain text;
            // the non-default statuses are highlighted with a badge so colours
            // draw the eye to rows that need attention.
            var statusColor = {draft: 'warning', deprecated: 'secondary'}[q.status];
            var statusHtml = q.status === 'active'
                ? esc(q.status)
                : (statusColor
                    ? '<span class="badge text-bg-' + statusColor + '" style="font-size:12px">' + esc(q.status) + '</span>'
                    : '&mdash;');
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
            // "Built-in" rows stay as plain text; "Overridden" and "Custom"
            // rows are highlighted with a badge so colours draw the eye to
            // user-modified queries (matching the "env" badge in Settings ->
            // Runtime Settings, which uses text-bg-info).
            var origin = q.origin || 'builtin';
            var source = origin === 'builtin'
                ? 'Built-in'
                : '<span class="badge text-bg-info" style="font-size:12px">' + (origin === 'override' ? 'Overridden' : 'Custom') + '</span>';
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
                '<td>' + source + '</td>' +
                '<td>' + editBtn + '</td>' +
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
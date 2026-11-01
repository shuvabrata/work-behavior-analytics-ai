"""The single declarative authorization table for the API.

Every route's required role is declared here and applied at include time or in
the route decorator. ``tests/test_authz_matrix.py`` enumerates the live app and
asserts that every operation appears here with the declared dependency actually
attached, so a new route without a declaration fails CI rather than defaulting
open.
"""

from __future__ import annotations

from typing import Literal

Role = Literal["public", "session", "user", "admin", "service"]
Grant = Role | frozenset[Role]

#: (http method, full path template) -> required authorization.
#: - "public"  : no dependency at all; deliberately open.
#: - "session" : no bearer dependency; the handler validates the wba_session cookie.
#: - "user"    : require_user  — wba-user, wba-admin *and* wba-service.
#: - "admin"   : require_admin — wba-admin only.
#: - "service" : require_service — wba-service only.
#: - a frozenset: require_roles(*grant) — any one of the listed roles.
AUTHZ_MATRIX: dict[tuple[str, str], Grant] = {
    # ── public ───────────────────────────────────────────────────────────
    ("GET", "/api/health"): "public",
    ("GET", "/api/v1/auth/login"): "public",
    ("GET", "/api/v1/auth/callback"): "public",
    # ── session cookie (no bearer; the handler authenticates) ────────────
    ("POST", "/api/v1/auth/logout"): "session",
    ("POST", "/api/v1/auth/token"): "session",
    # ── any authenticated principal ──────────────────────────────────────
    ("GET", "/api/v1/auth/me"): "user",
    # activity
    ("GET", "/api/v1/activity/suggest"): "user",
    ("GET", "/api/v1/activity/timeline"): "user",
    # chats
    ("POST", "/api/v1/chats/"): "user",
    ("GET", "/api/v1/chats/{session_id}"): "user",
    ("POST", "/api/v1/chats/{session_id}/stream"): "user",
    ("GET", "/api/v1/chats/metrics/stream"): "user",
    ("DELETE", "/api/v1/chats/{session_id}"): "user",
    # commands
    ("GET", "/api/v1/commands/"): "user",
    ("GET", "/api/v1/commands/{command_id}"): "user",
    ("POST", "/api/v1/commands/"): frozenset({"admin", "service"}),
    ("PATCH", "/api/v1/commands/{command_id}/status"): "service",
    # connectors — reads are user; writes and /test are admin
    ("GET", "/api/v1/connectors/"): "user",
    ("GET", "/api/v1/connectors/{connector_type}"): "user",
    ("GET", "/api/v1/connectors/{connector_type}/configs"): "user",
    ("PATCH", "/api/v1/connectors/{connector_type}"): "admin",
    ("DELETE", "/api/v1/connectors/{connector_type}/config"): "admin",
    ("POST", "/api/v1/connectors/{connector_type}/configs"): "admin",
    ("PUT", "/api/v1/connectors/{connector_type}/configs/{item_id}"): "admin",
    ("PATCH", "/api/v1/connectors/{connector_type}/configs/{item_id}/status"): "admin",
    ("DELETE", "/api/v1/connectors/{connector_type}/configs/{item_id}"): "admin",
    ("DELETE", "/api/v1/connectors/{connector_type}"): "admin",
    ("POST", "/api/v1/connectors/{connector_type}/test"): "admin",
    # graph
    ("POST", "/api/v1/graph/execute"): "user",
    ("POST", "/api/v1/graph/expand"): "user",
    ("GET", "/api/v1/graph/collaboration-network"): "user",
    ("GET", "/api/v1/graph/collaboration-network/ego"): "user",
    ("GET", "/api/v1/graph/health"): "user",
    # graph-themes — reads user; authoring and /set-default admin (Plan D owns the rest)
    ("GET", "/api/v1/graph-themes/"): "user",
    ("GET", "/api/v1/graph-themes/effective"): "user",
    ("GET", "/api/v1/graph-themes/{theme_id}"): "user",
    ("POST", "/api/v1/graph-themes/"): "admin",
    ("PATCH", "/api/v1/graph-themes/{theme_id}"): "admin",
    ("DELETE", "/api/v1/graph-themes/{theme_id}"): "admin",
    ("POST", "/api/v1/graph-themes/{theme_id}/clone"): "admin",
    ("POST", "/api/v1/graph-themes/{theme_id}/set-default"): "admin",
    # queries — browse user; catalog authoring admin; favourites user (058 scopes to own rows)
    ("GET", "/api/v1/queries/catalog"): "user",
    ("GET", "/api/v1/queries/catalog/namespaces"): "user",
    ("GET", "/api/v1/queries/catalog/{namespace}/{slug}"): "user",
    ("PUT", "/api/v1/queries/catalog/{namespace}/{slug}"): "admin",
    ("DELETE", "/api/v1/queries/catalog/{namespace}/{slug}"): "admin",
    ("GET", "/api/v1/queries/catalog-metadata"): "user",
    ("GET", "/api/v1/queries/catalog-metadata/{catalog_id:path}"): "user",
    ("PUT", "/api/v1/queries/catalog-metadata/{catalog_id:path}"): "user",
    # search
    ("GET", "/api/v1/search"): "user",
    ("POST", "/api/v1/search/scoped"): "user",
    ("GET", "/api/v1/search/persons"): "user",
    # settings — reads user (incl. the snapshot); writes admin
    ("GET", "/api/v1/settings/"): "user",
    ("GET", "/api/v1/settings/runtime-snapshot"): "user",
    ("PATCH", "/api/v1/settings/"): "admin",
    ("PATCH", "/api/v1/settings/{key}"): "admin",
    ("POST", "/api/v1/settings/reset"): "admin",
    ("POST", "/api/v1/settings/{key}/reset"): "admin",
}

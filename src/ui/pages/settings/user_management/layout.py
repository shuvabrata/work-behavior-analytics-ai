"""User Management settings page layout.

Renders the user table, pagination, search, and the create/edit/password modals
and the delete confirmation. The role checkboxes are built from the set the API
reports (fetched into ``um-roles``), never from a constant in this package, so
``ASSIGNABLE_REALM_ROLES`` stays the single source of truth.
"""

from __future__ import annotations

from typing import Any

import dash_bootstrap_components as dbc
from dash import dcc, html

from ui.components.common import create_page_header
from ui.styles import (
    CARD_CONTAINER_STYLE,
    COLOR_BORDER,
    COLOR_GRAY_MEDIUM,
    FONT_SANS,
    FONT_SIZE_SMALL,
    FONT_SIZE_XSMALL,
    SPACING_MEDIUM,
    SPACING_SMALL,
    SPACING_XSMALL,
)

DEFAULT_LIMIT = 25


def _role_checkboxes(roles: list[str], id_prefix: str) -> list[Any]:
    """Build the assignable-role checkboxes for a form, from the API's role list."""
    return [
        dbc.Checklist(
            id=f"{id_prefix}-roles",
            options=[{"label": role, "value": role} for role in roles],
            value=[],
            style={"fontFamily": FONT_SANS, "fontSize": FONT_SIZE_XSMALL},
        )
    ]


def _render_table(users: list[dict[str, Any]]) -> dbc.Table:
    """Render the user table for one page of ``UserSummary`` dicts."""
    header = html.Thead(
        html.Tr(
            [html.Th(label) for label in ("Username", "Name", "Email", "Roles", "Enabled", "Actions")]
        )
    )

    rows: list[Any] = []
    for user in users:
        user_id = str(user.get("id", ""))
        name = " ".join(
            part for part in (user.get("first_name"), user.get("last_name")) if part
        )
        rows.append(
            html.Tr(
                [
                    html.Td(user.get("username", "")),
                    html.Td(name),
                    html.Td(user.get("email") or ""),
                    html.Td(", ".join(user.get("roles", []))),
                    html.Td("Yes" if user.get("enabled") else "No"),
                    html.Td(
                        html.Div(
                            [
                                dbc.Button(
                                    "Edit",
                                    id={"type": "um-row", "action": "edit", "user_id": user_id},
                                    size="sm",
                                    color="secondary",
                                    n_clicks=0,
                                ),
                                dbc.Button(
                                    "Password",
                                    id={"type": "um-row", "action": "password", "user_id": user_id},
                                    size="sm",
                                    color="secondary",
                                    n_clicks=0,
                                ),
                                dbc.Button(
                                    "Delete",
                                    id={"type": "um-row", "action": "delete", "user_id": user_id},
                                    size="sm",
                                    color="outline-danger",
                                    n_clicks=0,
                                ),
                            ],
                            style={"display": "flex", "gap": SPACING_XSMALL},
                        )
                    ),
                ]
            )
        )

    if not rows:
        rows.append(
            html.Tr(
                html.Td(
                    "No users found.",
                    colSpan=6,
                    style={"color": COLOR_GRAY_MEDIUM, "fontSize": FONT_SIZE_SMALL},
                )
            )
        )

    return dbc.Table(
        [header, html.Tbody(rows)],
        bordered=False,
        hover=True,
        responsive=True,
        size="sm",
        className="align-middle executive-table",
        style={"fontFamily": FONT_SANS, "fontSize": FONT_SIZE_SMALL},
    )


def _create_form() -> dbc.Modal:
    return dbc.Modal(
        [
            dbc.ModalHeader(dbc.ModalTitle("New user")),
            dbc.ModalBody(
                [
                    dbc.Input(id="um-create-username", placeholder="Username", type="text"),
                    dbc.Input(
                        id="um-create-email", placeholder="Email", type="email", class_name="mt-2"
                    ),
                    dbc.Input(id="um-create-first-name", placeholder="First name", class_name="mt-2"),
                    dbc.Input(id="um-create-last-name", placeholder="Last name", class_name="mt-2"),
                    dbc.Checklist(
                        id="um-create-enabled",
                        options=[{"label": "Enabled", "value": "enabled"}],
                        value=["enabled"],
                        class_name="mt-2",
                    ),
                    html.Div(id="um-create-roles-container", className="mt-2"),
                    dbc.Input(
                        id="um-create-password",
                        placeholder="Temporary password (optional)",
                        type="password",
                        class_name="mt-2",
                    ),
                ]
            ),
            dbc.ModalFooter(
                [
                    dbc.Button(
                        "Cancel",
                        id="um-create-cancel",
                        color="secondary",
                        size="sm",
                        className="me-2",
                        n_clicks=0,
                    ),
                    dbc.Button("Create", id="um-create-save", color="primary", size="sm", n_clicks=0),
                ]
            ),
        ],
        id="um-create-modal",
        is_open=False,
    )


def _edit_form() -> dbc.Modal:
    return dbc.Modal(
        [
            dbc.ModalHeader(dbc.ModalTitle("Edit user")),
            dbc.ModalBody(
                [
                    dbc.Input(id="um-edit-email", placeholder="Email", type="email"),
                    dbc.Input(id="um-edit-first-name", placeholder="First name", class_name="mt-2"),
                    dbc.Input(id="um-edit-last-name", placeholder="Last name", class_name="mt-2"),
                    dbc.Checklist(
                        id="um-edit-enabled",
                        options=[{"label": "Enabled", "value": "enabled"}],
                        value=[],
                        class_name="mt-2",
                    ),
                    html.Div(id="um-edit-roles-container", className="mt-2"),
                ]
            ),
            dbc.ModalFooter(
                [
                    dbc.Button(
                        "Cancel",
                        id="um-edit-cancel",
                        color="secondary",
                        size="sm",
                        className="me-2",
                        n_clicks=0,
                    ),
                    dbc.Button("Save", id="um-edit-save", color="primary", size="sm", n_clicks=0),
                ]
            ),
        ],
        id="um-edit-modal",
        is_open=False,
    )


def _password_form() -> dbc.Modal:
    return dbc.Modal(
        [
            dbc.ModalHeader(dbc.ModalTitle("Reset password")),
            dbc.ModalBody(
                [
                    dbc.Input(id="um-password-value", placeholder="New password", type="password"),
                    dbc.Checklist(
                        id="um-password-temporary",
                        options=[{"label": "Require change on first login", "value": "temporary"}],
                        value=["temporary"],
                        class_name="mt-2",
                    ),
                ]
            ),
            dbc.ModalFooter(
                [
                    dbc.Button(
                        "Cancel",
                        id="um-password-cancel",
                        color="secondary",
                        size="sm",
                        className="me-2",
                        n_clicks=0,
                    ),
                    dbc.Button("Reset", id="um-password-save", color="primary", size="sm", n_clicks=0),
                ]
            ),
        ],
        id="um-password-modal",
        is_open=False,
    )


def get_layout() -> html.Div:
    """Return the User Management settings page layout."""
    return html.Div(
        [
            create_page_header(
                [("Settings", "/app/settings"), ("User Management", None)],
                "Create, edit, and remove application users.",
            ),
            html.Div(id="um-feedback"),
            dcc.Store(id="um-state", data={"offset": 0, "limit": DEFAULT_LIMIT, "search": ""}),
            dcc.Store(id="um-roles", data=[]),
            dcc.Store(id="um-refresh", data=0),
            dcc.Store(id="um-pending-delete", data=None),
            dcc.Store(id="um-edit-target", data=None),
            dcc.Store(id="um-password-target", data=None),
            dcc.ConfirmDialog(
                id="um-delete-confirm",
                message="Delete this user? This cannot be undone.",
            ),
            html.Div(
                [
                    dbc.Input(
                        id="um-search",
                        type="search",
                        placeholder="Search users by username, email, or name…",
                        debounce=True,
                        className="catalog-search-input",
                        style={"flex": "1"},
                    ),
                    dbc.Button(
                        "New user",
                        id="um-create-open",
                        color="primary",
                        size="sm",
                        n_clicks=0,
                    ),
                ],
                style={
                    "display": "flex",
                    "alignItems": "center",
                    "gap": SPACING_XSMALL,
                    "maxWidth": "650px",
                    "margin": "0 auto",
                    "marginBottom": SPACING_SMALL,
                },
            ),
            html.Div(id="um-table"),
            html.Div(
                [
                    dbc.Button(
                        [html.I(className="fas fa-chevron-left me-1"), "Previous"],
                        id="um-prev",
                        color="secondary",
                        outline=True,
                        size="sm",
                        disabled=True,
                        n_clicks=0,
                        style={"fontFamily": FONT_SANS, "fontSize": FONT_SIZE_XSMALL},
                    ),
                    html.Div(
                        "Page 1",
                        id="um-page-indicator",
                        style={
                            "fontFamily": FONT_SANS,
                            "fontSize": FONT_SIZE_XSMALL,
                            "color": COLOR_GRAY_MEDIUM,
                            "minWidth": "80px",
                            "textAlign": "center",
                        },
                    ),
                    dbc.Button(
                        ["Next", html.I(className="fas fa-chevron-right ms-1")],
                        id="um-next",
                        color="secondary",
                        outline=True,
                        size="sm",
                        disabled=True,
                        n_clicks=0,
                        style={"fontFamily": FONT_SANS, "fontSize": FONT_SIZE_XSMALL},
                    ),
                ],
                style={
                    "display": "flex",
                    "alignItems": "center",
                    "justifyContent": "center",
                    "gap": SPACING_SMALL,
                    "marginTop": SPACING_MEDIUM,
                    "paddingTop": SPACING_SMALL,
                    "borderTop": f"1px solid {COLOR_BORDER}",
                },
            ),
            _create_form(),
            _edit_form(),
            _password_form(),
        ],
        style=CARD_CONTAINER_STYLE,
    )

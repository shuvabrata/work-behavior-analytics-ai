"""Connector registry shared by the API and the UI.

``CONNECTOR_REGISTRY`` is hardcoded metadata (display name, icon, section,
implemented features, setup type, optional producer container) describing every
connector type the platform knows about. It is not a data path and holds no
secrets, so both runtimes read it directly.

It lives in ``domain`` so the UI can render the Connectors page without
importing the API package. ``app/api/connectors/v1/registry.py`` re-exports it
so the API's own ``from .registry import CONNECTOR_REGISTRY`` call sites and
any ``app.api...`` path keep resolving unchanged.

The values are the single source of truth for:
  * the Connectors page cards and their launch/scan controls
  * ``app/scheduler.py`` resolving a connector's ``producer_container``
  * ``app/api/commands/v1/service.py`` validating command targets
"""

__all__ = ["CONNECTOR_REGISTRY"]

CONNECTOR_REGISTRY = {
    "github": {
        "display_name": "GitHub",
        "icon": "fa-brands fa-github",
        "section": "connections",
        "supports_items": True,
        "setup_type": "db_backed",
        "producer_container": "github-producer",
    },
    "jira": {
        "display_name": "Jira",
        "icon": "fa-brands fa-jira",
        "section": "connections",
        "supports_items": True,
        "setup_type": "db_backed",
        "producer_container": "jira-producer",
    },
    "slack": {
        "display_name": "Slack",
        "icon": "fa-brands fa-slack",
        "section": "connections",
        "supports_items": True,
        "setup_type": "db_backed",
    },
    "teams": {
        "display_name": "Microsoft Teams",
        "icon": "fa-brands fa-microsoft",
        "section": "connections",
        "supports_items": True,
        "setup_type": "db_backed",
    },
    "confluence": {
        "display_name": "Confluence",
        "icon": "fa-brands fa-confluence",
        "section": "connections",
        "supports_items": True,
        "setup_type": "db_backed",
        "producer_container": "confluence-producer",
    },
    "google_docs": {
        "display_name": "Google Docs",
        "icon": "fa-brands fa-google",
        "section": "connections",
        "supports_items": True,
        "setup_type": "db_backed",
    },
    "sharepoint": {
        "display_name": "SharePoint",
        "icon": "fa-brands fa-microsoft",
        "section": "connections",
        "supports_items": True,
        "setup_type": "db_backed",
    },
    "email": {
        "display_name": "Email",
        "icon": "fa-solid fa-envelope",
        "section": "connections",
        "supports_items": True,
        "setup_type": "db_backed",
    },
    "atlassian_mcp": {
        "display_name": "Atlassian MCP Server",
        "icon": "fa-brands fa-atlassian",
        "section": "mcp",
        "supports_items": False,
        "setup_type": "db_backed",
    },
    "github_mcp": {
        "display_name": "GitHub MCP Server",
        "icon": "fa-brands fa-github",
        "section": "mcp",
        "supports_items": False,
        "setup_type": "manual",
    },
}

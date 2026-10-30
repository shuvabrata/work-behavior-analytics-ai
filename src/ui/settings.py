"""The UI runtime's settings singleton.

A credential-free :class:`domain.settings.UISettings` instance. The UI container
holds no database URL, no data-store credentials and no LLM provider key, so it
must never import ``app.settings`` (whose ``ApiSettings`` cannot even be
constructed without ``DATABASE_URL``).

Use ``settings.API_BASE_URL`` for the UI→API base URL and the ``UI_*`` /
``GRAPH_UI_*`` fields for display configuration. Anything the UI needs that is
not on ``UISettings`` must come from the API over HTTP, not from here.
"""

from __future__ import annotations

from domain.settings import UISettings

settings = UISettings()

__all__ = ["UISettings", "settings"]

"""Collaboration Network page package.

Exposes get_layout() so the main Dash layout can call
``collaboration_network.get_layout()`` exactly as before.
Importing this package also registers all Dash callbacks via the
callbacks sub-package.
"""

__all__ = ["get_layout"]

from app.dash_app.pages.collaboration_network.layout import get_layout

from app.dash_app.pages.collaboration_network import callbacks  # noqa: F401

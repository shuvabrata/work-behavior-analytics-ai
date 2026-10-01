"""Activity Timeline page package.

Exposes ``get_layout()`` so the main Dash layout can call
``timeline.get_layout()``.  Importing this package also registers all Dash
callbacks via the callbacks module.
"""

__all__ = ["get_layout"]

from app.dash_app.pages.timeline.layout import get_layout

from app.dash_app.pages.timeline import callbacks  # noqa: F401
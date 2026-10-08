"""Activity Timeline page package.

Exposes get_layout() and registers all Dash callbacks on import.
"""

__all__ = ["get_layout"]

from app.dash_app.pages.timeline.layout import get_layout
from app.dash_app.pages.timeline import callbacks  # noqa: F401

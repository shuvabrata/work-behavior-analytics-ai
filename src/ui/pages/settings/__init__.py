"""Settings pages."""

from .layout import get_layout
from .runtime import get_runtime_layout
from .graph_styling import get_layout as get_graph_styling_layout
from .user_management import get_layout as get_user_management_layout

# Import callbacks to register them with Dash
# pylint: disable=unused-import
from . import callbacks  # noqa: F401
from . import runtime  # noqa: F401
from . import graph_styling  # noqa: F401
from . import user_management  # noqa: F401

__all__ = [
    "get_layout",
    "get_runtime_layout",
    "get_graph_styling_layout",
    "get_user_management_layout",
]
"""Per-person (ego) Collaboration Network page package.

Importing this package registers all Dash callbacks for the ego page.
"""

# The person-picker callbacks (search, suggestion relay, pick, clear) are
# registered as a side effect of importing the Graph page's callbacks package,
# because they are pattern-matching and shared by every person picker in the app.
# Importing it here guarantees they are registered even if the user deep-links
# straight to /app/collaboration/person without visiting /app/graph first.
# noqa: F401 is intentional — this import is for its side effect only.
from ui.pages.graph import callbacks as _graph_callbacks  # noqa: F401

from ui.pages.collaboration_network_ego.layout import get_layout

from ui.pages.collaboration_network_ego import callbacks  # noqa: F401

__all__ = ["get_layout"]

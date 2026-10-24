"""Per-person Collaboration Network spotlight callbacks.

Binds the shared spotlight implementation (``app.dash_app.components.spotlight``)
to the ego page's component ids (``ego-*``), so the "Search nodes..." box behaves
identically to the Collaboration Network page's.

Importing this module registers the two spotlight callbacks as a side effect.
"""

from app.dash_app.components.spotlight import register_spotlight

register_spotlight("ego")

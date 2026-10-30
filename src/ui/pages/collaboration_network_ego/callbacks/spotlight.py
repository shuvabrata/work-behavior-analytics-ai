"""Per-person Collaboration Network spotlight callbacks.

Binds the shared spotlight implementation (``ui.components.spotlight``)
to the ego page's component ids (``ego-*``), so the "Search nodes..." box behaves
identically to the Collaboration Network page's.

Importing this module registers the two spotlight callbacks as a side effect.
"""

from ui.components.spotlight import register_spotlight

register_spotlight("ego")

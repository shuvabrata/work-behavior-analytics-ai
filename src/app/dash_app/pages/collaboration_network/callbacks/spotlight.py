"""Collaboration Network spotlight callbacks.

The implementation is shared with every other page that renders a spotlight
search box — see ``app.dash_app.components.spotlight``. This module only binds
it to the collab page's component ids (``collab-*``).

Importing this module registers the two spotlight callbacks as a side effect,
exactly as before the extraction.
"""

from app.dash_app.components.spotlight import (
    MIN_QUERY_LENGTH,
    SEARCH_FIELDS,
    apply_spotlight_classes,
    match_node,
    register_spotlight,
)

# Private aliases kept for the existing unit tests and any deep importers.
_apply_spotlight_classes = apply_spotlight_classes
_match_node = match_node
_MIN_QUERY_LENGTH = MIN_QUERY_LENGTH
_SEARCH_FIELDS = SEARCH_FIELDS

register_spotlight("collab")

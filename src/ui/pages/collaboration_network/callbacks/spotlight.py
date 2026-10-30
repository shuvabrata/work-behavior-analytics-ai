"""Collaboration Network spotlight callbacks.

The implementation is shared with every other page that renders a spotlight
search box — see ``ui.components.spotlight``. This module only binds
it to the collab page's component ids (``collab-*``).

Importing this module registers the two spotlight callbacks as a side effect,
exactly as before the extraction.
"""

from ui.components.spotlight import (
    apply_spotlight_classes,
    match_node,
    register_spotlight,
)

# Indirections the tests reach for through this module. `tests/test_collab_spotlight.py`
# imports `_apply_spotlight_classes` from here (not from components.spotlight), and
# `tests/test_spotlight_wiring.py` asserts both names *are* the shared objects — so
# they are load-bearing, and repointing the tests would turn that identity check into
# a tautology. The `MIN_QUERY_LENGTH` / `SEARCH_FIELDS` constants need no alias: no
# test imports them.
_apply_spotlight_classes = apply_spotlight_classes
_match_node = match_node

register_spotlight("collab")

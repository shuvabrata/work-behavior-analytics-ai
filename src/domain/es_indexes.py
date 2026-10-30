"""Elasticsearch index/entity metadata shared by the API, the UI and the scripts.

``MANAGED_INDEXES`` is the authoritative list of ``(source, entity_type)`` pairs
that have an Elasticsearch index. It lives in ``domain`` because three separate
places need it:

  * ``app/scripts/create_es_indexes.py`` creates one index per entry
  * ``ui/pages/search.py`` derives the search dropdowns from it
  * ``scripts/reconcile_es.py`` and ``scripts/clear_es_data.py`` iterate it
  * the ES-index test suites assert coverage of ``SUPPORTED_ENTITY_TYPES``

The index *mappings* and the script itself stay in ``app/scripts``; only the
shared metadata moves here.
"""

__all__ = ["MANAGED_INDEXES"]

# ---------------------------------------------------------------------------
# Registry of all managed (source, entity_type) pairs.
# ---------------------------------------------------------------------------
# This constant is the authoritative list used by:
#   • this script to create indexes
#   • tests/test_es_index_coverage.py to verify every SUPPORTED_ENTITY_TYPE
#     is covered
#
# CRITICAL: Any new entity type OR new source for an existing entity type MUST
# be added here AND to SUPPORTED_ENTITY_TYPES in src/common/activity_signal/models.py.
# If you miss adding a (source, entity_type) pair here:
#   1. Elasticsearch will dynamically create the index without proper text analyzers
#      (e.g., partial searches on email/name won't work).
#   2. The unmanaged index will NOT be included in the `wba_all` global search alias,
#      meaning cross-domain searches will silently fail to find these entities.
MANAGED_INDEXES: list[tuple[str, str]] = [
    ("github", "Repository"),
    ("github", "Commit"),
    ("github", "PullRequest"),
    ("github", "Issue"),
    ("github", "Person"),
    ("github", "Team"),
    ("github", "File"),
    ("jira", "Project"),
    ("jira", "Issue"),
    ("jira", "Epic"),
    ("jira", "Initiative"),
    ("jira", "Sprint"),
    ("jira", "Person"),
    ("confluence", "Space"),
    ("confluence", "Page"),
    ("confluence", "Blogpost"),
    ("confluence", "Person"),
]

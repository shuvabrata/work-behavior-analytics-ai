"""Loader for the collaboration Cypher queries.

The query files live in the ``queries`` directory beside this module, so the path
is resolved relative to this file rather than by walking up from whichever layer
happens to need a query. That keeps a moved or restructured caller from silently
pointing at the wrong directory.
"""

from pathlib import Path

QUERIES_DIR = Path(__file__).parent / "queries"
"""Directory holding this package's ``.cypher`` files."""

COLLABORATION_SCORE_QUERY = "collaboration_score.cypher"
"""Filename of the canonical collaboration scoring query."""


def load_query(name: str) -> str:
    """Return the text of a Cypher file in this package's ``queries`` directory.

    Args:
        name: Filename inside ``queries``, e.g. ``"collaboration_score.cypher"``.

    Returns:
        The file's contents, decoded as UTF-8.

    Raises:
        FileNotFoundError: If no such file exists, naming the path that was tried.
    """
    path = QUERIES_DIR / name
    if not path.exists():
        raise FileNotFoundError(f"Collaboration query file not found: {path}")
    return path.read_text(encoding="utf-8")


def load_collaboration_score_query() -> str:
    """Return the canonical collaboration scoring query.

    Used by both the org-wide and the per-person (ego) collaboration services, so
    the two views can never disagree about which query defines a collaboration.
    """
    return load_query(COLLABORATION_SCORE_QUERY)

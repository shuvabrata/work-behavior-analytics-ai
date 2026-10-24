"""Prefix-parameterised graph spotlight search.

Shared by every page that renders a ``create_controls_bar`` search box: the
spotlight highlights nodes whose searchable fields contain the query and dims
everything else, composing on top of whatever classes the page's own filters
already applied.

Client-side matching is used instead of Elasticsearch because a network page can
load 1000+ nodes, and sending that many wba_ids in an ES terms filter makes ES
return the total count while silently dropping the hits array. The fields the
match needs are already present in the element data, so no ES round-trip is
required.

Component ids are derived from ``prefix``:

- ``{prefix}-spotlight-input`` / ``{prefix}-spotlight-count`` — rendered by
  ``create_controls_bar``
- ``{prefix}-spotlight-debounced-store`` — the page's layout must declare this
- ``{prefix}-cytoscape`` — the graph being highlighted

This lives outside ``pages/`` because importing a page package runs its
``__init__`` (which registers that page's callbacks), so a second page cannot
import a helper from the first without risking a circular import.
"""

from typing import Any

from dash import Input, Output, State, callback, clientside_callback
from dash.exceptions import PreventUpdate

from app.dash_app.pages.graph.utils import is_node_data
from common.logger import logger


MIN_QUERY_LENGTH = 3
"""Queries shorter than this clear the spotlight instead of dimming the graph."""

SEARCH_FIELDS = ("label", "full_name", "name", "login", "email")
"""Node-data fields probed, in priority order, for a case-insensitive substring."""

# Held as a template rather than an f-string so the JS braces need no escaping.
# The timer name is namespaced per prefix so two pages' debounces cannot clobber
# each other if both are ever mounted.
_DEBOUNCE_JS = """
function(value) {
    if (window.__SPOTLIGHT_TIMER__) {
        clearTimeout(window.__SPOTLIGHT_TIMER__);
    }
    return new Promise(function(resolve) {
        window.__SPOTLIGHT_TIMER__ = setTimeout(function() {
            resolve(value !== undefined ? value : '');
        }, 400);
    });
}
"""


def match_node(data: dict[str, Any], query_lower: str) -> bool:
    """Return True if any searchable field in ``data`` contains ``query_lower``."""
    for field in SEARCH_FIELDS:
        val = data.get(field)
        if val and query_lower in str(val).lower():
            return True
    return False


def apply_spotlight_classes(
    elements: list[dict[str, Any]] | None,
    match_wba_ids: set[str] | None,
) -> list[dict[str, Any]]:
    """Add spotlight-match / spotlight-dim classes to Cytoscape elements.

    When ``match_wba_ids`` is None, all spotlight-* classes are stripped (clear
    mode). Edges are spotlight-match only when both endpoints match, otherwise
    spotlight-dim. Non-spotlight classes (dimmed, community, filter ...) are
    preserved.
    """
    # Pass 1 (nodes only): collect Cytoscape element ids of matching nodes
    matching_cyto_ids: set[Any] = set()
    if match_wba_ids is not None:
        for elem in (elements or []):
            data = elem.get("data", {})
            if is_node_data(data) and data.get("wba_id", "") in match_wba_ids:
                matching_cyto_ids.add(data.get("id", ""))

    modified = []
    for elem in (elements or []):
        data = elem.get("data", {})
        existing = elem.get("classes", "")
        # Preserve all non-spotlight classes (dimmed, community, filter, etc.)
        classes = {c for c in existing.split() if c and not c.startswith("spotlight-")}

        if match_wba_ids is not None:
            if is_node_data(data):
                if data.get("wba_id", "") in match_wba_ids:
                    classes.add("spotlight-match")
                else:
                    classes.add("spotlight-dim")
            else:
                # Edge: match only when both endpoints are in matching nodes
                src = data.get("source", "")
                tgt = data.get("target", "")
                if src in matching_cyto_ids and tgt in matching_cyto_ids:
                    classes.add("spotlight-match")
                else:
                    classes.add("spotlight-dim")

        modified.append({**elem, "classes": " ".join(sorted(classes))})
    return modified


def register_spotlight(prefix: str) -> None:
    """Register the spotlight callbacks for one page's components.

    Args:
        prefix: Id prefix of the page, e.g. ``"collab"`` or ``"ego"``. The page
            must render ``{prefix}-spotlight-input``, ``{prefix}-spotlight-count``
            and ``{prefix}-cytoscape``, and its layout must declare a
            ``{prefix}-spotlight-debounced-store`` dcc.Store.
    """
    cytoscape_id = f"{prefix}-cytoscape"

    clientside_callback(
        _DEBOUNCE_JS.replace("__SPOTLIGHT_TIMER__", f"_{prefix}SpotlightTimer"),
        Output(f"{prefix}-spotlight-debounced-store", "data"),
        Input(f"{prefix}-spotlight-input", "value"),
        prevent_initial_call=True,
    )

    @callback(
        Output(cytoscape_id, "elements", allow_duplicate=True),
        Output(f"{prefix}-spotlight-count", "children"),
        Input(f"{prefix}-spotlight-debounced-store", "data"),
        State(cytoscape_id, "elements"),
        prevent_initial_call=True,
    )
    def update_spotlight(
        query: str | None,
        elements: list[dict[str, Any]] | None,
    ) -> tuple[list[dict[str, Any]], str]:
        """Apply spotlight highlighting using client-side field matching."""
        if not elements:
            raise PreventUpdate

        # Clear spotlight when the query is below the minimum length
        if not query or len(query.strip()) < MIN_QUERY_LENGTH:
            return apply_spotlight_classes(elements, None), ""

        q = query.strip()
        q_lower = q.lower()

        node_elements = [e for e in elements if is_node_data(e.get("data", {}))]

        match_wba_ids = {
            e["data"]["wba_id"]
            for e in node_elements
            if e["data"].get("wba_id") and match_node(e["data"], q_lower)
        }

        node_count = len(node_elements)
        match_count = len(match_wba_ids)

        logger.info(
            f"[{prefix.capitalize()} Spotlight] query={q!r}  "
            f"node_count={node_count}  match_count={match_count}"
        )

        updated = apply_spotlight_classes(elements, match_wba_ids)
        count_text = f"{match_count} of {node_count} nodes match" if node_count > 0 else ""
        return updated, count_text

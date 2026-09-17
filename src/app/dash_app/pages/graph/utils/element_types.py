"""Helpers for determining Cytoscape element types.

Graph callbacks should use these helpers instead of ad-hoc checks so node/edge
classification logic stays consistent across the graph page.
"""

from typing import Any


def is_edge_data(data: dict[str, Any]) -> bool:
    """Return True when data belongs to an edge element."""
    return data.get("elementType") == "edge"


def is_node_data(data: dict[str, Any]) -> bool:
    """Return True when data belongs to a node element."""
    return data.get("elementType") == "node"


def is_edge_element(element: dict[str, Any]) -> bool:
    """Return True when Cytoscape element is an edge."""
    return is_edge_data(element.get("data", {}))


def is_node_element(element: dict[str, Any]) -> bool:
    """Return True when Cytoscape element is a node."""
    return is_node_data(element.get("data", {}))

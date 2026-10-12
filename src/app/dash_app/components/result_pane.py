"""Shared graph/table result-pane builders.

Used by the graph page and the catalog editor's View Test modal. The module
relies on the shared Cytoscape stylesheet module (``app.dash_app.graph_styles``)
but lives in the shared components package because two pages use it.
"""

from dash import html
import dash_cytoscape as cyto

from app.dash_app.graph_styles import CYTOSCAPE_STYLESHEET
from app.dash_app.styles import (
    GRAPH_CYTOSCAPE_STYLE,
    GRAPH_EMPTY_STATE_ICON_STYLE,
    GRAPH_EMPTY_STATE_TEXT_STYLE,
)


def create_graph_result_container(id_prefix: str = "graph") -> html.Div:
    """Create main graph visualization container with Cytoscape

    Returns:
        html.Div containing Cytoscape graph component
    """
    return html.Div(
        id=f"{id_prefix}-cytoscape-container",
        style={"display": "none"},  # Hidden initially, then maintains consistent size after first query
        children=[
            # Do not enable autoRefreshLayout=True. If the user has manually dragged nodes
            # into positions they like, add/remove nodes via filters can disturb that arrangement.
            cyto.Cytoscape(
                id=f"{id_prefix}-cytoscape",
                elements=[],
                layout={'name': 'cose', 'animate': True, 'spacingFactor': 1.5},
                style=GRAPH_CYTOSCAPE_STYLE,
                stylesheet=CYTOSCAPE_STYLESHEET,
                userZoomingEnabled=True,
                userPanningEnabled=True,
                wheelSensitivity=0.3,
                minZoom=0.05,
                maxZoom=3
            )
        ]
    )


def create_table_result_container(id_prefix: str = "graph") -> html.Div:
    """Create container for tabular query results

    Returns:
        html.Div for displaying tables
    """
    return html.Div(
        id=f"{id_prefix}-table-container",
        style={"display": "none"}  # Hidden by default
    )


def create_results_empty_state(id_prefix: str = "graph") -> html.Div:
    """Create empty state display (shown before any query execution)

    Returns:
        html.Div with empty state message
    """
    return html.Div(
        id=f"{id_prefix}-results-container",
        style={
            "minHeight": "calc(75vh)",
            "padding": "16px"
        },
        children=[
            html.Div(
                [
                    html.Div(
                        "◆",
                        style=GRAPH_EMPTY_STATE_ICON_STYLE
                    ),
                    html.P(
                        "No results to display. Execute a query to visualize network relationships.",
                        style=GRAPH_EMPTY_STATE_TEXT_STYLE
                    )
                ],
                className="text-center",
                style={"marginTop": "80px"}
            )
        ]
    )

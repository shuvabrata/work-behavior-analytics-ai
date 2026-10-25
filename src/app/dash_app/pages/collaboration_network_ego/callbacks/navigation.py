"""Per-person (ego) Collaboration Network navigation — fit, fullwidth toggle, layout reset."""

from typing import Any
from dash import Input, Output, callback, clientside_callback

from app.dash_app.components.common import register_fullwidth_callback
from ..layout import _EGO_LAYOUT

register_fullwidth_callback("ego")


# Clientside callback — fit graph to viewport when Fit button is clicked
clientside_callback(
    """
    function(n_clicks) {
        if (n_clicks) {
            const elem = document.getElementById('ego-cytoscape');
            if (elem && elem._cyreg && elem._cyreg.cy) {
                elem._cyreg.cy.fit(null, 30);
            }
        }
        return window.dash_clientside.no_update;
    }
    """,
    Output("ego-fit-btn", "className"),
    Input("ego-fit-btn", "n_clicks"),
    prevent_initial_call=True,
)


@callback(
    Output("ego-cytoscape", "layout", allow_duplicate=True),
    Input("ego-reset-btn", "n_clicks"),
    prevent_initial_call=True,
)
def reset_ego_layout(n_clicks: int | None) -> dict[str, Any]:
    """Re-apply the preset layout to restore default zoom and pan."""
    stop_value = 1000 if (n_clicks or 0) % 2 == 0 else 1001
    return {**_EGO_LAYOUT, "stop": stop_value}

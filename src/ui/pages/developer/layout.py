"""Developer hub page layout.

Displays a grid of cards linking to developer-facing sub-pages.
"""

from dash import html
import dash_bootstrap_components as dbc

from ui.components.common import create_page_header
from ui.styles import CARD_CONTAINER_STYLE
from ui.pages.settings.components.settings_card import settings_card

DEVELOPER_CARD_TYPE = "developer-card"


def get_layout() -> html.Div:
    """Return the developer hub page layout."""
    cards = [
        settings_card(
            card_id="api",
            title="REST API",
            icon="fa-solid fa-code",
            description="Browse interactive API documentation.",
            href="/app/developer/api",
            card_type=DEVELOPER_CARD_TYPE,
        ),
        settings_card(
            card_id="mcp",
            title="MCP Server Config",
            icon="fa-solid fa-server",
            description="Connect AI agents via the Model Context Protocol.",
            coming_soon=True,
            card_type=DEVELOPER_CARD_TYPE,
        ),
    ]

    return html.Div(
        [
            create_page_header(
                [("Developer", None)],
                "API documentation and integration tools.",
            ),
            html.Div(
                dbc.Row(
                    [dbc.Col(card, md=3, sm=6, xs=12) for card in cards],
                    className="g-3",
                ),
                style=CARD_CONTAINER_STYLE,
            ),
        ]
    )

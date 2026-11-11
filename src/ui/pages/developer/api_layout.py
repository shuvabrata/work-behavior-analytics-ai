"""REST API documentation sub-page."""

from dash import html
import dash_bootstrap_components as dbc

from ui.components.common import create_page_header
from ui.styles import (
    CARD_CONTAINER_STYLE,
    COLOR_NAVY,
    COLOR_GRAY_MEDIUM,
    FONT_SANS,
    FONT_SIZE_MEDIUM,
    FONT_SIZE_SMALL,
    FONT_WEIGHT_MEDIUM,
    SPACING_SMALL,
    SPACING_XSMALL,
    COLOR_BACKGROUND_LIGHT,
    COLOR_BORDER,
)
from ui.settings import settings as app_settings


def get_api_layout() -> html.Div:
    """Return the REST API documentation sub-page layout."""
    base_url = app_settings.EXTERNAL_BASE_URL
    links = [
        {
            "title": "Swagger UI",
            "href": f"{base_url}/docs",
            "description": "Interactive REST API explorer. Try any endpoint directly from your browser.",
            "icon": "fa-solid fa-flask",
        },
        {
            "title": "ReDoc",
            "href": f"{base_url}/redoc",
            "description": "Full API reference with detailed schema descriptions and example payloads.",
            "icon": "fa-solid fa-book",
        },
    ]

    cards = [
        html.Div(
            [
                html.Div(
                    [
                        html.I(
                            className=link["icon"],
                            style={"fontSize": "20px", "color": COLOR_NAVY, "marginRight": SPACING_XSMALL},
                        ),
                        html.Div(
                            html.A(
                                link["title"],
                                href=link["href"],
                                target="_blank",
                                rel="noopener noreferrer",
                                style={"color": COLOR_NAVY, "fontWeight": FONT_WEIGHT_MEDIUM, "textDecoration": "none"},
                            ),
                            style={"fontFamily": FONT_SANS, "fontSize": FONT_SIZE_MEDIUM, "flex": 1},
                        ),
                    ],
                    style={"display": "flex", "alignItems": "center"},
                ),
                html.Div(
                    link["description"],
                    style={
                        "fontFamily": FONT_SANS,
                        "fontSize": FONT_SIZE_SMALL,
                        "color": COLOR_GRAY_MEDIUM,
                        "marginTop": SPACING_XSMALL,
                        "lineHeight": "1.5",
                    },
                ),
            ],
            style={
                "padding": SPACING_SMALL,
                "backgroundColor": COLOR_BACKGROUND_LIGHT,
                "border": f"1px solid {COLOR_BORDER}",
                "borderRadius": "2px",
            },
        )
        for link in links
    ]

    return html.Div(
        [
            create_page_header(
                [("Developer", "/app/developer"), ("REST API", None)],
                "Interactive documentation for the Work Behavior Analytics AI REST API.",
            ),
            html.Div(
                dbc.Row(
                    [dbc.Col(card, md=4, sm=6, xs=12) for card in cards],
                    className="g-3",
                ),
                style=CARD_CONTAINER_STYLE,
            ),
        ]
    )

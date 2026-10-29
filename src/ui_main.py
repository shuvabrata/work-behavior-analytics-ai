"""WSGI entrypoint for the Dash UI runtime.

The UI is a standalone service: it holds no database driver, no data-store
credentials and no LLM provider key. Every piece of data it renders arrives
over HTTP from the API (see ``src/ui/api_client.py``).
"""
from ui.layout import create_dash_app
from ui.request_logging import register_request_logging

app = create_dash_app()
server = app.server  # Flask — served by gunicorn

register_request_logging(server)

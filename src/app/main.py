"""Temporary single-process entrypoint — deleted in Step 8.

The UI and the API share one process until Step 8, which gives the UI its own
container and entrypoint. Deleting this module before then would leave
``entrypoint.sh`` (still running ``uvicorn app.main:app``) pointing at nothing,
and the stack could not be rebuilt.
"""
from a2wsgi import WSGIMiddleware

from app.api_main import app
from ui_main import server

app.mount("/app", WSGIMiddleware(server))  # type: ignore[arg-type]

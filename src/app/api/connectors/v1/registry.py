"""Re-export of the connector registry.

``CONNECTOR_REGISTRY`` now lives in :mod:`domain.connector_registry` so the UI
runtime can read it without importing the API package. This module keeps it
importable as ``app.api.connectors.v1.registry.CONNECTOR_REGISTRY`` for the
API's own call sites (``app/api/connectors/v1/service.py`` uses the relative
``from .registry import CONNECTOR_REGISTRY``).

``__all__`` is required: ``mypy`` runs strict (``no_implicit_reexport``), so an
undeclared re-export is an error at the importing site.
"""

from domain.connector_registry import CONNECTOR_REGISTRY

__all__ = ["CONNECTOR_REGISTRY"]

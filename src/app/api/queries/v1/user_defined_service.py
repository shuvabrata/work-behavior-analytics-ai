"""File I/O for user-defined query catalog overrides.

This module owns all writes and deletes under the ``user_defined/`` tree of
the query catalog. Reads funnel through :func:`app.query_catalog.load_catalog`,
which merges user overrides over the system catalog at load time — so no
changes to the read path are needed here.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from common.logger import logger
from app.api.graph.v1.query import validate_read_only_query
from app.query_catalog import (
    CatalogLoadError,
    CatalogQuery,
    CatalogQueryWrite,
    get_catalog_query,
    get_default_catalog_dir,
    load_namespaces,
)
from app.query_catalog.loader import SAFE_ID_SEGMENT, USER_DEFINED_DIR

# Fields the loader derives at load time — never written to the YAML file.
_DERIVED_FIELDS = ("id", "slug", "namespace", "available_views", "source_path")


def save_query(namespace: str, slug: str, payload: CatalogQueryWrite) -> CatalogQuery:
    """Write a user-defined query override and return the merged query.

    Args:
        namespace: Namespace directory (system or custom).
        slug: Query slug (filename stem).
        payload: Write-side model with the query definition.

    Returns:
        The merged :class:`CatalogQuery` as loaded by the catalog loader.

    Raises:
        ValueError: If the namespace/slug is not path-safe, or any query
            variant contains write operations (mapped to 422 by the router).
    """
    if not SAFE_ID_SEGMENT.fullmatch(namespace) or not SAFE_ID_SEGMENT.fullmatch(slug):
        raise ValueError(f"Invalid namespace or slug: {namespace}/{slug}")

    for view, query_text in payload.queries.items():
        if not validate_read_only_query(query_text):
            raise ValueError(f"{view} query contains write operations")

    root = get_default_catalog_dir()
    target = root / USER_DEFINED_DIR / namespace / f"{slug}.yaml"

    _ensure_namespace_declared(root, namespace)

    target.parent.mkdir(parents=True, exist_ok=True)
    serialized = _serialize_payload(payload)
    target.write_text(serialized, encoding="utf-8")
    logger.info("Saved user-defined catalog query %s/%s", namespace, slug)

    try:
        return get_catalog_query(f"{namespace}/{slug}")
    except CatalogLoadError as exc:
        logger.error("Saved user query %s/%s failed to reload: %s", namespace, slug, exc)
        raise


def delete_query(namespace: str, slug: str) -> bool:
    """Delete a user-defined query override if it exists.

    Args:
        namespace: Namespace directory.
        slug: Query slug (filename stem).

    Returns:
        ``True`` if an override file was deleted, ``False`` if none existed.
    """
    root = get_default_catalog_dir()
    target = root / USER_DEFINED_DIR / namespace / f"{slug}.yaml"
    if not target.exists():
        return False

    target.unlink()
    logger.info("Deleted user-defined catalog query %s/%s", namespace, slug)
    return True


def _serialize_payload(payload: CatalogQueryWrite) -> str:
    """Serialize a write model to YAML, excluding derived fields."""
    data = payload.model_dump(exclude=_DERIVED_FIELDS, exclude_none=True)
    return yaml.dump(data, default_flow_style=False, sort_keys=False)


def _ensure_namespace_declared(root: Path, namespace: str) -> None:
    """Ensure ``namespace`` is declared in ``user_defined/catalog.yaml``.

    System namespaces and already-declared user namespaces need no update. A
    brand-new custom namespace is appended with a humanized display name.
    """
    for existing in load_namespaces():
        if existing.directory == namespace:
            return

    user_catalog_file = root / USER_DEFINED_DIR / "catalog.yaml"
    if user_catalog_file.exists():
        data = _load_yaml_mapping(user_catalog_file)
    else:
        data = {"namespaces": []}

    raw_namespaces = data.get("namespaces")
    if not isinstance(raw_namespaces, list):
        raw_namespaces = []
        data["namespaces"] = raw_namespaces

    display_name = namespace.replace("_", " ").title()
    raw_namespaces.append({"name": display_name, "directory": namespace})

    user_catalog_file.parent.mkdir(parents=True, exist_ok=True)
    user_catalog_file.write_text(
        yaml.dump(data, default_flow_style=False, sort_keys=False),
        encoding="utf-8",
    )
    logger.info("Declared new user-defined namespace %s", namespace)


def _load_yaml_mapping(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    if not isinstance(data, dict):
        raise CatalogLoadError(f"{path} must contain a YAML mapping")
    return data
"""File I/O for user-defined query catalog overrides.

This module owns all writes and deletes under the ``user_defined/`` tree of
the query catalog. Reads funnel through :func:`app.query_catalog.load_catalog`,
which merges user overrides over the system catalog at load time — so no
changes to the read path are needed here.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any
from uuid import uuid4

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
_DERIVED_FIELDS = {"id", "slug", "namespace", "available_views", "source_path"}


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

    # The directory must exist before the namespace is declared: the loader
    # raises if a declared user namespace has no directory, so declaring first
    # would leave the catalog unloadable if this call fails in between.
    target.parent.mkdir(parents=True, exist_ok=True)

    _ensure_namespace_declared(root, namespace)

    serialized = _serialize_payload(payload)
    previous = target.read_bytes() if target.exists() else None
    _atomic_write_text(target, serialized)
    logger.info("Saved user-defined catalog query %s/%s", namespace, slug)

    try:
        return get_catalog_query(f"{namespace}/{slug}")
    except CatalogLoadError as exc:
        if previous is None:
            target.unlink(missing_ok=True)
        else:
            _atomic_write_text(target, previous.decode("utf-8"))
        logger.error(
            "Saved user query %s/%s failed to reload; rolled back: %s",
            namespace, slug, exc,
        )
        raise


def delete_query(namespace: str, slug: str) -> bool:
    """Delete a user-defined query override if it exists.

    Args:
        namespace: Namespace directory.
        slug: Query slug (filename stem).

    Returns:
        ``True`` if an override file was deleted, ``False`` if none existed.

    Raises:
        ValueError: If the namespace or slug is not path-safe. Both segments
            are interpolated into a filesystem path, so an unvalidated ``..``
            segment would escape ``user_defined/`` (mapped to 422 by the
            router).
    """
    if not SAFE_ID_SEGMENT.fullmatch(namespace) or not SAFE_ID_SEGMENT.fullmatch(slug):
        raise ValueError(f"Invalid namespace or slug: {namespace}/{slug}")
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


def _atomic_write_text(path: Path, text: str) -> None:
    """Write ``text`` to ``path`` atomically.

    Writes to a uniquely named sibling temp file and ``os.replace``s it into
    place, so a crash mid-write leaves the previous file intact rather than a
    truncated one — a truncated catalog file makes the whole catalog
    unloadable, since the loader validates every file on every read.
    """
    tmp_path = path.parent / f".{path.name}.{uuid4().hex}.tmp"
    try:
        tmp_path.write_text(text, encoding="utf-8")
        os.replace(tmp_path, path)
    except OSError:
        tmp_path.unlink(missing_ok=True)
        raise


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
    _atomic_write_text(
        user_catalog_file,
        yaml.dump(data, default_flow_style=False, sort_keys=False),
    )
    logger.info("Declared new user-defined namespace %s", namespace)


def _load_yaml_mapping(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    if not isinstance(data, dict):
        raise CatalogLoadError(f"{path} must contain a YAML mapping")
    return data
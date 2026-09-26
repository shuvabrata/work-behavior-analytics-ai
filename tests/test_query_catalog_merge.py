"""Unit tests for user-defined query catalog merge logic.

These tests build synthetic catalogs in ``tmp_path`` so they never touch the
real ``queries_catalog/`` tree.
"""

from pathlib import Path

import pytest
import yaml

from app.query_catalog import CatalogLoadError, load_catalog, load_namespaces


pytestmark = pytest.mark.unit


def _write_yaml(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data), encoding="utf-8")


def _build_system_catalog(catalog_dir: Path) -> None:
    """Create a minimal system catalog with two namespaces and two queries."""
    _write_yaml(
        catalog_dir / "catalog.yaml",
        {"namespaces": [{"name": "GitHub", "directory": "github"}]},
    )
    _write_yaml(
        catalog_dir / "github" / "top_committers.yaml",
        {
            "name": "Top Committers",
            "description": "System query.",
            "queries": {"tabular": "MATCH (n) RETURN n LIMIT 10"},
        },
    )
    _write_yaml(
        catalog_dir / "github" / "open_prs.yaml",
        {
            "name": "Open PRs",
            "description": "System query.",
            "queries": {"tabular": "MATCH (n:PR) RETURN n LIMIT 10"},
        },
    )


def _build_user_catalog(catalog_dir: Path) -> None:
    """Create a user_defined tree with one override and one addition."""
    _write_yaml(
        catalog_dir / "user_defined" / "catalog.yaml",
        {"namespaces": [{"name": "My Queries", "directory": "my_queries"}]},
    )
    _write_yaml(
        catalog_dir / "user_defined" / "github" / "top_committers.yaml",
        {
            "name": "Top Committers (User)",
            "description": "User override.",
            "queries": {"tabular": "MATCH (n) RETURN n LIMIT 5"},
        },
    )
    _write_yaml(
        catalog_dir / "user_defined" / "my_queries" / "custom_query.yaml",
        {
            "name": "Custom Query",
            "description": "Brand new query.",
            "queries": {"tabular": "MATCH (n) RETURN n LIMIT 1"},
        },
    )


def test_b1_no_user_dir_returns_system_unchanged(tmp_path):
    catalog_dir = tmp_path / "queries_catalog"
    _build_system_catalog(catalog_dir)

    queries = load_catalog(catalog_dir)
    namespaces = load_namespaces(catalog_dir)

    assert len(queries) == 2
    assert len(namespaces) == 1
    assert all(not namespace.is_user_defined for namespace in namespaces)


def test_b2_empty_user_dir_returns_system_unchanged(tmp_path):
    catalog_dir = tmp_path / "queries_catalog"
    _build_system_catalog(catalog_dir)
    (catalog_dir / "user_defined").mkdir(parents=True)

    queries = load_catalog(catalog_dir)

    assert len(queries) == 2


def test_b3_override_existing_system_query(tmp_path):
    catalog_dir = tmp_path / "queries_catalog"
    _build_system_catalog(catalog_dir)
    _build_user_catalog(catalog_dir)

    queries = load_catalog(catalog_dir)
    by_id = {query.id: query for query in queries}

    override = by_id["github/top_committers"]
    assert override.name == "Top Committers (User)"
    assert "user_defined/" in override.source_path
    assert "LIMIT 5" in override.queries["tabular"]

    # System version must be excluded — only one entry for this id.
    assert len([q for q in queries if q.id == "github/top_committers"]) == 1


def test_b4_new_query_in_existing_namespace(tmp_path):
    catalog_dir = tmp_path / "queries_catalog"
    _build_system_catalog(catalog_dir)
    _build_user_catalog(catalog_dir)

    # Rebuild a system-only catalog to get the baseline count.
    system_only = tmp_path / "system_only"
    _build_system_catalog(system_only)

    merged = load_catalog(catalog_dir)
    assert len(merged) == len(load_catalog(system_only)) + 1


def test_b5_new_query_in_custom_namespace(tmp_path):
    catalog_dir = tmp_path / "queries_catalog"
    _build_system_catalog(catalog_dir)
    _build_user_catalog(catalog_dir)

    system_only = tmp_path / "system_only"
    _build_system_catalog(system_only)

    merged_ns = load_namespaces(catalog_dir)
    system_ns = load_namespaces(system_only)
    assert len(merged_ns) == len(system_ns) + 1


def test_b6_multiple_overrides_across_namespaces(tmp_path):
    catalog_dir = tmp_path / "queries_catalog"
    _build_system_catalog(catalog_dir)
    _write_yaml(
        catalog_dir / "user_defined" / "catalog.yaml",
        {"namespaces": [{"name": "My Queries", "directory": "my_queries"}]},
    )
    (catalog_dir / "user_defined" / "my_queries").mkdir(parents=True)
    _write_yaml(
        catalog_dir / "user_defined" / "github" / "top_committers.yaml",
        {
            "name": "Top Committers (User)",
            "description": "User override.",
            "queries": {"tabular": "MATCH (n) RETURN n LIMIT 5"},
        },
    )
    _write_yaml(
        catalog_dir / "user_defined" / "github" / "open_prs.yaml",
        {
            "name": "Open PRs (User)",
            "description": "User override.",
            "queries": {"tabular": "MATCH (n:PR) RETURN n LIMIT 3"},
        },
    )

    queries = load_catalog(catalog_dir)
    by_id = {query.id: query for query in queries}

    assert by_id["github/top_committers"].name == "Top Committers (User)"
    assert by_id["github/open_prs"].name == "Open PRs (User)"
    assert len(queries) == 2


def test_b7_duplicate_slug_in_user_set_raises(tmp_path, monkeypatch):
    """Two user files resolving to the same id must raise.

    A file's id is ``{namespace.directory}/{slug}``, so two distinct files
    cannot naturally collide. We monkeypatch ``_load_query_file`` to force two
    different user files to yield the same id, exercising the guard.
    """
    import app.query_catalog.loader as loader_module

    catalog_dir = tmp_path / "queries_catalog"
    _build_system_catalog(catalog_dir)
    _write_yaml(
        catalog_dir / "user_defined" / "catalog.yaml",
        {"namespaces": [{"name": "My Queries", "directory": "my_queries"}]},
    )
    _write_yaml(
        catalog_dir / "user_defined" / "github" / "top_committers.yaml",
        {
            "name": "User A",
            "description": "User override.",
            "queries": {"tabular": "MATCH (n) RETURN n LIMIT 5"},
        },
    )
    _write_yaml(
        catalog_dir / "user_defined" / "my_queries" / "custom_query.yaml",
        {
            "name": "Custom Query",
            "description": "Brand new query.",
            "queries": {"tabular": "MATCH (n) RETURN n LIMIT 1"},
        },
    )

    real_load = loader_module._load_query_file
    user_ids_seen: list[str] = []

    def _forced_load(*, query_file, namespace, base_dir, validate_cypher):
        query = real_load(
            query_file=query_file,
            namespace=namespace,
            base_dir=base_dir,
            validate_cypher=validate_cypher,
        )
        # Only force collisions among user files (paths under user_defined/).
        if "user_defined" in str(query_file):
            if user_ids_seen:
                # Force this user file to collide with the first user file.
                query = query.model_copy(update={"id": user_ids_seen[0]})
            user_ids_seen.append(query.id)
        return query

    monkeypatch.setattr(loader_module, "_load_query_file", _forced_load)

    with pytest.raises(CatalogLoadError, match="Duplicate catalog query id"):
        load_catalog(catalog_dir)


def test_b8_user_namespace_has_is_user_defined_true(tmp_path):
    catalog_dir = tmp_path / "queries_catalog"
    _build_system_catalog(catalog_dir)
    _build_user_catalog(catalog_dir)

    namespaces = load_namespaces(catalog_dir)
    user_ns = next(ns for ns in namespaces if ns.directory == "my_queries")
    assert user_ns.is_user_defined is True


def test_b9_system_namespace_has_is_user_defined_false(tmp_path):
    catalog_dir = tmp_path / "queries_catalog"
    _build_system_catalog(catalog_dir)
    _build_user_catalog(catalog_dir)

    namespaces = load_namespaces(catalog_dir)
    system_ns = next(ns for ns in namespaces if ns.directory == "github")
    assert system_ns.is_user_defined is False


def test_b10_namespace_listing_includes_custom_user_ns(tmp_path):
    catalog_dir = tmp_path / "queries_catalog"
    _build_system_catalog(catalog_dir)
    _build_user_catalog(catalog_dir)

    namespaces = load_namespaces(catalog_dir)
    user_ns = next(ns for ns in namespaces if ns.directory == "my_queries")

    assert user_ns.is_user_defined is True
    assert user_ns.order == 1
    assert user_ns.name == "My Queries"
"""Unit tests for the fingerprint-keyed parsed-catalog cache.

These tests build synthetic catalogs in ``tmp_path`` via the same helper
approach as ``tests/test_query_catalog_merge.py`` so they never touch the real
``queries_catalog/`` tree.
"""

import os
from pathlib import Path

import pytest
import yaml

import app.query_catalog.loader as loader
from app.query_catalog import CatalogLoadError, clear_catalog_cache, load_catalog


pytestmark = pytest.mark.unit


def _write_yaml(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data), encoding="utf-8")


def _build_system_catalog(catalog_dir: Path) -> None:
    """Create a minimal system catalog with one namespace and two queries."""
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


@pytest.fixture
def tmp_catalog(tmp_path):
    """Build a synthetic catalog and hand back its directory."""
    catalog_dir = tmp_path / "queries_catalog"
    _build_system_catalog(catalog_dir)
    clear_catalog_cache()
    yield catalog_dir
    clear_catalog_cache()


def test_second_load_hits_the_cache(tmp_catalog, monkeypatch):
    """The second load of an unchanged catalog must not reparse any file."""
    calls: list[str] = []
    real = loader._load_query_file

    def counting(**kwargs):
        calls.append(str(kwargs["query_file"]))
        return real(**kwargs)

    monkeypatch.setattr(loader, "_load_query_file", counting)
    clear_catalog_cache()
    loader.load_catalog(tmp_catalog)
    first = len(calls)
    loader.load_catalog(tmp_catalog)
    assert first > 0
    assert len(calls) == first  # second call parsed nothing


def test_adding_a_file_invalidates_the_cache(tmp_catalog):
    """A newly written query file must appear on the next load."""
    assert all(q.id != "github/count_prs" for q in load_catalog(tmp_catalog))

    _write_yaml(
        tmp_catalog / "github" / "count_prs.yaml",
        {
            "name": "Count PRs",
            "description": "Added after first load.",
            "queries": {"tabular": "MATCH (n:PR) RETURN count(n)"},
        },
    )

    ids = {q.id for q in load_catalog(tmp_catalog)}
    assert "github/count_prs" in ids


def test_editing_a_file_invalidates_the_cache(tmp_catalog):
    """A rewritten query file must show its new content on the next load."""
    by_id = {q.id: q for q in load_catalog(tmp_catalog)}
    assert by_id["github/open_prs"].name == "Open PRs"

    _write_yaml(
        tmp_catalog / "github" / "open_prs.yaml",
        {
            "name": "Open Pull Requests",
            "description": "Renamed after first load.",
            "queries": {"tabular": "MATCH (n:PR) RETURN n LIMIT 10"},
        },
    )

    by_id = {q.id: q for q in load_catalog(tmp_catalog)}
    assert by_id["github/open_prs"].name == "Open Pull Requests"


def test_deleting_a_file_invalidates_the_cache(tmp_catalog):
    """A removed query file must disappear on the next load."""
    assert any(q.id == "github/open_prs" for q in load_catalog(tmp_catalog))

    (tmp_catalog / "github" / "open_prs.yaml").unlink()

    assert all(q.id != "github/open_prs" for q in load_catalog(tmp_catalog))


def test_cache_is_keyed_by_directory(tmp_path):
    """Two catalogs must not serve each other's cached entries."""
    first_dir = tmp_path / "catalog_a"
    second_dir = tmp_path / "catalog_b"
    _build_system_catalog(first_dir)
    _write_yaml(
        second_dir / "catalog.yaml",
        {"namespaces": [{"name": "GitHub", "directory": "github"}]},
    )
    _write_yaml(
        second_dir / "github" / "only_b.yaml",
        {
            "name": "Only B",
            "description": "Lives in catalog B.",
            "queries": {"tabular": "MATCH (n) RETURN n LIMIT 1"},
        },
    )
    clear_catalog_cache()

    first_ids = {q.id for q in load_catalog(first_dir)}
    second_ids = {q.id for q in load_catalog(second_dir)}

    assert "github/top_committers" in first_ids
    assert "github/only_b" not in first_ids
    assert second_ids == {"github/only_b"}


def test_validate_cypher_is_part_of_the_key(tmp_catalog):
    """A lenient load must not satisfy a later validating load."""
    _write_yaml(
        tmp_catalog / "github" / "writes.yaml",
        {
            "name": "Writes",
            "description": "Contains a write statement.",
            "queries": {"graph": "CREATE (n:Temp) RETURN n"},
        },
    )

    lenient = {q.id for q in load_catalog(tmp_catalog, validate_cypher=False)}
    assert "github/writes" in lenient

    with pytest.raises(CatalogLoadError):
        load_catalog(tmp_catalog, validate_cypher=True)


def test_returned_list_is_fresh(tmp_catalog):
    """Each call returns a new list; mutating it must not affect the cache."""
    first = load_catalog(tmp_catalog)
    second = load_catalog(tmp_catalog)
    assert first is not second

    original_len = len(second)
    first.pop()
    assert len(load_catalog(tmp_catalog)) == original_len


def test_mtime_preserving_write_is_not_detected(tmp_catalog):
    """Documented limitation: fingerprint invalidation assumes mtime/size change.

    This is **not** a bug to fix here: a writer that deliberately preserves both
    the mtime and the size (``cp -p``, ``rsync -a``, a restored backup) can be
    missed until the process restarts or ``clear_catalog_cache()`` is called.
    """
    path = tmp_catalog / "github" / "open_prs.yaml"
    assert {q.id: q for q in load_catalog(tmp_catalog)}["github/open_prs"].name == "Open PRs"

    before = path.stat()
    # Same-length name so the file size is unchanged.
    _write_yaml(
        path,
        {
            "name": "Open Prs",  # 8 chars, same as "Open PRs"
            "description": "System query.",
            "queries": {"tabular": "MATCH (n:PR) RETURN n LIMIT 10"},
        },
    )
    os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))

    # Cache still serves the old content because the fingerprint is unchanged.
    assert {q.id: q for q in load_catalog(tmp_catalog)}["github/open_prs"].name == "Open PRs"

    # A deterministic reset picks up the new content.
    clear_catalog_cache()
    assert {q.id: q for q in load_catalog(tmp_catalog)}["github/open_prs"].name == "Open Prs"

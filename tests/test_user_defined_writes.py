"""Unit tests for crash-safe user-defined catalog writes.

These tests exercise the write path in
``app.api.queries.v1.user_defined_service`` and the read-path error mapping in
``app.api.queries.v1.router``. Every write test is hermetic: the ``tmp_catalog``
fixture redirects the service at a throwaway catalog root so the real
``queries_catalog/`` tree is never touched.
"""

from pathlib import Path

import pytest
from fastapi import HTTPException

from app.api.queries.v1 import router
from app.api.queries.v1 import user_defined_service
from app.query_catalog import CatalogLoadError


pytestmark = [pytest.mark.unit, pytest.mark.asyncio]


def _write_payload(name: str = "Test Query") -> user_defined_service.CatalogQueryWrite:
    """Build a minimal valid write payload."""
    return user_defined_service.CatalogQueryWrite(
        name=name,
        description="Test description.",
        queries={"tabular": "MATCH (n) RETURN n LIMIT 1"},
        tags=["test"],
    )


@pytest.fixture
def tmp_catalog(tmp_path, monkeypatch):
    """Redirect the write service at a throwaway catalog root.

    ``save_query`` resolves the catalog root through ``get_default_catalog_dir``
    and ``_ensure_namespace_declared`` calls ``load_namespaces()`` with no
    argument (which would resolve the *real* catalog directory), so both names
    are patched to keep the whole test hermetic.
    """
    root = tmp_path / "queries_catalog"
    (root / "user_defined").mkdir(parents=True)
    monkeypatch.setattr(user_defined_service, "get_default_catalog_dir", lambda: root)
    monkeypatch.setattr(user_defined_service, "load_namespaces", lambda: [])
    return root


async def test_namespace_is_not_declared_when_mkdir_fails(tmp_catalog, monkeypatch):
    """The namespace directory is created before the registry mentions it."""
    real_mkdir = Path.mkdir

    def fake_mkdir(self, *args, **kwargs):
        if self.name == "new_ns":
            raise PermissionError("denied")
        return real_mkdir(self, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", fake_mkdir)

    with pytest.raises(PermissionError):
        user_defined_service.save_query("new_ns", "q", _write_payload())

    registry = tmp_catalog / "user_defined" / "catalog.yaml"
    assert not registry.exists() or "new_ns" not in registry.read_text(encoding="utf-8")


async def test_atomic_write_replaces_content(tmp_catalog):
    """A successful atomic write leaves only the target file, no temp sibling."""
    target = tmp_catalog / "user_defined" / "file.yaml"

    user_defined_service._atomic_write_text(target, "a: 1")

    assert target.read_text(encoding="utf-8") == "a: 1"
    assert list(target.parent.iterdir()) == [target]


async def test_atomic_write_keeps_original_when_replace_fails(tmp_catalog, monkeypatch):
    """A failed replace leaves the previous bytes intact and no temp file."""
    target = tmp_catalog / "user_defined" / "file.yaml"
    target.write_text("original", encoding="utf-8")

    def fake_replace(src, dst):
        raise OSError("replace failed")

    monkeypatch.setattr(user_defined_service.os, "replace", fake_replace)

    with pytest.raises(OSError):
        user_defined_service._atomic_write_text(target, "new")

    assert target.read_text(encoding="utf-8") == "original"
    assert [entry.name for entry in target.parent.iterdir() if entry.name.endswith(".tmp")] == []


async def test_save_restores_previous_file_when_reload_fails(tmp_catalog, monkeypatch):
    """An existing override is restored byte-for-byte when the reload fails."""
    namespace_dir = tmp_catalog / "user_defined" / "github"
    namespace_dir.mkdir(parents=True)
    target = namespace_dir / "keep.yaml"
    target.write_text("name: Original\n", encoding="utf-8")

    def fake_get_catalog_query(query_id, *args, **kwargs):
        raise CatalogLoadError("boom")

    monkeypatch.setattr(
        user_defined_service, "get_catalog_query", fake_get_catalog_query
    )

    with pytest.raises(CatalogLoadError):
        user_defined_service.save_query("github", "keep", _write_payload())

    assert target.read_text(encoding="utf-8") == "name: Original\n"


async def test_save_removes_new_file_when_reload_fails(tmp_catalog, monkeypatch):
    """A brand-new override file is removed when the reload fails."""
    def fake_get_catalog_query(query_id, *args, **kwargs):
        raise CatalogLoadError("boom")

    monkeypatch.setattr(
        user_defined_service, "get_catalog_query", fake_get_catalog_query
    )

    target = tmp_catalog / "user_defined" / "github" / "fresh.yaml"

    with pytest.raises(CatalogLoadError):
        user_defined_service.save_query("github", "fresh", _write_payload())

    assert not target.exists()


async def test_unreadable_catalog_is_reported_not_leaked(tmp_catalog, monkeypatch):
    """An unreadable catalog maps to a controlled 500 without leaking paths."""
    import app.api.queries.v1.query as query_module

    def fake_load_catalog(*args, **kwargs):
        raise CatalogLoadError("/abs/path leaked.yaml")

    monkeypatch.setattr(query_module, "load_catalog", fake_load_catalog)

    with pytest.raises(HTTPException) as exc_info:
        await router.list_catalog_queries(namespace=None, tag=None, q=None, view=None)

    assert exc_info.value.status_code == 500
    assert "/abs/path leaked" not in str(exc_info.value.detail)

"""Unit tests for the query catalog metadata API."""

from pathlib import Path

import pytest
import yaml
from fastapi import HTTPException

from app.api.queries.v1 import router
from app.api.queries.v1 import user_defined_service
from app.query_catalog import get_default_catalog_dir
from app.query_catalog.model import CatalogQueryWrite


pytestmark = [pytest.mark.unit, pytest.mark.asyncio]


def _write_payload(name: str = "Test Query") -> CatalogQueryWrite:
    return CatalogQueryWrite(
        name=name,
        description="Test description.",
        queries={"tabular": "MATCH (n) RETURN n LIMIT 1"},
        tags=["test"],
    )


def _remove_user_namespace(namespace: str) -> None:
    """Remove a custom user namespace entry and its empty dir.

    ``delete_query`` deliberately leaves the namespace entry in
    ``user_defined/catalog.yaml`` (an empty namespace is harmless at load
    time), so tests that create a brand-new custom namespace must clean it up
    themselves to avoid polluting the real catalog. If the namespaces list
    becomes empty, the whole ``catalog.yaml`` is removed to restore the exact
    pre-test state (``load_namespaces`` raises on an empty list).
    """
    root = get_default_catalog_dir()
    user_catalog_file = root / "user_defined" / "catalog.yaml"
    if user_catalog_file.exists():
        with user_catalog_file.open("r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle) or {}
        raw_namespaces = data.get("namespaces", [])
        data["namespaces"] = [
            ns for ns in raw_namespaces if ns.get("directory") != namespace
        ]
        if data["namespaces"]:
            user_catalog_file.write_text(
                yaml.dump(data, default_flow_style=False, sort_keys=False),
                encoding="utf-8",
            )
        else:
            user_catalog_file.unlink()

    namespace_dir = root / "user_defined" / namespace
    if namespace_dir.is_dir():
        namespace_dir.rmdir()


async def test_list_catalog_queries():
    response = await router.list_catalog_queries(namespace=None, tag=None, q=None, view=None)
    data = response.model_dump()

    assert data["count"] == 140
    assert len(data["items"]) == 140
    assert data["items"][0]["id"] == "hall_of_fame/top_n_blockers"
    assert set(data["items"][0]["queries"]) == {"tabular", "graph"}
    assert data["items"][0]["summary"] == "Top 10 people whose assigned issues are blocking the most other work."
    assert data["items"][0]["default_view"] == "tabular"
    assert data["items"][0]["owner"] == "hall-of-fame-analytics"
    assert data["items"][0]["status"] in {"active", "draft", "deprecated"}


async def test_filter_catalog_by_namespace():
    response = await router.list_catalog_queries(namespace="github", tag=None, q=None, view=None)
    data = response.model_dump()

    assert data["count"] == 28
    assert all(item["namespace"]["directory"] == "github" for item in data["items"])


async def test_filter_catalog_by_namespace_display_name():
    response = await router.list_catalog_queries(namespace="GitHub", tag=None, q=None, view=None)
    data = response.model_dump()

    assert data["count"] == 28


async def test_filter_catalog_by_view():
    response = await router.list_catalog_queries(namespace=None, tag=None, q=None, view="graph")
    data = response.model_dump()

    assert data["count"] == 139
    assert all("graph" in item["available_views"] for item in data["items"])


async def test_search_catalog_queries():
    response = await router.list_catalog_queries(
        namespace=None,
        tag=None,
        q="direct code reviews",
        view=None,
    )
    data = response.model_dump()

    assert data["count"] == 1
    assert data["items"][0]["id"] == "person_to_person/direct_code_reviews"
    assert data["items"][0]["summary"] == "Compare two people by direct code review activity."
    assert data["items"][0]["owner"] == "graph-team"
    assert data["items"][0]["status"] in {"active", "draft", "deprecated"}


async def test_search_catalog_queries_by_owner_and_status_metadata():
    owner_response = await router.list_catalog_queries(
        namespace=None,
        tag=None,
        q="graph-team",
        view=None,
    )
    owner_data = owner_response.model_dump()
    assert owner_data["count"] == 38
    assert all(item["owner"] == "graph-team" for item in owner_data["items"])

    draft_response = await router.list_catalog_queries(
        namespace=None,
        tag=None,
        q="graph-team draft",
        view=None,
    )
    draft_data = draft_response.model_dump()
    assert all(item["owner"] == "graph-team" and item["status"] == "draft" for item in draft_data["items"])

    active_response = await router.list_catalog_queries(
        namespace=None,
        tag=None,
        q="graph-team active",
        view=None,
    )
    active_data = active_response.model_dump()
    assert all(item["owner"] == "graph-team" and item["status"] == "active" for item in active_data["items"])

    assert draft_data["count"] + active_data["count"] == owner_data["count"]


async def test_get_catalog_query_detail():
    response = await router.get_catalog_query("hall_of_fame", "top_n_committers")
    data = response.model_dump()

    assert data["id"] == "hall_of_fame/top_n_committers"
    assert data["name"] == "Top N Code Committer"
    assert data["namespace"]["name"] == "Hall of Fame"
    assert "LIMIT 10" in data["queries"]["tabular"]
    assert data["summary"] == "Top 10 contributors by commit count."
    assert data["default_view"] == "tabular"
    assert data["owner"] == "hall-of-fame-analytics"
    assert data["status"] in {"active", "draft", "deprecated"}


async def test_get_catalog_query_detail_includes_rich_metadata():
    response = await router.get_catalog_query("person_to_person", "direct_code_reviews")
    data = response.model_dump()

    assert data["default_view"] == "tabular"
    assert data["summary"] == "Compare two people by direct code review activity."
    assert data["owner"] == "graph-team"
    assert data["status"] in {"active", "draft", "deprecated"}
    assert data["parameters"][0]["label"] == "First person"
    assert data["parameters"][0]["type"] == "person_id"
    assert data["parameters"][0]["placeholder"]


async def test_get_catalog_query_missing_returns_404():
    with pytest.raises(HTTPException) as exc_info:
        await router.get_catalog_query("github", "does_not_exist")

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "Catalog query not found"


async def test_list_catalog_namespaces():
    response = await router.list_catalog_namespaces()
    data = response.model_dump()

    assert data["count"] == 9
    assert [item["directory"] for item in data["items"]] == [
        "hall_of_fame",
        "schema",
        "cross_domain",
        "confluence",
        "github",
        "jira",
        "people_and_identity",
        "person",
        "person_to_person",
    ]


# ── User-defined overrides (PUT/DELETE) ───────────────────────────────
# These tests hit the real queries_catalog/ tree, so they must clean up after
# themselves (delete any files they create) to keep `count == 140` valid.


async def test_c1_put_creates_user_file():
    saved = await router.put_catalog_query("github", "test_c1", _write_payload())
    try:
        assert saved.id == "github/test_c1"
        assert "user_defined/" in saved.source_path
    finally:
        await router.delete_catalog_query("github", "test_c1")


async def test_c2_put_overwrites():
    await router.put_catalog_query("github", "test_c2", _write_payload(name="First"))
    try:
        saved = await router.put_catalog_query(
            "github", "test_c2", _write_payload(name="Second")
        )
        assert saved.name == "Second"
    finally:
        await router.delete_catalog_query("github", "test_c2")


async def test_c3_put_new_query():
    await router.put_catalog_query("github", "test_c3", _write_payload())
    try:
        response = await router.list_catalog_queries(
            namespace="github", tag=None, q=None, view=None
        )
        data = response.model_dump()
        assert any(item["id"] == "github/test_c3" for item in data["items"])
    finally:
        await router.delete_catalog_query("github", "test_c3")


async def test_c4_put_with_write_cypher_returns_422():
    payload = CatalogQueryWrite(
        name="Write Query",
        description="Should be rejected.",
        queries={"tabular": "MATCH (n) DELETE n"},
    )
    with pytest.raises(HTTPException) as exc_info:
        await router.put_catalog_query("github", "test_c4", payload)
    assert exc_info.value.status_code == 422


async def test_c5_put_missing_required_fields_returns_422():
    # The write model rejects empty required fields at construction time, which
    # FastAPI surfaces as a 422 when the request body is deserialized.
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        CatalogQueryWrite(name="", description="", queries={})


async def test_c6_delete_removes_file_then_get_shows_system_version():
    await router.put_catalog_query("github", "test_c6", _write_payload(name="Override"))
    await router.delete_catalog_query("github", "test_c6")
    # After delete, the query no longer exists (no system version for this id).
    with pytest.raises(HTTPException) as exc_info:
        await router.get_catalog_query("github", "test_c6")
    assert exc_info.value.status_code == 404


async def test_c7_delete_non_existent_returns_204():
    response = await router.delete_catalog_query("github", "test_c7_does_not_exist")
    assert response.status_code == 204


async def test_c8_get_merged_catalog_after_override():
    await router.put_catalog_query("github", "test_c8", _write_payload(name="Merged"))
    try:
        response = await router.get_catalog_query("github", "test_c8")
        assert response is not None
        assert response.name == "Merged"
        assert "user_defined/" in response.source_path
    finally:
        await router.delete_catalog_query("github", "test_c8")


async def test_c9_get_namespaces_includes_custom_user_ns():
    await router.put_catalog_query("test_c9_ns", "test_c9", _write_payload())
    try:
        response = await router.list_catalog_namespaces()
        data = response.model_dump()
        assert any(item["directory"] == "test_c9_ns" for item in data["items"])
    finally:
        await router.delete_catalog_query("test_c9_ns", "test_c9")
        _remove_user_namespace("test_c9_ns")

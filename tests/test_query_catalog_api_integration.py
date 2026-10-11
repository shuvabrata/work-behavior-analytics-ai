"""HTTP integration tests for the YAML-backed query catalog API."""

from __future__ import annotations

from typing import Any

import httpx
import pytest
import yaml

from app.main import app
from app.query_catalog import get_default_catalog_dir


pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

_API_BASE = "http://test"


def _client() -> httpx.AsyncClient:
    """Return an in-process HTTP client bound to the ASGI app."""
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url=_API_BASE,
    )


async def _get(path: str, *, params: dict[str, str] | None = None) -> httpx.Response:
    async with _client() as client:
        return await client.get(path, params=params)


async def _put(path: str, *, payload: dict[str, Any]) -> httpx.Response:
    async with _client() as client:
        return await client.put(path, json=payload)


async def _delete(path: str) -> httpx.Response:
    async with _client() as client:
        return await client.delete(path)


def _write_payload(name: str = "Integration Test Query") -> dict[str, Any]:
    """Build a minimal valid PUT body."""
    return {
        "name": name,
        "description": "Integration test description.",
        "queries": {"tabular": "MATCH (n) RETURN n LIMIT 1"},
        "tags": ["integration-test"],
    }


def _cleanup_user_namespace(namespace: str) -> None:
    """Remove a user namespace's registry entry and its now-empty directory.

    ``delete_query`` deliberately leaves the namespace entry in
    ``user_defined/catalog.yaml`` (an empty namespace is harmless at load time),
    so tests that create an override — especially in a brand-new custom
    namespace — must clean up after themselves or they pollute the real catalog.
    If the namespaces list empties, the whole ``catalog.yaml`` is removed,
    because ``load_namespaces`` rejects an empty list.
    """
    root = get_default_catalog_dir()
    user_catalog_file = root / "user_defined" / "catalog.yaml"
    if user_catalog_file.exists():
        with user_catalog_file.open("r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle) or {}
        data["namespaces"] = [
            entry
            for entry in data.get("namespaces", [])
            if entry.get("directory") != namespace
        ]
        if data["namespaces"]:
            user_catalog_file.write_text(
                yaml.dump(data, default_flow_style=False, sort_keys=False),
                encoding="utf-8",
            )
        else:
            user_catalog_file.unlink()

    namespace_dir = root / "user_defined" / namespace
    if namespace_dir.is_dir() and not any(namespace_dir.iterdir()):
        namespace_dir.rmdir()


async def test_catalog_list_endpoint_returns_normalized_catalog():
    response = await _get("/api/v1/queries/catalog")

    assert response.status_code == 200
    data = response.json()

    assert data["count"] == 140
    assert len(data["items"]) == 140

    first_item = data["items"][0]
    assert first_item["id"] == "hall_of_fame/top_n_blockers"
    assert first_item["slug"] == "top_n_blockers"
    assert first_item["namespace"]["directory"] == "hall_of_fame"
    assert set(first_item["queries"]) == {"tabular", "graph"}
    assert first_item["available_views"] == ["tabular", "graph"]
    assert first_item["summary"] == "Top 10 people whose assigned issues are blocking the most other work."
    assert first_item["default_view"] == "tabular"
    assert first_item["owner"] == "hall-of-fame-analytics"
    assert first_item["status"] in {"active", "draft", "deprecated"}
    assert all(item["summary"] for item in data["items"])
    assert all(item["default_view"] in {"tabular", "graph"} for item in data["items"])
    assert all(item["owner"] for item in data["items"])
    assert all(item["status"] in {"active", "draft", "deprecated"} for item in data["items"])


async def test_catalog_namespaces_endpoint_returns_display_order():
    response = await _get("/api/v1/queries/catalog/namespaces")

    assert response.status_code == 200
    data = response.json()

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
    assert [item["order"] for item in data["items"]] == list(range(9))


@pytest.mark.parametrize("namespace", ["github", "GitHub"])
async def test_catalog_list_endpoint_filters_by_namespace_directory_or_display_name(namespace: str):
    response = await _get("/api/v1/queries/catalog", params={"namespace": namespace})

    assert response.status_code == 200
    data = response.json()

    assert data["count"] == 28
    assert all(item["namespace"]["directory"] == "github" for item in data["items"])
    response = await _get(
        "/api/v1/queries/catalog",
        params={"q": "direct code reviews"},
    )

    assert response.status_code == 200
    data = response.json()

    assert data["count"] == 1
    item = data["items"][0]
    assert item["id"] == "person_to_person/direct_code_reviews"
    assert item["summary"] == "Compare two people by direct code review activity."
    assert item["default_view"] == "tabular"
    assert item["owner"] == "graph-team"
    assert item["status"] in {"active", "draft", "deprecated"}
    params = item["parameters"]
    assert len(params) == 2
    for param in params:
        assert param["required"] is True
        assert param["type"] == "person_id"
        assert param["placeholder"]
        assert param["description"]
    assert params[0]["name"] == "person1_id"
    assert params[0]["env_var"] == "PERSON1_ID"
    assert params[0]["label"] == "First person"
    assert params[1]["name"] == "person2_id"
    assert params[1]["env_var"] == "PERSON2_ID"
    assert params[1]["label"] == "Second person"


async def test_catalog_list_endpoint_searches_owner_and_status_metadata():
    owner_response = await _get("/api/v1/queries/catalog", params={"q": "graph-team"})

    assert owner_response.status_code == 200
    owner_data = owner_response.json()

    assert owner_data["count"] == 38
    assert all(item["owner"] == "graph-team" for item in owner_data["items"])

    draft_response = await _get("/api/v1/queries/catalog", params={"q": "graph-team draft"})
    assert draft_response.status_code == 200
    draft_data = draft_response.json()
    assert all(item["owner"] == "graph-team" and item["status"] == "draft" for item in draft_data["items"])

    active_response = await _get("/api/v1/queries/catalog", params={"q": "graph-team active"})
    assert active_response.status_code == 200
    active_data = active_response.json()
    assert all(item["owner"] == "graph-team" and item["status"] == "active" for item in active_data["items"])

    assert draft_data["count"] + active_data["count"] == owner_data["count"]


async def test_catalog_list_endpoint_searches_namespace_owner_and_status_metadata():
    response = await _get("/api/v1/queries/catalog", params={"q": "github-analytics"})

    assert response.status_code == 200
    data = response.json()

    assert data["count"] == 28
    assert all(item["namespace"]["directory"] == "github" for item in data["items"])
    assert all(item["owner"] == "github-analytics" for item in data["items"])


async def test_catalog_list_endpoint_filters_by_view():
    response = await _get("/api/v1/queries/catalog", params={"view": "graph"})

    assert response.status_code == 200
    data = response.json()

    assert data["count"] == 139
    assert all("graph" in item["available_views"] for item in data["items"])


async def test_catalog_list_endpoint_rejects_invalid_view_filter():
    response = await _get("/api/v1/queries/catalog", params={"view": "invalid"})

    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["query", "view"]


async def test_catalog_detail_endpoint_returns_full_query_entry():
    response = await _get("/api/v1/queries/catalog/person_to_person/direct_code_reviews")

    assert response.status_code == 200
    data = response.json()

    assert data["id"] == "person_to_person/direct_code_reviews"
    assert data["slug"] == "direct_code_reviews"
    assert data["name"] == "Direct Code Reviews"
    assert data["namespace"]["name"] == "Person-to-Person"
    assert data["available_views"] == ["tabular", "graph"]
    assert data["default_view"] == "tabular"
    assert data["summary"] == "Compare two people by direct code review activity."
    assert data["owner"] == "graph-team"
    assert data["status"] in {"active", "draft", "deprecated"}
    assert data["parameters"][0]["label"] == "First person"
    assert "LIMIT 10" in data["queries"]["tabular"]
    assert "LIMIT 100" in data["queries"]["graph"]


async def test_catalog_detail_endpoint_returns_404_for_missing_query():
    response = await _get("/api/v1/queries/catalog/github/does_not_exist")

    assert response.status_code == 404
    assert response.json() == {"detail": "Catalog query not found"}


# ── User-defined overrides (PUT/DELETE) over HTTP ─────────────────────
# These tests hit the real queries_catalog/ tree, so every test that writes must
# clean up after itself to keep the exact-count assertions above (140 / 28 / 9)
# valid. Cleanup runs in a `finally` so a mid-test failure cannot leave residue.


async def test_c1_put_creates_user_query():
    path = "/api/v1/queries/catalog/github/test_c1"
    try:
        response = await _put(path, payload=_write_payload())

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == "github/test_c1"
        assert data["slug"] == "test_c1"
        assert data["namespace"]["directory"] == "github"
        assert data["origin"] == "custom"
        assert "user_defined/" in data["source_path"]
    finally:
        await _delete(path)
        _cleanup_user_namespace("github")


async def test_c2_put_overwrites_existing_override():
    path = "/api/v1/queries/catalog/github/test_c2"
    try:
        first = await _put(path, payload=_write_payload(name="First Name"))
        assert first.status_code == 200
        assert first.json()["name"] == "First Name"

        second = await _put(path, payload=_write_payload(name="Second Name"))
        assert second.status_code == 200
        assert second.json()["name"] == "Second Name"
        assert second.json()["origin"] == "custom"
    finally:
        await _delete(path)
        _cleanup_user_namespace("github")


async def test_c3_put_new_query_appears_in_catalog_and_detail():
    path = "/api/v1/queries/catalog/github/test_c3"
    try:
        assert (await _put(path, payload=_write_payload())).status_code == 200

        listing = await _get("/api/v1/queries/catalog", params={"namespace": "github"})
        assert listing.status_code == 200
        assert any(item["id"] == "github/test_c3" for item in listing.json()["items"])

        detail = await _get(path)
        assert detail.status_code == 200
        assert detail.json()["id"] == "github/test_c3"
    finally:
        await _delete(path)
        _cleanup_user_namespace("github")


async def test_c4_put_with_write_cypher_returns_422():
    path = "/api/v1/queries/catalog/github/test_c4"
    payload = _write_payload()
    payload["queries"] = {"tabular": "MATCH (n) DELETE n"}
    try:
        response = await _put(path, payload=payload)

        assert response.status_code == 422
        detail = response.json()["detail"]
        assert isinstance(detail, str)
        assert "write" in detail.lower()
        # Validation runs before any write, so nothing was persisted.
        assert (await _get(path)).status_code == 404
    finally:
        await _delete(path)
        _cleanup_user_namespace("github")


async def test_c5_put_missing_required_fields_returns_422():
    response = await _put(
        "/api/v1/queries/catalog/github/test_c5",
        payload={"name": "", "description": "", "queries": {}},
    )

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert isinstance(detail, list) and detail


async def test_c6_delete_removes_user_query():
    path = "/api/v1/queries/catalog/github/test_c6"
    assert (await _put(path, payload=_write_payload())).status_code == 200
    assert (await _get(path)).status_code == 200

    response = await _delete(path)
    assert response.status_code == 200
    assert response.json() == {"message": "Query override deleted"}

    assert (await _get(path)).status_code == 404
    _cleanup_user_namespace("github")


async def test_c7_delete_non_existent_returns_204():
    response = await _delete("/api/v1/queries/catalog/github/test_c7_does_not_exist")

    assert response.status_code == 204
    assert response.content == b""


async def test_c8_put_overrides_system_query_then_delete_restores_it():
    path = "/api/v1/queries/catalog/hall_of_fame/top_n_committers"

    original = await _get(path)
    assert original.status_code == 200
    original_name = original.json()["name"]
    assert original.json()["origin"] == "builtin"

    try:
        override = await _put(path, payload=_write_payload(name="Overridden Top N"))
        assert override.status_code == 200
        body = override.json()
        assert body["origin"] == "override"
        assert body["name"] == "Overridden Top N"
        assert "user_defined/" in body["source_path"]

        merged = await _get(path)
        assert merged.status_code == 200
        assert merged.json()["name"] == "Overridden Top N"
        assert merged.json()["origin"] == "override"
    finally:
        await _delete(path)
        _cleanup_user_namespace("hall_of_fame")

    restored = await _get(path)
    assert restored.status_code == 200
    assert restored.json()["name"] == original_name
    assert restored.json()["origin"] == "builtin"


async def test_c9_namespaces_include_custom_user_namespace():
    baseline = await _get("/api/v1/queries/catalog/namespaces")
    assert baseline.status_code == 200
    base_count = baseline.json()["count"]

    path = "/api/v1/queries/catalog/test_c9_ns/test_c9"
    try:
        assert (await _put(path, payload=_write_payload())).status_code == 200

        response = await _get("/api/v1/queries/catalog/namespaces")
        assert response.status_code == 200
        data = response.json()
        assert data["count"] == base_count + 1

        entry = next(
            item for item in data["items"] if item["directory"] == "test_c9_ns"
        )
        assert entry["name"] == "Test C9 Ns"
        assert entry["is_user_defined"] is True
        assert entry["order"] == base_count
    finally:
        await _delete(path)
        _cleanup_user_namespace("test_c9_ns")


async def test_put_accepts_mixed_case_key():
    """The id regex deliberately allows upper case in slug segments."""
    path = "/api/v1/queries/catalog/github/Mixed_Case_Key"
    try:
        response = await _put(path, payload=_write_payload())

        assert response.status_code == 200
        assert response.json()["id"] == "github/Mixed_Case_Key"
    finally:
        await _delete(path)
        _cleanup_user_namespace("github")


async def test_put_rejects_path_unsafe_key():
    path = "/api/v1/queries/catalog/github/bad.key"

    response = await _put(path, payload=_write_payload())

    assert response.status_code == 422
    assert (await _get(path)).status_code == 404

"""Unit tests for the query catalog metadata API."""

import pytest
from fastapi import HTTPException

from app.api.queries.v1 import router


pytestmark = [pytest.mark.unit, pytest.mark.asyncio]


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

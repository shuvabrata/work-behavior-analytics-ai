"""Live-Neo4j smoke tests for the Person query catalog.

Runs every queries_catalog/person/*.yaml query against a live Neo4j instance
and asserts the key display columns are non-null. Catches property-name
mismatches (e.g. .title vs .summary) that the catalog loader's read-only check
does not.

Run with: pytest tests/test_person_catalog_queries.py -m neo4j -v
"""

import pytest

from app.api.graph.v1.query import execute_cypher_query
from app.query_catalog import load_catalog
from app.settings import settings


pytestmark = [pytest.mark.integration, pytest.mark.neo4j]


@pytest.mark.skipif(
    not settings.NEO4J_ENABLED,
    reason="Neo4j is not enabled (NEO4J_ENABLED=false)"
)
class TestPersonCatalogQueries:
    """Smoke tests for the Person catalog queries against live Neo4j."""

    @pytest.fixture(scope="class")
    def person_id(self):
        rows = execute_cypher_query(
            "MATCH (p:Person) RETURN p.id AS id LIMIT 1", timeout=10
        )
        if not rows:
            pytest.skip("No Person nodes in the database")
        return rows[0]["id"]

    def test_all_person_queries_execute(self, person_id):
        queries = [q for q in load_catalog() if q.id.startswith("person/")]
        assert queries, "expected at least one person catalog query"
        for query in queries:
            for view, cypher in query.queries.items():
                results = execute_cypher_query(
                    cypher, timeout=30, parameters={"person_id": person_id}
                )
                assert isinstance(results, list)

    @pytest.mark.parametrize(
        "catalog_id,column",
        [
            ("person/assigned_epics", "title"),
            ("person/assigned_initiatives", "title"),
            ("person/blocking_and_blocked_issues", "title"),
            ("person/open_assigned_issues", "title"),
            ("person/reported_issues", "title"),
            ("person/work_item_tree", "issue_title"),
            ("person/modified_pages", "last_modified"),
            ("person/sprint_membership", "sprint_state"),
            ("person/repository_collaborations", "full_name"),
            ("person/commented_on", "title"),
            ("person/mentioned_in", "title"),
        ],
    )
    def test_display_column_not_null(self, person_id, catalog_id, column):
        query = next(q for q in load_catalog() if q.id == catalog_id)
        cypher = query.queries.get("tabular") or query.queries.get("graph")
        results = execute_cypher_query(
            cypher, timeout=30, parameters={"person_id": person_id}
        )
        for row in results:
            assert row.get(column) is not None, (
                f"{catalog_id} returned null for '{column}'"
            )
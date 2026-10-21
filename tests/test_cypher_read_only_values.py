"""Acceptance tests: a read-only query is accepted when a write keyword appears
only inside a *value* (string, backtick identifier, comment), not as syntax.

Context
-------
``validate_read_only_query`` (``src/app/api/graph/v1/query.py``) uppercases the
whole query and regex-scans it for ``WRITE_KEYWORDS`` with ``\\b`` boundaries.
Because the scan is text-wide rather than syntax-aware, the word ``CREATE``
inside an ordinary id such as ``'org/create-react-app'`` matches exactly like a
real ``CREATE`` clause, and the query is rejected with HTTP 400.

Every query in :data:`ACCEPTED_QUERIES_WITH_KEYWORD_VALUES` is genuine read-only
Cypher. All of them **fail** against the current implementation — that is the
point of this file; it is the executable statement of the defect. The suite is
expected to go green once the read-only check is made value-aware.

Baseline: 47 collected, 25 pass / 22 fail. The two
``keyword_in_empty_adjacent_literal_*`` cases in
:data:`ACCEPTED_PLAIN_READ_ONLY_QUERIES` also fail against the current
implementation — the group name reflects that a lexer-driven check accepts them
structurally, not that they pass today.

The guard cases in :class:`TestStillRejectsWrites` all pass today and must keep
passing: the fix must not weaken write detection to buy precision.

Run:

    pytest -m unit tests/test_cypher_read_only_values.py -q
"""

import pytest

from app.api.graph.v1.query import validate_read_only_query

pytestmark = pytest.mark.unit


#: (case id, read-only query whose write keyword occurs only inside a value)
#: Each query is valid Cypher and performs no write. All currently REJECTED.
ACCEPTED_QUERIES_WITH_KEYWORD_VALUES: list[tuple[str, str]] = [
    (
        "repository_id_hyphenated_keyword",
        "MATCH (a:Repository {id: 'org/create-react-app'}) "
        "OPTIONAL MATCH (a)-[r]-(b) RETURN a, r, b LIMIT 50",
    ),
    (
        "repository_id_slash_keyword",
        "MATCH (a:Repository {id: 'github::Repository::acme/merge-queue'}) RETURN a",
    ),
    (
        "repository_id_delete_keyword",
        "MATCH (a:Repository {id: 'github::Repository::acme/delete-old-files'}) RETURN a",
    ),
    (
        "repository_id_drop_keyword",
        "MATCH (a:Repository {id: 'github::Repository::acme/drop-table'}) RETURN a",
    ),
    (
        "where_string_literal",
        "MATCH (n:Person) WHERE n.name = 'SET' RETURN n",
    ),
    (
        "where_double_quoted_literal",
        'MATCH (n:Person) WHERE n.name = "DELETE" RETURN n',
    ),
    (
        "map_literal_value",
        "RETURN {kind: 'DROP'} AS m",
    ),
    (
        "list_literal_values",
        "MATCH (n:Person) WHERE n.k IN ['CREATE', 'MERGE'] RETURN n",
    ),
    (
        "call_yield_argument",
        "CALL db.labels() YIELD label WHERE label = 'CREATE' RETURN label",
    ),
    (
        "return_expression_literal",
        "MATCH (n) RETURN n.name AS name, 'CREATE' AS tag",
    ),
    (
        "backtick_identifier_label",
        "MATCH (n:`create-table`) RETURN n",
    ),
    (
        "backtick_identifier_alias",
        "MATCH (n) RETURN n.x AS `remove`",
    ),
    (
        "relationship_property_value",
        "MATCH (a)-[r {note: 'DETACH'}]->(b) RETURN r",
    ),
    (
        "with_list_literal",
        "WITH ['FOREACH'] AS ks UNWIND ks AS k RETURN k",
    ),
    (
        "line_comment_before_return",
        "MATCH (n) // CREATE not really\nRETURN n",
    ),
    (
        "block_comment_inline",
        "MATCH (n) /* DELETE */ RETURN n",
    ),
    (
        "block_comment_leading",
        "/* CREATE */ MATCH (n) RETURN n",
    ),
    (
        "line_comment_leading",
        "// CREATE\nMATCH (n) RETURN n",
    ),
    (
        "escaped_quote_then_keyword",
        r"MATCH (n) WHERE n.x = 'a\'CREATE' RETURN n",
    ),
    (
        "literal_is_whole_token",
        "MATCH (n) WHERE n.x = 'CREATE' RETURN n",
    ),
]

#: Read-only queries that already pass today and must keep passing. These pin
#: the *other* direction of the boundary: the check must not become so lenient
#: that ordinary read queries are accepted for the wrong reason.
ACCEPTED_PLAIN_READ_QUERIES: list[tuple[str, str]] = [
    ("plain_match", "MATCH (n) RETURN n"),
    ("optional_match", "OPTIONAL MATCH (n) RETURN n"),
    ("with_then_return", "WITH 1 AS x RETURN x"),
    ("unwind", "UNWIND [1,2,3] AS x RETURN x"),
    ("call_labels", "CALL db.labels() YIELD label RETURN label"),
    (
        "keyword_prefixed_value_not_a_token",
        "MATCH (a:Repository {id: 'org/setup-scripts'}) RETURN a",
    ),
    # A write keyword inside an empty-adjacent literal is still a STRING token,
    # so a lexer-driven check accepts it. These two cases were originally
    # asserted False (as a guard against the abandoned string-neutralisation
    # approach, which would have collapsed ``'' OR '' = 'CREATE'`` into
    # `` OR = `` and promoted the literal body into live query text). That
    # implementation was not chosen: the checker lexes, and never inspects
    # literal contents. Both queries are genuinely read-only.
    (
        "keyword_in_empty_adjacent_literal_or",
        "MATCH (n:Person) WHERE n.name = '' OR '' = 'CREATE' RETURN n",
    ),
    (
        "keyword_in_empty_adjacent_literal_and",
        "MATCH (n:Person) WHERE n.name = '' AND '' = 'SET' RETURN n",
    ),
]


class TestAcceptsReadOnlyQueriesWithKeywordsInValues:
    """A write keyword inside a value must not disqualify a read-only query."""

    @pytest.mark.parametrize(
        "case_id,query",
        ACCEPTED_QUERIES_WITH_KEYWORD_VALUES,
        ids=[case for case, _ in ACCEPTED_QUERIES_WITH_KEYWORD_VALUES],
    )
    def test_accepts_read_only_query(self, case_id: str, query: str) -> None:
        assert validate_read_only_query(query) is True, (
            f"{case_id}: read-only query rejected because a write keyword "
            f"appears inside a value: {query!r}"
        )


class TestStillAcceptsPlainReadOnlyQueries:
    """Regression guard: ordinary read-only queries keep working."""

    @pytest.mark.parametrize(
        "case_id,query",
        ACCEPTED_PLAIN_READ_QUERIES,
        ids=[case for case, _ in ACCEPTED_PLAIN_READ_QUERIES],
    )
    def test_accepts_plain_read_only_query(self, case_id: str, query: str) -> None:
        assert validate_read_only_query(query) is True


class TestStillRejectsWrites:
    """The security control must not be weakened to buy precision."""

    @pytest.mark.parametrize(
        "case_id,query",
        [
            ("create_clause", "CREATE (n:Test) RETURN n"),
            ("create_after_match", "MATCH (n) CREATE (m:Test) RETURN m"),
            ("set_clause", "MATCH (n) SET n.x = 1 RETURN n"),
            ("delete_clause", "MATCH (n) DELETE n"),
            ("detach_delete", "MATCH (n) DETACH DELETE n"),
            ("merge_clause", "MERGE (n:Test) RETURN n"),
            ("remove_clause", "MATCH (n) REMOVE n.x"),
            ("foreach_clause", "MATCH (n) FOREACH (x IN [1] | SET n.x = x)"),
            ("drop_index", "DROP INDEX idx"),
            ("drop_constraint", "DROP CONSTRAINT c"),
        ],
    )
    def test_rejects_write_query(self, case_id: str, query: str) -> None:
        assert validate_read_only_query(query) is False, (
            f"{case_id}: write query was accepted: {query!r}"
        )

    @pytest.mark.parametrize(
        "case_id,query",
        [
            (
                "apoc_cypher_doit",
                "CALL apoc.cypher.doIt('CREATE (n)')",
            ),
            (
                "apoc_cypher_run",
                "CALL apoc.cypher.run('CREATE (n:Test)', {})",
            ),
            (
                "apoc_periodic_iterate",
                "CALL apoc.periodic.iterate('MATCH (n) RETURN n', 'DELETE n', {})",
            ),
            (
                "apoc_doit_double_quoted",
                'CALL apoc.cypher.doIt("CREATE (n)")',
            ),
        ],
    )
    def test_rejects_apoc_write_procedures(self, case_id: str, query: str) -> None:
        """APOC writes hide inside string literals, so they must stay caught.

        This is why the APOC scan must remain a raw-text substring check even
        once the keyword scan becomes value-aware.
        """
        assert validate_read_only_query(query) is False, (
            f"{case_id}: APOC write procedure was accepted: {query!r}"
        )

    @pytest.mark.parametrize(
        "case_id,query",
        [
            ("empty", ""),
            ("whitespace_only", "   "),
            ("newlines_only", "\n\t  \n"),
        ],
    )
    def test_rejects_empty_query(self, case_id: str, query: str) -> None:
        assert validate_read_only_query(query) is False


class TestRejectsNonReadStartingQuery:
    """The query must still begin with a read operation."""

    @pytest.mark.parametrize(
        "case_id,query",
        [
            ("bare_return", "RETURN 1"),
        ],
    )
    def test_accepts_return_start(self, case_id: str, query: str) -> None:
        assert validate_read_only_query(query) is True

    @pytest.mark.parametrize(
        "case_id,query",
        [
            ("unknown_clause", "FOOBAR (n) RETURN n"),
        ],
    )
    def test_rejects_unknown_start(self, case_id: str, query: str) -> None:
        assert validate_read_only_query(query) is False

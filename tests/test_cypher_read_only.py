"""Unit tests for the value-aware read-only checker.

``app.api.graph.v1.cypher_read_only.is_read_only_cypher`` decides read-only
status by lexing the query and rejecting it only when a token *is* a write
keyword. Values (string literals, backtick identifiers) and comments never
produce keyword tokens, which is what makes ordinary ids containing words such
as ``create`` or ``drop`` acceptable. See
``plans/047-cypher-read-only-value-aware-check.md``.

Run:

    pytest -m unit tests/test_cypher_read_only.py -q
"""

import pytest

from app.api.graph.v1.cypher_read_only import is_read_only_cypher

pytestmark = pytest.mark.unit


WRITE_TOKEN_KEYWORD_QUERIES: list[tuple[str, str]] = [
    ("create", "CREATE (n:Test) RETURN n"),
    ("merge", "MERGE (n:Test) RETURN n"),
    ("set", "MATCH (n) SET n.x = 1 RETURN n"),
    ("delete", "MATCH (n) DELETE n"),
    ("detach_delete", "MATCH (n) DETACH DELETE n"),
    ("remove", "MATCH (n) REMOVE n.x"),
    ("foreach", "MATCH (n) FOREACH (x IN [1] | SET n.x = x)"),
]


class TestRejectsWriteTokenKeywords:
    """Each write keyword typed as a real clause is a write token."""

    @pytest.mark.parametrize(
        "case_id,query",
        WRITE_TOKEN_KEYWORD_QUERIES,
        ids=[case for case, _ in WRITE_TOKEN_KEYWORD_QUERIES],
    )
    def test_rejects_write_clause(self, case_id: str, query: str) -> None:
        assert is_read_only_cypher(query) is False, f"{case_id}: write clause accepted: {query!r}"


ACCEPTED_VALUE_SHAPE_QUERIES: list[tuple[str, str]] = [
    ("single_quoted", "MATCH (n) WHERE n.x = 'CREATE' RETURN n"),
    ("double_quoted", 'MATCH (n) WHERE n.x = "DELETE" RETURN n'),
    ("backtick_identifier", "MATCH (n:`create-table`) RETURN n"),
    ("line_comment", "MATCH (n) // CREATE not really\nRETURN n"),
    ("block_comment", "MATCH (n) /* DELETE */ RETURN n"),
    ("escaped_quote", r"MATCH (n) WHERE n.x = 'a\'CREATE' RETURN n"),
    ("map_literal", "RETURN {kind: 'DROP'} AS m"),
    ("list_literal", "MATCH (n) WHERE n.k IN ['CREATE', 'MERGE'] RETURN n"),
    ("call_yield_where", "CALL db.labels() YIELD label WHERE label = 'CREATE' RETURN label"),
]


class TestAcceptsValueShapes:
    """A write keyword inside a value never becomes a keyword token."""

    @pytest.mark.parametrize(
        "case_id,query",
        ACCEPTED_VALUE_SHAPE_QUERIES,
        ids=[case for case, _ in ACCEPTED_VALUE_SHAPE_QUERIES],
    )
    def test_accepts_value_shape(self, case_id: str, query: str) -> None:
        assert is_read_only_cypher(query) is True, f"{case_id}: read-only query rejected: {query!r}"


class TestSubstringKeywords:
    """APOC writes hide inside literals, so the substring scan stays raw-text."""

    @pytest.mark.parametrize(
        "case_id,query",
        [
            ("apoc_doit", "CALL apoc.cypher.doIt('CREATE (n)')"),
            ("apoc_run", "CALL apoc.cypher.run('CREATE (n:Test)', {})"),
            ("apoc_periodic_iterate", "CALL apoc.periodic.iterate('MATCH (n) RETURN n', 'DELETE n', {})"),
        ],
    )
    def test_rejects_apoc_write_procedure(self, case_id: str, query: str) -> None:
        keywords = ("APOC.CYPHER.DOIT", "APOC.CYPHER.RUN", "APOC.PERIODIC.ITERATE")
        assert is_read_only_cypher(query, substring_keywords=keywords) is False, (
            f"{case_id}: APOC write procedure accepted: {query!r}"
        )

    def test_substring_keywords_default_to_disabled(self) -> None:
        """Without the parameter the APOC procedure is not detected."""
        assert is_read_only_cypher("CALL apoc.cypher.doIt('CREATE (n)')") is True


class TestIdentKeywords:
    """``DROP`` lexes as an identifier, so the caller opts into it explicitly."""

    def test_rejects_bare_drop_identifier(self) -> None:
        assert is_read_only_cypher("DROP INDEX idx", ident_keywords=("DROP",)) is False

    def test_accepts_drop_inside_a_value(self) -> None:
        query = "MATCH (a:Repository {id: 'github::Repository::acme/drop-table'}) RETURN a"
        assert is_read_only_cypher(query, ident_keywords=("DROP",)) is True

    def test_ident_keywords_default_to_disabled(self) -> None:
        """With no ``ident_keywords`` a DROP identifier is not detected."""
        assert is_read_only_cypher("MATCH (n) RETURN n AS drop") is True

    def test_rejects_drop_used_as_an_alias_when_opted_in(self) -> None:
        """Conservative on purpose: any bare DROP identifier is rejected."""
        assert is_read_only_cypher("MATCH (n) RETURN n AS drop", ident_keywords=("DROP",)) is False


class TestFailsClosed:
    """Unlexable or empty input is rejected."""

    @pytest.mark.parametrize(
        "case_id,query",
        [
            ("unterminated_string", "MATCH (n) WHERE n.x = 'abc"),
            ("unterminated_block_comment", "MATCH (n) /* unclosed"),
            ("empty", ""),
            ("whitespace_only", "   "),
        ],
    )
    def test_rejects(self, case_id: str, query: str) -> None:
        assert is_read_only_cypher(query) is False, f"{case_id}: accepted: {query!r}"

    def test_rejects_unterminated_backtick(self) -> None:
        assert is_read_only_cypher("MATCH (n:`unclosed) RETURN n") is False


class TestReadStart:
    """The first token must be a read clause."""

    def test_accepts_return_start(self) -> None:
        assert is_read_only_cypher("RETURN 1") is True

    def test_rejects_unknown_start(self) -> None:
        assert is_read_only_cypher("FOOBAR (n) RETURN n") is False

    def test_rejects_comments_only_query(self) -> None:
        """A comments-only query lexes to ``[EOF]``; rule 6 rejects it."""
        assert is_read_only_cypher("// just a comment") is False


class TestLiteralContentsAreNeverInspected:
    """A write keyword inside a literal is a STRING token and must be accepted.

    Do not add a rule that inspects literal *contents* to reject these: such a
    rule rejects every read-only query whose literal happens to contain a write
    keyword, which is exactly the bug this checker exists to fix.
    """

    @pytest.mark.parametrize(
        "case_id,query",
        [
            ("or_empty_adjacent", "MATCH (n:Person) WHERE n.name = '' OR '' = 'CREATE' RETURN n"),
            ("and_empty_adjacent", "MATCH (n:Person) WHERE n.name = '' AND '' = 'SET' RETURN n"),
        ],
    )
    def test_accepts_write_keyword_in_empty_adjacent_literal(self, case_id: str, query: str) -> None:
        assert is_read_only_cypher(query) is True, f"{case_id}: read-only query rejected: {query!r}"


class TestReadStartParityWithReadOnlyKeywords:
    """Every entry of the deleted ``READ_ONLY_KEYWORDS`` must still be an accepted start.

    ``WHERE n.x = 1``, ``LIMIT 10``, ``ORDER BY n.x`` and ``SKIP 10`` are all
    accepted today by the legacy ``startswith`` check over
    ``READ_ONLY_KEYWORDS``. Dropping any of ``WHERE``/``ORDER``/``SKIP``/
    ``LIMIT`` from ``READ_START_TOKENS`` is a regression, not a tightening: it
    returns HTTP 400 for valid read-only queries typed into the Console.
    """

    @pytest.mark.parametrize(
        "case_id,query",
        [
            ("where", "WHERE n.x = 1"),
            ("limit", "LIMIT 10"),
            ("order", "ORDER BY n.x"),
            ("skip", "SKIP 10"),
        ],
    )
    def test_read_start_parity_with_read_only_keywords(self, case_id: str, query: str) -> None:
        assert is_read_only_cypher(query) is True, f"{case_id}: read-only start rejected: {query!r}"


class TestReadStartRejectsKeywordPrefixedIdentifiers:
    """The kind test is stricter than the legacy ``startswith`` check.

    ``MATCHING (n) RETURN n`` lexes as an ``IDENT``, not a ``MATCH``, and is
    correctly rejected here, whereas ``startswith("MATCH")`` accepts it today.
    This *is* a behaviour change and it is deliberate — the query is not valid
    Cypher either way.
    """

    @pytest.mark.parametrize(
        "case_id,query",
        [
            ("matching", "MATCHING (n) RETURN n"),
            ("matchx", "MATCHX (n) RETURN n"),
            ("returns", "RETURNS (n)"),
        ],
    )
    def test_read_start_rejects_keyword_prefixed_identifiers(self, case_id: str, query: str) -> None:
        assert is_read_only_cypher(query) is False, f"{case_id}: prefixed identifier accepted: {query!r}"

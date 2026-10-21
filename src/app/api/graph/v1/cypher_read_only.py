"""Value-aware read-only check for raw Cypher queries.

The legacy check in :mod:`app.api.graph.v1.query` uppercased the whole query
string and regex-scanned it for write keywords with ``\\b`` word boundaries.
Because the scan ran over raw text rather than parsed syntax, a write keyword
appearing **inside a value** — a string literal, a backtick identifier or a
comment — matched exactly like a real clause. Ordinary ids such as
``github::Repository::facebook/create-react-app`` therefore produced HTTP 400
on genuinely read-only queries.

This module replaces the text-wide scan with a lexer-driven decision: the query
is tokenised (via ``cypherast``) and rejected only if a token *is* a write
keyword. Values and comments never produce keyword tokens, so the false
positive disappears structurally rather than by special-casing. See
``plans/047-cypher-read-only-value-aware-check.md``.

Two keyword groups cannot be expressed as token kinds and stay explicit
parameters of :func:`is_read_only_cypher`:

* APOC write procedures hide the write inside a string literal, so they remain
  a raw-text substring scan (deliberately literal-blind).
* ``DROP`` is not a Cypher clause at all (it appears in ``DROP INDEX`` /
  ``DROP CONSTRAINT``), so it lexes as an identifier and must be opted into by
  the caller.
"""

from __future__ import annotations

from collections.abc import Sequence

from cypherast.errors import TokenizeError
from cypherast.lexer import Lexer, Token, TokenKind

from common.logger import logger

__all__ = [
    "READ_START_TOKENS",
    "WRITE_KEYWORD_TOKENS",
    "is_read_only_cypher",
    "tokenise_cypher",
]


# Write clauses that ``cypherast`` exposes as first-class token kinds.
WRITE_KEYWORD_TOKENS: frozenset[TokenKind] = frozenset(
    {
        TokenKind.CREATE,
        TokenKind.MERGE,
        TokenKind.SET,
        TokenKind.DELETE,
        TokenKind.DETACH,
        TokenKind.REMOVE,
        TokenKind.FOREACH,
    }
)

# Token kinds that may legally start a read-only query. This is the token-kind
# equivalent of the deleted ``READ_ONLY_KEYWORDS`` constant (which listed
# MATCH, OPTIONAL, WITH, UNWIND, RETURN, WHERE, ORDER, SKIP, LIMIT, UNION,
# CALL); every entry there must stay accepted or valid read-only
# queries typed into the Console regress to HTTP 400.
READ_START_TOKENS: frozenset[TokenKind] = frozenset(
    {
        TokenKind.MATCH,
        TokenKind.OPTIONAL,
        TokenKind.WITH,
        TokenKind.UNWIND,
        TokenKind.RETURN,
        TokenKind.WHERE,
        TokenKind.ORDER,
        TokenKind.SKIP,
        TokenKind.LIMIT,
        TokenKind.CALL,
        TokenKind.UNION,
    }
)


def tokenise_cypher(query: str) -> list[Token] | None:
    """Lex ``query``. Return None if it cannot be lexed.

    Args:
        query: The Cypher query string to tokenise.

    Returns:
        The list of tokens produced by the lexer, or ``None`` when the lexer
        raises :class:`~cypherast.errors.TokenizeError` (for example an
        unterminated string literal, backtick identifier or block comment).
    """
    try:
        return Lexer(query).tokenize()
    except TokenizeError as exc:
        logger.warning(f"Query validation failed: Could not tokenize query: {exc}")
        return None


def is_read_only_cypher(
    query: str,
    *,
    substring_keywords: Sequence[str] = (),
    ident_keywords: Sequence[str] = (),
) -> bool:
    """True if the query contains no write operation.

    Args:
        query: The Cypher query string to validate.
        substring_keywords: Keywords detected by a raw-text substring scan.
            Intended for APOC write procedures, whose write lives inside a
            string literal and can never be seen as a keyword token.
        ident_keywords: Keywords rejected when they appear as a bare identifier
            token. Intended for ``DROP``, which ``cypherast`` lexes as an
            identifier.

    Returns:
        True if the query is read-only, False otherwise. Fails closed: an
        empty query or one that cannot be lexed is rejected.
    """
    if not query or not query.strip():
        return False

    tokens = tokenise_cypher(query)
    if tokens is None:
        return False

    for token in tokens:
        if token.kind in WRITE_KEYWORD_TOKENS:
            logger.warning(f"Query validation failed: Contains write operation '{token.kind.name}'")
            return False

    normalized = query.upper()
    for substring_keyword in substring_keywords:
        if substring_keyword.upper() in normalized:
            logger.warning(f"Query validation failed: Contains write operation '{substring_keyword}'")
            return False

    upper_ident_keywords = {keyword.upper() for keyword in ident_keywords}
    for token in tokens:
        if token.kind is TokenKind.IDENT and token.text.upper() in upper_ident_keywords:
            logger.warning(f"Query validation failed: Contains write operation '{token.text}'")
            return False

    # Comments are never emitted as tokens by cypherast, so the first token is
    # always significant syntax. A query that is only comments/whitespace
    # lexes to ``[EOF]`` and is rejected by the read-start check below.
    first_token = tokens[0]
    if first_token.kind not in READ_START_TOKENS:
        logger.warning(
            f"Query validation failed: Does not start with read operation. Starts with: {first_token.text[:30]}"
        )
        return False

    return True

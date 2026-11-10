"""Unit tests proving catalogue metadata is scoped to its owner.

There is no Postgres fixture for unit tests in this repo and no sqlite test
database, so these assert on the **compiled SQL** of the statement each
query-layer function builds. That is the only technique that can see a WHERE
predicate or an ``ON CONFLICT`` target: a canned-row fake cannot, because the
filtering happens in Postgres, not in Python.

Markers: ``unit``.
"""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy.dialects import postgresql

from app.api.queries.v1 import query as metadata_query

pytestmark = [pytest.mark.unit, pytest.mark.asyncio]

#: Placeholder row returned by the recorder; the tests assert on SQL, never on it.
_ROW = object()


class _Result:
    """Minimal stand-in for a SQLAlchemy ``Result``."""

    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def scalars(self) -> "_Result":
        return self

    def all(self) -> list[Any]:
        return list(self._rows)

    def scalar_one_or_none(self) -> Any:
        return self._rows[0] if self._rows else None

    def scalar_one(self) -> Any:
        return self._rows[0]


class _Recorder:
    """AsyncSession stub that records statements and returns canned rows."""

    def __init__(self, rows: tuple[Any, ...] = (_ROW,)) -> None:
        self.statements: list[Any] = []
        self._rows = list(rows)

    async def execute(self, stmt: Any) -> _Result:
        self.statements.append(stmt)
        return _Result(self._rows)

    async def refresh(self, row: Any) -> None:
        return None


def _sql(sess: _Recorder) -> str:
    """Return the most recently executed statement as compiled SQL."""
    return str(
        sess.statements[-1].compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )


class TestListCatalogMetadataIsScoped:
    async def test_filters_by_subject(self) -> None:
        """``list_catalog_metadata`` only returns the caller's rows."""
        sess = _Recorder()
        await metadata_query.list_catalog_metadata(sess, subject="user-1")  # type: ignore[arg-type]
        sql = _sql(sess)
        assert "catalog_metadata.subject" in sql
        assert "'user-1'" in sql


class TestGetCatalogMetadataIsScoped:
    async def test_filters_by_subject_and_catalog_id(self) -> None:
        """``get_catalog_metadata`` matches on the owner as well as the id."""
        sess = _Recorder()
        await metadata_query.get_catalog_metadata(  # type: ignore[arg-type]
            sess, subject="user-1", catalog_id="a/b"
        )
        sql = _sql(sess)
        assert "'user-1'" in sql
        assert "'a/b'" in sql


class TestUpsertCatalogMetadataTargetsCompositeKey:
    async def test_conflict_target_is_catalog_id_and_subject(self) -> None:
        """The upsert conflicts on the composite key, not ``catalog_id`` alone.

        With the old unique constraint dropped, an ``ON CONFLICT (catalog_id)``
        target would raise at runtime — there is no longer an index to infer.
        """
        sess = _Recorder()
        await metadata_query.upsert_catalog_metadata(  # type: ignore[arg-type]
            sess, subject="user-1", catalog_id="a/b", is_favourite=True
        )
        sql = _sql(sess)
        assert "ON CONFLICT (catalog_id, subject) DO UPDATE" in sql

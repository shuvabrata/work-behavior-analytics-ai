"""Unit tests for the collaboration query loader and its wiring into the service.

The refactor this guards replaces two inline file reads in
``api/graph/v1/service.py`` with one loader. Its main risk is not the path — it is
that the query text changes while nobody is looking, so the tests here pin the
text the service actually executes.
"""

from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any

import pytest

from app.analytics.collaboration.queries_loader import (
    QUERIES_DIR,
    load_collaboration_score_query,
    load_query,
)
from app.api.graph.v1 import service

pytestmark = pytest.mark.unit

EGO_FOCUS = "github::Person::probe"


def test_loader_is_colocated_with_the_query_files():
    """QUERIES_DIR must be resolved from this module, not from a caller's depth."""
    loader_module = importlib.import_module(
        "app.analytics.collaboration.queries_loader"
    )
    assert QUERIES_DIR == Path(loader_module.__file__).parent / "queries"
    assert (QUERIES_DIR / "collaboration_score.cypher").is_file()


def test_loads_the_scoring_query_verbatim():
    expected = (QUERIES_DIR / "collaboration_score.cypher").read_text(encoding="utf-8")
    assert load_collaboration_score_query() == expected


def test_scoring_query_is_the_current_one():
    """Guards against the loader quietly pointing at a stale file."""
    query = load_collaboration_score_query()
    assert "$focus_id" in query, "the ego focus filter is missing"
    assert query.count("UNION ALL") == 17, "not all 18 layer blocks are present"


def test_missing_query_raises_with_the_path():
    with pytest.raises(FileNotFoundError) as excinfo:
        load_query("does_not_exist.cypher")
    assert "does_not_exist.cypher" in str(excinfo.value)


def _capture_query(monkeypatch: pytest.MonkeyPatch, call: Any) -> str:
    """Run ``call`` with execute_cypher_query stubbed and return the query it passed."""
    captured: dict[str, str] = {}

    def fake_execute(query: str, timeout: int | None = None, parameters: Any = None) -> list:
        captured["query"] = query
        return []

    monkeypatch.setattr(service, "execute_cypher_query", fake_execute)
    with pytest.raises(ValueError):  # the service raises once the query returns no rows
        call()
    return captured["query"]


def test_org_service_executes_the_shared_query(monkeypatch: pytest.MonkeyPatch):
    query = _capture_query(monkeypatch, service.get_collaboration_network)
    assert query == load_collaboration_score_query()


def test_ego_service_executes_the_shared_query(monkeypatch: pytest.MonkeyPatch):
    query = _capture_query(
        monkeypatch, lambda: service.get_ego_network(EGO_FOCUS)
    )
    assert query == load_collaboration_score_query()

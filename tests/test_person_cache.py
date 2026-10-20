from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from connectors.commons.person_cache import PersonCache
from connectors.neo4j_db.models import Person, _is_account_id_stub, merge_person


pytestmark = pytest.mark.unit


class _SingleResult:
    def __init__(self, row):
        self._row = row

    def single(self):
        return self._row


def test_get_or_create_person_reuses_existing_person_by_atlassian_account() -> None:
    session = MagicMock()

    def run_side_effect(query: str, **_kwargs):
        if "WHERE im.id IN $identity_ids" in query:
            return _SingleResult({"id": "jira::Person::acc123"})
        raise AssertionError(f"Unexpected query: {query}")

    session.run.side_effect = run_side_effect
    cache = PersonCache()

    with patch("connectors.commons.person_cache.merge_person") as mock_merge_person:
        person_id, is_new = cache.get_or_create_person(
            session,
            email=None,
            name="Alice Dev",
            provider="confluence",
            external_id="acc123",
            account_id="acc123",
        )

    assert person_id == "jira::Person::acc123"
    assert is_new is False
    mock_merge_person.assert_called_once()
    person = mock_merge_person.call_args.args[1]
    assert person.id == "jira::Person::acc123"
    assert person.name == "Alice Dev"


def test_get_or_create_person_prefers_email_before_atlassian_account() -> None:
    session = MagicMock()

    def run_side_effect(query: str, **_kwargs):
        if "WHERE p.email = $email" in query:
            return _SingleResult({"id": "github::Person::alice"})
        raise AssertionError(f"Unexpected query: {query}")

    session.run.side_effect = run_side_effect
    cache = PersonCache()

    with patch("connectors.commons.person_cache.merge_person") as mock_merge_person:
        person_id, is_new = cache.get_or_create_person(
            session,
            email="alice@example.com",
            name="Alice Dev",
            provider="confluence",
            external_id="acc123",
            account_id="acc123",
        )

    assert person_id == "github::Person::alice"
    assert is_new is False
    assert session.run.call_count == 1
    mock_merge_person.assert_called_once()
    person = mock_merge_person.call_args.args[1]
    assert person.id == "github::Person::alice"
    assert person.email == "alice@example.com"


# ---------------------------------------------------------------------------
# Merge guard: account-id shaped names must not clobber a real name
# ---------------------------------------------------------------------------


def test_is_account_id_stub_recognises_atlassian_ids() -> None:
    assert _is_account_id_stub("712020:cc7f7515-d137-44a0-9858-22b270a86387") is True
    assert _is_account_id_stub("557058:62105664-0fbe-4128-ab5c-3b0071e8f7f5") is True


def test_is_account_id_stub_treats_empty_blank_as_stub() -> None:
    assert _is_account_id_stub(None) is True
    assert _is_account_id_stub("") is True
    assert _is_account_id_stub("   ") is True


def test_is_account_id_stub_does_not_match_real_names() -> None:
    assert _is_account_id_stub("Alice Dev") is False
    assert _is_account_id_stub("Shuva Brata Deb") is False
    assert _is_account_id_stub("alice@example.com") is False


def test_merge_person_skips_name_when_incoming_is_account_id_stub() -> None:
    """A stub named by account id must NOT overwrite an existing real name."""
    session = MagicMock()
    person = Person(
        id="confluence::Person::712020:cc7f7515-d137-44a0-9858-22b270a86387",
        name="712020:cc7f7515-d137-44a0-9858-22b270a86387",
        email=None,
        url=None,
    )
    merge_person(session, person)
    # ``name`` must never be written to a raw account id, so it cannot clobber
    # a previously-resolved real name. The display props ARE coalesce-filled so
    # the node is never left blank, but a plain overwrite is forbidden.
    all_queries = " ".join(call.args[0] for call in session.run.call_args_list)
    assert "p.name = $name" not in all_queries
    assert "p._display_name = $_display_name" not in all_queries
    assert "p._on_hover_name = $_on_hover_name" not in all_queries
    # fill-only guards are present for the display props
    assert "coalesce(p._display_name, $_display_name)" in all_queries
    assert "coalesce(p._on_hover_name, $_on_hover_name)" in all_queries


def test_merge_person_fills_display_name_when_name_empty() -> None:
    """An empty name still coalesce-fills _display_name so the node is not blank."""
    session = MagicMock()
    person = Person(
        id="jira::Person::712020:23da340e-0000-0000-0000-000000000000",
        name="",
        email=None,
        url=None,
    )
    merge_person(session, person)
    # ``name`` is not written (empty), but _display_name is coalesce-filled so
    # the node renders a label (the account id, derived from the node id).
    all_queries = " ".join(call.args[0] for call in session.run.call_args_list)
    assert "p.name = $name" not in all_queries
    assert "p._display_name = $_display_name" not in all_queries
    assert "coalesce(p._display_name, $_display_name)" in all_queries
    assert "coalesce(p._on_hover_name, $_on_hover_name)" in all_queries


def test_merge_person_sets_display_name_when_real_name() -> None:
    session = MagicMock()
    person = Person(
        id="jira::Person::acc123",
        name="Alice Dev",
        email="alice@example.com",
        url=None,
    )
    merge_person(session, person)
    all_queries = " ".join(call.args[0] for call in session.run.call_args_list)
    assert "p.name = $name" in all_queries
    assert "p._display_name = $_display_name" in all_queries


def test_merge_person_sets_name_when_real_name() -> None:
    session = MagicMock()
    person = Person(
        id="jira::Person::acc123",
        name="Alice Dev",
        email="alice@example.com",
        url=None,
    )
    merge_person(session, person)
    all_queries = " ".join(call.args[0] for call in session.run.call_args_list)
    assert "p.name = $name" in all_queries


# ---------------------------------------------------------------------------
# Cache-hit re-merge: a richer name should upgrade an earlier stub
# ---------------------------------------------------------------------------


def test_cache_hit_upgrades_person_with_real_name() -> None:
    """On a provider-cache hit, the incoming richer name should be merged."""
    session = MagicMock()

    def run_side_effect(query: str, **_kwargs):
        if "WHERE p.email = $email" in query:
            return _SingleResult(None)
        raise AssertionError(f"Unexpected query: {query}")

    session.run.side_effect = run_side_effect
    cache = PersonCache()
    cache._provider_cache[("jira", "acc123")] = "confluence::Person::acc123"

    with patch("connectors.commons.person_cache.merge_person") as mock_merge_person:
        person_id, is_new = cache.get_or_create_person(
            session,
            email="lalika@example.com",
            name="Lalika Doe",
            provider="jira",
            external_id="acc123",
            account_id="acc123",
        )

    assert person_id == "confluence::Person::acc123"
    assert is_new is False
    mock_merge_person.assert_called_once()
    person = mock_merge_person.call_args.args[1]
    assert person.id == "confluence::Person::acc123"
    assert person.name == "Lalika Doe"


def test_cache_hit_merge_skips_account_id_stub_name() -> None:
    """A cache-hit stub (name == account id) must not overwrite the real name."""
    session = MagicMock()
    cache = PersonCache()
    cache._provider_cache[("jira", "acc123")] = "confluence::Person::acc123"

    with patch("connectors.commons.person_cache.merge_person") as mock_merge_person:
        person_id, _ = cache.get_or_create_person(
            session,
            email=None,
            name="712020:cc7f7515-d137-44a0-9858-22b270a86387",
            provider="jira",
            external_id="acc123",
            account_id="acc123",
        )

    assert person_id == "confluence::Person::acc123"
    mock_merge_person.assert_called_once()
    person = mock_merge_person.call_args.args[1]
    # merge_person itself guards the name; the Person passed still carries it,
    # but the underlying merge query will skip it via the stub guard.
    assert person.name == "712020:cc7f7515-d137-44a0-9858-22b270a86387"


def test_atlassian_account_cache_hit_remerges_richer_person() -> None:
    """An atlassian-account cache hit should also upgrade an earlier stub."""
    session = MagicMock()
    cache = PersonCache()
    cache._atlassian_account_cache["acc123"] = "confluence::Person::acc123"

    with patch("connectors.commons.person_cache.merge_person") as mock_merge_person:
        person_id, is_new = cache.get_or_create_person(
            session,
            email=None,
            name="Lalika Doe",
            provider="jira",
            external_id="acc123",
            account_id="acc123",
        )

    assert person_id == "confluence::Person::acc123"
    assert is_new is False
    mock_merge_person.assert_called_once()
    person = mock_merge_person.call_args.args[1]
    assert person.name == "Lalika Doe"

def _reroute_session(owner_id: str | None = "github::Person::alice") -> MagicMock:
    """Session whose email lookup returns ``owner_id`` and everything else misses."""
    session = MagicMock()

    def run_side_effect(query: str, **_kwargs):
        if "WHERE p.email = $email" in query:
            return _SingleResult({"id": owner_id} if owner_id else None)
        return _SingleResult(None)

    session.run.side_effect = run_side_effect
    return session


def _two_calls(cache: PersonCache, session: MagicMock) -> tuple[str, str]:
    first_id, _ = cache.get_or_create_person(
        session, email=None, name="712020:abc",
        provider="jira", external_id="712020:abc", account_id="712020:abc",
    )
    second_id, _ = cache.get_or_create_person(
        session, email="alice@x.com", name="Alice",
        provider="jira", external_id="712020:abc", account_id="712020:abc",
    )
    return first_id, second_id


def test_provider_cache_hit_with_email_owned_by_other_person_reroutes() -> None:
    cache = PersonCache()
    session = _reroute_session()

    with patch("connectors.commons.person_cache.merge_person"), \
            patch("connectors.commons.person_cache.rehome_person") as mock_rehome:
        first_id, second_id = _two_calls(cache, session)

    assert first_id == "jira::Person::712020:abc"
    assert second_id == "github::Person::alice"
    mock_rehome.assert_called_once_with(session, "jira::Person::712020:abc", "github::Person::alice")


def test_reroute_repoints_caches_and_third_call_needs_no_query() -> None:
    cache = PersonCache()
    session = _reroute_session()
    with patch("connectors.commons.person_cache.merge_person"), \
            patch("connectors.commons.person_cache.rehome_person"):
        _two_calls(cache, session)
        queries_before = cache.db_queries
        third_id, _ = cache.get_or_create_person(
            session, email="alice@x.com", name="Alice",
            provider="jira", external_id="712020:abc", account_id="712020:abc",
        )
    assert third_id == "github::Person::alice"
    assert cache.db_queries == queries_before
    assert cache._provider_cache[("jira", "712020:abc")] == "github::Person::alice"
    assert cache._atlassian_account_cache["712020:abc"] == "github::Person::alice"
    assert cache._email_cache["alice@x.com"] == "github::Person::alice"


def test_no_owner_merges_email_onto_cached_person_without_rehome() -> None:
    cache = PersonCache()
    session = _reroute_session(owner_id=None)
    with patch("connectors.commons.person_cache.merge_person") as mock_merge, \
            patch("connectors.commons.person_cache.rehome_person") as mock_rehome:
        _, second_id = _two_calls(cache, session)
    assert second_id == "jira::Person::712020:abc"
    mock_rehome.assert_not_called()
    assert mock_merge.call_args.args[1].email == "alice@x.com"
    assert cache._email_cache["alice@x.com"] == "jira::Person::712020:abc"


def test_rehome_failure_returns_cached_id_and_warns() -> None:
    cache = PersonCache()
    session = _reroute_session()
    with patch("connectors.commons.person_cache.merge_person"), \
            patch("connectors.commons.person_cache.rehome_person", side_effect=RuntimeError("boom")), \
            patch("connectors.commons.person_cache.logger") as mock_logger:
        _, second_id = _two_calls(cache, session)
    assert second_id == "jira::Person::712020:abc"
    mock_logger.warning.assert_called_once()
    assert cache._provider_cache[("jira", "712020:abc")] == "jira::Person::712020:abc"


def test_owner_is_cached_person_does_not_rehome() -> None:
    cache = PersonCache()
    session = _reroute_session(owner_id="jira::Person::712020:abc")
    with patch("connectors.commons.person_cache.merge_person"), \
            patch("connectors.commons.person_cache.rehome_person") as mock_rehome:
        _, second_id = _two_calls(cache, session)
    assert second_id == "jira::Person::712020:abc"
    mock_rehome.assert_not_called()


def test_repeated_hits_with_same_email_query_owner_at_most_once() -> None:
    cache = PersonCache()
    session = _reroute_session(owner_id=None)
    with patch("connectors.commons.person_cache.merge_person"), \
            patch("connectors.commons.person_cache.rehome_person"):
        _two_calls(cache, session)
        queries_before = cache.db_queries
        cache.get_or_create_person(
            session, email="alice@x.com", name="Alice",
            provider="jira", external_id="712020:abc", account_id="712020:abc",
        )
    assert cache.db_queries == queries_before


def test_pending_identity_mapping_is_repointed_on_reroute() -> None:
    cache = PersonCache()
    session = _reroute_session()
    with patch("connectors.commons.person_cache.merge_person"), \
            patch("connectors.commons.person_cache.rehome_person"):
        cache.get_or_create_person(
            session, email=None, name="712020:abc",
            provider="jira", external_id="712020:abc", account_id="712020:abc",
        )
        cache.queue_identity_mapping(
            "jira::Person::712020:abc", "jira::IdentityMapping::712020:abc",
            "jira", "712020:abc", "", "2026-01-01T00:00:00Z",
        )
        cache.get_or_create_person(
            session, email="alice@x.com", name="Alice",
            provider="jira", external_id="712020:abc", account_id="712020:abc",
        )
    _identity, rel = cache._pending_identities["jira::IdentityMapping::712020:abc"]
    assert rel.to_id == "github::Person::alice"
    assert rel.from_id == "jira::IdentityMapping::712020:abc"


def test_unique_constraint_failure_in_merge_is_logged_as_warning() -> None:
    cache = PersonCache()
    err = RuntimeError("Node(1) already exists with label `Person` and property `email`")
    with patch("connectors.commons.person_cache.merge_person", side_effect=err), \
            patch("connectors.commons.person_cache.logger") as mock_logger:
        cache._try_merge_richer_person(MagicMock(), "jira::Person::x", "X", "a@x.com", None, None)
    mock_logger.warning.assert_called_once()

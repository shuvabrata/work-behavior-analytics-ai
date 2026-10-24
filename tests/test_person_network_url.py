"""Tests for the per-person collaboration network URL contract.

The deep link documented in ``docs/design/collaboration-network-design.md`` is a
public interface: other components build these links, and the page parses them.
These tests pin both halves, and the round trip between them, so a change to one
side cannot silently break the other.
"""

from __future__ import annotations

from urllib.parse import urlsplit

import pytest

from app.common.person_network_url import (
    DEFAULT_MAX_COLLABORATORS,
    MAX_MAX_COLLABORATORS,
    MIN_MAX_COLLABORATORS,
    PERSON_NETWORK_PATH,
    build_person_network_url,
    clamp_max_collaborators,
    is_valid_wba_id,
    parse_person_network_url,
    search_with_person,
)


pytestmark = pytest.mark.unit

PERSON = "github::Person::alice"


def _search_of(url: str) -> str:
    """Return the query part of *url* as ``dcc.Location.search`` would see it."""
    return "?" + urlsplit(url).query


# ---------------------------------------------------------------------------
# is_valid_wba_id
# ---------------------------------------------------------------------------

def test_wba_id_accepts_three_non_empty_segments():
    assert is_valid_wba_id("github::Person::alice") is True
    assert is_valid_wba_id("jira::Issue::PROJ-1") is True


def test_wba_id_allows_colons_inside_the_id_segment():
    """Only the first two separators split, so an id may itself contain ``::``."""
    assert is_valid_wba_id("github::PullRequest::org/repo#1") is True


@pytest.mark.parametrize(
    "candidate",
    ["", "bad", "a::b", "jira::::x", "::Person::x", "Person::x::"],
)
def test_wba_id_rejects_malformed_keys(candidate: str) -> None:
    assert is_valid_wba_id(candidate) is False


# ---------------------------------------------------------------------------
# clamp_max_collaborators
# ---------------------------------------------------------------------------

def test_cap_defaults_when_absent_or_blank():
    assert clamp_max_collaborators(None) == DEFAULT_MAX_COLLABORATORS
    assert clamp_max_collaborators("") == DEFAULT_MAX_COLLABORATORS
    assert clamp_max_collaborators("   ") == DEFAULT_MAX_COLLABORATORS


def test_cap_falls_back_on_unparseable_input():
    assert clamp_max_collaborators("not-a-number") == DEFAULT_MAX_COLLABORATORS


def test_cap_clamps_into_the_range_the_api_accepts():
    """An out-of-range link must still produce a value the endpoint will serve."""
    assert clamp_max_collaborators("0") == MIN_MAX_COLLABORATORS
    assert clamp_max_collaborators("-5") == MIN_MAX_COLLABORATORS
    assert clamp_max_collaborators("999") == MAX_MAX_COLLABORATORS
    assert clamp_max_collaborators("50") == 50


# ---------------------------------------------------------------------------
# build
# ---------------------------------------------------------------------------

def test_build_targets_the_person_network_route():
    url = build_person_network_url(PERSON)
    assert url.startswith(PERSON_NETWORK_PATH + "?")


def test_build_encodes_the_wba_id():
    """The ``::`` separators must be escaped, or the query string is ambiguous."""
    url = build_person_network_url(PERSON)
    assert "::" not in url.split("?", 1)[1]
    assert "github%3A%3APerson%3A%3Aalice" in url


def test_build_omits_cap_when_not_given():
    """Omission lets the page apply its own default rather than pinning one."""
    parsed = parse_person_network_url(_search_of(build_person_network_url(PERSON)))
    assert parsed["max_collaborators"] == DEFAULT_MAX_COLLABORATORS
    assert "max_collaborators" not in build_person_network_url(PERSON)


def test_build_writes_cap_when_given():
    url = build_person_network_url(PERSON, 50)
    assert "max_collaborators=50" in url


def test_build_clamps_an_out_of_range_cap_rather_than_emitting_it():
    assert "max_collaborators=500" in build_person_network_url(PERSON, 999)


def test_build_passes_extra_settings_through():
    url = build_person_network_url(PERSON, None, {"lookback_days": 30, "exclude_bots": "true"})
    assert "lookback_days=30" in url
    assert "exclude_bots=true" in url


def test_build_skips_empty_extra_settings():
    url = build_person_network_url(PERSON, None, {"lookback_days": None, "layers": ""})
    assert "lookback_days" not in url
    assert "layers" not in url


# ---------------------------------------------------------------------------
# parse
# ---------------------------------------------------------------------------

def test_parse_reads_a_person_and_cap():
    parsed = parse_person_network_url("?person=github%3A%3APerson%3A%3Aalice&max_collaborators=50")
    assert parsed["person"] == PERSON
    assert parsed["max_collaborators"] == 50


def test_parse_tolerates_a_missing_leading_question_mark():
    parsed = parse_person_network_url("person=github%3A%3APerson%3A%3Aalice")
    assert parsed["person"] == PERSON


def test_parse_returns_none_for_a_malformed_person():
    """A bad deep link degrades to "no person selected", never a bad query."""
    assert parse_person_network_url("?person=not-a-wba-id")["person"] is None


def test_parse_returns_none_when_absent():
    assert parse_person_network_url("")["person"] is None
    assert parse_person_network_url(None)["person"] is None


def test_parse_always_yields_a_usable_cap():
    assert parse_person_network_url("")["max_collaborators"] == DEFAULT_MAX_COLLABORATORS
    assert parse_person_network_url("?max_collaborators=junk")["max_collaborators"] == DEFAULT_MAX_COLLABORATORS


# ---------------------------------------------------------------------------
# build -> parse round trip (the contract other components depend on)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("cap", [None, 10, 50, 100])
def test_built_urls_parse_back_to_what_was_asked_for(cap: int | None) -> None:
    parsed = parse_person_network_url(_search_of(build_person_network_url(PERSON, cap)))
    assert parsed["person"] == PERSON
    expected = DEFAULT_MAX_COLLABORATORS if cap is None else cap
    assert parsed["max_collaborators"] == expected


def test_round_trip_survives_ids_with_punctuation():
    tricky = "github::PullRequest::org/repo#1"
    parsed = parse_person_network_url(_search_of(build_person_network_url(tricky)))
    assert parsed["person"] == tricky


@pytest.mark.parametrize(
    "wba_id",
    [
        "github::PullRequest::org/repo#1",   # '#' would truncate if left raw
        "jira::Issue::PROJ+1",               # '+' would decode to a space
        "jira::Issue::A&B",                  # '&' would split the parameter
        "github::Person::alice",             # plain: the common case
    ],
)
def test_built_urls_survive_characters_reserved_in_urls(wba_id: str) -> None:
    """Encoding is required for reserved characters, not for the ``::`` separator.

    A raw ``::`` happens to survive a query string, so a hand-built link works
    for plain Person ids and fails only for ids containing ``#``, ``+`` or
    ``&``. The builder must be correct for all of them.
    """
    assert parse_person_network_url(_search_of(build_person_network_url(wba_id)))["person"] == wba_id


def test_raw_colons_are_tolerated_on_arrival():
    """A hand-written raw link still parses — the page is forgiving, not strict.

    Pasting ``?person=github::Person::alice`` must work; the page normalises the
    address bar afterwards (see the URL-sync callback), which is cosmetic rather
    than load-bearing.
    """
    parsed = parse_person_network_url("?person=github::Person::alice")
    assert parsed["person"] == "github::Person::alice"


# ---------------------------------------------------------------------------
# search_with_person — the page's URL-sync merge
# ---------------------------------------------------------------------------

def test_rewrite_sets_the_person_on_an_empty_query():
    assert search_with_person("", PERSON) == "?person=github%3A%3APerson%3A%3Aalice"


def test_rewrite_replaces_an_existing_person():
    updated = search_with_person("?person=github%3A%3APerson%3Aold", PERSON)
    assert parse_person_network_url(updated)["person"] == PERSON


def test_rewrite_preserves_other_settings():
    updated = search_with_person("?layers=a&lookback_days=30", PERSON)
    assert "layers=a" in updated
    assert "lookback_days=30" in updated
    assert parse_person_network_url(updated)["person"] == PERSON


def test_rewrite_removes_the_person_when_cleared():
    updated = search_with_person("?person=github%3A%3APerson%3Aa&lookback_days=30", None)
    assert "person" not in updated
    assert "lookback_days=30" in updated


def test_rewrite_can_empty_the_query_entirely():
    assert search_with_person("?person=github%3A%3APerson%3Aa", None) == ""


@pytest.mark.parametrize(
    "search, wba",
    [
        ("?person=", None),
        ("?person=github%3A%3APerson%3A%3Aalice", PERSON),
        ("?lookback_days=30", None),
        ("", None),
    ],
)
def test_rewrite_returns_none_when_nothing_would_change(search: str, wba: str | None) -> None:
    """The no-op guard is load-bearing.

    The page writes ``url.search`` from this value and also reads ``url.search``
    to load the network. If an unchanged write were emitted, the resulting
    navigation would re-trigger the loader for the same person — a redundant
    query, and a loop on every navigation. ``None`` lets the callback answer
    ``no_update`` instead.
    """
    assert search_with_person(search, wba) is None


def test_rewrite_is_idempotent_with_a_real_wba_id():
    """Applying the rewrite twice must be a no-op the second time."""
    once = search_with_person("?lookback_days=30", PERSON)
    assert search_with_person(once, PERSON) is None

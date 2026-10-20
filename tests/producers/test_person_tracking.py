"""Unit tests for the shared PersonSeenTracker."""

import pytest

from connectors.producers.person_tracking import PersonSeenTracker, looks_like_profile

pytestmark = pytest.mark.unit


def test_stub_shapes_are_not_profiles() -> None:
    assert looks_like_profile("acc1", "acc1", "") is False
    assert looks_like_profile("acc1", "", "") is False
    assert looks_like_profile("acc1", None, None) is False


def test_name_only_is_profile() -> None:
    assert looks_like_profile("acc1", "Alice", "") is True


def test_email_only_is_profile() -> None:
    assert looks_like_profile("acc1", "acc1", "a@x.com") is True


def test_stub_then_stub() -> None:
    t = PersonSeenTracker()
    assert t.claim("a", is_profile=False) is True
    assert t.claim("a", is_profile=False) is False


def test_stub_then_profile() -> None:
    t = PersonSeenTracker()
    assert t.claim("a", is_profile=False) is True
    assert t.claim("a", is_profile=True) is True
    assert t.claim("a", is_profile=True) is False
    assert t.claim("a", is_profile=False) is False


def test_profile_then_stub() -> None:
    t = PersonSeenTracker()
    assert t.claim("a", is_profile=True) is True
    assert t.claim("a", is_profile=False) is False


def test_ids_independent() -> None:
    t = PersonSeenTracker()
    assert t.claim("a", is_profile=True) is True
    assert t.claim("b", is_profile=False) is True
    assert t.claim("b", is_profile=True) is True


def test_has_profile() -> None:
    t = PersonSeenTracker()
    t.claim("a", is_profile=False)
    assert t.has_profile("a") is False
    t.claim("a", is_profile=True)
    assert t.has_profile("a") is True


def test_stub_only_ids() -> None:
    t = PersonSeenTracker()
    t.claim("a", is_profile=False)
    t.claim("b", is_profile=False)
    assert t.stub_only_ids() == {"a", "b"}
    t.claim("a", is_profile=True)
    assert t.stub_only_ids() == {"b"}

"""Per-scan bookkeeping of which Persons a producer has already published.

A producer sometimes learns about a user only from a reference (an @mention, a
reviewer list) and publishes a *stub* — no display name, no email. A later
sighting of the same user (assignee, comment author, commit author) may carry
the real *profile*. A plain "seen" set lets the stub win and silently drops the
profile. ``PersonSeenTracker`` instead allows, per id and per scan, at most one
stub followed by at most one profile.

All methods are synchronous with no ``await``, so each call is atomic on a
single asyncio event loop (no lock needed). Do not share an instance across threads.
"""

from __future__ import annotations


def looks_like_profile(identifier: str, name: str | None, email: str | None) -> bool:
    """True when ``name``/``email`` carry real information about ``identifier``.

    A stub is built with ``name == identifier`` (or empty) and no email. A user
    with a real name but a hidden email *is* a profile: nothing richer will
    arrive from the same API visibility.
    """
    if email:
        return True
    return bool(name) and name != identifier


class PersonSeenTracker:
    """Decide whether a Person signal should be published (see module docstring)."""

    def __init__(self) -> None:
        self._profiles: set[str] = set()
        self._stubs: set[str] = set()

    def claim(self, person_id: str, *, is_profile: bool) -> bool:
        """Record a sighting; return True if the caller should publish a signal now."""
        if person_id in self._profiles:
            return False
        if not is_profile and person_id in self._stubs:
            return False
        (self._profiles if is_profile else self._stubs).add(person_id)
        return True

    def has_profile(self, person_id: str) -> bool:
        """True if a profile signal was already claimed for ``person_id`` (lets callers skip costly lookups)."""
        return person_id in self._profiles

    def stub_only_ids(self) -> set[str]:
        """Ids published only as a stub so far (used by plan 048's end-of-scan lookup)."""
        return self._stubs - self._profiles

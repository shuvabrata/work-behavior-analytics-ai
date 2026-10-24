"""URL contract for the per-person (ego) collaboration network page.

This module is the single source of truth for the deep link that opens
``/app/collaboration/person`` focused on one Person. Any component that wants to
send a user to a specific person's network should build its link here rather
than assembling query strings by hand, so the parameter names and the page's
parser cannot drift apart.

Two halves, deliberately mirrored:

* :func:`build_person_network_url` — produce a link (for navigation targets,
  `href`s, or deep links handed to other systems).
* :func:`parse_person_network_url` — read one back.

The page's own callback uses the parser; components that only link out need the
builder. Because both live here, a change to the contract is a one-file change.

Kept in ``app.common`` rather than in the page package: importing a page
package runs its ``__init__`` (which imports layouts and callbacks), so a page
module cannot be imported by another page without risking a circular import —
see CLAUDE.md's Dash UI rules.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs, quote, urlencode

PERSON_NETWORK_PATH = "/app/collaboration/person"
"""Route of the per-person collaboration network page."""

PERSON_PARAM = "person"
"""Query parameter carrying the focus Person's canonical ``wba_id``."""

MAX_COLLABORATORS_PARAM = "max_collaborators"
"""Query parameter capping how many collaborators are fetched."""

DEFAULT_MAX_COLLABORATORS = 25
"""Cap applied when the URL omits ``max_collaborators``."""

MIN_MAX_COLLABORATORS = 1
MAX_MAX_COLLABORATORS = 500
"""Bounds the API accepts for ``max_collaborators``.

Mirrored in the endpoint's own ``Query(ge=..., le=...)`` declaration; a value
outside this range would be rejected with a 400 by the API, so the UI clamps
into it before building a link.
"""


def is_valid_wba_id(wba_id: str) -> bool:
    """Return whether *wba_id* is a well-formed ``{source}::{type}::{id}`` key.

    Mirrors ``app.api.activity.v1.service.parse_wba_id``. Only the first two
    ``::`` separators split — the id itself may contain ``::``, as in
    ``github::PullRequest::org/repo#1``.

    Args:
        wba_id: Candidate canonical key.

    Returns:
        True when the key has three non-empty ``::``-separated segments.
    """
    parts = (wba_id or "").split("::", 2)
    return len(parts) == 3 and all(parts)


def clamp_max_collaborators(value: Any) -> int:
    """Coerce *value* into the range the API accepts for ``max_collaborators``.

    Absent, blank or unparseable input falls back to the default rather than
    failing, mirroring the page's tolerance for a hand-edited URL.

    Args:
        value: Raw value from a URL query string, or ``None``.

    Returns:
        An int within ``[MIN_MAX_COLLABORATORS, MAX_MAX_COLLABORATORS]``.
    """
    if value is None or str(value).strip() == "":
        return DEFAULT_MAX_COLLABORATORS
    try:
        parsed = int(str(value).strip())
    except (TypeError, ValueError):
        return DEFAULT_MAX_COLLABORATORS
    return max(MIN_MAX_COLLABORATORS, min(parsed, MAX_MAX_COLLABORATORS))


def build_person_network_url(
    wba_id: str,
    max_collaborators: int | None = None,
    extra_params: dict[str, Any] | None = None,
) -> str:
    """Build the deep link to one Person's collaboration network.

    Args:
        wba_id: Canonical Person key, e.g. ``github::Person::alice``. Returned
            as-encoded even when malformed, so callers can surface a bad id
            rather than silently producing a link to nobody; use
            :func:`is_valid_wba_id` first if you need to reject it.
        max_collaborators: Collaborator cap to fetch with. ``None`` omits the
            parameter, letting the page apply its own default. Otherwise it is
            written explicitly so the intended cap survives the round trip.
        extra_params: Optional additional query parameters (for example the
            collaboration settings the Analytics card sends). Keys with a
            ``None``/empty value are skipped.

    Returns:
        Path plus query string, e.g.
        ``/app/collaboration/person?person=github%3A%3APerson%3Aalice``.
    """
    params: list[tuple[str, str]] = [
        (PERSON_PARAM, wba_id),
    ]
    if max_collaborators is not None:
        params.append(
            (MAX_COLLABORATORS_PARAM, str(clamp_max_collaborators(max_collaborators)))
        )
    for key, value in (extra_params or {}).items():
        if value is None or value == "":
            continue
        params.append((key, str(value)))
    return f"{PERSON_NETWORK_PATH}?{urlencode(params, quote_via=quote, safe='')}"


def parse_person_network_url(search: str | None) -> dict[str, Any]:
    """Read the person-network contract back out of a URL query string.

    Args:
        search: The query string, with or without a leading ``?`` (Dash passes
            ``dcc.Location.search``).

    Returns:
        ``{"person": str | None, "max_collaborators": int}`` — ``person`` is
        ``None`` unless a well-formed wba_id was supplied, so a malformed link
        degrades to "no person selected" rather than querying with a bad id.
        ``max_collaborators`` is always a usable int.
    """
    params = parse_qs((search or "").lstrip("?"), keep_blank_values=True)
    candidates = params.get(PERSON_PARAM) or [""]
    raw_person = candidates[0].strip()
    cap_candidates: list[str] = params.get(MAX_COLLABORATORS_PARAM) or []
    return {
        "person": raw_person if is_valid_wba_id(raw_person) else None,
        "max_collaborators": clamp_max_collaborators(
            cap_candidates[0] if cap_candidates else None
        ),
    }


def search_with_person(search: str | None, wba_id: str | None) -> str | None:
    """Return *search* with its ``person`` parameter set to *wba_id* (or removed).

    Every other parameter is preserved in order, so rewriting the URL on a
    pick never discards the collaboration settings the link carried.

    Args:
        search: Current query string, with or without a leading ``?``.
        wba_id: Person key to write, or ``None`` to remove the parameter.

    Returns:
        The updated query string (leading ``?``, or ``""`` when nothing
        remains) — or ``None`` when the value is already what was asked for, so
        callers can return ``no_update`` and avoid re-triggering navigation and
        a redundant reload.
    """
    current = parse_qs((search or "").lstrip("?"), keep_blank_values=True)
    existing_candidates: list[str] = current.get(PERSON_PARAM) or []
    existing = existing_candidates[0] if existing_candidates else None
    new_value = wba_id if wba_id else None
    if (existing or None) == new_value:
        return None

    pairs: list[tuple[str, str]] = []
    written = False
    for key, values in current.items():
        if key == PERSON_PARAM:
            if new_value is not None:
                pairs.append((key, new_value))
                written = True
            continue
        for value in values:
            pairs.append((key, value))
    if new_value is not None and not written:
        pairs.append((PERSON_PARAM, new_value))

    return "?" + urlencode(pairs, quote_via=quote, safe="") if pairs else ""

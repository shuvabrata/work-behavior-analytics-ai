#!/usr/bin/env python3
"""Render every distinct Activity-scope timeline card as ASCII, from live data.

The Activity Timeline page renders one card per ``activity_actions`` row.  The
card's *appearance* is decided by a 5-tuple:

    (lane source, lane entity_type, lane_role, relationship_type, other entity_type)

This script enumerates every 5-tuple actually present in Postgres, picks a real
example row for each, and draws the card exactly as it will look **after plan
043** (``plans/043-activity-timeline-card-reading-order.md``):

    line 1  the humanized relationship        (the scan axis)
    line 2  <EntityType> · <object name>      + time, right-aligned

where the *object* is the other side of the relationship — the target when the
lane entity is the actor, the actor when the lane entity is the target.

Line 1/line 2 text is produced by the application's own helpers
(``card_primary``, ``card_secondary``, ``entity_type_label``) with the app
timezone, so the ASCII cannot drift from the real card.  The object's name is
resolved the same way the app resolves it — from ``activity_events.display_name``,
newest row for the other side's ``(source, entity_type, entity_id)`` — then falls
back to ``related_id``, then to ``activity_actions.summary``.

The script is strictly **read-only**: it issues SELECTs and writes nothing but
its own stdout.  ``--json PATH`` is the only file it can write, and only on
request.

Usage
-----
    source .venv/bin/activate
    PYTHONPATH=src python scripts/render_activity_cards.py
    PYTHONPATH=src python scripts/render_activity_cards.py --source github
    PYTHONPATH=src python scripts/render_activity_cards.py --lane-type Person
    PYTHONPATH=src python scripts/render_activity_cards.py --min-count 2
    PYTHONPATH=src python scripts/render_activity_cards.py --json cards.json

Environment (read from ``.env``, falling back to the process environment):
``DATABASE_URL`` — the async SQLAlchemy URL (``postgresql+asyncpg://``); the
dialect suffix is stripped so psycopg2 can consume it.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Repo convention (see scripts/report_timeline_person_identity_coverage.py): make
# ``src`` importable so the app's own helpers can be reused verbatim.
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

import psycopg2  # noqa: E402
from psycopg2.extras import RealDictCursor  # noqa: E402

from app.common.timezone import get_app_timezone  # noqa: E402
from ui.pages.timeline import layout as _timeline_layout  # noqa: E402
from ui.pages.timeline.helpers import (  # noqa: E402
    card_primary as _card_primary,
)
from ui.pages.timeline.helpers import (  # noqa: E402
    card_secondary as _card_secondary,
)
from ui.pages.timeline.helpers import (  # noqa: E402
    entity_type_label,
)

# Borrowed from the real renderer so the preview cannot drift from the card.
_EVENT_TIME_FORMAT = _timeline_layout._EVENT_TIME_FORMAT

# ---------------------------------------------------------------------------
# Card geometry — mirrors the real card (design doc §7.1, §7.4)
# ---------------------------------------------------------------------------

# Lanes are min-width 220px.  The card inside one is 3px lane accent + 1px border
# + 7px padding each side, so the text box is 220 - 4 - 14 = 202px.
LANE_WIDTH_PX = 220

# Average advance width of Inter at the two card font sizes, measured close
# enough for a monospace-styled preview.  The real card uses CSS ellipsis; we
# reproduce the resulting character budget.
_PRIMARY_PX_PER_CHAR = 7.7  # 14px, medium weight
_SECONDARY_PX_PER_CHAR = 6.6  # 12px, regular

# The time is right-aligned on the secondary line and always kept whole.
_TIME_RESERVE_CHARS = 2 + len("12:00 PM")  # gap + time


def _text_width_px() -> int:
    """Return the card's inner text width in pixels."""
    return LANE_WIDTH_PX - (3 + 1) - (7 * 2)


def _truncate(text: str, limit: int) -> str:
    """Truncate ``text`` to ``limit`` characters, appending an ellipsis."""
    if limit <= 0:
        return ""
    if len(text) <= limit:
        return text
    if limit == 1:
        return "…"
    return text[: limit - 1].rstrip() + "…"


# ---------------------------------------------------------------------------
# Connection
# ---------------------------------------------------------------------------


def load_env(path: Path) -> None:
    """Load ``.env`` into the process environment without overriding it."""
    try:
        from dotenv import load_dotenv  # noqa: E402

        load_dotenv(path, override=False)
        return
    except ImportError:
        pass
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


def postgres_dsn() -> str:
    """Return a psycopg2 DSN from ``DATABASE_URL``.

    ``DATABASE_URL`` is an async SQLAlchemy URL (``postgresql+asyncpg://``); the
    dialect suffix is stripped — the same normalisation the consumer's
    ``activity_writer`` performs.
    """
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        raise SystemExit("DATABASE_URL is not set (checked .env and the environment)")
    return re.sub(r"^postgresql\+\w+://", "postgresql://", url)


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------

# One row per activity_actions row, annotated with the lane's role and the other
# side's identity.  ``target_source`` is used when the column exists (plan 043
# Phase 2)
# phase 1) and silently ignored when it does not — exactly the COALESCE the plan
# specifies.  The probe below decides which SELECT to use.
_COLUMNS_WITH_TARGET_SOURCE = """
    a.id,
    a.source,
    a.event_time,
    a.actor_entity_type,
    a.actor_entity_id,
    a.target_entity_type,
    a.target_entity_id,
    a.relationship_type,
    a.summary,
    a.url,
    COALESCE(a.target_source, a.source) AS target_source
"""

_COLUMNS_WITHOUT_TARGET_SOURCE = """
    a.id,
    a.source,
    a.event_time,
    a.actor_entity_type,
    a.actor_entity_id,
    a.target_entity_type,
    a.target_entity_id,
    a.relationship_type,
    a.summary,
    a.url,
    a.source AS target_source
"""

# Every distinct card, keyed by the lane's own perspective.  ``is_actor`` marks
# rows where the lane entity is the actor; the other side is then the target.
_CARDS_SQL = """
WITH sides AS (
    SELECT
        a.id,
        a.source        AS lane_source,
        a.actor_entity_type AS lane_type,
        TRUE            AS is_actor,
        a.relationship_type,
        a.target_entity_type AS other_type,
        a.target_entity_id   AS other_id,
        {target_source}      AS other_source,
        a.summary,
        a.url,
        a.event_time
    FROM activity_actions a

    UNION ALL

    SELECT
        a.id,
        a.source,
        a.target_entity_type,
        FALSE,
        a.relationship_type,
        a.actor_entity_type,
        a.actor_entity_id,
        a.source,
        a.summary,
        a.url,
        a.event_time
    FROM activity_actions a

    -- A self-relationship (actor == target) would otherwise be counted twice;
    -- the lane is both sides, so keep only the actor view.
    WHERE NOT (
        a.actor_entity_type = a.target_entity_type
        AND a.actor_entity_id = a.target_entity_id
    )
),
ranked AS (
    SELECT
        s.*,
        COUNT(*) OVER (
            PARTITION BY s.lane_source, s.lane_type, s.is_actor,
                         s.relationship_type, s.other_type
        ) AS combo_count,
        ROW_NUMBER() OVER (
            PARTITION BY s.lane_source, s.lane_type, s.is_actor,
                         s.relationship_type, s.other_type
            ORDER BY s.event_time DESC, s.id DESC
        ) AS rn
    FROM sides s
)
SELECT
    r.lane_source,
    r.lane_type,
    r.is_actor,
    r.relationship_type,
    r.other_type,
    r.combo_count,
    r.other_id,
    r.other_source,
    r.summary,
    r.url,
    r.event_time,
    (
        SELECT e.display_name
        FROM activity_events e
        WHERE e.source = r.other_source
          AND e.entity_type = r.other_type
          AND e.entity_id = r.other_id
          AND e.display_name IS NOT NULL
        ORDER BY e.event_time DESC, e.id DESC
        LIMIT 1
    ) AS related_name
FROM ranked r
WHERE r.rn = 1
ORDER BY r.lane_source, r.lane_type, r.is_actor DESC, r.combo_count DESC
"""


def fetch_cards(cur: Any, dsn_has_target_source: bool) -> list[dict[str, Any]]:
    """Return one annotated example row per distinct activity card."""
    sql = _CARDS_SQL.format(
        target_source=(
            "a.target_source" if dsn_has_target_source else "a.source"
        )
    )
    cur.execute(sql)
    return list(cur.fetchall())


def has_target_source(cur: Any) -> bool:
    """Return whether ``activity_actions.target_source`` exists (plan 043 Phase 2)."""
    cur.execute(
        """
        SELECT 1
        FROM information_schema.columns
        WHERE table_name = 'activity_actions' AND column_name = 'target_source'
        """
    )
    return cur.fetchone() is not None


# ---------------------------------------------------------------------------
# Card composition — mirrors plan 043 (Phases 4/5) exactly
# ---------------------------------------------------------------------------


def _format_event_time(raw: datetime | None) -> str:
    """Render an event timestamp as the card does: time-of-day, app timezone.

    Format is ``%I:%M %p`` with **no** zero-stripping — it must match
    ``layout._EVENT_TIME_FORMAT`` exactly, or the preview shows ``2:44 PM`` where
    the real card shows ``02:44 PM``.
    """
    if raw is None:
        return ""
    if raw.tzinfo is None:
        raw = raw.replace(tzinfo=timezone.utc)
    return raw.astimezone(get_app_timezone()).strftime(_EVENT_TIME_FORMAT)


def _as_card_event(row: dict[str, Any]) -> dict[str, Any]:
    """Normalise a query row into the event dict the card helpers expect.

    The row names the other side ``other_id``; the helpers (plan 043) call it
    ``related_id``.  ``entity_type`` is the *other* side's type, as it is on the
    real ``TimelineEvent``.
    """
    return {
        "relationship_type": row.get("relationship_type"),
        "entity_type": row.get("other_type"),
        "related_name": row.get("related_name"),
        "related_id": row.get("other_id"),
        "summary": row.get("summary"),
    }


def card_primary(row: dict[str, Any]) -> str:
    """Line 1 — the app helper that owns the format (no private reimplementation)."""
    return _card_primary(_as_card_event(row))


def card_secondary_object(row: dict[str, Any]) -> tuple[str, bool]:
    """Line 2's name, and whether it came from a resolved display_name.

    The name comes from the app helper that owns the format; the ``resolved``
    flag is derived here for the preview's raw-id reporting only.
    """
    event = _as_card_event(row)
    name = _card_secondary(event)
    resolved = bool(
        isinstance(event.get("related_name"), str) and event["related_name"].strip()
    )
    return name, resolved


# Two id shapes that are technically a display_name but unreadable on a card:
#   * Atlassian account id  557058:62105664-0fbe-4128-ab5c-3b0071e8f7f5
#   * git commit SHA        90c96746132bd8279703d7c43998b80bc6d491da
# Deliberately narrow: GitHub logins ("shuvabrata"), Jira keys ("BTS-15") and
# Jira project keys ("BTS") ARE the human-readable name for those entities.
_ATLASSIAN_ID = re.compile(r"^\d{6}:[0-9a-f-]{16,}$", re.IGNORECASE)
_GIT_SHA = re.compile(r"^[0-9a-f]{40}$", re.IGNORECASE)

# The entity type whose natural id is a name (a GitHub/Jira Person is identified
# by a readable login/account, so a Person name equal to its id is acceptable).
_READABLE_ID_TYPES = frozenset({"Person", "Project", "Space", "Repository", "Branch"})


def looks_like_raw_id(name: str, other_id: str | None, other_type: str) -> bool:
    """Return whether a resolved name is really an unreadable raw id."""
    if not name:
        return False
    if _ATLASSIAN_ID.match(name) or _GIT_SHA.match(name):
        return True
    # A name identical to the entity's id is only a smell for entity types whose
    # id is not itself meaningful (Commit, File, Issue, Page, ...).
    return bool(other_id and name == other_id and other_type not in _READABLE_ID_TYPES)


def render_card(row: dict[str, Any]) -> dict[str, Any]:
    """Build the two display lines and the truncation facts for one card."""
    other_type = str(row.get("other_type") or "")
    type_label = entity_type_label(other_type)

    primary = card_primary(row)
    name, resolved = card_secondary_object(row)
    secondary = f"{type_label} · {name}" if name else type_label
    time_text = _format_event_time(row.get("event_time"))

    width = _text_width_px()
    primary_limit = int(width / _PRIMARY_PX_PER_CHAR)
    secondary_limit = max(
        1, int(width / _SECONDARY_PX_PER_CHAR) - _TIME_RESERVE_CHARS
    )

    return {
        "lane_source": row.get("lane_source"),
        "lane_type": row.get("lane_type"),
        "is_actor": bool(row.get("is_actor")),
        "relationship_type": row.get("relationship_type"),
        "other_type": other_type,
        "other_id": row.get("other_id"),
        "related_name": row.get("related_name"),
        "name_resolved": resolved,
        "raw_id_shown": looks_like_raw_id(name, row.get("other_id"), other_type),
        "count": int(row.get("combo_count") or 0),
        "time": time_text,
        "primary": primary,
        "secondary": secondary,
        "primary_shown": _truncate(primary, primary_limit),
        "secondary_shown": _truncate(secondary, secondary_limit),
        "primary_truncated": len(primary) > primary_limit,
        "secondary_truncated": len(secondary) > secondary_limit,
    }


# ---------------------------------------------------------------------------
# ASCII rendering
# ---------------------------------------------------------------------------


def _box(card: dict[str, Any]) -> list[str]:
    """Draw one card as an ASCII box at the lane's minimum width."""
    width = _text_width_px()
    primary_budget = int(width / _PRIMARY_PX_PER_CHAR)
    secondary_budget = max(
        1, int(width / _SECONDARY_PX_PER_CHAR) - _TIME_RESERVE_CHARS
    )
    inner = max(primary_budget, secondary_budget + _TIME_RESERVE_CHARS)

    # Left column is the secondary text, right column the time.
    sec = card["secondary_shown"]
    tim = card["time"]

    lines = [
        "┌" + "─" * inner + "┐",
        "│" + card["primary_shown"].ljust(inner) + "│",
        "│" + (sec + " " * max(1, inner - len(sec) - len(tim)) + tim).ljust(inner) + "│",
        "└" + "─" * inner + "┘",
    ]
    return lines


def _group_header(source: str, lane_type: str, total: int, combos: int) -> str:
    """Header for one lane group."""
    return (
        f"{source} · {lane_type}"
        f"   ({total} rows across {combos} distinct card"
        f"{'s' if combos != 1 else ''})"
    )


def _card_caption(card: dict[str, Any]) -> str:
    """The `[role] REL -> OtherType   Nx` caption above each card."""
    arrow = "->" if card["is_actor"] else "<-"
    role = "actor " if card["is_actor"] else "target"
    if not card["name_resolved"]:
        origin = "RAW ID — no event row for the object"
    elif card["raw_id_shown"]:
        origin = "RAW ID — display_name holds an account id, not a name"
    else:
        origin = "display_name"
    return (
        f"[{role}] {card['relationship_type']} {arrow} {card['other_type']}"
        f"   {card['count']}×   (object name: {origin})"
    )


def render_report(cards: list[dict[str, Any]]) -> str:
    """Render every card, grouped by lane source then lane entity type."""
    if not cards:
        return "No activity cards found."

    out: list[str] = []
    width = _text_width_px()
    out.append("Activity Timeline — card preview (Activity scope, post-plan-043 layout)")
    out.append(
        f"Lane width {LANE_WIDTH_PX}px → text box {width}px "
        f"(~{int(width / _PRIMARY_PX_PER_CHAR)} chars primary, "
        f"~{int(width / _SECONDARY_PX_PER_CHAR) - _TIME_RESERVE_CHARS} chars secondary + time)"
    )
    out.append(
        "Line 1 = relationship (the scan axis). Line 2 = <Type> · <object name> + time."
    )
    out.append(
        "The lane the user selected is the sentence subject and is not repeated on the card."
    )
    out.append("")

    by_group: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for card in cards:
        by_group.setdefault(
            (str(card["lane_source"]), str(card["lane_type"])), []
        ).append(card)

    total_rows = sum(card["count"] for card in cards)
    for (source, lane_type), group in by_group.items():
        group.sort(key=lambda c: (not c["is_actor"], -c["count"]))
        out.append("=" * 78)
        out.append(
            _group_header(
                source, lane_type, sum(c["count"] for c in group), len(group)
            )
        )
        out.append("=" * 78)
        for card in group:
            out.append(f"  {_card_caption(card)}")
            for line in _box(card):
                out.append("    " + line)
            flags = []
            if card["primary_truncated"]:
                flags.append(f"line 1 clipped: {card['primary']!r}")
            if card["secondary_truncated"]:
                flags.append(f"line 2 clipped: {card['secondary']!r}")
            if not card["name_resolved"]:
                flags.append(
                    f"object name unresolved — showing {card['secondary'].split(' · ')[-1]!r}"
                )
            elif card["raw_id_shown"]:
                flags.append(
                    "object name resolved to a raw id, not a human name — "
                    "the Person signal carried no name field"
                )
            for flag in flags:
                out.append(f"      ! {flag}")
            out.append("")

    out.append("-" * 78)
    out.append(
        f"{len(cards)} distinct cards across {len(by_group)} lane (source, entity_type) "
        f"groups."
    )
    out.append(
        f"{total_rows} lane-perspective rows represented — each action_actions row is "
        "counted\nonce from the actor's lane and once from the target's lane, because "
        "a card's\nappearance depends on which side the selected lane sits on."
    )

    # Resolve quality — how many rows show a real name vs a raw id on line 2.
    unresolved = [c for c in cards if not c["name_resolved"]]
    raw_id = [c for c in cards if c["name_resolved"] and c["raw_id_shown"]]
    named = [c for c in cards if c["name_resolved"] and not c["raw_id_shown"]]
    out.append("")
    out.append("Object-name resolution")
    out.append(
        f"  {len(named)}/{len(cards)} cards show a human object name; "
        f"{len(raw_id)} resolve to a raw id; {len(unresolved)} have no event row."
    )
    if raw_id:
        out.append("")
        out.append(
            "  Resolves, but the stored display_name is an account id — the object "
            "is a Person\n  whose signal carried no human name:"
        )
        for card in raw_id:
            out.append(
                f"    {card['lane_source']} · {card['lane_type']} "
                f"[{'actor ' if card['is_actor'] else 'target'}] "
                f"{card['relationship_type']} -> {card['other_type']}"
                f"   ({card['count']}×)   e.g. {card['related_name']!r}"
            )
    if unresolved:
        out.append("")
        out.append("  No activity_events row for the object — falls back to the raw id:")
        for card in unresolved:
            out.append(
                f"    {card['lane_source']} · {card['lane_type']} "
                f"[{'actor ' if card['is_actor'] else 'target'}] "
                f"{card['relationship_type']} -> {card['other_type']}"
                f"   ({card['count']}×)   e.g. {card['secondary'].split(' · ')[-1]!r}"
            )
    return "\n".join(out)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description=(
            "Render every distinct Activity-scope timeline card as ASCII, "
            "using live Postgres data and the post-plan-043 layout."
        )
    )
    parser.add_argument("--source", help="Only lane groups from this source.")
    parser.add_argument(
        "--lane-type", help="Only this lane entity_type (e.g. Person)."
    )
    parser.add_argument(
        "--min-count",
        type=int,
        default=1,
        help="Skip cards seen fewer than N times (default: 1).",
    )
    parser.add_argument(
        "--json",
        metavar="PATH",
        help="Also write the card data as JSON to PATH.",
    )
    return parser.parse_args()


def main() -> int:
    """Connect, enumerate the cards, and print the ASCII report."""
    args = parse_args()
    load_env(REPO_ROOT / ".env")

    conn = psycopg2.connect(postgres_dsn())
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            target_source_present = has_target_source(cur)
            cards = fetch_cards(cur, target_source_present)
    finally:
        conn.close()

    rendered = [render_card(row) for row in cards]

    if args.source:
        rendered = [c for c in rendered if c["lane_source"] == args.source]
    if args.lane_type:
        rendered = [c for c in rendered if c["lane_type"] == args.lane_type]
    rendered = [c for c in rendered if c["count"] >= args.min_count]

    if not target_source_present:
        print(
            "note: activity_actions.target_source does not exist yet "
            "(plan 043 Phase 2) — resolving the object's source from the "
            "action's own source, as the plan's COALESCE does.\n"
        )

    print(render_report(rendered))

    if args.json:
        Path(args.json).write_text(
            json.dumps(rendered, indent=2, default=str), encoding="utf-8"
        )
        print(f"\nWrote {len(rendered)} cards to {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

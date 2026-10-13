#!/usr/bin/env python3
"""Report the Activity Timeline coverage gain from Person-identity expansion.

The Activity Timeline store (Postgres) holds **raw** provider-scoped entity ids,
while Elasticsearch indexes a Person under their **canonical** ``wba_id``.  The
identity-expansion change makes the read path expand a ``Person`` lane — at
request time — to every ``IdentityMapping`` identity that maps to the canonical
person (resolved from Neo4j), instead of matching the canonical id alone.

This script measures that change against a live installation, read-only:

* **Before** — the lane as it behaved pre-change: a single ``(source, entity_id)``
  pair derived from the canonical ``wba_id``.
* **After** — the lane post-change: the same pair *plus* every identity Neo4j
  resolves for that person.

For each Person known to Elasticsearch it reports how many timeline rows
(``activity_actions`` + ``activity_events``) the lane can reach before and after,
the identities gained, and the aggregate coverage improvement.  It also reports
data-health signals that explain a low or zero gain (missing graph nodes, orphan
activity, persons whose only mapping is their own).

Usage
-----
    source .venv/bin/activate
    python scripts/report_person_identity_coverage.py
    python scripts/report_person_identity_coverage.py --json coverage.json
    python scripts/report_person_identity_coverage.py --person-source neo4j

Run it with the project virtualenv (it needs ``psycopg2``, ``neo4j`` and
``requests``).  The script never writes to any database.  ``--json PATH`` is the
only file it writes, and only when you ask for it.

Environment (read from ``.env`` via python-dotenv, falling back to the process
environment): ``DATABASE_URL``, ``NEO4J_URI``, ``NEO4J_USERNAME``,
``NEO4J_PASSWORD``, ``ELASTICSEARCH_URL``, ``ELASTIC_PASSWORD``.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Repo convention (see scripts/reconcile_es.py, scripts/merge_duplicate_persons.py):
# make ``src`` importable so the app's own code can be reused.
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

import psycopg2  # noqa: E402
import requests  # noqa: E402
from neo4j import GraphDatabase  # noqa: E402

# Reuse the application's own identity parser so this report measures exactly
# what the runtime does.  A local mirror keeps the script runnable if the app
# package cannot be imported.
try:
    from app.api.activity.v1.identity import parse_identity_id  # noqa: E402
except ImportError:  # pragma: no cover - fallback for a bare interpreter

    def parse_identity_id(identity_id: str) -> tuple[str, str] | None:
        """Mirror of ``app.api.activity.v1.identity.parse_identity_id``."""
        parts = identity_id.split("::", 2)
        if len(parts) != 3 or not parts[0] or not parts[2]:
            return None
        return parts[0], parts[2]


Identity = tuple[str, str]  # (source, entity_id)


def parse_wba_id(wba_id: str) -> tuple[str, str, str] | None:
    """Split a canonical ``{source}::{EntityType}::{entity_id}`` id.

    Returns ``(source, entity_type, entity_id)`` or ``None`` when malformed.
    ``entity_id`` keeps any embedded ``::`` (only the first two separators
    split), matching the application's lane construction.
    """
    parts = wba_id.split("::", 2)
    if len(parts) != 3 or not parts[0] or not parts[2]:
        return None
    return parts[0], parts[1], parts[2]


def own_pair_of(wba_id: str) -> Identity | None:
    """Return the lane's own ``(source, entity_id)`` pair for a Person wba_id."""
    parsed = parse_wba_id(wba_id)
    if parsed is None:
        return None
    return parsed[0], parsed[2]


def lane_pairs(wba_id: str, identity_ids: list[str]) -> tuple[Identity, list[Identity]]:
    """Return ``(own_pair, after_identities)`` for a person.

    Mirrors ``service.py::_fetch_lane``: the lane's own pair is unioned in first,
    then deduplicated with order preserved.
    """
    own = own_pair_of(wba_id)
    if own is None:
        return ("", ""), []
    resolved: list[Identity] = []
    for identity_id in identity_ids:
        ident = parse_identity_id(identity_id)
        if ident is not None:
            resolved.append(ident)
    after = list(dict.fromkeys([own, *resolved]))
    return own, after


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


def load_env() -> None:
    """Populate ``os.environ`` from the repo ``.env`` without overriding it."""
    env_path = REPO_ROOT / ".env"
    try:
        from dotenv import load_dotenv  # noqa: E402

        load_dotenv(env_path, override=False)
        return
    except ImportError:
        pass
    if not env_path.exists():
        return
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


def postgres_dsn() -> str:
    """Return a psycopg2-compatible DSN from ``DATABASE_URL``.

    ``DATABASE_URL`` is an async SQLAlchemy URL (``postgresql+asyncpg://``); the
    dialect suffix is stripped so psycopg2 can consume it — the same
    normalisation the consumer's ``activity_writer`` performs.
    """
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        raise SystemExit("DATABASE_URL is not set (checked .env and environment).")
    for prefix in ("postgresql+asyncpg://", "postgresql+psycopg2://", "postgres+asyncpg://"):
        if url.startswith(prefix):
            return "postgresql://" + url[len(prefix) :]
    return url


def git_head() -> str:
    """Return the short HEAD SHA, or ``"unknown"``."""
    try:
        return (
            subprocess.run(
                ["git", "-C", str(REPO_ROOT), "rev-parse", "--short", "HEAD"],
                capture_output=True,
                text=True,
                check=False,
            ).stdout.strip()
            or "unknown"
        )
    except OSError:
        return "unknown"


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class PersonRow:
    """One canonical Person lane and its before/after reach."""

    wba_id: str
    source: str
    entity_id: str
    display_name: str | None
    identities_after: list[Identity] = field(default_factory=list)
    added_identities: list[Identity] = field(default_factory=list)
    actions_before: int = 0
    actions_after: int = 0
    events_before: int = 0
    events_after: int = 0
    in_neo4j: bool = False

    @property
    def total_before(self) -> int:
        """Timeline rows the lane reached before the change."""
        return self.actions_before + self.events_before

    @property
    def total_after(self) -> int:
        """Timeline rows the lane reaches after the change."""
        return self.actions_after + self.events_after

    @property
    def gain(self) -> int:
        """Rows newly reachable."""
        return self.total_after - self.total_before

    @property
    def expanded(self) -> bool:
        """Whether the lane gains any identity."""
        return bool(self.added_identities)


@dataclass
class Report:
    """The full report payload (also the ``--json`` shape)."""

    generated_at: str
    repo_head: str
    person_source: str
    es_url: str
    neo4j_uri: str
    postgres_host: str
    persons: list[PersonRow]
    counts: dict[str, Any]
    health: dict[str, Any]


# ---------------------------------------------------------------------------
# Sources
# ---------------------------------------------------------------------------


def build_es_headers() -> dict[str, str]:
    """Return auth headers for Elasticsearch when a password is configured."""
    import base64

    password = os.environ.get("ELASTIC_PASSWORD", "")
    if not password:
        return {}
    token = base64.b64encode(f"elastic:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


def fetch_es_persons(es_url: str) -> dict[str, dict[str, Any]]:
    """Return ``{canonical_wba_id: source_fields}`` for every ES person doc.

    Elasticsearch indexes one document per (source, entity) pair under
    ``{source}_{entity_type}_index``; a Person doc's ``_id`` is the *canonical*
    wba_id.  Returns an empty mapping when ES is unreachable.
    """
    url = f"{es_url.rstrip('/')}/*_person_index/_search"
    body = {
        "size": 10000,
        "_source": [
            "wba_id", "source", "entity_type",
            "full_name", "login", "email", "account_id",
        ],
    }
    try:
        resp = requests.post(url, json=body, headers=build_es_headers(), timeout=30)
        resp.raise_for_status()
        payload = resp.json()
    except Exception as exc:  # pylint: disable=broad-except
        print(f"  ! Elasticsearch query failed ({exc}) — falling back to Neo4j.", file=sys.stderr)
        return {}

    persons: dict[str, dict[str, Any]] = {}
    for hit in payload.get("hits", {}).get("hits", []):
        src = hit.get("_source", {})
        if src.get("entity_type") and src["entity_type"] != "Person":
            continue
        wba_id = src.get("wba_id") or hit.get("_id")
        if wba_id:
            persons[wba_id] = src
    return persons


def fetch_neo4j_persons(uri: str, user: str, password: str) -> dict[str, dict[str, Any]]:
    """Return ``{person_id: {"identities": [...], "name": ...}}`` for Person nodes.

    ``MAPS_TO`` is stored once as a directed ``(IdentityMapping)-[:MAPS_TO]->(Person)``
    edge and read undirected (see ``docs/design/RELATIONSHIPS_DESIGN.md``), so the
    pattern below is direction-agnostic.
    """
    query = (
        "MATCH (p:Person) "
        "OPTIONAL MATCH (p)-[:MAPS_TO]-(i:IdentityMapping) "
        "RETURN p.id AS person_id, "
        "       coalesce(p._display_name, p.name) AS display_name, "
        "       [x IN collect(i.id) WHERE x IS NOT NULL] AS identity_ids"
    )
    out: dict[str, dict[str, Any]] = {}
    driver = GraphDatabase.driver(uri, auth=(user, password))
    try:
        with driver.session() as session:
            for record in session.run(query):
                out[record["person_id"]] = {
                    "identities": list(record["identity_ids"]),
                    "name": record["display_name"],
                }
    finally:
        driver.close()
    return out


Row = tuple[int, frozenset[Identity]]  # (row id, Person-side pairs the row touches)


def fetch_person_activity(dsn: str) -> tuple[list[Row], list[Row]]:
    """Return ``(action_rows, event_rows)`` for every Person-participating row.

    Each row is ``(id, {Person-side (source, entity_id) pairs})`` — an action
    naming a Person on *both* sides carries two pairs, but the row itself is
    still counted once by :func:`_reach`.

    Only rows whose Person side could belong to a lane are fetched, so the whole
    timeline is scanned in two queries regardless of table size.
    """
    action_sql = """
        SELECT id, source, actor_entity_type, actor_entity_id,
               target_entity_type, target_entity_id
        FROM activity_actions
        WHERE actor_entity_type = 'Person' OR target_entity_type = 'Person'
    """
    event_sql = """
        SELECT id, source, entity_id
        FROM activity_events
        WHERE entity_type = 'Person'
    """

    action_rows: list[Row] = []
    event_rows: list[Row] = []
    conn = psycopg2.connect(dsn)
    try:
        with conn.cursor() as cur:
            cur.execute(action_sql)
            for row_id, source, a_type, a_id, t_type, t_id in cur.fetchall():
                pairs = set()
                if a_type == "Person" and a_id:
                    pairs.add((source, a_id))
                if t_type == "Person" and t_id:
                    pairs.add((source, t_id))
                if pairs:
                    action_rows.append((row_id, frozenset(pairs)))
            cur.execute(event_sql)
            for row_id, source, entity_id in cur.fetchall():
                if entity_id:
                    event_rows.append((row_id, frozenset({(source, entity_id)})))
    finally:
        conn.close()
    return action_rows, event_rows


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------


def _reach(rows: list[Row], lane: set[Identity]) -> int:
    """Count rows that touch any identity in *lane* (each row counted once)."""
    return sum(1 for _, pairs in rows if pairs & lane)


def build_report(args: argparse.Namespace) -> Report:
    """Assemble the coverage report from the three live sources."""
    es_url = os.environ.get("ELASTICSEARCH_URL", "http://localhost:9200")
    neo4j_uri = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
    neo4j_user = os.environ.get("NEO4J_USERNAME", "neo4j")
    neo4j_password = os.environ.get("NEO4J_PASSWORD", "")
    dsn = postgres_dsn()

    print("Connecting…", file=sys.stderr)
    es_persons = fetch_es_persons(es_url) if args.person_source == "es" else {}
    graph = fetch_neo4j_persons(neo4j_uri, neo4j_user, neo4j_password)

    person_source = "es"
    if not es_persons:
        person_source = "neo4j"
        print("  · no ES persons found — reporting Neo4j Person nodes instead.", file=sys.stderr)
        es_persons = {pid: {"source": (parse_wba_id(pid) or ("", "", ""))[0]} for pid in graph}

    action_rows, event_rows = fetch_person_activity(dsn)

    rows: list[PersonRow] = []
    claimed: set[Identity] = set()
    for wba_id, es_doc in sorted(es_persons.items()):
        parsed = parse_wba_id(wba_id)
        if parsed is None or parsed[1] != "Person":
            continue
        source, _, entity_id = parsed
        own, after = lane_pairs(wba_id, graph.get(wba_id, {}).get("identities", []))
        if not after:
            continue
        added = [i for i in after if i != own]

        lane_before: set[Identity] = {own}
        lane_after: set[Identity] = set(after)
        claimed |= lane_after

        display = (
            es_doc.get("full_name")
            or es_doc.get("login")
            or graph.get(wba_id, {}).get("name")
            or entity_id
        )
        rows.append(
            PersonRow(
                wba_id=wba_id,
                source=source,
                entity_id=entity_id,
                display_name=display,
                identities_after=after,
                added_identities=added,
                actions_before=_reach(action_rows, lane_before),
                actions_after=_reach(action_rows, lane_after),
                events_before=_reach(event_rows, lane_before),
                events_after=_reach(event_rows, lane_after),
                in_neo4j=wba_id in graph,
            )
        )

    # Lanes also exist for graph-only persons (not yet indexed in ES); count their
    # identities as claimed so their activity is not misreported as orphan.
    for pid, node in graph.items():
        own = own_pair_of(pid)
        if own is None or (parse_wba_id(pid) or ("", "", ""))[1] != "Person":
            continue
        _, after = lane_pairs(pid, node.get("identities", []))
        claimed |= set(after)

    # --- aggregate counts -------------------------------------------------
    total_before = sum(r.total_before for r in rows)
    total_after = sum(r.total_after for r in rows)
    expanded = [r for r in rows if r.expanded]
    cross_provider = [r for r in rows if any(src != r.source for src, _ in r.added_identities)]
    provider_counts: dict[str, int] = {}
    for r in rows:
        for src, _ in r.identities_after:
            provider_counts[src] = provider_counts.get(src, 0) + 1
    counts = {
        "persons_total": len(rows),
        "persons_expanded": len(expanded),
        "persons_with_cross_provider_mapping": len(cross_provider),
        "persons_unchanged": len(rows) - len(expanded),
        "identities_by_provider": dict(sorted(provider_counts.items())),
        "actions_before": sum(r.actions_before for r in rows),
        "actions_after": sum(r.actions_after for r in rows),
        "events_before": sum(r.events_before for r in rows),
        "events_after": sum(r.events_after for r in rows),
        "rows_before": total_before,
        "rows_after": total_after,
        "rows_gained": total_after - total_before,
        "coverage_gain_pct": (
            round(100.0 * (total_after - total_before) / total_before, 2) if total_before else None
        ),
    }

    # --- data health ------------------------------------------------------
    all_rows = action_rows + event_rows
    all_pairs: set[Identity] = set()
    for _, pairs in all_rows:
        all_pairs |= pairs
    orphan_pairs = sorted(all_pairs - claimed)
    graph_person_ids = {pid for pid in graph if (parse_wba_id(pid) or ("", "", ""))[1] == "Person"}
    only_own = sorted(
        pid for pid in graph_person_ids
        if graph[pid]["identities"] and set(lane_pairs(pid, graph[pid]["identities"])[1]) == {own_pair_of(pid)}
    )
    health = {
        "es_persons_not_in_graph": sorted(set(es_persons) - set(graph)),
        "graph_persons_not_in_es": sorted(graph_person_ids - set(es_persons)),
        "persons_with_no_identity_mapping": sorted(
            pid for pid in graph_person_ids if not graph[pid]["identities"]
        ),
        "persons_whose_only_mapping_is_their_own": only_own,
        "orphan_person_activity_pairs": [list(p) for p in orphan_pairs],
        "orphan_person_activity_rows": sum(
            1 for _, pairs in all_rows if pairs & set(orphan_pairs)
        ),
        "total_person_activity_rows_scanned": len(all_rows),
    }

    return Report(
        generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        repo_head=git_head(),
        person_source=person_source,
        es_url=es_url,
        neo4j_uri=neo4j_uri,
        postgres_host=dsn.split("@")[-1].split("/")[0] if "@" in dsn else "?",
        persons=rows,
        counts=counts,
        health=health,
    )


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _fmt_pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value:+.2f}%"


def render(report: Report) -> None:
    """Print the human-readable report to stdout."""
    rule = "=" * 100
    print(rule)
    print(" Activity Timeline — Person lane coverage report")
    print("   BEFORE: the lane matches the single canonical identity only")
    print("   AFTER : the lane is expanded to every IdentityMapping identity (Neo4j, read-time)")
    print(rule)
    print(f" Generated   : {report.generated_at}")
    print(f" Repo HEAD   : {report.repo_head}")
    print(f" Person list : {report.person_source.upper()}")
    print(f" Sources     : ES {report.es_url} | Neo4j {report.neo4j_uri} | Postgres {report.postgres_host}")

    c = report.counts
    print()
    print(" --- Coverage summary " + "-" * 79)
    print(f"   Person lanes (from {report.person_source.upper()})        : {c['persons_total']}")
    print(f"   Lanes that gain identities (change helps) : {c['persons_expanded']}")
    print(f"   ...of which gain a CROSS-PROVIDER identity: {c['persons_with_cross_provider_mapping']}")
    print(f"   Lanes unchanged                           : {c['persons_unchanged']}")
    if c["identities_by_provider"]:
        breakdown = ", ".join(f"{src}={n}" for src, n in c["identities_by_provider"].items())
        print(f"   Identities per provider (after)           : {breakdown}")
    print()
    print(f"   Actions reachable  before → after : {c['actions_before']} → {c['actions_after']}")
    print(f"   Events  reachable  before → after : {c['events_before']} → {c['events_after']}")
    print(f"   TOTAL rows         before → after : {c['rows_before']} → {c['rows_after']}")
    print(f"   Rows newly reachable              : {c['rows_gained']}")
    print(f"   Coverage gain                     : {_fmt_pct(c['coverage_gain_pct'])}")

    print()
    print(" --- Per-person detail " + "-" * 78)
    id_w = min(max((len(r.wba_id) for r in report.persons), default=20), 62)
    name_w = min(max((len(r.display_name or "") for r in report.persons), default=10), 24)
    print(
        f" {'Person (canonical wba_id)':<{id_w}} {'Name':<{name_w}} "
        f"{'Ident':>5} {'Total B→A':>12} {'Gain':>6}  Added identities"
    )
    print(" " + "-" * (id_w + name_w + 40))
    for r in sorted(report.persons, key=lambda p: (-p.gain, p.wba_id)):
        added = ", ".join(f"{s}::{e}" for s, e in r.added_identities) or "—"
        name = (r.display_name or "")[:name_w]
        print(
            f" {r.wba_id:<{id_w}} {name:<{name_w}} {len(r.identities_after):>5} "
            f"{r.total_before:>5}→{r.total_after:<5} {r.gain:>+6}  {added}"
        )

    h = report.health
    print()
    print(" --- Data health " + "-" * 83)
    print(f"   Person activity rows scanned              : {h['total_person_activity_rows_scanned']}")
    print(f"   ES persons missing from Neo4j             : {len(h['es_persons_not_in_graph'])}")
    print(f"   Neo4j persons missing from ES             : {len(h['graph_persons_not_in_es'])}")
    print(f"   Persons with NO IdentityMapping (gap)     : {len(h['persons_with_no_identity_mapping'])}")
    print(f"   Persons whose only mapping is their own   : {len(h['persons_whose_only_mapping_is_their_own'])}")
    print(f"   Orphan Person activity pairs              : {len(h['orphan_person_activity_pairs'])}"
          f"  ({h['orphan_person_activity_rows']} rows)")
    for pair in h["orphan_person_activity_pairs"][:20]:
        print(f"       · {pair[0]}::{pair[1]}")
    for pid in h["persons_with_no_identity_mapping"][:20]:
        print(f"       · no mapping: {pid}")

    print()
    print(" --- Interpretation " + "-" * 81)
    if c["persons_expanded"] == 0:
        print("   No Person in this installation has more than one identity mapping, so the")
        print("   change expands nothing here. This is a DATA result, not a code defect: the")
        print("   consumer only creates a cross-provider MAPS_TO edge when two provider")
        print("   identities dedup — matching email, or a shared Atlassian account_id.")
        print("   'Persons whose only mapping is their own' above are exactly that case.")
    else:
        print(f"   {c['persons_expanded']} of {c['persons_total']} Person lanes reach more timeline rows")
        print(f"   after the change ({_fmt_pct(c['coverage_gain_pct'])} overall). Lanes not listed as")
        print("   expanded behave exactly as before; non-Person lanes are untouched by design.")
    print(rule)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> int:
    """Parse args, build the report, render it, optionally dump JSON."""
    parser = argparse.ArgumentParser(
        description="Measure Activity Timeline Person-lane coverage before/after identity expansion.",
    )
    parser.add_argument(
        "--person-source",
        choices=["es", "neo4j"],
        default="es",
        help="Where to read the Person list from (default: es, falls back to neo4j).",
    )
    parser.add_argument("--json", metavar="PATH", help="Also write the report as JSON to PATH.")
    args = parser.parse_args()

    load_env()
    report = build_report(args)
    render(report)

    if args.json:
        Path(args.json).write_text(json.dumps(asdict(report), indent=2), encoding="utf-8")
        print(f"\n JSON written to {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

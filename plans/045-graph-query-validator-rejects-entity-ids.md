# Plan 045: Graph query validator rejects entity ids that contain a write keyword

> **Status: PROBLEM STATEMENT ONLY — no solution specified.**
>
> This document records a confirmed defect and its measured evidence so it can be
> addressed deliberately later. It deliberately does **not** prescribe an
> approach, and it is **not** ready for an executor. Do not implement from this
> file; the design decision has not been made.
>
> Written 2026-10-17 at commit `1fa7800`. Found while reviewing
> `plans/044-activity-timeline-detail-modal.md`, which is the first change to
> route timeline card navigation through this code path.

## Status

- **Priority**: P2 (P1 once any surface auto-executes a user-supplied id — see "Why this matters")
- **Effort**: not estimated (design undecided)
- **Risk**: not assessed (design undecided)
- **Depends on**: none
- **Category**: bug (input validation is literal-blind)
- **Planned at**: commit `1fa7800`, 2026-10-17
- **Issue**: —

## The problem

`validate_read_only_query()` in `src/app/api/graph/v1/query.py:38-83` guards
every raw Cypher execution against write operations. It works by:

1. uppercasing the **entire** query string (`' '.join(query.upper().split())`, `:60`), then
2. regex-matching each entry of `WRITE_KEYWORDS` against it with `\b` word
   boundaries (`:63-74`).

`WRITE_KEYWORDS` (`:31-35`) is:

```python
WRITE_KEYWORDS = [
    'CREATE', 'MERGE', 'DELETE', 'DETACH', 'SET',
    'REMOVE', 'DROP', 'FOREACH',
    'APOC.CYPHER.DOIT', 'APOC.CYPHER.RUN', 'APOC.PERIODIC.ITERATE'
]
```

Because the scan is over the **whole string** rather than the parsed statement,
it also matches inside string literals — including entity ids that are
interpolated into the query. `-` is a non-word character, so a hyphen-delimited
token inside an id matches `\bCREATE\b` exactly as a real `CREATE` clause would.

The consequence: **a read-only query is rejected as a write operation when an
entity id happens to contain one of those words as a hyphen-delimited token.**

## Measured evidence

All of the following were run on 2026-10-17 against the live local stack
(`POST /api/v1/graph/execute`, `NEO4J_ENABLED=true`, 456 nodes), using the exact
query shape the timeline deep link builds:

```cypher
MATCH (a:<Type> {id: '<wba_id>'}) OPTIONAL MATCH (a)-[r]-(b) RETURN a, r, b LIMIT 50
```

| id interpolated into the query | result |
|---|---|
| `github::Repository::shuvabrata/work-behavior-analytics-ai` | ✅ `ok`, nodes=20 |
| `github::Repository::facebook/create-react-app` | ❌ **HTTP 400** — `Contains write operation 'CREATE'` |
| `github::Repository::acme/merge-queue` | ❌ **HTTP 400** — `'MERGE'` |
| `github::Repository::acme/delete-old-files` | ❌ **HTTP 400** — `'DELETE'` |
| `github::Repository::acme/drop-table` | ❌ **HTTP 400** — `'DROP'` |
| `github::Repository::acme/setup-scripts` | ✅ `ok` — `setup` does not match `\bSET\b` |

The validator was also exercised directly (no HTTP), confirming the failure is
in the validator and not in Neo4j:

```python
validate_read_only_query(
    "MATCH (a:Repository {id: 'github::Repository::facebook/create-react-app'})"
    "-[r]-(b:Person {id: 'x'}) RETURN a, r, b LIMIT 50"
)  # -> False, logged: "Contains write operation 'CREATE'"
```

The regex is case-insensitive by construction (the query is uppercased first),
so the id's own casing is irrelevant.

## Why this matters

The affected id shapes are **ordinary**, not adversarial:

- **Repository names.** `create-react-app`, `merge-queue`, `delete-old-files`,
  `drop-table`, `setup-scripts`, `remove-unused`, `foreach-batch` are all normal
  names in a real GitHub org.
- **Git branch names.** Git refs may contain a single quote, which breaks the
  interpolated string literal outright — measured:
  `github::Branch::acme/repo::feat/it's-here` → **HTTP 400**,
  `Cypher syntax error` (a *different* failure mode from the keyword match, but
  the same root cause: the id is interpolated, not parameterised).
- Any id containing a `::`-delimited or `/`-delimited segment equal to one of
  the ten keywords.

## Affected surfaces

| Surface | How the id reaches the validator | Status |
|---|---|---|
| **Activity Timeline card → Graph deep link** (`plans/044-…` Phase 5c) | `graph_deep_link()` interpolates the id into Cypher and ships it as `/app/graph?cypher=…`; the Graph page pre-fills it into the Console and auto-executes (`graph/callbacks/right_panel.py:100-105` → `graph/callbacks/query.py:118,189`). | **Newly introduced by 044.** Today the card is `href="/app/graph"` with no query and cannot fail. |
| **Search page "View in Graph" / person-activity buttons** (`pages/search.py:273-279`, `:349`, `:458`) | `_build_node_cypher()` builds the same interpolated shape from a `wba_id` and ships it as `?cypher=`. | **Pre-existing.** Same exposure today. |
| `POST /api/v1/graph/execute` generally | Any caller passing a raw query with an id inlined. | Pre-existing. |

The Timeline properties fetch in `plans/044-…` is **not** affected: it uses a
parameterised `MATCH (n) WHERE n.id IN $ids` (`_NODE_PROPERTIES_CYPHER`), so the
id never enters the query text. The asymmetry — one path parameterised, one
interpolated — is what makes this easy to miss in review.

## Not yet decided

The following are **open questions**, not recommendations. The point of this
document is that the choice has not been made.

1. **Where to fix it.** Candidates that have been observed to exist, with the
   trade-offs that make the choice non-obvious:
   - `validate_read_only_query` itself (`api/graph/v1/query.py`) — the root
     cause, but it is shared by every raw-Cypher caller, and any loosening
     weakens a security control. A stricter-than-needed guard is arguably the
     safe default.
   - The deep-link builders (`graph_deep_link`, `_build_node_cypher`) — narrowly
     scoped to the two affected surfaces, but leaves the underlying validator
     literal-blind for the next caller.
   - The Graph page's Console auto-execute path — would change behaviour for
     hand-typed queries too.

2. **What "correct" means for the validator.** Options range from "parse the
   statement and ignore string literals" (correct, but needs a real parser or
   careful tokenisation) to "keep the current conservative scan and route around
   it at the call sites" (no security change). The current behaviour is a
   deliberate over-approximation; whether to trade that for precision is the
   actual decision.

3. **Whether the deep link should parameterise instead.** The Console tab
   currently carries a query *string* through a URL, so there is no parameter
   channel. Making the deep link parameterised may be a larger change than the
   validator fix, or it may be the cleaner one — not yet investigated.

4. **Whether the quote-in-id case belongs to this problem or a separate one.**
   It is a distinct failure (Cypher syntax error, not a keyword false-positive)
   with the same root cause. It may warrant its own plan or be folded in here.

5. **Whether `search.py`'s two call sites should be fixed in the same change.**
   They share the root cause but are a different surface with their own tests.

## Explicitly out of scope for this document

- Any implementation, patch, or migration.
- Any change to `WRITE_KEYWORDS`, `validate_read_only_query`, the Graph page,
  or the Search page. Nothing here authorises an edit to source.

## Maintenance notes

- The reviewer checklist in `plans/044-activity-timeline-detail-modal.md`
  (~line 1822) asserts "the properties fetch is exactly one HTTP call per click"
  and does not mention this validator. If 044 lands unchanged, its "Open in
  Graph" link inherits this defect for any id matching the table above.
- `WRITE_KEYWORDS` and `READ_ONLY_KEYWORDS` live at
  `src/app/api/graph/v1/query.py:24-35`; the validation function is directly
  below at `:38`. Any change here affects every raw-Cypher execution in the app,
  including the Catalog Editor's Quick Test.
- The `id`-interpolated query shapes are built in exactly two places today:
  `app/dash_app/pages/timeline/helpers.py::graph_deep_link` (added by 044) and
  `app/dash_app/pages/search.py::_build_node_cypher`. Both should be re-checked
  if the validator's behaviour changes.

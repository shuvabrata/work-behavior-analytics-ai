# Plan 043: Activity Timeline — make event cards read as a sentence

> **Executor instructions**: Follow this plan step by step. Do not commit, push, or
> open a PR — leave changes in the working tree and report them. Run the `Verify`
> commands as you go; they are the acceptance check for each step.
>
> **Drift check (run first)** — check **both** committed and uncommitted drift. A
> commit-range diff alone cannot see uncommitted work, and on a clean tree at
> `90c9674` it returns nothing:
> ```
> git diff --stat 90c9674..HEAD -- <in-scope paths>   # committed drift
> git status --short -- <in-scope paths>              # uncommitted drift
> ```
> where `<in-scope paths>` is the `## Scope` table's file list, plus the two
> read-only files that render or exercise the changed code (changes there matter
> even though you will not edit them):
> ```
> src/app/api/activity/v1/ src/app/db/models/activity_action.py \
>   src/app/db/models/activity_event.py src/app/alembic/versions/ \
>   src/connectors/consumers/activity_writer.py \
>   src/app/dash_app/pages/timeline/ \
>   src/app/dash_app/assets/executive-dashboard.css \
>   tests/test_activity_api_integration.py \
>   tests/test_activity_api_unit.py \
>   tests/test_activity_person_identity.py \
>   tests/test_activity_timeline_ui_helpers.py \
>   tests/test_activity_timeline_edge_cases.py \
>   docs/design/activity-timeline-design.md
> ```
> If either command reports changes, re-read those files before proceeding. Line
> numbers below are approximate — **locate every symbol by content**, and confirm
> each "Current state" excerpt against the live code before editing.
>
> **Note on the base commit**: `90c9674` is "Activity Timeline — resolve a Person
> lane across all identity mappings (#338)" — the Person-identity lane expansion,
> which touched the same API files this plan changes. It is **merged**, its new
> file (`src/app/api/activity/v1/identity.py`) is committed, and the working tree
> is clean. So there is **no pending work in flight** on these files: the excerpts
> below were taken from that merged state and **do** match the live code. A
> mismatch therefore means genuine drift, not staleness — treat it as a STOP
> condition, do not assume the plan is out of date.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: MEDIUM (adds one nullable column + a read-time subquery; UI restructure)
- **Depends on**: none
- **Category**: UX defect (cards do not read as a sentence)
- **Design decision**: relationship-first card, neutral relation label, object
  name resolved at read time from `activity_events.display_name`.
- **Planned at**: commit `90c9674`, 2026-10-16

## Why this matters

Selecting a person and reading their timeline gives cards that do not form a
natural reading pattern. Today a card is:

```
line 1   Title of an Epic
line 2   Epic · Mentions                              09:14
```

The user wants the card to read as:

> **Shuva Brata Deb** has a *Mentions* relationship to the **Epic** titled
> "Title of an Epic", noted at 09:14.

Three separate causes:

1. **Wrong line order.** The object title (`summary`) occupies the prominent
   line 1 and the action is buried in a muted line 2. With many cards stacked,
   the scan axis should be the **action**, not the title.
2. **Wrong source field.** `activity_actions.summary` is built from the **actor's**
   `title / summary / key` (`activity_writer.py`, `_decompose_relationships` →
   `attrs.get("title") or attrs.get("summary") or attrs.get("key")`). The card
   needs the **other side's** name. Today it is only accidentally right — when the
   lane entity happens to be the relationship's *target*.
3. **The name-picker misses two entity types.** Even the object's *own*
   pre-computed name is an unusable id for commits and people — see "Cause 3"
   below. Without fixing this, the new line 2 renders a 40-character SHA on the
   highest-volume cards in the store.

Verified failure modes (run against live code):

| Case | Lane role | `summary` (line 1 today) | Other side's name |
|---|---|---|---|
| A — Epic `MENTIONS` Shuva | lane = **target** | `"Title of an Epic"` — the other side ✅ | present |
| B — Shuva `COLLABORATOR` Repository | lane = **actor** | `"Shuva Brata Deb"` — the lane's *own* name ❌ | **not stored** |

In Case B `summary` is not merely wrong, it is often `NULL`: it is built from
`title/summary/key`, while a `PersonAttributes` payload carries `name`/`full_name`
and **no** `title`/`summary`/`key`. So Person-actor cards cannot name their object
from `summary` at all.

### Cause 3 — the name-picker misses two entity types

Measured against the live store:

```
84 distinct cards; 45 show a human object name, 33 resolve to a raw id,
6 have no activity_events row
```

**Root cause (verified):** `_compute_display_name` searches
`name / title / summary / key`. Two attribute models — and only two — store their
human name under a *different* word:

| Entity | Its name lives in | Has any of the four? | `display_name` becomes |
|---|---|---|---|
| `CommitAttributes` | `message` | **no** | the 40-char SHA |
| `PersonAttributes` | `full_name`, `login` | **no** | the provider account id |

The other **12** entity types each happen to define one of the four words
(`PageAttributes.title`, `IssueAttributes.summary/key`, `RepositoryAttributes.name`,
…), which is why a `Page · October 2026` card renders correctly and a commit card
does not. It is not a Page special case — Page simply uses a word the picker knows.

**The one change that fixes both** — extend the lookup, in the single function
that defines it:

```python
for field in ("name", "title", "summary", "key", "full_name", "message"):
```

Safe because it is **purely additive**: only two attribute models define
`full_name` / `message`, and **neither defines any of the four existing words**, so
a new field can never shadow an existing name. Reordering is not required.

**Cards recovered** (the two highest-volume rows in the store):

| Card | Today | After |
|---|---|---|
| `github · PullRequest [actor] INCLUDES -> Commit` (213×) | `Commit · 528be7629e25674ca…` | `Commit · <commit message>` |
| `github · File [actor] MODIFIES -> Commit` (196×) | `Commit · 90c96746132bd827…` | `Commit · <commit message>` |
| `jira · Issue [actor] REPORTED_BY -> Person` (14×) | `Person · 557058:6210…` | `Person · <full name>` |

**Deliberately out of scope:** the remaining 6 cards fall back to an *already
readable* id (`Commit REFERENCES -> Issue` → `UI-2`, `PullRequest TARGETS ->
Branch` → `work-behavior-analytics-ai::main`). Those are not defects. Also out of
scope: `GraphNode.display_name()` in `src/connectors/neo4j_db/node_base.py:58`
holds the **same** four-word lookup with the same commit gap (so the Graph page
shows SHAs too) — same defect, different feature surface; noted in §10 instead.

**Delivery window:** `display_name` is stamped at write time, so this fixes
**newly ingested signals only**. Existing rows keep their ids — accepted, and no
backfill is added.

## Current state

**Card build** — `src/app/dash_app/pages/timeline/layout.py`, `build_event_card`:

```python
summary = card_summary(event)
relationship = humanize_relationship(str(event.get("relationship_type") or ""))
type_label = entity_type_label(str(event.get("entity_type") or ""))
time_text = _format_event_time(event.get("event_time"))
...
return html.A(
    [
        html.Div(summary, className="timeline-card-summary", title=summary),
        html.Div(meta, className="timeline-card-meta"),
    ],
    href="/app/graph", target="_blank", rel="noopener noreferrer",
    className="timeline-card", style=card_style, title=summary, **payload,
)
```

`meta` is `<Type(colored)> · <relationship> · <time>`; the time is pinned right by
`margin-left: auto` on `.timeline-card-time`.

**Line-1 fallback** — `helpers.py`, `card_summary`, used by *both* the card and
`popup_fields` (for the hover popup's headline).

**API event shape** — `src/app/api/activity/v1/model.py`, `TimelineEvent` has
`signal_id, event_time, relationship_type, summary, entity_type, source, url,
details`. It carries **no** indication of which side the lane entity was on, and
**no** id for the other side. Both are discarded in
`service.py::_action_to_event`, which keeps only
`other_type = target_entity_type | actor_entity_type`.

**Storage** — `activity_actions` has `actor_entity_type/id`,
`target_entity_type/id`, `relationship_type`, `summary`, `url`. It does **not**
store the target's own `source` — even though `RelationshipTarget` carries one
(`github Issue REFERENCES → jira Issue` is the live cross-source case).

**Not scope-aware** — `build_event_card` / `build_cell` / `build_grid_body` never
receive `scope`. `render_grid` (`callbacks.py`) *does* have it, in
`data["params"]["scope"]`.

## Decisions (agreed during planning)

| # | Decision | Rationale |
|---|----------|-----------|
| 1 | **Elide the subject.** The card is a fragment; the sticky lane header supplies the "who". | The lane header is sticky-top and always visible. Repeating the name per card truncates the object title at 220px and pushes the card past `min-height: 40px`. |
| 2 | **Relationship on line 1**, `Type · <object name>` + time on line 2. | The action is the scan axis when many cards stack; it forms a clean left-edge column. |
| 3 | **Verbatim relation label** — `humanize_relationship` unchanged. No inverse map, no `_BY` stripping, no per-relation specialization. | Not scalable, and `direction` is unusable (see Risks). The label reads as a neutral connector, matching the requested "has a *Mentions* relationship to". |
| 4 | **Scope-aware card, same 2-line shape.** History inverts: line 1 = `Type · <lane name>`, line 2 = `Updated` + time. | In history the lane *is* the subject; the varying thing is the state. Keeping one shape/height preserves the grid. |
| 5 | **Additive API fields**: `lane_role`, `related_id`, `related_name`. | The UI cannot recover which side the lane was on. Defaults keep the response backward-compatible. |
| 6 | **Resolve the object's name at read time** from `activity_events.display_name`. | The name is often unavailable at write time (the target's own signal may arrive later), and there is no backfill. `display_name` is pre-computed, in the same Postgres DB, and index-backed. |
| 7 | **One nullable column `target_source`**; the lane-aware resolve branches on the existing actor predicate. | `COALESCE(target_source, source)` alone is wrong when the lane is the target (the other side is then the *actor*, whose source is the signal's). |
| 8 | **No backfill.** `COALESCE` covers history. | Matches the repo's stated no-backfill stance. Every same-source row resolves immediately; only pre-existing cross-source `REFERENCES` rows keep a raw id. |
| 9 | **No `ActivitySignal` change** → no spec regeneration. | Only *readers* change; `rel.target.source` is already emitted by producers. |
| 10 | **Hover popup, tooltip, `aria-label` and click behaviour are OUT OF SCOPE.** | Explicit user decision. `popup_fields` output and the card's `href`/`target`/`title`/`title=` attributes stay byte-identical. |
| 11 | **Retire `card_summary`**; add `card_primary` + `card_secondary`. | The name "summary" would otherwise denote a relationship string. |
| 12 | **Extend `_compute_display_name` with `full_name` + `message`, clamped to 512 chars.** | Commits and people have no `name/title/summary/key`, so their stored `display_name` is a raw id — the new line 2 would show a SHA on the store's two highest-volume cards. The clamp is mandatory: the column is `VARCHAR(512)` while `message` is allowed up to 2000, and an over-long value makes the writer drop the whole signal (measured: 10/195 commit rows). Purely additive otherwise; no backfill (write-time only, new signals only). |

## Commands you will need

Activate the virtualenv first (`source .venv/bin/activate`). Code lives in `src/`
but is imported as top-level packages, so `PYTHONPATH=src` is required for anything
that imports app code (`pytest.ini` sets it for tests).

| Purpose | Command | Expected on success |
|---|---|---|
| Typecheck | `mypy src/` | exit 0, no errors (strict mode) |
| Lint | `pylint src --score=y` | exit 0, score **≥ 9.0** |
| Tests (the gate) | `pytest -m unit tests -q` | all pass |
| One module | `pytest -m unit tests/test_activity_api_integration.py -q` | all pass |
| Migration | `cd src/app && alembic upgrade head` | exit 0 |
| Migration round-trip | `cd src/app && alembic downgrade -1 && alembic upgrade head` | exit 0 both ways |
| Security scan | `bandit -c .bandit.yml -r src/ -lll` | no High severity |
| Spec freshness | `PYTHONPATH=src python scripts/generate_signal_activity_spec.py && git diff --stat docs/design/spec-activity-signal.md` | **no diff** |

## Scope

**In scope** — the only files this plan may modify:

| File | What changes | Phase |
|---|---|---|
| `src/connectors/consumers/activity_writer.py` | name-picker gains two fields + 512 clamp; action row carries `target_source` | 1, 2 |
| `src/app/db/models/activity_action.py` | new nullable `target_source` column | 2 |
| `src/app/db/models/activity_event.py` | **comment only** on `display_name` — no column change | 1 |
| `src/app/alembic/versions/<new>.py` | create — one additive `ADD COLUMN` | 2 |
| `src/app/api/activity/v1/model.py` | three additive `TimelineEvent` fields | 3 |
| `src/app/api/activity/v1/query.py` | lane-aware resolve subquery + new return shape | 3 |
| `src/app/api/activity/v1/service.py` | populate the new fields; unpack the tuple return | 3 |
| `src/app/api/activity/v1/mock_data.py` | **no change required** — see Phase 3d | — |
| `src/app/dash_app/pages/timeline/helpers.py` | `card_primary` / `card_secondary`; retire `card_summary` | 4 |
| `src/app/dash_app/pages/timeline/layout.py` | two-line card; thread `scope` | 5 |
| `src/app/dash_app/pages/timeline/callbacks.py` | read `scope` from the stored payload | 5 |
| `src/app/dash_app/assets/executive-dashboard.css` | card class rename + flex ellipsis | 5 |
| `tests/test_activity_timeline_ui_helpers.py` | rewrite the `card_summary` test | 6 |
| `tests/test_activity_api_integration.py` | fake session + new assertions | 6 |
| `tests/test_activity_api_unit.py` | **check only** — do NOT add the clamp test here; its home is the new writer file below | — |
| `tests/test_activity_writer_display_name.py` | **create** — the `_compute_display_name` clamp + `full_name`/`message` tests | 6 |
| `tests/test_activity_person_identity.py` | 3 `_action_to_event` call sites + 2 SQL-count assertions | 6 |
| `tests/test_activity_timeline_edge_cases.py` | one assertion made substring-tolerant | 6 |
| `docs/design/activity-timeline-design.md` | §4.2, §3.2, §5.1, §5.3, §7.4, §10, §11 | 1, 6 |

**Out of scope** — see `## Out of scope (explicit)` below; do NOT touch the
Neo4j graph node layer, the producers, `src/common/activity_signal/`, or any file
not listed above.

## Git workflow

- **Do not commit, push, or open a PR.** This repo's rule (CLAUDE.md) is that
  changes are left in the working tree for the operator to review. No branch
  creation either — work on the current branch.
- If the operator explicitly dispatches you in an isolated worktree, follow that
  instruction instead; it overrides this section.
- Do not run `git stash`, `git checkout`, `git reset`, or `git clean`. The tree
  is clean at `89a0ec5`, but the operator works directly on this branch (the
  plan and the README index all landed in that commit), so
  leave their commits — and any uncommitted work they add later — alone. A
  destructive git command would discard it.

## Implementation

### Phase 1 — Writer: make the name-picker cover commits and people

Do this **first**: it is the change that makes newly ingested data readable, so
everything verified in later phases sees clean names.

**1a.** `src/connectors/consumers/activity_writer.py`, `_compute_display_name`
(the single definition — one caller, `_write_signal`). Extend the tuple, add the
**length clamp**, and update the docstring, which currently names only four fields:

```python
# ``activity_events.display_name`` is VARCHAR(512). A blank is not an option:
# the writer's INSERT would fail and the whole signal would be dropped.
_DISPLAY_NAME_MAX = 512


def _compute_display_name(signal: ActivitySignal) -> str:
    """Return the human-readable name for a signal's entity.

    Covers the two entity types whose name field the graph-side rule misses:
    ``CommitAttributes.message`` and ``PersonAttributes.full_name``.  Without
    those, a commit's name is its 40-character SHA and a person's is their
    provider account id.

    Tries ``name``, ``title``, ``summary``, ``key``, then ``full_name`` and
    ``message``, and falls back to the raw entity ``id``.  The result is clamped
    to ``_DISPLAY_NAME_MAX`` because ``activity_events.display_name`` is
    ``VARCHAR(512)`` while producers allow a commit message up to 2000
    characters — an over-long value makes the INSERT raise, and the writer
    catches that and skips the entire signal (event row *and* action rows).
    """
    attrs = signal.attributes.model_dump()
    for field in ("name", "title", "summary", "key", "full_name", "message"):
        value = attrs.get(field)
        if value and isinstance(value, str):
            return value[:_DISPLAY_NAME_MAX]
    return signal.id
```

> **Do not skip the clamp.** This is not defensive hygiene — it is a measured
> data-loss bug otherwise. `producers/github/constants.py:8` sets
> `_TEXT_MAX = 2000`, and `build_commit_signal.py:60` truncates a commit message
> to that, so a message of 513–2000 characters reaches this function intact.
> Measured in the local store: **10 of 195** `Commit` rows have a message over
> 512 characters, the longest exactly 2000. Without the clamp, changing the
> INSERT to carry `message` as `display_name` fails for those signals, and
> `activity_writer.py:245-247` swallows the error and drops the signal — losing
> the commit's own card *and* its action rows (e.g. `PullRequest INCLUDES ->
> Commit`, 213×). A card ellipsises at ~26 characters, so 512 is ample for display.

The two new fields are **appended**, never reordered — only
`PersonAttributes`/`CommitAttributes` define them and neither defines any of the
original four, so no existing name can be shadowed. There is **no second
implementation** to update (verified: `_compute_display_name` is defined once and
called once).

Add a **unit test for the clamp** in a **new file**,
`tests/test_activity_writer_display_name.py` (start it with
`pytestmark = pytest.mark.unit`, and import
`from connectors.consumers.activity_writer import _compute_display_name`). There
is **no existing writer test to mirror** — nothing under `tests/` imports
`activity_writer` today — and the file belongs beside the consumer code, not in
`tests/test_activity_api_unit.py` (whose docstring scopes it to the pure
functions in `app/api/activity/v1/service.py`, and which imports no connector
module). A signal whose commit message exceeds 512 characters must yield a
`display_name` of exactly 512 characters, never longer, and never raise.

**1b.** `docs/design/activity-timeline-design.md` §4.2 step 2 — the doc currently
says "first non-empty of `attributes.name` / `title` / `summary` / `key`". Rewrite
it to list all six fields and state *why* the last two exist (commits and people).
Do **not** describe it as "mirrors `GraphNode.display_name()`" any more — it no
longer does, and the `## Out of scope` section records the divergence.

**1c.** `src/app/db/models/activity_event.py` line 51 — a **code comment** carries
the same now-false claim as the doc:

```python
    # Computed at write time — mirrors GraphNode.display_name(); see activity_writer.py.
    display_name: Mapped[str | None] = mapped_column(String(512), nullable=True)
```

Rewrite the comment only; **do not touch the column definition** (the type,
nullability, and the 512 length are all load-bearing — the length is what the
Phase 1a clamp exists to respect). State the truth: the writer covers commits and
people via `full_name` / `message`, the graph-side rule does not, and the two
deliberately differ:

```python
    # Computed at write time by activity_writer._compute_display_name, which covers
    # commits (message) and people (full_name) that GraphNode.display_name() misses.
    # Clamped to this column's width there — keep the 512 in sync with that clamp.
    display_name: Mapped[str | None] = mapped_column(String(512), nullable=True)
```

This matters because the comment is the thing most likely to make a future reader
"re-sync" the two implementations — which would reintroduce the commit-gap bug on
one side.

**Verify**
```
mypy src/
pytest -m unit tests -q
```
Then confirm the behaviour directly — with the consumer running, re-scan a repo so
fresh signals land, and check the stored value: `INCLUDES -> Commit` should now
read a commit message instead of `528be7629e…`. (Rows written before this change
still show the SHA — that is the accepted no-backfill behaviour, not a failure.)

### Phase 2 — Storage: carry the target's own source

**2a.** `src/app/db/models/activity_action.py` — add a nullable column beside
`target_entity_id`:

```python
target_source: Mapped[str | None] = mapped_column(String(32), nullable=True)
```

**2b.** New Alembic migration. Head is currently `e636212b35b4`:

```
cd src/app && alembic revision -m "add activity_actions target_source"   # then edit, or hand-write
```

Set `down_revision = "e636212b35b4"` and make the body a single additive ALTER —
**no data migration**:

```python
def upgrade() -> None:
    op.add_column(
        "activity_actions",
        sa.Column("target_source", sa.String(length=32), nullable=True),
    )

def downgrade() -> None:
    op.drop_column("activity_actions", "target_source")
```

**2c.** `src/connectors/consumers/activity_writer.py` — in
`_decompose_relationships`, add the key to the row dict:

```python
"target_source": rel.target.source or signal.source,
```

and extend the `INSERT INTO activity_actions (...)` column list plus the tuple in
the `conn.executemany` list comprehension with `target_source`.

**Verify**
```
mypy src/
docker compose up -d postgres                       # prerequisite for the next line
cd src/app && alembic upgrade head                  # → exit 0
cd src/app && alembic downgrade -1 && alembic upgrade head   # → exit 0 both ways
pytest -m unit tests/test_activity_api_unit.py -q   # → all pass
```
Expected: every command exits 0; `cd src/app && alembic current` afterwards names
the **new** revision (not `e636212b35b4`). If `alembic upgrade head` fails with a
multiple-heads error, stop — see `## STOP conditions`.

The ALTER is additive and nullable, so existing rows keep working and existing
INSERTs without the column would too — the writer change is what starts populating it.

### Phase 3 — API: expose the other side and resolve its name

**3a.** `src/app/api/activity/v1/model.py` — add three fields to `TimelineEvent`:

```python
lane_role: Literal["actor", "target"] | None = Field(
    default=None,
    description=(
        "Which side of the relationship the lane entity was on. None for "
        "scope=history, where the lane entity is the subject itself."
    ),
)
related_id: str | None = Field(
    default=None, description="Entity id of the *other* side, when known."
)
related_name: str | None = Field(
    default=None,
    description=(
        "Resolved display name of the *other* side, read from "
        "activity_events.display_name. None when the other side has no "
        "timeline row yet — the UI falls back to related_id, then summary."
    ),
)
```

Defaults keep old responses valid. `Literal` is already imported in this module.

**3b.** `src/app/api/activity/v1/query.py` — `fetch_actions_for_entity` gains a
lane-aware scalar subquery. It **must not** multiply rows: `activity_events` holds
many rows per entity (one per distinct state), so a plain join would inflate the
lane and corrupt pagination. Return shape changes from `list[ActivityAction]` to
`list[tuple[ActivityAction, str | None]]`.

The `actor_match` predicate already exists in this function — reuse it to express
`lane_role` in SQL, so the subquery targets the correct side:

```python
related_source = case(
    (actor_match, func.coalesce(ActivityAction.target_source, ActivityAction.source)),
    else_=ActivityAction.source,
)
related_type = case(
    (actor_match, ActivityAction.target_entity_type),
    else_=ActivityAction.actor_entity_type,
)
related_id = case(
    (actor_match, ActivityAction.target_entity_id),
    else_=ActivityAction.actor_entity_id,
)

related_name_subq = (
    select(ActivityEvent.display_name)
    .where(
        ActivityEvent.source == related_source,
        ActivityEvent.entity_type == related_type,
        ActivityEvent.entity_id == related_id,
        ActivityEvent.display_name.is_not(None),
    )
    .order_by(ActivityEvent.event_time.desc())
    .limit(1)
    .scalar_subquery()
)

stmt = select(ActivityAction, related_name_subq.label("related_name"))
```

Then the statement, filters, ordering and **the return line**:

```python
from sqlalchemy import and_, case, func, or_, select, tuple_  # add case, func

stmt = select(ActivityAction, related_name_subq.label("related_name")).where(
    or_(actor_match, target_match)
)
# --- unchanged from here ---
if from_time is not None:
    stmt = stmt.where(ActivityAction.event_time >= from_time)
if to_time is not None:
    stmt = stmt.where(ActivityAction.event_time <= to_time)
if cursor_time is not None and cursor_id is not None:
    stmt = stmt.where(
        tuple_(ActivityAction.event_time, ActivityAction.id)
        < (cursor_time, cursor_id)
    )
stmt = stmt.order_by(
    ActivityAction.event_time.desc(), ActivityAction.id.desc()
).limit(limit)

result = await db.execute(stmt)
# NOT .scalars() — it returns only the FIRST column of each row, which silently
# drops related_name and degrades every card to a raw id with green tests.
return [(action, name) for action, name in result.all()]
```

Three things this step must get right, all of which are easy to get wrong:

1. **Add `case` and `func` to the `sqlalchemy` import.** The current line is
   `from sqlalchemy import and_, or_, select, tuple_` — the snippet above does not
   compile without the addition.
2. **Replace the return line.** `fetch_actions_for_entity` currently ends with
   `result = await db.execute(stmt)` / `return list(result.scalars().all())`.
   Leaving that in place is a **silent** failure: `related_name` is an optional
   field, so nothing raises — every card just falls back to the raw id and the
   whole feature quietly does nothing. (Verified against the installed
   SQLAlchemy: for a two-column select, `.scalars().all()` yields only the first
   column.)
3. **Signature becomes `list[tuple[ActivityAction, str | None]]`.** This repo runs
   `strict = True` with `warn_return_any = True`, so a `row[0]`-style access that
   types as `Any` will fail `mypy src/`. Use the unpacking form above. If mypy
   still objects, use an explicit `cast(...)` — **never** fall back to
   `.scalars()`. Do not use `Result.tuples()`; it is deprecated in the installed
   SQLAlchemy 2.1.

`ActivityEvent` is already imported here (`fetch_display_label` uses it).

> **This step breaks two tests you have not been told about yet — do not stop.**
> `tests/test_activity_person_identity.py` asserts on this function's compiled
> SQL (`TestActionsPredicate`) and calls `_action_to_event` directly
> (`TestActionToEvent`). Both are repaired in **Phase 6e**, which is where the
> file enters Scope. Finish Phase 3 as written, then go to 6e — the intermediate
> red state between here and there is expected. Do **not** restore `.scalars()`,
> weaken the subquery, or reach for `xfail` to get back to green.

> **Only one of the two identical lines changes.** `return list(result.scalars().all())`
> appears **twice** in this file: line 83 inside `fetch_actions_for_entity`
> (change it) and line 127 inside `fetch_event_history` (**leave it** — that
> select is single-column, `ActivityEvent`, so `.scalars()` is correct there and
> changing it breaks `scope=history`).

> **Caution**: verify SQLAlchemy correlates the subquery against the outer
> `ActivityAction` rather than emitting a cartesian join — compile the statement
> once against the postgres dialect and confirm `activity_events` appears only
> inside the `SELECT` sub-clause, never as a second top-level `FROM`. Then confirm
> the returned row count for a lane equals the row count *without* the subquery.
> This is the single riskiest step.

**3c.** `src/app/api/activity/v1/service.py`:

- `_build_event` — accept `lane_role`, `related_id`, `related_name` and pass them
  to `TimelineEvent`.
- `_action_to_event` — take the `(action, related_name)` pair, determine the role
  from the existing condition, and set:

  Insert `related_name` as the **second positional** parameter, keeping the
  existing `*` keyword-only marker for the rest (match the current shape so the
  call site in the previous bullet works as written):

```python
def _action_to_event(
    action: ActivityAction,
    related_name: str | None,
    *,
    lane_entity_type: str,
    lane_identity_ids: frozenset[str],
) -> TimelineEvent:
```

  Then, inside it:

```python
is_actor = (
    action.actor_entity_type == lane_entity_type
    and action.actor_entity_id in lane_identity_ids
)
lane_role = "actor" if is_actor else "target"
related_id = action.target_entity_id if is_actor else action.actor_entity_id
```

  (`other_type` keeps its current meaning — it is already the other side's type,
  so line 2's type and `related_id` stay consistent.)
- `_event_to_event` (history) — set `lane_role=None`, `related_id=None`,
  `related_name=None`.
- `_fetch_lane` — **two** consumers must be updated for the new tuple shape, not
  one. The call site itself is unchanged; unpacking is not optional:

```python
        action_rows = await query.fetch_actions_for_entity(...)   # unchanged call
        events = [
            _action_to_event(
                action,
                related_name,
                lane_entity_type=entity_type,
                lane_identity_ids=frozenset(eid for _, eid in identities),
            )
            for action, related_name in action_rows
        ]
        # [0] is required: last_row feeds _encode_cursor(last_row.event_time,
        # last_row.id) below, and a tuple has neither attribute — leaving it
        # un-unpacked raises AttributeError on every full page, breaking
        # "Load more events".
        last_row = action_rows[-1][0] if action_rows else None
```

  The existing `last_row: ActivityEvent | ActivityAction | None` annotation stays
  valid — it now holds the unwrapped ORM row. Nothing else in `_fetch_lane`
  changes; the `next_cursor` / `_encode_cursor` block below is untouched.

**3d.** `src/app/api/activity/v1/mock_data.py` — **no change required.** The new
`TimelineEvent` fields all default to `None`, and `card_secondary`'s fallback
chain lands on `summary`, which every mock spec already populates (default
`"Mock activity"`; history sets the lane label). So mock cards render the new
two-line layout correctly as-is — e.g. `Created` / `PullRequest · Mock activity` —
and the existing `card_variety` spec that sets `summary=None` now exercises the
type-only fallback for free.

Do **not** add `related_id` / `related_name` / `lane_role` to `_Spec`. It has no
fields for them, and the mock's real value is the *geometric* edge cases it
invents (30-day gaps, 100-event spikes, cell overflow, empty lanes, pagination
traps, XSS strings) — none of which this change touches, because it alters card
*text*, not layout.

**Verify**
```
pytest -m unit tests -q                                  # → all pass
mypy src/                                                # → exit 0
pytest -m unit tests/test_activity_api_integration.py -q # → all pass, incl. the row-multiplication guard
```
The third command is the gate for the no-row-multiplication requirement: the
integration test asserts that a lane whose other side has several
`activity_events` rows still returns one event per action row. It runs with a
mocked DB, so it needs **no** running app, no Postgres and no mock mode.

> Optional manual check (not a gate): with the app running and mock mode enabled
> (`TIMELINE_MOCK_SCENARIO` set — see the timeline design doc §9), this prints the
> event count and the response keys for one lane:
> ```
> curl -s "http://localhost:8000/api/v1/activity/timeline?wba_ids=mock::Person::alice&mock=pagination&limit=5" \
>   | python -c "import json,sys; d=json.load(sys.stdin); print(len(d['lanes'][0]['events']), d['lanes'][0]['events'][0].keys())"
> ```
> Skip it if setting up the app is not possible — the test above already covers it.

### Phase 4 — UI helpers: the two lines

**4a.** `src/app/dash_app/pages/timeline/helpers.py`:

- **Retire `card_summary`.** Delete it and update its import in `layout.py`.
- **Add** `card_primary(event) -> str` — line 1:

```python
def card_primary(event: dict[str, Any]) -> str:
    """Return line 1: the humanized relationship, else the entity type."""
    relationship = humanize_relationship(str(event.get("relationship_type") or ""))
    if relationship:
        return relationship
    return entity_type_label(str(event.get("entity_type") or ""))
```

- **Add** `card_secondary(event) -> str` — **the object's name alone**, no type
  label and no separator (the layout renders `<colored Type> · <this>` and
  appends the time). Object name priority: `related_name` → `related_id` →
  `summary` → `""`:

```python
def card_secondary(event: dict[str, Any]) -> str:
    """Return the *other* side's display name, or ``""`` when unknown.

    Prefers the resolved ``related_name``, then the raw ``related_id``, then
    ``summary``.  Deliberately excludes the entity-type label: the layout
    renders that itself as a colour-coded span (see ``build_event_card``), so
    returning ``"<Type> · <name>"`` here would duplicate it.
    """
    for key in ("related_name", "related_id", "summary"):
        value = event.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""
```

- **`popup_fields` must keep its output byte-identical** (hover is out of scope).
  It currently calls `card_summary`. Replace that with a small private
  `_popup_headline(event)` carrying today's exact logic
  (`summary` → `"<Relationship> · <Type>"` → `"Event"`). Record in a comment that
  this intentionally duplicates a variant of the old `card_summary` and is to be
  consolidated by the later hover/popup plan.

**4b.** For **history** scope the layout calls the helpers differently (see 5a) —
`card_primary` supplies `"Updated"` naturally (it is
`humanize_relationship("STATE_CHANGE")`), and history's line 1 is built from the
lane label instead. Do **not** add a `STATE_CHANGE` special case to either helper.

**Verify**
```
pytest -m unit tests/test_activity_timeline_ui_helpers.py -q
mypy src/ && pylint src --score=y
```

### Phase 5 — UI layout: the card

**5a.** `src/app/dash_app/pages/timeline/layout.py`:

- `build_event_card(event, lane_color, type_color, *, scope="activity")` — two
  lines, both provided by the helpers:

| scope | line 1 | line 2 |
|---|---|---|
| `activity` | `card_primary(event)` (the relationship) | `<Type> · card_secondary(event)` + time |
| `history` | `<Type> · card_secondary(event)` (the lane's identity) | `card_primary(event)` + time |

  Use `card_primary(event)` for history's line 2 — it already yields `"Updated"`
  for `STATE_CHANGE` with no special-casing.

  **The line-2 DOM is load-bearing — build it exactly like this, do not collapse
  the two spans into one.** `card_secondary` returns the *name alone* (no type,
  no separator); the layout owns the type label because it also owns
  `type_color`:

```python
    body: list[Any] = [
        html.Span(type_label, className="timeline-card-type", style={"color": type_color}),
        html.Span("·", className="timeline-card-sep"),
        html.Span(card_secondary(event), className="timeline-card-name"),
    ]
    if time_text:
        body.append(html.Span(time_text, className="timeline-card-time"))
```

  `type_label` is already computed in this function today (it is the current
  `meta`'s first span) — reuse it; do not recompute it.
  **A single fused `Type · name` span is wrong here**: it leaves `type_color`
  unused (pylint `W0613`, `unused-argument`, which is *not* in `.pylintrc`'s
  disable list) and drops the per-entity colour from every card.

  Class names become `.timeline-card-primary` and `.timeline-card-secondary`.
  **Keep `title=`, `href`, `target`, `rel` and the `data-timeline-event` payload
  exactly as they are** (out of scope).

- `build_cell(...)` — accept `scope: str = "activity"` and pass it through to
  `build_event_card`. Note `build_cell` already carries
  `# pylint: disable=too-many-arguments` — if pylint's count check trips, extend
  that disable rather than restructuring.
- `build_grid_body(...)` — accept `scope: str = "activity"`, pass to every
  `build_cell` call (three call sites: the no-rows branch, the per-row loop, and
  the expanded-idle-run loop).
- `src/app/dash_app/pages/timeline/callbacks.py` — in `render_grid`, read
  `scope = str((data.get("params") or {}).get("scope") or "activity")` and pass it
  to `build_grid_body`. `render_grid`'s own `Input`/`Output` signature is
  unchanged (scope already lives in the stored `data`).

**5b.** `src/app/dash_app/assets/executive-dashboard.css` — replace the
`.timeline-card-summary` / `.timeline-card-meta` block:

```css
.timeline-card-primary {
    font-family: 'Inter', sans-serif;
    font-size: 14px;
    font-weight: var(--font-weight-medium);
    color: var(--color-charcoal-medium);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}

.timeline-card-secondary {
    display: flex;
    align-items: center;
    gap: 4px;
    margin-top: 2px;
    font-family: 'Inter', sans-serif;
    font-size: 12px;
    color: var(--color-gray-medium);
    white-space: nowrap;
    overflow: hidden;
}
```

The `.timeline-card-type` / `.timeline-card-sep` / `.timeline-card-time` rules
stay. The truncating element is the **name** span, not a `Type · name` half:

```css
.timeline-card-name {
    flex: 1 1 auto;
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
}
```

so the name ellipsises while `.timeline-card-time` keeps its existing
`margin-left: auto` pin. (`flex: 1 1 auto` on the type/sep spans would let the
type label itself be squeezed; only the name grows and shrinks.) Nothing else in
the `.timeline-card` block changes — `min-height: 40px`, `padding: 3px 7px`, the
3px lane-accent left border and the 2px radius all stay, so the per-cell height
budget (`MAX_CELL_CARDS = 3`) is unaffected.

**Verify — machine-checkable (this is the gate)**
```
pytest -m unit tests -q                                        # → all pass
```

**Verify — manual, operator-run (NOT a gate; do not block on it).** To see the
real page, mock mode makes the scenarios reproducible: set `TIMELINE_MOCK_SCENARIO=even`
in `.env`, then `docker compose up -d --force-recreate app`, and open
`/app/timeline` (design doc §9 has the full scenario catalog):
- `mock=even` — activity cards read `<action>` / `<Type> · <name>  HH:MM`.
- `mock=card_variety` — a long title ellipsises on line 2; the time stays right-aligned.
- `scope=history` (group by Day) — cards read `<Type> · <lane name>` / `Updated  HH:MM`.
- Cards still hover-popup, open `/app/graph` in a new tab, and hold 3-per-cell + "+N more".

If a browser or the app is unavailable, report that this step was not performed —
do not mark the phase failed, and do not improvise a substitute. The gate above is
what Phase 5 is judged on.

### Phase 6 — Tests and documentation

**6a.** `tests/test_activity_timeline_ui_helpers.py`:
- Rewrite `test_card_summary_fallback` as `test_card_primary` + `test_card_secondary`
  (drop the `card_summary` import; assert the `related_name → related_id → summary
  → type` priority and the relationship-vs-type fallback).
- Add a regression assertion that `"STATE_CHANGE"` yields `"Updated"` via
  `card_primary` (guards history's line 2 without a special case).
- Extend the `popup_fields` test to assert the headline is unchanged.

**6b.** `tests/test_activity_api_integration.py` — despite the name, this file is
marked `pytest.mark.unit` (line 35) and mocks the DB via a `get_async_db`
dependency override, so it runs in the `pytest -m unit` gate — the same gate as
Phase 3's verify step. **Update the fake DB session FIRST**, or every test in the
file fails with `AttributeError: 'FakeResult' object has no attribute 'all'`.

Three coordinated changes:

1. **`FakeResult` gains `all()`.** It currently exposes only `scalars()` and
   `first()`:

```python
class FakeResult:
    def all(self) -> list[Any]:
        return self._rows
```

2. **The actions branch must return `(action, related_name)` pairs.**
   `FakeSession.execute` currently ends with `return FakeResult(self.actions)` —
   a list of bare `ActivityAction` — but the service now unpacks
   `for action, related_name in action_rows`. Pair them in the fixture instead,
   e.g. store `[(action, related_name), ...]` and return that list from this
   branch. Leave the other two branches returning bare rows: the
   `display_name/avatar_url` label lookup and the `activity_events` history select
   both still use `.scalars()`.

3. **`_make_action` gains `target_source`** (the new column), and the canned set
   must include **one action with a real related name and one whose
   `related_name` is `None`**, so both the resolved-name path and the raw-id
   fallback stay pinned.

Then add the assertions:

- `lane_role == "target"` when the lane entity is the target, `"actor"` when it
  is the actor.
- `related_id` names the **other** side in both directions.
- A row-multiplication guard: a lane whose other side has **several**
  `activity_events` rows must still return one event per action row.

> **Do not "fix" a failing run by reverting `fetch_actions_for_entity` to
> `.scalars()`.** That makes these tests pass again while silently dropping
> `related_name` in production — `related_name` is optional, so nothing raises and
> the feature quietly degrades to today's raw-id behaviour. If the tests fail,
> the fix is in the fake, never in the return line.

**6c.** Update `docs/design/activity-timeline-design.md`:
- §4.2 — the `display_name` step now names **six** fields (`name / title /
  summary / key / full_name / message`), and the "mirrors `GraphNode.display_name()`"
  clause is **removed** (it is no longer true; see Out of scope). If Phase 1b
  already made this edit, confirm it rather than redoing it.
- §3.2 `activity_actions` table — add the `target_source` row.
- §5.1 `TimelineEvent` shape — add `lane_role`, `related_id`, `related_name`.
- §5.3 — the contract note "activity events carry no related-entity id" is now
  **superseded**; rewrite it to describe the resolved name and the `related_id`
  fallback, and record that the resolved name is only as good as the stored
  `display_name` (i.e. an id for rows written before Phase 1).
- §7.4 Cards & interaction — replace the two-line description with the new one
  (relationship-first; scope-dependent lines; verbatim neutral label; the sticky
  lane header is the sentence subject).
- §10 Deferred — remove "The related-entity id on activity cards"; add a note that
  the hover popup's headline/field design is the follow-up plan, and add the
  `GraphNode.display_name()` commit gap (Graph page shows SHAs) as a known defect.
- §11 Source map — add `tests/test_activity_writer_display_name.py` to the Tests
  row. The Tests row currently omits `tests/test_activity_person_identity.py`,
  which is a real timeline test file — add it while you are there.

**Verify**
```
pytest -m unit tests -q
mypy src/
pylint src --score=y
bandit -c .bandit.yml -r src/ -lll
PYTHONPATH=src python scripts/generate_signal_activity_spec.py && git diff --stat docs/design/spec-activity-signal.md
```
The last command must produce **no diff** — nothing in `src/common/activity_signal/`
changed, so the spec-freshness CI gate is unaffected. If it does differ, stop: a
model change slipped in that this plan did not intend.

**6d.** `tests/test_activity_timeline_edge_cases.py` — **one assertion needs a
one-word edit; the rest of the file does not.** Read this before concluding the
tests missed something. It is the only test file that renders cards through the
layout (`build_grid` → `build_grid_body` → `build_cell` → `build_event_card`);
every other test stops at the helpers. Its `_render()` helper calls
`build_grid_body(...)` without a `scope`, so it always renders the `"activity"`
default — that part is unchanged. (Its name,
`test_history_scope_person_state_change`, is misleading: it has never exercised
the history branch.)

What *does* change is its text collector:

```python
def _texts(node: Any) -> list[str]:        # edge_cases.py:55
    if isinstance(node, str): return [node]
```

It returns **whole leaf strings**, and the pinned line-2 DOM (Phase 5a) puts the
name inside a compound span — `"Person · Alice Johnson"`, not `"Alice Johnson"`.
So in `test_history_scope_person_state_change`, change

```python
    assert "Alice Johnson" in texts          # ← fails: compound span
```

to a substring test:

```python
    assert any("Alice Johnson" in text for text in texts)
```

`assert "Updated" in texts` stays as-is (line 1 is its own `Div`, a bare string).
Verified against the pinned card: the collected texts are
`['Mar 15', 'Updated', 'Person · Alice Johnson', '03:30 PM']`, so the exact-member
form fails and the substring form passes. Do **not** "fix" this by loosening the
card back to a fused `Type · name` span — Phase 5a pins the split form
deliberately, so the type label keeps its per-entity colour.

Consequence, accepted deliberately: **no automated test pins the end-to-end
`scope` pass-through** (`render_grid` → `build_grid_body` → `build_cell` →
`build_event_card`). Because each parameter is defaulted, dropping one would fail
*silently* — history cards would just render activity-style. That gap is covered
by the **manual** history check in Phase 5 instead ("`scope=history` — cards read
`<Type> · <lane name>` / `Updated`"), which is why no test is added here. If the
scope branch is ever found rendering wrongly, this is the file to add a real
`scope="history"` layout test to.

**6e.** `tests/test_activity_person_identity.py` — **five of its 15 tests break on
this plan** and this step is what repairs them. It is easy to miss: the file is
not named in Phases 1–5, but it imports `_action_to_event` directly and asserts on
the compiled SQL of `fetch_actions_for_entity`. Nothing else in the file changes.

**(a) The three `_action_to_event` call sites** (lines ~188, ~202, ~218, inside
`TestActionToEvent`) use the keyword-only style and will raise
`TypeError: _action_to_event() missing 1 required positional argument:
'related_name'`. Pass `None` as the second positional argument — all three tests
assert only on `event.entity_type`, so the resolved name is irrelevant to them,
and `None` exercises the documented fallback:

```python
        event = _action_to_event(
            action,
            None,
            lane_entity_type="Person",
            lane_identity_ids=frozenset({"alice", "557058:abc"}),
        )
```

**(b) The two compiled-SQL counts** in `TestActionsPredicate` (lines ~279, ~295)
are scoped to the whole statement:

```python
assert sql.count("source=") == 4         # 2 identities
assert sql.count("source=") == 2         # 1 identity
```

The new correlated subquery repeats the identity disjuncts inside each `CASE`, and
the SELECT column list gains `activity_actions.target_source`, so the whole-statement
count rises to **11** and **6** (measured). The assertions' *intent* — "one disjunct
per identity, per side" — is about the `WHERE` clause, so keep that intent and scope
to it:

```python
        where = sql.split("FROMactivity_actionsWHERE", 1)[-1]
        # One disjunct per identity, per side — the added target_source column and
        # the resolve subquery's CASE both contain "source=", so scope to WHERE.
        assert where.count("source=") == 4            # 2 identities
        assert where.count("actor_entity_id=") == 2   # one per identity, actor side
        assert where.count("target_entity_id=") == 2  # one per identity, target side
```

for the two-identity case, and `2` / `1` / `1` for the single-identity one.
**Do not delete or `xfail` these tests** — the disjunct-per-identity property is
the fix from `90c9674` and must stay pinned.

**Verify**
```
pytest -m unit tests/test_activity_person_identity.py -q    # → 15 passed
```

> **This file is in Scope for exactly these edits.** It is the one place the
> "editing a file not in Scope" STOP condition must not fire; if you believe any
> *other* unlisted file needs changing, that is still a STOP.

**Spec-freshness check (docs must move with the code).** Beyond the generated
spec, confirm nothing still contradicts the shipped behaviour.

> **Prove the gate bites before trusting it.** These are *negative* assertions
> (expected output: nothing), and a negative grep passes vacuously when its pattern
> is wrong — which is exactly how this gate was first written. So: run each one
> **before** making the fix and confirm it currently *does* match, then run it
> again after. If a pattern matches nothing at either point, it is broken, not
> satisfied.

| Run now (expect ≥1 hit) | Run after (expect **no** hits) |
|---|---|
| `grep -rn 'first non-empty of \`attributes.name\`' docs/design/` | same |
| `grep -rni 'mirrors GraphNode' docs/design/ src/` | same |
| `grep -rni 'carry no related-entity id' docs/design/` | same |

Notes on the patterns — these were verified against the live tree, and the naïve
form of each is wrong:

- **`mirrors GraphNode` must be case-insensitive and unbracketed.** The two live
  occurrences differ in case *and* punctuation: the writer's docstring reads
  `"""Mirrors GraphNode.display_name() from node_base.py.` (capital M) while the
  model comment reads `# … mirrors GraphNode.display_name(); …` (lowercase, no
  backticks). A pattern containing backticks or matching lowercase only finds
  neither.
- **Scope the second one to `src/`, not `src/connectors/consumers/`.** The false
  claim lives in two places — the writer docstring (fixed by 1a) and a comment at
  `src/app/db/models/activity_event.py:51` (fixed by 1c). A narrower scope reports
  clean while one survives, which is worse than no gate at all.
- **`carry no related-entity id` must not include a leading "activity events".**
  The doc renders it as `**Activity events carry no related-entity id.**` — the
  capital A breaks a lowercase full-phrase match.

**One deliberate exception — must still match, and must be left alone:**
```
grep -rn 'first non-empty of name/title/summary/key' docs/project-plan/completed/
```
This must return exactly one hit:
`docs/project-plan/completed/neo4j-node-common-display-properties.md:141`. That
file is a historical record of the original four-field rule. Do **not** edit it,
and do not treat its presence as a failure of this gate.

## Test plan

Files are named in Phases 1 and 6; this section is the checklist. The repo has
**no root `conftest.py`** and silently skips unmarked tests, so every new test
needs `@pytest.mark.unit` or a module-level `pytestmark` — a test that "passes"
without a marker is not running.

**`tests/test_activity_timeline_ui_helpers.py`** (existing file, 37 tests)
- Rewrite `test_card_summary_fallback` as `test_card_primary` + `test_card_secondary`.
  Model the structure on the existing `test_humanize_relationship` and
  `test_entity_type_token_mapping` in the same file.
- Cases for `card_primary`: a relationship → its humanized label; `STATE_CHANGE` →
  `"Updated"`; an empty relationship → the entity-type label.
- Cases for `card_secondary`: `related_name` wins; `related_id` when the name is
  missing; `summary` when both are missing; the bare type label when all three are
  empty; the `Type · name` separator format.
- Extend the existing `popup_fields` test to assert the headline is **unchanged**
  (hover is out of scope).

**`tests/test_activity_api_integration.py`** (existing file, 22 tests) — update
the fake first (Phase 6b), then add:
- `lane_role` is `"target"` when the lane is the target, `"actor"` when it is the
  actor (both directions of the same relationship).
- `related_id` names the **other** side in both directions.
- Row-multiplication guard: an other-side entity with **several**
  `activity_events` rows still yields one event per action row.
- One action with a `related_name` and one with `None`, asserting both the
  resolved and fallback strings.

**`tests/test_activity_writer_display_name.py`** (**create**) — two cases:
`_compute_display_name` returns exactly 512 characters for an over-long commit
message (the Phase 1 clamp), and it resolves `full_name` for a `Person` (whose
attributes carry no `name`/`title`/`summary`/`key`). Keep `tests/test_activity_api_unit.py`
untouched — it is listed in Scope as *check only* precisely so the clamp test
does not land in the wrong module.

**`tests/test_activity_person_identity.py`** (existing, 15 tests) — five of its
tests break on this plan and are updated in Phase 6e, not here: three
`_action_to_event` call sites (the new `related_name` positional) and the two
compiled-SQL counts in `TestActionsPredicate` (the added subquery repeats the
identity disjuncts inside its `CASE`).

**Verify**: `pytest -m unit tests -q` → all pass, including the new cases.

**Accepted coverage gap (do not "fix" it).** Nothing automated pins the end-to-end
`scope` pass-through (`render_grid` → `build_grid_body` → `build_cell` →
`build_event_card`). The only file that renders cards through the layout,
`tests/test_activity_timeline_edge_cases.py`, always uses the `"activity"` default
and asserts by membership, so it cannot catch a dropped pass-through — and because
every `scope` parameter is defaulted, such a drop fails *silently* (history cards
would render activity-style). This is knowingly covered by the Phase 5 **manual**
history check instead of a test. See Phase 6d.

## STOP conditions

Stop and report back — do not improvise — if:

- **The resolve subquery compiles to a cartesian join.** Confirm `activity_events`
  appears only inside the `SELECT` sub-clause, never as a second top-level `FROM`.
  If it does, the lane will contain duplicated events and pagination will corrupt.
- **`mypy src/` rejects the tuple typing** after a genuine attempt at the unpacking
  form in Phase 3b. Use `cast(...)` if that resolves it; if it still fails, stop —
  do not switch to `.scalars()` (silent feature loss) and do not add a blanket
  `# type: ignore`.
- **`pytest -m unit tests -q` still fails after the fake session is updated** per
  Phase 6b. Report the failure rather than adjusting production code to satisfy a
  test.
- **The Alembic head is not `e636212b35b4`**, or another migration was added since
  (`alembic heads` shows more than one). Re-derive `down_revision` from
  `alembic heads` instead of using the value in Phase 2b.
- **`_compute_display_name` cannot be made to respect the 512 limit** without
  changing the column width — the plan assumes a clamp, not a schema change.
- **A step requires editing a file not in the `## Scope` table.** That is a plan
  defect, not a judgement call. The four test files added to Scope by Phases 6b
  and 6e — `test_activity_api_integration.py`, `test_activity_api_unit.py` (check
  only), `test_activity_writer_display_name.py`, `test_activity_person_identity.py`
  and `test_activity_timeline_edge_cases.py` — are *in* Scope; this condition is
  about files beyond that list.
- **The code at a cited location does not match the excerpt** in `## Current
  state` — the repo has drifted. (This is *not* stale excerpts: the tree was clean
  at `90c9674` when this plan was written, so real drift means someone committed or
  edited these files afterwards.)
- **`src/common/activity_signal/` needs to change.** Nothing in this plan should
  require it; if it does, the design is wrong (it would also break the
  spec-freshness CI gate).

## Maintenance notes

**What future changes will collide with this**
- The resolve subquery in `fetch_actions_for_entity` and the writer's
  `_DISPLAY_NAME_MAX` clamp are **two halves of one contract**: the reader assumes
  `display_name` is a short human string. If the column is widened, revisit the
  clamp; if the clamp is removed, the writer starts dropping signals again.
- `_compute_display_name` now deliberately **diverges** from
  `GraphNode.display_name()` (`src/connectors/neo4j_db/node_base.py:58`), which
  still uses the original four-word rule. The two are no longer mirrors — if
  someone "re-syncs" them, the commit-gap bug returns on one side.
- Adding a paginated or per-lane endpoint later must preserve the
  `(ActivityAction, related_name)` tuple shape, or reintroduce the `.scalars()`
  drop.
- If a new entity type is added whose name field is not one of the six, its cards
  will silently render a raw id.

**What a reviewer should scrutinize**
- That `fetch_actions_for_entity` ends in `result.all()`, **not** `.scalars()` —
  and that `fetch_event_history` still uses `.scalars()`.
- That one `pytest -m unit` assertion would actually fail if `related_name` were
  dropped (otherwise the silent regression is unpinned).
- That the migration is additive and nullable, with no data statement.
- That no `Graph` page or producer file was touched.

**Deliberately deferred** (see `## Out of scope`): the Neo4j `display_name` twin,
backfilling `display_name`/`target_source`, the hover-popup field design, and
mention-only person resolution.

## Acceptance criteria

- [ ] Activity card line 1 is the relationship; line 2 is `Type · <name>` + time.
- [ ] Line 2 names the object in **both** directions: lane-as-target (Case A) and
      lane-as-actor (Case B, including a Person actor whose `summary` is NULL).
- [ ] The relationship label is `humanize_relationship` output, unmodified — no
      inverse map, no `_BY` handling, no per-relation vocabulary.
- [ ] History scope renders the same 2-line shape as `<Type> · <lane name>` /
      `Updated` + time.
- [ ] Hover popup output, the card's tooltip, and the click target are unchanged.
- [ ] Lane pagination and per-cell counts are unchanged (no row multiplication).
- [ ] `pytest -m unit tests -q`, `mypy src/`, `pylint src --score=y` (≥ 9.0) and
      `bandit` all pass; the activity-signal spec regenerates with no diff.
      (`pylint src` exits non-zero on this repo even at a clean 9.68/10 — the CI
      job reads the **score** via `--exit-zero`, so check the number, not the
      exit code.)
- [ ] `tests/test_activity_person_identity.py` passes all 15 tests, with its
      disjunct-per-identity intent intact and the three `_action_to_event` call
      sites updated — not deleted, not `xfail`ed.
- [ ] The activity card's line 2 renders the entity type in its **own**
      colour-coded span (`type_color` is used, not dead); `card_secondary`
      returns the object name alone.
- [ ] `_compute_display_name` resolves `full_name` (Person) and `message`
      (Commit); the existing four fields are untouched and **not reordered**.
- [ ] `_compute_display_name` never returns a string longer than 512 characters
      (a test with a 2000-char commit message passes), so no signal is dropped by
      a `VARCHAR(512)` overflow.
- [ ] `docs/design/activity-timeline-design.md` §4.2 lists all six fields and no
      longer claims the rule "mirrors `GraphNode.display_name()`".

## Out of scope (explicit)

- **Hover popup / tooltip content, `aria-label`, and click behaviour** — deferred
  to a separate plan. `popup_fields` keeps byte-identical output; no lane label is
  threaded into the card for tooltips.
- **Any backfill of `display_name`.** Phase 1 is write-time only, so rows already
  in the store keep their raw ids (a commit still renders as its SHA). Accepted.
- **`GraphNode.display_name()` in `src/connectors/neo4j_db/node_base.py:58`** —
  same four-word lookup, same commit gap (`Commit` there holds `sha`/`message`
  with no override), so the **Graph** page also shows SHAs for commits. Same
  defect, different feature surface (its own callers, tests and Cypher
  properties). Worth its own plan; not folded in here.
- Resolving a *mention-only* person (no `IdentityMapping`) — unchanged from the
  accepted limitation in the timeline design doc §5.3.8.
- Backfilling `target_source` for pre-existing rows.
- Per-lane event totals, outbound "View Timeline" buttons, mobile interactions.

## Risks

| Risk | Mitigation |
|---|---|
| **The subquery multiplies rows.** `activity_events` has many rows per entity, so a naive join inflates a lane and breaks pagination. | `ORDER BY event_time DESC LIMIT 1` scalar subquery (one value per action row); explicit integration test in 6b asserting event count per action row. |
| **Subquery correlation mis-compiles** (cartesian join, silent slowdown). | Inspect the compiled SQL once; compare event counts with and without the subquery before moving on. This is the step to verify hardest. |
| **Resolving the wrong side.** The other side may be the actor or the target, and `COALESCE(target_source, source)` alone is wrong for lane-as-target. | Branch on the existing `actor_match` predicate (`case(...)`); covered by both-direction tests in 6b. |
| **`direction` looks like the answer but is not.** It is `None` on most producers (37 occurrences vs 2 `OUT`), means Neo4j *edge orientation* rather than grammatical voice, and is not persisted in `activity_actions` at all. | Documented in Decisions #3; the label stays verbatim and neutral. |
| **A new name field shadows an existing one.** | Cannot happen: only `PersonAttributes`/`CommitAttributes` define `full_name`/`message`, and **neither** defines `name`, `title`, `summary` or `key` (verified against the live models). The fields are appended, never reordered, so the change is a strict superset. |
| **`display_name` divergence goes unnoticed.** The comment in `_compute_display_name` and the doc both said "mirrors `GraphNode.display_name()`"; after Phase 1 that is false, and the graph side still shows commit SHAs. | Phase 1a updates the docstring and Phase 1b the design doc; §10 Out-of-scope records the Neo4j twin as a separate plan so the divergence is deliberate and written down, not accidental. |
| **Existing rows keep raw ids after Phase 1** (write-time change, no backfill), so a reviewer may read the unchanged SHA as a failed fix. | Accepted and documented; Phase 1's verify step says so explicitly — the stored value only changes once fresh signals land. |
| **Raw ids leak into the UI** where the other side has no `activity_events` row yet (and no backfill can repair it). | Accepted: `related_name → related_id → summary → type` degrades in that order, and `mock=card_variety` exercises the fallback visibly. The 6 remaining raw ids are readable keys (`UI-2`, `BTS-7`, `work-behavior-analytics-ai::main`), not opaque handles. |
| **A class rename breaks styling** that referenced `.timeline-card-summary`. | No test or code references the old class names (verified). The CSS block is replaced in the same step (5b, Phase 5). |
| **Drift after this plan was written** — the resolve touches `query.py` and `service.py`, which the merged Person-identity change (`90c9674`) also modified. | The dual drift check at the top (commit range **and** `git status`) covers both committed and uncommitted drift; locate every symbol by content, never by line number. |
| **The resolve silently no-ops** — `.scalars()` left in place drops `related_name`, and because the field is optional nothing raises. | Phase 3b states the return line explicitly and Phase 6b pins it with an assertion; `## STOP conditions` forbids reverting to `.scalars()`. |

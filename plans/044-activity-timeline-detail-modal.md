# Plan 044: Activity Timeline — event detail modal

> **Executor instructions**: Follow this plan step by step. Do not commit, push, or
> open a PR — leave changes in the working tree and report them. Run the `Verify`
> commands as you go; they are the acceptance check for each step.
>
> **Drift check (run first)** — check **both** committed and uncommitted drift:
> ```
> git diff --stat 202e763..HEAD -- src/app/dash_app/pages/timeline/ \
>   src/app/dash_app/components/common.py \
>   src/app/api/activity/v1/ src/app/api/graph/v1/ \
>   src/app/dash_app/assets/executive-dashboard.css \
>   docs/design/activity-timeline-design.md
> git status --short -- src/app/dash_app/pages/timeline/ \
>   src/app/dash_app/components/common.py \
>   src/app/api/activity/v1/ src/app/api/graph/v1/ \
>   src/app/dash_app/assets/executive-dashboard.css \
>   docs/design/activity-timeline-design.md
> ```
> If either reports changes, re-read those files before proceeding. Line numbers
> below are approximate — **locate every symbol by content**, and confirm each
> "Current state" excerpt against the live code before editing.
>
> **Note on the base commit**: `202e763` is "Activity Timeline Design card
> ordering". Plan 043 (`plans/043-activity-timeline-card-reading-order.md`) was
> executed against `90c9674` and is **committed at `202e763`** — verified: that
> commit contains `helpers.card_secondary` and the
> `add_activity_actions_target_source` migration. Its migration is **applied**:
> `alembic current` reports `51d673fb286f (head)` and
> `activity_actions.target_source` (`varchar(32)`) exists.
>
> This plan builds directly on it: it assumes `TimelineEvent` already carries
> `lane_role`, `related_id` and `related_name`, that `helpers.card_primary` /
> `card_secondary` exist, and that `activity_actions` has the `target_source`
> column. If any of those are absent, **that is a STOP condition** — Plan 043
> has been reverted or the branch moved, and this plan cannot be executed.

## Status

- **Priority**: P1
- **Effort**: L
- **Risk**: MEDIUM (a new Dash modal + one clientside click branch; one additive API field)
- **Depends on**: `plans/043-activity-timeline-card-reading-order.md` (committed at `202e763`)
- **Category**: direction (UX — the card is a fragment; the modal is the full sentence)
- **Planned at**: commit `202e763`, 2026-10-17

## Why this matters

Plan 043 made the timeline card read as a fragment — `Mentions` /
`PullRequest · Title of an Epic` — with the subject elided into the sticky lane
header. The card is deliberately terse: two lines, ~40px, no room for detail.

There is therefore **no way to see what an event actually is**. Hovering shows a
small 300px popover with a headline, a meta line, a time and a source link, and
clicking the card navigates to `/app/graph` with no query context at all
(`href="/app/graph"`, `layout.py:629`). To see either entity's real properties a
user must leave the timeline, reach the Graph page, and search manually.

This plan adds an **event detail modal**: click a card, get a large
(`size="xl"`) modal that reads as the complete sentence the card fragments —
subject, relationship, target — with **both entities' Neo4j properties rendered
side by side**, using the *same* table renderer the Graph page's right panel
uses, so a change to that renderer changes both surfaces.

## Current state

The facts the executor needs, inlined. Confirm each against the live code before
editing.

### The card today

`src/app/dash_app/pages/timeline/layout.py`, `build_event_card` (ends ~line 636):

```python
    return html.A(
        lines,
        href="/app/graph",
        target="_blank",
        rel="noopener noreferrer",
        className="timeline-card",
        style=card_style,
        title=title_text,
        **payload,
    )
```

`title_text = _popup_headline(event)` and `payload` is
`{"data-timeline-event": json.dumps(popup_fields(event, _format_full_datetime(...)))}`.

`build_event_card(event, lane_color, type_color, *, scope="activity")` —
`lane_color` is the lane's accent, `type_color` the other side's entity colour.
It is called from `build_cell` (line 639), which is called from
`build_grid_body` (line 729), which is called from `render_grid` in
`callbacks.py` (line 735). `build_grid_body` receives the **lane dicts**
(`lanes`, containing `label`) and passes `lane_key=wba_id` (line 794) — the lane's
id, **not** its display name.

### The hover popup today

`helpers.py`, `popup_fields(event, datetime_text)` (line 512) → a dict with
`summary` (from `_popup_headline`, line 463), `relationship`, `entity_type`,
`source`, `datetime`, and `url` only when present. `_popup_headline` prefers
`event["summary"]` — the *actor's* title, which Plan 043 proved wrong for
lane-as-actor cards.

`callbacks.py` line ~972 is an install-once `clientside_callback` binding
delegated `mouseover` / `focusin` / `mouseout` / `focusout` / `keydown` /
`scroll` listeners on `document`, driving `#timeline-popup-portal`
(`layout.py`, `POPUP_PORTAL_ID = "timeline-popup-portal"`, line 258). Contents
are built with `createElement` / `textContent` — **never `innerHTML`** — because
summary/label/url are ingested data.

The page root already contains the portal div, `role="tooltip"`, plus
`dcc.Store(id="timeline-selected-store", storage_type="memory", data=[])` and
other stores (`layout.py` ~line 351-370).

### The shared properties renderer (the reuse target)

`src/app/dash_app/components/common.py`:

- `_panel_properties_table(items: list[Any]) -> html.Table` — **line 693**. The
  table renderer that emits `className="details-prop-row"`. It stringifies every
  value, and special-cases (a) date-like keys/values into a humanized duration
  span with the exact timestamp as a `title` tooltip, (b) `url` keys / `http(s)`
  values into a link + external-link icon, (c) mono values (`id`, or >16 chars
  with no space) into `html.Code` + a `dcc.Clipboard` copy icon, (d) everything
  else into a span + copy icon. It drops nothing itself — filtering happens in
  `_panel_build_visible_properties` (line 664), which excludes `None` values and
  any key starting with `_` (so `_display_name`, `_on_hover_name`,
  `_last_updated_at` never show).
- `build_element_properties_content(data, *, expand_node_enabled=True)` — **line
  796**. Takes a **Cytoscape element `data` dict** (`{elementType: "node"|"edge",
  wba_id, label, nodeType, ...neo4j props}`), branches node-vs-edge, and renders
  a per-panel **header** (`label` + `nodeType`) plus, for nodes, an
  **"Expand Node" button** (disabled when `expand_node_enabled=False`, with a
  "Not available for this graph" caption).

This module is **already shared** — the Graph page
(`pages/graph/callbacks/display.py:9`) and the Collaboration Network page
(`pages/collaboration_network/callbacks/display.py:6`) both import from it. Any
page may import it absolutely; there is no circular-import problem.

Styling: `DETAILS_PANEL_HEADER_STYLE`, `DETAILS_PANEL_SUBTYPE_STYLE`,
`DETAILS_TABLE_STYLE`, `DETAILS_TABLE_KEY_STYLE`, `DETAILS_MUTED_TEXT_STYLE` are
in `src/app/dash_app/styles.py` lines 607-654. `.details-prop-row`,
`.details-prop-icon`, `.details-prop-value-wrap` are in
`src/app/dash_app/assets/executive-dashboard.css` around lines 1277-1300.

### The input dict shape the renderer needs

`neo4j_to_cytoscape(graph_response)` — `pages/graph/utils/data_transform.py:63`
— converts a `GraphResponse` dict into Cytoscape elements. For a node it builds:

```python
        cyto_node_data = {
            **node.get('properties', {}),
            'id': neo4j_element_id,   # Neo4j element_id
            'wba_id': wba_id,         # canonical WBA id
            'label': display_name,    # from _resolve_display_name
            'displayLabel': compact_label,
            '_onHoverName': ...,
            'nodeType': node_label,
            'elementType': 'node'
        }
```

So **each element is `{"group": "nodes", "data": {...}}`** — the panel builder
needs the inner `data` dict. `neo4j_to_cytoscape` is importable by any page (the
catalog editor's test callbacks already do it,
`pages/catalog/editor_test_callbacks.py:242`).

### The Graph fetch endpoint (reused as-is — no change)

- `POST /api/v1/graph/execute` — `src/app/api/graph/v1/router.py:22`; request
  `GraphExecuteRequest` (`model.py:16`: `source: Literal["raw","catalog"]`,
  `query: str | None`, `catalog_id: str | None`, `view`, `parameters:
  dict[str, Any]`); response `GraphResponse` (`model.py:104`: `nodes:
  list[GraphNode]`, `relationships`, `rawResults`, `isGraph: bool`,
  `resultCount`). `GraphNode` = `wba_id, elementId, labels, properties`.
- It validates write-keywords via `validate_read_only_query` and maps
  `RuntimeError → HTTP 500` (`router.py:68`). With `NEO4J_ENABLED=false`, the
  service raises `RuntimeError` → **HTTP 500**, not an empty payload.

### The view test modal (the size/shape to mirror)

`src/app/dash_app/pages/catalog/editor_layout.py`, `_render_test_results_modal`
(**line 521**) — the canonical "large modal" in this app:

```python
    return dbc.Modal(
        [
            dbc.ModalHeader(dbc.ModalTitle("", id="editor-test-modal-title")),
            dbc.ModalBody(
                dcc.Loading(
                    type="circle",
                    children=[ ... ],
                )
            ),
            dbc.ModalFooter(
                dbc.Button("Close", id="editor-test-modal-close",
                           color="secondary", size="sm")
            ),
        ],
        id="editor-test-modal",
        size="xl",
        scrollable=True,
        is_open=False,
    )
```

This is the target: `dbc.Modal`, `size="xl"` (Bootstrap `modal-xl`,
`max-width: 1140px`), `scrollable=True` (ModalBody scrolls on its own),
`z-index: 1050`, opened by a callback on `is_open` returning `no_update` on
close (`editor_test_callbacks.py:160-182`).

### `TimelineEvent` today

`src/app/api/activity/v1/model.py` — `signal_id, event_time,
relationship_type, summary, entity_type, source, url, details`, plus Plan 043's
`lane_role: Literal["actor","target"] | None`, `related_id: str | None`,
`related_name: str | None`.

**`source` is the *signal's* source, not the other side's.** The other side's
source is computed inside `fetch_actions_for_entity` as `related_source`
(`src/app/api/activity/v1/query.py:81-84`) but is **never selected as an output
column**, so it never reaches the API response. This plan closes that gap.

### Person node identity (why the left panel needs a hop)

A Person's Neo4j `id` is **not** necessarily the lane's WBA id.
`src/connectors/commons/person_cache.py:125-151` resolves a GitHub person by
**email** to an *already existing* Person node id — e.g. `github::Person::alice`
resolves to `jira::Person::557058:abc`. So `MATCH (p:Person {id:
"github::Person::alice"})` can return nothing for a lane that renders perfectly.

The repo's own precedent for this is `src/app/api/activity/v1/identity.py:27`:

```python
_IDENTITIES_CYPHER = (
    "MATCH (p:Person {id: $person_id})-[:MAPS_TO]-(i:IdentityMapping) "
    "RETURN i.id AS identity_id"
)
```

and `service.py:246-249` special-cases Person lanes with exactly this hop.

### Repo conventions that apply

- Dash pages: shared code must live in `dash_app/` or `dash_app/components/` —
  never imported across `pages/<name>/` (CLAUDE.md). Import absolutely:
  `from app.dash_app.components.common import ...`.
- Every page package's `__init__.py` must `from . import callbacks  # noqa: F401`
  or module-level `@callback`s never register — and with
  `suppress_callback_exceptions=True` the failure is **silent**.
- Dash fetches backend APIs with **sync `requests`** and
  `runtime_settings.get_int("HTTP_REQUEST_TIMEOUT")`; see
  `pages/timeline/api.py:125-129`.
- `from common.logger import logger` — never `print()`.
- Full type annotations (`mypy src/` is strict); built-in generics; `X | None`.
- Styles come from `styles.py` tokens (`COLOR_*`, `FONT_*`) and
  `assets/executive-dashboard.css`; **no ad-hoc hex or inline font sizes**.
- Modals render in a Bootstrap portal outside `#app-shell`; the theme class is
  mirrored onto `document.body`, and dark rules for `.modal-*` live at
  `executive-dashboard.css:1733-1805`. Nothing new is needed for dark mode.

## Decisions (agreed during planning)

| # | Decision | Rationale |
|---|----------|-----------|
| 1 | **Click opens the modal; the hover peek stays.** | Progressive disclosure. The peek is instant and needs no network; the modal is deliberate and fetches. |
| 2 | **The card stops being a link.** It becomes an `html.Div` — the whole card is the modal trigger. | One click target, one behaviour. The Graph navigation moves into the modal header (Decision 8). |
| 3 | **Fetch both nodes with ONE `POST /api/v1/graph/execute`** carrying constant parameterized Cypher and `parameters: {a, b}`. | No new endpoint, no new models, no new router wiring. Reuses `neo4j_to_cytoscape` and the shared table renderer. |
| 4 | **Add one additive field `related_wba_id` to `TimelineEvent`.** | The other side's `source` is not on the event, so the sibling's WBA id cannot be built in the UI. `related_source` is already computed in `query.py`; this exposes it pre-concatenated. |
| 5 | **Share the TABLE renderer, not the panel builder.** New `render_properties_table()` is called by both `build_element_properties_content` (graph + collaboration network) and the new modal body builder. | "A change in one affects both" without dragging the graph panel's per-panel header and dead "Expand Node" button into the modal. |
| 6 | **The modal header is the full sentence**: lane name · relationship · target name (as the Graph deep-link) · time. | The card elides the subject; the modal restores it. Neither panel needs a title, so the panels sit close together. |
| 7 | **Lane entity is the LEFT panel, always; the connector is non-directional.** | The lane is the card's subject. Plan 043 Decision 3 established the relation label is verbatim and neutral because `direction` is unusable — an arrow would re-assert a direction the data cannot support. |
| 8 | **The Graph deep-link opens in a NEW TAB** and runs the 2-node subgraph. | Matches today's card behaviour (`target="_blank"`). The subgraph shows what the modal shows, including the edge. |
| 9 | **Person lanes hop via `IdentityMapping`; every other type matches the id directly.** | Mirrors `service.py:246-249`. The naive id match misses merged Person nodes (`person_cache.py:125-151`). |
| 10 | **The modal always opens**; a missing node degrades to a per-panel "Not found in graph" note. Both missing → one empty state. `NEO4J_ENABLED=false` → one explanatory state. | The header needs no network, so the click is never dead. |
| 11 | **History scope shows a ONE-panel modal** (no connector, no second fetch), header `<lane name> · Updated · <time>`. | `lane_role` is `None` and `related_id` is `None` in history — there is no other side. |
| 12 | **Both panels show CURRENT Neo4j state**, with a muted "current state" caption. | Neo4j holds current state; `details` is empty for activity events, so an as-of-event panel is not available for the other side. One rule for both panels. |
| 13 | **50/50 panel split, ONE shared body scroll.** | Nested scroll regions in a modal are awkward; keeping the panels aligned reads as one table pair. |
| 14 | **The peek's headline becomes the same sentence**, gains a muted "Click for details" hint, and the native `title=` tooltip is REMOVED. | The peek currently shows `event["summary"]` — the field Plan 043 proved wrong — so hovering and clicking would describe one event two ways. The native tooltip duplicates the headline ~1s later and overlaps the portal. |
| 15 | **Mock data gains a `wba::other::<Type>::<id>` lane id convention** and `related_id` / `related_name` / `lane_role`. | Without it the feature is undemonstrable in mock mode. The ids deliberately match no real node, so clicking a mock card exercises the "Not found" paths deterministically with zero Neo4j calls. |

## Commands you will need

Activate the virtualenv first (`source .venv/bin/activate`). Code lives in `src/`
but is imported as top-level packages, so **`PYTHONPATH=src` is required** for
anything that imports app code (`pytest.ini` sets it for tests).

| Purpose | Command | Expected on success |
|---|---|---|
| Typecheck | `mypy src/` | exit 0, no errors (strict) |
| Lint | `pylint src --score=y` | score **≥ 9.0** (it exits non-zero even at 9.68 — read the number) |
| Tests (the gate) | `pytest -m unit tests -q` | all pass |
| One module | `pytest -m unit tests/test_activity_api_unit.py -q` | all pass (unchanged in this plan) |
| API integration | `pytest -m unit tests/test_activity_api_integration.py -q` | all pass (mocked DB — needs no app, Postgres or mock mode) |
| Migration (already applied) | `cd src/app && alembic current` | `51d673fb286f (head)` — Plan 043's `target_source` column is live |
| Components | `pytest -m unit tests/test_activity_timeline_ui_helpers.py -q` | all pass |
| Security scan | `bandit -c .bandit.yml -r src/ -lll` | no High severity |
| Spec freshness | `PYTHONPATH=src python scripts/generate_signal_activity_spec.py && git diff --stat docs/design/spec-activity-signal.md` | **no diff** |

There is **no root `conftest.py`** and unmarked tests are silently skipped, so
every new test needs `@pytest.mark.unit` or a module-level
`pytestmark = pytest.mark.unit`. A test that "passes" without a marker is not
running.

## Suggested executor toolkit

- Read `docs/design/activity-timeline-design.md` §7.4 (Cards & interaction) and
  §5.3 before starting — this plan updates both.
- Read `docs/design/design-system.md` before styling; do not invent tokens.

## Scope

**In scope** — the only files this plan may modify:

| File | What changes | Phase |
|---|---|---|
| `src/app/api/activity/v1/model.py` | two additive fields: `related_wba_id`, `lane_entity_type` | 1 |
| `src/app/api/activity/v1/query.py` | select `related_wba_id` as a 3rd column; return-shape followed through | 1 |
| `src/app/api/activity/v1/service.py` | thread `related_wba_id` + `lane_entity_type`; `_action_to_event` returns both | 1 |
| `src/app/dash_app/components/common.py` | extract `render_properties_table`; add `render_visible_properties` | 2 |
| `src/app/dash_app/pages/timeline/api.py` | `fetch_node_properties(wba_ids)` HTTP client | 3 |
| `src/app/dash_app/pages/timeline/helpers.py` | `detail_sentence` / `detail_payload` / `graph_deep_link` / `graph_lookup_id`; `popup_fields` headline change; drop `_popup_headline` | 3, 4 |
| `src/app/dash_app/pages/timeline/layout.py` | card → `Div` + `role`/`tabIndex`; modal skeleton; Graph link; drop the `_popup_headline` import | 5 |
| `src/app/dash_app/pages/timeline/callbacks.py` | click branch in the clientside listener; detail callback | 5 |
| `src/app/dash_app/assets/executive-dashboard.css` | modal layout + `In` column rules | 5 |
| `src/app/api/activity/v1/mock_data.py` | mock lane ids + event fields | 6 |
| `tests/test_activity_api_integration.py` | fake session returns 3-tuples; `related_wba_id` / `lane_entity_type` assertions; `mock::` ids re-pointed | 6, 7 |
| `tests/test_activity_timeline_ui_helpers.py` | updated `popup_fields` test + new `detail_*` tests; `mock::` ids re-pointed | 6, 7 |
| `tests/test_activity_timeline_mock.py`, `tests/test_activity_timeline_callbacks.py` | `mock::` ids re-pointed to `wba::other::` | 6 |
| `tests/test_activity_timeline_detail_modal.py` | **create** — SQL shape + `render_properties_table` + payload builders | 7 |
| `docs/design/activity-timeline-design.md` | §5.1, §5.3, §7.4, §11 | 7 |

**Out of scope** — do NOT touch:

- `src/common/activity_signal/` — nothing here changes the signal schema. If you
  believe it must, STOP: the spec-freshness CI gate would fail and the design is
  wrong.
- The producers (`src/connectors/producers/`), the consumer, the Neo4j sink, and
  `src/connectors/neo4j_db/node_base.py` (the `GraphNode.display_name()` commit
  gap is a **separate, known defect** — out of scope, see Maintenance notes).
- `src/app/api/graph/v1/` — `POST /graph/execute` is reused **unchanged**.
- The Graph page and the Collaboration Network page: they must keep rendering
  exactly as they do today. Phase 2 is a **pure refactor** for them.
- `_fetch_lane`'s pagination, the timeline grid, cell overflow, idle separators.
- The `timeline-popup-portal`'s positioning logic (Decision 14 changes the
  *content* of the peek, not its placement/behaviour).

## Git workflow

- **Do not commit, push, or open a PR.** This repo's rule (CLAUDE.md) is that
  changes are left in the working tree for the operator to review. No branch
  creation either — work on the current branch.
- Do not run `git stash`, `git checkout`, `git reset`, or `git clean`.

## Implementation

### Phase 1 — API: expose the other side's canonical WBA id

`related_source` is already computed in `fetch_actions_for_entity`; it is simply
not selected. Build the full id server-side so the UI never concatenates WBA ids.

**1a.** `src/app/api/activity/v1/query.py`, inside `fetch_actions_for_entity`.
`related_source` and `related_id` are already `CASE` expressions (lines 81-92).
Add a third column by string-concatenating with `func.concat` — **not** the `||`
operator, which is overridden in some databases:

```python
    related_wba_id = func.concat(
        related_source, "::", related_type, "::", related_id
    )

    stmt = select(
        ActivityAction,
        related_name_subq.label("related_name"),
        related_wba_id.label("related_wba_id"),
    ).where(or_(actor_match, target_match))
```

**Change the return line** to carry the third column:

```python
    result = await db.execute(stmt)
    # NOT .scalars() — it returns only the FIRST column of each row, which
    # silently drops related_name and related_wba_id.
    return [(action, name, wba) for action, name, wba in result.all()]
```

The signature becomes:

```python
) -> list[tuple[ActivityAction, str | None, str | None]]:
```

**1b.** `src/app/api/activity/v1/model.py` — add **two** additive fields to
`TimelineEvent`, after `related_name`:

```python
    related_wba_id: str | None = Field(
        default=None,
        description=(
            "Canonical WBA id of the *other* side, "
            "'{source}::{entity_type}::{id}'. None for scope=history, and None "
            "when the other side's source is unknown. The UI uses this to look "
            "the sibling node up in Neo4j."
        ),
    )
    lane_entity_type: str | None = Field(
        default=None,
        description=(
            "The lane entity's OWN entity type. Needed because ``entity_type`` "
            "is the *other* side's type, so the UI cannot otherwise tell which "
            "side of the event the lane was — and the Person→IdentityMapping "
            "lookup hop depends on it. None for scope=history, where "
            "``entity_type`` is already the lane's own."
        ),
    )
```

`lane_entity_type` is **derivable and must be derived on the server** — do not
leave it for the UI to guess. `_action_to_event` already computes the branch
that decides it (see 1c).

**1c.** `src/app/api/activity/v1/service.py`:

- `_build_event` — accept `related_wba_id: str | None = None` and
  `lane_entity_type: str | None = None` and pass both into `TimelineEvent`.
- `_action_to_event` — the third positional parameter, and set it. Its existing
  keyword-only `lane_entity_type: str` parameter already holds **the lane's own
  type** (it is what `is_actor` compares against) — so `lane_entity_type` is
  passed straight through to the event and the UI never has to infer the side:

```python
def _action_to_event(
    action: ActivityAction,
    related_name: str | None,
    related_wba_id: str | None,
    *,
    lane_entity_type: str,
    lane_identity_ids: frozenset[str],
) -> TimelineEvent:
```

  and inside, after `related_id`:

```python
    related_wba_id=related_wba_id,
    lane_entity_type=lane_entity_type,
```

- `_fetch_lane` — unpack three values from the new tuple shape:

```python
        events = [
            _action_to_event(
                action,
                related_name,
                related_wba_id,
                lane_entity_type=entity_type,
                lane_identity_ids=frozenset(eid for _, eid in identities),
            )
            for action, related_name, related_wba_id in action_rows
        ]
```

  `last_row = action_rows[-1][0] if action_rows else None` is **unchanged** —
  `[0]` is still the ORM row. `_event_to_event` is **unchanged**: history events
  keep `related_wba_id=None` via the `_build_event` default.

**Verify**
```
pytest -m unit tests -q
mypy src/
```
Expect the tuple-shape change to break tests that call `_action_to_event` or
assert on the compiled SQL — **that is expected**; they are repaired in Phase 7.
Do **not** restore `.scalars()` or reshape the query to get back to green.

### Phase 2 — Components: share the table renderer

**2a.** `src/app/dash_app/components/common.py` — rename the private
`_panel_properties_table` (line 693) to a **public**
`render_properties_table`. **Change its body in NO way whatsoever** — not the
heuristics, not a comment, not a variable name. Every value-formatting decision
(date spans, links, mono `html.Code`, copy icons) must keep producing
byte-identical output, because the Graph page and the Collaboration Network page
render through this same function and **this plan is not allowed to change what
they show**.

> **Resist the temptation to "improve" the mono heuristic for the modal.** A WBA
> id (`github::Person::alice`) is long, has no space, and so reaches the
> `is_mono` branch as `html.Code`. That is fine: the modal's table cell sets
> `wordBreak: break-word` (`common.py:787`) and `::` is a break opportunity, so
> the id wraps inside the narrow column. Widening the mono condition to exclude
> `::` would *also* change the Graph page's rendering, which is a regression on a
> surface out of scope.

Update **only the docstring**, to say it is the single shared `(key, value)`
table renderer used by the graph panel, the collaboration network panel and the
timeline detail modal.

**2b.** Give it the same `None`/private-key filtering the panel builder applies,
by adding a thin wrapper **beside** it (do not change `render_properties_table`'s
pure signature):

```python
#: The same synthetic keys the graph right panel hides, so the modal shows the
#: same rows as the panel it mirrors (see ``build_element_properties_content``).
_PANEL_NODE_EXCLUDE_KEYS = frozenset(
    {"displayLabel", "id", "wba_id", "label", "nodeType", "elementType"}
)


def render_visible_properties(props: dict[str, Any]) -> html.Div:
    """Render a node's properties, hiding private/internal keys and None values.

    The shared entry point for the timeline detail modal.  It applies the *exact*
    visibility rule the graph right panel applies — ``_panel_build_visible_properties``
    with the same ``_PANEL_NODE_EXCLUDE_KEYS`` — so the modal and the panel show
    the same rows in the same style, and then delegates to
    ``render_properties_table``.
    """
    properties = _panel_build_visible_properties(props, _PANEL_NODE_EXCLUDE_KEYS)
    items = sorted(properties.items())
    wba_id = props.get("wba_id") or props.get("id")
    if wba_id is not None:
        items = [("id", wba_id)] + items
    if not items:
        return html.P(
            "No properties", className="text-muted", style=DETAILS_MUTED_TEXT_STYLE
        )
    return render_properties_table(items)
```

The exclude set is spelled out here rather than inlined as `set()` on purpose:
passing an empty set would let `label`, `nodeType`, `elementType`, `displayLabel`
and `wba_id` through as table rows, and would render a **second** identity row
alongside the injected `("id", wba_id)` one.

`build_element_properties_content` should then use `_PANEL_NODE_EXCLUDE_KEYS` for
its node branch instead of its own inline literal (line 824), so the two sets can
never drift apart.

**2c.** Point the existing callers at the renamed function:

- In `common.py`, `build_element_properties_content` — the node branch
  (`_panel_properties_table(sorted_items)`) and the edge branch
  (`_panel_properties_table(meta_items)`).
- Grep for any other caller:
  `grep -rn "_panel_properties_table" src/` — **fix every hit**; a missed one is
  an `AttributeError` at request time.

Do **not** change what `build_element_properties_content` renders — the Graph
page and the Collaboration Network page must be byte-identical after this phase.

**Verify**
```
pytest -m unit tests -q
mypy src/ && pylint src --score=y
grep -rn "_panel_properties_table" src/     # → no matches
```
Then confirm `build_element_properties_content` output is unchanged — the
existing Graph/CN tests are the gate. If none pin it, render a node dict through
it before and after this phase and diff the two `str(...)` outputs; they must be
identical.

### Phase 3 — Timeline API client: fetch node properties

**3a.** `src/app/dash_app/pages/timeline/api.py` — add, following this module's
existing conventions exactly (`requests` with a runtime timeout, a dedicated
exception, `logger.warning` on failure):

```python
class NodePropertiesError(RuntimeError):
    """Raised when the graph property fetch fails (non-200 or transport error)."""


#: One indexed scan for every requested id, then a Person hop.  A node that does
#: not exist is simply absent from the result, which is what lets the UI render a
#: per-panel "not found" state instead of an empty property table.  The
#: ``MAPS_TO`` hop and the ``coalesce`` are explained in step 3b — **write the
#: final form from 3b here**; the placeholder below is what 3b replaces.
_NODE_PROPERTIES_CYPHER = (
    "MATCH (n) WHERE n.id IN $ids RETURN n LIMIT 2"
)


def fetch_node_properties(wba_ids: list[str]) -> dict[str, dict[str, Any]]:
    """Fetch node properties for each WBA id, keyed by WBA id.

    Returns ``{}`` for an empty input.  A node that does not exist in Neo4j is
    simply absent from the result — callers render a per-node "not found" state.
    Raises :class:`NodePropertiesError` on a transport error or a non-200
    response, which includes the HTTP 500 the backend returns when
    ``NEO4J_ENABLED`` is false.
    """
    ids = [str(w) for w in wba_ids if w]
    if not ids:
        return {}
    try:
        # Bandit's B113 only recognises literal timeouts; ours is runtime-configured.
        response = requests.post(  # nosec B113
            f"{get_api_base_url()}/api/v1/graph/execute",
            json={
                "query": _NODE_PROPERTIES_CYPHER,
                "source": "raw",
                "view": "graph",
                "parameters": {"ids": ids},
            },
            timeout=runtime_settings.get_int("HTTP_REQUEST_TIMEOUT"),
        )
    except requests.RequestException as exc:
        logger.warning(f"[Timeline] node properties request failed: {exc}")
        raise NodePropertiesError(f"request failed: {exc}") from exc

    if response.status_code != 200:
        logger.warning(
            f"[Timeline] node properties returned {response.status_code}"
        )
        raise NodePropertiesError(f"HTTP {response.status_code}")

    try:
        payload = response.json()
    except ValueError as exc:
        raise NodePropertiesError(f"invalid JSON: {exc}") from exc

    elements = neo4j_to_cytoscape(payload if isinstance(payload, dict) else {})
    result: dict[str, dict[str, Any]] = {}
    for element in elements:
        data = element.get("data")
        if isinstance(data, dict) and data.get("wba_id"):
            result[str(data["wba_id"])] = data
    return result
```

Add the import: `from app.dash_app.pages.graph.utils import neo4j_to_cytoscape`.
This is a **page-level import of another page's `utils` subpackage** — permitted,
already done by `pages/timeline/callbacks.py:29` and
`pages/catalog/editor_test_callbacks.py:21`. Do not move it.

**Note on the query**: `WHERE n.id IN $ids` uses the `id`-uniqueness
constraint/index on every label. Do **not** write `MATCH (n {id: $a})` twice and
do not `UNION`; a single indexed `IN` scan is one round trip and one plan. The
`OPTIONAL MATCH` in 3b's final form is for the **Person hop only** — it is not a
second entity lookup, and it cannot drop rows because a `MATCH` with `WHERE n.id
IN $ids` establishes `n` first.

**3b. Person lanes need the hop (Decision 9).** The modal must translate a
Person WBA id into the IdentityMapping id **before** calling
`fetch_node_properties`. Add a pure helper in
`src/app/dash_app/pages/timeline/helpers.py` (it is a string transform; it
belongs beside the other pure helpers):

```python
_PERSON_MARKER = "::Person::"
_IDENTITY_MARKER = "::IdentityMapping::"


def graph_lookup_id(wba_id: str, entity_type: str) -> str:
    """Return the id to look this entity up by in Neo4j.

    A Person's canonical node id is NOT necessarily its lane WBA id: the person
    cache resolves a provider person to an existing canonical Person (by email
    or Atlassian account id), so ``github::Person::alice`` may live in the graph
    as ``jira::Person::557058:abc``.  The graph therefore has to be entered via
    the person's IdentityMapping node, exactly as
    ``api/activity/v1/identity.py`` does.  Every other entity type is stored
    under its own canonical id and is matched directly.
    """
    if entity_type != "Person" or _PERSON_MARKER not in wba_id:
        return wba_id
    return wba_id.replace(_PERSON_MARKER, _IDENTITY_MARKER, 1)
```

**Then update `_NODE_PROPERTIES_CYPHER` to handle both cases in one query**, so
the single round trip still covers both panels:

```python
_NODE_PROPERTIES_CYPHER = (
    "MATCH (n) WHERE n.id IN $ids "
    "OPTIONAL MATCH (n)-[:MAPS_TO]-(p:Person) "
    "WITH coalesce(p, n) AS resolved "
    "RETURN DISTINCT resolved AS n LIMIT 2"
)
```

- For a non-Person id, `[:MAPS_TO]` matches nothing and `coalesce` yields the
  node itself.
- For an IdentityMapping id, it yields the canonical Person.
- `DISTINCT` collapses the case where both ids resolve to the same node (a
  self-referencing event), which would otherwise emit two identical panels.

> **This Cypher has already been executed against the live local graph and all
> five cases pass** — measured on 2026-10-17 against
> `neo4j:5.26-community`. You do **not** need to re-derive it; implement it as
> written. The measured evidence, so you can recognise a regression:
>
> | Input | Rows | Result |
> |---|---|---|
> | `confluence::IdentityMapping::557058:62105664-…` | 1 | **Person** `jira::Person::557058:62105664-…` (a *merged* person) |
> | `jira::Person::557058:62105664-…` (already canonical) | 1 | itself, `Person` |
> | `github::Repository::shuvabrata/work-behavior-analytics-ai` | 1 | itself, `Repository` (no `MAPS_TO`, correctly not hopped) |
> | `wba::other::Person::nope` (missing) | 0 | absent → the "Not found" panel |
> | merged id **+** a missing id, one call | 1 | only the resolvable node |
>
> The merged case is real, not hypothetical: both
> `confluence::IdentityMapping::557058:62105664-…` and
> `jira::IdentityMapping::557058:62105664-…` reach the **same**
> `jira::Person::557058:62105664-…`. A naive `MATCH (p:Person {id: $lane_id})`
> would have returned nothing for a Confluence-identity lane — which is why the
> hop is required.
>
> The `id`-equality is index-backed: `SHOW INDEXES` confirms a `RANGE` index on
> `id` for every one of the 16 entity labels (`Person`, `Issue`, `PullRequest`,
> `Repository`, …), so `WHERE n.id IN $ids` is a seek, not a scan. Do not
> replace it with a property-map match, which would be a scan.
>
> The deep-link Cypher is also verified: the lane-only form returns 37 rows for
> a real Repository id, and the related-node form returns **0** when no such edge
> exists (the expected case for a mock or historical event) — the Graph page
> shows the nodes and the user sees the edge is absent, which is correct rather
> than an error.

**Verify**
```
mypy src/ && pylint src --score=y
```
Re-run the five-case check above **once**, after wiring `fetch_node_properties`,
to confirm the code path (not just the Cypher) behaves — substituting a real
IdentityMapping id from
`MATCH (im:IdentityMapping)-[:MAPS_TO]-(p:Person) RETURN im.id LIMIT 1`. If Neo4j
is unavailable, report this step as not performed — the unit tests in Phase 7 are
the gate.

### Phase 4 — Helpers: the modal payload and the peek's new sentence

**4a.** `src/app/dash_app/pages/timeline/helpers.py` — replace
`_popup_headline` (line 463) with a shared sentence builder, and add the modal
payload builders. The lane's display name is **not** on the event, so it is
passed in:

```python
def detail_sentence(event: dict[str, Any], lane_label: str) -> str:
    """Return the card's full sentence: ``<subject> <relationship> <object>``.

    The card elides the subject into the sticky lane header, so ``lane_label``
    supplies it here.  The object's name prefers the resolved ``related_name``
    and falls back to ``related_id`` — the same chain ``card_secondary`` uses.
    Returns a fragment (never empty) so both the modal header and the hover peek
    can render it unconditionally.
    """
    subject = (lane_label or "").strip()
    relationship = humanize_relationship(str(event.get("relationship_type") or ""))
    obj = card_secondary(event)
    if not relationship:
        relationship = entity_type_label(str(event.get("entity_type") or ""))
    parts = [part for part in (subject, relationship, obj) if part]
    return " ".join(parts) or "Event"
```

**Careful**: `card_secondary` returns the *other side's name alone*. Read it
before assuming it includes a type label.

**4b.** `popup_fields` (line 512) — Decision 14. Change the headline source and
add the click hint. The payload key stays `summary` so the existing clientside
`build()` keeps working **without a JS change**, but its value is now the
sentence:

```python
def popup_fields(
    event: dict[str, Any], datetime_text: str, lane_label: str = ""
) -> dict[str, Any]:
    """Build the JSON payload carried on each card for the hover popup.

    ``summary`` is the same sentence the detail modal's header shows
    (``detail_sentence``), so hovering and clicking describe the event
    identically — the old ``_popup_headline`` preferred ``event["summary"]``,
    which is the *actor's* title and is frequently absent for Person-actor
    events.  ``hint`` drives the peek's muted "Click for details" affordance.
    """
    fields: dict[str, Any] = {
        "summary": detail_sentence(event, lane_label),
        "relationship": humanize_relationship(
            str(event.get("relationship_type") or "")
        ),
        "entity_type": entity_type_label(str(event.get("entity_type") or "")),
        "source": str(event.get("source") or ""),
        "datetime": datetime_text,
        "hint": "Click for details",
    }
    url = event.get("url")
    if isinstance(url, str) and url:
        fields["url"] = url
    return fields
```

Keep the `lane_label` parameter **defaulted** so existing call sites and tests
that pass only two arguments keep working.

**4c.** Add the modal payload builder, also in `helpers.py`:

```python
def detail_payload(event: dict[str, Any], lane_label: str, lane_wba_id: str,
                   datetime_text: str, scope: str) -> dict[str, Any]:
    """Build the JSON payload carried on each card for the detail modal.

    Everything the modal needs to render its header and issue its one Neo4j
    fetch, with no second round trip.  In ``history`` scope there is no other
    side (``lane_role`` is None), so ``related_wba_id`` is None and the modal
    renders a single panel.
    """
    related = event.get("related_wba_id")
    # ``entity_type`` is the OTHER side's type, so the lane's own type comes
    # from the API's ``lane_entity_type`` in activity scope, and from
    # ``entity_type`` in history scope (where the lane entity IS the event).
    lane_type = (
        str(event.get("entity_type") or "")
        if scope == "history"
        else str(event.get("lane_entity_type") or "")
    )
    return {
        "lane_wba_id": lane_wba_id,
        "lane_label": lane_label,
        "lane_entity_type": lane_type,
        "related_wba_id": related if isinstance(related, str) and related else None,
        "relationship": humanize_relationship(
            str(event.get("relationship_type") or "")
        ),
        "datetime": datetime_text,
        "scope": scope,
    }
```

`lane_entity_type` comes from the field added in Phase 1b — do **not** infer it
in the UI. In particular do not try to derive it from `lane_role`: `lane_role`
tells you *which side* the lane was on, not what type that side is. Getting this
wrong silently skips the Person hop in Phase 3b, so merged Person lanes render
"Not found" while every test stays green.

**Why `lane_entity_type` is a server field and not a UI inference**: in
`_action_to_event` (`src/app/api/activity/v1/service.py:184-190`) the line
`other_type = action.target_entity_type if is_actor else action.actor_entity_type`
proves the actor and target types are both known server-side and that
`entity_type` is deliberately the *other* one. The lane's own type is the
complementary branch, which is exactly the keyword-only `lane_entity_type`
parameter already passed into `_action_to_event` from `_fetch_lane`. Passing it
through (Phase 1c) is one line and removes all inference from the UI.

**Verify**
```
pytest -m unit tests/test_activity_timeline_ui_helpers.py -q
mypy src/ && pylint src --score=y
```
The existing `popup_fields` test asserts the **old** headline
(`with_url["summary"] == "Reviewed PR"`, line 383) and **will fail** — updating
it is Phase 7's job. That failure is expected; do not revert the change.

### Phase 5 — UI: the card trigger and the modal

**5a.** `layout.py`, `build_event_card` — Decision 2 and 14. Change the return
from `html.A` to `html.Div`, drop `href`/`target`/`rel`/`title`, and carry the
richer detail payload. `build_event_card` needs the lane's label and wba id, so
extend its signature and thread them through `build_cell` → `build_grid_body`
(the same pattern Plan 043 used for `scope`).

```python
def build_event_card(
    event: dict[str, Any],
    lane_color: str,
    type_color: str,
    *,
    scope: str = "activity",
    lane_label: str = "",
    lane_wba_id: str = "",
) -> html.Div:
```

and at the end:

```python
    payload: Any = {
        "data-timeline-event": json.dumps(
            # ``lane_label`` is REQUIRED here, not optional: it is the sentence's
            # subject.  Omitting it yields "<relationship> <object>" with no
            # subject — the exact failure Decision 14 exists to prevent.
            popup_fields(
                event,
                _format_full_datetime(event.get("event_time")),
                lane_label,
            )
        ),
        "data-timeline-detail": json.dumps(
            detail_payload(
                event,
                lane_label,
                lane_wba_id,
                _format_full_datetime(event.get("event_time")),
                scope,
            )
        ),
    }
    return html.Div(
        lines,
        className="timeline-card",
        style={**card_style, "cursor": "pointer"},
        **payload,
    )
```

**Do not remove the card's two-line body.** `cursor: pointer` replaces the link
cursor the anchor used to give.

**5a-ii. Remove every trace of the deleted `_popup_headline`.** Phase 4a deletes
that function, but `layout.py` imports it (line 24, inside the
`from app.dash_app.pages.timeline.helpers import (...)` block) and calls it:

```python
    title_text = _popup_headline(event)     # layout.py:615
```

Leaving either in place is a `NameError`/`ImportError` at render time. So:

- Delete `_popup_headline` from `layout.py`'s helper import block.
- Delete the `title_text = ...` line **and** its two preceding comment lines.
- The `title=title_text` keyword is already gone with the `html.A` → `html.Div`
  change in 5a.

**5a-iii. Give the card a keyboard affordance (Decision 2's cost).** The card was
an `html.A`, so it was focusable and Enter-activatable, and
`.timeline-card:focus-visible` (`assets/executive-dashboard.css:2054-2059`) styled
that focus. An `html.Div` has none of that. Preserve it:

```python
    return html.Div(
        lines,
        className="timeline-card",
        style={**card_style, "cursor": "pointer"},
        role="button",
        tabIndex=0,
        **payload,
    )
```

and extend the delegated `keydown` listener in `callbacks.py` (the existing one
at ~line 1099) so Enter/Space on a focused card opens the modal. Factor that out
rather than duplicating the click body:

```javascript
            function openDetail(card) {
                var raw = card.getAttribute('data-timeline-detail');
                if (!raw) { return false; }
                var data;
                try { data = JSON.parse(raw); } catch (e) { return false; }
                ... set_props calls ...
                return true;
            }
            document.addEventListener('click', function(ev) {
                var card = cardFrom(ev.target);
                if (card) { openDetail(card); }
            });
            document.addEventListener('keydown', function(ev) {
                if (ev.key !== 'Enter' && ev.key !== ' ') { return; }
                var card = cardFrom(ev.target);
                if (card && openDetail(card)) { ev.preventDefault(); }
            });
```

Keep `focusin` working too: the existing popup `focusin` listener already handles
a focused card, and now that the card is focusable it will fire — which is the
desired behaviour (focus shows the peek). Do **not** remove the `focusin` /
`focusout` listeners.

**5a-iv. Thread the lane label.** `build_cell` already receives `lane_key` — pass
`lane_label=<the lane's display label>` and `lane_wba_id=lane_key` down to every
`build_event_card`. `build_grid_body` has the lane dicts in `lanes`; build a
`{wba_id: label}` map beside the existing `lane_ids`
(`lane_ids = [str(lane.get("wba_id") or "") for lane in lanes]`, line 751) and
pass the label for each `wba_id`.

- **pylint**: `build_cell` and `build_grid_body` already carry
  `# pylint: disable=too-many-arguments`; if the count trips again, extend that
  disable rather than restructuring.
- The label map must include a fallback for a lane missing from the dict —
  `.get(wba_id, "")` is fine, since `detail_sentence` treats an empty subject as
  "no subject" rather than rendering a stray space.

**5b.** `layout.py` — add the modal skeleton to the page root, beside the
existing popup portal (Step 5a's Decision 1 keeps the portal). Mirror
`_render_test_results_modal` (Phase "Current state"):

```python
DETAIL_MODAL_ID = "timeline-detail-modal"
DETAIL_TITLE_ID = "timeline-detail-title"
DETAIL_STORE_ID = "timeline-detail-store"
DETAIL_PANELS_ID = "timeline-detail-panels"
DETAIL_GRAPH_LINK_ID = "timeline-detail-graph-link"
```

```python
            dcc.Store(id=DETAIL_STORE_ID, storage_type="memory", data=None),
            dbc.Modal(
                [
                    dbc.ModalHeader(
                        [
                            # The whole sentence the card fragments.  Children
                            # are filled by the clientside set_props in step 5d
                            # so the modal opens with a populated header and no
                            # round trip; the panels fill behind the spinner.
                            dbc.ModalTitle("", id=DETAIL_TITLE_ID),
                            # The Graph deep-link (Decision 8) — a NEW TAB.  Its
                            # href is set clientside from the card payload,
                            # because it embeds a URL-encoded Cypher query.
                            html.A(
                                [html.I(className="fas fa-diagram-project me-1"),
                                 "Open in Graph"],
                                id=DETAIL_GRAPH_LINK_ID,
                                href="#",
                                target="_blank",
                                rel="noopener noreferrer",
                                className="timeline-detail-graph-link ms-auto me-3",
                            ),
                        ],
                        close_button=True,
                    ),
                    dbc.ModalBody(
                        dcc.Loading(
                            type="circle",
                            children=html.Div(id=DETAIL_PANELS_ID),
                        )
                    ),
                ],
                id=DETAIL_MODAL_ID,
                size="xl",
                scrollable=True,
                is_open=False,
            ),
```

- `dbc.ModalHeader(..., close_button=True)` supplies the ✕; `ms-auto` pushes the
  link to the right, before the close button.
- The body starts **empty** — no placeholder builder is needed, because the
  clientside branch sets `is_open` and the server callback fills the panels
  within the same tick. Do **not** invent a `build_detail_placeholder` helper;
  one does not exist and the spinner from `dcc.Loading` is the waiting state.
- `href="#"` is a deliberate initial value, immediately overwritten by step 5d
  before the modal is ever visible. It must **never** be left as `#` in
  practice — the Phase 5 manual pass checks a real href.

**5c.** `helpers.py` — add the deep-link builder. It belongs here, with the other
pure helpers, and **not** in the clientside branch: the ids are interpolated into
Cypher, so the query string is constructed **server-side** and shipped as an
opaque `graph_url` in the card payload. The browser never builds Cypher.

```python
def graph_deep_link(lane_wba_id: str, related_wba_id: str | None) -> str:
    """Return the ``/app/graph?cypher=`` URL for this event's entities.

    With a ``related_wba_id`` the query loads the two nodes and the
    relationship between them (what the modal shows); without one — history
    scope, where there is no other side — it loads the lane node and its
    immediate neighbours.  Mirrors the ``?cypher=`` shape
    ``pages/search.py:273`` uses; the Graph page reads it in
    ``handle_url_deep_link_tab`` to open the Console tab, pre-fill the query and
    auto-execute it (``graph/callbacks/right_panel.py:100-105``).

    Both endpoints are matched on the nodes' canonical ``id`` property, which is
    index-backed (``scripts/create_neo4j_indexes.py``), so neither is a scan.
    """
    if related_wba_id:
        cypher = (
            f"MATCH (a {{id: '{lane_wba_id}'}})-[r]-(b {{id: '{related_wba_id}'}}) "
            "RETURN a, r, b LIMIT 50"
        )
    else:
        cypher = (
            f"MATCH (a {{id: '{lane_wba_id}'}}) "
            "OPTIONAL MATCH (a)-[r]-(b) RETURN a, r, b LIMIT 50"
        )
    return f"/app/graph?cypher={quote(cypher)}"
```

Import `quote` from `urllib.parse` at the top of `helpers.py` (check the
existing import block first — do not duplicate an existing import).

Call it from `detail_payload` (Phase 4c) as an **always-present** key, so the
clientside branch needs no conditional:

```python
    result["graph_url"] = graph_deep_link(lane_wba_id, related_wba_id)
```

where `related_wba_id` is the already-normalised `related` local variable from
4c (a `str` or `None`).

**5d.** `callbacks.py` — extend the **existing** install-once clientside
callback (line ~972). Two additions inside the `if (!window.__timelinePopupWired)`
block, and one new delegated listener:

```javascript
            // Detail modal — the card is a plain div now, so this is the only
            // click affordance.  The header and the Graph link are set here
            // (no round trip) so the modal opens immediately with a populated
            // header; the panels are filled by the server callback on
            // timeline-detail-store.  No Cypher is built here — data.graph_url
            // is built server-side.
            document.addEventListener('click', function(ev) {
                var card = cardFrom(ev.target);
                if (!card) { return; }
                var raw = card.getAttribute('data-timeline-detail');
                if (!raw) { return; }
                var data;
                try { data = JSON.parse(raw); } catch (e) { return; }
                window.__timelinePopupHide();
                var title = [data.lane_label, data.relationship, data.datetime]
                    .filter(Boolean).join('  \\u00b7  ');
                if (window.dash_clientside && window.dash_clientside.set_props) {
                    window.dash_clientside.set_props('timeline-detail-title', {children: title});
                    if (data.graph_url) {
                        window.dash_clientside.set_props('timeline-detail-graph-link', {href: data.graph_url});
                    }
                    window.dash_clientside.set_props('timeline-detail-store', {data: data});
                    window.dash_clientside.set_props('timeline-detail-modal', {is_open: true});
                }
            });
```

`set_props` on `timeline-detail-store` fires the server callback; `is_open` is
owned solely by this branch (never by the server).

Add the click hint to the peek's `build(data)`:

```javascript
                if (data.hint) {
                    frag.appendChild(make('div', 'timeline-popup-hint', data.hint));
                }
```

**5e.** `callbacks.py` — the server callback that fills the panels:

```python
@callback(
    Output("timeline-detail-panels", "children"),
    Input("timeline-detail-store", "data"),
    prevent_initial_call=True,
)
def render_detail_panels(payload: dict[str, Any] | None) -> Any:
    """Fetch both entities' Neo4j properties and render the side-by-side panels."""
```

Its body:

1. `if not payload: return no_update`
2. Build the lookup id for the left panel with
   `graph_lookup_id(payload["lane_wba_id"], payload["lane_entity_type"])` and
   use `payload["related_wba_id"]` for the right.
3. `fetch_node_properties([left, right])`, wrapped in
   `try/except NodePropertiesError` → return a single empty state
   (`create_alert("Could not load properties for this event.", color="danger")`
   is acceptable — but prefer the inline panel empty state below, so the modal
   body stays uniform).
4. Render:
   - **history** (`related_wba_id is None`): one panel, full width, using
     `render_visible_properties` on the left node; if the node is missing, the
     "Not found in graph" state.
   - **activity**: a `html.Div(className="timeline-detail-grid")` containing
     `left_panel`, `connector`, `right_panel`, where each panel is
     `render_visible_properties(node_data)` or `_not_found(wba_id)`, and the
     connector is
     `html.Div([html.I(className="fas fa-link", title=relationship)], className="timeline-detail-connector")`.
     **The connector is non-directional** (Decision 7) and its `title` carries
     the relationship for hover parity.
     Use `fas fa-link` — a core Font Awesome icon, so it is definitely present in
     the pinned `font-awesome/6.4.0` build (`dash_app/layout.py:30`). If it does
     not render, `fas fa-share-nodes` (used at `analytics/registry.py:32`) is a
     proven-in-repo fallback. Confirm the icon is visible in the Phase 5 manual
     pass — a silently blank glyph is easy to miss.

5. **Only the panel body is replaced** — never `is_open`. The clientside branch
   owns `is_open`, so it must never be a server `Output` (two owners would fight
   on every remount).

`_not_found(wba_id)` returns the muted block:

```python
def _not_found(wba_id: str) -> html.Div:
    """Per-panel state when the entity has no node in Neo4j."""
    return html.Div(
        [
            html.Div("Not found in graph", className="timeline-detail-missing-title"),
            html.Div(wba_id, className="timeline-detail-missing-id"),
        ],
        className="timeline-detail-missing",
    )
```

**5f.** `layout.py` — register nothing new in `pages/timeline/__init__.py`
(`from . import callbacks  # noqa: F401`) already covers the new module-level
`@callback`. **Do not skip this check**: with
`suppress_callback_exceptions=True` a missing import fails silently.

**5g.** `assets/executive-dashboard.css` — add the layout rules. Use tokens only:

```css
/* Activity Timeline — event detail modal */
.timeline-detail-grid {
    display: flex;
    align-items: flex-start;
    gap: var(--spacing-xsmall);
}

.timeline-detail-panel {
    flex: 1 1 0;
    min-width: 0;   /* allow the table to shrink instead of overflowing */
}

.timeline-detail-connector {
    flex: 0 0 auto;
    align-self: center;
    padding: 0 4px;
    color: var(--color-gray-medium);
    font-size: 14px;
}

.timeline-detail-caption {
    font-size: 10px;
    color: var(--color-gray-medium);
    text-transform: uppercase;
    letter-spacing: 0.7px;
    margin-bottom: 6px;
}

.timeline-detail-missing {
    padding: 12px 0;
    font-style: italic;
    color: var(--color-gray-medium);
    font-size: 12px;
}

.timeline-detail-missing-id {
    margin-top: 4px;
    font-family: 'Inter', sans-serif;
    font-size: 10px;
    word-break: break-all;
}

/* The Graph deep-link in the modal header (Decision 8) — opens a new tab. */
.timeline-detail-graph-link {
    font-family: 'Inter', sans-serif;
    font-size: 12px;
    color: var(--color-navy);
    text-decoration: none;
    white-space: nowrap;
}

.timeline-detail-graph-link:hover {
    text-decoration: underline;
}

.timeline-popup-hint {
    margin-top: 6px;
    font-size: 10px;
    color: var(--timeline-popup-muted);
    opacity: 0.85;
}
```

One **shared** body scroll (Decision 13) means nothing scrolls individually —
`scrollable=True` already gives `ModalBody` its own scroll, and the two panels
grow together. Do **not** add per-panel `max-height`/`overflow`.

**Verify — machine-checkable (the gate)**
```
pytest -m unit tests -q
mypy src/ && pylint src --score=y
```

**Verify — manual, operator-run (NOT a gate; do not block on it).** With
`TIMELINE_MOCK_SCENARIO=even` in `.env` and
`docker compose up -d --force-recreate app`, open `/app/timeline`:
- Click a card → the xl modal opens **immediately** with the sentence in the
  header, then the panels fill.
- The header's Graph link opens `/app/graph` **in a new tab** with the subgraph.
- Both panels show properties in the shared `.details-prop-row` style; long WBA
  ids wrap rather than overflow; the copy icons and the connector glyph render
  (a missing icon is an empty box, not an error).
- Because mock lane ids match no real node (Decision 15), both panels show
  "Not found in graph" — and the console shows **zero** Neo4j calls beyond the
  one `/graph/execute`.
- Hovering the same card still shows the peek, now with the sentence and the
  "Click for details" hint, and **no** native tooltip.

If a browser or the app is unavailable, report this step as not performed — do
not mark the phase failed, and do not improvise a substitute.

### Phase 6 — Mock data: make the feature demonstrable

`src/app/api/activity/v1/mock_data.py`. Today `_materialize` (line 323) builds
`TimelineEvent` with no `related_id`, `related_name`, `related_wba_id` or
`lane_role`.

**Two facts to know before you start** (both verified against the live file):

1. **There is no lane-id builder.** Mock lane ids come from the *caller* —
   `build_timeline` iterates `request.wba_ids` (line 419-421) and
   `_lane_identity` (line 168-181) merely **parses** the id it is given. The only
   literal `mock::` ids in the module are the `_SUGGESTION_CATALOGUE` entries
   (line 455-464). So "change the lane-id builder" is not a thing; the ids to
   change are the catalogue entries.
2. **`_materialize` already has a `lane_entity_type` parameter** (line 328),
   holding the lane's own type. Pass it through; do not re-derive it.

**6a.** Change the six `_SUGGESTION_CATALOGUE` ids (line 455-464) from
`mock::<Type>::<id>` to `wba::other::<Type>::<id>` — e.g.
`("wba::other::Person::alice", "Alice Johnson", "Person", "github", ...)`.

- `api/activity/v1/service.py`'s `parse_wba_id` accepts any `a::b::c` triple, so
  no validation change is needed.
- `wba::other::` is a **reserved namespace that matches no real node id**, so
  mock cards deterministically exercise the per-panel "Not found in graph" state
  with **zero** Neo4j traffic. That is the point: mock mode stays fully offline.
- The label/avatar logic in `_lane_identity` keys off the **parsed** entity type,
  not the source, so `Person` lanes keep their avatars.

**6b.** Update the tests that hardcode the old ids. **Four** test files contain
the literal `mock::` (verified):

```
tests/test_activity_api_integration.py
tests/test_activity_timeline_callbacks.py
tests/test_activity_timeline_mock.py
tests/test_activity_timeline_ui_helpers.py
```

Run `grep -rn '"mock::' tests/*.py` and fix **every** hit — a missed one is a
failing test, not a silent pass. Note that in
`test_activity_timeline_callbacks.py` many of these are *selection fixtures*
(`_ALICE = _selection_item("mock::Person::alice", "Alice")`) that never reach
`parse_wba_id`; they still must be updated for consistency, but only the ones
that flow into `build_timeline` affect behaviour. If updating a fixture-only id
would churn an unrelated assertion, leave that one and note it — the gate is the
`pytest -m unit tests -q` run below. **These four files are added to this plan's
Scope for exactly this edit.**

**6c.** In `_materialize`'s **activity** branch (line 353), populate the new
fields:

```python
        else:
            relationship = spec.relationship
            summary = spec.summary
            entity_type = spec.other_type
            details = {}
            related_id = f"mock-other-{lane_index}-{index}"
            related_name = f"Mock {spec.other_type} {index}"
            related_wba_id = f"wba::other::{spec.other_type}::{related_id}"
            lane_role = "actor"
```

and pass `related_id=related_id, related_name=related_name,
related_wba_id=related_wba_id, lane_role=lane_role,
lane_entity_type=lane_entity_type` into the `TimelineEvent`. The **history**
branch keeps `related_*` at their `None` defaults (there is no other side) but
sets `lane_entity_type=lane_entity_type`.

**Do not** add `related_*` fields to `_Spec`: the mock's value is its
*geometric* scenarios. Deriving them in `_materialize` keeps `_Spec` untouched.

**Verify**
```
pytest -m unit tests -q
grep -rn "mock::" tests/ src/     # → only the new "wba::other::" ids, no bare "mock::"
```
Then confirm mock output carries the fields and the id is the reserved form:
```
TIMELINE_MOCK_SCENARIO=even PYTHONPATH=src python -c "
from app.api.activity.v1 import mock_data
from app.api.activity.v1.model import TimelineRequest
r = mock_data.build_timeline(
    TimelineRequest(wba_ids=['wba::other::Person::alice']), 'even'
)
e = r.lanes[0].events[0]
print(r.lanes[0].wba_id, e.related_wba_id, e.related_name, e.lane_role,
      e.lane_entity_type)
"
```
Expect a lane id starting `wba::other::`, and a non-None
`related_wba_id` / `related_name` / `lane_role` / `lane_entity_type`.

### Phase 7 — Tests and documentation

**7a.** `tests/test_activity_api_integration.py` — the fake session returns
`(action, related_name)` pairs today; it will break on the three-tuple. Update
the fake to return `(action, related_name, related_wba_id)` and add assertions:
`related_wba_id` is the **other** side's canonical id in **both** directions,
and is `None` for history.

**7b.** `tests/test_activity_person_identity.py` — the three `_action_to_event`
call sites (keyword style) need the third positional argument (`None` is fine;
those tests assert only on `event.entity_type`). The two compiled-SQL counts
(`TestActionsPredicate`) may shift by the new `concat` column — re-measure with
the file's own `where = sql.split("FROMactivity_actionsWHERE", 1)[-1]` pattern
and update the numbers. **Do not delete or `xfail` them** — the
disjunct-per-identity property is the fix from `90c9674`.

**7c.** `tests/test_activity_timeline_detail_modal.py` (**create**) —
`pytestmark = pytest.mark.unit`. Cover, with no network and no Neo4j:

- **The Cypher is a single statement and indexed**: assert
  `_NODE_PROPERTIES_CYPHER` contains `IN $ids` and does not contain `UNION`.
- **`graph_lookup_id`**: a Person id hops to `::IdentityMapping::`; a
  non-Person id is returned unchanged; a Person id already containing
  `::IdentityMapping::` is not double-rewritten.
- **`render_properties_table` parity**: the same `(key, value)` list rendered
  through `render_properties_table` and through `build_element_properties_content`
  produces the same `details-prop-row` rows (parse both `str(...)` outputs and
  compare the row count and the key/value text) — this is the regression pin for
  Decision 5, and it must fail if someone re-forks the table.
- **`render_visible_properties`**: `_display_name` and `None` values are hidden;
  an `id` row is injected first; a node with nothing visible renders the "No
  properties" state.
- **`detail_payload`**: activity carries a non-None `related_wba_id`; history
  carries `None`; the payload is JSON-serializable (`json.dumps` must not raise).
- **`detail_sentence`**: subject + humanized relationship + object; falls back to
  the entity type when there is no relationship; never returns `""`.

**7d.** `tests/test_activity_timeline_ui_helpers.py` — update
`test_popup_fields_from_event` (line 366): the headline is now the sentence, and
`hint` is present. Add a case asserting the headline uses `related_name` in
preference to the raw `summary` — the whole point of Decision 14.

**7e.** `docs/design/activity-timeline-design.md`:
- §5.1 `TimelineEvent` shape — add `related_wba_id` **and** `lane_entity_type`,
  stating why the latter exists (`entity_type` is the other side's type, and the
  Person→IdentityMapping hop needs the lane's own).
- §5.3 — note that the sibling's canonical id is now carried on the event.
- §7.4 Cards & interaction — replace the two-line card bullet's **interaction**
  half: the card is no longer a link; clicking opens the event detail modal. Add
  a new subsection describing the modal (header sentence, the Graph deep-link in
  a new tab, the two shared-renderer panels, the neutral connector, current-state
  semantics, the history single-panel case, and the per-panel not-found state).
  State explicitly that the modal's tables are rendered by the **same** function
  as the Graph right panel.
- §11 Source map — add `tests/test_activity_timeline_detail_modal.py`.

**Verify**
```
pytest -m unit tests -q
mypy src/
pylint src --score=y
bandit -c .bandit.yml -r src/ -lll
PYTHONPATH=src python scripts/generate_signal_activity_spec.py && git diff --stat docs/design/spec-activity-signal.md
```
The last command must produce **no diff** — nothing in
`src/common/activity_signal/` changed. If it differs, STOP: a schema change
slipped in that this plan did not intend.

## Test plan

| File | New/updated | Cases |
|---|---|---|
| `tests/test_activity_timeline_detail_modal.py` | **create** | Cypher shape; `graph_lookup_id`; table-renderer parity; visible-property filtering; `detail_payload` for activity + history; `detail_sentence` |
| `tests/test_activity_timeline_ui_helpers.py` | update | `popup_fields` headline is the sentence + `hint`; `related_name` beats `summary` |
| `tests/test_activity_api_integration.py` | update | fake returns 3-tuples; `related_wba_id` correct in both directions; `None` for history |
| `tests/test_activity_person_identity.py` | update | 3 call sites take the new positional; re-measured SQL counts |

Model the new test module structurally on
`tests/test_activity_timeline_ui_helpers.py` (module docstring, `pytestmark`,
small pure-function tests, no fixtures).

**Accepted coverage gaps (do not "fix" them).**
- Nothing automated pins the clientside click/keydown branch or the modal's
  `is_open` handoff — there is no JS test harness in this repo. Covered by the
  Phase 5 manual check. The two halves are deliberately kept thin for this
  reason. The **card's `role`/`tabIndex` and the keyboard branch** are in the
  same category: pin what you can in Python (`build_event_card` returns a `Div`
  whose `role` is `"button"` and whose `tabIndex` is `0`, and whose props carry
  `data-timeline-detail`) and leave the JS to the manual pass.
- Nothing automated pins the Graph deep-link URL. `graph_deep_link` **is** a pure
  function, so test it: assert the returned string starts with
  `/app/graph?cypher=`, that `unquote`-ing the remainder round-trips to the
  expected Cypher, and that the related-id form contains both ids while the
  history form contains only the lane id.
- Nothing automated pins the clientside `set_props` header. Same reason.
- If the client-facing half is ever found broken, the place to start is the
  slice of the clientside function in `callbacks.py`.

## Done criteria

Machine-checkable. ALL must hold:

- [ ] `pytest -m unit tests -q` exits 0, including the new module.
- [ ] `mypy src/` exits 0 (strict).
- [ ] `pylint src --score=y` reports **≥ 9.0** (read the number; the command
      exits non-zero even at 9.68).
- [ ] `bandit -c .bandit.yml -r src/ -lll` reports no High severity.
- [ ] `PYTHONPATH=src python scripts/generate_signal_activity_spec.py` leaves
      `docs/design/spec-activity-signal.md` with **no diff**.
- [ ] `grep -rn "_panel_properties_table" src/` returns **no matches**.
- [ ] `grep -rn "href=\"/app/graph\"" src/app/dash_app/pages/timeline/` returns
      **no matches** (the card is no longer a link).
- [ ] `grep -rn "title=title_text\|_popup_headline" src/app/dash_app/pages/timeline/`
      returns **no matches** — the native tooltip is removed, and the deleted
      `_popup_headline` is no longer imported or called by `layout.py`.
- [ ] `grep -rn "build_detail_placeholder" src/` returns **no matches** (no
      such helper was invented).
- [ ] The card is keyboard-reachable: `build_event_card` returns an `html.Div`
      with `role == "button"` and `tabIndex == 0`, and carries both
      `data-timeline-event` and `data-timeline-detail`. Pin this in
      `tests/test_activity_timeline_detail_modal.py` by calling
      `build_event_card` directly and asserting the three attributes.
- [ ] `graph_deep_link` is unit-tested for both the related-id and the
      lane-only form (see the accepted-coverage-gaps note).
- [ ] `build_element_properties_content` renders identically to before Phase 2
      (the existing Graph/Collaboration-Network tests pass, or the
      before/after string diff is empty).
- [ ] `TimelineEvent` carries `related_wba_id` and `lane_entity_type`; both are
      non-None for an activity event and `None` for history.
- [ ] `lane_entity_type` is populated from the server (`_action_to_event`'s
      parameter), **not** inferred in `helpers.py` —
      `grep -rn "lane_entity_type" src/app/dash_app/pages/timeline/` shows only
      reads of the event dict, never a derivation.
- [ ] No file outside the `## Scope` table is modified (`git status --short`).
- [ ] `plans/README.md` status row updated.

## STOP conditions

Stop and report back — do not improvise — if:

- **Plan 043 has not landed**: `TimelineEvent` has no `lane_role` /
  `related_id` / `related_name`, or `helpers.card_primary` does not exist, or
  `activity_actions` has no `target_source` column. This plan cannot be executed
  without it.
- **`_action_to_event`'s `lane_entity_type` parameter turns out to mean
  something other than the lane's own entity type.** Phase 1c passes it straight
  through as the new `lane_entity_type` field. Before doing so, read
  `service.py:184-190` and confirm `is_actor` compares `action.actor_entity_type`
  against it — i.e. it *is* the lane's type. If the code says otherwise, stop
  rather than guessing a derivation.
- **`mypy src/` rejects the three-tuple return type** after a genuine attempt at
  the unpacking form in Phase 1. Use an explicit `cast(...)` if that resolves
  it; if it still fails, stop. **Never** fall back to `.scalars()` — it silently
  drops `related_name` and `related_wba_id`, and because both are optional
  nothing raises.
- **`render_properties_table`'s body has to change** to make the modal work, or
  `build_element_properties_content`'s rendered output changes in Phase 2. That
  phase is a pure rename + wrapper for the Graph page; **any** visual change
  there is a regression on a surface this plan is not allowed to alter. If the
  modal's columns need different value formatting, that is its own problem to
  solve in `render_visible_properties` (which may post-process the `(key, value)`
  list before delegating) — not by editing the shared table.
- **The properties query returns more rows than nodes requested**, or a Person
  lookup returns an IdentityMapping node instead of the Person. The
  `coalesce`/`DISTINCT` shape is load-bearing.
- **`is_open` ends up with two owners** (a server callback and the clientside
  branch both writing it). The clientside branch owns it; the server owns only
  `timeline-detail-panels.children`.
- **The spec regeneration produces a diff** — a signal-schema change slipped in.
- **A step requires editing a file not in the `## Scope` table.** That is a plan
  defect, not a judgement call.
- **The code at a cited location does not match the excerpt** in `## Current
  state` — the repo has drifted. (This is genuine drift, not staleness: the
  excerpts were taken from the live tree at `202e763`.)

## Maintenance notes

**What future changes will collide with this**

- `render_properties_table` is now the **single** `(key, value)` table renderer
  for three surfaces (Graph right panel, Collaboration Network right panel,
  Timeline detail modal). Changing its value heuristics changes all three — that
  is the intent (Decision 5), but it means a style tweak for one surface must be
  checked against the other two. Its body is deliberately **untouched** by this
  plan.
- `_PANEL_NODE_EXCLUDE_KEYS` is now shared by the graph panel and the modal, so
  a key added to one surface's hidden set hides it on both. That is intended
  parity; add per-surface filtering in `render_visible_properties` instead if a
  future modal needs to show something the graph panel hides.
- The card carries **two** JSON payloads (`data-timeline-event` for the peek,
  `data-timeline-detail` for the modal). They overlap by design — the peek is
  cheap and offline, the modal's `graph_url` is server-built. If they ever
  diverge in what they say about the same event, the peek's `detail_sentence` is
  the shared source of truth for the wording; keep it that way.
- **Keyboard parity is now manual**: the card is a `role="button"` div, so the
  Enter/Space branch in the clientside listener is what makes it operable. If
  that listener is ever rewritten, re-check keyboard access.
- `build_element_properties_content` still owns the graph panel's *chrome*
  (per-panel header, Expand Node button). The modal deliberately does not use it.
  If a future surface wants the graph panel's chrome **and** the modal's chromeless
  body, that is the moment to reconsider, not before.
- `_NODE_PROPERTIES_CYPHER` mirrors `api/activity/v1/identity.py`'s Person hop in
  a second place. If the Person↔IdentityMapping model changes (e.g. MAPS_TO stops
  being undirected), both must change together — see
  `docs/design/RELATIONSHIPS_DESIGN.md`.
- Adding a new entity type whose canonical id is not
  `{source}::{entity_type}::{id}` breaks both `related_wba_id` and
  `graph_lookup_id`.
- The `is_open` / `timeline-detail-store` split is the modal's contract: the
  clientside branch never fetches, and the server never opens. Preserve it or
  the modal either blocks on the round trip or fights itself on remount.

**What a reviewer should scrutinize**

- That `fetch_actions_for_entity` ends in `result.all()` with **three** columns,
  and that `fetch_event_history` still uses `.scalars()`.
- That `build_element_properties_content`'s rendered output is unchanged — diff
  its `str(...)` before and after.
- That the modal's table is genuinely `render_properties_table` and not a
  re-implementation.
- That the connector has **no** direction arrow.
- That no file under `src/connectors/` and no `src/common/activity_signal/` file
  was touched.
- That the properties fetch is exactly **one** HTTP call per click (check the
  browser network tab in the manual pass).

**Deliberately deferred (out of scope)**

- **`GraphNode.display_name()`'s commit gap** (`src/connectors/neo4j_db/node_base.py:58`):
  the same four-word lookup Plan 043 fixed in the writer, still present on the
  graph side, so the **Graph page** shows SHAs for commits. Same defect,
  different surface (its own callers, tests and Cypher properties). Worth its own
  plan. This plan **reuses** the graph-side renderer, so the modal will show a
  commit's SHA in its `id` row and its `message` in a `message` row — consistent
  with the Graph page, which is the point, but it means the modal does **not**
  launder the graph's naming defect.
- Backfilling `activity_events.display_name` or `activity_actions.target_source`
  — unchanged from Plan 043's stance.
- Resolving a *mention-only* person (no `IdentityMapping`) — unchanged from the
  accepted limitation in the timeline design doc §5.3.8.
- The `details` attribute snapshot: `TimelineEvent.details` is `{}` for activity
  events, so no event-time property panel is possible for the other side, which
  is why Decision 12 chose current-state semantics for both.
- Mobile interactions, per-lane event totals, keyboard focus management inside
  the modal beyond `dbc.Modal`'s built-in behaviour.

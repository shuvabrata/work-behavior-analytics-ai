# Plan 044: Activity Timeline — event detail modal

> **Executor instructions**: Follow this plan step by step. Do not commit, push, or
> open a PR — leave changes in the working tree and report them. Run the `Verify`
> commands as you go; they are the acceptance check for each step.
>
> **Drift check (run first)** — check **both** committed and uncommitted drift:
> ```
> git diff --stat d77db38..HEAD -- src/app/dash_app/pages/timeline/ \
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
> **Note on the base commit**: `d77db38` is "Make timeline cards line ordering
> correct (#339)" — the card-reading-order change, **squash-merged to `main`**.
> Its predecessor `90c9674` (#338, the Person-identity lane expansion) was the
> base it was written against.
>
> The baseline was originally stamped as `202e763` (the same change on the
> now-merged `feature/timeline-card-readability` branch). That commit is **not**
> an ancestor of `main` — it exists only on that branch — so the stamp was moved
> to `d77db38`, which **is** on `main` and is content-identical for every
> in-scope path (verified: `git diff --stat 202e763 d77db38 -- <in-scope paths>`
> is empty, and `git diff --stat d77db38..HEAD -- <in-scope paths>` gives the
> same answer the old stamp did). Use `d77db38` for drift detection.
>
> Verified at `d77db38`: the tree contains `helpers.card_secondary` and the
> `add_activity_actions_target_source` migration. Its migration is **applied**:
> `alembic current` reports `51d673fb286f (head)` and
> `activity_actions.target_source` (`varchar(32)`) exists.
>
> This plan builds directly on that change: it assumes `TimelineEvent` already
> carries `lane_role`, `related_id` and `related_name`, that
> `helpers.card_primary` / `card_secondary` exist, and that
> `activity_actions` has the `target_source` column. If any of those are absent,
> **that is a STOP condition** — the change has been reverted or the branch
> moved, and this plan cannot be executed.

## Status

- **Priority**: P1
- **Effort**: L
- **Risk**: MEDIUM (a new Dash modal + one clientside click branch; one additive
  API field; the sibling lookup carries a `MAPS_TO` branch and a re-keying step,
  which is where a silent "Not found" regression can hide — see Decision 9b)
- **Depends on**: the card-reading-order change, squash-merged to `main` as
  `d77db38` (#339)
- **Related**: `plans/045-graph-query-validator-rejects-entity-ids.md` — a
  pre-existing defect in the Graph deep-link path this plan newly routes through.
  **Not a dependency**: 045 is a problem statement only, and 044 must not wait on
  it nor fix it.
- **Category**: direction (UX — the card is a fragment; the modal is the full sentence)
- **Planned at**: commit `d77db38` (originally stamped `202e763`; see the base-commit
  note above), 2026-10-17. Drift check verified clean at review time.
- **Revised**: 2026-10-17 — the API change is now a single field built in the
  service (not a query-layer column), mock data is untouched, and the click nonce
  is dropped. See Decisions 4, 7b, 15, 17.
- **Revised again**: 2026-10-17 (review) — **Decision 9 was wrong for the
  sibling** and is now split into 9a (lane: no hop) and 9b (sibling: one
  `MAPS_TO` hop). Measured on the live graph: 3 of 9 real Person sibling ids are
  not node ids, covering 58 of 382 Person-involving rows, and 11 of the 14 cards
  on the local `confluence::Page::26705923` lane. Phase 3a now fetches both
  sides in one two-branch query and **keys the result by the id requested**;
  Phase 5c's `graph_deep_link` routes Person ids through `_node_pattern`. The
  pre-existing deep-link validator defect found in the same review is recorded
  separately in `plans/045-graph-query-validator-rejects-entity-ids.md` and is
  **not** fixed here.
- **Revised 2026-10-18 (post-execution)**: the first executor run hit the stop
  condition *"`lane_wba_id` turns out not to have three `::`-separated segments"*
  — 4 tests in `tests/test_activity_timeline_edge_cases.py` render hand-built
  single-segment lane ids (`"a"`) through `build_grid_body`, so Phase 5a's
  unconditional `detail_payload` call raises `ValueError`. The finding is
  confirmed (reproduced in the executor's worktree). Resolution: the fixtures are
  invalid WBA ids that never occur in production (`parse_wba_id` guarantees three
  segments), so **step 7f** makes them well-formed and that test file is added to
  Scope. No production guard is added — a type-segment-less id cannot produce a
  label-scoped `MATCH` and therefore cannot be handled without changing the query
  shape. The corresponding STOP condition is narrowed accordingly.

## Why this matters

The card-reading-order change (`d77db38`, #339) made the timeline card read as a fragment — `Mentions` /
`PullRequest · Title of an Epic` — with the subject elided into the sticky lane
header. The card is deliberately terse: two lines, ~40px, no room for detail.

There is therefore **no way to see what an event actually is**. Hovering shows a
small 300px popover with a headline, a meta line, a time and a source link, and
clicking the card navigates to `/app/graph` with no query context at all
(`href="/app/graph"`, `layout.py:629`). To see either entity's real properties a
user must leave the timeline, reach the Graph page, and search manually.

Note on scope: this plan adds **one** API field and reuses the existing graph
endpoint, the existing cytoscape transform and the existing properties table. It
does not add a shared abstraction, a mock-id convention, or client-side
freshness machinery — the *Why* for each of those omissions is in the Decisions
table (4, 7b, 15, 17).

This plan adds an **event detail modal**: click a card, get a large
(`size="xl"`) modal that reads as the complete sentence the card fragments —
subject, relationship, target — with **both entities' Neo4j properties rendered
side by side**, using the *same* table renderer the Graph page's right panel
uses, so a change to that renderer changes both surfaces.

**The two sides are looked up differently, and that asymmetry is the crux of
this design** (Decision 9a/9b). The lane's id comes from the ES-backed typeahead
and *is* its Neo4j node id. The other side's id comes from the raw
`activity_actions` row and is **provider-scoped** — when Neo4j deduped that
person onto another provider's canonical node, the provider-scoped id was never
created, so a naive lookup silently renders "Not found in graph" for a person who
is in the graph. On the local data that is **11 of the 14 cards** on the
`confluence::Page::26705923` lane. The modal therefore resolves both sides in one
query, with a `MAPS_TO` branch for Person ids, and keys the result by the id it
asked for rather than the id that came back.

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
`event["summary"]` — the *actor's* title, which `d77db38` (#339) proved wrong for
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
  `RuntimeError → HTTP 500` (`router.py:68`). An unreachable Neo4j makes the
  service raise `RuntimeError` → **HTTP 500**, not an empty payload.

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
relationship_type, summary, entity_type, source, url, details`, plus the
card-reading-order change's
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
| 3 | **Fetch both nodes with ONE `POST /api/v1/graph/execute`** carrying constant parameterized Cypher and `parameters: {ids: [...], mids: [...]}`. | No new endpoint, no new models, no new router wiring. Reuses `neo4j_to_cytoscape` and the shared table renderer. One call is possible because the Person hop is a **second branch of the same query** (Decision 9b), not a second request — the ids and their mapping ids travel together in one payload, and the result is keyed by the id **requested** (not by the `wba_id` that comes back, which legitimately differs for a deduped Person). |
| 4 | **Add one additive field `related_wba_id` to `TimelineEvent`.** | The other side's `source` is not on the event, so the sibling's WBA id cannot be built in the UI. It is assembled in `_action_to_event` from the row's own `target_source` — no query-layer change, no tuple reshaping, no SQL-count churn. |
| 5 | **Share the TABLE renderer, not the panel builder.** New `render_properties_table()` is called by both `build_element_properties_content` (graph + collaboration network) and the new modal body builder. | "A change in one affects both" without dragging the graph panel's per-panel header and dead "Expand Node" button into the modal. |
| 6 | **The modal header is the full sentence**: lane name · relationship · target name (as the Graph deep-link) · time. | The card elides the subject; the modal restores it. Neither panel needs a title, so the panels sit close together. |
| 7 | **Lane entity is the LEFT panel, always; the connector is non-directional.** | The lane is the card's subject. `d77db38` (#339) established the relation label is verbatim and neutral because `direction` is unusable — an arrow would re-assert a direction the data cannot support. |
| 7b | **The lane's entity type is derived from the lane's WBA id, not sent as a field.** | A lane id *is* `{source}::{entity_type}::{id}` (`service.py::_fetch_lane`), and `build_grid_body` already threads that id into every card as `lane_wba_id`. The other side's type is derived the same way (5c), so both sides use one idiom and the API gains one field instead of two. |
| 8 | **The Graph deep-link opens in a NEW TAB** and runs the 2-node subgraph. | Matches today's card behaviour (`target="_blank"`). The subgraph shows what the modal shows, including the edge. |
| 9 | **The LANE is looked up by its own canonical WBA id — no `IdentityMapping` hop, no label. The SIBLING is looked up through the `MAPS_TO` hop when it is a Person.** | These are two different questions and the earlier draft of this row conflated them. **(a) The lane**: a lane can only come from the ES-backed typeahead, and every Person document in ES is keyed by the canonical Neo4j id (the ES sink refuses to create a shadow document), so a lane id IS the node id — this is the property `service.py:246-249` already relies on. **(b) The sibling**: it does *not* come from the typeahead — it is built from the raw `activity_actions` row (`target_entity_id` / `actor_entity_id`), which carries the **provider-scoped** id. When a Person arrived from a second provider, Neo4j reused the canonical node and the provider-scoped id was **never created** (`person_cache.py:125-151`; `elasticsearch_sink.index_signal_with_canonical_id`, `:154-192`). So `confluence::Person::557058:…` is **not** a node id when the node is `jira::Person::557058:…`. Measured on the live graph: **3 of 9** distinct real Person sibling ids miss, covering 58 of 382 Person-involving rows (~15%) — and on the lane `confluence::Page::26705923`, **11 of its 14 events** carry a `confluence::Person::…` sibling. Without the hop the right panel reads "Not found in graph" for a person who is in the graph, and the deep link returns `nodes=0 rels=0`. The hop is therefore a **second branch of the same single query**, and the result is keyed by the id **requested** — not by the `wba_id` that comes back, which legitimately differs in exactly this case. See 3a. |
| 10 | **The modal always opens**; a missing node degrades to a per-panel "Not found in graph" note. Both missing → one empty state. A failed properties fetch → the generic *"Could not load properties for this event."* (see step 5e.3). | The header needs no network, so the click is never dead. The graph API answers **HTTP 500** for any Cypher runtime error, so a 500 must not be diagnosed as a configuration problem. |
| 11 | **History scope shows a ONE-panel modal** (no connector, no second fetch), header `<lane name> · Updated · <time>`. | `lane_role` is `None` and `related_id` is `None` in history — there is no other side. |
| 12 | **Both panels show CURRENT Neo4j state**, with a muted "current state" caption. | Neo4j holds current state; `details` is empty for activity events, so an as-of-event panel is not available for the other side. One rule for both panels. |
| 13 | **50/50 panel split, ONE shared body scroll.** | Nested scroll regions in a modal are awkward; keeping the panels aligned reads as one table pair. |
| 14 | **The peek's headline becomes the same sentence**, gains a muted "Click for details" hint, and the native `title=` tooltip is REMOVED. | The peek currently shows `event["summary"]` — the field `d77db38` (#339) proved wrong — so hovering and clicking would describe one event two ways. The native tooltip duplicates the headline ~1s later and overlaps the portal. |
| 15 | **Mock data (`mock_data.py`) is left exactly as it is — no lane-id rename, no `related_*` on `_materialize`, no `lane_role`.** The only mock-specific code in this plan is the gated branch in `detail_payload`. | Mock lane ids already resolve to no node: measured live, `MATCH (n) WHERE n.id STARTS WITH 'mock::' RETURN count(n)` is **0**, and a two-id fetch returns an empty node list. So clicking a mock card already exercises the per-panel "Not found" state with zero Neo4j traffic. The one thing mock mode lacks is a sibling id (mock events carry a sibling *type* but never a `related_id`), so `detail_payload` synthesises a three-segment placeholder under three guards — activity scope only, `mock::` lane only, no existing `related_wba_id` (see 4c). |
| 16 | **The modal body's tables are emitted through a `_detail_panel` helper** carrying `.timeline-detail-panel` and the "Current state" caption. | Decision 13's 50/50 split and Decision 12's caption are both CSS/render requirements — the class must actually be emitted or `flex: 1 1 0` + `min-width: 0` never applies and long ids push the tables apart. One helper makes both impossible to forget. |
| 17 | **`timeline-detail-store` carries the card's payload and is the only trigger for the panels.** No nonce. | The panels are a pure function of the two node ids in the payload, and the header is built from the same payload, so a byte-equal payload means an identical header *and* identical panels — nothing to correct. Dash's renderer already skips unchanged props by deep equality, so an equal payload simply does not re-fetch. `is_open` is owned by the clientside branch; the store too. |

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
| Migration (already applied) | `cd src/app && alembic current` | `51d673fb286f (head)` — the `target_source` column from `d77db38` (#339) is live |
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
| `src/app/api/activity/v1/model.py` | one additive field: `related_wba_id` | 1 |
| `src/app/api/activity/v1/service.py` | build `related_wba_id` in `_action_to_event`; pass it through `_build_event` | 1 |
| `src/app/dash_app/components/common.py` | extract `render_properties_table`; add `render_visible_properties` | 2 |
| `src/app/dash_app/pages/timeline/api.py` | `fetch_node_properties(wba_ids)` HTTP client + `_mapping_id_for`; the two-branch `_NODE_PROPERTIES_CYPHER` | 3 |
| `src/app/dash_app/pages/timeline/helpers.py` | `detail_sentence` / `detail_payload` / `graph_deep_link` / `_node_pattern`; `popup_fields` headline + hint + scope; drop `_popup_headline` | 3, 4 |
| `src/app/dash_app/pages/timeline/layout.py` | card → `Div` + `role`/`tabIndex`; modal skeleton; Graph link; drop the `_popup_headline` import | 5 |
| `src/app/dash_app/pages/timeline/callbacks.py` | click/keydown branch in the clientside listener; detail callback | 5 |
| `src/app/dash_app/assets/executive-dashboard.css` | modal layout, panel/caption/connector/missing/graph-link rules | 5 |
| `tests/test_activity_api_integration.py` | `related_wba_id` assertions (both directions, None for history) | 7 |
| `tests/test_activity_timeline_ui_helpers.py` | updated `popup_fields` test + new `detail_*` tests | 7 |
| `tests/test_activity_timeline_detail_modal.py` | **create** — cypher shape, fetch keying, panel helpers, payload builders | 7 |
| `tests/test_activity_timeline_edge_cases.py` | synthetic lane ids made well-formed (`"a"` → `"github::Person::a"`) — see 7f | 7 |
| `docs/design/activity-timeline-design.md` | §5.1, §5.3, §7.4, §11 | 7 |

**Out of scope** — do NOT touch:

- `src/common/activity_signal/` — nothing here changes the signal schema. If you
  believe it must, STOP: the spec-freshness CI gate would fail and the design is
  wrong.
- The producers (`src/connectors/producers/`), the consumer, the Neo4j sink, and
  `src/connectors/neo4j_db/node_base.py` (the `GraphNode.display_name()` commit
  gap is a **separate, known defect** — out of scope, see Maintenance notes).
- `src/app/api/graph/v1/` — `POST /graph/execute` is reused **unchanged**. In
  particular, do **not** "fix" `validate_read_only_query` here so that ids
  containing a write keyword are accepted; that defect is tracked separately in
  `plans/045-graph-query-validator-rejects-entity-ids.md` and must be decided on
  its own.
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

The UI cannot build the sibling's WBA id (the other side's `source` is not on the
event), so the server builds it. **Build it in Python, in `_action_to_event`** —
every ingredient is already on the ORM row the service holds, so the query layer
is not touched at all (no third column, no tuple reshaping, no test churn).

**1a.** *(removed — there is no query-layer change in this plan. Do **not** add a
`func.concat` column to `fetch_actions_for_entity`, and do **not** change its
return shape: `tests/test_activity_person_identity.py` asserts on its compiled
SQL, and `_fetch_lane` unpacks its 2-tuples.)*

**1b.** `src/app/api/activity/v1/model.py` — add **one** additive field to
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
```

That is the **only** new field. The lane entity's own type is **not** a field:
a lane's WBA id already *is* `{source}::{entity_type}::{id}`
(`service.py::_fetch_lane` builds it that way), `build_grid_body` already threads
that same id into every card as `lane_wba_id`, and `graph_deep_link` (5c) derives
the label from it with the same `split("::", 2)[1]` idiom it already uses for the
other side. In history scope `entity_type` is already the lane's own type
(`_event_to_event`), so no scope branch is needed either.

**1c.** `src/app/api/activity/v1/service.py`:

- `_build_event` — accept `related_wba_id: str | None = None` and pass it into
  `TimelineEvent`.
- `_action_to_event` — build the id locally and pass it through. Every ingredient
  is already computed here: `is_actor` decides the same branch the SQL `CASE` at
  `query.py:81` encodes, and `other_type` / `related_id` are already locals.
  `target_source` is the row's own column (`activity_action.py:59`), so no query
  change is needed:

```python
    is_actor = (
        action.actor_entity_type == lane_entity_type
        and action.actor_entity_id in lane_identity_ids
    )
    lane_role: Literal["actor", "target"] = "actor" if is_actor else "target"
    other_type = action.target_entity_type if is_actor else action.actor_entity_type
    related_id = action.target_entity_id if is_actor else action.actor_entity_id
    # The other side's own source: the target's when the lane is the actor, else
    # the row's own source.  Mirrors ``related_source`` in the query layer, and
    # ``target_source`` is never empty when written (activity_writer.py:134).
    other_source = (
        (action.target_source or action.source) if is_actor else action.source
    )
    return _build_event(
        ...
        related_id=related_id,
        related_name=related_name,
        related_wba_id=f"{other_source}::{other_type}::{related_id}",
    )
```

  `_action_to_event`'s signature, `_fetch_lane`'s loop and its
  `last_row = action_rows[-1][0] if action_rows else None` are all **unchanged**.
  `_event_to_event` is **unchanged**: history events keep `related_wba_id=None`
  via the `_build_event` default.

**Verify**
```
pytest -m unit tests -q
mypy src/
git diff --stat src/app/api/activity/v1/query.py     # → no output (untouched)
```
Both must be green on the first run. If `pytest` or `mypy` goes red here, the
build has been done in the wrong layer — re-read 1c rather than adjusting the
query or the tests.

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

Widen the callee's annotation first, in `_panel_build_visible_properties`
(`common.py:664`) — a ``frozenset`` is **not** assignable to a ``set[Any]``
parameter under `mypy` strict, and the body only does ``k not in exclude_keys``,
so the read-only abstraction is the honest type:

```python
# ``set`` is invariant in mypy, so a ``frozenset`` constant cannot be passed to a
# ``set`` parameter.  This is a read-only use, so take the abstract type.
def _panel_build_visible_properties(
    data: dict[str, Any], exclude_keys: AbstractSet[Any]
) -> dict[str, Any]:
```

Add ``from collections.abc import Set as AbstractSet`` to `common.py`'s imports
(the repo prefers `collections.abc` for exactly this — CLAUDE.md, "Code style").

Then the constant and the wrapper:

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
`mypy src/` must be clean. The usual cause of a failure here is the
`frozenset`/`set` invariance above (`arg-type`) — that is an **`arg-type`**
error, which the `app.dash_app.*` override does **not** suppress, so widening the
annotation is required, not optional.
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


#: One round trip for both sides.  Two branches, one call:
#:
#: * branch 1 — the id **is** a node id (every non-Person entity, and every
#:   Person whose provider identity is its canonical node).  A node that does
#:   not exist is simply absent, which is what lets the UI render a per-panel
#:   "not found" state.
#: * branch 2 — the id is a Person whose provider identity was deduped onto a
#:   *different* provider's canonical Person node, so the id is **not** a node
#:   id (Decision 9b).  ``MAPS_TO`` recovers it.  The mapping node and the
#:   ``MAPS_TO`` edge are returned alongside the Person so the caller can pair
#:   them unambiguously (a Person may have several mappings, so position is not
#:   a safe pairing key).
#:
#: Both branches must alias their columns identically — Cypher rejects a UNION
#: whose branches return different column names ("All sub queries in an UNION
#: must have the same return column names").  The ``null`` placeholders exist
#: only to satisfy that rule.
#:
#: The ``id`` property is indexed per label, so branch 1 is a scan when
#: unlabelled — see the note below.  This is deliberate.
_NODE_PROPERTIES_CYPHER = (
    "MATCH (n) WHERE n.id IN $ids RETURN n AS node, null AS mapping, null AS rel "
    "UNION "
    "MATCH (i:IdentityMapping) WHERE i.id IN $mids "
    "MATCH (i)-[r:MAPS_TO]-(p:Person) RETURN p AS node, i AS mapping, r AS rel"
)


def _mapping_id_for(wba_id: str) -> str | None:
    """Return the ``IdentityMapping`` id matching a Person WBA id, else ``None``.

    ``confluence::Person::557058:abc`` → ``confluence::IdentityMapping::557058:abc``.
    Only Person ids have a mapping branch; every other type returns ``None``.
    """
    if "::Person::" not in wba_id:
        return None
    return wba_id.replace("::Person::", "::IdentityMapping::", 1)


def fetch_node_properties(wba_ids: list[str]) -> dict[str, dict[str, Any]]:
    """Fetch node properties for each WBA id, keyed by the id **requested**.

    Returns ``{}`` for an empty input.  An id that resolves to no node is simply
    absent from the result — callers render a per-node "not found" state.

    The result is keyed by the id the caller asked for, **not** by the node that
    came back: a Person sibling is requested by its provider-scoped id but
    resolves to a canonical Person node whose ``wba_id`` differs (Decision 9b),
    so the ``data`` dict's own ``wba_id`` must not be used as the key.

    Raises :class:`NodePropertiesError` on a transport error or a non-200
    response.
    """
    ids = [str(w) for w in wba_ids if w]
    if not ids:
        return {}
    mids = [mid for mid in (_mapping_id_for(w) for w in ids) if mid]
    try:
        # Bandit's B113 only recognises literal timeouts; ours is runtime-configured.
        response = requests.post(  # nosec B113
            f"{get_api_base_url()}/api/v1/graph/execute",
            json={
                "query": _NODE_PROPERTIES_CYPHER,
                "source": "raw",
                "view": "graph",
                "parameters": {"ids": ids, "mids": mids},
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
    nodes: dict[str, dict[str, Any]] = {}
    element_to_wba: dict[str, str] = {}
    for element in elements:
        if element.get("group") != "nodes":
            continue
        data = element.get("data")
        if not isinstance(data, dict) or not data.get("wba_id"):
            continue
        nodes[str(data["wba_id"])] = data
        if data.get("id"):
            element_to_wba[str(data["id"])] = str(data["wba_id"])

    # Pair each mapping node with the Person it MAPS_TO, via the returned edge.
    # ``mapping_to_person`` is keyed by the *requested* Person id, so branch-2
    # hits land under the key the caller used.
    mapping_to_person: dict[str, dict[str, Any]] = {}
    for element in elements:
        if element.get("group") != "edges":
            continue
        data = element.get("data")
        if not isinstance(data, dict) or data.get("relType") != "MAPS_TO":
            continue
        source = element_to_wba.get(str(data.get("source")))
        target = element_to_wba.get(str(data.get("target")))
        if not source or not target:
            continue
        for a, b in ((source, target), (target, source)):
            if "::IdentityMapping::" in a and "::Person::" in b:
                requested = a.replace("::IdentityMapping::", "::Person::", 1)
                mapping_to_person[requested] = nodes[b]

    result: dict[str, dict[str, Any]] = {}
    for requested in ids:
        data = nodes.get(requested) or mapping_to_person.get(requested)
        if data is not None:
            result[requested] = data
    return result
```

Add the import: `from app.dash_app.pages.graph.utils import neo4j_to_cytoscape`.
This is a **page-level import of another page's `utils` subpackage** — permitted,
already done by `pages/timeline/callbacks.py:29` and
`pages/catalog/editor_test_callbacks.py:21`. Do not move it.

**Note on the query**: `WHERE n.id IN $ids` does **not** use the per-label `id`
indexes when the `MATCH` is unlabelled. `EXPLAIN` on the live graph:

```
MATCH (n)        WHERE n.id IN $ids RETURN n   → ProduceResults > Limit > Filter > AllNodesScan
MATCH (n:Person) WHERE n.id IN $ids RETURN n   → ProduceResults > Limit > NodeUniqueIndexSeek
```

So branch 1 is a full node scan. This is a **deliberate** trade, not an
oversight: the ids are of unknown label, and splitting them by label would mean
one `MATCH` per label (or a `UNION` per label), which costs more plans and more
query text than the scan costs at this graph's size. Do **not** "optimise" this
by dropping the `UNION` and the mapping branch — branch 2 is what makes a
deduped Person sibling resolve at all (Decision 9b). Do not add a label to
branch 1 either: the requested id's label is not known to the caller.

**3b. The Person hop is required for the sibling (Decision 9b).** A Person
**lane** id is its node id and needs no translation, but a Person **sibling**
may be a provider-scoped id whose node was never created because Neo4j deduped
the person onto another provider's canonical node. `fetch_node_properties`
handles both in one call: branch 1 covers the id-is-a-node-id case, branch 2
recovers the deduped case through `MAPS_TO`.

> **Why the earlier draft's argument was wrong.** It reasoned that "a lane is
> only ever created from the typeahead, which reads Elasticsearch, and every
> Person document in ES is keyed by the canonical Neo4j id" — so no hop. That
> premise is **true for the lane and false for the sibling**. The sibling is not
> drawn from the typeahead; it is built from the raw `activity_actions` row,
> whose `target_entity_id` / `actor_entity_id` is the **provider-scoped** id
> (`activity_writer._decompose_relationships`). When a person is seen from a
> second provider, `person_cache.get_or_create_person` reuses the existing
> canonical node by email and the second provider's Person id is never created —
> but its `IdentityMapping` node **is** created (`person_cache.queue_identity_mapping`),
> and that is what branch 2 walks.
>
> **Measured on the live graph (456 nodes), 2026-10-17** — the ids are the ones
> the plan's own Phase 1c rule produces from real rows:
>
> | Requested id (built by 1c) | Branch 1 | Branch 2 (via `MAPS_TO`) |
> |---|---|---|
> | `github::Person::shuvabrata` | ✅ itself | n/a |
> | `jira::Person::557058:62105664-…` | ✅ itself | n/a |
> | `jira::Person::712020:cc7f7515-…` | ✅ itself | n/a |
> | `confluence::Person::557058:62105664-…` | ❌ absent | ✅ → `jira::Person::557058:62105664-…` |
> | `confluence::Person::712020:cc7f7515-…` | ❌ absent | ✅ → `jira::Person::712020:cc7f7515-…` |
> | `confluence::Person::712020:23da340e-…` | ❌ absent | ✅ → `jira::Person::712020:23da340e-…` |
> | `confluence::Page::26705923` | ✅ itself | n/a |
> | `github::PullRequest::work-behavior-analytics-ai::339` | ✅ itself | n/a |
> | `mock::Person::alice`, `mock::PullRequest::mock-other` | ❌ absent | ❌ absent → "Not found" (correct, Decision 15) |
>
> Whole-dataset sweep: **3 of 9** distinct real Person sibling ids miss branch 1
> and are recovered by branch 2; **58 of 382** Person-involving action rows are
> affected (~15%). The worst single lane is `confluence::Page::26705923`, where
> **11 of its 14 events** carry a `confluence::Person::…` sibling.
>
> **The keying must be by the requested id, not by the returned `wba_id`.** In
> the deduped case the two differ by construction. That is why
> `fetch_node_properties` builds `mapping_to_person` from the returned `MAPS_TO`
> edge and keys the final result by the id the caller passed. Keying by the
> node's own `wba_id` is the bug this branch exists to avoid.
>
> **Do not** try to pair the mapping to its Person by position or by list order:
> a Person can have several `IdentityMapping` nodes (the live graph has a
> `jira` and a `confluence` mapping for the same person), so only the returned
> `MAPS_TO` edge identifies the pairing.

> **This Cypher has already been executed against the live local graph** —
> measured on 2026-10-17 against `neo4j:5.26-community`. You do **not** need to
> re-derive it; implement it as written. The measured evidence, so you can
> recognise a regression:
>
> | Input | Rows | Result |
> |---|---|---|
> | `jira::Person::557058:62105664-…` (a real lane id) | 1 | itself, `Person` |
> | `github::Repository::shuvabrata/work-behavior-analytics-ai` | 1 | itself, `Repository` |
> | `mock::Person::nope` (missing) | 0 | absent → the "Not found" panel |
> | a real id **+** a missing id, one call | 1 | only the resolvable node |
> | `confluence::Person::557058:62105664-…` **+** its mapping | 2 | the mapping node, the `MAPS_TO` edge, and the canonical `jira::Person::…` |
>
> Keep the `IN` form — see the note above for why a per-id property-map match
> would also be a scan.
>
> The deep-link Cypher is also verified: the lane-only form returns 37 rows for
> a real Repository id, and the related-node form returns **0** when no such edge
> exists (the expected case for a mock or historical event) — the Graph page
> shows the nodes and the user sees the edge is absent, which is correct rather
> than an error. For a **deduped Person sibling** the related-node form returns
> **0** unless it is written through the hop — see 5c.

**Verify**
```
mypy src/ && pylint src --score=y
```
Re-run the case table above **once**, after wiring `fetch_node_properties`, to
confirm the code path (not just the Cypher) behaves — including the **deduped
Person** rows, which are the ones branch 2 exists for. Take real ids from:

```
MATCH (p:Person) RETURN p.id LIMIT 5          # canonical ids → branch 1
MATCH (i:IdentityMapping) RETURN i.id LIMIT 5 # mapping ids  → branch 2
```

For each mapping id, `fetch_node_properties([<the matching ::Person:: id>])`
must return a non-empty dict whose single value's `wba_id` is the **canonical
`Person`** id (e.g. requesting `confluence::Person::557058:…` yields a node whose
`wba_id` is `jira::Person::557058:…`). If a mapping id's Person id comes back
absent, branch 2 is mis-wired — re-read 3a rather than adding a fallback.

If Neo4j is unavailable, report this step as not performed — the unit tests in
Phase 7 are the gate.

### Phase 4 — Helpers: the modal payload and the peek's new sentence

**4a.** `src/app/dash_app/pages/timeline/helpers.py` — replace
`_popup_headline` (line 463) with a shared sentence builder, and add the modal
payload builders. The lane's display name is **not** on the event, so it is
passed in:

```python
def detail_sentence(
    event: dict[str, Any], lane_label: str, *, scope: str = "activity"
) -> str:
    """Return the card's full sentence: ``<subject> <relationship> <object>``.

    The card elides the subject into the sticky lane header, so ``lane_label``
    supplies it here.  Returns a fragment (never empty) so both the modal header
    and the hover peek can render it unconditionally.

    The object is appended **only in activity scope**.  ``card_secondary`` falls
    back to ``event["summary"]`` after ``related_name``/``related_id``, and in
    history scope that summary is the lane's OWN display name
    (``_event_to_event`` sets ``summary=event.display_name``, with no
    ``related_*``), so appending it would render
    "Alice Johnson Updated Alice Johnson".
    """
    subject = (lane_label or "").strip()
    relationship = humanize_relationship(str(event.get("relationship_type") or ""))
    if not relationship:
        relationship = entity_type_label(str(event.get("entity_type") or ""))
    parts = [part for part in (subject, relationship) if part]
    if scope != "history":
        parts.append(card_secondary(event))
    return " ".join(part for part in parts if part) or "Event"
```

**Careful**: `card_secondary` returns the *other side's name alone*. Read it
before assuming it includes a type label — and note the scope gate above is
**not** the same chain as `card_secondary`; it deliberately drops that
function's third (``summary``) fallback in history scope.

**4b.** `popup_fields` (line 512) — Decision 14. Change the headline source and
add the click hint. The payload key stays `summary` so the existing clientside
`build()` keeps working **without a JS change**, but its value is now the
sentence:

```python
def popup_fields(
    event: dict[str, Any],
    datetime_text: str,
    lane_label: str = "",
    *,
    scope: str = "activity",
) -> dict[str, Any]:
    """Build the JSON payload carried on each card for the hover popup.

    ``summary`` is the same sentence the detail modal's header shows
    (``detail_sentence``), so hovering and clicking describe the event
    identically — the old ``_popup_headline`` preferred ``event["summary"]``,
    which is the *actor's* title and is frequently absent for Person-actor
    events.  ``hint`` drives the peek's muted "Click for details" affordance.
    ``scope`` is forwarded to ``detail_sentence`` so history cards do not repeat
    the lane's own name (see 4a).
    """
    fields: dict[str, Any] = {
        "summary": detail_sentence(event, lane_label, scope=scope),
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

Keep `lane_label` and `scope` **defaulted** so existing call sites and tests
that pass only two arguments keep working.

**4c.** Add the modal payload builder, also in `helpers.py`:

```python
def detail_payload(event: dict[str, Any], lane_label: str, lane_wba_id: str,
                   datetime_text: str, scope: str) -> dict[str, Any]:
    """Build the JSON payload carried on each card for the detail modal.

    Everything the modal needs to render its header and issue its one Neo4j
    fetch, with no second round trip.  In ``history`` scope there is no other
    side (``lane_role`` is None), so ``related_wba_id`` is None and the modal
    renders a single panel.  The lane's OWN type is not carried here: it is the
    middle segment of ``lane_wba_id`` (Decision 7b), which the clientside branch
    passes straight through.
    """
    related = event.get("related_wba_id")
    related_wba_id = related if isinstance(related, str) and related else None
    if (
        related_wba_id is None
        and scope != "history"          # Decision 11: history is one panel, always
        and lane_wba_id.startswith("mock::")   # mock lanes only — never real data
    ):
        # Mock events carry a sibling TYPE but no sibling id.  Build a
        # placeholder in the SAME {source}::{type}::{id} grammar as the lane id,
        # so graph_deep_link's middle-segment label is the sibling's real type.
        # A 4-segment id (e.g. "mock::Person::other::Issue") would parse the
        # label as "Person" — the exact conflation the card-reading-order change's mock guidance
        # warns about.
        related_entity_type = str(event.get("entity_type") or "")
        if related_entity_type:
            related_wba_id = f"mock::{related_entity_type}::mock-other"
    return {
        "lane_wba_id": lane_wba_id,
        "lane_label": lane_label,
        "related_wba_id": related_wba_id,
        "relationship": humanize_relationship(
            str(event.get("relationship_type") or "")
        ),
        "datetime": datetime_text,
        "scope": scope,
        # Needs ``related_wba_id`` normalised first, hence the local above.
        "graph_url": graph_deep_link(lane_wba_id, related_wba_id),
    }
```

> **The mock branch above is the whole of this plan's mock support**
> (Decision 15), and each of its three conditions is load-bearing:
>
> - `related_wba_id is None` — real activity events already carry the true
>   sibling id from Phase 1, so the branch can only ever add to mock data.
> - `scope != "history"` — **this one is easy to lose.** `_event_to_event` sets
>   `entity_type` to the lane's *own* type and leaves `related_wba_id` None, so
>   without this guard the fallback would invent a sibling for history and the
>   modal would render two panels plus a connector, breaking Decision 11's
>   single-panel history modal and step 5e's `right is None` branch.
> - `lane_wba_id.startswith("mock::")` — mock lanes only, never real data. Use
>   `startswith` on the literal inline; do **not** introduce a module constant
>   for the prefix (a tuple constant compared with `==` silently never matches).
>
> The placeholder id is **three segments** (`mock::<Type>::mock-other`) so it is
> in the same `{source}::{type}::{id}` grammar as the lane id — which is what
> makes `graph_deep_link`'s `split("::", 2)[1]` yield the sibling's *real* type.
> A four-segment id would parse the label as `mock`, and the deep link would run
> a nonsense subgraph. It matches no node, so the right panel still shows
> "Not found in graph" and the whole click still issues **exactly one**
> `POST /api/v1/graph/execute`. Everything else about mock data is unchanged: no
> lane-id rename, no `related_*` on `_materialize`, no `lane_role`. Do **not**
> generalise this into a fallback for real data — the sibling's id for real
> events comes from the API field added in Phase 1.

The lane's own type is deliberately **not** in the payload: `lane_wba_id` is
`{source}::{entity_type}::{id}`, and `graph_deep_link` reads the middle segment
(Decision 7b) — the same idiom it already uses for the other side, and the same
one `helpers.selection_from_wba_ids` uses. Do **not** derive it from `lane_role`:
that says *which side* the lane was on, not what type that side is.

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
(the same pattern the card-reading-order change used for `scope`).

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
                scope=scope,
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

**5a-iv. Thread the lane label.** `build_event_card` takes these two as
**keyword-only** (`lane_label`, `lane_wba_id` — see 5a) and has **no** `lane_key`
parameter. `build_cell` already has `lane_key` (the lane's wba id) as a
parameter; the lane's *display label* does not exist there and must be looked up
by `wba_id`. So this is three edits, not one:

1. **`build_cell`** — add a `lane_label` parameter beside the existing
   `lane_key` (both keyword-only, both defaulted):

```python
def build_cell(  # pylint: disable=too-many-arguments
    events: list[dict[str, Any]],
    lane_color: str,
    effective_nodes: dict[str, Any] | None,
    base_tokens: dict[str, Any],
    *,
    show_empty_note: bool = False,
    expanded: bool = False,
    row_key: str = "",
    lane_key: str = "",
    lane_label: str = "",
    scope: str = "activity",
) -> html.Div:
```

2. **Inside `build_cell`** — forward both into the card call (this is the only
   place `lane_key` becomes `lane_wba_id`):

```python
    cards: list[Any] = [
        build_event_card(
            event,
            lane_color,
            entity_type_color(
                str(event.get("entity_type") or ""), effective_nodes, base_tokens
            ),
            scope=scope,
            lane_label=lane_label,
            lane_wba_id=lane_key,
        )
        for event in shown
    ]
```

3. **`build_grid_body`** — the lane dicts are in `lanes`, which is already a
   parameter. Build the label map beside the existing `lane_ids`
   (`lane_ids = [str(lane.get("wba_id") or "") for lane in lanes]`, line 751):

```python
    lane_labels = {
        str(lane.get("wba_id") or ""): str(lane.get("label") or "")
        for lane in lanes
    }
```

   and pass it in the **main** cell loop, which is the only `build_cell` call
   that already passes `lane_key=wba_id`:

```python
                build_cell(
                    list(cells.get(wba_id) or []),
                    lane_colors.get(wba_id, ""),
                    effective_nodes,
                    base_tokens,
                    show_empty_note=first_row and lane_empty.get(wba_id, False),
                    expanded=cell_expansion_key(row_key, wba_id) in expanded_cell_set,
                    row_key=row_key,
                    lane_key=wba_id,
                    lane_label=lane_labels.get(wba_id, ""),
                    scope=scope,
                )
```

- The other `build_cell` calls (the empty-grid early return and the expanded
  idle row) pass neither `lane_key` nor `lane_label` — leave them alone; no
  cards are rendered without events.
- **pylint**: `build_cell` and `build_grid_body` already carry
  `# pylint: disable=too-many-arguments`; if the added parameter trips the count,
  extend that disable rather than restructuring.
- `lane_labels.get(wba_id, "")` is the required fallback for a lane missing from
  the dict: `detail_sentence` treats an empty subject as "no subject" rather than
  rendering a stray space.

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
    immediate neighbours.  The ``?cypher=`` shape is the one
    ``pages/search.py:349`` and ``:458`` construct; the Graph page reads it in
    ``handle_url_deep_link_tab`` (``graph/callbacks/right_panel.py:100-105``) to
    open the Console tab, pre-fill the query and auto-execute it.

    Both labels are read from their own WBA id (``{source}::{type}::{id}``), so
    callers pass ids only — the same ``split("::", 2)[1]`` idiom
    ``selection_from_wba_ids`` uses.

    **Both MATCHes are label-scoped on purpose.**  The ``id`` index is
    **per-label** (every entity label, created by
    ``src/app/scripts/create_neo4j_indexes.py``), so an *unlabelled*
    ``MATCH (a {id: …})`` cannot use any of them — it plans as
    ``AllNodesScan > Filter``.  Both labels come from parsed WBA ids, and
    ``detail_payload`` only ever passes ids that came from a validated lane key
    (``parse_wba_id`` in ``service.py``) or from the API's ``related_wba_id``.

    **A Person id is matched through its ``IdentityMapping``.**  A Person id on
    either side may be a provider-scoped id whose Person node was never created,
    because Neo4j deduped the person onto another provider's canonical node
    (Decision 9b).  The label alone would then match nothing and the Graph page
    would open empty.  Anchoring on the ``IdentityMapping`` (which *is* created
    for every provider identity) and hopping one ``MAPS_TO`` to the Person
    resolves the deduped case as well as the ordinary one, since a non-deduped
    Person has its own mapping too.
    """
    lane_pattern = _node_pattern("a", lane_wba_id)
    if related_wba_id:
        cypher = (
            f"MATCH {lane_pattern} "
            f"MATCH {_node_pattern('b', related_wba_id)} "
            "MATCH (a)-[r]-(b) RETURN a, r, b LIMIT 50"
        )
    else:
        cypher = (
            f"MATCH {lane_pattern} "
            "OPTIONAL MATCH (a)-[r]-(b) RETURN a, r, b LIMIT 50"
        )
    return f"/app/graph?cypher={quote(cypher)}"
```

Write `_node_pattern` as a **module-level private helper beside
`graph_deep_link`** (not a closure inside it) — mypy strict and pylint both
prefer it that way, and Phase 7 tests it directly:

```python
def _node_pattern(var: str, wba_id: str) -> str:
    """Return a label-scoped Cypher pattern that resolves ``wba_id`` to a node.

    A Person is resolved through its ``IdentityMapping`` plus one ``MAPS_TO``
    hop, because a Person's provider-scoped id may not be its node id at all
    (Decision 9b).  Every other entity type is matched directly on its own id,
    which the per-label ``id`` index serves as a seek.
    """
    source, entity_type, entity_id = wba_id.split("::", 2)
    if entity_type == "Person":
        mapping_id = f"{source}::IdentityMapping::{entity_id}"
        return (
            f"(i_{var}:IdentityMapping {{id: '{mapping_id}'}})"
            f"-[:MAPS_TO]-({var}:Person)"
        )
    return f"({var}:{entity_type} {{id: '{wba_id}'}})"
```

> **Verified on the live graph**, 2026-10-17 — all six forms below were executed
> through `POST /api/v1/graph/execute` and returned a non-error `GraphResponse`:
>
> | Case | Result |
> |---|---|
> | Page lane + **deduped** Person sibling | ✅ 2 nodes, 9 rels (`confluence::Page::…` + `jira::Person::…`) |
> | Person lane + PR sibling | ✅ 2 nodes, 2 rels |
> | Person lane + Commit sibling | ✅ 2 nodes, 2 rels |
> | history, Person lane only | ✅ lane + neighbours |
> | history, Page lane only | ✅ lane + neighbours |
>
> Without the hop, the first row returns `nodes=0 rels=0` — an empty Graph page.
> Note that the `i_a` / `i_b` mapping nodes are **not** projected by
> `RETURN a, r, b`, so the Graph page shows the same two entity nodes it did
> before.

Import `quote` from `urllib.parse` at the top of `helpers.py` (check the
existing import block first — do not duplicate an existing import).

Call it from `detail_payload` (Phase 4c), which already does this — see the
``"graph_url"`` key there. It takes the already-normalised ``related_wba_id``
local, so the clientside branch needs no conditional.

**The label is always present**, because `lane_wba_id` always has three
`::`-separated segments: it is the lane key the API minted, and the modal is only
reachable from a card built from a validated lane (`parse_wba_id` rejects any key
without three non-empty parts, and `router.py` validates every requested
`wba_ids` entry up front). So there is no empty-label branch to guard — and
**do not add one**: a bare `MATCH (a: {id: …})` is a Cypher syntax error, so a
defensive fallback would need to change the query shape, not just drop a label.
If `lane_wba_id` ever turns out to lack a type segment, that is a STOP condition
(see the STOP section), not something to paper over here.

> **Known limitation, tracked separately — do not fix here.** The Graph page's
> `validate_read_only_query` scans the *whole* query string for write keywords,
> including inside string literals, so an id containing a hyphen-delimited
> keyword (e.g. `github::Repository::acme/merge-queue`) is rejected with HTTP 400
> and the deep link shows an error instead of a graph. This is **pre-existing**
> (the Search page's `_build_node_cypher` has the same exposure) and the fix
> belongs in the validator, not here. See
> `plans/045-graph-query-validator-rejects-entity-ids.md`. Do **not** add
> keyword-escaping or a URL-shape fallback in `graph_deep_link` — that is a
> decision for 045.

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
                    // The payload IS the store value, unchanged (Decision 17).
                    // A byte-equal payload means an identical header and
                    // identical panels (both derive from the same two node
                    // ids), so Dash's own change detection skipping the repeat
                    // is the correct behaviour.
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
2. Take the two lookup ids **straight from the payload**:
   `left = payload["lane_wba_id"]`, `right = payload.get("related_wba_id")`.
   Build the list of ids actually to fetch: `ids = [left] if not right else [left, right]`.
   **No translation step here** — `fetch_node_properties` owns the Person hop
   (Decision 9b / 3a). The ids stay in their requested form, and the dict it
   returns is keyed by exactly those ids, so `nodes[left]` and `nodes[right]`
   are correct even when the resolved node's own `wba_id` differs.
3. `nodes = fetch_node_properties(ids)`, wrapped in
   `try/except NodePropertiesError` → return `_detail_error(...)` (see below).
   **Do not use `create_alert`** for this: an alert belongs in the page's
   feedback slot, and the modal body is its own section — the inline state keeps
   the body uniform.
4. Render, **through `_detail_panel`** (see below, and Decisions 12 and 16):
   - **history** (`right` is `None`): one panel using
     `_detail_panel(render_visible_properties(nodes[left]))` when
     `left in nodes`, else `_detail_panel(_not_found(left))`.
   - **activity**: a `html.Div(className="timeline-detail-grid")` containing
     `_detail_panel(render_visible_properties(nodes[left]))` (or
     `_detail_panel(_not_found(left))`), then the connector, then the same for
     `right`. The connector is
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
   on every remount). `timeline-detail-store` is the **only** `Input`.

Two small helpers sit beside the callback. `_detail_panel` is the one that makes
Decisions 12 and 16 real — every panel goes through it, so the class and the
caption cannot be forgotten:

```python
def _detail_panel(body: Any) -> html.Div:
    """One side of the modal.

    ``.timeline-detail-panel`` is the flex child: ``flex: 1 1 0`` +
    ``min-width: 0`` (5g) is what makes the two tables share the width and wrap
    long WBA ids instead of pushing each other apart.  The caption is Decision
    12 — these are the entities' CURRENT properties, not an as-of-event snapshot.
    """
    return html.Div(
        [
            html.Div("Current state", className="timeline-detail-caption"),
            body,
        ],
        className="timeline-detail-panel",
    )


def _detail_error(message: str) -> html.Div:
    """Modal-body error state.  NOT ``create_alert`` — see step 3 above."""
    return html.Div(
        [html.Div(message, className="timeline-detail-missing-title")],
        className="timeline-detail-missing",
    )
```

The `except` branch reports a single generic cause — the API answers HTTP 500
for every Cypher runtime error, so a 500 cannot be diagnosed as a
configuration problem:

```python
    except NodePropertiesError:
        return _detail_error("Could not load properties for this event.")
```

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

.timeline-detail-missing-title {
    /* Used by both _not_found and _detail_error.  The parent's italic already
       carries the tone; this is a no-op unless the title needs its own weight. */
    font-style: normal;
    font-weight: var(--font-weight-medium);
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
- **Click a second, different card**, then the first again — the header **and**
  the panels must match the card each time. Re-clicking the *same* card twice in
  a row re-opens from the already-rendered panels (Decision 17: an equal payload
  does not re-fetch) — that is expected, not a bug.
- The header's Graph link opens `/app/graph` **in a new tab** with the subgraph.
- Both panels show properties in the shared `.details-prop-row` style; long WBA
  ids wrap rather than overflow; the copy icons and the connector glyph render
  (a missing icon is an empty box, not an error).
- Each panel shows the **"Current state"** caption above its table, and the two
  tables sit side by side at equal width (`.timeline-detail-panel`).
- Because mock lane ids match no real node (Decision 15), both panels show
  "Not found in graph" — the right panel via the mock sibling id from 4c — and
  the network tab shows exactly **one** `/graph/execute` per click.
- Hovering the same card still shows the peek, now with the sentence and the
  "Click for details" hint, and **no** native tooltip.

**Verify — the deduped-Person case (NOT a gate, but do it if Neo4j is up).**
Mock mode cannot exercise this, because mock ids match no node by design. Turn
mock mode **off** (`TIMELINE_MOCK_SCENARIO=` empty in `.env`, then
`docker compose up -d --force-recreate app`) and select the lane
**`confluence::Page::26705923`** (type `26705923`, or pick the Confluence Page
named "First Engineering Page" from the typeahead):
- Click any of the cards whose second line reads `Person · shuvabratadeb` —
  **11 of that lane's 14 cards** are this shape on the current local data.
- The **right** panel must show real properties (a `Person` table with `id`,
  `name`, `email`, …), **not** "Not found in graph". Before this plan's fix it
  showed "Not found in graph" for all 11.
- The header's Graph link must open a graph with **two** nodes and edges between
  them, **not** an empty canvas.
- Still exactly **one** `/graph/execute` per click (the hop is inside the same
  single query — 3a).

If Neo4j is down or the lane is not present in the local data, report this step
as not performed — the Phase 7 tests are the gate.

If a browser or the app is unavailable, report this step as not performed — do
not mark the phase failed, and do not improvise a substitute.

### Phase 6 — Mock data: NO CHANGE

**There is nothing to do in this phase. `src/app/api/activity/v1/mock_data.py`
must not be modified.**

This phase previously specified a reshaped mock lane-id convention plus
`related_*` / `lane_role` on `_materialize`. All of it is unnecessary, and the
measurements below are why:

- **Mock lane ids already resolve to no node.** Measured against the live local
  graph: `MATCH (n) WHERE n.id STARTS WITH 'mock::' RETURN count(n)` → **0**, and
  a properties fetch for two mock ids returns an empty node list
  (`isGraph: false, resultCount: 0`). So the per-panel "Not found in graph" state
  is already exercised deterministically with zero Neo4j traffic — which was the
  entire argument for the rename.
- **The source on those catalogue entries is real, not `mock`.** The entries read
  `("mock::Person::alice", "Alice Johnson", "Person", "github", …)` — the source
  is `github`/`jira`/`confluence`. `parse_wba_id` accepts any `a::b::c`, and no
  node id is ever constructed from a lane's WBA id (node identity comes from the
  connector pipeline), so the prefix changes nothing anywhere.
- **The rename's cost was real**: ~40 line edits across `mock_data.py` and four
  test files, plus a new reserved-source convention to document and a
  "the three-part shape is load-bearing" rule to keep. Net behaviour change:
  none.

The one thing mock mode does need — that the sibling's **type** is visible in the
right panel — is two lines inside `detail_payload` (step 4c), which is where the
knowledge belongs. Leave `_SUGGESTION_CATALOGUE`, `_lane_identity` and
`_materialize` exactly as they are.

**Verify**
```
git diff --stat src/app/api/activity/v1/mock_data.py   # → no output
```

### Phase 6 (formerly 6a-6c) — removed

The former steps 6a-6c are deleted for the same reason: the modal derives both
node ids without them (the lane id from the card, the sibling from
`related_wba_id` or the mock fallback in 4c), and `lane_role` is read nowhere in
this design.

### Phase 7 — Tests and documentation

**7a.** `tests/test_activity_api_integration.py` — add assertions only. The fake
session's return shape is **unchanged** (still `(action, related_name)` pairs;
the service builds the WBA id itself in Phase 1c). Assert that:
`related_wba_id` is the **other** side's canonical id in **both** directions
(actor-side and target-side rows), that it uses the row's own `target_source` for
the actor direction, and that it is `None` for history.

**7b.** `tests/test_activity_person_identity.py` — **no change, and it is not in
Scope.** Its three `_action_to_event` call sites keep their current signature, and
its compiled-SQL assertions are unaffected because this plan does not touch
`fetch_actions_for_entity`. If this file goes red, the build was done in the
wrong layer — fix Phase 1c rather than the test.
`where = sql.split("FROMactivity_actionsWHERE", 1)[-1]` pattern and update the
numbers. **Do not delete or `xfail` them** — the disjunct-per-identity property
is the fix from `90c9674`.

**7c.** `tests/test_activity_timeline_detail_modal.py` (**create**) —
`pytestmark = pytest.mark.unit`. Cover, with no network and no Neo4j:

- **The Cypher has both branches and is a single statement**: assert
  `_NODE_PROPERTIES_CYPHER` contains `IN $ids`, contains `IN $mids`, contains
  `MAPS_TO`, and contains `UNION` **exactly once** (one union, two branches).
  A regression that drops the mapping branch must fail this.
- **`_mapping_id_for` translates only Person ids**: a `…::Person::x` id yields
  `…::IdentityMapping::x`; a `…::Repository::x` id yields `None`; a Person id
  keeps its own source segment (the mapping id is same-source, not canonicalised).
- **`fetch_node_properties` keys by the id requested, not by the returned
  `wba_id`** (the Decision 9b regression pin — this is the whole point of the
  change). Stub the HTTP layer with a payload whose node carries a **different**
  `wba_id` from the one asked for, plus a `MAPS_TO` edge pairing it back to the
  requested id, and assert the result is keyed by the **requested** id. Then
  assert that asking for **two** ids returns both rows, and that an id with no
  branch-1 node and no `MAPS_TO` edge is simply **absent** (so the caller renders
  the per-panel "Not found" state rather than a KeyError).
  Build the stub payload by passing a `GraphResponse`-shaped dict through the
  real `neo4j_to_cytoscape` (import it in the test) rather than hand-rolling
  cytoscape elements — that keeps the fixture honest about the transform's
  element shape.
- **The pairing is by `MAPS_TO` edge, not by order**: give the stub **two**
  mapping nodes with edges to the **same** Person, in the reverse of the
  requested order, and assert the result still maps each requested id to the
  right node. A positional pairing implementation must fail this.
- **`_detail_panel`** (Decision 16): the returned `html.Div` has
  `className == "timeline-detail-panel"` and its first child carries
  `className == "timeline-detail-caption"` with the "Current state" text.
- **`_detail_error` copy**: a `NodePropertiesError` path — whether from an HTTP
  500 or a transport failure — yields the generic "Could not load properties for
  this event." sentence.
- **`detail_payload` carries no nonce** (Decision 17): two payloads built from
  *identical* events compare **equal**, so a re-click on the same card does not
  re-fetch. Assert equality directly — that is the property the design now relies
  on.
- **`graph_deep_link` is label-scoped and derives both labels from the ids**
  (the `id` index is per-label): for a related pair of **non-Person** entities
  the Cypher contains `MATCH (a:PullRequest {id: '…'})` and
  `(b:Issue {id: '…'})`; for history it contains only the lane id;
  `unquote`ing the query round-trips.
- **`_node_pattern` routes Person through the mapping hop** (Decision 9b):
  `_node_pattern("b", "confluence::Person::abc")` contains
  `(i_b:IdentityMapping {id: 'confluence::IdentityMapping::abc'})` and
  `-[:MAPS_TO]-(b:Person)`; `_node_pattern("b", "github::Repository::a/b")`
  contains `(b:Repository {id: 'github::Repository::a/b'})` and **no** `MAPS_TO`.
  Then assert the whole deep link for a deduped Person sibling contains both the
  mapping id and `MAPS_TO` — this is the pin that keeps the Graph link from
  opening an empty canvas.
- **The mock sibling id is narrow and well-formed** (three cases, all required):
  1. `detail_payload` for a `mock::Person::alice` lane in **activity** scope with
     `entity_type == "PullRequest"` returns `related_wba_id ==
     "mock::PullRequest::mock-other"` — assert the **exact** value, so a
     four-segment regression cannot slip through a `startswith` check;
  2. the same call with `scope="history"` returns **`None`** (Decision 11 — the
     fallback must not fire in history, or the modal renders two panels);
  3. a **real** lane id (e.g. `github::Person::alice`) with no `related_wba_id`
     on the event returns **`None`** (the fallback must not fire for real data).
- **`render_properties_table` parity**: the same `(key, value)` list rendered
  through `render_properties_table` and through `build_element_properties_content`
  produces the same `details-prop-row` rows (parse both `str(...)` outputs and
  compare the row count and the key/value text) — this is the regression pin for
  Decision 5, and it must fail if someone re-forks the table.
- **`render_visible_properties`**: `_display_name` and `None` values are hidden;
  an `id` row is injected first; a node with nothing visible renders the "No
  properties" state.
- **`detail_payload`**: activity carries a non-None `related_wba_id`; history
  carries `None`; the lane's type is **not** a payload key (Decision 7b); the
  payload is JSON-serializable (`json.dumps` must not raise).
- **`detail_sentence`**: subject + humanized relationship + object; falls back to
  the entity type when there is no relationship; never returns `""`; and in
  **history** scope (`scope="history"`, `summary == lane_label`, no
  `related_*`) returns `<lane> Updated` with the lane's name appearing exactly
  **once** (the lane's name must not be repeated).

**7d.** `tests/test_activity_timeline_ui_helpers.py` — update
`test_popup_fields_from_event` (line 366): the headline is now the sentence, and
`hint` is present. Add a case asserting the headline uses `related_name` in
preference to the raw `summary` — the whole point of Decision 14.

**7e.** `docs/design/activity-timeline-design.md`:
- §5.1 `TimelineEvent` shape — add `related_wba_id`. Note that the lane's own
  type is deliberately **not** a field: it is the middle segment of the lane's
  WBA id (and `entity_type` is already the lane's own type in history scope), so
  both the UI and the deep link derive it.
- §5.1/§7.4 — record the **two different lookup rules**, since conflating them is
  the bug this plan's review found. **(a) The lane** is looked up by its own
  canonical id with no hop: a lane only ever comes from the ES-backed typeahead,
  whose Person documents are keyed by the canonical Neo4j id. **(b) The sibling**
  may need one `MAPS_TO` hop: its id comes from the raw `activity_actions` row
  and is provider-scoped, so when Neo4j deduped that person onto another
  provider's canonical node the provider-scoped id is not a node id at all. State
  that both are resolved in **one** `/graph/execute` call, and that the result is
  keyed by the id **requested**, not by the `wba_id` that came back.
- §5.3 — note that the sibling's canonical id is now carried on the event.
- §7.4 Cards & interaction — replace the two-line card bullet's **interaction**
  half: the card is no longer a link; clicking opens the event detail modal. Add
  a new subsection describing the modal (header sentence, the Graph deep-link in
  a new tab, the two shared-renderer panels, the neutral connector, current-state
  semantics, the history single-panel case, and the per-panel not-found state).
  State explicitly that the modal's tables are rendered by the **same** function
  as the Graph right panel, and that each panel carries a "Current state"
  caption. Do **not** document a click nonce — there is none; note instead that
  the panels render from the payload's two node ids, so a repeat click on the
  same card re-opens from the already-rendered panels.
- §11 Source map — add `tests/test_activity_timeline_detail_modal.py`.

**7f.** `tests/test_activity_timeline_edge_cases.py` — **fixture fix only.** This
file's `_lane` helper builds lane dicts by hand and four of its tests render them
through `build_grid_body`, so Phase 5a now routes every card through
`detail_payload` → `graph_deep_link` → `_node_pattern`, which unpacks the lane id
as `{source}::{type}::{id}`. The hand-built ids (`"a"`, `"b"`, `"lane0"`) have one
segment and raise `ValueError: not enough values to unpack (expected 3, got 1)`.

A lane id reaching the timeline from the API is **always** three segments —
`parse_wba_id` in `service.py` rejects anything else — so the malformed ids exist
only as test fixtures. Fix the fixtures, **not** the production code:

- In the rendering tests, replace every single-segment lane id with a well-formed
  one. The minimal set:
  - `"a"` → `"github::Person::a"` (lines ~76, ~84, ~93, ~111, ~119)
  - `"b"` → `"github::Person::b"` (lines ~85, ~93)
  - `f"lane{index}"` → `f"github::Person::lane{index}"` (line ~101)
- `_lane`'s `"label": wba_id` line may stay as it is — the label becomes the
  sentence's subject, and no assertion in this file depends on its text.
- Leave `test_lane_exactly_limit_clears_cursor_on_empty_page` (line ~141) alone:
  its `{"wba_id": "a", …}` is passed to `has_more`/`merge_lane_page`, which never
  render a card.
- Change **nothing else** in this file — no new assertions, no behavioural edits.
  It stays the render sweep it was; only the ids become valid.

**Do not** instead add a guard or fallback in `graph_deep_link` /
`_node_pattern` / `detail_payload` for ids without a type segment. `_node_pattern`
needs the middle segment to emit a **label-scoped** `MATCH`, and a bare
`MATCH (a: {id: …})` is a Cypher syntax error — so a "guard" could not merely drop
a label, it would have to change the query shape or suppress the deep link for a
real event. Malformed lane ids never reach production code, so that branch would
be dead code guarding an impossible input.

**Verify (7f)**
```
pytest -m unit tests/test_activity_timeline_edge_cases.py -q   # all pass
```

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
| `tests/test_activity_timeline_detail_modal.py` | **create** | Cypher shape (both branches, one `UNION`); `_mapping_id_for`; fetch keying **by requested id** (incl. the differing-`wba_id` and order-independence pins); `_detail_panel`; error copy; payload equality (no nonce); mock-sibling narrowness; label-scoped deep link + `_node_pattern` Person hop; table-renderer parity; visible-property filtering; `detail_payload` for activity + history; `detail_sentence` incl. the history single-name case |
| `tests/test_activity_timeline_ui_helpers.py` | update | `popup_fields` headline is the sentence + `hint`; `related_name` beats `summary` |
| `tests/test_activity_api_integration.py` | update | `related_wba_id` correct in both directions (fake session shape unchanged) and using `target_source`; `None` for history |
| `tests/test_activity_timeline_edge_cases.py` | update (fixtures only) | lane ids become `{source}::{type}::{id}` so the render sweep still renders now that every card builds a `graph_deep_link` — see 7f. No new assertions. |

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
- The `MAPS_TO` hop's *graph* behaviour is pinned only by the stub in 7c, not by
  a live Neo4j test — the repo has no unit-level Neo4j fixture for the timeline.
  The live check is the Phase 5 deduped-Person manual step.
- Nothing automated pins the Graph deep-link URL's *end-to-end* behaviour (the
  Graph page pre-filling and auto-executing it). `graph_deep_link` **is** a pure
  function, so its shape **is** tested (7c): assert the returned string starts
  with `/app/graph?cypher=`, that `unquote`-ing the remainder round-trips to the
  expected Cypher, that the related-id form contains both ids while the history
  form contains only the lane id, and that a Person id routes through
  `_node_pattern`'s `MAPS_TO` hop. What is **not** tested is that the Graph page
  actually runs it — that is the Phase 5 manual step.
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
- [ ] `grep -rn "graph_lookup_id" src/ tests/` returns **no matches** — mock lane
      ids are unchanged (`mock::`, not a new reserved source), and the hop is
      spelled `_mapping_id_for` / `_node_pattern` rather than that retired name.
- [ ] `git diff --stat src/app/api/activity/v1/query.py src/app/api/activity/v1/mock_data.py tests/test_activity_person_identity.py`
      shows **no output** — the query layer, mock data and the identity tests are
      all untouched (Decisions 4, 15).
- [ ] The modal's panels carry their class: every panel rendered by
      `render_detail_panels` goes through `_detail_panel`, so
      `grep -c 'className="timeline-detail-panel"\|className=_PANEL_CLASS'`
      in `callbacks.py` and the `_detail_panel` body both show it — and
      `.timeline-detail-caption` is emitted (Decision 16). Pinned by a 7c test.
- [ ] `timeline-detail-store` carries the raw card payload with **no** `nonce`
      key (Decision 17): `grep -rn "nonce" src/app/dash_app/pages/timeline/`
      returns **no matches**, and the 7c payload-equality test passes.
- [ ] `graph_deep_link` emits a **label-scoped** `MATCH` for both forms, with
      both labels derived from the ids it is passed, and routes a **Person** id
      through the `IdentityMapping` + `MAPS_TO` hop (`_node_pattern`) so a
      deduped Person sibling does not open an empty graph.
- [ ] `fetch_node_properties` keys its result by the id **requested**, not by the
      returned node's `wba_id` — pinned by the 7c re-keying test, which must fail
      if the keying is switched back to `data["wba_id"]`.
- [ ] `_NODE_PROPERTIES_CYPHER` contains `MAPS_TO` and exactly **one** `UNION`
      (both branches present); `_mapping_id_for` translates only `::Person::` ids.
- [ ] The properties fetch is still exactly **one** `/graph/execute` call per
      click — the hop is a second branch of the same query, not a second request.
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
- [ ] `TimelineEvent` carries `related_wba_id`; it is non-None for an activity
      event and `None` for history. The field `lane_entity_type` is **not** added
      to `TimelineEvent` — `grep -n "lane_entity_type" src/app/api/activity/v1/model.py`
      returns **no matches** (Decision 7b). *(Do not widen this to `src/`: the
      pre-existing private `lane_entity_type` parameter in `service.py` and
      `mock_data.py` is untouched and must stay.)*
- [ ] `tests/test_activity_timeline_edge_cases.py` renders with well-formed
      three-segment lane ids (step 7f) and `git diff d77db38 -- tests/test_activity_timeline_edge_cases.py`
      shows **only** those id literals changed — no new assertions, no behavioural
      edits. `graph_deep_link` / `_node_pattern` / `detail_payload` carry **no**
      guard for an id without a type segment.
- [ ] No file outside the `## Scope` table is modified (`git status --short`).
- [ ] `plans/README.md` status row updated.

## STOP conditions

Stop and report back — do not improvise — if:

- **The card-reading-order change (`d77db38`, #339) has not landed**:
  `TimelineEvent` has no `lane_role` /
  `related_id` / `related_name`, or `helpers.card_primary` does not exist, or
  `activity_actions` has no `target_source` column. This plan cannot be executed
  without it.
- **A Person LANE's WBA id turns out not to be its Neo4j node id.** Decision 9a
  rests on this. Test it early: `MATCH (p:Person {id: $lane_id})` for a real
  lane must return one row. If it does not, STOP and report — the lane's own
  lookup rule has to change too, and this plan needs re-planning rather than a
  local patch. *(A **sibling** Person id failing that lookup is **expected**,
  not a STOP: it is exactly what branch 2 of `_NODE_PROPERTIES_CYPHER` exists
  for. Measured on the local graph, 3 of 9 real Person sibling ids miss branch 1
  and are recovered by the hop.)*
- **A Person id's `IdentityMapping` id cannot be derived by string substitution.**
  `_mapping_id_for` assumes `{source}::Person::{id}` ↔
  `{source}::IdentityMapping::{id}` (the same-source rule `identity.py:32-49`
  documents). If a real Person's mapping lives under a *different* source
  segment than the Person id, STOP and report — the substitution is wrong and the
  sibling would still miss.
- **`MAPS_TO` is not returned as an edge by `/graph/execute`.** The pairing in
  `fetch_node_properties` reads `relType == "MAPS_TO"` off the transformed
  elements. If the API does not surface relationship edges for this query shape,
  STOP rather than switching to a positional pairing — a Person may have several
  mappings, so position is not a safe key.
- **`_action_to_event`'s `is_actor` is not the lane-is-actor predicate.** Phase
  1c's `other_source` and the `related_wba_id` it builds rest on `is_actor` being
  the same condition the query's `actor_match` encodes. If reading
  `service.py:184-190` shows it comparing something other than
  `action.actor_entity_type` / `action.actor_entity_id`, stop rather than
  guessing which branch is right.
- **`target_source` is not what the query layer's `related_source` uses.** Phase
  1c builds `other_source` from `action.target_source or action.source` and
  must match `query.py`'s `related_source` `CASE` exactly. If the live code
  computes that source differently (a new column, an extra fallback), stop — a
  divergent id would make the sibling panel silently miss.
- **`lane_wba_id` turns out not to have three `::`-separated segments — in a
  code path other than the ones step 7f already covers.** Phase 5c derives the
  lane's `MATCH` label from `lane_wba_id.split("::", 2)[1]` and does **not** guard
  for an empty label (a bare `MATCH (a: {id: …})` is a syntax error, so a fallback
  would change the query shape). Every lane id the **API** produces has three
  segments (`parse_wba_id` rejects anything else), and the one known source of
  malformed ids — the hand-built lane fixtures in
  `tests/test_activity_timeline_edge_cases.py` — is fixed by **step 7f**, which is
  in Scope. So this is **no longer a STOP** for that file: apply 7f. It remains a
  STOP if you find *another* caller passing an id without a type segment that 7f
  does not cover — report it rather than adding a fallback.
- **`pytest -m unit tests -q` goes red in Phase 1.** The whole point of building
  `related_wba_id` in `_action_to_event` is that **no** existing test needs to
  change. A red run means the change was made in the wrong layer (most likely a
  third `select` column or a changed return shape) — revert to 1c rather than
  repairing the tests.
- **`_detail_panel`'s class is not what 5g defines**, or a panel is emitted
  without it. The two are a matched pair (Decision 16) — if the class name
  changes, change it in **both** the helper and the CSS in the same edit.
- **`render_properties_table`'s body has to change** to make the modal work, or
  `build_element_properties_content`'s rendered output changes in Phase 2. That
  phase is a pure rename + wrapper for the Graph page; **any** visual change
  there is a regression on a surface this plan is not allowed to alter. If the
  modal's columns need different value formatting, that is its own problem to
  solve in `render_visible_properties` (which may post-process the `(key, value)`
  list before delegating) — not by editing the shared table.
- **The properties query returns a node whose `wba_id` differs from the id you
  requested — and `fetch_node_properties` keys the result by that node's
  `wba_id` instead of by the id requested.** That is the **one** way this design
  fails silently: the right panel would render "Not found in graph" for a
  deduped Person sibling. Keying by the requested id is **required**, not
  optional (Decision 9b, 3a). *(A differing `wba_id` is itself **expected** for a
  deduped Person — that is the hop working. Do not "fix" it by removing the
  hop.)*
- **`is_open` ends up with two owners** (a server callback and the clientside
  branch both writing it). The clientside branch owns it; the server owns only
  `timeline-detail-panels.children`.
- **The spec regeneration produces a diff** — a signal-schema change slipped in.
- **A step requires editing a file not in the `## Scope` table.** That is a plan
  defect, not a judgement call.
- **The code at a cited location does not match the excerpt** in `## Current
  state` — the repo has drifted. (This is genuine drift, not staleness: the
  excerpts were taken from the live tree at `d77db38`.)

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
- `_NODE_PROPERTIES_CYPHER` has **two branches** (Decision 9b): a direct
  `n.id IN $ids` lookup, and a `MAPS_TO` branch for a Person whose provider
  identity was deduped onto another provider's canonical Person. It is the same
  `MAPS_TO` relationship `api/activity/v1/identity.py` walks for lane expansion,
  but the two are independent call sites — changing the relationship's shape or
  direction affects both. **Do not remove the mapping branch**: without it a
  deduped Person sibling renders "Not found in graph" (measured: 11 of 14 cards
  on the local `confluence::Page::26705923` lane). Do not remove the
  requested-id keying either — the returned node's `wba_id` legitimately differs
  from the id requested in exactly that case.
- **A new entity type is fine as long as its canonical id stays
  `{source}::{entity_type}::{id}`.** What breaks things is a type whose **node
  id** is not the id its signals carry (the Person-with-dedup case). Such a type
  needs its own branch in `_NODE_PROPERTIES_CYPHER` *and* its own hop in
  `_node_pattern` for the deep link — a Person-only special case today.
- Adding a new entity type whose canonical id is not
  `{source}::{entity_type}::{id}` breaks `related_wba_id` and **both** of
  `graph_deep_link`'s label derivations (`split("::", 2)[1]` on the lane id and on
  the sibling id) at once.
- The `is_open` / `timeline-detail-store` split is the modal's contract: the
  clientside branch never fetches, and the server never opens. `is_open` has one
  owner (clientside) and `panels.children` has one owner (server); the store is
  the only thing crossing between them. Preserve the three-way split or the modal
  either blocks on the round trip or fights itself on remount.
- **The panels are a pure function of the payload's two node ids**, which is why
  a repeat click on an identical card does not re-fetch (Decision 17). If a
  future change makes a panel depend on anything else — a per-click timestamp, a
  graph mutation counter — then the payload must change per click too, and
  Decision 17 has to be revisited rather than a nonce quietly reintroduced.
- `.timeline-detail-panel` and `_detail_panel` are a matched pair. The class is
  what applies `flex: 1 1 0` + `min-width: 0`; without it long WBA ids push the
  two tables apart instead of wrapping. Rename one, rename both.

**What a reviewer should scrutinize**

- That `src/app/api/activity/v1/query.py` is **unchanged**, and that
  `related_wba_id` is built in `_action_to_event` from the row's own
  `target_source` with the same branch the query's `related_source` `CASE` uses
  (`git diff` on `query.py`, `mock_data.py` and
  `tests/test_activity_person_identity.py` is empty).
- That `build_element_properties_content`'s rendered output is unchanged — diff
  its `str(...)` before and after.
- That the modal's table is genuinely `render_properties_table` and not a
  re-implementation.
- That the connector has **no** direction arrow.
- That no file under `src/connectors/` and no `src/common/activity_signal/` file
  was touched.
- That the properties fetch is exactly **one** HTTP call per click — one
  `POST /api/v1/graph/execute` carrying both ids (Decision 3; check the browser
  network tab in the manual pass). The `MAPS_TO` hop is a branch of that same
  query, **not** a second request.
- That the **right** panel renders properties for a deduped Person sibling, not
  "Not found in graph" — the Decision 9b regression. The quickest check is the
  local `confluence::Page::26705923` lane, where 11 of 14 cards are this shape.
- That `fetch_node_properties` keys its result by the id **requested**: the
  returned node's `wba_id` legitimately differs for a deduped Person, and keying
  on the node's own `wba_id` would silently produce the "Not found" panel.
- That `graph_deep_link` routes Person ids through `_node_pattern`'s mapping hop,
  so the "Open in Graph" link is not empty for those same cards.
- That both panels carry `.timeline-detail-panel` and the "Current state"
  caption, and that a click on a *different* card re-renders the panels
  (Decisions 12, 16).
- That the mock fallback in `detail_payload` is gated on `mock::` and cannot fire
  for a real lane: for a real lane with no `related_wba_id`, the right panel must
  render "Not found in graph" (there is genuinely no sibling), **not** a
  fabricated id.

**Deliberately deferred (out of scope)**

- **`GraphNode.display_name()`'s commit gap** (`src/connectors/neo4j_db/node_base.py:58`):
  the same four-word lookup `d77db38` (#339) fixed in the writer, still present on the
  graph side, so the **Graph page** shows SHAs for commits. Same defect,
  different surface (its own callers, tests and Cypher properties). Worth its own
  plan. This plan **reuses** the graph-side renderer, so the modal will show a
  commit's SHA in its `id` row and its `message` in a `message` row — consistent
  with the Graph page, which is the point, but it means the modal does **not**
  launder the graph's naming defect.
- Backfilling `activity_events.display_name` or `activity_actions.target_source`
  — unchanged from `d77db38`'s (#339) stance.
- Resolving a *mention-only* person (no `IdentityMapping`) — unchanged from the
  accepted limitation in the timeline design doc §5.3.8. Note that the
  `MAPS_TO` branch in `_NODE_PROPERTIES_CYPHER` **depends** on the
  `IdentityMapping` existing: a person who was never given one still misses.
  That is the pre-existing limitation, not a new one.
- **`validate_read_only_query` rejecting ids that contain a write keyword**
  (`api/graph/v1/query.py:38-83` — it scans string literals, so e.g.
  `github::Repository::acme/merge-queue` is rejected as a `MERGE`). This is
  **pre-existing** — the Search page's `_build_node_cypher` has the same
  exposure — and it is tracked separately in
  `plans/045-graph-query-validator-rejects-entity-ids.md`. Do **not** add
  keyword escaping or a URL-shape fallback in `graph_deep_link`; that is a
  decision for 045.
- The `details` attribute snapshot: `TimelineEvent.details` is `{}` for activity
  events, so no event-time property panel is possible for the other side, which
  is why Decision 12 chose current-state semantics for both.
- Mobile interactions, per-lane event totals, keyboard focus management inside
  the modal beyond `dbc.Modal`'s built-in behaviour.

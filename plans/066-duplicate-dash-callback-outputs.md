# Plan 066: Restore one-writer-per-output on the Dash callback graph

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 9fe08fe1..HEAD -- src/ui/ tests/`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: M
- **Risk**: MED
- **Depends on**: plans/065 (DONE — landed as commit `9fe08fe1`)
- **Category**: bug
- **Planned at**: commit `9fe08fe1`, 2026-11-10

## Why this matters

Dash's callback contract is **one writer per output property**. When two
callbacks declare the same `Output`, Dash 4.5 no longer raises at startup — it
accepts the registration silently, adds a second entry to the callback map, and
stores the per-callback contexts under a **hash-suffixed** key. The app appears
to work, so the defect is invisible until two callbacks that own the same output
fire in the same page session and the last writer silently wins.

**Why it is not merely theoretical.** The Dash docs state the contract, and this
repo already respects it deliberately in places: `src/ui/pages/chat.py:196-201`
and `:261-274` pass `allow_duplicate=True` with `prevent_initial_call=True` on
every shared output — evidence the team knows the rule and applies it
selectively. The collisions listed below are the ones where the flag is
**missing**.

**A verified live symptom exists already.** `catalog-metadata-store.data` is
declared by both `load_query_catalog` and `toggle_catalog_favourite`. Plan 065's
Gate B exercised both paths and passed, so the *current* behaviour happens to
work — the loader is a multi-output callback and the toggler is a single-output
one, which gives them distinct callback ids and lets Dash deliver both. That is
luck, not design: it depends on the arity of each callback, which any future
edit can change.

**What improves.** The output graph is restored to one writer per property,
matching what Dash requires and what the repo already does elsewhere. The
verification step adds a permanent, machine-checkable guard so a new collision
cannot be introduced silently.

## Current state

### The detection trap (read this first)

Dash serializes callback outputs in **two** encodings in
`GET /app/_dash-dependencies`:

- a **single** output → a dict: `{"id": "...", "property": "...", "allow_duplicate": false}`
- a **multi** output → one dotted **string**: `"..id1.prop1...id2.prop2.."`
  (note the `...` separator between entries and the `..` at both ends)

A detector that only handles the dict form **misses every multi-output callback
— including `catalog-metadata-store`**, because the loader declares three
outputs and therefore serializes as a string. This was confirmed by
observation: a dict-only detector reported 0 duplicates; the corrected detector
reported 22.

Use the library's own inverse function rather than re-implementing the split:

```python
from dash._utils import split_callback_id

split_callback_id("a.b")             # -> {"id": "a", "property": "b"}
split_callback_id("..a.b...c.d..")   # -> [{"id":"a","property":"b"}, {"id":"c","property":"d"}]
```

Also note: **`allow_duplicate` does not survive serialization.** In the live
JSON, both `streaming-active` entries report `allow_duplicate: false` even
though `src/ui/pages/chat.py:261,274` set it to `True`. Do not use the JSON to
decide whether a collision is sanctioned — read the source.

### The collision inventory (measured 2026-11-10, commit `9fe08fe1`)

22 duplicated output specs exist. They split into three groups:

**(a) False positives — do NOT touch.** `{"name":["MATCH"],...}` and
`{"...":["ALL"],...}` pattern-matching ids are scoped per callback by Dash;
identical strings across callbacks do not collide. 3 specs:
`catalog-person-chip.style`, `catalog-person-search-area.style`,
`catalog-person-value.data`.

**(b) Already sanctioned — verify only.** These carry `allow_duplicate=True` in
source; confirm and leave alone. `ego-loading-state.data`
(`collaboration_network_ego/callbacks/filter.py:524`), `timeline-loading-store.data`
(`timeline/callbacks.py:534,865,894`), the `time-slider-*-fine` family
(`graph/callbacks/filtering.py:578`).

**(c) The real defects — unsanctioned collisions.** No `allow_duplicate` on
either writer:

| Output | Writers | Notes |
|---|---|---|
| `catalog-metadata-store.data` | `graph/callbacks/catalog.py:268`, `:460` | the one found during plan 065 |
| `node-type-available-store.data` | `graph/callbacks/filtering.py:402`, `query.py:110` | |
| `relationship-type-available-store.data` | `graph/callbacks/filtering.py:305`, `query.py:111` | |
| `connector-scroll-trigger.data` | `connectors/callbacks.py:1614`, `:1631` | both `clientside_callback` |
| `collab-loading-state.data` | `collaboration_network/callbacks/filter.py:42` **and a second, dynamic writer — see the warning below** | |
| `ego-loading-state.data` | `collaboration_network_ego/callbacks/filter.py:96` + the same dynamic helper | one writer has `allow_duplicate=True`, the other does not |
| `timeline-loading-store.data` | `timeline/callbacks.py:550` + the same dynamic helper | as above |
| `timeline-deeplink-alert.children` | `timeline/callbacks.py:430`, `:667` | |

**⚠️ Some outputs are declared through a *dynamic* helper, so grepping for the
literal id will not find every writer.** `register_loading_overlay_hider` in
`src/ui/components/common.py:622-654` registers a `clientside_callback` whose
output is `Output(store_id, "data")` — a **parameter**, not a literal:

```python
        Output(store_id, "data"),  # dummy — we only write, never read back
        Input(store_id, "data"),
        prevent_initial_call=False,
```

It is called three times — `collaboration_network/callbacks/filter.py:301`
(`collab-loading-state`), `collaboration_network_ego/callbacks/filter.py:506`
(`ego-loading-state`), `timeline/callbacks.py:544` (`timeline-loading-store`) —
and each call adds a second writer for that store, silently. This is why
`collab-loading-state.data` has one grep hit but two live writers.

A similar pattern exists at `src/ui/components/common.py:546`
(`Output(cytoscape_id, "className")`) and `src/ui/components/spotlight.py:131`
(`Output(cytoscape_id, "elements", allow_duplicate=True)`).

**Consequence for the fix:** for these, the resolution is not to add
`allow_duplicate` at the call site — the `Output(store_id, "data")` line is a
*declared dummy* whose only purpose is to satisfy Dash's requirement that a
callback have at least one output. Prefer dropping the dummy output and using
`no_update` entirely clientside, or mark it `allow_duplicate=True` alongside the
real writer. Decide per case and say which you chose.

**Step 1 re-measures this list; the table above is a starting point, not a
substitute for running the detector.**

### Repo conventions that apply

- The sanctioned pattern is at `src/ui/pages/chat.py:196-201` — read it. A shared
  output takes `allow_duplicate=True` **and** the callback takes
  `prevent_initial_call=True` (Dash raises `DuplicateCallback` if
  `allow_duplicate=True` is used without it — see
  `.venv/lib/python3.14/site-packages/dash/_validate.py:594-619`).
- Where a collision is accidental (two callbacks that should never both own the
  property), prefer **removing** the duplicate output over adding
  `allow_duplicate` — the flag is for genuinely-intended multiple writers.
- Tests carry markers. A `unit`-marked test is the right home for the detector.
- Do **not** commit or push unless asked.

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Unit tests | `pytest -m unit tests -q` | ≥ **2632 passed**, 0 failed, 2 skipped |
| Duplicate detector | `pytest tests/test_dash_callback_outputs.py -q` | all pass |
| Typecheck | `mypy src/` | exit 0 |
| Lint | `pylint src --score=y` | ≥ 10.0 |
| Style | `flake8` | exit 0 |
| Live callback map | see Step 1 | see Step 1 |

The detector must run against the **live** callback map, which requires the
Compose stack (`docker compose up -d`). If the stack is down, the test must skip
rather than fail — mark it so.

## Scope

**In scope**:
- `src/ui/pages/graph/callbacks/catalog.py`
- `src/ui/pages/graph/callbacks/filtering.py`
- `src/ui/pages/graph/callbacks/query.py`
- `src/ui/pages/connectors/callbacks.py`
- `src/ui/pages/collaboration_network/callbacks/filter.py`
- `src/ui/pages/timeline/callbacks.py`
- `tests/test_dash_callback_outputs.py` (create)
- `src/ui/pages/chat.py` — **only** if the detector shows a genuine unsanctioned
  collision there; otherwise leave untouched

**Out of scope** (do NOT touch):
- Any callback already carrying `allow_duplicate=True` on **all** its writers —
  it is sanctioned; changing it is churn.
- `MATCH`/`ALL` pattern-matched ids — not real collisions.
- Any behaviour change to what a callback returns. This plan changes **which
  callbacks own which output**, never the values.
- `src/app/` — this is UI-only.
- Anything under `plans/` other than this file and `README.md`.

## Steps

### Step 1: Build the detector and re-measure the collision set

Create `tests/test_dash_callback_outputs.py`. Mark it `unit`, and skip when the
stack is unreachable (these tests read the live UI, unlike the rest of the
`unit` suite):

```python
pytestmark = [pytest.mark.unit]

def test_no_unsanctioned_duplicate_outputs() -> None:
    """Every output property is owned by exactly one callback, or all owners
    declare allow_duplicate=True."""
```

The detector must:

1. Fetch `GET https://localhost/app/_dash-dependencies` with a real session
   cookie (`tests.auth_helpers.session_cookies("user")`).
2. Normalise both output encodings using `dash._utils.split_callback_id`.
3. Group by `(component_id, property)`.
4. Exempt `MATCH`/`ALL` pattern ids.
5. For any group with >1 writer, assert the collision is sanctioned — which
   requires reading the **source** for `allow_duplicate=True`, since the flag is
   absent from the JSON. Resolve each callback id back to its `@callback`
   registration and check for the flag, **or** maintain an explicit allow-list of
   sanctioned pairs with a comment naming the file that sanctions it.

Option 2 (an explicit allow-list) is acceptable and simpler; the test then fails
when a *new* collision appears, which is the property that matters.

**Verify**: `pytest tests/test_dash_callback_outputs.py -q` → **fails**, listing
the group (c) collisions above. This failure is the expected outcome of Step 1 —
it proves the detector works and is not vacuous.

**Verify** (non-vacuousness, mandatory): temporarily add
`allow_duplicate=True` to a collision the allow-list does not cover, confirm the
test still fails for the other entries, then revert. A detector that passes when
collisions exist is worthless. Record the observed failure text.

### Step 2: Fix the collisions

For each group (c) entry, read both call sites and decide:

- **Accidental** (the two callbacks should not both own the property) → remove
  the `Output(...)` from the one that should not own it, and adjust that
  callback's return value / arity accordingly. This is the common case for a
  "state is set here *and* there" pair.
- **Intended** (the property is genuinely a shared scratchpad, as
  `catalog-metadata-store.data` is — the loader seeds it and the toggler mutates
  it) → add `allow_duplicate=True` to **both** writers and ensure the
  non-initial one has `prevent_initial_call=True`.

For `catalog-metadata-store.data` specifically: the intended shape is shared, so
use `allow_duplicate=True` on both. The loader fires on navigation
(`Input("url", "pathname")`), so it needs
`prevent_initial_call="initial_duplicate"` rather than `True` — verified: with
that combination Dash registers the pair without raising.

**Verify** after each file: `pytest -m unit tests -q` → no new failures.

**Verify**: `pytest tests/test_dash_callback_outputs.py -q` → **passes**.

### Step 3: Confirm no behaviour regressed

The contracts worth re-checking by hand, because the automated suite cannot see
them:

- Star a query on `/app/graph` as a logged-in user → the star fills in.
- Reload → the star is still filled (the loader's metadata seed still works).
- The connector edit flow (`connector-scroll-trigger`) still scrolls to the
  edited item.

**Verify**: record the observed result of each in your report.

## Test plan

- New: `tests/test_dash_callback_outputs.py` — the static detector described in
  Step 1. Structural pattern for the live-HTTP style:
  `tests/test_auth_flow.py` (drives `https://localhost`, uses `tests.auth_helpers`).
- The detector is the regression guard: it fails the moment a new collision is
  introduced without `allow_duplicate`.
- Non-vacuousness is checked in Step 1 by observing it fail against the current
  tree.

## Done criteria

- [ ] `pytest tests/test_dash_callback_outputs.py -q` passes
- [ ] Detector observed **failing** against the unfixed tree (recorded)
- [ ] `pytest -m unit tests -q` exits 0, ≥ 2632 passed
- [ ] `mypy src/` exits 0; `pylint src --score=y` ≥ 10.0; `flake8` exits 0
- [ ] Every group (c) collision resolved, and each resolution is either a removed
      duplicate `Output` or `allow_duplicate=True` on **all** its writers
- [ ] No `MATCH`/`ALL` pattern id was modified
- [ ] No callback's returned values changed
- [ ] Star toggle and connector-edit flows still work (Step 3 observed)
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report if:

- The live detector finds **fewer** group (c) collisions than the table above —
  the codebase drifted and this plan's inventory is stale.
- A fix requires changing what a callback **returns** (not just which outputs it
  declares) in a way that alters rendered content. That is a behaviour change
  beyond this plan's remit.
- Adding `allow_duplicate=True` raises `DuplicateCallback` at startup after
  `prevent_initial_call` is set — the Dash version behaves differently from what
  this plan assumes (Dash 4.5.0 was verified).
- Removing a duplicate `Output` leaves a callback with zero outputs.

## Maintenance notes

- **The detector is the lasting value here.** Future UI work adds callbacks
  constantly; without it, a new collision is silent. Keep it in the `unit` marker
  set so it runs in CI.
- **A reviewer should scrutinize**: that each fix chose *remove* vs
  *allow_duplicate* deliberately, and that `prevent_initial_call` accompanies
  every `allow_duplicate=True` (Dash raises otherwise).
- **Deferred out of this plan**: a broader audit of whether the *intended*
  shared-output pairs (`catalog-metadata-store` especially) would be better
  modelled as a single owning callback with `set_props`, the pattern already used
  in `src/ui/components/permission_errors.py:41-47`. That is a design change, not
  a defect fix.

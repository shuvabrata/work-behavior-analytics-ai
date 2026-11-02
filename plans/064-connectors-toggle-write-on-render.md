# Plan 064: Stop the Connectors page writing on render, and make the item toggle user-driven

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the next
> step. If anything in "STOP conditions" occurs, stop and report — do not
> improvise. When done, update the status row for this plan in `plans/README.md`
> — unless a reviewer dispatched you and told you they maintain the index.
>
> **Drift check (run first)**: `git diff --stat e9224091..HEAD -- src/ui/pages/connectors/callbacks.py tests/`
> If `src/ui/pages/connectors/callbacks.py` changed since this plan was written,
> compare the "Current state" excerpts against the live code before proceeding;
> on a mismatch, treat it as a STOP condition.
>
> **Reconciled 2026-11-02 at `8395a9e5`.** The drift check fires, but the drift is
> **line numbers only** (+3 to +27 in `callbacks.py`); every excerpted code shape
> is unchanged and the bug is still present. Current anchors: `render_items_list`
> `:499-502`, `is_active = item.get("enabled", True)` `:547`, the switch id `:702`,
> the toggle callback `:1373-1384`, the `PATCH` `:1409-1412`. **Locate by content,
> not by line number**, and do not stop on the non-empty diff.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: MED
- **Depends on**: plans/057 (the enforcement that made this visible — see "Why this matters")
- **Category**: bug
- **Planned at**: commit `e9224091`, 2026-11-01

## Why this matters

Selecting a connector on the Connectors page fires **one `PATCH` per configured
item**, with no user interaction. For a user this produces a red alert
("Failed to update configuration: Role 'wba-admin' is required.") on a page they
only *looked at*; for an admin it silently re-writes every item's `enabled` flag.

The admin case is the dangerous one, and it is invisible: the page reads
`enabled` into the switch, then PATCHes that same value straight back. Nothing
looks wrong. But if anything else changed an item between the read and the write
— a producer run, another browser tab — the page render **reverts it** to the
stale value. So this is a lost-update race, plus N redundant writes per page
view, plus the spurious 403s.

Measured live on 2026-11-01 before the fix, from `docker logs wba-ai-api`:

```
PATCH /api/v1/connectors/github/configs/1/status    401/403  (15 occurrences)
PATCH /api/v1/connectors/github/configs/6/status    403      (6 occurrences)
… 60 requests in total across ~6 page loads
```

What improves when this lands: viewing the page performs **zero** writes; the
spurious alert disappears for every role; and toggling an item still works when a
user actually clicks the switch.

**Note on ordering with plan 057.** The 403 alert only became visible after 057
turned on enforcement. That is what exposed this — but the write-on-render
behaviour and the lost-update race are **pre-existing** and unaffected by 057's
role decisions. Do not "fix" this by widening roles; the write should not be
happening at all.

### The sweep result — this is the only instance (read before designing a wider fix)

Every callback in `src/ui` that performs an API write was AST-swept on
2026-11-01 and classified by its `Input`:

- **27** take `n_clicks` / `submit_n_clicks` — genuinely user-gated.
- **2** take a store fed by a debounce, and POST read-only endpoints
  (`update_spotlight` → `/api/v1/search/scoped`; `execute_query` →
  `/api/v1/graph/execute`). POST is used because the payload exceeds nginx's 8 KB
  request-line limit (documented at `src/ui/pages/graph/callbacks/spotlight.py:8`),
  not because they mutate.
- **1** is this bug: `handle_inline_toggle`.

**Do not turn this into a framework or a lint rule.** There is exactly one
instance; fix that instance.

## Current state

All line numbers are from `src/ui/pages/connectors/callbacks.py` at `e9224091`.

**1. The render callback** (``:496-499``) — pure render, takes the items store and
emits the list:

```python
@callback(
    Output("connector-items-list", "children"),
    Input("connector-items-store", "data"),
)
def render_items_list(store: Dict[str, Any] | None) -> List[Any]:
```

**2. It reads `enabled` off the item** (``:546``):

```python
        is_active = item.get("enabled", True)
```

**3. …and bakes it into a switch whose id is a MATCH wildcard** (``:700-704``):

```python
                            html.Div(
                                dbc.Switch(
                                    id={"type": "config-enabled-switch", "connector_type": connector_type, "config_id": item_id},
                                    value=is_active,
                                    label="Active" if is_active else "Disabled",
                                    className="executive-switch mb-0",
                                ),
```

**4. The toggle callback listens to that same `value` prop** (``:1347-1358``):

```python
@callback(
    [
        Output("connector-action-feedback", "children", allow_duplicate=True),
        Output({"type": "config-enabled-switch", "connector_type": MATCH, "config_id": MATCH}, "value"),
        Output({"type": "config-enabled-switch", "connector_type": MATCH, "config_id": MATCH}, "label"),
        Output("connector-items-store", "data", allow_duplicate=True),
    ],
    Input({"type": "config-enabled-switch", "connector_type": MATCH, "config_id": MATCH}, "value"),
    State("connector-items-store", "data"),
    prevent_initial_call=True
)
def handle_inline_toggle(
    new_enabled_state: bool,
    store: Dict[str, Any] | None,
) -> tuple[dbc.Alert | Any, bool | Any, str, Dict[str, Any] | Any]:
```

**5. The PATCH** (``:1382-1385``):

```python
        api_client.patch(
            f"/api/v1/connectors/{connector_type}/configs/{config_id}/status",
            json={"enabled": new_enabled_state},
        )
```

### The root cause, precisely

`handle_inline_toggle` declares the switch's **`value`** as its `Input`. Dash fires
a callback when any `Input` changes — including when a *render* changes it. So:

1. `render_items_list` re-runs (any store change, navigation, refresh).
2. It rebuilds the switches. MATCH-id components are re-instantiated, which Dash
   treats as **new matches**, not as an initial call.
3. `prevent_initial_call=True` suppresses only the genuine first call of the
   layout — it does **not** cover re-instantiated MATCH matches.
4. Each new switch's `value` is "new" to Dash, so `handle_inline_toggle` fires
   once per item, `new_enabled_state` being the value the render just wrote.
5. Handler PATCHes that value back. Loop complete.

The value the handler receives came from the render, so a stale render writes a
stale value over a fresher one in the database. That is the lost update.

### Repo conventions that apply

- Dash callbacks are decorated at module level and registered by importing the
  page package; `src/ui/pages/connectors/__init__.py` already does this.
- Tests call callback functions **directly** and mock `callback_context`; see
  `tests/test_connectors_delete.py:30-50` for the exact pattern to match
  (including the `mock_ctx.triggered_id = {...}` idiom and the `PreventUpdate`
  assertion style).
- UI tests are `pytestmark = pytest.mark.unit` and use
  `unittest.mock.patch` on `ui.pages.connectors.callbacks.callback_context`.
- Styling constants come from `src/ui/styles.py`; do not introduce inline literals.
- Type hints on all parameters and returns.
- No comments except to explain a non-obvious "why".

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Activate venv | `source .venv/bin/activate` | venv on PATH |
| One test file | `pytest -m unit tests/test_connectors_toggle.py -q` | all pass |
| Connectors tests | `pytest -m unit tests/test_connectors_delete.py tests/test_connectors_scan_ui.py tests/test_connector_card.py -q` | all pass |
| Full unit suite | `pytest -m unit tests -q` | ≥ 2590 passed, 0 failed |
| Typecheck | `mypy src/` | exit 0 |
| Lint | `pylint src --score=y` | ≥ 9.0 |
| Baseline note | — | `pytest -m unit tests -q` was **2590 passed / 0 failed / 2 skipped** at `e9224091`. Re-verify; do not trust this line. |

## Scope

**In scope** (the only files you should modify or create):

- `src/ui/pages/connectors/callbacks.py` — the toggle fix.
- `tests/test_connectors_toggle.py` (create) — the regression tests.

**Out of scope** (do NOT touch, even though they look related):

- `src/app/auth/matrix.py`, `src/app/api/**` — the role/route decision is **057's**
  and is already settled: `PATCH /connectors/{type}/configs/{item_id}/status` is
  admin-or-service. This plan does not change it.
- `src/ui/pages/graph/**` — the read-only POST-by-verb callbacks there are correct
  and deliberate (payload size). Leave them.
- `src/ui/pages/settings/**`, `src/ui/pages/catalog/**`, `src/ui/pages/timeline/**`
  — swept and clean. No changes.
- Other callbacks in `connectors/callbacks.py` — all 13 others are `n_clicks`-gated.
- Any shared component or a new helper module. The fix is local to this page.

## Steps

### Step 1: Make the toggle a no-op when the value did not actually change

**Do not remove the switch, and do not change its layout, label, or styling.**
The fix is a guard inside `handle_inline_toggle`, not a restructuring of the list.

`handle_inline_toggle` already receives the items store as `State`. The store
holds the **last known value for every item** — the same values
`render_items_list` read when it built the switches. Therefore a switch change
that matches the store is, by definition, the render echoing its own value back.
A change that differs is a user action.

Add the guard immediately after the existing `store` validity check
(`callbacks.py:1374-1380`), before the `api_client.patch` call:

```python
    current = next(
        (item.get("enabled", True) for item in store.get("items", []) if item.get("id") == config_id),
        None,
    )
    if current is None or current == new_enabled_state:
        return no_update, no_update, no_update, no_update
```

`config_id` is already in scope (it is read from `triggered_id` a few lines
above). `no_update` is already imported in this module — confirm with
`grep -n "no_update" src/ui/pages/connectors/callbacks.py`.

**Why this is correct and terminates.** Trace a real click:

1. Store says `enabled=True`; the switch renders `value=True`.
2. The user clicks it to `False`. Dash fires the callback with
   `new_enabled_state=False`.
3. `current == True`, `new_enabled_state == False` → they differ, so the guard
   does not fire. The handler PATCHes, and returns the updated store with
   `enabled=False` plus the new switch value/label.
4. The store changed, so `render_items_list` re-runs and rebuilds the switch with
   `value=False`. That re-instantiation fires the callback again with
   `new_enabled_state=False`.
5. Now `current == False` and `new_enabled_state == False` → **equal, guard
   returns `no_update`. No second PATCH.** The loop stops after exactly one write.

And on a page render, every switch echoes its store value, so **every** call is
guarded out: zero writes.

**What this deliberately does not fix.** If the database changed behind the UI's
back, the render still shows the stale value and the guard suppresses the write —
which is the desired behaviour here (a page view must not overwrite data). The UI
showing stale data until reload is a separate, pre-existing display concern and is
**out of scope** for this plan. Do not add polling or refetching.

**Verify**: `grep -n "current == new_enabled_state" src/ui/pages/connectors/callbacks.py` → one match

> **STOP AND REPORT** if `no_update` is not already imported in this module, or if
> `config_id` is not in scope at the guard's location. Both were true at
> `e9224091`; if either is false the file has drifted.

### Step 2: Regression tests

Create `tests/test_connectors_toggle.py` with `pytestmark = pytest.mark.unit`.
Model the structure on `tests/test_connectors_delete.py` (direct callback
invocation, `patch` on `callback_context`, `ApiError` handling).

Cover these cases — each must assert something meaningful, not merely that a call
returned:

1. **Render performs no write.** Call `render_items_list` with a store containing
   two items; patch `ui.pages.connectors.callbacks.api_client` with a `MagicMock`
   and assert `.patch` was **never called** and `.post`/`.put`/`.delete` were
   never called. This is the regression this plan exists for.
2. **A genuine toggle still writes.** Call `handle_inline_toggle` with a mocked
   `callback_context.triggered_id` naming a real switch, `new_enabled_state=False`,
   and a valid store; assert `api_client.patch` was called once with
   `/api/v1/connectors/github/configs/42/status` and `json={"enabled": False}`.
3. **A toggle with no store is refused.** `store=None` (or `status != "ok"`) must
   return the reverted value and call nothing on `api_client`.
4. **A 403 produces the alert.** Patch `api_client.patch` to raise
   `ApiError(...)` and assert the returned first element is the danger alert whose
   text contains the error, and that the switch value is restored to the previous
   state.

### Step 3: Verify against the running stack

The end-to-end proof is that loading the page writes nothing.

1. Rebuild the UI: `docker compose up -d --build ui`
2. Note the current count in the API log:
   `docker logs wba-ai-api --since 1m 2>&1 | grep -c "configs/.*/status"`
3. Open `https://localhost/app`, go to Connectors, click the GitHub connector.
   **Wait 10 seconds. Do not click any switch.**
4. Re-run the same `grep -c` command. **Expected: the count has not increased.**
   Before the fix, this incremented by one per config item per load.

**Verify**: step 4's count is unchanged, and no `Failed to update configuration`
alert appears on the page.

## Test plan

Priority order:

1. **Render-performs-no-write** — the exact regression; a test that only checks
   the toggle still works would pass on the broken code too.
2. **A genuine toggle still writes** — proves the fix did not simply disable the
   feature. Without this, a "fix" that removes the `Input` entirely would pass.
3. **403 → alert** — pins the user-visible behaviour the operator reported.
4. **No-store guard.**

Structural pattern: `tests/test_connectors_delete.py`.

**Anti-vacuity (mandatory).** After the tests pass, revert your
`callbacks.py` fix temporarily, run `pytest -m unit tests/test_connectors_toggle.py -q`,
and confirm **test 1 fails** (the render writes). Restore the fix and confirm it
passes. Paste both outputs. A test 1 that passes against the broken code is
worthless and must be rewritten.

## Done criteria

ALL must hold:

- [ ] `pytest -m unit tests/test_connectors_toggle.py -q` passes (4 new tests)
- [ ] `pytest -m unit tests -q` exits 0, ≥ 2590 passed, 0 failed (state the number)
- [ ] `mypy src/` exits 0; `pylint src --score=y` ≥ 9.0
- [ ] Loading the Connectors page adds **zero** `configs/*/status` requests to the
      API log (Step 3, with both counts pasted)
- [ ] A genuine switch click still updates one item and shows no alert
- [ ] The anti-vacuity revert was performed and test 1 failed as required
- [ ] No files outside the Scope list are modified (`git status`)
- [ ] `plans/README.md` status row updated

## Execution record — 2026-11-02

Executor: one `general-purpose` subagent, working in the **current tree on `main`,
uncommitted** at the operator's instruction (not an isolated worktree). Reviewer:
this session.

**Result — approved.** Guard added to `handle_inline_toggle` exactly as specified;
`tests/test_connectors_toggle.py` created. Reviewer re-ran every gate
independently and reproduced: 6 passed (new file), 79 passed (connectors
regression), **2627 passed / 0 failed / 2 skipped** (full unit suite), `mypy src/`
clean, `pylint src` 9.69.

**Two plan errors surfaced and corrected during execution:**

1. **The 403 path does not produce the alert this plan predicted.** Step 2's case 4
   expected the danger alert "Failed to update configuration: …" for a 403. That
   path does not produce it: `PermissionDeniedError` subclasses `ApiError`
   (`src/ui/api_client.py:99`) and the `except (AuthExpiredError,
   PermissionDeniedError)` branch catches it *first* (`callbacks.py:1424`), routing
   through `handle_api_error` to a **warning** permission alert. The danger alert is
   reachable only via the plain `ApiError` branch. Both paths are now covered.
2. **The plan's literal test 1 cannot discriminate.** "Call `render_items_list` and
   assert `api_client.patch` was never called" passes against the *broken* code as
   well — `render_items_list` performs no write in either version. The write lives
   in `handle_inline_toggle`, fired by Dash's MATCH-id re-instantiation, which a
   direct function call does not reproduce. The plan's "anti-vacuity" instruction
   (revert the fix, confirm test 1 fails) therefore could not be satisfied as
   written. The executor kept the literal test as a contract pin and added
   **`test_render_echo_performs_no_write`**, which drives the toggle callback with
   the store's own value — exactly what Dash does — and *is* the discriminating
   regression test: it fails (5 passed / 1 failed) without the guard and passes
   with it.

**Stale numbers in this plan, corrected at dispatch:** the unit baseline was
**2621** at `8395a9e5`, not the stated 2590; the 6 new tests bring it to 2627.
All cited line numbers had drifted +3 to +27 (the plan's own reconcile note covers
this); the executor located everything by content.

**Not verified — operator action required.** Step 3 (zero `configs/*/status`
requests on page load) needs an authenticated Keycloak SSO browser session, which
neither the executor nor the reviewer could drive — credential lookup was blocked
by the permission classifier, correctly. Partial evidence obtained: `ui` image
rebuilt, `wba-ai-ui` healthy, and the running container's copy of `callbacks.py`
contains the guard (`docker exec wba-ai-ui grep -c "current == new_enabled_state"
…` → 1). The operator should log in at `https://localhost/app`, open Connectors,
select the GitHub connector, wait ~10s without touching a switch, and confirm the
API log count is unchanged; then click one switch and confirm exactly one PATCH.

## STOP conditions

Stop and report if:

- **You cannot find a fix satisfying (a) no write on render, (b) click still
  works, (c) UI unchanged — without inventing a mechanism.** Report the list
  composition and your proposed approach; do not guess. (See Step 1.)
- **`src/ui/pages/connectors/callbacks.py` does not match the "Current state"
  excerpts.** The file has drifted.
- **Fixing this appears to require touching `src/ui/components/` or another page.**
  The sweep says it should not.
- **`pytest -m unit tests -q` does not report 2590 passed / 0 failed / 2 skipped
  before you start.** Something other than this plan changed the baseline.
- **You are tempted to widen a role in `src/app/auth/matrix.py` to silence the
  alert.** That is the wrong fix and reverses a decision 057 settled deliberately.

## Maintenance notes

- **A render callback must never write to a store or prop it also listens to.**
  That cycle is what produced this bug. When adding a new control to this page,
  check which callback re-renders it, and ensure the control's `value` is not an
  `Input` to a callback whose `Output` feeds the render.
- **`prevent_initial_call=True` does not prevent this class of bug.** It covers
  the initial layout call only. Any MATCH-id component that is re-instantiated by
  a render will fire its `Input`s again. The 4 other callbacks on this page that
  use MATCH ids all key on `n_clicks` and are immune — keep it that way.
- **The lost-update race is the real severity.** If a future change reintroduces a
  write on render, the symptom in production will be *silent state reversion*, not
  an error — an admin will see nothing wrong.
- **Deferred:** plan 059 makes UI 401/403 responses render as a clear banner
  rather than a raw exception string. The alert text in test 4 will change shape
  when 059 lands; the assertion should remain "an alert is shown containing the
  error", not an exact string match on today's wording.

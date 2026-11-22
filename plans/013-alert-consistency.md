# Plan 013: One alert standard — neutral surface, compact geometry, app-wide font

> **Executor instructions**: This plan is **five steps**. Steps 1-4 each end at a
> human browser gate; step 5 is the closing command gate. Do one step, run its
> commands, report its measurements, then **STOP**. The operator reviews that step
> in the browser and replies with feedback; you iterate on that same step until
> they say it is done. **Do not start the next step on your own initiative.**
>
> **Gate protocol** (steps 1-4):
>
> 1. Make the step's edits.
> 2. Run the step's command checks and the rebuild command. Confirm the new code
>    is live in the container, not just on the host.
> 3. Collect the step's measurements in a browser and report them as a table with
>    real numbers.
> 4. State explicitly which of the step's requirements passed and which did not.
> 5. **STOP and wait.** Do not begin the next step, and do not "fix" a failing
>    requirement by changing a value the step does not name — report it instead.
> 6. When the operator replies with feedback, address only that feedback, re-run
>    the measurements, and report again. Repeat until they confirm the step.
>
> If anything in "STOP conditions" occurs, stop and report — do not improvise.
> When the whole plan is done, update the status row for this plan in
> `plans/README.md` — unless a reviewer dispatched you and told you they maintain
> the index.
>
> **Why the steps are split this way.** Step 1 changes the app's base font, which
> reaches *every* page. Step 2 changes what *every* alert looks like. Step 3
> removes the inline overrides that would otherwise keep some alerts inconsistent.
> Step 4 handles the one alert that is deliberately not a normal alert. Splitting
> the app-wide font change from the alert change means "the whole app looks
> different" and "the alerts look wrong" are separately attributable — the earlier
> flat version of this plan merged them and made a bad outcome impossible to act
> on.
>
> **Drift check (run first)**:
> `git diff --stat 652744e4..HEAD -- src/ui/styles.py src/ui/assets/executive-dashboard.css src/ui/components/common.py src/ui/pages/graph/utils/ui_components.py src/ui/pages/graph/callbacks/query.py src/ui/pages/settings/graph_styling/callbacks.py src/ui/pages/settings/user_management/callbacks.py src/ui/pages/collaboration_network/callbacks/filter.py docs/design/design-system.md`
> If any in-scope file changed since `652744e4`, compare the "Current state"
> excerpts against the live code before proceeding; on a mismatch, treat it as a
> STOP condition.

## Status

- **Priority**: P2
- **Effort**: M (five steps; four gated)
- **Risk**: MED (step 1 is app-wide; steps 2-4 are alert-only)
- **Depends on**: none
- **Category**: tech-debt (UI consistency / design tokens)
- **Planned at**: commit `652744e4`, 2026-11-22

### Progress

| Step | Scope | Status |
|---|---|---|
| 1 | App base font: `.app-shell` inherits Inter | TODO |
| 2 | Alert CSS: base rule, five variants, dismiss button, compact geometry | TODO |
| 3 | Remove the inline overrides that keep alerts inconsistent | TODO |
| 4 | The collaboration status banner gets its own class | TODO |
| 5 | Design doc + full CI gate | TODO |

## Why this matters

The app's alerts are the one surface that ignores the design system. Bootstrap
Materia's late rules paint them as solid saturated slabs — `background: #4caf50
linear-gradient(...)` for success, `#e51c23` for danger — and the app's stylesheet
never overrides them. So an alert is a bright green or red block sitting in a
workbench whose other surfaces are neutral cards with a 1px border. In the dark
theme it is worse: the slab colours are hardcoded light-theme hex values, so a
dark-mode page shows a light-green alert.

The height is also wrong. Materia's `.alert` applies `--bs-alert-bg` plus
`padding: var(--bs-alert-padding-y) var(--bs-alert-padding-x)`, which is 16px on
every side. A single-line alert therefore stands about 48px tall for one line of
text. The app already has a compact precedent — `.alert-inline-badge` — but it is
used by exactly one call site.

And the type is inconsistent. There are **five distinct** font sizes in play
across six alert builders, because each builder sets its own inline size:

| Builder | Size | Alerts |
|---|---|---|
| `create_alert` (inline `style`) | 13px (`FONT_SIZE_XSMALL`) | 77 |
| `VALIDATION_ALERT_STYLE` | 14px (`FONT_SIZE_SMALL`) | 3 |
| `.alert-inline-badge` (CSS) | 13px (`var(--font-size-xsmall)`) | 1 |
| raw `dbc.Alert` inline | 11px (`FONT_SIZE_XTINY`) | 2 |
| `ALERT_TEXT_STYLE` (inline `<p>`) | 15px (`FONT_SIZE_MEDIUM`) | 1 |
| `.alert-heading` (Materia) | 1.25rem | 1 |

Two changes are wanted, and they have different blast radii:

- **The base font is app-wide.** `.app-shell` sets no `font-family`, so every
  inherited text node falls back to Materia's `--bs-body-font-family`, which is
  Roboto. Every explicitly-styled element — including every alert — sets Inter.
  The app is therefore half Roboto and half Inter. Step 1 fixes the base, and
  step 1's gate is where the effect on every page is judged.
- **The alert surface is component-wide.** Every alert in the app is a Bootstrap
  `.alert`, so a base `.alert` rule reaches all of them. Steps 2-4 change that
  rule, the inline overrides that fight it, and the one alert that is not a
  normal alert.

The honest summary is: **the base font is global, the alert surface is one
component.** There is no page-scoping mechanism here, and none is needed — an
alert is an alert wherever it appears.

## Current state

### The alert CSS today

`src/ui/assets/executive-dashboard.css` has **no base `.alert` rule at all**. The
only alert rules are two compact blocks and one unrelated sticky-container rule:

```css
/* src/ui/assets/executive-dashboard.css:703-718 */
.alert-inline-badge.alert {
    font-family: var(--font-sans);
    font-size: var(--font-size-xsmall);
    padding: 3px 22px 3px 8px;
    margin-bottom: 0;
}

.alert-inline-badge.alert-dismissible .btn-close {
    padding: 0;
    top: 50%;
    right: 6px;
    transform: translateY(-50%);
    width: 10px;
    height: 10px;
    background-size: 10px auto;
}
```

There is no `.alert { }` selector anywhere in the file. Every alert therefore
inherits Materia's slab treatment, 16px padding and 6px radius.

### The base font today

```css
/* src/ui/assets/executive-dashboard.css:135-142 */
.app-shell {
    background-color: var(--color-background-light);
    height: 100vh;
    display: flex;
    flex-direction: column;
    overflow: hidden;
    font-size: 15px;
}
```

No `font-family`. Bootstrap Materia's `--bs-body-font-family` is `Roboto,
-apple-system, ...`, so inherited text renders in Roboto while every
`style={"fontFamily": FONT_SANS}` element renders in Inter.

### The five alert builders

```python
# src/ui/components/common.py:161-174 — 77 call sites
def create_alert(...):
    merged_style = {
        "fontFamily": FONT_SANS,
        "fontSize": FONT_SIZE_XSMALL,        # 13px
        **(style or {}),
    }
```

It sets only the family and the size — no border, radius or padding. The slab
appearance comes entirely from Materia's `.alert` rules, not from Python.

```python
# src/ui/styles.py:367-369
VALIDATION_ALERT_STYLE = {
    "fontSize": FONT_SIZE_SMALL
}
```

```python
# src/ui/styles.py:514-516
ALERT_TEXT_STYLE = {
    "fontSize": FONT_SIZE_MEDIUM
}
```

```python
# src/ui/pages/settings/graph_styling/callbacks.py:378
style={"fontSize": FONT_SIZE_XTINY},     # 11px
```

```python
# src/ui/pages/settings/user_management/callbacks.py:41
style={"fontSize": FONT_SIZE_XTINY},     # 11px
```

### The one alert that is not a normal alert

```python
# src/ui/pages/collaboration_network/callbacks/filter.py:784
create_alert(
    ...,
    color="light",
    class_name="mb-0 py-2",
    style={"fontSize": FONT_SIZE_SMALL},
)
```

This is the org-network status banner above the graph. It is a persistent header
strip, not an interruption, and its larger size and extra vertical padding are
deliberate. It must keep them; it just needs to keep them through a class rather
than an inline style.

### Tests that touch alerts

`tests/test_ui_permission_errors.py` asserts `alert.color`, `alert.dismissable`
and the text — never `alert.style`. No test asserts any alert font size or
padding. The change is therefore test-neutral; the full suite is the check.

### Repo conventions that apply

- **Design docs must not cite `file:line`** and must not reference plan numbers,
  letters, or stages. Name the module, never the line.
- **Design docs must not carry meta-explanations** — state the fact, never why a
  passage exists or why wording was chosen.
- Comments explain **why**, never **what**.
- `styles.py` re-exports theme tokens with an explicit `__all__`; removing a
  module-level constant that another module imports needs the import removed too.

## Commands you will need

Run from the repo root. Activate the virtualenv first: `source .venv/bin/activate`.

| Purpose | Command | Expected on success |
|---|---|---|
| Unit tests | `pytest -m unit tests -q` | all pass |
| Typecheck | `mypy src/` | exit 0, no errors |
| Lint | `pylint src --score=y` | score ≥ 10.0 |
| Rebuild the UI | `docker compose build ui && docker compose up -d --force-recreate ui` | container recreated |
| Confirm the container has the new code | `docker compose exec ui grep -c "<a value you changed>" /app/ui/<path>` | ≥ 1 |

**`docker compose build` alone is not enough** — it leaves the old container
serving the old code. Always follow with `--force-recreate`, and confirm the new
value is live **by reading it out of the container**, not out of the host file.

The container path is `/app/ui/...`, not `/app/src/ui/...` — `Dockerfile.ui`
copies `src/ui/` to `./ui/`.

## Suggested executor toolkit

- Measure through `https://localhost/app/...`. The Compose stack terminates TLS
  at the `nginx` service; neither the `api` nor the `ui` service publishes a host
  port.
- The `chrome-devtools` MCP tools, if available, are the cheapest way to measure
  rendered geometry. If Chrome is not installed for that MCP, drive the Playwright
  Chromium binary at
  `~/.cache/ms-playwright/chromium-1248/chrome-linux64/chrome` over CDP instead.
- **Measure computed styles, not the stylesheet.** For an alert, read
  `getComputedStyle(el).backgroundColor`, `.fontSize`, `.fontFamily`,
  `.paddingTop`, `.borderLeftColor` and `.borderRadius`. Reading the CSS file tells
  you what you wrote; computed style tells you what won the cascade.

## Scope

**In scope** (the only files you should modify):

- `src/ui/assets/executive-dashboard.css` — `.app-shell` base font, the new
  `.alert` base rule and variants, the dismiss-button rule, the
  `.alert-status-banner` class, and the removal of the superseded
  `.alert-inline-badge` block
- `src/ui/components/common.py` — remove the inline `fontSize` and `fontFamily`
  from `create_alert`'s merged style
- `src/ui/styles.py` — remove `VALIDATION_ALERT_STYLE` and `ALERT_TEXT_STYLE`
- `src/ui/pages/graph/utils/ui_components.py` — stop importing and applying
  `ALERT_TEXT_STYLE`
- `src/ui/pages/graph/callbacks/query.py` — stop passing `VALIDATION_ALERT_STYLE`
- `src/ui/pages/settings/graph_styling/callbacks.py` — remove the inline style
- `src/ui/pages/settings/user_management/callbacks.py` — remove the inline style
- `src/ui/pages/collaboration_network/callbacks/filter.py` — swap the inline style
  for the class
- `docs/design/design-system.md` — the new Alerts section (step 5)

**Out of scope** (do NOT touch, even though they look related):

- **`ALERT_LINK_STYLE`, `ALERT_SEPARATOR_STYLE`, `ALERT_HINT_STYLE` and
  `ALERT_DOC_LINK_ICON_STYLE` in `src/ui/styles.py`.** Only two of the five alert
  constants are removed. The link, separator, hint and doc-link-icon styles set
  properties the base rule does not set (colour, underline, margin), so they stay
  valid. Do not "tidy" them away.
- **`create_permission_denied_alert`** in `src/ui/components/common.py`. It calls
  `create_alert`, so it inherits the change automatically. Do not edit it.
- **The `.card-config-alert` rule** in the stylesheet. It is a sticky wrapper
  `div` around the Analytics config feedback, not an alert surface. It is not a
  `.alert` element and the base rule does not reach it.
- **Any `SPACING_*` or `FONT_SIZE_*` token value.** This plan changes no token
  value. It removes two constants and changes CSS.
- **`docs/design/frontend-design-skill.md`.** Its design-direction block is about
  page composition; an alert is a component. Nothing there needs to change.

## Git workflow

- You are on branch `feature/table-consistency`. Create a new branch first:
  `git checkout -b alert-consistency`.
- **One commit per step**, after that step's gate is confirmed by the operator.
  Commit messages are **plain imperative sentences** — see `git log --oneline`
  for the style.
- **Do NOT push and do NOT open a PR.** Leave the work on the branch and report.

## Steps

Steps 1-4 each end at a manual gate. Follow the gate protocol in the header: do
the step, report measurements, **stop**, iterate on feedback, and only move on
when the operator confirms.

---

### Step 1 — Give the app one base font (MANUAL GATE)

Everything here is global. The gate is where the operator judges whether the app
now reads as one typeface.

#### 1a. Pin the base font on `.app-shell`

In `src/ui/assets/executive-dashboard.css`, the `.app-shell` rule gains one
declaration:

```css
.app-shell {
    background-color: var(--color-background-light);
    height: 100vh;
    display: flex;
    flex-direction: column;
    overflow: hidden;
    /* Unstyled text would otherwise inherit Bootstrap Materia's Roboto while
       every explicitly-styled element renders in Inter. Pin the base so the
       two agree. */
    font-family: var(--font-sans);
    font-size: 15px;
}
```

`--font-sans` is already defined in the custom-property block as `Inter,
-apple-system, ...`. Nothing else changes.

**Step 1 verification**:

```bash
grep -c "font-family: var(--font-sans)" src/ui/assets/executive-dashboard.css   # ≥ 1
grep -A8 "^\.app-shell {" src/ui/assets/executive-dashboard.css | grep -c "font-family"   # 1
pytest -m unit tests -q
```

#### GATE 1 — browser review of the base font

Rebuild and confirm the container is live:

```bash
docker compose build ui && docker compose up -d --force-recreate ui
docker compose exec ui grep -A8 "^\.app-shell {" /app/ui/assets/executive-dashboard.css | grep -c "font-family"
```

Then measure and report. The requirement is one thing: **inherited text now
renders in Inter.**

For each of these routes, report the computed `font-family` of a plain text node
(not a styled element) and of an alert where one is visible:

| Route | What to measure |
|---|---|
| `/app/analytics` | a card's body text |
| `/app/settings/user-management` | a table cell |
| `/app/connectors` | a connector name |
| `/app/chat` | a message line |
| `/app/graph` | a filter label |

**Requirement**: every measured node reports `Inter` (or the Inter stack), not
`Roboto`. Report the exact computed string, including the fallback chain.

Also confirm **both themes** on Analytics and Chat. A font change should not
interact with theme, but confirm it rather than assume it.

**Report** the table, state whether the requirement passed, and **stop**.

---

### Step 2 — Replace the alert surface (MANUAL GATE)

This is the whole visual change. It touches one CSS block and nothing else.

#### 2a. Add the base `.alert` rule

Append a clearly-delimited section to `src/ui/assets/executive-dashboard.css`:

```css
/* ============================================================================= */
/* Alerts — one surface for every variant                                         */
/* ============================================================================= */

/* The base is neutral in both themes; the variant only colours the left edge.
   Bootstrap Materia paints each variant as a solid slab with a hardcoded
   light-theme hex, which reads as a marketing banner in a workbench and breaks
   in the dark theme. A neutral surface plus a coloured edge carries the same
   semantics without the slab. */
.alert {
    background-color: var(--color-background-light);
    background-image: none;
    border: 1px solid var(--color-border);
    border-left: 3px solid var(--color-border);
    border-radius: 2px;
    color: var(--color-charcoal);
    font-family: var(--font-sans);
    font-size: var(--font-size-xsmall);
    padding: 6px 12px;
    margin-bottom: 8px;
}

.alert-success  { border-left-color: var(--color-success); }
.alert-warning  { border-left-color: var(--color-warning); }
.alert-danger   { border-left-color: var(--color-error); }
.alert-info     { border-left-color: var(--color-info); }
.alert-primary  { border-left-color: var(--color-navy); }
.alert-secondary,
.alert-light,
.alert-dark     { border-left-color: var(--color-border); }

/* A dismissable alert needs room on the right for the ×, and the base rule's
   symmetric 12px does not provide it. */
.alert.alert-dismissible { padding-right: 22px; }

/* Materia renders an alert heading at 1.25rem. Inside a 31px-tall compact alert
   that dominates the text beneath it; one step above the body keeps the
   hierarchy without the banner weight. */
.alert .alert-heading {
    font-size: var(--font-size-small);
    font-weight: 600;
    margin: 0 0 4px 0;
}

/* Bootstrap anchors the × at top:0 with a 16px padding box, which sits it
   outside a compact alert's text line. Re-anchor it to the vertical centre. */
.alert .btn-close {
    padding: 0;
    top: 50%;
    right: 8px;
    transform: translateY(-50%);
    width: 10px;
    height: 10px;
    background-size: 10px auto;
}
```

All five accent tokens exist in the `:root` block: `--color-success`,
`--color-warning`, `--color-error`, `--color-info` and `--color-navy`. Note the
danger variant maps to `--color-error` — there is no `--color-danger` token.
`--color-background-light`, `--color-border`, `--color-charcoal` and
`--font-sans` are all defined there too.

The base font size is `--font-size-xsmall` (13px), which is the single size the
whole app's alerts should use. Do not use `--font-size-small` (14px) here.

#### 2b. Remove the superseded `.alert-inline-badge` block

The block at lines 703-716 is now redundant — the base rule covers its size,
padding, radius and font. Delete it. The **class name stays in use** by the
Catalog editor badge, so do not remove the class from any Python file; only the
CSS block goes.

#### 2c. Scope the status banner

The collaboration org-network banner is not an interruption — it is a persistent
header strip above the graph — so it should not take the compact geometry. Add a
class for it:

```css
.alert-status-banner {
    padding: 8px 12px;
    font-size: var(--font-size-small);
}
```

Step 4 applies the class. Declaring it here keeps the CSS review in one place.

**Step 2 verification**:

```bash
grep -c "^\.alert {" src/ui/assets/executive-dashboard.css          # 1
grep -c "alert-inline-badge" src/ui/assets/executive-dashboard.css  # 0
grep -c "alert-status-banner" src/ui/assets/executive-dashboard.css # 1
pytest -m unit tests -q
```

#### GATE 2 — browser review of the alert surface

Rebuild and confirm the container is live:

```bash
docker compose build ui && docker compose up -d --force-recreate ui
docker compose exec ui grep -c "^\.alert {" /app/ui/assets/executive-dashboard.css
```

Then measure every alert type. Trigger each one and report computed style:

| Alert | Where to trigger | Variant |
|---|---|---|
| Connector save success | Connectors → edit a connector → save | success |
| Connector save failure | Connectors → save with an invalid field | danger |
| Permission denied | A 403 path (or the Settings users page as a non-admin) | warning |
| Validation warning | Graph → run an invalid query | warning |
| Status banner | `/app/collaboration` | light |

For each, report: `backgroundColor`, `borderLeftColor`, `borderLeftWidth`,
`borderRadius`, `fontSize`, `fontFamily`, `paddingTop`, `paddingBottom`, and the
rendered **height**.

**Requirements**:

- Every alert's background is the neutral surface, not a saturated slab. Report
  the computed RGB and confirm it is not one of Materia's variant hexes.
- Every alert's font size is the same value, and its font family is Inter.
- Single-line alerts are **shorter than the pre-change height**. Record the
  before/after height.
- The dismiss button sits inside the alert's bounds, not outside them.
- **Both themes.** In the dark theme, confirm the surface is dark and the text is
  light — the failure mode this plan exists to fix is a light slab on a dark page.

**Report** the table and the before/after heights, state which requirements
passed, and **stop**.

---

### Step 3 — Remove the inline overrides (MANUAL GATE)

Step 2's CSS cannot win against an inline style. This step removes the inline
styles so the base rule is the only thing setting an alert's type.

#### 3a. Simplify `create_alert`

In `src/ui/components/common.py`, the function currently merges a size and a
family into the caller's style. After this step it applies no type at all —
the CSS owns it. Keep the signature and keep merging the caller's `style`, so a
caller that genuinely needs an override still can.

Remove the `fontSize` and `fontFamily` keys from the merged style. Those are the
only two keys the function contributes, so what remains is the caller's own
`style` passed through unchanged.

#### 3b. Remove the two dead constants

In `src/ui/styles.py`, delete `VALIDATION_ALERT_STYLE` and `ALERT_TEXT_STYLE`.
Then remove their imports and call sites:

- `src/ui/pages/graph/callbacks/query.py` — stop importing
  `VALIDATION_ALERT_STYLE` and stop passing `style=VALIDATION_ALERT_STYLE` at its
  three call sites.
- `src/ui/pages/graph/utils/ui_components.py` — stop importing `ALERT_TEXT_STYLE`
  and stop applying it to the hint text.

Do **not** remove `ALERT_LINK_STYLE`, `ALERT_SEPARATOR_STYLE`, `ALERT_HINT_STYLE`
or `ALERT_DOC_LINK_ICON_STYLE` — they set properties the base rule does not.

#### 3c. Remove the two raw inline styles

In `src/ui/pages/settings/graph_styling/callbacks.py` and
`src/ui/pages/settings/user_management/callbacks.py`, remove the
`style={"fontSize": FONT_SIZE_XTINY}` argument from the `dbc.Alert` call. Remove
the now-unused `FONT_SIZE_XTINY` import if nothing else in the module uses it —
check before removing.

**Step 3 verification**:

```bash
grep -rn "VALIDATION_ALERT_STYLE\|ALERT_TEXT_STYLE" src/   # no matches
grep -rn "fontSize.*FONT_SIZE_XTINY" src/ui/pages/settings/graph_styling/callbacks.py src/ui/pages/settings/user_management/callbacks.py   # no matches
pytest -m unit tests -q
mypy src/
```

#### GATE 3 — browser review of the type consistency

Rebuild and confirm the container is live. Then re-measure the same five alerts
from gate 2 and add the two that were previously 11px:

| Alert | Where |
|---|---|
| Settings → Graph Styling save feedback | `/app/settings/graph-styling` |
| Settings → User Management action feedback | `/app/settings/user-management` |
| Graph validation warning | `/app/graph`, invalid query |

**Requirement**: every alert in the app now reports the **same** computed
`fontSize`. Report the value and confirm no alert differs. Also confirm no alert
grew a scrollbar or clipped its text — removing a size override can make text
larger, which is the intended direction, but a fixed-height container could clip.

**Report** the table, state whether the requirement passed, and **stop**.

---

### Step 4 — The status banner gets its class (MANUAL GATE)

#### 4a. Swap the inline style for the class

In `src/ui/pages/collaboration_network/callbacks/filter.py`, the banner currently
passes `style={"fontSize": FONT_SIZE_SMALL}`. Replace it with the class declared
in step 2c, keeping the existing `class_name` value:

```python
create_alert(
    ...,
    color="light",
    class_name="mb-0 alert-status-banner",
)
```

Then remove the `FONT_SIZE_SMALL` import if nothing else in the module uses it.

**Step 4 verification**:

```bash
grep -n "alert-status-banner" src/ui/pages/collaboration_network/callbacks/filter.py   # 1
grep -n "fontSize" src/ui/pages/collaboration_network/callbacks/filter.py             # no matches
pytest -m unit tests -q
```

#### GATE 4 — browser review of the status banner

Rebuild and confirm the container is live. Then measure `/app/collaboration`:

- The banner's height and computed padding, versus the pre-change value.
- Its font size, and confirmation that it is **larger** than a normal alert's.
- That it sits flush above the graph with no visible gap change.
- **Both themes.**

**Requirement**: the banner keeps its larger size and extra vertical padding, and
is visibly distinct from a normal alert. It must not have become compact.

**Report** the numbers, state whether the requirement passed, and **stop**.

---

### Step 5 — Design doc and full CI gate

No browser gate. Do this only after gates 1-4 are confirmed.

#### 5a. Add the Alerts section to `docs/design/design-system.md`

Place it under `## Components`, after the Destructive Buttons section. It must
state:

- The surface recipe: neutral background, 1px border, 3px coloured left edge,
  2px radius.
- The five variants and their accent colours, named by token.
- That the base type is set once by the `.alert` rule and that builders must not
  set `fontSize` or `fontFamily` inline.
- The compact geometry, and that `.alert-status-banner` is the exception for
  persistent strips.
- That the surface is theme-neutral and needs no dark-theme override.

Constraints for this file:

- **Never cite a line number.** Name the class or the module.
- **Never reference this plan** by number, letter, or stage.
- **No meta-explanations.** State what is true; do not explain why the section
  exists.

#### 5b. Run the full gate

```bash
source .venv/bin/activate
pytest -m unit tests -q
mypy src/
pylint src --score=y
```

**Verify**: unit tests pass; `mypy` exits 0; `pylint` reports ≥ 10.0. These are
the three CI gates this change can affect. The PR workflow
(`.github/workflows/pr_checks.yml`) also runs a spec-freshness check and bandit,
neither of which a UI change can disturb.

## Test plan

**No new test files.** This is a visual change, and the only meaningful evidence
is measured rendered geometry, which each gate requires. The existing suite must
stay green:

- `tests/test_ui_permission_errors.py` asserts `alert.color`, `alert.dismissable`
  and the text — never `alert.style`. Removing the inline style cannot break it.
- No test asserts an alert font size or padding. If a test fails after step 3,
  it is because a module-level import was removed and a call site still uses it —
  fix the call site, do not loosen the test.

## Done criteria

ALL must hold, **after gates 1-4 have each been confirmed by the operator**:

- [ ] `pytest -m unit tests -q` exits 0
- [ ] `mypy src/` exits 0
- [ ] `pylint src --score=y` reports ≥ 10.0
- [ ] `grep -c "^\.alert {" src/ui/assets/executive-dashboard.css` → 1
- [ ] `grep -c "alert-inline-badge" src/ui/assets/executive-dashboard.css` → 0
- [ ] `grep -rn "VALIDATION_ALERT_STYLE\|ALERT_TEXT_STYLE" src/` → no matches
- [ ] `grep -rn "font-family: var(--font-sans)" src/ui/assets/executive-dashboard.css` → ≥ 1
- [ ] **Gate 1 confirmed**: inherited text renders in Inter on every sampled page,
      in both themes
- [ ] **Gate 2 confirmed**: every alert has a neutral surface, one font size, and
      a shorter single-line height; the dismiss button sits inside the alert
- [ ] **Gate 3 confirmed**: every alert in the app reports the same font size
- [ ] **Gate 4 confirmed**: the collaboration status banner kept its larger size
- [ ] `docs/design/design-system.md` has an Alerts section with no line numbers and
      no plan reference
- [ ] No files outside the in-scope list are modified (`git status`)
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report back (do not improvise) if:

- The `.alert` selectors, the `create_alert` style block, or the five builder call
  sites do not match the "Current state" excerpts — the codebase has drifted.
- **A step's gate is not yet confirmed by the operator.** Do not proceed to the
  next step. This is the plan's primary control.
- **Step 1 makes any page visibly worse.** A base font change can reflow text
  that was measured against Roboto's metrics. If a page's text wraps where it did
  not before, report the page and the element — do not compensate by shrinking a
  font size, and do not revert the whole change.
- **Step 2's base rule does not win.** If a computed `backgroundColor` is still
  one of Materia's variant hexes, a more specific rule is winning. Report the
  selector that won; do not escalate to `!important`.
- **`--color-info` does not exist** under that name. Report the actual token name
  rather than adding a new custom property.
- Removing a constant in step 3 leaves a module with an unused import that
  `pylint` flags. Fix the import; do not disable the lint check.
- A `class_name` argument in Python already contains the class you are adding, so
  the class appears twice. Report it rather than guessing which to keep.

## Maintenance notes

For whoever owns this after it lands:

- **The alert surface is now CSS-owned.** A future builder that sets an inline
  `fontSize` or `padding` on an alert will silently override the base rule and
  reintroduce the inconsistency. A reviewer should reject inline type on a
  `.alert`.
- **The variant list is not exhaustive.** Only the six variants in use are
  styled. Bootstrap has more; a new one will render with the neutral surface and
  a neutral edge, which is correct but undifferentiated. Add a variant rule when
  a new semantic colour is actually used.
- **Materia's slab rules are still present in the bundle.** The base rule wins by
  cascade order today, which is a property of the stylesheet being loaded after
  Materia. If the asset order ever changes, alerts will revert to slabs. The
  `background-image: none` declaration is what makes this safe against the
  shorthand; do not remove it.
- **The base font is set on `.app-shell`, not on `body`.** Text rendered outside
  the shell — a modal portal, a tooltip appended to `body` — does not inherit it.
  Those surfaces set their own family today. If a new portal appears unstyled, it
  will render in Roboto.

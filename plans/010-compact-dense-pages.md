# Plan 010: Compact the data-dense pages and raise the app-wide font scale

> **Executor instructions**: This plan is **eight steps, each gated by a human
> browser review**. Do one step, run its commands, report its measurements, then
> **STOP**. The operator reviews that step in the browser and replies with
> feedback; you iterate on that same step until they say it is done. **Do not
> start the next step on your own initiative.** Steps 1-6 each end at a manual
> gate; step 7 is documentation and step 8 is the closing command gate.
>
> **Gate protocol** (applies to steps 1-6):
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
> **Why the steps are split this way.** Step 1 changes what *every* page looks
> like (text scale and shared chrome). Steps 2-6 change *one page each*, so a
> change that looks wrong can be attributed to a single page and reverted without
> touching the others. That attribution is the point of the split: the earlier
> flat version of this plan made a page's density and the app's text scale
> arrive together, which made "this page looks worse" impossible to act on.
>
> **Drift check (run first)**:
> `git diff --stat cef02fa4..HEAD -- src/ui/styles.py src/ui/layout.py src/ui/assets/executive-dashboard.css src/ui/pages/graph src/ui/pages/timeline src/ui/pages/search.py src/ui/pages/catalog src/ui/pages/collaboration_network src/ui/pages/collaboration_network_ego src/ui/components/result_pane.py src/ui/components/person_picker.py tests/test_person_autocomplete.py tests/test_shared_graph_components.py docs/design/design-system.md docs/design/frontend-design-skill.md`
> `src/ui/pages/chat.py` and `tests/test_chat_stream_bridge.py` are **not** in
> scope and are already modified on this branch — that is unrelated work, leave
> it alone. If any *in-scope* file changed since `cef02fa4`, compare the "Current
> state" excerpts against the live code before proceeding; on a mismatch, treat
> it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: L (eight gated steps; the operator reviews between each)
- **Risk**: MED
- **Depends on**: none
- **Category**: tech-debt (UI density / design tokens)
- **Planned at**: commit `cef02fa4`, 2026-11-21

### Progress

| Step | Scope | Status |
|---|---|---|
| 1 | Shared text scale, shared chrome, `.dense-page` CSS | ✅ DONE (gate 1 confirmed) |
| 2 | Graph | ✅ DONE (gate 2 confirmed) |
| 3 | Timeline | ✅ DONE (gate 3 confirmed) |
| 4 | Search | ✅ DONE (gate 4 confirmed) |
| 5 | Catalog | ✅ DONE (gate 5 confirmed) |
| 6 | Collaboration Network (both pages) | ✅ DONE (gate 6 confirmed) |
| 7 | Design docs | ⬜ TODO |
| 8 | Full CI gate | ⬜ TODO |

## Why this matters

The app is a heavy-duty workbench, but it spends screen area the way a marketing
page does: the top bar is a fixed 44px, the content wrapper adds 8px on every
side, panel gutters are 24px each, and card padding is 24px. Meanwhile the
typography sits *below* the browser default — Bootstrap Materia sets a 16px body
font and the app styles almost everything at 9–15px. So the app is at once
spacious around its content and small in its content.

Two changes are wanted, and they have different blast radii. Being explicit about
which is which is what makes this plan reviewable:

- **The text scale and the shared chrome are app-wide.** The font tokens, the
  stylesheet's literal sizes, the top bar and the page header are used by every
  page, card pages included. Step 1 changes them, and step 1's gate is where the
  effect on the card pages (Analytics, Connectors, Settings, Developer, Chat) is
  judged. There is no page-scoping mechanism that could exempt them: the tokens
  have ~159 call sites on card/form pages against ~87 on dense pages, so a token
  raise is a *larger* change to the card pages than to the dense ones.
- **Density is per-page.** Reclaiming gutters, padding and canvas height is
  wanted only on the pages that display **lists and graphs** — Graph, Timeline,
  Search, Catalog, and the two Collaboration Network pages. This is delivered by
  a root CSS class, `.dense-page`, that those six pages opt into. The shared
  `SPACING_*` token values are never changed, so the card pages cannot get
  tighter.

So the honest summary is: **text and chrome are global, density is per-page.**
Steps 2-6 each add one page's density, and because step 1 has already landed the
global half, each of those steps shows only that page's change.

## Current state

### The token layer

`src/ui/styles.py` holds the design tokens. These are the blocks step 1 changes
(the spacing block stays as-is — see "Scope"):

```python
# src/ui/styles.py:32-39
FONT_SIZE_XLARGE = "42px"
FONT_SIZE_LARGE = "15px"
FONT_SIZE_MEDIUM = "14px"
FONT_SIZE_SMALL = "13px"
FONT_SIZE_XSMALL = "12px"
FONT_SIZE_TINY = "11px"
FONT_SIZE_XTINY = "10px"
FONT_SIZE_XXSMALL = "9px"
```

```python
# src/ui/styles.py:125-132
SPACING_XXXSMALL = "4px"
SPACING_XXSMALL = "8px"
SPACING_XSMALL = "12px"
SPACING_SMALL = "16px"
SPACING_MEDIUM = "24px"
SPACING_LARGE = "32px"
SPACING_XLARGE = "40px"
SPACING_XXLARGE = "48px"
```

Browser/global chrome tokens, also in `src/ui/styles.py`:

```python
# src/ui/styles.py:230-241
TOPBAR_STYLE = {
    "minHeight": "auto",
    "height": "44px",
    "padding": "0",
    "borderBottom": f"1px solid {COLOR_BORDER}",
    "boxShadow": "0 1px 2px var(--color-topbar-shadow)",
    "backgroundColor": COLOR_BACKGROUND_WHITE
}

TOPBAR_CONTAINER_STYLE = {
    "padding": "8px 16px"
}
```

The page header above every page's content:

```python
# src/ui/styles.py:139-150
COMPACT_PAGE_HEADER_STYLE = {
    "display": "flex",
    "alignItems": "center",
    "gap": SPACING_XSMALL,
    "fontFamily": FONT_SANS,
    "fontSize": FONT_SIZE_SMALL,
    "textTransform": "uppercase",
    "letterSpacing": "0.8px",
    "borderBottom": f"1px solid {COLOR_BORDER}",
    "paddingBottom": SPACING_XSMALL,
    "marginBottom": SPACING_XXSMALL
}
```

The content wrapper in `src/ui/layout.py:155`:

```python
content = html.Div(id="page-content", className="p-2")
```

`.p-2` is Bootstrap's `0.5rem` = **8px**; `.px-1 .py-1` is `0.25rem` = **4px**.
The stylesheet does not override either class.

### The CSS

`src/ui/assets/executive-dashboard.css` (2450 lines) defines CSS custom
properties at the top. It has **no global base font-size rule** — unstyled text
inherits Bootstrap Materia's `--bs-body-font-size: 1rem` (16px) while every
explicitly-styled element is set to 9–15px. That inconsistency is what step 1
fixes.

```css
/* src/ui/assets/executive-dashboard.css:61-63 */
    /* Font Sizes */
    --font-size-small: 13px;
    --font-size-xsmall: 12px;
```

Only 3 rules in the whole file reference `var(--font-size-...)` — the inline
result badge (line 660), the sidebar nav links (1074), and the executive switch
label (1409). The remaining 47 `font-size` declarations hardcode px. Those 3
follow the variable automatically when you change it; the 47 do not, which is why
step 1 sweeps them separately.

**The stylesheet is not the whole story.** The dense pages also set font sizes
**inline in Python**, where no stylesheet rule can reach — the same
inline-beats-class fact that makes a `.dense-page .graph-filter-card { padding }`
rule dead code. There are **37** such declarations below 13px across the six
dense pages, and they are distributed per page:

| Page | Inline `fontSize` literals below 13px |
|---|---|
| Graph (`layout.py` 12, `components/sliders.py` 2, `components/modals.py` 2, `callbacks/catalog.py` 10, `utils/ui_components.py` 1) | **27** |
| Collaboration Network (`layout.py`) | 5 |
| Collaboration Network per-person (`layout.py`) | 4 |
| Search (`search.py`) | 1 |
| Timeline (`layout.py`), Catalog (`layout.py`) | 0 |

That distribution is why each page's step handles its own: no stylesheet rule can
reach them, so they belong with the page that owns them.

Only one test reads font sizes out of this stylesheet —
`tests/test_person_autocomplete.py`, which pins the person-chip and
header-picker declarations (step 1). No test asserts the three variable-backed
rules, and none asserts the sidebar, the badge, or the switch. No test asserts
any inline `fontSize` literal except `person_picker.py`'s `12px`.

### The dense-grade CSS classes already exist

The dense pages own their own classes, which is what makes the per-page steps
viable:

- `.timeline-card` — `src/ui/assets/executive-dashboard.css:2051`. Deliberately
  dense already, and its own comment states the technique step 1 generalises:

  ```css
  /* src/ui/assets/executive-dashboard.css:2051-2065 */
  .timeline-card {
      ...
      /* Tight vertical padding: the reclaimed height pays for the larger text,
         keeping the per-row height (and so the number of visible cards) unchanged. */
      padding: 3px 7px;
      margin-bottom: 4px;
      box-sizing: border-box;
      min-height: 40px;
      overflow: hidden;
  }
  ```
  Note the `overflow: hidden` is **horizontal only in effect** — the card has no
  `max-height`, the grid row is `alignItems: start` (so cells size to their
  content), and both text lines are `nowrap`. The card therefore grows to fit
  its two lines and can never clip vertical text. `overflow: hidden` is what
  makes the ellipsis work.
- `.graph-filter-card`, `.graph-filter-card-body` — line 814.
- `.graph-right-panel-tab-bar`, `.graph-right-panel-tab-icon` — lines 679, 696.
- `.executive-table` (Catalog table **and** Settings → User Management) — line 1018.
- `.catalog-person-chip-*` — line 1748 onward.

### The page roots

Each dense page's `get_layout()` returns an `html.Div` — this is where the scope
class attaches. Note that four of the six already pass `id=` and `style=`:

| Page | File | `get_layout` returns at | Root call shape |
|---|---|---|---|
| Graph | `src/ui/pages/graph/layout.py` | line 616 | `html.Div([` … `])` — no kwargs |
| Timeline | `src/ui/pages/timeline/layout.py` | line 321 | `html.Div(` … `)` — no kwargs |
| Search | `src/ui/pages/search.py` | line 762 | `html.Div(` … `)` — no kwargs |
| Catalog | `src/ui/pages/catalog/layout.py` | line 94 | `html.Div(` … `)` — no kwargs |
| Collab Network | `src/ui/pages/collaboration_network/layout.py` | line 167 | already `id="collab-page"`, `style=...` |
| Collab Network (per-person) | `src/ui/pages/collaboration_network_ego/layout.py` | line 191 | already `id="ego-page"`, `style=...` |

For the four without keyword arguments, add `className="dense-page"` after the
children list. For the two Collab pages, add it alongside the existing keywords.

Example of the exact shape to change (Timeline's, and the same shape as Search's
and Catalog's):

```python
# src/ui/pages/timeline/layout.py:319-322
def get_layout() -> html.Div:
    """Return the Activity Timeline page scaffold with selector and lane row."""
    return html.Div(
        [
```

### The viewport-height constants encode today's chrome height

Three constants size a canvas or scroll region as `100vh minus the chrome above
it`. **If you shrink the chrome without updating these, the content height does
not change and roughly a third of the gain is silently lost.** They are corrected
in step 1, together with the chrome change that causes it — see that step for
why.

| Constant | File | Value |
|---|---|---|
| `GRID_SCROLL_STYLE["maxHeight"]` | `src/ui/pages/timeline/layout.py:206` | `calc(100vh - 220px)` |
| `_CANVAS_HEIGHT` | `src/ui/pages/collaboration_network_ego/layout.py:45` | `calc(100vh - 148px)` |
| Collab canvas `height` | `src/ui/pages/collaboration_network/layout.py:194` | `calc(100vh - 200px)` |
| Chat messages `height` | `src/ui/pages/chat.py:57` | `calc(100vh - 220px)` — **do not touch**, Chat is not a dense page |

### Existing tests that pin values this plan changes

- `tests/test_shared_graph_components.py:581-582` asserts the graph time-slider
  section has `borderRadius == "4px"` and `padding == "8px"` (floats, not tokens).
  The action's padding is `"8px"` — **8px is still `SPACING_XXSMALL`'s value, so
  the assertion survives if you migrate it to the token.**
- `tests/test_person_autocomplete.py` — five assertions read the CSS as text and
  pin the chip and header-picker declarations. They will **fail** once step 1
  changes those declarations, so step 1 updates them value for value.

### Repo conventions that apply

- **Design docs must not cite `file:line`** and must not reference plan numbers,
  letters, or stages. Name the module, never the line.
- **Design docs must not carry meta-explanations** — state the fact, never why a
  passage exists or why wording was chosen.
- `styles.py` re-exports theme tokens with an explicit `__all__`; if you add a
  module-level constant that another module imports, it needs to be declared.
- Comments explain **why**, never **what**. The existing `.timeline-card` comment
  is the house style for this kind of change.

## Commands you will need

Run from the repo root. Activate the virtualenv first: `source .venv/bin/activate`.

| Purpose | Command | Expected on success |
|---|---|---|
| Unit tests | `pytest -m unit tests -q` | all pass |
| Targeted tests | `pytest -m unit tests/test_person_autocomplete.py tests/test_shared_graph_components.py tests/test_page_header_component.py tests/test_result_pane.py -q` | all pass |
| Typecheck | `mypy src/` | exit 0, no errors |
| Lint | `pylint src --score=y` | score ≥ 10.0 |
| Style (advisory) | `flake8` | **see the note below — not a gate** |
| Bring the stack up | `docker compose up -d` | all services healthy |
| Rebuild the UI | `docker compose build ui && docker compose up -d --force-recreate ui` | container recreated |
| Confirm the container has the new code | `docker compose exec ui grep -c "<a value you changed>" /app/ui/<path>` | ≥ 1 |

**`docker compose build` alone is not enough** — it leaves the old container
serving the old code. Always follow with `--force-recreate`, and confirm the new
value is live **by reading it out of the container**, not out of the host file.

**`flake8` is not a CI gate and must not be treated as one.** The PR workflow
(`.github/workflows/pr_checks.yml`) runs pytest, a spec-freshness check, pylint,
mypy and bandit — there is no flake8 step. The repo currently has ~1981 flake8
findings (`W293` alone accounts for ~1155), so an `exit 0` expectation is
meaningless and an attempt to satisfy it would mean reformatting unrelated code
into a UI-density diff. The in-scope files alone carry pre-existing findings:
`W293` and `E501` in `src/ui/layout.py`, `graph/layout.py`,
`graph/utils/ui_components.py` and others, `F841` at
`graph/callbacks/catalog.py:572`, `W292` in `catalog/layout.py`.

Use flake8 only as a local smell check on the lines you actually touched: your
diff should add no **new** finding. Do not reflow, reindent or reformat any
pre-existing code to satisfy it. If you run `flake8` on the whole tree it will
report hundreds of pre-existing findings, and that is the expected baseline, not
a failure of this plan.

## Suggested executor toolkit

- The `chrome-devtools` MCP tools, if available, are the cheapest way to measure
  rendered geometry (`take_snapshot`, `evaluate_script`). If Chrome is not
  installed for that MCP, drive the Playwright Chromium binary at
  `~/.cache/ms-playwright/chromium-1248/chrome-linux64/chrome` over CDP instead
  (the `websockets` Python package is available in the venv).
- Measure through `https://localhost/app/...`. The Compose stack terminates TLS
  at the `nginx` service; neither the `api` nor the `ui` service publishes a host
  port.
- Read `docs/design/design-system.md` § Typography and § Spacing System before
  step 7 — they are the tables you are updating.

## Scope

**In scope** (the only files you should modify):

- `src/ui/styles.py` — font-size tokens, topbar tokens, page-header token
- `src/ui/layout.py` — the font request, the content wrapper's padding class
- `src/ui/assets/executive-dashboard.css` — the CSS var block, the shell base
  font-size, the literal font sizes, the `.dense-page` block
- `src/ui/pages/graph/**` — root class, gutters, filter-card padding, inline font
  sizes, canvas height override
- `src/ui/pages/timeline/layout.py` — root class, `GRID_SCROLL_STYLE` maxHeight
- `src/ui/pages/search.py` — root class, result-card padding/margin, inline font size
- `src/ui/pages/catalog/layout.py` — root class
- `src/ui/pages/collaboration_network/layout.py` — root class, canvas height,
  gutters, filter-card padding, inline font sizes
- `src/ui/pages/collaboration_network_ego/layout.py` — root class, gutters,
  `_CANVAS_HEIGHT`, filter-card padding, inline font sizes
- `src/ui/components/result_pane.py` — the two height overrides (step 2)
- `tests/test_person_autocomplete.py` — the pinned sizes (step 1)
- `docs/design/design-system.md`, `docs/design/frontend-design-skill.md` (step 7)

**Out of scope** (do NOT touch, even though they look related):

- **`SPACING_XXXSMALL` … `SPACING_XXLARGE` values in `src/ui/styles.py`.**
  Leaving them unchanged is what protects the card pages from getting tighter.
  Do not "improve" them.
- `src/ui/pages/analytics.py`, `src/ui/pages/connectors/**`,
  `src/ui/pages/settings/**` (including `user_management/`),
  `src/ui/pages/developer/**`, `src/ui/pages/chat.py` — the card and form pages.
  They receive step 1's global text change, which step 1's gate reviews. They
  must **not** receive density: do not add `dense-page` to any of their roots,
  and do not sweep their inline font sizes.
- `src/ui/pages/catalog/editor_layout.py` — the Catalog **editor** is a form. Step
  2 gives `result_pane.py` an optional override so the editor keeps today's 75vh
  result view. Do not add `dense-page` to its root, and do not sweep its inline
  font sizes.
- `src/ui/components/person_picker.py` — its inline `12px` (lines 128, 174) is
  pinned by a test as a literal. Leave it; migrating it is a separate cleanup.
- `src/ui/graph_styles.py` — node/edge sizing, unrelated.
- `src/ui/pages/chat.py`'s `calc(100vh - 220px)`.
- `collaboration_network_ego/layout.py`'s `_EMPTY_STATE_STYLE` docstring, which
  mentions a historical `calc(100vh - 145px)` — prose about a bug that was fixed,
  not a live constant. Do not "correct" it to the new `_CANVAS_HEIGHT`.
- `src/ui/pages/graph/components/sliders.py`'s `"8px"` section padding — a no-op
  to migrate (`SPACING_XXSMALL` is still `8px`). Skip it to keep the diff minimal.
  Its inline **font sizes are** in scope for step 2.

## Git workflow

- You are on branch `feature/spacing-app-wide-review`. Create a new branch first:
  `git checkout -b compact-dense-pages`.
- **One commit per step**, after that step's gate is confirmed by the operator.
  Commit messages are **plain imperative sentences** — see `git log --oneline`
  for the style, e.g. `Activity timeline backend (#323)`.
- **Do NOT push and do NOT open a PR.** Leave the work on the branch and report.

## Steps

Steps 1-6 each end at a manual gate. Follow the gate protocol in the header: do
the step, report measurements, **stop**, iterate on feedback, and only move on
when the operator confirms.

---

### Step 1 — The shared text scale, the shared chrome, and the density CSS (MANUAL GATE)

Everything here is used by every page, so it is one step with one gate. It also
writes the `.dense-page` CSS block, which is **inert until a page opts in** in
steps 2-6 — that is deliberate: the CSS is reviewed once here, and each later
step is a one-line opt-in whose effect is immediately visible and attributable.

#### 1a. Raise the font-size tokens

In `src/ui/styles.py`, replace the font-size block with:

```python
FONT_SIZE_XLARGE = "42px"
FONT_SIZE_LARGE = "16px"
FONT_SIZE_MEDIUM = "15px"
FONT_SIZE_SMALL = "14px"
FONT_SIZE_XSMALL = "13px"
FONT_SIZE_TINY = "12px"
FONT_SIZE_XTINY = "11px"
FONT_SIZE_XXSMALL = "11px"
```

`FONT_SIZE_XTINY` and `FONT_SIZE_XXSMALL` now share a value deliberately: they
are the 9–10px family and 11px is the floor. **Do not delete either constant** —
`FONT_SIZE_XTINY` has 32 references across 12 files and `FONT_SIZE_XXSMALL` 8
across 3. Keeping the names means no call site changes.

#### 1b. Fix the font request

In `src/ui/layout.py:35`, weight 700 is rendered by the app but never downloaded,
and weight 300 is downloaded but used nowhere:

```python
# from
"https://fonts.googleapis.com/css2?family=Cormorant+Garamond:wght@300;400;600;700&family=Inter:wght@300;400;500;600&display=swap"
# to
"https://fonts.googleapis.com/css2?family=Cormorant+Garamond:wght@300;400;600;700&family=Inter:wght@400;500;600;700&display=swap"
```

Inter 700 is genuinely rendered: `FONT_WEIGHT_BOLD` has no call sites, but three
places hardcode the literal `700` for the required-field asterisk
(`src/ui/components/person_picker.py:115`,
`src/ui/pages/graph/callbacks/catalog.py:659`,
`src/ui/components/common.py:1255`) and one stylesheet rule sets
`font-weight: 700` (line 1666, `.catalog-person-required-marker`). Without the
font file the browser synthesises a smeared bold. Leave Cormorant's weights alone
— only the Inter half of the URL changes. The payload is unchanged: one weight is
swapped for another.

#### 1c. Update the CSS variables and pin a shell base font-size

In `src/ui/assets/executive-dashboard.css`, update the custom properties:

```css
    /* Font Sizes */
    --font-size-small: 14px;
    --font-size-xsmall: 13px;
```

and give `.app-shell` an explicit base so unstyled text stops inheriting 16px:

```css
.app-shell {
    background-color: var(--color-background-light);
    height: 100vh;
    display: flex;
    flex-direction: column;
    overflow: hidden;
    /* Unstyled text would otherwise inherit Bootstrap's 16px body font while
       every explicitly-styled element sits near 13-14px. Pin the base between
       the two so inherited and explicit text agree. */
    font-size: 15px;
}
```

#### 1d. Raise the stylesheet's literal font sizes

**This part exists because 1a alone does not raise the app's text.** The
stylesheet has 57 `font-size` declarations: 3 use a variable, 7 are `em`-relative
(they scale from their parent, so they follow automatically), and 47 are literal
px. Fifteen of those literals are `10px` — below the 11px floor 1a establishes
for the tokens. Splitting the app across two different scales is worse than
either, so raise the literals here.

**The set is defined by this command, not by a hand-copied list of line
numbers** — line numbers shift as you edit, and a list transcribed at planning
time does not survive that. Run it to get the exact declarations in scope:

```bash
grep -nE "font-size: *(9|10|11|12)px" src/ui/assets/executive-dashboard.css
```

Raise each match **by one step**, preserving their relative order rather than
flattening them all to one value:

| Current | New | Rationale |
|---|---|---|
| `12px` | `13px` | joins the token scale (`FONT_SIZE_XSMALL`) |
| `11px` | `12px` | joins the token scale (`FONT_SIZE_TINY`) |
| `10px` | `11px` | the floor 1a sets for the tokens |
| `9px` | `11px` | floor; there are none currently, but the grep covers it |

Flat-to-13px would erase every deliberate size distinction the stylesheet
encodes (a metadata line versus its label). One step preserves the hierarchy
while lifting the whole scale, which is the same rule 1a applies to the tokens.

**Four named exceptions**, because they look in-scope and are not:

- **The timeline card is raised deliberately, in this step.** Its two text
  declarations are already ≥13px, so the one-step rule would leave them alone —
  but step 3's measurements depend on the card rendering at 15px/13px:

  | Declaration | From | To |
  |---|---|---|
  | `.timeline-card-primary` | `14px` | `15px` |
  | `.timeline-card-secondary` | `12px` | `13px` |

  Both lines are `white-space: nowrap` with `text-overflow: ellipsis`, so the
  larger text truncates each title earlier. Step 3's gate measures that loss
  rather than assuming it away.
- **The five person-chip / header-picker declarations** are raised +1px each, and
  five test assertions pin them verbatim. Apply the values and update the tests
  in the same edit:

  | Declaration | From | To | Test assertion to update |
  |---|---|---|---|
  | `.catalog-person-chip-name` | `12px` | `13px` | `test_person_autocomplete.py:836` → `"13px"` |
  | `.catalog-person-chip-id` | `10px` | `11px` | `test_person_autocomplete.py:837` → `"11px"` |
  | `.ego-header-picker .form-control` | `14px !important` | `15px !important` | `test_person_autocomplete.py:816` → `font-size: 15px !important` |
  | `.ego-header-picker .catalog-person-chip-name` | `13px` | `14px` | `test_person_autocomplete.py:844` → `"14px"` |
  | `.ego-header-picker .catalog-person-chip-id` | `11px` | `12px` | `test_person_autocomplete.py:845` → `"12px"` |

  Do **not** change these assertions' intent — they exist to prove the base chip
  rules stay smaller than the header host's overrides. Keep that relationship
  (header chip one step larger than the base chip). One stylesheet comment states
  the relationship these values encode — "Tighter than the shared 6px/10px" —
  and goes stale (`6px/10px` → `6px/11px`); correct it. The neighbouring "Both
  raised from the shared 12px/10px" stays true and needs no edit.
- **`.timeline-load-more` and `.timeline-segment .form-check-label`** (both
  `11px`) are **click targets**, not text lines. Leave them at 11px — the same
  reasoning the Scope section applies to the Search page's filter inputs.
- **The 7 `em`-relative declarations** (lines 1324-1326, 1339, 1356, 1370, 1915).
  They inherit from their parent, so they rise with it automatically; rewriting
  them to px would break that. `.setup-banner-dismiss` (line 1915) is a dismiss
  glyph, not text.

**Anything already at 13px or above is exempt**, except the two timeline-card
declarations named above. In particular the five `13px !important` form-control
rules (lines 172, 196, 223, 591, 1197) and the header-picker `14px !important`
(handled above) are pinned against inline styles — changing them changes control
heights.

**Do not** blanket-rewrite with `sed`: several `10px` values sit on decorative
elements (chevrons, small badges) where a size increase is noise, and a few rules
size a container to its text. Read each hunk. If a rule's purpose is unclear,
leave it and note it in your report rather than guessing.

Two notes on other pinned values:

- `tests/test_shared_graph_components.py:581-582` stays valid whether or not you
  migrate `sliders.py`'s section padding to `SPACING_XXSMALL` (still `"8px"`).
- `tests/test_person_autocomplete.py:851-856` asserts
  `text_input.style["fontSize"] == "12px"` — an inline literal in
  `src/ui/components/person_picker.py:174`. `person_picker.py` is out of scope,
  so this test passes unchanged. Do not touch it.

#### 1e. Shrink the shared chrome

**Do the arithmetic before choosing the topbar height.** The tallest control in
the top bar is 32px, and it is the one that sets the container's content height.
Three controls are pinned at exactly 32px — the global search input
(`.global-search-input`, `height: 32px !important`), the theme toggle
(`.theme-toggle-btn`, `width/height: 32px`), and the account-menu trigger
(`.account-menu-toggle`, `width/height: 32px`). The sidebar toggle is **not**
pinned: `TOGGLE_BUTTON_STYLE` sets a 16px font at `line-height: 1` with 4px
padding and no height, and the stylesheet carries only `:hover`/`:focus` rules
for `.sidebar-toggle-btn`, so Bootstrap's `.btn-sm` sizes it to about 26px.

The equation therefore describes a **maximum**, not a uniform row:

```
content height = 32px (tallest control) + 2 × container vertical padding
```

Today: 32 + 2×8 = **48px** of content inside a 44px `box-sizing: border-box`
topbar — it already overflows slightly, which the `minHeight: auto` absorbs. That
means **38px is too short**: 32 + 2×4 = 40px, so the topbar would be 2px smaller
than its own tallest content and Bootstrap's `.navbar` would stretch it back,
silently negating the gain.

Set the height to **40px** and the container padding to `4px 12px`, so the
content (40px) exactly fills the box and the 8px of reclaimed height is real:

```python
TOPBAR_STYLE = {
    "minHeight": "auto",
    "height": "40px",
    ...
}

TOPBAR_CONTAINER_STYLE = {
    "padding": "4px 12px"
}
```

If you want more than 8px back here, the 32px controls must shrink first — that
is a separate change, not a number to guess at.

In `COMPACT_PAGE_HEADER_STYLE`, tighten the two bottom values:

```python
    "paddingBottom": SPACING_XXSMALL,
    "marginBottom": SPACING_XXXSMALL
```

(That is `12px → 8px` and `8px → 4px`, expressed through unchanged tokens.)

In `src/ui/layout.py:155`:

```python
content = html.Div(id="page-content", className="px-1 py-1")
```

#### 1f. Correct the three viewport-height constants

**These live in per-page files but belong in this step.** They are the arithmetic
of 1e: the chrome above the dense content dropped by exactly **16px** (4 from the
topbar, 8 from the page header, 4 from the content wrapper), and each constant
subtracts that chrome from `100vh`. If they were deferred to their page's step,
this step's gate would show three canvases overflowing their viewport with a
scrollbar — a known-broken intermediate state that would waste a review cycle.

```
new constant = old constant − 16px (restores today's content height)
             − extra (grows the content)
```

The table subtracts **20px**: it absorbs the 16px and grows the data area by 4px.
That is a deliberately small gain — the canvas already fills the viewport, and
subtracting more than the chrome actually shrank would push it below the fold and
introduce a page scrollbar.

| File | From | To |
|---|---|---|
| `src/ui/pages/timeline/layout.py:206` | `calc(100vh - 220px)` | `calc(100vh - 200px)` |
| `src/ui/pages/collaboration_network_ego/layout.py:45` | `calc(100vh - 148px)` | `calc(100vh - 128px)` |
| `src/ui/pages/collaboration_network/layout.py:194` | `calc(100vh - 200px)` | `calc(100vh - 180px)` |

**Leave the adjacent comments alone.** None of the three sites states a value, so
none needs updating to match:

- `timeline/layout.py`'s `GRID_SCROLL_STYLE` comment explains what the constant
  is *for* ("Fill the viewport below the topbar + header + selector bar"), which
  stays true at any value.
- `collaboration_network_ego/layout.py`'s `_CANVAS_HEIGHT` docstring is the same
  shape: "sized to the chrome the page actually renders above it."
- `collaboration_network/layout.py`'s canvas `height` has no adjacent comment.

And do not touch the ego module's `_EMPTY_STATE_STYLE` docstring, which mentions
`calc(100vh - 145px)` — historical prose about a bug that was fixed.

#### 1g. Write the `.dense-page` CSS block

Append a clearly-delimited section to `src/ui/assets/executive-dashboard.css`.
Scope **every** rule under `.dense-page`. This block is **inert until a page adds
the class** in steps 2-6, which is why it can be written here in one reviewable
piece:

```css
/* ============================================================================= */
/* Compact density — data-dense pages only                                        */
/* ============================================================================= */

/* These pages display lists and graphs, so the space around the content is worth
   more as content. Card/form pages (Analytics, Connectors, Settings, Developer,
   Chat) deliberately keep the roomier base values: density is a property of the
   page, not of the app. */

/* The card is two single lines, each nowrap + ellipsis, so its height is
   content-driven and min-height never binds. Tightening line-height is the
   whole density gain here: ~49px today at the inherited 1.5, ~44px at 1.3.
   Do NOT add a min-height — it would be inert and unverifiable. */
.dense-page .timeline-card {
    line-height: 1.3;
    padding: 2px 6px;
}

.dense-page .graph-right-panel-tab-icon {
    padding: 3px 8px;
}

.dense-page .graph-right-panel-tab-bar {
    padding: 3px 0 4px 0;
    margin-bottom: 6px;
}

.dense-page .executive-table thead th,
.dense-page .executive-table tbody td {
    padding-top: 2px;
    padding-bottom: 2px;
}
```

Both `.executive-table` tables use `size="sm"`, so Bootstrap's Materia bundle
(`.table-sm>:not(caption)>*>*`) already applies `4px` on all four sides. The
rule above therefore has to go *below* 4px to have any effect; at 4px it was a
restatement of Bootstrap's value and changed nothing measurable. Vertical only —
a `padding` shorthand would also set the horizontal values and move column
gutters.

**Deliberately absent: the `.graph-filter-card` family of padding rules.**
`.graph-filter-card`, its `.card-body`, and `.graph-filter-card-body` all carry an
**inline** `padding` in Python, and an inline style outranks any class selector:

| Element | Site | Inline value |
|---|---|---|
| `.graph-filter-card-body` | `graph/layout.py` | `"0 0 24px 0"` |
| `.graph-filter-card-body` | `collaboration_network/layout.py` | `"0 0 24px 0"` |
| `.graph-filter-card-body` | `collaboration_network_ego/layout.py` | `"0 0 24px 0"` |
| `.graph-filter-card` | all three files | `{"border": "none", "backgroundColor": "transparent"}` |

A `.dense-page .graph-filter-card-body { padding: … }` rule would therefore be
dead code that silently does nothing. Those values are changed in Python instead —
steps 2 and 6. Do not add these CSS rules.

**Step 1 verification**:

```bash
grep -n "FONT_SIZE_" src/ui/styles.py                      # the seven new values
grep -c "font-size: 15px" src/ui/assets/executive-dashboard.css   # 1
grep -c "Inter:wght@400;500;600;700" src/ui/layout.py      # 1
grep -nE "font-size: *(9|10)px" src/ui/assets/executive-dashboard.css   # no matches
grep -cE "font-size: *var\(" src/ui/assets/executive-dashboard.css      # 3
grep -n "\"height\": \"40px\"" src/ui/styles.py            # 1
grep -rn "calc(100vh" src/ui/pages/ --include="*.py"       # the three new values + chat 220px + the ego docstring's 145px
grep -c "dense-page" src/ui/assets/executive-dashboard.css # 5
pytest -m unit tests/test_person_autocomplete.py tests/test_shared_graph_components.py tests/test_page_header_component.py -q
```

**Do not** use the `src/ui/pages/*.py` glob for the `calc(100vh` check: it expands
only to the three top-level modules (`analytics.py`, `chat.py`, `search.py`) and
prints just `chat.py`, so it cannot confirm the timeline, ego or collab values.

#### GATE 1 — browser review of the shared change

Rebuild and confirm the container is live:

```bash
docker compose build ui && docker compose up -d --force-recreate ui
docker compose exec ui grep -c "font-size: 15px" /app/ui/assets/executive-dashboard.css
```

The container path is `/app/ui/...`, not `/app/src/ui/...` — `Dockerfile.ui`
copies `src/ui/` to `./ui/`. Reading the host file instead of the container's is
exactly the mistake that makes an un-rebuilt container look like a pass.

Then capture **before/after** numbers for the app-wide change, and report a table
with real measured values.

**Dense pages (all six — no page is dense yet, so this is the baseline for steps
2-6)**: record each page's chrome height (topbar height + content-area top
offset), the visible row count, and the canvas width and height. These are the
numbers steps 2-6 will be compared against.

**Card and form pages (Analytics, Connectors, Settings, Developer, Chat)** — this
is the review that decides whether the global text raise is acceptable. Measure
and report:

- **A card's interior padding, before vs after.** It must be **identical**: step 1
  changes no padding token. A difference means a token leaked.
- **Text regressions.** Larger text in a fixed-height box is the failure mode
  here, and it is not caught by a padding check. Look specifically at:
  - **Chat's composer** — a fixed `68px` textarea with `lineHeight: 1.6`. At the
    old 15px, two lines plus 32px padding already exceeded the box (80px); at the
    new 16px it is 83.2px. Confirm it scrolls internally rather than clipping.
  - **Analytics' cards** — `minHeight: "220px"` on the card container, with 18
    `FONT_SIZE_*` sites in that module.
  - **The setup banner** — it renders in the global shell above *every* page, so
    it is neither a card nor a dense page. Confirm it does not wrap or overflow
    at 13px.
  - **Settings → User Management's table** — it shares `.executive-table`, whose
    base `thead th` (11px→12px) and `tbody td` (12px→13px) text this step
    changed. Confirm no column overflows.
- **Both themes** (light and dark) on at least Analytics, Chat and Settings.

**Report**: a before/after table, plus an explicit statement of which card pages
show a text regression and what it looks like. If a card page looks worse, say so
and **stop** — do not compensate by shrinking a value the step does not name.

---

### Step 2 — Graph (MANUAL GATE)

Graph carries the most change of any page: 27 inline font literals, five padding
values, two gutters, and a canvas-height override.

#### 2a. Opt in to the density class

In `src/ui/pages/graph/layout.py:616`, the return is `html.Div([` with a `])`
terminator, so the call becomes:

```python
    return html.Div([
        ...
    ], className="dense-page")
```

#### 2b. Compress the gutters and the inline padding

In `src/ui/pages/graph/layout.py`. **Locate each by its surrounding text, not by
the line number** — the numbers are from the planning commit and shift as you
edit:

| Locate by | From | To |
|---|---|---|
| `graph-viz-col` | `"paddingRight": "24px"` | `"12px"` |
| `graph-details-col` | `"paddingLeft": "24px"` | `"12px"` |
| `className="graph-filter-card-body"` | `{"padding": "0 0 24px 0"}` | `{"padding": "0 0 12px 0"}` |
| the console card's `dbc.CardBody` wrapper | `{"padding": "16px"}` | `{"padding": "12px"}` |
| the status strip | `{"padding": "8px 0"}` | `{"padding": "4px 0"}` |

The `graph-filter-card-body` change is the Python-side replacement for the CSS
rule step 1 deliberately omits: the value is inline, so only a Python edit
reaches it.

#### 2c. Raise the page's inline `fontSize` literals

Graph's 27 declarations are spread across five modules. Raise each literal below
13px by the same one step as step 1d, and express it with the token that already
holds that value rather than a new literal:

| Current | Replace with |
|---|---|
| `"fontSize": "12px"` | `FONT_SIZE_XSMALL` (`13px`) |
| `"fontSize": "11px"` | `FONT_SIZE_TINY` (`12px`) |
| `"fontSize": "10px"` | `FONT_SIZE_XTINY` (`11px`) |

The modules, with their counts and the token imports they will need:

| Module | Declarations | Notes |
|---|---|---|
| `src/ui/pages/graph/layout.py` | 12 | the four filter section labels, both checklists, the radio group, the slider hint, two secondary-text lines |
| `src/ui/pages/graph/callbacks/catalog.py` | 10 | imports no `FONT_SIZE_*` today — add the imports |
| `src/ui/pages/graph/components/sliders.py` | 2 | |
| `src/ui/pages/graph/components/modals.py` | 2 | |
| `src/ui/pages/graph/utils/ui_components.py` | 1 | already imports 15 `FONT_SIZE_*` tokens |

`src/ui/pages/graph/utils/ui_components.py` and most of `layout.py` already import
the tokens; add an import where a module needs one. A module that imports none of
the three should keep its literal rather than gain an import for a single value —
note it in your report.

Use this to enumerate, then read each hit and confirm its module is one of the
five:

```bash
grep -rnE '["'\'']fontSize["'\'']\s*:\s*["'\''](9|10|11|12)px["'\'']' src/ui/pages/graph/
```

#### 2d. Give the result pane a height override, without changing the editor

`src/ui/components/result_pane.py` is shared by the Graph page (dense) and the
Catalog editor's View Test modal (a form surface — must keep today's 75vh).
`GRAPH_CYTOSCAPE_STYLE` (height `75vh`) and the empty state's
`minHeight: calc(75vh)` both live here. **Do not change `GRAPH_CYTOSCAPE_STYLE`
in `styles.py`**, because the editor uses it too.

Add an optional parameter defaulting to today's behaviour to **both** builders:

```python
def create_graph_result_container(
    id_prefix: str = "graph", style_override: dict[str, Any] | None = None
) -> html.Div:
    """Create main graph visualization container with Cytoscape."""
    graph_style = {**GRAPH_CYTOSCAPE_STYLE, **(style_override or {})}
    ...
                style=graph_style,
```

```python
def create_results_empty_state(
    id_prefix: str = "graph", style_override: dict[str, Any] | None = None
) -> html.Div:
    """Create empty state display (shown before any query execution)."""
    empty_style = {"minHeight": "calc(75vh)", "padding": "16px"}
    empty_style.update(style_override or {})
    ...
                style=empty_style,
```

**The empty state needs it as much as the canvas.** `create_results_empty_state`
is the Graph page's **default** view — what renders before any query runs — and it
is sized independently at `calc(75vh)`. Both it and the Cytoscape canvas are
children of the same `dcc.Loading` in `graph/layout.py`, so overriding only the
canvas gives that column two different heights depending on whether a query has
run.

The module currently imports only `html`, `cyto`, and the style constants — **add
`from typing import Any`** or `mypy` strict will fail on the new annotations.

Then in `src/ui/pages/graph/layout.py:474`, pass a viewport-relative height to
both builders. The canvas is currently `75vh`, which is **not** coupled to the
chrome above it, so it does not benefit from step 1's reclaimed space:

```python
create_graph_result_container(
    id_prefix="graph",
    style_override={"height": "calc(100vh - 140px)"},
),
...
create_results_empty_state(
    id_prefix="graph",
    style_override={"minHeight": "calc(100vh - 140px)"},
),
```

Note the two keys: the canvas takes `height`, the empty state takes `minHeight`.
They are different properties on different components, so each override names its
own.

**Derive the number, don't trust it.** Chrome above the canvas is: topbar (40px)
+ page header (its text plus the new 8px/4px bottom spacing) + content-wrapper top
padding (4px) + the controls bar and status strip. Measure that offset at this
step's gate and adjust the constant so the canvas bottom lands just inside the
viewport with no page scrollbar. If the measured value differs from 140px by more
than ~10px, use the measured one and note it in your report.

Leave `catalog/editor_layout.py:537` calling `create_graph_result_container` with
no override, so the editor is byte-for-byte unchanged.

**Step 2 verification**:

```bash
grep -rc "dense-page" src/ui/pages/graph/layout.py           # 1
grep -rnE '["'\'']fontSize["'\'']\s*:\s*["'\''](9|10)px["'\'']' src/ui/pages/graph/   # no matches
grep -n "style_override" src/ui/components/result_pane.py src/ui/pages/graph/layout.py  # both; layout.py 2x
grep -n "style_override" src/ui/pages/catalog/editor_layout.py   # no matches
pytest -m unit tests -q
mypy src/
```

#### GATE 2 — browser review of Graph

Rebuild the UI, then measure Graph at `https://localhost/app/graph` and report:

- **Before running any query**: the **empty state** (`graph-results-container`)
  height **and** the canvas height. They share one column and both are overridden
  — a canvas-only measurement would report a pass while the default view is still
  75vh. Record both at the same moment.
- **After running a query**: canvas width and height, and the visible node count.
- **Gutter widths** for the two columns.
- **The filter panel's height**, and whether its four section labels, both
  checklists, the radio group and the slider hint all read at their new sizes
  without any of them wrapping onto a second line.
- **Row/column count** on the right-panel Catalog table, versus step 1's baseline.
- **No page scrollbar**, and no horizontal scrollbar.
- **Both themes.**

**Requirements**: chrome height is less than step 1's baseline; canvas width and
height are greater; the empty state's height matches the canvas height; the
filter panel shows no wrapping; the Catalog table shows at least as many rows as
the baseline.

**Report** the before/after table and state which requirements passed. **Then
stop** — do not start step 3.

---

### Step 3 — Timeline (MANUAL GATE)

Timeline's density is entirely in step 1's `.dense-page` block; this step is the
opt-in plus a measurement of the trade-off that block creates.

#### 3a. Opt in

In `src/ui/pages/timeline/layout.py:321`, add the class to the existing call:

```python
def get_layout() -> html.Div:
    """Return the Activity Timeline page scaffold with selector and lane row."""
    return html.Div(
        [
            ...
        ],
        className="dense-page",
    )
```

Timeline has **no** inline `fontSize` literals below 13px, so there is nothing
else to raise.

**Step 3 verification**:

```bash
grep -c "dense-page" src/ui/pages/timeline/layout.py   # 1
pytest -m unit tests -q
```

#### GATE 3 — browser review of Timeline

Rebuild, then measure `https://localhost/app/timeline` and report:

- **The card height**, before (step 1 baseline) and after. Expected ~44px — the
  `.dense-page .timeline-card` rule sets `line-height: 1.3` and `padding: 2px 6px`
  on a card that is two single `nowrap` lines.
- **The visible card count per lane**, before and after.
- **Truncation loss, per lane.** This is the trade-off the density rule creates:
  because both card lines are `nowrap` with `text-overflow: ellipsis`, the raised
  text (step 1's 15px/13px) fits roughly 7% fewer characters before the ellipsis.
  For each lane, report how much of each title now ends in an ellipsis versus the
  step 1 baseline. A row-count win that costs a third of each title is not a win.
- **No clipped text.** The card is two single lines and must never clip
  vertically. If a line is clipped, a rule caused wrapping — report which one
  rather than experimenting with heights.
- **Both themes.**

**Report** the per-lane truncation table and the row counts. If the added
truncation loses meaningful text, report it — **do not** shrink the card fonts
back to compensate; that is an operator decision.

**Then stop** — do not start step 4.

---

### Step 4 — Search (MANUAL GATE)

#### 4a. Opt in

In `src/ui/pages/search.py:762`, add `className="dense-page"` to the
`get_layout()` root's existing call.

#### 4b. Compress the result card

`src/ui/pages/search.py`, the result card at lines 578-588. Compress `padding`
from its current token to the next one down, expressed with the token rather than
a literal:

```python
    return html.Div(
        card_children,
        style={
            "backgroundColor": COLOR_BACKGROUND_LIGHT,
            "border": f"1px solid {COLOR_BORDER}",
            "borderLeft": f"3px solid {badge_bg}",
            "borderRadius": "2px",
            "padding": SPACING_XSMALL,
            "marginBottom": SPACING_XSMALL,
        },
    )
```

`SPACING_XSMALL` is `12px`; the card's padding was `SPACING_SMALL` (`16px`) and
its margin was already `SPACING_XSMALL`, so only the padding value changes.

**Values come from the token scale, not from literals.** The original draft of
this step used a page-local literal because the token *values* are shared with
the card pages — but changing a value is not the same act as reusing an existing
one. Reusing `SPACING_XSMALL` here touches nothing the card pages read, so it
costs them nothing, while a literal would put hardcoded pixels into a codebase
whose design system states spacing must always come from the `SPACING_*` tokens.
The measure of compliance is whether the token's *value* is edited, not whether
the token is referenced.

This is the smaller of the two available gains, and it was chosen deliberately:
it reclaims 80px of results-list height against the 156px a 10px/8px literal pair
would, and in exchange the step keeps the documented token convention intact. A
future pass that wants the larger gain should do it by adding a value to the
token scale, not by hardcoding.

**Do not** compress the page's filter inputs. They take their padding and
line-height from the shared `INPUT_STYLE` constant (`src/ui/styles.py`), which
this page applies at seven sites — the two `dbc.Select` dropdowns, the search box,
and others. Those are click targets in a form, not result rows; shrinking them
reduces usability without showing more results.

**`INPUT_STYLE` is shared with Settings → Runtime**, a card page, so changing it
would densify a page this plan must leave alone. That is the reason to touch
neither the constant nor the sites that consume it. If a later pass wants denser
Search filters, it needs a page-local style, not a change to the shared constant.

#### 4c. Raise the page's one inline literal

`src/ui/pages/search.py:838` holds `"fontSize": "12px"` — raise it to
`FONT_SIZE_XSMALL` (`13px`). The module already imports 24 `FONT_SIZE_*` tokens,
so no new import is needed.

**Step 4 verification**:

```bash
grep -c "dense-page" src/ui/pages/search.py   # 1
grep -rnE '["'\'']fontSize["'\'']\s*:\s*["'\''](9|10)px["'\'']' src/ui/pages/search.py   # no matches
grep -n '"padding": SPACING_XSMALL,\|"marginBottom": SPACING_XSMALL,' src/ui/pages/search.py   # 2
grep -n '"padding": "10px"\|"marginBottom": "8px"' src/ui/pages/search.py   # no matches
pytest -m unit tests -q
```

#### GATE 4 — browser review of Search

Rebuild, then measure `https://localhost/app/search` with a query that returns
several results, and report:

- **Visible result count** versus step 1's baseline, and the result card's height.
- **The filter inputs are unchanged** — same padding and line height as the
  baseline. They are deliberately not compressed.
- **No text is clipped** inside a result card, and no card's badge wraps onto a
  second line.
- **Both themes.**

**Then stop** — do not start step 5.

---

### Step 5 — Catalog (MANUAL GATE)

#### 5a. Opt in

In `src/ui/pages/catalog/layout.py`, the `get_layout()` root is a bare
`return html.Div(` with a list and a `)` terminator — it carries no keyword
arguments today, so add one:

```python
    return html.Div(
        [
            ...
        ],
        className="dense-page",
    )
```

That is the same shape as Timeline's. (The two Collab pages differ: their roots
already have `id=` and `style=`, so there the class is added alongside them.)

Catalog's density is entirely in step 1's `.dense-page` block (the two
`.executive-table` rules). It has **no** inline `fontSize` literals below 13px.

**Important — the table class is shared.** `.executive-table` is used by both
this page and Settings → User Management. Only the **dense override** is scoped
under `.dense-page`; the base rules were already raised app-wide in step 1d. So
Settings' table keeps its roomier padding and gets only step 1's text change,
while Catalog's table gets both. Confirm this at the gate rather than assuming it.

**Step 5 verification**:

```bash
grep -c "dense-page" src/ui/pages/catalog/layout.py   # 1
pytest -m unit tests -q
```

#### GATE 5 — browser review of Catalog, and of Settings' table

Rebuild, then measure and report:

- `https://localhost/app/catalog` — the table's visible row count versus step 1's
  baseline, and the row height. The table is rendered by a clientside callback, so
  allow it to finish before measuring.
- **`https://localhost/app/settings/user-management`** — this page shares
  `.executive-table` and must **not** have become denser. Measure its row height
  and compare against the step 1 baseline; the values must be equal. This is the
  check that proves the `.dense-page` scoping actually held.
- **Both themes** on the Catalog page.

**Report** both pages' numbers. If Settings' table became denser, the scoping
failed — report it rather than adjusting a value.

**Then stop** — do not start step 6.

---

### Step 6 — Collaboration Network, both pages (MANUAL GATE)

**The org and per-person pages are one design and are gated together.** They are
identical on every sizing value today, so compressing one and not the other is
what would make them look different — not a pre-existing difference. A gate that
reviewed only one could not confirm they match, which is the whole requirement.

#### 6a. Opt in to the density class — both pages

- `src/ui/pages/collaboration_network/layout.py:167` — the root already has
  `id="collab-page"` and `style={"padding": "0 8px"}`; add
  `className="dense-page"`.
- `src/ui/pages/collaboration_network_ego/layout.py:191` — the root already has
  `id="ego-page"` and the same `style`; add `className="dense-page"`.

#### 6b. Compress the gutters and the filter-card padding — both pages

Apply the same six changes to both files. **Locate each by its surrounding text,
not by the line number** — the numbers are from the planning commit and shift as
you edit:

| Locate by | From | To |
|---|---|---|
| `collab-viz-col` | `"paddingRight": "16px"` | `"8px"` |
| `collab-details-col` | `"paddingLeft": "16px"` | `"8px"` |
| `className="graph-filter-card-body"` (collab) | `"padding": "0 0 24px 0"` | `"0 0 12px 0"` |
| `ego-viz-col` | `"paddingRight": "16px"` | `"8px"` |
| `ego-details-col` | `"paddingLeft": "16px"` | `"8px"` |
| `className="graph-filter-card-body"` (ego) | `"padding": "0 0 24px 0"` | `"0 0 12px 0"` |

The `graph-filter-card-body` padding is the same `"0 0 24px 0"` in all three
graph-style files; Graph's is changed in step 2. These two are the Python-side
replacement for the CSS rule step 1 deliberately omits. Leaving either at 24px
makes that page's filter panel taller than the other's.

#### 6c. Raise the pages' inline `fontSize` literals

Nine declarations across the two files, by the same one-step rule as step 1d —
five in `collaboration_network/layout.py` and four in
`collaboration_network_ego/layout.py`. Enumerate them with:

```bash
grep -rnE '["'\'']fontSize["'\'']\s*:\s*["'\''](9|10|11|12)px["'\'']' src/ui/pages/collaboration_network/layout.py src/ui/pages/collaboration_network_ego/layout.py
```

Both files already import `FONT_SIZE_*` tokens, so no new imports are needed. Use
the same substitution table as step 2c.

**Step 6 verification**:

```bash
grep -c "dense-page" src/ui/pages/collaboration_network/layout.py src/ui/pages/collaboration_network_ego/layout.py   # 1 each
grep -rnE '["'\'']fontSize["'\'']\s*:\s*["'\''](9|10)px["'\'']' src/ui/pages/collaboration_network/ src/ui/pages/collaboration_network_ego/   # no matches
grep -n '"paddingRight": "8px"\|"paddingLeft": "8px"' src/ui/pages/collaboration_network/layout.py src/ui/pages/collaboration_network_ego/layout.py   # 2 each
pytest -m unit tests -q
```

#### GATE 6 — browser review of both Collaboration Network pages

Rebuild, then measure **both** `https://localhost/app/collaboration` and
`https://localhost/app/collaboration/person` (the per-person page needs a person
selected in the header before its canvas renders) and report, for each:

- **The left and right column gutter widths.**
- **The filter panel's height.**
- **The canvas width and height**, versus step 1's baseline.
- **The inline label sizes** — the `10px` slider hints and `11px`/`12px` labels
  must read at their new sizes without wrapping.
- **No page scrollbar**, and no horizontal scrollbar.
- **Both themes.**

**Requirement — the two pages must match.** Every number above must be **equal**
between the two routes. A mismatch means one of the six lines in 6b was missed.

**Report** a two-column table (org | per-person) and state explicitly whether
every row matched. **Then stop** — do not start step 7.

---

### Step 7 — Update the design docs

No gate; this is a documentation step. Do it only after gates 1-6 are confirmed.

**`docs/design/design-system.md`**:

- Update the Font Sizes table (§ Typography) to the new values. The table today
  stops at `11px` and does not list `FONT_SIZE_TINY`, `FONT_SIZE_XTINY` or
  `FONT_SIZE_XXSMALL` at all. Add the rows, and note that `FONT_SIZE_XTINY` and
  `FONT_SIZE_XXSMALL` now share `11px` as the floor.
- Update the Google Fonts Import URL in the same section. The doc quotes it
  verbatim and states it is "included in layout.py", so leaving it behind
  documents a font request the app no longer makes. Match step 1b's new weight
  list, and leave the Cormorant half alone.
- Add a "Dense pages" subsection describing the two-tier rule: which pages are
  dense, how the `.dense-page` scope class works, and that card/form pages keep
  the roomier base. State plainly that the **text** scale is app-wide while
  **density** is per-page — do not imply the card pages are untouched by the text
  change.
- **Leave the Spacing System table's values as they are.** This plan changes no
  `SPACING_*` value.

**`docs/design/frontend-design-skill.md`** — the "Project Design Direction:
Executive Dashboard" block describes a single uniform aesthetic. Add a bullet
noting that data-dense surfaces (Graph, Timeline, Search, Catalog, Collaboration
Network) run tighter spacing than card/form surfaces, and name the `.dense-page`
scope class as the mechanism.

Constraints for both files:

- **Never cite a line number.** Name the module or the class, never `file:line`.
- **Never reference this plan** by number, letter, or stage.
- **No meta-explanations.** State what is true; do not explain why a passage
  exists or why a wording was chosen.

**Verify**:

```bash
grep -n "Inter:wght" docs/design/design-system.md                  # the new weight list
grep -n "FONT_SIZE_LARGE" docs/design/design-system.md             # row reads 16px
grep -n "FONT_SIZE_XTINY\|FONT_SIZE_XXSMALL" docs/design/design-system.md   # both rows, 11px
```

---

### Step 8 — Run the full gate

```bash
source .venv/bin/activate
pytest -m unit tests -q
mypy src/
pylint src --score=y
```

**Verify**: unit tests pass; `mypy` exits 0; `pylint` reports ≥ 10.0. These are
the three CI gates that this change can affect — the PR workflow
(`.github/workflows/pr_checks.yml`) runs pytest, pylint, mypy and bandit, plus a
spec-freshness check that no UI change can disturb. `flake8` is **not** part of
that workflow; see "Commands you will need" for why it is advisory only.

`mypy` runs strict — every new/changed function needs full annotations. Step 2's
`style_override` parameters need `dict[str, Any] | None`, and `result_pane.py`
needs `from typing import Any` added to its imports.

## Test plan

**No new test files.** This is a deliberate choice: the change is visual, and the
only meaningful evidence is measured rendered geometry, which each step's gate
requires. Code-level assertions would pin numbers without proving the pages
actually show more information.

What the existing suite must keep doing:

- `tests/test_page_header_component.py` asserts the header style **equals**
  `COMPACT_PAGE_HEADER_STYLE`. Step 1e changes two values *inside that token*, so
  the test stays green — it compares against the token, not literals. If it fails,
  you edited the header inline instead of the token; revert and fix.
- `tests/test_person_autocomplete.py` — five assertions updated in step 1d, value
  for value. These are the only tests that pin a font size, and they read the CSS
  as raw text, so they must move in lockstep with the declarations.
- `tests/test_shared_graph_components.py` — stays green unchanged; its
  `padding == "8px"` assertion holds because `SPACING_XXSMALL` is unchanged.
- `tests/test_result_pane.py` — asserts the container and Cytoscape **ids** only,
  no styles, so step 2d's new parameters leave it green. It is the file to extend
  if a unit-level check on the override is wanted.

Verification: `pytest -m unit tests -q` → all pass, including the five updated
assertions.

## Done criteria

ALL must hold, **after gates 1-6 have each been confirmed by the operator**:

- [ ] `pytest -m unit tests -q` exits 0
- [ ] `mypy src/` exits 0; `pylint src --score=y` reports ≥ 10.0 (the CI gates —
      `flake8` is not one; see "Commands you will need")
- [ ] `grep -rn "dense-page" src/ui/pages/ | wc -l` → 6 (one per dense page root)
- [ ] `grep -c "dense-page" src/ui/assets/executive-dashboard.css` → 5 — the five
      selectors in step 1g's block: `.timeline-card`,
      `.graph-right-panel-tab-icon`, `.graph-right-panel-tab-bar`, and the two
      `.executive-table` selectors. There is deliberately no `graph-filter-card`
      rule.
- [ ] `grep -n "dense-page .graph-filter-card" src/ui/assets/executive-dashboard.css` → no matches
- [ ] `grep -nE "font-size: *(9|10)px" src/ui/assets/executive-dashboard.css` → no matches
- [ ] `grep -cE "font-size: *var\(" src/ui/assets/executive-dashboard.css` → 3
- [ ] `grep -rnE '["'\'']fontSize["'\'']\s*:\s*["'\''](9|10)px["'\'']' src/ui/pages/graph/ src/ui/pages/collaboration_network/ src/ui/pages/collaboration_network_ego/ src/ui/pages/search.py` → no matches
- [ ] `grep -n "SPACING_\(XXXSMALL\|XXSMALL\|XSMALL\|SMALL\|MEDIUM\|LARGE\|XLARGE\|XXLARGE\) =" src/ui/styles.py` → values unchanged from `4px/8px/12px/16px/24px/32px/40px/48px`
- [ ] `grep -n "\"height\": \"40px\"" src/ui/styles.py` → 1
- [ ] `grep -rn "calc(100vh" src/ui/pages/ --include="*.py"` → timeline 200px, ego
      128px, collab 180px, chat 220px (unchanged), step 2d's two Graph overrides,
      and the ego `_EMPTY_STATE_STYLE` docstring's historical `145px` (leave it).
      **Do not use the `src/ui/pages/*.py` glob here.**
- [ ] `grep -c "Inter:wght@400;500;600;700" src/ui/layout.py` → 1
- [ ] `grep -n "Inter:wght" docs/design/design-system.md` → matches `layout.py`
- [x] **Gate 1 confirmed**: card-page interior padding identical to before; card
      and form pages reviewed for text regressions (Chat composer, Analytics
      cards, setup banner, Settings table); both themes checked
- [x] **Gate 2 confirmed**: Graph canvas and empty state both grown and **equal**;
      filter panel shows no wrapping
      - Canvas and empty state both measured 784px tall. Canvas sits 52px lower
        only while the status strip is visible; dismissing the alert collapses the
        strip to zero and the canvas returns flush to the viewport edge. The
        transient offset is accepted — the strip is dismissable and the canvas is
        pannable, so no content is unreachable. No change made.
- [x] **Gate 3 confirmed**: Timeline row count ≥ baseline, per-lane truncation loss
      reported, no clipped card text
      - Card height 52px → 44px and lane pitch 56px → 48px, identical in both
        themes. Zero vertically clipped cards.
      - Row count at the natural window is 4 = baseline. The grid is
        content-height-limited, so the reclaimed height shrinks the container
        instead of revealing another row; scrolled windows show the dense card
        crossing an extra-row threshold one step earlier (216px: 2 → 3 rows;
        330px: 3 → 4 rows). No window shows fewer rows than the baseline.
      - **Truncation loss: none.** Comparing fit-per-text against the pre-density
        card metrics, the primary line sits at 100% in both states, and the
        secondary name is equal or slightly better under the dense rule
        (+0.0pp, +1.6pp, +1.9pp) — the tighter padding (6px vs 7px per side)
        hands each name ~2px more width. No text is worse off.
      - Page keeps no scrollbar: `scrollHeight == clientHeight` at a 900px
        viewport, and neither axis overflows.
- [x] **Gate 4 confirmed**: Search result count ≥ baseline, filter inputs unchanged
      - Result card padding `SPACING_SMALL` → `SPACING_XSMALL` (16px → 12px);
        `marginBottom` stays `SPACING_XSMALL` (12px). Card height 175px → 167px and
        the results column's scrollHeight 2178px → 2098px (80px of reclaimed list
        length, ~3.7%).
      - Visible cards at a given scroll position are never meaningfully fewer under
        the density rule. Sweep of `#content-col` scrollTop 0→1300 in 100px steps
        against a forced pre-step-4 reference: identical at 10 positions, and +1
        fully-visible card at 800, 1000 and 1200. One position (400) reports one
        card fewer, and inspecting the geometry shows the card's top edge sits
        0.6px above the viewport edge — a sub-pixel boundary artifact, not a
        regression.
      - **Filter inputs unchanged**, as required: the shared `INPUT_STYLE`
        consumers measure `padding: 16px 14px`, `line-height: 19.5px`,
        `font-size: 13px`, `height: 34px` both before and after. The constant was
        not touched, so Settings → Runtime is unaffected.
      - No text clipped in any card (`0` cards with overflowing leaf text in both
        states), and all 10 result badges render on a single line with no
        wrapping. Both themes measure identical; no horizontal overflow.
- [x] **Gate 5 confirmed**: Catalog table denser **and** Settings → User Management
      table **not** denser
      - Catalog (`denseScope=True`): cell padding `4px` → `2px` vertical, row height
        48/50px → **44/46px**, table height 6990px → **6426px** (−564px), visible
        rows 14 → **15**. Identical in both themes.
      - Settings → User Management (`denseScope=False`): cell padding `4px`,
        row height 38px, table height 103px — **unchanged**, matching the pre-step-5
        baseline exactly. This is the check that proves the `.dense-page` scoping held.
      - The step required a `.executive-table` rule that actually bites. The original
        `padding-top/bottom: 4px` restated Bootstrap Materia's `.table-sm` value
        (`size="sm"` on both tables) and measured as a no-op — computed padding was
        4px with and without the class on both pages. The rule was corrected to 2px
        so the density is real; see the amended CSS block above step 2.
      - Horizontal cell padding is deliberately left at Bootstrap's 4px: a `padding`
        shorthand would move column gutters, which is out of scope for this step.
- [x] **Gate 6 confirmed**: every measured value **equal** between the two
      Collaboration Network pages
      - Org and per-person pages match on every sizing value, in both themes:
        root `padding: 0 8px` with `className="dense-page"`; viz column
        `padding-right: 8px`; details column `padding-left: 8px` with the 1px left
        border; filter-card body `padding: 0 0 12px 0`; identical inline font-size
        sets (`11px`/`12px`/`13px`, all token-backed).
      - No label wraps in either filter panel (0 wrapped), so the +1px literal
        raise did not reflow a control.
      - No page scrollbar and no horizontal overflow on either page; canvas fills
        the viewport on both.
      - The org page carries one extra control (a `graph-filter-checklist`, absent
        from the per-person page), so it has 5 inline font literals against 4 —
        the value the original plan mis-stated as 4 vs 4. Both pages' literals were
        raised with the same tokens.
      - The plan's claim that "no new imports are needed" was wrong: both files
        imported only `FONT_SIZE_SMALL`/`FONT_SIZE_XSMALL`. `FONT_SIZE_TINY` and
        `FONT_SIZE_XTINY` were added to both import blocks, verified as used in
        each (pylint has no unused-import).
      - **Follow-on fix found by browser review**: both collaboration filter
        panels had `graph-filter-card-body` at `padding: 0 0 12px 0` — zero left
        and right — so the panel's inner text sat flush against its left edge.
        Pre-existing, not caused by this step (HEAD carried the same `0 0 24px 0`
        with the horizontal values already at zero); Graph had been fixed the same
        way during its own step. Both pages now read `0 8px 12px 8px`, matching
        Graph, and the first text line measures an 8px inset from the panel edge in
        both themes. The column gutters were deliberately left at their new 8px —
        only the inner container's horizontal padding changed.
- [ ] Measured: the rendered topbar is 40px, not re-inflated by Bootstrap to fit
      its 32px controls
- [ ] No files outside the in-scope list are modified (`git status`)
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report back (do not improvise) if:

- The `get_layout()` roots, the padding values or the inline literals in "Current
  state" and in the steps do not match the live code — the codebase has drifted
  since this plan was written.
- **A step's gate is not yet confirmed by the operator.** Do not proceed to the
  next step. This is the plan's primary control and the reason it is split.
- **Step 1 makes any card or form page visibly worse** — text clipped in the Chat
  composer's fixed 68px box, an Analytics card's content overflowing its 220px
  minimum, the setup banner wrapping, or a Settings table column overflowing.
  Report the page and the effect. Do not compensate by shrinking a value the step
  does not name, and do not revert the whole sweep.
- `tests/test_page_header_component.py` fails after step 1e. It compares the header
  style to the token, so a failure means `COMPACT_PAGE_HEADER_STYLE` was edited in
  a way the test does not expect. Investigate rather than loosening it.
- **The literal raise in step 1d or a page's step makes that page visibly worse.**
  Lifting a 10px label to 11px, or a 12px one to 13px, can break a tightly-sized
  container, wrap an uppercase badge onto two lines, or push a table column into
  overflow. Report which rule or module, with the page and the effect. The inline
  literals are the likelier of the two to reflow a container, because several of
  them size a Dash control (a `dbc.Checklist`, a `dbc.RadioItems`) rather than a
  text line.
- A two-line timeline card is clipped after step 3. The card is two single `nowrap`
  lines, so this means a rule caused wrapping. Report which rule rather than
  experimenting with heights.
- The two Collaboration Network pages measure **differently** at gate 6 — different
  gutters, or filter panels of different heights. They are identical before this
  change, so a difference means one of the six lines in 6b was missed. Report which
  one rather than adjusting a value to compensate.
- Graph's **empty state and canvas** measure differently at gate 2, or the empty
  state is still 75vh. Both are overridden in step 2d; a mismatch means one of the
  two call sites was missed.
- **Settings → User Management's table becomes denser** at gate 5. The `.dense-page`
  scoping has failed; find the cause before proceeding.
- Compressing a page's gutters causes visible overflow, wrapping, or a horizontal
  scrollbar.
- A dense page's density turns out to be driven by a CSS rule you were not told
  about, such that a `.dense-page` override does not take effect (a specificity
  conflict). Report it rather than escalating `!important`.
- Anything appears to require editing a file in the "Out of scope" list.

## Maintenance notes

For the human or agent who owns this after it lands:

- **The two tiers are enforced by convention, not by code.** Nothing stops a future
  page from adding `className="dense-page"`, and nothing catches a dense value
  leaking into a shared class. A reviewer should check that every new density rule
  is scoped under `.dense-page`, and that no card page's root ever gains the class.
- **The text scale is app-wide and has no per-page escape hatch.** The `FONT_SIZE_*`
  tokens have more call sites on card/form pages than on dense pages, so any future
  change to them lands on the card pages too. Review it against the card pages
  first, not the dense ones.
- **Inline styles are the recurring trap here.** `.graph-filter-card*` padding and
  every dense page's label sizes are set inline in Python, where no stylesheet rule
  can reach. Before adding a CSS override for a dense-page element, check whether
  the element carries an inline style for the same property — if it does, the rule
  is dead code and the value belongs in Python. The reverse also holds: a new inline
  `fontSize` on a dense page bypasses the token scale entirely.
- **The two Collaboration Network pages are kept identical by hand.** They share a
  design and their sizing values match, but nothing enforces that. A change to one
  page's gutters, filter padding or canvas height should be mirrored in the other; a
  reviewer should diff the two layout modules whenever one is touched.
- **The four `calc(100vh - Npx)` constants are coupled to the chrome height.** If
  the topbar height or the page-header padding changes again, all four need
  re-deriving, or the canvases will stop filling the viewport. Graph's two overrides
  are coupled the same way. This is the most fragile part of the change.
- **`FONT_SIZE_XTINY` and `FONT_SIZE_XXSMALL` now hold the same value.** They are
  kept as separate names because ~40 call sites import them. Collapsing them into
  one constant is a reasonable follow-up but must be a separate change with its own
  sweep.
- **The Search filter inputs were deliberately left at their current padding** —
  they are click targets, not rows. A later pass that compresses them is making a
  usability trade-off, not a density win.
- **Timeline card text is `nowrap` + ellipsis, so its font size trades against how
  much of each title is visible.** Raising the size shortens the visible text.
  Anything that later widens the lane columns, or that switches a card line to wrap,
  changes that trade-off — re-measure rather than assuming the current sizes are
  right.
- **The timeline card styles have no test coverage.** The
  `tests/test_activity_timeline_*` suites assert component structure, not CSS, so
  nothing fails if a card rule breaks. A reviewer changing timeline styling has only
  visual verification to rely on.
- **Deferred out of this plan**: a user-selectable density mode. The values are now
  largely centralised (tokens + `.dense-page`), so it is feasible, but it would
  require routing the ~112 remaining literal CSS px values through custom properties
  first, and would double the visual-verification surface. The inline `fontSize`
  values are now token-backed in name, but a density mode would still need them read
  from a runtime source rather than a module constant.

# Plan 061: Make the authn/authz design document a design document

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving on. If
> anything in "STOP conditions" occurs, stop and report — do not improvise.
> Do **not** commit or push. Do not update `plans/README.md` — the reviewer
> maintains the index.
>
> **Each step ends with a MANUAL GATE.** Hand back to the operator and wait for
> `PASS`. A `FAIL` is a STOP condition.
>
> **Drift check (run first)**: `git diff --stat 225d3639..HEAD -- docs/design/authn-authz-design.md CLAUDE.md .env.example DEVELOPER_QUICK_START.md`
> The diff is **never empty** — every `Planned at` stamp in `plans/` was recorded
> on a feature branch that is not an ancestor of `main`. Judge drift by opening the
> "Current state" excerpts below against the live files, not by the diff being
> empty.

## Status

- **Priority**: P1
- **Effort**: **L** (rewritten 2026-11-03 — Step 2 is a full-document rewrite, not an edit pass)
- **Risk**: LOW (documentation only)
- **Depends on**: plans/060 (**DONE**)
- **Category**: docs
- **Planned at**: commit `225d3639`, 2026-10-30. **Re-planned 2026-11-03 at `781c4d1a`.**
- **Design reference**: `docs/design/authn-authz-design.md`
- **All steps complete.** 1 (factual corrections), 2 (de-plan), 3 (regression), 4 (de-history), 5 (Non-API Surfaces coherence).

## The two operator rulings this plan ended up serving

1. *"The design doc should not refer to plan doc names and stages. Plan documents will be deleted
   over time… only design artifacts and not implementation plan."* → **Step 2**, and the shape of
   the whole plan.
2. *"Lines like this are useless and add no value… Review this document to make sure such historic
   references are not present. Keep the design doc concise."* → **Step 4**, after Step 2 shipped.

Both are the same principle: a design document states what is true, not how it came to be. The
document went 1006 → 789 lines, 18 → 15 `##` sections, with every fact table intact
(matrix 28 rows, Decision Summary 14, Configuration 12).

## Why this matters

Two problems, both about the same file.

**First (Step 1, done): the document was factually stale.** Eight specific claims
had been overridden by decisions taken while building the auth programme. A
developer reading it would have implemented the wrong thing. Those are corrected.

**Second (Step 2, this plan's real work): the document is written as a programme
document, not a design document.** The operator's ruling:

> *"The design doc should not refer to plan doc names and stages. Plan documents
> will be deleted over time. The document needs to be rewritten completely to
> contain only design artifacts and not implementation plan. The plans have been
> implemented and therefore this design document should survive long term for
> developers as a reference document containing facts and design only."*

This matters because `plans/` is explicitly ephemeral in this repository —
`plans/README.md:16` says *"Plan files for completed work are removed as they
land — that is this directory's convention."* Every `Plan C` / `Plan D` / `Plan E`
reference in this document is therefore a reference that **will** dangle. There are
**37** of them. No other document in `docs/design/` has a single one; this file is
the outlier.

The reference document a developer reaches for must describe the system that
exists, in the present tense, with no dependency on a plan number that has since
been deleted.

## Current state

**`docs/design/authn-authz-design.md`** — 1006 lines after Step 1, 18 `##` sections,
41 `###` sections. Self-verified at `781c4d1a`:

| Measure | Count |
|---|---|
| `Plan C` references | 13 |
| `Plan B` references | 6 |
| `Plan E` references | 5 |
| `Plan D` references | 5 |
| `Plan F` references | 4 |
| `Plan A` references | 4 |
| **Total `Plan <letter>`** | **37** |
| Lines containing `[Pp]lan` | 46 |
| Parenthesised plan numbers, e.g. `(053)` | 2 (`:268`, `:961`) |
| `##` sections | 18 |
| `###` sections | 41 |
| Endpoint-matrix data rows | 26 |
| Decision-Summary rows | 14 |
| Configuration-table rows | 12 |

The plan references fall into three groups:

**(a) Inline prose, ~33 occurrences, spread across the whole document.** These
read as `Plan C added X`, `Deferred to Plan D`, `handled by a separate plan (Plan
E)`, `Settled in Plan C (053)`. Most describe real design facts and need only to be
restated in the present tense or as ordinary future work.

**(b) `## Implementation Plans` (lines 768–793, ~26 lines).** A six-row A–F table,
plus the paragraphs *"Why B precedes C"*, *"Documentation changes required in C"*,
and *"Why F is broken out rather than left as a paragraph"*. Pure programme
content. It duplicates `plans/README.md`, which is the live index.

**(c) `## Plan B Scope — Dash–API Runtime Separation` (lines 796–929, 134 lines).**
A scope sketch for the Dash–API split, which has **already shipped**. Contains
`dash_app/` file counts and LOC figures, a coupling inventory, a work-item list, a
test-impact estimate and a sizing table — all describing work that is done, against
a package path (`dash_app/`) that no longer exists.

### Repo conventions that apply

- `CLAUDE.md` is the **single source of truth**; `.github/copilot-instructions.md`
  is a symlink to it.
- The document's prose style is direct, evidence-based, and cites `file:line`.
  Match it. Do not add a changelog, a revision history, or a "what changed" note.
- Every other file in `docs/design/` is the style target: **to state a fact is to
  state it; no plan number, no implementation history.**
- Do **not** commit or push.

## Scope

**In scope** (this step):
- `docs/design/authn-authz-design.md` — the whole file.

**Already changed by Step 1** (leave alone unless a rewrite edit touches the same
line): `CLAUDE.md`, `DEVELOPER_QUICK_START.md`, `.env.example`, `INSTALL_GUIDE.md`,
`docker-compose.yml`.

**Out of scope** (do NOT touch):
- Any source code. If a doc and the code disagree and the **code** is wrong, STOP
  and report — the fix belongs to the work that owns it.
- Deleting or editing anything under `plans/`. The plan record stays.
- `.github/copilot-instructions.md` — it is a symlink.
- `README.md`, CI config, release notes.

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Unit tests | `pytest -m unit tests -q` | unchanged, 0 fail |
| Typecheck | `mypy src/` | exit 0 |
| Lint | `pylint src --score=y` | ≥ 9.0 |
| Security | `bandit -c .bandit.yml -r src/ -lll` | exit 0 |
| Doc length | `wc -l docs/design/authn-authz-design.md` | reported, not asserted |

---

### Step 1: The eight factual corrections — ✅ DONE 2026-11-03

**Dispatch record.** Executed in the working tree at `781c4d1a`, uncommitted, by a
general-purpose executor. Verdict **APPROVE**, after one revision round.

Corrections applied (items 1–8 of the original "Current state" list):

- **1a/1b** — added the `wba-service` scope sentence and the runtime-snapshot note
  under the endpoint matrix. **No service-column cell was changed**, as required.
- **1c** — theme authoring user cell `✓ *(own themes)*` → `✗`, with the admin-only
  note rewritten.
- **1c-2** — the `wba-user` Roles row narrowed to *"manage their own chat
  sessions"*; it had claimed *"favourites, and graph themes"*, both false against
  `src/app/auth/matrix.py`.
- **1d** — the favourite-toggle matrix row deliberately left untouched (plan 065's
  concern).
- **1e** — the false "revoked or deleted row ends access immediately" claim
  replaced with the honest **at most 15 minutes** bound and its rationale.
- **1f** — the two cookie-authenticated endpoints (`/api/v1/auth/token`,
  `/api/v1/auth/logout`) documented as the only exception to bearer-only.
- **1g** — Status line, Overview and the "Current State" heading rewritten from
  unbuilt to as-built.
- **1h** — theme endpoint paths corrected from `/api/v1/graph_themes/` to
  `/api/v1/graph-themes/` (rows 336 and 338 today). The Step 3 endpoint sweep was
  empty afterwards; it reported exactly those two paths before, so it is not
  vacuous.
- **1i** — `APP_PUBLIC_BASE_URL` and `KEYCLOAK_INTERNAL_URL` added to the
  Configuration table.
- **1j** — the docs-routes bullet rewritten from *"Plan C must revisit it"* to
  *"Reviewed under Plan C, kept public."*
- **1k/1l/1m** — `ADMIN_GUIDE.md` → `IAM_ADMIN_GUIDE.md` in
  `DEVELOPER_QUICK_START.md`; the design doc registered in `CLAUDE.md`'s Reference
  documents table; the bearer rule added to `CLAUDE.md`; the Keycloak/auth env
  paragraph added; a "Signing in" section added to the quick start; `.env.example`
  verified already complete.

**Revision round** (operator-approved scope widening) also: narrowed the
`## Summary` capability sentence to match the Roles table, and propagated the
`IAM_ADMIN_GUIDE.md` rename to the three remaining stale references in
`.env.example:214`, `INSTALL_GUIDE.md:125` and `docker-compose.yml:52`.

**Step 1 did NOT do** (Step 2's job): remove plan references. In fact it *added*
three — the Status line *"Implemented in Plan C"*, the 1g sentence *"Plan C added
`src/app/auth/`"*, and *"Reviewed under Plan C, kept public"*. Those come out in
Step 2.

---

### Step 2: Rewrite the document as a design document

**This is a rewrite of a 1006-line file. Work section by section, top to bottom,
and do not skip a section.** The rule is simple and applies everywhere:

> **State the system, in the present tense, as a fact. Never cite a plan letter, a
> plan number, or a plan stage. Never describe implementation history or sequencing.**

#### 2a — Delete two sections outright

Delete both, in full, including their subsections:

1. **`## Implementation Plans`** — the `## Implementation Plans` heading, the
   *"Six plans. Dependency order is A → B → C → D → E…"* sentence, the six-row A–F
   table, and the three paragraphs after it (*"Why B precedes C"*, *"Documentation
   changes required in C"*, *"Why F is broken out rather than left as a
   paragraph"*). Delete the `---` rule that separates the section too; keep the
   document's other `---` rules.
2. **`## Plan B Scope — Dash–API Runtime Separation`** — the heading, the
   *"This is a scope sketch for review…"* note, and all of `### Why this exists`,
   `### What is already true (verified)`, `### Coupling inventory`,
   `### Work items`, `### Test impact`, `### Sizing`, `### Explicit non-goal`.

**Migrate nothing.** The operator's decision is that this content describes
completed implementation work and the design it delivered is already stated
elsewhere in the document — the UI/API split is Overview property 1 and
`## Non-API Surfaces` §1, and the theme/ownership gaps are in the Roles and matrix
notes. There is a doubled `---` separator immediately before `## Future
Considerations`; leave exactly one.

After this step the document must contain **no occurrence of the substring
`Plan` in any case** — the 37 plan-letter references, the 2 parenthesised numbers,
and the 46 matching lines all reach zero. This can only be true if every remaining
one is rewritten, so treat any residual match as unfinished work, not an exception.

#### 2b — Rewrite the inline plan references, section by section

Do each section in document order. The substitution principle is the same
throughout: **a plan reference is a way of saying *when* something was decided;
replace it with a statement of *what is true*.**

| Current text (paraphrased) | Rewrite as |
|---|---|
| `**Status:** Implemented in Plan C; this document describes the system as built.` (`:6`) | `**Status:** Implemented. This document describes the system as built.` |
| `…no authentication… before Plan C.` (`:12`) | `…no authentication… before this design was implemented.` |
| `(Plan B)` / `a prerequisite (Plan B)` (`:25`, `:32`) | Delete the parenthetical; state the property directly — *"the UI and API are separate runtimes"*. |
| `scoped as Plan F` (`:54`) | Delete; the bullet already states the boundary. |
| `A separate prerequisite plan (Plan A) adds an nginx TLS-terminating proxy…` (`:55`) | Rewrite as present fact: *"TLS termination is provided by an nginx proxy in the Compose stack, and the application is proxy-aware. This design assumes HTTPS…"* |
| `Splitting the UI and API into separate runtimes. Plan B does this…` (`:58`) | *"Splitting the UI and API into separate runtimes. The two run as separate containers, with the UI unable to reach a database. This design assumes that separation…"* |
| `handled by a separate plan (Plan E)` (`:63`) | *"…are **not yet hardened**. This design does not address them."* |
| `Deferred to Plan D… Until Plan D lands, the theme-authoring row… is admin-only in practice.` (`:64-67`) | State the fact and the gap: *"Per-user configuration storage does not exist, so theme writes are admin-only; see the endpoint matrix."* |
| `Named as Plan F so it stays visible` (`:68`) | Delete the phrase; the bullet and the Future Considerations section already state it. |
| `### Before Plan C: no authentication existed` (`:103`) | `### Before this design: no authentication existed` |
| `Plan C added \`src/app/auth/\` (…)` (`:116`) | *"The system that implements this design is \`src/app/auth/\` (…)."* |
| `**Settled in Plan C (053).** The app container must be able to *fetch*…` (`:268`) | *"The app container must be able to *fetch* discovery and JWKS from that URL…"* — drop the banner and the number. |
| `Theme writes are **admin-only** in Plan C. Plan D adds nullable \`subject\` ownership; until it lands, "own themes" does not exist… the same per-user gap as Plan D. Plan D's migration scopes…` (`:358-363`) | Restate once, plan-free: theme writes are admin-only; there is no owner column on `graph_themes`, so "own themes" does not exist; adding nullable `subject` ownership would scope user themes to their creator while leaving the global `is_default` shared. Keep the `db/models/graph_theme.py:46-48` citation. |
| `**Reviewed under Plan C, kept public.**` (`:610`) | `**Deliberately public.**` Keep the justifying sentences verbatim. |
| `\`EXTERNAL_BASE_URL\` and \`AUTH_COOKIE_SECURE\` are owned by Plan A (TLS and proxy-awareness) and consumed here.` (`:649`) | *"\`EXTERNAL_BASE_URL\` and \`AUTH_COOKIE_SECURE\` come from the TLS/proxy-awareness configuration. They are listed because the login flow is incorrect without them."* |
| `### 2. Host-exposed infrastructure → Plan E` (`:566`) | `### 2. Host-exposed infrastructure` (drop the arrow and the plan). Same for `### 3. Other exposures → Plan E` (`:579`). |
| `listed these endpoints as exposures for Plan E to close` (`:601`) | *"an earlier draft of this document listed these endpoints as exposures to close"* — or delete the sentence; it records superseded reasoning. |
| `The brief requires that paths… be identified and handled by a separate plan.` (`:542-543`) | *"Paths that reach the backend without passing through the secured API are inventoried below."* |
| `nginx terminates TLS in front of the application and Keycloak (Plan A).` (`:708`) | *"nginx terminates TLS in front of the application and Keycloak."* |
| `the entire reason the proxy-awareness work is a prerequisite rather than an afterthought. The Plan B separation is what makes…` (`:721-722`) | *"…which is why proxy-awareness is load-bearing. The UI/API separation is what makes the two services independently scalable…"* |
| `Nothing in Plan C is localhost-only *by construction*…` (`:743`) | *"Nothing in this design is localhost-only *by construction*…"* |
| `(Plan E owns broader credential handling)` (`:759`) | *"(broader credential handling is not yet addressed)"* |
| `Plan A's proxy-awareness makes this a configuration change…` (`:760`) | *"Proxy-awareness makes this a configuration change…"* |
| `Found while building Plan C (053), **unresolved**…` (`:961`) | *"**Unresolved**, and deliberately not blocking…"* — drop the plan banner and number. |
| `### Per-person data scoping (Plan F)` (`:932`) | `### Per-person data scoping` and rewrite the body's first sentence, which says *"Named as Plan F so the work stays visible"*, to state the gap directly. |

**Also, and independently of plan references**, three statements are false and must
be corrected while you are in the line:

1. **`## Decision Summary` row 9** (`:92`) reads *"Per-user ownership of chat
   sessions and catalog favourites"*. Chat sessions are owner-scoped; **catalog
   favourites are not** — `CatalogMetadata` has no `subject` column, so favourites
   remain global. Rewrite the row to claim only what exists (per-user chat-session
   ownership) and, if you keep the favourites half, mark it as not yet implemented.
   Do **not** touch the `Favourite toggle` row of the endpoint matrix — that is
   explicitly out of scope here.
2. **`## Session Management → ### Storage`** (`:440`) ends *"— or a dedicated key;
   the plan will decide, but it must not be stored in plaintext."* This is an
   unresolved decision written as a plan placeholder. The code resolves it: the
   refresh token is stored as `refresh_token_encrypted` and encrypted with the
   existing Fernet machinery keyed by `CONNECTOR_ENCRYPTION_KEY`
   (`src/app/auth/session_cookie.py:58,104`; `src/app/db/models/auth_session.py`).
   State that as fact.
3. **Decision Summary row 14** (`:97`) says *"Forced into phase 1 because a
   bearer-only API breaks the producers and consumer otherwise."* Drop the *"Forced
   into phase 1"* phrasing; keep the technical reason.

#### 2c — Re-point stale file paths

The document cites `dash_app/`, which no longer exists — the package is `src/ui/`
(imported as `ui.*`). Two citations survive Step 2a:

- `docs/design/authn-authz-design.md:479` — `dash_app/api_client.py` → `src/ui/api_client.py`
- `docs/design/authn-authz-design.md:526` — `dash_app/components/common.py:159` → `src/ui/components/common.py:159`

**Three further paths are stale and must be corrected:**

- `docs/design/authn-authz-design.md:108` cites `src/app/main.py:158-181`. **That file
  does not exist** — the UI/API split removed it. `add_request_context` now lives in
  `src/app/api_main.py` (its `@app.middleware("http")` decorator is at `:155`, the
  function ends around `:180`). Correct the filename and check the range.
- `docs/design/authn-authz-design.md:386` cites `src/ui/layout.py:27-28` for the two
  `/app/` prefix settings. They are at `:29-30` (`:27` is `app = dash.Dash(`). Correct
  the range.
- `docs/design/authn-authz-design.md:526` cites `pages/settings/runtime.py:300` as the
  canonical alert-region example. The feedback `html.Div` is at `:299` and `:300` is
  the `create_page_header(...)` call. Re-point to the element that is actually the
  example.

**Fully qualify every path citation you keep.** Many are abbreviated with an
implied base (`client.py:47`, `pages/settings/runtime.py:300`,
`db/models/graph_theme.py:46-48`, `api/chats/v1/router.py:39-72`). A reference
document must be navigable: resolve each to a real path from the repository root
(`src/common/runtime_settings/client.py:47`, `src/ui/pages/settings/runtime.py:300`,
`src/app/db/models/graph_theme.py:46-48`, `src/app/api/chats/v1/router.py:39-72`,
and so on). The `file:line` **numbers** must be checked against the live file — if
the line no longer holds the cited thing, correct it or drop the line number.
Do not invent a citation for something you did not verify.

#### 2d — Verify

Run all of the following and report each actual observed value.

```
# ── plan references: every one must be zero ──────────────────────────────
grep -cE '\bPlan [A-F]\b'                docs/design/authn-authz-design.md   # → 0
grep -ciE '\bplans?\b'                   docs/design/authn-authz-design.md   # → 0
grep -cE '\(0[0-9]{2}\)'                 docs/design/authn-authz-design.md   # → 0
grep -n  'Implementation Plans'          docs/design/authn-authz-design.md   # → no matches
grep -n  'Plan B Scope'                  docs/design/authn-authz-design.md   # → no matches
grep -n  'dash_app'                      docs/design/authn-authz-design.md   # → no matches

# ── content preservation: these must be UNCHANGED from the values below ──
grep -c '^## '                           docs/design/authn-authz-design.md   # → 15  (18 originally; Step 2 deleted two, Step 4 deleted `## Current State`)
sed -n '/^| Feature | Endpoint/,/^$/p' docs/design/authn-authz-design.md | grep -c '^|'   # → 28 (26 data rows + header + separator)
sed -n '/^## Decision Summary/,/^---/p' docs/design/authn-authz-design.md | grep -c '^| [0-9]'   # → 14
sed -n '/^## Configuration/,/^---/p' docs/design/authn-authz-design.md | grep -c '^| `'   # → 12

# ── Step 1's corrections must survive the rewrite ────────────────────────
grep -c 'graph-themes'                   docs/design/authn-authz-design.md   # → ≥2 (not reverted to the underscore)
grep -c 'graph_themes/'                  docs/design/authn-authz-design.md   # → 0
grep -c 'at most 15 minutes'             docs/design/authn-authz-design.md   # → ≥1
grep -c 'The two cookie-authenticated endpoints' docs/design/authn-authz-design.md  # → 1
grep -c 'KEYCLOAK_INTERNAL_URL'          docs/design/authn-authz-design.md   # → ≥3
grep -c 'APP_PUBLIC_BASE_URL'            docs/design/authn-authz-design.md   # → ≥2
grep -c 'IAM_ADMIN_GUIDE.md'             docs/design/authn-authz-design.md   # → ≥2
awk -F'|' '/^\| Theme authoring/{print $4}' docs/design/authn-authz-design.md | grep -c '✓'  # → 0

# ── no placeholder/undecided prose survives ──────────────────────────────
grep -nE 'the plan will|will decide|must be built in phase|phase 1' docs/design/authn-authz-design.md   # → no matches
```

Then the citation check. Run this **exactly**:

```bash
python - <<'PY'
import pathlib, re

doc = pathlib.Path('docs/design/authn-authz-design.md').read_text()
root = pathlib.Path('.')

# Backticked tokens that look like repo paths.
tokens = set(re.findall(r'`([A-Za-z0-9_./-]+\.(?:py|js|json|ya?ml|txt|sh|md|conf|template))(?::[0-9]+(?:-[0-9]+)?)?`', doc))

SKIP_PREFIX = ('/api/', '/app/', '/docs', '/redoc', '/openapi', '/auth/', '/stream/')
SKIP_EXACT = {
    'CLAUDE.md',                      # repo root, exists
    'IAM_ADMIN_GUIDE.md',             # repo root, exists
    'deploy/certs/*',                 # glob, not a literal path
}

missing = []
for tok in sorted(tokens):
    if tok.startswith(SKIP_PREFIX) or tok in SKIP_EXACT:
        continue
    if '*' in tok or '{' in tok:
        continue
    if not (root / tok).exists():
        missing.append(tok)

print('path citations checked:', len(tokens))
print('missing:', missing)
PY
```

→ `missing: []`, or every entry is one you can explain in NOTES as a genuine
non-path (a module name, a URL). **A citation that does not resolve to a real file
is a defect in a reference document** — fix the path or drop the citation.

> ### 🚦 MANUAL GATE 2 — the rewrite
>
> Operator reads the rewritten document end to end and confirms:
> 1. No plan letter, plan number, or implementation stage appears anywhere.
> 2. The `## Implementation Plans` and `## Plan B Scope` sections are gone and
>    nothing they uniquely said was lost.
> 3. Every remaining claim reads as a statement about the system, not about work.
> 4. The endpoint matrix still matches `src/app/auth/matrix.py`.
> Wait for `PASS`.

---

### Step 3: Final consistency sweep and full regression

**Verify**: `pytest -m unit tests -q` → **2627 passed, 2 skipped, 0 failed** at
the time of writing; report the observed figures
**Verify**: `mypy src/` → exit 0
**Verify**: `pylint src --score=y` → ≥ 9.0
**Verify**: `bandit -c .bandit.yml -r src/ -lll` → exit 0
**Verify**: `grep -rn "authn-authnz" docs/ CLAUDE.md | wc -l` → `0`. **`plans/` is
deliberately excluded**: the original command searched `plans/` too, and its only
match in the repository is the plan's own copy of the command — a self-referential
check that could never return `0`.
**Verify**: the doc↔code endpoint sweep below.

The sweep must find the paths **inside the matrix table cells**, which begin with an
HTTP method. A naive `` `(/api/…) `` pattern only matches a backtick immediately
before `/api` and catches 5 of the document's paths — it would miss every row this
plan touches. Run exactly this:

```bash
python - <<'PY'
import re, pathlib

doc = pathlib.Path('docs/design/authn-authz-design.md').read_text()
matrix = pathlib.Path('src/app/auth/matrix.py').read_text()

def norm(p: str) -> str:
    p = re.sub(r'\{[^}]+\}', '{x}', p)   # {id} / {session_id} placeholders
    p = re.sub(r'\[[^\]]*\]', '', p)     # [/ego] shorthand in a cell
    return p.rstrip('*').rstrip('/')

raw = set(re.findall(r'`(?:\w+\s+)?(/api/[^`\s?,]+)', doc))
candidates = {p for p in raw if p.count('/') >= 3
              and '*' not in re.sub(r'\[[^\]]*\]', '', p)}
matrix_norm = {norm(p) for p in re.findall(r'"(/api/[^"]+)"', matrix)}

missing = sorted(p for p in candidates
                 if norm(p) not in matrix_norm and '/auth/' not in p)
print('missing from matrix:', missing)
assert not missing, f'documented paths absent from matrix.py: {missing}'
PY
```

→ prints `missing from matrix: []` and exits 0 — from the state after Step 1 the
`graph_themes` defect is already fixed, so the sweep is expected to be clean
throughout this step. A non-empty list is a STOP condition.

> ### 🚦 MANUAL GATE 3 — consistency
>
> Operator confirms the sweep is empty and that nothing was changed outside the
> files listed in Scope.
> Wait for `PASS`.

---

### Step 4: Remove historical narration

**Operator ruling, 2026-11-03, reviewing the Step 2 output:**

> *"Lines like this are useless and add no value. 'This application had no authentication and no
> authorization on any surface before this design was implemented.' Review this document to make
> sure such historic references are not present. Keep the design doc concise."*

Step 2 removed plan references but left a second class of the same defect: sentences that describe
**the system's history** rather than the system. A reference document states what is true. The
past-tense founding story belongs in the commits and in `plans/`, not here.

The rule for this step: **delete narration about how the system came to be.** State the present
fact, or say nothing.

#### 4a — Delete `## Current State` entirely

Lines 98–122: the `## Current State` heading, `### Before this design: no authentication existed`,
and `### Connector secrets were gated by a query parameter`, together with the separating `---`.

Every paragraph in it is history: the greps that returned no matches, `add_request_context` being
the only middleware, the absence of a user model, and the `include_secrets` query parameter. None
of it describes the system that exists. The live facts it contains are already stated elsewhere —
`include_secrets=true` is admin-only in the endpoint matrix, and the `Person` / `IdentityMapping`
distinction is stated in `### Per-person data scoping`.

**Preserve exactly one fact** by moving it to the top of `## Architecture`, as its first
paragraph, before `### Topology`:

> The implementation lives in `src/app/auth/` (`dependencies.py`, `matrix.py`, `principal.py`,
> `session_cookie.py`, `tokens.py`).

Do **not** carry over `src/app/api_main.py:157-180` — that citation belongs to the deleted
paragraph and is not needed once the paragraph is gone.

#### 4b — Rewrite the Overview's opening

Lines 12–14 currently open the document with the history:

> This application had **no authentication and no authorization on any surface** before this design
> was implemented. Every HTTP endpoint, every Dash callback, and every backing service was reachable
> by anyone who could reach the host.

Delete both sentences. The paragraph then continues *"Two roles are required: …"*, which needs a
subject. Replace the whole opening paragraph with:

> Identity is delegated to **Keycloak**, which this repository runs as part of its own Docker
> Compose stack. Authorization distinguishes a **read-only** role from an **admin** role.

Then rewrite the next paragraph, which is framed against the history (*"The design is not only
'add a login'. It moves the trust boundary."*), to state the position directly:

> The **API is the product**. Every frontend — Dash, or a React SPA or thick client in future —
> is an ordinary authenticated API client, and the presentation layer is physically separated
> from the API and stripped of database access. A frontend shortcut into the in-process service
> layer is a defect, not a path to guard.

**Then delete the third paragraph (lines 24–27) entirely** — it restates property 1 in the list
immediately below it, which is exactly the redundancy the ruling's *"keep the design doc concise"*
targets.

#### 4c — Rewrite the remaining history-relative sentences

| Line | Current | Change to |
|---|---|---|
| 241 | *"The application's Postgres service has no init scripts today, so this introduces one"* | *"The application's Postgres service has no init scripts, so this introduces one"* |
| 246 | *"A restore or reset of the application database now has the identity provider inside its failure domain."* | *"A restore or reset of the application database therefore includes the identity provider in its failure domain."* |
| 397 | *"The producers and the consumer call `/api/v1` over HTTP today, and a bearer-only API breaks them"* | *"The producers and the consumer call `/api/v1` over HTTP, and a bearer-only API breaks them"* |
| 534–535 | *"A request to the unauthenticated `POST /app/_dash-update-component` would otherwise reach them without touching `/api/v1`, so securing the API alone would leave these open."* | *"`POST /app/_dash-update-component` is unauthenticated and executes every server-side callback, so an in-process import here is a data path that bypasses the API entirely."* |
| 543 | *"All three are pure shortcuts over HTTP endpoints that already existed."* | *"Each is a shortcut over an HTTP endpoint that already exists."* |
| 545 | *"so an equivalent in-process shortcut cannot reappear."* | *"so an in-process shortcut cannot be reintroduced."* |
| 585–588 | *"This is a **decision, not an oversight**. The routes were unreachable for a period by accident rather than by design: nginx routes only `/api` and `/app`, and the API publishes no host port, so the API's own root paths had no browser-facing URL. Exposing them restores a developer affordance lost in that transition."* | *"This is a **decision, not an oversight**. They expose the API schema, not data: every operation still requires a bearer, and the schema reveals no credential. They are developer-local tooling and the only browser-based way to exercise a bearer-only API."* |
| 594–596 | *"not an exemption from it. **Deliberately public.** These routes were reconsidered and deliberately left unauthenticated. They expose the API schema, not data: every operation still requires a bearer, and the schema reveals no credential. They are developer-local tooling and the only browser-based way to exercise a bearer-only API."* | *"not an exemption from it. The routes are public by decision, and `tests/test_nginx_docs_routes.py` and `tests/test_docs_endpoints_server.py` guard them."* |
| 680 | *"This is the single highest-value test in the change."* | *"This is the single highest-value test of the authorization model."* |
| 689 | `### Docker Compose (current)` | `### Docker Compose` |
| 755 | *"requires three things that do not exist today"* | *"requires three things that do not exist"* |
| 763 | *"all currently return global results."* | *"all return global results."* |

Note on the §5 rewrite: the paragraph at 585–588 and the first bullet at 594–596 overlap — both
would state that the routes are deliberately public and what they expose. Write the fact **once**,
in the paragraph, and leave the bullet to carry only its own point (*"**The full API schema is
public** to anyone who can reach `localhost:443`. That is acceptable for a developer-local
deployment; it is a deliberate exception to "the API is authorized", not an exemption from it."*).

Also tighten the `## Non-Goals` bullet at 63–65, which repeats itself:

> *"…requires a data model that does not exist, because a preference cannot be keyed by a subject
> before per-user ownership exists. There is no per-user configuration store, so the theme-authoring
> row in the endpoint matrix is admin-only; see the endpoint matrix."*

→ *"Per-user state — graph themes a user creates, and any future preferences — requires a per-user
ownership model that does not exist. The theme-authoring row in the endpoint matrix is therefore
admin-only."*

**Do not touch** *"already"* used as a present-state word rather than a history word — e.g. *"the
test suite already uses"* (`:382`), *"`fetch_runtime_snapshot` already falls back to env/defaults"*
(`:413`), *"A bearer already issued … remains valid"* (`:443`). Those are correct. The same goes
for the `--import-realm` create-only gotcha at 228–229, which describes current tooling behaviour.

#### 4d — Verify

Re-run the full Step 2d block (every value must still hold) plus:

```
grep -nE '\bCurrent State\b'                docs/design/authn-authz-design.md   # → no matches
grep -c '^## '                              docs/design/authn-authz-design.md   # → 15  (was 16)
grep -nE 'before this design|had no authentication|was implemented|by accident|reconsidered|restores a developer' docs/design/authn-authz-design.md   # → no matches
grep -nE 'today|currently|in the change'    docs/design/authn-authz-design.md   # → no matches
wc -l                                       docs/design/authn-authz-design.md   # → report (expect < 810)
```

The content-preservation counts are the guard: **matrix still 28 rows, Decision Summary still 14,
Configuration still 12.** Deleting history must not remove a fact.

Then re-run the Step 3 endpoint sweep (`missing from matrix: []`) — the only other gate that reads
this file.

> ### 🚦 MANUAL GATE 4 — concision
>
> Operator re-reads the document and confirms no sentence describes the system's history or
> evolution, and that nothing factual was lost with the `## Current State` section.

---

### Step 5: Fix the `## Non-API Surfaces` framing

Step 4 exposed a contradiction that Steps 2–4 created between a section heading and its own
content. It is small and self-contained.

`## Non-API Surfaces` opens with:

> Paths that reach the backend **without** passing through the secured API are inventoried below:

and its first entry is:

> ### 1. Application-internal bypasses
> Three Dash callbacks **reach** Neo4j and Elasticsearch **through `/api/v1`**…

The intro promises paths that avoid the API; §1's first sentence says the opposite. §1 is not an
instance of what the section says it inventories, and its heading names a bypass that the
paragraph then says does not exist. (Before Step 2 this was coherent — §1 read *"used to reach …
All three are now resolved"*, a record of a closed bypass. That record was history, and removing
the history left the heading and the intro stranded.)

**Edit 1 — the `## Non-API Surfaces` intro.** Replace the single intro sentence with:

> The secured API is not the only surface. The app's own callback path, the backing services it
> exposes, the browser-side callbacks, and the deliberately public documentation routes are
> inventoried below, with how each is handled.

**Edit 2 — retitle §1 and rewrite its opening.** Change the heading to:

> ### 1. Data-store access from the UI

Replace the section's opening paragraph (currently *"Three Dash callbacks reach Neo4j and
Elasticsearch through `/api/v1`, by calling `ui.api_client` rather than importing the API's own
service functions. `POST /app/_dash-update-component` is unauthenticated and executes every
server-side callback, so an in-process import here is a data path that bypasses the API
entirely."*) with:

> Three Dash callbacks need data from Neo4j or Elasticsearch. Each calls `ui.api_client`, which
> goes over `/api/v1`, rather than importing the API's own service functions — the API is the only
> path to a data store. `POST /app/_dash-update-component` is unauthenticated and executes every
> server-side callback, so an in-process import there would bypass the API entirely; the container
> split is what prevents it: the UI image carries neither a database driver nor a data-store
> client.

Then **delete the now-redundant sentence** immediately after the table — *"Each is a shortcut over
an HTTP endpoint that already exists. The isolation is enforced by the container split: the UI
image carries neither a database driver nor a data-store client, so an in-process shortcut cannot
be reintroduced."* — because both of its claims have just been made in the opening. **Keep the
table** (it is the evidence for which endpoint each callback uses) and **keep** the
`CONNECTOR_REGISTRY` paragraph that follows, tightening only its last clause:

> That is a hardcoded dict, not a data path — a coupling to note, not a bypass.

**Do not touch §2, §3, §4 or §5.** Their headings and content agree with themselves.

**Verify**:

```
grep -n 'Application-internal bypasses' docs/design/authn-authz-design.md   # → no matches
grep -n 'Data-store access from the UI' docs/design/authn-authz-design.md   # → 1
grep -c 'cannot be reintroduced'        docs/design/authn-authz-design.md   # → 0 (folded into the opening)
grep -cE '^## '                         docs/design/authn-authz-design.md   # → 15 (unchanged)
sed -n '/^| Feature | Endpoint/,/^$/p' docs/design/authn-authz-design.md | grep -c '^|'   # → 28 (unchanged)
```

Then re-run the Step 3 endpoint sweep (`missing from matrix: []`) and re-run the full Step 2d
grep block. Nothing factual may change: this step renames and reframes only.

> ### 🚦 MANUAL GATE 5
>
> Operator confirms the `## Non-API Surfaces` intro, §1's heading, and §1's content now agree with
> one another, and that the three-callback table is still present.

---

### Step 6: Remove `## Non-Goals`

**Operator ruling, 2026-11-03:** *"The entire Non Goals section can be removed. Its not adding
value."*

#### 6a — Delete the section

Delete, in full:

- the `## Non-Goals` heading
- the intro line *"Explicitly **out of scope** for this design, recorded so they are decisions
  rather than omissions:"*
- all ten bullets
- the `---` rule that closes the section

Leave exactly one `---` between `## Overview` and `## Decision Summary`. Do not delete the `---`
that terminates `## Decision Summary` itself. **Change nothing else in the document.**

No other file — and no section within this document — links to `#non-goals`
(`grep -n 'non-goals\|Non-Goals' docs/design/authn-authz-design.md` returns only the heading, and
no other file under `docs/` references it). Nothing needs re-pointing.

#### 6b — Content that leaves with the section

Verified before deleting: nine of the ten bullets restate content stated elsewhere —

| Bullet | Also stated in |
|---|---|
| Per-person data scoping | `## Future Considerations` → `### Per-person data scoping` |
| Back-channel logout | `## Future Considerations` → `### Back-channel logout` |
| Host-exposed infrastructure ports | `## Non-API Surfaces` §2 and §3 |
| TLS termination | `## Deployment Topologies` → `### Docker Compose` |
| UI/API runtime split | `## Overview` property 1 |
| Per-user configuration storage | the endpoint-matrix note under `### Endpoint matrix` |
| MCP (outbound OAuth) | `## Future Considerations` → `### MCP as a resource server` |
| API Gateway specifics | `## Deployment Topologies` → `### AWS API Gateway + ECS (target)` |

**One bullet is unique to this section:** *"Multi-tenancy. No tenant scoping of any kind."* No
other section states it. It is deleted with the rest, per the ruling. If the operator wants the
boundary recorded, it belongs as a sentence in `## Overview` — **do not add it anywhere
unprompted.**

#### 6c — Verify

```
grep -cE '^## Non-Goals'                 docs/design/authn-authz-design.md   # → 0
grep -n 'Non-Goals\|non-goals'           docs/design/authn-authz-design.md   # → no matches
grep -cE '^## '                          docs/design/authn-authz-design.md   # → 14  (was 15)
grep -c '^---$'                          docs/design/authn-authz-design.md   # → report; no two may be adjacent
grep -c 'multi-tenancy\|Multi-tenancy'   docs/design/authn-authz-design.md   # → 0 (expected; see 6b)

# nothing else may move
sed -n '/^| Feature | Endpoint/,/^$/p' docs/design/authn-authz-design.md | grep -c '^|'   # → 28
sed -n '/^## Decision Summary/,/^---/p' docs/design/authn-authz-design.md | grep -c '^| [0-9]'   # → 14
sed -n '/^## Configuration/,/^---/p' docs/design/authn-authz-design.md | grep -c '^| `'   # → 12
grep -c 'graph-themes'                   docs/design/authn-authz-design.md   # → 2
grep -c 'at most 15 minutes'             docs/design/authn-authz-design.md   # → 1
grep -c 'KEYCLOAK_INTERNAL_URL'          docs/design/authn-authz-design.md   # → 3
grep -ciE '\bplans?\b'                   docs/design/authn-authz-design.md   # → 0
wc -l                                    docs/design/authn-authz-design.md   # → report (expect ≈ 763)
```

Then re-run the anchor check (all 3 internal links must still resolve — the section being deleted
is not a link target, so this must pass unchanged) and the Step 3 endpoint sweep
(`missing from matrix: []`).

> ### 🚦 MANUAL GATE 6
>
> Operator confirms `## Non-Goals` is gone, the document flows `## Overview` → `## Decision
> Summary`, and nothing else changed.

---

## Test plan

Documentation only — no new tests. The verification is the grep set in Step 2d, the
citation check, the endpoint sweep in Step 3, and the full regression suite, which
proves no code changed. There is **no behavioural test for any of this**: the
document has no executable check against the code beyond the Step 3 sweep, so the
sweep is the plan's only real guard on correctness of content. Treat a non-empty
sweep as a genuine failure.

## Done criteria

- [ ] `grep -ciE '\bplans?\b' docs/design/authn-authz-design.md` → `0`
- [ ] `grep -cE '\bPlan [A-F]\b' docs/design/authn-authz-design.md` → `0`
- [ ] `grep -cE '\(0[0-9]{2}\)' docs/design/authn-authz-design.md` → `0`
- [ ] `## Implementation Plans` and `## Plan B Scope` are both gone (`grep -n` → no matches)
- [ ] `grep -n 'dash_app' docs/design/authn-authz-design.md` → no matches
- [ ] `##` section count is **16** (was 18)
- [ ] Endpoint matrix `|` rows still **28**; Decision Summary rows still **14**; Configuration rows still **12**
- [ ] Endpoint-matrix service-column cells unchanged (`git diff` shows no `✓ → ✗` in column 4 of the endpoint matrix)
- [ ] Decision Summary row 9 no longer claims implemented per-user catalog favourites
- [ ] The `auth_session` refresh-token sentence states the Fernet/`CONNECTOR_ENCRYPTION_KEY` fact, not *"the plan will decide"*
- [ ] Step 1's corrections all survive (the Step 2d "corrections survive" block passes)
- [ ] Every path citation resolves; the citation script prints `missing: []`
- [ ] The Step 3 endpoint sweep prints `missing from matrix: []`
- [ ] `pytest -m unit tests -q` unchanged, 0 fail; `mypy` exit 0; `pylint` ≥ 9.0; `bandit` exit 0
- [ ] No source file modified: `git status --short` shows only documentation
- [ ] `plans/README.md` status row updated by the reviewer

## STOP conditions

Stop and report if:

- It is impossible to state a fact without a plan reference — i.e. the sentence has
  no content other than *when* something was done. Report it; the sentence should
  probably be deleted, and that is the operator's call.
- A section deletion appears to remove information that no other section carries.
  Report what would be lost rather than preserving it silently.
- The design document and `src/app/auth/matrix.py` disagree on a role and the code
  appears to be the wrong side. Doc changes must not paper over a code defect.
  **This includes the service column.**
- A path citation cannot be resolved to a real file and the correct path is not
  obvious — report it rather than guessing.
- `.github/copilot-instructions.md` is **not** a symlink.

## Maintenance notes

- **The document is a reference, not a record.** Future changes to the auth system
  edit it in place, in the present tense. Do not add plan numbers, revision
  histories, or "was previously" notes; that history belongs in `plans/`, which is
  deliberately ephemeral (`plans/README.md:16`).
- **The endpoint matrix is a copy of `src/app/auth/matrix.py`.** When a route's
  role changes, both change. `tests/test_authz_matrix.py` guards the code side;
  nothing guards the document side, which is why Step 3's consistency sweep exists.
  Its original regex only matched a backtick immediately before `/api` and so
  skipped every table cell; keep the method-prefix-tolerant version.
- **`graph_themes` vs `graph-themes`**: the Python module and DB table use the
  underscore, the HTTP path uses the hyphen. Check
  `src/app/api/graph_themes/v1/router.py`'s prefix rather than copying an existing
  row.
- **Not yet implemented, and documented as such**: per-user catalog favourites
  (`CatalogMetadata` has no `subject` column), user-writable theme authoring
  (`graph_themes` has no owner column), per-person data scoping, and hardening of
  the host-exposed infrastructure ports. When any of these lands, update the
  affected sections — the document states the gap, so it must also state the
  closure.
- **A reviewer should scrutinize**: that the revocation bound and the two
  cookie-authenticated endpoints are stated honestly, not glossed — and, for this
  rewrite, that no fact was dropped along with the plan scaffolding.

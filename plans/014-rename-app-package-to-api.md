# Plan 014: Rename the `app` package to `api`

> **Executor instructions**: This plan is **four steps**. Step 1 is the rename and
> is atomic — the tree does not import until every file in it is edited, so do not
> stop halfway through it. Step 2 is a browser gate. Step 3 fixes documentation
> references that are *already* wrong, independent of this rename. Step 4 is the
> closing command gate. Do one step, run its commands, report its measurements,
> then **STOP**. The operator reviews that step and replies before you start the
> next one. **Do not start the next step on your own initiative.**
>
> **Drift check (run first)**:
> `git diff --stat 5143c4cf..HEAD -- src/app mypy.ini .bandit.yml .dockerignore Dockerfile.api pytest.ini .github/workflows/pr_checks.yml docs/design`
> If any in-scope file changed since `5143c4cf`, compare the "Current state"
> excerpts against the live code before proceeding; on a mismatch, treat it as a
> STOP condition.
>
> When the whole plan is done, update the status row for this plan in
> `plans/README.md` — unless a reviewer dispatched you and told you they maintain
> the index.

## Status

- **Priority**: P3
- **Effort**: M (one wide mechanical step, one browser step, one docs step, one command step)
- **Risk**: MED — Step 1 is a ~500-import rename, plus strings and paths, that cannot be partially applied
- **Depends on**: none
- **Category**: tech-debt (naming / developer navigation)
- **Planned at**: commit `5143c4cf`, 2026-11-27

### Progress

| Step | Scope | Status |
|---|---|---|
| 1 | Rename `src/app` → `src/api` and rewrite every import, string, path and runtime reference | TODO |
| 2 | Browser gate: the app boots and every page renders | TODO |
| 3 | Fix the stale `src/app/dash_app/*` documentation references | TODO |
| 4 | Lint/type/security/doc gates | TODO |

## Why this matters

Every other container's source directory is named after the thing it serves.
`src/ui` is the Dash UI served by `Dockerfile.ui` as the compose service `ui`.
`src/connectors` backs the four producer/consumer services. But the FastAPI
service is `api` in the compose file, `Dockerfile.api` on disk, and `wba_api` as
an nginx upstream — while its source directory is `src/app` and its import
package is `app.*`. Three of the four names for one service agree; the fourth is
the one a developer actually types.

The mismatch has a second cost beyond navigation. `src/app/` contains a
subdirectory also called `api/` (the router tree), so the API service's router
imports are spelled `app.api.graph.v1.router`. After the rename they become
`api.api.graph.v1.router` — which is honest about what it is, even if it reads
awkwardly. The alternative (flattening the `v1` level, or renaming the inner
package) is deliberately **out of scope**: `src/app/api/auth/` and `src/app/auth/`
both exist and would collide if the router tree were flattened, and no `v2` is
planned, so the `v1` level is a separate decision with its own blast radius.

### What this rename does and does not cover

| Directory | Container(s) | Renamed? |
|---|---|---|
| `src/app` → `src/api` | `api` | **yes** |
| `src/ui` | `ui` | no — already correct |
| `src/connectors` | `github-producer`, `jira-producer`, `confluence-producer`, `signal-consumer` | no — one source layer backs four containers by design |
| `src/common` | all six app images | no — shared layer |
| `src/domain` | `api`, `ui` | no — shared pure-logic layer |

The `src/connectors` decision is deliberate: the four services share
`connectors/commons/` and `connectors/neo4j_db/`, so per-container directories
would either duplicate that code four ways or cross-import between siblings.

## Current state

The Dockerfile for the API copies the package to a directory literally named
`app` and the entrypoint changes into `app/` to run Alembic:

```dockerfile
COPY src/app/ ./app/
COPY src/common/ ./common/
COPY src/domain/ ./domain/
```

```bash
cd /app/app && alembic upgrade head
```

`alembic.ini` sits beside the package and resolves it by walking up one level:

```ini
script_location = %(here)s/alembic
prepend_sys_path = ..
```

Nothing about this is broken today. The rename changes the directory name and the
import name; the *relative* relationship between `alembic.ini` and the package it
sits in does not change, so `prepend_sys_path = ..` stays correct.

## Step 1 — Rename the package

**This step is atomic.** The repository does not import until all of the edits
below are complete. Run the whole step, then the step's checks, then report.

### 1a. Move the directory

```bash
git mv src/app src/api
```

Use `git mv`, not `mv`, so the history follows the files.

### 1b. Rewrite Python imports

**The rewrite must be line-anchored to import statements.** A word-boundary
pattern such as `(^|[^A-Za-z0-9_.])app\.` is **not** sufficient: it also matches
every attribute access on a Dash or FastAPI instance, because `app = FastAPI(...)`
is the only form it is guaranteed to spare. Applied to this tree it rewrites
**180 wrong lines across 63 files** — `app.include_router` (×13) and
`@app.middleware` in `src/api/api_main.py`, `app.title` / `app.layout` /
`@app.callback` (×6) in `src/ui/layout.py`, `app.dependency_overrides` in
`tests/conftest.py`, `app.callback_map` in
`tests/test_layout_callback_registration.py`, `app.clientside_callback` in
`src/ui/components/permission_errors.py`, `server = app.server` in
`src/ui_main.py`, and `@app.post` / `@app.get` in `scripts/temp_stream_server.py`.

Anchor every substitution at the start of a statement instead:

```bash
grep -rlE '^[[:space:]]*(from|import) app(\.|[[:space:]]|$)' src tests scripts simulation --include='*.py' \
  | xargs sed -i -E \
    -e 's/^([[:space:]]*)from app\./\1from api./' \
    -e 's/^([[:space:]]*)from app import/\1from api import/' \
    -e 's/^([[:space:]]*)import app\./\1import api./'
```

That covers 501 import lines across `src/`, `tests/`, `scripts/` and
`simulation/`.

`simulation/` is included in the sweep for completeness only — it holds 17 Python
files and **zero** `app.*` imports, so it contributes no edits. Leave it in the
target list: a future simulation script that does import the API should be
renamed by this same sweep rather than silently missed.

Three references sit **mid-line** — prose, comments and docstrings — so no
line-anchored pattern reaches them, and none is a functional break. Fix them by
hand in this step; do not write a sweep for prose:

```
src/app/analytics/collaboration/ego.py:27         # ``from app.analytics.collaboration.ego import ...`` call sites
tests/test_activity_api_integration.py:277        # The router imports get_async_db from app.db.session — override that.
tests/conftest.py:76                              ``... does not import app.api_main at collection time — ...``
```

`tests/conftest.py:76` is the one to catch: it is a docstring inside the fixture
that also holds the rename targets below, so it is easy to edit around and
leave stale.

Note what this step does **not** cover, so you do not assume it is exhaustive:
it rewrites `from`/`import` statements at line start. Mid-line references
(above), quoted strings (1c) and filesystem paths (1d, 1f) are separate.

**Verify the FastAPI instance, the Dash instance and every monkeypatch target
survived.** None of these may be renamed:

```bash
grep -c "app = FastAPI" src/api/api_main.py            # expect 1
grep -c "app.include_router" src/api/api_main.py       # expect 13
grep -rn "app\.dependency_overrides" tests | wc -l     # expect 19
grep -c "app\.clientside_callback" src/ui/components/permission_errors.py  # expect 1
grep -c "@app.callback" src/ui/layout.py               # expect 6
grep -c "server = app.server" src/ui_main.py           # expect 1
grep -c "app\.dependency_overrides" tests/conftest.py  # expect 3
```

If any of those counts is zero, the blanket sweep was used — restore the file
with `git checkout -- <file>` and re-run the anchored commands above.

### 1c. Rewrite quoted string references

Mock patch targets are strings, so no import-anchored pattern reaches them.
There are **41** double-quoted package references in **seven** test modules —
not six in two:

| File | Occurrences |
|---|---|
| `tests/test_graph_themes_service.py` | 22 |
| `tests/test_scheduler.py` | 7 |
| `tests/test_mcp_test_connection.py` | 5 |
| `tests/test_commands_api.py` | 3 |
| `tests/test_admin_users_api.py` | 2 |
| `tests/test_collaboration_query_loader.py` | 1 |
| `tests/test_graph_driver_singleton.py` | 1 |

They appear as `patch("app.scheduler.CONNECTOR_REGISTRY", …)`,
`patch("app.api.graph_themes.v1.service.qry.<fn>")`,
`monkeypatch.setattr("app.common.neo4j_driver.GraphDatabase", …)` and similar.
All 41 are double-quoted; there are **zero** single-quoted `'app.…'` package
references in the tree, so a double-quote-anchored strip is exact:

```bash
grep -rlE '"app\.[a-zA-Z_]' tests --include='*.py' | xargs sed -i -E 's/"app\./"api./g'
```

Missing these fails roughly 40 unit tests with `ModuleNotFoundError: No module
named 'app'` — and Step 1's own import check still reports 0, because these are
indented string literals.

**Check**: `grep -rnE '"app\.[a-zA-Z_]' tests src scripts simulation --include='*.py' | wc -l` → 0

### 1d. Rewrite the runtime path references

The API container reaches its own package by hardcoded path in **two** files,
and there are **seven** such references — not the two a `cd /app/app` and
`COPY src/app/` replacement covers. Each one left behind stops the container
from starting:

| File | Line | Content | Covered by the commands below? |
|---|---|---|---|
| `src/api/entrypoint.sh` | 15 | `cd /app/app && alembic upgrade head` | yes |
| `src/api/entrypoint.sh` | 20 | `cd /app && python app/scripts/init_rabbitmq.py` | yes |
| `src/api/entrypoint.sh` | 25 | `cd /app && python app/scripts/create_neo4j_indexes.py` | yes |
| `src/api/entrypoint.sh` | 30 | `cd /app && python app/scripts/create_es_indexes.py` | yes |
| `src/api/entrypoint.sh` | 45 | `cd /app && uvicorn app.api_main:app --host 0.0.0.0 --port 8000 \` | yes |
| `Dockerfile.api` | 23 | `COPY src/app/ ./app/` | yes |
| `Dockerfile.api` | 59 | `ENTRYPOINT ["app/entrypoint.sh"]` | yes |

```bash
sed -i 's|/app/app && alembic|/app/api \&\& alembic|; s|app/scripts/|api/scripts/|g; s|uvicorn app\.api_main|uvicorn api.api_main|' src/api/entrypoint.sh
sed -i 's|COPY src/app/ ./app/|COPY src/api/ ./api/|; s|ENTRYPOINT \["app/entrypoint.sh"\]|ENTRYPOINT ["api/entrypoint.sh"]|' Dockerfile.api
sed -i 's|- src/app/alembic|- src/api/alembic|' .bandit.yml
sed -i -E 's|^app/(\*\*/)?|api/\1|; s|^app/\.|api/.|' .dockerignore
```

`ENTRYPOINT` is a Dockerfile instruction, so its path is relative to the
`WORKDIR /app` set earlier in the file. It must become `api/entrypoint.sh` —
**not** `/app/api/entrypoint.sh`. `docker-compose.yml` sets no `command:` for
the `api` service, so this instruction is the only thing that starts the
container; if it is left pointing at `app/entrypoint.sh` the container exits
before migrations run and every Step 2 route fails.

**Check**: `grep -nE 'app/scripts|app\.api_main|app/entrypoint|cd /app/app|COPY src/app' Dockerfile.api src/api/entrypoint.sh | wc -l` → 0

The `.dockerignore` rewrite keeps the file internally consistent. Those `app/`
rules match nothing today and will match nothing afterwards — the build context
is the repo root and the package is reached as `src/app/`, never `./app/` — so
this command is housekeeping, not a functional fix.

Then update the mypy per-module overrides in `mypy.ini`. Both sections are
**live**: `src/app/scripts/redrive_dlq.py` exists, `PYTHONPATH=src python -c
"import app.scripts.redrive_dlq"` resolves it, and `mypy` lists the section
under `unused section(s)` only for the two it does *not* apply
(`[mypy-ui.*]`, `[mypy-app.analytics.collaboration.algorithm]`). A mypy section
matches the module, not a symbol the module imports:

```ini
[mypy-app.scripts.redrive_dlq]              → [mypy-api.scripts.redrive_dlq]
[mypy-app.analytics.collaboration.algorithm] → [mypy-api.analytics.collaboration.algorithm]
```

Rename both. Do not delete either — removing a mypy override is a separate
decision.

`pytest.ini` needs **no change** — `pythonpath = src . tests` is relative to the
repository root, not to the package name. The CI `PYTHONPATH` in
`.github/workflows/pr_checks.yml` likewise needs no change.

### 1e. Check for references outside the patterns above

The `grep` in 1b is a source-file sweep. Before crossing this off, confirm
nothing else in the repository refers to the old name:

```bash
grep -rnE '(^|[^A-Za-z0-9_.])app\.(api|settings|ai_agent|auth|db|analytics|runtime_settings|scheduler|query_catalog|common|scripts)' \
  src tests scripts simulation docs/design CLAUDE.md DEVELOPER_QUICK_START.md Dockerfile.api deploy .bandit.yml mypy.ini
```

Every hit must be either a FastAPI-instance reference (`app.dependency_overrides`,
`app.api_main` used as a *variable* — there should be none of these) or a
documented path reference you are fixing in Step 3. Report any hit you do not
understand rather than guessing.

This pattern matches on a **dot** (`app.<module>`), so it cannot see references
spelled with a **slash** — `uvicorn app.api_main` is matched, but
`python app/scripts/…` and `ENTRYPOINT ["app/entrypoint.sh"]` are not. Those are
covered by 1d's table and its check; do not treat 1e as the exhaustive sweep.

### 1f. Fix the path literals that build the package path from components

Three `unit`-marked modules locate package files by joining string components,
so their path never contains `src/app` or `app.<module>` as a contiguous string.
No step above reaches them, and each breaks under the rename:

| File | Line | Current | New |
|---|---|---|---|
| `tests/test_auth_allowlist.py` | 25 | `Path(__file__).resolve().parent.parent / "src" / "app" / "api"` | `/ "src" / "api" / "api"` |
| `tests/test_auth_allowlist.py` | 80 | `{"src/app/api/auth/v1/router.py"}` | `{"src/api/api/auth/v1/router.py"}` |
| `tests/test_nginx_docs_routes.py` | 210 | `REPO_ROOT / "src" / "app" / "api_main.py"` | `/ "src" / "api" / "api_main.py"` |
| `tests/z_collab_validation/test_collaboration_layers.py` | 29–30 | `/ "src" / "app" / "analytics" / …` | `/ "src" / "api" / "analytics" / …` |

Edit these **by hand** — four lines, each a one-off. A regex over them risks a
partial match, and the `src/api/api/…` doubleness on the first two is correct
and expected (service directory `api`, router package `api`).

What breaks if they are missed:

- `test_auth_allowlist.py` — `_API_ROOT.rglob("*.py")` finds nothing, so
  `_files_reading_the_session_cookie()` returns an empty set and the assertion
  fails with `unexpected files reading the session cookie: []`. That reads as a
  security regression, not a rename leftover.
- `test_nginx_docs_routes.py` — `read_text()` on the missing path raises
  `FileNotFoundError`.
- `test_collaboration_layers.py` — `integration`/`neo4j` marked, so it is outside
  the Step 4 unit gate, but it is the same defect and
  `docs/design/collaboration-network-design.md` points readers at this directory.

A single-line path pattern misses the third file, which splits the join across
two physical lines. Match the components instead — both counts must reach zero:

```bash
grep -rn '/ "app"' tests --include='*.py' | wc -l    # 3 at plan time, expect 0
grep -rn '"src/app' tests --include='*.py' | wc -l   # 1 at plan time, expect 0
```

Do **not** widen this to a bare `grep -n '"app"' tests`: three unrelated modules
(`test_ui_auth.py`, `test_ui_session_guard_stale.py`, `test_stream_proxy.py`)
declare `@pytest.fixture(name="app")`, which is a fixture name and must be left
alone.

All three modules pass today (`pytest -m unit tests/test_auth_allowlist.py
tests/test_nginx_docs_routes.py -q` → 15 passed), so a red result here is the
rename's doing, not a pre-existing failure.

### Step 1 checks

```bash
# The package imports and the app object still builds
PYTHONPATH=src python -c "import api.api_main; print(api.api_main.app.title)"

# No stale import form survives. NOTE: the older pattern
#   '^\s*(from app\.|from app import|import app$)'
# reports 0 here even when 10 'import app.<mod> as <alias>' statements remain —
# it cannot match the alias form and it sees the error later as a collection
# failure. Use this selector, which matches all three forms:
grep -rnE '^[[:space:]]*(from|import) app(\.|[[:space:]]|$)' src tests scripts simulation --include='*.py' | wc -l   # expect 0

# The FastAPI instance is intact
grep -c "app = FastAPI" src/api/api_main.py   # expect 1

# No non-import 'app.' attribute access was rewritten (see 1b)
grep -c "app.include_router" src/api/api_main.py   # expect 13
grep -c "@app.callback" src/ui/layout.py           # expect 6
grep -rc "app\.dependency_overrides" tests/conftest.py  # expect 3

# The path literals are fixed (see 1f)
grep -rn '/ "app"' tests --include='*.py' | wc -l    # expect 0
grep -rn '"src/app' tests --include='*.py' | wc -l   # expect 0
```

If `import api.api_main` fails, do not advance — the rename is incomplete.

## Step 2 — Browser gate

Bring the stack up and confirm the rename did not break the running application.
The image must be **rebuilt and the container recreated**, not just rebuilt —
`docker compose build` alone leaves the old container serving the old code.

```bash
docker compose build api && docker compose up -d --force-recreate api
docker compose logs api --tail 50      # expect: migrations complete, no ImportError
```

Confirm the entrypoint's Alembic path resolved by checking the log line rather
than assuming. Then walk these, and report what you saw for each:

| Route | Expect |
|---|---|
| `https://localhost/api/health` | 200 |
| `https://localhost/docs` | Swagger UI renders |
| `https://localhost/app/` | Chat page renders |
| `https://localhost/app/analytics` | Analytics cards render |
| `https://localhost/app/graph` | Graph page renders, catalog tab loads |
| `https://localhost/app/connectors` | Connector table renders |
| `https://localhost/app/settings` | Settings page renders |

The API and UI are separate services; the UI reaching the API over
`http://api:8000` is what a broken rename would most likely break, so open at
least one page that performs a callback (Graph's catalog tab) rather than only
checking that HTML is served.

## Step 3 — Fix the stale documentation references

This step is **independent of the rename** and fixes references that are wrong
today: **22** occurrences across `docs/design/` and the root Markdown files point
at a `dash_app` package that no longer exists — the UI moved to `src/ui`. (One
further `dash_app` hit is `` `create_dash_app()` `` in `CLAUDE.md`, which is
correct current text; leave it alone.)

These are real defects. `docs/design/frontend-design-skill.md` names
`src/app/dash_app/pages/library/` as *the reference implementation* for new pages;
`src/ui/pages/library` does not exist either. `docs/design/collaboration-network-design.md`
points at `src/app/dash_app/analytics/…` for the tuning CLI. Anyone following these
paths lands nowhere.

Fix by **verifying each target exists** before writing it, then rewriting:

| Stale reference | Correct target |
|---|---|
| `src/app/dash_app/assets/executive-dashboard.css` | `src/ui/assets/executive-dashboard.css` |
| `src/app/dash_app/assets/stream-bridge.js` | `src/ui/assets/stream-bridge.js` |
| `src/app/dash_app/graph_styles.py` | `src/ui/graph_styles.py` |
| `src/app/dash_app/layout.py` | `src/ui/layout.py` |
| `src/app/dash_app/styles.py` | `src/ui/styles.py` |
| `src/app/dash_app/pages/analytics.py` | `src/ui/pages/analytics.py` |
| `src/app/dash_app/pages/settings.py` | `src/ui/pages/settings/` |
| `src/app/dash_app/pages/settings/graph_styling/` | `src/ui/pages/settings/graph_styling/` |
| `src/app/dash_app/pages/collaboration_network/` | `src/ui/pages/collaboration_network/` |
| `src/app/dash_app/pages/collaboration_network_ego/` | `src/ui/pages/collaboration_network_ego/` |
| `src/app/dash_app/pages/timeline/` | `src/ui/pages/timeline/` |
| `src/app/dash_app/pages/graph/utils/graph_operations.py` | `src/ui/pages/graph/utils/graph_operations.py` (file confirmed to exist) |
| `src/app/dash_app/pages/library/` | `src/ui/pages/catalog/` — this is the page the passage describes: `catalog/layout.py` declares `dcc.Store(id="library-store")` and `catalog/callbacks.py` builds the rows clientside with `tbody.innerHTML = rows.join('')` |
| `src/app/common/graph_theme.py` | `src/domain/graph_theme.py` |
| `src/app/common/node_size.py` | `src/domain/node_size.py` |
| `src/app/common/person_network_url.py` | `src/domain/person_network_url.py` |

The last three are also pre-existing drift: those modules live in `src/domain/`
now, not in a `common` package under the API.

**Order matters — do the table above before this sweep.** The table's rows are
the exceptions: `src/app/dash_app/…` belongs under `src/ui/`, and
`src/app/common/{graph_theme,node_size,person_network_url}.py` belong under
`src/domain/`. The sweep below rewrites every `src/app` to `src/api`
indiscriminately, so running it first turns those rows into
`src/api/dash_app/…` and `src/api/common/…` — the table's stale patterns no
longer match the text, and you are left with references that are wrong twice
over. Hand-edit the table first, then sweep what remains:

```bash
grep -rl "src/app" docs/design *.md | xargs sed -i 's|src/app|src/api|g'
```

**The path sweep alone is not sufficient.** The root Markdown files also contain
`app.*` *import examples*, which the `src/app` substitution cannot match. In
`CLAUDE.md`:

```
76:  from app.settings import settings         # the API → src/app/
77:  from app.ai_agent.providers import get_provider
94:  src/app/         FastAPI API (imported as app.*)
138: from app.ai_agent.providers import get_provider
161: `app.settings.settings` — pydantic-settings from `.env` (startup config)
224: Loaded from `.env` (see `.env.example`) via `app.settings`. Key variables:
243: `app.settings` singleton (`.env` at startup), not from `runtime_settings`
```

Line 94 is the one that states the import convention outright — leaving it would
document the old name as the rule. After the path sweep, update these by hand:
each `app.<module>` in prose or a code fence becomes `api.<module>`, and the
`# the API → src/app/` comment on line 76 becomes `src/api/`.

Three more references sit outside that pattern and outside the `src/app`
substitution, so they need hand edits as well.

```
DEVELOPER_QUICK_START.md:166  PYTHONPATH=src uvicorn app.api_main:app --reload
DEVELOPER_QUICK_START.md:199  PYTHONPATH=src uvicorn app.api_main:app --reload
```

Both become `uvicorn api.api_main:app`. They are shell command lines: they carry
no backtick before `app.` and no `from`, so the import-example grep below does
not see them, and they carry no `src/app`, so the path sweep does not either.

The third has no `src/` prefix at all and is likewise invisible to the path
sweep — it is inside an ASCII diagram in
`docs/design/runtime-settings-design.md`:

```
                                   │ app/dash_app/    │
                                   │ pages/settings   │
                                   │ .py (category)   │  ← Step 7 (if new cat)
```

It labels the Dash settings page, so rewrite the box to the UI location rather
than to `api/`. `grep -rn "src/app" docs/design` will not find it; Step 3's
`dash_app` check will.

**In-scope root Markdown files** (the `*.md` glob in the command above):

| File | Action |
|---|---|
| `CLAUDE.md` | **Yes** — 19 `src/app` path refs plus the 7 import examples above |
| `DEVELOPER_QUICK_START.md` | **Yes** — `cd src/app` at line 180, plus the two `uvicorn app.api_main:app` command lines above, plus `cd app && alembic revision …` at line 186 (container-internal, becomes `cd api && …`) |
| `AGENTS.md` | No — a 295-byte pointer that sends readers to `CLAUDE.md`; edit `CLAUDE.md` only |
| `README.md`, `INSTALL_GUIDE.md`, `IAM_ADMIN_GUIDE.md`, `user-faq.md` | No — verified to contain no `src/app` or `app.*` reference |

`CLAUDE.md` **must** be updated: it is the canonical project guide, it states
`src/app/ FastAPI API (imported as app.*)` as the import convention, and
`.github/copilot-instructions.md` is a symlink to it — so an un-updated
`CLAUDE.md` would feed the stale name to GitHub Copilot as well. Edit `CLAUDE.md`
in place; never re-create the Copilot file.

`docs/project-plan/` is a **dated implementation record** and is deliberately out
of scope — do not rewrite it. Existing plans under `plans/` are also out of scope.

### Step 3 check

```bash
grep -rn "src/app" docs/design *.md | wc -l        # 84 at plan time, expect 0
grep -rn "create_dash_app" docs/design *.md | wc -l         # must stay >= 1 (correct text, never rename this)
grep -rnE '(^|[^_])dash_app' docs/design *.md | wc -l        # 22 stale refs to remove, expect 0
grep -rnE '`app\.[a-z_]+|from app\.|uvicorn app\.' CLAUDE.md DEVELOPER_QUICK_START.md | wc -l   # 7 at plan time, expect 0
```

The `dash_app` gate is deliberately **not** a bare `grep "dash_app"`. `CLAUDE.md`
contains `` `create_dash_app()` ``, a substring match on `dash_app` that is
correct text describing the current factory function — a bare count can never
reach zero without mangling it. `(^|[^_])dash_app` excludes it, leaving the 22
genuine stale references (which are written as bare `dash_app/…` or
`app/dash_app`, never with an underscore before them — verified). This matches
`app/dash_app` and `` `dash_app/components/` `` alike, so the one reference with
no `src/` prefix is included.

## Step 4 — Closing gates

```bash
PYTHONPATH=src python scripts/generate_signal_activity_spec.py
git diff --exit-code docs/design/spec-activity-signal.md   # expect no diff (the generator imports common.*, not app.*)

pytest -m unit tests -q
mypy src/
pylint src --score=y
bandit -c .bandit.yml -r src/ -lll
```

All must be green. `pylint` must stay **≥ 10.0**.

**`flake8` is deliberately not in this list.** It is not a CI gate
(`.github/workflows/pr_checks.yml` runs pytest, mypy, pylint, bandit and the
spec-freshness check) and it is far from clean at plan time — **1977 findings,
1129 of them under `src/`**, none of which this rename touches. Requiring it
green would either fail on unrelated pre-existing debt or invite reflowing
unrelated lines into a rename diff. If you run it, record the count before and
after; an unchanged count is the pass condition, and pre-existing findings must
be left alone.

If the spec-freshness check
produces a diff, that is unexpected for this change — report it rather than
committing the regenerated file.

Report the final counts:

```bash
grep -rnE '^[[:space:]]*(from|import) app(\.|[[:space:]]|$)' src tests scripts simulation --include='*.py' | wc -l   # 0
grep -rnE '"app\.[a-zA-Z_]' tests src scripts simulation --include='*.py' | wc -l   # 0
grep -rn '/ "app"' tests --include='*.py' | wc -l    # 0
grep -rn "src/app" docs/design *.md | wc -l   # 0
grep -rnE '(^|[^_])dash_app' docs/design *.md | wc -l   # 0
ls src/   # expect: api common connectors domain ui ui_main.py
```

## STOP conditions

Stop and report, without improvising, if any of these occur:

- `import api.api_main` fails and the cause is not a missed import rewrite.
- The Step 2 browser walk shows a page that renders but whose callbacks do nothing
  — that is the `suppress_callback_exceptions` silent-failure mode and points at a
  module that stopped importing.
- A `src/app` reference remains in a **code** file (`src/`, `tests/`, `scripts/`,
  `simulation/`, a Dockerfile, a config) after Step 1.
- `pylint` drops below 10.0.
- The unit suite fails in a way that does not reproduce before the rename.
- A test fails with `ModuleNotFoundError: No module named 'app'` — that is a
  missed quoted patch target (1c), not a broken rename. Check the seven modules
  listed there before concluding anything else.
- The API container exits immediately in Step 2 and the log shows the entrypoint
  itself is missing (rather than a migration or import error) — 1d's
  `ENTRYPOINT` line was not updated.
- A `unit` test fails on an empty set or a `FileNotFoundError` rather than an
  import error — that is a missed path literal (1f).

## Out of scope

Deliberately not part of this plan, each for a stated reason:

- **Flattening the `v1` level** in `src/api/api/<domain>/v1/`. `src/app/api/auth/`
  and `src/app/auth/` both exist, so a flatten produces a collision that needs its
  own resolution step.
- **Renaming the inner `api` router package** to remove the `api.api.*` doubleness.
  Same collision, same separate decision.
- **Merging `src/api/common/` into `src/common/`.** These are two different
  packages that happen to share a name — `app.common.encryption` /
  `app.common.neo4j_driver` are API-local, while `src/common/` is the cross-service
  layer. Worth a plan of its own; not this one.
- **Renaming `src/connectors`.** One source layer backs four containers by design.
- **`docs/project-plan/` and `plans/`.** Dated records; not rewritten.
- **`tests/app/`**, which holds a single `.txt` (`manual_questions.txt`) and mirrors
  no package. Left alone to keep this change to one concern.

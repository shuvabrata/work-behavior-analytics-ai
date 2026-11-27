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
> `git diff --stat 5143c4cf..HEAD -- src/app mypy.ini .bandit.yml .dockerignore Dockerfile.api pytest.ini .github/workflows/pr_checks.yml docs/design producer-development-guide.md`
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
- **Risk**: MED — Step 1 is a ~500-occurrence rename that cannot be partially applied
- **Depends on**: none
- **Category**: tech-debt (naming / developer navigation)
- **Planned at**: commit `5143c4cf`, 2026-11-27

### Progress

| Step | Scope | Status |
|---|---|---|
| 1 | Rename `src/app` → `src/api` and rewrite every import and path reference | TODO |
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

Two patterns cover every real import:

- `from app.` → `from api.` (491 occurrences across `src/`, `tests/`,
  `scripts/`, `simulation/`)
- `import app` → `import api`

Use a word-boundary-anchored match so a local variable or the FastAPI instance
named `app` is never touched:

```bash
grep -rlE '(^|[^A-Za-z0-9_.])app\.' src tests scripts simulation --include='*.py' \
  | xargs sed -i -E 's/(^|[^A-Za-z0-9_.])app\./\1api./g'
```

**Verify the FastAPI instance survived.** `src/api/api_main.py` binds
`app = FastAPI(...)` and calls `app.include_router(...)` / `@app.middleware(...)`;
`tests/conftest.py` and ten other test modules call `app.dependency_overrides`.
None of those may be renamed. `app = FastAPI` has no trailing `.` so the pattern
above cannot match it, but confirm explicitly:

```bash
grep -c "app = FastAPI" src/api/api_main.py            # expect 1
grep -c "app.include_router" src/api/api_main.py       # expect 12
grep -rn "app\.dependency_overrides" tests | wc -l     # expect non-zero, all still 'app.'
```

### 1c. Rewrite quoted string references

Mock patch targets are strings, so `sed` on the import form misses them. Six
occurrences in two files:

```
tests/test_collaboration_query_loader.py:33   "app.analytics.collaboration.queries_loader"
tests/test_mcp_test_connection.py:39,63,94,117,420  "app.ai_agent.mcp_integration.tool_executor.*"
```

```bash
sed -i -E 's/"app\./"api./g' tests/test_collaboration_query_loader.py tests/test_mcp_test_connection.py
```

### 1d. Rewrite the runtime path references

```bash
sed -i 's|cd /app/app && alembic upgrade head|cd /app/api \&\& alembic upgrade head|' src/api/entrypoint.sh
sed -i 's|COPY src/app/ ./app/|COPY src/api/ ./api/|' Dockerfile.api
sed -i 's|- src/app/alembic|- src/api/alembic|' .bandit.yml
sed -i -E 's|^app/(\*\*/)?|api/\1|; s|^app/\.|api/.|' .dockerignore
```

Then update the mypy per-module overrides in `mypy.ini` — the module paths change,
and one of them (`app.scripts.redrive_dlq`) is **already dead** because
`redrive_dlq.py` imports no such symbol; rename it anyway and note it in the
report rather than deleting it, since deleting a mypy override is a separate
decision:

```ini
[mypy-app.scripts.redrive_dlq]              → [mypy-api.scripts.redrive_dlq]
[mypy-app.analytics.collaboration.algorithm] → [mypy-api.analytics.collaboration.algorithm]
```

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

### Step 1 checks

```bash
# The package imports and the app object still builds
PYTHONPATH=src python -c "import api.api_main; print(api.api_main.app.title)"

# No stale import form survives
grep -rnE '^\s*(from app\.|from app import|import app$)' src tests scripts simulation --include='*.py' | wc -l   # expect 0

# The FastAPI instance is intact
grep -c "app = FastAPI" src/api/api_main.py   # expect 1
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
today: 20 occurrences across `docs/design/` and the root Markdown files point at
`src/app/dash_app/`, a package that no longer exists — the UI moved to `src/ui`.

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
| `src/app/dash_app/pages/graph/utils/graph_operations.py` | `src/ui/pages/graph/utils/` (confirm the file) |
| `src/app/dash_app/pages/library/` | **no such page** — `src/ui/pages/` has `catalog/`, `graph/`, `settings/`, `timeline/`, `connectors/`, `developer/`, `collaboration_network/`, `collaboration_network_ego/`. Determine which page actually carries the described clientside row-building callback and name that one |
| `src/app/common/graph_theme.py` | `src/domain/graph_theme.py` |
| `src/app/common/node_size.py` | `src/domain/node_size.py` |
| `src/app/common/person_network_url.py` | `src/domain/person_network_url.py` |

The last three are also pre-existing drift: those modules live in `src/domain/`
now, not in a `common` package under the API.

Then sweep every remaining `src/app` reference in `docs/design/` and the root
Markdown files to `src/api`:

```bash
grep -rl "src/app" docs/design *.md | xargs sed -i 's|src/app|src/api|g'
```

`docs/project-plan/` is a **dated implementation record** and is deliberately out
of scope — do not rewrite it. Existing plans under `plans/` are also out of scope.

### Step 3 check

```bash
grep -rn "src/app" docs/design *.md | wc -l        # expect 0
grep -rn "dash_app" docs/design *.md | wc -l       # expect 0
```

## Step 4 — Closing gates

```bash
PYTHONPATH=src python scripts/generate_signal_activity_spec.py
git diff --exit-code docs/design/spec-activity-signal.md   # expect no diff (the generator imports common.*, not app.*)

pytest -m unit tests -q
mypy src/
pylint src --score=y
bandit -c .bandit.yml -r src/ -lll
flake8
```

All must be green. `pylint` must stay **≥ 10.0**. If the spec-freshness check
produces a diff, that is unexpected for this change — report it rather than
committing the regenerated file.

Report the final counts:

```bash
grep -rnE '^\s*(from app\.|from app import|import app$)' src tests scripts simulation --include='*.py' | wc -l   # 0
grep -rn "src/app" docs/design *.md | wc -l   # 0
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

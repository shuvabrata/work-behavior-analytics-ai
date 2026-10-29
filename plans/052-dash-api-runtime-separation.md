# Plan 052 — Phase 4: client, audit, docs

> **This document covers Phase 4 only (Steps 10–14).** Phases 1–3 — the moves, the
> structural split and going live (Steps 1–9) — are **complete and
> operator-approved**, and their step text has been removed so this file contains
> only what the remaining work needs. A backup of the original 14-step plan holds
> the full history; the executed record is also in the Progress tracker below and
> in the git log.

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Every step ends with a MANUAL GATE.** After completing a step's automated
> verification, stop and hand back to the operator for a human check. Do not
> begin the next step until the operator replies `PASS`. If they reply `FAIL`,
> treat it as a STOP condition. Record each gate's outcome in the Progress
> tracker below before continuing.
>
> **Every step ends at a stable state — the stable-state rule.** After each step,
> `docker compose up -d --build` must come up healthy and the UI must be browsable
> at `https://localhost/app`. The operator rebuilds the stack after every step, so
> a step that leaves it unable to start is a defect in the step, not something to
> work around by running a stale image. **A step may only remove something when
> the same step makes its replacement real.**
>
> **The split is live and is the starting condition.** Phase 4 does not re-open
> any of it. Before starting, confirm the ground you are standing on:
>
> ```bash
> docker compose ps                        # api, ui, nginx, postgres, neo4j, rabbitmq, elasticsearch, github-mcp all healthy
> curl -sf https://localhost/api/health    # {"status":"healthy"}
> curl -sf -o /dev/null -w '%{http_code}' https://localhost/app/   # 200
> ```
>
> If any of those fail, STOP — the Phase 3 state has regressed and Phase 4's
> gates cannot mean anything on top of it.

## Status

- **Priority**: P1
- **Phases 1–3 (Steps 1–9)**: ✅ complete, operator-approved — see the Progress tracker
- **Remaining**: Phase 4 — Steps 10–14
- **Category**: architecture | security
- **Design reference**: `docs/design/authn-authz-design.md`, "Plan B Scope"
- **Baseline to hold**: `pytest -m unit tests -q` → **2365 passed, 0 failed, 2 skipped**;
  `mypy src/` exit 0; `pylint src --score=y` → **9.67**; `bandit` exit 0

## What Phase 4 is for

Phases 1–3 delivered **isolation**: the UI runtime holds no database driver, no
data-store credentials and no LLM provider key, and it reaches the API only over
HTTP. That property is physical — two images, two containers — and it is done.

Phase 4 delivers the **other** property, which is not the same one:

1. ~~**Isolation**~~ — the UI runtime cannot reach a database at all. **Delivered by Phases 1–3.**
2. **Adequacy** — the API exposes every capability the UI needs, so a different
   frontend could be built against it today. **Step 11's audit is what proves this.**

Plus two pieces of finishing work that only make sense once the split is real:
**one HTTP chokepoint** for every UI→API call (Step 10), a **concurrency
measurement** proving the split did not silently serialize callbacks (Step 12),
and **documentation** that no longer describes the pre-split world (Step 13).

Neither property authenticates anyone — Plan C (Keycloak) remains independently
necessary, and this plan deliberately carries no credentials.

### Explicit non-goals

- **The container split is not a substitute for authorizing the API.**
- **Renaming the `src/app/` package to `src/api/`** — deliberately deferred to a
  separate follow-on plan. It is cosmetic (238 files import `app.*`), carries no
  isolation gain, and this plan's test fallout is already its largest risk.
- **Per-user configuration, per-person data scoping, Keycloak, infrastructure
  hardening** — Plans D, F, C, E.

## Decisions that govern Phase 4

Carried forward from the planning interview; the Phase 1–3 decisions are settled
and recorded in the backup and the git log.

| # | Decision | Choice |
|---|---|---|
| 11 | Shared HTTP client | **All UI→API calls** go through `src/ui/api_client.py`. Step 7 migrated 3 (the collaboration and spotlight swaps, because it created the module for them); **Step 10 migrates the remaining 57**, for 60 in total |
| 14 | Local dev | **Two documented commands**, no `dev.sh` (deferred as out of scope) |
| 16 | Audit artifact | A **step in this plan**, not a long-lived doc. Three-way comparison, **discarded** once it passes |
| 17 | Design doc | **Edit `authn-authz-design.md` in Step 13** (4 sections), so Plan C is not written against a stale premise |
| 18 | Requirements | `requirements.api.txt` / `requirements.ui.txt`, each carrying only what its runtime needs; **CI installs both**. No automated dependency-absence check |

## Repo conventions that apply

- **Settings** are fields on the `ApiSettings` class in `src/app/settings.py`, with
  a sensible default and a comment. `DATABASE_URL` has **no default** — that is
  deliberate and is what makes `ApiSettings` unconstructable in the UI. The UI's
  credential-free base is `domain.settings.UISettings`.
- **Never `print()`** — use `from common.logger import logger`.
- **Type hints on all parameters and returns.** Built-in generics
  (`list[str]`, `dict[str, int]`), `X | None`. `mypy src/` runs **strict**.
- **Tests carry a marker.** `pytestmark = pytest.mark.unit` at module level, or a
  per-test decorator. Unmarked tests are **silently skipped** by `pytest -m unit tests`.
- **Commit messages** are plain imperative sentences, e.g.
  `Separate Dash and API into independent runtimes`. Not conventional-commit
  style (that is only for Dependabot bumps).
- **Do not commit, push, or open a PR** unless explicitly asked.
- Package `__init__.py` re-exports must be declared with `__all__` (mypy strict
  treats plain re-exports as private).

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Unit tests (CI gate) | `pytest -m unit tests -q` | **2365+** pass, 0 fail, exit 0 |
| Single test file | `pytest -m unit tests/test_<name>.py -q` | all pass |
| Typecheck (CI gate) | `mypy src/` | no errors, exit 0 |
| Lint (CI gate) | `pylint src --score=y` | score ≥ 9.0 |
| Security scan (CI gate) | `bandit -c .bandit.yml -r src/ -lll` | exit 0 |
| Compose config syntax | `docker compose config -q` | exit 0 |
| Nginx config syntax | `docker run --rm --network work-behavior-analytics-ai_wba-ai-network -v "$PWD/deploy/nginx/nginx.conf:/etc/nginx/nginx.conf:ro" -v "$PWD/deploy/certs:/etc/nginx/certs:ro" nginx:1.30-alpine nginx -t` | `syntax is ok`, `test is successful` |
| Full stack | `docker compose up -d` | all services healthy |
| Health over TLS | `curl -sf https://localhost/api/health` | `{"status":"healthy"}` |
| UI over TLS | `curl -sf -o /dev/null -w '%{http_code}' https://localhost/app/` | `200` |
| OpenAPI (container-internal only) | `docker compose exec -T api python -c "import json,urllib.request; print(len(json.load(urllib.request.urlopen('http://localhost:8000/openapi.json'))['paths']))"` | **`40`** (Step 7 added `/api/v1/search/scoped`) |

**Container and service names are `api` and `ui`** — the `app` name was retired in
Phase 3. Use `docker compose exec api …` / `docker compose exec ui …`, or the
container names `wba-ai-api` / `wba-ai-ui`. **The API publishes no host port**, so
`http://localhost:8000` is reachable only from inside the containers.

**Note on `curl`:** use the **no-`-k`** form. The mkcert CA is in the Linux trust
store, so strict TLS works on any machine that ran `mkcert -install`. The `-k`
form is blocked by the sandbox classifier in some harnesses.

**Note on `docker run` against these images:** both set an `ENTRYPOINT`, which
**hijacks the command** — `docker run --rm wba-api-test pip list` boots the
service instead of listing packages and then hangs. Always pass
`--entrypoint pip` (or `--entrypoint python`) for inspection, and clean up any
stray containers a bare invocation leaves behind.

Run Python commands with the virtualenv active (`source .venv/bin/activate`) and
`PYTHONPATH=src` where importing app code outside pytest. For Python hitting
`https://localhost`, export the mkcert CA (`SSL_CERT_FILE` **and**
`REQUESTS_CA_BUNDLE` = `$(mkcert -CAROOT)/rootCA.pem`); `curl` needs neither.

## Scope

**In scope (Phase 4):**

- `src/ui/api_client.py` — **extended** in Step 10 (it already exists from Step 7)
- The **57 remaining** UI→API call sites across **14** `src/ui/` files (Step 10's table)
- `tests/` — new tests for the client and the audit, and any stub repointed by a swap
- `CLAUDE.md`, `DEVELOPER_QUICK_START.md`, `USER_GUIDE.md`, `scripts/setup.sh`, `.env.example`
- `docs/design/authn-authz-design.md` — **the four sections in Step 13 only**
- The Step 11 audit artifact (**temporary** — discarded once it passes)
- `plans/README.md` — status row

**Out of scope** (do NOT touch, even though they look related):

- **Renaming `src/app/` → `src/api/`.** Its own follow-on plan. Every `app.*`
  import stays as-is.
- **Keycloak, `authn_session`, `AUTH_*` / `KEYCLOAK_*` settings, bearer tokens,
  the `/app/stream/<id>` proxy route.** Plan C's. This plan carries **no
  credentials** in `api_client.py` — Plan C teaches it to attach a token, which
  is why the two plans are not merged.
- **Anything Phase 1–3 built.** The split, the images, the compose topology, the
  nginx upstreams, the entrypoints and `src/domain/` are settled. Re-opening them
  is a STOP condition, not a refactor.
- **`src/connectors/`.** Producers and the consumer are unchanged by Phase 4.
- **FastAPI's `/docs`, `/redoc`, `/openapi.json` settings.** Unreachable over TLS
  as a Plan 051 side effect. `docs_url=None` is Plan E's decision.
- **`scripts/temp_stream_server.py`.** Plan E.
- **TLS for container-to-container traffic.** Internal traffic stays plain HTTP
  on the Docker bridge.
- **A `scripts/dev.sh`.** Considered and deferred (Decision 14). Two documented
  commands instead.

---

## Steps

### Phase 4 — Client, audit, docs

---

### Step 10: Grow `src/ui/api_client.py` and migrate all 57 call sites

**In this plan the client carries no credentials.** Plan C teaches it to attach a
bearer token — which is why the two plans are not merged.

**`api_client.py` already exists — Step 7 created it** (7d-i), and this step
**extends** it. Two things it established that this step must **not** change:

- **`ApiError`, the single transport-level type**, raised on every non-2xx and
  carrying `status_code`. Step 7 introduced it; this step's Gate 10 check 3 is
  the same requirement, not a new one.
- **The base URL and the timeout already live in the client**, so call sites pass
  a *path*, not a URL, and no timeout. Step 7's three call sites are already in
  that form — that is what makes this step additive rather than a rewrite.

**Do not move the collaboration translation into the client.** 7d-i deliberately
put the `404 + detail.error == "No collaboration data"` →
`CollaborationDataUnavailable` mapping in
`src/ui/collaboration_params.py:translate_api_error`, not in `api_client`, for
two reasons that still hold here: the client's single-type contract would break,
and the generic client must not depend on a collaboration-domain error
(`domain/collaboration/errors.py`). Keep `translate_api_error` where it is, and
keep `tests/test_ui_api_client_status_mapping.py` passing — it guards both halves
of that split. Adding a *second*, client-level mapping would re-break the collab
banners by making the call sites' `except ApiError` wrapper unreachable.

**Grow the client** into the single chokepoint for UI→API calls:

- Owns the base URL (from `UISettings.API_BASE_URL`) and the timeout (from
  `ui.runtime_settings`, read **per call** — never captured at import).
- Exposes `get`/`post`/`put`/`patch`/`delete` with a consistent signature,
  keeping 7d-i's `get_json`/`post_json` working (they are already used by three
  call sites — do not rename them out from under those).
- **One exception type** carrying `status_code` — `ApiError`, as established.
- **Accepts an injectable transport** (a `requests.Session` or a callable) so
  tests can stub the API without monkeypatching `requests` globally. With 47 test
  files touching the UI, that matters. 7d-iii's test already relies on this being
  injectable, so the seam exists from Step 7.

**Migrate the remaining 57 sites across these 14 files.** Head-weighted:

Step 7 already migrated **3** sites (the two collab callbacks and the spotlight)
in 3 other files; those are not in this list and must not be touched again. The
end state is **60** UI→API sites, all through `api_client`.

| File | Sites |
|---|---|
| `pages/connectors/callbacks.py` | 17 |
| `pages/catalog/editor_callbacks.py` | 8 |
| `pages/settings/runtime.py` | 7 |
| `pages/settings/graph_styling/callbacks.py` | 5 |
| `pages/graph/callbacks/catalog.py` | 4 |
| `pages/timeline/api.py` | 3 |
| `pages/search.py` | 3 |
| `pages/graph/utils/graph_operations.py` | 2 |
| `pages/chat.py` | 2 |
| `pages/catalog/callbacks.py` | 2 |
| `pages/graph/callbacks/query.py` | 1 |
| `pages/catalog/editor_test_callbacks.py` | 1 |
| `pages/connectors/layout.py` | 1 |
| `components/setup_banner.py` | 1 |

**Note the `# nosec B113` comments** in `timeline/api.py:72,130,225` — the client
must preserve whatever those were suppressing (a missing timeout), by always
passing one.

**Verify**: `grep -rn "requests\.\(get\|post\|put\|patch\|delete\)" src/ui/` → no matches
**Verify**: `grep -rln "api_client" src/ui/ | wc -l` → **18 or more** (this step's 14 files, plus Step 7's three, plus `collaboration_params.py`)
**Verify**: `pytest -m unit tests -q` → all pass
**Verify**: `mypy src/` → exit 0
**Verify**: `pylint src --score=y` → ≥ 9.0

> ### 🚦 MANUAL GATE 10 — operator check
>
> **Report to the operator:** the five verify outputs and `git diff --stat`.
>
> **Operator verifies:**
> 1. **Zero** raw `requests.*` calls remain in `src/ui/`. The grep is the gate.
> 2. The client carries **no** credentials — no `Authorization` header, no token
>    parameter, no `KEYCLOAK_*`/`AUTH_*` reference. Confirm this explicitly; it is
>    the boundary between this plan and Plan C.
> 3. One exception type carrying `status_code`, not per-call `raise_for_status` —
>    `ApiError`, as Step 7 introduced it. Confirm the count is still **one**:
>    `grep -rn "raise_for_status" src/ui/` → no matches outside `api_client.py`.
> 4. **The collaboration mapping is still at the call sites, not in the client.**
>    `grep -n "CollaborationDataUnavailable" src/ui/api_client.py` → no matches,
>    and `translate_api_error` still exists in `src/ui/collaboration_params.py`.
>    A client-level mapping would satisfy check 3 on paper while making the collab
>    `except ApiError` wrappers unreachable — reintroducing the "An unexpected
>    error occurred." banner that Step 7d-i exists to prevent.
> 5. The transport is injectable, so tests do not monkeypatch the `requests`
>    module globally.
> 6. Timeouts are read **per call**, not captured at import. A value captured
>    once at import is the bug class this plan exists to keep out of the UI.
> 7. **A browser sweep of every page**: Chat, Search, Graph, Timeline, Analytics,
>    Catalog, Connectors, Settings, Collaboration Network (org + ego). A missed
>    call site is a runtime error on a rarely-exercised page — this is the check
>    that finds it.
>
> Wait for `PASS` before starting Step 11.

---

### Step 11: API-completeness audit (regression check, discarded afterwards)

**This is a regression gate, not a long-lived document.** Its purpose is to
verify this plan did not break anything. The artifact is discarded once it passes.

**Run it after Step 10**, when all UI→API calls have one chokepoint to enumerate.

**The three-way comparison:**

| Set | Source |
|---|---|
| **A** — endpoints the UI calls | the `api_client.py` call sites |
| **B** — endpoints the schema exposes | `GET /openapi.json` |
| **C** — `A ⊆ B` | every UI-called path resolves to a real route |

**B must be read container-internally.** Verified: `https://localhost/openapi.json`
→ **404** (Plan 051's deliberate consequence). Use:

```bash
docker exec wba-ai-api python -c "
import json, urllib.request
print(len(json.load(urllib.request.urlopen('http://localhost:8000/openapi.json'))['paths']))
"
```
→ `40` (Step 7 added `/api/v1/search/scoped`; a different number is fine if routes were legitimately added).

**Plus two checks the comparison implies:**

1. **Response-shape** — for each of the ~24 UI-called endpoints, the UI's parsing
   matches the endpoint's `response_model`. This is where Step 7's collab
   round-trip comparison and its `ids` scoping both surface.
2. **Orphans** — endpoints in B that no UI path uses. Those are **fine** (the API
   is allowed to be broader than Dash); listing them is what demonstrates the API
   is not Dash-shaped.

**Baseline for set A** (24 distinct paths, measured at the baseline commit — plus
`/search/scoped`, which Step 7 adds and which therefore will not appear in a
pre-split measurement):

```
/api/v1/settings/                                    (and /reset, /{key}/reset)
/api/v1/graph-themes/                                (+ /effective, /{id}, /{id}/set-default)
/api/v1/search                                       (/search/persons, /search/scoped POST)
/api/v1/chats                                        (/chats/{session_id})
/api/v1/commands/
/api/v1/connectors/                                  (+ /{type}, /{type}/configs,
                                                      /{type}/configs/{id},
                                                      /{type}/configs/{id}/status,
                                                      /{type}/test)
/api/v1/graph/execute                                (/graph/expand)
/api/v1/queries/catalog                              (/catalog-metadata,
                                                      /catalog-metadata/{id},
                                                      /catalog/namespaces,
                                                      /catalog/{namespace}/{slug})
/api/v1/activity/timeline                            (/activity/suggest)
```

**Discard the table after it passes.** Leave no artifact — the plan's step record
is the only place it appears.

**Verify**: every path in A resolves in B
**Verify**: response shapes match for all A endpoints
**Verify**: orphans listed and reviewed (not necessarily zero)
**Verify**: `pytest -m unit tests -q` → all pass

> ### 🚦 MANUAL GATE 11 — operator check
>
> **Report to the operator:** the count of paths in A and B, the mismatch list
> (empty if clean), and the orphan list.
>
> **Operator verifies:**
> 1. **`A ⊆ B` holds** — every endpoint the UI calls is a real route. A single
>    miss is a broken page.
> 2. Response shapes match. Spot-check the two most complex: the collaboration
>    network and the search response.
> 3. Orphans were reviewed and are genuinely not-needed by the UI. An orphan that
>    *should* be used means a call site was missed in Step 10.
> 4. No artifact was left behind.
>
> Wait for `PASS` before starting Step 12.

---

### Step 12: gunicorn concurrency gate

**This exists because the split can silently serialize every callback.**

Before the split, Starlette ran sync Dash callbacks in a threadpool (~40
threads), so concurrent callbacks did not block each other. Gunicorn's default
worker is `sync` with one thread, which **would** serialize them. Step 8 pins
`--worker-class gthread --workers 4 --threads 8`, but that is an assumption about
flags, not a measurement.

**Measure it.** Fire N concurrent Dash callback POSTs at
`https://localhost/app/_dash-update-component` and confirm they overlap in time.

Use a payload that takes measurable time — the collaboration network response is
**1.67 MB** and exercises the slow path (Neo4j + Louvain). `client_max_body_size
50m` is already set, so payload size is not the limit.

**The gate:** N concurrent requests complete in materially less than N ×
(single-request duration). If they serialize, total time ≈ N × single.

Suggested N = 4 (matching `--workers 4`), and repeat at N = 12 to exercise the
threads within a worker.

**Verify**: 4 concurrent requests complete in < 2× the single-request duration
**Verify**: 12 concurrent requests complete in < 4× the single-request duration
**Verify**: the timings and the single-request baseline are recorded

> ### 🚦 MANUAL GATE 12 — operator check
>
> **Report to the operator:** the single-request baseline, the 4-concurrent and
> 12-concurrent timings, and the concurrency mechanism used.
>
> **Operator verifies:**
> 1. **The timings show overlap, not serialization.** If 4 concurrent requests
>    take ≈4× the single-request time, the callbacks are serializing — the flags
>    are wrong or the worker class is not `gthread`.
> 2. The measurement used a **real slow callback**, not a trivial one. A fast
>    endpoint cannot distinguish serialization from parallelism.
> 3. Confirm in the UI container that the running process is
>    `gunicorn --worker-class gthread` — check the process args, not the file.
> 4. If serialization is observed, the fix is to correct the flags and re-measure.
>    **Do not accept the flags as verified because they are present in the file.**
>
> Wait for `PASS` before starting Step 13.

---

### Step 13: Update the documentation

Four categories, all of which are now false or incomplete.

**17a. `CLAUDE.md`**

- Line 15, the "Run app (API + UI)" row: replace the single `uvicorn app.main:app --reload`
  with **two commands**, per Decision 14:
  - API: `PYTHONPATH=src uvicorn app.api_main:app --reload` → `http://127.0.0.1:8000/api/health`
  - UI: `PYTHONPATH=src gunicorn ui_main:server --bind 127.0.0.1:8001 --reload` →
    `http://127.0.0.1:8001/app` (with `API_BASE_URL=http://127.0.0.1:8000` set).
  State plainly that local dev needs **both** processes, and that the Compose
  stack remains the supported path.
- The "Docker Compose services" table: replace the `app` row with `api` and add
  a `ui` row. Neither publishes a host port.
- The architecture section: `src/ui/` and `src/domain/` are new top-level
  packages; update the three-layer diagram to four.
- The import-convention examples: add `from domain.graph_theme import …`.

**17b. `DEVELOPER_QUICK_START.md`** — Option 2 (`:106`, `:134`) currently says
`uvicorn app.main:app --reload`. Update to the two-process flow, and label it
clearly (Option 1, the Compose path, is unchanged and still recommended).

**17c. `USER_GUIDE.md`** — the container/logs sections reference the `app`
service. Update `docker compose logs app` → `logs api`, and note that `ui` is a
separate service.

**17d. `scripts/setup.sh`** — the failure message at `:400` says
`docker compose logs app`; change to `api`. The health poll at `:384` still
targets `https://localhost/api/health`, which is correct. Consider adding a UI
readiness check.

**17e. `.env.example`** — `API_SERVER=http://app:8000/` (`:106`) → `http://api:8000/`.

**17f. `docs/design/authn-authz-design.md`** — **four sections** now state
mechanisms this plan made impossible. Edit them so Plan C is not written against
a stale premise:

1. **Enforcement points** — "ASGI middleware is the only mechanism that can guard
   a mounted WSGI application" is **false**. The UI is a Flask/WSGI service. The
   replacement is Flask `before_request` (redirect to login when no session
   cookie) plus `stream_with_context` for the SSE proxy.
2. **The `/app/stream/<session_id>` proxy route** — its justification referenced
   the `a2wsgi` mount and the `routes_pathname_prefix` asymmetry. It is now a
   plain Flask route on `ui_main:server`.
3. **Deployment Topologies** — "Two containers: the UI runtime and the API
   runtime… They are separated by Plan B" becomes present tense, and the UI
   container's contents listed there are now literally true.
4. **Non-API Surfaces → "Application-internal bypasses → Plan B"** — the three
   in-process callbacks are resolved. Update the table to say so.

**Do not rewrite the rest of that document.** It owns authn/authz; this plan
only corrects what it invalidated.

**Verify**: `grep -rn "uvicorn app.main" CLAUDE.md DEVELOPER_QUICK_START.md` → no matches
**Verify**: `grep -rn "app\.main:app" CLAUDE.md DEVELOPER_QUICK_START.md` → no matches
**Verify**: `grep -n "docker compose logs app" USER_GUIDE.md scripts/setup.sh` → no matches
**Verify**: `grep -n "app:8000" .env.example CLAUDE.md` → no matches
**Verify**: `grep -n "ASGI middleware is the only mechanism" docs/design/authn-authz-design.md` → no matches
**Verify**: `bash -n scripts/setup.sh` → exit 0

> ### 🚦 MANUAL GATE 13 — operator check
>
> **Report to the operator:** the six verify outputs and `git diff` for each file.
>
> **Operator verifies:**
> 1. **The local-dev story is actually followable.** Walk it: start the API in
>    one terminal, the UI in another, and confirm `http://127.0.0.1:8001/app`
>    loads and its callbacks reach the API. `CLAUDE.md` is what every future
>    agent reads — if these two commands are wrong, every subsequent task is
>    misled.
> 2. The Compose services table matches `docker-compose.yml` exactly.
> 3. `authn-authz-design.md` no longer claims an ASGI-mount mechanism for the UI.
>    Read the four edited sections.
> 4. **The doc edits did not stray.** Only the four specified sections changed.
>
> Wait for `PASS` before starting Step 14.

---

### Step 14: Final CI gates and full-stack smoke

```bash
pytest -m unit tests -q
mypy src/
pylint src --score=y
bandit -c .bandit.yml -r src/ -lll
docker compose config -q
```

**Plus the full page sweep**, since this is the last gate:

| Page | Check |
|---|---|
| Chat | streams progressively; sessions list; create/delete |
| Search | query returns results; person search |
| Graph | query executes; spotlight highlights (Step 7's `ids`) |
| Timeline | renders; deep-link to Graph works |
| Analytics | gallery renders; both collaboration cards launch |
| Collaboration Network (org) | plots; filters apply |
| Collaboration Network (ego) | plots; person picker; collaborator cap |
| Catalog | browse; editor loads; favourite toggle |
| Connectors | list; env table renders (Step 6); scan status |
| Settings | runtime settings load; a write round-trips |

**Verify**: all five commands exit 0; `pylint` ≥ 9.0
**Verify**: every page in the sweep renders and its primary action works
**Verify**: `git status --short` shows no files outside the Scope list
**Verify**: `git diff --stat` touches no file under `src/connectors/` (except the zero expected)

> ### 🚦 MANUAL GATE 14 — operator check (final)
>
> **Report to the operator:** all five command outputs, the page-sweep table, and
> `git status --short`.
>
> **Operator verifies:**
> 1. All five gates pass. `pylint` ≥ 9.0.
> 2. `pytest -m unit tests -q` shows **no fewer** tests than the **2365** baseline
>    plus this phase's additions. A drop means tests were skipped, not fixed.
> 3. The page sweep is complete. **Do not accept "the main pages work"** — this
>    is the gate that catches a missed call site from Step 10 and a missed import
>    from an earlier phase.
> 4. No file outside the Scope list was modified.
> 5. The audit's conclusion (Step 11) is reflected: no capability reachable only
>    in the UI layer.
>
> Reply `PASS` to close the plan, then update the Progress tracker and
> `plans/README.md`.

---

## Progress tracker

Mark each cell as you go. `⬜` not started · `🔄` in progress · `✅` passed ·
`❌` failed (stop and report). **Do not start a step whose gate is not `✅`.**

**Phases 1–3 — COMPLETE (Steps 1–9).** Do not re-open these; the executed record
is in the backup of the original plan and in the git log.

| Phase | Steps | What it delivered | State |
|---|---|---|---|
| 1 — pure moves | 1–4 | `src/domain/` created (`graph_theme`, `node_size`, `person_network_url`, `theme_tokens` **with its geometry injection loop**, collaboration metadata, the registries); `runtime_settings/events.py` → `common/messaging/settings_events.py` | ✅ complete |
| 2 — structural split | 5–7 | `src/app/dash_app/` → `src/ui/`; `api_main.py` + `ui_main.py`; DB-free `UISettings` / `ui.runtime_settings` / `domain.timezone`; the three bypasses (collab, ego, spotlight) → HTTP; new `POST /api/v1/search/scoped`; `api_client.py` created; `_PENDING_STEP_7` drained | ✅ complete |
| 3 — go live | 8–9 | Two images, two entrypoints, `src/app/main.py` **deleted**, compose `app`→`api` + new `ui`, nginx upstream split, `API_SERVER` renamed, **`app` network alias dropped** | ✅ complete |

**Phase 4 — client, audit, docs**

| Step | What it changes | Automated verify | Manual gate | Status |
|------|-----------------|------------------|-------------|--------|
| 10 | `src/ui/api_client.py` grown into the single chokepoint; **57** remaining call sites across **14** files migrated | zero raw `requests.*` in `src/ui/`; suite/`mypy`/`pylint` | Operator confirms no credentials; **full page sweep** | ⬜ |
| 11 | API-completeness audit (`A ⊆ B`, response shapes, orphans) | comparison passes; artifact discarded | Operator reviews mismatch and orphan lists | ⬜ |
| 12 | gunicorn concurrency gate | 4 and 12 concurrent requests overlap | Operator confirms overlap, not serialization | ⬜ |
| 13 | Docs: `CLAUDE.md`, `DEVELOPER_QUICK_START.md`, `USER_GUIDE.md`, `setup.sh`, `.env.example`, `authn-authz-design.md` | six grep gates | Operator **walks the two-process local dev flow** | ⬜ |
| 14 | Full CI gates + full-stack smoke | all five gates; every page renders | Operator signs off the complete page sweep | ⬜ |

---

## Test plan

**The regression floor.** `pytest -m unit tests -q` must hold at
**2365 passed, 0 failed, 2 skipped** or better at every step. A drop in the count
is a STOP condition — it means tests were silently skipped by a missing marker or
a broken import, not that they were removed.

**New tests this phase:**

- **`tests/test_ui_api_client_*.py`** — the client's contract, in the shape Step 7
  established with `tests/test_ui_api_client_status_mapping.py`: every non-2xx
  raises **one** `ApiError` carrying `status_code`, the transport is injectable,
  and the timeout is read **per call** rather than captured at import. Extend the
  existing file rather than duplicating it, and keep its two halves passing.
- Any test whose stub patched a now-removed `requests.*` call site must be
  **repointed to the client seam**, not deleted. Step 7 did exactly this for
  `tests/test_collab_consumer.py` and `tests/test_ego_page_callbacks.py`; the same
  convention applies to Step 10's 14 files.

**Mutations to run (not optional):**

1. **Step 10** — point one migrated call site back at `requests` directly; the
   `grep -rn "requests\.\(get\|post\|put\|patch\|delete\)" src/ui/` gate must fail.
   This is what proves the gate is not passing on an empty match set.
2. **Step 10** — break the client's timeout so it is read once at import; the
   per-call test must fail. A test that passes both ways guards the wrong thing.

**Repointed stubs must stay non-vacuous.** After any stub move, break the thing
under test and confirm the test fails. Step 7's rewrites were verified this way
(dropping a serializer line failed `test_collab_consumer.py`; renaming the ego
`person` param failed two ego tests) — a stub that returns a canned body
regardless of its arguments passes while proving nothing.

## Done criteria

ALL must hold:

- [ ] `pytest -m unit tests -q` exits 0, with ≥ **2365** passed and **0 failed**
- [ ] `mypy src/` exits 0
- [ ] `pylint src --score=y` reports ≥ 9.0
- [ ] `bandit -c .bandit.yml -r src/ -lll` exits 0
- [ ] `docker compose config -q` exits 0
- [ ] `grep -rn "requests\.\(get\|post\|put\|patch\|delete\)" src/ui/` → **no matches**
- [ ] `grep -rn "raise_for_status" src/ui/` → no matches outside `api_client.py`
- [ ] `grep -n "CollaborationDataUnavailable" src/ui/api_client.py` → **no matches**
      (the collaboration mapping stays at the call sites, in
      `src/ui/collaboration_params.py`)
- [ ] `grep -rln "api_client" src/ui/` → **≥ 18** files (Step 7's 3 + Step 10's 14 + `collaboration_params.py`)
- [ ] `src/ui/api_client.py` carries **no credentials** — no `Authorization` header, no token parameter, no `AUTH_*` / `KEYCLOAK_*` reference
- [ ] Timeouts are read **per call** from `ui.runtime_settings`, never captured at import
- [ ] Step 11: every path in A resolves in B; response shapes match for all A endpoints; orphans listed and reviewed (not necessarily zero); **no artifact left behind**
- [ ] Step 12: 4 concurrent requests complete in **< 2×** the single-request duration, and 12 in **< 4×** — measured against a real slow callback, not a trivial one
- [ ] `grep -rn "uvicorn app.main" CLAUDE.md DEVELOPER_QUICK_START.md` → no matches
- [ ] `grep -rn "app\.main:app" CLAUDE.md DEVELOPER_QUICK_START.md` → no matches
- [ ] `grep -n "docker compose logs app" USER_GUIDE.md scripts/setup.sh` → no matches
- [ ] `grep -n "app:8000" .env.example CLAUDE.md` → no matches
- [ ] `grep -n "ASGI middleware is the only mechanism" docs/design/authn-authz-design.md` → no matches
- [ ] `bash -n scripts/setup.sh` → exit 0
- [ ] Every page in Step 14's sweep renders and its primary action works
- [ ] No files outside the Scope list are modified (`git status`)
- [ ] **All of Steps 10–14's manual gates recorded `✅` in the Progress tracker**
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report back (do not improvise) if:

- **More or fewer than 57 `requests.*` call sites** exist in `src/ui/` at Step 10's
  start, or the distribution does not match its 14-file table. The count is
  load-bearing: it is the completeness measure for the one-chokepoint property.
  Report the actual per-file list rather than working around it.
- **`docker compose up -d --build` cannot reach `https://localhost/app`.** This is
  the stable-state rule. A Phase 4 step that breaks the running UI is a defect in
  the step.
- **A test count drops**, rather than a test failing. A silently skipped test is
  worse than a failing one.
- **A change appears to require touching an out-of-scope file** — in particular
  anything under `src/connectors/`, the images, the compose topology or the nginx
  config. Phase 4 is code, tests and docs; a packaging change here means
  something earlier regressed. Report it.
- **A Phase 4 change appears to need credentials in `api_client.py`**, or an
  `AUTH_*` / `KEYCLOAK_*` setting. That is Plan C's scope and this plan
  deliberately excludes it — stop and report rather than adding it.
- **Step 11's `A ⊆ B` fails.** A UI-called path with no route is a broken page;
  fix the call site, do not add a route to satisfy the audit.
- **Step 12 shows serialization** (4 concurrent ≈ 4× the single-request time).
  The worker flags are wrong or the worker class is not `gthread`; correct the
  flags and re-measure. **Do not accept the flags as verified because they are in
  the file.**
- **Any Step 14 page fails to render or its primary action errors.**
- **Producers fall back to default runtime settings.** Check the connector logs
  for `Runtime settings API unreachable` — that is the silent-degradation failure
  mode, and it means the Phase 3 rename has regressed.
- **`docker compose up` fails with `bind: address already in use` on 80/443.**
  Report which process holds the port; do not remap.

## Maintenance notes

**What future changes interact with this:**

- **Plan C (Keycloak)** builds directly on this. It:
  1. Teaches `src/ui/api_client.py` to attach `Authorization: Bearer` — the
     client's single chokepoint is what makes that a one-file change. **This is
     why Step 10's `grep` matters**: a surviving raw `requests` call is a call
     Plan C cannot authenticate.
  2. Adds Flask `before_request` auth to the UI (not ASGI middleware — see the
     revised `authn-authz-design.md`).
  3. Adds the `/app/stream/<session_id>` SSE proxy as a Flask route.
  4. Sets `AUTH_COOKIE_SECURE` derived from `EXTERNAL_BASE_URL`'s scheme.
- **The `src/app/` → `src/api/` rename** is deferred to its own plan (Decision 6).
  It is cosmetic: 238 files import `app.*`, no isolation gain. Do it when this
  plan and Plan C have both settled.
- **`scripts/dev.sh`** was considered and deferred (Decision 14). If local-dev
  friction becomes a real complaint, that is the shape to add.
- **A new UI→API call** must go through `api_client.py`. A raw `requests` call
  reintroduces the per-site timeout bug Step 6 fixed and the auth gap Plan C will
  close. The `grep` in the done criteria is the guard.
- **A new pure shared module** belongs in `src/domain/`, and must keep the
  package's transport-free property (`tests/test_domain_purity.py`).
- **A new service** must not be named `app`. The alias is gone; the name is
  retired.
- **Adding a provider or a streaming endpoint** may need the nginx upstream and
  `proxy_buffering off` revisited — see `docs/design/nginx-tls-design.md`.

**What a reviewer should scrutinize:**

- **`api_client.py` carries no credentials.** That is the Plan B / Plan C boundary.
- **The collaboration mapping is at the call sites, not in the client.** A
  client-level `404 → CollaborationDataUnavailable` mapping would satisfy "one
  exception type" on paper while making the collab callbacks' `except ApiError`
  wrappers unreachable — reintroducing the "An unexpected error occurred." banner
  that Step 7d-i exists to prevent. `translate_api_error` stays in
  `src/ui/collaboration_params.py`, and `tests/test_ui_api_client_status_mapping.py`
  guards both halves.
- **Timeouts are read per call.** A timeout captured at import is the import-time
  staleness bug class returning.
- **The transport is injectable**, so tests do not monkeypatch the `requests`
  module globally — with 47 test files touching the UI, global patching is how
  stub leaks happen.
- **Step 10 did not weaken a stub.** A rewritten test that returns a canned
  response regardless of its arguments is vacuous; break the thing under test and
  confirm it fails.
- **Step 12 measured rather than assumed.** The gunicorn flags being present in
  the file is not evidence they are effective.
- **`client_max_body_size 50m` survives any nginx edit.** It is a Plan 051 fix and
  the collaboration pages depend on it.
- **`docs/design/authn-authz-design.md` was edited in exactly four places.** Only
  the four specified sections changed.
- **Step 13's edits did not stray.** `CLAUDE.md` is what every future agent reads;
  if the two local-dev commands are wrong, every subsequent task is misled.
- **No Phase 1–3 file was re-opened.** The images, the compose topology, the nginx
  upstreams, the entrypoints and `src/domain/` are settled.

**Explicitly deferred out of this plan:**

- The `src/app/` → `src/api/` package rename — its own plan.
- `scripts/dev.sh` — two documented commands instead.
- Any credential handling in `api_client.py` — Plan C.
- The `/app/stream/<id>` SSE proxy route — Plan C.
- `AUTH_*`, `KEYCLOAK_*`, per-user ownership, the `auth_session` table — Plan C.
- FastAPI's `/docs`, `/redoc`, `/openapi.json` — Plan E.
- Per-person data scoping — Plan F.

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
2. **Adequacy** — the **current UI** reaches every capability it needs through the
   API, with no database driver of its own. A future frontend is out of scope; the
   bar is that today's Dash UI does its whole job over API interfaces.
   **Step 11's audit is what proves this.**

Plus two pieces of finishing work that only make sense once the split is real:
**one HTTP chokepoint** for every UI→API call (Step 10), a **concurrency check**
confirming the split did not silently serialize callbacks (Step 12), and
**documentation** that no longer describes the pre-split world (Step 13).

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
| 19 | API error granularity | The UI may collapse API responses into one `ApiError`, but the **FastAPI server itself must keep granular HTTP status codes** — `401`/`403`/`404`/`422`/`5xx` as appropriate. Direct consumers (`curl`, a future frontend) see the real status; only the UI's client flattens it. Do **not** add a catch-all handler on the API side. |

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
- `src/ui/pages/graph/callbacks/context_menu.py` and
  `src/ui/pages/graph/callbacks/expansion.py` — they contain **no** `requests.*`
  call sites of their own, so they are absent from the 14-file table, but they
  `except requests.exceptions.Timeout` / `ConnectionError` around calls that land
  in `pages/graph/utils/graph_operations.py` (which *is* in the table). Step 10's
  exception-handler subsection covers them.
- `tests/` — new tests for the client and the audit, and any stub repointed by a swap
- `CLAUDE.md`, `DEVELOPER_QUICK_START.md`, `USER_GUIDE.md`, `scripts/setup.sh`
- `docs/design/authn-authz-design.md` — **the four sections in Step 13 only**
- **`.env.example` is NOT in scope** — its `API_SERVER` value was already corrected to
  `http://api:8000/` before this step; Step 13e records this. Touching it fails the gate.
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

### Step 10: Grow `src/ui/api_client.py`, migrate all 57 call sites and their error handlers

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

**Migrate the exception handlers too — this is part of the migration, not a
separate cleanup.** Changing a call site from `requests` to `api_client` changes
the exception type it raises: `requests.exceptions.Timeout` /
`ConnectionError` / `RequestException` no longer occur; `ApiError` does. An
`except requests.exceptions.*` clause left in place therefore becomes **dead
code**, and the generic `except Exception` beneath it catches `ApiError`
instead — silently changing what the user sees.

**41 such clauses exist across 12 files, plus 9 more in a third spelling.** They
are not `requests.*` call sites, so the table above does not count them and the
grep gates below would otherwise miss them. Two spellings exist — both are dead
after migration:

```bash
grep -rn "requests\.exceptions" src/ui/ --include="*.py"   # 41 sites, 12 files
grep -rn "requests\.RequestException" src/ui/ --include="*.py"  # 9 sites, 3 files
#   timeline/api.py:77,135,235
#   settings/graph_styling/callbacks.py:413,578,656,742,825
#   graph/utils/graph_operations.py:45
```

Also remove the now-unused imports: `grep -rn "import requests" src/ui/ --include="*.py"`
returns **16** lines outside `api_client.py` (15 module-level plus an indented
local import at `pages/connectors/layout.py:799` — note that one is inside a
function, so a `^import` anchored grep misses it; use the unanchored form above).

The two highest-risk files are the ones **absent from the 14-file table**:
`pages/graph/callbacks/context_menu.py:193,202` and
`pages/graph/callbacks/expansion.py:139,148,288,300`. They wrap
`execute_expansion_and_merge` (`pages/graph/utils/graph_operations.py:90`,
which *is* migrated) and render the specific alerts — for example
`create_expansion_error_alert("Expansion timed out", error_type="timeout")`.
After migration those branches never fire and the generic fallback renders
instead.

For each of the 50 dead exception clauses:

1. Replace the caught type with `ApiError` (import it from `ui.api_client`).
   `except requests.exceptions.RequestException` → `except ApiError`; the
   narrower `Timeout` / `ConnectionError` clauses → `except ApiError`.
2. **Preserve the handler's behaviour and message.** The branching changes
   meaning: `ApiError` carries `status_code`, not "was this a timeout". Do not
   try to reconstruct the distinction by inspecting `ApiError` — keep one
   `except ApiError` per former clause where the handler bodies differ only in
   their log text, or keep two branches if the handler bodies genuinely differ
   (e.g. a distinct alert), both catching `ApiError`. If a call site *needs* to
   tell a transport failure from a 4xx response, **stop and report** — that
   requires extending `ApiError` and belongs to Plan C.
3. Remove `import requests` from the file when nothing else in it uses the
   module (pylint will flag it; an unused import fails the gate below).

Do **not** extend `ApiError` with a timeout/connection flag as part of this
step.

**Verify**: `grep -rn "requests\." src/ui/ --include="*.py" | grep -v "src/ui/api_client.py"` → **no matches** (this subsumes the narrower greps below and catches `.exceptions`, `.RequestException` and `.Response` spellings). `api_client.py` is excluded because it *is* the wrapper: it legitimately keeps `requests.Response` (`:62`, `:92`) and `requests.request` (`:99`).
**Verify**: `grep -rn "import requests" src/ui/ --include="*.py" | grep -v "src/ui/api_client.py"` → **no matches**
**Verify**: `grep -rn "requests\.\(get\|post\|put\|patch\|delete\)" src/ui/` → no matches
**Verify**: `grep -rn "requests\.exceptions" src/ui/ --include="*.py"` → no matches
**Verify**: `grep -rn "requests\.RequestException" src/ui/ --include="*.py"` → no matches
**Verify**: `grep -rln --include="*.py" "api_client" src/ui/ | wc -l` → **20 or more** (this step's 14 call-site files, plus Step 7's three, plus `collaboration_params.py`, plus the two handler files now importing `ApiError`). The `--include` matters: without it, `__pycache__/*.pyc` matches inflate the count (9 vs 4 today) — and after migration that inflation could carry a missed file over the threshold.
**Verify**: `pytest -m unit tests -q` → all pass
**Verify**: `mypy src/` → exit 0
**Verify**: `pylint src --score=y` → ≥ 9.0

> ### 🚦 MANUAL GATE 10 — operator check
>
> **Report to the operator:** every verify output above and `git diff --stat`.
>
> **Operator verifies:**
> 1. **Zero** references to the `requests` module remain in `src/ui/` — not just
>    `requests.get(...)` call sites but also `requests.exceptions.*` clauses and
>    `import requests` lines. `grep -rn "requests\." src/ui/ --include="*.py" |
>    grep -v "src/ui/api_client.py"` is the gate — `api_client.py` is exempt
>    because it is the one module that legitimately wraps `requests`.
> 2. The client carries **no** credentials — no `Authorization` header, no token
>    parameter, no `KEYCLOAK_*`/`AUTH_*` reference. Confirm this explicitly; it is
>    the boundary between this plan and Plan C.
> 3. One exception type carrying `status_code`, not per-call `raise_for_status` —
>    `ApiError`, as Step 7 introduced it. Confirm the count is still **one**:
>    `grep -rn "raise_for_status" src/ui/ --include="*.py"` → **no matches at
>    all**. Note `api_client.py` does not use `raise_for_status` itself — it
>    checks `response.ok` and calls `_describe()` — so there is no legitimate
>    exception to "no matches" here.
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
> 8. **The error handlers were migrated with the calls.** In the Graph page,
>    force an expansion that times out (or stop the API container mid-expansion):
>    the "Expansion timed out" alert must still render — not the generic "An
>    unexpected error occurred." If the generic alert appears, a handler still
>    catches `requests.exceptions` while the call raises `ApiError`. This is the
>    regression Gate 10's greps alone cannot prove.
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
flags, not a functional check.

**Check it functionally.** Fire N concurrent Dash callback POSTs at
`https://localhost/app/_dash-update-component` and confirm every request returns
successfully — no 5xx, no timeout, no dropped connection. The point is that the
stack handles concurrent callbacks at all; it is not a latency benchmark.

Suggested N = 4 (matching `--workers 4`), and repeat at N = 12 to exercise the
threads within a worker. Any real callback works — a fast one is fine.

**Verify**: 4 concurrent requests all complete with a 2xx response
**Verify**: 12 concurrent requests all complete with a 2xx response
**Verify**: no request returns a 5xx or times out during either run

> ### 🚦 MANUAL GATE 12 — operator check
>
> **Report to the operator:** the 4-concurrent and 12-concurrent results (status
> codes and any failures), and the concurrency mechanism observed.
>
> **Operator verifies:**
> 1. **All concurrent requests succeed.** No 5xx, no timeout, no connection drop.
>    A serialization failure shows up here as timeouts or gateway errors when the
>    request queue backs up.
> 2. Confirm in the UI container that the running process is
>    `gunicorn --worker-class gthread` — check the process args, not the file.
> 3. If failures are observed, correct the flags and re-run the functional check.
>    **Do not accept the flags as verified because they are present in the file.**
>
> Wait for `PASS` before starting Step 13.

---

### Step 13: Update the documentation

> **Reconciled 2026-10-30 at `cb11f9b1`.** The step below was re-written against the live
> tree: `src/app/main.py` **no longer exists**, `src/app/dash_app/` is now `src/ui/`, and
> `src/domain/` and `src/ui_main.py` are new. The previous line-number citations had
> drifted, so they have been replaced with a grep-verified inventory. The executor must
> work from the inventory, not from line numbers.
>
> **The edits must not reference this plan, its phase, or its step numbers.** These are
> ordinary project docs; they describe the system as it is, with no provenance markers.

**Scope of "now false or incomplete" is wider than the four categories below** — every
place in the in-scope files that names the retired `app` **service**, the deleted
`app.main:app` **module path**, or the old `dash_app/` **package** is wrong and is listed
here. Do not touch files outside this list.

**Verified local-dev invocation.** Both commands below were run against this tree and
returned the stated result — write them into the docs as-is:

```bash
# Terminal 1 — API. Start this FIRST.
PYTHONPATH=src uvicorn app.api_main:app --reload            # → http://127.0.0.1:8000/api/health  → 200

# Terminal 2 — UI. Needs the API's URL; the UI is a Flask/WSGI service.
API_BASE_URL=http://127.0.0.1:8000 PYTHONPATH=src \
  gunicorn ui_main:server --bind 127.0.0.1:8001 --reload    # → http://127.0.0.1:8001/app         → 200
```

Both were verified on 2026-10-30 (API on `:8021`, UI on `:8022`/`:8023`/`:8025`):
`/api/health` → `200`, `/app/` → `200`, and the UI log shows it reaching the API —
`Fetched runtime settings snapshot from http://127.0.0.1:8021/api/v1/settings/runtime-snapshot`.
`gunicorn --reload` works with the default `sync` worker **and** with
`--worker-class gthread`. `gunicorn` is not in `requirements_dev.txt`; it is in
`requirements.ui.txt`, so a developer who installed all `requirements*.txt` per
`DEVELOPER_QUICK_START.md`'s setup loop already has it.

**13a. `CLAUDE.md`** — grep-verified stale claims. Every one of these must be corrected:

| Line | Current (stale) | Why it is wrong | Correction |
|---|---|---|---|
| 15 | `uvicorn app.main:app --reload` → UI at `127.0.0.1:8000/app` | `app.main` is deleted; one process no longer serves both | The two-command block above; state that local dev needs **both** processes and that the Compose stack remains the supported path |
| 36 | Compose table row: `` `app` `` \| FastAPI + Dash \| 8000 | Service renamed in Phase 3 | Replace with `api` (FastAPI only) and add a `ui` row (Dash/Flask). Neither publishes a host port. Match `docker-compose.yml:23,97` |
| 37 | `` `nginx` `` \| … front of `` `app` `` | Stale service name | `front of the api and ui services` |
| 49 | "Only `app.dash_app.*` relaxes …" | `mypy.ini:32` now has `[mypy-ui.*]` | `ui.*` |
| 60 | import examples omit `domain` | `src/domain/` is a new top-level package | Add `from domain.graph_theme import …   # pure shared domain logic → src/domain/` |
| 73 | "Three separately-containerized layers" | Now four packages | Four; list `src/ui/`, `src/app/`, `src/connectors/`, `src/common/` (+ `src/domain/` as pure shared logic) |
| 76 | `src/app/  FastAPI + Dash application` | Dash is no longer in `src/app/` | `src/app/` = FastAPI API (`app.*`); `src/ui/` = Dash/Flask UI (`ui.*`); `src/domain/` = pure shared logic (`domain.*`) |
| 99 | "router.py  FastAPI routes, wired in src/app/main.py" | `src/app/main.py` is deleted | `wired in src/app/api_main.py` |
| 127 | `### Dash UI (src/app/dash_app/)` | Package moved | `### Dash UI (src/ui/)` |
| 129 | "mounted onto FastAPI at `/app` via `a2wsgi` `WSGIMiddleware`" | There is **no** mount and no `a2wsgi` — the UI is its own Flask service | `created by create_dash_app() in ui/layout.py and served by gunicorn as a standalone Flask app from src/ui_main.py. It owns the /app/* paths; the API owns /api/*.` |
| 133 | "Put cross-page modules at `dash_app/` … (`from app.dash_app.graph_styles import …`)" | Stale paths | `ui/` and `from ui.graph_styles import …` |
| 142–143 | runtime-settings bullets name only `app.settings` / `app.runtime_settings` | The UI holds neither | Keep the `app.*` bullets as **API-side**, and add that the UI reads `ui.settings` (credential-free `UISettings`) and `ui.runtime_settings` (fetched from the API's snapshot endpoint) |
| 145 | "Dash pages call the backend API over HTTP with sync `requests` … using `settings.API_BASE_URL` … and `runtime_settings.get_int(...)`" | Dash no longer calls `requests` directly | `through the single client in src/ui/api_client.py` — it owns the base URL (`UISettings.API_BASE_URL`) and reads the timeout per call |
| 184, 192 | "include it in `src/app/main.py`" | Deleted | `src/app/api_main.py` |
| 195 | "create the package in `dash_app/pages/` … `dash_app/layout.py`" | Stale paths | `ui/pages/` … `ui/layout.py` |
| 211 | "the app publishes no host port" | Now two services | `neither the api nor the ui service publishes a host port` |

**Leave the API-layering and AI-agent sections (`src/app/api/<domain>/v1/`,
`src/app/ai_agent/`) alone** — those paths are still correct.

**13b. `DEVELOPER_QUICK_START.md`** — four stale spots:

- `:95` `docker compose logs -f app` → `-f api` (and mention `ui`).
- `:106` (Option 2's local run) and `:134` (the integration-test note) both say
  `uvicorn app.main:app --reload` → the two-command block above.
- `:111` "Dash UI: http://localhost:8000/app" → the UI now runs on its own port;
  state `http://127.0.0.1:8001/app` (with the API on `:8000`).
- `:122` `docker compose exec app bash -c "cd app && alembic revision …"` → the API
  service. The API image's WORKDIR is `/app` and it copies `src/app/` to `./app/`
  (`Dockerfile.api:8,23`), so the inner `cd app` is correct once the service name is
  `api`: `docker compose exec api bash -c "cd app && alembic revision --autogenerate -m 'description'"`.

**Plus one correction the plan missed — operator-reported 2026-10-30.** Option 2 was
titled "PostgreSQL Only" and started only `postgres`, but the locally-run API reads Neo4j
and Elasticsearch directly: with either down, `/api/v1/search` and
`/api/v1/graph/collaboration-network` return **`500`** (verified by the reviewer — the API
still reports `/api/health` `200`, so the failure shows only on the data endpoints). The
section must start **all three** stores and retitle accordingly. RabbitMQ is optional
here: the lifespan catches the connection failure and logs a warning (`api_main.py:107`),
and the API stays healthy without it. The stores publish their default host ports
(`docker-compose.yml`: postgres `5432`, neo4j `7474`/`7687`, elasticsearch `9200`), so no
`.env` change is needed.

**Keep the prose minimal** — the operator has flagged verbosity in this section. State the
command and the one-line reason; do not restate rationale, ports, env defaults or failure
modes in the doc.

Keep Option 1 (Compose) labelled as the recommended path; Option 2 is the local flow.

**13c. `USER_GUIDE.md`** — the `app` **service** is referenced 13 times and no longer
exists. Every one must change; `ui` is a separate service now:

| Line(s) | Current | Correction |
|---|---|---|
| 135 | "the application container no longer publishes port 8000" | Still true; say the `api` and `ui` containers publish no host port |
| 174–176 | "### View App Logs Only" / `docker compose logs app` | Retitle to cover both services; show `docker compose logs -f api` and `-f ui` |
| 186, 193, 198 | `docker compose logs -f app`, `logs app --tail 50`, `logs -f -t app` | `api` (add a `ui` variant where it reads naturally) |
| 235 | "Open a Shell in the App Container" / `exec app bash` | Say which service; the API is the one with migrations and a DB |
| 265, 277 | `docker compose logs app` (in the troubleshooting sections) | `api` and `ui` — a 502 is usually `ui` |
| 317 | `docker compose restart app` (after a `.env` change) | `api` and `ui` — the `.env` is mounted into `api` only (`docker-compose.yml:70`) |
| 330, 333, 334, 340 | Quick-reference / support table rows | Same substitutions |

**13d. `scripts/setup.sh`** — `:400` says `docker compose logs app`; change to `api`.
The health poll at `:384` targets `https://localhost/api/health` and is correct as-is —
`api` is the service that owns `/api/health`. Do **not** add a UI readiness check unless
it is trivially safe; the UI's own healthcheck already exists in compose and this is a
shell script whose only failure path is a timeout message.

**13e. `.env.example`** — **already correct, no change needed.** `:106` reads
`API_SERVER=http://api:8000/`. Verified 2026-10-30. Skip it; do not "fix" it again.

**13f. `docs/design/authn-authz-design.md`** — **four sections** state mechanisms this
programme has made impossible. Edit **only** these; the document owns authn/authz and
this step corrects what it invalidated. **Do not rewrite the rest, and do not add plan
or phase provenance to the prose — write it as present-tense fact.**

1. **"Enforcement points" (`:335–364`)** — the claim "Middleware is the only mechanism
   that can guard a mounted WSGI application — FastAPI dependencies do not apply to
   `app.mount("/app", WSGIMiddleware(...))` (`src/app/main.py:196-197`)" is now **false
   twice over**: there is no mount and `src/app/main.py` does not exist. The UI is a
   standalone Flask app (`src/ui_main.py` → `server = app.server`, served by gunicorn).
   Replace with Flask `before_request` (resolve the session cookie, otherwise redirect
   to the login flow) as the `/app/*` guard, plus `stream_with_context` for the SSE proxy.
   The paragraph at `:345–354` explaining the `requests_pathname_prefix` /
   `routes_pathname_prefix` asymmetry and the pre-mount path is also obsolete: in
   `src/ui/layout.py:27-28` **both** prefixes are now set to `"/app/"`, so a Flask route
   registered as `/stream/<session_id>` is reachable at `/app/stream/<session_id>`
   directly, with no mount involved. Rewrite that paragraph to say so.
2. **"The one browser-direct API call" (`:445–471`)** — it justifies the proxy via the
   `a2wsgi` mount and the prefix asymmetry, and cites
   `src/app/dash_app/assets/stream-bridge.js:215`. That path is now
   `src/ui/assets/stream-bridge.js:215` (the file, and its `fetch('/api/v1/chats/' … )`
   call, still exist — verify before editing). Restate the route's home as a plain Flask
   route on `ui_main:server`. Keep the `401`/dual-credential reasoning intact.
3. **"Deployment Topologies" → "Docker Compose (current)" (`:619–628`)** — "Two
   containers: the UI runtime … and the API runtime … They are separated by Plan B"
   becomes present tense, and the sentence describing what the UI container holds is now
   literally true (verify against `docker-compose.yml:97–137` and `requirements.ui.txt`).
4. **"Non-API Surfaces" → "1. Application-internal bypasses" (`:501–519`)** — all three
   listed callbacks are resolved: each now imports `ui.api_client` and calls the HTTP
   endpoint (`pages/collaboration_network/callbacks/filter.py:12-13,91`;
   `pages/collaboration_network_ego/callbacks/filter.py:13-14,211`;
   `pages/graph/callbacks/spotlight.py:18,126`). Update the table/paragraph to past
   tense and note the isolation is enforced by the container split. The
   `CONNECTOR_REGISTRY` note below it now lives at `src/domain/connector_registry.py`;
   update the path.

**Verify**: `grep -rn "app\.main\|uvicorn app.main" CLAUDE.md DEVELOPER_QUICK_START.md` → no matches
**Verify**: `grep -rn "docker compose logs app\|docker compose exec app\|docker compose restart app" USER_GUIDE.md DEVELOPER_QUICK_START.md scripts/setup.sh` → no matches
**Verify**: `grep -n "three-layer\|Three separately" CLAUDE.md` → no matches
**Verify**: `grep -n "dash_app" CLAUDE.md` → no matches
**Verify**: `grep -n "app:8000" .env.example CLAUDE.md` → no matches
**Verify**: `grep -n "ASGI middleware is the only mechanism" docs/design/authn-authz-design.md` → no matches
**Verify**: `grep -n "WSGIMiddleware\|a2wsgi" docs/design/authn-authz-design.md` → no matches
**Verify**: `bash -n scripts/setup.sh` → exit 0
**Verify**: `git status --short` shows changes to **only** `CLAUDE.md`,
`DEVELOPER_QUICK_START.md`, `USER_GUIDE.md`, `scripts/setup.sh` and
`docs/design/authn-authz-design.md`

> ### 🚦 MANUAL GATE 13 — operator check
>
> **Report to the operator:** the verify outputs and `git diff` for each file.
>
> **Operator verifies:**
> 1. **The local-dev story is actually followable.** Walk it: start the API in
>    one terminal, the UI in another, and confirm `http://127.0.0.1:8001/app`
>    loads and its callbacks reach the API. `CLAUDE.md` is what every future
>    agent reads — if these two commands are wrong, every subsequent task is
>    misled.
> 2. The Compose services table matches `docker-compose.yml` exactly.
> 3. `authn-authz-design.md` no longer claims an ASGI-mount mechanism for the UI,
>    and the four edited sections are the only ones that changed.
> 4. **The doc edits did not stray** — no file outside the five named was touched,
>    and no edit mentions a plan, phase or step number.
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
**Verify**: the API keeps **granular** status codes for direct consumers — `curl -o /dev/null -w '%{http_code}' https://localhost/api/v1/nonexistent` → `404` (not a generic 500), and a validation failure returns `422`. The UI's single `ApiError` type is a client-side concern; it must not flatten the server's HTTP semantics.

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
| 10 | `src/ui/api_client.py` grown into the single chokepoint; **57** remaining call sites across **14** files migrated | zero raw `requests.*` in `src/ui/`; suite/`mypy`/`pylint` | Operator confirms no credentials; **full page sweep** | ✅ complete — Gate 10 passed 2026-10-30 |
| 11 | API-completeness audit (`A ⊆ B`, response shapes, orphans) | comparison passes; artifact discarded | Operator reviews mismatch and orphan lists | ✅ complete — Gate 11 passed 2026-10-30 |
| 12 | gunicorn concurrency gate | 4 and 12 concurrent requests all return 2xx | Operator confirms all succeed; no 5xx/timeouts | ✅ complete — Gate 12 passed 2026-10-30 |
| 13 | Docs: `CLAUDE.md`, `DEVELOPER_QUICK_START.md`, `USER_GUIDE.md`, `setup.sh`, `authn-authz-design.md` (`.env.example` already correct) | eight grep gates + `bash -n` | Operator **walks the two-process local dev flow** | 🔄 executed 2026-10-30, reviewer-approved — **awaiting operator PASS** |
| 14 | Full CI gates + full-stack smoke | all five gates; every page renders | Operator signs off the complete page sweep | ⬜ |

### Gate 10 record — 2026-10-30, `61a29670` + uncommitted Step 10 diff

Executed in the live working tree, uncommitted. Operator passed the gate.

**Automated gates (re-run by the reviewer, not taken from the executor's report):**

| Gate | Result |
|---|---|
| `requests\.` in `src/ui/` (excl. `api_client.py`) | 0 — confirmed by an independent `pathlib.rglob` scan |
| `import requests` (excl. client) | 0 ✓ second method |
| `requests.get/post/put/patch/delete` | 0 ✓ second method |
| `requests.exceptions` / `.RequestException` | 0 / 0 ✓ second method |
| `raise_for_status` in `src/ui/` | 0 |
| `CollaborationDataUnavailable` in `api_client.py` | 0 — mapping stays in `collaboration_params.py` |
| Files referencing `api_client` | 20 (floor ≥20) |
| `pytest -m unit tests -q` | 2378 passed, 0 failed, 2 skipped |
| `mypy src/` | exit 0 |
| `pylint src --score=y` | 9.68 (baseline 9.67) |
| `bandit -c .bandit.yml -r src/ -lll` | exit 0, High 0 |
| Credentials in `api_client.py` | none |

**Recorded deviations (judged on merit):**

1. **`ApiError` was extended with `STATUS_NO_RESPONSE = 0`.** Five files genuinely
   need to tell a transport failure from an HTTP status to preserve their old
   alerts (the Graph timeout/connection messages, Timeline's `HTTP nnn` vs
   `request failed`). It reuses the existing `status_code` field rather than
   adding a flag, so the single-type contract holds. It carries no credential, so
   the Plan B / Plan C boundary is intact.
2. **The former `Timeout` and `ConnectionError` alerts were consolidated.** The
   two branches both catch `ApiError` now, so the old "Could not connect to
   server." wording is gone. The plan permits this consolidation; the specific
   timeout alerts are preserved, which is what Gate 10 check 8 requires.

**Out-of-scope change, operator-requested:** `tests/producers/test_daemon_common.py`
— deleted `TestUpdateStatus::test_default_api_server`. Its
`patch.dict(os.environ, {}, clear=True)` block contained only `pass`, so it never
unset `API_SERVER`; it passed only on ambient state and would fail whenever
`load_dotenv()` pulled `API_SERVER` from `.env`. It asserted a fallback that never
applies in deployment (every connector service in `docker-compose.yml` sets
`API_SERVER` explicitly). The suite is green in both env states after removal.

**Pre-existing, unrelated, not fixed here:** nine inconsistent silent `API_SERVER`
fallbacks exist across `src/connectors/` (three different values). Candidate for
its own plan.

**Not covered by automated gates, operator-verified:** the full page sweep and the
forced-expansion-timeout alert check (Gate 10 checks 7–8). The reviewer separately
drove the real expansion callbacks to confirm an `ApiError` renders
"Expansion timed out" while a generic `Exception` renders "Expansion error: …",
and that the new tests are non-vacuous.

### Gate 12 record — 2026-10-30, `234f1cb7` + uncommitted Step 10 diff

Executed in the live working tree, uncommitted. Operator passed the gate.

**Mechanism, read from the running process (not the file):**

```
/proc/1/cmdline: gunicorn ui_main:server --bind 0.0.0.0:8000 \
                 --worker-class gthread --workers 4 --threads 8 --preload
```

Process tree: 1 master (pid 1) + exactly 4 workers (pids 7–10).

**Functional result** (real Dash callback POSTs to
`https://localhost/app/_dash-update-component`, using the theme-toggle callback
from `src/ui/layout.py:258`; threads released together via `threading.Barrier`):

| N | Status codes | Result |
|---|---|---|
| 4 | `200` × 4 | all 2xx, no 5xx, no timeout |
| 12 | `200` × 12 | all 2xx, no 5xx, no timeout |

Server log for the run window: **371 requests, all `status=200`, zero 4xx/5xx.**

**Non-vacuity — genuine parallelism, not just 2xx.** A serialized `sync` worker
also returns 200s, so wall-clock overlap was measured separately: wall vs the
sum of per-request latencies (what wall would equal if fully serial).

| N | wall | sum of latencies | max latency | overlap factor |
|---|---|---|---|---|
| 4 | 13.25 ms | 32.26 ms | 9.37 ms | 2.44× |
| 12 | 33.26 ms | 223.95 ms | 25.69 ms | 6.73× |

At N=12 wall (33 ms) is far below the serialized bound (224 ms) — concurrent
execution confirmed.

**Two discarded measurements (not counted as evidence):**

1. All threads sharing one `requests.Session` with `pool_maxsize=1` — this
   serialized the requests **client-side**, producing a false "SERIALIZED"
   reading.
2. Comparing against a ~4 ms serial baseline where TLS-handshake cost dominated
   the signal.

The final method gives each worker its own pre-warmed session, so the timed
window contains only server-side work.

**Harness note (Dash 4.4.1, for future callback-level load tests):** the
`outputs` field of a `_dash-update-component` body must be a **dict** for a
single non-pattern output. A list raises `InvalidCallbackReturnValue`
("output 0 is a wildcard multi-output") → 500. The browser always sends the
correct form; no product code is affected. The transient 500s in the UI log
around 06:28–06:30 were malformed probe payloads from this investigation, not a
stack defect.

**Not covered by automated gates, operator-verified:** the running worker class
and count were confirmed from `/proc`, not from the entrypoint file; the overlap
measurement is what proves the flags are effective rather than merely present.

### Gate 13 record — 2026-10-30, `cb11f9b1` + uncommitted Step 13 diff

Executed in the live working tree, uncommitted. **Reviewer-approved; awaiting the
operator's PASS at the manual gate.**

**The step was reconciled before dispatch.** Its original text cited
`src/app/main.py:196-197`, `dash_app/layout.py:27` and a `uvicorn app.main:app` row at
`CLAUDE.md:15` — all of which the plan's own Phases 1–3 had since removed. The step was
re-written in place against the live tree: grep-verified claim inventory instead of line
numbers, `.env.example` moved **out** of scope (its `API_SERVER` was corrected before this
step), and the stale-claim set widened from 4 categories to the real set — the original
counted only `logs app` in `USER_GUIDE.md`; there were **13** `app`-service references.

**The local-dev commands were verified by the reviewer, not transcribed.** Both were run
against this tree on spare ports:

| Check | Result |
|---|---|
| `uvicorn app.api_main:app` → `/api/health` | `200` |
| `gunicorn ui_main:server` → `/app/` | `200` |
| UI reaches the API | `Fetched runtime settings snapshot from http://127.0.0.1:8021/api/v1/settings/runtime-snapshot` |
| `gunicorn --reload`, default `sync` worker | `200` |
| `gunicorn --worker-class gthread --reload` | `200` |

**Automated gates (re-run by the reviewer, not taken from the executor's report):**

| Gate | Result |
|---|---|
| `grep -rn "app\.main\|uvicorn app.main"` CLAUDE.md, DEV_QUICK_START.md | 0 |
| `grep -rn "docker compose (logs\|exec\|restart) app"` USER_GUIDE.md, DEV_QUICK_START.md, setup.sh | 0 |
| `grep "Three separately\|three-layer"` CLAUDE.md | 0 |
| `grep "dash_app/\|app\.dash_app"` CLAUDE.md | 0 (the surviving `create_dash_app` match is the real function name) |
| `grep "app:8000"` .env.example, CLAUDE.md | 0 |
| `grep "ASGI middleware is the only mechanism"` design doc | 0 |
| `grep -E "WSGIMiddleware\|a2wsgi"` design doc | 0 |
| `bash -n scripts/setup.sh` | exit 0 |
| `git diff --name-only` | the 5 in-scope docs only |
| Plan/phase/step provenance markers in the 5 docs | none added |

**Independently verified facts, not taken on trust:** the three former bypasses now call
HTTP (`get_json("/api/v1/graph/collaboration-network")` at
`collaboration_network/callbacks/filter.py:91`, `…/ego` at the ego `filter.py:211`, and
`post_json("/api/v1/search/scoped")` at `spotlight.py:126`); `CONNECTOR_REGISTRY` is
imported from `src/domain/connector_registry.py` (`connectors/callbacks.py:13`);
`src/ui/layout.py:27-28` sets **both** Dash prefixes to `/app/`;
`src/ui/assets/stream-bridge.js:215` still holds the browser-direct
`fetch('/api/v1/chats/' …)`; `requirements.ui.txt` carries no data-store driver;
`src/app/main.py` is absent and `src/app/api_main.py` is present.

**One executor correction to the plan, accepted:** the plan said spotlight's replacement
was `GET /api/v1/search`. It is **`POST /api/v1/search/scoped`** (`spotlight.py:126`) —
the `ids`-scoped endpoint Step 7 added. The executor used the true endpoint. The
original claim in this plan's Step 10 "verify" list is stale on this point; recorded here
rather than silently fixed.

**Documented deviation, judged on merit:** the gate requiring zero `WSGIMiddleware`/`a2wsgi`
matches forced a sixth edit, outside the four named sections — `:744` in the "Plan B Scope"
section still described `app.mount("/app", WSGIMiddleware(dash_app.server))`. The executor
reworded that one sentence to drop the stale mechanism while keeping the factual claim, and
added no provenance. The gate as written could not have passed without it, so this is the
gate doing its job rather than scope creep.

**Pre-existing, untouched:** `plans/052-dash-api-runtime-separation.md` shows as modified;
that is the reviewer's own reconciliation edit and the gate-record block, not the executor's.

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
- **A regression test for the migrated error handlers**, covering the case this
  plan's first draft missed: with the client raising `ApiError`, the Graph
  expansion handlers in `pages/graph/callbacks/context_menu.py` and
  `pages/graph/callbacks/expansion.py` must still render their specific alert
  ("Expansion timed out"), not the generic fallback. Model the test on the
  existing expansion tests in `tests/`; stub the client seam to raise `ApiError`
  and assert on the alert text. If no such test exists, add one — this is the
  only automated proof that the `except` clauses were converted.

**Mutations to run (not optional):**

1. **Step 10** — point one migrated call site back at `requests` directly; the
   `grep -rn "requests\.\(get\|post\|put\|patch\|delete\)" src/ui/` gate must fail.
   This is what proves the gate is not passing on an empty match set.
2. **Step 10** — break the client's timeout so it is read once at import; the
   per-call test must fail. A test that passes both ways guards the wrong thing.
3. **Step 10** — restore one `except requests.exceptions.Timeout` clause on a
   migrated call site (re-add the `import requests` so the file imports); the
   `grep -rn "requests\." src/ui/ --include="*.py" | grep -v "src/ui/api_client.py"`
   gate must fail. This proves the gate catches handler clauses, not only call
   sites — the failure mode that would otherwise silently degrade a page's error
   message to the generic one.

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
- [ ] `grep -rn "requests\." src/ui/ --include="*.py" | grep -v "src/ui/api_client.py"` → **no matches** (catches call sites, `requests.exceptions.*` and `requests.RequestException` clauses; `api_client.py` is the exempt wrapper)
- [ ] `grep -rn "import requests" src/ui/ --include="*.py" | grep -v "src/ui/api_client.py"` → **no matches**
- [ ] `grep -rn "requests\.\(get\|post\|put\|patch\|delete\)" src/ui/` → **no matches**
- [ ] `grep -rn "requests\.exceptions" src/ui/ --include="*.py"` → **no matches**
- [ ] `grep -rn "requests\.RequestException" src/ui/ --include="*.py"` → **no matches**
- [ ] `grep -rn "raise_for_status" src/ui/ --include="*.py"` → **no matches**
      (`api_client.py` uses `response.ok`, not `raise_for_status`, so there is no
      legitimate match anywhere under `src/ui/`)
- [ ] `grep -n "CollaborationDataUnavailable" src/ui/api_client.py` → **no matches**
      (the collaboration mapping stays at the call sites, in
      `src/ui/collaboration_params.py`)
- [ ] `grep -rln --include="*.py" "api_client" src/ui/ | wc -l` → **≥ 20** files (Step 7's 3 + Step 10's 14 call-site files + `collaboration_params.py` + the 2 handler files); the `--include` keeps `__pycache__/*.pyc` out of the count
- [ ] `src/ui/api_client.py` carries **no credentials** — no `Authorization` header, no token parameter, no `AUTH_*` / `KEYCLOAK_*` reference
- [ ] Timeouts are read **per call** from `ui.runtime_settings`, never captured at import
- [ ] Step 11: every path in A resolves in B; response shapes match for all A endpoints; orphans listed and reviewed (not necessarily zero); **no artifact left behind**
- [ ] Step 12: 4 and 12 concurrent requests all complete with **2xx** responses; no 5xx or timeouts under concurrent load
- [ ] `grep -rn "app\.main\|uvicorn app.main" CLAUDE.md DEVELOPER_QUICK_START.md` → no matches
- [ ] `grep -rn "docker compose logs app\|docker compose exec app\|docker compose restart app" USER_GUIDE.md DEVELOPER_QUICK_START.md scripts/setup.sh` → no matches
- [ ] `grep -n "Three separately\|three-layer" CLAUDE.md` → no matches
- [ ] `grep -n "dash_app" CLAUDE.md` → no matches
- [ ] `grep -n "app:8000" .env.example CLAUDE.md` → no matches
- [ ] `grep -n "ASGI middleware is the only mechanism" docs/design/authn-authz-design.md` → no matches
- [ ] `grep -n "WSGIMiddleware\|a2wsgi" docs/design/authn-authz-design.md` → no matches
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
  Report the actual per-file list rather than working around it. The two handler
  files in Scope (`context_menu.py`, `expansion.py`) are expected to contribute
  **zero** call sites — their 41 siblings' `requests.exceptions` clauses are
  counted by the separate grep, not this one.
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
- **A migrated call site's handler must distinguish a transport failure (timeout,
  connection refused) from an HTTP error response.** `ApiError` carries only
  `status_code`; `requests.exceptions.Timeout` and `ConnectionError` are no
  longer raised. Converting both branches to `except ApiError` is the expected
  answer; extending `ApiError` with a timeout/connection flag is Plan C's, not
  this plan's. Report the site instead of extending the type.
- **Step 11's `A ⊆ B` fails.** A UI-called path with no route is a broken page;
  fix the call site, do not add a route to satisfy the audit.
- **Step 12 shows concurrency failures** (5xx, timeouts or dropped connections
  under concurrent load). The worker flags are wrong or the worker class is not
  `gthread`; correct the flags and re-run the functional check. **Do not accept
  the flags as verified because they are in the file.**
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
- **Step 12 checked concurrency functionally.** The gunicorn flags being present
  in the file is not evidence they are effective.
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

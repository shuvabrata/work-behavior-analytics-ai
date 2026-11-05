# Plan 066: A failed service token must fail, not silently degrade

> **Status: DRAFT — for refinement.** Caller behaviour is deliberately left open at
> Step 4; that is the decision this plan exists to surface, not to assume.
>
> **Executor instructions**: Follow this plan step by step. Run every verification
> command and confirm the expected result before moving on. If anything in "STOP
> conditions" occurs, stop and report — do not improvise.
> Do **not** commit or push. Do not update `plans/README.md` — the reviewer
> maintains the index.

## Status

- **Priority**: P1
- **Effort**: **M**
- **Risk**: MED (changes startup and failure behaviour in three long-running processes)
- **Depends on**: 055 (service tokens) — **DONE**, `7698f1e7`
- **Category**: auth / correctness
- **Planned at**: commit `781c4d1a`, 2026-11-05, branch `feature/authn-doc`

## The defect

`fetch_runtime_snapshot()` (`src/common/runtime_settings/client.py:51-55`) catches
`ServiceTokenError` and **sends the request anyway, without an `Authorization`
header**:

```python
try:
    request_kwargs["headers"] = {"Authorization": f"Bearer {get_service_token()}"}
except ServiceTokenError:
    logger.warning(f"Service token unavailable for client_id={client_id} — fetching runtime snapshot unauthenticated")
```

`/api/v1/settings/runtime-snapshot` is granted `user`, so the unauthenticated call
returns `401`. That `401` is caught by the `RequestException` branch at `:64-65`,
which logs **"Runtime settings API unreachable"** — a second, false diagnosis, since
the API was reachable and refused. Line `:72` then returns `RuntimeConfig()`: every
setting at its environment or code default.

So a credential failure produces:

1. a wrong log line naming the wrong cause,
2. a process that keeps running on settings nobody chose,
3. no signal to the operator that the service credential is broken.

The environment fallback itself is not the defect. It exists for a CLI utility run
outside Compose, where there is no API to reach. It must not double as a bypass for
a failed credential.

### The precedent that proves it

The UI hit this exact bug and routed around it. `src/ui/runtime_settings.py:89-100`
carries the reasoning in a docstring:

> *"The shared `common.runtime_settings.client.fetch_runtime_snapshot` helper is no
> longer used here: it authenticates with a **service** token, and the UI container
> holds no `KEYCLOAK_*` environment, so that call would always go out unauthenticated
> — and once plan 057 requires a credential on the snapshot route, silently stop
> refreshing with no error and no broken page."*

The UI was fixed by not calling the helper. The producers and consumer call it, and
are still exposed.

### Scope of the exposure

| Call site | Context | Effect today |
|---|---|---|
| `src/connectors/producers/daemon_common.py:549` | `run_daemon` startup | daemon runs on defaults |
| `src/connectors/producers/daemon_common.py:660` | scan child startup | scan runs on defaults |
| `src/connectors/producers/daemon_common.py:707` | test child startup | test runs on defaults |
| `src/connectors/producers/daemon_common.py:138` | live settings listener | refresh is a silent no-op |
| `src/connectors/consumers/main.py:207` | consumer startup | consumer runs on defaults |
| `src/connectors/consumers/main.py:217` | live settings listener | refresh is a silent no-op |

The listener call sites (`:138`, `:217`) are the worst shape: they fire on a
RabbitMQ `settings.changed` event, log an info line that settings were applied, and
actually apply defaults.

### What the design document now says

`docs/design/authn-authz-design.md` → `### Service accounts` was corrected on
2026-11-05 to state the intended rule:

> Authentication failure is fatal to the call, not something the caller papers over.
> A runtime-settings read therefore propagates the failure rather than substituting
> defaults. Command-status reporting is the exception — a failed update is logged and
> dropped.

**The document is currently ahead of the code.** This plan closes that gap.

## Design decisions

### D1 — The client stops swallowing the auth failure

`fetch_runtime_snapshot` must not attempt an unauthenticated request. On
`ServiceTokenError` it raises rather than falling back.

The signature changes to make the failure part of the contract. Preferred shape:

```python
def fetch_runtime_snapshot(api_base_url: str, timeout: int = 10) -> RuntimeConfig:
    """...
    Raises:
        ServiceTokenError: A service credential could not be obtained. This is a
            configuration or availability fault and is never retried unauthenticated.
        RuntimeSettingsUnavailableError: The API was unreachable or returned data
            that could not be parsed; the caller may substitute environment defaults.
    """
```

Two distinct failures, two distinct types. The second preserves the existing
unreachable-API fallback for the CLI case; the first does not.

**Alternative considered and rejected:** keeping a single function and returning
`None`/`RuntimeConfig()` on auth failure. It moves the decision to every caller
silently — which is the current bug in a different shape.

### D2 — The fallback becomes explicit, not implicit

Today line `:72` falls back for *any* failure. After this change a caller must ask
for the fallback by catching `RuntimeSettingsUnavailableError` itself. A caller that
does not catch it fails loudly, which is the safe default.

The CLI case that motivated the original fallback should opt in explicitly. Identify
that caller during Step 1 — if none exists in `src/`, say so in the execution record
and the fallback has no in-repo consumer; consider deleting the fallback path rather
than preserving it for a hypothetical.

### D3 — Status reporting stays best-effort (**operator ruling, 2026-11-05**)

`_update_status` (`daemon_common.py:347-357`) already logs and drops on failure.
That is correct and **must not change**: a lost status PATCH degrades the Recent
Actions view but does not make the scan's behaviour incorrect. Do not add a fallback,
and do not make it fatal.

This asymmetry is now stated in the design doc and is the intent of this plan.

## What is deliberately NOT decided here

**What each caller does when the snapshot cannot be fetched.** Failing a scan is a
behaviour change with operational consequences, and the right answer differs by
caller. Step 4 enumerates the options and requires an operator decision before any
code is written. Do not pre-empt it.

## Scope

**In scope:**
- `src/common/runtime_settings/client.py`
- `src/connectors/producers/daemon_common.py` (call sites only)
- `src/connectors/consumers/main.py` (call sites only)
- `tests/test_settings_client.py`
- `tests/test_runtime_settings_client_auth.py`
- `docs/design/authn-authz-design.md` — only if the implementation diverges from what
  it now states

**Out of scope:**
- `src/ui/runtime_settings.py` — already correct, see the precedent above
- `_update_status` and status reporting generally
- `common.auth.service_token` itself, unless Step 1 finds its own defect
- Any change to the API's grants or the runtime-snapshot endpoint

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Unit tests | `pytest -m unit tests -q` | baseline **2627 passed, 2 skipped, 0 failed** at `781c4d1a`; report observed |
| Targeted | `pytest -m unit tests/test_settings_client.py tests/test_runtime_settings_client_auth.py -q` | all pass |
| Typecheck | `mypy src/` | exit 0 |
| Lint | `pylint src --score=y` | ≥ 9.0 |
| Security | `bandit -c .bandit.yml -r src/ -lll` | exit 0 |

## Steps

### Step 1: Establish the current behaviour and find the CLI caller

Run these and record the actual output:

```
grep -rn "fetch_runtime_snapshot" --include="*.py" src/ scripts/ | grep -v "def fetch_runtime_snapshot"
grep -rn "runtime_settings" --include="*.py" scripts/
```

Answer explicitly in the execution record:

1. Every call site, and whether it is a long-running service, a child process, or a
   CLI command.
2. **Is there a CLI or script caller relying on the environment fallback?** The
   original docstring names "CLI utilities that may run outside Docker Compose". If
   no such caller exists in-repo, the fallback has no consumer and D2's "opt in
   explicitly" has nothing to preserve — report that, and the plan's Step 3 shrinks
   to deleting the fallback.
3. Whether `get_service_token()` itself has a silent-degradation defect. Read
   `src/common/auth/service_token.py` fully. It has a backoff window; confirm a
   failure inside the window still raises rather than returning a stale token.

> **🚦 MANUAL GATE 1** — operator confirms the call-site inventory and the answer to
> question 2. Wait for `PASS`.

---

### Step 2: Split the two failure types in the client

Introduce `RuntimeSettingsUnavailableError` and make `fetch_runtime_snapshot`:

- call `get_service_token()` **outside** any `try` that would swallow it,
- let `ServiceTokenError` propagate,
- raise `RuntimeSettingsUnavailableError` only for transport failure and unparseable
  data.

Keep the existing warning-and-fallback behaviour available to callers that catch the
new exception — but the function itself no longer substitutes defaults.

**Verify** the module imports cleanly and nothing else in `src/` imports the removed
behaviour:

```
grep -rn "RuntimeConfig()" --include="*.py" src/ | grep -v "config.py"
python -c "import common.runtime_settings.client"
```

> **🚦 MANUAL GATE 2** — operator reviews the new signature and the error taxonomy.
> Wait for `PASS`.

---

### Step 3: Update the tests to assert the new contract

`tests/test_runtime_settings_client_auth.py:40-53`
(`test_token_failure_still_sends_request_without_header`) asserts the **defective**
behaviour and must be replaced, not adjusted. It currently asserts:

- `config` is still returned,
- `mock_get.call_count == 1` — i.e. the request was sent,
- `"headers" not in mock_get.call_args[1]` — i.e. it went unauthenticated.

Replace with a test asserting `ServiceTokenError` propagates and **`requests.get` is
never called**. That second assertion is the one that matters: it proves no
unauthenticated request was attempted.

Also add a test that `RuntimeSettingsUnavailableError` is raised for a connection
error and for unparseable data, kept distinct from the auth failure.

**Verify:**

```
pytest -m unit tests/test_runtime_settings_client_auth.py tests/test_settings_client.py -q
grep -n "unauthorized\|without_header\|unauthenticated" tests/test_runtime_settings_client_auth.py   # → no matches for the old assertions
```

> **🚦 MANUAL GATE 3** — operator confirms the old test is genuinely replaced rather
> than weakened. Wait for `PASS`.

---

### Step 4: **OPERATOR DECISION** — caller behaviour

Present these and wait. **Do not write caller code before an explicit choice.**

| Option | Behaviour on auth failure | Trade-off |
|---|---|---|
| **A — Fail the scan** | The child process exits non-zero; `_update_status` records `failed` with a clear message. | A broken credential is visible immediately. A scan the operator asked for does not run at all. |
| **B — Refuse to start the daemon** | `run_daemon` exits before opening RabbitMQ. | Loudest signal; the producer is visibly down. Blast radius is the whole producer, including scans that would not have needed settings. |
| **C — Retry with backoff, then fail** | Bounded retries before A or B. | Tolerates a Keycloak blip. More moving parts; needs a bound and a total-time budget. |
| **D — Fail loudly but continue on defaults** | Log at ERROR and continue. | Operator signal without stopping work. Contradicts the ruling that this must not be a silent fallback — only acceptable if the log is genuinely loud and the state is reported. |

Sub-decisions to settle with the choice:

1. Does the daemon-parent case (`:549`) differ from the scan-child case (`:660`)?
   The parent starts once; the child per scan.
2. For the listener call sites (`:138`, `:217`) — on a failed refresh, should the
   cache **keep its current values** (as the UI does) or reset to defaults? Keeping
   is almost certainly right: defaults on a transient blip would be the same bug in
   miniature. Confirm.
3. What does the operator see? A log line only, or the command's `error_message`?

> **🚦 MANUAL GATE 4 — OPERATOR DECISION.** Record the chosen option and the three
> sub-decisions verbatim. Wait for `PASS`.

---

### Step 5: Implement the caller behaviour

Apply the Step 4 decision minimally, at each of the six call sites. The listener
sites get the "keep current values" behaviour confirmed in Step 4.2.

No comments describing what the code does; only a "why" where the choice is
non-obvious.

**Verify:** the chosen behaviour is observable in a targeted test for at least one
caller — do not rely on reading the code.

> **🚦 MANUAL GATE 5** — operator confirms the implementation matches the Step 4
> record exactly.

---

### Step 6: Full regression

```
pytest -m unit tests -q
mypy src/
pylint src --score=y
bandit -c .bandit.yml -r src/ -lll
```

Baseline at `781c4d1a` is **2627 passed, 2 skipped, 0 failed**. Any test count change
must be explainable by the tests added or replaced in Step 3.

> **🚦 MANUAL GATE 6** — operator confirms all four gates and the test-count delta.

---

## Test plan

The behavioural proof is that **no unauthenticated request is attempted**. Every test
asserting a fallback must distinguish "the API was unreachable" from "the credential
failed", because conflating them is the defect.

The producer/consumer call-site tests are the weaker half: they need the transport
stubbed, so they prove the branch taken, not that a real 401 propagates. State that
limitation rather than overclaiming.

## Done criteria

- [ ] `fetch_runtime_snapshot` raises `ServiceTokenError` on credential failure and never sends an unauthenticated request
- [ ] Transport failure and parse failure are a distinct exception type
- [ ] `test_token_failure_still_sends_request_without_header` is replaced by a test asserting no request is made
- [ ] Step 4's decision is recorded verbatim and implemented at all six call sites
- [ ] Listener call sites keep current cache values on a failed refresh
- [ ] `_update_status` is unchanged
- [ ] `pytest -m unit tests -q` = 2627 + the added tests, 0 failed; mypy, pylint ≥ 9.0, bandit all pass
- [ ] No source file outside the Scope list is modified

## STOP conditions

Stop and report if:

- Step 1 finds a real in-repo CLI caller whose environment fallback is load-bearing
  in a way this plan would break.
- `get_service_token()` turns out to return a stale token instead of raising within
  its backoff window — that is a second defect and belongs to its own change.
- Step 4's options cannot be decided without a broader operational decision about
  what a producer should do when its settings are unavailable.
- Any existing test beyond the two named files depends on the swallow-and-degrade
  behaviour.
- The design document and this plan disagree about what the code should do. The
  operator's 2026-11-05 ruling in `### Service accounts` is the intent; report a
  conflict rather than resolving it silently.

## Maintenance notes

- **The two failure modes are not interchangeable.** A test that asserts "returns
  defaults" without saying *why* the fetch failed will let this bug back in.
- The UI already routes around this helper for the same reason. If a third consumer
  appears that legitimately has no service credential, it should follow the UI's
  pattern — call the API with its own credential — rather than resurrecting the
  unauthenticated fallback.
- Related: `docs/design/authn-authz-design.md` → `### Service accounts`.

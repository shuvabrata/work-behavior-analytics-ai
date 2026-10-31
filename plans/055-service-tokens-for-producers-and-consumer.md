# Plan 055: Give producers, the consumer, and the runtime-settings client a service token

> **Executor instructions**: This plan is a **single step** — every code change is
> described in "The step" below, and you make them all before running anything.
> Then run **Automated verification** to completion. Only then hand back for the
> **Manual gates**, which are all at the end.
>
> Do not improvise. If anything under "STOP conditions" occurs, stop and report.
> When done, update the status row in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 94b57de3..HEAD -- src/common/ src/connectors/producers/ src/connectors/consumers/main.py docker-compose.yml deploy/keycloak/realm-wba.json.template requirements.*.txt tests/producers/`
> Any mismatch against "Current state" is a STOP condition.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: MED
- **Depends on**: plans/054
- **Category**: security
- **Planned at**: commit `94b57de3`, 2026-10-31
- **Design reference**: `docs/design/authn-authz-design.md`, "Service accounts"
- **This is step 3 of 9** in the Plan C sequence.
- **Status**: **DONE** — executed 2026-10-31 in the live tree on
  `feature/plan-c-keycloak`, left **uncommitted** at the operator's instruction.
  Three execution rounds (a plan-defect STOP, the scoped-test fix, and the
  operator's import-policy reversal). Gates: 2457 unit passed / 0 failed /
  2 skipped, mypy exit 0, pylint 9.68, bandit exit 0, `docker compose config -q`
  exit 0. **One criterion is operator-gated and still outstanding** — the live
  token check (see Done criteria). Nothing is enforced yet; `/api/health` and
  every `/api/v1` route remain open, which is 057's job.

## Why this matters

The API will accept **bearer tokens only** (plan 057). Producers and the signal
consumer call `/api/v1` over HTTP today with **no credentials at all** — so the
moment enforcement switches on, command polling, command-status reporting,
connector-config fetching, and runtime-settings fetches all start returning
`401` (or `403`). Command-status reporting is what feeds the Recent Actions UI,
and the design says explicitly it does **not** degrade gracefully, which is why
this must land **before** enforcement.

This step adds one shared client-credentials helper, wires it into every machine
call site, and resolves the two questions 054 deliberately left open (the service
token's `aud`/`azp` and its authorization). **Nothing is enforced yet**, so the
work is additive and provable: the helper fetches a real token from the running
Keycloak (plan 053) and the callers start sending it. A `401` cannot occur until
plan 057.

## Current state

**`src/common/runtime_settings/client.py`** — the snapshot fetcher used by all
three producers **and** the consumer. It takes no credential:

```python
    url = f"{api_base_url.rstrip('/')}/api/v1/settings/runtime-snapshot"
    try:
        resp = requests.get(url, timeout=timeout)
        resp.raise_for_status()
        data: dict[str, Any] = resp.json()
        config = RuntimeConfig(**data)
```

It intentionally degrades to `RuntimeConfig()` defaults on any failure. That
fallback **stays** — a transient token failure must not break a scan.

**`src/connectors/producers/daemon_common.py`** — three API helpers, each
opening a fresh `httpx.Client` with no auth header:

- `_reconcile_startup_orphans` (`:291`): `GET {_api_base()}/api/v1/commands/`
- `_update_status` (`:323`): `PATCH {_api_base()}/api/v1/commands/{id}/status`
- `_get_command_status` (`:341`): `GET {_api_base()}/api/v1/commands/{id}`

Plus one runtime-settings call at `:137`,
`runtime_cache.refresh(fetch_runtime_snapshot(_api_base()))`. Base URL comes from
`_api_base()` (`:174`), which reads `API_SERVER` lazily.

**Three more machine call sites the original plan missed** — verified live, all
unauthenticated, all requesting secrets:

- `src/connectors/producers/github/github_config.py:19-29`
- `src/connectors/producers/jira/jira_config.py:21-29`
- `src/connectors/producers/confluence/confluence_config.py:16-24`

Each does `requests.get(f"{api_server}/api/v1/connectors/{type}/configs",
params={"include_secrets": "true"}, timeout=10)`. Enabled in practice:
`CONFIGURATION_SOURCE=SERVER` is set in `.env:108` and reaches the producer
containers through their `env_file` (confirmed in-process:
`docker compose exec -T github-producer printenv CONFIGURATION_SOURCE` → `SERVER`).

**`src/connectors/consumers/main.py`** — at `:206` (startup) and `:217` (every
settings event) it calls `fetch_runtime_snapshot(api_base)`; no credential path.

**The four connector images** each `COPY src/connectors/` + `COPY src/common/`
(`Dockerfile.github-producer:17-18`, `.jira-producer:16-17`,
`.confluence-producer:16-17`, `.signal-consumer:17-18`). So anything added under
`src/common/` is already in every image — **no Dockerfile change is needed**.

**Each of those four services already has `env_file: .env`**
(`docker-compose.yml:299-300, 322-323, 345-346, 369-370`), so they already
receive `KEYCLOAK_SERVICE_CLIENT_SECRET` (present, non-placeholder, in `.env`).
They do **not** receive `KEYCLOAK_INTERNAL_URL`: it is absent from `.env`, and
`docker compose config | grep -c 'keycloak:8080/auth/realms/wba'` → **0**. The
API gets that value from `domain/settings.py`'s default, not from compose.

**`deploy/keycloak/realm-wba.json.template`** — `wba-internal` (`:39-52`) declares
**no `protocolMappers`**, and `service-account-wba-internal` (`:91-95`) holds only
`wba-service`. Consequently the real token carries **no `aud` claim** and
`azp=wba-internal`, which `src/app/auth/tokens.py:121-128` rejects (it requires
`aud ⊇ wba-web` and `azp == wba-web`). 054 recorded this and handed the decision
to this plan — see "Decisions taken".

**`requirements.jira-producer.txt` / `requirements.confluence-producer.txt`** do
not list `requests`; both images resolve it transitively via
`atlassian-python-api` (`requests 2.34.2` importable in all four images today —
verified live).

**Baseline** (verified on `94b57de3`): `pytest -m unit tests -q` → **2437 passed,
2 skipped**; `pylint src --score=y` → 9.68.

### Repo conventions that apply

- Type hints everywhere; `mypy src/` strict. `from common.logger import logger`;
  never `print()`.
- New shared code goes in `src/common/` (already copied into all four images).
- **Never log a token or a client secret.** Log the client id and status only.
- Tests carry `pytestmark = pytest.mark.unit`.
- Do **not** commit or push unless asked.

## Decisions taken (do not re-litigate)

| Subject | Decision |
|---|---|
| Service-token audience | Add an `oidc-audience-mapper` to `wba-internal` so its token carries `aud=["wba-internal"]`, and record that the validator must accept **either** configured client. Rejecting a token with no `aud` stays correct; the fix is to make the token carry one. |
| `azp` policy | The validator must accept `azp ∈ {wba-web, wba-internal}` and require the matched audience to equal `azp`. The `src/app/auth/tokens.py` edit itself is **plan 057's** (it owns that file); this plan pins the policy in a test and in the amendment below. |
| Producer config fetches | **In scope.** All three send the service token. `include_secrets=true` must become admin-**or-service** — see "Required amendment to plan 057". |
| Required env vars | `KEYCLOAK_INTERNAL_URL` and `KEYCLOAK_SERVICE_CLIENT_ID` are added to compose explicitly; `KEYCLOAK_SERVICE_CLIENT_SECRET` rides the existing `env_file: .env`. **No secret is ever given a default value.** |
| `depends_on: keycloak` | **Not added** to any connector. The helper is lazy and a Keycloak that is not up must degrade, not block startup. |
| 401 retry | One retry, **uniformly** for all three daemon helpers (the original plan's two-of-three split was arbitrary). Never a loop. |
| Failed-token behaviour | A failed fetch is cached for 30s (see "The step"), so a Keycloak outage costs at most one attempt per 30s per process rather than one per API call. |

## Required amendment to plan 057 (carry this forward)

`plans/057` currently decides `include_secrets=true` → **admin only**, and its
expected-status matrix asserts `403` for the service token. That makes the three
producer config fetches fail permanently once enforcement lands. **057 must be
amended in the same change that enforces:**

- Decision table row `include_secrets` → "admin **and service**; every other
  principal is rejected".
- Router `connectors` row → `/test` and writes stay admin-only;
  `include_secrets=true` accepts `require_any("admin", "service")`.
- `tests/test_connectors_secrets_gating.py` → service token + `include_secrets=true`
  expects **200**, not 403.

Rationale: the producers legitimately need the credentials of the connectors they
serve, and a machine credential that already holds `POST`-free graph writes is the
right holder. It does **not** widen `wba-service` anywhere else — the four-endpoint
rule stands.

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Unit tests | `pytest -m unit tests -q` | ≥ 2437 + new, 0 fail |
| Typecheck | `mypy src/` | exit 0 |
| Lint | `pylint src --score=y` | ≥ 9.0 |
| Security scan | `bandit -c .bandit.yml -r src/ -lll` | exit 0 |
| Compose syntax | `docker compose config -q` | exit 0 |
| Token fetch (live) | `docker compose exec -T github-producer python -c "from common.auth.service_token import get_service_token; print(len(get_service_token()))"` | a number > 0 |

## Scope

**In scope**:
- `src/common/auth/__init__.py` (create)
- `src/common/auth/service_token.py` (create) — the cached client-credentials helper.
- `src/common/runtime_settings/client.py` — attach a token, keep the fallback.
- `Dockerfile.ui` — add `COPY src/common/auth/ ./common/auth/` (step 5b).
- `src/connectors/producers/daemon_common.py` — one authed-request helper, three call sites.
- `src/connectors/producers/{github/github_config,jira/jira_config,confluence/confluence_config}.py` — send the token.
- `src/connectors/consumers/main.py` — verify no code change is needed.
- `deploy/keycloak/realm-wba.json.template` — the `wba-internal` audience mapper.
- `docker-compose.yml` — `KEYCLOAK_INTERNAL_URL` + `KEYCLOAK_SERVICE_CLIENT_ID` on the four connector services.
- `.env.example` — document `KEYCLOAK_INTERNAL_URL` for connector processes.
- `requirements.jira-producer.txt`, `requirements.confluence-producer.txt` — pin `requests`.
- `tests/test_service_token.py`, `tests/test_runtime_settings_client_auth.py`, `tests/test_daemon_common_auth.py` (create)
- `tests/producers/{github,jira,confluence}/test_*_main.py` — update the config-fetch call assertion.
- `tests/test_settings_client.py` — **added to scope after the first execution
  round** (see "Scope correction" below): the 5 degrade tests must tolerate the
  new token warning without weakening their assertion.

**Out of scope** (do NOT touch):
- Any router or dependency — enforcement is plan 057.
- `src/app/auth/tokens.py` — 057 owns it. This plan *pins the policy in a test* only.
- `src/ui/` — the UI has no service credential and must never take this path (see
  "Cross-plan handoff to 056").
- `src/app/scheduler.py` — calls `create_and_publish_command()` in-process, never
  over HTTP. No token needed.
- `src/app/api_main.py`.
- `.env` — never write real secrets into the working tree; document names only.

## The step

Make **all** of the following changes, then move to Automated verification.

### 1. `src/common/auth/__init__.py` (create)

```python
"""Machine-to-machine authentication for connector processes."""

__all__ = ["ServiceTokenError", "get_service_token", "invalidate_service_token"]

from common.auth.service_token import (
    ServiceTokenError,
    get_service_token,
    invalidate_service_token,
)
```

### 2. `src/common/auth/service_token.py` (create)

Contract:

- `get_service_token() -> str` returns a valid access token from a **process-wide
  cache**, fetching only when the cached token is within 60s of expiry. Refresh is
  lazy: importing the module performs no I/O.
- `invalidate_service_token() -> None` drops the cache **and the failure backoff**,
  so a `401` can force one immediate retry with a fresh token.
- `ServiceTokenError(Exception)` is the only failure type callers catch. Callers
  decide whether to degrade.
- Configuration comes from `os.environ` using the `os.environ.get(name, default)`
  style `_api_base()` already uses:
  - `KEYCLOAK_INTERNAL_URL` — default `http://keycloak:8080/auth/realms/wba`
    (the realm base; the token path is appended — do **not** re-derive it from
    `KEYCLOAK_ISSUER`, which is the browser-facing URL).
  - `KEYCLOAK_SERVICE_CLIENT_ID` — default `wba-internal`.
  - `KEYCLOAK_SERVICE_CLIENT_SECRET` — **no default.** Empty ⇒ `ServiceTokenError`
    naming the client id. A committed default would ship a credential in git and,
    worse, would fail as a Keycloak `401` that looks like a network problem.
- Token request: `POST {KEYCLOAK_INTERNAL_URL}/protocol/openid-connect/token`,
  `grant_type=client_credentials`, form-encoded, via `requests`, `timeout=10`.
  Store `expires_at = time.monotonic() + expires_in - 60`.
- **Failure backoff (30s):** on failure, record `expires_at = monotonic() + 30`
  with no token, so a Keycloak outage costs one attempt per 30s per process
  instead of one 10s-timeout attempt per command-status PATCH. This is the
  mitigation for the producer daemons being multi-threaded and chatty.
- **Thread safety:** a `threading.Lock` with a double-checked fast path, so a
  burst of calls issues one request. Hold module state in a small dataclass
  instance rather than module globals — `mypy` strict and `pylint`'s
  `global-statement` both object to the alternative.
- **Logging:** one WARNING per failed fetch, naming the client id and, for an HTTP
  failure, the status code. **Never** the secret and **never** `resp.text` — the
  body may echo the request.

Target shape:

```python
class ServiceTokenError(Exception):
    """A service token could not be obtained from Keycloak."""

def get_service_token() -> str:
    """Return a cached, unexpired ``wba-internal`` access token."""

def invalidate_service_token() -> None:
    """Discard the cached token and failure backoff, so the next call re-fetches."""
```

### 3. `src/common/runtime_settings/client.py`

- Import `get_service_token` / `ServiceTokenError` at **module level**, with
  `from common.auth import ServiceTokenError, get_service_token`, placed with the
  other first-party imports (next to `from common.logger import logger`). **No**
  `import-outside-toplevel`, **no** lazy import, **no** `ModuleNotFoundError`
  guard — see "Import policy" under step 5. `common.auth` imports only
  `requests`, `os`, `threading`, `time`, `dataclasses` and `common.logger`, and
  does not import back into this module, so there is no cycle.
- **This makes `Dockerfile.ui` a hard dependency of this step** — see step 5b.
  Without that COPY, the UI container dies at import of this module.
- Fetch the token in its **own** `try`. On `ServiceTokenError`, log a distinct
  `logger.warning` naming the client id and send the request **without** the
  header. Do **not** short-circuit to `RuntimeConfig()` on a token failure: the
  request still has a real chance pre-057, and post-057 the resulting `401` is
  already covered by the existing `RequestException` path. This keeps today's
  behaviour byte-identical.
- Add `headers={"Authorization": f"Bearer {token}"}` when a token was obtained.
- Leave the existing `except` clauses and the degrade-to-`RuntimeConfig()`
  behaviour untouched. Do **not** print or log the token.
- Exactly **one** `Authorization` occurrence in the file.

> **Scope correction (added 2026-10-31, after the first execution round).**
> `tests/test_settings_client.py` (`.venv`-visible, pre-existing, tracked since
> `b0571c30`) was **omitted from this plan's scope list**. Its five
> `TestFetchRuntimeSnapshot.test_falls_back_on_*` tests assert
> `logger.warning` is called **exactly once**. With this step in place the
> token-unavailable path emits a *second* warning, so all five fail on
> `mock_warn.assert_called_once()`. This is a **plan defect**, not an executor
> error: step 3 mandates the warning and this plan's own
> `tests/test_runtime_settings_client_auth.py` asserts it, while a file the plan
> never scoped forbids it. `tests/test_settings_client.py` is therefore **in
> scope**. The fix must **strengthen**, not weaken, those tests: they must assert
> the API-unreachable warning is among the calls **and** that the function still
> degrades. Do **not** delete an assertion, switch to `assert_called()`, or
> suppress the token warning. Recommended shape — `.env` is not guaranteed to
> carry the service client id when the app test suite runs, so pin the
> expectation explicitly:
> ```python
> with patch("common.runtime_settings.client.requests.get") as mock_get:
>     ...
>     with patch("common.runtime_settings.client.logger.warning") as mock_warn:
>         config = fetch_runtime_snapshot("http://app:8000")
>
> assert isinstance(config, RuntimeConfig)
> assert config.HTTP_REQUEST_TIMEOUT == 60
> messages = [call.args[0] for call in mock_warn.call_args_list]
> assert any("API unreachable" in message for message in messages)
> ```
> (`mock_warn.call_args_list` is the real `unittest.mock` attribute; do not
> invent a `call_args_list`-looking helper.) `test_strips_trailing_slash` already
> passes and must keep passing **without** modification — the executor achieved
> that by attaching the header only when a token was obtained, which is the
> behaviour this plan's step 3 wording mandates ("add `headers=…` when a token
> was obtained"). Keep it that way.

### 4. `src/connectors/producers/daemon_common.py`

Add `from common.auth import ServiceTokenError, get_service_token` and
`from common.auth import invalidate_service_token` at **module level**, with the
other `common.*` imports (next to `from common.logger import logger`). Remove the
two `# pylint: disable=import-outside-toplevel` comments the first execution
round added inside the helpers, and delete the in-function imports.

Then add one module-local pair rather than repeating headers and retry logic:

```python
def _auth_headers() -> dict[str, str]:
    """Return an Authorization header for the app API, or {} if unavailable.

    A token failure must not stop status reporting: the request then goes out
    unauthenticated and the caller's existing ``except`` block handles the
    result.
    """

def _api_request(method: str, url: str, **kwargs: Any) -> httpx.Response:
    """Send an authenticated request, retrying once with a fresh token on 401."""
```

- `_auth_headers()` catches `ServiceTokenError`, logs one WARNING, returns `{}`.
- `_api_request` opens one `httpx.Client(timeout=10)`, sends with
  `headers=_auth_headers()`, and **on a 401 only** calls
  `invalidate_service_token()` and repeats the request **once**. No loop, and no
  third attempt.
- Route all three helpers through it, replacing their inline `httpx.Client`
  blocks: `_reconcile_startup_orphans` (`client.get(url, params=...)`),
  `_update_status` (`client.patch(url, json=...)`), `_get_command_status`
  (`client.get(url)`).
- **Do not change their error handling.** Each keeps its existing
  `except (httpx.HTTPError, ValueError, AttributeError)` log-and-continue (or
  return-`None`) shape, and `resp.raise_for_status()` stays in the caller. The
  `logger.debug` lines in `_update_status` stay as they are.
- The `fetch_runtime_snapshot(_api_base())` call at `:137` needs no edit — step 3
  handles it.

### 5. The three producer config fetches

In each of `github_config.py`, `jira_config.py`, `confluence_config.py`, keep the
URL and params as they are and add the auth header via a **module-level import**.
`common.auth` pulls in only `requests`, `os`, `threading`, `time` and
`common.logger` — all already present in these modules' dependency closure — and
it does **not** import back into `connectors` or `common.runtime_settings`, so
there is no circular dependency and no reason to defer it.

```python
from common.auth import ServiceTokenError, get_service_token
```

Place it with the other module-level imports, in the repo's pylint import order
(stdlib, third-party, then first-party `common.*` — `common.logger` is already
there, put this next to it).

Then, inside the function, keep the header construction:

```python
    headers: dict[str, str] = {}
    try:
        headers = {"Authorization": f"Bearer {get_service_token()}"}
    except ServiceTokenError:
        logger.warning("Service token unavailable — fetching connector config unauthenticated")
```

**The `try`/`except ServiceTokenError` stays at the call site** — it is not a
deferred-import workaround. It is the deliberate degradation policy: a Keycloak
outage must not stop a scan. Only *import* failures must be allowed to surface
loudly (see "Import policy" below).

Pass `headers=headers` to the existing `requests.get`. Keep
`params={"include_secrets": "true"}` and keep the existing
`raise` on `requests.exceptions.RequestException`. Rationale for adding a
credential to a route that is not yet enforced: the header is ignored today, so
the change is inert until 057 — and it is exactly the change that keeps the
producer working *at* 057.

#### Import policy (applies to every import this plan adds)

**No implicit-optional handling of imports.** A `ModuleNotFoundError` must
propagate — it means the deployment is broken and the operator must see it, not
a silently unauthenticated request. This is the opposite of the token-failure
policy above, and the two must not be conflated:

| Failure | Behaviour | Mechanism |
|---|---|---|
| `ServiceTokenError` (no secret, Keycloak down, bad response) | **degrade** — send unauthenticated, log one warning | `try`/`except ServiceTokenError` at the call site |
| `ModuleNotFoundError` (file not deployed into the image) | **fail loudly** — propagate | nothing; a module-level import raises naturally |

So: **no `import-outside-toplevel` for `common.auth` anywhere in this plan**, and
no `try`/`except ModuleNotFoundError` / `ImportError` wrapper around it. The
`# pylint: disable=import-outside-toplevel` comments the first execution round
added to `daemon_common.py` and `client.py` are to be **removed** along with the
comments that motivate them.

### 5b. `Dockerfile.ui` — the UI image must carry `common.auth`

`src/common/runtime_settings/client.py` is shared with the UI
(`src/ui/runtime_settings.py` imports it via `common.runtime_settings`), and
`Dockerfile.ui` copies `src/common/` **selectively**:

```
COPY src/common/__init__.py ./common/
COPY src/common/logger.py ./common/
COPY src/common/runtime_settings/ ./common/runtime_settings/
```

`src/common/auth/` is not in that list. With a module-level import in `client.py`
this becomes fatal at import time in the UI container, which is the intended
loud failure — but the fix is to **ship the module**, not to defer the import.
Add to `Dockerfile.ui`, immediately after the `runtime_settings/` COPY:

```dockerfile
COPY src/common/auth/ ./common/auth/
```

Then update the explanatory comment block above those COPY lines if it enumerates
what is deliberately excluded — `common/auth/` is now intentionally included, and
the comment currently implies the list is exhaustive. Keep `command_n_control/`
and `messaging/` excluded; do not widen this to `COPY src/common/ ./common/`.

**Why this is safe:** the UI will never *hold* the service secret. `Dockerfile.ui`
already does not copy `.env` and the UI service has no `KEYCLOAK_*` environment,
so `common.auth.service_token` in that container can only ever raise
`ServiceTokenError` ("no client credential configured") and degrade — which is
exactly today's behaviour. Shipping the module makes the failure a *degrade*
instead of a *crash*; it does not grant the UI a credential. The longer-term fix
(routing the UI's snapshot fetch through `api_client` so it uses the user's
bearer) remains plan 056's job — see the handoff below.

### 6. `deploy/keycloak/realm-wba.json.template`

Add to the **`wba-internal`** client only (`:39-52`), not `wba-web`:

```json
      "protocolMappers": [
        {
          "name": "wba-internal-audience",
          "protocol": "openid-connect",
          "protocolMapper": "oidc-audience-mapper",
          "consentRequired": false,
          "config": {
            "included.client.audience": "wba-internal",
            "id.token.claim": "false",
            "access.token.claim": "true"
          }
        }
      ],
```

This makes the service token's `aud` exactly `["wba-internal"]`, so the validator
has a real audience to check instead of a missing claim. Do **not** add a mapper
to `wba-web`, and do **not** change the `service-account-wba-internal` role grant.

Note for the operator: `--import-realm` does not update an already-imported realm.
Applying this requires recreating the `keycloak` database — the recipe is in
`ADMIN_GUIDE.md` ("To re-seed from the variable instead") and it drops **only**
the derived `keycloak` database. Re-import renders the template with the same
`.env` secret, so no credential changes.

### 7. `docker-compose.yml`

Add to **each** of `github-producer`, `jira-producer`, `confluence-producer`,
`signal-consumer`, under their existing `environment:` block:

```yaml
      KEYCLOAK_INTERNAL_URL: ${KEYCLOAK_INTERNAL_URL:-http://keycloak:8080/auth/realms/wba}
      KEYCLOAK_SERVICE_CLIENT_ID: ${KEYCLOAK_SERVICE_CLIENT_ID:-wba-internal}
```

- Do **not** add `KEYCLOAK_SERVICE_CLIENT_SECRET` with a default. It already
  arrives through each service's `env_file: .env`; a `${VAR:-...}` fallback here
  would put a credential in git.
- Do **not** add `keycloak` to any `depends_on`; leave the existing `api`
  dependency as is.
- `.env.example:181` already declares
  `KEYCLOAK_INTERNAL_URL=http://keycloak:8080/auth/realms/wba`; only its comment
  needs widening from "the API container" to "the API and the connector
  processes". Change no value — in particular, do not add a
  `KEYCLOAK_SERVICE_CLIENT_SECRET` example line with a real-looking default.

### 8. `requirements.jira-producer.txt` and `requirements.confluence-producer.txt`

Add `requests==2.34.2` (the version already resolved in both images). The helper
now depends on it directly; leaving it transitive means a future
`atlassian-python-api` upgrade silently breaks both producers.

### 9. `src/connectors/consumers/main.py`

**No edit.** Confirm by inspection that both call sites pass through step 3, and
that `pytest`/`grep` agree — see Automated verification.

## Cross-plan handoff to 056 (record, do not implement here)

`src/ui/runtime_settings.py:87` reuses `common...fetch_runtime_snapshot`, which
bypasses `src/ui/api_client.py`. The UI container has **no** `KEYCLOAK_*`
environment and no `.env` mount (deliberate — `docker-compose.yml:143-146`), so
post-055 the UI's token fetch fails, logs one warning, and proceeds
unauthenticated. Post-**057** that unauthenticated call meets
`require_any("user","admin","service")` → `401` → silent fall back to defaults,
i.e. the Settings UI would show wrong values.

**Plan 056 must route the UI's snapshot fetch through `api_client` (which carries
the user's bearer) instead of the shared helper.** Add that sentence to 056 when
it is next touched. The UI must **not** be given a service credential.

## Cross-plan observations (record only, fix elsewhere)

- The four connector containers already receive the whole `.env` via `env_file`
  (`OPENAI_API_KEY`, `CONNECTOR_ENCRYPTION_KEY`, … — confirmed in
  `docker compose config`). That predates this plan and is broader than the one
  service secret this plan needs. **Not fixed here** — it belongs to Plan E
  ("Infrastructure surface hardening"). Do not "tidy" it in this change.

## Automated verification

Run every command and confirm the expected result before handing back.

**New test files** (all `pytestmark = pytest.mark.unit`; stub
`common.auth.service_token.requests.post` — never hit Keycloak):

`tests/test_service_token.py`
- first call issues one request; a second call reuses the cache — assert the
  transport was called **exactly once** (not merely that a token came back).
- a token whose `expires_in` puts it inside the 60s margin is refreshed.
- `invalidate_service_token()` forces a re-fetch.
- a non-200 raises `ServiceTokenError`, and with `caplog` at WARNING the response
  body text and the secret appear in **no** log record.
- a non-JSON body, and a JSON body without `access_token`, each raise
  `ServiceTokenError`.
- an empty `KEYCLOAK_SERVICE_CLIENT_SECRET` raises `ServiceTokenError` without
  issuing a request.
- a failure is backed off: two consecutive calls after a failure issue **one**
  request; `invalidate_service_token()` clears the backoff.
- two threads calling concurrently issue **one** request (the lock).

`tests/test_runtime_settings_client_auth.py`
- with a working token, the request carries `Authorization: Bearer <token>`
  (capture through the stub).
- with `ServiceTokenError`, the request is **still sent**, with no `Authorization`
  header, and a warning naming the client id is logged.
- the existing degrade contract is unchanged: an unreachable API still returns
  `RuntimeConfig()` defaults.

`tests/test_daemon_common_auth.py`
- `_auth_headers()` returns the bearer header, and `{}` plus one warning when the
  token raises.
- `_api_request` on a 401 calls `invalidate_service_token` and retries **once** —
  assert the transport saw exactly two calls.
- `_api_request` on a 200 does **not** retry and does **not** invalidate.
- a second 401 is returned, not retried again (three calls never happen).

**Updated test files**: `tests/producers/github/test_github_main.py:50`,
`tests/producers/jira/test_jira_main.py:48`,
`tests/producers/confluence/test_confluence_main.py:63` each assert
`assert_called_once_with(url, params={"include_secrets": "true"}, timeout=10)`.
Add the `headers=` argument to each expectation. This is a **legitimate
signature change**, not accommodation of a broken test: the call site gained a
parameter by design. Any *other* producer test that fails is a STOP condition.

**Also update `tests/test_settings_client.py`** (in scope — see the Scope
correction under step 3): the five `test_falls_back_on_*` degrade tests. Each
must assert the API-unreachable warning is present in `mock_warn.call_args_list`
**and** that the fallback still occurs. Do not weaken them to
`assert_called()`, and do not suppress the new token warning. `test_strips_trailing_slash`
stays untouched and must still pass.

Then:

| Command | Expected |
|---|---|
| `pytest -m unit tests/test_service_token.py tests/test_runtime_settings_client_auth.py tests/test_daemon_common_auth.py -q` | all pass |
| `pytest -m unit tests -q` | ≥ 2437 + new, 0 fail |
| `mypy src/` | exit 0 |
| `pylint src --score=y` | ≥ 9.0 |
| `bandit -c .bandit.yml -r src/ -lll` | exit 0 |
| `docker compose config -q` | exit 0 |
| `grep -c "KEYCLOAK_SERVICE_CLIENT_ID" docker-compose.yml` | `4` |
| `docker compose config \| grep -c "keycloak:8080/auth/realms/wba"` | `4` — four connector services. The API is **not** counted: it takes the value from `domain/settings.py`, not compose. |
| `grep -n "Authorization" src/common/runtime_settings/client.py` | exactly `1` match |
| `grep -rn "Depends(require_" src/app/` | still **no** matches (enforcement is 057) |
| `grep -rn "logger" src/common/auth/service_token.py src/connectors/producers/daemon_common.py src/connectors/producers/*/[a-z]*_config.py \| grep -i "bearer \|secret"` | **no** matches |
| `grep -rn "from common.auth import" src/ --include='*.py'` | every match is at **column 0** — i.e. no indented (local) `common.auth` import survives anywhere |
| `grep -rn "import-outside-toplevel" src/common/runtime_settings/client.py src/connectors/producers/daemon_common.py` | **no** matches |
| `grep -c "COPY src/common/auth/" Dockerfile.ui` | `1` |
| `PYTHONPATH=src python -c "import common.runtime_settings.client as c; print(c.fetch_runtime_snapshot('http://127.0.0.1:1').HTTP_REQUEST_TIMEOUT)"` | prints the default — the fallback survives with no network and no Keycloak |
| `docker compose run --rm --no-deps --entrypoint python ui -c "import common.runtime_settings.client as c; print(c.fetch_runtime_snapshot('http://api:8000').HTTP_REQUEST_TIMEOUT)"` | prints a value (degraded) — **no `ModuleNotFoundError`**. This is the regression gate for step 5b; it fails today |

**Live, after the Keycloak realm is re-imported** (step 6's note). Run in a
**producer** container, not the API: the producers hold
`KEYCLOAK_SERVICE_CLIENT_SECRET` via `env_file`, the API container does not have
it in `os.environ` (it reads the mounted `.env` through pydantic only).

```bash
docker compose exec -T github-producer python -c "
from common.auth.service_token import get_service_token
t = get_service_token()
print('len', len(t))
print('reused', t == get_service_token())
"
```
→ prints `len <positive>` and `reused True`.

```bash
docker compose exec -T github-producer python -c "
import base64, json
from common.auth.service_token import get_service_token
p = get_service_token().split('.')[1]
p += '=' * (-len(p) % 4)
c = json.loads(base64.urlsafe_b64decode(p))
print(c['iss']); print(c.get('aud')); print(c.get('azp')); print(sorted(c['realm_access']['roles']))
"
```
→ `iss` is `https://localhost/auth/realms/wba`; `aud` is `['wba-internal']`;
`azp` is `wba-internal`; roles include `wba-service`.

**If `wba-service` is missing, STOP.** Plan 053's realm template must grant it to
the `wba-internal` service account; do not paper over it by widening another role.

## Manual gates

All gates are here, at the end. Hand back and wait for `PASS` on each; a `FAIL` is
a STOP condition.

> ### 🚦 GATE 1 — the helper
>
> Operator reads `src/common/auth/service_token.py` and confirms: lazy fetch, 60s
> refresh margin, a 30s failure backoff, double-checked locking with no module
> `global`, `expires_at` from `expires_in`, **no secret or token in any log call**,
> no default for the secret, and a dedicated exception type.
> Wait for `PASS`.

> ### 🚦 GATE 2 — live token and the audience decision
>
> Operator confirms the two live commands above: the token decodes with `iss` =
> `https://localhost/auth/realms/wba`, `aud` = `["wba-internal"]`, `azp` =
> `wba-internal`, roles include `wba-service`; and a second consecutive call
> returns the **same** token (cache). Then confirms the recorded policy — the
> realm now carries the mapper, and 057 is obliged to accept **either** configured
> client with `azp` matching the matched audience, and to allow
> `include_secrets=true` for admin **or** service.
> Wait for `PASS`.

> ### 🚦 GATE 3 — every machine call site
>
> Operator confirms **seven** credential-bearing call sites in three groups:
> the three daemon helpers `_reconcile_startup_orphans`, `_update_status`,
> `_get_command_status`; `fetch_runtime_snapshot`, which covers both the consumer
> and the daemon's runtime cache; and the three producer config fetches (one each
> in `github_config.py` / `jira_config.py` / `confluence_config.py`). Confirms each
> degrades to its pre-existing behaviour when the token is unavailable, that the
> existing log-and-continue handling is unchanged, that the 401 retry happens at
> most once, and that the consumer needed no code change.
> Wait for `PASS`.

> ### 🚦 GATE 4 — env, secrets and tests
>
> Operator confirms: the four connector services have `KEYCLOAK_INTERNAL_URL` and
> `KEYCLOAK_SERVICE_CLIENT_ID` and **no** secret default anywhere in
> `docker-compose.yml`; no `keycloak` entry was added to any `depends_on`; the
> cache test asserts a single transport call; the failure-backoff and single-retry
> assertions are non-vacuous; the degrade path is covered; and no test other than
> the three named `headers=` expectations was edited to accommodate a failure.
> Wait for `PASS`.

## Done criteria

- [x] `pytest -m unit tests -q` exits 0, ≥ 2437 + new tests — **2457 passed, 2 skipped, 0 failed**
- [x] `mypy src/` exits 0 — no issues in 311 files
- [x] `pylint src --score=y` ≥ 9.0 — **9.68**
- [x] `bandit -c .bandit.yml -r src/ -lll` exits 0
- [x] `docker compose config -q` exits 0
- [ ] `docker compose exec -T github-producer python -c "from common.auth.service_token import get_service_token; print(len(get_service_token()) > 0)"` prints `True` — **OPERATOR-GATED, NOT YET RUN.** Blocked on (a) rebuilding a producer image so `common/auth/` is present (no source bind-mount for the connector services) and (b) re-importing the realm so the `oidc-audience-mapper` lands. Recipe: `plans/README.md`, "055 (execution record)". This is the one criterion that proves the token is real.
- [x] No token or client secret appears in any log call: `grep -rn "logger" src/common/auth/service_token.py src/connectors/producers/daemon_common.py | grep -i "bearer \|secret"` → no matches
- [x] `grep -rn "Depends(require_" src/app/` → still no matches (enforcement is plan 057)
- [x] The "Required amendment to plan 057" section is carried into 057 (or reported to the operator if 057 is not to be edited yet) — carried in `plans/README.md`'s "Three amendments" list, which survives this file's deletion on merge
- [x] `plans/README.md` status row updated

## STOP conditions

Stop and report if:

- The live token lacks `wba-service`, or `aud` is still absent after the realm is
  re-imported (i.e. the mapper did not take effect — check the realm was actually
  re-created, not just restarted).
- `fetch_runtime_snapshot`'s fallback cannot be retained without catching
  `ServiceTokenError` in a way that hides real errors — report rather than
  broadening a bare `except`.
- A connector test other than the three named `headers=` expectations fails —
  report the test rather than editing it to accommodate the helper.
- `KEYCLOAK_SERVICE_CLIENT_SECRET` turns out to be a placeholder in `.env`: stop
  and report, because the live verification cannot pass and the operator must
  generate a real secret first.
- In-scope files have drifted from "Current state".
- A sixth `tests/test_settings_client.py` failure appears beyond the five
  `test_falls_back_on_*` tests — that file is scoped only for those five.

## Test plan

Covered in Automated verification. The highest-value assertions are the
**single-fetch cache** and the **failure backoff** (so a busy or Keycloak-less
daemon does not hammer Keycloak or stall on a 10s timeout per PATCH), the
**single 401 retry** (expiry mid-run), and the **unchanged degrade contract** (so
a Keycloak outage does not stop scans).

## Maintenance notes

- **The helper lives in `src/common/`** precisely because all four images copy
  that tree. Putting it under `src/app/` would force a Dockerfile change in four
  images.
- **A leaked `wba-internal` secret can trigger scans** (the service holds the
  connector-config read path, and 057 grants it `POST`-free commands access).
  Rotating it is a Keycloak admin-console operation plus a compose env change;
  Plan E owns broader credential handling.
- **Token expiry mid-scan** is what the single 401 retry covers. If scans ever
  become long-lived enough to need more, extend the retry in `_api_request`, not
  in each daemon.
- **A reviewer should scrutinize**: that no secret is logged, that the fallback
  still degrades rather than raising, that the realm mapper applies to
  `wba-internal` only, and that 057's amendment lands with 057.

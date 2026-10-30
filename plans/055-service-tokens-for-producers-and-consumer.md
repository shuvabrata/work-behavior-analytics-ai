# Plan 055: Give producers, the consumer, and the runtime-settings client a service token

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving on. If
> anything in "STOP conditions" occurs, stop and report — do not improvise.
> When done, update the status row in `plans/README.md`.
>
> **Every step ends with a MANUAL GATE.** Hand back to the operator and wait for
> `PASS`. A `FAIL` is a STOP condition.
>
> **Drift check (run first)**: `git diff --stat 225d3639..HEAD -- src/common/ src/connectors/producers/daemon_common.py src/connectors/consumers/main.py docker-compose.yml requirements.*.txt`
> Any mismatch against "Current state" is a STOP condition.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: MED
- **Depends on**: plans/054
- **Category**: security
- **Planned at**: commit `225d3639`, 2026-10-30
- **Design reference**: `docs/design/authn-authz-design.md`, "Service accounts"
- **This is step 3 of 9** in the Plan C sequence.

## Why this matters

The API will accept **bearer tokens only** (plan 057). Producers and the signal
consumer call `/api/v1` over HTTP today with **no credentials at all** — so the
moment enforcement switches on, command polling, command-status reporting, and
runtime-settings fetches all start returning `401`. Command-status reporting is
what feeds the Recent Actions UI, and the design says explicitly it does **not**
degrade gracefully, which is why this must land **before** enforcement.

This step adds one shared client-credentials helper and wires it into every
machine call site. **Nothing is enforced yet**, so the work is additive and
provable: the helper fetches a real token from the running Keycloak (plan 053)
and the callers start sending it. A `401` cannot occur until plan 057.

What improves when this lands: the producers and consumer authenticate as
`wba-internal`, and their runtime-settings fetch (which today fails silently to
defaults on any error) carries a token too.

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

- `_reconcile_startup_orphans` (~line 291): `GET {_api_base()}/api/v1/commands/`
- `_update_status` (~line 323): `PATCH {_api_base()}/api/v1/commands/{id}/status`
- `_get_command_status` (~line 341): `GET {_api_base()}/api/v1/commands/{id}`

Base URL comes from `_api_base()`:

```python
def _api_base() -> str:
    """Return the base URL of the app API (lazy, respects env changes)."""
    return os.environ.get("API_SERVER", "http://localhost:8000").rstrip("/")
```

**`src/connectors/consumers/main.py`** — at startup (`~line 206`) and on every
settings event (`~line 217`):

```python
    api_base = os.environ.get("API_SERVER", "http://api:8000")
    runtime_cache.refresh(fetch_runtime_snapshot(api_base))
    ...
        runtime_cache.refresh(fetch_runtime_snapshot(api_base))
```

**The four connector images** (`Dockerfile.github-producer`,
`Dockerfile.jira-producer`, `Dockerfile.confluence-producer`,
`Dockerfile.signal-consumer`) each do:

```dockerfile
COPY src/connectors/ /app/connectors
COPY src/common/ /app/common
```

So anything added under `src/common/` is already in every image — **no
Dockerfile change is needed**. They receive no `KEYCLOAK_*` environment today.

**Baseline**: `pytest -m unit tests -q` → 2391 passed (plus plan 054's new
tests).

### Repo conventions that apply

- Type hints everywhere; `mypy src/` strict.
- `from common.logger import logger`; never `print()`.
- New shared code goes in `src/common/` (already copied into all four images).
- **Never log a token or a client secret.** Log the client id and expiry only.
- Tests carry `pytestmark = pytest.mark.unit`.
- Do **not** commit or push unless asked.

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Unit tests | `pytest -m unit tests -q` | ≥ baseline, 0 fail |
| Typecheck | `mypy src/` | exit 0 |
| Lint | `pylint src --score=y` | ≥ 9.0 |
| Security scan | `bandit -c .bandit.yml -r src/ -lll` | exit 0 |
| Compose syntax | `docker compose config -q` | exit 0 |
| Token fetch (live) | `docker compose exec -T api python -c "from common.auth.service_token import get_service_token; print(len(get_service_token()))"` | a number > 0 |

## Scope

**In scope**:
- `src/common/auth/__init__.py` (create)
- `src/common/auth/service_token.py` (create) — the cached client-credentials helper.
- `src/common/runtime_settings/client.py` — attach a token, keep the fallback.
- `src/connectors/producers/daemon_common.py` — attach a token in the three helpers.
- `src/connectors/consumers/main.py` — pass credentials through.
- `docker-compose.yml` — add `KEYCLOAK_*` env to `github-producer`, `jira-producer`, `confluence-producer`, `signal-consumer`.
- `src/domain/settings.py` — **only if** a connector needs a new field; prefer reading `os.environ` in the helper as `_api_base()` already does.
- `tests/test_service_token.py` (create)
- `tests/test_runtime_settings_client_auth.py` (create)

**Out of scope** (do NOT touch):
- Any router or dependency — enforcement is plan 057.
- `src/ui/` — the UI uses the BFF, not a service account.
- `src/app/scheduler.py` — it calls `create_and_publish_command()` **in-process**
  and never crosses HTTP. It needs no token.
- `src/app/api_main.py`.
- `.env` — never write real secrets into the working tree; document names only.

## Steps

### Step 1: Create the shared service-token helper

Create `src/common/auth/__init__.py`:

```python
"""Machine-to-machine authentication for connector processes."""

from common.auth.service_token import get_service_token

__all__ = ["get_service_token"]
```

Create `src/common/auth/service_token.py`:

Contract:

- `get_service_token() -> str` returns a valid access token, using a **process-wide
  cache** and fetching a new one only when the cached token is within 60 seconds
  of expiry. Refresh is lazy, so importing the module performs no I/O.
- `invalidate_service_token() -> None` drops the cache, so a `401` from the API
  can force one immediate retry with a fresh token.
- Reads `KEYCLOAK_INTERNAL_URL` (realm base), `KEYCLOAK_SERVICE_CLIENT_ID`,
  `KEYCLOAK_SERVICE_CLIENT_SECRET` from the environment, with the same
  `os.environ.get(..., default)` style `_api_base()` uses. The defaults must be
  the compose dev values so a process started outside Compose still works.
- Token request: `POST {KEYCLOAK_INTERNAL_URL}/protocol/openid-connect/token`
  with `grant_type=client_credentials`, form-encoded, using `requests`.
  Read `expires_in` and store `expires_at = monotonic() + expires_in`.
- On any failure: log one WARNING naming the client id and the HTTP status
  (**never the secret or the response body, which may contain the token**) and
  raise a dedicated `ServiceTokenError`. Callers decide whether to degrade.
- Thread safety: a `threading.Lock` around the fetch path, so a burst of
  calls does not cause a burst of token requests. The producer daemons are
  multi-threaded.
- `KEYCLOAK_INTERNAL_URL` already ends with `/auth/realms/wba`; the token path
  is appended to it. Do **not** re-derive it from `KEYCLOAK_ISSUER`.

Target shape:

```python
class ServiceTokenError(Exception):
    """A service token could not be obtained from Keycloak."""

def get_service_token() -> str:
    """Return a cached, unexpired ``wba-internal`` access token."""

def invalidate_service_token() -> None:
    """Discard the cached token so the next call fetches a new one."""
```

**Verify**: `PYTHONPATH=src python -c "import common.auth.service_token as m; print(callable(m.get_service_token), callable(m.invalidate_service_token))"` → `True True`
**Verify**: `grep -n "logger" src/common/auth/service_token.py | grep -ci "token\s*=\|secret"` → `0` (no token/secret interpolated into a log call)
**Verify**: `mypy src/common/auth/` → exit 0

> ### 🚦 MANUAL GATE 1 — helper
>
> Operator reads the module and confirms: lazy fetch, 60s refresh margin, a
> lock, `expires_at` from `expires_in`, no secret or token in any log call, and
> a dedicated exception type.
> Wait for `PASS`.

---

### Step 2: Prove the helper against the running Keycloak

The helper must work against the real realm before anything depends on it.

**Verify** (from inside the API container, which joins the network — the helper
only needs `requests`, present in every image):
```bash
docker compose exec -T api python -c "
from common.auth.service_token import get_service_token
t = get_service_token()
print('len', len(t))
print('reused', t == get_service_token())
"
```
→ prints `len <positive>` and `reused True` (the cache works).

Then decode the claims **without validating** (dev only, to confirm the role):
```bash
docker compose exec -T api python -c "
import base64, json
from common.auth.service_token import get_service_token
p = get_service_token().split('.')[1]
p += '=' * (-len(p) % 4)
c = json.loads(base64.urlsafe_b64decode(p))
print(c['iss']); print(sorted(c['realm_access']['roles']))
"
```
→ `iss` is `https://localhost/auth/realms/wba`; roles include `wba-service`.

**If `wba-service` is missing, STOP.** Plan 053's realm template must grant it
to the `wba-internal` service account; do not paper over it by widening another
role.

**Verify**: `mypy src/` → exit 0

> ### 🚦 MANUAL GATE 2 — live token
>
> Operator verifies the token decodes with the right issuer and `wba-service`,
> and that a second consecutive call returns the **same** token (cache).
> Wait for `PASS`.

---

### Step 3: Make `fetch_runtime_snapshot` send a token

Edit `src/common/runtime_settings/client.py`. Add an `Authorization: Bearer`
header when a token is available, and **keep** the existing degrade-to-defaults
behaviour.

Rules:

- Call `get_service_token()` inside the `try`. If it raises
  `ServiceTokenError`, fall through to the existing warning-and-defaults path —
  do **not** raise out of this function (a scan must still start).
- Add a `headers={"Authorization": f"Bearer {token}"}` to the `requests.get`.
- **Import lazily** inside the function
  (`# pylint: disable=import-outside-toplevel`), matching the module's existing
  style of staying importable without heavy dependencies.
- Keep the existing exception handling intact; add `ServiceTokenError` to the
  caught tuple so the warning path covers it.
- Do **not** print or log the token.

**Verify**: `grep -n "Authorization" src/common/runtime_settings/client.py` → exactly one match
**Verify**: `PYTHONPATH=src python -c "import common.runtime_settings.client as c; print(c.fetch_runtime_snapshot('http://127.0.0.1:1').HTTP_REQUEST_TIMEOUT)"` → prints the default (proves the fallback still works with no network)
**Verify**: `pytest -m unit tests -q` → ≥ baseline

> ### 🚦 MANUAL GATE 3 — snapshot client
>
> Operator confirms the fallback path still returns defaults when the token
> cannot be fetched, and that the token is not logged.
> Wait for `PASS`.

---

### Step 4: Attach the token in the producer daemons

In `src/connectors/producers/daemon_common.py`, the three helpers each build a
URL and open a client. Add a small local helper rather than repeating the
header, e.g.:

```python
def _auth_headers() -> dict[str, str]:
    """Return an Authorization header for the app API, or {} if unavailable.

    A token failure must not stop status reporting: the request then goes out
    unauthenticated and the API's 401 is handled by the caller's existing
    ``except`` block.
    """
    try:
        return {"Authorization": f"Bearer {get_service_token()}"}
    except ServiceTokenError:
        logger.warning("Service token unavailable — sending request unauthenticated")
        return {}
```

Pass `headers=_auth_headers()` to the existing `client.get` / `client.patch`
calls in `_reconcile_startup_orphans`, `_update_status`, and
`_get_command_status`. **Do not change their error handling** — they already
catch `httpx.HTTPError` and log-and-continue, which now also covers a 401.

Additionally, in `_update_status` and `_get_command_status`, on a **401**
response specifically, call `invalidate_service_token()` once and retry the
request a single time. This is the expiry-mid-run case, and a single retry is
the whole mitigation. Do not add a retry loop.

**Verify**: `grep -c "get_service_token" src/connectors/producers/daemon_common.py` → at least `1`
**Verify**: `grep -c "headers=_auth_headers()" src/connectors/producers/daemon_common.py` → `3`
**Verify**: `mypy src/` → exit 0
**Verify**: `pylint src --score=y` → ≥ 9.0

> ### 🚦 MANUAL GATE 4 — daemons
>
> Operator confirms all three call sites send the header, the existing
> log-and-continue behaviour is unchanged, and the 401 retry happens at most
> once.
> Wait for `PASS`.

---

### Step 5: Pass credentials to the consumer

`src/connectors/consumers/main.py` calls `fetch_runtime_snapshot(api_base)`
twice. Since Step 3 makes that function attach a token itself, **no change to
the call sites is required** — but the consumer process must have the
`KEYCLOAK_*` environment (Step 6) or the token fetch fails and it silently
falls back to defaults, which is a real regression in behaviour without an
error.

Confirm by inspection that:
- no call site in the consumer needs editing;
- the consumer still starts and logs a successful snapshot fetch.

**Verify**: `grep -c "fetch_runtime_snapshot" src/connectors/consumers/main.py` → `2` (unchanged)
**Verify**: `mypy src/` → exit 0

> ### 🚦 MANUAL GATE 5 — consumer
>
> Operator confirms the consumer needed no code change and will receive the env
> in Step 6.
> Wait for `PASS`.

---

### Step 6: Give the four connector services `KEYCLOAK_*` environment

In `docker-compose.yml`, add to **each** of `github-producer`, `jira-producer`,
`confluence-producer`, and `signal-consumer`:

```yaml
      KEYCLOAK_INTERNAL_URL: http://keycloak:8080/auth/realms/wba
      KEYCLOAK_SERVICE_CLIENT_ID: ${KEYCLOAK_SERVICE_CLIENT_ID:-wba-internal}
      KEYCLOAK_SERVICE_CLIENT_SECRET: ${KEYCLOAK_SERVICE_CLIENT_SECRET:-dev-internal-secret}
```

Do **not** mount `.env` into these containers — that would hand them the LLM
keys and `CONNECTOR_ENCRYPTION_KEY` for one client secret.

If a producer currently `depends_on: api`, leave that as is; do **not** add
`keycloak` to `depends_on` — the helper is lazy and a Keycloak that is not up
yet must degrade, not block startup.

**Verify**: `docker compose config -q` → exit 0
**Verify**: `grep -c "KEYCLOAK_SERVICE_CLIENT_ID" docker-compose.yml` → at least `4`
**Verify**: `docker compose config | grep -c "keycloak:8080/auth/realms/wba"` → at least `5` (four services plus the API once plan 057 adds it)

> ### 🚦 MANUAL GATE 6 — compose env
>
> Operator confirms the four services have the three variables and that no
> secret beyond the service client secret is present in them.
> Wait for `PASS`.

---

### Step 7: Tests

**`tests/test_service_token.py`** — `pytestmark = pytest.mark.unit`
Stub the HTTP transport (do not hit Keycloak):
- first call performs a request; second call reuses the cache (assert the
  transport was called **once**).
- a token expiring within 60s is refreshed.
- `invalidate_service_token()` forces a re-fetch.
- a non-200 response raises `ServiceTokenError` and does **not** log the body.
- a missing `realm_access` / non-JSON response raises `ServiceTokenError`.
- concurrent calls from two threads issue one request (the lock).

**`tests/test_runtime_settings_client_auth.py`** — `pytestmark = pytest.mark.unit`
- with a working token, `fetch_runtime_snapshot` sends an `Authorization` header
  (capture the request through a stub).
- with `ServiceTokenError`, it returns `RuntimeConfig()` defaults and logs a
  warning — the existing degrade contract, unchanged.

**Verify**: `pytest -m unit tests/test_service_token.py tests/test_runtime_settings_client_auth.py -q` → all pass
**Verify**: `pytest -m unit tests -q` → ≥ baseline + new, 0 fail
**Verify**: `bandit -c .bandit.yml -r src/ -lll` → exit 0

> ### 🚦 MANUAL GATE 7 — tests
>
> Operator confirms the cache test asserts a single transport call (not just
> that a token was returned), and that the degrade path is covered.
> Wait for `PASS`.

---

## Test plan

Covered in Step 7. The highest-value assertions are the **single-fetch cache**
(so a busy daemon does not hammer Keycloak) and the **unchanged degrade
contract** (so a Keycloak outage does not stop scans).

## Done criteria

- [ ] `pytest -m unit tests -q` exits 0, ≥ baseline + new tests
- [ ] `mypy src/` exits 0
- [ ] `pylint src --score=y` ≥ 9.0
- [ ] `bandit -c .bandit.yml -r src/ -lll` exits 0
- [ ] `docker compose config -q` exits 0
- [ ] `docker compose exec -T api python -c "from common.auth.service_token import get_service_token; print(len(get_service_token()) > 0)"` prints `True`
- [ ] No token or client secret appears in any log call: `grep -rn "logger" src/common/auth/service_token.py src/connectors/producers/daemon_common.py | grep -i "bearer \|secret"` → no matches
- [ ] `grep -rn "Depends(require_" src/app/` → still no matches (enforcement is plan 057)
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report if:

- The live token (Step 2) lacks `wba-service`.
- `fetch_runtime_snapshot`'s fallback cannot be retained without catching
  `ServiceTokenError` in a way that hides real errors — report rather than
  broadening a bare `except`.
- A connector test now fails because it monkeypatches `requests.get` globally;
  report the test rather than editing it to accommodate the helper.
- In-scope files have drifted from "Current state".

## Maintenance notes

- **The helper lives in `src/common/`** precisely because all four images copy
  that tree. Putting it under `src/app/` would force a Dockerfile change in four
  images (see `plans/README.md`'s note on file moves needing COPY updates).
- **A leaked `wba-internal` secret can trigger scans** (service holds
  `POST /commands/`). Rotating it is a Keycloak admin-console operation plus a
  compose env change; Plan E owns broader credential handling.
- **Token expiry mid-scan** is the case the single 401 retry covers. If scans
  ever become long-lived enough to need more, extend the retry here, not in each
  daemon.
- **A reviewer should scrutinize**: that no secret is logged, that the fallback
  still degrades rather than raising, and that no `.env` was mounted into the
  connector containers.

# Plan 059: Make the UI's 401 and 403 behaviour explicit, not accidental

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving on. If
> anything in "STOP conditions" occurs, stop and report — do not improvise.
> When done, update the status row in `plans/README.md`.
>
> **Every step ends with a MANUAL GATE.** Hand back to the operator and wait for
> `PASS`. A `FAIL` is a STOP condition.
>
> **Drift check (run first)**: `git diff --stat 225d3639..HEAD -- src/ui/api_client.py src/ui/auth.py src/ui/pages src/ui/components/common.py tests/`
> Any mismatch against "Current state" is a STOP condition.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: MED
- **Depends on**: plans/058
- **Category**: security | dx
- **Planned at**: commit `225d3639`, 2026-10-30
- **Design reference**: `docs/design/authn-authz-design.md`, "Error handling"
- **This is step 7 of 9** in the Plan C sequence.

## Why this matters

Enforcement is live (plan 057). A standard user who clicks an admin-only action
now receives `403`, and a user whose session expired receives `401`. Today both
arrive as the page's *ordinary* error, which is why plan 057's gate explicitly
accepts "the refusal must not look like a crash". This plan makes the two
distinct:

- **401** — the session is gone. Redirect to the login flow and return the user
  to the page they were on.
- **403** — authenticated but not permitted. A clear, non-alarming message in
  the page's existing feedback region, so the user understands the *role* refused
  them, not that the application is broken.

The economics matter: there are **47 `except ApiError` sites across 16 files**.
Editing them all is churn with a high chance of drift between pages. Instead the
distinction is introduced **inside `api_client`** as two subclasses of
`ApiError`, so every existing handler keeps working unchanged, and the new
behaviour is added in one place.

What improves when this lands: no page ever shows "An unexpected error
occurred" for a role refusal, and an expired session re-authenticates the user
without losing their place.

## Current state

**`src/ui/api_client.py`** — `ApiError` is the single error type:

```python
class ApiError(Exception):
    def __init__(self, status_code: int, *, detail: Any = None,
                 detail_error: str | None = None,
                 message: str | None = None) -> None:
        self.status_code = status_code
        ...
        self.message = message or f"API request failed with status code {status_code}"
        super().__init__(self.message)
```

`_request()` calls `_call()`, then `if not response.ok: raise _describe(response)`.
`_describe()` builds an `ApiError` from the response. **This is the single place
all failures funnel through.**

**`src/ui/auth.py`** (plan 056) raises `SessionMissingError` /
`TokenExchangeUnavailable` when the cookie is absent or the exchange fails.

**`src/ui/components/common.py:159`** — `create_alert(content, color="info",
class_name="mb-2", dismissable=True, duration=None, style=None)` returns a
`dbc.Alert`. Use it for every message in this plan.

**`src/ui/pages/settings/runtime.py:300`** — the **canonical feedback region**
the design points at: a dedicated area near the top of the section, outside any
collapsed panel, that renders `create_alert(...)`. Match that placement.

**`src/ui/request_logging.py`** — the `before_request` guard from plan 056. It
302s navigations without a cookie and returns 401 JSON for Dash XHRs.

**47 handlers** use `except ApiError as exc:` (16 files). They are **not** to be
edited by this plan except where Step 3 explicitly says so.

### Repo conventions that apply

- Destructive buttons: `color="outline-danger"` only; a `dcc.ConfirmDialog` is
  required only for destructive data loss. A role refusal is not destructive.
- Alerts: dedicated feedback region near the top of the active section;
  `dismissable=True`; errors persist, transient successes auto-dismiss.
  Semantic colours: success = completed, danger = failure, warning = recoverable,
  info = neutral. A **403 is not a failure of the app** — use `warning`, so the
  user reads it as "not allowed", not "broken".
- Typography/spacing from `styles.py` tokens.
- Do **not** commit or push unless asked.

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Unit tests | `pytest -m unit tests -q` | ≥ baseline, 0 fail |
| Typecheck | `mypy src/` | exit 0 |
| Lint | `pylint src --score=y` | ≥ 9.0 |
| Rebuild UI | `docker compose up -d --build ui` | healthy |
| Count handlers | `grep -rn "except ApiError" src/ui \| wc -l` | unchanged (**47**) |

## Scope

**In scope**:
- `src/ui/api_client.py` — the two subclasses and their construction.
- `src/ui/auth.py` — a single redirect helper for the 401 path.
- `src/ui/components/common.py` — a new `create_permission_denied_alert`.
- `src/ui/components/permission_errors.py` (create) — one helper that pages call.
- The **pages that perform admin-only actions**, to use the helper: connectors,
  settings (runtime + graph styling), catalog editor, graph theme controls.
- `tests/test_ui_api_client_status_mapping.py` — extend (this file exists and
  guards the single-type contract).
- `tests/test_ui_permission_errors.py` (create)

**Out of scope** (do NOT touch):
- **The other 47 handlers.** They keep catching `ApiError`; the subclasses make
  that correct. Changing them is the churn this plan exists to avoid.
- The collaboration-specific `translate_api_error` mapping — plan 052's Step 10
  deliberately keeps it at the call sites. Leave it exactly where it is and keep
  its tests passing.
- Nav hiding or page-level gating — the design forbids it.
- The account bar (plan 056).
- Any API change.

## Steps

### Step 1: Two subclasses in the client, constructed centrally

In `src/ui/api_client.py`:

```python
class AuthExpiredError(ApiError):
    """401 — the session is gone (expired, revoked, or logged out).

    A subclass so every existing ``except ApiError`` handler still catches it;
    only the code that turns a 401 into a redirect needs the narrower type.
    """


class PermissionDeniedError(ApiError):
    """403 — authenticated, but the principal's role does not permit it."""
```

In `_describe()`, after constructing the `ApiError`, return the subclass when the
status matches:

```python
    base = ApiError(response.status_code, detail=..., message=...)
    if response.status_code == 401:
        return AuthExpiredError(base.status_code, detail=base.detail,
                                detail_error=base.detail_error, message=base.message)
    if response.status_code == 403:
        return PermissionDeniedError(base.status_code, detail=base.detail,
                                     detail_error=base.detail_error, message=base.message)
    return base
```

Build the base first and convert, rather than duplicating the three construction
paths in `_describe` — it has three branches (dict detail, string detail, list
detail) and duplicating them is how the types drift apart.

Export both from `__all__`.

**Verify**: `PYTHONPATH=src python -c "
from ui.api_client import ApiError, AuthExpiredError, PermissionDeniedError
print(issubclass(AuthExpiredError, ApiError), issubclass(PermissionDeniedError, ApiError))"` → `True True`
**Verify**: `pytest -m unit tests/test_ui_api_client_status_mapping.py -q` → passes unchanged
**Verify**: `mypy src/ui/api_client.py` → exit 0

> ### 🚦 MANUAL GATE 1 — subtypes
>
> Operator confirms the subclasses are raised from `_describe` (the single funnel)
> and that `ApiError` behaviour for every other status is byte-identical.
> Wait for `PASS`.

---

### Step 2: The 401 redirect, once

Add to `src/ui/auth.py`:

```python
def login_url(next_path: str) -> str:
    """Return the login URL that returns the user to *next_path* afterwards."""
    return f"/api/v1/auth/login?next={quote(next_path, safe='')}"
```

**Critical detail found in the code:** `next` is carried through the login flow
in the **PKCE cookie** (plan 056), not in a query string surviving two
redirects — so `login_url` only has to start the flow with the right `next`.
Use `urllib.parse.quote` with `safe=''` so a nested path such as
`/app/catalog/team/review` survives.

Then add a helper the page code can call:

**Navigation mechanism.** A Dash callback cannot issue an HTTP redirect. Two
options, both usable in this repo:

1. Update a `dcc.Location` `href` — the app already has a `dcc.Location` for
   `display_page` (`src/ui/layout.py`). Returning a new `href` from an
   `Output(..., "href")` of that component navigates the browser.
2. A `clientside_callback` setting `window.location.href`.

**Use option 1** for the 401 path: one new `clientside_callback` is enough and it
needs no per-page handler. Implement it in `src/ui/auth.py` as a registration
function `register_auth_redirect(app)` that wires:

- a `clientside_callback` from a `dcc.Store(id="auth-redirect")` to a
  `dcc.Location(id="auth-redirect-location")` component, setting `href`;
- and a `set_auth_redirect(path)` helper that writes the store.

Then a page's 401 handler calls `set_auth_redirect(login_url(current_path))` and
returns `PreventUpdate`. Add the store + location components to the app shell in
`src/ui/layout.py` and register the callback in `create_dash_app`.

**Fallback if the store round-trip proves awkward**: have the **server-side**
guard in `request_logging.py` handle it. Because a 401 from the API inside a
callback is not visible to the guard, this fallback is weaker. Try the store
route first; report if it fails rather than inventing a third mechanism.

**Verify**: `PYTHONPATH=src python -c "from ui.auth import login_url; print(login_url('/app/catalog/a/b'))"` → `/api/v1/auth/login?next=%2Fapp%2Fcatalog%2Fa%2Fb`
**Verify**: `grep -c "auth-redirect" src/ui/layout.py src/ui/auth.py` → at least `2`
**Verify**: `mypy src/ui/` → exit 0

> ### 🚦 MANUAL GATE 2 — redirect wiring
>
> Operator confirms the mechanism is a single registration (not per page), and
> that a path with slashes is encoded so `next` survives.
> Wait for `PASS`.

---

### Step 3: A permission-denied alert helper

Add to `src/ui/components/common.py`:

```python
def create_permission_denied_alert(action: str, *, dismissable: bool = True) -> dbc.Alert:
    """A 403 message: the action is refused because of the user's role.

    Deliberately ``warning``, not ``danger``: the application is working
    correctly, the user simply lacks the capability. The message names the
    action so the user knows what was refused.
    """
    return create_alert(
        f"You do not have permission to {action}. "
        "This requires an administrator.",
        color="warning",
        dismissable=dismissable,
    )
```

Create `src/ui/components/permission_errors.py` with one function pages call:

```python
def handle_api_error(exc: ApiError, action: str, *, current_path: str | None = None):
    """Return the UI element(s) for *exc*, or raise for the caller to re-raise.

    - ``AuthExpiredError`` -> schedule a login redirect, return ``no_update``.
    - ``PermissionDeniedError`` -> the permission alert for *action*.
    - anything else -> re-raise, so the page's existing handler keeps its
      current behaviour.
    """
```

**Why re-raise rather than return a generic alert:** the page already knows how
to render its own failures (timeout, validation, no-data). This helper must only
take over the two auth cases, so a page opts in without losing its existing
messages. Document that contract in the docstring.

**Verify**: `PYTHONPATH=src python -c "
from ui.components.common import create_permission_denied_alert
from ui.components.permission_errors import handle_api_error
print('ok')"` → `ok`
**Verify**: `mypy src/ui/components/` → exit 0

> ### 🚦 MANUAL GATE 3 — helper
>
> Operator confirms the 403 alert uses `warning`, names the action, and that
> `handle_api_error` re-raises non-auth errors instead of swallowing them.
> Wait for `PASS`.

---

### Step 4: Opt the admin-only pages in

Edit **only** the handlers that sit in front of an admin-only action. Find them
by the endpoints plan 057 gated:

| Page | Endpoints behind admin |
|---|---|
| `pages/connectors/callbacks.py` | config write, `/test`, `include_secrets=true` |
| `pages/settings/runtime.py` | `PATCH/POST /settings*` |
| `pages/settings/graph_styling/callbacks.py` | theme writes, `/set-default` |
| `pages/catalog/editor_callbacks.py` | `PUT/DELETE /queries/catalog/...` |

For each such handler, wrap the existing body:

```python
    try:
        ...
    except (AuthExpiredError, PermissionDeniedError) as exc:
        return handle_api_error(exc, "save connector configuration")
    except ApiError as exc:
        ...existing behaviour, unchanged...
```

**Keep the existing `except ApiError` clause below it.** The new clause is
narrower, so Python's clause ordering handles it, and every non-auth failure
keeps the page's current message. Do not reorder or delete the existing clause.

**Do not touch** handlers whose endpoint is read-only (search, timeline, graph
query, collaboration) — they cannot 403 under the matrix, and editing them is
churn.

Record in a comment above each edited handler which endpoint it fronts, so a
reviewer can check the page is in the right set.

**Verify**: `grep -rc "handle_api_error" src/ui/pages/ | grep -v ':0'` → lists exactly the four files above
**Verify**: `grep -rn "except ApiError" src/ui | wc -l` → **≥ 47** (the original clauses are still present)
**Verify**: `mypy src/` → exit 0
**Verify**: `pylint src --score=y` → ≥ 9.0

> ### 🚦 MANUAL GATE 4 — opt-in
>
> Operator confirms each edited handler still has its original `except ApiError`
> clause beneath the new one, and that no read-only page was touched.
> Wait for `PASS`.

---

### Step 5: Tests

**`tests/test_ui_api_client_status_mapping.py`** — extend (it already guards the
single-type contract):
- a 401 response raises `AuthExpiredError`, which **is** an `ApiError`.
- a 403 response raises `PermissionDeniedError`, which **is** an `ApiError`.
- a 404/422/500 still raises the **base** `ApiError`, not a subclass.
- every construction branch of `_describe` (dict detail, string detail, list
  detail / 422) produces the right class — parametrize over the three shapes.

**`tests/test_ui_permission_errors.py`** — `pytestmark = pytest.mark.unit`
- `handle_api_error(PermissionDeniedError(...), "save")` returns an alert whose
  text contains "permission" and "administrator", and whose colour is `warning`.
- `handle_api_error(AuthExpiredError(...), ...)` triggers the redirect store and
  returns `no_update`.
- `handle_api_error(ApiError(500), ...)` **re-raises**.
- The alert is dismissable.

Drive the Dash callback directly (the repo's `tests/test_catalog_callbacks.py`
shows the pattern of importing and calling callback functions rather than
booting a server).

**Verify**: `pytest -m unit tests/test_ui_api_client_status_mapping.py tests/test_ui_permission_errors.py -q` → all pass
**Verify**: `pytest -m unit tests -q` → ≥ baseline + new, 0 fail

> ### 🚦 MANUAL GATE 5 — tests
>
> Operator confirms the parametrized `_describe` test covers all three shapes,
> and the re-raise case is asserted (not merely "does not crash").
> Wait for `PASS`.

---

### Step 6: Browser verification of both paths

**Verify (automated prelude)**:
```bash
docker compose up -d --build ui
curl -s -o /dev/null -w '%{http_code}' https://localhost/app/settings/runtime   # logged out → 302
```

> ### 🚦 MANUAL GATE 6 — browser, mandatory
>
> **403 path** — as `dev-user`:
> 1. Open Settings → Runtime, change a value, save. A **warning** alert appears
>    naming the action and saying it requires an administrator. The page must not
>    render a generic "unexpected error", must not crash, and the alert must be
>    dismissable.
> 2. Open Connectors, save a config. Same behaviour.
> 3. Open the Catalog editor, attempt a save. Same behaviour.
>
> **401 path** — as `dev-user`, then invalidate the session server-side:
> 1. Delete or revoke the caller's row:
>    `docker compose exec -T postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "UPDATE auth_session SET revoked_at = now() WHERE revoked_at IS NULL"`
> 2. Load any page and trigger a callback (e.g. navigate to Search and type).
>    The browser must be sent to the Keycloak login page, and after logging in
>    must land back on the page it was on — **not** the app root.
> 3. Confirm the login URL carried `next=` for that page.
>
> **Read-only pages unaffected**: as `dev-user`, Search, Timeline, Graph,
> Collaboration Network and Analytics all still work with no alert.
>
> Wait for `PASS`.

---

## Test plan

Step 5. Priorities: **subclassing preserves every existing handler** (the
parametrized 404/422/500 cases), **the re-raise contract**, and **the 401
returns the user to the same page**.

## Done criteria

- [ ] `pytest -m unit tests -q` exits 0, ≥ baseline + new
- [ ] `mypy src/` exits 0; `pylint src --score=y` ≥ 9.0; `bandit` exits 0
- [ ] `grep -rn "except ApiError" src/ui | wc -l` ≥ **47** (no handler was removed)
- [ ] `grep -rn "handle_api_error" src/ui/pages/` touches only the four admin pages
- [ ] `grep -rn "CollaborationDataUnavailable" src/ui/api_client.py` → no matches (the collaboration mapping did not move into the client)
- [ ] `pytest -m unit tests/test_collab_spotlight.py tests/test_collaboration_network_page.py -q` → passes (the collab mapping is intact)
- [ ] In the browser, a 403 renders a warning alert, never a generic error
- [ ] In the browser, a revoked session redirects to login and returns to the same page
- [ ] No nav link was hidden and no page was gated
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report if:

- The `dcc.Store` → `dcc.Location` redirect does not fire from inside a callback,
  and the server-side guard cannot see the API 401 either.
- A page's existing `except ApiError` clause must be **removed** to make the new
  one work — that is the churn this plan forbids; report instead.
- `translate_api_error` behaviour changes (its tests fail) — the client-level
  subclasses must not alter the collaboration mapping.
- Adding `handle_api_error` to a page turns a previously-correct non-auth error
  message into a generic one.
- In-scope files drifted.

## Maintenance notes

- **Only four pages opt in.** A new admin-only action on a new page must call
  `handle_api_error` explicitly; the helper is not automatic because a page that
  has no good "action" noun would produce a vague message.
- **`AuthExpiredError` and `PermissionDeniedError` are `ApiError`s forever.** If
  anything ever needs to catch all three distinctly, it can; nothing may rely on
  `type(exc) is ApiError`.
- **Plan D** adds owner-scoped theme writes. Those handlers should use the same
  helper once they can 403 for a different reason ("not your theme").
- **A reviewer should scrutinize**: that no existing handler was deleted, that
  the collaboration mapping stayed at its call sites, and that a 403 reads as a
  role refusal, not an application failure.

# Plan 059: Make the UI's 401 and 403 behaviour explicit, not accidental

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving on. If
> anything in "STOP conditions" occurs, stop and report — do not improvise.
> When done, update the status row in `plans/README.md`.
>
> **This plan has ONE step and ONE manual gate, at the end.** The automated
> checks inside the step (`grep`, `pytest`, `mypy`, `pylint`) are the executor's
> own; the manual gate is the operator's. Do not invent intermediate gates.
>
> **Drift check (run first)**: `git diff --stat cfbb6ca2..HEAD -- src/ui tests/`
> Any mismatch against "Current state" is a STOP condition. (Drift since
> `cfbb6ca2` touches only `tests/`; `src/ui` must be byte-identical to what this
> plan describes.)

## Status

- **Priority**: P1
- **Effort**: L
- **Risk**: MED
- **Depends on**: plans/058
- **Category**: security | dx
- **Planned at**: commit `225d3639`, 2026-10-30
- **Executed**: 2026-11-01 at commit `cfbb6ca2`, in the working tree on
  `feature/ui-auth-error-handling`, **uncommitted**. Parts A–G done; the
  automated verification block passed in full (see the Execution record below).
  **The manual gate has NOT been run** — it is outstanding.
- **Deviations approved** (see Execution record): the redirect store is written
  with `set_props` rather than a declared `Output`; `spotlight.py` calls
  `handle_api_error` for its side effect and returns `no_update, no_update` (the
  handler has no alert slot); the plan's per-handler extension of
  `tests/test_ui_permission_errors.py` was reduced to testing `handle_api_error`
  in isolation — the return-tuple arity was instead verified externally, all 21
  handlers correct.
- **Amended**: 2026-11-01 at commit `7698f1e7`, before first execution. Three
  defects found by re-reading the plan against the live tree; all are recorded
  inline in the step they change. **The `Planned at` drift check above must be
  re-run before dispatch** — HEAD has moved well past `225d3639`, including
  plan 058's landed changes.
- **Restructured and re-verified**: 2026-11-01 at commit `cfbb6ca2`. The seven
  steps were merged into a single step with one manual gate at the end, and
  three further defects were found by verifying every citation against the live
  tree. All three are recorded in "Defects fixed in this restructuring" below
  and applied inline. **Line numbers in this plan are written against
  `cfbb6ca2`** and are the authority over any older citation.
- **Design reference**: `docs/design/authn-authz-design.md`, "Error handling"
- **This is step 7 of 9** in the Plan C sequence.

### Why this plan was amended before its first run

The operator reproduced a live defect that this plan only half-addresses:

> After restarting the containers, opening `https://localhost/app/` renders the
> pages and lands on Graph. The top bar shows no username and no sign-out. Any
> action needing the API shows a red "A bearer token is required." There is no
> way back to login except clearing cookies.

Three findings, each absorbed into the single step below:

1. **The redirect only fires inside a Dash callback.** `ui/session_guard.py`
   lets any request through while the `wba_session` cookie is *present*, and its
   docstring defers the stale-cookie case to "plan 058 turns that into a
   redirect" — but 058 shipped chat ownership, not a redirect. Nothing redirects
   at **page load**, so the trap the operator hit (page renders, no callback yet)
   survives a callback-only fix. → absorbed into the step as **Part B**.
2. **The account bar disappears exactly when it is needed.** `ui/components/
   account_bar.py` returns `None` on `ApiError` by design, so a dead session
   removes the username *and* sign-out together. The operator's suggested fix (a
   LOGIN control where LOGOUT sits) is the cheapest escape hatch. This was
   explicitly out of scope when the plan was written. → absorbed as **Part F**.
3. **The plan's original browser gate could not pass as written.** It required
   read-only pages to show "no alert" for a dead session, but only the four
   admin pages were being opted in, and the read-only pages catch bare
   `Exception`, not `ApiError` — so the subclasses never reach them. Search
   would render its danger alert ("Search failed. Check that the application
   server is running."). A done-criterion the plan's own scope made
   unachievable. → absorbed as **Part E**.

### Defects fixed in this restructuring (2026-11-01, at `cfbb6ca2`)

1. **The handler counts were stale and the floor had gone slack.** The original
   text's "47 `except ApiError` sites across 16 files" matched `225d3639`, not
   the live tree, which holds **49 across 18 files** (`account_bar.py` and
   `setup_banner.py` are new since). The done criterion `≥ 47` therefore no
   longer proved "no handler was removed" — deleting two would still pass. All
   counts are now the live values, and the done criterion is **exact**.
2. **The read-only handler table cited handlers that cannot see the new types.**
   Verified against the tree and corrected:
   - `search.py:196` and `analytics.py:696` are pure helpers
     (`_format_event_time`, `_config_from_layer_inputs`) that make **no API
     call**, so no auth error can ever arrive there. **Removed.**
   - `graph/callbacks/expansion.py` and `context_menu.py` are **unreachable** as
     originally described: `execute_expansion_and_merge`
     (`graph/utils/graph_operations.py:76-82`) catches `ApiError` itself and
     returns `{"ok": False, "error_message": ...}` for every status except
     `STATUS_NO_RESPONSE`. A 401/403 from `/graph/expand` is flattened to an
     `ok=False` string and never reaches these handlers. **The fix moved to that
     helper (Part E.3), and the caller clauses moved above the callers'
     existing `except ApiError`, not above their `except Exception`.**
   - `graph/callbacks/spotlight.py` **does not exist**; the file is
     `src/ui/pages/graph/callbacks/spotlight.py`, which reaches
     `/api/v1/search/scoped` directly at `:126` and so *is* a real candidate.
     **Path corrected.**
3. **Clause placement in the graph handlers was wrong.** The original plan said
   to insert the narrow clause "before the existing broad one" (`except
   Exception`). In the graph files an `except ApiError` clause already sits
   *above* the `except Exception` one (`query.py:311`, `expansion.py:138`/
   `:277`, `context_menu.py:192`). Inserting before `except Exception` would
   leave the `ApiError` clause to swallow every auth error first, and the new
   clause would be dead code. **Part E specifies the correct anchor per file.**

### Defects fixed at dispatch prep (2026-11-01, at `cfbb6ca2`)

Verified against the live tree immediately before the first execution. Two
path/placement errors would have sent the executor to the wrong file:

1. **`graph_operations.py` was cited at a non-existent path.** The plan said
   `src/ui/graph/utils/graph_operations.py`; the file is
   **`src/ui/pages/graph/utils/graph_operations.py`** (moved by `88c02f44`,
   "Dash and Api runtime separation"). All three citations corrected. The
   `re-raise` anchor itself is unchanged and still correct: the file's
   `except ApiError` is at `:77` with `STATUS_NO_RESPONSE` checked at `:78`.
2. **Part B.2 put Dash callback wiring in `src/ui/auth.py`.** That module's own
   docstring (`auth.py:15`) forbids importing `ui.api_client` (cycle) and
   imports no Dash. `register_auth_redirect` / `set_auth_redirect` now live in
   `src/ui/components/permission_errors.py`; only `login_url` stays in
   `auth.py`. The Part B verify line was updated to match.

Everything else in the plan re-verified clean at `cfbb6ca2`: `except ApiError`
is **49** across **18** files; `search.py` has **5** `except Exception`
(`:196`, `:237`, `:1020`, `:1174`, `:1289`); `query.py`'s auth clause belongs
above `:311`, not above `:353`; `expansion.py` `:138`/`:277`,
`context_menu.py` `:192`, `spotlight.py:129` all match; Part D's four files
count 12 / 4 / 5 / 7; `timeline/api.py` catches `ApiError` at `:65`, `:117`,
`:210`.

**Deliberately NOT changed — a decided tradeoff, do not "fix" it back.** Part B
probes the session with `GET /api/v1/auth/me` and treats **any** 401 as a dead
session, clearing the cookie and redirecting to login. A reviewer observed that
because `api_client._call` (`src/ui/api_client.py:147-153`) swallows
`SessionMissingError` *and* `TokenExchangeUnavailableError` identically and
sends a bearer-less request, a Keycloak outage is indistinguishable from a
revoked row at the HTTP level — so this step logs the user out during a Keycloak
restart as well as after a genuine revocation. The operator's ruling was
explicit: **"I want user to be logged out if there is a restart or keycloak
outage. Let's not complicate things. Keep it simple, any proof of token invalid
should force user to re-login."** An alternative probe (`ui.auth.get_token()`,
which preserves the 401-vs-503 distinction) was proposed and **rejected**. Do
not reintroduce it, and do not add retry, grace, or caching paths around the
probe.

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

The economics matter: there are **49 `except ApiError` sites across 18 files**.
Editing them all is churn with a high chance of drift between pages. Instead the
distinction is introduced **inside `api_client`** as two subclasses of
`ApiError`, so every existing handler keeps working unchanged, and the new
behaviour is added in one place.

What improves when this lands: no page ever shows "An unexpected error occurred"
for a role refusal, an expired session re-authenticates the user without losing
their place, and the trap the operator hit — a rendered app with no identity and
no way back to login — cannot occur.

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

`_request()` (`:171`) calls `_call()`, then `if not response.ok: raise
_describe(response)` (`:180-181`). `_describe()` (`:100`) builds an `ApiError`
from the response. **This is the single place all failures funnel through.**

**`src/ui/auth.py`** (plan 056) raises `SessionMissingError` /
`TokenExchangeUnavailableError` when the cookie is absent or the exchange fails.

**`src/ui/components/common.py:159`** — `create_alert(content, color="info",
class_name="mb-2", dismissable=True, duration=None, style=None)` returns a
`dbc.Alert`. Use it for every message in this plan.

**`src/ui/pages/settings/runtime.py:300`** — the **canonical feedback region**
the design points at: a dedicated area near the top of the section, outside any
collapsed panel, that renders `create_alert(...)`. Match that placement.

**`src/ui/request_logging.py:50`** — registers the UI's single `before_request`
hook, which calls the session guard from plan 056 (`ui/session_guard.py`) and
then logs the request. The guard 302s navigations without a cookie and returns
401 JSON for Dash XHRs. **Its check is cookie *presence* only** — see Part B.

**`src/ui/session_guard.py`** — `session_guard()` (`:67`) returns `None`
whenever `current_session_id()` is truthy. `current_session_id()` (`ui/auth.py`)
is a bare `request.cookies.get(...)` — it reports presence, never validity. The
module docstring (`:8`) still defers the stale-cookie case to plan 058, which
landed chat ownership instead. **That docstring line is wrong and must be
corrected.**

**`src/ui/components/account_bar.py:81-96`** — `render_account_bar` fetches
`/api/v1/auth/me` and returns `None` on any `ApiError`, removing the username
and the Sign out button together.

**`src/ui/layout.py`** — `create_dash_app()` (`:24`); the app shell with
`dcc.Location(id="url", refresh=False)` at `:116`; `display_page` at `:142`;
`get_account_bar_layout()` mounted at `:97`; `clientside_callback` is already
imported at `:7` and used at `:247+`.

**`src/ui/pages/graph/utils/graph_operations.py:76-82`** — `execute_expansion_and_merge`
catches `ApiError`, re-raises only `STATUS_NO_RESPONSE`, and otherwise returns
`{"ok": False, "error_message": exc.message}`. **This is why a 401 on the Graph
page never reaches a caller's handler.**

**49 handlers** use `except ApiError as exc:` (18 files; verified at
`cfbb6ca2`). They are **not** to be edited by this plan except where the step
below explicitly says so.

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
| Count handlers | `grep -rn "except ApiError" src/ui \| wc -l` | unchanged (**49**) |
| Count search handlers | `grep -c "except Exception" src/ui/pages/search.py` | unchanged (**5**) |

## Scope

**In scope**:
- `src/ui/api_client.py` — the two subclasses and their construction.
- `src/ui/auth.py` — a single redirect helper for the 401 path (`login_url`
  only; the Dash wiring goes in `permission_errors.py`, see Part B.2).
- `src/ui/components/common.py` — a new `create_permission_denied_alert`.
- `src/ui/components/permission_errors.py` (create) — the helpers pages call,
  plus `register_auth_redirect` / `set_auth_redirect`.
- `src/ui/layout.py` — mount the redirect `dcc.Store` / `dcc.Location` and call
  `register_auth_redirect(app)` in `create_dash_app`.
- The **pages that perform admin-only actions**, to use the helper: connectors,
  settings (runtime + graph styling), catalog editor, graph theme controls.
- `src/ui/session_guard.py` — **added 2026-11-01** (Part B): reject a
  navigation whose session the API refuses, so a stale cookie cannot render a
  dead page.
- `src/ui/components/account_bar.py` — **added 2026-11-01** (Part F): a Sign in
  control when the session is gone. This reverses the plan's original
  "account bar is out of scope" carve-out, which is what left the operator with
  no in-app way out.
- `src/ui/pages/graph/utils/graph_operations.py` — **added 2026-11-01** (Part E.3):
  `execute_expansion_and_merge` is where a `/graph/expand` 401 is actually
  visible, because it swallows `ApiError` into `ok=False` before its callers see
  it. One narrow re-raise for the auth subclasses only.
- The **read-only pages' error clauses** — **added 2026-11-01** (Part E),
  limited to adding one narrower `except` clause in the specific handlers named
  there, anchored exactly as Part E specifies. Not a licence to restructure
  those files.
- `tests/test_ui_api_client_status_mapping.py` — extend (this file exists and
  guards the single-type contract).
- `tests/test_ui_permission_errors.py` (create)
- `tests/test_ui_session_guard_stale.py` (create) — **added 2026-11-01** (Part B)
- `tests/test_ui_account_bar_signed_out.py` (create) — **added 2026-11-01** (Part F)

**Out of scope** (do NOT touch):
- **The other 49 handlers.** They keep catching `ApiError`; the subclasses make
  that correct. Changing them is the churn this plan exists to avoid.
- The collaboration-specific `translate_api_error` mapping — plan 052's Step 10
  deliberately keeps it at the call sites. Leave it exactly where it is and keep
  its tests passing.
- Nav hiding or page-level gating — the design forbids it. **Note (2026-11-01):
  Part F adds a Sign in control to the account bar, which is not nav hiding or
  page gating — nothing is hidden from an authenticated user and no page is
  blocked. The prohibition stands.**
- Any API change. Everything in this plan is UI-side; the API's own behaviour
  (including the 401/503 split it already implements) is correct and is not to
  be altered.
- **Superseded (2026-11-01)**: "The account bar (plan 056)" was listed as out of
  scope. Part F now edits it, because the original carve-out is what left a
  stale session with no username and no way to sign in or out. Everything else
  about plan 056's account-bar design (the Python callback, the form POST logout,
  rendering nothing on unrelated failures) is unchanged.

## Step (single): Make 401 and 403 distinct, and always leave a way back to login

Parts A–G below are one unit of work. Do them in order; A–C are prerequisites
for D–F, and G is the test suite for all of them. The automated `Verify` lines
are yours to run as you go. The manual gate at the end is the only hand-back.

---

### Part A: Two subclasses in the client, constructed centrally

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

In `_describe()` (`:100`), after constructing the `ApiError`, return the
subclass when the status matches:

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
paths in `_describe` — it has three branches (dict detail at `:108`, string
detail at `:117`, list detail at `:121`) and duplicating them is how the types
drift apart.

Export both from `__all__` (`:37`).

**Verify**: `PYTHONPATH=src python -c "
from ui.api_client import ApiError, AuthExpiredError, PermissionDeniedError
print(issubclass(AuthExpiredError, ApiError), issubclass(PermissionDeniedError, ApiError))"` → `True True`
**Verify**: `pytest -m unit tests/test_ui_api_client_status_mapping.py -q` → passes unchanged
**Verify**: `mypy src/ui/api_client.py` → exit 0

---

### Part B: Redirect to login — at page load AND from inside a callback

Two mechanisms, because a Dash callback and a page navigation fail differently.
Both must land, but they share one URL builder.

**B.1 — the shared URL builder.** Add to `src/ui/auth.py`:

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

**B.2 — the callback path.** A Dash callback cannot issue an HTTP redirect.
Two options, both usable in this repo:

1. Update a `dcc.Location` `href` — the app already has a `dcc.Location` for
   `display_page` (`src/ui/layout.py:116`). Returning a new `href` from an
   `Output(..., "href")` of that component navigates the browser.
2. A `clientside_callback` setting `window.location.href`.

**Use option 1**: one new `clientside_callback` is enough and it needs no
per-page handler. **Placement — do not put this in `src/ui/auth.py`.** That
module is deliberately dependency-light: its own docstring (`auth.py:15`)
forbids importing `ui.api_client` (an import cycle) and its `__all__` exports
only token/session primitives. Importing Dash into it to register a callback
would contradict that design. Put the two redirect symbols in
**`src/ui/components/permission_errors.py`** (Part C creates it; it already
imports `ui.api_client` and is the module callers reach for) as:

- `register_auth_redirect(app)` — wires a `clientside_callback` from a
  `dcc.Store(id="auth-redirect")` to a `dcc.Location(id="auth-redirect-location")`
  component, setting `href`;
- `set_auth_redirect(path)` — writes the store.

Only `login_url` (a pure string helper, no imports beyond `urllib.parse`) stays
in `src/ui/auth.py` as Part B.1 specifies.

Then a page's 401 handler calls `set_auth_redirect(login_url(current_path))` and
returns `no_update` (see Part C's helper). Add the store + location components
to the app shell in `src/ui/layout.py` and call `register_auth_redirect(app)` in
`create_dash_app`.

Record this placement decision in the module docstring so a later reader does
not "tidy" it back into `auth.py`.

**Fallback if the store round-trip proves awkward**: have the **server-side**
guard in `request_logging.py` handle it. Because a 401 from the API inside a
callback is not visible to the guard, this fallback is weaker. Try the store
route first; report if it fails rather than inventing a third mechanism.

**B.3 — the page-load path (the operator's original defect).** B.2 does not
help here: it only fires once a callback runs, and the operator's trap is a page
that renders *before* any callback. Fix it in `src/ui/session_guard.py`, whose
current check is cookie *presence* only:

```python
def session_guard() -> Response | None:
    if _is_exempt(request.path):
        return None
    if current_session_id():
        return None
    return _unauthenticated_response()
```

When the cookie is present but the row behind it is gone, the guard passes the
request through, `display_page` serves a full page, and nothing redirects. Add a
probe:

```python
def _session_is_rejected() -> bool:
    """Return whether the API refuses the cookie we hold.

    Only called when a cookie is present, so the common authenticated path is
    one cheap ``/auth/me`` call per *navigation* — never per asset or callback.
    """
```

Rules the executor must follow:

- **Only probe on the paths that render a page.** Assets and the two
  `_dash-*` endpoints stay exempt exactly as they are today; do not widen the
  probe to them. Gate the probe behind the *existing* `_is_exempt()` check
  (`:39`), and additionally behind "this is a document navigation"
  (`request.method == "GET" and not _is_dash_xhr()`), reusing the helpers
  already in the module (`_is_dash_xhr` at `:46`).
- **Probe with `ui.api_client`**, i.e. `GET /api/v1/auth/me`. Catch
  `PermissionDeniedError` (403) as *not* rejected — an authenticated user
  lacking a role is a valid session and must not be logged out. Only
  `AuthExpiredError` (401) means "rejected". Per the decided tradeoff in
  "Defects fixed" above, a 401 is accepted as proof the session is gone
  regardless of *why* the exchange produced it — **do not** try to distinguish a
  revoked row from a Keycloak outage, and do not add retry or grace paths.
- **On rejection, clear the cookie and redirect**, using the same
  `_unauthenticated_response()` path (`:58`) so the `next=` encoding is
  inherited rather than re-implemented. Clearing matters: without it the next
  navigation probes again and the user enters a redirect loop.
- **If the probe itself cannot reach the API** (transport error,
  `STATUS_NO_RESPONSE`), **let the request through** and change nothing. A
  transport failure is not proof of an invalid token; this rule is what stops an
  API outage from becoming a login loop, and it is independent of the tradeoff
  above.
- This must not import `api_client` at module scope if that creates a cycle with
  `ui.auth` — import inside the function if needed. Check with
  `python -c "import ui.session_guard"`.

**Correct the stale docstring** in the same edit: replace the "plan 058 turns
that into a redirect" sentence at `:8` with a statement of what this part
actually implements.

**Per-request cost.** One `GET /api/v1/auth/me` per page navigation for an
authenticated user. Acceptable: it is a single indexed lookup, and it replaces a
render the user cannot use. Do **not** cache the result in a module global — the
UI runs multiple gunicorn workers and a per-worker cache would let one worker
serve a dead page.

**Tests — `tests/test_ui_session_guard_stale.py`** (`pytestmark = pytest.mark.unit`).
Install a fake transport via `api_client.set_transport` (the repo's existing
seam) and drive `session_guard()` inside a Flask test request context:
- cookie present + `/auth/me` → 200 ⇒ `session_guard()` returns `None`.
- cookie present + `/auth/me` → 401 ⇒ returns a 302 whose `Location` starts
  `/api/v1/auth/login?next=`, **and** the response clears `wba_session`.
- cookie present + `/auth/me` → 403 ⇒ returns `None` (must NOT log out).
- cookie present + transport raises ⇒ returns `None` (must NOT loop).
- cookie **absent** ⇒ unchanged behaviour: 302 for a navigation, 401 JSON for a
  Dash XHR.
- an exempt path (`/app/assets/x.js`) ⇒ no probe is made at all (assert the
  fake transport was not called).

**Verify**: `PYTHONPATH=src python -c "from ui.auth import login_url; print(login_url('/app/catalog/a/b'))"` → `/api/v1/auth/login?next=%2Fapp%2Fcatalog%2Fa%2Fb`
**Verify**: `PYTHONPATH=src python -c "import ui.session_guard"` → no ImportError
**Verify**: `grep -c "auth-redirect" src/ui/layout.py src/ui/components/permission_errors.py` → at least `2`, and `grep -c "auth-redirect" src/ui/auth.py` → `0` (the Dash wiring stays out of the dependency-light auth module)
**Verify**: `grep -n "plan 058" src/ui/session_guard.py` → **no matches**
**Verify**: `pytest -m unit tests/test_ui_session_guard_stale.py -q` → passes
**Verify**: `mypy src/ui/` → exit 0

---

### Part C: A permission-denied alert helper

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

---

### Part D: Opt the admin-only pages in

Edit **only** the handlers that sit in front of an admin-only action. Find them
by the endpoints plan 057 gated:

| Page | Endpoints behind admin | `except ApiError` clauses present |
|---|---|---|
| `pages/connectors/callbacks.py` | config write, `/test`, `include_secrets=true` | 12 |
| `pages/settings/runtime.py` | `PATCH/POST /settings*` | 4 |
| `pages/settings/graph_styling/callbacks.py` | theme writes, `/set-default` | 5 |
| `pages/catalog/editor_callbacks.py` | `PUT/DELETE /queries/catalog/...` | 7 |

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
churn. (Part E covers the specific read-only handlers that *do* need it.)

Record in a comment above each edited handler which endpoint it fronts, so a
reviewer can check the page is in the right set.

**Verify**: `grep -rc "handle_api_error" src/ui/pages/ | grep -v ':0'` → lists exactly the four files above
**Verify**: `grep -rn "except ApiError" src/ui | wc -l` → **= 49** (the original clauses are still present)
**Verify**: `mypy src/` → exit 0
**Verify**: `pylint src --score=y` → ≥ 9.0

---

### Part E: Make a dead session reach the read-only pages too

The original browser gate asserts that Search, Timeline, Graph, Collaboration
Network and Analytics show **no** crash alert for a dead session. Part D makes
that impossible on its own: it opts in only the four admin pages, and these
pages catch bare `Exception` (or already swallow `ApiError`), so the Part A
subclasses are invisible to them.

**E.1 — the handlers that need a new clause.** Verified at `cfbb6ca2`. Each row
states the exact anchor, which differs by file:

| File:line of the `except` | Enclosing function | Direct API call | Insert the new clause… |
|---|---|---|---|
| `src/ui/pages/search.py:1174` | `execute_search` (`:1110`) | `api_client.get` at `:1173` | above `except Exception as exc:` |
| `src/ui/pages/search.py:1289` | `paginate_search` (`:1252`) | `api_client.get` at `:1288` | above `except Exception as exc:` |
| `src/ui/pages/graph/callbacks/query.py:353` | `execute_query` (`:124`) | `api_client.post` at `:241` | **above `except ApiError as exc:` at `:311`** |
| `src/ui/pages/graph/callbacks/spotlight.py:129` | (spotlight) | `api_client.post_json` at `:126` | above `except Exception as exc:` |

**Read the anchor column carefully.** In `query.py` an `except ApiError` clause
already sits above the `except Exception` one. Inserting before `except
Exception` would leave the `ApiError` clause to catch every auth error first and
the new clause would be dead code. This is the correction recorded in "Defects
fixed" item 3.

**Handlers deliberately EXCLUDED — do not edit them:**
- `src/ui/pages/search.py:196` (`_format_event_time`) and `:237`
  (`_build_attributes_table`) — date/number formatting helpers, **no API call**.
- `src/ui/pages/search.py:1020` (`restore_search_on_navigate`) — calls the API
  at `:1019`, but its `except` path returns the pre-built `_no_restore` tuple
  with no user-visible alert, so a dead session there is already silent. Adding a
  clause would change a working path for no benefit. Leave it.
- `src/ui/pages/analytics.py:696` (`_config_from_layer_inputs`) — config
  validation, **no API call**.
- `src/ui/pages/timeline/api.py` — already catches `ApiError` at `:65`, `:117`,
  `:210` (verified: 3 matches), so the Part A subclasses reach it for free.
  **Do not edit it.**
- `src/ui/pages/graph/callbacks/expansion.py` and `context_menu.py` — see E.3.

**E.2 — the clause shape.** Same rule as Part D: the original clause stays,
unchanged and in place.

```python
    except (AuthExpiredError, PermissionDeniedError) as exc:
        return handle_api_error(exc, "<the action this handler performs>")
    except Exception as exc:          # or: except ApiError as exc:  — per E.1
        ...existing behaviour, byte-for-byte unchanged...
```

`handle_api_error` already does the right thing for both classes: a 401
schedules the login redirect and returns `no_update`; a 403 returns the warning
alert. **A read-only page can still 403**, so this is not only about 401 —
`/api/v1/search` is `allowed` for every role, but a page that happens to front a
gated endpoint would otherwise show *"the application server is not running"*.

**Return-shape caveat — this is the trap in this part.** Several of these
handlers return a *tuple* of many outputs (Search returns nine values, with
`dbc.Alert` in slot 0). `handle_api_error` returns a single element or
`no_update`. The executor must **not** blindly `return handle_api_error(...)`;
it must map the helper's result into the handler's own return shape, expanding
`no_update` to every slot. Prefer:

```python
    except (AuthExpiredError, PermissionDeniedError) as exc:
        alert = handle_api_error(exc, "run this search")
        return (alert, "", _empty_header, _empty_pagination,
                "Page 1", True, True, 1, last_query_params or {})
```

using the handler's **existing** empty-values, so no new shape is invented. Read
each handler's current `except` body and mirror its return tuple exactly. If a
handler's shape cannot be satisfied this way, **STOP and report** — do not invent
a slot.

**Do not** change any message, colour, or return value on the paths that are not
auth errors.

**E.3 — the Graph expansion path, which needs a second edit.** `expansion.py`
and `context_menu.py` cannot see an auth error at all, because
`execute_expansion_and_merge` (`src/ui/pages/graph/utils/graph_operations.py:76-82`)
catches `ApiError` and converts every status except `STATUS_NO_RESPONSE` into
`{"ok": False, "error_message": ...}`. Editing the callers alone would add dead
clauses.

Change the helper to let the two auth subclasses through:

```python
    except ApiError as exc:
        if exc.status_code == STATUS_NO_RESPONSE:
            # No HTTP response (timeout / connection refused): the caller's
            # expansion-error handler owns the user-facing alert.
            raise
        if isinstance(exc, (AuthExpiredError, PermissionDeniedError)):
            # An auth failure must reach the caller's auth handler: flattening
            # it into ``ok=False`` would render it as a generic expansion error
            # and the user would never be sent to login.
            raise
        logger.warning(...)
        return {"ok": False, "error_message": exc.message or "Unknown error"}
```

Then add the E.2 clause in the **graph callers**, anchored above their
existing `except ApiError` (not the `except Exception` below it):

| File | Existing `except ApiError` at | Also present |
|---|---|---|
| `src/ui/pages/graph/callbacks/expansion.py` | `:138` and `:277` | `except Exception` at `:150`, `:292` |
| `src/ui/pages/graph/callbacks/context_menu.py` | `:192` | `except Exception` at `:204` |

**Verify**: `grep -c "handle_api_error" src/ui/pages/search.py` → **= 2**
**Verify**: `grep -c "handle_api_error" src/ui/pages/graph/callbacks/query.py` → **= 1**
**Verify**: `grep -c "handle_api_error" src/ui/pages/graph/callbacks/spotlight.py` → **= 1**
**Verify**: `grep -c "handle_api_error" src/ui/graph/callbacks/*.py` → **no matches** (the wrong path)
**Verify**: `grep -c "except Exception" src/ui/pages/search.py` → **= 5**, unchanged
**Verify**: `grep -rn "except ApiError" src/ui | wc -l` → still **= 49**
**Verify**: `pytest -m unit tests/test_collab_spotlight.py tests/test_collaboration_network_page.py -q` → passes
**Verify**: `mypy src/` → exit 0
**Verify**: `pylint src --score=y` → ≥ 9.0

Extend `tests/test_ui_permission_errors.py` with one case per edited handler,
driving the callback directly with a fake transport returning 401, asserting the
redirect store was written and that the non-auth path still produces its original
message (the existing behaviour is the thing most likely to be broken here).

---

### Part F: A way back in — Sign in where Sign out sits

**The defect.** `src/ui/components/account_bar.py` renders the username and the
Sign out button, and on `ApiError` returns `None`:

```python
def render_account_bar(_pathname: str | None) -> Any:
    try:
        payload = api_client.get_json("/api/v1/auth/me")
    except ApiError:
        # Unauthenticated or unreachable: render nothing. The account bar is a
        # convenience, never a user-facing error surface.
        return None
```

So a dead session removes **both** the identity *and* the only in-app way to
sign in or out — leaving cookie-clearing as the only recovery, the operator's
exact report. Part B.3 makes this rarer, not impossible (a signature-key
rotation can still 401 mid-session), so the escape hatch is still required.

**What to change.** Keep the existing success path and the existing
"render nothing for an unrelated failure" behaviour. Add a **signed-out** branch
for the one case that is genuinely actionable:

```python
def render_account_bar(_pathname: str | None) -> Any:
    try:
        payload = api_client.get_json("/api/v1/auth/me")
    except AuthExpiredError:
        # The session is gone: offer the way back in, in the slot the Sign out
        # button occupies. Previously this returned nothing, which left no
        # in-app route to login.
        return _signed_out_children(_pathname)
    except ApiError:
        # Unreachable API or any other failure: render nothing, as before. A
        # transport error must not advertise a login the user may not need.
        return None
    ...
```

Rules:

- **Only `AuthExpiredError` (401) shows the control.** A 403 means the session is
  fine; a transport error means the API is down. Neither should produce a Sign in
  button.
- The control is a plain `<a href="{login_url(current_path)}">` styled to match
  the Sign out button's size and family, **not** a `dcc.Location` update — the
  login flow needs a top-level navigation to reach Keycloak. Use the existing
  `login_url()` from Part B.1 so the `next=` encoding is shared, and pass the
  current path (the callback already receives `_pathname`) so the user returns
  where they were.
- **Label it "Sign in"**, not "Login" — the adjacent control is "Sign out", and
  the pair should read as a pair.
- Use `styles.py` tokens (`FONT_SANS`, `FONT_SIZE_XSMALL`) exactly as the Sign
  out button does; do not introduce new sizes.
- **Do not** add a `ConfirmDialog` — signing in is not destructive (the repo's
  ConfirmDialog rule covers destructive data loss only).
- Update the module docstring (`account_bar.py:15-17`): its claim that "a missing
  account bar is not user-facing breakage" is now only true for non-401 failures.

**Tests — `tests/test_ui_account_bar_signed_out.py`** (`pytestmark = pytest.mark.unit`).
Call `render_account_bar` directly with a fake transport (the pattern already
used for callback tests in this repo):
- 401 from `/auth/me` ⇒ the result contains a link whose href starts
  `/api/v1/auth/login?next=` and contains the text **Sign in**.
- 403 ⇒ `None` (a role-less session is still signed in).
- transport failure ⇒ `None`.
- 200 with a username ⇒ unchanged: the username and the Sign out form, and
  **no** Sign in link.

**Verify**: `grep -n "Sign in" src/ui/components/account_bar.py` → present
**Verify**: `grep -n "AuthExpiredError" src/ui/components/account_bar.py` →
  present, and the broad `except ApiError` clause still below it
**Verify**: `pytest -m unit tests/test_ui_account_bar_signed_out.py -q` → passes
**Verify**: `mypy src/` → exit 0

---

### Part G: Tests

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

**Verify**: `pytest -m unit tests/test_ui_api_client_status_mapping.py tests/test_ui_permission_errors.py tests/test_ui_session_guard_stale.py tests/test_ui_account_bar_signed_out.py -q` → all pass
**Verify**: `pytest -m unit tests -q` → ≥ baseline + new, 0 fail

---

### Automated verification (run all before handing back)

```bash
pytest -m unit tests -q
mypy src/
pylint src --score=y
bandit -c .bandit.yml -r src/ -lll
grep -rn "except ApiError" src/ui | wc -l                    # = 49
grep -rn "except ApiError" src/ui | cut -d: -f1 | sort -u | wc -l   # = 18
grep -c "except Exception" src/ui/pages/search.py            # = 5
grep -n "plan 058" src/ui/session_guard.py                   # no matches
grep -rn "CollaborationDataUnavailable" src/ui/api_client.py # no matches
docker compose up -d --build ui
curl -s -o /dev/null -w '%{http_code}' https://localhost/app/settings/runtime   # logged out → 302
```

> ### 🚦 MANUAL GATE — the only hand-back
>
> **1. 403 shows a warning, not a crash.** As `dev-user`:
> - Settings → Runtime: change a value, save. A **warning** alert appears naming
>   the action and saying it requires an administrator — not a generic
>   "unexpected error", no crash, and dismissable.
> - Connectors: save a config. Same behaviour.
> - Catalog editor: attempt a save. Same behaviour.
>
> **2. A revoked session redirects at page load — the operator's original bug.**
> Sign in, then revoke server-side and **leave the browser cookie intact**:
> ```bash
> docker compose exec -T postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
>   -c "UPDATE auth_session SET revoked_at = now() WHERE revoked_at IS NULL"
> ```
> Reload `https://localhost/app/`. The browser must be sent to the Keycloak
> login page. It must **not** render a page with an empty account bar. Then log
> back in and confirm you land on the page you were on, **not** the app root, and
> that the login URL carried `next=`.
>
> **3. The same, from a callback.** With the session revoked again, navigate to
> Search and type. Same redirect, same return-to-page behaviour.
>
> **4. Read-only pages do not report a dead session as a crash.** As `dev-user`
> with the session revoked, visit Search, Timeline, Graph, Collaboration Network
> and Analytics. Each must move the browser to login — and none may show *"Check
> that the application server is running."*
>
> **5. The non-auth path is untouched.** Stop the API
> (`docker compose stop api`) and confirm Search shows its **original** danger
> alert, not a login redirect. An API outage must not become a login loop. Also
> confirm a page still renders (no probe loop).
>
> **6. There is always a way back in.** With the session revoked and cookies
> intact, if the redirect does not fire first, the top bar must show a working
> **Sign in** control that reaches Keycloak and returns to the page you were on.
> There must be **no** state in which the app shows neither a username nor a
> Sign in control while still rendering usable pages.
>
> **7. The restart scenario from the report.** `docker compose restart` the
> stack, reopen `https://localhost/app/`, and confirm you are either redirected
> to login or offered Sign in — never left on a rendered page with a red "A
> bearer token is required."
>
> Wait for `PASS`.

---

## Test plan

Part G, plus the per-part test files in B.3, E.1 and F. Priorities:
**subclassing preserves every existing handler** (the parametrized 404/422/500
cases), **the re-raise contract**, **the 401 returns the user to the same page**,
**a dead session cannot render a page** (Part B.3), **a read-only page's non-auth
error message is unchanged** (Part E), and **there is always a way back to
login** (Part F).

## Done criteria

- [ ] `pytest -m unit tests -q` exits 0, ≥ baseline + new
- [ ] `mypy src/` exits 0; `pylint src --score=y` ≥ 9.0; `bandit` exits 0
- [ ] `grep -rn "except ApiError" src/ui | wc -l` **= 49**, and across **= 18** files (no handler was removed)
- [ ] `grep -rn "handle_api_error" src/ui/pages/` touches the four admin pages from Part D **and** the Part E handlers, and nothing else
- [ ] `grep -rn "handle_api_error" src/ui/graph/callbacks/` → no matches (the corrected path is `src/ui/pages/graph/callbacks/`)
- [ ] `grep -rn "CollaborationDataUnavailable" src/ui/api_client.py` → no matches (the collaboration mapping did not move into the client)
- [ ] `pytest -m unit tests/test_collab_spotlight.py tests/test_collaboration_network_page.py -q` → passes (the collab mapping is intact)
- [ ] In the browser, a 403 renders a warning alert, never a generic error
- [ ] In the browser, a revoked session redirects to login and returns to the same page
- [ ] `grep -n "plan 058" src/ui/session_guard.py` → no matches (Part B.3)
- [ ] With a **present but revoked** cookie, a page navigation 302s to login and clears the cookie (Part B.3, Gate 2)
- [ ] With the API stopped, a page still renders and makes **no** login redirect (Part B.3 must not loop on an outage)
- [ ] `grep -c "except Exception" src/ui/pages/search.py` **= 5** (Part E did not restructure the file)
- [ ] `grep -n "Sign in" src/ui/components/account_bar.py` → present (Part F)
- [ ] `grep -c "handle_api_error" src/ui/pages/graph/callbacks/expansion.py src/ui/pages/graph/callbacks/context_menu.py` → present in both (Part E.3 moved the fix to the right place)
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
- **(Part B.3)** The `/auth/me` probe cannot be confined to page navigations — if
  it fires for assets or Dash callbacks, stop; the per-request cost is not
  acceptable and the design is wrong, not the test.
- **(Part B.3)** The probe turns an **API outage** into a login redirect. A
  transport failure is not proof of an invalid token; offline must degrade to the
  old behaviour. (This is distinct from the accepted tradeoff that a Keycloak
  outage — which the API reports as a 401 — *does* log the user out.)
- **(Part B.3)** Clearing the cookie on rejection still loops (probe → redirect →
  probe). Report the observed sequence rather than raising the probe's timeout or
  adding a retry.
- **(Part E)** A read-only handler's return shape cannot be satisfied from
  `handle_api_error`'s result without inventing new empty values. Report the
  handler and its tuple arity; do not guess at a slot.
- **(Part E.3)** Re-raising the auth subclasses from
  `execute_expansion_and_merge` changes behaviour on a **non-auth** error path
  (e.g. a graph expansion test starts failing). Report; the flattening must stay
  intact for everything except the two auth subclasses.
- **(Part F)** Placing the Sign in control requires restructuring the account
  bar's existing success path. It must be additive.
- In-scope files drifted.

## Execution record (2026-11-01, `cfbb6ca2`, `feature/ui-auth-error-handling`, uncommitted)

Parts A–G executed in the working tree; nothing committed. Reviewer re-ran every
gate independently:

| Gate | Result |
|---|---|
| `pytest -m unit tests -q` | **2621 passed, 2 skipped, 0 failed** (exit 0) |
| `mypy src/` | No issues found |
| `pylint src --score=y` | **9.69/10** |
| `bandit -c .bandit.yml -r src/ -lll` | exit 0, `No issues identified` |
| `grep -rn "except ApiError" src/ui \| wc -l` | **49**; across **18** files |
| `grep -c "except Exception" src/ui/pages/search.py` | **5** (unchanged) |
| `grep -n "plan 058" src/ui/session_guard.py` | no matches |
| `grep -c "CollaborationDataUnavailable" src/ui/api_client.py` | 0 |
| `tests/test_collab_spotlight.py` + `tests/test_collaboration_network_page.py` | 42 passed |

Findings verified by the reviewer, not the executor:

- **The redirect wiring is real.** `create_dash_app()` mounts both
  `auth-redirect` (Store) and `auth-redirect-location` in the layout, and the
  callback registers as a genuine **clientside** callback
  (`_dashprivate_clientside_funcs`). The unit tests stub `set_props`, so nothing
  pins this end-to-end; the manual gate does.
- **Return-tuple arity is correct on all 21 edited handlers** (static
  decorator/output analysis): `search.py` 9, `query.py` 22 via `error_response`
  → `build_response` (identical to its existing `except ApiError` shape),
  `expansion.py` 10/11, `context_menu.py` 10, `connectors/callbacks.py`
  4/4/2/1/1/2/5/4/3, `runtime.py` 2/2/2, `graph_styling` 2/6/3/3,
  `spotlight.py` 2. No new slot was invented.
- **`restore_search_on_navigate` (`search.py:1020`) untouched**, as Part E
  requires.

Documented deviations from the executor (judged on merit, not reflex):

1. `set_auth_redirect` uses `dash.set_props` rather than declaring the store as
   an `Output` — keeps the helper callable from any callback without adding a
   store output to every handler. Valid on dash 4.4.1.
2. `spotlight.py` calls `handle_api_error(...)` for its side effect and returns
   `no_update, no_update`; the handler has two outputs and no alert slot, so a
   403 alert is not surfaced there. The endpoint is `require_user`, so 403 is
   unreachable in practice.
3. The plan asked for one `test_ui_permission_errors.py` case **per edited
   handler**; the shipped file tests `handle_api_error` in isolation instead.
   The reviewer backfilled the gap by verifying arity statically (all 21
   correct). A future change that breaks a page's return tuple will not be
   caught by the unit suite — only by the manual gate.

**Outstanding: the manual gate (items 1–7) has not been run.**

## Maintenance notes

- **Only four admin pages opt in.** A new admin-only action on a new page must
  call `handle_api_error` explicitly; the helper is not automatic because a page
  that has no good "action" noun would produce a vague message.
- **`AuthExpiredError` and `PermissionDeniedError` are `ApiError`s forever.** If
  anything ever needs to catch all three distinctly, it can; nothing may rely on
  `type(exc) is ApiError`.
- **Plan D** adds owner-scoped theme writes. Those handlers should use the same
  helper once they can 403 for a different reason ("not your theme").
- **Part B.3 adds one `GET /api/v1/auth/me` per page navigation** for an
  authenticated user. That is the price of not rendering dead pages. It is
  deliberately not cached per worker: the UI runs multiple gunicorn workers, and
  a per-worker cache would let one worker keep serving a page the others have
  already rejected. If page-load latency ever becomes a complaint, look here
  first, and prefer a short TTL in a *shared* store over a per-worker global.
- **The cookie and the session row can disagree.** The restart/kill path is:
  Keycloak's signing keys change on container recreation, the BFF's token
  exchange starts failing, and the browser keeps a perfectly well-formed
  `wba_session` cookie that resolves to a revoked row. Part B.3 is the only thing
  that notices. Anything that later short-circuits "cookie present ⇒ trust it"
  reintroduces the operator's original trap.
- **`_session_is_rejected` deliberately does not distinguish cause.** Any 401
  from `/auth/me` is treated as a dead session, including one caused by a
  Keycloak outage. This is an operator decision recorded in "Defects fixed"
  above — the alternative (`ui.auth.get_token()`, which exposes the 401-vs-503
  split) was considered and rejected in favour of simplicity. Do not add retry,
  grace, or caching around the probe.
- **`execute_expansion_and_merge` re-raises auth errors only.** Every other
  non-`STATUS_NO_RESPONSE` status still flattens to `ok=False`. Its callers rely
  on that; if a future change needs the API's message for a specific status,
  extend the flattening deliberately rather than widening the re-raise.
- **A reviewer should scrutinize**: that no existing handler was deleted, that
  the collaboration mapping stayed at its call sites, that a 403 reads as a role
  refusal not an application failure, that Part E's new clauses sit **above** the
  `except ApiError` clause wherever one exists (not merely above `except
  Exception`), and that Part B.3's probe is confined to navigations (grep for
  where `_session_is_rejected` is called — it must sit behind both the
  `_is_exempt()` check and the navigation check).

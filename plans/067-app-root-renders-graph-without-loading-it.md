# Plan 067: Make the app root land on a URL whose callbacks actually run

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 9fe08fe1..HEAD -- src/ui/ deploy/nginx/nginx.conf tests/ src/app/api/auth/v1/service.py deploy/keycloak/realm-wba.json.template`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none.
- **Category**: bug
- **Planned at**: commit `9fe08fe1`, 2026-11-10

## Why this matters

`display_page` in `src/ui/layout.py` falls through to the Graph layout for **any**
unrecognised path, "so a typo or a stale bookmark still lands somewhere useful".
The fallthrough renders the Graph page's DOM — but several Graph callbacks are
gated on an exact `pathname` match. On the fallthrough path the URL is **not**
`/app/graph`, so those callbacks correctly decline to run, and the user gets a
Graph page whose Query Catalog panel is permanently empty, reading
"No catalog metadata loaded yet."

**This is a real, observed failure.** While browser-checking the per-user catalog
favourites change, an operator
sitting at `https://localhost/app/` saw exactly that: a rendered Graph page with
a dead catalog panel. Navigating manually to `https://localhost/app/graph` fixed
it instantly. The cost is a page that looks functional and silently is not —
the worst failure shape, because the user has no signal that anything is wrong
and no way to know the URL is the problem.

**What improves.** The two paths a *browser* arrives at without asking —
`/app` and `/app/` — stop rendering a half-wired page. They canonicalise to
`/app/graph`, which is already the documented landing path (`DEFAULT_NEXT_PATH`
in `src/app/api/auth/v1/service.py:53`).

The trailing-slash form of the Graph path, `/app/graph/`, is a **second** entry
into the same defect and is fixed in this plan too (Step 4). `display_page`
normalises the trailing slash before routing (`src/ui/layout.py:179`), so
`/app/graph/` renders the Graph layout — but the catalog gate compares the raw
pathname and rejects it, leaving the same dead panel. After Steps 1–4, no URL
that renders the Graph layout reaches it with a dead catalog panel.

## Current state

### The three-part mechanism

**1. The catch-all fallthrough** — `src/ui/layout.py:212-215`:

```python
        # Unknown paths fall back to the Graph page (the app default since the
        # sidebar rework) so a typo or a stale bookmark still lands somewhere
        # useful instead of erroring.
        return graph.get_layout()
```

**2. The exact-match gates.** Two callbacks bail unless the pathname is exactly
`/app/graph`:

```python
# src/ui/pages/graph/callbacks/catalog.py:273
    if pathname != "/app/graph":
        return no_update, no_update, no_update
```

```python
# src/ui/pages/graph/callbacks/analytics_mode.py:16
    if pathname != "/app/graph":
        return {}, {}
```

The first of these is what empties the catalog panel.

These two are the **only** gates in the UI that compare against a single
un-normalised literal. Every other page's equivalent gate accepts both slash
forms, e.g.:

```python
# src/ui/pages/catalog/callbacks.py:27
    if pathname not in ("/app/catalog", "/app/catalog/", "/app/library", "/app/library/"):
```

```python
# src/ui/pages/settings/runtime.py:359
    if pathname not in ("/app/settings/runtime", "/app/settings/runtime/"):
```

So `/app/graph/` — which `display_page` *does* route to the Graph layout, since
it normalises the slash at `src/ui/layout.py:179` — is the second half-wired
entry point, and the trailing-slash blindness is peculiar to these two gates
rather than an intentional design.

**Important — normalising is not the same as accepting `/app/`.** The suggested
predicate is `(pathname or "").rstrip("/") != "/app/graph"`. Because
`"/app/".rstrip("/")` is `"/app"`, the app root still does **not** match the
graph gate. Normalising the gate does not make the root claim to be the Graph
page; it only lets the trailing-slash form of the Graph path through. The root
is handled by the redirect in Step 1.

**3. How a browser reaches a non-canonical path.** `deploy/nginx/nginx.conf:139-140`:

```nginx
        location = / {
            return 302 /app;
```

so `/` → `/app` → (Flask strict-slash 308) → `/app/`, which Dash serves as the
app root. `display_page` receives `pathname = "/app/"`, matches no route, and
takes the fallthrough. **Confirmed in the UI container log** on 2026-11-10:
`GET /app/graph status=200` once, vs `GET /app/ status=302` 73 times.

### Verified behaviour (measured 2026-11-10)

Replaying the catalog callback through `POST /app/_dash-update-component` with a
real session cookie:

| `url.pathname` supplied | `query-catalog-store.data` |
|---|---|
| `/app/graph` | **140 items** |
| `/app/` | `null` |
| `/app` | `null` |

So the loader is correct; only the URL is wrong.

### Repo conventions that apply

- The UI has exactly **one** `before_request` hook, registered at
  `src/ui/session_guard.py:115-122` (`register_session_guard`). The module
  docstring explains why there is only one: "a single ``before_request`` is
  simpler to reason about than two." **Add any server-side redirect there, not
  in a second hook.**
- `src/ui/session_guard.py:53-57` shows the existing navigation-vs-callback
  distinction (`_is_dash_xhr`): a redirect must only be returned for a document
  navigation. Returning a 302 to a Dash callback breaks it (Dash parses the
  response as JSON).
- Tests carry markers. `unit` for pure logic; `server` for anything driving
  `https://localhost` (the Compose stack must be up; those tests **fail**, not
  skip, when it is down).
- Do **not** commit or push unless asked.

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Unit tests | `pytest -m unit tests -q` | ≥ **2632 passed**, 0 failed, 2 skipped |
| Targeted tests | `pytest -m unit tests/test_ui_session_guard_stale.py -q` | all pass |
| Typecheck | `mypy src/` | exit 0 |
| Lint | `pylint src --score=y` | ≥ 10.0 |
| Style | `flake8` | exit 0 |
| Stack (for server tests) | `docker compose up -d` | all services healthy |

## Scope

**In scope**:
- `src/ui/session_guard.py` — add the canonicalising redirect
- `deploy/nginx/nginx.conf` — point `location = /` at the canonical path
- `src/ui/pages/graph/callbacks/catalog.py` — normalise the `pathname` gate
- `src/ui/pages/graph/callbacks/analytics_mode.py` — normalise the `pathname` gate
- `tests/test_ui_session_guard_stale.py` — extend (this is the existing
  session-guard test file; there is no `tests/test_session_guard.py`)
- `tests/test_catalog_favourites_ui.py` — extend with the `/app/graph/` cases
- `tests/` — a `server`-marked test for the redirect, if none exists

**Out of scope** (do NOT touch):
- `display_page`'s fallthrough in `src/ui/layout.py`. Removing it would turn a
  mistyped URL into an error page — a regression. The fallthrough stays; this
  plan ensures users do not *arrive* at a path that only half-works.
- The **other** `pathname`-gated callbacks under `src/ui/pages/` (connectors,
  catalog, settings). They already tolerate both slash forms — see the
  "Current state" section — so there is nothing to change. Leave them alone.
- `src/app/api/auth/v1/service.py` — `DEFAULT_NEXT_PATH` is already `/app/graph`.
  **This file also holds the post-logout URI, which must stay `/app` — see the
  STOP conditions. Do not "align" it to `/app/graph`.**
- `deploy/keycloak/realm-wba.json.template` — the realm's
  `post.logout.redirect.uris` is registered as `${APP_PUBLIC_BASE_URL}/app` and
  must not change. See the STOP conditions.
- Any `src/app/` change.

## Steps

### Step 1: Canonicalise the app root server-side

Add a redirect in `session_guard` so a document navigation to `/app` or `/app/`
lands on `/app/graph`. Place it **before** the session checks, so an
unauthenticated browser is canonicalised and then redirected to login with the
correct `next` (rather than logging in and landing back on the broken path).

The rule must:

- match exactly `/app` and `/app/` (after `rstrip("/")`), nothing else
- apply **only** to document navigations (reuse the existing `_is_dash_xhr()`
  check — return `None` and let the request through for a callback)
- return `302` with `Location: /app/graph`
- log the redirect, matching the existing `logger.info(f"Session guard: …")`
  style at `src/ui/session_guard.py:69`

**Verify**: `pytest -m unit tests/test_ui_session_guard_stale.py -q` → all pass.

**Verify** (manual, stack up):

```
docker compose exec -T ui sh -lc 'echo probe'
```

then confirm in the UI log that a `GET /app/` navigation is followed by a
`GET /app/graph` 200 rather than rendering the root.

### Step 2: Fix the root redirect in nginx

`deploy/nginx/nginx.conf:139-140` currently sends `/` to `/app`, which then
takes the 308 → `/app/` hop into the broken path. Point it at the canonical URL
directly:

```nginx
        location = / {
            return 302 /app/graph;
```

**This file is bind-mounted.** A plain `nginx -s reload` may keep serving the
old config (the container can hold a stale inode). Recreate the container and
confirm it sees the edit:

```
docker compose up -d --force-recreate nginx
docker compose exec -T nginx sh -lc 'grep -n "app/graph" /etc/nginx/nginx.conf'
```

**Verify**: the grep prints the line you added. If it does not, the container is
serving a stale bind mount — STOP and report.

**Verify**: `docker compose config -q` → exit 0 (compose file still valid; this
file is not part of it, but run it to confirm nothing else broke).

### Step 3: Prove the previously-broken path now works

With the stack up and the containers recreated:

1. Navigate to `https://localhost/` in a fresh tab, signed in.
2. Confirm the address bar ends at `/app/graph` and the Query Catalog panel
   lists queries (not "No catalog metadata loaded yet").
3. Repeat for `https://localhost/app` and `https://localhost/app/` typed
   directly.

**Verify**: record the final URL and whether the catalog loaded, for all three.

### Step 4: Normalise the two Graph gates so `/app/graph/` also loads

`/app/graph/` renders the Graph layout (`display_page` normalises the slash) but
both gates reject it, so it shows the same dead catalog panel. Normalise the
comparison in both:

```python
# src/ui/pages/graph/callbacks/catalog.py:273
    if (pathname or "").rstrip("/") != "/app/graph":
        return no_update, no_update, no_update
```

```python
# src/ui/pages/graph/callbacks/analytics_mode.py:16
    if (pathname or "").rstrip("/") != "/app/graph":
        return {}, {}
```

Change **only** the guard expression. Do not alter either callback's return
values, docstring, or decorator. Do not use a prefix/`startswith` match — that
would also accept `/app/graphs` or `/app/graph/x`, which are different routes.

**Verify**: `pytest -m unit tests -q` → no new failures (≥ 2632 passed).

**Verify**: `pytest -m unit tests/test_catalog_favourites_ui.py -q` → all pass
(this file already drives `load_query_catalog("/app/graph")`).

## Test plan

- Extend `tests/test_ui_session_guard_stale.py` with `unit`-marked cases for the
  new predicate: `/app` and `/app/` → canonical target; `/app/graph`,
  `/app/analytics`, and `/app/` carrying an XHR header → not redirected.
  **Read the file first and match its structure exactly.** It already has the
  scaffolding this needs:
  - an `app` fixture returning a bare `Flask(__name__)`
  - a `transport` fixture that monkeypatches `api_client._transport` and
    `auth._post`, so no real HTTP is made
  - a `_request(app, path, *, cookie=..., method=...)` helper building a
    `test_request_context`
  - `pytestmark = pytest.mark.unit` and the `_StubResponse` class

  A redirect test therefore looks like
  `with _request(app, "/app/", cookie=True): response = session_guard()` then
  asserting `response.status_code == 302` and the `Location` header. Reuse the
  file's own idiom; do not introduce a second style.
- Non-vacuousness: the `/app/graph` and `/app/analytics` negative cases must
  **fail** if the predicate is widened to a prefix match. Confirm by temporarily
  widening it, observing the failure, and reverting.
- If a `server`-marked test is added, it must assert the redirect **status and
  `Location` header** for `/` and `/app/`, not merely a 200 somewhere.
- For Step 4, add `unit` cases that call `load_query_catalog` directly (and
  `toggle_query_panel_for_analytics_mode`), asserting it does **not** return
  `no_update` for `/app/graph/`. `tests/test_catalog_favourites_ui.py:175`
  already calls `load_query_catalog("/app/graph")` — match that idiom. Include a
  negative case: `/app/graphs` and `/app/graph/x` must still be rejected, so a
  `startswith` regression is caught.

## Done criteria

- [ ] `pytest -m unit tests -q` exits 0, ≥ 2632 passed
- [ ] `mypy src/` exits 0; `pylint src --score=y` ≥ 10.0; `flake8` exits 0
- [ ] `https://localhost/`, `https://localhost/app`, `https://localhost/app/`
      all end at `/app/graph` with the catalog loaded (Step 3 observed)
- [ ] `https://localhost/app/graph` still renders normally
- [ ] `https://localhost/app/graph/` also loads the catalog (Step 4)
- [ ] A Dash callback request is **not** redirected (no 302 on `/_dash-*`)
- [ ] `nginx.conf` edit is live in the container (`grep` inside the container)
- [ ] `src/app/api/auth/v1/service.py` and
      `deploy/keycloak/realm-wba.json.template` are unmodified
      (`git status` shows neither)
- [ ] No file outside the in-scope list modified
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report if:

- `display_page`'s fallthrough or the `pathname != "/app/graph"` gates do not
  match the excerpts above — the codebase drifted.
- Canonicalising `/app/` breaks the login flow: verify that a **logged-out**
  navigation to `https://localhost/` still ends at the Keycloak login page and,
  after signing in, lands on `/app/graph` with the catalog loaded. If it lands
  anywhere with an empty catalog, stop.
- The nginx container cannot be made to serve the edited config.
- The `pathname` values observed in the browser differ from `/app/` (e.g. Dash
  is configured with a different prefix than the plan assumes) — record what you
  actually see.
- **You are tempted to change the post-logout redirect to `/app/graph`.** Do
  not. The app's post-logout URI is `/app`, and it is registered with Keycloak
  as `post.logout.redirect.uris = ${APP_PUBLIC_BASE_URL}/app`
  (`deploy/keycloak/realm-wba.json.template`), matching the value the API sends
  as `post_logout_redirect_uri` (`src/app/api/auth/v1/service.py`, the
  RP-initiated logout URL). Keycloak validates the requested URI against that
  registered set. Changing either to `/app/graph` makes Keycloak reject the
  request and render its own error page instead of returning the user, and the
  realm **cannot** be re-seeded non-destructively (`--import-realm` is
  create-only). Canonicalising `/app` → `/app/graph` at the nginx/UI layer is
  the intended fix; the registered `/app` URI is correct and must stay. If you
  believe it must change, STOP and report.

## Maintenance notes

- **The invariant this protects:** any path that `display_page` routes to the
  Graph layout — whether by an explicit route, the trailing-slash normalisation,
  or the fallthrough — must leave the Graph page fully wired. The fallthrough is
  a safety net for typos, not a route; `/app` and `/app/` were the paths that
  broke it.
- **The post-logout URI is deliberately `/app`, not `/app/graph`.** It is
  registered with Keycloak and cannot be changed without a realm re-seed. A
  future change that "canonicalises the root" must not touch it.
- **A reviewer should scrutinize**: that the redirect is navigation-only (a
  redirected Dash callback breaks the page), and that the nginx change is
  actually live — a bind-mounted config can silently serve a stale inode, so the
  in-container `grep` is the proof, not the host file.
- **If a future page adds another `pathname`-gated callback**, the same trap
  reappears for any path that renders its layout. Prefer gating on the *page
  identity* rather than a literal URL string, or add the route to `display_page`
  explicitly.
- **Deferred**: making the fallthrough itself smarter (rendering a "page not
  found" affordance rather than the Graph layout). That is a UX decision, not a
  defect fix.

## Execution record — 2026-11-10 — DONE

All four steps executed uncommitted in the working tree on
`feature/callback-issue`.

| Step | Change | Evidence |
|---|---|---|
| 1 | `session_guard` canonicalises `/app` and `/app/` to `/app/graph` before the session checks | 13 targeted tests pass, incl. the no-redirect cases for `/app/graph`, `/app/analytics`, and XHR |
| 2 | nginx `location = /` → `/app/graph` | in-container grep line 140, `nginx -t` ok, `curl /` → `302 /app/graph` |
| 3 | Rebuilt the `ui` image (no source mount) and browser-verified all three root forms plus the logged-out flow | all land on `/app/graph` with 140 catalog queries; API log shows the fetch |
| 4 | Both Graph gates normalised with `rstrip("/")` | `/app/graph/` loads; `/app/graphs` still empty; full suite 2647 passed |

**Verification gates**: `pytest -m unit tests -q` → 2647 passed, 0 failed,
2 skipped; `mypy src/` exit 0; `pylint src` 10.00/10; flake8 findings on the
edited files are byte-identical to HEAD (pre-existing).

**Note for a future run**: the `ui` service has no source bind-mount, so a UI
change is not live until `docker compose up -d --build ui`. Step 3 would have
produced a false failure against the stale image.

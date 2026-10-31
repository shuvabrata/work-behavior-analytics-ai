# Plan 056: Add the login flow, the BFF token exchange, the UI session guard, and the SSE proxy

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving on. If
> anything in "STOP conditions" occurs, stop and report — do not improvise.
> When done, update the status row in `plans/README.md`.
>
> **Gate policy**: Steps 1–3 are **automated-only** — run their verification
> commands, paste the output in your report, and continue without waiting. There
> is **one MANUAL GATE**, at the end of Step 4, and it covers only what no
> automated check can see: that the chat answer streams incrementally through the
> proxy rather than arriving in one buffered chunk, that the account bar renders,
> and that login/logout round-trips in a real browser. A `FAIL` at that gate is a
> STOP condition.
>
> **Drift check (run first)**: `git diff --stat 225d3639..HEAD -- src/app/api_main.py src/ui/api_client.py src/ui/layout.py src/ui_main.py src/ui/assets/stream-bridge.js src/ui/request_logging.py deploy/nginx/nginx.conf tests/test_chat_stream_bridge.py`
> Any mismatch against "Current state" is a STOP condition.

## Status

- **Priority**: P1
- **Effort**: L
- **Risk**: HIGH
- **Depends on**: plans/055
- **Category**: security
- **Planned at**: commit `225d3639`, 2026-10-30
- **Design reference**: `docs/design/authn-authz-design.md`, "Dash Integration
  (BFF)", "Session Management", "Login sequence"
- **This is step 4 of 9** in the Plan C sequence.

## Why this matters

After this step a real user can log in through Keycloak, the Dash UI carries
the session cookie, and every UI→API call sends a bearer token that Dash minted
server-side from that cookie. Chat streaming moves from a browser-direct API
call to a cookie-authenticated Dash proxy route, so the browser never holds a
token.

**Enforcement is still off.** The API accepts a bearer when present but does not
require one; that switch is plan 057. This ordering is deliberate and is the
only one in which every step leaves a working stack: enforcement must land
*after* the UI can send a credential, never before.

The consequence you must state plainly to the operator: between this plan and
plan 057 there is a short window where users log in but the API would still
answer an unauthenticated request. That window is closed by the very next plan;
do not compensate for it by adding enforcement early.

What improves when this lands: real login/logout, a session table in use, a
per-worker token cache, `/api/v1/auth/me`, and a working stream that no longer
depends on the browser talking to the API.

## Current state

**`src/ui/api_client.py`** — the single UI→API chokepoint (~250 lines). Key
facts:

- `_call()` builds `url = settings.API_BASE_URL.rstrip("/") + path` and calls
  `transport(method, url, params=..., json=..., timeout=runtime_settings.get_int("HTTP_REQUEST_TIMEOUT"))`.
- `ApiError(Exception)` carries `status_code`, `detail`, `detail_error`, `message`.
- `STATUS_NO_RESPONSE = 0` for transport failures.
- `set_transport()` is the test seam. **47 `except ApiError` sites across 16
  files** rely on this one type — plan 058 subclasses it, do not change it here.

**`src/ui_main.py`** — the UI entrypoint, 12 lines:

```python
app = create_dash_app()
server = app.server  # Flask — served by gunicorn
register_request_logging(server)
```

**`src/ui/layout.py:27-28`** — both prefixes are `/app/`:

```python
        requests_pathname_prefix="/app/",
        routes_pathname_prefix="/app/",
```

Consequently a Flask route registered on `server` as `/stream/<session_id>` is
reachable by the browser at **`/app/stream/<session_id>`** with no mount.

**`src/ui/request_logging.py`** — already defines `server.before_request`
(`_before_request`, line 33). It currently only drives
`refresh_if_stale()` and logging. **The session guard is added here** — do not
register a second `before_request` on the same server unless you confirm Flask
runs both in registration order (it does, but one hook is simpler to reason about).

**`src/ui/assets/stream-bridge.js:215`** — the only browser-direct API call:

```js
            fetch('/api/v1/chats/' + sessionId + '/stream', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ message: message })
            }).then(function (response) {
```

**`tests/test_chat_stream_bridge.py:171-176`** — the only guard on that URL,
and it is **vacuous**: it asserts `"/stream" in content`, which stays true for
`/app/stream/`. Step 3 replaces it with an exact assertion.

**`deploy/nginx/nginx.conf`** — has `location /api/v1/chats/` with
`proxy_buffering off` for the stream. After this change the browser calls
`/app/stream/...`, which falls under `location /app`, so the proxy route must
set `X-Accel-Buffering: no` itself.

**Baseline**: `pytest -m unit tests -q` → 2391 passed plus plans 054-055's tests.

### Repo conventions that apply

- API layering is strict: `model.py` (Pydantic), `router.py` (HTTP only),
  `service.py` (business logic, transaction boundaries), `query.py` (DB access).
- Routers are included in `src/app/api_main.py` with `prefix="/api/v1"`.
- Async SQLAlchemy 2.0 (`Mapped`/`mapped_column`), `get_async_db` for sessions.
- UI pages must not import across page packages; shared code lives in `ui/` or
  `ui/components/`. A new shared component goes in `src/ui/components/`.
- Settings: `ui.settings.settings` for the UI, `app.settings.settings` for the
  API. Both now carry the `KEYCLOAK_*` / `AUTH_*` fields from plan 053.
- Use `create_alert` (`src/ui/components/common.py:159`) for feedback; the
  canonical feedback-region placement is `pages/settings/runtime.py:300`.
- **Never log a token, refresh token, or client secret.**
- Do **not** commit or push unless asked.

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Unit tests | `pytest -m unit tests -q` | ≥ baseline, 0 fail |
| Typecheck | `mypy src/` | exit 0 |
| Lint | `pylint src --score=y` | ≥ 9.0 |
| Security scan | `bandit -c .bandit.yml -r src/ -lll` | exit 0 |
| Compose config | `docker compose config -q` | exit 0 |
| Rebuild a runtime | `docker compose up -d --build api ui` | both healthy |
| Nginx syntax | `docker run --rm --network work-behavior-analytics-ai_wba-ai-network -v "$PWD/deploy/nginx/nginx.conf:/etc/nginx/nginx.conf:ro" -v "$PWD/deploy/certs:/etc/nginx/certs:ro" nginx:1.30-alpine nginx -t` | syntax ok |
| Login redirect | `curl -s -o /dev/null -w '%{http_code} %{redirect_url}' 'https://localhost/api/v1/auth/login?next=/app/graph'` | `302` to Keycloak |

**The API and UI images have no source bind-mount.** Every `curl https://localhost`
verification below runs against the container, so run
`docker compose up -d --build api ui` at the start of each step that changes
container code (Step 1 → `api`, Steps 2–3 → `ui`) and wait for `healthy` before
running that step's curls. A green curl against a stale image proves nothing.

## Scope

**In scope**:
- `src/app/api/auth/__init__.py`, `model.py`, `query.py`, `service.py`, `router.py` (create)
- `src/app/api_main.py` — include the auth router (only the include line).
- `src/app/auth/session_cookie.py` (create) — cookie name, hashing, PKCE state cookie.
- `src/ui/auth.py` (create) — per-worker token cache and session-cookie helpers.
- `src/ui/api_client.py` — attach the bearer header.
- `src/ui/runtime_settings.py` — route the snapshot fetch through `api_client`.
- `src/ui/request_logging.py` — the session guard (or a new `src/ui/session_guard.py` registered there).
- `src/ui/stream_proxy.py` (create) — the SSE proxy Flask route.
- `src/ui_main.py` — register the stream proxy route.
- `src/ui/assets/stream-bridge.js` — the one-line URL change.
- `src/ui/components/account_bar.py` (create) — username and logout (no role
  badge; see Step 3b).
- `src/ui/layout.py` — render the account bar in the topbar.
- `tests/test_auth_flow.py`, `tests/test_auth_session_service.py`,
  `tests/test_ui_auth.py`, `tests/test_stream_proxy.py` (create)
- `tests/test_chat_stream_bridge.py` — strengthen the vacuous assertion.

**Out of scope** (do NOT touch):
- **Enforcement.** No `Depends(require_*)` may be added to any existing router.
  That is plan 057.
- Per-user ownership of chats/favourites — plan 057.
- The 401/403 UI behaviour (banners, redirect on expiry) — plan 058. In this
  step a 401 surfaces as the page's ordinary error, exactly as today.
- `graph_themes` ownership — plan D.
- `src/common/` — service tokens shipped in plan 055.

## Steps

### Step 1: The API side — cookie primitives, session service, and the auth endpoints

Three parts, all API-side. Write the tests for this step in the same step.

#### 1a. Session-cookie primitives

Create `src/app/auth/session_cookie.py`:

- `SESSION_COOKIE_NAME = "wba_session"` — the opaque id the browser holds.
- `PKCE_COOKIE_NAME = "wba_oidc"` — the login-in-progress cookie.
- `hash_session_id(raw: str) -> str` — SHA-256 hex. **The raw id is never
  stored**; the row holds this hash.
- `new_session_id() -> str` — `secrets.token_urlsafe(32)`.
- `encode_pkce_cookie(state: str, verifier: str) -> str` — serialize to JSON,
  then Fernet-encrypt with `app.common.encryption.encrypt` so the verifier is
  never readable by the browser. Returns the token string.
- `decode_pkce_cookie(value: str) -> tuple[str, str]` — decrypt and parse;
  raises `ValueError` on a bad token or shape.
- Cookie attribute constants derived from settings, in one place so the UI and
  API cannot disagree:
  `cookie_kwargs() -> dict` returning
  `{"httponly": True, "secure": settings.AUTH_COOKIE_SECURE, "samesite": "Lax", "path": "/"}`.
  **`path="/"` is required** — the UI mounts at `/app` and the auth endpoints
  at `/api`, so a narrower path would make one side unable to see the cookie.

#### 1b. The `auth_session` service and query layer

Create `src/app/api/auth/` following the repo's four-file layering.

`query.py` — DB access only:

- `async def create_session(db, *, session_id_hash, subject, username, roles, refresh_token_encrypted, expires_at) -> AuthSession`
- `async def get_active_session(db, session_id_hash) -> AuthSession | None` —
  a row with `revoked_at IS NULL`.
- `async def touch_session(db, row, *, last_seen_at, refresh_token_encrypted: str | None = None) -> None`
  — updates `last_seen_at` (and the rotated refresh token, if given).
- `async def revoke_session(db, row, *, revoked_at) -> None`
- `async def purge_expired(db, *, now) -> int` — deletes rows well past
  `expires_at` or `revoked_at`; called opportunistically, never on a request path.

`service.py` — business logic and transaction boundaries:

- `async def start_login(next_path: str) -> LoginRedirect` — generate `state`
  and a PKCE `code_verifier` + `S256` challenge, build the Keycloak authorize
  URL from **`settings.KEYCLOAK_ISSUER`** (`/protocol/openid-connect/auth`) with
  `client_id`, `redirect_uri = f"{settings.APP_PUBLIC_BASE_URL}/api/v1/auth/callback"`,
  `response_type=code`, `scope="openid profile"`, `code_challenge`,
  `code_challenge_method=S256`, `state`. Also return the encoded PKCE cookie.
  **Sanitise `next_path`**: accept only a value starting with `/app` and
  containing no `//`, `\`, or newline; otherwise fall back to `/app/graph`.
  This is the open-redirect guard.

  **Use `settings.APP_PUBLIC_BASE_URL`, not `EXTERNAL_BASE_URL`, and not a
  literal host.** The redirect URI must be byte-identical to what the realm's
  `redirectUris` entry resolves to (plan 053 templates that entry from
  `APP_PUBLIC_BASE_URL`). `APP_PUBLIC_BASE_URL` carries a startup validator that
  keeps it consistent with `KEYCLOAK_ISSUER`, so a deployment that sets a real
  domain changes one setting and every redirect follows. A hardcoded
  `https://localhost` here would work in dev and fail in production with a
  `redirect_uri` mismatch.
- `async def complete_login(db, *, code, state, pkce_cookie_value) -> LoginResult`
  — decode the PKCE cookie, compare `state` in constant time
  (`secrets.compare_digest`), POST to
  `{settings.KEYCLOAK_INTERNAL_URL}/protocol/openid-connect/token` with
  `grant_type=authorization_code`, `code`, `redirect_uri`,
  `client_id`, `client_secret`, `code_verifier`; validate the returned
  `access_token`/`id_token` via plan 054's `validate_bearer_token`; create the
  session row with `refresh_token_encrypted = encrypt(refresh_token)`,
  `expires_at = now + settings.AUTH_SESSION_MAX_HOURS`;
  return the raw session id and the redirect target.
- `async def exchange_token(db, *, session_id) -> TokenResponse` — the BFF
  mechanism, specified below.
- `async def logout(db, *, session_id) -> str` — revoke the row, build the
  Keycloak `end_session_endpoint` URL from discovery with `id_token_hint` (or
  `client_id` when no id_token is retained) and
  `post_logout_redirect_uri = f"{settings.APP_PUBLIC_BASE_URL}/app"`; return it.

**Do not store the access token or the id_token** in the row. Only the
refresh token (encrypted) is persisted; the access token is returned to the
caller and never written down.

#### 1c. The token-exchange endpoint

This is the one endpoint that reads the session cookie, and the security core
of the plan. Implement `exchange_token`:

1. `hash_session_id(session_id)` → look up an active row. Missing/revoked → 401.
2. **Enforce the app caps** against the row and runtime settings:
   - idle: `now - last_seen_at > AUTH_SESSION_IDLE_MINUTES` → revoke, 401.
   - max: `now > expires_at` → revoke, 401.
3. **Always refresh at Keycloak** (do not try to reuse a stored access token —
   none is stored). POST `client_credentials`-style form to
   `{KEYCLOAK_INTERNAL_URL}/protocol/openid-connect/token` with
   `grant_type=refresh_token`, `client_id`, `client_secret`,
   `refresh_token=decrypt(row.refresh_token_encrypted)`.
4. **Persist the rotated refresh token.** Keycloak returns a new
   `refresh_token` on refresh. Overwrite `row.refresh_token_encrypted` with
   `encrypt(new_refresh_token)` and update `last_seen_at` in the same
   transaction. **Skipping this logs every user out at the first refresh** —
   this is the highest-value bug this step can introduce.
5. On `invalid_grant` / 400 from Keycloak: revoke the row and return 401.
   On a transport failure / 5xx: return **503** and leave the row alone, so a
   Keycloak restart does not destroy sessions.
6. Re-validate the returned access token with `validate_bearer_token` (roles
   are re-read from the refreshed token, so a revoked role takes effect within
   one access-token lifetime) and refresh `row.roles` with the new snapshot.
7. Return `{"access_token": ..., "token_type": "bearer", "expires_in": ...}`.

`router.py` endpoints:

| Method | Path | Auth | Notes |
|---|---|---|---|
| `GET` | `/auth/login` | public | `?next=`, returns 302 to Keycloak, sets the PKCE cookie |
| `GET` | `/auth/callback` | public | validates state, creates the session, sets `wba_session`, clears the PKCE cookie, 302 to `next` |
| `POST` | `/auth/logout` | session cookie | revokes the row, clears the cookie, 302 to Keycloak's end-session URL |
| `POST` | `/auth/token` | session cookie | **the BFF exchange**; returns a bearer |
| `GET` | `/auth/me` | bearer | returns `{subject, username, roles}` |

For `/auth/me`, use plan 054's `get_principal` — it is the one route in this
step that uses a role dependency, and it needs only "any authenticated
principal". Give it `require_user`.

Include the router in `src/app/api_main.py` next to the others:

```python
app.include_router(auth_v1_router, prefix="/api/v1")
```

and add the import beside the existing router imports.

#### 1d. Tests for this step

**`tests/test_auth_flow.py`** — `pytestmark = pytest.mark.unit`
Through `httpx.ASGITransport` against the real `app`, with the **token
endpoint's Keycloak calls stubbed** (no network):
- `/auth/login` returns 302 with `code_challenge_method=S256`, `state`, and the
  exact `redirect_uri`.
- `/auth/login?next=https://evil.example` results in a `next` that is `/app/graph`.
- `/auth/callback` with a mismatched `state` → 400 and **no** session row.
- `/auth/callback` happy path → sets `wba_session` with `HttpOnly`, `Secure`,
  `SameSite=Lax`, `Path=/`, and creates exactly one row.
- `/auth/token` with no cookie → 401; with a revoked row → 401; with an expired
  idle row → 401 **and** the row is revoked.
- **`/auth/token` twice returns a refreshed token and the row's
  `refresh_token_encrypted` changes each time** — the rotation-persistence test.
- Keycloak returning 500 on refresh → **503**, and the row is **not** revoked.
- `/auth/logout` revokes the row and clears the cookie.

**`tests/test_auth_session_service.py`** — `pytestmark = pytest.mark.unit`
- idle/max comparisons at the boundary (exactly at the limit vs one second past).
- `username`/`roles` snapshot written at creation.
- `next` sanitiser table: `/app/graph` ok; `//evil`, `https://evil`,
  `/app/../x`, and a newline all fall back.

**Verify** (all automated — no hand-back):
- `PYTHONPATH=src python -c "
from app.auth.session_cookie import hash_session_id, new_session_id, encode_pkce_cookie, decode_pkce_cookie
s=new_session_id(); c=encode_pkce_cookie('st','vf'); print(len(hash_session_id(s))==64, decode_pkce_cookie(c))"` → `True ('st', 'vf')`
- `mypy src/app/auth/ src/app/api/auth/` → exit 0
- `pytest -m unit tests/test_auth_flow.py tests/test_auth_session_service.py -q` → all pass
- `docker compose up -d --build api` → healthy
- `curl -s -o /dev/null -w '%{http_code}' 'https://localhost/api/v1/auth/login?next=/app/graph'` → `302`
- `curl -s -o /dev/null -w '%{redirect_url}' 'https://localhost/api/v1/auth/login?next=/app/graph'` → starts with `https://localhost/auth/realms/wba/protocol/openid-connect/auth`
- `curl -s -o /dev/null -w '%{http_code}' -X POST https://localhost/api/v1/auth/token` → `401`
- `curl -s https://localhost/api/v1/auth/me -H 'Cookie: wba_session=bogus'` → `401`
- `grep -rn "access_token\|refresh_token" src/app/api/auth/ | grep -i logger` → no matches (no token is ever logged)

**Dependency, do not skip:** the login page's CSS/JS come from
`/auth/resources/...`, which nginx must proxy — plan 053 originally proxied only
`/auth/realms/` and that made the login form render unstyled (all assets 404).
That is fixed in 053; if login works but looks broken, check
`curl -s https://localhost/auth/realms/wba/account | grep -oE '(src|href)="/[^"]+"'`
returns paths that fetch `200` through nginx. **Also note the login page must be
reached on `https://localhost`, not the keycloak loopback port** — the port serves
only the admin console (`KC_HOSTNAME_ADMIN`).

The open-redirect sanitiser is covered by the unit test's `next` table and by the
`/auth/login?next=https://evil.example` case above — the **state cookie** carries
`next`, so assert it in the callback test rather than by hand.

---

### Step 2: The UI credential path — token cache, bearer header, session guard

Three parts, all UI-side, plus their tests. Nothing here requires a browser.

#### 2a. The UI token cache

Create `src/ui/auth.py`:

- `get_token() -> str` — read the `wba_session` cookie from Flask's request
  context. If absent, raise `SessionMissingError`. Otherwise look up a
  module-level dict `{session_id_hash: (token, expires_at_monotonic)}`. Reuse
  while more than **60 s** remain; else POST to
  `{settings.API_BASE_URL}/api/v1/auth/token` with `cookies={"wba_session": raw}`
  (do **not** send the shared client, to avoid a recursion: `api_client` calls
  this module), cache and return the token.
- `invalidate_token() -> None` — drop the current cookie's entry, so a 401 can
  force one re-exchange.
- `current_session_id() -> str | None` — read the cookie, for the guard and the
  account bar.
- Use a `threading.Lock`; gunicorn runs `gthread` with 4 workers × 8 threads.
- **Never put the token in a cookie, a Dash store, or the page.** It lives in
  this dict only.
- On a 401 from `/auth/token`, raise `SessionMissingError`; on 503/transport
  failure raise `TokenExchangeUnavailable`.

**Do not import `ui.api_client` from this module** — `api_client` imports
`ui.auth`, and the reverse edge is an import cycle.

#### 2b. Attach the bearer header in the shared client

In `src/ui/api_client.py`, in `_call()` add the header **when a session cookie is
present**, and leave the client working unchanged when it is not (tests and the
pre-login surface).

```python
    headers: dict[str, str] = {}
    try:
        headers["Authorization"] = f"Bearer {get_token()}"
    except (SessionMissingError, TokenExchangeUnavailable):
        # No session (tests, or an unauthenticated surface) — send without one.
        # Plan 057 makes the API require it; until then this degrades exactly as
        # today, so a missing cookie never masks a real API error.
        pass
```

Then pass `headers=headers` to the transport call. Keep `set_transport()` and
the `ApiError` contract **exactly** as they are — 47 handlers depend on them.

A `401`-triggered single retry belongs to plan 058 (where the redirect lives).
Do not add it here.

#### 2c. The UI session guard

Add a guard to `src/ui/request_logging.py` (or a new `src/ui/session_guard.py`
imported and registered from there) inside the existing `before_request`:

Behaviour, in order:

1. Skip entirely for **static assets** — any path starting with `/app/assets/`.
   Also skip `/app/_dash-layout` and `/app/_dash-dependencies`: Dash fetches
   these during initial render, and blocking them produces a blank page instead
   of a login redirect. Everything else, including `/app/_dash-update-component`
   and `/app/stream/…`, is guarded.
2. If a `wba_session` cookie is present → allow. **Do not validate it here.**
   The API is the authority; the first API call returns 401 if the row is gone,
   and plan 058 turns that into a redirect. A cookie check here would either
   duplicate the API's logic or require a DB the UI does not have.
3. If the cookie is **absent**:
   - **A document navigation** (method `GET`, and the request does not look like
     a Dash XHR) → `302` to
     `/api/v1/auth/login?next=<request.path>`. Detect a Dash XHR by the
     `X-Requested-With` header **or** a path under `/app/_dash-`; Dash's fetch
     does not always set the former, so check both.
   - **A Dash callback / XHR** → return a **401 JSON** response
     (`{"detail": {"error": "unauthenticated"}}`), so the page shows an error
     instead of parsing an HTML login page as JSON.
4. Always let `/app/assets/*` through — blocking them leaves the login page
   unstyled and the app unusable churn.

Exclude the health/asset paths that gunicorn or nginx probe; the existing
`/app/` health check is a navigation and will 302 when logged out, which is
acceptable (nginx treats `302` as a healthy response). **Confirm this**, do not
assume it: `docker compose ps ui` must stay `healthy`.

#### 2d. Route the UI's runtime-settings fetch through the client

The UI keeps a runtime-settings cache and refreshes it from the API's
`GET /api/v1/settings/runtime-snapshot` via `refresh_if_stale()`. Today
`src/ui/runtime_settings.py:96-98` reaches that endpoint with
`common.runtime_settings.client.fetch_runtime_snapshot`, which authenticates with
a **service** token — and the UI container holds no `KEYCLOAK_*` env, so
`get_service_token()` there always raises and the request goes out
unauthenticated.

That is harmless **today only because the snapshot route has no auth dependency
yet** (`src/app/api/settings/v1/router.py:41` takes just `db`). Plan 057's Step 4a
promotes it to `require_any("user", "admin", "service")`. From that moment the
UI's credential-free fetch 401s; `fetch_runtime_snapshot` treats any non-200 as
"API unreachable", logs a warning, and returns bare `RuntimeConfig()` defaults;
`refresh()` sees an all-defaults snapshot and returns early keeping current
values. The result is a **silent** failure — the UI stops picking up runtime
settings edits, with no error and no broken page:

```python
# src/ui/runtime_settings.py — current behaviour after 057
snapshot = fetch_runtime_snapshot(settings.API_BASE_URL)
if snapshot == RuntimeConfig():
    logger.warning("UI runtime-settings snapshot was empty — keeping current values")
    return
```

**Do this here, not in 057.** This step is where the UI first acquires a
credential; before it, the shared helper is the only option, and after 057 the
window is already broken. Change `refresh()` in `src/ui/runtime_settings.py` to
fetch through `ui.api_client` (`get_json("/api/v1/settings/runtime-snapshot")`),
so the call rides the user's bearer token from 2b.

Two constraints:

- **Keep the degrade.** `refresh()` is called from `before_request` and must
  never raise into the request cycle. Catch `ApiError` — including
  `STATUS_NO_RESPONSE` for a down API — and return early, preserving the values
  the cache already holds, exactly as the current helper's fallback does. Logging
  stays at WARNING.
- **Keep the import edge one-way.** `api_client` imports `ui.runtime_settings`
  at module level (`src/ui/api_client.py:33`), so importing `api_client` at the
  top of `ui/runtime_settings.py` is an **import cycle**. Import it lazily
  inside `refresh()`, the way the shared helper is imported today:

  ```python
  # Imported lazily: ui.api_client imports this module at module level, so a
  # top-level import here is a cycle.
  # pylint: disable=import-outside-toplevel
  from ui import api_client
  ```

**Do not remove the `common.runtime_settings` / `common.auth` imports.**
`src/domain/timezone.py:24` still imports `RuntimeConfigCache` from that package,
and `src/common/runtime_settings/__init__.py:11` re-exports
`fetch_runtime_snapshot`, which pulls in `common.auth` at import. So the UI's
import closure keeps `common.runtime_settings` — and therefore `common.auth` and
the `COPY src/common/auth/ ./common/auth/` line in `Dockerfile.ui:37` — **even
after this change**. Removing that `COPY` breaks the UI image at import. Dropping
it would mean reworking `common/runtime_settings/__init__.py`'s eager re-export
first; if you want that follow-up, write it as a separate plan, not a line in
this step.

#### 2e. Tests for this step

**`tests/test_ui_auth.py`** — `pytestmark = pytest.mark.unit`
- with no cookie, `get_token()` raises `SessionMissingError`.
- with a stub transport, the second `get_token()` reuses the cache.
- a token within 60 s of expiry is re-fetched.
- `invalidate_token()` forces a re-fetch.

**`tests/test_ui_runtime_snapshot_auth.py`** — `pytestmark = pytest.mark.unit`
Drive `ui.runtime_settings.refresh()` with a stub transport (the
`ui.api_client.set_transport` seam) and assert:
- the request goes to `/api/v1/settings/runtime-snapshot` **through
  `api_client`**, so it carries the `Authorization` header 2b attaches — stub
  `get_token` and assert the header is present. Asserting only "headers exist"
  is too weak: pin that the service-token path is gone by also asserting
  `common.runtime_settings.client.fetch_runtime_snapshot` is **not called**
  (patch it and assert `call_count == 0`).
- an `ApiError` (both a 401 and a `STATUS_NO_RESPONSE` transport failure) leaves
  the cache's existing values untouched and does **not** raise.
- a 200 with a populated payload does update the cache.

**Verify** (all automated — no hand-back):
- `grep -n "fetch_runtime_snapshot" src/ui/runtime_settings.py` → no match in
  `refresh()` (the docstring may still name it historically — the call must be gone)
- `grep -n "from ui import api_client" src/ui/runtime_settings.py` → present, and
  **inside** `refresh()`, not at module level
- `pytest -m unit tests/test_ui_runtime_snapshot_auth.py -q` → all pass
- `PYTHONPATH=src python -c "import ui.auth"` → no error
- `grep -n "wba_session" src/ui/auth.py` → present (reads it)
- `grep -c "access_token" src/ui/layout.py src/ui/assets/*.js` → `0` (the token never reaches the page)
- `grep -n "Authorization" src/ui/api_client.py` → exactly one occurrence
- `grep -n "import.*api_client" src/ui/auth.py` → **no match** (no import cycle)
- `mypy src/ui/auth.py` → exit 0
- `pytest -m unit tests -q` → ≥ baseline (the existing client tests pass a stub transport and no cookie, so the header path is not taken)
- `mypy src/` → exit 0
- `pylint src --score=y` → ≥ 9.0
- `docker compose up -d --build ui` → healthy
- `curl -s -o /dev/null -w '%{http_code} %{redirect_url}' https://localhost/app/graph` (no cookie jar) → `302` to `/api/v1/auth/login?next=/app/graph`
- `curl -s -o /dev/null -w '%{http_code}' -X POST -H 'X-Requested-With: XMLHttpRequest' -H 'Content-Type: application/json' -d '{}' https://localhost/app/_dash-update-component` → `401`
- `curl -s -o /dev/null -w '%{http_code}' https://localhost/app/assets/executive-dashboard.css` → `200`
- `docker compose ps ui` → `healthy` after a minute

---

### Step 3: The SSE proxy, the account bar, and the strengthened bridge test

#### 3a. The SSE proxy route

Create `src/ui/stream_proxy.py` with a registration function
`register_stream_proxy(server: Flask) -> None` that adds:

```python
    @server.route("/app/stream/<session_id>", methods=["POST"])
    def stream_proxy(session_id: str) -> Response:
        ...
```

**CORRECTED during execution (2026-10-31).** This plan originally specified
`@server.route("/stream/<session_id>")` and claimed it would be "browser-reachable
at `/app/stream/<session_id>` because both Dash prefixes are `/app/`". **That is
false.** Dash's `requests_pathname_prefix` governs Dash's *own* routes; it does
not prefix a route registered directly on the Flask server. With the bare path,
`POST /app/stream/<id>` is answered by Dash's `/app/<path:path>` catch-all with
**405 Method Not Allowed**, and chat streaming fails in the browser. The route
must carry the `/app` prefix itself.

This defect survived every automated gate because a cookie-less `curl` to
`/app/stream/<id>` returns **401 from the session guard**, which runs before
routing — so the plan's own Step 3 verification (`→ 401`) passed for the wrong
reason. See the execution record at the bottom of this file.

Handler behaviour:

1. `token = get_token()` — inherits the cookie-based exchange.
2. Open the upstream with **`stream=True`**:
   `requests.post(f"{settings.API_BASE_URL}/api/v1/chats/{session_id}/stream", json=request.get_json(silent=True) or {}, headers={"Authorization": f"Bearer {token}"}, stream=True, timeout=(10, None))`.
   Use `requests` directly here, **not** `api_client` (which buffers the body).
3. If the upstream status is >= 400, relay the status and body as JSON (the
   browser's `stream-bridge.js` already renders `HTTP <status>: <body>`), rather
   than starting an event stream.
4. Otherwise return
   `Response(stream_with_context(_relay(upstream)), mimetype="text/event-stream")`
   where `_relay` iterates `upstream.iter_content(chunk_size=None)` and yields,
   closing the upstream in a `finally`.
5. Set `X-Accel-Buffering: no` on the response (nginx buffers `/app` requests by
   default; the `/api/v1/chats/` block that had `proxy_buffering off` is no
   longer in the path).
6. **Stream the client's request body through as-is.** The browser sends
   `{"message": ...}`.

In `src/ui_main.py`, after `register_request_logging(server)`:

```python
register_stream_proxy(server)
```

**Register order matters**: register the proxy *after* the guard/logging is
attached, so the route is covered; Flask applies `before_request` regardless of
route registration order, so both orders are safe — but keep it after for
readability.

In `src/ui/assets/stream-bridge.js` change the URL to the proxy:

```js
            fetch('/app/stream/' + sessionId, {
```

**Do not** change anything else in that file — the SSE parsing, error display,
and resolve contract are all still correct.

#### 3b. The account bar

**API**: `/auth/me` is already in Step 1. Confirm it returns
`{"subject", "username", "roles"}` and uses `require_user`.

**UI**: create `src/ui/components/account_bar.py` exposing
`get_account_bar_layout()`:

- Renders a placeholder container with an `id` (e.g. `account-bar`).
- A `clientside_callback` fetches `settings.API_BASE_URL`? **No** — the browser
  must not call the API. Populate it from a **Python callback** that calls
  `api_client.get_json("/api/v1/auth/me")` and renders username + role badge.
- The logout control is a `dbc.Button` posting a navigation to
  `/api/v1/auth/logout` (the endpoint accepts `POST`, so use a small
  `clientside_callback` that submits a form, or a `dcc.Location` update after a
  `POST` through a Python callback). Choose the simplest that works and record
  which.
- **CORRECTED during execution (2026-10-31): no role badge is rendered.** This
  plan specified "username + role badge". The operator removed the badge while
  testing Step 4 — the role is an authorization detail the API enforces per
  request, not something the top bar needs to advertise. The Step 4 gate
  criterion that asked for it was wrong; see the execution record.
- **No `ConfirmDialog`** — logout is not destructive data loss (the repo's
  ConfirmDialog rule is for destructive actions).
- On `ApiError`, render nothing rather than an error; a missing account bar is
  not user-facing breakage.

Register the callback by adding the module to `src/ui/components/__init__.py`
with `__all__`, and render `get_account_bar_layout()` in the topbar in
`src/ui/layout.py` (find `TOPBAR_STYLE` / the brand element and add it to that
row).

#### 3c. Tests for this step

**`tests/test_stream_proxy.py`** — `pytestmark = pytest.mark.unit`
Use Flask's `test_client`. Stub the upstream with `responses`-style injection or
monkeypatch `requests.post` **locally in the test**:
- no cookie → 401, upstream not called.
- upstream 404 → the browser receives 404 JSON.
- upstream 200 event body → the response is `text/event-stream` and carries
  `X-Accel-Buffering: no`.

**`tests/test_chat_stream_bridge.py`** — replace the vacuous assertion:

```python
def test_stream_bridge_calls_the_app_proxy_not_the_api_directly():
    """The browser must call the cookie-authenticated Dash proxy, never /api/v1."""
    content = _STREAM_BRIDGE.read_text(encoding="utf-8")
    assert "'/app/stream/' + sessionId" in content
    assert "/api/v1/chats" not in content
```

#### 3d. Prove the two new assertions are non-vacuous

The old bridge test passed for the wrong reason; two of the new tests are the
kind that can pass without testing anything, so prove each one **fails** when the
behaviour is removed. This replaces the former manual review of those tests.

**Bridge test** — temporarily point the JS back at the API and confirm the test
fails:

```bash
cp src/ui/assets/stream-bridge.js /tmp/sb.bak
sed -i "s#'/app/stream/' + sessionId#'/api/v1/chats/' + sessionId + '/stream'#" src/ui/assets/stream-bridge.js
pytest -m unit tests/test_chat_stream_bridge.py -q   # MUST FAIL
cp /tmp/sb.bak src/ui/assets/stream-bridge.js
pytest -m unit tests/test_chat_stream_bridge.py -q   # MUST PASS
```

**Refresh-rotation test** — temporarily stop persisting the rotated refresh
token (`touch_session(..., refresh_token_encrypted=None)` in `exchange_token`)
and confirm the rotation test fails:

```bash
cp src/app/api/auth/service.py /tmp/auth-service.bak
# edit exchange_token's touch_session call to pass refresh_token_encrypted=None
pytest -m unit tests/test_auth_flow.py -q            # MUST FAIL on the rotation test
cp /tmp/auth-service.bak src/app/api/auth/service.py
pytest -m unit tests/test_auth_flow.py -q            # MUST PASS
```

Confirm both mutated runs failed for the **expected** assertion, not for an
unrelated import or syntax error.

**Verify** (all automated — no hand-back):
- `grep -n "fetch('/app/stream/'" src/ui/assets/stream-bridge.js` → exactly one match
- `grep -c "api/v1/chats" src/ui/assets/stream-bridge.js` → `0`
- `grep -n "account_bar" src/ui/layout.py` → present
- `grep -n "X-Accel-Buffering" src/ui/stream_proxy.py` → present
- the two mutation runs above behaved as stated
- `pytest -m unit tests/test_stream_proxy.py tests/test_chat_stream_bridge.py -q` → all pass
- `pytest -m unit tests -q` → ≥ baseline + new, 0 fail
- `mypy src/` exit 0; `pylint src --score=y` ≥ 9.0; `bandit -c .bandit.yml -r src/ -lll` exit 0
- `docker compose config -q` exit 0; the `nginx -t` command from the Commands table → syntax ok
- `docker compose up -d --build ui` → healthy
- `curl -s -o /dev/null -w '%{http_code}' -X POST -H 'Content-Type: application/json' -d '{"message":"hi"}' https://localhost/app/stream/does-not-exist` → `401` (no cookie) — proves the route exists and is guarded
- `python - <<'PY'
import ast, pathlib
p = pathlib.Path('src/ui/components/account_bar.py')
ast.parse(p.read_text()); print('parsed')
PY` → `parsed`

---

### Step 4: THE MANUAL GATE — the browser walkthrough

Everything before this is green by automated check. This gate exists for the
three things no command in this plan can observe: **incremental delivery over the
proxy**, **rendered UI**, and **the real login/logout round trip**. Do not treat
it as a restatement of Step 3.

> ### 🚦 MANUAL GATE 1 — browser end-to-end (mandatory)
>
> Sign in as `dev-user` at `https://localhost/app`, then confirm:
>
> **1. Login and navigation**
> - Logged out, opening `https://localhost/app` lands on Keycloak's login page.
> - After signing in you return to `/app/graph` — not a bare host root.
> - The page is **styled** (CSS and JS loaded from `/auth/resources/...`
>   through nginx; unstyled means audit assets 404 and nginx's `/auth` proxy).
>
> **2. Chat streaming — the gate that catches what curl cannot**
> - In Chat, send a message. The answer must **stream word by word**, not appear
>   all at once at the end. If it arrives in one chunk, buffering is on — check
>   `X-Accel-Buffering: no` is on the response and that `stream=True` is set.
> - DevTools → Network: the request is `POST /app/stream/<id>`, its
>   `Content-Type` is `text/event-stream`, and **no** request goes to
>   `/api/v1/chats/...`.
>
> **3. Account bar**
> - The top bar shows `dev-user` with a **Sign out** button and **no role badge**.
>   The badge this gate originally asked for was removed during execution — see
>   the "account bar" correction in Step 3b.
> - The browser holds no access token — `document.cookie` and every Dash store
>   show only `wba_session`.
>
> **4. Logout round trip**
> - Clicking logout lands on the Keycloak login page, and signing in again works
>   (proving the row was revoked and a new session was created).
> - Logged out, the chat page redirects to login rather than erroring.
>
> **5. Containers stay healthy**
> - `docker compose ps` shows `api` and `ui` `healthy` after the whole walkthrough
>   (the logged-out health probe may 302 — nginx counts that as healthy).
>
> Wait for `PASS`. A `FAIL` is a STOP condition.

---

## Test plan

Covered in Steps 1–3, with Step 3d proving the two assertions that could
otherwise pass vacuously. The three tests that matter most:

1. **Refresh-token rotation persistence** — the single most likely silent bug.
2. **503 (not 401) when Keycloak is down on refresh** — preserves sessions.
3. **The stream bridge calls `/app/stream/`** — replaces a vacuous assertion
   that could never have failed.

The browser walkthrough in Step 4 covers what none of these can: incremental SSE
delivery through the proxy, rendered account bar, and the login/logout round trip.

## Done criteria

- [ ] `pytest -m unit tests -q` exits 0, ≥ baseline + new tests
- [ ] `mypy src/` exits 0; `pylint src --score=y` ≥ 9.0; `bandit` exits 0
- [ ] `docker compose config -q` exits 0; `nginx -t` passes
- [ ] `curl -s -o /dev/null -w '%{http_code}' https://localhost/api/v1/auth/login` → `302`
- [ ] `curl -s -o /dev/null -w '%{http_code}' -X POST https://localhost/api/v1/auth/token` → `401`
- [ ] `curl -s -o /dev/null -w '%{http_code}' https://localhost/app/graph` → `302` (no cookie)
- [ ] `grep -c "/api/v1/chats" src/ui/assets/stream-bridge.js` → `0`
- [ ] The UI snapshot fetch goes through `api_client` and carries a bearer:
      `pytest -m unit tests/test_ui_runtime_snapshot_auth.py -q` passes, and
      `grep -c "fetch_runtime_snapshot" src/ui/runtime_settings.py` counts no
      *call* site (README handoff 3 — without this, 057 silently stops the UI
      picking up runtime-settings edits)
- [ ] The Step 3d mutation runs both failed on the expected assertion
- [ ] **MANUAL GATE 1 passed** — chat streams word-by-word through `/app/stream/<id>` in the browser
- [ ] No log line contains a token: `grep -rn "access_token\|refresh_token" src/app/api/auth/service.py | grep -i logger` → no matches
- [ ] **No route gained a role dependency**: `grep -rn "Depends(require_" src/app/api/` shows only `src/app/api/auth/v1/router.py`
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report if:

- Keycloak's token endpoint does **not** return a rotated `refresh_token`
  (then rotation-persistence is moot and the design assumption changed).
- The Dash callback path cannot be distinguished from a navigation by the
  headers available — report rather than 302-ing callbacks (that breaks the
  page in a way that is hard to diagnose).
- `stream_with_context` cannot be made to work with the installed Flask under
  gunicorn gthread.
- The nginx `/app` location buffers the stream despite `X-Accel-Buffering: no`
  (then a `proxy_buffering off` location for `/app/stream/` is needed — an
  nginx change the operator should approve).
- `/auth/me` or the token exchange needs the cookie on a path the UI cannot see
  (a `path` mistake) — fix the constant, do not widen to `path=/app`.
- In-scope files have drifted.

## Maintenance notes

- **The token cache is per worker.** With 4 workers a user may hold 4 cached
  tokens; that is fine (same subject) and avoids a shared store. Do not add
  Redis — the UI container must not acquire a datastore.
- **`/auth/token` is one of exactly two cookie-authenticated paths.** Plan 057's
  allowlist test enforces that; adding a third will fail CI by design.
- **The 15-minute access token means a refresh every ~14 minutes per worker.**
  That is the load on Keycloak; if it becomes a problem, lengthen the access
  token in the realm, not the cache margin.
- **`X-Accel-Buffering: no` is load-bearing.** A reviewer should confirm it and
  that `stream=True` is set; without both, chat appears frozen then dumps.
- **The UI's snapshot fetch now rides the user's bearer, not a service token.**
  A consequence worth knowing: while logged out, the UI's runtime-settings cache
  stops refreshing entirely (every `refresh()` 401s and degrades). That is
  correct — there is no user to configure for — and it self-heals on the next
  request after login, at most `REFRESH_TTL_SECONDS` later. Do not "fix" it by
  adding a service credential to the UI: the UI is deliberately credential-free
  apart from the session cookie.
- **Plan D** adds `subject` ownership to themes. The account bar is the natural
  place to show a "your themes" affordance later, if one is wanted.

---

## Execution record — 2026-10-31

Executed in the live tree on `feature/plan-c-keycloak`, **uncommitted**. Steps 1–3
were dispatched to an executor under this plan's automated-only gate policy;
Step 4 has been driven by the operator.

### Step 4 gate progress

| Gate item | Status | Evidence |
|---|---|---|
| 1. Login and navigation | ✅ PASS | Operator signed in as `dev-user`, returned to `/app/graph`, page styled |
| 2. Chat streaming | ✅ PASS | Operator observed the answer arriving incrementally, not in one chunk |
| 3. Account bar | ✅ PASS (amended) | `dev-user` + Sign out rendered; **badge removed by request** |
| 4. Logout round trip | ✅ PASS | Sign out reached Keycloak's login page and signing back in worked (after the post-logout URI fix below) |
| 5. Containers healthy | ✅ PASS | `docker compose ps` — `api`, `ui`, `nginx`, `keycloak`, `postgres`, `neo4j`, `rabbitmq`, `elasticsearch` all up; every service with a healthcheck reports `healthy` |

**MANUAL GATE 1: ✅ PASSED** — all five items, 2026-10-31.

### Three defects found during execution — all plan errors, not executor errors

**1. The SSE proxy route needed an explicit `/app` prefix (Step 3a).** Fixed in
`src/ui/stream_proxy.py`; see the correction in Step 3a. The browser showed
`HTTP 405: Method Not Allowed` on `POST /app/stream/<id>`. The plan's premise —
that Dash's `requests_pathname_prefix` makes a bare `/stream/<id>` route reachable
at `/app/stream/<id>` — is false. The route now registers
`/app/stream/<session_id>` directly, verified: the URL map lists it, and
`POST /app/stream/x` with a session cookie reaches the handler (200).

**2. Login failed on a realm gap (Step 1/2 boundary).** `wba-web` tokens carried
no `aud` claim while `src/app/auth/tokens.py:123` required one, so
`/auth/callback` failed with `login_failed` and the API logged
`Token is missing the "aud" claim`. Root cause was a 054/055 gap, not this plan's
code: 054 built a strict validator, 055 gave `wba-internal` an audience mapper and
explicitly declined to give `wba-web` one. Fixed by **plan 062** (realm mapper +
the `kcadm.sh` reconcile mechanism this repo lacked).

**3. Logout failed with `Invalid redirect uri` (Step 1).** `service.py:408` sends
`post_logout_redirect_uri = {APP_PUBLIC_BASE_URL}/app`, but nothing ever
registered that URI in the realm — `deploy/keycloak/realm-wba.json.template` had
no `post.logout.redirect.uris` attribute, and a grep across every Plan C plan and
the design doc found the parameter mentioned **only** here at 056:250. Keycloak
rejects an unregistered post-logout redirect. Note the asymmetry that caused it:
`redirectUris` *was* templated so login would work; the logout equivalent was
never added. Fixed by adding the attribute to the template **and** a second
check-and-update block to `scripts/keycloak-realm-reconcile.sh` — the first use of
plan 062's reconcile mechanism for a change it was not originally written for,
which is exactly the pattern 062 claimed would work. Operator decision: logout
lands on `/app`, which sits behind the session guard, so the user ends at the
login page rather than a settled logged-out page. That is intended.

### Why the automated gates could not catch these defects

Worth recording, because the same shape recurs:

- **The cookie-less curl is blind to routing.** `POST /app/stream/<id>` without a
  cookie returns **401** from the session guard, which runs *before* routing. This
  plan's own Step 3 verification (`→ 401`) and the reviewer's re-run both passed
  while the route was unreachable. A 401 here proves the guard works, not that the
  route exists.
- **Stubbing the validator hides a realm that cannot produce a valid token.** The
  flow tests replace `validate_bearer_token` (`tests/test_auth_flow.py:138-143`),
  so no test ever feeds it a real token; and the live curl only asserted that
  `/auth/login` returns 302. The callback and token exchange were never exercised
  by any automated check.
- **Nothing tested the logout redirect end to end.** No automated check follows a
  logout through Keycloak and back, and no unit test could — the failure is realm
  configuration the app cannot see. The third defect was reachable only by
  clicking Sign out in a browser.
- Plan 062 narrows the second gap with a realm-shaped token test. The first and
  third are closed only by a real browser run, which is what Step 4 is for.

**The pattern across all three:** every one of these passed its own automated
check while being broken. A check that does not exercise the failing path is not
evidence — it is the appearance of evidence. Two of the three were also found by
the operator in a browser, not by any gate or review, including the reviewer's.

### Scope amendments

- **No role badge** in the account bar. Requested by the operator during Step 4;
  `_role_badge`, `_ADMIN_BADGE` and `_USER_BADGE` were removed from
  `src/ui/components/account_bar.py`. The Step 4 gate criterion that asked for a
  badge was corrected above.
- `tests/test_stream_proxy.py` — its four request paths were updated to the real
  `/app/stream/...` URL. They had been written against `/stream/...`, which would
  have kept passing against a route that does not exist in production.

### Verified totals at this record

`pytest -m unit tests` → 2519 passed, 2 skipped; `mypy src/` exit 0 (322 files);
`pylint src --score=y` 9.69; `bandit -c .bandit.yml -r src/ -lll` exit 0.

# Plan 003: Make the admin user list's `total` honest and stop replaying a rejected admin token

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. **Do NOT update `plans/README.md`** — your
> reviewer maintains that index.
>
> **Drift check (run first)**:
> `git diff c390367c -- src/app/api/admin_users/v1/query.py src/app/auth/keycloak_admin.py tests/test_admin_users_service.py tests/test_keycloak_admin_client.py`
> This must print nothing. If it prints a diff, the code no longer matches the
> "Current state" excerpts below — treat that as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: bug
- **Planned at**: commit `c390367c`, 2026-11-12

## Why this matters

Two independent defects in the admin user management surface that shipped on
the `feature/user-management` branch:

1. **`total` is computed by subtracting a count that is not in the same scope as
   the count it is subtracted from.** Keycloak's `/users/count` returns the count
   *for the current search term*, but the service-account count is always
   *global*. With a search term in play the subtraction can produce a negative
   `total` (`-1` when a search matches only a service account), and it can
   understate the truth by the global service-account count (`26` matching real
   users reported as `24`). The UI disables its **Next** button when
   `offset + limit >= total` (`src/ui/pages/settings/user_management/callbacks.py`),
   so an understated total hides the last page of a search — users become
   unreachable except by narrowing the search. The no-search path is already
   correct today.

2. **A `401` from Keycloak's admin API is reported to the caller but the cached
   token that caused it is never discarded.** `_admin_token()` caches the token
   process-wide and `invalidate_admin_token()` exists for exactly this purpose
   but has no production caller. Consequences: after anything that invalidates
   the token server-side (a client-secret rotation, a Keycloak restart, a realm
   re-seed), every admin call keeps replaying the dead token until its cache
   entry expires — the token is cached with a 60-second refresh margin off a
   900-second lifespan, so ~14 minutes of solid `503`s. The operator sees
   "identity_provider_unavailable" and nothing points at the real cause.

After this plan both are fixed with small, local changes, and each fix gets a
regression test that fails against today's code.

## Current state

### File 1 — `src/app/api/admin_users/v1/query.py`

The Keycloak-backed data access layer for the admin surface. The function in
question is `list_users`, lines 41–60:

```python
def list_users(
    offset: int, limit: int, search: str | None
) -> tuple[list[UserSummary], int]:
    """Return a page of listable users and the count of listable users.

    Keycloak's own count includes service-account users, so ``total`` is
    ``count - service_account_count`` — the count of rows the pager can render.
    """
    raw_users, count = keycloak_admin.list_users(offset, limit, search)
    service_account_count = keycloak_admin.count_users(_SERVICE_ACCOUNT_PREFIX)

    summaries: list[UserSummary] = []
    for user in raw_users:
        if is_service_account(user):
            continue
        roles = keycloak_admin.realm_roles(str(user["id"]))
        summaries.append(
            _to_summary(user, sorted(set(roles) & ASSIGNABLE_REALM_ROLES))
        )
    return summaries, count - service_account_count
```

Facts you need, already verified:

- `_SERVICE_ACCOUNT_PREFIX = "service-account-"` is defined at the top of this
  same file.
- `keycloak_admin.list_users(offset, limit, search)` returns
  `(page, count_for_this_search)`. `count_for_this_search` is global when
  `search` is falsy.
- `keycloak_admin.count_users(search)` returns the count for *its* argument.
  Called with `_SERVICE_ACCOUNT_PREFIX` it is always the **global** number of
  service-account users (this realm has 2: the `wba-internal` and
  `wba-admin-api` service accounts).
- `search` arrives as `None` or `""` for "no filter" — the router declares
  `search: str | None = None` and the UI sends `""` when the box is empty. Both
  are falsy.

### File 2 — `src/app/auth/keycloak_admin.py`

The Keycloak Admin REST client. Token caching, lines 130–176:

```python
def _admin_token() -> str:
    token = _cached_token()
    if token is not None:
        return token
    if _in_failure_backoff():
        raise KeycloakUnavailableError("admin token fetch failed recently; backing off")

    with _state.lock:
        token = _cached_token()
        if token is not None:
            return token
        ...
        _state.access_token = token
        _state.expires_at = expires_at
        return token


def invalidate_admin_token() -> None:
    """Discard the cached token and failure backoff, so the next call re-fetches."""
    with _state.lock:
        _state.access_token = None
        _state.expires_at = 0.0
```

`_request` maps HTTP status codes to exception types. Lines 205–208:

```python
    if resp.status_code in (401, 403):
        raise KeycloakUnavailableError(
            f"admin API refused the service account (status {resp.status_code})"
        )
```

Facts you need, already verified:

- `invalidate_admin_token()` is called in production **nowhere** — its only
  caller today is the autouse `_reset_token` fixture in
  `tests/test_keycloak_admin_client.py`.
- `_admin_token()` holds `_state.lock` only for the duration of its own body;
  `_request` calls `invalidate_admin_token()` *after* `_admin_token()` has
  returned, so the lock is free and re-acquiring it cannot deadlock.
- `_state` is module-global (`_state = _TokenState()`), so tests must reset it
  between cases — the existing autouse fixture already does.
- A `403` means the token is *valid* but the service account lacks a required
  `realm-management` role. A `401` means the token itself was rejected. These
  are different causes and warrant different handling (see the fix).

### Test files you will extend

- `tests/test_admin_users_service.py` — house pattern for the `query`-layer
  tests is `test_list_total_excludes_service_accounts` (around line 206): call
  `monkeypatch.undo()` to drop the module-wide `_patch_query` stub, then
  `monkeypatch.setattr(query, "keycloak_admin", _FakeAdmin)` with a small class
  of `@staticmethod`s. Follow that shape.
- `tests/test_keycloak_admin_client.py` — house pattern is the local
  `_FakeResponse` class, the `_settings(monkeypatch)` helper, and
  `monkeypatch.setattr(requests, "post", ...)` for the token endpoint plus
  `monkeypatch.setattr(requests, "request", ...)` for the admin call. See
  `test_admin_401_becomes_unavailable` (line 73) and `test_token_is_cached`
  (line 55). The module has an autouse `_reset_token` fixture that calls
  `k.invalidate_admin_token()` before every test.

### Repo conventions

- Type hints on all parameters and returns; `X | None`, not `Optional`.
- Default to **no comments**. A comment is allowed only to explain a *why* that
  is not obvious from the code — the 401-vs-403 distinction in Fix 2 is exactly
  that case and gets one short line. No change-log or past-tense comments.
- `from common.logger import logger` for logging; never `print()`.
- Do not add logging to either fix. Neither fix has anything to log that isn't
  already logged by a caller.

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Activate venv | `source .venv/bin/activate` | exit 0 |
| Targeted tests | `PYTHONPATH=src pytest -m unit tests/test_admin_users_service.py tests/test_keycloak_admin_client.py -q` | all pass, including the 3 new tests |
| Full unit gate | `PYTHONPATH=src pytest -m unit tests -q` | all pass (2760 passed, 2 skipped before your changes — the count rises by your new tests) |
| Typecheck | `mypy src/` | exit 0, `Success: no issues found` |
| Lint | `pylint src/app/api/admin_users src/app/auth/keycloak_admin.py --score=y` | `10.00/10` |

Note: `pytest.ini` already sets `pythonpath = src . tests`, so `PYTHONPATH=src`
is belt-and-braces; keep it, it is what this repo's docs specify.

## Scope

**In scope** (the only files you may modify):
- `src/app/api/admin_users/v1/query.py` — the `list_users` total computation
- `src/app/auth/keycloak_admin.py` — the 401/403 branch in `_request`
- `tests/test_admin_users_service.py` — regression tests for the total
- `tests/test_keycloak_admin_client.py` — regression tests for the token

**Out of scope** (do NOT touch, even though they look related):
- `plans/README.md` and `plans/002-rename-realm-roles-and-clients.md` — the
  reviewer owns the index; `002` is an uncommitted plan file that already exists
  in the working tree. Leave both exactly as you find them.
- `src/ui/pages/settings/user_management/**` — the UI is correct here; it reads
  `total` and disables the pager as designed. Do not compensate for the bad
  total in the UI.
- `src/app/api/admin_users/v1/service.py`, `router.py`, `model.py` — no change
  is needed in these. In particular do **not** remove the unused private
  `_translate_not_found` helper: that is a separate cleanup, not this plan.
- Any change to the HTTP status codes or error bodies the router returns.
- Any `count_users`-batching or `realm_roles`-batching refactor — the
  per-row `realm_roles` call is a known performance item, filed separately.

## Git workflow

- **Work in the current working tree, on the current branch
  (`feature/user-management`). Do NOT create a branch, worktree, or commit.**
  Leave every change uncommitted; the operator reviews and commits it
  themselves.
- Do NOT run `git commit`, `git push`, `git checkout`, `git stash`,
  `git restore`, `git reset`, or `git clean` for any reason. If you believe you
  need one of these, STOP and report instead.
- `git status` at the end must show modifications to exactly the four
  in-scope files, plus whatever `__pycache__` / `.pytest_cache` churn the test
  run produces.

## Implementation

There are no manual gates in this plan: every change below is confirmable by a
command. Do the four edits in this order, verifying after each.

### Edit 1 — compute `total` in the right scope (`query.py`)

Replace the body of `list_users` so that the service-account subtraction only
happens when it is actually in scope, and the result can never go negative:

```python
def list_users(
    offset: int, limit: int, search: str | None
) -> tuple[list[UserSummary], int]:
    """Return a page of listable users and the count of listable users.

    Keycloak's count always includes service-account users while the page
    filters them out. With no search term every service account is inside the
    count, so it is subtracted exactly. With one, the count covers only the
    matching subset and the service accounts within that subset are not
    separately countable, so the count stands — overstating by at most however
    many service accounts match the term.
    """
    raw_users, count = keycloak_admin.list_users(offset, limit, search)
    total = count
    if not search:
        total = max(0, count - keycloak_admin.count_users(_SERVICE_ACCOUNT_PREFIX))

    summaries: list[UserSummary] = []
    for user in raw_users:
        if is_service_account(user):
            continue
        roles = keycloak_admin.realm_roles(str(user["id"]))
        summaries.append(
            _to_summary(user, sorted(set(roles) & ASSIGNABLE_REALM_ROLES))
        )
    return summaries, total
```

Three things this change is doing, so you can judge it:

- `not search` is True for both `None` and `""`, so the no-filter path behaves
  as it does today (and the UI's empty search box hits it).
- `max(0, ...)` removes the negative-total case entirely. It also covers the
  benign race where Keycloak's two calls disagree because a user was created or
  deleted in between.
- When a search term is present, `count_users` is no longer called at all. That
  is deliberate: its result is out of scope for a search-scoped count, and
  dropping the call also removes one Keycloak round trip per search render.

**Verify**: `git diff -- src/app/api/admin_users/v1/query.py` shows the new
`total` lines, and
`grep -n "count - service_account_count" src/app/api/admin_users/v1/query.py`
returns no matches (exit status 1).

### Edit 2 — discard a rejected token (`keycloak_admin.py`)

Replace the combined 401/403 branch in `_request` (lines 205–208) with two
branches:

```python
    if resp.status_code == 401:
        # A rejected token must not stay cached: every later call would replay
        # it until its cache entry lapsed, turning one rotation into minutes of
        # 503s. A 403 below is a valid token missing a role, not a stale one.
        invalidate_admin_token()
        raise KeycloakUnavailableError(
            f"admin API refused the service account (status {resp.status_code})"
        )
    if resp.status_code == 403:
        raise KeycloakUnavailableError(
            f"admin API refused the service account (status {resp.status_code})"
        )
```

Both branches still raise the same `KeycloakUnavailableError` with the same
message, so the router's mapping (503 `identity_provider_unavailable`) and the
design doc's stated contract are unchanged. Only the 401 path now also clears
the cache.

Do not add a retry-on-401. That is a deliberate omission — see Maintenance
notes.

**Verify**: `git diff -- src/app/auth/keycloak_admin.py` shows the split branch,
and the diff leaves the message string
`admin API refused the service account (status {resp.status_code})` present
twice (once per branch).

### Edit 3 — regression tests for the total (`tests/test_admin_users_service.py`)

Add three tests next to `test_list_total_excludes_service_accounts`, in the same
style (`monkeypatch.undo()` then patch `query.keycloak_admin` with a static
class). Use a fresh local class per test, or one parametrised class — whichever
reads more cleanly to you; keep the existing test untouched and passing.

Define a small recording fake that lets each test control the three numbers:

- `list_users(offset, limit, search)` → `(page, count)`
- `count_users(search)` → records the call and returns the global
  service-account count
- `realm_roles(uid)` → `["wba-user"]`

Cases to cover:

1. **Search present, count is search-scoped** — the negative-total regression.
   `list_users` returns `([_raw("sa", username="service-account-x")], 1)` (i.e.
   the only match is a service account) and `count_users` returns `3`. Assert
   `total == 1` and `summaries == []`. Against today's code this asserts `-2`
   and fails, which is the point.
2. **Search present, several real matches** — the understated-total regression.
   `list_users` returns 25 non-service-account rows and count `26`;
   `count_users` returns `3`. Assert `total == 26`.
3. **`count_users` is skipped when searching** — in either of the cases above,
   assert the fake recorded **no** `count_users` call when `search` is truthy,
   and exactly one call when `search` is `None`. This pins the deliberate
   round-trip saving so a future edit cannot silently reintroduce the call.
4. **Clamp** — no search term, `list_users` returns count `1` while
   `count_users` returns `3`. Assert `total == 0`, not `-2`.

(1, 2 and 4 are separate assertions; combining them into one parametrised test
over `(search, count, service_account_count, expected_total)` is fine and
probably cleaner.)

**Verify**: `PYTHONPATH=src pytest -m unit tests/test_admin_users_service.py -q`
→ all pass. Then confirm the tests actually catch the bug: temporarily revert
`query.py` to `return summaries, count - service_account_count` (keep the
recording fake in place), re-run, and confirm cases 1 and 4 **fail**. Restore
your fix (re-apply Edit 1) and re-run to green. Report both results — a new test
that passes against the old code proves nothing.

### Edit 4 — regression tests for the token (`tests/test_keycloak_admin_client.py`)

Add two tests using the existing `_settings(monkeypatch)` helper and
`_FakeResponse`.

1. **`test_admin_401_invalidates_token`** — prime the cache with a successful
   token fetch, then make the admin call return 401:
   - `monkeypatch.setattr(requests, "post", <fake counting posts, returns
     {"access_token": "t", "expires_in": 300}>)`
   - call `k._admin_token()` once and assert it returns `"t"` (cache primed)
   - `monkeypatch.setattr(requests, "request", lambda *a, **kw:
     _FakeResponse(401, text="unauthorized"))`
   - `with pytest.raises(k.KeycloakUnavailableError): k.get_user("abc")`
   - assert `k._state.access_token is None`
   - call `k.get_user("abc")` again inside `pytest.raises` and assert the post
     counter is now `2` — i.e. the second call re-fetched instead of replaying
     the rejected token.
2. **`test_admin_403_keeps_token`** — same priming, but the admin call returns
   403. Assert `pytest.raises(k.KeycloakUnavailableError)` still holds **and**
   `k._state.access_token == "t"`, then assert the post counter is still `1`
   after a second call. This pins the deliberate difference: a 403 is a valid
   token missing a role, so it must not force a re-fetch on every request.

**Verify**: `PYTHONPATH=src pytest -m unit tests/test_keycloak_admin_client.py -q`
→ all pass. Then confirm test 1 catches the bug: temporarily revert the 401/403
split to the original combined branch, re-run, and confirm
`test_admin_401_invalidates_token` **fails** (the cached token survives). Restore
Edit 2 and re-run to green. Report both results.

### Final verification

Run the whole gate set and paste each result:

- `PYTHONPATH=src pytest -m unit tests -q` → all pass
- `mypy src/` → `Success: no issues found`
- `pylint src/app/api/admin_users src/app/auth/keycloak_admin.py --score=y` → `10.00/10`
- `git status --porcelain` → only the four in-scope files modified
  (plus ignored cache churn)
- `git diff --stat` → no test file deleted, no unrelated file touched

## Test plan

| Test | File | Covers |
|---|---|---|
| `test_list_total_under_search_is_not_negative` | `tests/test_admin_users_service.py` | Finding 1, negative-total regression |
| `test_list_total_under_search_covers_all_matches` | `tests/test_admin_users_service.py` | Finding 1, understated-total regression |
| `test_list_total_clamps_and_skips_global_count` | `tests/test_admin_users_service.py` | Finding 1, clamp + round-trip saving |
| `test_admin_401_invalidates_token` | `tests/test_keycloak_admin_client.py` | Finding 2, stale-token replay |
| `test_admin_403_keeps_token` | `tests/test_keycloak_admin_client.py` | Finding 2, the deliberate non-invalidation for 403 |

Structural patterns to follow: `test_list_total_excludes_service_accounts`
(`tests/test_admin_users_service.py`) and `test_admin_401_becomes_unavailable` /
`test_token_is_cached` (`tests/test_keycloak_admin_client.py`).

The existing `test_list_total_excludes_service_accounts` passes `search=None`, so
it stays green under Edit 1 unchanged — do not weaken it to make room for the new
ones.

## Done criteria

All must hold:

- [ ] `PYTHONPATH=src pytest -m unit tests -q` exits 0; the 5 tests in the table
      above exist and pass
- [ ] Each of the two new tests was shown to **fail** against the pre-fix code
      (both temporary reverts performed and reported)
- [ ] `mypy src/` exits 0 with `Success: no issues found`
- [ ] `pylint src/app/api/admin_users src/app/auth/keycloak_admin.py --score=y`
      reports `10.00/10`
- [ ] `grep -n "count - service_account_count" src/app/api/admin_users/v1/query.py`
      returns no matches
- [ ] `grep -c "invalidate_admin_token()" src/app/auth/keycloak_admin.py`
      returns a count of at least 2 (the definition plus the `_request` call)
- [ ] `git status --porcelain` lists exactly the four in-scope files as modified
      — no branch created, nothing committed
- [ ] `plans/README.md` and `plans/002-rename-realm-roles-and-clients.md` are
      byte-identical to how you found them

## STOP conditions

Stop and report (do not improvise) if:

- The drift check prints a diff, or the code at the cited lines does not match
  the "Current state" excerpts.
- Fixing either defect appears to require touching a file outside the in-scope
  list — in particular if you conclude the UI must change to compensate for
  `total`. It must not: the UI is correct and the server value is wrong.
- A verification command fails twice after a reasonable fix attempt.
- You cannot make a new test fail against the pre-fix code. That means the test
  does not actually cover the defect; report it rather than adjusting the
  assertion until it passes.
- Any command would create a branch or a commit.

## Maintenance notes

- **The scope rule for `total` is the thing to preserve.** If Keycloak later
  grows a way to exclude service accounts server-side, collapse this back to a
  single count call; until then, anyone adding a new filter dimension to
  `list_users` must decide whether the global service-account count is still in
  scope for it. The docstring states the current answer — keep it and the code
  in agreement.
- **A reviewer should scrutinize**: that the 401 branch really does clear the
  cache (the second `get_user` call in the test must trigger a second token
  POST), and that the 403 branch really does not. A split that invalidates on
  both, or neither, passes a careless test and defeats the fix.
- **Deliberately deferred, do not add on top of this plan**:
  - *Retry once on 401.* The textbook fix is to invalidate and immediately
    retry the call once. It is omitted here because it changes `_request`'s
    control flow (the executor reviewed this plan for a single-branch change)
    and because the visible failure is already recovered by the admin reloading
    the page. File it separately if 401s turn out to be common in practice.
  - *The per-row `realm_roles` call in `list_users`.* One Keycloak request per
    rendered row, plus the count call — the known performance item, filed
    separately. Edit 1 removes one round trip; it does not address the N.
  - *Deleting the unused `_translate_not_found` in
    `src/app/api/admin_users/v1/service.py`.* Dead private code, no behavioural
    cost; bundle it with whichever change next touches the error mapping.
- **Interacts with plan 002** (rename the realm roles and client ids): 002
  changes the *strings* `wba-admin` / `wba-user` / the client ids, and touches
  neither file this plan edits. They are order-independent; land them in either
  order.

## Execution record

Executed 2026-11-12 in the working tree on `feature/user-management`, left
uncommitted, by a dispatched executor and then reviewed and independently
verified.

- Targeted gate: `PYTHONPATH=src pytest -m unit tests/test_admin_users_service.py tests/test_keycloak_admin_client.py -q`
  → 30 passed. `mypy src/` → no issues. `pylint src/app/api/admin_users src/app/auth/keycloak_admin.py --score=y`
  → 10.00/10.
- Full unit gate at execution time: 2765 passed, 2 skipped (baseline 2760 + the
  5 new tests).
- Revert proofs (both performed and observed): with the pre-fix `total` body
  restored, the three new `total` tests failed at `-2 == 1`, `23 == 26` and
  `-2 == 0`; with the pre-fix combined 401/403 branch restored,
  `test_admin_401_invalidates_token` failed at `assert 't' is None`. Both were
  then restored to green.
- The working tree moved under the run: HEAD advanced from `c390367c` to
  `036bff08` ("rename plan", which tracked plan 002's file) mid-execution. The
  four in-scope files were unchanged against `c390367c`, so the drift check
  passed and plan 002 stays order-independent with this one.
- Not addressed here, deliberately: no retry-on-401, no batching of the per-row
  `realm_roles` call, and `_translate_not_found` remains dead code. See
  Maintenance notes.

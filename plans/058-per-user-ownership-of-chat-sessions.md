# Plan 058: Scope chat sessions to their owner

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving on. If
> anything in "STOP conditions" occurs, stop and report — do not improvise.
> When done, update the status row in `plans/README.md`.
>
> **This plan has exactly ONE manual gate** (Gate 1, the live foreign-chat
> check). Step 1 has no gate; the automated gate at the end of Step 2 proves the
> code. Do not stop for approval between Step 1 and Step 2.
>
> **Drift check (run first)**:
> `git diff --stat 665b1426..HEAD -- src/app/ai_agent/ai_agent.py src/app/api/chats/v1/service.py src/app/api/chats/v1/router.py tests/test_stream_endpoint.py`
> Any diff against the "Current state" excerpts below in those files is a STOP
> condition.
>
> **Locate by content, not by line number.** Line numbers below were accurate at
> the stamp commit and will drift as you edit.

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: LOW-MED
- **Depends on**: plans/057 (DONE)
- **Category**: security
- **Planned at**: commit `665b1426`, 2026-11-01
- **Design reference**: `docs/design/authn-authz-design.md`, Decision 9,
  "Endpoint matrix", the `Chat (own sessions)` row
- **This is step 6 of 9** in the Plan C sequence, first half.
  **Its sibling is `plans/065-per-user-catalog-favourites.md`** — the favourites
  half of the original 058, split out because the two halves share no files and
  the favourites half carries a destructive migration. Run 058 first.
- **Status: DONE 2026-11-01.** Steps 1–2 approved; Step 3 (Gate 1) PASS. All
  gates green at HEAD `7698f1e7`; changes uncommitted in the working tree.
- **Gate 1 was run scripted, not by hand.** The plan's claim that no script can
  obtain a `dev-user` bearer is **wrong** — `tests/auth_helpers.py` completes the
  real Keycloak login form and the BFF cookie→bearer exchange for both roles.
  Observed against the real stack, two genuinely different subjects: dev-user
  `POST /chats/` → 201; dev-user `GET` own → 200; **dev-admin `GET` dev-user's →
  404** (not 403); dev-admin `POST /stream` → 404 with a JSON body and no
  `text/event-stream`; dev-admin `DELETE` → 404 and the owner's subsequent `GET`
  still 200; unknown id → 404; anonymous → 401. The browser path was verified
  too: dev-admin's **session cookie** through the Dash proxy
  `POST /app/stream/<dev-user id>` → 404 `{"detail":"Session not found."}` — the
  route `src/ui/assets/stream-bridge.js` actually calls. The running `api`
  container was confirmed to carry this tree's code before the result was
  accepted.
- **Steps 1–2**: APPROVED 2026-11-01 (reviewer re-ran all done criteria;
  working tree at HEAD `7698f1e7`, uncommitted). **Step 3 (manual browser gate)
  not run.**
- **Review deviation from this plan's text**: Step 1.2 specified
  `stream_chat_response` re-checks ownership. That places a `ChatSessionNotFoundError`
  raise inside an async generator that the router has already entered, so it would
  surface as a mid-stream SSE `error` event rather than a JSON 404. The executor
  removed the re-check from `stream_chat_response` and left the route's
  pre-stream `get_chat_session_status` probe as the single enforcement point.
  Reviewer verified the route still 404s a foreign stream
  (`tests/test_chat_ownership.py::test_foreign_stream_is_404_and_does_not_stream`),
  the deletion is safe (every call site is handled in-router), and the check is
  load-bearing (patched to a no-op in memory, foreign stream/read/delete flip to
  200). If the service is ever called outside this router, reinstate a check that
  raises **before** the generator is created.

## Why this matters

Plan 057 made every request prove *who* it is. It did not stop one authenticated
user from acting on another user's data.

**Chat sessions are the remaining hole.** Sessions live in a process-wide dict
keyed by a GUID. Anyone who knows or guesses a `session_id` can read its status,
stream into it, or delete it. The design calls this "the `any session_id is
usable by anyone` hole", and the endpoint matrix marks the chat rows as
`✓ (own sessions)` — a claim the code does not yet honour: it is `✓` for
everyone's.

After this plan, a chat session belongs to the subject that created it, and
`GET/POST/DELETE /chats/{id}` returns **404** for a session the caller does not
own. 404, not 403, so the response does not confirm the id exists.

## Current state

**`src/app/ai_agent/ai_agent.py`** — the session store is a module-level dict:

```python
_chat_sessions: dict[str, list[dict[str, Any]]] = {}
```

`new_chat(system_prompt: str = "You are a helpful AI assistant.") -> str` stores
`_chat_sessions[session_id] = [{"role": "system", "content": system_prompt}]`.
`stream_chat` reads and appends to it; `end_chat` does
`_chat_sessions.pop(session_id, None)`.

`_chat_sessions` has exactly three readers (verified with
`grep -rn "_chat_sessions" src/` at the stamp commit):

| Reader | Bearing |
|---|---|
| `src/app/ai_agent/ai_agent.py` | the store's owner — you edit this |
| `src/app/api/chats/v1/service.py` | **in scope** — the API's read path |
| `src/app/ai_agent/ai_agent_cli.py` | **out of scope, unaffected** — the CLI calls `new_chat()` with no owner and is the only reader of the sessions it creates |

**IMPORTANT — a pre-existing constraint, not something you fix here:** the API
runs under **uvicorn with one worker** (`src/app/entrypoint.sh`, no `--workers`),
so the dict is process-wide in practice. Do not add persistence; that is out of
scope.

**`src/app/api/chats/v1/service.py`** — every function takes only a
`session_id`:

```python
def create_chat_session(chat: ChatCreate) -> ChatSession:
    session_id = new_chat(system_prompt=chat.system_prompt or "")
    return ChatSession(session_id=session_id)

def get_chat_session_status(session_id: str) -> ChatSessionStatus:
    exists = session_id in _chat_sessions
    message_count = len(_chat_sessions.get(session_id, [])) if exists else None
    ...
```

**`src/app/api/chats/v1/router.py`** — four ownership routes, none of which
passes a principal: `POST /`, `GET /{session_id}`, `POST /{session_id}/stream`,
`DELETE /{session_id}`, plus `GET /metrics/stream`. Note that the stream route
short-circuits **before** building its response:

```python
        session_status = service.get_chat_session_status(session_id)
        if not session_status.exists:
            raise HTTPException(status_code=404, detail="Session not found.")
```

That branch bypasses any ownership check you add to the service, so a foreign
caller would still reach the stream. Step 1.4 removes it.

The routers all carry a router-level `dependencies=[Depends(require_user)]` from
plan 057, added at include time in `src/app/api_main.py`. That proves
*authenticated*; it says nothing about *whose* session.

**Tests that depend on the code above** — read these before editing:

| File | Marker | Bearing on this plan |
|---|---|---|
| `tests/test_stream_endpoint.py` | asyncio only (**no `unit`**) | Seeds `ai_agent._chat_sessions[session_id] = [...]` directly at 7 sites and POSTs to the **real app's** `/api/v1/chats/{id}/stream` via `ASGITransport(app=app)`, asserting 200. **Breaks** once ownership is enforced — and no gate notices, because the file carries no marker so `-m unit` deselects all 8 tests. |
| `tests/test_chat_mcp_integration.py` | `unit` | Creates sessions through `POST /api/v1/chats/`, so owner == caller under the conftest override. Should keep passing untouched. If it does not, STOP — the defect is yours. |
| `tests/conftest.py` | — | An autouse fixture authenticates every credential-less API test as `test-admin` (roles `wba-admin` + `wba-user`); a request carrying its own `Authorization` header or `wba_session` cookie falls through to the real verifier. **Do not edit this file.** |

### Decisions already taken (do not re-litigate)

| Subject | Decision |
|---|---|
| Chat ownership storage | Record the owning `sub` **in the in-process session entry**. No schema, no persistence, no new table. |
| Foreign session response | **404**, never 403 (do not confirm existence). |
| Unowned sessions | A session with no recorded owner is not reachable through the API **by anyone**, including an admin. |
| Favourites | **Not in this plan** — see `plans/065-per-user-catalog-favourites.md`. |
| Theme ownership | **Not here.** Stays admin-only until Plan D. |

### Repo conventions that apply

- `service.py` owns business logic; `router.py` does HTTP. `model.py` is
  unchanged here — no new field is returned to the client.
- Type hints everywhere; `mypy src/` is strict (`disallow_untyped_defs`).
- Tests carry markers. **An unmarked test is silently deselected by `-m unit`** —
  this trap is live in this plan (`tests/test_stream_endpoint.py`).
- Default to no comments; only comment the non-obvious "why".
- Do **not** commit or push unless asked.

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Unit tests | `pytest -m unit tests -q` | ≥ **2586 passed**, 0 failed, 2 skipped (baseline measured at `665b1426`) |
| Stream suite | `pytest tests/test_stream_endpoint.py -q` | all pass — **run by path**, it is not unit-marked |
| Typecheck | `mypy src/` | exit 0 |
| Lint | `pylint src --score=y` | ≥ 9.0 |
| Security scan | `bandit -c .bandit.yml -r src/ -lll` | exit 0 |

## Scope

**In scope**:
- `src/app/ai_agent/ai_agent.py` — record and expose the owner.
- `src/app/api/chats/v1/service.py` — ownership checks.
- `src/app/api/chats/v1/router.py` — thread the principal through.
- `tests/test_chat_ownership.py` (create)
- `tests/test_stream_endpoint.py` — update the direct `_chat_sessions` seeds so
  the 8 existing tests keep asserting 200.

**Out of scope** (do NOT touch):
- `src/app/api/chats/v1/model.py` — no response-shape change.
- `tests/conftest.py` and everything under `src/app/auth/` — plans 054-057 own
  them.
- `src/app/ai_agent/ai_agent_cli.py` — its sessions are unowned, which is
  correct for a local CLI.
- `GET /chats/metrics/stream` — aggregate metrics, not per-session data. Leave
  it user-readable beyond the 057 router dependency.
- The UI. It already sends `Authorization: Bearer` on every call
  (`src/ui/api_client.py`) and will therefore automatically act as the
  logged-in user. It needs no change; do not teach it about ownership.
- Anything in `src/app/api/queries/` or `src/app/db/models/catalog_metadata.py`
  — that is plan 065.

## Steps

### Step 1: Enforce chat ownership (no manual gate)

**1.1 — Record the owner in `src/app/ai_agent/ai_agent.py`.**

Keep the message-list shape — `stream_chat` and `do_chat` index into it in
several places, and rewriting that is out of scope. Use a parallel dict:

```python
# Owning Keycloak `sub` per session. A session with no entry here (created by
# the CLI, or before this change) is unowned and is not reachable through the
# API. A parallel dict rather than a value-type change: do_chat/stream_chat
# treat the value as a message list in several places and changing the type
# ripples.
_chat_session_owners: dict[str, str] = {}
```

Change `new_chat` to take an optional keyword-only owner and record it:

```python
def new_chat(
    system_prompt: str = "You are a helpful AI assistant.",
    *,
    owner_subject: str | None = None,
) -> str:
```

Record `_chat_session_owners[session_id] = owner_subject` only when it is not
`None`. In `end_chat`, pop the owner alongside the messages. Add the helper the
API layer uses:

```python
def get_chat_owner(session_id: str) -> str | None:
    """Return the owning subject, or ``None`` when unowned/unknown."""
```

**1.2 — Enforce ownership in `src/app/api/chats/v1/service.py`.**

Every ownership-sensitive function takes the caller's subject. The service
reports "not found for this caller"; the router decides the status.

```python
class ChatSessionNotFoundError(Exception):
    """The session does not exist, or the caller does not own it.

    Deliberately one error for both cases: distinguishing them would let a
    caller probe for session ids that exist.
    """
```

- `create_chat_session(chat, *, owner_subject)` — pass it to `new_chat`.
- `get_chat_session_status(session_id, *, subject)` — raise
  `ChatSessionNotFoundError` when the session is unknown **or** its owner is not
  `subject`. An unowned session (`get_chat_owner` returns `None`) is not found
  for anyone.
- `stream_chat_response(session_id, user_message, *, subject)` — same check
  before streaming; raise `ChatSessionNotFoundError`.
- `delete_chat_session(session_id, *, subject)` — same check, then `end_chat`.

**1.3 — Thread the principal in `src/app/api/chats/v1/router.py`.**

Use a **handler parameter** (unlike plan 057's `dependencies=[...]` form) because
the value is genuinely needed:

```python
@router.get("/{session_id}", response_model=ChatSessionStatus)
async def get_chat_session(
    session_id: str,
    principal: Principal = Depends(require_user),
) -> ChatSessionStatus:
    ...
    except ChatSessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Session not found.") from exc
```

Do this on all four ownership routes: `POST /` (create, passing
`principal.subject` as `owner_subject`), `GET /{session_id}`,
`POST /{session_id}/stream`, `DELETE /{session_id}`. Import `Principal` from
`app.auth.principal` and `require_user` from `app.auth.dependencies`.
`GET /metrics/stream` is unchanged.

**1.4 — Convert the stream route's short-circuit (do not skip this).**

`stream_message` currently calls `get_chat_session_status(session_id)` and raises
its own 404 *before* returning the `StreamingResponse`. That path never sees an
ownership check, so a foreign caller would pass. Replace it so the route calls
the ownership-checked status and raises 404 **before** the generator is built:

```python
    try:
        service.get_chat_session_status(session_id, subject=principal.subject)
    except ChatSessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Session not found.") from exc
```

The `if not session_status.exists:` branch must be **gone** — a session that
exists but is not the caller's must not reach `StreamingResponse`. Keep the outer
`except ValueError` / `except RuntimeError` handlers.

**1.5 — Update `tests/test_stream_endpoint.py`.**

Its 7 direct `ai_agent._chat_sessions[session_id] = [...]` seeds create unowned
sessions, which now 404. Set the owner alongside each seed:

```python
        ai_agent._chat_sessions[session_id] = [{"role": "system", "content": "System."}]
        ai_agent._chat_session_owners[session_id] = "test-admin"
```

and pop the owner in each test's `finally`/fixture teardown, alongside the
existing `_chat_sessions.pop(...)`. `test-admin` matches the conftest fixture's
subject, so the default authenticated caller owns them.

Leave the file's marker alone — do **not** add `pytest.mark.unit`. Adding it
would pull 8 tests into CI's measured baseline as a side effect of this plan;
that is plan 060's remit.

**Verify**: `mypy src/` → exit 0
**Verify**: `grep -n "require_user" src/app/api/chats/v1/router.py` → names it on
four routes, whose paths are `POST /`, `GET /{session_id}`,
`POST /{session_id}/stream`, `DELETE /{session_id}`. Read the output and confirm
those four by path; do not rely on a bare count.
**Verify**: `grep -n "session_status.exists" src/app/api/chats/v1/router.py` →
**no matches** (the short-circuit is gone).
**Verify**: `PYTHONPATH=src python -c "
from app.ai_agent.ai_agent import new_chat, get_chat_owner, end_chat
s=new_chat(owner_subject='alice'); print(get_chat_owner(s)); end_chat(s); print(get_chat_owner(s))"` → `alice` then `None`
**Verify**: `pytest tests/test_stream_endpoint.py -q` → all pass

---

### Step 2: Ownership tests and the automated gate

**`tests/test_chat_ownership.py`** (create) — `pytestmark = pytest.mark.unit`.

Drive the real app through `httpx.ASGITransport(app=app)` and override
`get_principal` per case (`app.dependency_overrides[get_principal] = ...`,
restored afterwards). The conftest autouse fixture already installs a
`test-admin` principal; override it with a *different* subject for the foreign
cases. Follow `tests/test_authz_enforcement.py` for the override-and-restore
shape.

Assert:

- the creator's `GET /{id}` → 200.
- a **different** subject's `GET /{id}` → **404** (not 403).
- a different subject's `POST /{id}/stream` → 404 and **does not** stream.
- a different subject's `DELETE /{id}` → 404 and the session **still exists**
  for the owner (assert the owner's subsequent `GET` still returns 200).
- a session created with `owner_subject=None` → 404 for everyone, including an
  admin principal.
- the pre-existing 404 for a genuinely unknown id is unchanged.

Stub the provider (`monkeypatch.setattr(ai_agent, "_provider", ...)`) for the
stream case so no LLM call is attempted; see
`tests/test_chat_mcp_integration.py` for a minimal fake.

**AUTOMATED GATE — run once for this plan:**

**Verify**: `pytest -m unit tests -q` → ≥ **2586 passed**, 0 failed, 2 skipped
**Verify**: `pytest -m unit tests/test_chat_ownership.py -q` → all pass
**Verify**: `pytest tests/test_stream_endpoint.py -q` → all pass
**Verify**: `mypy src/` → exit 0
**Verify**: `pylint src --score=y` → ≥ 9.0
**Verify**: `bandit -c .bandit.yml -r src/ -lll` → exit 0

---

### Step 3: Live check with two real users

With the stack up (`docker compose up -d`), plans 053-057 deployed, the realm
reconciled, and the API/UI rebuilt from this working tree:

1. Sign in as `dev-user` in one browser profile. Open the chat page, send a
   message, and note the session id (the network tab shows
   `POST /api/v1/chats/<id>/stream`).
2. Sign in as `dev-admin` in a second profile. There is **no** way to obtain a
   `dev-user` bearer from a script — `/auth/token` exchanges the browser's
   `wba_session` cookie, and the realm disables the password grant on both
   clients — so perform this check **in the browser** as `dev-admin`, using the
   `dev-user` session id where the app would put it. Expect **404**.
3. Confirm `dev-admin` can still create and use **their own** chat (the change
   must not break the happy path).

**Verify**: (manual; record the observed status codes and visible state in the
gate record.)

> ### 🚦 MANUAL GATE 1 — foreign chat is 404 (browser, mandatory)
>
> Operator reports the exact status and visible state for each of the three
> checks. Any non-404 on the foreign chat at step 2, or a broken own-chat at
> step 3, is a STOP. Wait for `PASS`.

---

## Test plan

Step 2. The load-bearing assertions: **404 not 403** for a foreign chat, **the
foreign delete does not delete**, **the foreign stream does not stream**, and
**an unowned session is invisible to an admin**. The `grep` checks in Step 1
exist to keep the *stream* route honest — it is the easiest one to leave on the
old path while every other check still passes.

## Done criteria

- [ ] `pytest -m unit tests -q` exits 0, ≥ 2586 passed / 0 failed
- [ ] `pytest tests/test_stream_endpoint.py -q` exits 0 (it is not unit-marked)
- [ ] `mypy src/` exits 0; `pylint src --score=y` ≥ 9.0; `bandit` exits 0
- [ ] `grep -n "session_status.exists" src/app/api/chats/v1/router.py` → no matches
- [ ] `grep -n "require_user" src/app/api/chats/v1/router.py` → the four ownership routes by path
- [ ] A foreign chat request returns 404 in the live check (Gate 1)
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report if:

- `_chat_sessions` has a fourth reader beyond the three named in "Current
  state" — the parallel dict is then the wrong shape.
- `tests/test_chat_mcp_integration.py` starts failing. It creates sessions
  through the API, so owner == caller under the conftest override; a failure
  there means the service check is wrong, not that the test needs editing.
  **Do not edit that file to make it pass.**
- Any *unit-marked* test outside the scope list starts failing.
- In-scope files drifted from the excerpts.

## Maintenance notes

- **Chat sessions die on API restart** and that is unchanged. Persisting them is
  a separate, larger change; do not start it here.
- **`subject` is a Keycloak `sub`**, stable and never reused. It is not a
  username — do not join on `username` anywhere.
- **The favourites half of the original plan 058 is `plans/065`** and adds
  `subject` to `catalog_metadata`. It is independent of this plan; run it next.
- **A reviewer should scrutinize**: that the chat 404 does not leak existence
  (one error class for both cases), and that the *stream* route was converted
  rather than left on its `session_status.exists` short-circuit.
- **`tests/test_stream_endpoint.py` carries no `unit` marker**, so CI's
  `pytest -m unit` never runs it. It is the only regression cover for the SSE
  path's 200 case; run it by path. Adding the marker is plan 060's remit.

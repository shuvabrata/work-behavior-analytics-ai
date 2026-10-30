# Plan 058: Scope chat sessions and catalog favourites to their owner

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving on. If
> anything in "STOP conditions" occurs, stop and report — do not improvise.
> When done, update the status row in `plans/README.md`.
>
> **Every step ends with a MANUAL GATE.** Hand back to the operator and wait for
> `PASS`. A `FAIL` is a STOP condition.
>
> **Drift check (run first)**: `git diff --stat 225d3639..HEAD -- src/app/ai_agent/ai_agent.py src/app/api/chats/v1/ src/app/api/queries/v1/ src/app/db/models/catalog_metadata.py src/app/alembic/versions/ tests/test_catalog_metadata_api.py`
> Any mismatch against "Current state" is a STOP condition.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: MED
- **Depends on**: plans/057
- **Category**: security
- **Planned at**: commit `225d3639`, 2026-10-30
- **Design reference**: `docs/design/authn-authz-design.md`, Decision 9,
  "Endpoint matrix" (`Favourite toggle` and `Chat (own sessions)` rows)
- **This is step 6 of 9** in the Plan C sequence.

## Why this matters

Plan 057 made every request prove *who* it is. It did not stop one authenticated
user from acting on another user's data. Two holes remain:

1. **Chat sessions.** Sessions live in a process-wide dict keyed by a GUID.
   Anyone who knows or guesses a `session_id` can read its status, stream into
   it, or delete it. The design calls this "the `any session_id is usable by
   anyone` hole".
2. **Catalog favourites.** `catalog_metadata.catalog_id` is **globally unique** —
   one shared favourite per catalog entry. A standard user toggling a star
   changes what every user sees, which is a shared-configuration write the matrix
   says only admins may make.

After this plan, a chat session belongs to the subject that created it and a
favourite belongs to the subject that set it.

What improves when this lands: `GET/POST/DELETE /chats/{id}` returns **404** for
a session the caller does not own (404, not 403, so it does not confirm the id
exists), and the star toggle is per-user with no schema back-compat problem.

## Current state

**`src/app/ai_agent/ai_agent.py`** — the session store is a module-level dict:

```python
_chat_sessions: dict[str, list[dict[str, Any]]] = {}
```

`new_chat(system_prompt: str = "You are a helpful AI assistant.") -> str` at line
123 stores `_chat_sessions[session_id] = [{"role": "system", "content": system_prompt}]`.
`stream_chat` reads and appends to it; `end_chat` does
`_chat_sessions.pop(session_id, None)` at line 335.

**IMPORTANT — a pre-existing constraint, not something you fix here:** the API
runs under **uvicorn with one worker** (`src/app/entrypoint.sh:45`, no
`--workers`), so the dict is process-wide in practice. Do not add persistence;
that is out of scope.

**`src/app/api/chats/v1/service.py`** — every function takes only a
`session_id`:

```python
def create_chat_session(chat: ChatCreate) -> ChatSession:
    session_id = new_chat(system_prompt=chat.system_prompt or "")
    return ChatSession(session_id=session_id)

def get_chat_session_status(session_id: str) -> ChatSessionStatus:
    exists = session_id in _chat_sessions
    ...
```

**`src/app/api/chats/v1/router.py`** — four routes, none of which passes a
principal: `POST /`, `GET /{session_id}`, `POST /{session_id}/stream`,
`DELETE /{session_id}`, plus `GET /metrics/stream`.

**`src/app/db/models/catalog_metadata.py`** — no owner column, and:

```python
    catalog_id: Mapped[str] = mapped_column(
        String(255), nullable=False, unique=True
    )
```

**`src/app/api/queries/v1/service.py`** — `list_catalog_metadata`,
`get_catalog_metadata`, `set_catalog_metadata` all key on `catalog_id` alone.
The router wraps `set_catalog_metadata` in a `PUT /catalog-metadata/{catalog_id:path}`.

**Alembic head**: whatever plan 054 created (`add auth_session`).
`src/app/db/models/__init__.py` imports every model.

### Decisions already taken (do not re-litigate)

| Subject | Decision |
|---|---|
| Chat ownership storage | Record the owning `sub` **in the in-process session entry**. No schema, no persistence. |
| Foreign session response | **404**, never 403 (do not confirm existence). |
| Favourites schema | Add non-null `subject`; drop the global unique index; add unique `(catalog_id, subject)`. |
| Existing favourite rows | **Delete them in the migration.** They are dev-era artifacts with no real owner. |
| Theme ownership | **Not here.** Stays admin-only until Plan D. |

### Repo conventions that apply

- `service.py` owns business logic and transaction boundaries; `query.py` owns DB access.
- Alembic for every schema change; import the model in `db/models/__init__.py`.
- `Mapped`/`mapped_column`, `datetime` with `timezone=True`.
- Type hints everywhere; `mypy src/` strict.
- Tests carry markers.
- Do **not** commit or push unless asked.

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Unit tests | `pytest -m unit tests -q` | ≥ baseline, 0 fail |
| Typecheck | `mypy src/` | exit 0 |
| Lint | `pylint src --score=y` | ≥ 9.0 |
| Security scan | `bandit -c .bandit.yml -r src/ -lll` | exit 0 |
| Migration | `cd src/app && alembic upgrade head` | exit 0 |
| Migration preview | `cd src/app && alembic upgrade head --sql \| grep -c 'catalog_metadata'` | ≥ 1 |

## Scope

**In scope**:
- `src/app/ai_agent/ai_agent.py` — record and expose the owner.
- `src/app/api/chats/v1/service.py`, `router.py`, `model.py` — thread the principal through and enforce ownership.
- `src/app/db/models/catalog_metadata.py` — add `subject`.
- `src/app/api/queries/v1/query.py`, `service.py`, `router.py` — scope favourites.
- `src/app/alembic/versions/<new>_catalog_metadata_subject.py` (create)
- `tests/test_chat_ownership.py` (create)
- `tests/test_catalog_metadata_subject.py` (create)
- `tests/test_catalog_metadata_api.py` — update for the new owner semantics.

**Out of scope** (do NOT touch):
- Any auth mechanism — plans 054-057 own it.
- `graph_themes` — Plan D.
- Chat persistence or a chat-sessions table — explicitly not in this plan.
- The UI. `pages/chat.py` passes `session_id` through unchanged; the API is the
  authority and the UI does not need to know about ownership.
- `GET /chats/metrics/stream` — aggregate metrics, not per-session data. Leave
  it user-readable.

## Steps

### Step 1: Record the owner in the chat session store

In `src/app/ai_agent/ai_agent.py`, change the stored value so an entry carries an
owner. **Keep the message list shape** — `stream_chat` and `do_chat` index into
it, and rewriting that is out of scope.

Minimal, least-invasive shape — a parallel dict rather than changing the value
type:

```python
_chat_sessions: dict[str, list[dict[str, Any]]] = {}
# Owning Keycloak `sub` per session. A session with no entry here (created
# before this change, or by a process that did not pass an owner) is treated as
# unowned and is not accessible through the API.
_chat_session_owners: dict[str, str] = {}
```

Change `new_chat` to accept an optional owner and record it:

```python
def new_chat(
    system_prompt: str = "You are a helpful AI assistant.",
    *,
    owner_subject: str | None = None,
) -> str:
```

Record `_chat_session_owners[session_id] = owner_subject` when it is not `None`.
In `end_chat`, pop the owner alongside the messages.

Add a helper used by the API layer:

```python
def get_chat_owner(session_id: str) -> str | None:
    """Return the owning subject, or ``None`` when unowned/unknown."""
```

A parallel dict is chosen deliberately over changing the value type: `do_chat`
and `stream_chat` treat the value as a message list in several places, and a
value-type change would ripple. State this in a comment so a future reader does
not "simplify" it back.

**Verify**: `PYTHONPATH=src python -c "
from app.ai_agent.ai_agent import new_chat, get_chat_owner, end_chat
s=new_chat(owner_subject='alice'); print(get_chat_owner(s)); end_chat(s); print(get_chat_owner(s))"` → `alice` then `None`
**Verify**: `mypy src/` → exit 0

> ### 🚦 MANUAL GATE 1 — owner recorded
>
> Operator confirms the message-list shape is untouched and the owner is cleared
> with the session.
> Wait for `PASS`.

---

### Step 2: Enforce chat ownership in the service and router

In `src/app/api/chats/v1/service.py`, every ownership-sensitive function takes
the caller's subject. **Return 404 semantics, not 403** — the router decides the
status, the service reports "not found for this caller".

```python
class ChatSessionNotFoundError(Exception):
    """The session does not exist, or the caller does not own it.

    Deliberately one error for both cases: distinguishing them would let a
    caller probe for session ids that exist.
    """
```

- `create_chat_session(chat, *, owner_subject) -> ChatSession` — pass
  `owner_subject` to `new_chat`.
- `get_chat_session_status(session_id, *, subject)` — raise
  `ChatSessionNotFoundError` when the session is unknown **or** its owner is not
  `subject`.
- `stream_chat_response(session_id, user_message, *, subject)` — same check
  before streaming; raise `ChatSessionNotFoundError`.
- `delete_chat_session(session_id, *, subject)` — same check, then `end_chat`.

In `src/app/api/chats/v1/router.py`, obtain the principal on the four
ownership-sensitive routes. Use a **handler parameter** here (unlike plan 057's
`dependencies=[...]` form) because the value is genuinely needed:

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

The existing `stream_message` route already raises 404 for a missing session;
make it use the same ownership path so the two cannot diverge.

**`POST /` sets the owner** from `principal.subject`.
**`GET /metrics/stream`** takes no principal check beyond the router-level
`require_user` from plan 057 — it returns aggregates only.

**Verify**: `mypy src/` → exit 0
**Verify**: `grep -c "principal: Principal = Depends(require_user)" src/app/api/chats/v1/router.py` → `4` (create, get, stream, delete)
**Verify**: `pytest -m unit tests -q` → ≥ baseline

> ### 🚦 MANUAL GATE 2 — chat ownership
>
> Operator reviews the router: all four ownership routes take the principal, and
> an unowned session (owner `None`) is treated as not found.
> Wait for `PASS`.

---

### Step 3: Add `subject` to `catalog_metadata` and migrate

In `src/app/db/models/catalog_metadata.py`:

```python
    subject: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
```

Remove `unique=True` from `catalog_id` and add a composite unique constraint:

```python
    __table_args__ = (
        UniqueConstraint("catalog_id", "subject", name="uq_catalog_metadata_catalog_subject"),
    )
```

Update `__init__` to take `subject` as a required keyword argument, and update
`__repr__`.

Generate the migration:

```bash
cd src/app && alembic revision --autogenerate -m "catalog metadata per subject"
```

**The autogenerated migration will not do the right thing by itself** for a
non-null column on a table with rows. Edit it so the upgrade is:

1. `op.drop_constraint("catalog_metadata_catalog_id_key", "catalog_metadata", type_="unique")`
   — the exact constraint name may differ; inspect the DB with
   `\d catalog_metadata` and use the real name.
2. `op.execute("DELETE FROM catalog_metadata")` — the decided backfill: existing
   rows have no owner and are deleted. Put a comment saying so.
3. `op.add_column("catalog_metadata", sa.Column("subject", sa.String(255), nullable=False))`
   — safe **because step 2 emptied the table**. Order matters: delete first.
4. `op.create_index("ix_catalog_metadata_subject", "catalog_metadata", ["subject"])`
5. `op.create_unique_constraint("uq_catalog_metadata_catalog_subject", "catalog_metadata", ["catalog_id", "subject"])`

`downgrade()` reverses these (drop the constraint and index, drop the column,
recreate the unique constraint on `catalog_id`). Accept that favourites cannot
be restored — say so in the docstring.

Run `cd src/app && alembic upgrade head`.

**Verify**: `cd src/app && alembic heads` → one head
**Verify**: `docker compose exec -T postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c '\d catalog_metadata'` → shows `subject`, the index, and the composite unique constraint; `catalog_id` has no global unique constraint
**Verify**: `docker compose exec -T postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -tc 'SELECT count(*) FROM catalog_metadata'` → `0`

> ### 🚦 MANUAL GATE 3 — migration
>
> Operator confirms the delete-before-add ordering (a non-null column added to a
> populated table would fail), that the rows are gone, and that no other table
> changed.
> Wait for `PASS`.

---

### Step 4: Scope favourites to the caller

In `src/app/api/queries/v1/query.py` and `service.py`, every catalogue-metadata
operation takes `subject` and filters on it:

- `list_catalog_metadata(db, *, subject, is_favourite=None)` — always
  `WHERE subject = :subject`.
- `get_catalog_metadata(db, *, subject, catalog_id)` — returns `None` when the
  row belongs to someone else. Do **not** distinguish "missing" from
  "someone else's".
- `set_catalog_metadata(db, *, subject, catalog_id, is_favourite)` — upsert keyed
  on `(catalog_id, subject)`.

In `router.py`, add `principal: Principal = Depends(require_user)` to
`GET /catalog-metadata`, `GET /catalog-metadata/{catalog_id:path}`, and
`PUT /catalog-metadata/{catalog_id:path}`, and pass `principal.subject` down.

**Keep the existing validation** that `catalog_id` exists in the YAML catalog
(404 otherwise) — it is a separate concern and still correct.

**Verify**: `grep -c "subject=principal.subject" src/app/api/queries/v1/router.py` → `3`
**Verify**: `mypy src/` → exit 0
**Verify**: `mypy src/` and `pylint src --score=y` → clean

> ### 🚦 MANUAL GATE 4 — favourites
>
> Operator confirms a favourite set by one subject is invisible to another, and
> that the YAML-existence validation still returns 404 for an unknown
> `catalog_id`.
> Wait for `PASS`.

---

### Step 5: Tests

**`tests/test_chat_ownership.py`** — `pytestmark = pytest.mark.unit`
Through `httpx.ASGITransport` with `get_principal` overridden per case:
- `dev-user` creates a session; `GET /{id}` returns 200 for the creator.
- a **different** subject's `GET /{id}` → **404** (not 403).
- a different subject's `POST /{id}/stream` → 404 and **does not** stream.
- a different subject's `DELETE /{id}` → 404 and the session **still exists**
  for the owner.
- a session created with `owner_subject=None` → 404 for everyone.
- the existing 404 for a genuinely unknown id is unchanged.

**`tests/test_catalog_metadata_subject.py`** — `pytestmark = pytest.mark.unit`
Use the existing DB fixtures if present; otherwise exercise the service against a
stubbed session (follow the pattern in `tests/test_catalog_metadata_api.py`):
- two subjects can each favourite the same `catalog_id` and get independent rows.
- one subject's `GET` does not return the other's row.
- `PUT` by subject B on a row owned by A creates a **new** row, not an update.

**`tests/test_catalog_metadata_api.py`** — update existing assertions to include
the owner, and add the cross-subject invisibility case.

**Verify**: `pytest -m unit tests/test_chat_ownership.py tests/test_catalog_metadata_subject.py tests/test_catalog_metadata_api.py -q` → all pass
**Verify**: `pytest -m unit tests -q` → ≥ baseline + new, 0 fail
**Verify**: `bandit -c .bandit.yml -r src/ -lll` → exit 0

> ### 🚦 MANUAL GATE 5 — tests
>
> Operator confirms the cross-subject chat test asserts 404 **and** that the
> session survives a foreign delete.
> Wait for `PASS`.

---

### Step 6: Live check with two real users

With the stack up and plans 053-057 deployed:

1. Log in as `dev-user` in one browser profile; create a chat and note the URL /
   session id.
2. Log in as `dev-admin` in a second profile; request
   `GET /api/v1/chats/<dev-user's id>` through the UI's normal path (or via a
   bearer token obtained from `/auth/token`). Expect **404**.
3. As `dev-user`, star a catalog query. As `dev-admin`, confirm the star is not
   shown.

**Verify**: (manual; record the observed status codes and screenshots in the gate
record.)

> ### 🚦 MANUAL GATE 6 — live ownership (browser, mandatory)
>
> Operator performs the three checks above and reports the exact status and
> visible state for each. Any non-404 on the foreign chat is a STOP.
> Wait for `PASS`.

---

## Test plan

Step 5. The load-bearing assertions: **404 not 403** for a foreign chat, **the
foreign delete does not delete**, and **two subjects favourite independently**.

## Done criteria

- [ ] `pytest -m unit tests -q` exits 0, ≥ baseline + new
- [ ] `mypy src/` exits 0; `pylint src --score=y` ≥ 9.0; `bandit` exits 0
- [ ] `alembic heads` shows exactly one head
- [ ] `\d catalog_metadata` shows `subject`, the composite unique constraint, and **no** unique constraint on `catalog_id` alone
- [ ] `SELECT count(*) FROM catalog_metadata` → `0` after migration
- [ ] `grep -c "Depends(require_user)" src/app/api/chats/v1/router.py` → `4`
- [ ] A foreign chat request returns 404 in the live check
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report if:

- `_chat_sessions` is read anywhere outside `src/app/ai_agent/ai_agent.py` in a
  way the parallel dict breaks (grep it first; add call sites to the scope if so).
- The real unique-constraint name differs from the one in the migration and you
  cannot determine it from `\d catalog_metadata`.
- Deleting `catalog_metadata` rows is unacceptable to the operator (that decision
  is recorded, but a live-data objection overrides it — report).
- A UI page breaks because it relied on global favourites (it should not; the
  catalogue page reads through the scoped endpoint).
- In-scope files drifted.

## Maintenance notes

- **Chat sessions die on API restart** and that is unchanged. Persisting them is
  a separate, larger change; do not start it here.
- **`subject` is a Keycloak `sub`**, stable and never reused. It is not a
  username — do not join on `username` anywhere.
- **Plan D** adds `subject` to `graph_themes` with the same pattern; reuse this
  migration's shape, and note that themes need a nullable column (builtin rows
  have no owner) where favourites needed non-null.
- **A reviewer should scrutinize**: that the chat 404 does not leak existence,
  and that the migration deletes before adding the non-null column.

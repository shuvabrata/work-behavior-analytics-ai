# Plan 065: Scope catalog favourites to their owner

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving on. If
> anything in "STOP conditions" occurs, stop and report — do not improvise.
> When done, update the status row in `plans/README.md`.
>
> **This plan has exactly TWO manual gates** — Gate A on the **destructive**
> migration, Gate B on the live star-invisibility check. The automated gate at
> the end of Step 2 runs **once** for the whole plan; do not repeat it between
> steps. It includes the stack-dependent integration file, so bring the stack up
> (`docker compose up -d`) before running it.
>
> **Drift check (run first)**:
> `git diff --stat 665b1426..HEAD -- src/app/db/models/catalog_metadata.py src/app/api/queries/v1/query.py src/app/api/queries/v1/service.py src/app/api/queries/v1/router.py tests/test_catalog_metadata_model.py tests/test_catalog_metadata_api.py docs/design/authn-authz-design.md`
> Any diff against the "Current state" excerpts below in the model, query or
> service files is a STOP condition. Two files in that list are **expected to
> differ** from the stamp commit — `docs/design/authn-authz-design.md` (rewritten
> to state the opposite decision, which Step 4 corrects) and
> `tests/test_catalog_metadata_api.py` (now `authenticated` and green). Compare
> those two by content, not by diff emptiness. Run `cd src/app && alembic heads`
> and expect exactly one head before you start.
>
> **Locate by content, not by line number.** Line numbers below were accurate at
> the stamp commit and will drift as you edit.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: MED
- **Depends on**: plans/057 (DONE). Independent of plans/058 — but run 058 first;
  it is smaller and carries no migration.
- **Category**: security
- **Planned at**: commit `665b1426`, 2026-11-01
- **Design reference**: `docs/design/authn-authz-design.md`. Decision 9 and the
  `wba-user` roles row currently state that catalog favourites are **not**
  per-user and the toggle remains global — this plan implements the opposite
  decision, so **that document is in scope and must be updated** (see Step 4).
  There is no "Endpoint matrix" section in that document; do not go looking for
  one.
- **This is step 6 of 9** in the Plan C sequence, second half. **The number 065
  is appended, not sequential**: this work was originally the favourites half of
  `plans/058`, which was split into `058-per-user-ownership-of-chat-sessions.md`
  (chat) and this file. It executes **immediately after 058**, before plan 059.
  Plans 059-064 were already written and are not renumbered.

## Why this matters

Plan 057 made every request prove *who* it is. It did not stop one authenticated
user from writing data that affects others.

**Catalog favourites are shared configuration.** `catalog_metadata.catalog_id` is
**globally unique** — one favourite row per catalog entry, for the whole
application. A standard user toggling a star changes what every user sees. The
endpoint matrix grants `PUT /api/v1/queries/catalog-metadata/{id}` to a standard
user only for ***(own rows)***, and that qualifier does not exist in the code: the
write is a shared-configuration write, which the same matrix says only admins may
make.

After this plan, a favourite belongs to the subject that set it.

What improves when this lands: one user starring a catalog query no longer
appears in another user's favourites, and the endpoint finally matches the
`✓ (own rows)` the matrix claims.

## Current state

**`src/app/db/models/catalog_metadata.py`** — no owner column, and:

```python
    catalog_id: Mapped[str] = mapped_column(
        String(255), nullable=False, unique=True
    )
```

The uniqueness in the live database is a named constraint,
**`uq_catalog_metadata_catalog_id`** (verified against the running stack on
2026-11-01), created by
`src/app/alembic/versions/2026_09_03_1200-0c1d2e3f4a5b_add_catalog_metadata.py`:

```python
    op.create_unique_constraint(
        'uq_catalog_metadata_catalog_id', 'catalog_metadata', ['catalog_id']
    )
```

There is **no** constraint named `catalog_metadata_catalog_id_key` — do not write
a `drop_constraint` for that name.

The table also carries `id` (PK), `is_favourite` (boolean, not null),
`created_at` and `updated_at` (timestamptz, not null, `server_default now()`),
and `updated_at` has `onupdate=func.now()`. The model's `__init__` takes
`catalog_id` and an optional `is_favourite`, with an explicit
`super().__init__(...)`; `__repr__` prints `id`, `catalog_id`, `is_favourite`.

**Alembic head at the stamp commit: `fc1b240aeecb`** (`add auth_session`, plan
054). Confirm with `cd src/app && alembic heads` → exactly one head.

**`src/app/api/queries/v1/query.py`** — the three metadata functions key on
`catalog_id` alone:

```python
async def list_catalog_metadata(
    db: AsyncSession, *, is_favourite: bool | None = None
) -> list[CatalogMetadata]:
    stmt = select(CatalogMetadata).order_by(CatalogMetadata.catalog_id)
    if is_favourite is not None:
        stmt = stmt.where(CatalogMetadata.is_favourite.is_(is_favourite))
    ...

async def get_catalog_metadata(
    db: AsyncSession, catalog_id: str
) -> CatalogMetadata | None:
    stmt = select(CatalogMetadata).where(
        CatalogMetadata.catalog_id == catalog_id
    )
    ...

async def upsert_catalog_metadata(
    db: AsyncSession, catalog_id: str, is_favourite: bool
) -> CatalogMetadata:
    stmt = (
        pg_insert(CatalogMetadata)
        .values(catalog_id=catalog_id, is_favourite=is_favourite)
        .on_conflict_do_update(
            index_elements=[CatalogMetadata.catalog_id],
            set_={"is_favourite": is_favourite, "updated_at": func.now()},
        )
        .returning(CatalogMetadata)
    )
```

**`src/app/api/queries/v1/service.py`** — thin wrappers plus a YAML-existence
guard you must keep:

```python
async def set_catalog_metadata(
    db: AsyncSession, catalog_id: str, is_favourite: bool
) -> CatalogMetadata:
    _require_catalog_query(catalog_id)
    row = await query.upsert_catalog_metadata(db, catalog_id, is_favourite)
    await db.commit()
    await db.refresh(row)
    return row
```

`_require_catalog_query(catalog_id)` raises `CatalogQueryNotFoundError` (→ 404)
when the id is not in the YAML catalog. That is a separate concern from
ownership and stays exactly as it is.

**`src/app/api/queries/v1/router.py`** — the three metadata routes in full:

```python
@router.get("/catalog-metadata", response_model=CatalogMetadataListResponse)
async def list_catalog_metadata(
    is_favourite: bool | None = Query(
        default=None, description="Filter by favourite state"
    ),
    db: AsyncSession = Depends(get_async_db),
) -> CatalogMetadataListResponse:
    items = await service.list_catalog_metadata(db, is_favourite=is_favourite)
    ...

@router.get("/catalog-metadata/{catalog_id:path}", response_model=CatalogMetadataResponse)
async def get_catalog_metadata(
    catalog_id: str,
    db: AsyncSession = Depends(get_async_db),
) -> CatalogMetadataResponse:
    row = await service.get_catalog_metadata(db, catalog_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Catalog metadata not found")
    ...

@router.put("/catalog-metadata/{catalog_id:path}", response_model=CatalogMetadataResponse)
async def set_catalog_metadata(
    catalog_id: str,
    payload: CatalogMetadataPatch,
    db: AsyncSession = Depends(get_async_db),
) -> CatalogMetadataResponse:
    try:
        row = await service.set_catalog_metadata(db, catalog_id, payload.is_favourite)
    except CatalogQueryNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    ...
```

**`src/app/api/queries/v1/router.py` — a 057 change you must NOT undo.** Plan 057
already added `dependencies=[Depends(require_admin)]` to `PUT` and `DELETE
/queries/catalog/{namespace}/{slug}` — the *override* (YAML authoring) routes:

```python
@router.put(
    "/catalog/{namespace}/{slug}",
    response_model=CatalogQuery,
    response_model_exclude_none=True,
    dependencies=[Depends(require_admin)],
)
```

Those stay exactly as they are. The *favourites* routes
(`/queries/catalog-metadata*`) take a per-route principal in Step 2 and have **no**
admin requirement. Do not add `require_admin` to the metadata routes, and do not
remove it from the override routes.

`src/app/api/queries/v1/model.py` needs **no change**: `CatalogMetadataResponse`
exposes `id`, `catalog_id`, `is_favourite`, `created_at`, `updated_at`. `subject`
is an internal scoping key, not a response field — do not add it.

**Tests that depend on the code above** — read these before editing:

| File | Marker | Bearing on this plan |
|---|---|---|
| `tests/test_catalog_metadata_model.py` | `unit` | Builds `CatalogMetadata(catalog_id=...)` without `subject`, and `test_catalog_id_unique_constraint_defined` asserts `("catalog_id",)` is a unique column set. **Both break** when `subject` becomes required and the constraint becomes composite. |
| `tests/test_catalog_metadata_api.py` | `integration`, `server`, `authenticated` | Calls `https://localhost`; `tests/conftest.py` attaches a real admin bearer, and `tests/auth_helpers.user_headers()` mints a `wba-user` bearer for cross-subject cases. **Runnable and green today** (`8 passed`). Its assertions must be updated for the new semantics — see Step 2 — and it stays in the automated gate. |
| `tests/test_catalog_favourites_ui.py` | `unit` | Drives the Graph page's star callback with stubbed metadata. Asserts on `is_favourite` only, never on an owner — should keep passing untouched. If it does not, STOP. |
| `tests/conftest.py` | — | Autouse fixture authenticates every credential-less API test as `test-admin`. **Do not edit this file.** |

### Decisions already taken (do not re-litigate)

| Subject | Decision |
|---|---|
| Favourites schema | Add non-null `subject`; drop the global unique constraint; add unique `(catalog_id, subject)`. |
| Existing favourite rows | **Delete them in the migration.** They are dev-era artifacts with no real owner. (8 rows existed on the live stack on 2026-11-01.) |
| Foreign row response | `GET` returns 404 — do **not** distinguish "missing" from "someone else's". |
| Chat session ownership | **Not in this plan** — see `plans/058-per-user-ownership-of-chat-sessions.md`. |
| Theme ownership | **Not here.** Stays admin-only until Plan D. |

### Repo conventions that apply

- `service.py` owns business logic and transaction boundaries; `query.py` owns DB
  access.
- Alembic for every schema change; import the model in `db/models/__init__.py`.
- `Mapped`/`mapped_column`, `datetime` with `timezone=True`.
- Type hints everywhere; `mypy src/` is strict.
- Tests carry markers.
- Do **not** commit or push unless asked.

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Unit tests | `pytest -m unit tests -q` | ≥ **2629 passed**, 0 failed, 2 skipped (live baseline; this plan adds tests, so the count rises) |
| Typecheck | `mypy src/` | exit 0 |
| Lint | `pylint src --score=y` | ≥ 10.0 (CI fails below 10.0 — `.pylintrc` `fail-under=10`) |
| Integration tests | `pytest -m "integration and server" tests/test_catalog_metadata_api.py -q` | all pass (stack up) |
| Security scan | `bandit -c .bandit.yml -r src/ -lll` | exit 0 |
| Migration | `cd src/app && alembic upgrade head` | exit 0 |
| Migration heads | `cd src/app && alembic heads` | exactly one head |
| Migration preview | `cd src/app && alembic upgrade fc1b240aeecb:<NEW_REV> --sql` | see Step 1 |
| Schema inspect | `docker compose exec -T postgres sh -lc 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "\d catalog_metadata"'` | see Step 1 |
| Row count | `docker compose exec -T postgres sh -lc 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -tc "SELECT count(*) FROM catalog_metadata"'` | `0` after the migration |

Two command notes, both verified on 2026-11-01:

- The `psql` invocations **must** run through `sh -lc`. Without it the host shell
  expands `$POSTGRES_USER` to empty and psql fails with
  `role "wba" does not exist`.
- `alembic upgrade head --sql` is an offline dump of the **whole** schema from
  base to head, so grepping it for `catalog_metadata` returns `0` on an
  up-to-date database (the `CREATE TABLE` lives in an already-applied revision).
  Scope the dump to the new revision, as in the table above.

## Scope

**In scope**:
- `src/app/db/models/catalog_metadata.py` — add `subject`; composite constraint.
- `src/app/api/queries/v1/query.py`, `service.py`, `router.py` — scope favourites.
- `src/app/alembic/versions/<new>_catalog_metadata_subject.py` (create,
  hand-written — no `--autogenerate`)
- `tests/test_catalog_metadata_subject.py` (create)
- `tests/test_catalog_metadata_model.py` — update for the required `subject` and
  the composite constraint.
- `tests/test_catalog_metadata_api.py` — update its assertions and fixture for
  the new per-subject semantics. **Runnable today (`8 passed`)** and it stays in
  the automated gate (stack up).
- `tests/auth_helpers.py` — add a `subject(role)` helper that decodes the `sub`
  claim from the bearer JWT, so the teardown fixture can identify each role's own
  rows.
- `docs/design/authn-authz-design.md` — update Decision 9 and the `wba-user`
  roles row, which currently assert the opposite decision.

**Out of scope** (do NOT touch):
- Any auth mechanism — plans 054-057 own it. In particular do not edit
  `src/app/auth/`, `tests/conftest.py`, or the `AUTHZ_MATRIX` rows.
- `PUT`/`DELETE /queries/catalog/{namespace}/{slug}` and their `require_admin`.
- `src/app/api/queries/v1/model.py` — no response-shape change.
- `graph_themes` — Plan D.
- Chat sessions — plan 058.
- The UI. It reads and writes through these endpoints and will automatically act
  as the logged-in user, since `api_client` sends `Authorization: Bearer`. Do not
  teach the Graph page about ownership.

## Steps

### Step 1: Add `subject` to `catalog_metadata` and migrate

In `src/app/db/models/catalog_metadata.py`:

```python
    subject: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
```

Remove `unique=True` from `catalog_id` and add a composite unique constraint
(import `UniqueConstraint` from `sqlalchemy`):

```python
    __table_args__ = (
        UniqueConstraint("catalog_id", "subject", name="uq_catalog_metadata_catalog_subject"),
    )
```

**The `name=` argument is load-bearing.** The naming convention in
`src/app/db/base.py` (`"uq": "uq_%(table_name)s_%(column_0_name)s"`) would
otherwise render this composite constraint as `uq_catalog_metadata_catalog_id` —
the same name as the constraint this migration drops. Do not omit it.

Update `__init__` to take `subject` as a required keyword argument, and update
`__repr__`. Update the module docstring: `catalog_id` is no longer globally
unique — a row is unique per `(catalog_id, subject)`.

**Write the migration by hand — do not use `--autogenerate`.** Autogenerate
produces a non-null column without the delete-first ordering and drops the
explicit constraint names. Create the empty revision and fill it in:

```bash
cd src/app && alembic revision -m "catalog metadata per subject"
```

Confirm the generated file's `down_revision` is `fc1b240aeecb`, then write:

```python
def upgrade() -> None:
    """Scope catalog favourites to their owner."""
    op.drop_constraint("uq_catalog_metadata_catalog_id", "catalog_metadata", type_="unique")
    # Existing rows predate ownership and have no real owner; drop them so the
    # non-null column can be added.
    op.execute("DELETE FROM catalog_metadata")
    op.add_column("catalog_metadata", sa.Column("subject", sa.String(length=255), nullable=False))
    op.create_index("ix_catalog_metadata_subject", "catalog_metadata", ["subject"])
    op.create_unique_constraint(
        "uq_catalog_metadata_catalog_subject", "catalog_metadata", ["catalog_id", "subject"]
    )


def downgrade() -> None:
    """Revert to a single global favourite per catalog query.

    Per-user rows cannot be collapsed back into one global row, so the table is
    emptied before the global unique constraint is restored — recreating it over
    duplicate catalog_ids fails.
    """
    op.drop_constraint("uq_catalog_metadata_catalog_subject", "catalog_metadata", type_="unique")
    op.drop_index("ix_catalog_metadata_subject", table_name="catalog_metadata")
    op.drop_column("catalog_metadata", "subject")
    op.execute("DELETE FROM catalog_metadata")
    op.create_unique_constraint(
        "uq_catalog_metadata_catalog_id", "catalog_metadata", ["catalog_id"]
    )
```

Order matters in `upgrade()`: the delete must precede the non-null `add_column`.
In `downgrade()` the delete must precede the constraint restore, for the same
reason — two subjects favouring one query leave duplicate `catalog_id` values.

Run `cd src/app && alembic upgrade head`.

**Verify**: `cd src/app && alembic heads` → one head
**Verify**: `cd src/app && alembic upgrade fc1b240aeecb:<NEW_REV> --sql` →
contains `DELETE FROM catalog_metadata`, `ADD COLUMN subject`, and both new
constraint/index names
**Verify**:
`docker compose exec -T postgres sh -lc 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "\d catalog_metadata"'`
→ shows `subject`, `ix_catalog_metadata_subject`,
`uq_catalog_metadata_catalog_subject`; **no** unique constraint on `catalog_id`
alone; `uq_catalog_metadata_catalog_id` is gone
**Verify**:
`docker compose exec -T postgres sh -lc 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -tc "SELECT count(*) FROM catalog_metadata"'`
→ `0`
**Verify** (rollback round-trip): `cd src/app && alembic downgrade -1` → exit 0,
then `alembic upgrade head` → exit 0

> ### 🚦 MANUAL GATE A — migration (destructive)
>
> Operator confirms: the delete-before-add ordering (a non-null column added to a
> populated table would fail), that the previously-existing rows are gone, that
> the old `uq_catalog_metadata_catalog_id` is dropped, and that **no other table
> changed**. Wait for `PASS`.

### Gate A record — 2026-11-09 (PASSED)

Revision `04d7fde989ed`, `down_revision = fc1b240aeecb`. Applied by the API
container's own entrypoint (`src/app/entrypoint.sh` → `cd /app/app && alembic
upgrade head`), after the operator ran
`docker compose build api && docker compose up -d --force-recreate api`.
The host shell cannot reach the DB directly (`.env` `DATABASE_URL` names the
container host `postgres`, which does not resolve from the host), so the
entrypoint is the correct and only path.

Evidence:

- `alembic heads` (host, offline) → `04d7fde989ed (head)` — exactly one head.
- `alembic upgrade fc1b240aeecb:04d7fde989ed --sql` → emitted DDL is, in order:
  `DROP CONSTRAINT uq_catalog_metadata_catalog_id`; `DELETE FROM
  catalog_metadata`; `ADD COLUMN subject VARCHAR(255) NOT NULL`; `CREATE INDEX
  ix_catalog_metadata_subject`; `ADD CONSTRAINT
  uq_catalog_metadata_catalog_subject UNIQUE (catalog_id, subject)`. The delete
  precedes the non-null add, as required.
- Pre-migration `\d catalog_metadata` → `uq_catalog_metadata_catalog_id` was the
  live constraint name; there was no `catalog_metadata_catalog_id_key`.
- API container log → `Running upgrade fc1b240aeecb -> 04d7fde989ed, catalog
  metadata per subject`, then `Migrations complete`.
- `alembic_version` → `04d7fde989ed`.
- Post-migration `\d catalog_metadata` → columns `id`, `catalog_id`,
  `is_favourite`, `created_at`, `updated_at`, **`subject`** (varchar(255), NOT
  NULL); indexes `pk_catalog_metadata`, **`ix_catalog_metadata_subject`**, and
  **`uq_catalog_metadata_catalog_subject` UNIQUE (catalog_id, subject)**.
  `uq_catalog_metadata_catalog_id` is gone. No other table changed.
- `SELECT count(*) FROM catalog_metadata` → **`0`** (the pre-existing rows were
  deleted, as decided).
- `/api/health` → `200`; `Application startup complete`.
- **Round-trip** — operator ran `alembic downgrade -1 && alembic upgrade head`:
  downgrade `04d7fde989ed -> fc1b240aeecb`, then upgrade `fc1b240aeecb ->
  04d7fde989ed`, then `04d7fde989ed (head)`. Both exits 0. Post-round-trip
  `\d catalog_metadata` is identical to the pre-round-trip shape (`subject`,
  `ix_catalog_metadata_subject`, `uq_catalog_metadata_catalog_subject`, no
  `uq_catalog_metadata_catalog_id`) and `count(*)` is `0`.

**Gate A verdict: PASS** (operator, 2026-11-09).

---

### Step 2: Scope favourites to the caller, and the automated gate

**2.1 — `src/app/api/queries/v1/query.py`.**

Every catalogue-metadata operation takes `subject` and filters on it:

- `list_catalog_metadata(db, *, subject, is_favourite=None)` — always
  `WHERE subject = :subject`.
- `get_catalog_metadata(db, *, subject, catalog_id)` — returns `None` when the
  row belongs to someone else. Do **not** distinguish "missing" from "someone
  else's".
- `upsert_catalog_metadata(db, *, subject, catalog_id, is_favourite)` — the
  `ON CONFLICT` target becomes **the composite constraint**, not `catalog_id`:

```python
        .values(subject=subject, catalog_id=catalog_id, is_favourite=is_favourite)
        .on_conflict_do_update(
            index_elements=[CatalogMetadata.catalog_id, CatalogMetadata.subject],
            set_={"is_favourite": is_favourite, "updated_at": func.now()},
        )
```

**2.2 — `src/app/api/queries/v1/service.py`.**

Thread `subject` through all three wrappers. Keep `_require_catalog_query` and
call it **before** the upsert, exactly where it is today. Return `None` (not an
error) from `get_catalog_metadata` when the row is not the caller's.

**2.3 — `src/app/api/queries/v1/router.py`.**

Add a principal parameter to each of the three metadata routes and pass
`principal.subject` down:

```python
    principal: Principal = Depends(require_user),
```

Import `Principal` from `app.auth.principal` and `require_user` from
`app.auth.dependencies`. Leave the neighbouring `require_admin` on the override
routes untouched, and leave `CatalogMetadataResponse` unchanged.

The YAML-existence 404 for an unknown `catalog_id` on `PUT` stays — it is a
separate concern and still correct.

**2.4 — `tests/test_catalog_metadata_model.py`** (update, required by 1):

- `_make_metadata` and the inline `CatalogMetadata(catalog_id=...)` case must
  pass `subject=...`.
- `test_catalog_id_unique_constraint_defined` currently asserts `("catalog_id",)`
  is a unique column set. It now must assert `("catalog_id", "subject")`.
- `test_instantiates_with_defaults` must construct with a `subject`.

**2.5 — `tests/test_catalog_metadata_subject.py`** (create) —
`pytestmark = pytest.mark.unit`.

There is **no Postgres fixture for unit tests** in this repo and no sqlite test
database. Assert on the **compiled SQL** of the statement each query-layer
function builds, using a recorder session that captures the statement passed to
`execute()`. This is the only technique that can see a WHERE predicate or an
`ON CONFLICT` target — a canned-row fake cannot, because the filtering happens in
Postgres, not in Python.

```python
pytestmark = [pytest.mark.unit, pytest.mark.asyncio]

class _Recorder:
    """AsyncSession stub that records statements and returns canned rows."""
    def __init__(self, rows=()):
        self.statements = []
        self._rows = list(rows)
    async def execute(self, stmt):
        self.statements.append(stmt)
        return _Result(self._rows)
    async def refresh(self, row):
        return None

def _sql(sess) -> str:
    return str(sess.statements[-1].compile(
        dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
```

Three cases, each asserting a fact that disappears if the change is reverted:

1. `list_catalog_metadata(db, subject="user-1")` → `_sql` contains
   `catalog_metadata.subject` and the literal `'user-1'`.
2. `get_catalog_metadata(db, subject="user-1", catalog_id="a/b")` → `_sql`
   contains both `'user-1'` and `'a/b'`.
3. `upsert_catalog_metadata(db, subject="user-1", catalog_id="a/b", is_favourite=True)`
   → `_sql` contains `ON CONFLICT (catalog_id, subject) DO UPDATE`.

Use the compiled text for case 3. `index_elements` is **not** an attribute on the
compiled `OnConflictDoUpdate` node (it is consumed at compile time), so
`stmt._post_values_clause.index_elements` raises `AttributeError`. Either assert
on the compiled string as above, or on
`[c.name for c in stmt._post_values_clause.inferred_target_elements]`.

**Non-vacuousness check (mandatory).** Run this file once with (a) the `subject`
predicate deleted from `get_catalog_metadata` and (b) `index_elements` left as
`[CatalogMetadata.catalog_id]`. Both must **fail**. Record the observed failures
in the gate record, then restore. A test that passes with the change reverted is
worthless.

**2.6 — `tests/test_catalog_metadata_api.py`** (rewrite for the new semantics).

This file is `integration` + `server` + `authenticated`, runs today
(`8 passed`), and **stays in the automated gate** (stack up). Two identities:
`admin_headers()` and `user_headers()` from `tests/auth_helpers.py`.

**Fix the teardown fixture first — it leaks rows after this change.** The
session-scoped `metadata_snapshot` fixture currently snapshots and tears down by
`catalog_id` alone *as admin*. Once reads are per-subject, `GET
/catalog-metadata` returns only the caller's rows, so a row created by a
`dev-user` test is never listed and never deleted. It must:

- snapshot a set of `(catalog_id, subject)` pairs, fetched **once for each of the
  two identities** — `admin_headers()` and `user_headers()` — and take the union;
- on teardown, fetch **again for both identities** and delete any pair not in the
  snapshot. Both phases must cover both identities: a `dev-user` row is invisible
  to the admin read, so an admin-only teardown silently leaks it;
- the subject for each identity is the principal's Keycloak `sub`, which the dev
  users do **not** have hard-coded in the realm template (Keycloak assigns a
  random UUID at import). Decode the `sub` claim from the bearer JWT — add a
  `subject(role)` helper beside `headers()` in `tests/auth_helpers.py` that
  base64-decodes the token payload (no signature verification needed in a test).
  Do **not** hard-code a subject string; `dev-admin`/`dev-user` are usernames,
  not `sub` values;
- delete by both keys:

```python
def _delete_metadata_row(catalog_id: str, subject: str) -> None:
    ...
    cur.execute(
        "DELETE FROM catalog_metadata WHERE catalog_id = %s AND subject = %s",
        (catalog_id, subject),
    )
```

Then rewrite the assertions. Cases, each named for the harm it prevents:

| Case | Assertion |
|---|---|
| `test_user_star_is_invisible_to_admin` | `user` PUTs X true → `user` GET lists X; `admin` GET does **not** |
| `test_admin_star_is_invisible_to_user` | symmetric |
| `test_two_subjects_coexist` | both star X → 2 rows; each GET shows only its own `is_favourite` |
| `test_put_by_other_subject_does_not_update_owner` | `user` stars X, then `admin` stars X → `user` GET still `is_favourite=true` (the core regression) |
| `test_get_foreign_row_is_404` | `admin` owns X; `user` `GET /{X}` → **404**, body does not distinguish "someone else's" from missing |
| `test_put_is_idempotent_per_subject` | same subject PUTs twice → exactly 1 row for that subject |
| `test_put_unknown_catalog_id_still_404` | unchanged (the existence guard still runs before the upsert) |

**Non-vacuousness check:** revert the router to a `catalog_id`-keyed upsert and
confirm `test_put_by_other_subject_does_not_update_owner` fails.

**2.7 — `tests/test_catalog_favourites_ui.py`** — leave untouched. It drives the
star callback with stubbed metadata and asserts on `is_favourite` only; the UI is
unchanged (it acts as the logged-in user because `src/ui/api_client.py` attaches
the bearer). It must keep passing — if it does not, STOP.

**AUTOMATED GATE — run once for this plan:**

**Verify**: `pytest -m unit tests -q` → ≥ **2629 passed + the new tests**, 0 failed, 2 skipped
**Verify**: `pytest -m unit tests/test_catalog_metadata_subject.py tests/test_catalog_metadata_model.py tests/test_catalog_favourites_ui.py -q` → all pass
**Verify**: `pytest -m "integration and server" tests/test_catalog_metadata_api.py -q` → all pass (stack up)
**Verify**: `mypy src/` → exit 0
**Verify**: `pylint src --score=y` → ≥ 10.0
**Verify**: `bandit -c .bandit.yml -r src/ -lll` → exit 0

### Step 2 record — 2026-11-09 (code complete; integration pending rebuild)

Code changes landed (uncommitted): `query.py`, `service.py`, `router.py` take and
filter on `subject`; the upsert's `ON CONFLICT` target is the composite
`(catalog_id, subject)`; the three metadata routes take
`principal: Principal = Depends(require_user)` and pass `principal.subject`.
`require_admin` remains on the *override* routes only. The authz matrix already
declared `"user"` for all three metadata routes — no matrix change was needed.

Independent evidence (host working tree, `.venv`):

- `pytest -m unit tests -q` → **2632 passed, 2 skipped, 0 failed** (baseline 2629
  + 3 new in `tests/test_catalog_metadata_subject.py`).
- `pytest -m unit tests/test_catalog_metadata_subject.py
  tests/test_catalog_metadata_model.py tests/test_catalog_favourites_ui.py -q`
  → **25 passed**. `test_catalog_favourites_ui.py` passes untouched, as the plan
  requires.
- `mypy src/` → `Success: no issues found in 325 source files`.
- `pylint src --score=y` → **10.00/10** (one pre-existing `C0412` in the
  untouched `src/ui/components/common.py`).
- `bandit -c .bandit.yml -r src/ -lll` → exit 0, 0 High.

**Non-vacuousness checks (both confirmed by observing the failure, then reverting):**

1. Deleting the `subject` predicate from `get_catalog_metadata` →
   `test_filters_by_subject_and_catalog_id` fails: the compiled SQL is
   `... WHERE catalog_metadata.catalog_id = 'a/b'` with no `'user-1'`.
2. Setting `index_elements=[CatalogMetadata.catalog_id]` →
   `test_conflict_target_is_catalog_id_and_subject` fails: the compiled SQL emits
   `ON CONFLICT (catalog_id)` rather than `ON CONFLICT (catalog_id, subject)`.

**OUTSTANDING — integration gate.** `pytest -m "integration and server"
tests/test_catalog_metadata_api.py -q` has **not** been run. It drives the live
stack over `https://localhost`, and the running `api` container was built before
these edits: `grep -c require_user /app/app/api/queries/v1/router.py` → `0`, and
`get_catalog_metadata` in the container still carries the old `catalog_id`-only
signature. The image must be rebuilt and the container recreated
(`docker compose build api && docker compose up -d --force-recreate api`) —
`build` alone leaves the old container serving old code. **Do not treat the
integration file as passing until that run is observed.**

### Step 2 record, continued — 2026-11-10 (integration gate PASSED)

After the operator's rebuild, the first integration run was **2 failed, 1 error**
— and the failures were in the *test*, not the implementation. Two defects, both
in `tests/test_catalog_metadata_api.py` as originally written by this plan:

1. **DSN built from `settings.DATABASE_URL`.** That value names the container host
   `postgres`, which a host-run test cannot resolve, so teardown died with
   `could not translate host name "postgres"`. The repo already has the correct
   pattern in `tests/test_auth_integration.py::_dsn` — build the DSN from
   `POSTGRES_*` env values against the published `127.0.0.1:5432`. Adopted it.
2. **No per-test isolation.** Several tests share `VALID_CATALOG_ID` and mutate
   persistent state, with only session-scoped cleanup. A row left by one test was
   visible to the next, so "the other identity does not see X" assertions reported
   the previous test's verdict.

The decisive evidence that the *implementation* was correct all along: with the
`psycopg2` teardown broken, the table retained two distinct rows for one
`catalog_id` — `07f52a87-…` (`dev-user`) and `7d871eae-…` (`dev-admin`), each
with its own `is_favourite`. That is exactly the intended per-subject behaviour.

Added an autouse `_isolate_metadata` fixture that clears this suite's rows for
both identities before and after each test. It **clears rather than restores**:
`VALID_CATALOG_ID` is scratch for this suite, so a pre-existing row there is
residue from a crashed earlier run — preserving it is the bug, not the fix. The
plan's session-scoped `metadata_snapshot` still restores the pre-run state.

**Final integration result: 13 passed, 0 failed, 0 errors.** Post-run
`SELECT count(*) FROM catalog_metadata` → **`0`** — the teardown leaks nothing.

**Non-vacuousness of the composite conflict target.** The plan asks for the
router/query to be reverted and a test failure observed. Rather than a second
image rebuild, the fact was established structurally against the live schema:
`pg_indexes` for `catalog_metadata` shows only
`uq_catalog_metadata_catalog_subject ON (catalog_id, subject)` — **no** unique
index on `catalog_id` alone. Postgres infers the `ON CONFLICT` arbiter from a
unique index, so an `ON CONFLICT (catalog_id)` target cannot resolve on this
schema. The unit-level revert proof for the same fact is recorded above
(non-vacuousness check 2).

**Automated gate — all green, re-run after the test fixes:**

- `pytest -m unit tests -q` → **2632 passed, 2 skipped, 0 failed**
- `pytest -m "integration and server" tests/test_catalog_metadata_api.py -q` →
  **13 passed**
- `mypy src/` → `Success: no issues found in 325 source files`
- `pylint src --score=y` → **10.00/10**
- `bandit -c .bandit.yml -r src/ -lll` → exit 0

---

### Step 3: Live check with two real users

With the stack up (`docker compose up -d`), the realm reconciled, and the API/UI
rebuilt from this working tree.

The API-level invisibility is already proven by the rewritten
`tests/test_catalog_metadata_api.py` in the automated gate. This step covers the
one thing those tests cannot see: **what the browser renders**.

1. Sign in as `dev-user` in one browser profile. On the Graph page, star a
   catalog query. Confirm the star renders filled, and that the favourites
   filter in `src/ui/pages/graph/callbacks/catalog.py` shows it.
2. Sign in as `dev-admin` in a second profile. Reload the catalog and confirm
   the star is **outline**, not filled, and the query is absent from
   `dev-admin`'s favourites filter.
3. As `dev-admin`, star a **different** query. Confirm `dev-user` still sees only
   their own star.
4. As `dev-user`, star an id that does not exist in the YAML catalog and confirm
   the **404** is unchanged (the existence guard still runs before the upsert).

**Verify**: (manual; record the observed state for each check in the gate
record.)

> ### 🚦 MANUAL GATE B — one user's star is invisible to another (browser, mandatory)
>
> Operator reports the exact rendered state for each check. Any leak of one
> user's star to the other, or a lost 404 on check 4, is a STOP.
> Wait for `PASS`.

### Gate B record — 2026-11-10 (PASSED)

Two browser profiles on `https://localhost/app/graph` — `dev-user` and
`dev-admin`. The plan's checks 1–4, with the DB inspected after each:

| Check | Observed | Verdict |
|---|---|---|
| 1. `dev-user` stars "Top N Code Committer"; `dev-admin` reloads | `dev-admin` saw an outline star and no re-sort. DB: one row, `hall_of_fame/top_n_committers` owned by `07f52a87-…` (`dev-user`) | PASS |
| 2. `dev-admin` stars "Top N Code Reviewer"; `dev-user` reloads | `dev-user` saw it outline; its own committer star still filled. DB: row owned by `7d871eae-…` (`dev-admin`) | PASS |
| 3. Both star the **same** query (`Top N Code Reviewer`) | Filled in **both** profiles at once. DB: **two rows for one `catalog_id`**, one per subject (id 1511 `07f52a87-…`, id 1506 `7d871eae-…`). The second star **inserted** a new row rather than updating the other's — composite-key behaviour | PASS |
| 4. Unknown `catalog_id` still 404 | `PUT /api/v1/queries/catalog-metadata/nonexistent/does_not_exist` → **404** `{"detail":"Catalog query not found: …"}`; control `PUT` on a valid id → **200** | PASS |

**Two notes for anyone re-running this gate:**

- **The page URL must be `https://localhost/app/graph`.** `load_query_catalog`
  gates on an exact `pathname` match, and `display_page` falls through to the
  Graph layout for unknown paths — so a browser at bare `/app/` *renders* the
  Graph page while the catalog callback correctly declines to load, leaving the
  panel at "No catalog metadata loaded yet." That is pre-existing routing
  behaviour, unrelated to this change.
- **Check 4 cannot be driven from the browser console.** `/api/v1` is bearer-only;
  the browser holds a `wba_session` cookie and the bearer is attached
  server-side by `src/ui/api_client.py`. A console `fetch` carries no
  `Authorization` header and correctly returns 401. Use a real bearer (e.g.
  `tests/auth_helpers.user_headers()`).

**Gate B verdict: PASS** (operator, 2026-11-10).

---

### Step 4: Update the design document

`docs/design/authn-authz-design.md` currently records the **opposite** decision.
Update it so the design record matches the shipped behaviour:

1. Decision 9 (the Decision Summary table) currently reads:

   > Per-user ownership of chat sessions | Chat sessions are owner-scoped,
   > closing the "any `session_id` is usable by anyone" hole. Catalog favourites
   > are **not** per-user: catalog metadata carries no `subject` column, so the
   > favourite toggle remains global.

   Rewrite it to state that catalog favourites are owner-scoped, keyed by
   `(catalog_id, subject)`, and that the favourite toggle writes the caller's own
   row.

2. The `wba-user` roles row currently says the standard user manages "their own
   chat sessions". Extend it to include catalog favourites.

**Verify**: `grep -n "favourite" docs/design/authn-authz-design.md` → no line
claims favourites are not per-user or that the toggle is global.

### Step 4 record — 2026-11-10 (DONE)

Two passages updated:

1. **Decision 9** — retitled "Per-user ownership of chat sessions and catalog
   favourites"; the rationale now states that `catalog_metadata` carries a
   non-null `subject` column, is unique per `(catalog_id, subject)`, and that the
   toggle writes the caller's own row.
2. **`wba-user` roles row** — now reads "manage their own chat sessions and their
   own catalog favourites".

**Verified** (observed): `grep -n "favourite" docs/design/authn-authz-design.md`
→ the two updated lines only; `grep -niE "not per-user|remains global|no
'subject' column"` → no matches.

---

## Test plan

Step 2, split by what each layer can actually prove:

- **Unit** (`tests/test_catalog_metadata_subject.py`) asserts on **compiled SQL** —
  the `subject` predicate in `list_catalog_metadata` / `get_catalog_metadata`, and
  the composite `ON CONFLICT (catalog_id, subject)` target in
  `upsert_catalog_metadata`. A canned-row fake cannot prove these, because the
  filtering happens in Postgres. Both assertions are verified non-vacuous by
  reverting the change and observing the failure.
- **Integration** (`tests/test_catalog_metadata_api.py`, stack up) is the only
  place the SQL filtering is genuinely exercised, with two real identities
  (`admin_headers()` / `user_headers()`). The load-bearing cases: **two subjects
  favourite the same `catalog_id` independently**, **one subject's `GET` does not
  return the other's row (404)**, and **`PUT` by subject B on a row owned by A
  does not update A's row**.
- **Gate B** then proves only the browser rendering, which no API test can see.

## Done criteria

- [ ] `pytest -m unit tests -q` exits 0, ≥ 2629 passed + the new tests / 0 failed
- [ ] `pytest -m "integration and server" tests/test_catalog_metadata_api.py -q` exits 0 (stack up)
- [ ] `mypy src/` exits 0; `pylint src --score=y` ≥ 10.0; `bandit` exits 0
- [ ] New unit tests fail when the `subject` predicate / composite `ON CONFLICT` target is reverted (non-vacuousness check recorded)
- [ ] `alembic heads` shows exactly one head; `alembic downgrade -1` then `alembic upgrade head` both exit 0
- [ ] `\d catalog_metadata` shows `subject`, `ix_catalog_metadata_subject`, `uq_catalog_metadata_catalog_subject`, and neither `uq_catalog_metadata_catalog_id` nor `catalog_metadata_catalog_id_key`
- [ ] `SELECT count(*) FROM catalog_metadata` → `0` after the migration
- [ ] Row count unchanged after the integration run (teardown fixture leaks nothing)
- [ ] `CatalogMetadataResponse` still exposes no `subject` field
- [ ] `grep -n "favourite" docs/design/authn-authz-design.md` shows no "not per-user" / "remains global" claim
- [ ] One user's star renders invisible to another in the live check (Gate B)
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report if:

- `tests/test_catalog_favourites_ui.py` or any other *unit-marked* test outside
  the scope list starts failing. The known candidates are accounted for above;
  anything else means the blast radius is wider than this plan claims.
- Deleting `catalog_metadata` rows is unacceptable to the operator (that decision
  is recorded, but a live-data objection overrides it — report).
- `alembic heads` shows more than one head before you start — another plan's
  migration is unreconciled. Report rather than guessing a merge.
- In-scope files drifted from the excerpts.

## Maintenance notes

- **`subject` is a Keycloak `sub`**, stable and never reused. It is not a
  username — do not join on `username` anywhere.
- **Plan D** adds `subject` to `graph_themes` with the same pattern; reuse this
  migration's shape, and note that themes need a **nullable** column (builtin
  rows have no owner) where favourites needed non-null. That difference is the
  part most likely to be copied wrongly.
- **The favourites rows are now per-user**, so `SELECT count(*) FROM
  catalog_metadata` grows with usage rather than staying at the number of
  catalog entries. A future "favourite counts" feature must not assume one row
  per `catalog_id`.
- **A reviewer should scrutinize**: that the migration deletes before adding the
  non-null column, that the `ON CONFLICT` target is the *composite* constraint
  (targeting `catalog_id` alone would raise at runtime once the old unique
  constraint is gone), and that `require_admin` was not added to the metadata
  routes.

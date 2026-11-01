# Plan 065: Scope catalog favourites to their owner

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving on. If
> anything in "STOP conditions" occurs, stop and report — do not improvise.
> When done, update the status row in `plans/README.md`.
>
> **This plan has exactly TWO manual gates** — Gate A on the **destructive**
> migration, Gate B on the live star-invisibility check. The automated gate at
> the end of Step 2 runs **once** for the whole plan; do not repeat it between
> steps.
>
> **Drift check (run first)**:
> `git diff --stat 665b1426..HEAD -- src/app/db/models/catalog_metadata.py src/app/api/queries/v1/query.py src/app/api/queries/v1/service.py src/app/alembic/versions/`
> Any diff against the "Current state" excerpts below in the model, query or
> service files is a STOP condition. A new migration file in that directory is
> fine — as long as it is not another plan's *unrebased* head; run
> `cd src/app && alembic heads` and expect exactly one head before you start.
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
- **Design reference**: `docs/design/authn-authz-design.md`, Decision 9,
  "Endpoint matrix", the `Favourite toggle` row
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
| `tests/test_catalog_metadata_api.py` | `integration`, `server` | Calls `https://localhost` with **no `Authorization` header** — currently 8 errors, all 401, since 057. **Not runnable in this plan**; see Step 2. |
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
| Unit tests | `pytest -m unit tests -q` | ≥ **2586 passed**, 0 failed, 2 skipped (baseline measured at `665b1426`) |
| Typecheck | `mypy src/` | exit 0 |
| Lint | `pylint src --score=y` | ≥ 9.0 |
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
- `src/app/alembic/versions/<new>_catalog_metadata_subject.py` (create)
- `tests/test_catalog_metadata_subject.py` (create)
- `tests/test_catalog_metadata_model.py` — update for the required `subject` and
  the composite constraint.
- `tests/test_catalog_metadata_api.py` — update its assertions for the new
  semantics. See Step 2: it cannot execute until plan 060 exists, so it is in
  **no** Verify and no done criterion.

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

Update `__init__` to take `subject` as a required keyword argument, and update
`__repr__`. Update the module docstring: `catalog_id` is no longer globally
unique — a row is unique per `(catalog_id, subject)`.

Generate the migration:

```bash
cd src/app && alembic revision --autogenerate -m "catalog metadata per subject"
```

**The autogenerated migration will not do the right thing by itself** for a
non-null column on a table with rows. Edit it so `upgrade()` is, in this order:

1. `op.drop_constraint("uq_catalog_metadata_catalog_id", "catalog_metadata", type_="unique")`
   — this is the real, verified name. Do not invent a different one.
2. `op.execute("DELETE FROM catalog_metadata")` — the decided backfill: existing
   rows have no owner and are deleted. Put a comment saying so.
3. `op.add_column("catalog_metadata", sa.Column("subject", sa.String(255), nullable=False))`
   — safe **because step 2 emptied the table**. Order matters: delete first.
4. `op.create_index("ix_catalog_metadata_subject", "catalog_metadata", ["subject"])`
5. `op.create_unique_constraint("uq_catalog_metadata_catalog_subject", "catalog_metadata", ["catalog_id", "subject"])`

`downgrade()` reverses these — drop the composite constraint and index, drop the
column, recreate `uq_catalog_metadata_catalog_id` on `catalog_id`. Accept that
favourites cannot be restored; say so in the docstring.

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

> ### 🚦 MANUAL GATE A — migration (destructive)
>
> Operator confirms: the delete-before-add ordering (a non-null column added to a
> populated table would fail), that the previously-existing rows are gone, that
> the old `uq_catalog_metadata_catalog_id` is dropped, and that **no other table
> changed**. Wait for `PASS`.

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
database. Follow the established pattern in
**`tests/test_activity_api_integration.py`**: override `get_async_db` with a fake
session whose `execute()` returns canned rows, and assert on the SQLAlchemy
statement it captured — that file's docstring describes the technique, and it is
how this repo unit-tests query-layer scoping without a database.

Assert:

- the statement `list_catalog_metadata` builds carries a `subject` predicate;
- `get_catalog_metadata` for a row owned by another subject yields `None`;
- `upsert_catalog_metadata` targets `["catalog_id", "subject"]` and binds
  `subject`.

If you cannot build a meaningful fake for the `pg_insert ... on_conflict` path,
**say so in a comment and assert on the constructed statement only** — do not
fabricate a passing test, and do not weaken the service to make stubbing easier.

**2.6 — `tests/test_catalog_metadata_api.py`** (update, **not** gated).

This file is `integration` + `server` and calls `https://localhost` with **no
`Authorization` header**; since 057 it fails with 8× 401, and `-m unit` deselects
it entirely. Update its assertions for the new semantics (a row carries
`subject`; add the cross-subject invisibility case), but **do not** try to make
it execute — minting a bearer for integration tests is plan 060's job. Do **not**
relax authentication to make it pass. It appears in no Verify and no done
criterion.

**AUTOMATED GATE — run once for this plan:**

**Verify**: `pytest -m unit tests -q` → ≥ **2586 passed**, 0 failed, 2 skipped
**Verify**: `pytest -m unit tests/test_catalog_metadata_subject.py tests/test_catalog_metadata_model.py tests/test_catalog_favourites_ui.py -q` → all pass
**Verify**: `mypy src/` → exit 0
**Verify**: `pylint src --score=y` → ≥ 9.0
**Verify**: `bandit -c .bandit.yml -r src/ -lll` → exit 0

---

### Step 3: Live check with two real users

With the stack up (`docker compose up -d`), plans 053-057 deployed, the realm
reconciled, and the API/UI rebuilt from this working tree:

1. Sign in as `dev-user` in one browser profile. On the Graph page, star a
   catalog query. Confirm it appears in `dev-user`'s favourites filter.
2. Sign in as `dev-admin` in a second profile. Reload the catalog and confirm
   the star is **not** shown, and the query is not in `dev-admin`'s favourites
   filter (`GET /api/v1/queries/catalog-metadata?is_favourite=true`).
3. As `dev-admin`, star a **different** query. Confirm `dev-user` still sees only
   their own star — the two rows coexist.
4. As `dev-user`, star an id that does not exist in the YAML catalog and confirm
   the **404** is unchanged (the existence guard still runs before the upsert).

**Verify**: (manual; record the observed state for each check in the gate
record.)

> ### 🚦 MANUAL GATE B — one user's star is invisible to another (browser, mandatory)
>
> Operator reports the exact visible state for each check. Any leak of one
> user's star to the other, or a lost 404 on check 4, is a STOP.
> Wait for `PASS`.

---

## Test plan

Step 2. The load-bearing assertions: **two subjects favourite the same
`catalog_id` independently**, **one subject's `GET` does not return the other's
row**, and **`PUT` by subject B on a row owned by A creates a new row rather
than updating A's**. The query-layer unit tests are statement-level because there
is no unit-test database; the live Gate B is what proves the behaviour
end-to-end.

## Done criteria

- [ ] `pytest -m unit tests -q` exits 0, ≥ 2586 passed / 0 failed
- [ ] `mypy src/` exits 0; `pylint src --score=y` ≥ 9.0; `bandit` exits 0
- [ ] `alembic heads` shows exactly one head
- [ ] `\d catalog_metadata` shows `subject`, `ix_catalog_metadata_subject`, `uq_catalog_metadata_catalog_subject`, and neither `uq_catalog_metadata_catalog_id` nor `catalog_metadata_catalog_id_key`
- [ ] `SELECT count(*) FROM catalog_metadata` → `0` after the migration
- [ ] `CatalogMetadataResponse` still exposes no `subject` field
- [ ] One user's star is invisible to another in the live check (Gate B)
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report if:

- `tests/test_catalog_favourites_ui.py` or any other *unit-marked* test outside
  the scope list starts failing. The known candidates are accounted for above;
  anything else means the blast radius is wider than this plan claims.
- `tests/test_catalog_metadata_api.py` cannot be made semantically correct
  without touching authentication — report; that is 060's territory.
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

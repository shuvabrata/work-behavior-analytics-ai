# Plan 011: Drop the dead `connectors.enabled` column

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**:
> `git diff --stat 8e1d0b5a..HEAD -- src/app/db/models/connector.py src/app/api/connectors/v1/ src/app/scheduler.py tests/test_scheduler.py docs/design/scan-scheduler-design.md`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P3
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: tech-debt
- **Planned at**: commit `8e1d0b5a`, 2026-11-22
- **Issue**: https://github.com/shuvabrata/work-behavior-analytics-ai/issues/290

## Why this matters

`connectors.enabled` is a boolean that no code ever writes and no code ever reads
for a decision. It exists only to be serialized into two API responses. Worse
than dead, it is *wrong*: both seed migrations insert `enabled = false` for every
connector type, nothing ever sets it to `true`, and the ORM's `default=True`
applies only at row creation — which no code path performs. So the API reports
`"enabled": false` for GitHub, Jira and Confluence while those connectors are
configured and scanning on a schedule. A maintainer reading that field, or a
future UI binding to it, is misled.

Removing it also removes a fourth overlapping signal for "is this connector
usable" — `status = 'coming_soon'`, `scan_interval_hours IS NULL`, and a missing
registry `producer_container` already cover that ground, and all three are
maintained. The column is the only one that is not.

**Do not re-implement it as a kill switch as part of this plan.** That is a
different, larger feature with partial enforcement (it could not stop a manually
invoked `docker compose run github-producer`) and precedence rules against the
per-item flags. This plan deletes dead weight; it does not build the feature the
column was meant to serve.

## Current state

### The column, its model field, and its only readers

- `src/app/db/models/connector.py` — the `Connector` ORM model. Line 18 is the
  column:

  ```python
  enabled: Mapped[bool] = mapped_column(Boolean, default=True)
  ```

- `src/app/api/connectors/v1/model.py` — API models. `ConnectorStatus` begins at
  line 83; line 87 is the field to remove:

  ```python
  class ConnectorStatus(BaseModel):
      connector_type: str
      display_name: str
      status: str
      enabled: bool          # <-- line 87, remove this line
      config: Optional[Dict[str, Any]] = None
      last_tested_at: Optional[datetime] = None
      last_test_error: Optional[str] = None
      scan_interval_hours: Optional[int] = None

      model_config = ConfigDict(from_attributes=True)
  ```

- `src/app/api/connectors/v1/service.py` — the only two reads in the entire
  repository. Line 393 in `list_connectors()`:

  ```python
                  "connector_type": connector.connector_type,
                  "display_name": meta["display_name"],
                  "status": connector.status,
                  "enabled": connector.enabled,      # <-- line 393, remove
                  "config": _normalize_connector_config(connector.connector_type, connector.config),
  ```

  and line 417 in `get_connector()`, in an otherwise identical dict:

  ```python
              "status": connector.status,
              "enabled": connector.enabled,          # <-- line 417, remove
              "config": _normalize_connector_config(
  ```

  Both are passthroughs: the value is copied into the response dict and nothing
  downstream consumes it.

### The confirmation that it is never written

`src/app/api/connectors/v1/query.py` — the whole DB-access layer for connectors —
contains zero references to `enabled`. The only writer of the `connectors` table
is `update_connector_config` (sets `config`), `update_connector_status` (sets
`status`, `last_test_error`, `last_tested_at`), and `upsert_config_item` /
`delete_config_item` (which touch the per-connector-type config tables, not
`connectors`). No `Connector(...)` construction and no `setattr(connector, ...)`
exists anywhere in `src/`, `tests/` or `scripts/`.

### The scheduler does not use it

`src/app/scheduler.py` line 110 selects on the interval only:

```python
    stmt = select(Connector).where(
        Connector.scan_interval_hours.isnot(None),
    )
```

The `Connector.enabled.is_(True)` clause was deleted in `cc40b461` ("Phase 4 UI
changes", 2026-09-15). The module docstring at line 27 still says "For each
enabled connector", which is now stale wording.

### A unit test pins the dead behavior

`tests/test_scheduler.py` — the helper at lines 43-53 carries an `enabled`
parameter:

```python
def _make_connector(
    connector_type: str = "github",
    enabled: bool = True,
    scan_interval_hours: int | None = 24,
) -> MagicMock:
    """Build a mock Connector with the attributes the scheduler reads."""
    c = MagicMock()
    c.connector_type = connector_type
    c.enabled = enabled
    c.scan_interval_hours = scan_interval_hours
    return c
```

and lines 172-190 hold the test whose only purpose is the removed column:

```python
    @pytest.mark.asyncio
    async def test_disabled_connector_still_due(self, mock_db):
        """enabled=False does NOT prevent a scan — the enabled flag is ignored.

        The scheduler only keys off ``scan_interval_hours``. A disabled
        connector with an interval and no scan history is still due.
        """
        connector = _make_connector(
            connector_type="github",
            scan_interval_hours=24,
            enabled=False,
        )
        ...
        assert due == [("github", "producer_container")]
```

The class docstring at line 126 ("Due-check logic for each enabled connector
with a schedule.") also uses the word.

### The design doc records the decision

`docs/design/scan-scheduler-design.md` line 28 is decision-table row 10, and
line 44 restates it in the tick loop:

```
| 10 | `enabled` flag | Ignored — the scheduler keys only off `scan_interval_hours` | The `enabled` flag is unused in practice; connectors default to `enabled=False` yet still need scheduled scans |
| 11 | Multi-instance safety | `scheduler_lease` table — distributed leader election via Postgres `UPDATE` | Resilient; automatic failover when the leader dies |
```

```
2. **Selects schedulable connectors** — connectors with a non-null
   `scan_interval_hours`. The `enabled` flag is not considered.
```

Once the column is gone, row 10 documents a column that no longer exists and
line 44's second sentence refers to nothing.

### ⚠️ The `enabled` you must NOT touch

There are **six other unrelated `enabled` concepts** in this codebase. A
find-and-replace on the word will break working features. Specifically, all of
the following are **correct and must be left exactly as they are**:

1. **Per-item `enabled`** on the config tables (`github_configs.enabled`,
   `jira_configs.enabled`, …) — live, and read by the producers to skip disabled
   items. Surfaces in `src/app/api/connectors/v1/model.py` as the `enabled: bool`
   field on every `*ConfigItemRequest` (lines 30, 37, 43, 49, 58, 64, 69, 80) and
   every `*ConfigItem` (lines 105, 117, 128, 139, 153, 164, 174, 190); in
   `service.py`'s `REQUEST_FIELDS` / `RESPONSE_FIELDS` (lines 43-109), in
   `update_config_item_status` (lines 549-554), and in `router.py:200`.
2. **The Atlassian MCP `enabled` key inside the `connectors.config` JSONB** —
   a different thing entirely, despite sharing the column's table. Used at
   `service.py:26` (`CONNECTOR_CONFIG_ALLOWED_FIELDS["atlassian_mcp"]`),
   `service.py:266-288` (validation), `src/ui/pages/connectors/components/config_forms.py:271`
   (the form checkbox), `src/ui/pages/connectors/components/tooltips.py:49`, and
   consumed at runtime by `src/app/ai_agent/mcp_integration/atlassian_config_loader.py:110`
   and `tool_executor.py:56`.
3. **The UI config-item toggle** — `src/ui/pages/connectors/callbacks.py` lines
   547, 702, 1376-1436 (`config-enabled-switch` → `PATCH /configs/{id}/status`).
4. **MCP manager flags** — `atlassian_enabled` / `github_enabled` in
   `src/app/ai_agent/mcp_integration/client_manager.py` and `tool_executor.py`.
5. **Producer per-item checks** — `src/connectors/producers/github/main.py:78`,
   `jira/main.py:1308`, `confluence/main.py:846`.
6. **Unrelated subsystems** — `src/ui/pages/settings/user_management/**` (app
   user accounts) and `src/app/settings.py` / runtime settings.

**Never edit an applied Alembic migration.** `2026_03_15_2049-31c15cb26b13_add_connectors_schema.py`,
`2026_03_15_2052-5c6a3b1f9e7d_seed_connectors.py` and
`2026_04_25_1200-c4f3a8b7d912_seed_mcp_connectors.py` mention `connectors.enabled`.
They are historical records of the schema as it was built; changing them breaks
checksums on any database that already ran them.

### Repo conventions that apply

- Migrations: `src/app/alembic/versions/`, hand-written or autogenerated, one
  revision per schema change, `down_revision` chaining to the current head. The
  closest exemplar is `2026_10_26_1200-b3f7c1a9d204_drop_projects_table.py` —
  a small drop with a docstring explaining *why* and a `downgrade()` that
  recreates what was removed.
- Alembic config is `src/app/alembic.ini`; run migrations from `src/app`.
- Code style: full type annotations on every parameter and return (`mypy` runs
  strict). Default to **no comments**; comments explain *why* only. Never
  narrate a change ("removed the enabled flag") in code or docstrings.
- Pylint must hold a repo-wide score ≥ 10.0.
- Design docs must not cite `file:line` and must not reference plan numbers.

## Commands you will need

Run from the repo root. Activate the virtualenv first: `source .venv/bin/activate`.
`PYTHONPATH=src` is required for anything importing app code (pytest.ini sets it
for tests).

| Purpose | Command | Expected on success |
|---|---|---|
| Backing services | `docker compose up -d postgres` | postgres healthy |
| Current migration head | `cd src/app && alembic heads` | exactly one head, `04d7fde989ed` |
| Apply migrations | `cd src/app && alembic upgrade head` | exit 0 |
| Roll back one revision | `cd src/app && alembic downgrade -1` | exit 0 |
| Column is gone | `docker compose exec -T postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "\d connectors"` | no `enabled` row in the column list |
| Unit tests | `pytest -m unit tests -q` | all pass |
| Scheduler tests | `pytest -m unit tests/test_scheduler.py -q` | all pass |
| Typecheck | `mypy src/` | exit 0, no errors |
| Lint | `pylint src --score=y` | score ≥ 10.0 |
| Security scan | `bandit -c .bandit.yml -r src/ -lll` | no High findings |

**Note on the migration command**: do **not** run `alembic revision --autogenerate`
for this change. Autogenerate compares the whole metadata against the live
database and will capture unrelated drift as extra operations in your migration.
Hand-write the revision using the content given in step 4.

**Note on the spec-freshness CI gate**: it covers only
`docs/design/spec-activity-signal.md` and the `ActivitySignal` models. This plan
does not touch them, so the gate is not triggered. No generator run is needed.

## Scope

**In scope** (the only files you should modify):

- `src/app/db/models/connector.py` — remove the `enabled` column
- `src/app/api/connectors/v1/model.py` — remove `ConnectorStatus.enabled`
- `src/app/api/connectors/v1/service.py` — remove the two passthrough dict entries
- `src/app/scheduler.py` — one-word docstring correction
- `tests/test_scheduler.py` — drop the `enabled` helper parameter and the
  `test_disabled_connector_still_due` test
- `docs/design/scan-scheduler-design.md` — remove decision row 10, renumber, and
  drop the stale sentence
- `src/app/alembic/versions/2026_11_22_1200-d4e5f6a7b8c9_drop_connectors_enabled.py`
  (create)

**Out of scope** (do NOT touch, even though they look related):

- Every `enabled` listed in the "⚠️ The `enabled` you must NOT touch" section
  above — the per-item flags, the Atlassian MCP JSONB key, the UI config-item
  toggle, the MCP manager flags, the producer checks, the user-management page.
- All existing files under `src/app/alembic/versions/` — applied migrations are
  immutable.
- `docs/project-plan/connectors-page-implementation.md` — this mentions the
  column in its schema tables and its seed-SQL snippet, but it is a dated
  implementation plan (its own header reads "Created: March 15, 2026") recording
  what was built at that time, not a living design reference. Rewriting its
  checklists and SQL would falsify that record. **Leave it.** See Maintenance
  notes for the follow-up decision.
- `src/ui/**` — the UI never read the connector-level field, so no UI change is
  needed. Do not add or remove anything there.
- The public response shape of any endpoint other than the removal of the
  `enabled` key itself.

## Git workflow

- Branch: `drop-connectors-enabled` (off the current `main`).
- **One commit for the whole change** is appropriate here — it is a single
  atomic removal, and splitting the code removal from the migration would leave
  an intermediate state where the ORM and the schema disagree.
- Commit message style is a plain imperative sentence, matching
  `git log --oneline` (e.g. `Activity timeline backend (#323)`). Suggested:
  `Drop the unused connectors.enabled column (#290)`
- **Do NOT push and do NOT open a PR.** Leave the work on the branch and report.

## Steps

### Step 1: Remove the field from the code

Make these five edits. Do them all before running anything — the codebase is
consistent only when all five are done together.

1. `src/app/db/models/connector.py` — delete line 18:
   `enabled: Mapped[bool] = mapped_column(Boolean, default=True)`.
   If `Boolean` becomes an unused import in this file, remove it from the
   `from sqlalchemy import ...` line. (Check: the file also uses `DateTime`,
   `Integer`, `String`. `Boolean` is used only by this column, so it does become
   unused.)

2. `src/app/api/connectors/v1/model.py` — delete the line `enabled: bool` from
   inside `ConnectorStatus` (currently line 87). Delete **only** that one line —
   the other `enabled: bool` occurrences in this file belong to the per-item
   config models and stay.

3. `src/app/api/connectors/v1/service.py` — delete `"enabled": connector.enabled,`
   from the dict in `list_connectors()` (currently line 393) and the identical
   line from the dict in `get_connector()` (currently line 417). Two lines total.

4. `src/app/scheduler.py` — in the module docstring, change
   `For each enabled connector with ``scan_interval_hours IS NOT NULL``:`
   to
   `For each connector with ``scan_interval_hours IS NOT NULL``:`
   Nothing else in this file changes.

5. `tests/test_scheduler.py` — remove the `enabled: bool = True,` parameter and
   the `c.enabled = enabled` assignment from `_make_connector` (lines 43-53),
   and delete the whole `test_disabled_connector_still_due` method (lines
   172-190). Leave the class docstring's wording alone if it reads naturally
   without the field; if it does not, change "for each enabled connector with a
   schedule" to "for each connector with a schedule". Do not delete any other
   test.

**Verify**:
```
grep -rn "connector\.enabled\|Connector\.enabled" src/ tests/
```
→ **no matches**. (This is the exact grep from issue #290 and is the primary
done signal for the code half.)

```
grep -c '"enabled": connector' src/app/api/connectors/v1/service.py
```
→ `0` (it is `2` before this change — the two passthroughs). Do **not** use a
broader pattern such as `grep '"enabled"' src/app/api/connectors/v1/service.py |
grep -c "connector"`: that returns `1` even after a correct edit, because the
per-item write at the end of the file
(`... {"enabled": enabled})`) also contains the substring `connector`, and it
must be kept. (This confirms the two passthroughs are gone while the per-item
`"enabled"` entries in `REQUEST_FIELDS` / `RESPONSE_FIELDS` remain.)

```
pytest -m unit tests -q && mypy src/ && pylint src --score=y
```
→ tests pass, mypy exit 0, pylint ≥ 10.0.

> **Beware of the `rtk` grep proxy**: it has been observed to return a false `0`
> for `grep -c` and for brace-style patterns. If any of the greps above returns
> an unexpected result, re-run it via `rtk proxy grep ...` (or plain
> `/usr/bin/grep`) before concluding anything.

### Step 2: Create the migration

Create
`src/app/alembic/versions/2026_11_22_1200-d4e5f6a7b8c9_drop_connectors_enabled.py`
with exactly this content:

```python
"""drop connectors enabled

Revision ID: d4e5f6a7b8c9
Revises: 04d7fde989ed
Create Date: 2026-11-22 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd4e5f6a7b8c9'
down_revision: Union[str, Sequence[str], None] = '04d7fde989ed'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Drop the unused ``connectors.enabled`` column."""
    op.drop_column('connectors', 'enabled')


def downgrade() -> None:
    """Restore the ``connectors.enabled`` column."""
    op.add_column(
        'connectors',
        sa.Column('enabled', sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.alter_column('connectors', 'enabled', server_default=None)
```

The `server_default=sa.false()` in `downgrade()` is required: the original column
was `nullable=False` with no server default, so re-adding it to a populated table
needs a value for existing rows. The second statement then drops the default so
the restored schema matches the original exactly.

**Verify**:
```
cd src/app && alembic heads
```
→ exactly one head, `d4e5f6a7b8c9`.

```
cd src/app && alembic upgrade head
```
→ exit 0, applies `04d7fde989ed -> d4e5f6a7b8c9`.

```
docker compose exec -T postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "\d connectors"
```
→ the column list contains `connector_type`, `status`, `config`, `last_tested_at`,
`last_test_error`, `created_at`, `updated_at`, `scan_interval_hours` — and **no
`enabled`**.

Then confirm the downgrade works, since a broken `downgrade()` is a latent
deploy hazard:
```
cd src/app && alembic downgrade -1 && alembic upgrade head
```
→ both exit 0, and re-running the `\d connectors` check shows `enabled` absent
again after the re-upgrade.

### Step 3: Sweep the design doc

Edit `docs/design/scan-scheduler-design.md`:

1. Delete decision-table row 10 (the `enabled` flag row, currently line 28) and
   renumber the following row from `| 11 |` to `| 10 |`. The table then runs
   1-10 with no gap.
2. In the tick loop's step 2 (currently line 44), the text reads:

   ```
   2. **Selects schedulable connectors** — connectors with a non-null
      `scan_interval_hours`. The `enabled` flag is not considered.
   ```

   Change it to:

   ```
   2. **Selects schedulable connectors** — connectors with a non-null
      `scan_interval_hours`.
   ```

Do not add any sentence explaining the removal. The doc should read as though the
flag was never part of the design; state the fact, do not narrate the change. Do
not reference this plan's number anywhere in the doc.

**Verify**:
```
grep -n "enabled" docs/design/scan-scheduler-design.md
```
→ **no matches**.

### Step 4: Full gate

**Verify**:
```
pytest -m unit tests -q
mypy src/
pylint src --score=y
bandit -c .bandit.yml -r src/ -lll
```
→ unit tests all pass; `mypy` exit 0 with no errors; `pylint` score ≥ 10.0;
`bandit` reports no High-severity findings.

## Test plan

- **No new tests.** This plan removes a field; the behavior it could regress is
  "the connector list/detail response no longer carries `enabled`", which the
  existing response-model validation already enforces (FastAPI validates the
  returned dict against `ConnectorStatus`, so a leftover key would be dropped and
  a missing required field would 500).
- **One test is deleted**: `tests/test_scheduler.py::TestGetDueConnectors::test_disabled_connector_still_due`.
  Its premise — that `enabled=False` does not prevent a scan — becomes
  meaningless once the column is gone. The property it was protecting ("the
  scheduler keys only off `scan_interval_hours`") remains covered by
  `test_no_scan_history_is_due`, `test_within_interval_is_not_due`, and
  `test_null_interval_skipped`, which exercise the same code path through
  the interval alone.
- **Do not add a test asserting the absence of `enabled` in the response.** A
  test that greps a response dict for a key that the schema forbids adds no
  protection; the model definition is the contract.
- The `server`-marked suites (`tests/test_connectors_api.py`) are skipped by
  default (`pytest.mark.skip(reason="Disabled: modifies connector DB state")`)
  and assert only per-item `enabled`, so they need no change. If you choose to
  run them against a live stack, they must still pass unchanged.

## Done criteria

Machine-checkable. ALL must hold:

- [ ] `grep -rn "connector\.enabled\|Connector\.enabled" src/ tests/` returns no matches
- [ ] `grep -rn "enabled" docs/design/scan-scheduler-design.md` returns no matches
- [ ] `cd src/app && alembic heads` shows the single head `d4e5f6a7b8c9`
- [ ] `cd src/app && alembic upgrade head` then `alembic downgrade -1` then
      `alembic upgrade head` all exit 0
- [ ] `\d connectors` in psql lists no `enabled` column
- [ ] `pytest -m unit tests -q` exits 0
- [ ] `mypy src/` exits 0
- [ ] `pylint src --score=y` reports ≥ 10.0
- [ ] `bandit -c .bandit.yml -r src/ -lll` reports no High findings
- [ ] `git status` shows no modified file outside the Scope list
- [ ] `grep -c "enabled" src/app/api/connectors/v1/model.py` returns `17` (it is
      `18` before this change — the per-item fields survive and exactly one line
      was removed; this is the guard against over-deletion)
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report back (do not improvise) if:

- The code at the locations in "Current state" does not match the excerpts — in
  particular if `connector.enabled` has gained a *third* read site, or if a write
  path (`connector.enabled = ...`, `setattr(connector, ...)`, or raw SQL) now
  exists. Either would mean the column is no longer dead and this plan's premise
  is false.
- `alembic heads` shows more than one head, or a head other than `04d7fde989ed`.
  Another migration has landed; re-chain your `down_revision` to the new head
  rather than reverting anything.
- `pytest -m unit tests -q` fails in a test this plan does not name. Do not
  delete or edit the failing test to make the gate green — report it.
- Removing the field turns out to require a change to any file in the
  "Out of scope" list, or to any `enabled` in the "must NOT touch" list.
- The `alembic downgrade -1` step fails. A migration whose downgrade does not run
  is not shippable in this repo.

## Maintenance notes

For the human/agent who owns this code after the change lands:

- **The API response for `GET /api/v1/connectors/` and
  `GET /api/v1/connectors/{type}` loses the `enabled` key.** It is a
  breaking change to a documented-but-unused response field. The only consumer is
  the app's own UI, which never read it (`render_connectors` in
  `src/ui/pages/connectors/callbacks.py` reads `status` only). If any external
  client is later found to depend on it, the correct fix is to re-derive it from
  `status`, not to restore an unmaintained column.
- **The connectors page still reports connector health through `status`**, which
  `_refresh_connector_status()` recomputes on every config change. That is the
  maintained signal; it stays.
- **If a real connector-level kill switch is ever wanted**, it is a new feature,
  not a revival of this column. It must gate the scheduler, the manual
  `POST /api/v1/commands/` scan path, *and* test-connection, and it must define
  precedence against the per-item `enabled` flags. It cannot gate a directly
  invoked producer container (`docker compose run github-producer`), so its
  enforcement is inherently partial — document that limitation rather than
  implying it is total.
- **Deferred, for the operator to decide**:
  `docs/project-plan/connectors-page-implementation.md` still describes the
  column in its schema table and its seed-SQL snippet. It was left untouched
  because it is a dated implementation plan rather than a living reference. If
  this repo treats `docs/project-plan/` as living documentation rather than an
  archive, that file needs a matching sweep — but that is a documentation-policy
  call, not part of this change.
- **What a reviewer should scrutinize**: that the diff touches exactly the seven
  in-scope files, and that no `enabled` belonging to the per-item config models,
  the Atlassian MCP JSONB config, or the user-management page was removed. The
  `model.py` grep in the Done criteria exists precisely to catch that.

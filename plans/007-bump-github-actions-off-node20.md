# Plan 007: Bump `actions/checkout` and `actions/setup-python` off the deprecated Node 20 runtime

> **Executor instructions**: Follow this plan. Run every verification command and
> confirm the expected result. If a STOP condition occurs, stop and report — do
> not improvise. When done, update the status row in `plans/README.md` — unless a
> reviewer dispatched you and told you they maintain the index.
>
> **Drift check (run first)**: `grep -rn "uses: actions/\(checkout\|setup-python\)@" .github/workflows/`
> Expect six `actions/checkout@v4` and six `actions/setup-python@v5`, and no
> other versions of either. If the counts differ, the workflows have changed since
> this plan was written — STOP and report.

## Execution record — 2026-11-13

The bump was applied in the working tree on `feature/bootstrap-pwds`;
uncommitted.

### Verification evidence

Re-run by the reviewer against the edited files:

- `grep -rn "uses: actions/\(checkout\|setup-python\)@" .github/workflows/` →
  twelve lines: six `actions/checkout@v5`, six `actions/setup-python@v6`.
- `actions/checkout@v4` → 0 occurrences; `actions/setup-python@v5` → 0.
- `git diff --numstat` → `.github/workflows/pr_checks.yml` 10/10,
  `.github/workflows/security.yml` 2/2 — 12 changed lines in all. The whole diff
  is the two version suffixes; no line changed in any other way.
- **Plan error found during execution, corrected above:** Step 6's first draft
  predicted "6 and 6" insertions/deletions. That counted only one of the two
  actions. Twelve is correct (6 `checkout` + 6 `setup-python`). The executor
  reported the discrepancy rather than bending the result to match — the right
  call.
- Unchanged and confirmed so: `runs-on: ubuntu-latest` → 6,
  `python-version: "3.14"` → 6, `github/codeql-action/upload-sarif@v3` → 2.
- Both files parse as YAML with their job lists intact (`pr_checks.yml` →
  `pytest-unit`, `check-spec-freshness`, `pylint`, `mypy`, `security-bandit`;
  `security.yml` → `security-bandit`).

### Done criterion 10 is not load-bearing

The plan's final check is `pytest -m unit tests -q`. Neither file touched by this
plan is read by any test: the change is two version strings in CI configuration.
A green suite here cannot fail for a reason connected to the change, and a red one
could not implicate it. `git diff` restricted to the two workflow files is the
stronger and cheaper evidence, and it is above. The criterion is a template
artefact, not a gate — do not treat its absence as an unverified result.

## Status

- **Priority**: P3
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: dx
- **Planned at**: commit `c327ce0b`, 2026-11-13

## Why this matters

GitHub prints this on every workflow run:

```
Node.js 20 is deprecated. The following actions target Node.js 20 but are being
forced to run on Node.js 24: actions/checkout@v4, actions/setup-python@v5.
```

Node 20 is past end of life on GitHub's runners; the actions still declare it, and
the runner forces them onto Node 24. It is a warning today, but a JS action whose
declared runtime the runner no longer supports is exactly the class of change that
stops being a warning. Bumping the two majors that already target `node24` removes
the warning with no change in behaviour.

Measured for this plan (via the GitHub API, reading each action's `action.yml`
`runs.using`):

| Ref | `runs.using` |
|---|---|
| `actions/checkout@v4` | `node20` ← in use |
| `actions/checkout@v5` | `node24` |
| `actions/setup-python@v5` | `node20` ← in use |
| `actions/setup-python@v6` | `node24` |

`v5` and `v6` are chosen deliberately as the **smallest** majors that run on
`node24`: `checkout@v6` adds a credential-persistence change and `checkout@v7`
adds fork-checkout blocking plus an ESM rewrite; `setup-python@v7` removes the
`pip-install` input. None of those is wanted here — this plan is a runtime bump,
not a feature upgrade.

`github/codeql-action/upload-sarif@v3` is **not** in scope: its `action.yml` uses
`using: composite`, so it has no Node runtime of its own, which is why the warning
does not name it.

## Current state

Both workflow files pin the same two actions. `grep -c` gives:

| File | `actions/checkout@v4` | `actions/setup-python@v5` |
|---|---|---|
| `.github/workflows/pr_checks.yml` | 5 | 5 |
| `.github/workflows/security.yml` | 1 | 1 |
| **total** | **6** | **6** |

`pr_checks.yml` uses them in five jobs (`pytest-unit`, `check-spec-freshness`,
`pylint`, `mypy`, `security-bandit`); `security.yml` in one
(`security-bandit`). Every use is a bare `uses:` with no `with:` inputs on
checkout:

```yaml
      - name: Checkout
        uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.14"
```

`setup-python` is always used with `python-version: "3.14"` and nothing else. The
`pip-install` input removed in `v7` is not used, and Python 3.14 is supported by
`v6`.

### Repo conventions that apply

- Workflow YAML is two-space indented; every step keeps its `name:`.
- `runs-on: ubuntu-latest` stays exactly as it is — see out-of-scope.
- Never commit, push, or create a branch.

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Count check | `grep -rc "uses: actions/checkout@" .github/workflows/` | all `v5` |
| Count check | `grep -rc "uses: actions/setup-python@" .github/workflows/` | all `v6` |
| YAML validity | see verification below | both files parse; job names unchanged |
| Unit tests | `TEST_SUITE_WBA_ADMIN_USERNAME=app-admin TEST_SUITE_WBA_USER_USERNAME=app-user PYTHONPATH=src pytest -m unit tests -q` | exit 0 |

The two usernames must be supplied in the environment because no `.env` exists in
CI and the unit suite reads those variables through
`tests/auth_helpers.realm_username()`.

## Scope

**In scope** (the only files you may modify):

- `.github/workflows/pr_checks.yml`
- `.github/workflows/security.yml`

**Out of scope** (do NOT touch, even though they look related):

- **`runs-on: ubuntu-latest`** — stays. GitHub's notice about `ubuntu-latest`
  moving to Ubuntu 26 is informational; the runner image migrates on GitHub's
  schedule and this repo deliberately follows the default rather than pinning
  `ubuntu-24.04`. Do not change any `runs-on:` value.
- `python-version: "3.14"` — stays. It is supported by `setup-python@v6`.
- `github/codeql-action/upload-sarif@v3` — a composite action with no Node runtime
  of its own; the warning does not name it and bumping it is a separate decision
  with its own config implications.
- Any `with:` inputs, step `name:`s, job names, `env:` values, `on:` triggers,
  `permissions:`, and step ordering. This plan changes version strings only.
- `plans/` (all of it), `.env*`, `src/`, `tests/`, `scripts/`, `deploy/`.

## Git workflow

- Work in the current working tree, on the current branch. No branch, no
  worktree, no commits.
- Do NOT run `git commit`, `git push`, `git checkout`, `git stash`,
  `git restore`, `git reset`, or `git clean`.
- Do NOT run any `docker` command.

## Implementation

Replace every occurrence in both files:

| From | To |
|---|---|
| `uses: actions/checkout@v4` | `uses: actions/checkout@v5` |
| `uses: actions/setup-python@v5` | `uses: actions/setup-python@v6` |

Six of each, across the two files. Nothing else on those lines changes — the
indentation and the `uses:` prefix stay as they are. Do not reformat the files.

**Verify**:

1. `grep -rn "uses: actions/\(checkout\|setup-python\)@" .github/workflows/` →
   twelve lines, all reading `@v5` (checkout) or `@v6` (setup-python), with no
   `@v4` / `@v5`-for-setup-python remaining.
2. `grep -c "actions/checkout@v5" .github/workflows/pr_checks.yml` → `5`;
   `.github/workflows/security.yml` → `1`.
3. `grep -c "actions/setup-python@v6" .github/workflows/pr_checks.yml` → `5`;
   `.github/workflows/security.yml` → `1`.
4. `grep -c "actions/checkout@v4\|actions/setup-python@v5" .github/workflows/pr_checks.yml .github/workflows/security.yml` → `0` for each file.
5. Both files still parse and keep their jobs:

   ```bash
   .venv/bin/python -c "
   import yaml, pathlib
   for f in ('.github/workflows/pr_checks.yml', '.github/workflows/security.yml'):
       d = yaml.safe_load(pathlib.Path(f).read_text())
       print(f, list(d['jobs']))
   "
   ```

   Expected: `pr_checks.yml` →
   `['pytest-unit', 'check-spec-freshness', 'pylint', 'mypy', 'security-bandit']`;
   `security.yml` → `['security-bandit']`. (If PyYAML is unavailable, report that
   and rely on the greps plus `git diff` as evidence.)
6. Confirm nothing else moved:
   `git diff --stat` → only the two workflow files, with **12 insertions and 12
   deletions** across them (`pr_checks.yml` 10/10, `security.yml` 2/2). Twelve is
   the correct total: six `checkout` lines plus six `setup-python` lines each
   change one line in and one line out, so an earlier draft of this plan that said
   "6 and 6" was undercounting by half. Insertions must equal deletions.
   `git diff -U0` should show only lines whose sole change is the version suffix.

## Test plan

No test is added — a workflow file has no unit-testable behaviour. The
verification that matters is the count and YAML checks above, plus the CI run on
the next push, where the deprecation notice should no longer appear in the
`pytest-unit` job output. A reviewer should confirm the version strings and that
`runs-on` and `python-version` are untouched.

## Done criteria

- [ ] `grep -rc "actions/checkout@v4" .github/workflows/` → `0` for both files
- [ ] `grep -rc "actions/setup-python@v5" .github/workflows/` → `0` for both files
- [ ] `grep -c "actions/checkout@v5"` → 5 in `pr_checks.yml`, 1 in `security.yml`
- [ ] `grep -c "actions/setup-python@v6"` → 5 in `pr_checks.yml`, 1 in `security.yml`
- [ ] Both files parse as YAML and their job name lists are unchanged
- [ ] `grep -c "runs-on: ubuntu-latest" .github/workflows/pr_checks.yml .github/workflows/security.yml` → unchanged from before the edit (5 and 1)
- [ ] `grep -c 'python-version: "3.14"' .github/workflows/pr_checks.yml .github/workflows/security.yml` → unchanged (5 and 1)
- [ ] `pytest -m unit tests -q` exits 0 with the two usernames supplied
- [ ] Only the two workflow files are modified

## STOP conditions

Stop and report (do not improvise) if:

- The drift check finds a version other than `@v4` (checkout) or `@v5`
  (setup-python) — for instance if Dependabot has already bumped them, in which
  case this plan is obsolete rather than wrong.
- A `uses:` line carries a `#` comment or a SHA instead of a major tag; those need
  a deliberate decision, not a search-and-replace.
- Any `actions/checkout` step turns out to use `with:` inputs — `checkout@v5`
  changes credential persistence in `v6`, and the upgrade path would then deserve a
  second look rather than a blind bump.
- The change appears to require editing a file outside the two workflows.
- Any command would create a branch, a commit, or change container state.

## Maintenance notes

- **`v5` and `v6` are a floor, not a destination.** They are the smallest majors
  on `node24`. Moving to `checkout@v7` / `setup-python@v7` is a separate,
  deliberate change: `checkout@v7` blocks checking out fork PRs under
  `pull_request_target` and `workflow_run` (this repo triggers on `pull_request`,
  so it is unaffected today, but a future workflow using those triggers would be),
  and `setup-python@v7` removes the `pip-install` input.
- **The `ubuntu-latest` notice is unresolved by design.** GitHub is migrating that
  label to Ubuntu 26; this repo chooses to follow the default. If a runner-image
  change ever breaks CI, the fix is to pin `runs-on: ubuntu-24.04` in all six
  jobs — one string, six places, and this note is the record that it was a
  deliberate choice rather than an oversight.
- **Dependabot may take this over.** A future bump appearing as a Dependabot PR is
  expected; the count greps above are the cheap check that it touched every job
  rather than some of them.
- **A reviewer should scrutinize** that all six uses of each action moved — a
  partial bump leaves the warning in place, since one stale action is enough to
  emit it — and that `runs-on` and `python-version` are byte-identical to before.
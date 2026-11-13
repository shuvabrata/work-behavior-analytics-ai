# Plan 006: Attach `UPDATE_PASSWORD` explicitly so the seeded users must change their password at first login

> **Executor instructions**: Follow this plan. Run every verification command and
> confirm the expected result. If a STOP condition occurs, stop and report — do
> not improvise. When done, update the status row in `plans/README.md` — unless a
> reviewer dispatched you and told you they maintain the index.
>
> **Drift check (run first)**: `grep -n "\"temporary\": true\|requiredActions" deploy/keycloak/realm-wba.json.template`
> Expect exactly two `"temporary": true` lines and **no** `requiredActions` line.
> The working tree must also contain plans 004 and 005's uncommitted changes
> (`git status --porcelain` shows `realm-wba.json.template` modified).

## Execution record — 2026-11-13

The template edit was applied in the working tree on `feature/bootstrap-pwds`;
uncommitted. The re-seed is not performed and remains the operator's action.

### Verification evidence

Re-run by the reviewer:

- Render + parse: `unsubstituted: []`; `app-admin requiredActions =
  ['UPDATE_PASSWORD'] temporary = [True]`; `app-user` identical;
  `service-account-internal` and `service-account-admin-api` both
  `requiredActions = None temporary = []`.
- `grep -c '"temporary": true'` → `2`; `grep -c '"requiredActions":
  \["UPDATE_PASSWORD"\]'` → `2`.
- `docker compose config -q` → exit 0.
- `pytest -m unit tests -q` with the two usernames supplied →
  `2765 passed, 2 skipped`, matching the pre-change baseline.
- `git grep -c requiredActions -- . ':!plans'` → only
  `deploy/keycloak/realm-wba.json.template`. `entrypoint.sh`, `.env` and every
  other file are untouched by this plan; the diffs they carry are plans 004/005's.

### Not yet verifiable

`user_required_action` could not be checked until the operator re-seeded. It held
**0 rows** when the defect was found.

### Confirmed after the re-seed — 2026-11-13

The operator re-seeded (after fixing a Docker Desktop bind-mount staleness error
that had left the `keycloak` container exited; `docker compose rm -sf keycloak`
re-resolved the host path). Verified by the reviewer:

```
app-admin | (no action)        ← forced change completed in the browser
app-user  | UPDATE_PASSWORD    ← attached at import, not yet consumed
```

That is the exact two-row shape this plan predicted, and it distinguishes
attachment from consumption: the action was present at import and the browser
change cleared it for the one user who signed in. The mechanism is confirmed, not
merely assumed.

Residual state: `.env`'s two `TEST_SUITE_WBA_*_PASSWORD` values are still `FIXME`,
so the live `server` suites continue to skip until an operator records real
credentials. `auth_session` holds 2 rows (1 revoked), both username `app-admin` —
the older row's subject predates the re-seed; harmless because it is revoked.

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: LOW
- **Depends on**: plans 004 and 005 (both in the working tree, uncommitted). This
  plan corrects plan 004's core premise.
- **Category**: security
- **Planned at**: working tree on top of commit `bfa5d8f0`, 2026-11-13

## Why this matters

Plan 004 made the seeded application passwords one-time by setting
`"temporary": true` on their Keycloak credentials. That flag is ignored on
Keycloak's **realm import** path, which is exactly how this stack seeds the realm
(`kc.sh start-dev --import-realm`). The result is the opposite of the intent:
`app-admin` and `app-user` sign in with their bootstrap password and are never
asked to change it, so a credential that is written into `.env`, printed in
`INSTALL_GUIDE.md` and shared across every dev stack stays valid forever on an
account holding `admin`.

Evidence, measured on the live stack (Keycloak 26.8.1) after a clean re-seed:

```
user_required_action                                  → 0 rows
required_action_provider: "Update Password" | wba     → enabled = true
rendered realm in container: app-admin ('password', True)   → flag was present
```

A four-cell probe in throwaway realms isolated the cause:

| Path | Config | `UPDATE_PASSWORD` recorded? |
|---|---|---|
| Admin API (`kcadm create users`) | `temporary: true` only | yes |
| Admin API | `temporary: true` + `requiredActions` | yes |
| **Realm import** (`kcadm create realms -f`) | `temporary: true` only | **no** |
| **Realm import** | `temporary: true` + `requiredActions` | **yes** |

After this plan, the seeded users carry the required action, Keycloak interposes
the update-password form before issuing an auth code, and the bootstrap value
stops working once the change is completed.

## Current state

`deploy/keycloak/realm-wba.json.template` — the `"users"` array, lines 92–131.
The first user today:

```json
    {
      "username": "app-admin",
      "enabled": true,
      "emailVerified": true,
      "email": "app-admin@wba.invalid",
      "firstName": "Application",
      "lastName": "Admin",
      "realmRoles": [
        "admin",
        "user"
      ],
      "credentials": [
        {
          "type": "password",
          "value": "${APP_ADMIN_PASSWORD}",
          "temporary": true
        }
      ]
    },
```

The second user is identical apart from `"username": "app-user"`,
`"email"`, `"lastName": "User"`, a single `"user"` realm role, and
`${APP_USER_PASSWORD}`. The two `service-account-*` entries follow and carry no
`credentials` block.

Keycloak's user representation accepts a `requiredActions` array of action
**aliases**. The alias for the password-change action is `UPDATE_PASSWORD` —
exactly that spelling. `"Update Password"` (the display name) is not accepted.

The rendered realm is written by `deploy/keycloak/entrypoint.sh`, which
substitutes `${APP_ADMIN_PASSWORD}` / `${APP_USER_PASSWORD}` and aborts if any
`${...}` survives. It does not touch `requiredActions`, so nothing else changes.

### Repo conventions that apply

- JSON template: two-space indent, trailing keys in template order.
- Default to no comments. Do not narrate the change in the JSON.
- Never commit, push, or create a branch.

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Template still valid | see Step 1 | parsed JSON, 0 unsubstituted placeholders |
| Compose config valid | `docker compose config -q` | exit 0 |
| Unit tests | `TEST_SUITE_WBA_ADMIN_USERNAME=app-admin TEST_SUITE_WBA_USER_USERNAME=app-user PYTHONPATH=src pytest -m unit tests -q` | exit 0 |

The two usernames must be supplied in the environment because `.env` is not read
by the CI-shaped command and the unit suite resolves them through
`tests/auth_helpers.realm_username()` (plan 005).

## Scope

**In scope** (the only file you may modify):

- `deploy/keycloak/realm-wba.json.template`

**Out of scope:**

- `"temporary": true` on both credentials — **keep it**. It is correct and it is
  what makes the admin-API path work; this plan adds the explicit action, it does
  not replace the flag.
- The `realmRoles` arrays, `emailVerified`, `enabled`, emails, names, and the
  `service-account-*` users.
- `deploy/keycloak/entrypoint.sh` — no change. It has no list of required
  actions to update.
- `.env`, any container state, and any `docker compose` command that starts,
  stops, builds or recreates a container. `docker compose config -q` is allowed.
- Plans 004, 005, 001, 002 and `docs/project-plan/`.

## Git workflow

- Work in the current working tree, on the current branch. No branch, no
  worktree, no commits.
- Do NOT run `git commit`, `git push`, `git checkout`, `git stash`,
  `git restore`, `git reset`, or `git clean`.

## Implementation

In `deploy/keycloak/realm-wba.json.template`, add one key to **each** of the two
application users, immediately after `"lastName"` and before `"realmRoles"`:

```json
      "lastName": "Admin",
      "requiredActions": ["UPDATE_PASSWORD"],
      "realmRoles": [
```

and for `app-user`:

```json
      "lastName": "User",
      "requiredActions": ["UPDATE_PASSWORD"],
      "realmRoles": [
        "user"
      ],
```

Change nothing else. Both `"temporary": true` flags stay.

**Verify** — render with dummy values, parse, and assert the action is present on
both users and absent from the service accounts:

```bash
PYTHONPATH=src .venv/bin/python - <<'PY'
import json, re, pathlib
tpl = pathlib.Path("deploy/keycloak/realm-wba.json.template").read_text()
names = ["APP_PUBLIC_BASE_URL","KEYCLOAK_CLIENT_SECRET","KEYCLOAK_SERVICE_CLIENT_SECRET",
         "KEYCLOAK_ADMIN_CLIENT_ID","KEYCLOAK_ADMIN_CLIENT_SECRET",
         "APP_ADMIN_PASSWORD","APP_USER_PASSWORD"]
out = tpl
for n in names:
    out = out.replace("${%s}" % n, "dummy")
print("unsubstituted:", re.findall(r"\$\{[A-Z_]+\}", out))
doc = json.loads(out)
for u in doc["users"]:
    print(u["username"], "requiredActions =", u.get("requiredActions"),
          "temporary =", [c["temporary"] for c in u.get("credentials", [])])
PY
```

Expected:

```
unsubstituted: []
app-admin requiredActions = ['UPDATE_PASSWORD'] temporary = [True]
app-user requiredActions = ['UPDATE_PASSWORD'] temporary = [True]
service-account-internal requiredActions = None temporary = []
service-account-admin-api requiredActions = None temporary = []
```

Also run `docker compose config -q` → exit 0, and
`TEST_SUITE_WBA_ADMIN_USERNAME=app-admin TEST_SUITE_WBA_USER_USERNAME=app-user PYTHONPATH=src pytest -m unit tests -q` → exit 0.

## Operator action (report, do not perform)

The template change has no effect until the realm is re-seeded: `--import-realm`
is **create-only**, so an existing realm keeps its users and never re-reads the
template. Report that the operator must:

```bash
docker compose stop keycloak
docker compose exec -T postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c 'DROP DATABASE keycloak;'
docker compose exec -T postgres createdb -U "$POSTGRES_USER" -O keycloak keycloak
docker compose up -d keycloak
docker compose logs -f keycloak        # wait for "Importing realm", then healthy
```

Then verify the action attached, which is the observation that failed before this
plan:

```bash
docker compose exec -T postgres psql -U postgres -d keycloak \
  -c "SELECT ue.username, ura.required_action FROM user_required_action ura JOIN user_entity ue ON ue.id=ura.user_id;"
```

Expected: **2 rows**, both `app-admin` / `app-user` with `UPDATE_PASSWORD`. Before
this plan the same query returned 0 rows.

Then, in a private browser window at `https://localhost/app`, signing in as
`app-admin` with `APP_ADMIN_PASSWORD` must present Keycloak's update-password
form, not the application.

## Done criteria

- [ ] `grep -c '"temporary": true' deploy/keycloak/realm-wba.json.template` → `2` (unchanged)
- [ ] `grep -c '"requiredActions": \["UPDATE_PASSWORD"\]' deploy/keycloak/realm-wba.json.template` → `2`
- [ ] The render check prints `['UPDATE_PASSWORD']` for exactly `app-admin` and `app-user`, and `None` for both `service-account-*`
- [ ] `docker compose config -q` exits 0
- [ ] `pytest -m unit tests -q` exits 0 with the two usernames supplied
- [ ] Only `deploy/keycloak/realm-wba.json.template` is modified by this plan (`git status` still shows plans 004/005's files from earlier work)
- [ ] No container state changed and `.env` untouched

## Test plan

No test is added; this is realm configuration, not application behaviour, and the
application has no code path that reads `requiredActions`. The verification that
matters is the SQL query in the operator action — it is a direct observation of
the mechanism, and it is the query that returned 0 rows when the bug was found.
A reviewer should run it against the re-seeded realm, not against the template.

## STOP conditions

Stop and report (do not improvise) if:

- The drift check shows no `"temporary": true` in the template, or shows a
  `requiredActions` key already present. The first means plan 004's work is not in
  the tree; the second means someone already applied this plan.
- `"requiredActions"` is rejected during the render/parse check — for instance if
  the JSON is malformed. Do not "fix" it by moving the key elsewhere; report the
  exact error.
- You conclude a change to `entrypoint.sh` is needed. It is not: the renderer
  substitutes passwords only, and `requiredActions` contains no `${...}`.
- Applying the fix appears to require editing any file other than
  `deploy/keycloak/realm-wba.json.template`.
- Any command would create a branch, a commit, or change container state.

## Maintenance notes

- **This is the real mechanism; `temporary: true` alone is not.** Keep both. If a
  future Keycloak release starts honouring `temporary` on import, the explicit
  action is still correct and makes the intent legible in the template — the
  `temporary` flag alone is invisible in a diff of what Keycloak actually did.
- **The action alias is `UPDATE_PASSWORD`**, not the display name
  `Update Password`. A wrong spelling is silently ignored — it does not error, and
  the symptom is identical to the bug this plan fixes (no forced change). If a
  future edit changes that string, re-run the SQL check, not just the parse.
- **Re-seeding is still required after any template edit.** `--import-realm`
  creates only; it never reconciles an existing realm. Plan 004's maintenance
  notes and `IAM_ADMIN_GUIDE.md` say the same.
- **A reviewer should scrutinize** that both `temporary` flags survive, that the
  render check reports `None` for the service accounts, and — after the operator's
  re-seed — that `user_required_action` holds exactly 2 rows.
- **Historical record**: this plan exists because plan 004 asserted a Keycloak
  behaviour that does not hold on the import path. The same assertion appears in
  plan 004's "Why this matters" and in plan 005's user-facing docs; both are
  accurate only from this plan onward.
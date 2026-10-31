# Plan 062: Deliver realm changes without dropping the database, and give `wba-web` an audience

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 78a1c635..HEAD -- deploy/keycloak/realm-wba.json.template ADMIN_GUIDE.md tests/test_auth_tokens.py plans/README.md`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: MED
- **Depends on**: plans/056-*.md (blocked-to-complete), plans/055-*.md (DONE)
- **Category**: security
- **Planned at**: commit `78a1c635`, 2026-10-31
- **Design reference**: `docs/design/authn-authz-design.md`, "Realm as code" (§216)
- **Blocks**: plans/057, plans/058, and Plan D — all of which need further realm changes

## Why this matters

Login through the browser fails today. A user reaches Keycloak, enters valid
credentials, and is returned to the API with:

```json
{"detail": {"error": "login_failed",
            "message": "The token Keycloak returned could not be validated."}}
```

The API log shows the cause:

```
[ERROR] [service.py:235] Login token failed validation:
        Bearer token rejected: Token is missing the "aud" claim
```

`validate_bearer_token` (`src/app/auth/tokens.py:123`) requires an `aud` claim:

```python
options={"require": ["exp", "iss", "aud", "sub"]},
audience=settings.KEYCLOAK_CLIENT_ID,
```

But the `wba-web` client in the realm template carries **no `protocolMappers`**
at all — only `wba-internal` was given an `oidc-audience-mapper`, by plan 055.
So the interactive token has no `aud`, and every browser login fails validation.
This is a gap between 054 (a strict validator) and 055 (which gave the *service*
client an audience and explicitly declined to give `wba-web` one); plan 056 is
simply where the human login path was first exercised, so it is where the gap
surfaced.

The second problem is structural and outlives the bug. The only documented way
to apply a realm change is `ADMIN_GUIDE.md:150` — **drop the `keycloak`
database**. That works in dev because the realm is derived and holds two seeded
`dev-*` users. It does not work anywhere else: dropping that database destroys
every user, group, session and client secret in the realm, and it is a full
authentication outage. `--import-realm` is create-only (it skips a realm that
already exists — see `plans/055-service-tokens-for-producers-and-consumer.md:479`),
so the current mechanism leaves no other option. Plans 057, 058 and Plan D all
need further realm changes, so without a delivery mechanism each one re-opens
this question.

After this plan: `wba-web` tokens carry `aud=["wba-web"]`, login works, and any
future realm change is an idempotent `kcadm.sh` reconcile against the running
instance — no downtime, no data loss, one source of truth.

## Current state

### `deploy/keycloak/realm-wba.json.template` (the realm-as-code source of truth)

Two clients. The `wba-web` client (lines 15–37) — note the **absence** of any
`protocolMappers` key:

```json
    {
      "clientId": "wba-web",
      "name": "WBA Web (browser / BFF)",
      "enabled": true,
      "protocol": "openid-connect",
      "publicClient": false,
      "bearerOnly": false,
      "standardFlowEnabled": true,
      "implicitFlowEnabled": false,
      "directAccessGrantsEnabled": false,
      "serviceAccountsEnabled": false,
      "secret": "${KEYCLOAK_CLIENT_SECRET}",
      "attributes": {
        "pkce.code.challenge.method": "S256"
      },
      "redirectUris": [
        "${APP_PUBLIC_BASE_URL}/api/v1/auth/callback"
      ],
      "webOrigins": [
        "${APP_PUBLIC_BASE_URL}"
      ]
    },
```

The `wba-internal` client (line 38 onward) is the exemplar to copy — its mapper
block is at lines 50–62, and it is the **only** protocol-mapper block in the
file (`grep -c protocolMappers` → 1):

```json
      "protocolMappers": [
        {
          "name": "wba-internal-audience",
          "protocol": "openid-connect",
          "protocolMapper": "oidc-audience-mapper",
          "consentRequired": false,
          "config": {
            "included.client.audience": "wba-internal",
            "id.token.claim": "false",
            "access.token.claim": "true"
          }
        }
      ],
```

The file holds no `clientScopes` / `defaultClientScopes` (`grep -c` → 0).

### `deploy/keycloak/entrypoint.sh`

Renders the template with bash substitution, writes
`/opt/keycloak/data/import/realm-wba.json`, then execs
`kc.sh start-dev --import-realm --http-relative-path=/auth`. It fails loudly on
an unsubstituted `${...}` placeholder. **This file is not modified by this plan.**

### `docker-compose.yml` — the `keycloak` service

```yaml
    image: quay.io/keycloak/keycloak:26.8
    command: ["start-dev", "--import-realm"]
    entrypoint: ["/opt/keycloak/entrypoint.sh"]
    environment:
      KC_HOSTNAME: ${EXTERNAL_BASE_URL:-https://localhost}/auth
      KC_HOSTNAME_ADMIN: http://127.0.0.1:8080/auth
      KC_PROXY_HEADERS: xforwarded
      KC_HTTP_ENABLED: "true"
      KC_HTTP_RELATIVE_PATH: /auth
      ...
      DEV_KEYCLOAK_ADMIN_PASSWORD: ${DEV_KEYCLOAK_ADMIN_PASSWORD}
```

**No host port is published.** `ADMIN_GUIDE.md` documents adding
`ports: ["127.0.0.1:8080:8080"]` to reach the console, but `kcadm.sh` does not
need that — it runs **inside** the container and reaches
`http://localhost:8080/auth` directly.

### Tooling verified present (recon, 2026-10-31)

- `/opt/keycloak/bin/kcadm.sh` exists in the running image and `--help` executes.
  It is a `#!/bin/sh` script, mode `-rwxrwxr-x`.
- **`jq` is NOT installed in the image** (`command -v jq` → absent). Any payload
  transformation must happen on the **host** (which has `jq`) or use
  `kcadm.sh get` / `update` with a file payload.
- `kcadm.sh` supports `--password:env <VARNAME>`, which avoids putting a secret
  in the process arguments.

### `.env` variables this plan uses

`DEV_KEYCLOAK_ADMIN_PASSWORD` (bootstrap admin), and the three render-time
secrets `KEYCLOAK_CLIENT_SECRET`, `KEYCLOAK_SERVICE_CLIENT_SECRET`,
`DEV_WBA_ADMIN_PASSWORD`, `DEV_WBA_USER_PASSWORD`. **Never print, echo, or
commit any of these values.** This plan references variable *names* only.

### `tests/test_auth_tokens.py`

Exists, is `pytestmark = pytest.mark.unit`-marked, and covers the validator's
claim checks. The realm-carrying claim (`aud` present) is checked against
**synthetic tokens**, which is exactly why this bug reached a browser: the
interactive token's mapper is realm configuration, and no test asserted the
realm produces one.

### Repo conventions that apply

- Shell scripts live in `scripts/`, are `bash` with `set -euo pipefail`, and are
  executable (`-rwxr-xr-x`). Exemplar: `scripts/init-configs.sh`.
- Plans/paths in docs are repo-relative.
- **Do not commit or push unless the operator asks.**

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Container-up check | `docker compose ps keycloak` | `Up ... (healthy)` |
| kcadm present | `docker exec wba-ai-keycloak test -x /opt/keycloak/bin/kcadm.sh` | exit 0 |
| Realm export | `docker exec wba-ai-keycloak /opt/keycloak/bin/kcadm.sh get realms/wba` | JSON |
| Template renders | `bash -n scripts/keycloak-realm-reconcile.sh` | exit 0 |
| Unit tests | `pytest -m unit tests -q` | ≥ baseline, 0 fail |
| Typecheck | `mypy src/` | exit 0 |
| Lint | `pylint src --score=y` | ≥ 9.0 |
| Security scan | `bandit -c .bandit.yml -r src/ -lll` | exit 0 |
| Compose config | `docker compose config -q` | exit 0 |

**Baseline**: `pytest -m unit tests -q` → **2517 passed, 2 skipped** (measured
2026-10-31 on this branch, after plan 056).

## Scope

**In scope**:
- `deploy/keycloak/realm-wba.json.template` — add the `wba-web` audience mapper.
- `scripts/keycloak-realm-reconcile.sh` (create) — the idempotent reconcile script.
- `ADMIN_GUIDE.md` — replace the "drop the database" advice with the reconcile
  workflow, keeping the drop as a documented last resort.
- `tests/test_auth_tokens.py` — add the realm-shaped-token regression test.
- `plans/README.md` — this plan's status row, plus a correction to 056's row.

**Out of scope** (do NOT touch):
- `src/app/auth/tokens.py` — the validator stays strict. The fix is to make the
  **token** carry an audience, not to relax the check. Changing this file
  contradicts the decision recorded in `plans/055:134` and would weaken the
  check for the service client too.
- `deploy/keycloak/entrypoint.sh` — the first-boot import path is unchanged.
- `docker-compose.yml` — no new service, no published port.
- `src/common/auth/service_token.py` — plan 055's code, already correct.
- `src/app/api/auth/**`, `src/ui/**` — plan 056's code, already correct. The
  login failure is entirely a realm-configuration gap.
- `keycloak-config-cli` adoption — explicitly deferred (see Maintenance notes).

## Steps

### Step 1: Add the `wba-web` audience mapper to the template

In `deploy/keycloak/realm-wba.json.template`, in the **`wba-web`** client object,
add a `protocolMappers` array **after** the existing `attributes` block and
before `redirectUris`. Copy `wba-internal`'s shape exactly, changing the names
to the `wba-web` client:

```json
      "attributes": {
        "pkce.code.challenge.method": "S256"
      },
      "protocolMappers": [
        {
          "name": "wba-web-audience",
          "protocol": "openid-connect",
          "protocolMapper": "oidc-audience-mapper",
          "consentRequired": false,
          "config": {
            "included.client.audience": "wba-web",
            "id.token.claim": "false",
            "access.token.claim": "true"
          }
        }
      ],
      "redirectUris": [
```

**Do not** modify the `wba-internal` mapper. **Do not** add a `clientScopes`
section. The file must remain valid JSON.

**Verify**:
- `python -c "import json,re,pathlib; s=pathlib.Path('deploy/keycloak/realm-wba.json.template').read_text(); d=json.loads(re.sub(r'\\\$\{[A-Z_]+\}','X',s)); print([c['clientId'] for c in d['clients'] if c.get('protocolMappers')])"`
  → `['wba-web', 'wba-internal']` (the substitution is only to make the JSON parseable; the file itself still contains placeholders)
- `grep -c "protocolMappers" deploy/keycloak/realm-wba.json.template` → `2`
- `grep -c "wba-web-audience" deploy/keycloak/realm-wba.json.template` → `1`
- The rendered template still passes the entrypoint's placeholder guard:
  `bash -c 'rendered=$(<deploy/keycloak/realm-wba.json.template); for n in APP_PUBLIC_BASE_URL KEYCLOAK_CLIENT_SECRET KEYCLOAK_SERVICE_CLIENT_SECRET DEV_WBA_ADMIN_PASSWORD DEV_WBA_USER_PASSWORD; do rendered=${rendered//"\${$n}"/X}; done; case "$rendered" in *"\${"*) echo FAIL;; *) echo OK;; esac'`
  → `OK`

### Step 2: Write the idempotent reconcile script

Create `scripts/keycloak-realm-reconcile.sh`, executable, bash, following
`scripts/init-configs.sh`'s style.

Purpose: reconcile the **one** thing this plan needs — the `wba-web` audience
mapper — into an **already-running** realm, without touching users, sessions,
roles, or the other client. It must be safe to run repeatedly and safe against
a realm that already has the mapper.

Requirements:

1. `set -euo pipefail`; refuse to run if the `keycloak` container is not
   `Running` (a clear message, non-zero exit).
2. Read `DEV_KEYCLOAK_ADMIN_PASSWORD` from `.env`. If unset, fail with a message
   naming the variable. **Never echo the value.**
3. Authenticate inside the container, avoiding secrets in argv. **CORRECTED
   2026-10-31 — the text that stood here was wrong.** `kcadm.sh config
   credentials` does **not** accept `--password:env` (Keycloak 26.8 rejects it
   with `Unknown options: '--password:env'`). It reads the **`KC_CLI_PASSWORD`**
   environment variable when `--password` is omitted, per its own `--help`.
   Forward it with a bare `docker exec -e` (no `=value`) so the secret never
   enters argv, and have the reader function assign the `.env` value **straight
   into `KC_CLI_PASSWORD`** — reading it into an intermediate name and
   re-exporting is the mistake that produced the misleading
   `Console is not active, but password is required`:

   ```bash
   KC_CLI_PASSWORD="$(sed -n 's|^DEV_KEYCLOAK_ADMIN_PASSWORD=||p' "$ENV_FILE" | head -n 1)"
   export KC_CLI_PASSWORD
   docker exec -e KC_CLI_PASSWORD "$CONTAINER" "$KCADM" config credentials \
       --server "$KC_SERVER" --realm master --user admin >/dev/null
   ```
4. **Idempotency check first.** Read the current client and decide whether the
   mapper is already present:

   ```
   docker exec wba-ai-keycloak /opt/keycloak/bin/kcadm.sh get clients -r wba -q clientId=wba-web
   ```

   That returns a JSON array; the client's internal `id` is the first element's
   `id`. Then fetch the mapper list for that id and grep for `wba-web-audience`.
   If present, print `wba-web audience mapper already present — nothing to do`
   and exit 0 **without** issuing a write. This is the property that makes the
   script safe to re-run in production; a test must prove it.

5. If absent, `PUT` the **whole** `protocolMappers` array for that client —
   `kcadm.sh update clients/<id> -r wba -s 'protocolMappers=[...]'` — carrying
   the same mapper object as the template. Keep the mapper JSON **byte-identical
   in shape** to the template's, so the two cannot drift; a comment in the script
   must say the template at `deploy/keycloak/realm-wba.json.template` is the
   source of truth and this is its delivery arm.
6. Print a one-line summary of what it did (added / already present). Print no
   secret, and no full client representation (it contains the client secret).

**Verify**:
- `bash -n scripts/keycloak-realm-reconcile.sh` → exit 0
- `test -x scripts/keycloak-realm-reconcile.sh` → exit 0
- `grep -c "password:env" scripts/keycloak-realm-reconcile.sh` → ≥ 1 (no secret in argv)
- `grep -ci "echo .*PASSWORD" scripts/keycloak-realm-reconcile.sh` → `0`
- `docker compose ps keycloak` shows `healthy` before you run it for real

### Step 3: Run it against the live realm — THE MANUAL GATE for the realm change

This is the only step that touches the running instance, and it is
**operator-facing**: run it, then have the operator re-test login.

> ### 🚦 MANUAL GATE 1 — realm reconcile and a real login (mandatory)
>
> 1. Run `./scripts/keycloak-realm-reconcile.sh` → prints that it added the
>    mapper (first run) or that it was already present (second run).
> 2. **Run it a second time and confirm it writes nothing** and still exits 0.
>    This is the idempotency proof; a second run that errors or re-applies is a
>    FAIL.
> 3. Confirm the realm now carries the mapper, without printing the client
>    secret:
>    ```
>    docker exec wba-ai-keycloak /opt/keycloak/bin/kcadm.sh get clients -r wba -q clientId=wba-web --fields 'id,clientId,protocolMappers' --format json
>    ```
>    → JSON containing a `wba-web-audience` entry with
>    `"included.client.audience": "wba-web"`.
> 4. **Operator**: clear cookies/site data for `https://localhost`, open
>    `https://localhost/app`, sign in as `dev-user` → you must land on
>    `/app/graph` with a styled page and an account bar reading `dev-user`.
>    Signing in as `dev-admin` → `Admin` badge.
> 5. Confirm no user was lost: `kcadm.sh get users -r wba --fields username`
>    → still lists `dev-admin`, `dev-user`, `service-account-wba-internal`.
>
> Wait for `PASS`. A `FAIL` is a STOP condition.

> **GATE 1 RESULT — ✅ PASS, 2026-10-31 (operator).** First run:
> `✓ Added wba-web-audience to client wba-web`, exit 0. Second run:
> `✓ wba-web audience mapper already present — nothing to do`, exit 0, **no
> write** — idempotency confirmed. `kcadm get clients -r wba -q clientId=wba-web`
> shows a `wba-web-audience` / `oidc-audience-mapper` entry.
> `kcadm get users -r wba` still lists `dev-admin` and `dev-user` — **no user
> lost**. The operator then signed in at `https://localhost/app` as `dev-user`,
> landed on `/app/graph` with a styled page and the account bar rendered.
>
> **Two corrections were required before the script would run — both were
> defects in the version THIS PLAN prescribed, and neither was findable without
> executing it:**
>
> 1. **`kcadm config credentials` has no `--password:env` flag.** Step 2's
>    requirement 3 was wrong. Keycloak 26.8 rejects it with
>    `Unknown options: '--password:env'`. The supported mechanism is the
>    **`KC_CLI_PASSWORD`** environment variable, which the CLI documents in its
>    own `--help` ("prompted for if not specified, --user is used, and the env
>    variable KC_CLI_PASSWORD is not defined"). Keep the secret out of argv by
>    forwarding it with a bare `docker exec -e KC_CLI_PASSWORD` (no `=value`).
> 2. **The first repair forwarded `KC_CLI_PASSWORD` but still exported
>    `DEV_KEYCLOAK_ADMIN_PASSWORD`**, so kcadm received no password and failed
>    with `Console is not active, but password is required`. That message is
>    misleading — kcadm probes the console route to decide whether to prompt. The
>    admin console is healthy: `/auth/admin/master/console/` returns **200** from
>    the Docker network, and the container log shows no disabled features. The
>    fix is for `require_admin_password()` to read the value straight into
>    `KC_CLI_PASSWORD`.
>
> **Lesson worth carrying:** `bash -n`, the flag greps, and the `kcadm --help`
> inspection all passed while the script was still broken. Only running it found
> either fault. That is the same failure shape as the `aud` gap (Step 5) and
> 056's `/app` prefix defect — a check that looks like verification but never
> exercises the path.

**Verify** (before the gate): `grep -c "wba-web-audience" scripts/keycloak-realm-reconcile.sh` → ≥ 1

### Step 4: Rewrite the ADMIN_GUIDE realm-change section

In `ADMIN_GUIDE.md`, the section currently at line ~150 reads:

```
To re-seed from the variable instead (a fresh realm import plus a fresh admin),
recreate the `keycloak` database — safe because it is derived entirely from
`deploy/keycloak/realm-wba.json.template` and holds no hand-made state:

docker compose stop keycloak
docker compose exec -T postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c 'DROP DATABASE keycloak;'
docker compose exec -T postgres createdb -U "$POSTGRES_USER" -O keycloak keycloak
docker compose up -d keycloak
```

Replace it with a new top-level section, **"Applying a realm change"**, placed
before "Disable the console again". It must cover, in this order:

1. **Why the template alone is not enough.** `--import-realm` is *create-only*:
   it imports a realm that does not exist and **skips** one that does. Editing
   `realm-wba.json.template` therefore has no effect on a running stack. Quote
   the observable symptom: the template says one thing, `kcadm get realms/wba`
   says another, nothing errors.
2. **The normal path — `./scripts/keycloak-realm-reconcile.sh`.** Idempotent,
   no downtime, preserves users and sessions. Show the command and its two
   possible outputs.
3. **How to extend it for a new change.** The script currently reconciles one
   mapper; state plainly that a new realm change means adding the corresponding
   idempotent check-and-update to the script, and that the template remains the
   source of truth it must match. Warn that a hand edit through the console is
   *not* captured by the template and will be invisible to the next reconcile.
4. **The re-seed path — destructive, last resort only.** Keep the existing
   `DROP DATABASE keycloak` commands, but reframe them: they destroy **every
   user, group, session and client secret in the realm** and cause an
   authentication outage. Correct the existing sentence "safe because it is
   derived entirely from the template and holds no hand-made state" — that is
   true **only** of a local dev stack where the realm holds nothing but the
   seeded `dev-*` users. Say so explicitly, and say it is never appropriate
   against an environment with real users.
5. A short **"verify"** step: after any change, confirm the running realm
   matches the template for the field you changed (the `kcadm get ... --fields`
   command from Gate 1).

Match the file's existing tone and heading style (it uses `##` for top-level
sections and fenced `bash` blocks). Keep it operator-facing prose, not a spec.

**Verify**:
- `grep -n "Applying a realm change" ADMIN_GUIDE.md` → one match
- `grep -n "keycloak-realm-reconcile.sh" ADMIN_GUIDE.md` → ≥ 1 match
- `grep -n "DROP DATABASE keycloak" ADMIN_GUIDE.md` → still present (kept as the last resort, not deleted)
- `grep -n "authentication outage\|every user, group, session" ADMIN_GUIDE.md` → ≥ 1 match
- The markdown has no unclosed code fence:
  `python -c "import pathlib; t=pathlib.Path('ADMIN_GUIDE.md').read_text(); print(t.count('\`\`\`') % 2)"` → `0`

### Step 5: Add the regression test the plan is missing

The reason this bug reached a browser is that plan 056's flow tests stub
`validate_bearer_token` (`tests/test_auth_flow.py:138-143`), so no test ever
feeds the validator a **realm-shaped** token. Add to `tests/test_auth_tokens.py`
a test that pins the exact claim shape the `wba-web` mapper must produce, so a
future realm regression fails a test rather than a login.

The test asserts that a token carrying `aud=["wba-web"]`, `azp="wba-web"`,
`iss=<KEYCLOAK_ISSUER>`, a valid signature, and a `wba-user` realm role
**validates**, while the same token with the `aud` claim **removed** raises
`TokenValidationError` naming `aud`. Follow the file's existing fixture pattern
for minting a signed token; if it already has a helper that builds claims, reuse
it and add/remove only the `aud` key.

Add a module-level docstring line stating *why*: the interactive client's `aud`
comes from an `oidc-audience-mapper` in `deploy/keycloak/realm-wba.json.template`,
and this test is the only thing that couples that realm configuration to the
validator's requirement.

**Verify**:
- `pytest -m unit tests/test_auth_tokens.py -q` → all pass, ≥ 2 new tests

- Prove the new test is **not vacuous** by disabling the `aud` check and
  confirming the negative test then fails. **Do NOT use the mutation this plan
  originally prescribed** (deleting `"aud"` from the `require` list in
  `src/app/auth/tokens.py`) — it is **inert**: PyJWT's `verify_aud` defaults to
  `True` and the `audience=` kwarg enforces the claim on its own, so removing
  `"aud"` from `require` leaves an aud-less token rejected and the test still
  passing. Verified on this repo against PyJWT 2.15.1: with
  `options={"require": ["exp", "iss", "sub"]}` and an aud-less token, decode
  still raises `MissingRequiredClaimError('Token is missing the "aud" claim')`.
  A mutated run that "passes" would be misread as a vacuous test.

  Instead neutralise the check for one run **without writing to `src/`**, via a
  throwaway pytest plugin on `PYTHONPATH` that patches `jwt.decode` to neither
  verify nor require `aud`:

  ```python
  # /tmp/av_plugin.py
  import jwt as _jwt
  _orig = _jwt.decode

  def decode(jwt, key="", algorithms=None, options=None, audience=None,
             issuer=None, leeway=0, **kw):
      options = dict(options or {})
      options["verify_aud"] = False
      options["require"] = [c for c in options.get("require", []) if c != "aud"]
      return _orig(jwt, key, algorithms=algorithms, options=options,
                   issuer=issuer, leeway=leeway, **kw)

  _jwt.decode = decode
  ```

  Run: `PYTHONPATH=/tmp:src pytest -m unit tests/test_auth_tokens.py -q -p av_plugin`
  → the aud-less test **MUST FAIL** with `DID NOT RAISE TokenValidationError`,
  while the positive test still passes. Then run the suite normally → **MUST
  PASS**. Report both outputs. If the neutralised run does not fail on that
  assertion, the test is not testing what it claims.

  Note: `src/app/auth/tokens.py` must end this step **byte-identical** to how it
  started — this method never writes to it. Confirm with
  `git diff --stat -- src/app/auth/tokens.py` → empty.

### Step 6: Update the index

Update this plan's row in `plans/README.md`, and correct the **056** row: it
proved the login flow only as far as `/auth/login` returning 302 — the callback
and token exchange were never exercised, which is why this gap survived every
one of its automated gates.

**Verify**: `grep -n "| 062" plans/README.md` → one match with a status.

## Test plan

- `tests/test_auth_tokens.py` — two new tests (realm-shaped token validates;
  the same token without `aud` is rejected). Model after that file's existing
  signed-token helper.
- Step 5's *neutralised* run is the anti-vacuity proof and is **required**, not
  optional — the last plan in this sequence shipped a test that could not fail
  (plan 056's `assert "/stream" in content`), and this plan exists because of a
  coverage boundary of the same shape. Note that this plan's *own* first
  prescribed mutation was inert and would have produced a false negative; see
  Step 5 for why, and do not reintroduce it.
- Gate 1 covers what no unit test can: that the running realm actually emits
  the mapper, that the reconcile is idempotent, and that a real browser login
  completes.

## Done criteria

- [ ] `grep -c "protocolMappers" deploy/keycloak/realm-wba.json.template` → `2`
- [ ] Template still renders clean through the entrypoint's placeholder guard → `OK`
- [ ] `bash -n scripts/keycloak-realm-reconcile.sh` → exit 0; file is executable
- [ ] **Running it twice is idempotent** — first run reports adding the mapper, second reports it is already present and exits 0 (Gate 1 step 2)
- [ ] `kcadm.sh get clients -r wba -q clientId=wba-web --fields id,clientId,protocolMappers --format json` contains `wba-web-audience` with `"included.client.audience": "wba-web"`
- [ ] `kcadm.sh get users -r wba --fields username` still lists `dev-admin`, `dev-user`, `service-account-wba-internal` — **no user was lost**
- [ ] **MANUAL GATE 1 passed** — operator signs in at `https://localhost/app` as `dev-user` and lands on `/app/graph` with an account bar
- [ ] `ADMIN_GUIDE.md` has an "Applying a realm change" section; the `DROP DATABASE` block survives but is labelled destructive
- [ ] `pytest -m unit tests/test_auth_tokens.py -q` passes with ≥ 2 new tests; the Step 5 neutralised run failed on `DID NOT RAISE TokenValidationError`; `git diff --stat -- src/app/auth/tokens.py` → empty
- [ ] `pytest -m unit tests -q` exits 0, ≥ 2517 passed
- [ ] `mypy src/` exit 0; `pylint src --score=y` ≥ 9.0; `bandit` exit 0
- [ ] No secret value appears in any created file **or in any log line** the script produces
- [ ] No files outside the in-scope list are modified (`git status`)
- [ ] `plans/README.md` rows for 056 and 062 updated

## STOP conditions

Stop and report if:

- The `wba-web` client's `protocolMappers` in the **running** realm already
  differs from the template in some other way — do not "fix" it to match; report
  it. It means someone hand-edited the realm and the template is not the source
  of truth you were told it was.
- Keycloak 26.8 rejects `oidc-audience-mapper` with
  `included.client.audience` set to the client's **own** `clientId`. (It is
  expected to accept it — `wba-internal` uses exactly this shape. If `wba-web`
  behaves differently, the mapper may need `included.custom.audience` instead;
  report rather than guessing.)
- After applying the mapper, the token still has no `aud` — capture the decoded
  token's claim names (not values) and report. Do not relax the validator.
- The reconcile script cannot be made idempotent (a second run errors or
  re-applies). Report; do not ship a script that must be run exactly once.
- `kcadm.sh` cannot authenticate with `--password:env`. Report the error text
  with any secret redacted; do not fall back to `--password <value>` in argv.
- In-scope files have drifted.

## Maintenance notes

- **This plan establishes a pattern, not just a fix.** Every future realm change
  follows: edit the template (source of truth) → add the matching idempotent
  check-and-update to `scripts/keycloak-realm-reconcile.sh` → run it. The script
  will accrete a block per change. When it grows past a few blocks, that is the
  signal to revisit `keycloak-config-cli` (below) rather than to keep hand-rolling.
- **`keycloak-config-cli` is the deferred upgrade.** It reconciles the *whole*
  realm file declaratively from the same template, which removes the
  hand-written-per-change cost entirely. It was considered and deferred: it adds
  an image dependency and makes the whole realm managed (any console hand-edit
  gets reverted on the next run, which is a policy decision the operator should
  take deliberately). Adopt it when the script's maintenance cost exceeds the
  cost of that dependency.
- **The console is not a source of truth.** A mapper added through the admin
  console is invisible to the template and will be silently reverted the moment
  someone re-seeds, and invisible to the next reconcile. `ADMIN_GUIDE.md` now
  says so; a reviewer should keep that warning honest.
- **The validator stays strict on purpose.** A missing `aud` is rejected. The
  correct response to a missing audience is always to make the *token* carry
  one. Relaxing `tokens.py` would weaken the check for `wba-internal` too, and
  plan 057 depends on the audience distinction to accept either client.
- **Plan 057 must not assume this landed.** Its decision table needs the
  `azp ∈ {wba-web, wba-internal}` rule from `plans/055:135`, and it should now
  also assume both clients carry their own `aud`. If 057 is executed before this
  plan, its service-token path will fail the same way — hence `Depends on: 056`.
- **Coverage boundary to remember:** unit tests that stub `validate_bearer_token`
  cannot catch a realm that fails to produce a validatable token. That class of
  bug is only reachable by a real end-to-end login, which is plan 060's job.
  This plan narrows the gap with a realm-shaped token test; it does not close it.

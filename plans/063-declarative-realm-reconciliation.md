# Plan 063: Reconcile the whole realm declaratively, and report drift instead of hiding it

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat 459cf85b..HEAD -- docker-compose.yml deploy/keycloak/realm-wba.json.template deploy/keycloak/entrypoint.sh scripts/keycloak-realm-reconcile.sh ADMIN_GUIDE.md .env.example`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.
>
> **Reconciled 2026-11-02 at `8395a9e5`.** The drift check fires on
> `scripts/keycloak-realm-reconcile.sh`, but that is **not drift**: the plan's
> stamp `459cf85b` pre-dates the `7698f1e7` (#362) merge that introduced the
> `client_uuid` refactor and the `wba-internal` audience mapper. The "Current
> state" excerpts — `reconcile_audience_mapper` / `reconcile_web_post_logout_uri`
> and the three calls at `:159-161` — match the committed script exactly. Proceed
> without a refresh; the finding (3 of 21 facts reconciled, no drift detection)
> is unchanged.

## Status

- **Priority**: P2
- **Effort**: L
- **Risk**: MED
- **Depends on**: plans/062-*.md (the kcadm script this plan supersedes or demotes)
- **Category**: tech-debt / security
- **Planned at**: commit `459cf85b`, 2026-10-31
- **Design reference**: `docs/design/authn-authz-design.md` §"Realm as code" (line 216)
- **Should run after**: plans/057 (enforcement lands first; do not change realm delivery while auth is being switched on)

## Why this matters

`scripts/keycloak-realm-reconcile.sh` delivers realm changes to a running
Keycloak, and it works — but it reconciles **3 of the 21** declarative facts the
realm template declares. It grew by appending one hand-written block per bug
found in the 054–056 sequence: a `wba-web` audience mapper, then a
`post.logout.redirect.uris` attribute, then a `wba-internal` audience mapper.
Three blocks, three bugs.

The coverage gap is not theoretical. **Four separate "the template says X, the
realm says Y" defects surfaced in that sequence, and every one passed whatever
check was supposed to cover it.** One of them — the missing `wba-internal`
audience mapper — would have failed authentication for every producer and the
consumer the moment plan 057 switched enforcement on. It was found only because
a reviewer decoded a live token by hand.

Two properties of the current script make this inevitable:

1. **Silent success on uncovered facts.** Change `accessTokenLifespan` in the
   template and run the script: it prints three green ticks and reconciles
   nothing. The realm silently diverges from the file that is supposed to
   define it.
2. **Name-only detection.** `reconcile_audience_mapper` checks whether a mapper
   of that *name* exists. Edit `included.client.audience` in the template and
   the script reports "already present" while the realm keeps the old value —
   the same class of bug it was built to catch, inside the tool itself.

After this plan: the realm is reconciled from the template as a whole, drift is
**reported** rather than hidden, and a test fails when a template fact is
neither reconciled nor explicitly exempted — so the next gap cannot be added
silently.

## Current state

### `scripts/keycloak-realm-reconcile.sh` — what exists today

Three reconcile blocks, called at lines 159–161:

```bash
reconcile_audience_mapper "$WEB_CLIENT_ID" "$WEB_MAPPER_NAME"
reconcile_audience_mapper "$INTERNAL_CLIENT_ID" "$INTERNAL_MAPPER_NAME"
reconcile_web_post_logout_uri
```

Detection, showing the name-only weakness (`reconcile_audience_mapper`):

```bash
    local mappers
    mappers="$(kcadm get "clients/${client_id}/protocol-mappers/models" -r "$REALM" --fields name --format csv --noquotes)"
    if grep -qx "$mapper_name" <<<"$mappers"; then
        info "${client_id_name} audience mapper already present — nothing to do"
        return 0
    fi
```

Its header comment claims more than it delivers:

```
# `deploy/keycloak/realm-wba.json.template` is the source of truth. Every mapper
# applied here must match the template byte-for-byte in shape; if the two drift,
# the realm stops matching the code that defines it.
```

True for the three it knows; **false for the other 18 facts**. That comment must
be corrected or removed by this plan.

The script also relies on a greedy-`sed` string parse to read an attribute out
of `kcadm`'s JSON (`reconcile_web_post_logout_uri`). It works, but it is a
string parse standing in for a JSON parse and will fail confusingly rather than
loudly on unexpected input.

### `deploy/keycloak/realm-wba.json.template` — the 21 declared facts

Measured at `459cf85b`:

| Fact | Reconciled by the script? |
|---|---|
| `realm.accessTokenLifespan`, `ssoSessionIdleTimeout`, `ssoSessionMaxLifespan`, `sslRequired`, `enabled` | ❌ |
| `realm.roles` (3 realm roles) | ❌ |
| `wba-web.redirectUris`, `webOrigins`, `publicClient`, `standardFlowEnabled`, `serviceAccountsEnabled`, `secret` | ❌ |
| `wba-web.attributes` → `pkce.code.challenge.method` | ❌ |
| `wba-web.attributes` → `post.logout.redirect.uris` | ✅ |
| `wba-web.mapper[wba-web-audience]` | ✅ |
| `wba-internal.publicClient`, `standardFlowEnabled`, `serviceAccountsEnabled`, `secret` | ❌ |
| `wba-internal.mapper[wba-internal-audience]` | ✅ |
| `users` (3 seeded users with roles and credentials) | ❌ |

**3 of 21.** The template is rendered by `deploy/keycloak/entrypoint.sh` before
import; it contains `${...}` placeholders and is **not** directly consumable by
any tool.

### `deploy/keycloak/entrypoint.sh` — the rendering step

Pure-bash substitution (not `envsubst`, absent from the image; not `sed`, which
mangles an `&` in a password), then writes the rendered file and execs Keycloak:

```bash
rendered=$(<"/opt/keycloak/realm-wba.json.template")
for name in APP_PUBLIC_BASE_URL KEYCLOAK_CLIENT_SECRET \
            KEYCLOAK_SERVICE_CLIENT_SECRET DEV_WBA_ADMIN_PASSWORD DEV_WBA_USER_PASSWORD; do
  rendered=${rendered//"\${$name}"/"${!name}"}
done
...
printf '%s\n' "$rendered" > /opt/keycloak/data/import/realm-wba.json
exec /opt/keycloak/bin/kc.sh start-dev --import-realm --http-relative-path=/auth
```

**This rendering logic is needed by any delivery mechanism**, and it currently
exists in exactly one place, inside the Keycloak container, writing to a path
only that container can see. Any second consumer must either duplicate it or
share it.

### `docker-compose.yml` — the `keycloak` service, and the absence of profiles

```yaml
  keycloak:
    image: quay.io/keycloak/keycloak:26.8
    container_name: wba-ai-keycloak
    restart: unless-stopped
    command: ["start-dev", "--import-realm"]
    entrypoint: ["/opt/keycloak/entrypoint.sh"]
    environment:
      KC_HOSTNAME: ${EXTERNAL_BASE_URL:-https://localhost}/auth
      KC_HTTP_RELATIVE_PATH: /auth
      KC_BOOTSTRAP_ADMIN_USERNAME: admin
      KC_BOOTSTRAP_ADMIN_PASSWORD: ${DEV_KEYCLOAK_ADMIN_PASSWORD}
      KEYCLOAK_CLIENT_SECRET: ${KEYCLOAK_CLIENT_SECRET}
      KEYCLOAK_SERVICE_CLIENT_SECRET: ${KEYCLOAK_SERVICE_CLIENT_SECRET}
      ...
    depends_on:
      postgres:
        condition: service_healthy
```

**No service in this repo uses `profiles:`** — verified: `grep -c "profiles:" docker-compose.yml` → 0. Docker Compose v2.40.3 supports it.

Existing service shapes to match:
- **Long-running**: `restart: unless-stopped` — `api`, `ui`, `nginx`, `keycloak`, `signal-consumer`.
- **One-shot**: no `restart:` field — `github-producer`, `jira-producer`, `confluence-producer`. They start on `up -d`, run, exit, and are re-run manually per `CLAUDE.md`.

The producer services are the closest precedent for credential handling — they
declare `env_file: [.env]` plus explicit `environment:` entries.

### `ADMIN_GUIDE.md` — the section this plan must rewrite

`## Applying a realm change` begins at line 150, with sub-sections:

| Line | Heading |
|---|---|
| 152 | `### Why editing the template is not enough` |
| 171 | `### The normal path` |
| 192 | `### Extending it for a new change` |
| 213 | `### Re-seeding from scratch — destructive, last resort only` |
| 234 | `### Verify a change` |

Lines 178 and 200 reference `./scripts/keycloak-realm-reconcile.sh` and its
"read the current value, skip the write" idempotency rule.

### Repo conventions that apply

- Compose services pin image digests/versions explicitly (`nginx:1.30-alpine`, `keycloak:26.8`) and carry a comment when the pin is deliberate.
- Shell scripts: `scripts/`, `bash`, `set -euo pipefail`, executable. Exemplar `scripts/init-configs.sh`.
- **Never put a credential in argv or a log.** `kcadm.sh` reads `KC_CLI_PASSWORD`; the reconcile script forwards it with a bare `docker exec -e KC_CLI_PASSWORD`.
- **Do not commit or push unless the operator asks.**

## Commands you will need

| Purpose | Command | Expected on success |
|---|---|---|
| Compose valid | `docker compose config -q` | exit 0 |
| Service is profiles-gated | `docker compose config \| grep -c "<service>"` | see step text |
| Keycloak up | `docker compose ps keycloak` | `Up ... (healthy)` |
| Realm read (read-only) | see "Reading the realm" below | JSON |
| Unit tests | `pytest -m unit tests -q` | ≥ baseline, 0 fail |
| Typecheck | `mypy src/` | exit 0 |
| Lint | `pylint src --score=y` | ≥ 9.0 |

**Reading the realm without writing to it.** `kcadm` does not persist a session
across `docker exec` calls; one invocation must authenticate and query together.
**Do not `source .env`** — it fails to parse (there is an unquoted value at line
171) and silently leaves the password unset, which produces a misleading
`Console is not active, but password is required`. Extract the single variable
instead, as the reconcile script does:

```bash
KC_CLI_PASSWORD="$(sed -n 's|^DEV_KEYCLOAK_ADMIN_PASSWORD=||p' .env | head -n 1)"; export KC_CLI_PASSWORD
docker exec -e KC_CLI_PASSWORD wba-ai-keycloak sh -c \
  '/opt/keycloak/bin/kcadm.sh config credentials --server http://localhost:8080/auth --realm master --user admin >/dev/null && /opt/keycloak/bin/kcadm.sh get realms/wba --fields "realm,accessTokenLifespan" --format json'
```

**Baseline**: `pytest -m unit tests -q` → **2519 passed, 2 skipped** (measured at
`459cf85b`).

## Scope

**In scope**:
- `deploy/keycloak/render-realm.sh` (create) — the rendering logic, extracted so
  more than one consumer can use it.
- `deploy/keycloak/entrypoint.sh` — call the extracted renderer.
- `docker-compose.yml` — the new reconciliation service (profiles-gated) and, if
  the renderer moves, the keycloak service's mounts.
- `scripts/realm-drift.sh` (create) — the drift report.
- `scripts/keycloak-realm-reconcile.sh` — correct its overstated header comment;
  demote or delete per Step 6.
- `ADMIN_GUIDE.md` — rewrite `## Applying a realm change` and its sub-sections.
- `tests/test_realm_template_coverage.py` (create) — the coverage guard.
- `plans/README.md` — this plan's status row.

**Out of scope** (do NOT touch):
- `deploy/keycloak/realm-wba.json.template` — the template is the source of
  truth and is correct. **This plan changes how it is delivered, not what it
  says.** If delivery reveals a template bug, report it as a finding; do not
  edit the template as part of this plan.
- `src/` — no application code. Realm delivery is infrastructure.
- Plan 057's enforcement work, if it has landed — do not change `src/app/auth/`.
- `deploy/nginx/nginx.conf`, `deploy/postgres/` — unrelated.
- The `keycloak` service's own `command`, `entrypoint`, and healthcheck —
  first-boot import behaviour stays exactly as it is.

## Steps

### Step 1: Establish the tool and its exact behaviour — evidence before design

**This step writes no code.** Its purpose is to replace this plan's unverified
assumptions with facts, because the rest of the plan depends on them and this
repository's recent history is a catalogue of unverified assumptions.

Record in your report, with the command that produced each:

1. **A compatible `keycloak-config-cli` image tag for Keycloak 26.8.** The tool
   versions in lockstep with Keycloak major/minor. Determine the current tags
   (inspect the registry / release notes), pick the one matching Keycloak 26.x,
   and state why. **Do not guess a version** — if you cannot determine a
   compatible tag with confidence, that is a STOP condition, not something to
   fill in.
2. **The tool's configuration keys and their defaults** for: Keycloak URL,
   realm file path, admin credentials, dry-run mode, and the behaviour for
   resources present in the realm but absent from the file. The last one is
   critical: if the default deletes unmanaged resources, running this against a
   live realm destroys anything not in the template. Report the exact key names
   and default values as the image documents them.
3. **Whether it can render `${...}` placeholders**, or whether the template must
   be pre-rendered. This determines whether Step 2 is required.
4. **Its output format in dry-run mode** — whether it prints a diff a human can
   read, and whether it exits non-zero when drift is found (which the drift
   script needs).

**Verify**: you have quoted evidence (image tag, doc text or `--help` output) for
each of the four points. No claim in your report may rest on recollection.

> **STOP conditions for this step**: no compatible tag can be established; the
> tool cannot be configured to leave unmanaged resources alone; or it cannot read
> the realm file at all without an admin credential this repo does not have.
> Report and stop — do not proceed on an assumption.

### Step 2: Extract the realm renderer

The rendering logic in `entrypoint.sh` is needed by both Keycloak's first-boot
import and whatever delivers changes (if Step 1.3 shows the tool cannot render
placeholders itself).

Create `deploy/keycloak/render-realm.sh`:

- Accepts an output path as `$1`; reads `/opt/keycloak/realm-wba.json.template`
  (or a path given as `$2`, defaulting to that).
- Performs the **same** substitution `entrypoint.sh` currently does, over the
  same variable list, using the same bash-substitution technique and the same
  unsubstituted-placeholder guard.
- **The substituted variable list must stay in exactly one place.** If the
  renderer owns it, `entrypoint.sh` calls the renderer rather than duplicating
  the loop.

Then update `deploy/keycloak/entrypoint.sh` to call the renderer, and add the
mount if the file lives outside the container's existing mounts (the keycloak
service currently mounts the template and entrypoint read-only; a new script
needs its own line).

**The rendered output must be byte-identical to what `entrypoint.sh` produced
before this step.** Prove it rather than asserting it: render with the old and
new paths into two files and diff them.

**Verify**:
- `bash -n deploy/keycloak/render-realm.sh` → exit 0; executable
- Rendering with the old inline loop and the new renderer to two temp files →
  `diff` reports **no differences**
- The placeholder guard still fires: deliberately introduce a `${TYPO}` in a
  *copy* of the template and confirm the renderer exits non-zero; do not leave
  the template modified
- `docker compose config -q` → exit 0

### Step 3: The reconciliation service, in dry-run only

Add the service to `docker-compose.yml`, **gated behind a Compose profile** so
it is inert during a normal `docker compose up -d`.

Why a profile, and not `restart: unless-stopped`: a reconciler that runs
continuously reverts any console change within minutes, silently, with no clear
causal link back to itself. That is the worst possible failure mode for an admin
tool. Reconciliation must be a deliberate, observed action. `profiles:` gives
exactly that — the service is documented and one command away, but never part of
a stack start.

Shape (adapt names to the tool you confirmed in Step 1):

```yaml
  realm-reconcile:
    image: <confirmed tag from Step 1>
    container_name: wba-ai-realm-reconcile
    profiles: ["tools"]
    env_file:
      - .env
    environment:
      <KEYCLOAK URL pointing at http://keycloak:8080/auth — the INTERNAL url>
      <admin user/password — see the credential note below>
      <realm file path>
      <DRY RUN enabled>
    volumes:
      - ./deploy/keycloak:/realm:ro
    networks:
      - wba-ai-network
    depends_on:
      keycloak:
        condition: service_healthy
```

**Credential handling — resolve this deliberately, do not hand-wave it.** This
is the one real cost of moving off the kcadm script, which sidesteps credentials
entirely by running inside the Keycloak container. The tool needs an admin
credential to talk to the Admin REST API. It must come from the environment
(`DEV_KEYCLOAK_ADMIN_PASSWORD`, which is already in `.env` and already granted to
the `keycloak` service), never from a file committed to the repo, and never
printed. Propose the mechanism you use in your report.

**Do not add `restart:` to this service.**

**Verify**:
- `docker compose config -q` → exit 0
- `docker compose config | grep -c "realm-reconcile"` → **> 0** (it is in the file)
- `docker compose config --services | grep -c realm-reconcile` → **0** — proving
  it is **not** part of a default start. This is the profiles assertion and it is
  the important one; a service that silently joins every `up -d` is the failure
  this step exists to prevent.
- `docker compose ps --format '{{.Service}}' | grep -c realm-reconcile` → `0`
  after a normal `up -d`

### Step 4: Run it in dry-run and confront the drift — THE MANUAL GATE

This is where the plan's value is realised or refuted: it reports everything the
realm and the template disagree about.

Run the service in dry-run mode against the running realm. Do **not** apply.

> ### 🚦 MANUAL GATE 1 — the drift report (mandatory)
>
> 1. Run the dry-run. Capture its **full** output.
> 2. Classify every difference it reports into exactly one of:
>    - **(a) Expected** — the realm genuinely should differ from the template
>      (e.g. a field Keycloak owns and the template does not set). Record why.
>    - **(b) Real drift** — the realm is out of step with the template and
>      should be corrected.
>    - **(c) Tool noise** — the tool cannot express or compare the field.
> 3. **Report the classification to the operator and STOP.** Do not apply
>    changes in this step. The operator decides what is (b).
>
> A dry-run that reports **no** differences is itself a finding worth reporting:
> either the realm is genuinely in sync, or the tool is not reading the file (a
> silent misconfiguration, and exactly the failure mode this plan exists to
> eliminate). Prove which, by deliberately introducing a known difference into a
> **copy** of the rendered realm file and confirming the dry-run detects it.
>
> Wait for `PASS`. A `FAIL` is a STOP condition.

**Verify** (before the gate): the dry-run command exits without error and
produces output. Paste it.

### Step 5: The drift check script

Create `scripts/realm-drift.sh`, which wraps the service so a human gets a
readable answer to "is the realm in sync with the template?" without remembering
the invocation.

- Runs the reconciliation service in **dry-run** mode only. **It must have no
  code path that applies changes.**
- Prints a clear verdict: in sync, or a list of differences.
- Exits **0** when in sync and **non-zero** when drift is detected, so it can be
  used in CI or a pre-deploy check.
- Follows the repo's shell conventions (`set -euo pipefail`, `scripts/`
  exemplar).
- Header comment states that this **reports** and does not change anything.

**Verify**:
- `bash -n scripts/realm-drift.sh` → exit 0; executable
- Run it against the in-sync realm → exit **0**, prints an in-sync verdict
- Introduce a deliberate difference in a **copy** of the rendered realm file,
  point the script at the copy → exit **non-zero**, names the difference
- `grep -ci "apply\|update\|create\|delete" scripts/realm-drift.sh` → the only
  matches are in prose explaining that it does not do these. Assert by reading
  the script, not by the count alone.

### Step 6: Resolve the kcadm script's fate

The old script is now either redundant or a fallback. **Report your
recommendation; do not delete it unilaterally.**

If the tool confirmed in Step 1 can apply everything the script does, the
recommendation is to **delete** `scripts/keycloak-realm-reconcile.sh` and its
references — carrying a second, 3-of-21-coverage delivery path is precisely the
drift risk this plan is removing.

If it cannot, **demote** it: correct the overstated header comment (it currently
claims template parity it does not have), add an explicit list of the facts it
does *not* reconcile, and note that it is a stopgap.

Either way, its header comment must stop claiming coverage it lacks. For each of
the 21 facts from "Current state", the header must say either "reconciled here"
or "NOT reconciled by this script".

**Verify**:
- If deleted: `grep -rn "keycloak-realm-reconcile" . --exclude-dir=.git --exclude-dir=__pycache__` → no matches outside `plans/` (which is historical record and must **not** be rewritten)
- If demoted: the header lists every uncovered fact, and the count of "NOT reconciled" entries equals 21 minus the reconciled count

### Step 7: Rewrite the ADMIN_GUIDE section, and add the coverage test

**7a.** Rewrite `ADMIN_GUIDE.md`'s `## Applying a realm change` (line 150) and
its sub-sections (152–248) for the new mechanism. Keep the file's tone — it is
operator-facing prose with fenced `bash` blocks, `##` for top-level sections.

Required content, in this order:

1. **Why the template alone is not enough** — keep the existing explanation
   (`--import-realm` is create-only; Keycloak logs `Realm 'wba' already exists.
   Import skipped`). It is correct and it is the reason any of this exists.
2. **How to check whether the realm has drifted** — `scripts/realm-drift.sh`,
   what its output means, and its exit codes. **This is the headline change: an
   operator should be able to answer "are we in sync?" in one command.**
3. **How to apply a change** — the profile-gated invocation, its dry-run first,
   and the expectation that the operator reads the output before applying.
4. **Why it does not run automatically** — states plainly that a continuously
   reconciling service would silently revert console changes, and that
   reconciliation is deliberately a manual, observed action.
5. **What the template owns vs. what the console owns** — a change made in the
   console is not captured by the template and will be reverted by the next
   apply. This replaces the existing warning box; keep that warning's force.
6. **Re-seeding from scratch** — keep the existing destructive block and its
   corrected framing (it destroys every user, group, session and client secret;
   dev-only; never against real users). Do not delete it.
7. **Verify a change** — keep the existing verification guidance.

Remove the sub-section "Extending it for a new change" if Step 6 deleted the
script — with a declarative reconciler there is no per-change block to add, which
was the whole problem. If the script was demoted, keep it but reframe it as the
stopgap path.

**7b.** Create `tests/test_realm_template_coverage.py`, marked
`pytestmark = pytest.mark.unit`.

The test that prevents this plan's problem from recurring: enumerate the
template's top-level declarative facts and assert each is either **reconciled**
or **explicitly exempted**, with the exemption list written out in the test.

- Parse `deploy/keycloak/realm-wba.json.template` (substituting `${...}` with a
  placeholder so it parses), and collect the facts: realm-level settings, realm
  roles, each client's flags/URIs/attributes/mappers, and the user list.
- Hold an explicit `UNMANAGED` set in the test, each entry with a one-line
  reason. Anything neither managed nor listed fails the test.
- Assert the exclusion list is **not** a wildcard — a test that exempts
  everything passes vacuously. Prove non-vacuity by adding a fact the test does
  not know about and confirming it fails.

**Verify**:
- `grep -n "Applying a realm change" ADMIN_GUIDE.md` → one match
- `grep -c "realm-drift.sh" ADMIN_GUIDE.md` → ≥ 2
- `grep -c "DROP DATABASE keycloak" ADMIN_GUIDE.md` → `1` (kept)
- `grep -c "authentication outage" ADMIN_GUIDE.md` → ≥ 1 (kept)
- Markdown fence parity: `python -c "import pathlib; t=pathlib.Path('ADMIN_GUIDE.md').read_text(); print(t.count('\`\`\`') % 2)"` → `0`
- `pytest -m unit tests/test_realm_template_coverage.py -q` → all pass
- The new test is non-vacuous — prove it by adding an unlisted fact to the
  template **in a copy**, confirming failure, and leaving the real template
  unmodified

### Step 8: Full gates and the index

Run every gate. Then update this plan's row in `plans/README.md`, and correct
plan 062's row: its reconcile script is superseded or demoted here, and 062's own
note claiming the script is the long-term delivery mechanism is no longer
accurate.

**Verify**: every command in "Done criteria" below; `grep -n "| 063" plans/README.md` → one match.

## Test plan

- `tests/test_realm_template_coverage.py` — the coverage guard (Step 7b). Model
  the structure on `tests/test_auth_tokens.py`: module docstring stating *why*,
  `pytestmark = pytest.mark.unit`, focused assertions.
- **Non-vacuity is required, not optional.** This plan exists because three
  checks in the 054–056 sequence passed while the thing they covered was broken.
  A coverage test that would pass with an empty exemption list, or that exempts
  everything, repeats that mistake. Prove it fails when it should.
- The renderer's byte-identity check (Step 2) is a diff against the previous
  behaviour — the strongest available statement that extraction changed nothing.
- Gate 1 (Step 4) covers what no test can: what the tool actually reports about
  a real realm.

## Done criteria

- [ ] Step 1 produced quoted evidence for all four points; no version or
      behaviour claim rests on recollection
- [ ] `bash -n deploy/keycloak/render-realm.sh` → exit 0, executable
- [ ] Old vs. new rendering → **no diff** (byte-identical)
- [ ] `docker compose config --services | grep -c realm-reconcile` → **0** (profiles-gated, not part of a default start)
- [ ] `docker compose config -q` → exit 0
- [ ] **MANUAL GATE 1 passed** — drift report captured, classified, and reported to the operator before any apply
- [ ] The drift script's detection is proven non-vacuous (a seeded difference is detected)
- [ ] `scripts/realm-drift.sh` has **no** apply path; verified by reading it
- [ ] `ADMIN_GUIDE.md`: new section content in the required order; `DROP DATABASE` block retained and still labelled destructive
- [ ] `pytest -m unit tests/test_realm_template_coverage.py -q` passes; the test is proven non-vacuous
- [ ] `pytest -m unit tests -q` exits 0, ≥ 2519 passed
- [ ] `mypy src/` exit 0; `pylint src --score=y` ≥ 9.0
- [ ] The kcadm script is deleted **or** its header lists every uncovered fact
- [ ] No credential appears in any committed file, in `docker-compose.yml`, or in any command output pasted into a report
- [ ] `deploy/keycloak/realm-wba.json.template` is **unmodified** (`git diff --stat` shows no change to it)
- [ ] No files outside the in-scope list are modified (`git status`)
- [ ] `plans/README.md` rows for 062 and 063 updated

## STOP conditions

Stop and report if:

- **No `keycloak-config-cli` tag can be established as compatible with Keycloak
  26.8 from evidence.** Do not guess a version — a wrong pin is worse than no
  pin, and this plan's whole point is to stop delivering unverified things.
- **The tool cannot be configured to leave resources absent from the file
  alone.** If its default is to delete them, applying it would destroy unmanaged
  realm state (roles, users, and anything Keycloak adds itself). Report; do not
  run it in apply mode.
- **The tool requires a credential this repo cannot supply safely** (e.g. it
  only accepts a credential on the command line). Report the constraint rather
  than weakening the handling.
- **The extraction in Step 2 changes the rendered output.** Byte-identity is the
  requirement; a diff means the extraction is wrong, not that the old output was.
- The dry-run reports differences whose classification you cannot determine —
  report them; do not apply and do not guess.
- In-scope files have drifted, or `deploy/keycloak/realm-wba.json.template` has
  been edited since this plan was written.

## Maintenance notes

- **Reconciliation is deliberately manual.** Do not "improve" this by adding
  `restart: unless-stopped` or removing the profile. A continuously running
  reconciler reverts console changes silently and makes the realm impossible to
  reason about. If someone wants automatic enforcement, the correct place is a
  CI/pre-deploy check running `scripts/realm-drift.sh` — which only *reports* —
  not a long-running container.
- **The realm file is authoritative once this lands.** Anything an operator
  changes in the console is reverted by the next apply. That is the intended
  trade for closing the drift gap, and it must be stated in `ADMIN_GUIDE.md`.
  If that policy is unwanted, the alternative is drift-reporting only (Step 5)
  with no apply path — a legitimate configuration, and preferable to pretending
  the two are kept in sync by hand.
- **The tool's versions move with Keycloak's.** Plan 053 pins `keycloak:26.8`.
  A Keycloak upgrade must upgrade this tool in the same change, or reconciliation
  silently stops working against the newer API. Note it wherever the Keycloak
  version is bumped.
- **`tests/test_realm_template_coverage.py` is the durable guard.** Blocks will
  be added to the template over time; the test fails when one is added without
  being reconciled or explicitly exempted. When it fails, the fix is either to
  extend reconciliation coverage or to add a reasoned exemption — never to widen
  a wildcard.
- **Worth deferring, not forgetting:** the four "templated but never delivered"
  defects in 054–056 all share a root cause — delivery is a step nobody
  remembers. A pre-deploy `realm-drift.sh` in CI would have caught all four. That
  is the natural follow-on once this lands, and it is a small change if Step 5's
  exit codes are honoured.

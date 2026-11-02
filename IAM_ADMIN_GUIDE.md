# Keycloak Admin Console

Operator guide for the Keycloak administration console in the local Compose
stack. The console is where you inspect the `wba` realm — its users, roles,
clients and sessions — and it is the only place those can be edited by hand.

It is **not** needed to run the application. Every table, page and endpoint
works without it.

## The console is off by default

The `keycloak` service publishes **no port**. This is deliberate: the admin
console is the highest-privilege surface in the stack, so it is not exposed
unless you ask for it.

Three consequences worth knowing up front:

- The console is **never reachable through nginx**, whether or not the port is
  published. nginx proxies only `/auth/realms/*` and `/auth/resources/*`; every
  other path under `/auth` (including `/auth/admin`, the console, and the admin
  REST API) returns **404**. See `deploy/nginx/nginx.conf`.
- Enabling the port binds it to `127.0.0.1` only, so it stays off the network.
  It is reachable from this host and from nowhere else.
- **The port is only for this console.** Everything users touch — login, the
  account console, token and JWKS endpoints — is served on the public origin
  `https://localhost/auth` through nginx, and needs no port. Opening those on the
  loopback port will appear to work and then fail in the browser; see the note
  under *Sign in*.

## Enable the console

Add these two lines to the `keycloak` service in `docker-compose.yml`, directly
under the existing `# Admin console not published.` comment:

```yaml
    ports:
      - "127.0.0.1:8080:8080"
```

Then recreate the service:

```bash
docker compose up -d keycloak
```

Open <http://127.0.0.1:8080/auth/admin/>.

> **The `127.0.0.1:` prefix is required.** Do not use `"8080:8080"` — that
> publishes the console on every interface, which is exactly what this default
> exists to prevent.

## Sign in

| Field | Value |
|---|---|
| Username | `admin` |
| Password | the `DEV_KEYCLOAK_ADMIN_PASSWORD` value in `.env` |

To read the password without printing it to your terminal history or scrollback:

```bash
grep '^DEV_KEYCLOAK_ADMIN_PASSWORD=' .env
```

`DEV_KEYCLOAK_ADMIN_PASSWORD` is the **Keycloak console** account, in the
`master` realm. It has no application roles and cannot sign into the app. That is
a different credential from `DEV_WBA_ADMIN_PASSWORD`, which is the `dev-admin`
**application** login in the `wba` realm. The names are similar on purpose — see
the *Keycloak credentials* table in `INSTALL_GUIDE.md`.

> ### `dev-admin` cannot sign in here — use the account console
>
> This console authenticates against the **`master` realm only**, so the only
> account that works on it is `admin`. The `wba`-realm users (`dev-admin`,
> `dev-user`) are not in `master` at all, and signing in with them fails with
> *Invalid username or password* no matter what you type — including the correct
> password. The error text is deliberately identical for a wrong password and a
> non-existent user, so it reads as a password problem when it is a realm one.
>
> To sign in as an application user, use the **account** console instead — and
> note the different host:
>
> <https://localhost/auth/realms/wba/account>
>
> **Use `https://localhost`, not this guide's loopback address.** The account
> console lives on the public origin (`KC_HOSTNAME`), while this admin console
> lives on the loopback origin (`KC_HOSTNAME_ADMIN`) — that split is what lets
> the admin surface stay unpublished. Opening the account console on the
> loopback port fails with *"Timeout when waiting for 3rd party check iframe
> message"*, because the page loads from one origin while its internal iframe
> targets the other. The account console also needs **no published port**: nginx
> proxies `/auth/realms/*` for it.

> ### Known limitation: the account console's data calls return `401`
>
> Signing in works and the page renders, but its data calls fail:
>
> ```
> GET /auth/realms/wba/account/supportedLocales                     401
> GET /auth/realms/wba/account/?userProfileMetadata=true            401
> ```
>
> **This is a real server-side rejection, not browser state.** Clearing site
> data or using a private window does not fix it. Confirmed 2026-10-31 against
> Keycloak 26.8.1:
>
> - The requests carry a valid `Authorization: Bearer` header, and the token
>   decodes correctly (`iss` = `https://localhost/auth/realms/wba`, not expired).
> - The differentiator is `Content-Type: application/json` on the GET, which
>   routes it to the account **REST API** rather than the HTML shell. Without
>   that header the same URL returns `200` — but that is the public SPA shell,
>   not data, so a `200` there proves nothing.
> - The token carries **no `aud` claim**, and realm `wba` contains **no audience
>   mapper** to add one. The Keycloak-created `master` realm has none either, so
>   this is not caused by importing our realm template.
> - Reproduced against `keycloak:8080` directly from inside the container, so
>   nginx is not involved.
>
> **Unresolved:** why a stock `account-console` token lacks the `account`
> audience here. A candidate fix is an `oidc-audience-mapper` (included client
> audience `account`) on the `account-console` client in
> `deploy/keycloak/realm-wba.json.template` — unproven.
>
> **Impact: none on the application.** Nothing in this repo calls
> `/realms/wba/account`; the app's own login is the BFF flow, not this console.
> The console exists only to inspect a session by eye — use the admin console
> (above) for that instead, or decode a token.

## If the sign-in does not work

The bootstrap admin is created **only on the very first boot against an empty
Keycloak database**. It is a one-shot seed, not a reconciler — so:

- Changing `DEV_KEYCLOAK_ADMIN_PASSWORD` in `.env` does **not** change the
  existing admin's password.
- If your Keycloak database was created before this variable existed, the admin
  account may not be present at all, and the console will load but reject every
  login.

The recovery command creates the account without putting the password on the
command line — it reads it from the container's own environment:

```bash
docker compose exec keycloak /opt/keycloak/bin/kc.sh bootstrap-admin user \
  --username admin --password:env KC_BOOTSTRAP_ADMIN_PASSWORD --no-prompt
```

Then sign in as `admin` with the `DEV_KEYCLOAK_ADMIN_PASSWORD` value from `.env`.

## Applying a realm change

### Why editing the template is not enough

The realm is imported on the very first boot against an empty Keycloak
database. `--import-realm` is **create-only**: it imports a realm that does not
exist and *skips* one that already does. Editing
`deploy/keycloak/realm-wba.json.template` therefore has no effect on a stack
that is already running — the file on disk says one thing, the live realm says
another, and nothing errors to tell you.

The symptom is silent. Compare the template against the running realm:

```bash
docker exec wba-ai-keycloak /opt/keycloak/bin/kcadm.sh get realms/wba
```

If what you edited is not in that output, the change has not been delivered.
Restarting Keycloak does not help either — the realm already exists, so the
import is skipped again.

### The normal path: re-seed the realm

There is no runtime reconcile step. The realm holds nothing but the seeded
`dev-*` users and is derived entirely from the template, so delivering a template
edit means recreating the Keycloak database and letting the next boot import it:

```bash
docker compose stop keycloak
docker compose exec -T postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c 'DROP DATABASE keycloak;'
docker compose exec -T postgres createdb -U "$POSTGRES_USER" -O keycloak keycloak
docker compose up -d keycloak
```

The next boot sees an empty database, so `--import-realm` imports the current
template in full. Every fact the template declares is delivered — not just the
ones a script happened to know about.

**This is destructive.** It destroys every user, group, session and client
secret in the realm and causes a full authentication outage while it runs. That
is an acceptable trade **only** on a local dev stack. It is **never** appropriate
against an environment with real users — see "When re-seeding is not acceptable"
below.

This drops **only** the `keycloak` database. The application's own database is a
separate one on the same server and is not touched.

### The console is not a source of truth

You can change anything you like through the admin console, and the change is
live immediately. That is useful for trying a setting before committing to it.
But the console change is invisible to the template, so:

- It is lost the next time the realm is re-seeded.
- Any other deployment built from the template never sees it.

Treat the console as a scratchpad. Once you know the value you want, put it in
`deploy/keycloak/realm-wba.json.template` and re-seed.

> **Editing the template on its own does nothing.** Re-seeding is the step that
> delivers it. An edit that has not been re-seeded has not been applied.

### When re-seeding is not acceptable

Re-seeding is the right answer for this dev stack and the wrong answer for any
environment with real users, sessions or client secrets. No non-destructive
delivery path is configured today, and **one must be added before this stack is
deployed anywhere the realm needs to survive.**

The usual choice is the official Terraform provider for Keycloak — declarative,
idempotent, and versioned in lockstep with Keycloak. Do not hand-edit the console
on such an environment in the meantime: the template would silently stop
describing the realm.

### Verify a change

After any realm change, confirm the running realm carries it. For the audience
mapper:

```bash
docker exec wba-ai-keycloak /opt/keycloak/bin/kcadm.sh get clients -r wba \
  -q clientId=wba-web --fields 'id,clientId,protocolMappers' --format json
```

The JSON must contain a `wba-web-audience` entry whose
`"included.client.audience"` is `"wba-web"`. Use the same shape to check any
other change you made — read the field you changed back from the running realm
and compare it to the template.

## Disable the console again

Remove the two `ports:` lines you added and recreate the service:

```bash
docker compose up -d keycloak
```

Confirm nothing is published:

```bash
docker compose config | grep -c 'target: 8080'   # → 0
```

Leaving the console closed is the intended steady state. Enable it when you need
it, close it when you are done.

## What is not in this guide

The realm is **code**, not console state: roles, clients, token lifetimes and the
seeded dev users all come from `deploy/keycloak/realm-wba.json.template` and are
imported on boot. Edits made in the console are not persisted back to the
template and will be lost when the realm is re-imported — so for anything that
should survive, change the template instead and re-import.

For the application side — how the API validates tokens, what the roles mean, and
how `wba-web` / `wba-internal` are used — see
`docs/design/authn-authz-design.md`.

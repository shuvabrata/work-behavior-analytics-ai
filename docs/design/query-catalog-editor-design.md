# Query Catalog Editor Design

**Audience:** Developers extending, debugging, or maintaining the user-defined
query catalog layer and the Library UI.
**Status:** Implemented. Landed on branch `feature/query-editor` (PR #318).
**Related docs:** [`design-system.md`](design-system.md) (UI tokens),
[`frontend-design-skill.md`](frontend-design-skill.md) (Executive Dashboard
aesthetic), [`high-level-design.md`](high-level-design.md) (system overview),
[`runtime-settings-design.md`](runtime-settings-design.md) (the runtime-mutable
settings layer this feature borrows UI patterns from).

---

## Table of Contents

1. [Overview](#1-overview)
2. [Goals and non-goals](#2-goals-and-non-goals)
3. [Catalog anatomy](#3-catalog-anatomy)
4. [The overlay model](#4-the-overlay-model)
5. [Query origin taxonomy](#5-query-origin-taxonomy)
6. [Read path](#6-read-path)
7. [Write model and API contract](#7-write-model-and-api-contract)
8. [Read-only enforcement](#8-read-only-enforcement)
9. [Namespace management](#9-namespace-management)
10. [On-disk format](#10-on-disk-format)
11. [Persistence and deployment model](#11-persistence-and-deployment-model)
12. [Library UI design](#12-library-ui-design)
13. [Error handling and status mapping](#13-error-handling-and-status-mapping)
14. [Key design decisions and rationale](#14-key-design-decisions-and-rationale)
15. [Known limitations and future work](#15-known-limitations-and-future-work)
16. [Testing strategy](#16-testing-strategy)

---

## 1. Overview

The query catalog is the app's library of Cypher queries — used by the graph
workbench, the AI augmentation chains, and any page that executes a named
query. Historically it was **read-only**: a set of YAML files shipped with the
app that users could browse and favourite but not change.

This feature adds a **user-defined overlay**: users can edit an existing
catalog query, create new queries in an existing or custom namespace, test a
Cypher variant without leaving the app, and reset any override back to its
factory version.

The central design choice is that the overlay is **merged at load time** inside
the catalog loader, not stored separately and not reconciled per consumer.
Every consumer that already reads the catalog through `load_catalog()` picks up
user edits with **no changes to its own code**.

The UI adds a **Library** page (listing, filter, search) and a full **query
editor** (metadata, tabular/graph Cypher, parameters, save / save-as / test /
reset).

---

## 2. Goals and non-goals

**Goals**

- Let a user override any built-in catalog query without editing shipped files.
- Let a user add new queries in existing namespaces or in new custom namespaces.
- Let a user reset an override to the factory version, or delete a query they added.
- Let a user test a Cypher variant against Neo4j from inside the editor.
- Require **zero** changes to existing catalog consumers for them to see the edits.

**Non-goals**

- A database-backed query store. The catalog remains filesystem/YAML.
- Multi-user isolation, sharing, or per-user catalogs. Deployment is
  single-user, self-hosted, trusted — no auth, no tenancy.
- Collaborative editing, versioning, or an audit trail of catalog changes.
- Editing the **system** catalog in place. Shipped queries are immutable; all
  user changes live in a separate overlay tree.
- A generic Cypher IDE. The editor is scoped to catalog queries plus a raw
  "Test" runner.

---

## 3. Catalog anatomy

The catalog lives in `queries_catalog/` and has two disjoint trees:

```text
queries_catalog/
├── catalog.yaml                 # master namespace registry (system)
├── <namespace>/                 # one directory per namespace
│   └── <slug>.yaml              # one file per query
└── user_defined/                # user overlay (created on first save)
    ├── catalog.yaml             # registry for custom user namespaces only
    └── <namespace>/             # mirrors the system layout
        └── <slug>.yaml
```

- **System tree** — shipped with the app, baked into the image, read-only at
  runtime. A query's identity is `id = "<namespace-directory>/<file-stem>"`.
- **User overlay** — everything under `user_defined/`. It may shadow a system
  query (same `id`, placed under the same namespace directory) or introduce a
  new query in a system namespace or a brand-new custom namespace.

The two trees are never merged on disk. They are merged **in memory** at load
time (Section 4), so the overlay is fully disposable and the system catalog
stays pristine.

---

## 4. The overlay model

`load_catalog()` is the single merge point. Its design shape:

```text
load_catalog(catalog_dir, validate_cypher=True) -> list[CatalogQuery]

  namespaces = load_namespaces(catalog_dir)      # system + user, merged
  system  = load every *.yaml from non-user namespaces, de-duped by id
  user    = load every *.yaml from every namespace's user_defined/ subdir,
            de-duped by id within the user set

  if user_defined/ does not exist:  return system (unchanged)
  else: merge user over system, keyed by id
          - id already present  -> user entry REPLACES the system entry
          - id not present      -> user entry is APPENDED

  return sorted(results, key=(namespace.order, name.lower()))
```

Design constraints this encodes:

- **The system de-dup guard must not reject user overrides.** System loading
  keeps its "duplicate id" guard; the user merge is a *separate post-pass*.
  Replace-by-id is the whole point, so the guard must not run across the two
  sets. Duplicate ids *within* the user set are still an error.
- **Sorting is unchanged.** The merged list is sorted by namespace order then
  query name, so a user override sorts **among** its namespace peers by name
  rather than being forced to the end. Do not special-case user queries in the
  sort.
- **`user_defined/` subdirectories are scanned for every namespace**, because
  an override of a system query lives at `user_defined/<system-namespace>/`,
  exactly mirroring the system path.
- **Load-time validation is retained.** User files go through the same
  `_load_query_file` path as system files, so a hand-edited override is
  validated (schema, path-safe slug, read-only Cypher) at the next load.

`load_namespaces()` merges the user namespace registry: system namespaces come
from `catalog.yaml`; user namespaces come from `user_defined/catalog.yaml` and
are appended with an `order` continuing from the system list.

---

## 5. Query origin taxonomy

Every loaded query carries an `origin` field:

| Origin | Meaning |
|---|---|
| `builtin` | Shipped in the system catalog, not overridden. |
| `override` | A user file whose `id` matches a system query. |
| `custom` | A user file with a new `id` (new query, any namespace). |

**`origin` is computed by the loader**, during the merge, because the loader is
the only place that simultaneously knows the system set and the user set. This
keeps path logic out of API consumers and out of the UI: the listing and editor
read a single field instead of inferring intent from `source_path` strings.

`source_path` is still populated (relative to `queries_catalog/`'s parent, e.g.
`queries_catalog/user_defined/github/foo.yaml`) for diagnostics, but `origin`
is the discriminator the UI branches on.

---

## 6. Read path

The read API (`service.py` → `query.py` → `loader.py`) is **untouched by this
feature**. It already funnels through `load_catalog()` and `load_namespaces()`,
so:

- `GET /api/v1/queries/catalog` returns the merged list.
- `GET /api/v1/queries/catalog/{namespace}/{slug}` returns the merged entry.
- `GET /api/v1/queries/catalog/namespaces` returns system + user namespaces.

The **only** read-path change is the additive `origin` field on `CatalogQuery`
and `is_user_defined` on `CatalogNamespace`. The existing response shape is
otherwise preserved; clients that ignore the new fields are unaffected.

> **Invariant worth protecting:** any future consumer that reads catalog YAML
> files *directly*, bypassing `load_catalog()`, will silently miss user
> overrides. New catalog consumers must go through the loader.

---

## 7. Write model and API contract

### Two models, one read and one write

`CatalogQuery` is the **normalized read model**: it requires derived fields
(`id`, `slug`, `namespace`, `available_views`, `source_path`) and forbids
extras. It therefore **cannot** be reused as a request body.

`CatalogQueryWrite` is the **write-side model** and is the PUT body. It holds
only author-supplied fields:

| Field | Notes |
|---|---|
| `name` | required, non-empty |
| `description` | required, non-empty |
| `summary` | optional |
| `queries` | `dict[CatalogView, str]`, ≥1 non-empty variant |
| `parameters` | list of `CatalogParameter`, default `[]` |
| `tags` | `list[str]`, default `[]` |
| `owner` | optional |
| `status` | `active` / `draft` / `deprecated`, optional |
| `default_view` | `tabular` / `graph`; must be a key in `queries` if set |

Both models forbid extra fields, so a client cannot smuggle in derived fields.
The loader derives identity and view metadata from the path and the file
content; the write service persists only author-supplied fields.

### Endpoints

| Method | Path | Body | Success | Failure |
|---|---|---|---|---|
| `GET` | `/api/v1/queries/catalog` | — | `200` merged list + `origin` | — |
| `GET` | `/api/v1/queries/catalog/namespaces` | — | `200` list + `is_user_defined` | — |
| `GET` | `/api/v1/queries/catalog/{ns}/{slug}` | — | `200` `CatalogQuery` | `404` unknown |
| `PUT` | `/api/v1/queries/catalog/{ns}/{slug}` | `CatalogQueryWrite` | `200` saved `CatalogQuery` | `422` invalid |
| `DELETE` | `/api/v1/queries/catalog/{ns}/{slug}` | — | `200` message, or `204` if no override existed | — |

The PUT endpoint is upsert-only on the **overlay tree** — it never writes to the
system tree, and the path's `{ns}/{slug}` is authoritative (it is not taken from
the body). A PUT to an existing override overwrites it; a PUT to a new id
creates it. The response is the merged query as re-loaded by the loader, so the
client sees exactly what a subsequent GET would return.

The write service owns all file I/O under `user_defined/`. It is synchronous
and is invoked from the async router via a worker thread, matching the pattern
used by the graph execute endpoint. Keeping file I/O in a dedicated module
leaves the read service (`service.py` / `query.py`) free of write concerns.

---

## 8. Read-only enforcement

The catalog must never be able to mutate the graph. Read-only is enforced in
**two** places, deliberately:

1. **At load** — `_load_query_file` rejects any file whose Cypher is not
   read-only, so a hand-edited YAML that bypasses the API still cannot load.
2. **At write** — the PUT path validates every variant with the same
   `validate_read_only_query()` before writing, so the error is surfaced as a
   `422` at authoring time rather than as a load failure later.

Both call the same predicate from the graph API (`CREATE`, `MERGE`, `DELETE`,
`DETACH`, `SET`, `REMOVE`, `DROP`, `FOREACH`, and the APOC write procedures are
rejected). The editor's "Test" runner additionally executes through the
existing graph endpoint under `source="raw"`, which applies the same guard.

---

## 9. Namespace management

`CatalogNamespace` gains an `is_user_defined` flag:

- `False` — a system namespace declared in the shipped `catalog.yaml`.
- `True` — a user namespace declared in `user_defined/catalog.yaml`.

The flag is the **single discriminator** for namespace provenance and is used
by the write service to decide whether a namespace registry entry needs
creating. It is exposed in the namespaces API so the UI can render System vs
user namespaces without re-deriving it.

**Auto-declaration.** When a query is saved into a namespace that does not exist
in *either* registry, the write service creates `user_defined/catalog.yaml` (if
absent) and appends a namespace entry whose display name is the directory with
underscores replaced by spaces, title-cased (`my_queries` → `My Queries`). Saving
into a system namespace or an already-declared user namespace needs no registry
change.

**Path safety.** Namespace directories and query slugs are both validated
against a single regex (`^[a-zA-Z0-9][a-zA-Z0-9_]*$` — must start
alphanumeric, then alphanumerics/underscore). It is applied on read (filename →
slug) and on write (path params), so path traversal and odd characters are
impossible by construction rather than by escaping. Note this allows **mixed
case**, a deliberate widening from an earlier lowercase-only draft.

---

## 10. On-disk format

An override file uses the same YAML schema as a system file, with only the
author-supplied fields — `id`, `slug`, `namespace`, `available_views`, and
`source_path` are **derived at load and never written**:

```yaml
# queries_catalog/user_defined/hall_of_fame/top_n_committers.yaml
name: Top N Committers
description: Most active committers, ranked.
summary: Ranked contributors
queries:
  tabular: MATCH (p:Person) RETURN p.name AS name LIMIT 25
  graph: MATCH (p:Person) RETURN p LIMIT 25
parameters:
  - name: limit
    required: true
    type: string
tags: [github, analytics]
status: active
default_view: tabular
```

YAML is dumped with `default_flow_style=False` and `sort_keys=False` so the
file is stable and human-diffable. Writing only author fields keeps the file
self-describing and prevents a saved file from asserting an identity that
disagrees with its own path.

---

## 11. Persistence and deployment model

The overlay is a **runtime artifact of a single-user, self-hosted instance**,
not part of the shipped code:

- **System catalog is read-only in the image.** `Dockerfile.app` copies
  `queries_catalog/`, chowns it to root, and removes write permission, so the
  running app cannot modify shipped queries.
- **Only `user_defined/` is writable.** The image pre-creates it owned by the
  app user (before the read-only pass) so a mounted volume inherits writable
  ownership on first mount.
- **`user_defined/` is a named volume.** `docker-compose.yml` mounts
  `catalog_user_defined` at `/app/queries_catalog/user_defined`, so overrides
  survive container rebuilds and image updates.
- **`user_defined/` is gitignored.** Overrides are local to the instance and
  must never be committed.

This shape is what makes "system catalog is immutable, overlay is disposable"
true at the filesystem level, not just by convention.

---

## 12. Library UI design

### Routes

| Route | Renders |
|---|---|
| `/app/library` | Listing page |
| `/app/library/new` | Blank editor |
| `/app/library/edit/{namespace}/{slug}` | Editor for an existing query |

The sidebar gains a **Library** entry (book icon) between Analytics and
Connectors. `display_page` matches the listing exactly and matches *any*
`/app/library/...` prefix to the editor, so `/new` and `/edit/...` share one
layout. The editor itself branches on the pathname: `/new` starts blank; an
edit path fetches the query and populates the form.

### Listing page

- **Filter bar:** namespace dropdown (default "All namespaces") and a search
  input that matches across all columns (name, id, summary, owner, status,
  default view, tags, origin).
- **Columns:** Name, Summary, Tags (chips), Status, Default View, Parameters
  (count), Views (tabular/graph icons), Origin (badge), Actions.
- **Badge rules:** `builtin` origin and `active` status render as plain text;
  `override` / `custom` origin and `draft` / `deprecated` status render as
  coloured badges, so colour draws the eye to what is non-default.
- **Rows navigate to the editor.** There is no destructive action on the
  listing — reset and delete live in the editor (see below).
- **Client-side rendering.** The table body is built in JavaScript from a raw
  catalog payload held in a `dcc.Store`, not by Dash components. Filtering and
  search are therefore instant and page load does not pay Dash's
  per-component cost for 140+ rows. Only the header row exists in the Dash
  layout.

### Editor

One layout serves both `/new` and `/edit`, with two collapsible sections and a
sticky action bar:

- **Action bar (sticky):** `Save` (visible only in edit mode — a namespace and
  key must exist to save), `Save As`, the query identifier (namespace + key) in
  the centre, and **one** destructive action whose label and visibility derive
  from `origin`:
  - `override` → **Reset to Factory**
  - `custom` → **Delete**
  - `builtin` → hidden (only transiently visible after a reset)

  Both variants use `color="outline-danger"` and sit behind a two-stage
  `dcc.ConfirmDialog` (click → dialog → confirm), with a message that names the
  query and states "This cannot be undone."
- **Metadata section:** name, owner, status (dropdown), summary, tags
  (comma-separated), description.
- **Queries section:** two monospace textareas, **Tabular Query** and
  **Graph Query**, each with its **own** Test button (`Test Tabular`,
  `Test Graph`) so there is never ambiguity about which variant is being
  exercised. Below them: the parameter list (add/remove rows of
  name/label/type/required/placeholder/description/env_var) and the
  Default View radio, restricted to the views that actually have Cypher.
- **Save As modal:** namespace dropdown (with a "+ New namespace…" option that
  reveals a free-text namespace input) plus a key input. This is how a new
  query is created, and how an existing one is copied to a new id.

### Behaviour of the destructive action

- **Override → Reset:** delete the overlay file, then **reload the form** with
  the factory data, because the built-in version survives underneath.
- **Custom → Delete:** delete the overlay file, then **navigate back to the
  listing**, because there is no factory version to fall back to.

### Testing a query

`Test Tabular` / `Test Graph` POST the textarea's Cypher to
`/api/v1/graph/execute` as `source="raw"`, `view="auto"` and render the result
in an inline pane: a table for tabular results, a summary alert for graph
results. This requires a live Neo4j; a down or unreachable graph surfaces as an
error alert, not a crash.

UI conventions follow the repo's mandatory standards: `outline-danger` for
destructive buttons, a dedicated dismissable feedback region near the top
(errors persist, successes auto-dismiss), and text-only collapsible headers
using the shared `collapse-toggle-subtle` class.

---

## 13. Error handling and status mapping

| Condition | Surface |
|---|---|
| Invalid namespace/slug segment | `422` (write service raises `ValueError`, router maps it) |
| Non-read-only Cypher in a PUT | `422` with the offending view named |
| Missing/invalid body fields | `422` (Pydantic validation on `CatalogQueryWrite`) |
| GET of an unknown query | `404` |
| DELETE with no override present | `204` (idempotent — not an error) |
| Written YAML fails to reload | `500` (`CatalogLoadError` propagates) |
| Malformed/hand-edited overlay file at load | `CatalogLoadError` naming the file |

A written file is **re-loaded before responding**, so a save that would produce
an unloadable catalog fails loudly at save time rather than silently poisoning
later reads.

---

## 14. Key design decisions and rationale

1. **Overlay in the loader, not a separate store or per-consumer merge.**
   *Why:* one merge point means every existing consumer gets user edits for
   free, and there is exactly one place that can be wrong. *Rejected:* a
   DB-backed query table (duplicates the catalog, needs migration/sync) and
   per-consumer overlay logic (N places to keep consistent).

2. **Replace-by-id override, interleaved sort.**
   *Why:* an override must be invisible to callers — same id, same namespace
   slot, sorted by name like its peers. *Rejected:* appending user queries to
   the end of a namespace (surprising ordering, and the merged list would differ
   between "override" and "new" for no reason).

3. **`origin` computed by the loader.**
   *Why:* only the loader sees both sets, so it is the correct — and only
   correct — place to classify a query as builtin/override/custom. *Rejected:*
   consumers string-matching `source_path`, which conflates "all user rows" with
   "overrides".

4. **A dedicated write model (`CatalogQueryWrite`), not `CatalogQuery`.**
   *Why:* the read model requires derived fields and forbids extras; reusing it
   would force clients to send identity fields the server must then ignore or
   verify. *Rejected:* making derived fields optional on `CatalogQuery` (blurs
   the contract and weakens validation for readers).

5. **Writes in a dedicated service module; read service untouched.**
   *Why:* clean separation keeps the read path free of file-mutation concerns
   and keeps the diff to the read layers near-zero (only additive fields).

6. **Filesystem/YAML as the store.**
   *Why:* the catalog is code that ships with the app and benefits from being
   diffable and reviewable; overrides are local and disposable in a
   single-user, trusted deployment. *Rejected:* a database store (heavier,
   needs migration + sync with the shipped YAML).

7. **Read-only enforced at load *and* write.**
   *Why:* the API guard stops accidental writes at authoring time; the load
   guard stops a hand-edited file from ever executing. Defence in depth for a
   property the catalog depends on absolutely.

8. **Namespace provenance as an explicit flag (`is_user_defined`).**
   *Why:* the write service and the UI both need to know whether a namespace is
   system or user, and deriving it from path prefixes would repeat the same
   string logic in several places.

9. **Destructive actions live in the editor, not the listing.**
   *Why:* reset/delete are consequential and belong next to the content being
   affected, behind a confirmation that names the query. *Rejected:* per-row
   destructive buttons in the listing (easy to misfire on a dense table).

10. **`origin` drives the destructive label (Reset vs Delete).**
    *Why:* an override has a factory fallback and a custom query does not —
    the label and the follow-up behaviour (reload vs navigate) must match that
    reality rather than offering one ambiguous verb.

11. **Client-side table rendering.**
    *Why:* 140+ Dash rows made the listing slow to render; building the rows in
    the browser makes filtering/search instant and keeps the page light.
    *Trade-off:* the row markup lives in a JS callback string
    (`callbacks.py`), so it is tested indirectly rather than as Dash components.

12. **Two Test buttons, one per variant.**
    *Why:* a single "Test" button leaves it ambiguous which textarea runs;
    binding each button to its own textarea removes the ambiguity entirely.

13. **Mixed-case-safe id regex.**
    *Why:* slug and namespace segments allow both cases
    (`^[a-zA-Z0-9][a-zA-Z0-9_]*$`), widening an earlier lowercase-only draft.
    Traversal is still impossible because the pattern admits no separators or
    dots.

---

## 15. Known limitations and future work

- **No concurrency control.** Saves are last-write-wins on the filesystem. If
  the API ever gains concurrent writers, add a lock or an optimistic-concurrency
  check.
- **Orphaned user namespaces.** Deleting the last query in a custom namespace
  leaves its registry entry in `user_defined/catalog.yaml`. Harmless (zero
  queries at load) but accumulates; a cleanup pass could prune empty user
  namespaces.
- **Overrides are instance-local.** They live on a named volume and are
  gitignored — not shared, synced, or backed up by the app.
- **Direct YAML readers bypass the overlay.** Any future consumer that reads
  catalog files without going through `load_catalog()` will miss user edits.
- **`Test` needs a live Neo4j.** Offline or down, it degrades to an error
  alert.
- **Duplicated id regex.** The same pattern exists in both `loader.py` and
  `model.py`; the loader's copy is the canonical one for the write path.
  Consolidating them would remove a drift risk.
- **No edit-time conflict check.** Save As onto an existing id overwrites it
  without a distinct "already exists" confirmation.

---

## 16. Testing strategy

Design-level expectations for anything touching this feature:

- **Merge semantics are tested against synthetic catalogs** built in a temp
  directory, not the real `queries_catalog/` — so override/add/no-op cases are
  deterministic and independent of local state.
- **Tests that hit the real catalog must clean up after themselves.** The
  catalog-cardinality assertions elsewhere in the suite assume no overrides are
  present at test time; any test that PUTs a query must DELETE it before it
  ends. Only temp-directory merge tests are immune.
- **UI callback tests mock HTTP** and assert on request URL and payload, so
  they run without Neo4j or a live server. The "Test" paths are covered by
  mocking the graph execute endpoint.
- **Route parsing is tested for both** `/app/library/new` and
  `/app/library/edit/{ns}/{slug}`, including trailing slashes.

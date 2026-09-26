# Query Catalog Editor — Implementation Plan

## 1. Sidebar & Routing

| Item | Detail |
|---|---|
| **Nav entry** | Between **Analytics** and **Connectors** — `fas fa-book` icon, "Library" label, href `/app/library` |
| **Listing page** | `/app/library` — table of all queries with filter + search |
| **Editor (edit)** | `/app/library/edit/{namespace}/{slug}` — opens in a **new browser tab** via `window.open` |
| **Editor (new)** | `/app/library/new` — opens in a **new browser tab**, blank form |

### Page routing (in `src/app/dash_app/layout.py`)
- Add `/app/library` → `library.get_layout()`
- Add `/app/library/edit/...` and `/app/library/new` → `library.get_editor_layout()` (or dispatch)
- Add `/app/library` as a wildcard route prefix to catch sub-paths

## 2. File Structure for New Code

```
src/app/
├── api/queries/v1/
│   ├── router.py                        # + new PUT, DELETE routes
│   ├── user_defined_service.py          # NEW: file I/O for user_defined/ writes/deletes
│   └── ...existing files...
├── dash_app/pages/
│   └── library/                         # NEW: full page package
│       ├── __init__.py                  # exports get_layout, get_editor_layout
│       ├── layout.py                    # listing page layout
│       ├── editor_layout.py             # editor page layout (shared by edit/new)
│       ├── callbacks.py                 # listing callbacks (load, filter, search, window.open)
│       └── editor_callbacks.py          # editor callbacks (save, save-as, test, reset)
├── dash_app/layout.py                   # + Library nav link, + /app/library routing
└── query_catalog/
    ├── loader.py                        # + user_defined merge logic
    └── ...existing files...
queries_catalog/
    └── user_defined/                    # NEW: created on first save
        └── catalog.yaml                 # optional custom user namespaces
```

## 3. Listing Page (`/app/library`)

### Data Source
- `GET /api/v1/queries/catalog` — fetches all (now merged) queries
- `GET /api/v1/queries/catalog/namespaces` — populates namespace dropdown

### Layout
- **Top bar**: "New Query" button (→ `window.open("/app/library/new")`) + namespace dropdown + search input
- **Table columns**: Name, Namespace, Tags (as chips), Status (badge), Views (tabular/graph icon indicators)
- **Clicking a row**: selects the query → actions become available
- **Per-row actions**: "Edit" button (→ `window.open` to editor in new tab) + "Reset to factory" button (→ `DELETE` API; only visible if `source_path` contains `user_defined/`)

### Key Callbacks
| Trigger | Action |
|---|---|
| `dcc.Location` pathname == `/app/library` | Fetch catalog → render table |
| Namespace dropdown change | Client-side filter rows |
| Search input change | Client-side filter rows by name, tags, id |
| "Edit" click (clientside) | `window.open("/app/library/edit/{ns}/{slug}")` |
| "New Query" click (clientside) | `window.open("/app/library/new")` |
| "Reset to factory" click | `ConfirmDialog` → `DELETE /api/v1/queries/catalog/{ns}/{slug}` → refresh table → alert |

### Reset confirmation dialog messages
```
"Are you sure you want to reset '{name}' to factory defaults?
This will discard all user edits for this query. This cannot be undone."
```

## 4. Editor Page (`/app/library/edit/{namespace}/{slug}`)

### Data Source
- `GET /api/v1/queries/catalog/{namespace}/{slug}` — loads query on page mount

### Layout
- **Read-only info bar**: `id` (namespace/slug), namespace name — displayed as muted text
- **Editable fields** (grouped visually):
  - **Metadata**: name (text), description (textarea), summary (textarea), owner (text), status (dropdown: active/draft/deprecated), tags (free-form tag input)
  - **Queries**: Two side-by-side code editors labeled "Tabular Query" and "Graph Query" — each a monospace `dbc.Textarea` (or `<textarea>` with `font-family: monospace`). If only one view exists, show a single editor with a label indicating which view
  - **Parameters**: List of parameter rows. Each row: name (text), label (text), type (dropdown: string/person_id), required (checkbox), placeholder (text), description (textarea), env_var (text). "Add parameter" button appends a new blank row. "Remove" button per row
  - **Default view**: Radio buttons (tabular/graph) — only options for which Cypher is non-empty
- **Action buttons** (bottom of form or sticky footer):
  - **Save** → `PUT /api/v1/queries/catalog/{namespace}/{slug}` with current form data
  - **Save As** → Modal asking for Namespace (dropdown + custom input) + Slug (text input) → `PUT` to new id
  - **Test** → `POST /api/v1/graph/execute` with current Cypher text as `source=raw` → render results in inline pane (mini table or basic graph view)
  - **Reset to Factory** → `ConfirmDialog` → `DELETE /api/v1/queries/catalog/{namespace}/{slug}` → reload page with system data

### Editor confirmation dialog messages
```
Reset to Factory: "Reset '{name}' to factory defaults? All user edits will be lost. This cannot be undone."
```

## 5. New Query Page (`/app/library/new`)

- Same editor layout as `/app/library/edit/...` but all fields start blank/empty
- Slug and Namespace fields are editable (they appear in the "Save As"-style selector)
- No "Reset to Factory" button
- "Save As" is the primary save action (since there's no existing id to PUT to)

## 6. New API Endpoints

### `PUT /api/v1/queries/catalog/{namespace}/{slug}` — Save/override a query
- **Request body** — Serialized `CatalogQuery` fields (name, description, summary, queries, parameters, tags, owner, status, default_view)
- **Validation**:
  1. `slug` and `namespace` directory must match path params (if editing existing)
  2. For new queries: slug + namespace validated as safe path segments
  3. All required fields present (name, description, at least one Cypher query)
  4. Cypher validated read-only via `validate_read_only_query()`
  5. Status must be valid enum value
- **Action**: Write YAML file to `queries_catalog/user_defined/{namespace}/{slug}.yaml`
- **Response**: 200 with the saved query metadata (mirrors `CatalogQuery`)
- **New namespaces**: If namespace doesn't exist in system catalog, auto-create a `catalog.yaml` under `user_defined/` if not present, append the new namespace, save

### `DELETE /api/v1/queries/catalog/{namespace}/{slug}` — Reset to factory
- **Action**: Delete `queries_catalog/user_defined/{namespace}/{slug}.yaml` if it exists
- **Response**: 200 + success message if file deleted; 204 No Content if no user override existed

### Implementation location
New file `src/app/api/queries/v1/user_defined_service.py` — keeps file I/O concerns separate from the existing read-only service.

## 7. Merge Logic (in `src/app/query_catalog/loader.py`)

### Algorithm
```
load_catalog(catalog_dir):
  1. Load system queries from catalog_dir (excluding user_defined/ subdirectory)
  2. Check for catalog_dir / user_defined/
  3. If user_defined/ doesn't exist or is empty:
       return system queries (unchanged)
  4. Load user namespaces from user_defined/catalog.yaml (if exists)
     → append them to system namespace list
  5. Load user queries from user_defined/ (with user namespaces as valid targets)
  6. Merge:
     - Build a dict keyed by query.id from system queries
     - For each user query:
       - If same id exists in system dict: REPLACE that entry (file-level override)
       - If new id: APPEND to the list
     - Preserve system namespace order; append user queries at end of their namespace
     - user-defined custom namespace queries appear after all system namespaces
  7. Return merged list
```

### `source_path` convention
- System queries: `queries_catalog/{namespace}/{slug}.yaml`
- User-defined queries: `queries_catalog/user_defined/{namespace}/{slug}.yaml`
- This is what the listing page checks to determine whether to show "Reset to factory"

### `load_namespaces()` changes
- After loading system namespaces, check `user_defined/catalog.yaml`
- If present, load and append user namespaces with `order` continuing from system max
- Return combined list

## 8. User-Defined File Format

### `queries_catalog/user_defined/catalog.yaml`
```yaml
namespaces:
- name: My Custom Queries
  directory: my_custom_queries
```

### `queries_catalog/user_defined/{namespace}/{slug}.yaml`
Same YAML schema as system query files. The full `CatalogQuery` fields serialized.

## 9. Test Plan

### A. Merge Unit Tests (new `tests/test_query_catalog_merge.py`)

All use `tmp_path` to construct synthetic catalogs.

| # | Test | Fixture setup | Expected |
|---|---|---|---|
| **B1** | No user_defined dir — system only | No `user_defined/` | Returns system queries only, count unchanged |
| **B2** | Empty user_defined dir | Empty `user_defined/` dir | Same as B1 |
| **B3** | User overrides existing system query | System: `hall_of_fame/top_n_committers.yaml`<br>User: `user_defined/hall_of_fame/top_n_committers.yaml` with modified description + Cypher | One merged entry with user's data, `source_path` points to `user_defined/`, system version excluded |
| **B4** | User adds new query in existing namespace | User: `user_defined/hall_of_fame/my_custom.yaml` | 141 queries, new query appended to hall_of_fame namespace |
| **B5** | User adds query in new custom namespace | User: `user_defined/catalog.yaml` with custom ns<br>User: `user_defined/my_stuff/foo.yaml` | 10 namespaces, new query under `my_stuff/` |
| **B6** | Multiple overrides across namespaces | User overrides in github/ + new in cross_domain/ | Each handled correctly, non-overridden queries unchanged |
| **B7** | Duplicate slug in user_defined rejected | Two user files with same id | `CatalogLoadError` |
| **B8** | Delete user override (API) | User file exists → `DELETE` called → file removed | Subsequent GET returns system version |
| **B9** | Delete non-existent override | No user file → `DELETE` called | Returns 204 No Content |
| **B10** | Namespace listing with custom user ns | User `catalog.yaml` with custom namespaces | `list_namespaces()` returns system + user, correct `order` values |

### B. API Integration Tests (extends `tests/test_query_catalog_api_integration.py`)

| # | Test | Call | Expected |
|---|---|---|---|
| **C1** | PUT creates user file | `PUT /api/v1/queries/catalog/hall_of_fame/top_n_committers` with modified body | 200, file created under `user_defined/` |
| **C2** | PUT updates existing user file | PUT again with further changes | 200, file overwritten |
| **C3** | PUT creates new query | PUT to non-existent slug | 200, new file created |
| **C4** | PUT with write Cypher rejected | PUT with `CREATE (n)` in queries | 422 |
| **C5** | PUT missing required fields | PUT without name or queries | 422 |
| **C6** | DELETE removes user file | After PUT, DELETE → subsequent GET | 200 from DELETE, GET shows system version |
| **C7** | DELETE non-existent override | DELETE without prior PUT | 204 |
| **C8** | GET returns merged catalog after override | After PUT override, GET catalog | Shows user version with correct `source_path` |
| **C9** | GET namespaces includes custom user ns | After creating user namespace | 10 entries |

### C. UI Callback Tests (new `tests/test_library_callbacks.py`)

| # | Test | Detail |
|---|---|---|
| **D1** | Table renders with correct columns | Mock `GET /catalog` → check table headers and row data |
| **D2** | Namespace filter works | Select namespace → only matching rows shown |
| **D3** | Search filters client-side | Type in search → rows filtered by name/tags/id |
| **D4** | "Edit" fires `window.open` | Click → correct URL formed |
| **D5** | "New Query" fires `window.open` | Click → `/app/library/new` |
| **D6** | "Reset" button only for user-modified | `source_path` contains `user_defined` → button visible. System → hidden |
| **D7** | "Reset" calls DELETE | Click → ConfirmDialog → confirm → DELETE called → success alert |

### D. Editor Callback Tests (new `tests/test_library_editor_callbacks.py`)

| # | Test | Detail |
|---|---|---|
| **E1** | Editor loads query data | Navigate to edit URL → GET query → form populated |
| **E2** | Save calls PUT | Click Save → PUT with form data → success alert |
| **E3** | Save As modal → PUT to new id | Fill namespace + slug → PUT to new path → success |
| **E4** | Test executes query | Click Test → POST `/api/v1/graph/execute` → results pane shown |
| **E5** | Test with write Cypher shows error | Write `CREATE (n)` → Test → 422 error displayed |
| **E6** | Reset to Factory in editor | ConfirmDialog → DELETE → form reloads with system data |

### E. Existing Test Verifications

| Test | Assertion | Impact of merge |
|---|---|---|
| `test_load_catalog_normalizes_all_existing_entries` | `len(queries) == 140`, `source_path` starts with `queries_catalog/` | If `user_defined/` empty/missing: **count unchanged**, `source_path` still correct. If `user_defined/` has overrides: count may increase. **Safe to run against empty user_defined/** |
| `test_catalog_list_endpoint_returns_normalized_catalog` | `data["count"] == 140` | Same as above. Integration test runs against real catalog. Will remain at 140 unless a user_defined override exists. **Add a note to the test that this count may change when user_defined queries exist** |

### F. Edge Cases

| # | Edge Case | Expected |
|---|---|---|
| **EC1** | `user_defined/catalog.yaml` references non-existent directory | `CatalogLoadError` with clear message |
| **EC2** | Slug collision across namespaces in user_defined | `CatalogLoadError` for duplicate id |
| **EC3** | Save with invalid slug chars (uppercase, spaces) | API returns 422 |
| **EC4** | Concurrent save + reset | Last-write-wins on filesystem; both valid independently |
| **EC5** | Editor loads deleted query | Save returns 404 → "Query no longer exists" alert |
| **EC6** | Save As with existing slug in target namespace | Overwrite with confirmation dialog |

## 10. Implementation Order

1. **`loader.py` — Merge logic** (highest risk, affects everything downstream)
2. **`user_defined_service.py` — PUT / DELETE API endpoints** (depends on merge logic)
3. **`router.py` — Register new routes**
4. **Merge + API tests** (B1–B10, C1–C9)
5. **Library listing page** (`/app/library`): layout + callbacks
6. **Library editor page** (`/app/library/edit/*`): layout + callbacks
7. **Sidebar nav + routing** in `layout.py`
8. **UI callback tests** (D1–D7, E1–E6)
9. **Existing test sensitivity check** — verify no regressions
10. **Edge case manual testing** — file system edge cases
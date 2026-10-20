# Refactor Plan: Rename `NEO4J_ENABLED` / `ELASTICSEARCH_ENABLED`

## Intent

Both Neo4j and Elasticsearch are **mandatory** databases for this app.
The original intent of `NEO4J_ENABLED` / `ELASTICSEARCH_ENABLED` was only to
let the AI agent chains skip lookups into those DBs.
Recent code spread these flags into non-AI-agent code (driver guards, API
routes, UI banners, the consumer sink), implying the DBs could be absent.
This refactor corrects that misuse.

## Decisions (resolved in interview)

| # | Decision | Resolution |
|---|---|---|
| 1 | Non-AI-agent guards | Remove ALL `if not NEO4J_ENABLED` / `if not ELASTICSEARCH_ENABLED` guards outside the AI agent chains |
| 2 | Remaining error handling | Let natural connection errors surface (driver raises, HTTP 5xx). No new flag-based guards. |
| 3 | Rename | `NEO4J_ENABLED` → `NEO4J_AI_LOOKUP_ENABLED`, `ELASTICSEARCH_ENABLED` → `ELASTICSEARCH_AI_LOOKUP_ENABLED` |
| 4 | Old names | Deleted entirely from `settings.py`, `config.py`, settings API model, runtime_settings bridge. No backward-compat aliases. |
| 5 | Python default | Remains `false` (so unit tests don't try to connect). `.env.example` default changes to `true`. |
| 6 | Consumer sink | Remove `ELASTICSEARCH_ENABLED` flag from `elasticsearch_sink.py` entirely. Sink always writes; fails if ES is down. |
| 7 | Alembic | New forward migration that renames the DB settings records and updates descriptions. |
| 8 | Tests | All `@pytest.mark.skipif(not settings.NEO4J_ENABLED/ELASTICSEARCH_ENABLED, ...)` skip gates removed. Tests that need live DBs fail naturally if DBs are absent. Monkeypatches updated to new names. |
| 9 | `RuntimeConfig` | Keep the field but rename it to `NEO4J_AI_LOOKUP_ENABLED`. |
| 10 | AI agent chains | Rename all references inside `chains.py`, `neo4j_chain.py`, `elasticsearch_chain.py`. Behavior unchanged. |
| 11 | Docs | Update `CLAUDE.md`, `.env.example`, `docker-compose.yml`, `DEVELOPER_QUICK_START.md`, `ai_agent_design_workflow.md`, any `plans/*.md` references. |
| 12 | CI | Update `.github/workflows/pr_checks.yml` references. |

---

## File-by-File Changes

### 1. `src/app/settings.py`
- Rename `NEO4J_ENABLED: bool = False` → `NEO4J_AI_LOOKUP_ENABLED: bool = False`
- Rename `ELASTICSEARCH_ENABLED: bool = False` → `ELASTICSEARCH_AI_LOOKUP_ENABLED: bool = False`

### 2. `src/common/runtime_settings/config.py`
- Rename `NEO4J_ENABLED: StrictBool = False` → `NEO4J_AI_LOOKUP_ENABLED: StrictBool = False`

### 3. `src/app/runtime_settings.py`
- Update the `RuntimeConfig(...)` constructor call: `NEO4J_ENABLED=...` → `NEO4J_AI_LOOKUP_ENABLED=app_settings.NEO4J_AI_LOOKUP_ENABLED`

### 4. `src/app/api/settings/v1/models.py`
- Rename `NEO4J_ENABLED: bool = False` → `NEO4J_AI_LOOKUP_ENABLED: bool = False`
- Update field description to: *"Controls whether the AI agent queries Neo4j for context enrichment."*

### 5. `src/app/common/neo4j_driver.py`
- **Remove** lines 39–40 (`if not settings.NEO4J_ENABLED: raise RuntimeError(...)`)
- Update docstring: remove mention of the flag.

### 6. `src/app/api/graph/v1/query.py`
- **Remove** lines 262–263 (`if not settings.NEO4J_ENABLED: raise RuntimeError(...)`)
- Update comment on line 184.

### 7. `src/app/api/graph/v1/router.py`
- **Remove** lines 324–331 (the `if not settings.NEO4J_ENABLED:` block in `/graph/health` that returns 503)
- Update error hint string on line 299 (remove reference to `NEO4J_ENABLED` setting).

### 8. `src/app/api/activity/v1/identity.py`
- **Remove** lines 67–72 (the `if not settings.NEO4J_ENABLED: return []` guard and its comment)

### 9. `src/app/main.py`
- **Remove** `if settings.NEO4J_ENABLED:` wrapper on line 151; always call `close_driver()` unconditionally.

### 10. `src/app/api/search/v1/service.py`
- **Remove** `if not settings.ELASTICSEARCH_ENABLED:` guard at line 218 (spotlight search)
- **Remove** `if not settings.ELASTICSEARCH_ENABLED:` guard at line 263 (main search)

### 11. `src/app/api/search/v1/persons_router.py`
- **Remove** `if not settings.ELASTICSEARCH_ENABLED:` guard at line 98

### 12. `src/app/dash_app/pages/search.py`
- **Remove** `if not settings.ELASTICSEARCH_ENABLED:` block (lines 768–780) and the `es_disabled_banner` variable entirely.

### 13. `src/app/dash_app/pages/timeline/callbacks.py`
- **Remove** the `if not settings.NEO4J_ENABLED:` branch inside the `NodePropertiesError` handler (lines 1227–1231); simplify to just `return _detail_error("Could not load properties for this event.")`

### 14. `src/app/ai_agent/chains/chains.py`
- Line 47: `if not settings.NEO4J_ENABLED:` → `if not settings.NEO4J_AI_LOOKUP_ENABLED:`
- Line 74: `if not settings.ELASTICSEARCH_ENABLED:` → `if not settings.ELASTICSEARCH_AI_LOOKUP_ENABLED:`

### 15. `src/app/ai_agent/chains/neo4j_chain.py`
- Line 47: `if _neo4j_graph is None and settings.NEO4J_ENABLED:` → `... and settings.NEO4J_AI_LOOKUP_ENABLED:`
- Line 400: `if not settings.NEO4J_ENABLED:` → `if not settings.NEO4J_AI_LOOKUP_ENABLED:`
- Docstring line 47-area: update variable name

### 16. `src/app/ai_agent/chains/elasticsearch_chain.py`
- Line 299 (docstring): update `ELASTICSEARCH_ENABLED` → `ELASTICSEARCH_AI_LOOKUP_ENABLED`
- Line 313: `if not settings.ELASTICSEARCH_ENABLED:` → `if not settings.ELASTICSEARCH_AI_LOOKUP_ENABLED:`

### 17. `src/connectors/consumers/sinks/elasticsearch_sink.py`
- **Remove** the `ELASTICSEARCH_ENABLED` env-var check in `build_es_client()` (lines 209–211). The function always attempts to build a client.
- Update module docstring (line 13) and `build_es_client` docstring (lines 198–211) to remove the flag documentation.

### 18. `src/connectors/consumers/main.py`
- **Remove** the `ELASTICSEARCH_ENABLED` documentation comment on line 15.

### 19. `src/app/scripts/create_es_indexes.py`
- Update docstring on line 5: remove `ELASTICSEARCH_ENABLED=true` reference.

### 20. `src/app/dash_app/pages/timeline/api.py`
- Update docstring on line 218: remove `NEO4J_ENABLED is false` reference.

### 21. Alembic — new migration
- New file: `src/app/alembic/versions/<timestamp>_rename_enabled_flags_to_ai_lookup.py`
- `upgrade()`:
  - `UPDATE application_settings SET key='NEO4J_AI_LOOKUP_ENABLED', description='...' WHERE key='NEO4J_ENABLED'`
  - `UPDATE application_settings SET key='ELASTICSEARCH_AI_LOOKUP_ENABLED', description='...' WHERE key='ELASTICSEARCH_ENABLED'`
- `downgrade()`: reverse renames
- New descriptions:
  - Neo4j: *"Controls whether the AI agent queries Neo4j for context enrichment during chat. When false, the Neo4j augmentation chain is skipped. Neo4j itself is always required for the application to function."*
  - ES: *"Controls whether the AI agent queries Elasticsearch for context enrichment during chat. When false, the Elasticsearch augmentation chain is skipped. Elasticsearch itself is always required for the application to function."*

### 22. Tests

**Remove skip gates** (replace `@pytest.mark.skipif(not settings.NEO4J_ENABLED, ...)` with no skip — or if the test genuinely requires a live DB and CI doesn't provide one, keep the skip but gate on DB reachability, not the flag):

| File | Change |
|---|---|
| `test_graph_execute_api_integration.py` | Remove `NEO4J_ENABLED` skip |
| `test_graph_query_integration.py` | Remove `NEO4J_ENABLED` skip |
| `test_graph_router.py` | Remove `NEO4J_ENABLED` skip |
| `test_graph_service.py` | Remove `NEO4J_ENABLED` skip |
| `test_person_catalog_queries.py` | Remove `NEO4J_ENABLED` skip |
| `test_person_integrity.py` | Remove `NEO4J_ENABLED` skip |
| `test_timestamp_properties.py` | Remove `NEO4J_ENABLED` skip |
| `tests/z_collab_validation/test_collaboration_layers.py` | Remove `NEO4J_ENABLED` skip |
| `test_persons_search_api.py` | Remove `ELASTICSEARCH_ENABLED` skip |
| `test_search_api.py` | Remove `ELASTICSEARCH_ENABLED` skip |
| `test_es_index_coverage.py` | Remove `ELASTICSEARCH_ENABLED` skip |

**Update monkeypatches** to new attribute names:

| File | Change |
|---|---|
| `test_chat_mcp_integration.py` | All `monkeypatch.setattr(settings, "NEO4J_ENABLED", ...)` → `"NEO4J_AI_LOOKUP_ENABLED"` |
| `test_elasticsearch_chain.py` | All `monkeypatch.setattr(settings, "ELASTICSEARCH_ENABLED", ...)` → `"ELASTICSEARCH_AI_LOOKUP_ENABLED"` |
| `test_graph_driver_singleton.py` | `monkeypatch.setattr(settings, "NEO4J_ENABLED", True)` → `"NEO4J_AI_LOOKUP_ENABLED"` |
| `test_graph_query_integration.py` | `monkeypatch.setattr(settings, "NEO4J_ENABLED", False)` → `"NEO4J_AI_LOOKUP_ENABLED"` |
| `test_graph_router.py` | `if settings.NEO4J_ENABLED:` → `if settings.NEO4J_AI_LOOKUP_ENABLED:` |
| `test_runtime_config_model.py` | `("NEO4J_ENABLED", False)` → `("NEO4J_AI_LOOKUP_ENABLED", False)` |
| `test_settings_client.py` | `"NEO4J_ENABLED": False` → `"NEO4J_AI_LOOKUP_ENABLED": False` |
| `test_settings_rabbitmq.py` | `NEO4J_ENABLED=False` → `NEO4J_AI_LOOKUP_ENABLED=False` |
| `test_settings_api.py` | `data["NEO4J_ENABLED"]` → `data["NEO4J_AI_LOOKUP_ENABLED"]` |
| `test_settings_ui.py` | `_make_setting("NEO4J_ENABLED")` → `_make_setting("NEO4J_AI_LOOKUP_ENABLED")` |
| `test_elasticsearch_sink.py` | Remove `ELASTICSEARCH_ENABLED` env var patches (the flag is gone from the sink) |
| `test_augmentation_history.py` | Update any flag references |
| `test_chains_mcp_composition.py` | Update any flag references |

### 23. Documentation

| File | Change |
|---|---|
| `.env.example` | Rename vars; change defaults to `true`; update comments |
| `.env.last_good` | Rename vars |
| `CLAUDE.md` | Update "Environment configuration" section: rename both vars |
| `DEVELOPER_QUICK_START.md` | Update any `NEO4J_ENABLED`/`ELASTICSEARCH_ENABLED` references |
| `docker-compose.yml` | Update env var names in service definitions |
| `docs/design/ai_agent_design_workflow.md` | Update mermaid labels, text, and config table |
| `plans/audit.md` | Update any references |
| `plans/044-*.md`, `plans/045-*.md` | Update any references |
| `.github/workflows/pr_checks.yml` | Update env var names |

---

## Non-Goals

- No behavior change to the AI agent chains themselves (they still skip DB lookups when the flag is false).
- No auth, multi-tenancy, or other scope expansion.
- No changes to the LangChain pipeline, MCP chains, or other augmentation logic.

---

## Execution Order (to minimise broken intermediate states)

1. `settings.py` + `config.py` rename (everything downstream breaks until step 2)
2. All source files: rename references, remove non-AI-agent guards (single commit)
3. `runtime_settings.py` bridge update
4. Alembic migration
5. Test updates
6. Documentation updates
7. Run `pytest -m unit tests -q` + `mypy src/` + `pylint src` to verify

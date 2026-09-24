# Plan 022 — Retire `AUTHORED_BY`: Unify Commit Authorship under `CREATED_BY`

**Priority**: P1  
**Effort**: M  
**Depends on**: —  
**Status**: DONE ✓

---

## Background

The graph currently uses two distinct relationship names for "a Person produced an artifact":

| Relationship | Entity pair | Direction |
|---|---|---|
| `AUTHORED_BY` | `Commit ↔ Person` | Undirected |
| `CREATED_BY` | `PullRequest → Person` | Directed |

As the platform grows to support additional connectors (Slack, Notion, Linear, Figma, Zendesk, etc.), every new artifact type would need to pick one of these names — or invent a third. This inconsistency will compound with each new connector.

The fix is simple: retire `AUTHORED_BY` and extend `CREATED_BY` to cover commits. The `CREATED_BY` / `CREATED` pair is already defined in the graph model and already used for Pull Requests.

**Out of scope**: `REPORTED_BY` on Jira Issues is kept untouched. It represents a distinct Jira-domain concept (the reporter role) and is used in the collaboration scoring logic as a named signal layer.

---

## Target Ontology

```
(Artifact)-[:CREATED_BY]->(Person)   ← canonical forward edge (any connector)
(Person)-[:CREATED]->(Artifact)      ← auto-generated reverse, for person-centric queries
```

Applies to: `Commit`, `PullRequest`, `Page`, `Blogpost`, and any future artifact node.

---

## Directionality Note

`AUTHORED_BY` was **undirected** — traversable from either end with `[:AUTHORED_BY]`. `CREATED_BY` is **directed** (`Artifact → Person`). Any query that used `[:AUTHORED_BY]` with no arrows must be updated to use explicit direction:

```cypher
-- Before (undirected)
MATCH (p:Person)-[:AUTHORED_BY]-(c:Commit)

-- After (directed, person-centric)
MATCH (p:Person)<-[:CREATED_BY]-(c:Commit)
```

The `collaboration_score.cypher` cross-commit traversal already had explicit arrows and requires only a type rename.

For `all_collaboration_partners.yaml`, which uses relationship types in an undirected multi-hop list, both `CREATED_BY` and its reverse `CREATED` must appear in the list to preserve traversal from either end.

---

## Changes

### 1. Core Graph Model

**[MODIFY] `src/connectors/neo4j_db/models.py`**

- Remove `"AUTHORED_BY"` from `UNDIRECTED_RELATIONSHIPS` (line 880) and its inline comment
- No change needed to `DIRECTIONAL_RELATIONSHIPS` — `"CREATED_BY": "CREATED"` is already defined (line 913) and will apply to commits automatically

---

### 2. GitHub Commit Producer

**[MODIFY] `src/connectors/producers/github/build_commit_signal.py`**

- Line 57: `type="AUTHORED_BY"` → `type="CREATED_BY"`

---

### 3. Activity Signal Domain Model

**[MODIFY] `src/common/activity_signal/models.py`**

- Line 60: Remove `"AUTHORED_BY"` from the allowed relationship type list (`"CREATED_BY"` and `"CREATED"` are already present at lines 68–69)
- Line 111: Update docstring example that mentions `AUTHORED_BY` → `CREATED_BY`

---

### 4. Collaboration Analytics

**[MODIFY] `src/app/analytics/collaboration/queries/collaboration_score.cypher`**

- Line 44 (Shared Commits layer): rename relationship type only — arrows are already explicit:

```cypher
-- Before
MATCH (dev1:Person)<-[:AUTHORED_BY]-(c1:Commit)-[:MODIFIES]->(f:File)
      <-[:MODIFIES]-(c2:Commit)-[:AUTHORED_BY]->(dev2:Person)

-- After
MATCH (dev1:Person)<-[:CREATED_BY]-(c1:Commit)-[:MODIFIES]->(f:File)
      <-[:MODIFIES]-(c2:Commit)-[:CREATED_BY]->(dev2:Person)
```

---

### 5. AI Agent Prompt

**[MODIFY] `src/app/ai_agent/neo4j_prompt.md`**

- Line 30: Remove `AUTHORED_BY` from the **Source Control** relationship list
- Line 31: Expand the `CREATED_BY` description to note it applies to both Commits and Pull Requests

---

### 6. Query Catalog

#### `queries_catalog/person/authored_commits.yaml`
- Lines 20, 30: `(p:Person {id: $person_id})-[:AUTHORED_BY]-(c:Commit)` → `(p:Person {id: $person_id})<-[:CREATED_BY]-(c:Commit)`

#### `queries_catalog/person/most_modified_files.yaml`
- Lines 20, 27, 31: `(p)-[:AUTHORED_BY]-(c:Commit)` → `(p)<-[:CREATED_BY]-(c:Commit)`

#### `queries_catalog/person/all_collaboration_partners.yaml`
- Lines 20, 30, 35: Replace `AUTHORED_BY` with `CREATED_BY|CREATED` in the undirected relationship type list (both directions of the pair required for multi-hop traversal)

#### `queries_catalog/person_to_person/shared_code_hotspots.yaml`
- Lines 28, 37: `(p1)-[:AUTHORED_BY]-(c1:Commit)` → `(p1)<-[:CREATED_BY]-(c1:Commit)` and `(c2:Commit)-[:AUTHORED_BY]-(p2)` → `(c2:Commit)-[:CREATED_BY]->(p2)`

#### `queries_catalog/person_to_person/shortest_paths_through_code.yaml`
- Lines 28, 39: Remove `AUTHORED_BY` from the `allShortestPaths` relationship list (`CREATED_BY` is already present)

#### `queries_catalog/person_to_person/shortest_paths_through_work_artifacts.yaml`
- Lines 28, 39: Remove `AUTHORED_BY` from the `allShortestPaths` relationship list (`CREATED_BY` is already present)

#### Hall of Fame queries (prior session — need `AUTHORED_BY` → `CREATED_BY` pass)

| File | What changes |
|---|---|
| `queries_catalog/hall_of_fame/top_n_committers.yaml` | tabular + both phases of graph query |
| `queries_catalog/hall_of_fame/top_n_multi_repo_contributors.yaml` | `OPTIONAL MATCH` commits |
| `queries_catalog/hall_of_fame/top_n_overall_mvp.yaml` | tabular `CALL` block + graph `OPTIONAL MATCH` (6 occurrences) |

---

### 7. Simulation

**[MODIFY] `simulation/layer7/generate_data.py`**
- Line 355: Comment update (`AUTHORED_BY` → `CREATED_BY`, undirected → directed)
- Line 357: `"type": "AUTHORED_BY"` → `"type": "CREATED_BY"`
- Lines 425, 430: Rename `authored_by` variable and print label → `created_by`

**[MODIFY] `simulation/layer7/load_to_neo4j.py`**
- Lines 8, 111: Comment/docstring — update relationship name
- Line 187: `(c:Commit)-[:AUTHORED_BY]-(p:Person)` → `(c:Commit)-[:CREATED_BY]->(p:Person)`

**[MODIFY] `simulation/data/layer7_commits.json`**
- Bulk string replace: `"type": "AUTHORED_BY"` → `"type": "CREATED_BY"` (~500 occurrences)

---

### 8. Tests

**[MODIFY] `tests/test_activity_signal_models.py`**
- Line 378: `{"ASSIGNED_TO", "AUTHORED_BY", "PART_OF", "MEMBER_OF"}` → `{"ASSIGNED_TO", "CREATED_BY", "PART_OF", "MEMBER_OF"}`

---

## Verification Plan

### Automated
```bash
# Confirm AUTHORED_BY is fully gone from source (expected: 0 matches)
grep -r "AUTHORED_BY" src/ queries_catalog/ simulation/layer7/ tests/

# Run signal model tests
pytest tests/test_activity_signal_models.py -v

# Full test suite
pytest -x
```

### Manual
1. Regenerate simulation data: `python simulation/layer7/generate_data.py`
2. Reload into Neo4j: `python simulation/layer7/load_to_neo4j.py`
3. Run `top_n_committers` and `authored_commits` queries via the app — results should match pre-change output
4. Run the `collaboration_score` computation — verify the Shared Commits layer (Section 3) returns non-zero scores

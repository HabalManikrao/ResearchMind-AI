# Knowledge Graph + Temporal Knowledge (#7) — Implementation Plan

_Pre-implementation audit + design, written **before** any code (spec §1). Goal: turn
ResearchMind from a system that stores research outputs into one that maintains a
**persistent, evidence-backed, temporal model of what it currently believes, why, and how
that belief changed** — as another **view/index over the existing substrate**, never a
parallel knowledge system (spec §0, §47)._

---

## 1. Current architecture (audited, not assumed)

Read: `app/knowledge/{service,vector_store}.py`, `api/knowledge.py`, `models/research.py`,
`models/{monitor,document,notification}.py`, `services/{research_diff,significance,
research_monitor,connectivity,provenance,dedup,freshness}.py`, `orchestration/orchestrator.py`,
`agents/verification.py`, frontend `Knowledge.tsx` / `KnowledgeGraphView.tsx` / `App.tsx`.

| Concern | Where it lives today | Reuse for #7 |
|---|---|---|
| **Existing "knowledge graph"** | `knowledge/service.build_graph(project_id)` — a per-project, *on-the-fly*, non-persisted node/edge view of Solutions/Claims/Sources for the run's **GraphTab** | Left **as-is** (different concept: a single-run visualization). #7 adds a **persistent, cross-run, temporal entity graph** beside it. |
| **Claims** (immutable per-run) | `Claim` (+ `confidence_meta`, `status`, `evidence_state`) | Entities **link to** existing claims; claims are never duplicated (spec §8). |
| **Evidence** | `ClaimSource` (stance + passage) + `Source` | Entity↔source + claim↔source reuse these; no new evidence system (§10). |
| **Verification / contradiction** | `verification.score_claim`, `evidence_state == "conflicting"`, `Conflict` | "Disputed" is **derived** from existing verification, not recomputed (§9, §14). |
| **Solutions / Recommendation** | `Solution.name` (already-extracted tech/approach names), `Recommendation.recommended_option` | The **best deterministic entity source** — structured, no LLM (§2, §16). |
| **Lineage / runs** | `research_projects` (`root_id`/`parent_id`/`run_number`/`completed_at`) | Entity↔run + temporal ordering reuse lineage; no new run abstraction (§12, §15). |
| **Research Diff** | `research_diff.diff_runs(old,new)` (NEW/STRENGTHENED/WEAKENED/CONTRADICTED/REMOVED) | The **only** diff engine; graph reconciliation consumes it (§14, §38). |
| **Monitoring** | `research_monitor` escalation forks a `refresh` child → `run_research` | Graph updates via the child run's completion hook — no second monitoring→graph pipeline (§22). |
| **Provenance / connectivity** | `Source.provenance`/`.availability`, `report_meta["source_health"]` | Graph facts carry the originating source/claim, so provenance is inherited, not re-derived (§35). |
| **Completion hook** | `orchestrator._index_knowledge` (best-effort, never fails a run) | The natural, already-best-effort place to build the graph (§20, §32). |
| **Migration** | `create_all` (new tables) + `_ensure_columns` (new columns) | #7 needs **new tables only** — graph status rides in `report_meta` JSON, so **zero existing-table changes** (§31). |
| **Ownership** | `research._get_project` (404, no leak); user-scoped routers | Entities/relationships carry `user_id`; every query is user-scoped (§24). **Note:** the legacy `/knowledge/graph` and `/search` are *not* per-user scoped (pre-existing personal-tool compromise); the new `/knowledge/entities*` endpoints **are**. |

**Conclusion:** #7 = 4 additive tables + one graph service + ownership-scoped read APIs +
one completion hook + a Knowledge/Entities UI. No graph DB, no parallel evidence/diff/run/
notification system.

---

## 2. Proposed graph architecture

```
run completes (research / research-again / monitoring child)
        │  orchestrator._index_knowledge  (best-effort, never fails the run)
        ▼
  graph.build_graph_for_project(project_id)          ← incremental, idempotent
        │   Tier-1 deterministic extraction (NO LLM):
        │     • Solutions → entities (TECHNOLOGY/PRODUCT)
        │     • Recommendation.recommended_option → entity
        │     • conservative resolve/dedup by (user, normalized_name, type)
        │     • claim ↔ entity by normalized substring match
        │     • entity ↔ source / entity ↔ run (kg_mentions)
        │     • relationships: ALTERNATIVE_TO (co-considered solutions, DERIVED),
        │       RELATED_TO (entity co-occurrence in a claim, DERIVED)
        │   Tier-2 bounded LLM (OFF by default, kg_llm_extraction_enabled):
        │     • one capped, schema-validated call for extra named entities (INFERRED)
        ▼
  if parent_id:  graph.reconcile_from_diff(parent_id, project_id)   ← consumes research_diff
        │     • CONTRADICTED/WEAKENED/REMOVED old claim  → new claim SUPERSEDES old
        │     • old claim's entity view becomes HISTORICAL; disputed derived from verification
        ▼
  report_meta["graph_status"] = {state: ok|degraded|skipped, entities, relationships}
```

Graph status is stored in the existing `report_meta` JSON (like `source_health`) — **no new
column**, and a degraded build never blocks the report (§20, §32). A `POST
/knowledge/graph/rebuild/{project_id}` retries a degraded build.

---

## 3. Proposed schema (4 new tables — additive, nullable, non-destructive)

`entity_type` and `predicate` are **plain string columns** validated against an extensible
in-code registry, so new types/predicates need **no migration** (§5, §7). All rows carry
`user_id` (nullable → legacy/unowned, readable by any user, matching the existing rule).

**`kg_entities`** — normalized, per-user-canonical entity.
`id, user_id(idx), canonical_name, normalized_name(idx), entity_type, description?,
aliases(JSON), meta(JSON), mention_count, first_observed_at, last_observed_at,
created_at, updated_at`. App-level identity = `(user_id, normalized_name, entity_type)`.

**`kg_relationships`** — entity↔entity, temporal.
`id, user_id(idx), subject_entity_id(idx), predicate, object_entity_id(idx), description?,
confidence(0-1), provenance_kind(explicit|derived|inferred), status(active|superseded|
retracted|disputed|historical), valid_from, valid_to?, first_observed_at, last_observed_at,
project_id?, claim_id?, source_id?, meta(JSON), created_at, updated_at`. Dedup =
`(user_id, subject, predicate, object)`.

**`kg_mentions`** — polymorphic entity↔{claim,source,document,project} provenance edge.
`id, user_id(idx), entity_id(idx), target_type(claim|source|document|project),
target_id(idx), project_id(idx, run context), role?, confidence, provenance_kind,
created_at`. One lean table covers §8/§10/§11/§12 without table sprawl.

**`kg_claim_links`** — claim↔claim (existing Claim rows; never duplicated).
`id, user_id(idx), subject_claim_id(idx), predicate(supersedes|supports|contradicts|
related_to|depends_on), object_claim_id(idx), project_id?, confidence, provenance_kind,
created_at`. `SUPERSEDES` (new→old) is the temporal transition from the diff (§13, §14, §38).

**Migration:** `Base.metadata.create_all` creates the four tables; nothing else changes.
Idempotent, non-destructive, safe twice. Tested by `test_kg_migration.py` (old-shape DB →
create_all twice → tables present, existing rows intact).

---

## 4. Entity resolution (conservative — §6, §39)

`normalize_name`: trim → collapse whitespace → casefold → strip surrounding punctuation
(keeps inner `.`/`+`, e.g. `unreal engine 5`, `c++`). Display `canonical_name` preserved.
`resolve_or_create(user, name, type)`:
1. exact match on `(user_id, normalized_name, entity_type)` → reuse, add alias if display differs.
2. else **create a new entity**. **Never** merge two entities by name similarity alone
   (spec §39: `Apple` ≠ `Apple Inc.` ≠ `Apple Records`). Aliases are added only for the
   *same* normalized identity or via explicit metadata — never fuzzy auto-merge.

Deferred (documented): cross-user global canonical identity, semantic (embedding) entity
resolution. First implementation is **user-scoped** with normalized identity fields (§25).

---

## 5. Temporal model (§13, §14, §15)

Claims are immutable per-run snapshots, so temporal state is expressed as **relationships +
supersession**, not by mutating claims:
- **Current vs historical claims for an entity**: a claim mentioning E is *current* unless a
  `kg_claim_links.SUPERSEDES` edge names it as the superseded object; then it is *historical*.
- **Supersession** is created by `reconcile_from_diff`: for a CONTRADICTED / WEAKENED /
  REMOVED old claim that matches a new claim in the child run, `new SUPERSEDES old`.
- **Relationship temporality**: `kg_relationships.status` + `valid_from`/`valid_to`. A
  re-observed relationship bumps `last_observed_at`; one whose supporting claim became
  contradicted is marked `DISPUTED`; a relationship only in older runs and not re-observed
  can be `HISTORICAL`.
- **Disputed** is **derived** from existing verification (`evidence_state == "conflicting"` /
  `contradiction_count > 0`) — never a new contradiction engine (§9, §14).
- Observation timestamps come from the run's `completed_at` (§13).

Nothing is physically deleted on change (§13).

---

## 6. Provenance & confidence (§15, §18, §35)

Every relationship/mention carries `provenance_kind`:
- **EXPLICIT** — present in existing structured data (e.g. Recommendation's chosen option).
- **DERIVED** — deterministically computed from claims/solutions/lineage (default for #7).
- **INFERRED** — produced by the optional bounded LLM tier.
Plus references to the originating `project_id` / `claim_id` / `source_id` and a `confidence`
(0-1). Large passages are **not** copied — the graph references evidence ids and the existing
evidence endpoint renders them (§15). Provenance (live/cached/local) is inherited from the
referenced `Source`, so a graph fact never implies live verification when evidence was
cached/local (§34, §35).

---

## 7. Extraction tiers (CPU-safe — §2, §16, §17)

**Tier 1 (default, deterministic, no LLM):** entities from `Solution.name`,
`Recommendation.recommended_option`; claim↔entity by normalized substring; relationships
`ALTERNATIVE_TO` (all solutions considered in a run are alternatives — DERIVED) and
`RELATED_TO` (two entities co-mentioned in one claim — DERIVED, bounded). This reuses
already-extracted structured data, so a normal run adds **zero** LLM calls.

**Tier 2 (optional, `kg_llm_extraction_enabled=false` by default):** one bounded,
schema-validated LLM call over the run's claim texts to surface additional named entities
(INFERRED), capped by count/length/retries. Malformed output is rejected — LLM output never
mutates the graph directly (§17). Off by default keeps offline/CPU-only runs unaffected (§34).

---

## 8. Integration (§20–§22, §38)

- **Research completion**: `_index_knowledge` also calls `build_graph_for_project` +
  (if `parent_id`) `reconcile_from_diff(parent_id, self)`. Best-effort; failure →
  `graph_status.degraded`, run still SUCCESS (§20, §32).
- **Research Again**: a continuation has `parent_id`, so the same hook does the incremental
  update + supersession — no rebuild of unrelated runs (§21).
- **Monitoring**: escalation forks a `refresh` child that runs `run_research`, so the same
  hook builds/reconciles the graph. No second pipeline (§22). Monitor notifications can
  optionally reference an entity, reusing the existing notification/diff link (§36).

---

## 9. API (ownership-enforced, bounded — §23, §24, §30, §33)

All under `/knowledge`, `Depends(get_current_user)`, user-scoped (`user_id == me OR NULL`),
paginated, deterministically ordered:
```
GET  /knowledge/entities?q=&type=&limit=&offset=      search/list
GET  /knowledge/entities/{id}                          detail (+ counts)
GET  /knowledge/entities/{id}/graph?depth=1|2          neighborhood (depth clamped ≤ 2)
GET  /knowledge/entities/{id}/claims?scope=current|historical|all
GET  /knowledge/entities/{id}/history                  observations + supersessions
GET  /knowledge/relationships/{id}                     relationship detail
POST /knowledge/graph/rebuild/{project_id}             retry a degraded build
```
Depth is hard-clamped; node/edge counts bounded; no unbounded recursion; entity pages avoid
N+1 via batched loads (§33). 404 (no leak) for another user's id.

---

## 10. Frontend (§26, §27, §41)

Knowledge page gains a **tabbed** layout: *Research* (existing semantic search) + *Entities*
(search + list). New **Entity detail** route `/knowledge/entities/:id`: type, description,
related entities (structured relationship **list** — no heavy viz, §27), **Current claims**
vs **Historical claims** (each links to the existing evidence drill-down), supporting/
contradicting sources, research runs, provenance pill, last-updated. Empty/loading/error/
unauthorized states. `lib/knowledgeGraph.ts` for type/predicate/provenance labels. Vitest
tests for search, detail, current-vs-historical, evidence navigation, empty/error states.

---

## 11. Non-goals (§44) — explicitly not built

Neo4j/Kuzu/graph DB, cross-user/global shared knowledge, unrestricted LLM extraction,
unbounded recursive queries, graph recommendation/GNN, heavy visualization, OCR, new search
provider, replacing Qdrant/Memory/Diff/Verification/ClaimSource. Cross-user global canonical
identity and semantic entity resolution are **deferred** with seams in place.

---

## 12. Testing & validation gates (§40–§42, §45)

Backend: entity normalization/resolution/dedup/type-validation; relationship dedup/predicate/
confidence/provenance; claim↔entity + claim↔source integration; temporal current/historical/
superseded/disputed + timestamps; graph-after-research / after-again / after-diff / after-
monitoring; offline (Tier-1 only, no false live provenance); failure isolation + retry +
partial build; cross-user/cross-project isolation; API pagination/limits/invalid-id/unauth/
depth-clamp; bounded-traversal / no-N+1. Frontend: navigation, search, detail, current-vs-
historical, relationships, provenance, evidence drill-down, empty/loading/error. Regression:
full `pytest` + `vitest` + `tsc --noEmit` + `vite build` all green; migration run twice.
Completion report (`docs/KNOWLEDGE-GRAPH-COMPLETION.md`) carries the readiness matrix with
**executed** counts — no READY claimed without running the tests.

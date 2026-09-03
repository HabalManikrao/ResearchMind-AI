# Knowledge Graph + Temporal Knowledge (#7) — Completion Report

_Completed: 2026-09-02. ResearchMind now maintains a **persistent, evidence-backed, temporal
model of what it currently believes, why, and how that belief changed** — layered over the
existing evidence → verification → memory → diff → monitoring substrate, never a parallel
system. Plan: `docs/KNOWLEDGE-GRAPH-PLAN.md`._

---

## Final Validation Report

```
Milestone #7 — Knowledge Graph + Temporal Knowledge

Audit:                       PASS
Implementation:              PASS
Migration:                   PASS
Entity Resolution:           PASS
Temporal Knowledge:          PASS
Research Integration:        PASS
Research Again Integration:  PASS
Research Diff Integration:   PASS
Monitoring Integration:      PASS
Offline:                     PASS
Security:                    PASS
Backend Tests:               275 passed
Frontend Tests:              48 passed
Type Check:                  PASS
Build:                       PASS
Regression:                  PASS
Documentation:               PASS

Overall:                     READY
```

- **Backend tests:** 275 passed, 0 failed (`pytest`, all offline) — was 248; **+27**
  (7 build/extraction, 4 temporal, 10 API + isolation, 5 pipeline integration, 1 migration).
- **Frontend tests:** 48 passed, 0 failed (`vitest`) — was 40; **+8** (5 mapping, 3 EntityDetail).
- **Type check + build:** `tsc --noEmit` clean + `vite build` OK (1857 modules, 438 kB).
- **Migration:** additive/idempotent/non-destructive — four new tables (`kg_entities`,
  `kg_relationships`, `kg_mentions`, `kg_claim_links`) via `create_all`; **zero changes to
  existing tables** (graph status rides in `report_meta`). Verified by `test_kg_migration.py`
  (old-shape DB → `create_all` twice → tables present, existing rows intact).

---

## 1. What was implemented

A persistent entity graph built **from existing structured data** (Solutions, Recommendation,
Claims) with **zero LLM calls on a normal run**; entity↔entity relationships with temporal
status; entity↔{claim,source,run} provenance edges; claim↔claim supersession links driven by
the existing Research Diff; ownership-scoped read APIs; and a Knowledge/Entities UI with
current-vs-historical claims and evidence drill-down.

## 2. Architecture (reuse-first)

Graph building hooks into `orchestrator._index_knowledge` (already best-effort) via
`_update_knowledge_graph` → `knowledge.graph.build_graph_for_project` + (for a continuation)
`reconcile_from_diff`. Because Research Again and Monitoring escalations both fork a `refresh`
child that runs `run_research`, **all three integrations share one code path** — no second
pipeline (§21, §22). A graph failure degrades `report_meta["graph_status"]` and never fails
the run (§20, §32); `POST /knowledge/graph/rebuild/{id}` retries.

## 3. Schema (`app/models/graph.py`)

`kg_entities` (normalized, per-user-canonical, extensible string `entity_type`),
`kg_relationships` (temporal entity↔entity: `predicate`, `confidence`, `provenance_kind`,
`status`, `valid_from/to`, `first/last_observed_at`, provenance ids), `kg_mentions`
(polymorphic entity↔{claim,source,document,project}), `kg_claim_links` (claim↔claim,
`SUPERSEDES` etc.). All rows carry `user_id` (nullable → legacy/unowned). `entity_type` /
`predicate` are plain strings validated against `knowledge/registry.py`, so new types need no
migration (§5, §7).

## 4. Entity resolution (`knowledge/graph.py`)

`normalize_name` (trim → collapse → casefold → strip surrounding punctuation, inner `.`/`+`
preserved). `resolve_or_create` matches on `(user_id, normalized_name, entity_type)` or
creates a new entity — it **never** merges by name similarity alone (`Apple` ≠ `Apple Inc.` ≠
`Apple Records`, tested). Different surface forms of the same identity are kept as aliases.

## 5. Relationship model & provenance

Deterministic relationships: `ALTERNATIVE_TO` (solutions compared in one run) and
`RELATED_TO` (entities co-mentioned in one claim), both DERIVED. Every fact carries
`provenance_kind` ∈ {EXPLICIT, DERIVED, INFERRED} and references to the originating
`project_id`/`claim_id`/`source_id` — no passages copied (§15, §18). The Tier-2 LLM tier
(`kg_llm_extraction_enabled`, **off by default**) is the only INFERRED source; its output is
schema-validated and never mutates the graph directly (§17).

## 6. Temporal semantics

Claims are immutable per-run snapshots, so temporality is expressed via supersession +
relationship status. `reconcile_from_diff` consumes the existing `research_diff.diff_runs`:
each new run's matching claim `SUPERSEDES` the prior one (→ the old claim becomes
**historical**, the new **current**); a CONTRADICTED claim marks its derived relationships
**DISPUTED**. "Disputed" is **derived** from existing verification (`evidence_state`), never a
new contradiction engine (§9, §14). Nothing is physically deleted (§13).

## 7-10. Research / Research Again / Diff / Monitoring integration

- **Research completion** builds the graph and records `graph_status` (`test_graph_built_after_research`).
- **Research Again** reconciles parent→child supersession (`test_graph_updated_after_research_again`).
- **Research Diff** is the sole reconciliation source — no graph-specific diff (§38).
- **Monitoring** escalations build/reconcile via the same child-run hook
  (`test_graph_updated_after_monitoring`).

## 11. Connectivity / offline

Tier-1 build needs no LLM and no network (`test_tier1_build_needs_no_llm` runs with a provider
that raises on any LLM call). Graph facts reference the originating `Source`, so provenance
(live/cached/local) is inherited, never fabricated — a graph fact never implies live
verification when the evidence was cached/local (§34, §35).

## 12. Security

Entities/relationships/mentions carry `user_id`; every read is scoped to `user_id == me OR
user_id IS NULL`. Another user's entity/relationship 404s and never appears in a listing
(`test_cross_user_entity_is_not_visible`); claim/source reads are re-checked against project
ownership. New endpoints require auth (the legacy `/knowledge/search|graph` remain the
pre-existing personal-tool compromise, unchanged).

## 13. Migration validation

`create_all` (four new tables) run twice = no-op on the second pass; existing research data
preserved (`test_kg_migration.py`). No FK ordering hazards (kg tables reference ids as plain
strings, not DB-level FKs, matching the app's existing style).

## 14. API endpoints added

```
GET  /knowledge/entities?q=&type=&limit=&offset=      (paginated, ordered, user-scoped)
GET  /knowledge/entities/{id}                          (detail + related + counts)
GET  /knowledge/entities/{id}/claims?scope=            (current|historical|all)
GET  /knowledge/entities/{id}/graph?depth=1|2          (depth hard-clamped ≤ 2)
GET  /knowledge/entities/{id}/history                  (observations + supersessions)
GET  /knowledge/relationships/{id}
POST /knowledge/graph/rebuild/{project_id}             (retry a degraded build)
```

## Files

**New (backend):** `models/graph.py`, `knowledge/registry.py`, `knowledge/graph.py`,
`schemas/graph.py`, `api/graph.py`; tests `test_kg_build.py`, `test_kg_temporal.py`,
`test_kg_api.py`, `test_kg_integration.py`, `test_kg_migration.py`.
**New (frontend):** `lib/knowledgeGraph.ts`, `pages/EntityDetail.tsx`; tests
`lib/knowledgeGraph.test.ts`, `pages/EntityDetail.test.tsx`.
**New (docs):** this file + `KNOWLEDGE-GRAPH-PLAN.md`.
**Modified (backend):** `models/__init__.py`, `config.py` (kg_* settings),
`orchestration/orchestrator.py` (graph build/reconcile hook), `main.py` (register router).
**Modified (frontend):** `api/types.ts`, `api/client.ts`, `pages/Knowledge.tsx` (Research +
Entities tabs), `App.tsx` (entity route).
**Modified (docs):** `CLAUDE.md`, `GAP-ANALYSIS.md`.

## Known limitations / deferred (with seams in place)

1. **User-scoped** entity identity (normalized fields retained) — cross-user global canonical
   identity is deferred (spec §25, non-goal for now).
2. **Deterministic** extraction only by default; the bounded LLM (INFERRED) tier is
   implemented but **off** for CPU safety (§2).
3. Semantic (embedding) entity resolution deferred — normalized relational matching only (§29).
4. A REMOVED-without-replacement claim stays visible as current until a superseding claim
   appears (historical retention is preferred over deletion, §13).
5. UI is a structured relationship **list**, not a heavy graph visualization (§27); the
   bounded `/graph` endpoint exists for a future progressive-enhancement viz.

## Definition of Done — acceptance (spec §45)

Architecture (no parallel evidence/run/diff/notification system, no graph DB), Database
(entity/relationship/claim/source associations + temporal + provenance, additive/idempotent
migration, data preserved), Intelligence (deterministic-first, bounded LLM, conservative
resolution, explicit/derived/inferred), Integration (research/again/diff/monitoring update
the graph; evidence/verification/provenance remain source of truth), Temporal (current/
historical/superseded/disputed + timestamps), API (search/detail/claims/history/relationship/
bounded traversal/pagination/ownership), Frontend (Knowledge section, entity search/detail,
current-vs-historical, relationships, provenance, evidence drill-down, empty/error/loading),
Reliability (graph failure isolated + retry + offline + no false provenance + cross-user
isolation), Quality (backend + frontend + type-check + build green, migration twice, docs, no
scope creep) — **all ✅**.

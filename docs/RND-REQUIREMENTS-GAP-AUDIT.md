# ResearchMind — R&D Engineering Laboratory Layer: Requirements → Code Gap Audit

**Date:** 2026-09-10 · **Baseline commit:** `d82bec2` (retry-in-place) · **Method:** static
audit of `backend/app/{models,api,capabilities,agents,orchestration,services,knowledge}`,
`frontend/src`, and the test suites. Statuses are evidence-based (file/model/route cited), not
assumed. This audit is the input to `RND-IMPLEMENTATION-PLAN.md`; **no production code was
changed to produce it.**

## Status legend
- **COMPLETE** — model + persistence + API/UI + workflow integration + tests, and the acceptance
  behavior works.
- **PARTIAL** — a real implementation exists but is missing fields, links, workflow integration,
  API/UI, or tests required by the master spec.
- **MISSING** — no first-class implementation.
- **BLOCKED** — cannot be built safely on the existing architecture (none found; see §Blockers).

## What already exists (do NOT rebuild)
Confirmed present and well-tested: `ResearchProject` run/orchestration, `Source`
(+reliability/provenance/freshness), Document RAG (`Document`, parsing/chunking/embedding/Qdrant),
Evidence (`ClaimSource` stance+passage + evidence API), `Claim` + deterministic verification
(`verification.score_claim`, `confidence_meta`), `Conflict` + contradiction agent, R&D analysis
(`Solution` + `Recommendation` via `rd_analysis`), Research Memory/Again/Diff (#4), Connectivity +
Provenance + Source cache (#5), Monitoring + significance (#6), Knowledge Graph + temporal (#7,
`kg_entities/relationships/mentions/claim_links`, **extensible entity/predicate registries — no
migration to add types**), Capability layer + REST `/v1` + MCP (#8), benchmark/eval harnesses
(#9/#10/#11), zero-evidence protection (post-#11), and **Retry-in-place** (`d82bec2`).

Models on disk: `user, schedule, document, cache, enums, research, monitor, notification, graph`.
**No** `Experiment/Hypothesis/Method/Dataset/Result/Conclusion/Objective/Terminology/Timeline/
ResearchLog/Checkpoint/Reproducibility/Analysis/Limitation/Comparison/ResearchBrief` model exists.

---

## A. Master research components (spec §2, the 28)

| # | Requirement | Status | Where it lives / what's missing |
|---|---|---|---|
| 1 | Research Brief | **MISSING** | Fields scattered on `ResearchProject` (`title`, `query`, `objective`, `constraints` JSON). No structured, editable, version-aware brief (problem statement / out-of-scope / assumptions / target users / expected outcome / success criteria). |
| 2 | Research Questions | **PARTIAL** | `ResearchQuestion` (`text, priority, is_followup, answered`). Missing: `category`, structured `status` (unanswered/partial/answered/contradicted/inconclusive), `answer`, `confidence`, explicit links to claims/evidence/sources/conclusions. |
| 3 | Objectives | **MISSING** | Only free-text `ResearchProject.objective`. No first-class `Objective` (priority/status/completion%/related questions/claims/experiments/conclusion). |
| 4 | Scope | **MISSING** | No structured included/excluded/out-of-scope. Only `constraints` JSON blob. |
| 5 | Constraints | **PARTIAL** | `ResearchProject.constraints` (JSON, unstructured, planner-consumed). No typed constraint categories (technical/time/dataset/hardware/regulatory). |
| 6 | Background | **MISSING** | No persisted background section. |
| 7 | Terminology | **MISSING** | No term/definition/synonym/acronym store. |
| 8 | Sources | **COMPLETE** | `Source` (+`reliability_score`, `provenance`, `freshness`, `meta`). |
| 9 | Documents | **COMPLETE** | `Document` + `documents/` pipeline (#3). |
| 10 | Evidence | **COMPLETE** | `ClaimSource` (stance+passage) + `GET /research/{id}/claims/{cid}/evidence`. |
| 11 | Claims | **COMPLETE** | `Claim` + `verification` + `confidence_meta` + evidence_state. |
| 12 | Methods | **MISSING** | No `Method` object (procedure/inputs/outputs/assumptions/limitations/evidence). |
| 13 | Experiments | **MISSING** | No `Experiment` object or lifecycle. |
| 14 | Datasets | **MISSING** | No `Dataset` object/versioning. |
| 15 | Results (structured) | **MISSING** | No `Result` rows (metric/value/unit/conditions/experiment link). `Solution.scores` are qualitative comparison ratings, not measured results. |
| 16 | Comparisons | **PARTIAL** | `Solution` + `scores` + `rd_analysis` produce a comparison **table**, but no first-class `Comparison` record (subject A/B, criterion, value, unit, evidence/experiment/result links). |
| 17 | Conflicts | **COMPLETE** | `Conflict` + `contradiction` agent + CONTRADICTS links. |
| 18 | Limitations | **MISSING** | No structured `Limitation` (type/severity/affected object/mitigation). Some reasons live inside `confidence_meta`. |
| 19 | Research Gaps | **PARTIAL** | `KnowledgeGap` (`question, reason, followup_query, round, resolved`). Missing importance/impact/missing-evidence/related links/status. |
| 20 | Hypotheses | **MISSING** | No `Hypothesis` object or status lifecycle. |
| 21 | Analysis | **PARTIAL** | `rd_analysis` yields `Solution`/`Recommendation`. Missing per-item classification (**FACT/INTERPRETATION/INFERENCE/HYPOTHESIS/OPINION**) tied to evidence. |
| 22 | Conclusions | **MISSING** | Report has narrative "conclusions" prose, but no first-class `Conclusion` (classification Proven…Disproved, traceability to claims/evidence/experiments/results). |
| 23 | Recommendations | **PARTIAL** | `Recommendation` (option/rationale/why/confidence/alternatives/risks/poc/roadmap). Single per project; no links to conclusions/experiments/results; no priority; not multi. |
| 24 | References | **COMPLETE** | `Source` rows rendered in report `## Sources`. |
| 25 | Research Timeline | **MISSING** | No structured, queryable timeline of lifecycle events. |
| 26 | Research Log | **PARTIAL** | `AuditLog` records coarse actions (create/start/stop/export/retry). Not a per-research decision/search/rejection/experiment log. |
| 27 | Knowledge Graph | **PARTIAL** | `#7` KG present; registries extensible. Missing lab entity types (experiment/method/dataset/result/hypothesis/conclusion/limitation) + predicates (tests/uses/produces/informs/affects/motivates). |
| 28 | Final Report | **COMPLETE (extendable)** | Deterministic assembly from rows (`report._assemble`). Needs new sections when lab objects exist (experiments/results/conclusions/limitations/traceability). |

## B. Cross-cutting requirements

| Ref | Requirement | Status | Notes |
|---|---|---|---|
| §19 | Analysis classification (FACT/INTERPRETATION/INFERENCE/HYPOTHESIS/OPINION) | **MISSING** | New `Analysis` object with a classification enum. |
| §24 | Full lifecycle stages / milestones | **PARTIAL** | `ProjectStatus` = created/planning/running/paused/completed/failed/cancelled + `current_stage` string + `progress`. No per-stage checkpoint records with artifact/failed/pending counts + next-action. |
| §25 | Failure recovery UI (Restart / Retry Stage / Continue / View Error) | **PARTIAL** | Failure shown (`error`, `FailedResearchCard`). **Restart** ≈ Retry-in-place (done). **Retry Failed Stage** and **Continue From Last Successful Stage** MISSING. |
| §26 | Retry Research (FAILED only) | **COMPLETE** | `POST /research/{id}/retry`, `reset_project_for_retry` (`d82bec2`). |
| §27 | Retry Failed Stage | **MISSING** | Requires stage checkpoints + per-stage re-entry into the orchestrator. |
| §28 | Continue From Last Successful Stage | **MISSING** | Requires durable stage checkpoints; orchestrator currently always runs the full pipeline from planning. |
| §29 | Structured Error History | **PARTIAL** | `proj.error` (last), `report_meta.retry_history` (retry attempts), `ResearchTask.error` (per task). No dedicated multi-error history with stage/component/type/recovery. |
| §30 | Reproducibility record | **MISSING** | No captured model/prompt/tool/query/dataset/seed/git-commit/env metadata per run/experiment/result. |
| §31 | Versioning (per-object) | **PARTIAL** | Run-level lineage + Research Again + Diff (#4) exist. No per-object immutable version history for briefs/claims/experiments/etc. |
| §32 | Research updates → re-evaluate affected | **PARTIAL** | Research Diff + Monitoring re-evaluate at the claim/recommendation level. Extend to new objects — **reuse, do not add a second diff engine.** |
| §34 | Bidirectional traceability | **PARTIAL** | claim→evidence→source and (implicitly) recommendation exist. Experiment/hypothesis/result/conclusion chains MISSING. |
| §35 | Confidence across objects | **PARTIAL** | Source reliability + claim `confidence_meta`. Missing for hypotheses/experiments/results/conclusions. |
| §36 | Agent workflow (evidence-first, no search→conclusion) | **PARTIAL** | Existing plan→collect→verify→conflict→rd→report is evidence-first. Missing hypothesis/method/experiment/dataset/result/conclusion stages (these are largely **user/manual-entry** objects, not auto-generated). |
| §37 | Offline-first / CPU budget | **COMPLETE (must preserve)** | Deterministic engines; LLM bounded/optional. New objects must be **deterministic + manual/CRUD-first** (no new mandatory LLM calls). |
| §38 | UI sections | **PARTIAL** | Tabs today: activity/plan/sources/documents/claims/conflicts/recommendation/graph/report/monitoring. Missing: evidence(own tab), methods/experiments/datasets/results/comparisons/limitations/gaps/hypotheses/analysis/conclusions/timeline/log + recovery controls beyond Retry. |
| §39 | REST API for new objects | **MISSING (framework ready)** | `research.py` + `_get_project` ownership pattern to reuse. |
| §40 | MCP for new capabilities | **MISSING (framework ready)** | `capabilities/` + `mcp/` + `v1.py` to reuse; add only read-oriented tools. |
| §41–42 | Additive, ownership-aware schema | **N/A (constraint)** | New tables via `create_all` + `_ensure_columns`; every table carries `project_id`; ownership via `_get_project`. |
| §46 | Truthfulness / anti-hallucination | **COMPLETE (must extend)** | Zero-evidence protection exists; new objects must never fabricate results/experiments (an unrun experiment is never "successful"). |

---

## C. Completeness baseline (against THIS master spec)

Counting the 28 components + 22 cross-cutting refs above (50 line items):
- **COMPLETE:** 9 (Sources, Documents, Evidence, Claims, Conflicts, References, Final-Report,
  Retry-Research, Offline/CPU, Truthfulness) → ~10
- **PARTIAL:** 16 (Questions, Constraints, Comparisons, Gaps, Analysis, Recommendations, Research
  Log, KG, lifecycle stages, failure-recovery UI, error history, versioning, updates, traceability,
  confidence, agent workflow, UI, §41–42) 
- **MISSING:** 18 (Brief, Objectives, Scope, Background, Terminology, Methods, Experiments,
  Datasets, Results, Limitations, Hypotheses, Conclusions, Timeline, Analysis-classification, Retry
  Stage, Continue-checkpoint, Reproducibility, REST/MCP for new objects)

**Evidence-based baseline: ≈ 38–42% of the R&D master specification.**
The **research→evidence→claims→conflicts→recommendation→report** half is strong (largely COMPLETE);
the **experiment/laboratory** half (methods→hypotheses→experiments→datasets→results→conclusions,
plus timeline/log/reproducibility/stage-recovery) is the bulk of the missing work.

## D. Blockers
**None architectural.** Every gap is additive on the existing substrate:
- New tables via `create_all` (all prior milestones added tables this way); nullable columns via
  `database._ensure_columns` + `_ADDED_COLUMNS`. No destructive migration required.
- KG extension needs **no migration** (string-based extensible registries).
- Ownership/security reuse `_get_project` (404-no-leak) and the capability layer.
- Stage-recovery (§27/§28) is the only item needing an orchestrator change (durable checkpoints);
  it is additive (a new `Checkpoint`/stage-status record + re-entry guards) and does not require
  rewriting `run_research`. If, during Phase E, checkpointing proves to require unsafe changes to
  the single-`_db_lock` write model, that phase STOPS and reports (per spec §55) rather than
  refactoring the orchestrator.

## E. Reuse map (extend, don't duplicate)
- Evidence/claims/verification/confidence → **reuse as-is**; new objects link to `Claim`/`Source`.
- Diff/updates → **reuse `research_diff` + monitoring**; extend classifiers, no second engine.
- Lineage/versioning → **reuse `root_id`/Research Again**; per-object history only where §31 needs it.
- KG → **reuse `knowledge/graph.py` + registries**; add entity types + predicates + mention kinds.
- API/MCP → **reuse `research.py`, capability layer, `v1.py`, `mcp/`**.
- Report → **reuse `report._assemble`** (structured-rows-in, prose-only-LLM); add sections.
- Recovery → **reuse `reset_project_for_retry` + `RunControl` + task statuses** for stage recovery.

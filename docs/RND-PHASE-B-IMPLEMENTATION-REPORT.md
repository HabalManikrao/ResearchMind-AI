# R&D Laboratory Layer — Phase B Implementation Report (Methods & Hypotheses)

**Baseline:** Phase A `1292e5901bda4836d6b30ed1d2bb794fd03085bd`. **Scope:** Methods + Hypotheses
only (Experiments/Datasets/Results are Phase C). **Not committed** at time of writing.

## Executive Summary
Added two first-class research objects — **Method** (a reusable *how*) and **Hypothesis** (a
proposition awaiting validation, explicitly **not** a Claim) — entirely additively on top of the
existing substrate. New tables via `create_all`; ownership via `_get_project`; relationships stored
as per-project-validated JSON id-lists; status/origin as validated string sets (migration-free).
The planner is *informed* of existing methods/hypotheses deterministically (no new LLM call). KG
vocabulary was extended; graph-builder emission and Diff/Memory/Monitoring integration are
explicitly deferred (documented). Nothing fabricates results and no hypothesis auto-advances.

## Audit Findings
Methods = **MISSING**, Hypotheses = **MISSING** before Phase B (`grep class (Method|Hypothesis)` →
none). Full matrix in `RND-PHASE-B-AUDIT.md`. No blockers; fully additive.

## Existing Infrastructure Reused
`_get_project` (404-no-leak ownership); `api/rnd.py` (Phase A router) as the home for the new CRUD;
the Phase A **validated-string-set** pattern (`enums.py`) and **version-bump** idiom
(`ResearchBrief`); existing `Source`/`Claim`/`ResearchQuestion`/`Objective` for relationships (no
new evidence system); `_build_brief_context` → `planner.make_plan(brief_context=)` for planner
integration; `knowledge/registry.py` extensible registries for KG vocabulary.

## Method Implementation
`models/experiment.py:Method` — name, description, procedure, inputs/outputs/assumptions/advantages/
disadvantages/limitations, applicability, `status` (proposed|active|deprecated|superseded), `origin`
(user|agent|derived), `source_ids`/`claim_ids` (traceability), `notes`, `version`. CRUD at
`/research/{id}/methods[/{mid}]`; PATCH bumps `version`; referenced source/claim ids validated
against the project.

## Hypothesis Implementation
`models/experiment.py:Hypothesis` — statement, reasoning, `status`
(proposed|testing|supported|partially_supported|rejected|inconclusive), `confidence` (0–100, null
until judged), `origin`, links to `question_ids`/`objective_ids`/`claim_ids`/`source_ids`, optional
`method_id`, plus `variables`/`expected_result`/`assumptions`/`notes`. **Distinct from Claim**;
status changes only by explicit client action (never auto-SUPPORTED). CRUD at
`/research/{id}/hypotheses[/{hid}]`.

## Database Changes
New tables `methods`, `hypotheses` (via `create_all`). **No** columns added to existing tables (no
`_ADDED_COLUMNS` change). Both carry `project_id` (FK CASCADE). Idempotent on fresh/existing/twice-run
DBs; Phase A data preserved (tested).

## API Changes
`api/rnd.py` extended: `GET/POST/GET{id}/PATCH/DELETE` for methods and hypotheses. Ownership via
`_get_project`; all relationship ids validated to belong to the same project (`_validate_object_links`)
→ cross-project/cross-user id injection returns 422.

## Frontend Changes
`components/LabPanel.tsx` + a **"Methods & Hypotheses"** tab in `LiveResearch`. Methods and
Hypotheses are visually distinct (icons, card styles); a PROPOSED hypothesis shows **"Not yet
validated"**; rejected hypotheses remain visible. `api/client.ts` + `types.ts` extended. Tests:
`LabPanel.test.tsx`.

## Knowledge Graph Changes
`knowledge/registry.py`: added entity types `method`, `hypothesis` and predicates `has_method`,
`has_hypothesis`, `addresses`, `derived_from`, `supported_by`, `uses_method`, `investigates`
(migration-free vocabulary). **Graph-builder node emission for method/hypothesis is deferred to
Phase G** — adding the vocabulary creates no nodes and changes no existing graph behavior.

## Planner / Orchestrator Changes
`orchestrator._build_brief_context` now also lists existing methods (name+status) and hypotheses
(statement+status, flagged "awaiting testing") in the deterministic planner hint. No new LLM/embedding
call; returns None when no front matter exists (existing runs unaffected). No orchestrator redesign;
no experiment execution.

## Provenance
`origin` (user|agent|derived) on both objects; "derived" is honest only when source/claim links are
present. No claim of "literature-derived" without links.

## Versioning
`Method.version` bumps on edit (reuses the Phase A `ResearchBrief` idiom). Hypothesis lifecycle is
captured by `status`; rejected hypotheses are retained (not deleted).

## Offline Behavior
All CRUD is deterministic and network-free. Test `test_creating_hypothesis_does_not_fabricate_or_call_llm`
monkeypatches `get_provider` to raise and confirms CRUD never constructs a provider.

## Security
Ownership enforced by `_get_project` (cross-user → 404, no leak) and per-project reference validation
(cross-project claim/source/question/objective/method → 422). Tested:
`test_cross_user_phase_b_is_404`, `test_cross_project_reference_rejected`,
`test_cross_project_method_id_rejected`, `test_phase_b_requires_auth`.

## Performance
CRUD is O(1) inserts/updates; reference validation is a single bounded `IN` query per id-list. No new
LLM/embedding calls, no unbounded graph traversal, no N+1.

## Tests
- Backend `test_rnd_phase_b.py`: **14** (CRUD, validation, versioning, relationships, cross-user 404,
  cross-project 422, truthfulness/no-LLM, no-experiment-tables, planner context, migration idempotency).
- Frontend `LabPanel.test.tsx`: **4** (render + unvalidated cue, create method, create hypothesis,
  status change/visible-rejected).

## Regression Results
- Backend: **388 passed** (374 → +14) · Frontend: **65 passed** (61 → +4)
- Typecheck: **PASS** · Build: **PASS**
- #9 benchmark: **30/30 (no failures)** · #10 evaluation: **1.0 vs 0.677** · #11 offline: in suite
- One Phase A test's `make_plan` spy already accepts `**`-free kwargs; no existing test needed edits
  this phase.

## Known Limitations
- KG graph-builder does not yet emit method/hypothesis **nodes** (vocabulary only) — Phase G.
- Research Diff / Memory / Monitoring do not yet include methods/hypotheses — deferred (they are
  consumers, not blockers; rows are queryable for future phases).
- Method history is a single `version` counter (not full per-version snapshots) — sufficient for
  "what changed"; full history is Phase F if required.

## Deferred Phase C Work
Experiment / Dataset / Result tables and execution; `Hypothesis.method_id` + link lists already give
Phase C a clean `Experiment(hypothesis_id, method_id, dataset_id)` to reference with no redesign.

## Master Specification Completeness
- Before Phase B: Methods = MISSING, Hypotheses = MISSING.
- After Phase B: Methods = **COMPLETE**, Hypotheses = **COMPLETE**.
- Overall R&D master-spec completeness: **≈40% → ≈48%** (front matter + methods + hypotheses done;
  experiments/results/analysis/conclusions/timeline/reproducibility/stage-recovery remain).

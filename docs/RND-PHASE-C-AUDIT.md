# R&D Laboratory Layer — Phase C Audit (Experiments, Datasets, Results)

**Baseline verified:** HEAD = `origin/master` = `37d9bbf4b0e228de088ead6d70234d298c94259c`
(Phase B). Working tree **clean**. Phase A = `1292e59`, Phase B = `37d9bbf` — both intact/pushed.
**Scope:** Experiments + Datasets + structured Results ONLY. No Analysis/Conclusion/Recommendation
rewrite, no stats engine, no execution engine (those are later phases).
**Method:** static inspection of `backend/app/{models,api,schemas,capabilities,orchestration,
knowledge}`, `frontend/src`, tests. Evidence-based; **no production code changed to produce this.**

## 1. What already exists (confirmed)
- **Phase A** (`models/brief.py`): `ResearchBrief`, `Objective`, `Constraint`, `Terminology`;
  `ResearchQuestion` first-class fields. API in `api/rnd.py`.
- **Phase B** (`models/experiment.py`): `Method`, `Hypothesis` (with links to questions/objectives/
  claims/sources + `Hypothesis.method_id`). CRUD in `api/rnd.py`; per-project reference validation
  (`_validate_object_links`, `_validate_refs`); version-bump idiom on `Method`.
- **Evidence substrate:** `Source`, `Document`, `Claim`, `ClaimSource` (stance+passage),
  `verification.score_claim` (confidence engine), `Source.meta["provenance"]` (#5). Reused as-is.
- **KG:** `knowledge/registry.py` — extensible string entity types + predicates (migration-free).
  Already has `method`/`hypothesis` types + `uses_method`/`produces`?-no/`addresses`/`derived_from`/
  `supported_by`/`investigates`/`has_method`/`has_hypothesis` predicates (Phase B).
- **Ownership:** `research._get_project(db,id,user)` → 404-no-leak; `capabilities.base.owned_project`.
- **Migrations:** `database.create_all` + idempotent `_ensure_columns` (`_ADDED_COLUMNS`) — new
  tables need no ALTER; nullable columns on existing tables do.
- **Planner hint:** `orchestrator._build_brief_context` (deterministic; lists brief/constraints/
  methods/hypotheses; no LLM).

## 2. What is missing (Phase C)
| Object | Status | Notes |
|---|---|---|
| Experiment | **MISSING** | `grep class Experiment` → NONE; no `experiments` table. |
| Dataset | **MISSING** | NONE; no `datasets` table. |
| Result (structured) | **MISSING** | NONE; no `results` table. `Solution.scores` are qualitative comparison ratings, not measured results. |
| Reproducibility record | **MISSING** | `grep -ril reproducib app/` → NONE. Phase C captures reproducibility *metadata on the experiment* (method/dataset+version/software/hardware/env/config/seed/procedure/io/metrics); a dedicated `ReproducibilityRecord` + a reproducible/partial/not/unknown **state** remains **Phase F** (deferred). |

## 3. What can be reused (reuse-before-create)
- **Module:** add `Experiment`, `Dataset`, `Result` to the **existing** `models/experiment.py`
  (created in Phase B for exactly this cluster).
- **API:** extend `api/rnd.py` with CRUD; reuse `_get_project` + `_validate_refs`/`_validate_object_links`
  (extend the validator to cover `method_id`/`hypothesis_id`/`dataset_id`/`experiment_id`).
- **Relationship style:** FK columns for the single-parent links (`experiment_id`, `dataset_id`,
  `method_id`, `hypothesis_id`, `objective_id`, `question_id`) + JSON id-lists only where genuinely
  many-to-many — consistent with Phase A/B. Every referenced id validated to the same project.
- **Enums:** validated **string sets** in `enums.py` (`EXPERIMENT_STATUSES`, `RESULT_TYPES`) — no
  Enum columns → migration-free, same as Phase A/B.
- **Confidence:** reuse the 0–100 float on `Result.confidence` (no second engine).
- **Provenance/truthfulness:** reuse the existing "record, don't fabricate" discipline; a `Result`
  carries an explicit `origin`/provenance (user/agent-recorded) — **never** invented.
- **KG:** add `experiment`/`dataset`/`result` entity types + `uses_dataset`/`produces`/`tests`
  predicates to the registry (vocabulary only; builder node emission stays Phase G).
- **Planner:** extend `_build_brief_context` deterministically (list experiments/datasets counts) —
  no new LLM call.
- **Frontend:** reuse the Phase B `LabPanel.tsx` pattern for new sections/tabs.

## 4. Proposed DB changes (additive, non-destructive, idempotent)
Three new tables via `create_all` (no ALTER, no `_ADDED_COLUMNS` needed):
- **`datasets`** — id, project_id(FK CASCADE), name, description, version, source, source_url,
  license, data_type, size, record_count, features(JSON), collection_method, collection_date,
  preprocessing, bias(JSON), limitations(JSON), quality, access_information, checksum, metadata(JSON),
  origin, timestamps. **Version-distinguishable:** a new version = a new row (parent identity via a
  nullable `supersedes_id`/shared `name`); never silent overwrite.
- **`experiments`** — id, project_id(FK), name, description, question_id/objective_id/hypothesis_id/
  method_id/dataset_id (nullable FKs), dataset_version, design fields (independent/dependent/
  controlled variables JSON, controls, assumptions JSON, expected_result, failure_conditions,
  procedure, inputs JSON, outputs JSON, metrics JSON), reproducibility metadata (hardware, software,
  software_versions JSON, environment, configuration JSON, seed), execution (status, planned_at,
  started_at, completed_at, actual_result_summary, raw_data_reference, processed_data_reference,
  execution_notes), origin, timestamps. **Truthfulness:** execution fields stay null unless recorded;
  `status` defaults PROPOSED and never auto-advances.
- **`results`** — id, project_id(FK), experiment_id(FK), dataset_id(nullable FK), name, description,
  result_type, metrics(JSON: [{name,value,unit,lower_bound,upper_bound,conditions}]), measurements
  (JSON), benchmark, error_rate/latency/throughput/accuracy/cost/resource_usage (nullable), 
  observations, anomalies, raw_data_reference, processed_data_reference, conditions, confidence
  (nullable 0–100), origin, notes, timestamps.

Enums (string sets): `EXPERIMENT_STATUSES = proposed|planned|running|completed|failed|cancelled|inconclusive`;
`RESULT_TYPES = measurement|benchmark|observation|qualitative|other`. Reuse `RND_ORIGINS`.

**Safety:** additive only; Phase A/B/earlier data untouched; `create_all` idempotent (tested).

## 5. Proposed API changes
Extend `api/rnd.py` (project-scoped, ownership via `_get_project`):
- `GET/POST/GET{id}/PATCH/DELETE  /research/{id}/experiments`
- `GET/POST/GET{id}/PATCH/DELETE  /research/{id}/datasets`
- `GET/POST/GET{id}/PATCH/DELETE  /research/{id}/results`  (+ list filter by `experiment_id`)
All relationship ids validated against the project (cross-project/user → 422; cross-user object → 404).

## 6. Proposed UI changes
`components/LabPanel.tsx` (or a sibling `ExperimentsPanel.tsx`) + tab(s): Experiments (status clearly
Proposed/Planned/Running/Completed/Failed/Cancelled/Inconclusive; planned never shown as executed),
Datasets (version/source/size/quality/limitations/access), Results (structured metrics with
value+unit+bounds+conditions, observations, anomalies, resource usage). Reuse Phase B card patterns.

## 7. KG implications
Add `experiment`/`dataset`/`result` entity types + `uses_dataset`/`produces`/`tests` predicates to
`knowledge/registry.py` (migration-free vocabulary). **Node emission by the graph builder is Phase G
(deferred)** — adding vocabulary changes no existing graph behavior.

## 8. Reproducibility implications
Phase C **captures** the metadata needed for future reproducibility on the Experiment row. It does
**not** compute or claim a reproducibility verdict — a `ReproducibilityRecord` + reproducible/partial/
not/unknown state is **Phase F (deferred)**. No field will imply reproducibility merely by existing.

## 9. Confidence/provenance reuse
`Result.confidence` reuses the 0–100 float representation (no second engine). `origin` on all three
objects (user/agent/derived) mirrors Phase B; a Result's provenance is explicit and never fabricated.

## 10. Existing tests covering related behavior
`test_rnd_phase_a.py`, `test_rnd_phase_b.py` (CRUD/ownership/cross-project/offline/planner patterns to
mirror); `test_research_again.py`, `test_research_diff.py`, `test_monitoring_*`, `test_pipeline*` must
stay green (Phase C is additive and must not touch them).

## 11. Architectural blockers
**None.** Fully additive. The only judgment calls (documented, not blockers):
- **Result → Evidence/Claim bridge:** turning a Result into first-class evidence for a Claim would
  touch the Analysis pipeline → **deferred to Phase D**. Phase C models the `Result` and its links so
  the bridge is a later addition, not a redesign.
- **Research Diff / Memory / Monitoring inclusion** of experiments/datasets/results → **deferred**
  (consumers, not blockers; rows remain queryable). Existing Diff/Again/Monitoring behavior is
  unchanged and must stay green.
- **Reproducibility verdict** → **Phase F**.

## 12. Explicitly deferred to later phases
Analysis/Conclusion/Recommendation integration (D); Result-as-evidence bridge (D);
reproducibility verdict record (F); per-object version-control framework (F); KG graph-builder node
emission (G); Diff/Memory/Monitoring inclusion (later); any execution/stats/scheduling engine (out of
scope entirely).

## Proposed test plan (implementation phase)
`test_rnd_phase_c.py`: Experiment/Dataset/Result CRUD; status validation + lifecycle;
planned≠executed + no-fabricated-result truthfulness gates; dataset version distinctness;
relationships (experiment→question/objective/hypothesis/method/dataset; result→experiment/dataset);
cross-user 404 + cross-project 422; offline (no provider constructed during CRUD); no experiment
tables leaking into Phase-D scope; migration idempotency + Phase A/B data preserved; planner context.
Frontend: Experiments/Datasets/Results render + create + status distinction + "not executed" cue.

---

**STOP 1.** Audit complete. Awaiting authorization to implement. No production code has been changed.

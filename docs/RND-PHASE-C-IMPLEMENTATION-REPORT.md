# R&D Laboratory Layer — Phase C Implementation Report (Experiments, Datasets, Results)

**Baseline:** `37d9bbf` (Phase B). **Scope:** Experiments + Datasets + structured Results only.
**Not committed** at time of writing (awaiting separate authorization).

## Executive Summary
Added three first-class research objects — **Dataset**, **Experiment**, **Result** — additively on
the Phase B substrate, completing the design→execution→measurement core of the digital thread
(Question→Objective→Hypothesis→Method→Experiment→Dataset→Result). Truthfulness is enforced *by
construction*: a fresh experiment is `proposed` with no execution data, the create contract can't set
execution fields, and a Result exists only when explicitly recorded. No new evidence/provenance/
confidence/authorization/KG/migration system was introduced — existing infrastructure was reused.

## Audit Findings
Experiments/Datasets/Results = **MISSING** before Phase C (`RND-PHASE-C-AUDIT.md`). No blockers;
fully additive. Result→Evidence bridge, Analysis/Conclusion, reproducibility verdict explicitly
deferred.

## Existing Infrastructure Reused
`models/experiment.py` (the Phase B module for this cluster); `api/rnd.py` + `_get_project`
(ownership) + `_validate_refs` (generalized to `_validate_object_links`/`_SINGLE_REF_MODELS`);
validated **string-set** enums + version idiom; 0–100 confidence float (`Result.confidence`); `origin`
provenance field; `knowledge/registry.py` (extensible KG vocabulary); `create_all` (additive tables);
`orchestrator._build_brief_context` (deterministic planner hint). No parallel engines.

## Method / Experiment / Dataset / Result Implementation
- **Dataset** — name, description, version, `supersedes_id`, source/source_url, license, data_type,
  size, record_count, features, collection_method/date, preprocessing, bias, limitations, quality,
  access_information, checksum, meta, origin. Version = new row; never overwritten.
- **Experiment** — name/description; digital-thread FKs (`question_id`/`objective_id`/`hypothesis_id`/
  `method_id`/`dataset_id`+`dataset_version`); design (independent/dependent/controlled variables,
  controls, assumptions, expected_result, failure_conditions, procedure, inputs, outputs, metrics);
  reproducibility metadata (hardware, software, software_versions, environment, configuration, seed);
  execution record (status, planned/started/completed_at, actual_result_summary, raw/processed data
  refs, execution_notes) — all execution fields nullable and only set by explicit PATCH; `origin`.
- **Result** — `experiment_id` (required), `dataset_id`; result_type; structured
  `metrics=[{name,value,unit,lower_bound,upper_bound,conditions}]`, measurements, benchmark, nullable
  error_rate/latency/throughput/accuracy/cost, resource_usage, observations, anomalies, data refs,
  conditions, confidence (nullable), origin, notes.

## Database Changes
3 new tables `datasets`, `experiments`, `results` via `create_all`. **No** columns added to existing
tables; **no** `_ADDED_COLUMNS` change. All carry `project_id` (FK CASCADE). Idempotent on
fresh/existing/twice-run DBs; Phase A/B/earlier data preserved (tested
`test_migration_idempotent_preserves_earlier_phases`).

## API Changes
`api/rnd.py` extended with full CRUD for `.../datasets`, `.../experiments`, `.../results` (+ results
list filter by `experiment_id`). Ownership via `_get_project`; every relationship id validated to the
same project (`_validate_object_links` now covers question/objective/hypothesis/method/dataset/
supersedes/experiment) → cross-project 422, cross-user 404. `ExperimentCreate` intentionally omits
execution fields. Delete-experiment explicitly deletes its results (SQLite FK cascade not enforced).

## Frontend Changes
`components/ExperimentsPanel.tsx` + an **Experiments** tab in `LiveResearch`. Sections: Experiments
(status badge; a non-executed experiment shows **"Not executed"** and hides execution details until
recorded), Datasets (version/source/size/quality/limitations/access), Results (structured metric
value+unit+bounds+conditions, observations, anomalies, resource usage). `api/client.ts` + `types.ts`
extended. Tests: `ExperimentsPanel.test.tsx`.

## Knowledge Graph Changes
`knowledge/registry.py`: added `experiment`/`dataset`/`result` entity types + `uses_dataset`/
`produces`/`tests` predicates (migration-free vocabulary). **Node emission deferred to Phase G** — no
existing graph behavior changed.

## Planner / Orchestrator Changes
`_build_brief_context` now also lists experiments (name+status, flagged "planned ≠ executed") and
datasets (name+version). Deterministic; **no new LLM/embedding call**; None when nothing exists.

## Provenance
`origin` (user/agent/derived) on all three objects; a dataset is only described as ResearchMind-
collected when explicitly marked; a Result's provenance is explicit and never fabricated.

## Versioning
Dataset versions are distinct rows (`supersedes_id` links lineage; earlier versions retained). Results
carry `dataset_id` (and experiments carry `dataset_version`) so a result stays attributable to the
inputs it came from. A universal version-control framework remains **Phase F**.

## Offline Behavior
All CRUD deterministic + network-free. `test_phase_c_crud_makes_no_llm_call` monkeypatches
`get_provider` to raise and confirms dataset/experiment/result CRUD never constructs a provider.

## Security
Ownership via `_get_project` (cross-user → 404, no leak); per-project reference validation
(cross-project experiment/dataset/hypothesis/… → 422). Tested: `test_cross_user_phase_c_is_404`,
`test_result_requires_valid_experiment_in_project`, `test_experiment_cross_project_hypothesis_rejected`,
`test_dataset_cross_project_supersedes_rejected`, `test_phase_c_requires_auth`.

## Performance
O(1) inserts/updates; reference validation = one bounded query per id-list / one `get` per single ref.
No new LLM/embedding calls, no background workers, no unbounded graph ops, no N+1.

## Tests
- Backend `test_rnd_phase_c.py`: **18** (dataset CRUD + version distinctness + cross-project supersedes;
  experiment planned≠executed + create-ignores-execution-fields + explicit-execution-PATCH +
  relationships + cross-project; result structured metrics + requires-experiment + invalid-type +
  cascade-on-experiment-delete; truthfulness no-fabrication + no-LLM; cross-user 404 + auth; migration
  idempotency; planner context).
- Frontend `ExperimentsPanel.test.tsx`: **4** (render + "Not executed"; execution hidden while
  proposed; recorded outcome revealed when executed; create experiment).

## Regression Results
- Backend: **406 passed** (388 → +18) · Frontend: **69 passed** (65 → +4)
- Typecheck **PASS** · Build **PASS** · #9 **30/30 (no failures)** · #10 **1.0 / 0.677** · #11 offline in-suite
- No existing test modified; no threshold weakened.

## Known Limitations
- KG builder does not yet emit experiment/dataset/result **nodes** (vocabulary only) — Phase G.
- Research Diff / Memory / Monitoring do not yet include Phase C objects — deferred (consumers, not
  blockers; rows queryable).
- Reproducibility is **captured** but no verdict is computed — Phase F.

## Deferred Phase C Work (→ later phases, documented, not implemented)
Result→Evidence/Claim bridge + Analysis/Conclusion/Recommendation (Phase D); reproducibility verdict
& universal versioning (Phase F); KG node emission (Phase G); Diff/Memory/Monitoring inclusion (later);
execution/stats/scheduling engines (out of scope).

## Master Specification Completeness
- Before Phase C: Experiments/Datasets/Results = MISSING.
- After Phase C: Experiments = **COMPLETE**, Datasets = **COMPLETE**, Results = **COMPLETE**.
- Overall R&D master-spec completeness: **≈48% → ≈60%** (front matter + methods + hypotheses +
  experiments + datasets + results done; analysis/conclusions/limitations/comparisons/timeline/
  reproducibility-verdict/stage-recovery/full-traceability remain).

## Confirmation
No Phase D+ implementation occurred. No analysis/conclusion/recommendation rewrite, no stats/execution
engine, no scheduling, no marketplace, no unrelated refactoring. Phase A/B commits intact.

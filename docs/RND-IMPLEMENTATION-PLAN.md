# ResearchMind — R&D Engineering Laboratory Layer: Implementation Plan

**Input:** `RND-REQUIREMENTS-GAP-AUDIT.md` (baseline ≈40%). **Baseline commit:** `d82bec2`.
**Principle:** extend the existing substrate; additive schema only; deterministic + offline-first;
no new mandatory LLM calls; ownership-scoped; tests + regression per phase; commit only when clean
and only when the user says so.

## Global design rules (apply to every phase)
1. **Additive persistence.** New tables via `create_all`; new nullable columns via
   `database._ensure_columns` + `_ADDED_COLUMNS`. Every table carries `project_id` (+`user_id`
   nullable where the KG pattern needs it). No destructive migration. Existing rows keep working.
2. **Ownership.** All new REST routes go through `_get_project(db, id, user)` (404-no-leak) and are
   scoped to the project's owner. MCP/`v1` reuse the capability layer's `owned_project`.
3. **Manual/CRUD-first, deterministic.** The lab objects (methods/hypotheses/experiments/datasets/
   results/conclusions/limitations/terminology/brief/objectives) are **researcher-entered structured
   data**, not LLM-generated. IDs, status transitions, links, traceability, and progress are
   deterministic. LLM assistance (e.g. "suggest hypotheses from gaps") is **optional, bounded, and
   off by default** behind a setting — never required for the object to exist.
4. **Truthfulness (§46).** An experiment that hasn't run has no result; an unsupported conclusion is
   marked so; results never live only in report prose. Reuse zero-evidence protection.
5. **Report (§47).** New sections are assembled from rows in `report._assemble` (LLM writes prose
   only). Sections appear **only when rows exist** (like the existing conflict/health disclosure).
6. **KG (§33).** Add entity types + predicates to `knowledge/registry.py` (no migration) and extend
   `knowledge/graph.py:build_graph_for_project` to mention the new rows. Conservative resolution
   unchanged.
7. **Tests + regression per phase.** New unit + integration + ownership + offline tests; then the
   full backend suite, frontend suite, typecheck, build, and #9/#10/#11 must stay green. Bump
   CLAUDE.md counts. STOP the phase if unstable (spec §50/§55).

## Schema strategy
One new module per cluster to keep `models/research.py` readable, all imported in `models/__init__`:
- `models/brief.py` — `ResearchBrief`, `Objective`, `ScopeItem`/`Constraint`, `Terminology`.
- `models/experiment.py` — `Method`, `Hypothesis`, `Experiment`, `Dataset`, `Result`, `Comparison`.
- `models/analysis.py` — `Analysis`, `Limitation`, `Conclusion` (+ extend `Recommendation` links,
  extend `KnowledgeGap`).
- `models/lifecycle.py` — `TimelineEvent`, `ResearchLogEntry`, `StageCheckpoint`, `ErrorRecord`,
  `ReproducibilityRecord`.
Enums added to `models/enums.py` (string enums, extensible where the KG pattern applies).

---

## PHASE A — Brief, Objectives, Scope/Constraints, Questions, Terminology
**Goal:** the research "front matter" as structured, editable, version-aware data.
- **Models:** `ResearchBrief` (1:1 project: problem_statement, background, scope_included,
  scope_excluded, assumptions, target_users, expected_outcome, success_criteria; `version` int).
  `Objective` (description, priority, status, completion_pct, links). `Constraint` (type enum +
  text). `Terminology` (term, definition, synonyms[], acronyms[], related[], source_id?, confidence).
  Extend `ResearchQuestion` (nullable cols via `_ensure_columns`: `category`, `q_status`, `answer`,
  `confidence`).
- **API:** `GET/PUT /research/{id}/brief`; `GET/POST/PATCH/DELETE /research/{id}/objectives`;
  `.../scope`, `.../constraints`, `.../terminology`; extend questions routes with the new fields.
- **Planner reuse:** brief/scope/constraints feed `planner.make_plan` as additional context
  (deterministic string assembly; zero new LLM calls — same pattern as `_build_prior_context`).
- **Frontend:** editable Brief panel + Objectives/Scope/Terminology tabs; Questions tab shows
  category/status/answer.
- **Tests:** CRUD, ownership 404, version bump, planner-context wiring, offline. **~15 tests.**

## PHASE B — Methods & Hypotheses
- **Models:** `Method` (name, description, procedure, inputs[], outputs[], assumptions[], pros[],
  cons[], limitations[], source_id?, applicable_conditions). `Hypothesis` (statement, reasoning,
  variables[], expected_result, actual_result, `status` proposed/testing/supported/partially/
  rejected/inconclusive, confidence; links to evidence/claims). **Distinct from Conclusion** — a
  hypothesis never auto-becomes a conclusion.
- **API:** `/research/{id}/methods`, `/research/{id}/hypotheses` (CRUD).
- **Frontend:** Methods + Hypotheses tabs.
- **Tests:** CRUD, status lifecycle, hypothesis≠conclusion invariant, ownership. **~12 tests.**

## PHASE C — Experiments, Datasets, Results
**Goal:** the lab core; strict anti-fabrication.
- **Models:** `Dataset` (name, version, source_id?, license, size, num_records, features[],
  data_type, preprocessing, known_biases[], limitations[], quality, access_method) — versions
  preserved (new row per version). `Experiment` (name, objective_id?, question_id?, method_id?,
  hypothesis_id?, variables, controls, hardware, software, environment, dataset_id?, configuration,
  procedure, inputs, outputs, metrics[], expected_result, actual_result, `status`
  planned/ready/running/completed/failed/cancelled/reproducible/non_reproducible/inconclusive).
  `Result` (experiment_id, dataset_id?, metric, value, unit, conditions, measurement_type, raw/
  processed, stats, benchmark, error_rate, latency, throughput, accuracy, cost, resource_usage,
  observation, anomaly, confidence).
- **Invariants (tested):** a `Result` requires an `Experiment` in a run/completed state; an
  experiment not `completed` never exposes results as authoritative; results are structured rows,
  never report-only.
- **API:** `/research/{id}/experiments` (+`/{eid}/results`), `/research/{id}/datasets`.
- **Frontend:** Experiments (with lifecycle), Datasets, Results tabs.
- **Tests:** CRUD, lifecycle, no-result-without-run, dataset versioning (no silent replace),
  ownership, offline. **~20 tests.**

## PHASE D — Comparisons, Limitations, Analysis, Conclusions
- **Models:** `Comparison` (subject_a, subject_b, criterion, value, unit, conditions, source_id?,
  experiment_id?, result_id?, confidence) — coexists with the existing `Solution` table (Solution =
  the qualitative recommendation matrix; Comparison = atomic evidence-linked data points).
  `Limitation` (type, description, severity, affected_object_ref, evidence, impact, mitigation,
  status). `Analysis` (statement, `classification` FACT/INTERPRETATION/INFERENCE/HYPOTHESIS/OPINION,
  links to sources/evidence/claims/results). `Conclusion` (statement, `classification`
  proven…disproved, confidence, links to claims/evidence/experiments/results/questions/limitations/
  contradicting-evidence, reasoning). Extend `Recommendation` (nullable links to conclusions/
  experiments/results, `priority`; keep the existing single-rec path working, allow N via a new
  route).
- **Anti-hallucination:** classification never silently upgraded; unsupported conclusion →
  `inconclusive/unknown`; reuse verification signals for "contradicted".
- **API:** `/research/{id}/comparisons`, `.../limitations`, `.../analysis`, `.../conclusions`;
  extend recommendations.
- **Frontend:** Comparisons/Limitations/Analysis/Conclusions tabs; classification badges.
- **Tests:** CRUD, classification rules, traceability links, conclusion↔evidence, ownership.
  **~20 tests.**

## PHASE E — Timeline, Research Log, Full lifecycle state, Failure recovery (stage-level)
- **Models:** `TimelineEvent` (append-only: event_type, ts, ref_id, summary). `ResearchLogEntry`
  (append-only: ts, actor, action, query?, decision?, reason?, ref?, error?). `StageCheckpoint`
  (project_id, stage, status pending/running/completed/failed, artifact_counts JSON, last_error?,
  attempt). `ErrorRecord` (project_id, ts, stage, component, error_type, message, retry_count,
  recovery_action, status).
- **Orchestrator (additive):** after each existing stage boundary in `run_research`, write a
  `StageCheckpoint` + `TimelineEvent` (deterministic, no new LLM). On failure, write `ErrorRecord`
  and mark the failed stage. **Retry Failed Stage** (§27) and **Continue From Last Successful
  Stage** (§28): new `POST /research/{id}/recovery` action that re-enters the orchestrator from the
  first non-completed checkpoint, reusing `reset_project_for_retry`'s cleanup semantics **scoped to
  that stage's artifacts only**. Emit timeline/log entries; preserve error history.
- **STOP condition:** if durable stage re-entry cannot be made safe under the single `_db_lock`
  write model without rewriting `run_research`, stop and report (spec §55) — ship §27/§28 as a
  documented PARTIAL rather than risk the completed orchestrator.
- **Frontend:** Timeline + Research Log tabs; failure panel with Restart / Retry Stage / Continue /
  View Error (extends `FailedResearchCard`).
- **Tests:** checkpoint writes, timeline/log append-only, stage retry preserves prior stages, error
  history preserved after success, ownership. **~20 tests.**

## PHASE F — Reproducibility & Versioning
- **Models:** `ReproducibilityRecord` (per run/experiment: model, model_version, prompt/system,
  tools, search_queries, search_date, dataset_version, software_version, git_commit, hardware, os,
  env, config, seed, raw/processed results) with explicit state reproducible/partial/not/unknown —
  **never claims reproducible when metadata is missing**. Per-object version history only where §31
  demands (brief/claims/conclusions/recommendations): pragmatic immutable-snapshot rows, reusing the
  lineage idea, not full event sourcing.
- **API:** `/research/{id}/reproducibility`; version endpoints where added.
- **Tests:** reproducibility-state honesty, version preservation, offline. **~12 tests.**

## PHASE G — Knowledge Graph expansion + full traceability
- **Registry:** add entity types (experiment, method, dataset, result, hypothesis, conclusion,
  limitation, objective, question) + predicates (tests, uses, produces, informs, affects, motivates,
  measures, concludes) to `knowledge/registry.py` (**no migration**).
- **Builder:** extend `knowledge/graph.py:build_graph_for_project` + `kg_mentions` to connect the new
  rows (deterministic, idempotent, conservative resolution unchanged).
- **Traceability API:** `GET /research/{id}/trace/{object}/{oid}` returning forward+reverse chains
  (recommendation→conclusion→claim→evidence→source; hypothesis→experiment→dataset→result→claim).
- **Frontend:** traceability drill-down in Conclusions/Recommendations; graph shows new nodes.
- **Tests:** KG build with lab nodes, both trace directions, no false merges, depth clamp, ownership.
  **~15 tests.**

## PHASE H — Final Report + UI + REST/MCP integration
- **Report:** extend `report._assemble` with Methodology / Experiments / Experimental Results /
  Comparative Analysis / Limitations / Conclusions / Future Research / Evidence Traceability
  sections — each rendered **only when rows exist**, from structured data.
- **UI:** wire the full tab set into `LiveResearch`; Overview shows counts (sources/docs/evidence/
  claims/verified/conflicts/methods/experiments/datasets/results/gaps/hypotheses/conclusions/
  recommendations/failures) + recovery controls.
- **MCP/`v1`:** add read-oriented capabilities for the new objects (brief/questions/objectives/
  experiments/results/conclusions/recommendations/timeline/trace) through the existing capability
  layer only — strict schemas, bounded output, ownership, error mapping. No new MCP server.
- **Tests:** report sections from rows, UI tabs, REST↔MCP equivalence + cross-user isolation for new
  capabilities. **~20 tests.**

---

## Sequencing & checkpoints
A→B→C→D→E→F→G→H. Each phase is independently shippable and leaves the app green. After each phase I
will report status and **pause for your commit instruction** (per your standing rule). Phases C and E
are the largest/riskiest (lab core; orchestrator stage-recovery) — expect a mid-phase check-in.

## What this plan will NOT do
No rewrite of orchestrator/evidence/claims/verification/diff/again/monitoring/KG/provenance/
connectivity/documents/REST/MCP; no second DB, diff engine, evidence/source store, or research-run
table; no new mandatory LLM calls; no fabricated experiment results; no destructive migration; no
weakening of ownership/rate-limiting/provenance; no changes to #9/#10/#11 fixtures or scores.

## Estimated new tests: ~150 across phases (backend + frontend), plus full regression each phase.

## Honest completeness trajectory
Baseline ≈40% → after A ≈50% → C ≈65% → D ≈75% → E ≈83% → G ≈90% → H ≈95%. Final % will be recomputed
from the requirements matrix with the same COMPLETE-means-implemented-persisted-integrated-tested bar.
Reproducibility of *actually executed* experiments (§30) may remain PARTIAL if the environment can't
run real experiments — that will be disclosed, not faked.

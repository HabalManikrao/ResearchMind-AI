# R&D Laboratory Layer — Phase B Audit (Methods & Hypotheses)

**Baseline:** Phase A commit `1292e5901bda4836d6b30ed1d2bb794fd03085bd` (working tree clean).
**Scope:** Methods + Hypotheses only. Experiments/Datasets/Results are **Phase C** — Phase B only
makes the architecture *ready* for them (no experiment tables, no fake results).
**Method:** static inspection of `backend/app/{models,api,schemas,agents,orchestration,knowledge}`,
`frontend/src`, and the test suites. Evidence-based statuses; "COMPLETE" is never claimed for a
free-text field that merely resembles the object.

## Requirement → current state

| Requirement | Status (before B) | Evidence / notes |
|---|---|---|
| Method model | **MISSING** | `grep class (Method\|Hypothesis)` over `app/models/` → NONE. Models present: user, schedule, document, cache, enums, research, monitor, notification, graph, **brief** (Phase A). |
| Hypothesis model | **MISSING** | same. |
| Method↔Source/Evidence/Claim links | **MISSING** (substrate present) | `Source`, `Document`, `ClaimSource`, `Claim` all exist and are reused — no new evidence system needed. |
| Hypothesis↔Question/Objective/Claim/Evidence links | **MISSING** (substrate present) | `ResearchQuestion` (Phase A first-class), `Objective` (Phase A), `Claim`, `ClaimSource`, `Source` exist. |
| Method/Hypothesis API | **MISSING** | `api/rnd.py` (Phase A) is the natural home; reuses `research._get_project` (404-no-leak). |
| Status validation | **PATTERN READY** | Phase A established validated **string sets** in `enums.py` (no Enum columns → migration-free). Reuse for method/hypothesis statuses. |
| Versioning | **PATTERN READY** | `ResearchBrief.version` bumps on edit (`api/rnd.py:update_brief`). Reuse the same `version+bump` idiom for Method. |
| Provenance | **PATTERN READY** | `Source.meta["provenance"]` (#5) for collected evidence; for authored objects a simple `origin` field (user/agent/derived) is the honest analogue. |
| Confidence | **REUSE** | `Claim.confidence` (0–100 float) + `confidence_meta`. Hypothesis reuses the 0–100 float representation; **no second confidence engine**. |
| Planner integration | **EXTEND** | Phase A `orchestrator._build_brief_context` → `planner.make_plan(brief_context=)`. Extend the same deterministic hint (no new LLM) to list existing methods/hypotheses. |
| Knowledge Graph | **REGISTRY EXTEND** | `knowledge/registry.py` entity types/predicates are **string sets, migration-free**. Add `method`/`hypothesis` types + `addresses`/`derived_from`/`supported_by`/`uses_method`/`has_method`/`has_hypothesis` predicates so the vocabulary exists. Full graph-builder node emission is **Phase G** (deferred, documented). |
| Research Diff | **DEFERRED** | `research_diff` diffs sources/claims/recommendation. Methods/Hypotheses diff belongs with the broader object-diff work; adding it now would bloat the engine for little Phase-B value. Deferred + documented (spec §36 allows). |
| Research Again / Memory | **DEFERRED (minimal-safe)** | Lineage/memory are consumers, not blockers. Method/Hypothesis carry-forward + memory-summary counts are deferred to a later phase; Phase B ensures the rows are queryable so future phases can consume them. |
| Monitoring | **DEFERRED** | Future monitoring may re-open hypotheses; Phase B only ensures status/confidence/provenance are persisted + queryable. No new monitoring. |
| Frontend Methods/Hypotheses tabs | **MISSING** | `LiveResearch` tab system + Phase A `BriefPanel` pattern to reuse. |
| Tests | **MISSING** | New `test_rnd_phase_b.py` + frontend component tests. |

## Design decisions (reuse-first)

1. **New module `models/experiment.py`** holding **only `Method` and `Hypothesis`** for Phase B
   (the module is where Phase C will add `Experiment`/`Dataset`/`Result`). New tables via
   `create_all`; both carry `project_id` (FK CASCADE) → inherit the project ownership boundary.
2. **Relationships as JSON id-lists**, not join tables — consistent with the existing
   `Claim.supporting_source_ids` / `Objective.question_ids` (Phase A) pattern, and the simplest thing
   that works (spec §29 "do not automatically create every relationship as a join table"). Fields:
   - `Method`: `source_ids`, `claim_ids` (supporting research); `version`; `origin`.
   - `Hypothesis`: `question_ids`, `objective_ids`, `claim_ids`, `source_ids`, optional `method_id`;
     `status`, `confidence`, `origin`, plus optional `expected_result`/`variables`/`assumptions`.
   API validates every referenced id belongs to the **same project** (ownership can't be crossed).
3. **Status/origin = validated string sets** in `enums.py` (patterns), not Enum columns → new members
   need no migration. `METHOD_STATUSES = proposed|active|deprecated|superseded`;
   `HYPOTHESIS_STATUSES = proposed|testing|supported|partially_supported|rejected|inconclusive`;
   `RND_ORIGINS = user|agent|derived`.
4. **Method version-aware** (`version` bumps on PATCH, like `ResearchBrief`). Hypothesis lifecycle is
   captured by `status` (rejected hypotheses are never deleted on reject — they remain visible).
5. **Truthfulness:** status is set only by explicit client action; nothing auto-advances PROPOSED →
   SUPPORTED. No experiment/result rows exist to fabricate. `origin="derived"` is honest only when
   source/claim links are provided (UI/reporting reads the links, never invents "literature-derived").
6. **Experiment-readiness (Phase C):** `Hypothesis.method_id` + the JSON link lists give Phase C a
   clean `Experiment(hypothesis_id, method_id, dataset_id)` to reference **without** any Phase-B
   redesign. No placeholder Experiment table is created.

## Database changes required
- New tables `methods`, `hypotheses` (via `create_all`). **No** `_ADDED_COLUMNS` entries needed
  (no columns added to existing tables). Idempotent on fresh/existing/twice-run DBs; Phase A data
  (`research_briefs`/`objectives`/`constraints`/`terminology`/questions) untouched.

## API changes required
- Extend `api/rnd.py`: CRUD `GET/POST/GET{id}/PATCH/DELETE` for `.../methods` and `.../hypotheses`,
  ownership via `_get_project`, referenced-id ownership validated against the project.

## KG changes required
- Add entity types + predicates to `knowledge/registry.py` (migration-free). Builder wiring deferred
  to Phase G.

## Orchestration/planner changes required
- Extend the deterministic planner hint to mention existing methods/hypotheses (no new LLM call).

## Tests required
- Backend `test_rnd_phase_b.py`: Method/Hypothesis CRUD, status + confidence validation, versioning,
  ownership (cross-user 404), cross-project reference rejection, relationship wiring
  (hypothesis→question/objective/claim/method), truthfulness (no auto-advance; create makes no LLM
  call), offline, planner context, migration idempotency, Phase-A regression.
- Frontend: Methods & Hypotheses panels render/create/validate; status + "not yet validated" cue.

## Blockers
**None.** Fully additive on the Phase A substrate; no rewrite of orchestrator/evidence/claims/KG; no
migration risk; ownership guaranteed by `_get_project` + per-project reference validation.

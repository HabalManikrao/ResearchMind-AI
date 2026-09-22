# R&D Laboratory Layer — Phase D Audit (Analysis, Conclusions & Recommendations)

**STOP 1 — audit only. No production code, schema, API, frontend, or tests were changed.**

- **Baseline verified:** HEAD = `8fafa26821e3c20b8dbf0934bd1b7e5a0e3bad4a` (Phase C). Working tree
  **clean**. `origin/master` is 1 behind (Phase C not pushed — expected). Ancestry confirmed: Phase A
  `1292e59`, Phase B `37d9bbf`, Phase C `8fafa26` are all ancestors-or-HEAD.
- **Scope:** Result→Evidence/Claim integration, structured **Analysis**, structured **Conclusions**,
  **Recommendation** extension, full traceability, final-report integration, UI, KG vocabulary,
  diff/memory/monitoring + confidence/provenance/versioning implications.
- **Method:** repository is the source of truth. Two read-only sub-audits over `rd_analysis.py`,
  `report.py`, `models/research.py`, `research_diff.py`, `orchestrator.py`, `significance.py`,
  `knowledge/{registry,graph}.py`, `api/{rnd,research}.py`, `schemas/research.py`,
  `frontend/.../LiveResearch.tsx`.

## 1. Result → Evidence → Claim
- **Evidence model:** `ClaimSource` (`models/research.py:284-309`) links `Claim`→**`Source`** (FK
  `source_id → sources.id`) with `stance` + quoted `passage`. This is the authoritative evidence edge;
  confidence via `verification.score_claim`; provenance via `Source.meta["provenance"]`.
- **Gap:** a `Result` (Phase C) is **not** a `Source`, so it **cannot currently become
  ClaimSource-style evidence** — **MISSING** bridge. Reuse-first fix: the new **Analysis** object is
  the join point (holds `claim_ids` + `result_ids` + `experiment_ids` + `source_ids`), so a Result
  becomes traceable *through Analysis* without a second evidence system and without forcing Results
  to masquerade as Sources. (A direct `Claim`↔`Result` link is **DEFERRED** — not needed for the
  Phase D chain.)

## 2. Analysis
- **MISSING** entirely. No `Analysis` model/schema/API/UI/KG type. The FACT / INTERPRETATION /
  INFERENCE / HYPOTHESIS / OPINION distinction does **not** exist anywhere. "Analysis" today is only
  the LLM-prose `## Detailed Analysis` heading in `report.py` and progress labels. Reuse: claims,
  sources, results, confidence (0–100), provenance (`origin`) — all exist and would be *referenced*,
  not duplicated.

## 3. Conclusions
- **MISSING** entirely. No `Conclusion` model/schema/API/UI/KG type; none of Proven / Strongly
  Supported / Supported / Weakly Supported / Inconclusive / Unknown / Contradicted / Disproved exists.
  "Conclusions" live only as LLM prose inside `## Executive Summary` / `## Detailed Analysis` in
  `report.py` — **backed by no structured row** (a core spec violation: the report prose is currently
  a de-facto source of truth for conclusions).

## 4. Recommendations
- **PARTIAL.** `Recommendation` (`models/research.py:355-373`) is first-class end-to-end:
  `recommended_option`, `rationale`, `why`, `confidence(0–100)`, `alternatives[]`, `risks[]`,
  `proof_of_concept`, `roadmap[]`. Produced by `rd_analysis.analyse()` (3 constrained LLM stages),
  persisted by `orchestrator._rd_analysis` (delete-first; single row per project), exposed at
  `GET /research/{id}/recommendation`, diffed (`research_diff._diff_recommendation`), carried in
  memory + significance, rendered in `RecommendationTab`.
- **Gaps vs master:** the **only** FK is `project_id`. `recommended_option` is free text; it links to
  `Solution` **only by a fuzzy name-match boolean** (`is_recommended`, `rd_analysis.py:224-229`). No
  links to **conclusions / analysis / experiments / results / claims / evidence**; no `priority`; no
  trade-offs/expected-benefit; single-per-project (no multiple recommendations).
- **Must extend, not replace** (the auto-generated recommendation is valuable): add nullable link
  columns + priority; allow linking to conclusions/results/experiments.

## 5. Full traceability (edge-by-edge)
| Edge | Status | Mechanism / gap |
|---|---|---|
| Source → Claim | **COMPLETE** | `ClaimSource` (stance+passage). |
| Claim → (verify/confidence) | **COMPLETE** | `verification.score_claim` + `confidence_meta`. |
| Result → Evidence/Claim | **MISSING** | Result isn't a Source; bridge via new Analysis (`result_ids`+`claim_ids`). |
| Experiment/Dataset → Result | **COMPLETE** | Phase C `Result.experiment_id`/`dataset_id`. |
| Claim → Analysis | **MISSING** | No Analysis object. |
| Analysis → Conclusion | **MISSING** | Neither object exists. |
| Conclusion → Recommendation | **MISSING** | No Conclusion; Recommendation has no `conclusion_ids`. |
| Recommendation → Solution | **PARTIAL** | Fuzzy name-match boolean only, no id link. |
| Reverse chain (Rec→…→Source) | **MISSING** (mostly) | Only Claim→Source reverse exists today. |
No duplicate/parallel evidence systems exist — the substrate to reuse is `Claim`/`ClaimSource`/
`Source`/`verification`.

## 6. Final report
- Generated from a mix: **4 LLM-prose sections** (Executive Summary / Key Findings / **Detailed
  Analysis** / Knowledge Gaps; `report._SECTIONS`) + **deterministic injection** from rows
  (comparison / recommendation / why / alternatives / risks / PoC / roadmap / conflicts / sources /
  confidence / health via `_rd_md`, `_assemble`).
- **No `## Conclusions` section from rows** — conclusions are prose only.
- **Zero-evidence protection INTACT** (`_EVIDENCE_INCOMPLETE_NOTICE`, `evidence_incomplete = not
  data.sources`; narrative LLM skipped on zero sources) — **but source-gated**.
- **Truthfulness risk (confirmed path):** the recommendation block is **hard-gated on claims-or-
  findings** (`orchestrator._rd_analysis: if not claims and not findings: return ""`), but the
  narrative prose is gated **only on `not data.sources`**. A run with **sources but zero claims and
  zero findings** still invokes the LLM to write `## Detailed Analysis`/`## Executive Summary` with
  `(no claims consolidated)`/`(none)` — so **prose "conclusions" can be produced with no structured
  claim/finding rows behind them**, restrained only by the system prompt. Phase D closes this by
  rendering Conclusions **from rows** and tightening the narrative gate.

## 7. Knowledge Graph
- Entity types (post-C): person…document, method, hypothesis, experiment, dataset, result, other.
  **Missing:** `analysis`, `conclusion`, `recommendation`. Predicates lack `based_on`, `analyzes`,
  `interprets`, `informed_by` (`supported_by`/`derived_from` already exist).
- Builder (`graph.py`) emits Solution names + `recommended_option` as **`technology`** entities with
  `related_to`/`alternative_to` edges. No Analysis/Conclusion/Recommendation node type. Node emission
  for R&D types is **Phase G (deferred)** — Phase D adds **vocabulary only**.

## 8. Research Again / Diff / Memory / Monitoring
- **Diff:** `_diff_recommendation` classifies unchanged/new/removed/`reversed`/`modified`; `_diff_claims`
  classifies new/removed/strengthened/weakened/contradicted. **No** analysis/conclusion diff.
- **Memory:** `_build_memory_summary` captures claims + recommendation (option+confidence). **No**
  analysis/conclusion.
- **Significance/Monitoring:** already keys on **recommendation reversal → CRITICAL** and **claim
  contradiction → CRITICAL/HIGH** (`significance._recommendation_changes`/`_claim_changes`). So the
  spec's *"new evidence → affected claims → affected recommendation"* flow **already works** through
  the existing diff+significance engines — **no second diff/lineage engine is needed**. Extending it
  to analysis/conclusion changes is optional and **DEFERRED** (or minimal), documented not built.

## 9. Confidence / Provenance
- Confidence exists at Source (`reliability_score`), Claim (`confidence`+`confidence_meta` reasons,
  computed by `verification`), Recommendation (`confidence`, LLM number). **No structured confidence**
  for Analysis/Conclusion — Phase D reuses the **0–100 float + reasons** convention (no second
  engine); a Conclusion's confidence is derived from / consistent with its supporting claims, never
  invented. Provenance flows via `origin` (user/agent/derived) on the new objects + the existing
  claim/source evidence links.

## 10. Versioning / History
- Only **run-level** lineage (Research Again / `root_id` / `research_diff`). No per-object version
  history for Result/Evidence/Claim/Analysis/Conclusion/Recommendation. **Phase D groundwork:**
  Analysis/Conclusion are immutable-ish rows rebuilt or edited in place; keep `origin` + timestamps.
  **Universal per-object versioning is Phase F (deferred)** — Phase D must not build it.

## 11. API / Capability
- `api/rnd.py` has CRUD for brief/objectives/constraints/terminology/methods/hypotheses/datasets/
  experiments/results (reuses `_get_project` + `_validate_object_links`/`_SINGLE_REF_MODELS`).
  `api/research.py` exposes `GET .../recommendation` (read-only, pipeline-generated) + `.../solutions`.
  **No** analysis/conclusion endpoints. Capability layer (`app/capabilities/`) + `/v1` + MCP do **not**
  cover Phase D objects. Extension is additive; **DEFERRED** whether to expose via `/v1`/MCP (keep
  Phase D to the browser-facing `rnd.py` router unless explicitly wanted).

## 12. Frontend
- Tabs: activity, brief, plan, sources, documents, claims, **lab** (Methods & Hypotheses),
  **experiments**, conflicts, **recommendation**, graph, report, monitoring. **No** Analysis or
  Conclusion tab. `RecommendationTab` renders the recommendation + solution-comparison table. Reuse
  the `LabPanel`/`ExperimentsPanel` pattern for new Analysis/Conclusions sections.

## 13. Security
- All Phase A–C objects use `_get_project` (cross-user → 404) + per-project reference validation
  (`_validate_object_links` → cross-project 422). Phase D objects **must** use the same:
  `analysis.{claim_ids,source_ids,result_ids,experiment_ids}`, `conclusion.{analysis_ids,claim_ids,
  source_ids,question_ids}`, `recommendation.{conclusion_ids,analysis_ids,result_ids,experiment_ids}`
  all validated to the same project. No new authorization mechanism.

## 14. Truthfulness risks (documented, NOT fixed in STOP 1)
1. **Prose conclusions unbacked** (sources-but-no-claims/findings path, §6) — narrative gate is
   source-only while recommendation gate is claims-or-findings.
2. **Recommendation grounding is prompt-only** — no code-level assertion that `recommended_option`
   maps to a verified claim/conclusion.
3. **No Conclusion rows** — the report's conclusions can't be traced to evidence at all today.
Phase D mitigations: render Conclusions from rows; require Analysis/Conclusion to carry ≥1 evidence
link; classification never auto-upgraded; tighten the narrative gate to claims/findings.

---

## EXACT GAP MATRIX
| Requirement | Master spec | Existing impl | Files | Status | Required change | Reuse | Deferred |
|---|---|---|---|---|---|---|---|
| Result→Evidence/Claim | Result traceable as evidence | ClaimSource is Claim↔Source only | `models/research.py:284` | **MISSING** | Analysis holds `result_ids`+`claim_ids` (join point) | ClaimSource/Claim/Source/verification | direct Claim↔Result link |
| Analysis (structured) | first-class + FACT/INTERP/INFER/HYP/OPINION | none | — | **MISSING** | new `Analysis` model+API+UI+KG-vocab | claims/results/confidence/origin | — |
| Conclusion (structured) | first-class + Proven…Disproved | prose only | `report.py` | **MISSING** | new `Conclusion` model+API+UI; render from rows | analysis/claim links, confidence | — |
| Recommendation links | rec→conclusion/evidence/experiment/result + priority/tradeoffs | only `project_id`; fuzzy name match | `models/research.py:355`, `rd_analysis.py:224` | **PARTIAL** | additive nullable link cols + priority (extend, don't replace) | existing Recommendation/diff/memory/significance | multi-rec optimization |
| Full traceability | fwd+reverse chain | only Claim↔Source | see §5 | **PARTIAL/MISSING** | id-link chain via Analysis/Conclusion | id-list validation pattern | KG node emission (G) |
| Report conclusions from rows | report = projection of objects | conclusions are prose | `report.py:_assemble/_rd_md` | **MISSING** | inject `## Conclusions`/`## Analysis` from rows; tighten gate | `_rd_md` injection pattern, zero-evidence guard | — |
| KG vocab (analysis/conclusion/recommendation) | entities+predicates | absent | `knowledge/registry.py` | **MISSING** | add types + `based_on`/`analyzes`/`interprets`/`informed_by` | registry (migration-free) | builder emission (G) |
| Diff of analysis/conclusion | update propagation | rec+claim diff only | `research_diff.py` | **DEFERRED** | none required (rec/claim path already covers propagation) | existing diff+significance | analysis/conclusion diff |
| Confidence for analysis/conclusion | structured | none | — | **MISSING** | reuse 0–100 + reasons | verification convention | — |
| Per-object versioning | history | run-level only | — | **DEFERRED** | none in D | lineage | **Phase F** |
| Reproducibility verdict | verdict state | metadata only (C) | — | **DEFERRED** | none in D | — | **Phase F** |

## PROPOSED PHASE D ARCHITECTURE (smallest that completes the chain)
**Chain:** Result → Evidence → Claim → **Analysis** → **Conclusion** → **Recommendation**.

1. **New models** (in a new `models/analysis.py`; tables via `create_all`, each `project_id` FK):
   - `Analysis` — `statement`, `classification` (fact|interpretation|inference|hypothesis|opinion),
     `reasoning`, `confidence?`, `origin`, links `claim_ids`/`source_ids`/`result_ids`/
     `experiment_ids`. **Must carry ≥1 evidence link** (claim/source/result) — enforced at API.
   - `Conclusion` — `statement`, `classification` (proven|strongly_supported|supported|
     weakly_supported|inconclusive|unknown|contradicted|disproved), `confidence?`, `reasoning`,
     `origin`, links `analysis_ids`/`claim_ids`/`source_ids`/`question_ids`, `contradicting_claim_ids`.
2. **Extend existing** (additive nullable cols via `_ADDED_COLUMNS`, no rewrite of `rd_analysis`):
   - `Recommendation` += `conclusion_ids`/`analysis_ids`/`result_ids`/`experiment_ids` (JSON),
     `priority`, `expected_benefit`, `tradeoffs` (nullable). Auto-generated single rec keeps working;
     user/agent can link it to conclusions.
3. **New relationships:** all as per-project-validated JSON id-lists (Phase B/C pattern); extend
   `_SINGLE_REF_MODELS`/`_validate_object_links` with analysis/conclusion/result/experiment refs.
4. **APIs:** `rnd.py` CRUD for `.../analysis`, `.../conclusions`; extend recommendation with a link
   PATCH (`api/research.py` or `rnd.py`). Ownership via `_get_project`; refs validated to project.
5. **UI:** Analysis + Conclusions sections (new tab or extend recommendation tab), reusing
   `LabPanel`/`ExperimentsPanel`; classification badges; traceability drill-down
   (Recommendation→Conclusion→Analysis→Claim→Evidence→Source/Result).
6. **KG vocabulary:** add `analysis`/`conclusion`/`recommendation` entity types + `based_on`/
   `analyzes`/`interprets`/`informed_by` predicates (vocabulary only; emission Phase G).
7. **Report:** inject `## Analysis` and `## Conclusions` **from rows** (only when rows exist, like the
   recommendation block); tighten the narrative gate to skip prose when there are no claims/findings
   (closes the §14.1 truthfulness gap). Zero-evidence protection preserved.
8. **Tests:** model/CRUD/validation/classification; ≥1-evidence-link enforcement; classification
   never auto-upgraded; cross-user 404 + cross-project 422; traceability chain; report rows-injection
   + truthfulness gate; migration idempotency (A/B/C/D data preserved); offline (no LLM in CRUD).
9. **Migration strategy:** new tables (`create_all`) + `_ADDED_COLUMNS` for the new nullable
   `Recommendation` columns. Idempotent; Phase A/B/C data preserved.
10. **Truthfulness protections:** Analysis requires evidence links; Conclusion requires ≥1 analysis
    or claim; no fabricated links; classification set only by explicit action; Conclusions rendered
    from rows so report prose is no longer the source of truth.

## EXPLICITLY DEFERRED (out of Phase D)
Analysis/Conclusion **diff & memory & monitoring inclusion** (rec/claim propagation already covers
the update flow); **KG graph-builder node emission** (Phase G); **reproducibility verdict** (Phase F);
**universal per-object version-control** (Phase F); advanced statistics / automated statistical
inference; autonomous experiment execution; decision intelligence; research autopilot; agent swarm;
portfolio intelligence; advanced recommendation optimization; direct Claim↔Result link table;
exposing Phase D via `/v1`/MCP (unless later requested).

## ARCHITECTURAL BLOCKERS
**None.** Fully additive on the existing Evidence→Claim→Verification→Confidence substrate. The single
non-model change proposed (tightening the report narrative gate + injecting Conclusions from rows) is
a small, well-scoped truthfulness fix in `report.py`, not a redesign. No parallel evidence/claim/
confidence/diff/lineage system is required.

---
**STOP 1 complete. No implementation performed. Awaiting authorization to implement Phase D.**

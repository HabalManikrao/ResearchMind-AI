# R&D Laboratory Layer — Phase D Implementation Report (Analysis, Conclusions & Recommendations)

**Baseline:** `8fafa26` (Phase C). **Scope:** the audited Phase D core — Result→Analysis→Claim
traceability, first-class **Analysis** & **Conclusion**, **Recommendation** extension, structured
report projection + truthfulness gate, KG vocabulary. **Not committed** at time of writing.

## Executive Summary
Completed the reasoning half of the digital thread —
**Result → Analysis → Claim → Conclusion → Recommendation** — entirely additively on the existing
Evidence (`ClaimSource`) / Claim / Verification / Confidence / provenance substrate. No second
evidence/claim/verification/confidence/authorization/diff/KG system was created. A `Result` becomes
traceable evidence **through Analysis** (never turned into a `Source`). The report now projects
`## Analysis` and `## Conclusions` from persisted rows, and a new truthfulness gate stops
sources-but-no-claims/findings runs from emitting LLM "conclusion" prose.

## Audit Findings
Analysis/Conclusion = MISSING; Recommendation = PARTIAL (only `project_id` FK, fuzzy Solution name
match); Result→Evidence bridge = MISSING; report conclusions = prose-only; one truthfulness gap
(sources-but-no-claims/findings). No blockers. Full detail: `RND-PHASE-D-AUDIT.md`.

## Existing Infrastructure Reused
`ClaimSource`/`Claim`/`Source`/`verification` (evidence + confidence); `_get_project` + generalized
`_validate_object_links` (ownership + cross-project ref validation); validated string-set enums +
`origin` provenance; `report._rd_md` injection pattern + `_EVIDENCE_INCOMPLETE_NOTICE` (zero-evidence
guard); `knowledge/registry.py` (extensible vocabulary); the existing single auto-generated
`Recommendation` + its diff/memory/significance/UI. Nothing duplicated.

## Analysis & Conclusion Implementation
`models/analysis.py`:
- `Analysis` — title, statement, `classification` (fact|interpretation|inference|hypothesis|opinion),
  reasoning, `confidence?`, `origin`, grounding link-lists `claim_ids`/`source_ids`/`result_ids`/
  `experiment_ids`. API **requires ≥1** of claim/source/result (`_require_grounding`). A `fact`
  classification carries no special verification — grounding is the links, not the label.
- `Conclusion` — title, statement, `classification` (proven|strongly_supported|supported|
  weakly_supported|inconclusive|unknown|contradicted|disproved), `confidence?`, reasoning, `origin`,
  links `analysis_ids`/`claim_ids`/`source_ids`/`question_ids`/`contradicting_claim_ids`. API requires
  ≥1 analysis or claim. Classification never auto-promoted; confidence nullable (absence preserved).

## Recommendation Extension (extended, NOT replaced)
`Recommendation` gains additive nullable columns (`_ADDED_COLUMNS`): `conclusion_ids`, `analysis_ids`,
`result_ids`, `experiment_ids`, `priority`, `expected_benefit`, `tradeoffs`. The pipeline still
generates the single recommendation exactly as before (never sets these); an explicit
`PATCH /research/{id}/recommendation/links` connects it into the chain. Existing `recommended_option`
/`rationale`/`confidence`/Solution behavior + diff/memory/significance/report unchanged.

## Database Changes
New tables `analyses`, `conclusions` (via `create_all`). Additive nullable columns on `recommendations`
(via `_ADDED_COLUMNS`). No existing table dropped/renamed; idempotent on fresh/existing/twice-run DBs;
Phase A/B/C data + existing recommendations preserved (tested).

## API Changes
`api/rnd.py`: CRUD `GET/POST/GET{id}/PATCH/DELETE` for `.../analysis` and `.../conclusions`;
`PATCH .../recommendation/links`. Ownership via `_get_project`; every relationship id validated to the
same project via generalized `_validate_object_links` + `_LIST_REF_MODELS`/`_SINGLE_REF_MODELS`
(cross-project → 422, cross-user → 404, no existence leak). No new authorization mechanism.

## Frontend Changes
`components/AnalysisPanel.tsx` + an **Analysis & Conclusions** tab: classification badges (visually
distinct from Claims), grounding shown, create controls **disabled until a grounding claim/analysis is
selected** (UI can't create an ungrounded item), classification change + delete. `RecommendationTab`
extended to show `priority`, `expected_benefit`, and a traceability line (linked conclusion/analysis
counts). `api/client.ts` + `types.ts` extended. Tests: `AnalysisPanel.test.tsx`.

## Knowledge Graph Changes
`knowledge/registry.py`: added `analysis`/`conclusion`/`recommendation` entity types + `analyzes`/
`interprets`/`based_on`/`informed_by` predicates (migration-free vocabulary). **Node emission deferred
to Phase G** — no existing graph behavior changed.

## Planner / Orchestrator Changes
`_build_report` now loads `Analysis`/`Conclusion` rows and passes them to `ReportInput`; the report
renders them deterministically. No new LLM/embedding call (Analysis/Conclusion are user/agent-authored
via API; a plain run has none, so the sections don't appear). No orchestrator redesign.

## Report / Truthfulness
- `## Analysis` and `## Conclusions` are injected **from rows** (`_analysis_conclusions_md`), only when
  rows exist — structured records are the source of truth, never regenerated prose.
- **Gate tightened:** `conclusions_unsupported = bool(sources) and not claims and not findings` → the
  LLM narrative is skipped and a "No evidence-backed conclusions available" notice shown. Source
  existence ≠ conclusion evidence. Zero-evidence protection (`evidence_incomplete`, source-gated)
  preserved and unchanged.
- Regression tests assert: analysis/conclusions render from rows; sections absent without rows;
  sources-without-claims/findings blocks narrative (LLM not called); normal path unaffected.

## Provenance / Confidence
`origin` on both new objects; confidence reuses the 0–100 float and is **nullable** (never fabricated).
No second confidence engine. A Result's/analysis's/conclusion's provenance is explicit.

## Offline Behavior
All CRUD deterministic + network-free. `test_phase_d_crud_makes_no_llm_call` monkeypatches
`get_provider` to raise and confirms analysis/conclusion CRUD constructs no provider.

## Security
Cross-user → 404 (`test_cross_user_phase_d_is_404`); cross-project refs → 422
(`test_cross_project_analysis_claim_rejected`, `test_recommendation_links_reject_cross_project`);
auth required (`test_phase_d_requires_auth`). Grounding enforced (`test_analysis_requires_grounding`,
`test_conclusion_requires_grounding`).

## Tests
- Backend `test_rnd_phase_d.py`: **19** (analysis grounding + all 5 classifications + Result bridge;
  conclusion grounding + all 8 classifications + confidence-absence + not-auto-promoted; recommendation
  link extension + preserved fields + cross-project + invalid priority; cross-user 404 + auth; no-LLM;
  report renders analysis/conclusions from rows; truthfulness gate blocks/allows narrative correctly).
- Frontend `AnalysisPanel.test.tsx`: **4** (render + badges + grounding; add-button gated on grounding;
  create grounded analysis; change conclusion classification).

## Regression Results
- Backend: **425 passed** (406 → +19) · Frontend: **73 passed** (69 → +4)
- Typecheck **PASS** · Build **PASS** · #9 **30/30 (no failures)** · #10 **1.0 / 0.677** · #11 offline in-suite
- No existing test weakened; no threshold changed. (Report tests Case D/E unaffected — the new gate
  only triggers when there are **no** claims AND **no** findings.)

## Known Limitations / Deferred
- KG builder does not emit analysis/conclusion/recommendation **nodes** (vocabulary only) — Phase G.
- Analysis/Conclusion **diff / memory / monitoring** inclusion — deferred (the existing rec/claim diff
  + significance already propagate new-evidence→affected-recommendation; documented, not built).
- **Comparisons** and **Limitations** first-class objects (grouped under the plan's Phase D heading)
  are **not** implemented — outside the authorized Phase D scope (Analysis/Conclusions/Recommendations
  only). Deferred.
- Reproducibility verdict + universal per-object versioning — **Phase F**.
- Multiple-recommendation optimization — out of scope.
- No `/v1` + MCP exposure of Phase D objects — deferred per the audit.

## Master Specification Completeness
- Before Phase D: Analysis MISSING, Conclusions MISSING, Recommendations PARTIAL.
- After Phase D: Analysis = **COMPLETE**, Conclusions = **COMPLETE**, Recommendations = **COMPLETE**
  (traceability extended).
- Overall R&D master-spec completeness: **≈60% → ≈72%** (the full evidence→claim→analysis→conclusion→
  recommendation chain is now first-class & traceable; comparisons/limitations, timeline/log,
  reproducibility-verdict, KG node emission, full versioning, and diff/memory/monitoring inclusion
  remain).

## Confirmation
No Phase E+ work implemented. No advanced statistics / autonomous experimentation / scheduling /
decision-intelligence / autopilot / agent-swarm / universal-versioning / reproducibility-verdict / KG
node-emission / analysis-conclusion diff engine. No unrelated refactoring. Phase A/B/C commits
untouched.

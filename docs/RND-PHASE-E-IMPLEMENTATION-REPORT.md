# R&D Laboratory Layer — Phase E Implementation Report (Comparisons, Limitations & Research Gaps)

**Baseline:** `eb3d5a1` (Phase D). **Scope:** the audited Phase E core — first-class Comparison &
Limitation, extension of the existing KnowledgeGap, report integration, KG vocabulary, truthfulness
gates. **Not committed** at time of writing.

## Executive Summary
Added first-class **Comparison** and **Limitation** objects and **extended the existing
`KnowledgeGap`** (no parallel gap system) — all additively on the existing ownership / per-project
reference-validation / report-injection / KG-registry substrate. No second evidence/claim/confidence/
provenance/relationship/KG/verification system. Comparison values are recorded data (never inferred),
flagged **ungrounded** unless they reference a source/experiment/result; limitations reference the
affected object + evidence; gaps remain **open questions, never verified facts**. The report now
projects `## Comparisons`, `## Limitations`, and `## Research Gaps` from persisted rows.

## Audit Findings
Comparison = PARTIAL (Solution table only); Limitation = PARTIAL (inline JSON fields on Method/Dataset);
Research Gap = PARTIAL (KnowledgeGap: 5 fields, read-only, auto-generated). No blockers. Full detail in
`RND-PHASE-E-AUDIT.md`.

## Existing Infrastructure Reused
`_get_project` + generalized `_validate_object_links`/`_LIST_REF_MODELS`; validated string-set enums +
`origin` provenance + nullable 0–100 confidence; `report._rd_md`/`_analysis_conclusions_md` injection
pattern; `knowledge/registry.py` (extensible vocabulary); the existing `KnowledgeGap` model + gap loop +
`GET /research/{id}/gaps` + `KnowledgeGapOut`. The `Solution` comparison matrix and inline
`Method`/`Dataset` limitation note-lists are retained (not migrated/removed).

## Comparison / Limitation / KnowledgeGap Implementation
- **`Comparison`** (`models/analysis.py`) — title/description, `subject_a` (required), `subject_b?`,
  `criterion`, `value` (string keeps units/ranges), `unit?`, `conditions`, `grounded` (computed by the
  API from source/experiment/result links), links `source_ids`/`experiment_ids`/`result_ids`,
  `confidence?`, `origin`. Numeric values are recorded, never inferred from prose.
- **`Limitation`** (`models/analysis.py`) — `ltype` (source|dataset|method|experiment|technology|
  research|statistical|environmental), title/description, `severity` (high|medium|low),
  `affected_kind`+`affected_id` (validated to the project for concrete kinds via `_validate_affected`;
  abstract kinds carry no id), impact/mitigation, `status` (open|mitigated|accepted|resolved), evidence
  links `source_ids`/`claim_ids`, `confidence?`, `origin`.
- **`KnowledgeGap` EXTENDED** (`_ADDED_COLUMNS`, additive nullable) — importance/impact/
  potential_investigation/status/confidence/origin + link lists (question/hypothesis/experiment/claim/
  conclusion/source). Auto-generated gaps keep working (defaults); write API added; a gap is an open
  question — `status` never auto-advances; agent gaps keep `origin="agent"`.

## Database Changes
New tables `comparisons`, `limitations` (via `create_all`). Additive nullable columns on
`knowledge_gaps` (`_ADDED_COLUMNS`). No existing table dropped; idempotent; Phase A–D data + existing
recommendations + existing/auto-generated gaps preserved (tested).

## API Changes
`api/rnd.py`: CRUD for `.../comparisons` and `.../limitations`; write endpoints for `.../gaps`
(`POST/PATCH/DELETE`) beside the existing read `GET /research/{id}/gaps` (which now returns the extended
fields). Ownership via `_get_project`; relationship ids validated to the project (`_LIST_REF_MODELS`
gained `hypothesis_ids`; `_validate_affected` for the limitation's affected object) → cross-project 422,
cross-user 404. No `/v1`/MCP additions (deferred, per audit).

## Frontend Changes
`components/SynthesisPanel.tsx` + a **Comparisons, Limitations & Gaps** tab: Comparisons (grounded/
ungrounded badge), Limitations (type+severity badges, status change, mitigation), Knowledge Gaps
(editable status, importance, **"Open question"** label — never shown as a verified fact).
`api/client.ts` + `types.ts` extended. Tests: `SynthesisPanel.test.tsx`.

## Knowledge Graph Changes
`knowledge/registry.py`: added `comparison`/`limitation`/`research_gap` entity types + `compares`/
`limits`/`affects`/`motivates` predicates (migration-free vocabulary). **Node emission deferred to
Phase G** — no existing graph behavior changed.

## Report / Truthfulness
`report._phase_e_md` injects `## Comparisons`, `## Limitations`, `## Research Gaps` **from rows** (only
when rows exist). Research Gaps are prefaced "open questions / missing knowledge, not verified findings"
and each gap is listed as a question; an **ungrounded** comparison value is explicitly flagged. Gaps
are auto-generated during runs, so a normal completed run now shows a structured `## Research Gaps`
section (additive, truthful). Zero-evidence + Phase D `conclusions_unsupported` gates unchanged.

## Provenance / Confidence
`origin` (user/agent/derived) on all three; confidence reuses the nullable 0–100 float (never
fabricated). Comparison `grounded` is derived from real links, not asserted.

## Offline Behavior
All CRUD deterministic + network-free. `test_phase_e_crud_makes_no_llm_call` monkeypatches
`get_provider` to raise and confirms comparison/limitation/gap CRUD constructs no provider.

## Security
Cross-user → 404 (`test_cross_user_phase_e_is_404`); cross-project refs → 422
(`test_comparison_crud_and_cross_project`, `test_limitation_affected_object_validated`,
`test_gap_links_and_cross_project`); auth required (`test_phase_e_requires_auth`); invalid
type/severity/status → 422.

## Tests
- Backend `test_rnd_phase_e.py`: **17** (comparison grounded/ungrounded + cross-project; limitation all
  8 types + severities/statuses + affected-object validation + evidence links; gap write API + defaults
  + links + cross-project + auto-generated-gap preservation; cross-user 404 + auth; no-LLM; report
  sections from rows + ungrounded flag + absent-without-rows; migration idempotency A–E).
- Frontend `SynthesisPanel.test.tsx`: **4** (render + ungrounded + gap-as-open-question; grounded flag;
  create limitation; change gap status).

## Regression Results
- Backend: **442 passed** (425 → +17) · Frontend: **77 passed** (73 → +4)
- Typecheck **PASS** · Build **PASS** · #9 **30/30 (no failures)** · #10 **1.0 / 0.677** · #11 offline in-suite
- No existing test weakened; no threshold changed.

## Known Limitations / Deferred
- KG builder does not emit comparison/limitation/gap **nodes** (vocabulary only) — Phase G.
- Comparison/Limitation/Gap **diff / memory / monitoring** inclusion — deferred (existing rec/claim
  diff + significance already carry the update flow; documented, not built).
- Reproducibility verdict + universal versioning — **Phase F**.
- Timeline / Research Log / lifecycle / stage-recovery — the plan's separate "Phase E" work, **future**.
- No `/v1` + MCP exposure of Phase E objects — deferred per the audit.

## Master Specification Completeness
- Before Phase E: Comparisons PARTIAL, Limitations PARTIAL, Research Gaps PARTIAL.
- After Phase E: Comparisons = **COMPLETE**, Limitations = **COMPLETE**, Research Gaps = **COMPLETE**.
- Overall R&D master-spec completeness: **≈72% → ≈80%** (all core research objects and the full
  evidence→claim→analysis→conclusion→recommendation chain + comparisons/limitations/gaps are now
  first-class & traceable; timeline/log, reproducibility-verdict, KG node emission, full versioning,
  and diff/memory/monitoring inclusion remain).

## Confirmation
No Phase F+ work implemented. No reproducibility-verdict / universal versioning / KG node emission /
comparison-limitation-gap diff engine / gap monitoring or memory integration / `/v1`+MCP additions /
advanced statistics / autonomous planning / scheduling / decision intelligence / autopilot / agent
swarm. No unrelated refactoring. Phase A/B/C/D commits untouched.

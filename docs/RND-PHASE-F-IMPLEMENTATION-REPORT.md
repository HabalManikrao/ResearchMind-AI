# R&D Laboratory Layer — Phase F Implementation Report (Reproducibility, Versioning & History)

**Baseline:** `5a70ed1` (Phase E). **Scope:** the audited Phase F core — first-class
ReproducibilityRecord + explicit verdict + safe auto-capture; versioning/history reuse existing
lineage. **Not committed** at time of writing.

## Executive Summary
Added a first-class **`ReproducibilityRecord`** (one per project/run, get-or-create) that aggregates a
**safe, non-secret** reproducibility snapshot plus an **explicit `verdict`** (default
**`not_assessed`**, never auto-computed to a positive value). Safe metadata is auto-captured at run
completion (best-effort, no new provider/network calls, no secrets); a positive verdict requires an
explicit human/agent assessment. Versioning and history **reuse** the existing run lineage (#4) and
Dataset versioning (Phase C) — no universal version table, no new diff/log engine. Fully additive; no
second evidence/claim/confidence/provenance/lineage/diff system.

## Audit Findings
Reproducibility record = MISSING; verdict = MISSING; metadata = PARTIAL (Experiment fields, manual);
Dataset & run versioning = COMPLETE; Research Log/Timeline = MISSING (separate lifecycle milestone).
No blockers. Full detail: `RND-PHASE-F-AUDIT.md`.

## Existing Infrastructure Reused
`_get_project` + `_validate_object_links` (ownership + per-project ref validation); run lineage +
`research_diff` (versioning/history/change-tracking); `config` (model/embedding/search identifiers);
`report._rd_md`/injection pattern; `provenance`/`origin` conventions; nullable 0–100 confidence. No KG
change (reproducibility is metadata). The Solution matrix, inline limitation lists, and Dataset
versioning are untouched.

## ReproducibilityRecord + Verdict
`models/reproducibility.py` — identifiers only: `model_name/version/provider`, `embedding_model(+ver)`,
`search_provider`, `provider_config_id` (never a key), `dataset_id`+`dataset_version`,
`software`/`software_versions`/`hardware`/`os`/`environment`/`configuration`/`seed`,
`git_commit`/`git_branch`/`git_dirty`, `raw/processed_data_reference`, `as_of`; plus `verdict`
(default `not_assessed`), `rationale`, `assessed_by`, `assessed_at`, `origin`, `notes`. 1:1 per project
(unique `project_id`), get-or-create. **Verdict is never auto-computed to a positive value; unavailable
values stay NULL (never fabricated).**

## Safe Auto-Capture
`orchestrator._capture_reproducibility(project_id, as_of)` runs just before report generation:
best-effort, reuses `config` (ollama_model, embedding_model, search_provider) + a git snapshot
(`_safe_git`, subprocess with 3s timeout, `None` on any failure — git is not a runtime dependency and
a commit is never fabricated), sets `provider_config_id` to a safe id (never a key), `verdict`
stays `not_assessed`, `origin="agent"`. It respects a pre-existing (manual) record and never overwrites
it; a failure never breaks the completed run.

## Database Changes
One new table `reproducibility_records` (via `create_all`). **No** columns added to existing tables (no
`_ADDED_COLUMNS` change). `project_id` FK CASCADE (+ nullable `experiment_id`/`dataset_id`). Idempotent
on fresh/existing/twice-run DBs; Phase A–E data preserved (tested).

## API Changes
`api/rnd.py`: `GET /research/{id}/reproducibility` (get-or-create) + `PUT` (manual record/verdict).
Ownership via `_get_project`; experiment/dataset refs validated to the project; **`_strip_secrets`**
removes credential-looking keys from `configuration` before persistence. No `/v1`/MCP (deferred).

## Frontend Changes
`components/ReproducibilityPanel.tsx` + a **Reproducibility** tab: an Assessment card (verdict select +
rationale + save; a "Not assessed" honesty note stating captured metadata ≠ reproduced) kept **visually
separate** from a Captured-Metadata card (safe identifiers; unavailable → "—"). `api/client.ts` +
`types.ts` extended. Tests: `ReproducibilityPanel.test.tsx`.

## Report / Truthfulness
`report._reproducibility_md` projects a `## Reproducibility` section from the record (only when a record
exists) — the verdict is the recorded one (never a positive verdict from prose or "complete metadata"),
NULL metadata is omitted (not fabricated), and `not_assessed` shows the explicit "does not imply the
research was reproduced" note. Zero-evidence + Phase D `conclusions_unsupported` gates unchanged.

## Versioning / History
**Reused, not rebuilt:** run/object versioning = run lineage (#4, immutable completed runs) + Dataset
versioning (C, new-row + supersedes_id). Change tracking = `research_diff`. No universal version table,
no immutable-snapshot engine, no research-event log. Research Log/Timeline + universal per-object
versioning are **DEFERRED** (the separate lifecycle milestone). `AuditLog` untouched.

## Provenance / Confidence
`origin` (user/agent/derived) on the record identifies manual vs auto-captured; unavailable field =
NULL = "unavailable". Reuses existing provenance/confidence conventions; no new framework.

## Secret Safety (hard rule)
The record schema exposes only identifiers; `_strip_secrets` drops any `configuration` key matching
key/token/secret/password/cookie/authorization/credential/bearer/access markers; auto-capture uses a
provider **config id**, never a key/url-with-secret. Tested (`test_secrets_are_never_persisted`).

## Offline Behavior
All CRUD deterministic + network-free (`test_reproducibility_crud_makes_no_llm_call`). Auto-capture uses
local config + optional git only; the offline pipeline still completes and captures a
`not_assessed` record (`test_completed_run_autocaptures_not_assessed`).

## Security
Cross-user → 404 (`test_cross_user_reproducibility_is_404`); cross-project experiment ref → 422;
auth required (`test_reproducibility_requires_auth`).

## Tests
- Backend `test_rnd_phase_f.py`: **17** (default not_assessed; complete-metadata≠reproducible; manual
  verdict keeps rationale/origin; invalid verdict 422; missing metadata NULL; secrets never persisted;
  dataset version exact; cross-project 422; cross-user 404 + auth; no-LLM; completed-run auto-capture
  not_assessed; git never fabricated; report honest/absent/no-invented-verdict; migration idempotency A–F).
- Frontend `ReproducibilityPanel.test.tsx`: **3** (not-assessed honesty + metadata/verdict separation;
  record explicit verdict; no positive verdict shown when not_assessed).

## Regression Results
- Backend: **459 passed** (442 → +17) · Frontend: **80 passed** (77 → +3)
- Typecheck **PASS** · Build **PASS** · #9 **30/30 (no failures)** · #10 **1.0 / 0.677** · #11 offline in-suite
- Research Again / Diff / Memory / Monitoring / KG / Evidence / Claims / Verification / Analysis /
  Conclusions / Recommendations / Comparisons / Limitations / Gaps all remain green (full suite). No
  existing test weakened; no threshold changed.

## Known Limitations / Deferred
- **Universal per-object versioning** — deferred (run lineage + Dataset versioning are the mechanism;
  the audit rejected a generic version table as over-engineering).
- **Research Log / Timeline / lifecycle / stage-recovery** — the separate future milestone; `AuditLog`
  is only an action trail.
- **Prompt/template versioning** — deferred (prompts live in code; not captured/versioned).
- Comparison/Limitation/Gap/Analysis/Conclusion **diff/memory/monitoring** inclusion — deferred.
- **KG node emission** — Phase G. **`/v1`+MCP** exposure — deferred.

## Master Specification Completeness
- Before Phase F: reproducibility record/verdict MISSING; per-object versioning PARTIAL.
- After Phase F: Reproducibility record + explicit verdict = **COMPLETE**; versioning = **COMPLETE via
  lineage/dataset** (universal per-object history explicitly deferred).
- Overall R&D master-spec completeness: **≈80% → ≈87%** (remaining: Research Log/Timeline + lifecycle
  stage-recovery, KG node emission (G), B–E object diff/memory/monitoring inclusion, prompt versioning,
  `/v1`+MCP exposure).

## Confirmation
No Phase G+ work implemented. No universal object versioning / generic version table / immutable
snapshot engine / research event log / lifecycle timeline / reproducibility automation / autonomous
execution / scheduling / decision intelligence / agent swarm / KG node emission / `/v1`+MCP additions /
unrelated refactoring. Phase A/B/C/D/E commits untouched.

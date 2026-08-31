# Research Memory + Research Again + Research Diff (#4) — Completion Report

_Completed: 2026-08-31. Versioned research runs, continue-with-prior-context, and a deterministic
"what changed" diff, built on the P0 evidence + Document RAG substrate. Plan:
`docs/RESEARCH-MEMORY-IMPLEMENTATION-PLAN.md`._

---

## Final Validation Report

```
Research Memory:       READY
Research Runs:         READY
Research Again:        READY
Research Lineage:      READY
Research Diff:         READY
Claim Diff:            READY
Evidence Diff:         READY
Confidence Diff:       READY
Document Diff:         READY
Security:              READY
Performance:           READY
Migration:             READY
```

- **Backend tests:** 175 passed, 0 failed (`pytest`, all offline) — was 152; **+23**
  (12 diff, 11 research-again/lineage/memory/immutability/security/carry-forward, 1 migration).
- **Frontend tests:** 20 passed, 0 failed (`vitest`) — was 13; **+7** (RunDiff ×3, History ×2, LineageBar ×2).
- **Build:** `npm run build` OK (`tsc --noEmit` clean + vite build).
- **Migration:** additive, idempotent, non-destructive — new nullable columns on `research_projects`
  via `_ensure_columns`, plus an idempotent `root_id` backfill; verified by
  `tests/test_migration_lineage.py` (old-shape DB → migrate twice → columns present, data intact).

---

## The one architectural decision

**A Research Run is a `ResearchProject`.** No parallel run table was introduced. The audit showed a
project already carries everything a run needs (query/mode/sources/constraints, its own sources/
findings/claims/evidence/conflicts/solutions/recommendation, the snapshotted report, timestamps,
status), and completed projects are already immutable in practice (nothing rewrites a `COMPLETED`
project; `/start` refuses to re-run one). We added a **lineage self-reference** and made "Research
Again" **fork a new project** — additive, idempotent, reusing 100% of the evidence substrate, with
historical truth immutable by construction. This directly follows the milestone's "do not duplicate
concepts an existing model represents" and "create a new run state; do not overwrite historical truth".

## What was implemented

- **Lineage columns** on `research_projects`: `parent_id`, `root_id`, `run_number`, `run_intent`,
  `completed_at`, `memory_summary` (all nullable/defaulted). Originals set `root_id = self.id`,
  `run_number = 1`, `run_intent = "original"`. A whole lineage is one indexed query on `root_id`.
- **Research Memory** (`memory_summary`): a compact structured record built once at completion from
  the finalized rows (question, key findings, high-confidence + weak claims, contradictions, open
  questions, important sources, recommendation, counts, confidence distribution, `as_of`).
  Retrieval-optimized, not prose. Exposed at `GET /research/{id}/memory`.
- **Research Again** (`POST /research/{id}/research-again`, intents `refresh`/`deepen`/`verify`/
  `full`): forks a linked run, records audit `research.again`, and starts it. The parent is read-only.
  The orchestrator builds the parent's **selective prior context** (top high-confidence claims, open
  questions, known contradictions, prior recommendation, previous date) and threads it into the
  planner with an intent-specific system addendum — **zero extra LLM calls** (injected into the
  existing `make_plan`).
- **Document carry-forward**: a re-run copies the parent's READY documents — copying each **physical
  file** (so neither run's delete orphans the other) and **copying chunk vectors without re-embedding**
  (`vector_store.copy_document_vectors` retrieves + re-upserts under the new project_id → CPU-free,
  isolation preserved). Best-effort and non-fatal.
- **Research Diff** (`GET /research/{id}/diff/{other_id}`, `services/research_diff.py`):
  deterministic, **no LLM in the default path**. Sources matched by normalized URL; claims matched
  normalized-text → token-set (Jaccard) → optional embedding cosine on the remainder (offline-safe
  degradation). Evidence-aware classification (NEW/REMOVED/UNCHANGED/STRENGTHENED/WEAKENED/
  CONTRADICTED) with **reasons built from `confidence_meta`** (never invented). Confidence deltas,
  recommendation diff (unchanged/modified/reversed/new/removed), and document-evidence diff by
  identity + checksum.
- **Lineage API**: `GET /research/{id}/runs` returns all runs sharing the root with per-run counts
  (sources/claims/evidence) and average confidence.
- **Frontend**: a **lineage bar** in the live view (run position, "Compare with Run #k", and a
  Research Again intent picker on completed runs); a dedicated **RunDiff page**
  (`research/:id/diff/:otherId`) with summary deltas and per-claim *previous → current* evidence
  drill-down; **lineage-grouped History**.

## Files

**New (backend):** `app/services/research_diff.py`; tests `test_research_diff.py`,
`test_research_again.py`, `test_migration_lineage.py`.
**New (frontend):** `src/pages/RunDiff.tsx`; tests `RunDiff.test.tsx`, `History.test.tsx`,
`LineageBar.test.tsx`.
**New (docs):** this file + `RESEARCH-MEMORY-IMPLEMENTATION-PLAN.md`.
**Modified (backend):** `models/research.py` (lineage columns), `database.py` (`_ADDED_COLUMNS` +
`_backfill_lineage`), `config.py` (`research_again_*` / `research_diff_*`), `agents/planner.py`
(`PriorContext` + `intent`), `orchestration/orchestrator.py` (prior-context build, memory summary,
`completed_at`), `documents/service.py` (`carry_forward_documents`), `knowledge/vector_store.py`
(`copy_document_vectors`), `api/research.py` (research-again / runs / memory / diff endpoints +
create lineage), `schemas/research.py` (lineage fields, `RunSummary`, `MemoryOut`,
`ResearchAgainRequest`, diff schemas).
**Modified (frontend):** `api/types.ts`, `api/client.ts`, `pages/LiveResearch.tsx`,
`pages/History.tsx`, `App.tsx`.
**Modified (docs):** `GAP-ANALYSIS.md` (milestone banner).

## Database changes

Six **nullable/defaulted** columns added to `research_projects` (no new tables, no row rewrites):
`parent_id`, `root_id`, `run_number` (DEFAULT 1), `run_intent`, `completed_at`, `memory_summary`.
Applied on fresh DBs by `create_all` and on existing DBs by `_ensure_columns` (idempotent
`ALTER TABLE ADD COLUMN`), followed by an idempotent `UPDATE ... SET root_id = id WHERE root_id IS
NULL` backfill. Existing projects/claims/sources/documents are untouched.

## Performance / cost (CPU Ollama)

- **Diff** makes **zero LLM calls** by default (identifier/normalized-text/token matching). Embedding
  claim-matching runs **only** on the still-ambiguous remainder, in one batched call, and degrades to
  the deterministic path when embeddings are unavailable.
- **Research Again** adds **no** LLM calls beyond a normal run — prior context is injected into the
  single existing planner call. Document carry-forward copies vectors via retrieve+re-upsert (no
  re-embedding).

## Security / isolation (§27)

Every endpoint routes through `_get_project` (own or legacy/unowned only → 404 otherwise). Diff
fetches **both** ids through ownership and additionally requires a shared `root_id` (else 404).
Carried document vectors are filtered by the new project_id (hard isolation preserved). Covered by
`test_cross_user_cannot_access_lineage_or_fork` and `test_diff_requires_same_lineage`.

## Reliability / immutability (§14, §15, §26)

Completed runs are immutable snapshots — Research Again only reads the parent and inserts a new
project; a failed re-run leaves the parent's claims and report byte-for-byte unchanged
(`test_research_again_failure_leaves_parent_intact`, `test_research_again_creates_linked_run_and_
preserves_parent`). Carried documents own their own physical files, so deleting one run's document
cannot orphan another's.

## Known limitations (intentional; future work)

1. **No live LLM claim-adjudication** — matching is deterministic + optional embeddings. The matcher
   is a pluggable seam; LLM tie-breaking for ambiguous pairs can be added later without touching the
   default (CPU-free) path.
2. **Document diff is identity/checksum-level**, not chunk-level semantic diff (explicitly out of
   scope, §30).
3. **Research Again continues a `COMPLETED` parent only** (a clean snapshot baseline) — continuing a
   FAILED run is not offered.
4. Out of scope per the brief: OCR, autonomous alerts/monitoring, MCP, collaboration, knowledge-graph
   redesign, live-vs-cached classification.

## Definition of Done — checklist

| Criterion | Status |
|---|---|
| Structured research memory retained per completed run | ✅ (`memory_summary` + `GET /memory`) |
| Each execution identified & linked (runs, lineage) | ✅ (`parent_id`/`root_id`/`run_number`) |
| Research Again continues/refreshes a prior run | ✅ (4 intents, prior context) |
| Research lineage visible/navigable | ✅ (`GET /runs`, History grouping, lineage bar) |
| Two runs comparable | ✅ (`GET /diff/{other_id}`, RunDiff page) |
| Claim / evidence / confidence / source / document diff | ✅ (evidence-aware, `confidence_meta` reasons) |
| Document evidence participates in the diff | ✅ (carry-forward + identity/checksum diff) |
| Memory project/user isolated | ✅ (ownership 404 + shared-root guard) |
| Diff avoids unnecessary LLM calls | ✅ (deterministic default; optional embeddings) |
| Historical completed runs immutable | ✅ (fork-not-mutate; failure isolation tested) |
| Existing + new tests pass | ✅ (175 backend + 20 frontend) |
| Documentation updated | ✅ (plan + this report + GAP-ANALYSIS banner) |
```

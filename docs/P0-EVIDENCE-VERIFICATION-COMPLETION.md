# P0 — Evidence & Verification: Completion Report

_Milestone: top-5 items **#1 Evidence drill-down** + **#2 Recency-aware confidence & active
contradiction search**. Audit date: 2026-08-28. This report is the readiness gate before Document
RAG (#3). It records an independent re-inspection of the delivered code, exact test results, known
limitations, and a per-area production-readiness rating._

---

## Executive Summary

ResearchMind's evidence layer moved from *computed-but-invisible* to *traceable, inspectable, and
recency/contradiction-aware*. Claims are now linked to their sources through a first-class join table
carrying the **quoted passage** and a **stance** (supports/contradicts). Confidence is computed from
source count, reliability, **recency**, and **contradiction count**, with a transparent breakdown
that explains the score. An **active contradiction search** looks for disconfirming evidence on the
most important claims and re-scores them. The UI exposes all of this as an expandable claims view.

All work is scoped strictly to #1 + #2. No Document RAG. No unrelated refactoring. The one code
change made *during this audit* was a defensive hardening surfaced by the audit itself (see
Verification §4).

**Bottom line: READY FOR DOCUMENT RAG** (details in the final gate).

---

## Architecture — how evidence & verification now work

```
collection ─▶ verify (cluster findings → claims)
                 │  builds ClaimSource(SUPPORTS, passage) links
                 │  score_claim(): count + reliability + recency  ─▶ confidence + confidence_meta
                 ▼
             dedupe ─▶ re-verify (86%)
                 ▼
   active contradiction search (87%)  ── bounded to top-N important claims
                 │  web search for disconfirming evidence → ClaimSource(CONTRADICTS, passage)
                 │  re-score affected claims  ─▶ status=CONFLICTED, lower confidence
                 ▼
   conflict detection (88%) ─▶ R&D (92%) ─▶ report (95→100%)
```

- **Evidence graph edge** = `ClaimSource` (`claim_id`, `source_id`, `stance`, `passage`). Authoritative,
  FK-backed. `claims.supporting_source_ids` (JSON) is retained **only** as a denormalised mirror for
  the knowledge-graph builder and older readers.
- **Confidence** is deterministic and computed in `agents/verification.score_claim` — never an LLM
  label. It emits a `confidence_meta` breakdown consumed by the API and UI.
- **Freshness** is a pure function of publish date + source type (`services/freshness.py`), used both
  in scoring and as UI badges. Reports are always generated *after* the contradiction re-score, so a
  report can never carry stale (pre-contradiction) confidence.

---

## Database — schema changes

New table **`claim_sources`** (`app/models/research.py::ClaimSource`):

| column | type | notes |
|---|---|---|
| id | String(36) PK | uuid |
| claim_id | FK → claims.id | `ondelete=CASCADE`, indexed |
| source_id | FK → sources.id | `ondelete=CASCADE`, indexed |
| stance | Enum(EvidenceStance) | supports / contradicts / neutral |
| passage | Text (nullable) | the quoted evidence |
| created_at / updated_at | DateTime | TimestampMixin |

New column **`claims.confidence_meta`** (JSON, nullable) — the confidence breakdown
(`support_count`, `contradiction_count`, `avg_reliability`, `freshness`, `outdated`, `reasons`).

New enum **`EvidenceStance`** (`supports`/`contradicts`/`neutral`).

Computed (not stored): `Source.freshness` property; `Claim.evidence_state` property
(supported/weak/conflicting/outdated/unverified, derived from status + confidence_meta).

**Migration mechanism.** There is still no Alembic. `database.init_db()` runs `create_all`
(idempotent, `checkfirst`) which creates `claim_sources`, then `database._ensure_columns()` — an
idempotent SQLite `ALTER TABLE ADD COLUMN` driven by the `_ADDED_COLUMNS` map — adds
`claims.confidence_meta` to pre-existing DBs. **Verified idempotent and non-destructive on a copy of
the live DB:** two consecutive startups leave exactly one `confidence_meta` column, correct FKs, and
**25 existing claims + 9 projects intact**.

---

## APIs — new / modified

- **NEW** `GET /research/{project_id}/claims/{claim_id}/evidence` → `ClaimEvidenceOut`
  (`{ claim, evidence[] }`). Each evidence item: `source_id, title, url, source_type, publisher,
  published_date, reliability_score, freshness, stance, passage`. Supporting evidence first, then
  contradicting; most-reliable first within each. Auth: `get_current_user` + `_get_project` ownership
  (404 for non-owner or foreign-project claim), and `claim.project_id == project_id` guard.
- **MODIFIED** `ClaimOut` now includes `confidence_meta` and `evidence_state`.
- **MODIFIED** `SourceOut` now includes `freshness`.
- Pipeline emits new events: `stage "Searching for contradicting evidence"` and a `contradiction`
  activity line.

---

## Verification — confidence & contradiction methodology

### Confidence (`score_claim`)
Inputs actually used: **distinct supporting-source count**, **mean supporting reliability**,
**recency** (mean freshness weight of supporting sources), **contradiction count**.

- Status: `INSUFFICIENT_EVIDENCE` (0 sources) → `CONFLICTED` (any contradiction or LLM conflict flag)
  → `VERIFIED` (≥2 sources, avg reliability ≥ 80) → `PARTIALLY_VERIFIED` (≥2, or a single very strong
  source) → `UNVERIFIED`.
- Confidence = `base(status) × recency_factor × contradiction_factor`, clamped to 0–99.
  `recency_factor = 0.7 + 0.3·mean_freshness_weight` (∈ [0.76 all-stale … 1.0 all-fresh]; unknown
  dates ≈ 0.955, near-neutral). `contradiction_factor = max(0.4, 1 − 0.25·n_contra)`.
- `confidence_meta.reasons` gives a plain-language "why" (source count, avg reliability, recency
  state, contradiction count).

**Edge cases audited (all handled):** empty sources → early return, no divide-by-zero; `n ≥ 1`
guaranteed before any division; reliability always present (float column, defaults 50); unknown
freshness → weight 0.85, aggregate label `unknown` (never "fresh"); all-stale → `outdated=true`;
contradictions → `CONFLICTED` + reduced confidence; duplicate sources → de-duplicated by `source_id`
in `verify()` and via distinct `ClaimSource` rows in the re-score path; extreme counts → all factors
bounded, confidence clamped. **Deterministic** for the same inputs + `as_of`.

### Active contradiction search (`agents/contradiction.py`)
- **Bounded**: only claims with status `VERIFIED`/`PARTIALLY_VERIFIED` **and** confidence ≥
  `contradiction_min_confidence` (55), then the **top `max_contradiction_checks` (3)** by confidence.
- **Cost per checked claim**: exactly **1 search + 1 LLM extraction call**. Results de-duplicated by
  URL within a claim.
- **Fail-safe at every level**: `_seek_one` swallows `SearchError` and LLM errors → `[]`; `seek`
  wraps each claim in try/except; and the orchestrator call site is wrapped so a failure in the whole
  stage is logged and skipped (cancellation still propagates) — the run still completes. Covered by
  `test_run_survives_contradiction_stage_failure`.
- Contradicting evidence is persisted as new `Source` rows (`meta.contradiction = true`) +
  `ClaimSource(CONTRADICTS)` links, and the affected claim is re-scored in place.

---

## UI — evidence drill-down behavior

- **Claims tab** rows are expandable (chevron). Collapsed: text, `EvidenceStateBadge`
  (Supported/Weak/Conflicting/Outdated/Unverified), confidence %, and support/contradiction counts.
- **Expanded**: a "Why this confidence" list (from `confidence_meta.reasons`), then evidence grouped
  into **Supporting** (neutral border) and **Contradicting** (orange border) sections. Each item shows
  the **quoted passage**, source link, `SourceTypeBadge`, `ReliabilityPill`, and `FreshnessPill`
  (🟢/🟡/🔴/⚪) + date.
- **States**: loading ("Loading evidence…"), empty ("No source-level evidence recorded." — e.g.
  pre-migration claims), and API-error (caught → empty list) are all handled. Evidence is fetched
  lazily on first expand and cached per claim.
- **Sources tab** also shows a `FreshnessPill` per source.
- Long passages wrap inside a bordered/italic block; the comparison table remains horizontally
  scrollable. No redesign was performed.

---

## Testing — exact results

```
Backend:  127 passed, 0 failed, 0 warnings   (pytest, ~105s, all offline)
Frontend:   9 passed, 0 failed               (vitest: 6 pure + 3 ClaimsTab DOM)
Build:    frontend `npm run build` OK (tsc --noEmit clean + vite build)
Migration: idempotent + non-destructive (verified on a copy of the live DB)
Total:    136 automated checks green
Failures:  0
Warnings:  none surfaced by pytest or the build
```

**Coverage added this milestone**
- `test_freshness.py` — domain thresholds (news/papers/web), unknown/missing/garbage dates, future
  dates, domain-dependent classification.
- `test_verification.py` (extended) — recency boosts confidence; contradiction flips to CONFLICTED
  and lowers confidence; outdated flag; `confidence_meta` inputs; evidence passages attached.
- `test_contradiction.py` — contradiction found / none / search failure / out-of-range index.
- `test_orchestrator_contradiction.py` — persists CONTRADICTS links + re-scores; no-op when disabled.
- `test_api_evidence.py` — endpoint shape, passages, freshness, unknown-claim 404, cross-user 404,
  source freshness field.
- `test_pipeline.py` (extended) — run survives a contradiction-stage failure (result preserved).
- Frontend `evidence.test.ts` + `ClaimsTab.test.tsx` — mapping logic + expand/fetch/render behavior.

**False-positive guard.** Tests assert negative paths (404s, empty evidence, search/LLM failure,
disabled flag) and ownership isolation, not just happy paths. The evidence-endpoint tests assert the
*shape and content* of passages/freshness/stance, not merely a 200.

**`.env` leakage fix (intentional, not masking a real problem).** The dev `backend/.env` sets
`MAX_RESEARCH_TASKS=3` etc. for CPU-only speed; that had been leaking into the suite and starving a
multi-source test. `conftest.py` now pins `MAX_RESEARCH_TASKS/MAX_FOLLOWUP_ROUNDS/MAX_SOURCES_PER_TASK`
to the code defaults the tests target. This makes tests **hermetic** (independent of a developer's
local tuning); it does not hide a production misconfiguration — production reads its own `.env`, and
these are performance knobs, not correctness settings.

---

## Performance — LLM / search cost

- **Added worst-case cost per run**: `max_contradiction_checks` (3) × (1 search + 1 LLM extraction)
  = **3 searches + 3 LLM calls**, and only for claims already above the confidence floor. On the
  CPU-Ollama box (~2.5 tok/s) that is a few minutes on top of the existing ~40-min run — bounded and
  predictable.
- **Cannot multiply uncontrollably**: the top-N cap and the confidence floor are hard limits; there
  is no loop or fan-out over sources. Search enrichment reuses existing SSRF-safe fetch and the
  provider's retry/timeout logic. Contradiction searches are not cached (a known limitation), but the
  fixed cap makes caching a nicety, not a safety requirement.
- Verification/scoring/freshness are pure CPU-cheap functions (no extra LLM calls beyond the existing
  clustering call).

---

## Known Limitations (explicit)

1. **Freshness thresholds are centralized but not env-configurable.** They live in one place
   (`freshness._THRESHOLDS` / `FRESHNESS_WEIGHT`) — not scattered — but changing them needs a code
   edit, not a setting. Fine for now; promote to settings if per-deployment tuning is wanted.
2. **`score_claim` assumes distinct sources.** It does not itself de-duplicate; callers do
   (`verify()` and the re-score path both pass distinct `source_id`s). Documented contract.
3. **SQLite does not enforce FKs by default** (`PRAGMA foreign_keys` is off). Integrity is maintained
   by ORM cascades + the explicit `claim_sources` delete in `_verify`. The FK/`ondelete=CASCADE`
   declarations become actively enforced once the planned Postgres swap lands.
4. **Pre-migration claims have no evidence links.** The 25 existing claims show the new badges (from
   status) but an empty evidence list until re-run; new/re-run research populates passages, freshness,
   and contradictions. This is expected backward-compatible behavior, not a defect.
5. **Contradiction query is templated, not LLM-crafted** (to save a per-claim LLM call). Good enough;
   an LLM-generated refutation query would find subtler counter-evidence at extra cost.
6. **Contradiction search is not cached** — safe because of the hard top-N cap.
7. **Conflict detection (claim-vs-claim) is still LLM-judgment only** — unchanged this milestone; it
   is a separate P1 item from source-level contradiction search.

---

## Migration Safety — how existing data is preserved

- `create_all` only creates missing tables (`checkfirst`); `_ensure_columns` only adds a column when
  `PRAGMA table_info` shows it absent. Both are safe to run on every startup.
- **No destructive operation** anywhere in startup: no `DROP`, no `DELETE`, no data rewrite. `ALTER
  TABLE ADD COLUMN` on SQLite is non-locking metadata-only and preserves rows.
- **Verified empirically** on a *copy* of the live DB: two startups → one `confidence_meta` column,
  correct FKs, 25 claims + 9 projects preserved. The live DB was never modified during this audit.
- Backward compatibility: `supporting_source_ids` is still written, so the knowledge-graph builder and
  the report's confidence aggregates keep working unchanged.

---

## Production Readiness — per area

| Area | Rating | Rationale |
|---|---|---|
| Evidence | **READY** | FK-backed join, quoted passages, ownership-scoped retrieval, tested. |
| Verification | **READY** | Deterministic computed confidence; all listed edge cases handled + tested. |
| Security | **READY** | Endpoint requires auth + project ownership; foreign-claim → 404; no bypass found. |
| Database | **READY WITH LIMITATIONS** | Idempotent non-destructive migration verified; but no Alembic and SQLite FKs not enforced (managed by ORM). Fine for single-user; formalize at Postgres. |
| API | **READY** | New endpoint + extended schemas, typed, tested (happy + negative + isolation). |
| UI | **READY** | Expand/loading/empty/error states; supporting vs contradicting distinct; freshness legible. |
| Performance | **READY** | Added cost hard-capped (3 searches + 3 LLM calls/run); cannot fan out. |
| Testing | **READY** | 127 backend + 9 frontend, negative/security/failure paths covered; hermetic. |
| Documentation | **READY** | CLAUDE.md (Evidence engine section), GAP-ANALYSIS.md (status), this report; frontend test deps documented. |

No area is **NOT READY**.

---

## Final Gate

### P0 Status: **READY FOR DOCUMENT RAG**

Recommended next milestone:

> **Document RAG (#3): PDF/DOCX ingestion → chunking → embeddings → Qdrant → retrieval → document
> evidence/citations → offline research.**

The evidence engine built here is the correct substrate for it: document chunks become `Source`s,
retrieved passages become `ClaimSource` evidence with the same stance/passage/freshness model, and the
existing Qdrant index + embeddings are reused. Establish the git baseline (below) before starting.

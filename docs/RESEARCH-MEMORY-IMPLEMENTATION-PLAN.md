# Research Memory + Research Again + Research Diff (#4) — Implementation Plan

_Milestone #4. Written **before** implementation, grounded in an audit of the current code
(`models/research.py`, `orchestration/orchestrator.py`, `api/research.py`,
`services/research_service.py`, `agents/planner.py`, `knowledge/service.py`, the frontend
`History.tsx`/`LiveResearch.tsx`/`api/client.ts`). Companion to
`docs/DOCUMENT-RAG-COMPLETION.md` and `docs/GAP-ANALYSIS.md`._

---

## 0. TL;DR — the one decision everything rests on

**A Research Run *is* a `ResearchProject`.** We do **not** introduce a new run table.

The audit shows a `ResearchProject` already carries everything a run needs — `query`, `mode`,
`sources_enabled`, `constraints`, its own `Source`/`Finding`/`Claim`/`ClaimSource`/`Conflict`/
`Solution`/`Recommendation` rows, the snapshotted `report_markdown`/`report_meta`, timestamps and
status. The orchestrator only ever rebuilds rows **within an active run**; once a project reaches
`COMPLETED`, nothing rewrites it, and `POST /research/{id}/start` already refuses to re-run a
completed project (409). So **completed projects are already immutable snapshots** — exactly what
"a Research Run should preserve enough information to reconstruct what happened" (§2) requires.

We make runs *versioned* by adding a **lineage self-reference** to `research_projects`
(`parent_id`, `root_id`, `run_number`, `run_intent`, plus `completed_at` and a compact
`memory_summary`). "Research Again" **creates a new project** linked to its parent; it never touches
the parent. "Research Diff" is a **read-only deterministic comparison** of two projects in the same
lineage.

Why not a real `research_runs` table with sources/claims re-parented to `run_id`? Because that would
require a destructive, non-idempotent migration (every existing `Source`/`Claim`/… row has no
`run_id`) and rewrites of every query in the orchestrator, API, report, dedup and knowledge layers —
directly violating §14 ("do not duplicate concepts an existing model represents"), §28 (additive,
idempotent, non-destructive migration) and the "smallest useful implementation" guidance (§7). The
lineage-column approach is additive, idempotent, reuses 100% of the evidence substrate, and keeps
historical truth immutable by construction.

---

## 1. Audit summary — what exists today

| Concern | Today | Implication for #4 |
|---|---|---|
| "Run" concept | `ResearchProject` == one execution | Add lineage columns; a new run = a new project |
| Children (sources/findings/claims/evidence/conflicts/solutions/recommendation) | FK `project_id ON DELETE CASCADE` | Diff reads them per-project; no re-parenting |
| Evidence graph | `ClaimSource(claim_id, source_id, stance, passage)` | Evidence-aware claim diff reads this directly |
| Report | `report_markdown`/`report_meta` on the project | Already an immutable per-run snapshot |
| Immutability | Completed projects never rewritten; `/start` blocks re-run (409) | Research Again always forks a new project |
| Source identity | `dedup.normalize_url` collapses URL variants | Reuse for deterministic source matching |
| Document identity | `Source.meta.document_id`; `Document.checksum` (sha256) | Document diff keys on document_id + checksum |
| Confidence rationale | `Claim.confidence_meta` (support/contradiction counts, avg_reliability, freshness, reasons) | Confidence diff explains change **from stored meta** (§20 — never invent) |
| Prior-research reuse | `knowledge.search()` cross-project semantic search | Reuse for "memory search" (§21/§22) — no new vector system |
| Ownership | `_get_project(db, id, user)` → 404 for other users | Every new endpoint routes through it |
| Planner | `make_plan(provider, query, *, constraints, market, as_of)` | Add optional `prior_context` + `intent` (one extra param, **same single LLM call**) |
| Run mgmt | `manager.start(project_id)` (in-proc asyncio) | Research Again calls `manager.start(new_id)` unchanged |

---

## 2. Data model changes (additive, idempotent — §28)

All new columns are **nullable** and applied by the existing idempotent path: declared on the model
(so `create_all` builds them on fresh DBs) **and** added to `database._ADDED_COLUMNS` so
`_ensure_columns()` `ALTER TABLE ADD COLUMN`s them on existing DBs.

`research_projects` gains:

| Column | Type | Meaning |
|---|---|---|
| `parent_id` | `String(36)`, nullable, indexed | The run this one continued from. `NULL` = original run. |
| `root_id` | `String(36)`, nullable, indexed | First run in the lineage (= the *investigation* id). Set to own id for originals. |
| `run_number` | `Integer default 1` | 1 for original; `parent.run_number + 1` for continuations. Denormalized for display. |
| `run_intent` | `String(20)`, nullable | How this run was created: `original`/`refresh`/`deepen`/`verify`/`full`. |
| `completed_at` | `DateTime(tz)`, nullable | Stamped when status → COMPLETED. Immutable-snapshot marker. |
| `memory_summary` | `JSON`, nullable | Compact structured memory record (see §6), built once at completion. |

`_ADDED_COLUMNS["research_projects"] = {"parent_id":"TEXT","root_id":"TEXT","run_number":"INTEGER DEFAULT 1","run_intent":"TEXT","completed_at":"TIMESTAMP","memory_summary":"TEXT"}`
(SQLite stores JSON as TEXT and datetimes as TIMESTAMP/TEXT — consistent with existing columns.)

**Backfill (idempotent):** in `init_db`, after `_ensure_columns`, run
`UPDATE research_projects SET root_id = id WHERE root_id IS NULL`. Existing projects become
single-run lineages (`root_id = id`, `run_number = 1`, `run_intent NULL` → treated as `original`).
Re-running is a no-op.

**No new tables.** `parent_id` is declared `ForeignKey("research_projects.id", ondelete="SET NULL")`
on the model (enforced on fresh DBs); on existing DBs the ALTER adds a plain column (SQLite doesn't
enforce FKs by default anyway — same posture as the rest of the schema).

---

## 3. Research Run creation & immutability (§14, §15)

- **Original run:** `create_research` sets `root_id = self.id`, `run_number = 1`,
  `run_intent = "original"` after the insert is flushed.
- **Continuation:** `POST /research/{id}/research-again` (see §5) forks a new project with
  `parent_id = parent.id`, `root_id = parent.root_id`, `run_number = parent.run_number + 1`,
  `run_intent = <mode>`, copying `query`, `title`, `mode`, `sources_enabled`, `constraints`.
- **Immutability guarantee:** Research Again is a pure *read* of the parent (to build prior context)
  plus an *insert* of a new project. No parent row is ever updated. The orchestrator's
  delete-and-rebuild passes operate only on the **new** project's own rows. `completed_at` is set
  once; a completed run is never re-entered (guarded by `/start`'s existing 409 + Research Again only
  forking from `COMPLETED` parents).

---

## 4. Prior context for a continuation run (§5, §8, §25)

When `run_research(project_id)` loads a project with `parent_id`, it builds **selective** prior
context from the parent's immutable rows (preferring the parent's `memory_summary` if present) and
passes it to the planner. This adds **zero** extra LLM calls — the context is injected into the
existing single `make_plan` call.

Selective context (bounded, never the whole report — §8):
- Parent `objective` + `query` + `completed_at` (as "previous research date").
- **High-confidence claims** (top `research_again_max_prior_claims`, VERIFIED/PARTIALLY_VERIFIED,
  by confidence).
- **Open questions**: unanswered `ResearchQuestion`s + unresolved `KnowledgeGap`s.
- **Known contradictions**: `Conflict` statements + any claims with `evidence_state == "conflicting"`.
- **Prior recommendation** (option + one-line rationale), if any.

`planner.make_plan` gains `prior_context: PriorContext | None = None` and `intent: str = "original"`.
A per-intent system-prompt addendum steers the plan:
- `refresh` — "re-verify whether these prior findings still hold; prioritise information newer than
  <date> and any changes since then."
- `deepen` — "focus on the unresolved/open questions below; do not re-litigate settled claims."
- `verify` — "design questions that specifically re-check the important prior claims below."
- `full` — a fresh comprehensive plan, but avoid trivially repeating high-confidence settled claims.
- `original` — unchanged behavior.

The run then executes the **normal** pipeline (collect → verify → contradiction → conflict → R&D →
report). "Research Again should reuse previous evidence intelligently rather than blindly repeating
expensive searches" (§25) is honored at the **planning** layer (settled questions aren't re-asked),
not by skipping collection — finding *new* evidence is the point of a re-run.

---

## 5. Research Again API (§6, §7, §24)

`POST /research/{id}/research-again`
- Body: `{ "intent": "refresh"|"deepen"|"verify"|"full", "mode"?: ResearchMode,
  "sources_enabled"?: string[], "auto_start"?: bool=true }`.
- Parent fetched via `_get_project` (ownership → 404). Parent must be `COMPLETED` (else 409 — you
  continue a finished snapshot). Creates the child (§3), records audit `research.again`, and
  `manager.start(child.id)` when `auto_start`.
- Returns the new `ProjectDetail` (with lineage fields) → frontend navigates to the live view.

**Modes shipped in v1:** `refresh`, `deepen`, `verify`, `full`. `continue` is folded into `deepen`
(continue unresolved research), and `find-changes` is served by the **Diff** view rather than a
separate run mode — this is the "smallest useful implementation" the milestone asks for (§7), and
avoids UI the current planner can't meaningfully differentiate.

---

## 6. Research Memory record (§5, §23)

At completion, the orchestrator builds `memory_summary` (JSON) from the just-finalized immutable
rows — "optimized for future retrieval rather than storing prose" (§23):

```json
{
  "question": "...", "objective": "...",
  "key_findings": ["..."],                     // top findings
  "high_confidence_claims": [{"text","confidence"}],
  "weak_claims": [{"text","confidence"}],       // weak/unverified
  "contradictions": [{"statement_a","statement_b"}],
  "open_questions": ["..."],
  "important_sources": [{"title","url","reliability"}],
  "recommendation": {"option","confidence"} | null,
  "counts": {"sources","claims","evidence"},
  "confidence": {"avg","supported","weak","conflicting"},
  "as_of": "YYYY-MM-DD"
}
```

- `GET /research/{id}/memory` → returns `memory_summary` (or a live-computed fallback for
  legacy/uncompleted runs). Ownership enforced.
- **Memory search** (§22) reuses the existing knowledge base (`knowledge.search`) — no new vector
  system (§21). `index_project` already embeds objective/claims/recommendation; we additionally
  keep it scoped so lineage siblings don't crowd out "related prior research" at planning time
  (exclude the current `root_id`'s runs from `_surface_related_research`).

---

## 7. Research Diff engine (§9–§13, §19, §20, §25)

New module `app/services/research_diff.py`, **deterministic-first, zero LLM calls** in the default
path (§25). `diff_runs(old_proj_id, new_proj_id) -> ResearchDiff`. Both projects loaded read-only.

### 7.1 Source diff (§12)
Key by `dedup.normalize_url(url)` (documents already have stable `document://{id}` urls). Categories
per source: `NEW` / `REMOVED` / `UNCHANGED` / `CHANGED` (reliability, freshness, or published_date
differs). Output counts + lists.

### 7.2 Claim matching (§10 — deterministic-first, LLM-free)
1. **Exact / normalized text** (lowercase, strip punctuation/extra whitespace) → match.
2. **Token-set similarity** (Jaccard ≥ `research_diff_token_threshold`) on the unmatched remainder →
   deterministic near-match.
3. **Semantic** (optional, `research_diff_semantic`): embed only the *still-unmatched* old+new
   claims (one batched Ollama `nomic-embed-text` call), greedy best cosine ≥
   `research_diff_semantic_threshold`. Degrades to steps 1–2 on `KnowledgeUnavailable` (offline-safe;
   FakeProvider embeddings make it deterministic in tests).
4. No live LLM adjudication in v1 (CPU budget, §25). The matcher is a pluggable seam so LLM
   tie-breaking can be added later; "ambiguous" pairs (multiple candidates within a small cosine
   band) are resolved by highest score and flagged, which the tests assert deterministically.

### 7.3 Evidence-aware claim classification (§11, §19)
For matched pairs, compare `confidence`, `status`, and evidence composition (support/contradiction
counts from `ClaimSource` + `confidence_meta`):
- `NEW` (only in new) · `REMOVED` (only in old — "disappeared") · `UNCHANGED`
- `STRENGTHENED` — confidence ↑ ≥ `research_diff_confidence_delta`, or gained supporting sources.
- `WEAKENED` — confidence ↓ ≥ delta, or lost support.
- `CONTRADICTED` — contradiction count rose from 0, or status → `CONFLICTED`.
Each changed claim carries a **reason built from the two `confidence_meta` blocks** (§20, never
invented): e.g. `"contradiction_count 0 → 2; support_count 4 → 3; freshness fresh → aging"`, plus
the old/new supporting+contradicting passages so the UI can show *previous evidence → current
evidence → reason* by reusing the evidence drill-down.

### 7.4 Confidence diff (§20)
Per matched pair: `{old, new, delta, direction}` (↑/↓/=). Aggregate: counts increased/decreased/
unchanged.

### 7.5 Recommendation diff (§9)
Compare parent vs new `Recommendation.recommended_option` (normalized): `UNCHANGED` /
`MODIFIED` (same option, rationale/confidence changed) / `REVERSED` (different option) /
`NEW` (old had none) / `REMOVED`.

### 7.6 Document-aware diff (§13)
Compares **document-sourced evidence** in each run (Sources with `source_type == "documents"`)
keyed by `meta.document_id`, resolving the `Document` row for `checksum`/metadata: `NEW` / `REMOVED`
/ `UNCHANGED` / `CHANGED` (checksum or metadata differs). No chunk-level semantic document diff in
v1 (explicitly out of scope). For a continuation run to actually *have* documents to compare, see
§8.

### 7.7 Output shape
```
ResearchDiff{
  old_run:{id,run_number,completed_at}, new_run:{...},
  sources:{added,removed,unchanged,changed, items[]},
  claims:{new,removed,unchanged,strengthened,weakened,contradicted, items[]},
  confidence:{increased,decreased,unchanged},
  recommendation:{kind, old, new},
  documents:{new,removed,unchanged,changed, items[]},
}
```

---

## 8. Document carry-forward for continuation runs (§13, isolation §27)

Documents are project-scoped; a forked run starts with none, which would make document diff and
hybrid re-runs hollow. So Research Again **carries the parent's documents forward** (best-effort,
`research_again_carry_documents`, default on):
- Copy `Document` + `DocumentChunk` rows to the new project (same on-disk `storage_path`; the file
  already exists thanks to checksum dedup).
- Copy vectors **without re-embedding**: `vector_store` gains `copy_document_vectors(old_point_ids,
  new_points)` that `retrieve(..., with_vectors=True)` from the parent's points and re-upserts them
  under the new project_id payload + new point_ids. CPU-free (no Ollama call), preserves project
  isolation (search still filters by the new `project_id`).
- Best-effort + non-fatal: any failure logs and the run proceeds without documents. Carried
  documents keep their original `checksum`, so an *unchanged* document diffs as `UNCHANGED`.

This is the smallest mechanism that makes "Document evidence participates in the diff" (DoD) and
hybrid re-runs real, without OCR or semantic document diff (out of scope, §30).

---

## 9. API surface (§24, §27)

All under `/research`, all ownership-enforced via `_get_project`:

| Endpoint | Purpose |
|---|---|
| `POST /research/{id}/research-again` | Fork + start a continuation run (§5) |
| `GET /research/{id}/runs` | Lineage: all runs sharing `root_id`, ordered by `run_number`; each with counts + confidence summary + intent + status + timestamps |
| `GET /research/{id}/diff/{other_id}` | Deterministic diff of two runs (§7). Both fetched via `_get_project`; must share `root_id` (else 404) |
| `GET /research/{id}/memory` | The run's `memory_summary` (§6) |

`ProjectSummary`/`ProjectDetail` schemas gain `parent_id`, `root_id`, `run_number`, `run_intent`,
`completed_at`. New schemas: `RunSummary`, `ResearchDiffOut` (+ nested), `MemoryOut`,
`ResearchAgainRequest`.

**Security tests (§27):** user A cannot read/diff user B's run (404 via `_get_project`); diffing
across different `root_id`s → 404; document isolation preserved after carry-forward; memory endpoint
ownership-scoped.

---

## 10. Frontend (§17, §18)

- `api/types.ts`: lineage fields on Project types; `RunSummary`, `ResearchDiff` (+ nested),
  `MemorySummary`, `ResearchAgainRequest`. `api/client.ts`: `runs`, `researchAgain`, `diff`,
  `memory`.
- **History** (`History.tsx`): group projects by `root_id` into investigations — show the latest
  run's title/status + a "N runs" badge; expanding lists the runs (run #, intent, date, quick
  counts). Minimal, no app redesign (§17).
- **LiveResearch** (`LiveResearch.tsx`): on a `COMPLETED` run, add a **Research Again** control
  (intent picker: Refresh / Deepen / Verify / Full) and a **lineage strip** (Run #k, ← previous)
  with a **"Compare with previous"** link.
- **RunDiff** (new `pages/RunDiff.tsx`, route `research/:id/diff/:otherId`): the diff panel from
  §18 — Sources / Claims / Confidence / Recommendation / Documents summary; each changed claim
  expands to *previous evidence → current evidence → reason*, **reusing the existing `ClaimsTab`
  evidence drill-down** components.
- Diff categories rendered with explicit labels/colors (§19): UNCHANGED/NEW/REMOVED/CHANGED/
  STRENGTHENED/WEAKENED/CONTRADICTED.

---

## 11. Config additions

```
research_again_max_prior_claims: int = 12
research_again_carry_documents: bool = True
research_diff_semantic: bool = True
research_diff_semantic_threshold: float = 0.82
research_diff_token_threshold: float = 0.6
research_diff_confidence_delta: float = 8.0
```

---

## 12. Tests (§29) — all offline

**Backend (pytest):**
- *Run/lineage*: original sets root_id=id/run_number=1; research-again increments; lineage query;
  `memory_summary` built at completion; failure → child FAILED, **parent rows byte-for-byte
  unchanged** (immutability).
- *Research Again*: creates new run; parent preserved; planner **receives prior context** (spy /
  FakeProvider capture); refresh/deepen/verify intents; failure isolation; carry-forward copies
  documents + vectors and keeps isolation.
- *Diff*: identical runs (all unchanged); new/removed/changed source; new/changed/unchanged/
  contradicted claim; confidence up/down; recommendation unchanged/modified/reversed/new.
- *Claim matching*: exact, normalized, semantic (FakeProvider embeddings), ambiguous (tie-break),
  unrelated (no match).
- *Documents*: unchanged, changed checksum, new, removed.
- *Security*: cross-user run/diff/memory → 404; cross-root diff → 404.
- *Migration*: startup twice; existing projects/claims/sources/documents intact (extend the existing
  idempotency test); backfill sets root_id.
- *Regression*: full existing suite (152) stays green.

**Frontend (vitest):** RunDiff renders categories + counts and drills into a changed claim's
evidence; History groups runs by lineage; Research-Again button posts the chosen intent.

---

## 13. Order of implementation

1. Model columns + `_ADDED_COLUMNS` + backfill; set lineage in `create_research`; migration test.
2. `memory_summary` + `completed_at` at completion; `GET /memory`.
3. Planner `prior_context`/`intent`; orchestrator prior-context builder; wire on `parent_id`.
4. `research-again` endpoint + `RunManager.start`; lineage `GET /runs`.
5. Document carry-forward (`copy_document_vectors` + row copy) in research-again.
6. `research_diff.py` + `GET /diff/{other_id}` + schemas.
7. Frontend types/client → History grouping → LiveResearch controls → RunDiff page.
8. Full backend + frontend test pass; `docs/RESEARCH-MEMORY-COMPLETION.md` + validation report.

---

## 14. Explicitly out of scope (§30)

OCR; chunk-level semantic document diff; autonomous alerts/scheduled monitoring; MCP; collaboration/
multi-user editing; knowledge-graph redesign; new LLM provider architecture; live-vs-cached
classification. Diff stays deterministic (no LLM in the default path); LLM claim-adjudication is left
as a documented pluggable seam.
```

# ResearchMind AI — Gap Analysis & Development Plan

_Audit date: 2026-08-28. Grounded in a full read of the codebase (five parallel subsystem
audits), not the CLAUDE.md summary. Every "existing/partial/absent" claim below is backed by
the actual source._

---

## ⚑ Implementation status — P0 milestone #1 + #2 DONE (2026-08-28)

The evidence & verification foundation (top-5 items **#1 Evidence drill-down** and **#2
Recency-aware confidence + active contradiction search**) is implemented, tested, and shipped.
Delivered:

- **`claim_sources` join table** (referential integrity + `stance` + quoted `passage`) replacing
  the opaque JSON id array as the authoritative evidence graph edge; `supporting_source_ids` kept
  as a mirror for backward compatibility.
- **Source freshness/recency** (`services/freshness.py`, domain-aware thresholds) surfaced on
  sources and folded into the confidence model.
- **Recency- and contradiction-aware confidence** (`verification.score_claim`) with a transparent
  `confidence_meta` breakdown (counts, avg reliability, freshness, reasons — the "why").
- **Active contradiction search** (`agents/contradiction.py`) — bounded search for disconfirming
  evidence on top-N important claims, persisted as `CONTRADICTS` links and re-scored.
- **`GET /research/{id}/claims/{claim_id}/evidence`** returning per-source passages + freshness.
- **Expandable claims UI** with quoted evidence, stance grouping, freshness badges, and the
  confidence rationale; freshness badges on the Sources tab. Clear states: Supported / Weak /
  Conflicting / Outdated / Unverified.
- **Tests:** backend 127 passing (freshness, scoring, contradiction agent, evidence API); frontend
  9 passing (pure mapping + `ClaimsTab` DOM behavior). Safe auto-migration (`database._ensure_columns`)
  adds the new column to existing DBs with no wipe.

The inventory rows below reflect the **pre-milestone** audit; the items above are now ✅.

---

## ⚑ Implementation status — Milestone #3 Document RAG DONE (2026-08-28)

`Local document search / RAG over user files` (top-5 item **#3**) is implemented, tested, shipped.
User-uploaded PDF/DOCX are now first-class research evidence via the **same** P0 evidence engine (no
parallel citation system): upload → validate (magic-byte + size + sanitize + sha256 dedup) → parse
(pypdf/python-docx) → structure-aware chunk → embed (Ollama) → **separate project-isolated Qdrant
`documents` collection** → a `documents` collection agent retrieves passages that become
`Source`/`ClaimSource(passage)` evidence with page/section/freshness. **Offline** (documents-only run
= zero network) and **hybrid** (documents + web) both work. New API `POST/GET/DELETE /documents` +
`/documents/search`; a frontend Documents tab (upload/status/list/delete/search) and 📄 document
evidence in the Claims drill-down. Additive migration (two new tables). See
`docs/DOCUMENT-RAG-IMPLEMENTATION-PLAN.md` and `docs/DOCUMENT-RAG-COMPLETION.md`.

---

## ⚑ Implementation status — Milestone #4 Research Memory + Again + Diff DONE (2026-08-31)

Versioned research (top-5 item **#4**) is implemented, tested, shipped. **A Research Run is a
`ResearchProject`** — no parallel run table — with an additive lineage self-reference
(`parent_id`/`root_id`/`run_number`/`run_intent`/`completed_at`/`memory_summary`). Completed runs are
immutable snapshots. **Research Again** (`POST /research/{id}/research-again`, intents refresh/deepen/
verify/full) forks a new run, threads the parent's *selective memory* (high-confidence claims, open
questions, contradictions, prior recommendation) into the planner with **zero extra LLM calls**, and
best-effort carries the parent's documents forward (row + vector copy, no re-embed). **Research Diff**
(`GET /research/{id}/diff/{other_id}`) is a deterministic, LLM-free comparison — sources (by
normalized URL), evidence-aware claims (normalized→token→optional-embedding matching; strengthened/
weakened/contradicted with reasons built from `confidence_meta`), confidence, recommendation, and
document evidence. New endpoints `GET /runs` and `GET /memory`. Frontend: lineage bar + Research Again
control in the live view, a dedicated RunDiff page (previous→current evidence drill-down), and
lineage-grouped History. Additive/idempotent migration with a `root_id` backfill. See
`docs/RESEARCH-MEMORY-IMPLEMENTATION-PLAN.md` and `docs/RESEARCH-MEMORY-COMPLETION.md`.

---

## A. Current Architecture (as-built)

```
                          FastAPI app (app/main.py)
                                    │
   ┌──────────────┬─────────────────┼──────────────────┬───────────────┐
   │              │                 │                  │               │
 Auth (JWT)   RateLimit/         RunManager        SchedulerService   SSE EventBus
 bcrypt       SecurityHdrs      (in-proc asyncio    (in-proc poll     (in-proc pub/sub,
 SSRF guard   middleware         tasks, in-mem       loop, spawns      per-project queues)
                                 controls)           new projects)
                                    │
                        orchestration/orchestrator.py  ── run_research()
                                    │
   plan (planner) → fan-out tasks (Semaphore 4) → dispatch.collect() [hardcoded source→fn map]
        │                                              │
        │                        ┌────────────┬────────┴────────┬──────────────┐
        │                      tavily_agents  github_research  academic_research
        │                      (web/docs/     (REST, repo       (arXiv Atom)
        │                       news/comm)     metadata)
        ▼
   extract findings (LLM/source) → dedupe (URL + Jaccard) → verify (LLM cluster + computed score)
        → detect conflicts (LLM) → gap loop (≤2 rounds) → R&D analysis (3 LLM stages)
        → build report (deterministic assembly + LLM prose) → index into Qdrant
                                    │
                         SQLite (async SQLAlchemy)  +  Qdrant embedded (on-disk vectors)
                                    │
                         Ollama (llama3.1:8b + nomic-embed-text)
```

**Data flow:** user picks sources → LLM plans questions → each `(source, question)` routed by a
hardcoded if/elif → real HTTP search → LLM extracts findings → deterministic dedup/scoring →
LLM verification/conflict/R&D → deterministic report assembly. **The LLM never selects tools;**
the human source-picker + a fixed budget/order decide everything.

**Frontend:** React SPA, sidebar shell, 9 screens, auth-gated. Live research view = 8 tabs
(Activity/Plan/Sources/Claims/Conflicts/Recommendation/Graph/Report) fed by SSE + 4s polling.
It is a **research-workspace UI, not a chatbot.**

---

## B. Feature Inventory

Quality: ★★★ solid · ★★ works-but-shallow · ★ stub/cosmetic · — absent.

| Capability | Existing | Partial | Missing | Quality | Priority to improve |
|---|:-:|:-:|:-:|:-:|:-:|
| Web / news / community search (Tavily+SearXNG) | ✅ | | | ★★★ | — |
| Documentation search | | ✅ | | ★★ (query-suffix, no docs API) | P2 |
| Academic search (arXiv, w/ method+limitations) | ✅ | | | ★★★ | P2 (screening) |
| GitHub search (repo metadata) | ✅ | | | ★★ (no code/releases/PRs/issues body) | P2 |
| API-research (arbitrary APIs) | | | ✅ | — | P3 |
| Local document search / RAG over user files | | | ✅ | — | **P0/P1** |
| Query decomposition / research planning | ✅ | | | ★★★ | — |
| Parallel research (asyncio, Semaphore) | ✅ | | | ★★★ | — |
| Automatic follow-up / gap loop (≤2 rounds) | ✅ | | | ★★★ (LLM-judged trigger) | P1 |
| Tool abstraction layer (Tool interface/registry) | | | ✅ | — | P2 |
| Dynamic tool selection by the agent | | | ✅ | — | P2/P3 |
| Source reliability/authority scoring | ✅ | | | ★★★ (domain-based) | — |
| Source **recency/freshness** in scoring | | | ✅ | — (recency stored, never scored) | **P0** |
| Claim extraction | | ✅ | | ★★ (grounded LLM, 2 stages) | P1 |
| Claim verification | | ✅ | | ★★ (clusters existing findings; **no active contradiction search**) | **P0** |
| Cross-source rule (≥2 sources to VERIFY) | ✅ | | | ★★ (count-based, not semantic) | P1 |
| Claim→source mapping (traceability) | ✅ | | | ★★ (JSON id list, no FK, no passage) | **P0** |
| Conflict / contradiction detection | | ✅ | | ★★ (LLM judgment, no programmatic compare) | P1 |
| Confidence scoring — **claims** | ✅ | | | ★★★ (computed: sources×reliability) | P1 (add recency/agreement) |
| Confidence scoring — **recommendation** | | ✅ | | ★ (LLM-labeled number — inconsistent w/ claims) | P1 |
| Deduplication | ✅ | | | ★★★ (URL + token Jaccard) | P2 (embeddings) |
| R&D analysis (comparison→rec→plan) | ✅ | | | ★★ (structured; ratings are LLM strings) | P2 |
| Solution comparison table | ✅ | | | ★★ (UI only, not exportable) | P2 |
| Structured research tables (product/academic/evidence) | | ✅ | | ★ (only comparison table) | P1 |
| Report (deterministic assembly + LLM prose) | ✅ | | | ★★★ | — |
| Report quality gate (pre-finalize checks) | | | ✅ | — | P1 |
| Export MD/HTML/PDF/DOCX | ✅ | | | ★★★ | — |
| Export CSV/XLSX/JSON | | | ✅ | — | P2 |
| Semantic search over completed projects | ✅ | | | ★★★ (embeddings + kw fallback) | — |
| Related-research lookup | ✅ | | | ★★ (nearest-neighbor only) | P2 |
| Research **memory / continuation** ("continue my research on X") | | | ✅ | ★ (cosmetic activity event only) | **P1** |
| Knowledge graph | | ✅ | | ★ (relational-reshape, non-persisted, no entity extraction, single-project) | P1 |
| Research reproducibility (full trace) | | ✅ | | ★ (final rows only; rejected sources/tool-calls dropped) | P1 |
| Research **versioning / diff / "what changed"** | | | ✅ | — | **P1** |
| Research history / projects | ✅ | | | ★★ (list only, no workspace) | P2 |
| Persistent per-project workspace | | ✅ | | ★ (single results page) | P2 |
| Scheduled research | ✅ | | | ★★★ | — |
| Research alerts / source monitoring / change-detect | | ✅ | | ★ (schedules re-run but never diff) | P1 |
| "Research Again" (refresh/deepen/verify) | | | ✅ | — | **P1** |
| **Online/offline connectivity awareness** | | | ✅ | — (no detection, no degradation, no live-vs-cached tag) | **P1** |
| Query / source caching | | | ✅ | — | P2 |
| Observability (tokens/durations/tool-calls) | | | ✅ | — (only coarse audit_logs) | P2 |
| Evidence drill-down UI (click claim → sources → passage) | | | ✅ | — (claims are dead-ends) | **P0** |
| Knowledge-graph visualization | | ✅ | | ★ (static non-interactive SVG) | P2 |
| Research-stage stepper UI | | | ✅ | — (free-text label + event feed) | P2 |
| Auth / SSRF / rate-limit / audit log | ✅ | | | ★★★ | — |
| LLM provider abstraction (Ollama impl) | ✅ | | | ★★★ (swappable; 1 impl ships) | — |
| MCP server / agent-tool interface | | | ✅ | — | P3 |

**Headline:** the *evidence spine is genuinely real and computed* (dedup, reliability, the ≥2-source
gate, claim confidence, deterministic report assembly). The gaps cluster in three places:
(1) **the evidence is invisible** — the UI throws away the traceability the backend computes;
(2) **verification is passive** — it never seeks disconfirming evidence and ignores recency;
(3) **there is no memory, no user-document ingestion, and no offline awareness** — three of the
project's own stated differentiators are absent.

---

## C. Benchmark vs. Modern Research Platforms

| Dimension | ResearchMind today | Elicit | Perplexity / GPT Deep Research | NotebookLM |
|---|---|---|---|---|
| General-purpose (not just papers) | ✅ 6 sources | ❌ academic-only | ✅ | ❌ user-docs-only |
| Evidence traceability | ✅ computed, ❌ **not surfaced** | ✅ per-claim, clickable | ⚠️ inline cites | ✅ grounded to docs |
| Claim → passage drill-down | ❌ | ✅ | ⚠️ | ✅ |
| Active contradiction-seeking | ❌ (passive over collected) | ⚠️ | ⚠️ | n/a |
| Conflict surfacing | ✅ (LLM) | ⚠️ | ❌ (blends) | n/a |
| Structured extraction tables | ⚠️ comparison only | ✅ (signature feature) | ❌ | ❌ |
| User-document RAG | ❌ | ⚠️ | ⚠️ | ✅ (signature) |
| Research memory / continuation | ❌ | ⚠️ notebooks | ⚠️ threads | ✅ |
| Versioning / "what changed" | ❌ | ❌ | ❌ | ❌ |
| Continuous monitoring / alerts | ⚠️ re-run, no diff | ❌ | ❌ | ❌ |
| Offline / local-first | ✅ LLM+vectors, ❌ no offline research | ❌ cloud | ❌ cloud | ❌ cloud |
| Knowledge graph | ⚠️ cosmetic | ❌ | ❌ | ❌ |

**Where ResearchMind can genuinely win** (whitespace no competitor owns): offline/local-first
research, research **diff/versioning**, autonomous **monitoring with change-detection**, and a
real claim↔evidence↔source **graph** — provided the evidence layer is made visible and verifiable
first.

---

## D. Prioritized Backlog

| Feature | Why needed | User value | Complexity | Dependencies | Priority |
|---|---|---|---|:-:|:-:|
| Evidence drill-down UI + passage storage | Traceability is computed but invisible; claims are dead-ends | Very high | Low–Med | store passage on claim↔source | **P0** |
| Recency in reliability/confidence + freshness badges | Correctness: stale sources scored as fresh | High | Low | scoring.py, published_date | **P0** |
| Active verification (contradiction-seeking) | "Never trust a single source" is only counting; no disconfirming search | High | Med | search layer, verify stage | **P0** |
| Claim↔source integrity (join table) | JSON id arrays → no referential integrity, no passage/quote | High | Low–Med | schema migration | **P0** |
| Unify confidence model (claim vs rec) | Two mechanisms; recommendation confidence is fabricated | Med | Low | rd_analysis, report | P1 |
| Document ingestion + RAG (local corpus) | Biggest missing capability; enables offline-over-own-docs | Very high | Med–High | Qdrant (exists), parsers, chunker, dispatch | **P1** |
| Research memory / continuation | "Continue my research on X" absent; each run from zero | High | Med | run-versioning, context injection | **P1** |
| Research versioning + diff ("what changed") | Signature differentiator; monitoring re-runs never diff | High | Med | run-history table, diff engine | **P1** |
| Online/offline connectivity awareness | Stated differentiator; fits flaky-corporate-proxy env | High | Med | connectivity probe, degradation, tags | **P1** |
| "Research Again" (refresh/deepen/verify) | No re-run affordance on completed reports | High | Low–Med | versioning, orchestrator entry points | P1 |
| Report quality gate | No pre-finalize completeness/hallucination/citation check | Med–High | Med | verify + report | P1 |
| Structured extraction tables (product/academic) | Only comparison table exists; Elicit's signature | Med | Med | schema for extraction rows, UI | P1 |
| Real persisted knowledge graph + entity extraction | Current graph is cosmetic reshape | Med | High | nodes/edges tables, NER stage | P2 |
| Tool abstraction layer + dynamic selection | Hardcoded map; blocks extensibility & agent autonomy | Med | Med–High | dispatch refactor | P2 |
| Query/source caching | Every run re-hits network | Med | Low–Med | cache store | P2 |
| Observability (tokens/durations/tool-calls) | Can't debug poor runs | Med | Low–Med | run-metrics table | P2 |
| Export CSV/XLSX/JSON | Structured data not machine-exportable | Low–Med | Low | openpyxl | P2 |
| GitHub deep (releases/issues/commits) | Repo-metadata only | Low–Med | Med | github API | P2 |
| Interactive graph viz | Static SVG | Low | Med | reactflow/cytoscape | P2 |
| MCP server + REST-as-platform | Platform play | Med | Med–High | stable API | P3 |
| API-research agent (arbitrary APIs) | Not in source set | Low | Med | tool layer | P3 |

---

## E. Target Architecture (incremental — reuses existing seams)

```
                         Research Orchestrator (existing, extended)
                                    │
   ┌───────────────┬───────────────┼──────────────────┬─────────────────┐
 Connectivity    Tool Registry   Evidence Engine   Memory/Version     Quality Gate
  Probe (new)     (new, wraps    (verify + recency  (run-history +      (new, pre-report)
                  existing        + contradiction    diff engine)
                  collect fns)    + passage store)
                                    │
        ┌───────────────┬──────────┴──────────┬────────────────┐
   Online tools      Local tools          Evidence store     Knowledge Graph
   web/news/gh/       DocCorpusTool         (claims↔sources    (persisted nodes/
   arxiv/docs         (RAG over user        join + passages)    edges + entities)
                      PDFs/DOCX → Qdrant)
```

**Principle:** every new capability slots behind an existing seam. Tools wrap the current
`collect()` functions; the evidence engine extends the current `verify` stage; memory/version add
tables without touching the pipeline shape; offline is a probe + a routing branch.

---

## F. Database Changes

New/changed tables (SQLite now, Postgres-ready):

- **`claim_sources`** (join table, replaces `claims.supporting_source_ids` JSON): `claim_id` FK,
  `source_id` FK, `stance` (supports/contradicts/neutral), `passage` (Text — the quoted evidence),
  `char_start/char_end` (int, offsets into source content). *Gives referential integrity + the
  passage needed for drill-down. P0.*
- **`documents`** + **`document_chunks`**: user-uploaded files → `documents(id, user_id, project_id?,
  filename, mime, sha256, bytes, status)`; `document_chunks(id, document_id, ordinal, text,
  token_count, qdrant_point_id)`. *Enables RAG. P1.*
- **`research_runs`**: multiple runs per project — `run(id, project_id, version_int, started_at,
  finished_at, status, params_json)`; move the run-scoped outputs to reference a run so versions
  coexist. Enables diff. *P1.*
- **`run_metrics`** / observability: `(run_id, tool, calls, sources_found, sources_rejected,
  llm_calls, prompt_tokens, completion_tokens, duration_ms, failed_searches)`. *P2.*
- **`kg_nodes`** / **`kg_edges`**: persisted, cross-project graph with `entity_type`, `label`,
  `relation`, provenance FK to claim/source. *P2.*
- **`monitors`**: topic-monitoring config distinct from `scheduled_research` + `monitor_findings`
  for change deltas. *P1/P2.*
- Add `reliability` **freshness inputs**: no new table — extend `sources` scoring at write time and
  add a computed `freshness_state` column (fresh/aging/outdated/unknown). *P0.*

Indexes: `claim_sources(claim_id)`, `claim_sources(source_id)`, `document_chunks(document_id)`,
`research_runs(project_id, version_int)`, `monitors(user_id, next_check_at)`.

---

## G. API Changes

New endpoints (all `[U]` unless noted):
- `GET /research/{id}/claims/{claim_id}/evidence` → sources + passages + stance (**P0**).
- `POST /research/{id}/again` `{mode: refresh|deepen|verify|contradict}` → spawns a new **run**
  (version+1) of the same project (**P1**).
- `GET /research/{id}/runs` and `GET /research/{id}/diff?from=&to=` → version list + change delta
  (**P1**).
- `POST /documents` (multipart upload), `GET /documents`, `DELETE /documents/{id}`,
  `POST /research/{id}/documents/{doc_id}` to attach a doc as a source (**P1**).
- `GET /health/connectivity` → live online/offline + per-source reachability (**P1**).
- `POST /monitors`, `GET /monitors`, `GET /monitors/{id}/changes` (**P1/P2**).
- `GET /research/{id}/export?format=csv|xlsx|json` (extend existing) (**P2**).
- Streaming: reuse the SSE bus; add `evidence`/`freshness`/`diff` event types.

---

## H. UI/UX Changes

- **Evidence drill-down (P0):** make each claim row expandable → supporting/contradicting sources,
  quoted passage, reliability + freshness pill, jump-to-source. Link conflicts back to the claims
  they affect.
- **Freshness badges (P0):** 🟢/🟡/🔴/⚪ on every source, domain-aware thresholds.
- **Documents panel (P1):** upload/drag-drop, list, attach-to-research; a NotebookLM-style
  "ask my documents" entry point.
- **"Research Again" button + Runs/Diff view (P1):** on completed reports; a "what changed" delta
  screen comparing two runs.
- **Stage stepper (P2):** Planning→Searching→Reading→Verifying→Synthesizing→Complete, driven by
  existing stage events.
- **Interactive graph (P2):** replace static SVG with reactflow/cytoscape; wire the two unused
  client methods (`api.tasks`, `api.addQuestion`) into a Tasks panel + user-question input.

---

## I. Phased Implementation Plan

**Phase 1 — Evidence made real & visible (P0).** claim_sources join + passage storage; recency
in scoring + freshness state/badges; active contradiction search in verify; evidence drill-down UI;
unify confidence. *Tests: verify picks up contradicting sources; freshness thresholds by domain;
claim→evidence endpoint returns passages.*

**Phase 2 — Local corpus / RAG (P1).** document upload + parse (pypdf/python-docx/markdown) +
chunk + embed into existing Qdrant; `DocCorpusTool` as a first-class source; documents panel.
*Tests: uploaded PDF becomes searchable; a run cites a user document.*

**Phase 3 — Memory, versioning, diff, Research-Again (P1).** research_runs table; continuation
(inject prior claims/findings as planning context); diff engine; "what changed" screen.
*Tests: second run of same project produces a diff; continuation reuses prior context.*

**Phase 4 — Offline awareness + monitoring (P1).** connectivity probe; graceful degradation to
local corpus + knowledge base when internet drops; live-vs-cached tagging; monitors with
change-detection notifications. *Tests: simulated internet-loss mid-run degrades instead of failing
and tags sources.*

**Phase 5 — Quality gate, structured tables, observability, extra exports (P1/P2).**
pre-report completeness/citation/hallucination checks; product/academic extraction tables;
run_metrics; CSV/XLSX/JSON export.

**Phase 6 — Platform (P2/P3).** persisted knowledge graph + entity extraction; tool-registry
refactor + dynamic selection; MCP server; interactive graph viz.

---

## J. Risks & Dependencies

- **CPU-only Ollama is the throughput ceiling.** Every new LLM stage (contradiction search,
  entity extraction, quality gate) adds minutes to a ~40-min run. *Mitigation: make each new
  stage opt-in per mode / gated to high-stakes claims only; cache aggressively.*
- **Active contradiction search multiplies network calls** against the same flaky corporate proxy.
  *Mitigation: bounded budget, run only for claims above a stakes threshold, reuse SSRF-safe fetch.*
- **Schema migrations:** no migration tool today (tables auto-create). Moving `supporting_source_ids`
  JSON → join table needs a one-off backfill script. *Mitigation: add Alembic, or a guarded
  idempotent backfill like the existing salvage pattern.*
- **Backward compatibility:** legacy `user_id IS NULL` projects and JSON-linked claims must keep
  rendering during/after the join-table move. *Dual-read during transition.*
- **Scope creep:** the master prompt is enormous. This plan deliberately front-loads correctness
  and the three real differentiators, and defers platform/graph/tool-registry work.

---

## K. Top 5 Highest-Impact Capabilities (do these first)

1. **Evidence drill-down + claim↔source integrity (P0).** The backend already computes
   traceability and confidence; the UI discards it. Add a `claim_sources` join with stored
   passages, expose `GET .../claims/{id}/evidence`, and make claims expandable to their quoted
   evidence + freshness. *Highest ROI in the whole plan — mostly surfacing work that already exists.*
2. **Recency-aware confidence + active contradiction search (P0).** Fold source freshness into the
   reliability/confidence model (domain-aware), and add a bounded disconfirming-evidence search for
   high-stakes claims. Fixes the two biggest correctness holes and honors "never trust a single
   source" for real. *Correctness before features — the project's own stated principle.*
3. **Document ingestion + RAG (P1).** Upload PDFs/DOCX/MD → chunk → embed into the existing Qdrant
   → first-class local source. Biggest missing capability, unlocks true offline research over the
   user's own corpus, and reuses infra that already ships.
4. **Research memory + "Research Again" + diff (P1).** Version runs, let a project continue with
   prior context, and diff two runs into a "what changed" report. Turns one-shot reports into a
   living research asset — a differentiator no benchmark offers.
5. **Online/offline connectivity awareness (P1).** Detect connectivity, degrade gracefully to the
   local corpus + knowledge base, and tag every source live-vs-cached (never present stale as live).
   The project's headline differentiator, and directly valuable in the flaky-proxy environment it
   runs in.
```


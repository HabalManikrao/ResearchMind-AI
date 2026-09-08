# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Current State: Phase 1–6 complete; Phase 7 near-complete (only Postgres/Redis swap left). Milestones #1–#10 shipped (evidence drill-down, verification, Document RAG, research memory/again/diff, connectivity intelligence, continuous monitoring, knowledge graph + temporal knowledge, API + MCP + extensibility, research-quality benchmark + production hardening, real-world evaluation + quality improvement)

A working end-to-end Deep Research pipeline across **six source agents** plus verification, dedup,
conflict detection, knowledge-gap follow-up, **structured R&D analysis**, a **semantic knowledge
base** (memory, reuse, graph), **report export** (MD/HTML/PDF/DOCX), **monitoring + audit log**,
**security hardening** (rate limiting, SSRF-safe fetch, security headers), **JWT authentication with
per-user project ownership**, **scheduled research**, and **in-app notifications**. The authoritative
product brief is `Master Development Prompt — Personal Autonomous Research AI Agent.md`. `README.md`
has setup/run steps.

Implemented so far:
- **Backend** (`backend/`, FastAPI + async SQLAlchemy + SQLite): Research Planner → **source-aware
  parallel task dispatch** across Web / Documentation / GitHub / Academic(arXiv) / News / Community
  agents → finding extraction → claim verification → **deduplication** (`app/services/dedup.py`) →
  **conflict detection** (`app/agents/conflict_detection.py`) → **R&D analysis**
  (`app/agents/rd_analysis.py`) → knowledge-gap follow-up loop → Markdown report. Live progress over
  SSE. Pause/resume/stop. State persisted to SQLite.
- **Knowledge base** (`backend/app/knowledge/`): completed projects are embedded (Ollama
  `nomic-embed-text`) and indexed into **Qdrant embedded local mode** (`vector_store.py`, on-disk at
  `QDRANT_PATH`, no server). `service.py` does semantic search, related-research lookup, and builds a
  per-project **knowledge graph** derived from the relational rows. All embedding-dependent calls
  degrade to keyword search if the embedding model isn't pulled (`KnowledgeUnavailable`). The
  orchestrator surfaces related prior research at planning time and indexes the project on completion.
- **Production layer** (Phase 7, partial): report export (`app/export/`, MD/HTML/PDF via xhtml2pdf/
  DOCX via python-docx) at `GET /research/{id}/export?format=`; monitoring (`app/api/monitoring.py`:
  `/monitoring/stats`, `/monitoring/audit`); security (`app/security/`: `RateLimitMiddleware`,
  `SecurityHeadersMiddleware`, and `net.validate_url` SSRF guard wired into the GitHub/arXiv fetches);
  audit logging (`app/services/audit.py` → `audit_logs` table) on create/start/stop/export.
- **Frontend** (`frontend/`, React + TS + Vite + Tailwind): Dashboard, New Research (source picker),
  live research view (Plan+gaps / Sources / Claims / Conflicts / **Recommendation** / **Graph** /
  Report tabs with **export buttons**), History, Knowledge Base (semantic search + reindex),
  **Monitoring** (stats + audit log).

Pipeline order & progress checkpoints are in `app/orchestration/orchestrator.py:run_research`. The
tail after the research/gap loop is: **dedupe → re-verify claims → detect conflicts → R&D analysis →
build report**.

### Evidence engine (claim ↔ source ↔ passage; recency- & contradiction-aware confidence)
Claims are traceable to their evidence through the **`claim_sources` join table** (`ClaimSource`:
`claim_id`, `source_id`, `stance` = supports/contradicts/neutral, quoted `passage`). It is the
authoritative evidence graph edge; `claims.supporting_source_ids` (JSON) is kept as a denormalised
mirror for the knowledge-graph builder. **Confidence is computed, not LLM-labelled**
(`verification.score_claim`): inputs are distinct-source count, mean reliability, **recency**
(`services/freshness.py`, domain-aware fresh/aging/stale thresholds — news stale in days, papers in
years), and **contradiction count**. Each claim stores a transparent `confidence_meta`
(`support_count`, `contradiction_count`, `avg_reliability`, `freshness`, `outdated`, human `reasons`)
and derives a display `evidence_state` (supported/weak/conflicting/outdated/unverified). After the
final verify, **active contradiction search** (`agents/contradiction.py`, bounded to the top-N
important claims via `contradiction_*` settings) searches the web for *disconfirming* evidence,
persists it as `CONTRADICTS` links, and re-scores the affected claims. Evidence is exposed at
`GET /research/{id}/claims/{claim_id}/evidence` (source + passage + freshness + stance) and rendered
in the frontend's expandable Claims tab. Pipeline order gained a stage: dedupe → re-verify (86%) →
**contradiction search (87%)** → conflict detection (88%) → R&D (92%). **Schema note:** there are no
migrations; a column added to an existing table is applied by `database._ensure_columns` (idempotent
SQLite `ALTER TABLE ADD COLUMN`) — keep `_ADDED_COLUMNS` in sync when adding nullable columns.

### Document RAG (#3): uploaded PDFs/DOCX as first-class evidence
User documents are **another collection source**, not a parallel citation system. Upload
(`POST /documents`, multipart, project-scoped, `api/documents.py`) → validate (extension allowlist +
**magic-byte sniff**, size cap, filename sanitized, UUID storage names, sha256 + duplicate detection,
`documents/service.py`) → background `process_document`: parse (`documents/parsing.py`: pypdf per-page
+ metadata, python-docx paragraphs/headings/tables) → structure-aware chunk (`documents/chunking.py`:
heading/paragraph boundaries, token budget + block overlap, exact page/section/char metadata) → embed
(same Ollama `nomic-embed-text`, batched) → index into a **separate Qdrant `documents` collection**
(`vector_store.upsert_documents/search_documents`, project-id-filtered ⇒ hard isolation). Status
lifecycle `uploaded→parsing→chunking→embedding→indexing→ready|failed` (`DocumentStatus`), polled via
`GET /documents/{id}/status`. At research time the **`documents` agent** (`agents/document_research.py`,
wired into `dispatch.py`/`SOURCE_ORDER`/`SOURCE_QUESTION_BUDGET`; `dispatch.collect` gained a
`project_id` param) retrieves top chunks and returns the uniform `CollectedSource` (`source_type=
"documents"`, `url="document://…"`, `meta={document_id,chunk_id,page_number,section,filename}`), so
persistence → `verify()` → `Claim`/`ClaimSource(passage)` → the evidence endpoint (now surfaces
`page_number`) all work unchanged. Freshness uses the document's own metadata dates (never upload
time; `freshness` "documents" threshold). **Offline** = a `sources_enabled=["documents"]` run makes
zero network calls (local Qdrant + Ollama); **hybrid** = documents + web together. Config:
`document_*` settings. Storage dir `document_storage/` is gitignored. Frontend: a **Documents tab**
(`components/DocumentsPanel.tsx`) for upload/status/list/delete/search, `Documents` in the source
picker, and 📄 document evidence in the expandable Claims tab. New deps: `pypdf`, `python-multipart`
(+ `reportlab` dev-only for test PDFs). Tests: `test_document_*.py` (parsing, chunking, security,
service, API, pipeline offline+hybrid) + frontend `DocumentsPanel.test.tsx`.

### Research Memory + Research Again + Research Diff (#4): a run IS a project
Versioned research **reuses `ResearchProject` as the run** — no separate run table. Additive nullable
lineage columns on `research_projects` (`parent_id`, `root_id`, `run_number`, `run_intent`,
`completed_at`, `memory_summary`; migration via `_ensure_columns` + an idempotent `root_id` backfill in
`database._backfill_lineage`). Originals set `root_id = self.id`/`run_number = 1`/`run_intent =
"original"` (`api/research.py:create_research`); a **whole lineage is one indexed query on `root_id`**.
Completed runs are **immutable snapshots** — nothing rewrites them and `/start` already blocks re-runs.
- **Research Again** (`POST /research/{id}/research-again`, intents `refresh|deepen|verify|full`)
  **forks a new linked project** and starts it; the parent is read-only. The orchestrator builds the
  parent's **selective prior context** (`_build_prior_context`: top high-confidence claims, open
  questions, known contradictions, prior recommendation, previous date) and threads it into the planner
  (`planner.make_plan(prior_context=, intent=)` — `PriorContext` + per-intent system addendum) with
  **zero extra LLM calls**. At completion the orchestrator writes `memory_summary` (`_build_memory_summary`).
- **Document carry-forward** (`documents/service.carry_forward_documents`): a re-run copies the parent's
  READY documents — each gets its **own physical file copy** (so neither run's delete orphans the other)
  and **chunk vectors are copied without re-embedding** (`vector_store.copy_document_vectors` =
  retrieve+re-upsert under the new `project_id`; CPU-free, isolation preserved). Best-effort/non-fatal.
- **Research Diff** (`GET /research/{id}/diff/{other_id}`, `services/research_diff.py`) is
  **deterministic, no LLM in the default path**: sources by `dedup.normalize_url`; claims matched
  normalized-text → token-set (Jaccard) → optional embedding cosine on the remainder (offline-safe);
  evidence-aware categories (`new/removed/unchanged/strengthened/weakened/contradicted`) with **reasons
  built from `confidence_meta`** (never invented); confidence deltas; recommendation diff
  (`unchanged/modified/reversed/new/removed`); document diff by identity + checksum. Both ids go through
  `_get_project` and must share `root_id` (else 404).
- **Lineage/memory APIs**: `GET /research/{id}/runs` (lineage + per-run counts) and `GET /memory`.
  **Frontend:** lineage bar + Research Again intent picker in the live view, a dedicated **RunDiff**
  page (`research/:id/diff/:otherId`, previous→current evidence drill-down), lineage-grouped **History**.
  Config: `research_again_*` / `research_diff_*`. Tests: `test_research_diff.py`,
  `test_research_again.py`, `test_migration_lineage.py` + frontend `RunDiff/History/LineageBar.test.tsx`.
  Docs: `docs/RESEARCH-MEMORY-{IMPLEMENTATION-PLAN,COMPLETION}.md`.

### Connectivity Intelligence + Live/Cached/Local Research (#5): source-aware resilience
ResearchMind knows the availability of every source and gracefully switches between live, cached, and
local evidence — **without ever labelling cached/local evidence as live**. The design is reuse-first:
provenance rides on existing structures, and only the web cache is genuinely new.
- **Provenance vs availability** (`services/provenance.py`): *provenance* (`live_web`/`cached_web`/
  `local_document`/`local_memory`/`local_database`) is stamped onto `Source.meta["provenance"]` at
  collection time and **never inferred**; *availability* (`live`/`cached`/`local`/`stale`/`unavailable`/
  `unknown`) is derived from provenance + freshness (stale overlays any origin). Exposed as computed
  `Source.provenance`/`Source.availability` properties (like the existing `Source.freshness`) — **zero
  migration**. A source is `live_web` **only** when `dispatch.collect` actually returned it live this
  run (spec §8). `UNAVAILABLE` is a run-level count of failed external tasks, never a phantom row.
- **Connectivity manager** (`services/connectivity.py`): a layered, bounded, **on-demand-cached**
  health model (not a poller, not one ICMP ping). Probes internet (HEAD to the hosts we actually call),
  the search provider, and local infra (Ollama/Qdrant/DB), each with a short timeout; snapshot cached
  `connectivity_cache_seconds`. States: `online`/`degraded`/`local_only`/`offline`/`recovering`/
  `unknown`; a previous-state memory yields `recovering` with no background traffic. Probes are
  module-level async fns so tests monkeypatch them. Singleton `manager`. `GET /system/connectivity`.
- **Source cache** (`models/cache.py` `CachedSource` + `services/source_cache.py`): the only new store.
  Last successful external result set per `(project_id, source_type, query_hash)`, **TTL by type**
  (`cache_ttl_*_minutes`), **project-isolated** (every read filters `project_id` — spec §30), content
  only (never keys/headers/cookies). New table via `create_all`.
- **Resilient collection** (`services/collection.py` `resilient_collect`): a source-agnostic wrapper
  over `dispatch.collect` the orchestrator's worker calls. Local agents (`documents`) always run
  (`local_document`, never cached); external agents honour the run's **`SourcePolicy`** (`live_only`/
  `live_preferred`/`cache_allowed`/`local_only`, nullable `research_projects.source_policy` col →
  default `live_preferred`): live success stamps `live_web` + caches (unless `live_only`); live failure
  serves the cached set (`cached_web`) if within TTL, else re-raises → the existing per-task try/except
  marks the task FAILED (= UNAVAILABLE). Partial failure never kills the run (spec §14).
- **Recovery** (`orchestrator._retry_failed_external`, spec §26): after the research loop, failed
  external tasks are retried **once** (bounded by `attempts`/`connectivity_max_retries`) **iff** a fresh
  `snapshot(force=True)` shows the provider healthy — reusing the previously-unwired `RETRYING` infra. A
  no-op when nothing failed (existing pipeline tests unaffected). Cross-run refresh is Research Again (#4).
- **Run health & disclosure** (`orchestrator._build_source_health`): live/cached/local (by provenance)
  + stale (by freshness, cross-cutting) + unavailable (failed external tasks) counts + a
  `research_health` label + connectivity snapshot, stored in the existing `report_meta["source_health"]`
  (no new column) and emitted over SSE. The report **deterministically discloses** cache/local/
  unavailable sourcing (`report._health_md`) **only when true** (spec §15). The diff detects
  `availability live → cached` etc. (`research_diff._diff_sources`). **Confidence is untouched** — no
  offline penalty; provenance is disclosed, not scored (spec §16, §19).
- **Frontend:** `lib/provenance.ts` (mapping), `ProvenancePill` on the Sources tab + claim evidence, a
  **Research Health** banner in the live view (quiet when fully-live), a connectivity pill in
  `SystemStatus`, and a source-policy picker in `NewResearch`. Config: `connectivity_*` / `source_cache_*`
  / `cache_ttl_*` / `default_source_policy`. Tests: `test_provenance.py`, `test_connectivity.py`,
  `test_source_cache.py`, `test_pipeline_connectivity.py`, `test_connectivity_security.py` + frontend
  `provenance.test.ts`, `ResearchHealthBanner.test.tsx`. Docs:
  `docs/CONNECTIVITY-INTELLIGENCE-{IMPLEMENTATION-PLAN,COMPLETION}.md`.

### Research Alerts + Continuous Monitoring (#6): evidence-aware watching, not generic alerts
ResearchMind remembers a completed investigation, watches it on a schedule, verifies **meaningful**
changes with the existing Diff engine, and notifies **only when what the user should believe has
changed** — never on search noise. Reuse-first: the only genuinely new pieces are a significance
engine and two small tables.
- **Monitor model** (`models/monitor.py`): `ResearchMonitor` (one per **lineage**, keyed by
  `root_id` from #4) holds cadence (`daily|weekly|monthly` → `interval_minutes`, floored by
  `min_schedule_interval_minutes`), `source_policy` (#5), `notify_policy` (`all|important|critical`),
  `last_run_id` (baseline), health counters, and a computed `health`
  (HEALTHY/DEGRADED/OFFLINE/FAILING/DISABLED). `MonitorCheck` is the immutable record of each check
  (found + suppressed changes, provenance_mode, source_health) — **monitoring history == research
  memory** (spec §26). Both tables are new (via `create_all`); no existing table is migrated.
- **Two-tier check** (`services/research_monitor.py:run_monitor_check`, spec §7, §25, §36): **Stage 1**
  is a cheap probe (`resilient_collect`, **no LLM**) that re-collects the baseline's top questions and
  compares source sets — a low-quality new source does **not** escalate; an authoritative/changed
  cited source does. **Stage 2** (only on escalation) forks a Research-Again `refresh` run (the only
  LLM-heavy step; awaited under a `monitor_max_concurrent_checks` semaphore), diffs it against the
  baseline with the **existing** `research_diff.diff_runs` (no `monitor_diff.py`, spec §24), and runs
  significance. Most scheduled checks stop cheaply at Stage 1.
- **Significance engine** (`services/significance.py`, spec §8, §10, §18): **deterministic** impact
  scoring over a `ResearchDiff` — recommendation reversal = CRITICAL, contradiction of a
  high-confidence claim = CRITICAL, major confidence drop = HIGH, bare new source = LOW noise. Every
  `Change` carries transparent reasons (never invented) + a **content-derived stable `dedup_key`** so
  the same change isn't re-notified across checks (spec §17). `meaningful = impact ≥ MEDIUM`;
  `notify_policy` sets the delivery threshold. 10 low-quality new sources → all suppressed; 1
  authoritative contradiction → CRITICAL alert.
- **Offline correctness** (spec §20): an *incomplete* external check (external unavailable, policy
  forbids cache) is recorded `degraded` + retried with backoff — **never** reported as "no changes".
- **Scheduler**: the existing in-process poller (`services/scheduler.py`) gained one call to
  `research_monitor.run_due_once()` — **no second scheduler** (§34). Restart-safe (monitors persist),
  concurrency-guarded (in-flight monitors skipped, LLM-heavy checks capped, stale-running reclaimed),
  bounded exponential backoff on failure (§22, §35).
- **Notifications**: reused. `Notification` gained nullable `severity`/`monitor_id`/`dedup_key`/`data`
  (via `_ADDED_COLUMNS`); a `monitor_alert` carries impact + a `data` pointer to the baseline→new-run
  diff. `notifications.notify()` extended (returns the id). In-app only — nothing leaves ResearchMind
  (§33, §40), no passages/secrets in payloads.
- **API** (`api/monitors.py`): `POST/GET/PATCH/DELETE /research/{id}/monitor`, `POST /monitor/run`
  (same pipeline, no duplicate schedule, §30), `GET /monitor/checks` (history). Ownership via
  `research._get_project` (404, no leak); one monitor per lineage (upsert). **Frontend**: `lib/
  monitoring.ts` (severity/health mapping), a **Monitoring tab** in `LiveResearch` ("Monitor this
  research" setup + status + recent checks → each links to the RunDiff), and severity chips + diff
  links in the notification center. Config: `monitor_*` settings. Tests: `test_significance.py`,
  `test_monitor_api.py`, `test_monitoring_pipeline.py`, `test_monitor_service.py`,
  `test_migration_monitoring.py` + frontend `monitoring.test.ts`, `MonitorCheckRow.test.tsx`. Docs:
  `docs/RESEARCH-MONITORING-{IMPLEMENTATION-PLAN,COMPLETION}.md`.

### Knowledge Graph + Temporal Knowledge (#7): an evidence-backed model of what is believed
A persistent, temporal entity graph layered **over** the existing substrate — never a parallel
knowledge system. The existing `knowledge/service.build_graph` (a per-project on-the-fly GraphTab
view) is untouched; #7 adds cross-run persisted entities/relationships.
- **Schema** (`models/graph.py`, four new tables via `create_all`, **no existing-table changes** —
  graph status rides in `report_meta`): `kg_entities` (normalized per-user-canonical; extensible
  string `entity_type` validated by `knowledge/registry.py`, so new types need no migration),
  `kg_relationships` (temporal entity↔entity: predicate, confidence, `provenance_kind`
  explicit/derived/inferred, `status` active/superseded/disputed/…, `valid_from/to`,
  `first/last_observed_at`, provenance ids), `kg_mentions` (polymorphic entity↔{claim,source,
  document,project} — connects **existing** rows, never duplicated), `kg_claim_links` (claim↔claim,
  `SUPERSEDES` etc.). All carry `user_id` (nullable → legacy/unowned).
- **Build** (`knowledge/graph.py:build_graph_for_project`, deterministic, **no LLM by default**,
  idempotent): entities from `Solution.name` + `Recommendation.recommended_option`; claim↔entity by
  normalized substring; entity↔source/run mentions; `ALTERNATIVE_TO` (co-considered solutions) +
  `RELATED_TO` (claim co-occurrence), all DERIVED. Conservative resolution
  (`_resolve_or_create_entity`) matches on `(user_id, normalized_name, entity_type)` and **never**
  merges by name similarity (`Apple` ≠ `Apple Inc.`). Optional Tier-2 LLM entity extraction
  (`kg_llm_extraction_enabled`, off; strict schema, INFERRED).
- **Temporal** (`reconcile_from_diff`, consumes the existing `research_diff.diff_runs` — no second
  diff engine): each new run's matching claim `SUPERSEDES` the prior → old becomes **historical**,
  new **current**; a CONTRADICTED claim marks its derived relationships **DISPUTED**. "Disputed" is
  **derived** from existing verification (`evidence_state`), not recomputed.
- **Integration**: hooked into `orchestrator._update_knowledge_graph` (after `_index_knowledge`,
  best-effort — a graph failure degrades `report_meta["graph_status"]`, never fails the run; retry via
  `POST /knowledge/graph/rebuild/{id}`). Research Again + Monitoring escalations fork a `refresh`
  child that runs `run_research`, so **all three integrations share one hook** (no second pipeline).
- **API** (`api/graph.py`, ownership-scoped `user_id == me OR NULL`, bounded/paginated):
  `GET /knowledge/entities` (search+type+pagination), `/entities/{id}` (detail+related+counts),
  `/entities/{id}/claims?scope=current|historical|all`, `/entities/{id}/graph?depth=1|2` (depth
  **hard-clamped ≤ 2**), `/entities/{id}/history`, `/relationships/{id}`, `POST /graph/rebuild/{id}`.
  **Frontend:** Knowledge page gains **Research + Entities** tabs; an **Entity detail** route
  (`/knowledge/entities/:id`) shows type/description/related entities/current-vs-historical claims
  (with evidence drill-down)/provenance. `lib/knowledgeGraph.ts` maps labels. Config: `kg_*` /
  `knowledge_graph_enabled`. Tests: `test_kg_{build,temporal,api,integration,migration}.py` + frontend
  `knowledgeGraph.test.ts`, `EntityDetail.test.tsx`. Docs:
  `docs/KNOWLEDGE-GRAPH-{PLAN,COMPLETION}.md`.

### API + MCP + Extensibility (#8): one capability layer, many thin adapters
ResearchMind's capabilities are consumed by the existing UI (humans), a versioned REST API
(programs), and MCP (AI agents) — all through **one capability layer**, never duplicated logic
(spec §1, §4, §55). The transport never changes research/evidence/provenance/security semantics.
- **Capability layer** (`app/capabilities/`): the single, transport-agnostic implementation of
  each capability (research start/status/report/claims/evidence/again/diff, documents, knowledge
  entity/graph/history, monitoring status/history, system health/connectivity/capabilities/
  version). Each function takes a resolved `User` + validated args, manages its own session,
  **enforces the existing ownership rule** (own or legacy-NULL; 404 no-leak), bounds output, and
  returns a plain dict. It **reuses existing services** (`research_service.manager`,
  `research_diff`, `knowledge.graph`, `research_monitor`, `connectivity`, `documents.service`)
  and the #7 `api/graph.py` / #6 `api/monitors.py` read helpers — no second engine/diff/graph.
  `base.py` has the stable error model (`CapabilityError` + machine codes), `resolve_user(token)`
  (mirrors `get_current_user` for MCP), a **capability registry** (discovery), and an in-memory
  bounded **idempotency store** (no migration).
- **REST `/v1`** (`app/api/v1.py`, 20 endpoints, additive — existing routes untouched so the
  frontend + all prior tests are unaffected): thin endpoints over capabilities, JWT auth, a
  structured **error envelope** (`{"error":{code,message,request_id}}` via a `CapabilityError`
  handler), **request IDs** (`RequestIdMiddleware`), **`Idempotency-Key`** on start/again,
  **202 + Location** for long-running research (reuses the background orchestrator — no second
  queue), pagination/limits, auto-OpenAPI.
- **MCP** (`app/mcp/`, **dependency-free** — the `mcp` pip SDK force-upgrades starlette/pydantic
  and breaks FastAPI, so it's a stdlib **JSON-RPC 2.0 stdio server** speaking the standard
  protocol; run `python -m app.mcp`): `initialize`/`tools/list`/`tools/call`/`resources`. **15
  tools** with strict schemas (`additionalProperties:false`) binding to capabilities; bounded
  structured results; `CapabilityError → isError` with a machine code; resources
  `research://{id}`, `research://{id}/claims`, `knowledge://entity/{id}[/history]`. Auth via
  `RESEARCHMIND_TOKEN` (or shared local user when `AUTH_ENABLED=false`). Tested at the protocol
  layer, incl. **REST↔MCP equivalence** and **cross-user isolation via MCP**.
- **Security**: no `read_file`/`fetch_url`/arbitrary-SQL/shell tools (asserted absent); malformed/
  traversal ids → 404/422; graph depth clamped; errors leak no stack/SQL/paths/secrets. **No
  migration, no new dependency.** Frontend: a read-only **Integrations** page (capability list +
  MCP setup, placeholder token). Config: `external_api_enabled`, `concurrent_research_limit`,
  `capability_*`, `idempotency_ttl_seconds`. Tests: `test_capabilities.py`, `test_v1_api.py`,
  `test_mcp.py`, `test_capability_security.py` + frontend `Integrations.test.tsx`. Docs:
  `docs/API-MCP-EXTENSIBILITY-{PLAN,COMPLETION}.md`.

### Research Quality Benchmark + Production Hardening (#9): a reproducible quality baseline
Milestone #9 added **no engine, no dependency, no migration** — it validates and hardens the existing
architecture. The **benchmark** (`benchmark/`, run `python -m benchmark.run_benchmark` from the repo
root) drives the **real** deterministic quality engines (`verification.score_claim`,
`freshness.freshness_state`, `provenance.*`, `research_diff._classify`, `significance.evaluate`,
`knowledge.graph.normalize_name` + resolution) against 30 machine-readable scenarios
(`benchmark/scenarios/*.json`, 10 categories) carrying ground truth, and scores structured outcomes
(claim accuracy, evidence support, citation correctness, contradiction detection, confidence
calibration ordering, freshness, provenance incl. a **no-false-live** hard gate, diff category,
significance impact, entity resolution). It is deterministic + offline (pins `OLLAMA_BASE_URL` to a
dead port), reimplements nothing, and its results land in `benchmark/results/latest.json`
(git-ignored, regenerable). Baseline: **30/30, all metrics 1.0** — the engines behave as specified. A
**negative control** proves the harness fails when ground truth is wrong (not rubber-stamping).
`tests/test_benchmark.py` runs it under pytest and asserts the thresholds so future milestones can't
silently regress quality. **Hardening fix (P1):** `clamp_page(-1,…)`/`api.graph.list_entities` produced
SQLite `LIMIT -1` (unbounded) — an external `/v1`/MCP client passing `?limit=-1` bypassed the page cap;
fixed at root (floor page size at 1) with regression tests. Docs:
`docs/RESEARCH-QUALITY-BENCHMARK-{PLAN,REPORT}.md`, `docs/PRODUCTION-HARDENING-COMPLETION.md`.

### Real-World Research Evaluation + Quality Improvement (#10): architecture value, measured
Milestone #10 evaluated whether the architecture actually produces better research — **no new
engine, no dependency, no migration**. The evaluation (`evaluation/`, run `python -m
evaluation.run_evaluation` from the repo root) compares **ResearchMind** (the REAL quality
engines composed as the pipeline composes them) against a **conventional one-shot LLM baseline**
(accept every claim, cite the first source, no contradiction/provenance/temporal handling) on the
**same** realistic fixture corpora — isolating architecture value from LLM quality. 18 claim-level
tasks (independent ground truth: `evaluation/tasks/*.json`) + 2 longitudinal product-value tasks,
scored at the **claim level** (§9): claim accuracy, evidence support, citation correctness (only
for claims the system asserts) + completeness, contradiction handling, temporal correctness,
confidence calibration, provenance + a **no-false-live** gate. Deterministic + offline; results in
`evaluation/results/latest.json` (git-ignored). **Result: ResearchMind 1.0 vs baseline 0.677**,
winning decisively on contradiction/provenance/no-false-live/temporal (+1.0 each) and claim
accuracy (+0.55); ties on completeness (baseline's is inflated by accepting unsupported claims);
costs more per-claim compute (the deliberate price of verification). The product-value loop is
shown **honestly**: Research-Again adds real value when evidence changed (new/contradicted claims,
recommendation reversal = CRITICAL) and **zero** on a pure repeat (noise suppressed).
**Quality fix (P2) found by the evaluation:** `verification.score_claim` flagged a claim OUTDATED
on a 1-fresh/1-stale tie (`outdated = stale_known >= (n+1)//2`) — a currently-true claim shown as
stale; fixed to a strict majority (`> len(known)/2`) with regression tests; RM overall 0.96→1.0,
#9 benchmark still 30/30. `tests/test_evaluation.py` asserts ResearchMind beats the baseline on the
architecture-differentiated metrics so the value can't silently regress. Honest limitation: this
measures architecture value on fixtures, **not** live-web collection quality. Docs:
`docs/REAL-WORLD-RESEARCH-EVALUATION-{PLAN,REPORT}.md`, `docs/RESEARCH-QUALITY-IMPROVEMENTS.md`.

### Report is assembled deterministically from structured data
The report LLM writes ONLY interpretive prose (Executive Summary / Key Findings / Detailed Analysis /
Knowledge Gaps). Everything decision-bearing is injected from stored rows so it stays evidence-
traceable and can't be softened (spec rules §23.2, §23.10):
- **Conflicting Information** ← `Conflict` rows.
- **Comparison / Recommendation / Why / Alternatives / Risks / PoC / Roadmap** ← `Solution` +
  `Recommendation` rows, produced by `rd_analysis.analyse()` in three constrained LLM stages
  (comparison → recommendation → delivery plan).
- **Sources / Research Confidence** ← `Source` + `Claim` aggregates.
When adding a report section, prefer this pattern (persist structured rows, render them in
`report._assemble`/`_rd_md`) over asking the narrative LLM for it.

**Locked-in choices:** LLM = local **Ollama** (`app/llm/`), search is **provider-selectable**
(`app/search/`, `SEARCH_PROVIDER`): **Tavily** (managed, needs key) or **SearXNG** (free, self-hosted,
no key) for web/docs/news/community; **GitHub REST API** and **arXiv API** for the other two; infra =
**lean local** (SQLite + in-process asyncio tasks + in-process SSE bus). No Docker/Postgres/Redis/Qdrant
required — they slot in behind existing interfaces.

**Search backend seam:** `app/search/factory.py:get_search_client(settings)` returns the client for
`settings.search_provider` — both `TavilyClient` and `SearxngClient` expose the same
`search(query, *, max_results, topic, days, time_range, include_domains) -> list[SearchResult]`, so the
orchestrator/agents are backend-agnostic (the orchestrator var is still named `tavily` but holds either).
SearXNG returns snippets only, so `SearxngClient` optionally enriches the top results by fetching each
page via the SSRF-safe `net.safe_get` and extracting text (`_html_to_text`), and normalizes SearXNG's
multi-engine scores to 0–1 to match Tavily's contract. It maps `topic="news"→categories=news`,
`days/time_range→time_range` buckets, and `include_domains→site:` operators. Add a backend by
implementing `search(...)` + a branch in the factory.

**Deviation from the spec worth knowing:** orchestration is a **custom DB-persisted async
orchestrator** (`app/orchestration/orchestrator.py`), not LangGraph. Satisfies the spec's "real
stateful multi-agent" requirement (§19, §23.1-3) with fewer moving parts; stages are explicit and
portable to a graph engine later.

### How the multi-agent dispatch works
- All collection agents return a uniform `CollectedSource` (`app/agents/common.py`); persistence,
  verification, and reporting are **source-agnostic**.
- `app/agents/dispatch.py` maps a task's source key (`web|docs|github|papers|news|community`) to the
  right agent's `collect(...)`. Web/docs/news/community share `tavily_agents.py`; GitHub and arXiv are
  their own modules.
- The orchestrator's `SOURCE_QUESTION_BUDGET` + `SOURCE_ORDER` decide how many top-priority questions
  each source researches, filling the global `MAX_RESEARCH_TASKS` budget web-first so it's never starved.
- **To add a source agent:** implement `collect(...)` returning `CollectedSource`, add a branch in
  `dispatch.py`, add it to `SOURCE_QUESTION_BUDGET`/`SOURCE_ORDER` and the frontend `SOURCES` list.
  Nothing else changes.

**Authentication (Phase 7, done):** JWT bearer auth with bcrypt password hashing. `app/models/user.py`
(`User`), `app/security/auth.py` (`hash_password`/`verify_password`, `create_access_token`/
`decode_token`, `get_current_user` dependency), `app/api/auth.py` (`POST /auth/register`, `POST
/auth/login`, `GET /auth/me`). Projects carry a nullable `user_id` (owner); `research.py`'s
`_get_project(db, id, user)` enforces ownership (returns **404** — not 403 — for another user's id so
existence isn't leaked), and list is scoped to `user_id == me OR user_id IS NULL`. **Legacy/unowned
projects (`user_id IS NULL`, created before auth) are readable by any authenticated user** — a
deliberate personal-tool compromise. Knowledge + monitoring routers require login (router-level
`dependencies=[Depends(get_current_user)]`) but are not per-user scoped. The **SSE stream** and
**export** endpoints accept the JWT as a `?token=` query param (browser `EventSource`/download links
can't set an Authorization header) via `_authenticate_query_token`. `AUTH_ENABLED=false` runs the API
as a shared "local" user (no login) for a single-user offline setup; the first registered account
becomes admin. **Frontend:** `auth/AuthContext.tsx` (token in `localStorage`, boot-time `/auth/me`
validation, `auth:unauthorized` event on any 401), `pages/Login.tsx` (login/register toggle),
`RequireAuth` route guard in `App.tsx`, account + logout in `Layout.tsx`; `api/client.ts` attaches the
bearer header and threads the token into stream/export URLs.

**Market Intelligence mode (`ResearchMode.MARKET` = "market"):** a recency-biased "what's happening in
the market right now" run. `orchestrator.run_research` reads `proj.mode`; when MARKET it computes
`recency_days = settings.market_recency_days` (default 180) and an `as_of` date, passes `market=True` +
`as_of` to `planner.make_plan` (uses `_MARKET_SYSTEM` → current-state questions with recency-framed
search queries), and threads `recency_days` → `_run_tasks` → `dispatch.collect` → `tavily_agents.collect`.
There, recency maps to Tavily params: **news** tightens `days=recency_days`; **web/docs/community** use
`time_range` buckets via `_time_range_for` (≤1 day/≤7 week/≤31 month/else year). `TavilyClient.search`
gained a `time_range` param. The report switches to a market layout: `report.generate_report` keys on
`ReportInput.mode == "market"` → `_MARKET_SECTIONS` (Market Snapshot / Current State & Key Players /
Recent Developments / Trends & Outlook / Knowledge Gaps) + `_MARKET_SYSTEM_EXTRA` (strict grounding:
report only what recent sources support, attribute time-sensitive claims to publish dates, no stale
prior knowledge) + a dated "Market snapshot as of <as_of>" header. Frontend: mode in `NewResearch`/
`Scheduled` pickers; picking Market auto-selects Web+News. Tests: `test_market_mode.py`.

**Scheduled research + notifications (Phase 7, done):** `app/models/schedule.py` (`ScheduledResearch`:
interval/once cadence, `next_run_at`) and `app/models/notification.py` (`Notification`, user-scoped).
`app/services/scheduler.py` runs a single in-process asyncio poller (`SchedulerService`, started/stopped
in `main.py` lifespan) that every `SCHEDULER_POLL_SECONDS` calls `run_due_once()` → for each due enabled
schedule, `_create_and_start(advance_cadence=True)` spawns a real `ResearchProject` (owned by the
schedule's user) via `manager.start`, advances/disables the cadence, and notifies. `_spawn_from_schedule`
(used by `POST /schedules/{id}/run-now`) starts a run **without** touching the cadence. Interval floored
by `MIN_SCHEDULE_INTERVAL_MINUTES`. `app/services/notifications.py` `notify(...)` (self-contained
session, never breaks a run, like `audit`) is fired from the orchestrator on COMPLETED/FAILED. APIs:
`app/api/schedules.py` (CRUD + run-now, user-scoped) and `app/api/notifications.py` (list/unread-count/
mark-read/read-all/delete). **Frontend:** `pages/Scheduled.tsx`, `pages/Notifications.tsx`, sidebar nav
+ polled unread badge in `Layout.tsx`. Tests drive the scheduler deterministically via `run_due_once()`
(`SCHEDULER_ENABLED=false` in conftest so the loop doesn't run).

Not yet built (remaining Phase 7): the **Postgres/Redis** swap (SQLite → Postgres, in-process SSE bus →
Redis pub/sub, in-process scheduler → Redis/Celery beat — all already behind seams). `net.validate_url`
exists as the SSRF control for any new outbound-fetch path — route new fetches through it. A pytest suite
(`backend/tests/`, 337 tests) covers units, API, middleware, auth + access control, schedules,
notifications, the evidence engine (freshness, scoring, contradiction agent, evidence API),
Document RAG (parsing, chunking, upload security, service, documents API, offline+hybrid pipeline),
research memory/again/diff (diff engine, lineage, immutability, carry-forward, migration),
connectivity intelligence (provenance, connectivity states, source cache + isolation, resilient
collect, live/offline/hybrid/fallback/recovery pipeline), research monitoring (significance impact +
suppression, monitor scheduling/backoff/concurrency/restart, two-tier pipeline no-change/escalate/
dedup/degraded, isolation, migration), knowledge graph (entity extraction/resolution/dedup,
relationships, temporal supersession/disputed, research+again+diff+monitoring integration, offline
Tier-1, failure isolation+retry, cross-user isolation, API pagination/depth-clamp, migration), and the
capability layer (transport-agnostic capabilities, REST /v1 adapter incl. error envelope/request-id/
idempotency/pagination, MCP protocol incl. discovery/call/error-mapping/bounded/offline/REST↔MCP
equivalence, cross-user + no-dangerous-tool security), production hardening (`test_hardening.py`:
pagination-bounds regression, offline-suite guard, embedding/graph failure injection, DB integrity,
CPU/Ollama Stage-1-no-LLM budget, full-lifecycle + REST/MCP external E2E) and the **research-quality
benchmark** (`test_benchmark.py` asserts the benchmark's thresholds so quality can't silently regress),
and the full faked pipeline — run it before and after changes (see Commands). The **frontend** now also has a Vitest suite (`frontend/`, `npm test`, 50
tests: evidence + provenance + monitoring + knowledge-graph mapping, `ClaimsTab` + `DocumentsPanel` DOM
behavior, RunDiff + History lineage + LineageBar, Research Health banner, MonitorCheckRow drill-down,
EntityDetail, Integrations).

## Intended Architecture

ResearchMind AI is an autonomous multi-agent research system: a user submits a natural-language
research request and the system plans, executes parallel research across source types, verifies claims,
detects conflicts, fills knowledge gaps via automatic follow-up, and produces an evidence-traceable
R&D report. It is **not** a chatbot wrapper — see the non-negotiable rules below.

### Stack (current)
- **Frontend:** React + TypeScript + Vite + Tailwind — `frontend/` (shadcn/ui planned, not yet added)
- **Backend:** Python + FastAPI + Pydantic v2 + async SQLAlchemy 2.0 — `backend/app/`
- **Agent orchestration:** custom DB-persisted async orchestrator in `backend/app/orchestration/`
  (LangGraph is the eventual target if a graph engine is needed; the stages are already explicit)
- **LLM:** provider abstraction (`app/llm/base.py`) over Ollama (`ollama_provider.py`); OpenAI/Anthropic
  are added by subclassing `AIProvider` and registering in `factory.py` — never hardcode a model
- **Search:** `app/search/` — `factory.get_search_client()` selects `tavily_client.py` (managed) or
  `searxng_client.py` (free/self-hosted) via `SEARCH_PROVIDER`; both share the `SearchResult` contract
- **Datastores now:** SQLite (`app/database.py`), in-process SSE bus (`app/services/events.py`).
  **Planned:** PostgreSQL, Qdrant (vector memory), Redis (cache + queue) — behind the same seams

### The research pipeline (the core loop)
Understand intent → **Research Planner** generates questions + plan → create research tasks →
**parallel research agents** collect sources → extract content → dedupe → score source reliability →
verify claims → detect conflicts → **knowledge-gap analysis → if gaps, spawn follow-up tasks and loop** →
R&D analysis → solution comparison → recommendations → final report.

The follow-up loop is a defining feature. It continues until all critical questions are answered, OR
max depth/source/task budget is hit, OR no new meaningful information appears.

### Agents (each is a real stateful component, not just a prompt)
Agents live as focused modules in `backend/app/agents/`: collection agents (`tavily_agents.py` for
web/docs/news/community, `github_research.py`, `academic_research.py`) plus reasoning agents
(`planner.py`, `verification.py`, `gap_analysis.py`, `report.py`) and the `dispatch.py` router. They are
**stateless reasoning/collection units**; the orchestrator (`app/orchestration/orchestrator.py`) owns
state and persistence and plays the "Research Manager" role. Collection (search/API) is deliberately
separate from reasoning (LLM extraction). Still to come as its own agent: standalone conflict detection
and R&D analysis — follow the same module shape and the dispatch pattern above.

### State, persistence, and tasks
Research state survives server restart, pause, task failure, and the user returning later — it lives in
SQLite, written continuously as the run progresses. Tasks carry the status lifecycle
(`PENDING/QUEUED/RUNNING/COMPLETED/FAILED/RETRYING/PAUSED/CANCELLED`, `app/models/enums.py`); a failed
task marks itself FAILED without aborting the run. Runs execute as in-process asyncio tasks managed by
`app/services/research_service.py` (`RunManager`), with pause/resume/cancel via
`app/orchestration/control.py`. Live activity is pushed over **SSE** (`GET /research/{id}/stream`) from
the in-process event bus. Concurrent SQLite writes are serialized by a module-level lock in the
orchestrator — keep that in mind before parallelizing DB writes further.

## Non-Negotiable Rules (from spec §23)

These constrain every design decision and are easy to violate accidentally:

1. **Real multi-agent system** — do not build agents that are only prompts with no structured task
   objects or persistent state. Separate research *collection* from AI *reasoning*.
2. **Evidence traceability** — every major recommendation must trace back to verified evidence. Never
   invent facts or sources. Preserve every source URL and its metadata.
3. **Never trust a single source** for important claims; prefer primary/authoritative sources; apply the
   source-reliability scores (spec §5) and claim statuses `VERIFIED/PARTIALLY_VERIFIED/CONFLICTED/UNVERIFIED/INSUFFICIENT_EVIDENCE` (§6).
4. **Never hide conflicts** — surface unresolved contradictions in the report (§7).
5. **Automatic follow-up** on critical knowledge gaps is required behavior, not optional (§8).
6. **Provider-agnostic** — no tight coupling to one LLM. All providers implement
   `generate() / stream() / structured_output() / health_check() / list_models()` (§22).
7. Support **cancellation and resumption** of in-flight research.
8. Show uncertainty honestly; revalidate reused knowledge-base entries when freshness matters.

## Data & API Contracts

The relational schema (spec §17) and REST surface (§16) are specified in the master prompt — treat them
as the contract. Notable endpoints follow `POST /research`, `POST /research/{id}/{start|pause|resume|stop}`,
`GET /research/{id}/{plan|questions|tasks|sources|findings|claims|conflicts|recommendations|report}`,
and `knowledge/{search|related|save}`. All major tables carry `id/created_at/updated_at`. Real-time
progress ships over WebSocket/SSE, not polling.

## Commands

**Backend** (from `backend/`, venv at `backend/.venv`):
```bash
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt   # Windows path; POSIX: .venv/bin/python
cp .env.example .env                                       # set TAVILY_API_KEY, OLLAMA_MODEL
.venv/Scripts/python -m uvicorn app.main:app --reload --port 8000
```
- API docs `http://localhost:8000/docs`; health `http://localhost:8000/health` (checks Ollama + Tavily).
- Tables auto-create on startup (`init_db()` in `app/database.py`) — no migrations yet; columns
  added to existing tables are applied by the idempotent `_ensure_columns` ALTER (see `_ADDED_COLUMNS`).
- **MCP server:** `.venv/Scripts/python -m app.mcp` (stdio JSON-RPC; auth via `RESEARCHMIND_TOKEN`,
  or the shared local user when `AUTH_ENABLED=false`). External REST API is `/v1/*` (OpenAPI at `/docs`).
- **Research-quality benchmark (#9):** from the **repo root**, `backend/.venv/Scripts/python -m
  benchmark.run_benchmark` (deterministic, offline; writes `benchmark/results/latest.json`). It's also
  asserted under pytest by `tests/test_benchmark.py`, so a quality regression turns the suite red.
- **Real-world evaluation (#10):** from the **repo root**, `backend/.venv/Scripts/python -m
  evaluation.run_evaluation` (deterministic, offline; ResearchMind vs a conventional baseline over
  fixture tasks; writes `evaluation/results/latest.json`). Asserted under pytest by
  `tests/test_evaluation.py` (ResearchMind must keep beating the baseline on the differentiated metrics).
- **Tests:** `pip install -r requirements-dev.txt` then `.venv/Scripts/python -m pytest` (337 tests,
  ~135s, all offline). Config in `pytest.ini` (`asyncio_mode=auto`). `tests/conftest.py` binds an
  isolated temp SQLite DB + Qdrant path via env before app import (incl. `AUTH_ENABLED=true` +
  `JWT_SECRET`), and provides fixtures: `client` (ASGI, **auto-registers a user and attaches its bearer
  token** — auth is enforced in the suite), `anon_client` (no credentials, for 401/isolation tests),
  `db`, `reset_db` (per-test schema recreate), `FakeProvider` (schema-branching fake LLM + fake
  embeddings), and `patch_pipeline` (runs the whole pipeline with no network). `register_user(client,
  ...)` helper mints extra accounts. Run one file: `pytest tests/test_pipeline.py`; one test:
  `pytest tests/test_dedup.py::test_normalize_url_collapses_variants`. Note: the orchestrator's
  module-level `_db_lock` is rebound per test in `patch_pipeline` because pytest-asyncio uses a fresh
  event loop per test.

**Frontend** (from `frontend/`):
```bash
npm install
npm run dev      # http://localhost:5173, proxies /api -> :8000 (see vite.config.ts)
npm run build    # tsc --noEmit type-check + vite production build
npm test         # Vitest suite (evidence mapping + ClaimsTab behavior)
```

**Prereqs to actually run research:** Ollama running locally with a model pulled
(`ollama pull llama3.1:8b`) and a Tavily API key in `backend/.env`. Without them the app boots and the
UI works, but a run will fail at the planning/search step with a clear error.

## Security Baseline (spec §21)

Auth with JWT/secure sessions, password hashing, encrypted API keys (never exposed to the frontend),
config via environment variables, rate limiting, input + URL validation, **SSRF protection** (the system
fetches arbitrary user-influenced URLs — this is a primary attack surface), access control, audit logging.

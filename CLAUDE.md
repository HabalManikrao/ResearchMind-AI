# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Current State: Phase 1–6 complete; Phase 7 near-complete (only Postgres/Redis swap left)

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
(`backend/tests/`, 152 tests) covers units, API, middleware, auth + access control, schedules,
notifications, the evidence engine (freshness, scoring, contradiction agent, evidence API),
Document RAG (parsing, chunking, upload security, service, documents API, offline+hybrid pipeline),
and the full faked pipeline — run it before and after changes (see Commands). The **frontend** now
also has a Vitest suite (`frontend/`, `npm test`, 13 tests: evidence mapping, `ClaimsTab` +
`DocumentsPanel` DOM behavior).

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
- **Tests:** `pip install -r requirements-dev.txt` then `.venv/Scripts/python -m pytest` (152 tests,
  ~127s, all offline). Config in `pytest.ini` (`asyncio_mode=auto`). `tests/conftest.py` binds an
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

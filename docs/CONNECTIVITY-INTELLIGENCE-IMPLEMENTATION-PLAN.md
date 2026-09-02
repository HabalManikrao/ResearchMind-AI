# Connectivity Intelligence + Live/Cached/Local Research (#5) — Implementation Plan

_Pre-implementation design, grounded in a full audit of the current code (spec §1, §2). The
principle: **source-aware research resilience**, not an online/offline toggle. ResearchMind must stay
useful when the internet disappears, honest when evidence is stale, transparent when sources are
cached, and automatically prefer live evidence when it is genuinely available._

---

## 0. TL;DR — the decisions

1. **Provenance rides on `Source.meta`, not a new column.** A source already carries `meta` (JSON),
   `created_at` (retrieved-at), and `published_date` (published-at). We stamp `meta["provenance"]`
   (`live_web`/`cached_web`/`local_document`/`local_memory`) + `meta["retrieved_at"]` at collection
   time and expose computed `Source.provenance` / `Source.availability` properties — exactly like the
   existing computed `Source.freshness`. Zero migration for provenance.
2. **A run's source policy is one nullable column** (`research_projects.source_policy`), applied by the
   existing `_ensure_columns` ALTER — same additive/idempotent pattern as #4's lineage columns.
3. **The web cache is genuinely new** (nothing caches web content today) → one new table
   `cached_sources`, **project- and user-scoped** for hard isolation (§30). Created by `create_all`.
   Query-level: keyed by `(project_id, source_type, query_hash, url)`, TTL by source type.
4. **Connectivity is layered and on-demand-cached, not a poller.** New `services/connectivity.py`
   reuses `provider.health_check`, cheap HTTPS HEAD probes of the hosts we already call, and a Qdrant/DB
   check. Snapshot cached for `connectivity_cache_seconds`. A tiny previous-state memory yields the
   `RECOVERING` transition without any background traffic (§27, §32).
5. **Resilience is a source-agnostic wrapper**, not per-agent edits. New `services/collection.py`
   `resilient_collect(...)` wraps `dispatch.collect`: live → stamp `live_web` + cache; live-fails →
   (policy-permitting) serve `cached_web`; local agents (`documents`) are already offline. The
   orchestrator's existing per-task try/except already gives partial-failure resilience (§14) — we
   build on it, we don't replace it.
6. **Recovery reuses the existing (currently unwired) task-retry infra.** After the research loop, if
   external tasks FAILED and a *fresh* connectivity probe shows the provider healthy, re-queue them
   once (bounded by `attempts`). Cross-run refresh of stale/unavailable evidence is **Research Again**
   (#4), which already exists — we make its `refresh` intent provenance-aware.
7. **Run health is computed into the existing `report_meta` JSON**, not a new column: live/cached/
   local/stale/unavailable counts + a `research_health` label + a `connectivity` snapshot. Surfaced in
   the report (deterministic disclosure, only when true — §15), SSE, and UI.
8. **Confidence is untouched** (§16, §19): no offline penalty. Provenance is *disclosed*, not scored.
   An authoritative local document already outscores a low-quality blog via `reliability_score`.

---

## 1. Audit of the existing system (§1)

| Concern | What exists today | Reuse / gap |
|---|---|---|
| Connectivity checks | `/health` (`api/system.py`): Ollama `health_check()`, `embeddings_available()`, search **configured** (key/URL present, *not* reachable). `net.validate_url` resolves DNS as an SSRF side-effect. `OllamaProvider.health_check` GETs `/api/tags`. | Reuse the local probes. **Gap:** no layered model, no external reachability, no caching, no states. |
| Caches | **None for web content.** Local evidence only: Qdrant `knowledge`+`documents`, `memory_summary`, #4 prior-context. | **Gap:** a bounded web cache is new. Local stores = the LOCAL provenance path. |
| Source timestamps | `Source.created_at`/`updated_at` (retrieved), `Source.published_date` (published). `freshness` computed from published_date, domain-aware thresholds. | Reuse: the retrieved-vs-published distinction already exists (§3 “uploaded today ≠ published today”). |
| Source metadata | `Source.meta` (JSON) — already per-type (`contradiction:True`, github stars, doc `page_number`). | Reuse as the provenance carrier. No new column. |
| Failure handling | `_run_tasks.worker` try/excepts each task → `FAILED`, emits activity, **continues**. Contradiction search is a non-gate. Search clients raise `SearchError`; agents catch extraction errors. | Reuse — **partial-failure resilience already exists** (§14). Build fallback on top. |
| Retry | `ResearchTask.attempts` + `TaskStatus.RETRYING` exist but the orchestrator **never retries**. Ollama retries transient net errors (not timeouts). | **Gap:** wire a bounded one-shot retry for recovery (§26). |
| Offline behavior | `documents` agent is fully local (Qdrant+Ollama, zero network). `sources_enabled=["documents"]` = offline run. | Reuse as LOCAL_ONLY. **Gap:** no *automatic* fallback web→local/cache. |
| Config | timeouts hardcoded in clients; `allow_private_fetch`; search settings. | **Gap:** centralize connectivity/cache/retry/policy config (§29). |
| Frontend status | `SystemStatus.tsx` + `useHealth` poll `/health` (LLM/search/embeddings pills). Sources tab + claim-evidence render `FreshnessPill`/`ReliabilityPill`/`SourceTypeBadge`. | Reuse the pill pattern for provenance badges; extend SystemStatus for connectivity. |

**Reuse-first conclusion:** the only genuinely new infrastructure is (a) the connectivity manager,
(b) the web cache table + service, and (c) the resilient-collect wrapper. Everything else extends an
existing seam (`meta`, `report_meta`, `_ensure_columns`, the per-task try/except, Research Again,
`_ADDED_COLUMNS`, the freshness-pill UI).

---

## 2. Core model (§3, §7, §8)

**Provenance** — where a persisted piece of evidence came from (`services/provenance.py`):
`LIVE_WEB`, `CACHED_WEB`, `LOCAL_DOCUMENT`, `LOCAL_MEMORY`, `LOCAL_DATABASE`.

**Availability** — the display state derived from provenance + freshness:
`LIVE`, `CACHED`, `LOCAL`, `STALE`, `UNAVAILABLE`, `UNKNOWN`.

Derivation (`availability_of(provenance, freshness)`):
- `freshness == "stale"` → `STALE` (evidence exists but exceeds its freshness threshold — §3).
- else `cached_web` → `CACHED`; `local_*` → `LOCAL`; `live_web` → `LIVE`; unknown provenance → `UNKNOWN`.

**`UNAVAILABLE` is deliberately not a persisted-Source state.** A persisted `Source` is evidence we
actually hold; a source that could not be fetched has no row. `UNAVAILABLE` is therefore counted at the
**run-health** level (failed external tasks), which is the honest representation and avoids inventing
phantom source rows (§34: never claim coverage we don't have).

**LIVE correctness (§8, §34):** a source is `live_web` **only** when `dispatch.collect` actually
returned it from an external provider *during this run*. A cache hit is `cached_web`. A URL, a healthy
domain, or “internet is up” never makes something live.

---

## 3. Connectivity manager (§4, §5, §6, §28)

`services/connectivity.py` — layered, bounded, cached; **no aggressive polling**.

Layers (each a small monkeypatchable async probe, short timeout `connectivity_timeout_seconds` ≈ 3s):
- **internet** — HTTPS HEAD to the hosts we already use (search-provider host, `api.github.com`,
  `export.arxiv.org`); reachable if *any* responds (§5: not one hard-coded site, not ICMP).
- **search_provider** — SearXNG: GET base_url; Tavily: HEAD `api.tavily.com` + key-configured.
- **ollama** — `provider.health_check()`.
- **qdrant** — `vector_store.get_client().get_collections()` in a thread (bounded).
- **database** — `SELECT 1`.

`snapshot()` returns `ConnectivitySnapshot(overall, internet, search_provider, ollama, qdrant,
database, checked_at)` and is **cached** for `connectivity_cache_seconds` (default 60). `overall`:
- `ONLINE` (internet + provider ok), `DEGRADED` (internet ok, provider or a source down),
  `OFFLINE`/`LOCAL_ONLY` (no internet but Ollama+Qdrant ok → local research still works),
  `UNKNOWN` (can’t tell). `RECOVERING` is emitted for one snapshot when a fresh probe flips a cached
  `OFFLINE/DEGRADED` back to healthy (previous-state memory — no poller).

`research_mode_for(snapshot, policy)` → `live` | `hybrid` | `cache` | `local` — the effective mode.

---

## 4. Source cache (§9, §10, §11, §30)

New table `cached_sources` (`models/cache.py`), created by `create_all`:
`id, project_id (idx), user_id, source_type, query_hash (idx), url, title, content, summary,
published_date, reliability_score, relevance_score, checksum (sha256 of content), meta (JSON),
retrieved_at, created_at`. **No headers, keys, cookies, or auth data are ever stored (§30).**

`services/source_cache.py`:
- `put(project_id, user_id, source_type, query, sources)` — replace prior rows for the key, insert one
  row per `CollectedSource` (checksum = sha256(content)).
- `get(project_id, source_type, query)` — return the freshest cached set **within TTL** for the type,
  or `[]`. Reconstructs `CollectedSource` with `meta["provenance"]="cached_web"`,
  `meta["cached_at"]`, `meta["cache_age_seconds"]`.
- **Isolation (§30):** every query filters by `project_id`; a re-run’s carried policy never crosses
  projects; a cross-project `get` returns nothing. Tested.

TTL by type (`cache_ttl_for(source_type)` from config, §10/§29): news short, community/web/docs medium,
github medium, papers/documents long. Centralized — no scattered literals.

---

## 5. Policy + fallback (§11, §12, §13, §15)

`SourcePolicy` (str enum): `LIVE_ONLY`, `LIVE_PREFERRED` (default), `CACHE_ALLOWED`, `LOCAL_ONLY`.
Stored in nullable `research_projects.source_policy` (resolved to `LIVE_PREFERRED` when null).

`services/collection.py::resilient_collect(agent, ..., policy, allow_cache)`:
- `documents` (local) → always run; stamp `local_document`. Never cached/failed.
- external agent:
  - `LOCAL_ONLY` → skip external entirely (return `[]`, mode local).
  - try live → success: stamp `live_web` + `retrieved_at`; if policy ≠ `LIVE_ONLY`, `source_cache.put`.
  - live fails: `LIVE_ONLY` → re-raise (task FAILED, honest); else `source_cache.get` → if hit, stamp
    `cached_web` (task COMPLETED, degraded); else re-raise (FAILED → counts as UNAVAILABLE).

Orchestrator: take a snapshot before dispatch; thread `policy` + `allow_cache` into the worker via
`resilient_collect`. Existing per-task try/except stays (partial failure §14). No entire-run abort for
one failed source (§13).

---

## 6. Recovery (§26)

Reuse the unwired retry infra. After the research+followup loop, `_retry_failed_external(...)`:
if any external task is `FAILED` **and** a fresh `connectivity.snapshot(force=True)` shows internet +
provider healthy, re-queue those tasks once (`attempts < connectivity_max_retries`, status→PENDING) and
run one more `_run_tasks`. Historical evidence untouched (§26). No-op when nothing failed (so existing
pipeline tests are unaffected). Cross-run refresh = **Research Again** (§20), already implemented.

---

## 7. Run health + report disclosure (§14, §15, §22, §23, §40)

At completion, `_build_source_health(project_id, snapshot, failed_external)` computes:
`{live, cached, local, stale, unavailable, provider_failures, retry_count, connectivity_state,
research_mode, research_health}` where `research_health ∈ {fully_live, partially_degraded,
cache_assisted, local_only, external_unavailable}`. Stored in `report_meta["source_health"]`;
emitted as an SSE `activity`; exposed on `ProjectDetail`/report.

**Deterministic report disclosure** (§15, §23.10 — only when true): the report assembler injects a
short *Research Health* note when `research_mode != live` or `unavailable > 0` (e.g. “Some external
sources were unavailable; findings rely partly on cached/local evidence.”). Never fabricated.

---

## 8. Research Diff integration (§21)

Extend `research_diff._diff_sources`: matched sources compare `provenance`/`availability`
(`live → cached`, `cached → live` = refreshed, `→ unavailable`), producing reasons like
`availability live → cached`. Timestamp-only jitter is **not** a change (§21). Reasons are built from
actual provenance fields, never invented (consistent with #4’s `confidence_meta` rule).

---

## 9. API (§37)

- `GET /system/connectivity` → `{overall_status, internet, providers, local_services, last_checked,
  research_mode}`. No secrets/internal network detail (§37).
- Extend `/health` `agents` with reachability where cheap.
- `SourceOut` + `ClaimEvidenceItem` gain computed `provenance` + `availability`.
- `ProjectDetail.report_meta` already carries `source_health` (no schema change).
- `ResearchCreate` gains optional `source_policy`.

---

## 10. Frontend (§17, §18, §22, §38)

- `lib/provenance.ts` — provenance/availability → label/badge (mirrors `lib/evidence.ts`), unit-tested.
- Sources tab + claim-evidence: a `ProvenancePill` beside the existing freshness pill (🟢 Live / 🔵
  Cached / 📄 Local / 🟡 Stale). Reuse, don’t duplicate indicators (§17).
- A **Research Health** banner (fully-live / cache-assisted / local-only / degraded) on the live/report
  view, from `report_meta.source_health`.
- `SystemStatus`: add a connectivity pill from `/system/connectivity`. Not a network dashboard (§38).
- `NewResearch`: a minimal source-policy select (Live preferred / Live only / Cache allowed / Local
  only) — the useful minimum (§11).

---

## 11. Configuration (§29)

`connectivity_timeout_seconds=3`, `connectivity_cache_seconds=60`, `connectivity_enabled=true`,
`connectivity_max_retries=1`, `source_cache_enabled=true`, `default_source_policy="live_preferred"`,
`cache_ttl_news_minutes`, `cache_ttl_web_minutes`, `cache_ttl_docs_minutes`,
`cache_ttl_github_minutes`, `cache_ttl_papers_minutes`, `cache_ttl_documents_minutes`. Safe defaults;
no user is required to set any (§29).

---

## 12. Database changes (§36)

- **New table** `cached_sources` (via `create_all`).
- **New nullable column** `research_projects.source_policy` (via `_ensure_columns`; add to
  `_ADDED_COLUMNS`). Additive, idempotent, non-destructive, backward compatible; startup runs twice in
  the migration test; existing research untouched. Provenance/run-health need **no** columns (they live
  in `Source.meta` / `report_meta`).

---

## 13. Testing strategy (§33, §44)

New `tests/`: `test_connectivity.py` (online/offline/degraded/recovery/timeout/DNS/provider-fail — all
via monkeypatched probes), `test_source_cache.py` (hit/miss/expired/disabled/duplicate/checksum/
isolation), `test_provenance.py` (live/cached/local/stale/unknown derivation + `resilient_collect`
live→cache fallback + LIVE_ONLY/LOCAL_ONLY), `test_pipeline_connectivity.py` (live/offline/hybrid/
partial-outage/fallback/recovery via `patch_pipeline`-style fakes), `test_connectivity_security.py`
(cross-project/user cache isolation). Extend `test_research_diff.py` with provenance-change cases.
Frontend: `provenance.test.ts` + a ProvenancePill render test. **All existing tests stay green.**

---

## 14. Non-goals (§42)

OCR, crawling, autonomous monitoring/alerts, MCP, enterprise connectors, browser automation, KG
redesign, advanced/semantic/distributed cache, multi-user collaboration. Out of scope.

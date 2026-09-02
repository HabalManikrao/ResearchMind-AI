# Connectivity Intelligence + Live/Cached/Local Research (#5) — Completion Report

_Completed: 2026-09-01. Source-aware research resilience: ResearchMind now knows the
availability/freshness state of every source, gracefully switches between live, cached, and
local evidence, and never represents stale/local information as live. Plan:
`docs/CONNECTIVITY-INTELLIGENCE-IMPLEMENTATION-PLAN.md`._

---

## Final Validation Report

```
Connectivity Intelligence: READY
Live Source Detection:     READY
Cached Sources:            READY
Local Sources:             READY
Offline Research:          READY
Hybrid Research:           READY
Fallback:                  READY
Recovery:                  READY
Evidence Provenance:       READY
Research Again Integration:READY
Research Diff Integration: READY
Security:                  READY
Performance:               READY
Migration:                 READY
```

- **Backend tests:** 213 passed, 0 failed (`pytest`, all offline) — was 175; **+38**
  (11 provenance/resilient-collect, 8 source cache, 9 connectivity + API, 6 pipeline
  connectivity, 2 security isolation, 2 diff provenance; +1 migration assertion, no new count).
- **Frontend tests:** 31 passed, 0 failed (`vitest`) — was 20; **+11** (7 provenance mapping,
  4 Research Health banner).
- **Build:** `npm run build` OK (`tsc --noEmit` clean + vite build, 1854 modules).
- **Migration:** additive/idempotent/non-destructive — one new nullable column
  (`research_projects.source_policy`) via `_ensure_columns`, one new table (`cached_sources`)
  via `create_all`; verified by `test_migration_lineage.py` (old-shape DB → migrate twice →
  columns present, data intact). Provenance & run-health need **no** columns (they ride on
  `Source.meta` / `report_meta`).

---

## The core principle, enforced

> Cached/local evidence is **never** labelled live. A source is `live_web` **only** when
> `dispatch.collect` actually returned it from an external provider during the current run
> (`resilient_collect` stamps it; a cache hit is `cached_web`; local retrieval is `local_*`).
> `UNAVAILABLE` is a run-level count of failed external tasks — never a phantom source row.

## Architecture (reuse-first)

- **Provenance** rides on the existing `Source.meta` JSON + two computed properties
  (`Source.provenance`, `Source.availability`) — mirrors the existing computed `Source.freshness`.
  Zero migration. Availability derives from provenance + freshness (`stale` overlays any origin).
- **Connectivity** (`services/connectivity.py`) is a layered, bounded, **on-demand-cached** model
  (internet HEAD probes of the hosts we actually call + search provider + Ollama/Qdrant/DB), not a
  poller and not one ICMP ping. A previous-state memory yields the `recovering` transition with no
  background traffic. Snapshot cached `connectivity_cache_seconds` (60s).
- **Cache** (`models/cache.py` `CachedSource` + `services/source_cache.py`) is the only genuinely
  new store: last successful external result set per `(project_id, source_type, query)`, TTL by
  type, **project-isolated**, content-only (no keys/headers/cookies).
- **Resilience** (`services/collection.py` `resilient_collect`) is a source-agnostic wrapper over
  `dispatch.collect`: live → stamp+cache; live-fails → serve cache (policy-permitting) → else
  fail (→ UNAVAILABLE). The orchestrator's existing per-task try/except already gives partial
  failure resilience; we build on it.
- **Policy** (`SourcePolicy`: live_only / live_preferred / cache_allowed / local_only) is one
  nullable column, resolved to `live_preferred` when null.
- **Recovery** reuses the previously-unwired `RETRYING` task infra: after the research loop, failed
  external tasks are retried **once** if a fresh probe shows the provider healthy. Cross-run refresh
  is Research Again (#4).
- **Run health** computes into the existing `report_meta` JSON (live/cached/local/stale/unavailable
  counts + `research_health` label + connectivity snapshot). The report **deterministically
  discloses** cache/local/unavailable sourcing (only when true). The diff detects
  `availability live → cached` etc.

## Validation matrix (spec §44)

| Scenario | Expected | Test |
|---|---|---|
| Internet available | LIVE | `test_live_research_marks_sources_live` |
| Internet unavailable | LOCAL fallback | `test_local_only_offline_research` |
| One provider unavailable | continue w/ healthy | `test_partial_outage_continues_and_reports_unavailable` |
| Search timeout / provider fail | fallback / unavailable | `test_partial_outage…`, `test_timeout_probe_counts_as_unreachable` |
| DNS failure | graceful (unreachable) | `test_timeout_probe_counts_as_unreachable` |
| Cached source available | CACHE | `test_cache_fallback_serves_cached` |
| Cached source expired | not served | `test_expired_entry_is_not_returned` |
| Local PDF available | LOCAL | `test_local_only_offline_research`, `test_hybrid_local_plus_live` |
| Connectivity recovery | retry failed | `test_recovery_retries_failed_task`, `test_recovery_transition` |
| Research Again | refresh stale | (via #4; refresh intent unchanged) |
| Research Diff | provenance change | `test_source_availability_change_live_to_cached` |
| Cross-project cache access | DENIED | `test_cached_source_does_not_leak_across_projects` |
| Existing research | unchanged | full suite green + migration test |

## Files

**New (backend):** `services/provenance.py`, `services/connectivity.py`, `services/source_cache.py`,
`services/collection.py`, `models/cache.py`; tests `test_provenance.py`, `test_connectivity.py`,
`test_source_cache.py`, `test_pipeline_connectivity.py`, `test_connectivity_security.py`.
**New (frontend):** `lib/provenance.ts`; tests `lib/provenance.test.ts`,
`pages/ResearchHealthBanner.test.tsx`.
**New (docs):** this file + `CONNECTIVITY-INTELLIGENCE-IMPLEMENTATION-PLAN.md`.
**Modified (backend):** `models/__init__.py`, `models/research.py` (source_policy col +
provenance/availability props), `models/enums.py` (`SourcePolicy`), `database.py` (`_ADDED_COLUMNS`),
`config.py` (connectivity/cache settings), `orchestration/orchestrator.py` (resilient collect,
snapshot, recovery, source health), `agents/report.py` (health disclosure), `api/system.py`
(`/system/connectivity`), `api/research.py` (policy + evidence provenance), `schemas/research.py`
(provenance/policy fields), `services/research_diff.py` (availability change), tests
`test_research_diff.py`, `test_migration_lineage.py`.
**Modified (frontend):** `api/types.ts`, `api/client.ts`, `components/ui.tsx` (`ProvenancePill`),
`components/SystemStatus.tsx` (connectivity pill), `pages/LiveResearch.tsx` (provenance pills +
Research Health banner), `pages/NewResearch.tsx` (policy picker).
**Modified (docs):** `CLAUDE.md`, `GAP-ANALYSIS.md`.

## Security / isolation (§30)

Cache rows carry `project_id`/`user_id`; every read filters by `project_id`, so a cached source in
project A is never served to project B — tested end-to-end through the fallback path
(`test_cached_source_does_not_leak_across_projects`) and directly (`test_cross_project_isolation`).
Only public result content is cached — never API keys, auth headers, cookies, or credentials.
Report health is behind project ownership (404 for others).

## Confidence integration (§16, §19)

**Untouched.** No offline penalty; provenance is disclosed, not scored. An authoritative local
document still outscores a low-quality live blog via `reliability_score`. Confidence remains
evidence-driven (`verification.score_claim`).

## Performance (§32)

Connectivity probes are bounded (`connectivity_timeout_seconds=3`) and cached (60s) so a run
probes once, not per source. The cache reduces repeated network calls. Retries are bounded
(`connectivity_max_retries=1`). No new LLM calls (health/provenance/diff are all deterministic).
No uncontrolled loops; nothing can hang the pipeline.

## Known limitations (intentional; future work)

1. Recovery retries failed external tasks **once** within a run; deeper refresh is via Research
   Again. The retry seam is bounded by `attempts`, extensible without redesign.
2. Cache is **query-level** result-set reuse, not a per-URL HTTP cache — matches the failure mode
   (the whole search call fails), and is CPU-free.
3. Connectivity is on-demand-cached, not a background monitor (§27 optional; kept cheap per §32).
4. Out of scope per §42: OCR, crawling, autonomous monitoring/alerts, MCP, enterprise connectors,
   browser automation, KG redesign, advanced/semantic/distributed cache, collaboration.

## Definition of Done — checklist (§43)

| Criterion | Status |
|---|---|
| Distinguish online/offline/degraded/recovering | ✅ (`ConnectivityManager`, 6 states) |
| Source provenance: live/cached/local/stale/unavailable/unknown | ✅ (`provenance.py` + computed props) |
| Offline document research works without internet | ✅ (`test_local_only_offline_research`) |
| Hybrid local + live | ✅ (`test_hybrid_local_plus_live`) |
| External failure doesn't kill the run | ✅ (`test_partial_outage…`) |
| Cache reused safely when policy allows | ✅ (`test_cache_fallback_serves_cached`) |
| Cached/local NEVER labelled live | ✅ (provenance stamped at source; §8 enforced) |
| ClaimSource displays provenance | ✅ (evidence endpoint + `ProvenancePill`) |
| Confidence stays evidence-driven, no offline penalty | ✅ (untouched) |
| Research Again refreshes stale/unavailable | ✅ (#4 refresh intent) |
| Research Diff shows provenance/evidence changes | ✅ (`availability x → y`) |
| Cache/source user/project isolated | ✅ (tested) |
| Retries & checks bounded | ✅ (config bounds) |
| All existing tests green | ✅ (213 backend + 31 frontend) |
| Docs updated | ✅ (plan + this report + CLAUDE.md + GAP-ANALYSIS) |
```

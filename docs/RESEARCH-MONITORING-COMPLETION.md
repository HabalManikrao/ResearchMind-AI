# Research Alerts + Continuous Monitoring (#6) — Completion Report

_Completed: 2026-09-02. ResearchMind now remembers a completed investigation, watches it
on a schedule, verifies meaningful changes with the existing Diff engine, and notifies the
user **only when what they should believe has changed** — never about search noise. Plan:
`docs/RESEARCH-MONITORING-IMPLEMENTATION-PLAN.md`._

---

## Final Validation Report

```
Monitoring:             READY
Scheduling:             READY
Incremental Checking:   READY
Change Detection:       READY
Significance Engine:    READY
Notifications:          READY
Deduplication:          READY
Connectivity:           READY
Offline Correctness:    READY
Research Again:         READY
Research Memory:        READY
Security:               READY
Performance:            READY
Migration:              READY
```

- **Backend tests:** 248 passed, 0 failed (`pytest`, all offline) — was 213; **+35**
  (13 significance, 6 monitor API + isolation, 4 monitoring pipeline, 9 monitor service +
  scheduling/backoff/concurrency, 1 migration, +2 covered by existing suites).
- **Frontend tests:** 40 passed, 0 failed (`vitest`) — was 31; **+9** (6 monitoring
  mapping, 3 MonitorCheckRow drill-down).
- **Build:** `npm run build` OK (`tsc --noEmit` clean + vite build, 1855 modules, 429 kB).
- **Migration:** additive/idempotent/non-destructive — two new tables
  (`research_monitors`, `monitor_checks`) via `create_all`; four new **nullable**
  `notifications` columns (`severity`, `monitor_id`, `dedup_key`, `data`) via the existing
  idempotent `_ensure_columns` ALTER. Verified by `test_migration_monitoring.py`
  (old-shape DB → migrate **twice** → columns + tables present, existing rows intact,
  new columns default NULL).

---

## The core principle, enforced

> ResearchMind does not merely tell the user that something new exists — it decides whether
> the new information **changes what the user should believe**. A monitoring check runs a
> cheap probe first; only a *candidate-significant* change escalates to a full verification
> run; only changes at/above the user's notification threshold produce an alert; and the
> same underlying change is never notified twice.

## Architecture (reuse-first — spec §1, §24, §25)

A monitoring check reuses almost everything and adds one significance engine + a two-tier
strategy:

- **Two-tier check** (`services/research_monitor.py`): **Stage 1** is a cheap probe
  (`resilient_collect`, *no LLM*) that re-collects the baseline's top questions and compares
  source sets — a low-quality new blog does not escalate; an authoritative/changed cited
  source does. **Stage 2** (only on escalation) forks a Research-Again `refresh` run (the
  only LLM-heavy step), diffs it against the baseline with the **existing** `diff_runs`, and
  runs significance. This keeps CPU-only Ollama affordable (spec §7, §36).
- **Significance engine** (`services/significance.py`): deterministic, transparent impact
  scoring over a `ResearchDiff` — recommendation reversal = CRITICAL, contradiction of a
  high-confidence claim = CRITICAL, major confidence drop = HIGH, etc. No arbitrary LLM
  scores (spec §10). 10 new low-quality sources → all LOW (suppressed); 1 authoritative
  contradiction → CRITICAL (spec §18).
- **Scheduler** — the existing in-process poller (`services/scheduler.py`) gained one call
  to `research_monitor.run_due_once()`. No second scheduler (spec §34). Restart-safe
  (monitors persist in the DB), concurrency-guarded (in-flight monitors skipped, LLM-heavy
  checks capped), with a stale-running reclaim and bounded exponential backoff (spec §22, §35).
- **Diff / Research Again / lineage / connectivity / notifications** — reused unchanged.
  A monitor alert carries `severity` + a `data` pointer to the baseline→new-run diff, which
  the notification center and Monitoring tab open with the existing RunDiff drill-down (§13).
- **Offline correctness** — an *incomplete* external check is recorded as `degraded` and
  retried; it is **never** reported as "no changes" (spec §20).
- **Research memory** — every check is persisted as a `MonitorCheck` (found + suppressed +
  provenance + source-health), so "what changed over the last month" is answerable (§26).

## Validation matrix (spec §37, §41)

| Scenario | Expected | Test |
|---|---|---|
| Recommendation reversal | CRITICAL | `test_recommendation_reversal_is_critical` |
| Contradiction of high-confidence claim | CRITICAL | `test_contradicted_high_confidence_claim_is_critical` |
| Major vs minor confidence drop | HIGH / MEDIUM | `test_major_confidence_drop_is_high_minor_is_medium` |
| 10 low-quality new sources | suppressed (no meaningful) | `test_ten_low_quality_new_sources_produce_no_meaningful_change` |
| 1 authoritative contradiction | meaningful + CRITICAL | `test_one_authoritative_contradiction_is_meaningful_and_critical` |
| live→cached provenance change | not an alert | `test_live_to_cached_provenance_change_is_not_an_alert` |
| No meaningful change | suppressed, no notification | `test_no_change_is_suppressed` |
| Meaningful change | escalate → verify → notify | `test_meaningful_change_escalates_and_notifies` |
| Repeated change | deduplicated (notified once) | `test_repeated_change_is_deduplicated` |
| Incomplete external check | degraded, never "no changes" | `test_incomplete_external_check_is_degraded_not_no_change` |
| Due monitor | launched, cadence advances | `test_due_monitor_is_launched_and_cadence_advances` |
| Already-running monitor | skipped (no duplicate) | `test_already_running_monitor_is_skipped` |
| Concurrency cap | one LLM-heavy check per tick | `test_concurrency_cap_limits_launches_per_tick` |
| Stale-running check | reclaimed | `test_stale_running_check_is_reclaimed` |
| Repeated failure | bounded exponential backoff | `test_backoff_grows_and_is_capped` |
| Restart | monitor survives, resumes | `test_monitor_survives_restart` |
| Cross-user / cross-project | 404, no leak | `test_monitor_is_isolated_across_users` |
| Create on incomplete research | 409 | `test_cannot_monitor_incomplete_research` |
| Migration (twice) | additive, intact | `test_monitoring_migration_additive_idempotent_nondestructive` |
| Existing Diff behaviour | unchanged | full suite green (`test_research_diff.py`) |

## Files

**New (backend):** `models/monitor.py` (`ResearchMonitor`, `MonitorCheck`),
`services/significance.py`, `services/research_monitor.py`, `api/monitors.py`,
`schemas/monitoring.py`; tests `test_significance.py`, `test_monitor_api.py`,
`test_monitoring_pipeline.py`, `test_monitor_service.py`, `test_migration_monitoring.py`.
**New (frontend):** `lib/monitoring.ts`; tests `lib/monitoring.test.ts`,
`pages/MonitorCheckRow.test.tsx`.
**New (docs):** this file + `RESEARCH-MONITORING-IMPLEMENTATION-PLAN.md`.
**Modified (backend):** `models/notification.py` (+4 nullable columns), `models/__init__.py`,
`database.py` (`_ADDED_COLUMNS["notifications"]`), `config.py` (monitor_* settings),
`services/notifications.py` (`notify()` gains severity/monitor_id/dedup_key/data + returns id),
`services/scheduler.py` (poller ticks monitors too), `schemas/scheduling.py`
(`NotificationOut` +severity/monitor_id/data), `main.py` (register `monitors` router).
**Modified (frontend):** `api/types.ts` (monitor types + Notification severity),
`api/client.ts` (monitor CRUD + run + checks), `pages/LiveResearch.tsx` (Monitoring tab +
setup + `MonitorCheckRow`), `pages/Notifications.tsx` (severity chip + diff link).
**Modified (docs):** `CLAUDE.md`, `GAP-ANALYSIS.md`.

## Security / isolation (spec §32, §33)

Monitors, checks, and notifications are user-scoped; a monitor is reachable only through its
lineage's project ownership (404 for others — no existence leak). A monitor alert is
addressed to the monitor's own `user_id`, so a user can never receive another user's research
information (`test_monitor_is_isolated_across_users`). #5 cache isolation is preserved (probe
cache reads filter `project_id`). No document passages, secrets, API keys, headers, or cookies
are placed in notifications, `monitor_checks`, or logs; `last_error` stores a category only.
In-app only — nothing is sent to external providers (§15, §33, §40).

## Performance (spec §36)

The cheap Stage-1 probe (no LLM) prevents most scheduled checks from ever running a full
research pass. A full verification run happens only on a candidate-significant change and is
serialized by a semaphore (`monitor_max_concurrent_checks=1`) so CPU Ollama isn't
oversubscribed. Connectivity probing is the bounded, 60 s-cached #5 model. Significance,
diff, and dedup are deterministic (no LLM). Retries/backoff are bounded; nothing polls
sub-hourly; nothing can hang the poller (each check is failure-isolated).

## Known limitations (intentional; future work)

1. Significance is **deterministic**; a bounded LLM tie-breaker for semantically ambiguous
   changes is a documented seam, not built (spec §10, §40).
2. Delivery is **in-app only**; Slack/Teams/email/webhook are explicit non-goals (§15, §40).
3. Schedules are **daily/weekly/monthly** — no arbitrary cron, no sub-hourly (§5, §40).
4. One monitor per lineage (upsert), matching the personal-tool scope.

## Definition of Done — checklist (spec §41)

| Criterion | Status |
|---|---|
| Monitor a completed research project | ✅ (`api/monitors.py`, 409 until a run completes) |
| Persistent schedule | ✅ (`research_monitors` table + shared poller, restart-safe) |
| Incremental checks avoid unnecessary deep research | ✅ (Stage-1 cheap probe gate) |
| Change detection via the existing Diff engine | ✅ (`diff_runs` reused, no `monitor_diff.py`) |
| Significance suppresses low-value changes | ✅ (`significance.py`, LOW = noise) |
| Notifications for important changes | ✅ (`monitor_alert`, severity + diff link) |
| Deduplication (no spam) | ✅ (`test_repeated_change_is_deduplicated`) |
| Connectivity provenance preserved | ✅ (probe via `resilient_collect`, provenance_mode) |
| Incomplete external check ≠ "no changes" | ✅ (`degraded`, `test_incomplete_external…`) |
| Important changes trigger deeper verification | ✅ (Research Again `refresh` run) |
| Monitoring history in research memory | ✅ (`monitor_checks`, `/monitor/checks`) |
| Users/projects isolated | ✅ (tested) |
| CPU/provider usage bounded | ✅ (cheap gate + semaphore + backoff) |
| Scheduler restart-safe | ✅ (`test_monitor_survives_restart`) |
| All existing + new tests pass | ✅ (248 backend + 40 frontend) |
| Docs updated | ✅ (plan + this report + CLAUDE.md + GAP-ANALYSIS) |
```

# Research Alerts + Continuous Monitoring (#6) — Implementation Plan

_Pre-implementation design. Written **before** any code, per spec §1. The guiding
principle: **do not notify users about search noise — notify them about meaningful
changes to knowledge, evidence, claims, sources, or recommendations.** Monitoring
answers "has something important changed since my last research run?", not "did a new
search result appear?"_

---

## 1. Audit — what already exists (reuse-first)

A real audit of the codebase (~25 files) shows most of the machinery already exists.
This milestone is **wiring + one significance engine + two small tables**, not new
infrastructure.

| Capability | Where it lives today | Reuse for monitoring |
|---|---|---|
| **Scheduler** (persistent, restart-safe, poller) | `services/scheduler.py` `SchedulerService._loop` polls `scheduled_research` every `scheduler_poll_seconds`; started in `main.py` lifespan | **Extend the same loop** to also tick due monitors. No new scheduler. Restart-safety comes free (monitors persist in DB). |
| **Diff engine** (deterministic, evidence-aware) | `services/research_diff.py` `diff_runs(old_id,new_id)` → sources/claims/confidence/recommendation/documents with NEW/REMOVED/STRENGTHENED/WEAKENED/CONTRADICTED categories, reasons built from `confidence_meta` | **Called as-is.** No `monitor_diff.py` (spec §24). |
| **Research Again** (fork a linked run, prior memory) | `api/research.py:research_again` + `orchestrator._build_prior_context`; `intent="refresh"` addendum already says "re-verify prior findings, prioritise what's NEWER" | **Exactly the monitoring semantic.** A deep monitor check forks a `refresh` child run — zero new LLM plumbing. |
| **Lineage** (a run IS a project; `root_id`) | `research_projects.root_id/parent_id/run_number/run_intent` | Monitor is keyed to a **lineage** (`root_id`); the baseline is the latest COMPLETED run in that lineage. |
| **Connectivity** (live/cached/local, health, policy) | `services/connectivity.py` `manager.snapshot()`, `SourcePolicy`, `services/collection.py:resilient_collect`, `services/provenance.py` | Cheap probe uses `resilient_collect` → provenance/degraded stamped honestly; a check records connectivity like a run. |
| **Notifications** (in-app, user-scoped) | `models/notification.py` + `services/notifications.py:notify()` + `api/notifications.py` + frontend `Notifications.tsx` + sidebar badge | **Reused.** Add nullable columns (severity, monitor_id, dedup_key, data) so a notification can carry impact + a diff link. |
| **Research memory** | `research_projects.memory_summary`, `orchestrator._build_memory_summary` | A monitor check is persisted (`monitor_checks`) so "what changed over the last month" is answerable (§26). |
| **Migration** (additive, idempotent) | `database._ADDED_COLUMNS` + `_ensure_columns` (SQLite ALTER) + `create_all` | New tables via `create_all`; new Notification columns via `_ADDED_COLUMNS`. Both idempotent, non-destructive. |
| **Task status incl. RETRYING/backoff** | `enums.TaskStatus`, `_retry_failed_external` recovery | Monitor health/backoff mirror this pattern (consecutive_failures → exponential next_check_at). |
| **Ownership** | `research.py:_get_project` (404 not 403); user-scoped routers | Every monitor endpoint goes through `_get_project`; monitors + checks + notifications are user-scoped. |

**Conclusion:** no duplicate scheduling, no duplicate diff, no duplicate notification
system, no duplicate research engine. New surface = 1 significance module, 1 monitor
service, 2 tables, 4 nullable notification columns, 1 API router, 1 frontend tab.

---

## 2. Monitoring architecture

```
                         SchedulerService._loop  (existing poller, +1 line)
                                     │  every scheduler_poll_seconds
                                     ▼
                      research_monitor.run_due_once()
                                     │  monitors with next_check_at ≤ now, enabled, not running
                                     ▼
        launch run_monitor_check(monitor_id)  as a background task (semaphore-bounded)
                                     │
             ┌───────────────────────┴───────────────────────┐
             ▼                                               (concurrency guard: skip if RUNNING)
   1) connectivity snapshot ──────────────────────────────────────────────┐
             │  external unavailable & policy can't serve cache            │
             ▼                                                             ▼
   2) STAGE 1 — cheap probe (resilient_collect, NO LLM pipeline)     DEGRADED CHECK
        re-collect top-K baseline questions across enabled sources        │ record degraded,
        compare fresh sources vs baseline (normalize_url + checksum)      │ backoff, retry later,
             │                                                            │ NEVER emit "no changes"
     ┌───────┴────────┐                                                    │  (spec §20)
     ▼                ▼                                                    ▼
  no significant   candidate significant new/changed source         (end check, HEALTH=degraded)
  new sources      (authoritative / high reliability / changed cited source)
     │                     │  ESCALATE (spec §7 stage-4, §25)
     ▼                     ▼
  SUPPRESS         3) Research Again — fork "refresh" child run, await run_research()
  (no_change)              │  (full evidence/claims/verify/contradiction/recommendation)
  record check             ▼
  no notification   4) DIFF  research_diff.diff_runs(baseline, child)
                           ▼
                   5) SIGNIFICANCE  significance.evaluate(diff) → [Change(impact, reasons, dedup_key)]
                           ▼
                   6) SUPPRESS low/noise; DEDUP already-notified keys; filter by notify_policy
                           ▼
                   7) NOTIFY (one summary notification, severity = max impact, diff link)
                           ▼
                   8) record MonitorCheck (memory), advance baseline, reset failures
```

**Why a cheap Stage-1 gate (spec §7, §36):** CPU-only Ollama makes a full research run
expensive. Stage 1 is collection-only (network + local retrieval, **no LLM**) and
compares source sets. Most scheduled checks find nothing meaningfully new and stop here
cheaply. A full `refresh` run (the only LLM-heavy part) happens **only when Stage 1
surfaces a candidate significant change** — this is the spec's "use Research Again when
deeper investigation is required; don't run full deep research every check."

---

## 3. Data model (additive, nullable, non-destructive — spec §38)

### New table `research_monitors` (one per lineage)
| column | type | notes |
|---|---|---|
| id | str pk | uuid |
| user_id | str idx | owner (isolation) |
| root_id | str idx | the lineage being watched |
| project_id | str | seed/original project (back-ref convenience) |
| enabled | bool | default true |
| interval_minutes | int | mapped from frequency daily/weekly/monthly; floored by `min_schedule_interval_minutes` |
| source_policy | str? | null → `default_source_policy` (#5) |
| notify_policy | str | `all` (medium+) / `important` (high+) / `critical` (critical only) |
| last_run_id | str? | baseline run to diff against (latest COMPLETED in lineage) |
| last_checked_at | dt? | last attempt |
| last_success_at | dt? | last successful (non-degraded) check |
| next_check_at | dt idx | scheduler key |
| last_status | str | idle/running/healthy/no_change/changes/degraded/failed |
| health | str | HEALTHY/DEGRADED/OFFLINE/FAILING/DISABLED (computed at read) |
| consecutive_failures | int | drives backoff |
| failure_count | int | lifetime |
| last_error | str? | **category only**, never payloads (privacy §33) |
| created_at / updated_at | dt | |

App-level rule: **one monitor per `root_id`** (upsert on create). Multiple users can't
share a lineage (ownership).

### New table `monitor_checks` (monitoring history == research memory, §26)
| column | type | notes |
|---|---|---|
| id | str pk | |
| monitor_id | str idx | |
| root_id | str idx | |
| baseline_run_id | str? | run compared against |
| new_run_id | str? | child run created (null for cheap/degraded checks) |
| status | str | no_change / changes / suppressed / degraded / failed |
| provenance_mode | str | live / hybrid / cache / local / degraded |
| meaningful_changes | JSON | `[{kind,impact,title,detail,dedup_key,refs}]` |
| suppressed_count | int | changes seen but below threshold/noise |
| notification_id | str? | link to the notification, if any |
| source_health | JSON | reused shape from `_build_source_health` |
| started_at / finished_at / created_at | dt | |

### Notification additive columns (via `_ADDED_COLUMNS["notifications"]`)
`severity TEXT`, `monitor_id TEXT`, `dedup_key TEXT`, `data JSON(TEXT)` — all nullable,
so every existing notification stays valid and existing code paths are unaffected.

### Migration
- Tables created by `create_all` (absent → created fresh with all columns).
- Notification columns added by the existing idempotent `_ensure_columns` ALTER.
- **No destructive changes.** Startup run twice = no-op on the second pass (test: extend
  `test_migration_lineage.py` shape or a new `test_migration_monitoring.py`).

---

## 4. Significance engine (`services/significance.py`) — spec §8, §10, §18

**Deterministic. Operates on a `ResearchDiff` + source metadata. No arbitrary LLM
scores** (§10). Every `Change` carries transparent reasons built from the diff's own
`confidence_meta`-derived reasons (never invented, §10, consistent with #4).

Impact levels: `LOW < MEDIUM < HIGH < CRITICAL`.

Rules (ordered, highest wins per change):
- **Recommendation reversed** → CRITICAL; **modified** → HIGH.
- **Claim CONTRADICTED** (was supported, now contradicted / newly conflicting) →
  CRITICAL if the claim was high-confidence (baseline ≥ `monitor_high_confidence`), else HIGH.
- **Claim WEAKENED**: confidence drop ≥ `monitor_major_delta` → HIGH; ≥ `research_diff_confidence_delta` → MEDIUM.
- **Claim STRENGTHENED**: major → MEDIUM; minor → LOW.
- **New claim**: strong evidence (support ≥2, reliability ok) → MEDIUM; else LOW.
- **New source**: HIGH only if authoritative (reliability ≥ `monitor_authoritative_reliability`
  **or** type in {papers, docs, github}) **and** it feeds a changed/new claim; a bare new
  source is LOW. → **10 new low-quality blogs = all LOW = suppressed; 1 authoritative
  source contradicting a major claim = CRITICAL** (spec §18).
- **Source became unavailable** (availability live→unavailable, or a cited source removed) → MEDIUM.

`meaningful = impact ≥ MEDIUM` (LOW is noise). `notify_threshold(notify_policy)`:
`all→MEDIUM`, `important→HIGH`, `critical→CRITICAL`.

**Dedup key (§17):** stable, content-derived — `sha1(kind | normalized-claim-or-url |
coarse-confidence-bucket)`. Never random. A monitor's already-notified keys are collected
from prior `monitor_checks.meaningful_changes` (notified ones) and filtered out before
notifying, so the same underlying change across consecutive checks is suppressed.

---

## 5. No-change suppression & offline correctness (spec §11, §20)

- **No meaningful changes** → status `no_change`, record the check, **no notification**.
- **Meaningful but below policy threshold** → recorded (suppressed_count), no notification.
- **Degraded/incomplete external check** (external unavailable and policy forbids cache, or
  probe raised) → status `degraded`, backoff + retry later, **never** report "no changes."
  This is the critical distinction: an incomplete check ≠ a clean check.
- Local-only monitors (policy `local_only`) still run against documents/memory and are
  honestly labelled `local`.

---

## 6. Connectivity integration (spec §19, §23)

The check takes a `connectivity.manager.snapshot()`. Stage-1 uses `resilient_collect`, so
provenance is stamped exactly as in a normal run (`live_web`/`cached_web`/`local_*`) and a
cache-served comparison is disclosed as `cache-assisted` in `provenance_mode`. **Never
claims a live update when live retrieval did not occur.** Recovery: a monitor that failed
while a provider was down runs a normal check when it next fires and the provider is
healthy; recovery itself is not a "change" unless content actually differs (§23).

---

## 7. Failure, backoff, concurrency (spec §21, §22, §34, §35)

- **Health states**: HEALTHY / DEGRADED / OFFLINE / FAILING / DISABLED, derived from
  `last_status` + `consecutive_failures` + enabled.
- **Backoff**: on failure `consecutive_failures++`, `next_check_at = now +
  min(interval * 2^failures, monitor_backoff_cap_minutes)`. On success reset to 0 and the
  normal cadence. Bounded — never hammers a provider.
- **Concurrency**: a module-level `set[str]` of running monitor ids + `last_status="running"`
  in the DB. `run_due_once` skips a monitor already running; a second trigger is dropped
  (§35). A global `asyncio.Semaphore(monitor_max_concurrent_checks=1)` serializes the
  LLM-heavy child runs so CPU Ollama isn't oversubscribed (§36).
- **Restart-safe**: monitors live in the DB; the poller resumes them after a restart. An
  in-flight check that died mid-run leaves `last_status="running"`; a stale-running guard
  (`last_checked_at` older than `monitor_stale_running_minutes`) reclaims it.

---

## 8. API (`api/monitors.py`) — spec §31

All ownership-enforced through `research._get_project` (404 for others).

```
POST   /research/{id}/monitor        create/enable (upsert per lineage)
GET    /research/{id}/monitor        monitor + recent checks (404 if none)
PATCH  /research/{id}/monitor        enable/disable, schedule, policy, sensitivity
DELETE /research/{id}/monitor        remove
POST   /research/{id}/monitor/run    run now (same pipeline; no duplicate schedule; §30)
GET    /research/{id}/monitor/checks monitoring history (memory, §26)
```
Notifications reuse the existing `/notifications` surface (now carrying severity + a diff
link in `data`).

---

## 9. Frontend (spec §27, §28) — lightweight

- `lib/monitoring.ts`: severity + health mapping (colour/label), like `lib/provenance.ts`.
- `api/client.ts` + `api/types.ts`: monitor CRUD + run + checks; Notification gains
  `severity`/`monitor_id`/`data`.
- **Monitoring tab** in `LiveResearch.tsx` (a completed run): enabled/disabled toggle,
  schedule, last/next check, health, source policy, recent meaningful changes → each links
  to the relevant **RunDiff** (reusing the existing diff drill-down, spec §13, §24).
- **"Monitor this research"** action on a completed run → simple setup (frequency / sources
  / notify policy / start).
- **Notification center** (`Notifications.tsx`): show severity chip + click-through to the
  diff/evidence for monitor notifications. The existing sidebar unread badge already covers
  §28. The existing global `Monitoring.tsx` (system stats) is untouched — different concept.

---

## 10. Security & privacy (spec §32, §33)

- Monitors, checks, and notifications are **user-scoped**; a monitor is reachable only via
  its lineage's project ownership. Cross-user / cross-project access 404s.
- A user can **never** receive a notification containing another user's research (owner is
  stamped at creation; notify targets the monitor's `user_id`).
- Cache/source isolation from #5 is preserved (Stage-1 cache reads filter `project_id`).
- **No sensitive payloads**: notifications and `monitor_checks` store change summaries
  (claim text, confidence deltas, source titles/urls) — never document passages, secrets,
  API keys, headers, or cookies. `last_error` stores a **category**, not a stack/response.
- In-app only; nothing is sent to external providers (§15, §33, §40).

---

## 11. Config (all bounded, CPU-aware)

```
monitor_enabled: bool = True
monitor_poll_seconds: int = reuse scheduler_poll_seconds (single poller)
monitor_default_frequency: "daily"                      # daily|weekly|monthly
monitor_min_interval_minutes: reuse min_schedule_interval_minutes (floor)
monitor_max_concurrent_checks: int = 1                  # serialize LLM-heavy runs
monitor_probe_tasks: int = 6                            # Stage-1 cheap probe budget
monitor_probe_min_reliability: float = 60.0            # escalate gate for new sources
monitor_authoritative_reliability: float = 70.0
monitor_high_confidence: float = 70.0
monitor_major_delta: float = 15.0                       # confidence drop = HIGH
monitor_backoff_cap_minutes: int = 1440                 # 24h backoff ceiling
monitor_stale_running_minutes: int = 60                 # reclaim a died-mid-run check
monitor_history_limit: int = 50                         # checks returned by the API
```

---

## 12. Testing (spec §37)

- **Significance** (`test_significance.py`): low/medium/high/critical mapping;
  recommendation reversal=critical; contradiction of high-confidence claim=critical;
  10 low-quality new sources → all suppressed; 1 authoritative contradiction → notify;
  dedup key stability.
- **Monitor service** (`test_monitor_service.py`): create/enable/disable/update/run-now;
  due selection; duplicate-run prevention (concurrency guard); restart persistence; backoff
  math; stale-running reclaim.
- **Monitoring pipeline** (`test_monitoring_pipeline.py`, driven like `patch_pipeline`):
  no-change suppression; new authoritative source → escalation + notification; changed
  claim; contradiction; confidence drop; recommendation change; degraded/offline correctness
  (never "no changes"); recovery; cache-assisted provenance.
- **Notifications** (`test_monitor_notifications.py`): generated / suppressed / deduplicated
  / read; project + user isolation.
- **Security** (`test_monitor_security.py`): cross-user monitor 404; cross-project; a user
  can't read another user's monitor notifications.
- **Diff regression**: existing `test_research_diff.py` unchanged and green.
- **Migration** (`test_migration_monitoring.py`): old-shape DB → migrate twice → new tables
  + notification columns present, existing rows intact.
- **Regression**: the full 213 backend + 31 frontend suites stay green.

---

## 13. Non-goals (spec §40)

Slack/Teams/email/SMS, arbitrary cron, sub-hourly polling, autonomous external actions,
OCR, KG redesign, MCP, multi-user collaboration, semantic/LLM significance (bounded
deterministic only for now — the seam is there to add a bounded LLM tie-breaker later).

---

## 14. Definition of Done → validation

Each DoD item (§41) maps to a test above; the completion report
(`docs/RESEARCH-MONITORING-COMPLETION.md`) will carry the READY/BLOCKED matrix (§42) with
**executed** backend/frontend counts, build + migration results — no READY claimed without
running the tests.

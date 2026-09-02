"""Research monitoring service (#6): the check pipeline + the due-poller.

Reuse-first (spec §1, §24, §25): a monitoring check leans entirely on machinery that
already exists — the connectivity/resilient-collection layer (#5) for a cheap probe, the
Research-Again fork + orchestrator for deep verification, the deterministic Diff engine
(#4) for change detection, the significance engine for impact, and the in-app notification
system for delivery. The only genuinely new logic is the **two-tier strategy** that keeps
CPU-only Ollama affordable:

    Stage 1  cheap probe (collection only, NO LLM) — did any *candidate-significant*
             source appear/change since the baseline run?
       │  no → record "no meaningful change", suppress (spec §11). Cheap.
       ▼  yes
    Stage 2  Research Again "refresh" run (the only LLM-heavy step) → Diff vs baseline →
             significance → dedup → notify only what clears the policy threshold.

Offline correctness (spec §20): an *incomplete* external probe is recorded as ``degraded``
and retried — it is **never** reported as "no changes".
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.config import get_settings
from app.database import SessionLocal
from app.models import (
    Claim,
    MonitorCheck,
    ProjectStatus,
    ResearchMonitor,
    ResearchProject,
    ResearchQuestion,
    Source,
)
from app.orchestration import orchestrator as orch
from app.orchestration.control import RunControl
from app.services import connectivity, notifications, research_diff, significance
from app.services.collection import resilient_collect
from app.services.dedup import normalize_url
from app.services.provenance import is_external

log = logging.getLogger("researchmind.monitor")

# In-flight monitor ids (concurrency guard, spec §35). A monitor already RUNNING is
# skipped rather than run twice. Module-level so it survives across poller ticks.
_running: set[str] = set()
# Strong references to background check tasks so they aren't garbage-collected.
_tasks: set[asyncio.Task] = set()

_FREQ_MINUTES = {"daily": 1440, "weekly": 10080, "monthly": 43200}

# Serializes the LLM-heavy Stage-2 runs so CPU-only Ollama isn't oversubscribed (spec
# §36). Created lazily and rebound if the running loop changes (pytest-asyncio uses a
# fresh loop per test, as with the orchestrator's _db_lock).
_slot_sem: asyncio.Semaphore | None = None
_slot_loop = None


def _run_slot() -> asyncio.Semaphore:
    global _slot_sem, _slot_loop
    loop = asyncio.get_event_loop()
    if _slot_sem is None or _slot_loop is not loop:
        _slot_sem = asyncio.Semaphore(max(1, get_settings().monitor_max_concurrent_checks))
        _slot_loop = loop
    return _slot_sem


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime | None) -> datetime | None:
    """SQLite returns naive datetimes; coerce to UTC-aware before comparing (#5 pattern)."""
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def frequency_to_minutes(frequency: str) -> int:
    return _FREQ_MINUTES.get(frequency, _FREQ_MINUTES["daily"])


def _checksum(content: str | None) -> str:
    return hashlib.sha1((content or "").encode("utf-8")).hexdigest()


def _resolved_policy(monitor: ResearchMonitor) -> str:
    return monitor.source_policy or get_settings().default_source_policy


# --------------------------------------------------------------------------- #
# Baseline resolution
# --------------------------------------------------------------------------- #
async def _latest_completed_run(db, root_id: str, exclude: str | None = None) -> ResearchProject | None:
    rows = (
        await db.execute(
            select(ResearchProject)
            .where(ResearchProject.root_id == root_id)
            .where(ResearchProject.status == ProjectStatus.COMPLETED)
            .order_by(ResearchProject.run_number.desc(), ResearchProject.completed_at.desc())
        )
    ).scalars().all()
    for r in rows:
        if exclude and r.id == exclude:
            continue
        return r
    return None


# --------------------------------------------------------------------------- #
# Stage 1 — cheap probe (collection only, no LLM)
# --------------------------------------------------------------------------- #
class _Probe:
    def __init__(self) -> None:
        self.new_sources: list = []       # CollectedSource not seen in the baseline
        self.changed_sources: list = []    # baseline url whose content checksum changed
        self.escalate = False
        self.live = self.cached = self.local = 0
        self.external_attempts = 0
        self.external_failures = 0

    @property
    def provenance_mode(self) -> str:
        if self.live and (self.cached or self.local):
            return "hybrid"
        if self.live:
            return "live"
        if self.cached:
            return "cache"
        if self.local:
            return "local"
        return "unknown"

    @property
    def degraded(self) -> bool:
        # An external probe was attempted but nothing external came back live or cached,
        # and it wasn't a deliberate local-only run → the external check is INCOMPLETE.
        return self.external_attempts > 0 and self.external_failures >= self.external_attempts


async def _cheap_probe(monitor: ResearchMonitor, baseline: ResearchProject) -> _Probe:
    """Re-collect the baseline's top questions across its sources — collection only, no
    LLM — and compare against the baseline's stored sources. Reuses ``resilient_collect``
    so provenance/degraded state is honest (#5)."""
    settings = get_settings()
    policy = _resolved_policy(monitor)
    probe = _Probe()

    async with SessionLocal() as db:
        questions = (
            await db.execute(
                select(ResearchQuestion)
                .where(ResearchQuestion.project_id == baseline.id)
                .order_by(ResearchQuestion.priority)
            )
        ).scalars().all()
        base_sources = (
            await db.execute(select(Source).where(Source.project_id == baseline.id))
        ).scalars().all()

    baseline_by_url = {normalize_url(s.url): s for s in base_sources}
    sources_enabled = list(baseline.sources_enabled or ["web"]) or ["web"]
    q_texts = [q.text for q in questions] or [baseline.objective or baseline.query]

    provider = orch.get_provider()
    tavily = orch.get_search_client(settings)

    # Build (source, question) probe pairs, budget-bounded (spec §36).
    pairs: list[tuple[str, str]] = []
    for q in q_texts:
        for s in sources_enabled:
            pairs.append((s, q))
    pairs = pairs[: settings.monitor_probe_tasks]

    seen_new: set[str] = set()
    for source_type, question in pairs:
        external = is_external(source_type)
        if external:
            probe.external_attempts += 1
        try:
            result = await resilient_collect(
                source_type, provider, tavily, settings,
                question=question, search_query=question,
                project_id=baseline.id, user_id=monitor.user_id, policy=policy,
            )
        except Exception:  # noqa: BLE001 - a genuinely unavailable external source
            if external:
                probe.external_failures += 1
            continue

        if result.outcome == "live":
            probe.live += 1
        elif result.outcome == "cached":
            probe.cached += 1
        elif result.outcome == "local":
            probe.local += 1

        for cs in result.sources:
            key = normalize_url(cs.url)
            if key in baseline_by_url:
                if _checksum(cs.content) != _checksum(baseline_by_url[key].content):
                    probe.changed_sources.append(cs)
                    probe.escalate = True  # content of a cited source drifted
            elif key not in seen_new:
                seen_new.add(key)
                probe.new_sources.append(cs)
                if _candidate_significant(cs, settings):
                    probe.escalate = True
    return probe


def _candidate_significant(cs, settings) -> bool:
    """A *new* source worth a deep re-check: authoritative type or clears the reliability
    floor. A low-quality blog does not escalate (spec §18: 10 new low-quality → nothing)."""
    if cs.source_type in significance.AUTHORITATIVE_TYPES:
        return True
    return cs.reliability_score >= settings.monitor_probe_min_reliability


# --------------------------------------------------------------------------- #
# Stage 2 — deep verification via Research Again, then Diff + significance
# --------------------------------------------------------------------------- #
async def _fork_refresh_run(baseline: ResearchProject, user_id: str) -> str:
    """Fork a linked ``refresh`` continuation of the baseline (reusing #4 lineage) and
    carry its documents forward. Returns the new child project id."""
    async with SessionLocal() as db:
        parent = await db.get(ResearchProject, baseline.id)
        child = ResearchProject(
            user_id=user_id,
            title=parent.title,
            query=parent.query,
            mode=parent.mode,
            constraints=dict(parent.constraints or {}),
            sources_enabled=list(parent.sources_enabled or ["web"]),
            source_policy=parent.source_policy,
            status=ProjectStatus.CREATED,
            parent_id=parent.id,
            root_id=parent.root_id or parent.id,
            run_number=(parent.run_number or 1) + 1,
            run_intent="refresh",
        )
        db.add(child)
        await db.commit()
        child_id = child.id

    if get_settings().research_again_carry_documents:
        try:
            from app.documents.service import carry_forward_documents

            await carry_forward_documents(
                parent_project_id=baseline.id, new_project_id=child_id, new_user_id=user_id,
            )
        except Exception:  # noqa: BLE001 - carry-forward is best-effort
            pass
    return child_id


async def _source_reliability_map(project_id: str) -> dict:
    async with SessionLocal() as db:
        rows = (
            await db.execute(select(Source).where(Source.project_id == project_id))
        ).scalars().all()
    return {normalize_url(s.url): (s.reliability_score, s.source_type) for s in rows}


async def _notified_keys(monitor_id: str) -> set[str]:
    """dedup keys already delivered in a prior notification for this monitor (spec §17)."""
    async with SessionLocal() as db:
        rows = (
            await db.execute(
                select(MonitorCheck)
                .where(MonitorCheck.monitor_id == monitor_id)
                .where(MonitorCheck.notification_id.isnot(None))
            )
        ).scalars().all()
    keys: set[str] = set()
    for r in rows:
        for ch in r.meaningful_changes or []:
            if ch.get("notified") and ch.get("dedup_key"):
                keys.add(ch["dedup_key"])
    return keys


# --------------------------------------------------------------------------- #
# The check
# --------------------------------------------------------------------------- #
async def run_monitor_check(monitor_id: str) -> dict:
    """Run one monitoring check. Self-contained and failure-isolated: it never raises to
    the caller — failures are recorded on the monitor with bounded backoff (spec §22)."""
    settings = get_settings()
    started = _now()

    async with SessionLocal() as db:
        monitor = await db.get(ResearchMonitor, monitor_id)
        if monitor is None or not monitor.enabled:
            return {"status": "skipped"}
        monitor.last_status = "running"
        monitor.last_checked_at = started
        await db.commit()
        user_id = monitor.user_id
        root_id = monitor.root_id

    _running.add(monitor_id)
    try:
        # --- Resolve the baseline run to compare against. ---------------------
        async with SessionLocal() as db:
            monitor = await db.get(ResearchMonitor, monitor_id)
            baseline = None
            if monitor.last_run_id:
                baseline = await db.get(ResearchProject, monitor.last_run_id)
            if baseline is None or baseline.status != ProjectStatus.COMPLETED:
                baseline = await _latest_completed_run(db, root_id)
        if baseline is None:
            return await _record_failure(monitor_id, started, "no_baseline",
                                         "No completed run to monitor yet")

        # --- Connectivity snapshot (honest provenance; steers nothing hard). --
        snapshot = None
        if settings.connectivity_enabled:
            try:
                snapshot = await connectivity.manager.snapshot()
            except Exception:  # noqa: BLE001 - probing must never sink a check
                snapshot = None

        # --- Stage 1: cheap probe. -------------------------------------------
        probe = await _cheap_probe(monitor, baseline)

        # Offline correctness (spec §20): an incomplete external check is NOT "no change".
        if probe.degraded:
            return await _record_degraded(monitor_id, baseline.id, started, probe)

        if not probe.escalate:
            return await _record_no_change(monitor_id, baseline.id, started, probe)

        # --- Stage 2: deep verification (the only LLM-heavy step). -----------
        child_id = await _fork_refresh_run(baseline, user_id)
        async with _run_slot():  # serialize LLM-heavy runs (spec §36)
            await orch.run_research(child_id, RunControl())

        async with SessionLocal() as db:
            child = await db.get(ResearchProject, child_id)
            child_status = child.status if child else None
            child_health = (child.report_meta or {}).get("source_health") if child else None
        if child_status != ProjectStatus.COMPLETED:
            return await _record_failure(
                monitor_id, started, "refresh_run_failed",
                "The verification run did not complete", new_run_id=child_id,
            )

        # --- Diff (reuse #4) + significance (deterministic). -----------------
        diff = await research_diff.diff_runs(baseline.id, child_id)
        rel_map = await _source_reliability_map(child_id)
        changes = significance.evaluate(diff, settings, source_reliability=rel_map)
        meaningful = [c for c in changes if significance.is_meaningful(c)]

        # Dedup against already-notified changes (spec §17).
        notified_before = await _notified_keys(monitor_id)
        fresh = [c for c in meaningful if c.dedup_key not in notified_before]
        threshold = significance.notify_threshold(monitor.notify_policy)
        notifiable = [c for c in fresh if significance.rank(c.impact) >= significance.rank(threshold)]

        return await _record_changes(
            monitor_id, baseline.id, child_id, started, probe,
            meaningful=meaningful, notifiable=notifiable, source_health=child_health,
        )
    except Exception as exc:  # noqa: BLE001 - a check must never crash the poller
        log.exception("Monitor check failed for %s", monitor_id)
        return await _record_failure(monitor_id, started, "error", type(exc).__name__)
    finally:
        _running.discard(monitor_id)


# --------------------------------------------------------------------------- #
# Result recording + scheduling
# --------------------------------------------------------------------------- #
def _next_after_success(monitor: ResearchMonitor) -> datetime:
    return _now() + timedelta(minutes=max(1, monitor.interval_minutes))


def _next_after_failure(monitor: ResearchMonitor) -> datetime:
    settings = get_settings()
    # Exponential backoff, capped (spec §22). consecutive_failures already incremented.
    factor = 2 ** min(monitor.consecutive_failures, 10)
    minutes = min(monitor.interval_minutes * factor, settings.monitor_backoff_cap_minutes)
    return _now() + timedelta(minutes=max(1, minutes))


async def _add_check(**kwargs) -> str:
    async with SessionLocal() as db:
        check = MonitorCheck(**kwargs)
        db.add(check)
        await db.commit()
        return check.id


async def _record_no_change(monitor_id, baseline_id, started, probe: _Probe) -> dict:
    async with SessionLocal() as db:
        monitor = await db.get(ResearchMonitor, monitor_id)
        root_id = monitor.root_id
    check_id = await _add_check(
        monitor_id=monitor_id, root_id=root_id, baseline_run_id=baseline_id, new_run_id=None,
        status="no_change", provenance_mode=probe.provenance_mode, meaningful_changes=[],
        suppressed_count=0, source_health=None, max_impact=None, escalated=False,
        started_at=started, finished_at=_now(),
    )
    async with SessionLocal() as db:
        monitor = await db.get(ResearchMonitor, monitor_id)
        monitor.last_status = "no_change"
        monitor.last_success_at = _now()
        monitor.consecutive_failures = 0
        monitor.last_error = None
        monitor.check_count = (monitor.check_count or 0) + 1
        monitor.next_check_at = _next_after_success(monitor)
        await db.commit()
    return {"status": "no_change", "check_id": check_id}


async def _record_degraded(monitor_id, baseline_id, started, probe: _Probe) -> dict:
    async with SessionLocal() as db:
        monitor = await db.get(ResearchMonitor, monitor_id)
        root_id = monitor.root_id
    check_id = await _add_check(
        monitor_id=monitor_id, root_id=root_id, baseline_run_id=baseline_id, new_run_id=None,
        status="degraded", provenance_mode="degraded", meaningful_changes=[],
        suppressed_count=0, source_health=None, max_impact=None, escalated=False,
        detail="External sources were unavailable — check incomplete, will retry.",
        started_at=started, finished_at=_now(),
    )
    async with SessionLocal() as db:
        monitor = await db.get(ResearchMonitor, monitor_id)
        monitor.last_status = "degraded"
        # Degraded is not a hard failure but should retry sooner than the full cadence
        # via a light backoff; count it toward consecutive_failures for health/backoff.
        monitor.consecutive_failures = (monitor.consecutive_failures or 0) + 1
        monitor.last_error = "degraded_connectivity"
        monitor.check_count = (monitor.check_count or 0) + 1
        monitor.next_check_at = _next_after_failure(monitor)
        await db.commit()
    return {"status": "degraded", "check_id": check_id}


async def _record_changes(
    monitor_id, baseline_id, new_run_id, started, probe: _Probe, *,
    meaningful, notifiable, source_health,
) -> dict:
    async with SessionLocal() as db:
        monitor = await db.get(ResearchMonitor, monitor_id)
        root_id = monitor.root_id
        notify_policy = monitor.notify_policy
        user_id = monitor.user_id
        title = None
        base = await db.get(ResearchProject, baseline_id)
        title = base.title if base else "your research"

    notifiable_keys = {c.dedup_key for c in notifiable}
    notification_id = None
    max_impact = significance.max_impact(notifiable or meaningful)

    if notifiable:
        summary, message = _compose_notification(title, notifiable)
        dedup_key = _combined_key(notifiable)
        notification_id = await notifications.notify(
            user_id, type="monitor_alert", title=summary, message=message,
            project_id=new_run_id, severity=max_impact, monitor_id=monitor_id,
            dedup_key=dedup_key,
            data={
                "baseline_run_id": baseline_id,
                "new_run_id": new_run_id,
                "root_id": root_id,
                "changes": [c.to_dict() for c in notifiable],
            },
        )

    # Persist every meaningful change; flag which ones were actually delivered so
    # future checks can dedup against them (spec §17).
    change_dicts = []
    for c in meaningful:
        d = c.to_dict()
        d["notified"] = c.dedup_key in notifiable_keys
        change_dicts.append(d)

    status = "changes" if notifiable else "suppressed"
    check_id = await _add_check(
        monitor_id=monitor_id, root_id=root_id, baseline_run_id=baseline_id,
        new_run_id=new_run_id, status=status, provenance_mode=probe.provenance_mode,
        meaningful_changes=change_dicts, suppressed_count=len(meaningful) - len(notifiable),
        notification_id=notification_id, source_health=source_health, max_impact=max_impact,
        escalated=True, started_at=started, finished_at=_now(),
    )

    async with SessionLocal() as db:
        monitor = await db.get(ResearchMonitor, monitor_id)
        monitor.last_status = status
        monitor.last_success_at = _now()
        monitor.last_run_id = new_run_id  # advance baseline to the newest verified run
        monitor.consecutive_failures = 0
        monitor.last_error = None
        monitor.check_count = (monitor.check_count or 0) + 1
        monitor.next_check_at = _next_after_success(monitor)
        await db.commit()
    return {"status": status, "check_id": check_id, "notification_id": notification_id,
            "notifiable": len(notifiable), "meaningful": len(meaningful)}


async def _record_failure(monitor_id, started, category, detail, new_run_id=None) -> dict:
    async with SessionLocal() as db:
        monitor = await db.get(ResearchMonitor, monitor_id)
        if monitor is None:
            return {"status": "failed"}
        monitor.consecutive_failures = (monitor.consecutive_failures or 0) + 1
        monitor.failure_count = (monitor.failure_count or 0) + 1
        monitor.check_count = (monitor.check_count or 0) + 1
        monitor.last_status = "failed"
        monitor.last_error = category  # category only — never a payload (privacy §33)
        monitor.next_check_at = _next_after_failure(monitor)
        root_id = monitor.root_id
        await db.commit()
    check_id = await _add_check(
        monitor_id=monitor_id, root_id=root_id, baseline_run_id=None, new_run_id=new_run_id,
        status="failed", provenance_mode="unknown", meaningful_changes=[],
        suppressed_count=0, detail=detail, max_impact=None, escalated=bool(new_run_id),
        started_at=started, finished_at=_now(),
    )
    return {"status": "failed", "check_id": check_id, "error": category}


# --------------------------------------------------------------------------- #
# Notification composition (in-app only; no passages/secrets — privacy §33)
# --------------------------------------------------------------------------- #
_IMPACT_ICON = {"critical": "⚠", "high": "⚠", "medium": "•", "low": "·"}


def _compose_notification(research_title: str, changes: list) -> tuple[str, str]:
    n = len(changes)
    top = significance.max_impact(changes)
    summary = f"Research update: {research_title}"
    lines = [f"{n} meaningful change{'s' if n != 1 else ''} detected "
             f"(highest impact: {top})."]
    for c in changes[:6]:
        icon = _IMPACT_ICON.get(c.impact, "•")
        lines.append(f"{icon} {c.impact.upper()} — {c.title}: {c.detail}")
    if n > 6:
        lines.append(f"…and {n - 6} more.")
    return summary, "\n".join(lines)


def _combined_key(changes: list) -> str:
    joined = "|".join(sorted(c.dedup_key for c in changes))
    return hashlib.sha1(joined.encode("utf-8")).hexdigest()[:32]


# --------------------------------------------------------------------------- #
# Poller (shares the scheduler loop; spec §34)
# --------------------------------------------------------------------------- #
def _launch(monitor_id: str) -> None:
    task = asyncio.create_task(run_monitor_check(monitor_id))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


async def run_due_once() -> int:
    """Launch checks for every monitor due right now, bounded by the concurrency cap and
    skipping any already running (spec §35). Returns how many were launched. Non-blocking:
    each check runs as its own background task so the poller returns immediately."""
    settings = get_settings()
    if not settings.monitor_enabled:
        return 0
    now = _now()
    launched = 0
    stale_before = now - timedelta(minutes=settings.monitor_stale_running_minutes)
    async with SessionLocal() as db:
        rows = (
            await db.execute(
                select(ResearchMonitor)
                .where(ResearchMonitor.enabled.is_(True))
                .where(ResearchMonitor.next_check_at <= now)
                .order_by(ResearchMonitor.next_check_at)
            )
        ).scalars().all()
        for monitor in rows:
            if monitor.id in _running:
                continue  # already running in this process (spec §35)
            # Reclaim a check that died mid-run (status stuck on "running"; spec §34).
            if monitor.last_status == "running" and monitor.last_checked_at and \
                    _aware(monitor.last_checked_at) > stale_before:
                continue
            if len(_running) + launched >= settings.monitor_max_concurrent_checks:
                break  # cap concurrent LLM-heavy checks; the rest wait for the next tick
            # Advance the cadence immediately so a slow check isn't re-launched next tick.
            monitor.next_check_at = now + timedelta(minutes=max(1, monitor.interval_minutes))
            await db.commit()
            _launch(monitor.id)
            launched += 1
    return launched

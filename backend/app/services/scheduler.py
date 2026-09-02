"""In-process scheduler for recurring/one-off research (spec §11).

A single asyncio task polls the `scheduled_research` table for due entries and
spawns a real research project (owned by the schedule's user) for each. This is
the "lean local" stand-in for a Celery/Redis beat worker and lives behind the
same seam — swap `SchedulerService` without touching the API or model.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.config import get_settings
from app.database import SessionLocal
from app.models import ProjectStatus, ResearchProject, ScheduledResearch
from app.services import notifications
from app.services.research_service import manager

log = logging.getLogger("researchmind.scheduler")


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _create_and_start(db, sched: ScheduledResearch, *, advance_cadence: bool) -> str:
    """Create + start a research project from a schedule.

    Assumes the caller holds an open session `db` and will commit. When
    `advance_cadence` is True (automatic firing) the schedule's next run time is
    moved forward / disabled; a manual "run now" passes False so the cadence is
    left untouched.
    """
    proj = ResearchProject(
        user_id=sched.user_id,
        title=sched.title or sched.query[:120],
        query=sched.query,
        mode=sched.mode,
        constraints=dict(sched.constraints or {}),
        sources_enabled=list(sched.sources_enabled or ["web"]),
        status=ProjectStatus.CREATED,
    )
    db.add(proj)
    await db.flush()  # assign proj.id

    now = _now()
    sched.last_run_at = now
    sched.last_project_id = proj.id
    sched.run_count = (sched.run_count or 0) + 1
    if advance_cadence:
        if sched.kind == "interval" and sched.interval_minutes:
            sched.next_run_at = now + timedelta(minutes=sched.interval_minutes)
        else:  # one-off: fire once, then disable
            sched.enabled = False
    await db.commit()

    # Kick off the background run (outside the DB write above).
    manager.start(proj.id)
    await notifications.notify(
        sched.user_id, type="schedule_run", project_id=proj.id,
        title="Scheduled research started",
        message=f"“{sched.title}” started automatically.",
    )
    return proj.id


async def _spawn_from_schedule(db, sched: ScheduledResearch) -> str:
    """Manual trigger ("run now"): start a run without changing the cadence."""
    return await _create_and_start(db, sched, advance_cadence=False)


async def run_due_once() -> int:
    """Spawn every schedule that is due right now. Returns how many fired."""
    now = _now()
    fired = 0
    async with SessionLocal() as db:
        rows = (
            await db.execute(
                select(ScheduledResearch)
                .where(ScheduledResearch.enabled.is_(True))
                .where(ScheduledResearch.next_run_at <= now)
                .order_by(ScheduledResearch.next_run_at)
            )
        ).scalars().all()
        for sched in rows:
            try:
                await _create_and_start(db, sched, advance_cadence=True)
                fired += 1
            except Exception:  # noqa: BLE001 - one bad schedule mustn't stop others
                log.exception("Failed to spawn scheduled research %s", sched.id)
                await db.rollback()
    return fired


class SchedulerService:
    def __init__(self) -> None:
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        settings = get_settings()
        if not settings.scheduler_enabled or (self._task and not self._task.done()):
            return
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._task = None

    async def _loop(self) -> None:
        poll = max(5, get_settings().scheduler_poll_seconds)
        while True:
            try:
                await run_due_once()
            except Exception:  # noqa: BLE001 - keep the loop alive
                log.exception("Scheduler tick failed")
            # Research monitoring (#6) shares this single poller — no separate scheduler
            # (spec §34). A failure here must not stop scheduled research or the loop.
            try:
                from app.services import research_monitor

                await research_monitor.run_due_once()
            except Exception:  # noqa: BLE001 - keep the loop alive
                log.exception("Monitor tick failed")
            await asyncio.sleep(poll)


scheduler = SchedulerService()

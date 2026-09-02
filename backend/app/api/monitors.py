"""Research monitoring API (#6, spec §31). Ownership-enforced through the lineage's
project; one monitor per research lineage (``root_id``)."""
from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.research import _get_project
from app.config import get_settings
from app.database import get_db
from app.models import MonitorCheck, ProjectStatus, ResearchMonitor, ResearchProject, User
from app.schemas.monitoring import (
    MonitorCheckOut,
    MonitorCreate,
    MonitorDetail,
    MonitorOut,
    MonitorUpdate,
)
from app.schemas.research import MessageOut
from app.security.auth import get_current_user
from app.services import audit, research_monitor

router = APIRouter(prefix="/research", tags=["monitoring"])


def _interval_for(frequency: str, interval_minutes: int | None) -> int:
    settings = get_settings()
    minutes = interval_minutes or research_monitor.frequency_to_minutes(frequency)
    return max(minutes, settings.min_schedule_interval_minutes)


async def _get_monitor(db: AsyncSession, root_id: str, user: User) -> ResearchMonitor | None:
    return (
        await db.execute(
            select(ResearchMonitor)
            .where(ResearchMonitor.root_id == root_id)
            .where(ResearchMonitor.user_id == user.id)
        )
    ).scalars().first()


async def _latest_completed_id(db: AsyncSession, root_id: str) -> str | None:
    row = (
        await db.execute(
            select(ResearchProject)
            .where(ResearchProject.root_id == root_id)
            .where(ResearchProject.status == ProjectStatus.COMPLETED)
            .order_by(ResearchProject.run_number.desc())
        )
    ).scalars().first()
    return row.id if row else None


@router.post("/{project_id}/monitor", response_model=MonitorOut, status_code=201)
async def create_monitor(
    project_id: str,
    body: MonitorCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Create (or re-enable/reconfigure) a monitor for a research lineage. Requires at
    least one COMPLETED run in the lineage to have a baseline to diff against (spec §29)."""
    proj = await _get_project(db, project_id, user)
    root_id = proj.root_id or proj.id
    baseline_id = await _latest_completed_id(db, root_id)
    if baseline_id is None:
        raise HTTPException(409, "This research has no completed run to monitor yet")

    interval = _interval_for(body.frequency, body.interval_minutes)
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    next_check = now if body.start == "now" else now + timedelta(minutes=interval)

    monitor = await _get_monitor(db, root_id, user)
    if monitor is None:
        monitor = ResearchMonitor(
            user_id=user.id, root_id=root_id, project_id=proj.id,
            enabled=True, frequency=body.frequency, interval_minutes=interval,
            source_policy=body.source_policy, notify_policy=body.notify_policy,
            last_run_id=baseline_id, next_check_at=next_check, last_status="idle",
        )
        db.add(monitor)
    else:  # upsert — never create a duplicate monitor for the same lineage
        monitor.enabled = True
        monitor.frequency = body.frequency
        monitor.interval_minutes = interval
        monitor.source_policy = body.source_policy
        monitor.notify_policy = body.notify_policy
        monitor.last_run_id = monitor.last_run_id or baseline_id
        monitor.next_check_at = next_check
        monitor.consecutive_failures = 0
        monitor.last_error = None
    await db.commit()
    await db.refresh(monitor)
    await audit.record("monitor.create", project_id=proj.id, user_id=user.id, request=request,
                       detail={"frequency": body.frequency, "notify_policy": body.notify_policy})
    return monitor


@router.get("/{project_id}/monitor", response_model=MonitorDetail)
async def get_monitor(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    proj = await _get_project(db, project_id, user)
    root_id = proj.root_id or proj.id
    monitor = await _get_monitor(db, root_id, user)
    if monitor is None:
        raise HTTPException(404, "No monitor configured for this research")
    checks = (
        await db.execute(
            select(MonitorCheck)
            .where(MonitorCheck.monitor_id == monitor.id)
            .order_by(MonitorCheck.created_at.desc())
            .limit(get_settings().monitor_history_limit)
        )
    ).scalars().all()
    return MonitorDetail(
        monitor=MonitorOut.model_validate(monitor),
        recent_checks=[MonitorCheckOut.model_validate(c) for c in checks],
    )


@router.patch("/{project_id}/monitor", response_model=MonitorOut)
async def update_monitor(
    project_id: str,
    body: MonitorUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    proj = await _get_project(db, project_id, user)
    root_id = proj.root_id or proj.id
    monitor = await _get_monitor(db, root_id, user)
    if monitor is None:
        raise HTTPException(404, "No monitor configured for this research")

    data = body.model_dump(exclude_unset=True)
    if "frequency" in data or "interval_minutes" in data:
        freq = data.get("frequency", monitor.frequency)
        monitor.frequency = freq
        monitor.interval_minutes = _interval_for(freq, data.get("interval_minutes"))
    for f in ("enabled", "source_policy", "notify_policy"):
        if f in data:
            setattr(monitor, f, data[f])
    await db.commit()
    await db.refresh(monitor)
    return monitor


@router.delete("/{project_id}/monitor", response_model=MessageOut)
async def delete_monitor(
    project_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    proj = await _get_project(db, project_id, user)
    root_id = proj.root_id or proj.id
    monitor = await _get_monitor(db, root_id, user)
    if monitor is None:
        raise HTTPException(404, "No monitor configured for this research")
    # Remove the monitor and its history (checks reference it by id).
    checks = (
        await db.execute(select(MonitorCheck).where(MonitorCheck.monitor_id == monitor.id))
    ).scalars().all()
    for c in checks:
        await db.delete(c)
    await db.delete(monitor)
    await db.commit()
    await audit.record("monitor.delete", project_id=proj.id, user_id=user.id, request=request)
    return MessageOut(message="Monitor removed")


@router.post("/{project_id}/monitor/run", response_model=MessageOut)
async def run_monitor_now(
    project_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Run a check now using the same pipeline — no duplicate schedule (spec §30). The
    check runs in the background; watch the notification center / monitor history."""
    proj = await _get_project(db, project_id, user)
    root_id = proj.root_id or proj.id
    monitor = await _get_monitor(db, root_id, user)
    if monitor is None:
        raise HTTPException(404, "No monitor configured for this research")
    if monitor.id in research_monitor._running:
        return MessageOut(message="A check is already running", ok=False)
    research_monitor._launch(monitor.id)
    await audit.record("monitor.run_now", project_id=proj.id, user_id=user.id, request=request)
    return MessageOut(message="Monitoring check started", ok=True)


@router.get("/{project_id}/monitor/checks", response_model=list[MonitorCheckOut])
async def get_monitor_checks(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Monitoring history — part of research memory (spec §26)."""
    proj = await _get_project(db, project_id, user)
    root_id = proj.root_id or proj.id
    monitor = await _get_monitor(db, root_id, user)
    if monitor is None:
        raise HTTPException(404, "No monitor configured for this research")
    checks = (
        await db.execute(
            select(MonitorCheck)
            .where(MonitorCheck.monitor_id == monitor.id)
            .order_by(MonitorCheck.created_at.desc())
            .limit(get_settings().monitor_history_limit)
        )
    ).scalars().all()
    return checks

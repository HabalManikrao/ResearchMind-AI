"""Scheduled research CRUD (spec §11). All schedules are user-scoped."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.models import ScheduledResearch, User
from app.schemas.research import MessageOut
from app.schemas.scheduling import ScheduleCreate, ScheduleOut, ScheduleUpdate
from app.security.auth import get_current_user
from app.services import audit
from app.services.scheduler import _spawn_from_schedule

router = APIRouter(
    prefix="/schedules", tags=["schedules"], dependencies=[Depends(get_current_user)]
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _get_owned(db: AsyncSession, schedule_id: str, user: User) -> ScheduledResearch:
    sched = await db.get(ScheduledResearch, schedule_id)
    if sched is None or sched.user_id != user.id:
        raise HTTPException(404, "Schedule not found")
    return sched


@router.post("", response_model=ScheduleOut, status_code=201)
async def create_schedule(
    body: ScheduleCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    settings = get_settings()
    interval = body.interval_minutes
    if body.kind == "interval":
        if not interval:
            raise HTTPException(422, "interval_minutes is required for an interval schedule")
        interval = max(interval, settings.min_schedule_interval_minutes)
        next_run = body.start_at or _now()
    else:  # once
        if not body.start_at:
            raise HTTPException(422, "start_at is required for a one-off schedule")
        next_run = body.start_at
    # Normalize any naive datetime to UTC-aware.
    if next_run.tzinfo is None:
        next_run = next_run.replace(tzinfo=timezone.utc)

    sched = ScheduledResearch(
        user_id=user.id,
        title=body.title or body.query[:120],
        query=body.query,
        mode=body.mode,
        sources_enabled=body.sources_enabled or ["web"],
        constraints=body.constraints,
        kind=body.kind,
        interval_minutes=interval,
        next_run_at=next_run,
    )
    db.add(sched)
    await db.commit()
    await db.refresh(sched)
    await audit.record("schedule.create", user_id=user.id, request=request,
                       detail={"kind": sched.kind, "interval_minutes": sched.interval_minutes})
    return sched


@router.get("", response_model=list[ScheduleOut])
async def list_schedules(
    db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
):
    rows = (
        await db.execute(
            select(ScheduledResearch)
            .where(ScheduledResearch.user_id == user.id)
            .order_by(ScheduledResearch.created_at.desc())
        )
    ).scalars().all()
    return rows


@router.get("/{schedule_id}", response_model=ScheduleOut)
async def get_schedule(
    schedule_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return await _get_owned(db, schedule_id, user)


@router.patch("/{schedule_id}", response_model=ScheduleOut)
async def update_schedule(
    schedule_id: str,
    body: ScheduleUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    sched = await _get_owned(db, schedule_id, user)
    settings = get_settings()
    data = body.model_dump(exclude_unset=True)
    if "interval_minutes" in data and data["interval_minutes"] is not None:
        data["interval_minutes"] = max(
            data["interval_minutes"], settings.min_schedule_interval_minutes
        )
    if "next_run_at" in data and data["next_run_at"] is not None:
        nr = data["next_run_at"]
        if nr.tzinfo is None:
            data["next_run_at"] = nr.replace(tzinfo=timezone.utc)
    for field, value in data.items():
        setattr(sched, field, value)
    await db.commit()
    await db.refresh(sched)
    return sched


@router.delete("/{schedule_id}", response_model=MessageOut)
async def delete_schedule(
    schedule_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    sched = await _get_owned(db, schedule_id, user)
    await db.delete(sched)
    await db.commit()
    await audit.record("schedule.delete", user_id=user.id, request=request)
    return MessageOut(message="Schedule deleted")


@router.post("/{schedule_id}/run-now", response_model=MessageOut)
async def run_now(
    schedule_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    sched = await _get_owned(db, schedule_id, user)
    project_id = await _spawn_from_schedule(db, sched)
    await audit.record("schedule.run_now", project_id=project_id, user_id=user.id,
                       request=request)
    return MessageOut(message="Research started", ok=True)

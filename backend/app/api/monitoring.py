"""Monitoring & observability endpoints (spec §10 Monitoring nav)."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import (
    AuditLog,
    Claim,
    Conflict,
    ProjectStatus,
    ResearchProject,
    Source,
)
from app.security.auth import get_current_user
from app.services.research_service import manager

router = APIRouter(
    prefix="/monitoring", tags=["monitoring"], dependencies=[Depends(get_current_user)]
)


@router.get("/stats")
async def stats(db: AsyncSession = Depends(get_db)):
    # Projects grouped by status.
    rows = (
        await db.execute(
            select(ResearchProject.status, func.count()).group_by(ResearchProject.status)
        )
    ).all()
    by_status = {status.value: count for status, count in rows}
    total_projects = sum(by_status.values())

    async def _count(model) -> int:
        return (await db.execute(select(func.count()).select_from(model))).scalar_one()

    return {
        "projects": {
            "total": total_projects,
            "by_status": by_status,
            "completed": by_status.get(ProjectStatus.COMPLETED.value, 0),
            "active_runs": len(manager.active_ids()),
        },
        "totals": {
            "sources": await _count(Source),
            "claims": await _count(Claim),
            "conflicts": await _count(Conflict),
        },
    }


@router.get("/audit")
async def audit_log(limit: int = 50, db: AsyncSession = Depends(get_db)):
    rows = (
        await db.execute(
            select(AuditLog).order_by(AuditLog.created_at.desc()).limit(min(limit, 200))
        )
    ).scalars().all()
    return [
        {
            "id": r.id,
            "action": r.action,
            "project_id": r.project_id,
            "client_ip": r.client_ip,
            "detail": r.detail,
            "created_at": r.created_at,
        }
        for r in rows
    ]

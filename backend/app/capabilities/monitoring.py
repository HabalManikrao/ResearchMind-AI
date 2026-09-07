"""Monitoring capabilities (#8): read-only status + change history, reusing the #6 monitor
service and the single ownership-scoped read path (spec §15, §55). No mutation here — create/
update stays on the internal endpoints that already validate cadence and prevent duplicates."""
from __future__ import annotations

from fastapi import HTTPException

from app.api import monitors as mapi
from app.capabilities.base import map_http_error
from app.database import SessionLocal


async def status(user, project_id: str) -> dict:
    async with SessionLocal() as db:
        try:
            detail = await mapi.get_monitor(project_id, db=db, user=user)
        except HTTPException as e:
            raise map_http_error(e)
    return detail.model_dump()


async def changes(user, project_id: str) -> dict:
    async with SessionLocal() as db:
        try:
            checks = await mapi.get_monitor_checks(project_id, db=db, user=user)
        except HTTPException as e:
            raise map_http_error(e)
    return {"project_id": project_id, "checks": [c.model_dump() for c in checks]}

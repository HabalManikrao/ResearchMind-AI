"""Audit logging helper (spec §21).

Records significant actions to the audit_logs table. Failures here must never break
the request, so callers use a fresh session and swallow errors.
"""
from __future__ import annotations

from fastapi import Request

from app.database import SessionLocal
from app.models import AuditLog


async def record(
    action: str,
    *,
    project_id: str | None = None,
    user_id: str | None = None,
    request: Request | None = None,
    detail: dict | None = None,
) -> None:
    client_ip = None
    if request is not None and request.client:
        client_ip = request.client.host
    try:
        async with SessionLocal() as db:
            db.add(
                AuditLog(
                    action=action,
                    project_id=project_id,
                    user_id=user_id,
                    client_ip=client_ip,
                    detail=detail or {},
                )
            )
            await db.commit()
    except Exception:
        pass  # auditing must never fail the request

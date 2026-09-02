"""Notification helper (spec §11; extended for monitoring #6).

Creates in-app notifications for a user. Like audit logging, this uses its own session
and swallows errors so it can never break a research run or a monitoring check. In-app
only — nothing is sent to external providers (privacy §33, non-goal §40).
"""
from __future__ import annotations

from app.database import SessionLocal
from app.models import Notification


async def notify(
    user_id: str | None,
    *,
    type: str,
    title: str,
    message: str = "",
    project_id: str | None = None,
    severity: str | None = None,
    monitor_id: str | None = None,
    dedup_key: str | None = None,
    data: dict | None = None,
) -> str | None:
    """Create a notification and return its id (or None if skipped/failed).

    ``severity``/``monitor_id``/``dedup_key``/``data`` are the monitoring extensions (#6):
    a monitor alert carries its impact level and a structured pointer to the relevant diff
    so the UI can open it. ``data`` must never contain document passages, secrets, or
    credentials (privacy §33) — callers pass change summaries only.
    """
    # Notifications are addressed to a user; skip if the project is unowned.
    if not user_id:
        return None
    try:
        async with SessionLocal() as db:
            notif = Notification(
                user_id=user_id,
                type=type,
                title=title,
                message=message,
                project_id=project_id,
                severity=severity,
                monitor_id=monitor_id,
                dedup_key=dedup_key,
                data=data,
            )
            db.add(notif)
            await db.commit()
            return notif.id
    except Exception:
        return None  # notifications must never fail the caller

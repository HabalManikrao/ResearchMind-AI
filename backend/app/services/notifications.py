"""Notification helper (spec §11).

Creates in-app notifications for a user. Like audit logging, this uses its own
session and swallows errors so it can never break a research run.
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
) -> None:
    # Notifications are addressed to a user; skip if the project is unowned.
    if not user_id:
        return
    try:
        async with SessionLocal() as db:
            db.add(
                Notification(
                    user_id=user_id,
                    type=type,
                    title=title,
                    message=message,
                    project_id=project_id,
                )
            )
            await db.commit()
    except Exception:
        pass  # notifications must never fail the caller

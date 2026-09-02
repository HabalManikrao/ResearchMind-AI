"""User notifications (spec §11 — notify on run completion/failure & schedules)."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Notification(Base):
    """An in-app notification addressed to a single user."""

    __tablename__ = "notifications"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(String(36), index=True)
    # e.g. research_completed | research_failed | schedule_run | monitor_alert | info
    type: Mapped[str] = mapped_column(String(50), default="info")
    title: Mapped[str] = mapped_column(String(300))
    message: Mapped[str] = mapped_column(Text, default="")
    project_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    read: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    # --- Research monitoring (#6): additive/nullable so pre-#6 rows stay valid. ---
    # Impact of the underlying change: low | medium | high | critical (null = not a
    # monitor alert). Lets the notification center rank and colour alerts (spec §12).
    severity: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # The monitor that raised this alert (null for research/schedule notifications).
    monitor_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    # Stable identifier of the underlying change set, for suppression of duplicates
    # across consecutive checks (spec §17). Content-derived, never random.
    dedup_key: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    # Structured payload the UI uses to open the relevant diff/evidence: baseline run,
    # new run, root, and the change list. Never contains passages/secrets (privacy §33).
    data: Mapped[dict | None] = mapped_column(JSON, nullable=True)

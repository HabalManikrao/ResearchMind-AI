"""Scheduled research (spec §11 — recurring/one-off automated runs).

A schedule is a saved research request plus a cadence. The in-process scheduler
(`app/services/scheduler.py`) polls for due schedules and spawns a real research
project owned by the same user.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Enum, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.enums import ResearchMode


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


class ScheduledResearch(Base):
    __tablename__ = "scheduled_research"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(String(36), index=True)
    title: Mapped[str] = mapped_column(String(500))
    query: Mapped[str] = mapped_column(Text)
    mode: Mapped[ResearchMode] = mapped_column(Enum(ResearchMode), default=ResearchMode.DEEP)
    sources_enabled: Mapped[list] = mapped_column(JSON, default=list)
    constraints: Mapped[dict] = mapped_column(JSON, default=dict)

    # Cadence. kind="interval" repeats every interval_minutes; kind="once" fires
    # a single time at next_run_at then disables itself.
    kind: Mapped[str] = mapped_column(String(20), default="interval")
    interval_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    next_run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, index=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_project_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    run_count: Mapped[int] = mapped_column(Integer, default=0)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )

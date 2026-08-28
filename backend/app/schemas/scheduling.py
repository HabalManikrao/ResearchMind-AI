"""Schemas for scheduled research and notifications."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import ResearchMode


class ScheduleCreate(BaseModel):
    query: str = Field(min_length=3)
    title: str | None = None
    mode: ResearchMode = ResearchMode.DEEP
    sources_enabled: list[str] = Field(default_factory=lambda: ["web"])
    constraints: dict = Field(default_factory=dict)
    kind: Literal["interval", "once"] = "interval"
    # Required for kind="interval"; floored server-side by MIN_SCHEDULE_INTERVAL_MINUTES.
    interval_minutes: int | None = Field(default=None, ge=1)
    # First fire time. Defaults to now (interval) — required for kind="once".
    start_at: datetime | None = None


class ScheduleUpdate(BaseModel):
    title: str | None = None
    query: str | None = Field(default=None, min_length=3)
    mode: ResearchMode | None = None
    sources_enabled: list[str] | None = None
    constraints: dict | None = None
    interval_minutes: int | None = Field(default=None, ge=1)
    next_run_at: datetime | None = None
    enabled: bool | None = None


class ScheduleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    query: str
    mode: ResearchMode
    sources_enabled: list
    constraints: dict
    kind: str
    interval_minutes: int | None
    next_run_at: datetime
    last_run_at: datetime | None
    last_project_id: str | None
    run_count: int
    enabled: bool
    created_at: datetime
    updated_at: datetime


class NotificationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    type: str
    title: str
    message: str
    project_id: str | None
    read: bool
    created_at: datetime


class UnreadCountOut(BaseModel):
    unread: int

"""Schemas for research monitoring (#6)."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class MonitorCreate(BaseModel):
    # Cadence: a human frequency (mapped to minutes server-side) OR an explicit interval.
    frequency: Literal["daily", "weekly", "monthly"] = "daily"
    interval_minutes: int | None = Field(default=None, ge=1)
    source_policy: str | None = Field(
        default=None, pattern="^(live_only|live_preferred|cache_allowed|local_only)$"
    )
    notify_policy: Literal["all", "important", "critical"] = "all"
    # "now" makes the first check due immediately; "scheduled" waits one interval.
    start: Literal["now", "scheduled"] = "scheduled"


class MonitorUpdate(BaseModel):
    enabled: bool | None = None
    frequency: Literal["daily", "weekly", "monthly"] | None = None
    interval_minutes: int | None = Field(default=None, ge=1)
    source_policy: str | None = Field(
        default=None, pattern="^(live_only|live_preferred|cache_allowed|local_only)$"
    )
    notify_policy: Literal["all", "important", "critical"] | None = None


class MonitorOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    root_id: str
    project_id: str
    enabled: bool
    frequency: str
    interval_minutes: int
    source_policy: str | None
    notify_policy: str
    last_run_id: str | None
    last_checked_at: datetime | None
    last_success_at: datetime | None
    next_check_at: datetime
    last_status: str
    health: str  # computed property on the model
    consecutive_failures: int
    failure_count: int
    check_count: int
    last_error: str | None
    created_at: datetime
    updated_at: datetime


class MonitorCheckOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    monitor_id: str
    baseline_run_id: str | None
    new_run_id: str | None
    status: str
    provenance_mode: str
    meaningful_changes: list
    suppressed_count: int
    notification_id: str | None
    source_health: dict | None
    detail: str | None
    max_impact: str | None
    escalated: bool
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime


class MonitorDetail(BaseModel):
    monitor: MonitorOut
    recent_checks: list[MonitorCheckOut]

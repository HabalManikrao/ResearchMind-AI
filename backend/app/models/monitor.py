"""Research monitoring (#6): watch a research lineage and alert on meaningful change.

A ``ResearchMonitor`` is attached to a research **lineage** (``root_id``) — reusing the
immutable-run model from #4 — plus a cadence, a source policy (#5), and a notification
policy. The in-process scheduler (``services/scheduler.py``) polls due monitors and runs
a check via ``services/research_monitor.py``. Each check is persisted as a
``MonitorCheck`` so monitoring history becomes part of research memory (spec §26).

Both tables are new (created by ``create_all``); nothing here migrates an existing table.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


class ResearchMonitor(Base):
    """Continuous-monitoring config for one research lineage (one per ``root_id``)."""

    __tablename__ = "research_monitors"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(String(36), index=True)  # owner (isolation)
    # The lineage being watched. A whole investigation is one root_id (#4); the baseline
    # run to diff against is the latest COMPLETED run in this lineage.
    root_id: Mapped[str] = mapped_column(String(36), index=True)
    project_id: Mapped[str] = mapped_column(String(36))  # seed/original project (back-ref)

    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    # Cadence. Human frequency (daily/weekly/monthly) is mapped to interval_minutes on
    # create; floored by min_schedule_interval_minutes. No sub-hourly (spec §5).
    frequency: Mapped[str] = mapped_column(String(20), default="daily")
    interval_minutes: Mapped[int] = mapped_column(Integer, default=1440)
    # Live/cached/local sourcing policy (#5). Null → default_source_policy.
    source_policy: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # Notification policy (spec §14): all (medium+) | important (high+) | critical.
    notify_policy: Mapped[str] = mapped_column(String(20), default="all")

    # Baseline run the next check diffs against (latest COMPLETED run in the lineage).
    last_run_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    last_checked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_success_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    next_check_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, index=True
    )
    # idle | running | healthy | no_change | changes | degraded | failed
    last_status: Mapped[str] = mapped_column(String(20), default="idle")
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0)
    failure_count: Mapped[int] = mapped_column(Integer, default=0)
    check_count: Mapped[int] = mapped_column(Integer, default=0)
    # Category only — never a stack trace or provider payload (privacy §33).
    last_error: Mapped[str | None] = mapped_column(String(200), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )

    @property
    def health(self) -> str:
        """Derived health for the UI (spec §21): DISABLED/FAILING/OFFLINE/DEGRADED/HEALTHY.
        Computed so it always reflects the latest counters, never stored stale."""
        if not self.enabled:
            return "disabled"
        if self.consecutive_failures >= 3:
            return "failing"
        if self.last_status == "degraded":
            return "degraded"
        if self.consecutive_failures > 0:
            return "degraded"
        return "healthy"


class MonitorCheck(Base):
    """One monitoring execution — the immutable record of what was detected (spec §16,
    §26). Cheap checks that found nothing still record a row (audit + "what changed over
    the last month"). ``meaningful_changes`` holds the significance output."""

    __tablename__ = "monitor_checks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    monitor_id: Mapped[str] = mapped_column(String(36), index=True)
    root_id: Mapped[str] = mapped_column(String(36), index=True)
    baseline_run_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    new_run_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    # no_change | changes | suppressed | degraded | failed
    status: Mapped[str] = mapped_column(String(20), default="no_change")
    # live | hybrid | cache | local | degraded — honest provenance of the comparison (#5).
    provenance_mode: Mapped[str] = mapped_column(String(20), default="unknown")
    # [{kind, impact, title, detail, dedup_key, refs}] — significance output.
    meaningful_changes: Mapped[list] = mapped_column(JSON, default=list)
    suppressed_count: Mapped[int] = mapped_column(Integer, default=0)
    notification_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    source_health: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Highest impact seen this check (low/medium/high/critical), for quick history display.
    max_impact: Mapped[str | None] = mapped_column(String(20), nullable=True)
    escalated: Mapped[bool] = mapped_column(Boolean, default=False)

    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

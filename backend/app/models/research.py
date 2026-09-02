"""Core research domain tables.

This is the MVP subset of the full schema in the master prompt (§17). Tables and
relationships are shaped so the remaining tables (conflicts, knowledge_gaps,
recommendations, knowledge_items, ...) can be added without migration churn.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.enums import (
    ClaimStatus,
    ConflictSeverity,
    ConflictStatus,
    EvidenceStance,
    ProjectStatus,
    ResearchMode,
    TaskStatus,
)
from app.services.freshness import freshness_state


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )


class ResearchProject(Base, TimestampMixin):
    __tablename__ = "research_projects"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    # Owner. Nullable so pre-auth ("legacy") projects remain readable; new projects
    # always carry an owner. ON DELETE SET NULL keeps research if an account is removed.
    user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # --- Research lineage (#4): a project IS a run. A "Research Again" forks a new
    # project linked to its parent, so completed runs stay immutable snapshots. ---
    # The run this one continued from (NULL for an original run).
    parent_id: Mapped[str | None] = mapped_column(
        ForeignKey("research_projects.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # First run in the lineage == the "investigation" id. Set to own id for originals;
    # inherited unchanged by every continuation, so a whole lineage is one indexed query.
    root_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    run_number: Mapped[int] = mapped_column(Integer, default=1)  # 1 = original, 2+ = continuation
    # How this run was created: original|refresh|deepen|verify|full.
    run_intent: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # Stamped once when the run reaches COMPLETED; an immutable-snapshot marker.
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Compact structured "research memory" record, built once at completion for reuse
    # by future runs and the memory endpoint (see orchestrator._build_memory_summary).
    memory_summary: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    title: Mapped[str] = mapped_column(String(500))
    query: Mapped[str] = mapped_column(Text)
    mode: Mapped[ResearchMode] = mapped_column(
        Enum(ResearchMode), default=ResearchMode.DEEP
    )
    status: Mapped[ProjectStatus] = mapped_column(
        Enum(ProjectStatus), default=ProjectStatus.CREATED, index=True
    )
    # Free-form constraints/preferences extracted from the request or provided by the user.
    constraints: Mapped[dict] = mapped_column(JSON, default=dict)
    # Selected source types, e.g. ["web", "github", ...]. MVP uses "web".
    sources_enabled: Mapped[list] = mapped_column(JSON, default=list)
    # Live/cached/local sourcing policy (#5). Nullable so pre-#5 runs default to
    # live_preferred at read time; see SourcePolicy. Resolved via _resolved_policy.
    source_policy: Mapped[str | None] = mapped_column(String(20), nullable=True)

    objective: Mapped[str | None] = mapped_column(Text, nullable=True)
    progress: Mapped[int] = mapped_column(Integer, default=0)  # 0-100
    current_stage: Mapped[str | None] = mapped_column(String(200), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Final report (markdown + structured metadata), populated at the end.
    report_markdown: Mapped[str | None] = mapped_column(Text, nullable=True)
    report_meta: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    questions: Mapped[list["ResearchQuestion"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    tasks: Mapped[list["ResearchTask"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    sources: Mapped[list["Source"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    findings: Mapped[list["Finding"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    claims: Mapped[list["Claim"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    conflicts: Mapped[list["Conflict"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    knowledge_gaps: Mapped[list["KnowledgeGap"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )


class ResearchQuestion(Base, TimestampMixin):
    __tablename__ = "research_questions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("research_projects.id", ondelete="CASCADE"), index=True
    )
    text: Mapped[str] = mapped_column(Text)
    priority: Mapped[int] = mapped_column(Integer, default=3)  # 1 (high) - 5 (low)
    is_followup: Mapped[bool] = mapped_column(default=False)
    answered: Mapped[bool] = mapped_column(default=False)

    project: Mapped[ResearchProject] = relationship(back_populates="questions")


class ResearchTask(Base, TimestampMixin):
    __tablename__ = "research_tasks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("research_projects.id", ondelete="CASCADE"), index=True
    )
    question_id: Mapped[str | None] = mapped_column(
        ForeignKey("research_questions.id", ondelete="SET NULL"), nullable=True
    )
    agent: Mapped[str] = mapped_column(String(50))  # source key: web|docs|github|papers|news|community
    description: Mapped[str] = mapped_column(Text)
    search_query: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[TaskStatus] = mapped_column(
        Enum(TaskStatus), default=TaskStatus.PENDING, index=True
    )
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    round: Mapped[int] = mapped_column(Integer, default=0)  # 0 = initial, 1+ = follow-up
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    project: Mapped[ResearchProject] = relationship(back_populates="tasks")


class Source(Base, TimestampMixin):
    __tablename__ = "sources"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("research_projects.id", ondelete="CASCADE"), index=True
    )
    task_id: Mapped[str | None] = mapped_column(
        ForeignKey("research_tasks.id", ondelete="SET NULL"), nullable=True
    )
    title: Mapped[str] = mapped_column(String(1000))
    url: Mapped[str] = mapped_column(String(2000), index=True)
    source_type: Mapped[str] = mapped_column(String(50), default="web")
    publisher: Mapped[str | None] = mapped_column(String(500), nullable=True)
    published_date: Mapped[str | None] = mapped_column(String(50), nullable=True)
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    reliability_score: Mapped[float] = mapped_column(Float, default=50.0)
    relevance_score: Mapped[float] = mapped_column(Float, default=0.0)
    # Source-type-specific structured fields (repo stars/forks, paper authors, etc.).
    meta: Mapped[dict] = mapped_column(JSON, default=dict)

    project: Mapped[ResearchProject] = relationship(back_populates="sources")

    @property
    def freshness(self) -> str:
        """Freshness state (fresh/aging/stale/unknown) for this source's type,
        judged against today. Computed, not stored, so it stays current."""
        return freshness_state(self.published_date, self.source_type)

    @property
    def provenance(self) -> str:
        """Where this evidence came from — live_web/cached_web/local_document/…
        Read from the stamp placed at collection time (#5); never inferred."""
        from app.services.provenance import provenance_of

        return provenance_of(self.source_type, self.meta)

    @property
    def availability(self) -> str:
        """Display state (live/cached/local/stale/unknown) derived from provenance +
        freshness. Computed so it always reflects current freshness (#5)."""
        from app.services.provenance import availability_of

        return availability_of(self.provenance, self.freshness)


class Finding(Base, TimestampMixin):
    __tablename__ = "findings"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("research_projects.id", ondelete="CASCADE"), index=True
    )
    source_id: Mapped[str | None] = mapped_column(
        ForeignKey("sources.id", ondelete="SET NULL"), nullable=True
    )
    question_id: Mapped[str | None] = mapped_column(
        ForeignKey("research_questions.id", ondelete="SET NULL"), nullable=True
    )
    text: Mapped[str] = mapped_column(Text)
    relevance_score: Mapped[float] = mapped_column(Float, default=0.0)

    project: Mapped[ResearchProject] = relationship(back_populates="findings")


class Claim(Base, TimestampMixin):
    __tablename__ = "claims"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("research_projects.id", ondelete="CASCADE"), index=True
    )
    text: Mapped[str] = mapped_column(Text)
    status: Mapped[ClaimStatus] = mapped_column(
        Enum(ClaimStatus), default=ClaimStatus.UNVERIFIED
    )
    confidence: Mapped[float] = mapped_column(Float, default=0.0)  # 0-100
    # List of source ids supporting the claim. Kept for backward compatibility and
    # for the knowledge-graph builder; the authoritative evidence links (with
    # stance + passage) live in the ``evidence`` relationship (ClaimSource rows).
    supporting_source_ids: Mapped[list] = mapped_column(JSON, default=list)
    # Transparent breakdown of how the confidence/status was derived: source count,
    # contradiction count, average reliability, aggregate freshness, and a list of
    # human-readable reasons the UI shows to explain "why this confidence".
    confidence_meta: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    project: Mapped[ResearchProject] = relationship(back_populates="claims")
    # passive_deletes: on parent delete, don't lazy-load children (async-unsafe);
    # the orchestrator deletes evidence links explicitly before replacing claims.
    evidence: Mapped[list["ClaimSource"]] = relationship(
        back_populates="claim", cascade="all, delete-orphan", passive_deletes=True
    )

    @property
    def evidence_state(self) -> str:
        """Display state for the UI: supported / weak / conflicting / outdated /
        unverified. Derived from status + the confidence breakdown so the badge
        reflects contradictions and staleness, not just the raw claim status."""
        meta = self.confidence_meta or {}
        if self.status == ClaimStatus.CONFLICTED or meta.get("contradiction_count"):
            return "conflicting"
        if meta.get("outdated"):
            return "outdated"
        if self.status == ClaimStatus.VERIFIED:
            return "supported"
        if self.status == ClaimStatus.PARTIALLY_VERIFIED:
            return "weak"
        return "unverified"


class ClaimSource(Base, TimestampMixin):
    """Evidence link: which source supports (or contradicts) a claim, with the
    quoted passage that is the evidence (spec §6 claim-to-source mapping).

    This is the authoritative, referential-integrity-backed evidence graph edge.
    ``claims.supporting_source_ids`` is kept as a denormalised mirror for the
    knowledge-graph builder and older readers.
    """

    __tablename__ = "claim_sources"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    claim_id: Mapped[str] = mapped_column(
        ForeignKey("claims.id", ondelete="CASCADE"), index=True
    )
    source_id: Mapped[str] = mapped_column(
        ForeignKey("sources.id", ondelete="CASCADE"), index=True
    )
    stance: Mapped[EvidenceStance] = mapped_column(
        Enum(EvidenceStance), default=EvidenceStance.SUPPORTS
    )
    # The specific quoted evidence from the source that bears on the claim.
    passage: Mapped[str | None] = mapped_column(Text, nullable=True)

    claim: Mapped["Claim"] = relationship(back_populates="evidence")
    source: Mapped["Source"] = relationship()


class Conflict(Base, TimestampMixin):
    __tablename__ = "conflicts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("research_projects.id", ondelete="CASCADE"), index=True
    )
    statement_a: Mapped[str] = mapped_column(Text)
    statement_b: Mapped[str] = mapped_column(Text)
    explanation: Mapped[str] = mapped_column(Text)
    severity: Mapped[ConflictSeverity] = mapped_column(
        Enum(ConflictSeverity), default=ConflictSeverity.MEDIUM
    )
    status: Mapped[ConflictStatus] = mapped_column(
        Enum(ConflictStatus), default=ConflictStatus.NEEDS_VERIFICATION
    )
    # Source ids implicated on each side, for traceability.
    source_ids: Mapped[list] = mapped_column(JSON, default=list)

    project: Mapped[ResearchProject] = relationship(back_populates="conflicts")


class Solution(Base, TimestampMixin):
    """A candidate technology/approach identified for comparison (spec §5 R&D)."""

    __tablename__ = "solutions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("research_projects.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(500))
    description: Mapped[str] = mapped_column(Text, default="")
    pros: Mapped[list] = mapped_column(JSON, default=list)
    cons: Mapped[list] = mapped_column(JSON, default=list)
    risks: Mapped[list] = mapped_column(JSON, default=list)
    # [{"criterion": str, "rating": str}] — per-dimension assessment.
    scores: Mapped[list] = mapped_column(JSON, default=list)
    is_recommended: Mapped[bool] = mapped_column(default=False)

    project: Mapped[ResearchProject] = relationship()


class Recommendation(Base, TimestampMixin):
    """The single evidence-based recommendation for a project (spec §13)."""

    __tablename__ = "recommendations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("research_projects.id", ondelete="CASCADE"), index=True
    )
    recommended_option: Mapped[str] = mapped_column(String(500), default="")
    rationale: Mapped[str] = mapped_column(Text, default="")
    why: Mapped[str] = mapped_column(Text, default="")
    confidence: Mapped[float] = mapped_column(Float, default=0.0)  # 0-100
    alternatives: Mapped[list] = mapped_column(JSON, default=list)  # list[str]
    risks: Mapped[list] = mapped_column(JSON, default=list)  # list[str]
    proof_of_concept: Mapped[str] = mapped_column(Text, default="")
    roadmap: Mapped[list] = mapped_column(JSON, default=list)  # [{"step","detail"}]

    project: Mapped[ResearchProject] = relationship()


class AuditLog(Base):
    """Immutable audit trail of significant actions (spec §21)."""

    __tablename__ = "audit_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    action: Mapped[str] = mapped_column(String(80), index=True)
    project_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    user_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    client_ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    detail: Mapped[dict] = mapped_column(JSON, default=dict)


class KnowledgeGap(Base, TimestampMixin):
    __tablename__ = "knowledge_gaps"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("research_projects.id", ondelete="CASCADE"), index=True
    )
    question: Mapped[str] = mapped_column(Text)
    reason: Mapped[str] = mapped_column(Text, default="")
    followup_query: Mapped[str] = mapped_column(Text, default="")
    round: Mapped[int] = mapped_column(Integer, default=0)
    resolved: Mapped[bool] = mapped_column(default=False)

    project: Mapped[ResearchProject] = relationship(back_populates="knowledge_gaps")

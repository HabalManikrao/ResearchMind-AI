"""R&D layer — research front matter (Phase A): Brief, Objectives, Constraints, Terminology.

All tables are additive, created by `create_all`, and carry `project_id` (FK, CASCADE) so they
inherit the project's ownership boundary (`_get_project`). String status/type fields are validated
at the schema layer against the sets in `enums.py` — no Enum columns, so new members need no
migration. `ResearchBrief` is 1:1 with a project (unique `project_id`) and is version-aware
(`version` bumps on each edit; history preservation of prior versions is Phase F).
"""
from __future__ import annotations

import uuid

from sqlalchemy import JSON, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.research import TimestampMixin


def _uuid() -> str:
    return str(uuid.uuid4())


class ResearchBrief(Base, TimestampMixin):
    """Structured, editable, version-aware research brief (1:1 with a project)."""

    __tablename__ = "research_briefs"
    __table_args__ = (UniqueConstraint("project_id", name="uq_brief_project"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("research_projects.id", ondelete="CASCADE"), index=True
    )
    problem_statement: Mapped[str] = mapped_column(Text, default="")
    background: Mapped[str] = mapped_column(Text, default="")
    expected_outcome: Mapped[str] = mapped_column(Text, default="")
    # JSON list columns (structured, not free-form prose).
    scope_included: Mapped[list] = mapped_column(JSON, default=list)
    scope_excluded: Mapped[list] = mapped_column(JSON, default=list)
    assumptions: Mapped[list] = mapped_column(JSON, default=list)
    target_users: Mapped[list] = mapped_column(JSON, default=list)
    success_criteria: Mapped[list] = mapped_column(JSON, default=list)
    version: Mapped[int] = mapped_column(Integer, default=1)


class Objective(Base, TimestampMixin):
    """A first-class research objective with progress + question links."""

    __tablename__ = "objectives"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("research_projects.id", ondelete="CASCADE"), index=True
    )
    description: Mapped[str] = mapped_column(Text)
    priority: Mapped[int] = mapped_column(Integer, default=3)  # 1 (high) - 5 (low)
    status: Mapped[str] = mapped_column(String(30), default="not_started")
    completion_pct: Mapped[int] = mapped_column(Integer, default=0)  # 0-100
    # Related research-question ids (denormalised link list; traceability in Phase G).
    question_ids: Mapped[list] = mapped_column(JSON, default=list)
    notes: Mapped[str] = mapped_column(Text, default="")


class Constraint(Base, TimestampMixin):
    """A typed research constraint (technical/time/dataset/hardware/regulatory/…)."""

    __tablename__ = "constraints"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("research_projects.id", ondelete="CASCADE"), index=True
    )
    ctype: Mapped[str] = mapped_column(String(30), default="other")
    text: Mapped[str] = mapped_column(Text)


class Terminology(Base, TimestampMixin):
    """A term/definition record. Ambiguity is preserved — the system never merges
    concepts just because names look similar (spec §10)."""

    __tablename__ = "terminology"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("research_projects.id", ondelete="CASCADE"), index=True
    )
    term: Mapped[str] = mapped_column(String(300), index=True)
    definition: Mapped[str] = mapped_column(Text, default="")
    synonyms: Mapped[list] = mapped_column(JSON, default=list)
    acronyms: Mapped[list] = mapped_column(JSON, default=list)
    related: Mapped[list] = mapped_column(JSON, default=list)
    source_id: Mapped[str | None] = mapped_column(
        ForeignKey("sources.id", ondelete="SET NULL"), nullable=True
    )
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)  # 0-100

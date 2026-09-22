"""R&D layer Phase D — Analysis & Conclusion.

Completes the digital thread: Result → **Analysis** → Claim → **Conclusion** → Recommendation, while
reusing the existing Evidence (`ClaimSource`) / Claim / Verification / Confidence / provenance
substrate — nothing here duplicates them. Both tables are additive (`create_all`), carry `project_id`
(FK CASCADE) for the ownership boundary, and use validated **string** classification fields (sets in
`enums.py`), not Enum columns, so new members need no migration.

Grounding is by reference, never invented:
- An `Analysis` references existing results/claims/sources via JSON id-lists (the API requires ≥1),
  so an experimental Result enters the evidence-backed world *through Analysis* — a Result is never
  turned into a Source. A `classification="fact"` does NOT make an analysis independently verified;
  its grounding is the links, not the label.
- A `Conclusion` references analyses/claims/sources; classification never auto-promotes and confidence
  is nullable (absence preserved, never fabricated).
"""
from __future__ import annotations

import uuid

from sqlalchemy import JSON, Float, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.research import TimestampMixin


def _uuid() -> str:
    return str(uuid.uuid4())


class Analysis(Base, TimestampMixin):
    """A classified analytical statement grounded in existing evidence objects.

    `classification` ∈ fact|interpretation|inference|hypothesis|opinion. Grounding links
    (`claim_ids`/`source_ids`/`result_ids`/`experiment_ids`) connect to EXISTING rows — the API
    enforces at least one so an analysis can never masquerade as an ungrounded fact.
    """

    __tablename__ = "analyses"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("research_projects.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(500), default="")
    statement: Mapped[str] = mapped_column(Text)
    classification: Mapped[str] = mapped_column(String(20), default="interpretation")
    reasoning: Mapped[str] = mapped_column(Text, default="")
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)  # 0-100; None if unset
    origin: Mapped[str] = mapped_column(String(20), default="user")  # user|agent|derived
    # Grounding — references to EXISTING objects (reuse; never a second evidence system).
    claim_ids: Mapped[list] = mapped_column(JSON, default=list)
    source_ids: Mapped[list] = mapped_column(JSON, default=list)
    result_ids: Mapped[list] = mapped_column(JSON, default=list)
    experiment_ids: Mapped[list] = mapped_column(JSON, default=list)
    notes: Mapped[str] = mapped_column(Text, default="")


class Conclusion(Base, TimestampMixin):
    """A classified conclusion traceable to its underlying analyses/claims/evidence.

    `classification` ∈ proven|strongly_supported|supported|weakly_supported|inconclusive|unknown|
    contradicted|disproved. Never auto-promoted; confidence nullable (absence preserved).
    """

    __tablename__ = "conclusions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("research_projects.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(500), default="")
    statement: Mapped[str] = mapped_column(Text)
    classification: Mapped[str] = mapped_column(String(30), default="inconclusive")
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)  # 0-100; None if unset
    reasoning: Mapped[str] = mapped_column(Text, default="")
    origin: Mapped[str] = mapped_column(String(20), default="user")
    # Traceability links to EXISTING objects.
    analysis_ids: Mapped[list] = mapped_column(JSON, default=list)
    claim_ids: Mapped[list] = mapped_column(JSON, default=list)
    source_ids: Mapped[list] = mapped_column(JSON, default=list)
    question_ids: Mapped[list] = mapped_column(JSON, default=list)
    contradicting_claim_ids: Mapped[list] = mapped_column(JSON, default=list)
    notes: Mapped[str] = mapped_column(Text, default="")

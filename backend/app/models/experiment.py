"""R&D layer — the experiment/laboratory cluster.

Phase B adds **Method** and **Hypothesis** only. Experiment/Dataset/Result are Phase C and will be
added to this module then — Phase B deliberately creates no experiment tables and no fabricated
results. Both tables are additive (`create_all`), carry `project_id` (FK CASCADE) so they inherit
the project's ownership boundary (`_get_project`), and use validated **string** status/origin fields
(sets in `enums.py`) rather than Enum columns, so new members need no migration.

Relationships to existing objects are stored as JSON id-lists (like `Claim.supporting_source_ids`
and `Objective.question_ids`), not join tables — the API validates every referenced id belongs to
the same project, so ownership can never be crossed. This keeps the schema minimal while giving
Phase C a clean `Experiment(hypothesis_id, method_id, dataset_id)` to reference without a redesign.
"""
from __future__ import annotations

import uuid

from sqlalchemy import JSON, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.research import TimestampMixin


def _uuid() -> str:
    return str(uuid.uuid4())


class Method(Base, TimestampMixin):
    """A reusable research/engineering methodology (benchmark/eval/measurement/algorithm/…).

    A Method is a *how*, not a claim or a result. It may be proposed by the researcher or the agent,
    or derived from literature (in which case `source_ids`/`claim_ids` record the derivation). It is
    version-aware (`version` bumps on edit) so methodological history is not silently overwritten.
    """

    __tablename__ = "methods"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("research_projects.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(500))
    description: Mapped[str] = mapped_column(Text, default="")
    procedure: Mapped[str] = mapped_column(Text, default="")
    inputs: Mapped[list] = mapped_column(JSON, default=list)
    outputs: Mapped[list] = mapped_column(JSON, default=list)
    assumptions: Mapped[list] = mapped_column(JSON, default=list)
    advantages: Mapped[list] = mapped_column(JSON, default=list)
    disadvantages: Mapped[list] = mapped_column(JSON, default=list)
    limitations: Mapped[list] = mapped_column(JSON, default=list)
    applicability: Mapped[str] = mapped_column(Text, default="")  # applicable conditions
    status: Mapped[str] = mapped_column(String(20), default="proposed")
    origin: Mapped[str] = mapped_column(String(20), default="user")  # user|agent|derived
    # Supporting research (traceability; reuses existing Source/Claim rows — no new evidence system).
    source_ids: Mapped[list] = mapped_column(JSON, default=list)
    claim_ids: Mapped[list] = mapped_column(JSON, default=list)
    notes: Mapped[str] = mapped_column(Text, default="")
    version: Mapped[int] = mapped_column(Integer, default=1)


class Hypothesis(Base, TimestampMixin):
    """A proposed explanation/prediction that REQUIRES testing — explicitly NOT a Claim.

    A Claim is an evidence-backed statement; a Hypothesis is a proposition awaiting validation. Status
    never auto-advances (a plausible LLM explanation does not make a hypothesis SUPPORTED); it changes
    only by explicit action or a future experimental/evidence workflow. Confidence reuses the existing
    0–100 representation (no second confidence engine) and never, by itself, proves the hypothesis.
    """

    __tablename__ = "hypotheses"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("research_projects.id", ondelete="CASCADE"), index=True
    )
    statement: Mapped[str] = mapped_column(Text)
    reasoning: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(30), default="proposed")
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)  # 0-100; None until judged
    origin: Mapped[str] = mapped_column(String(20), default="user")  # user|agent|derived
    # Why it exists / what it relates to (traceability — modelled explicitly, not inferred from text).
    question_ids: Mapped[list] = mapped_column(JSON, default=list)
    objective_ids: Mapped[list] = mapped_column(JSON, default=list)
    claim_ids: Mapped[list] = mapped_column(JSON, default=list)
    source_ids: Mapped[list] = mapped_column(JSON, default=list)
    # Optional methodology used to investigate it (a hypothesis may exist before a method is chosen).
    method_id: Mapped[str | None] = mapped_column(
        ForeignKey("methods.id", ondelete="SET NULL"), nullable=True
    )
    # Forward-compatible structured fields (kept minimal; full experiment fields are Phase C).
    variables: Mapped[list] = mapped_column(JSON, default=list)
    expected_result: Mapped[str] = mapped_column(Text, default="")
    assumptions: Mapped[list] = mapped_column(JSON, default=list)
    notes: Mapped[str] = mapped_column(Text, default="")

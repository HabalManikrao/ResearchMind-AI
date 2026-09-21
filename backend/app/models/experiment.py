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


# --------------------------------------------------------------------------- #
# Phase C — Datasets, Experiments, structured Results.
#
# Truthfulness is enforced at the model level by DEFAULTS, not by fiat: an Experiment starts
# `status="proposed"` with every execution field null, and nothing in the model advances it or
# fabricates a measurement. Execution timestamps / actual_result / data references are written only
# by an explicit client action (the API never sets them implicitly). A Result exists only when a
# client records one — an Experiment can (and by default does) exist with no Result.
# --------------------------------------------------------------------------- #
class Dataset(Base, TimestampMixin):
    """A research dataset / experimental input corpus. Version-distinguishable: a new version is a
    NEW row (optionally pointing at the one it supersedes via `supersedes_id`); an existing dataset
    identity is never silently overwritten. `origin` records provenance honestly — a dataset is only
    described as ResearchMind-collected when `origin="agent"` was set for an actual collection."""

    __tablename__ = "datasets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("research_projects.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(500))
    description: Mapped[str] = mapped_column(Text, default="")
    version: Mapped[str] = mapped_column(String(100), default="1")  # free-form (v1, 2024-05, sha, …)
    supersedes_id: Mapped[str | None] = mapped_column(
        ForeignKey("datasets.id", ondelete="SET NULL"), nullable=True
    )
    source: Mapped[str] = mapped_column(Text, default="")
    source_url: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    license: Mapped[str] = mapped_column(String(200), default="")
    data_type: Mapped[str] = mapped_column(String(100), default="")
    size: Mapped[str] = mapped_column(String(100), default="")  # human string, e.g. "2.3 GB"
    record_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    features: Mapped[list] = mapped_column(JSON, default=list)
    collection_method: Mapped[str] = mapped_column(Text, default="")
    collection_date: Mapped[str | None] = mapped_column(String(50), nullable=True)
    preprocessing: Mapped[str] = mapped_column(Text, default="")
    bias: Mapped[list] = mapped_column(JSON, default=list)
    limitations: Mapped[list] = mapped_column(JSON, default=list)
    quality: Mapped[str] = mapped_column(String(200), default="")
    access_information: Mapped[str] = mapped_column(Text, default="")
    checksum: Mapped[str | None] = mapped_column(String(128), nullable=True)
    meta: Mapped[dict] = mapped_column(JSON, default=dict)
    origin: Mapped[str] = mapped_column(String(20), default="user")  # user|agent|derived


class Experiment(Base, TimestampMixin):
    """A structured experimental design and (only when explicitly recorded) its execution record.

    PLANNED ≠ EXECUTED: `status` defaults to "proposed" and never auto-advances; `started_at`/
    `completed_at`/`actual_result_summary`/`*_data_reference` stay null unless a client records them.
    ResearchMind has no execution engine here — it records designs and manually-recorded outcomes,
    never fabricating measurements, timestamps, or success/failure.
    """

    __tablename__ = "experiments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("research_projects.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(500))
    description: Mapped[str] = mapped_column(Text, default="")
    # Digital-thread links (nullable; validated to the same project at the API).
    question_id: Mapped[str | None] = mapped_column(
        ForeignKey("research_questions.id", ondelete="SET NULL"), nullable=True
    )
    objective_id: Mapped[str | None] = mapped_column(
        ForeignKey("objectives.id", ondelete="SET NULL"), nullable=True
    )
    hypothesis_id: Mapped[str | None] = mapped_column(
        ForeignKey("hypotheses.id", ondelete="SET NULL"), nullable=True
    )
    method_id: Mapped[str | None] = mapped_column(
        ForeignKey("methods.id", ondelete="SET NULL"), nullable=True
    )
    dataset_id: Mapped[str | None] = mapped_column(
        ForeignKey("datasets.id", ondelete="SET NULL"), nullable=True
    )
    dataset_version: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # Experimental design.
    independent_variables: Mapped[list] = mapped_column(JSON, default=list)
    dependent_variables: Mapped[list] = mapped_column(JSON, default=list)
    controlled_variables: Mapped[list] = mapped_column(JSON, default=list)
    controls: Mapped[str] = mapped_column(Text, default="")
    assumptions: Mapped[list] = mapped_column(JSON, default=list)
    expected_result: Mapped[str] = mapped_column(Text, default="")
    failure_conditions: Mapped[str] = mapped_column(Text, default="")
    procedure: Mapped[str] = mapped_column(Text, default="")
    inputs: Mapped[list] = mapped_column(JSON, default=list)
    outputs: Mapped[list] = mapped_column(JSON, default=list)
    metrics: Mapped[list] = mapped_column(JSON, default=list)
    # Environment / reproducibility metadata (capture only — no verdict; verdict is Phase F).
    hardware: Mapped[str] = mapped_column(Text, default="")
    software: Mapped[str] = mapped_column(Text, default="")
    software_versions: Mapped[list] = mapped_column(JSON, default=list)
    environment: Mapped[str] = mapped_column(Text, default="")
    configuration: Mapped[dict] = mapped_column(JSON, default=dict)
    seed: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # Execution record — written ONLY on explicit action; null means "not executed".
    status: Mapped[str] = mapped_column(String(20), default="proposed")
    planned_at: Mapped[str | None] = mapped_column(String(50), nullable=True)
    started_at: Mapped[str | None] = mapped_column(String(50), nullable=True)
    completed_at: Mapped[str | None] = mapped_column(String(50), nullable=True)
    actual_result_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_data_reference: Mapped[str | None] = mapped_column(Text, nullable=True)
    processed_data_reference: Mapped[str | None] = mapped_column(Text, nullable=True)
    execution_notes: Mapped[str] = mapped_column(Text, default="")
    origin: Mapped[str] = mapped_column(String(20), default="user")


class Result(Base, TimestampMixin):
    """A structured research output attributed to the Experiment (and dataset) that produced it.

    A Result exists only when explicitly recorded — the system never generates one from a plan.
    Numeric fields (accuracy/latency/…) are nullable and stay null unless supplied; `metrics` is a
    structured list of {name,value,unit,lower_bound,upper_bound,conditions} so values live as data,
    not prose. `origin` records who recorded it (provenance is explicit, never fabricated).
    """

    __tablename__ = "results"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("research_projects.id", ondelete="CASCADE"), index=True
    )
    experiment_id: Mapped[str] = mapped_column(
        ForeignKey("experiments.id", ondelete="CASCADE"), index=True
    )
    dataset_id: Mapped[str | None] = mapped_column(
        ForeignKey("datasets.id", ondelete="SET NULL"), nullable=True
    )
    name: Mapped[str] = mapped_column(String(500), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    result_type: Mapped[str] = mapped_column(String(30), default="measurement")
    # Structured metrics: [{"name","value","unit","lower_bound","upper_bound","conditions"}].
    metrics: Mapped[list] = mapped_column(JSON, default=list)
    measurements: Mapped[list] = mapped_column(JSON, default=list)
    benchmark: Mapped[str] = mapped_column(String(300), default="")
    error_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    latency: Mapped[str | None] = mapped_column(String(100), nullable=True)
    throughput: Mapped[str | None] = mapped_column(String(100), nullable=True)
    accuracy: Mapped[float | None] = mapped_column(Float, nullable=True)
    cost: Mapped[str | None] = mapped_column(String(100), nullable=True)
    resource_usage: Mapped[str] = mapped_column(Text, default="")
    observations: Mapped[str] = mapped_column(Text, default="")
    anomalies: Mapped[str] = mapped_column(Text, default="")
    raw_data_reference: Mapped[str | None] = mapped_column(Text, nullable=True)
    processed_data_reference: Mapped[str | None] = mapped_column(Text, nullable=True)
    conditions: Mapped[str] = mapped_column(Text, default="")
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)  # 0-100; reuse convention
    origin: Mapped[str] = mapped_column(String(20), default="user")
    notes: Mapped[str] = mapped_column(Text, default="")

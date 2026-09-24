"""Request/response schemas."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import (
    ClaimStatus,
    ConflictSeverity,
    ConflictStatus,
    ANALYSIS_CLASSIFICATION_PATTERN,
    CONCLUSION_CLASSIFICATION_PATTERN,
    CONSTRAINT_TYPE_PATTERN,
    EXPERIMENT_STATUS_PATTERN,
    GAP_STATUS_PATTERN,
    HYPOTHESIS_STATUS_PATTERN,
    LIMITATION_SEVERITY_PATTERN,
    LIMITATION_STATUS_PATTERN,
    LIMITATION_TYPE_PATTERN,
    METHOD_STATUS_PATTERN,
    OBJECTIVE_STATUS_PATTERN,
    RESULT_TYPE_PATTERN,
    ProjectStatus,
    QUESTION_CATEGORY_PATTERN,
    QUESTION_STATUS_PATTERN,
    RND_ORIGIN_PATTERN,
    ResearchMode,
    TaskStatus,
)

DEFAULT_SOURCES = ["web"]


class ResearchCreate(BaseModel):
    query: str = Field(min_length=3)
    title: str | None = None
    mode: ResearchMode = ResearchMode.DEEP
    sources_enabled: list[str] = Field(default_factory=lambda: list(DEFAULT_SOURCES))
    constraints: dict = Field(default_factory=dict)
    auto_start: bool = True
    # Live/cached/local sourcing policy (#5). None => backend default (live_preferred).
    source_policy: str | None = Field(
        default=None, pattern="^(live_only|live_preferred|cache_allowed|local_only)$"
    )


class QuestionCreate(BaseModel):
    text: str = Field(min_length=3)
    priority: int = 3


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class ProjectSummary(ORMModel):
    id: str
    title: str
    query: str
    mode: ResearchMode
    status: ProjectStatus
    progress: int
    current_stage: str | None
    created_at: datetime
    updated_at: datetime
    # Research lineage (#4).
    parent_id: str | None = None
    root_id: str | None = None
    run_number: int = 1
    run_intent: str | None = None
    completed_at: datetime | None = None


class ProjectDetail(ProjectSummary):
    objective: str | None
    constraints: dict
    sources_enabled: list
    source_policy: str | None = None  # #5 live/cached/local sourcing policy
    error: str | None
    report_meta: dict | None


class ResearchAgainRequest(BaseModel):
    """Fork a completed run into a continuation run (#4)."""

    intent: str = Field("refresh", pattern="^(refresh|deepen|verify|full)$")
    mode: ResearchMode | None = None  # inherit parent's mode if omitted
    sources_enabled: list[str] | None = None  # inherit parent's sources if omitted
    auto_start: bool = True


class RunSummary(ORMModel):
    """One run in a lineage, with quick counts for the history/lineage view."""

    id: str
    run_number: int
    run_intent: str | None
    status: ProjectStatus
    created_at: datetime
    completed_at: datetime | None
    parent_id: str | None
    source_count: int = 0
    claim_count: int = 0
    evidence_count: int = 0
    avg_confidence: float = 0.0


class MemoryOut(BaseModel):
    project_id: str
    memory: dict | None


class QuestionOut(ORMModel):
    id: str
    text: str
    priority: int
    is_followup: bool
    answered: bool
    # R&D layer (Phase A) — first-class question fields (nullable for legacy rows).
    category: str | None = None
    q_status: str | None = None
    answer: str | None = None
    answer_confidence: float | None = None


class QuestionUpdate(BaseModel):
    """Partial update of a question's R&D fields. Any omitted field is left unchanged."""

    text: str | None = Field(default=None, min_length=3)
    priority: int | None = Field(default=None, ge=1, le=5)
    category: str | None = Field(default=None, pattern=QUESTION_CATEGORY_PATTERN)
    q_status: str | None = Field(default=None, pattern=QUESTION_STATUS_PATTERN)
    answer: str | None = None
    answer_confidence: float | None = Field(default=None, ge=0, le=100)
    answered: bool | None = None


# --------------------------------------------------------------------------- #
# R&D layer Phase A — Brief / Objectives / Constraints / Terminology.
# --------------------------------------------------------------------------- #
class ResearchBriefOut(ORMModel):
    id: str
    project_id: str
    problem_statement: str
    background: str
    expected_outcome: str
    scope_included: list
    scope_excluded: list
    assumptions: list
    target_users: list
    success_criteria: list
    version: int


class ResearchBriefUpdate(BaseModel):
    """Upsert the brief. Omitted fields are left unchanged; the version bumps on write."""

    problem_statement: str | None = None
    background: str | None = None
    expected_outcome: str | None = None
    scope_included: list[str] | None = None
    scope_excluded: list[str] | None = None
    assumptions: list[str] | None = None
    target_users: list[str] | None = None
    success_criteria: list[str] | None = None


class ObjectiveOut(ORMModel):
    id: str
    description: str
    priority: int
    status: str
    completion_pct: int
    question_ids: list
    notes: str


class ObjectiveCreate(BaseModel):
    description: str = Field(min_length=3)
    priority: int = Field(default=3, ge=1, le=5)
    status: str = Field(default="not_started", pattern=OBJECTIVE_STATUS_PATTERN)
    completion_pct: int = Field(default=0, ge=0, le=100)
    question_ids: list[str] = Field(default_factory=list)
    notes: str = ""


class ObjectiveUpdate(BaseModel):
    description: str | None = Field(default=None, min_length=3)
    priority: int | None = Field(default=None, ge=1, le=5)
    status: str | None = Field(default=None, pattern=OBJECTIVE_STATUS_PATTERN)
    completion_pct: int | None = Field(default=None, ge=0, le=100)
    question_ids: list[str] | None = None
    notes: str | None = None


class ConstraintOut(ORMModel):
    id: str
    ctype: str
    text: str


class ConstraintCreate(BaseModel):
    ctype: str = Field(default="other", pattern=CONSTRAINT_TYPE_PATTERN)
    text: str = Field(min_length=1)


class TerminologyOut(ORMModel):
    id: str
    term: str
    definition: str
    synonyms: list
    acronyms: list
    related: list
    source_id: str | None = None
    confidence: float | None = None


class TerminologyCreate(BaseModel):
    term: str = Field(min_length=1)
    definition: str = ""
    synonyms: list[str] = Field(default_factory=list)
    acronyms: list[str] = Field(default_factory=list)
    related: list[str] = Field(default_factory=list)
    source_id: str | None = None
    confidence: float | None = Field(default=None, ge=0, le=100)


class TerminologyUpdate(BaseModel):
    term: str | None = Field(default=None, min_length=1)
    definition: str | None = None
    synonyms: list[str] | None = None
    acronyms: list[str] | None = None
    related: list[str] | None = None
    source_id: str | None = None
    confidence: float | None = Field(default=None, ge=0, le=100)


# --------------------------------------------------------------------------- #
# R&D layer Phase B — Methods & Hypotheses.
# --------------------------------------------------------------------------- #
class MethodOut(ORMModel):
    id: str
    name: str
    description: str
    procedure: str
    inputs: list
    outputs: list
    assumptions: list
    advantages: list
    disadvantages: list
    limitations: list
    applicability: str
    status: str
    origin: str
    source_ids: list
    claim_ids: list
    notes: str
    version: int


class MethodCreate(BaseModel):
    name: str = Field(min_length=1, max_length=500)
    description: str = ""
    procedure: str = ""
    inputs: list[str] = Field(default_factory=list)
    outputs: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    advantages: list[str] = Field(default_factory=list)
    disadvantages: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    applicability: str = ""
    status: str = Field(default="proposed", pattern=METHOD_STATUS_PATTERN)
    origin: str = Field(default="user", pattern=RND_ORIGIN_PATTERN)
    source_ids: list[str] = Field(default_factory=list)
    claim_ids: list[str] = Field(default_factory=list)
    notes: str = ""


class MethodUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=500)
    description: str | None = None
    procedure: str | None = None
    inputs: list[str] | None = None
    outputs: list[str] | None = None
    assumptions: list[str] | None = None
    advantages: list[str] | None = None
    disadvantages: list[str] | None = None
    limitations: list[str] | None = None
    applicability: str | None = None
    status: str | None = Field(default=None, pattern=METHOD_STATUS_PATTERN)
    origin: str | None = Field(default=None, pattern=RND_ORIGIN_PATTERN)
    source_ids: list[str] | None = None
    claim_ids: list[str] | None = None
    notes: str | None = None


class HypothesisOut(ORMModel):
    id: str
    statement: str
    reasoning: str
    status: str
    confidence: float | None = None
    origin: str
    question_ids: list
    objective_ids: list
    claim_ids: list
    source_ids: list
    method_id: str | None = None
    variables: list
    expected_result: str
    assumptions: list
    notes: str


class HypothesisCreate(BaseModel):
    statement: str = Field(min_length=3)
    reasoning: str = ""
    status: str = Field(default="proposed", pattern=HYPOTHESIS_STATUS_PATTERN)
    confidence: float | None = Field(default=None, ge=0, le=100)
    origin: str = Field(default="user", pattern=RND_ORIGIN_PATTERN)
    question_ids: list[str] = Field(default_factory=list)
    objective_ids: list[str] = Field(default_factory=list)
    claim_ids: list[str] = Field(default_factory=list)
    source_ids: list[str] = Field(default_factory=list)
    method_id: str | None = None
    variables: list[str] = Field(default_factory=list)
    expected_result: str = ""
    assumptions: list[str] = Field(default_factory=list)
    notes: str = ""


class HypothesisUpdate(BaseModel):
    statement: str | None = Field(default=None, min_length=3)
    reasoning: str | None = None
    status: str | None = Field(default=None, pattern=HYPOTHESIS_STATUS_PATTERN)
    confidence: float | None = Field(default=None, ge=0, le=100)
    origin: str | None = Field(default=None, pattern=RND_ORIGIN_PATTERN)
    question_ids: list[str] | None = None
    objective_ids: list[str] | None = None
    claim_ids: list[str] | None = None
    source_ids: list[str] | None = None
    method_id: str | None = None
    variables: list[str] | None = None
    expected_result: str | None = None
    assumptions: list[str] | None = None
    notes: str | None = None


# --------------------------------------------------------------------------- #
# R&D layer Phase C — Datasets, Experiments, structured Results.
# --------------------------------------------------------------------------- #
class DatasetOut(ORMModel):
    id: str
    name: str
    description: str
    version: str
    supersedes_id: str | None = None
    source: str
    source_url: str | None = None
    license: str
    data_type: str
    size: str
    record_count: int | None = None
    features: list
    collection_method: str
    collection_date: str | None = None
    preprocessing: str
    bias: list
    limitations: list
    quality: str
    access_information: str
    checksum: str | None = None
    meta: dict
    origin: str


class DatasetCreate(BaseModel):
    name: str = Field(min_length=1, max_length=500)
    description: str = ""
    version: str = Field(default="1", max_length=100)
    supersedes_id: str | None = None
    source: str = ""
    source_url: str | None = Field(default=None, max_length=2000)
    license: str = ""
    data_type: str = ""
    size: str = ""
    record_count: int | None = Field(default=None, ge=0)
    features: list[str] = Field(default_factory=list)
    collection_method: str = ""
    collection_date: str | None = None
    preprocessing: str = ""
    bias: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    quality: str = ""
    access_information: str = ""
    checksum: str | None = Field(default=None, max_length=128)
    meta: dict = Field(default_factory=dict)
    origin: str = Field(default="user", pattern=RND_ORIGIN_PATTERN)


class DatasetUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=500)
    description: str | None = None
    version: str | None = Field(default=None, max_length=100)
    supersedes_id: str | None = None
    source: str | None = None
    source_url: str | None = Field(default=None, max_length=2000)
    license: str | None = None
    data_type: str | None = None
    size: str | None = None
    record_count: int | None = Field(default=None, ge=0)
    features: list[str] | None = None
    collection_method: str | None = None
    collection_date: str | None = None
    preprocessing: str | None = None
    bias: list[str] | None = None
    limitations: list[str] | None = None
    quality: str | None = None
    access_information: str | None = None
    checksum: str | None = Field(default=None, max_length=128)
    meta: dict | None = None
    origin: str | None = Field(default=None, pattern=RND_ORIGIN_PATTERN)


class ExperimentOut(ORMModel):
    id: str
    name: str
    description: str
    question_id: str | None = None
    objective_id: str | None = None
    hypothesis_id: str | None = None
    method_id: str | None = None
    dataset_id: str | None = None
    dataset_version: str | None = None
    independent_variables: list
    dependent_variables: list
    controlled_variables: list
    controls: str
    assumptions: list
    expected_result: str
    failure_conditions: str
    procedure: str
    inputs: list
    outputs: list
    metrics: list
    hardware: str
    software: str
    software_versions: list
    environment: str
    configuration: dict
    seed: str | None = None
    status: str
    planned_at: str | None = None
    started_at: str | None = None
    completed_at: str | None = None
    actual_result_summary: str | None = None
    raw_data_reference: str | None = None
    processed_data_reference: str | None = None
    execution_notes: str
    origin: str


class ExperimentCreate(BaseModel):
    name: str = Field(min_length=1, max_length=500)
    description: str = ""
    question_id: str | None = None
    objective_id: str | None = None
    hypothesis_id: str | None = None
    method_id: str | None = None
    dataset_id: str | None = None
    dataset_version: str | None = Field(default=None, max_length=100)
    independent_variables: list[str] = Field(default_factory=list)
    dependent_variables: list[str] = Field(default_factory=list)
    controlled_variables: list[str] = Field(default_factory=list)
    controls: str = ""
    assumptions: list[str] = Field(default_factory=list)
    expected_result: str = ""
    failure_conditions: str = ""
    procedure: str = ""
    inputs: list[str] = Field(default_factory=list)
    outputs: list[str] = Field(default_factory=list)
    metrics: list[str] = Field(default_factory=list)
    hardware: str = ""
    software: str = ""
    software_versions: list[str] = Field(default_factory=list)
    environment: str = ""
    configuration: dict = Field(default_factory=dict)
    seed: str | None = Field(default=None, max_length=100)
    # Execution fields are intentionally NOT accepted at create time (planned != executed).
    status: str = Field(default="proposed", pattern=EXPERIMENT_STATUS_PATTERN)
    planned_at: str | None = None
    origin: str = Field(default="user", pattern=RND_ORIGIN_PATTERN)


class ExperimentUpdate(BaseModel):
    """Full update — execution fields ARE settable here (this is the explicit 'record execution'
    action). Setting them is a deliberate client action, never automatic."""

    name: str | None = Field(default=None, min_length=1, max_length=500)
    description: str | None = None
    question_id: str | None = None
    objective_id: str | None = None
    hypothesis_id: str | None = None
    method_id: str | None = None
    dataset_id: str | None = None
    dataset_version: str | None = Field(default=None, max_length=100)
    independent_variables: list[str] | None = None
    dependent_variables: list[str] | None = None
    controlled_variables: list[str] | None = None
    controls: str | None = None
    assumptions: list[str] | None = None
    expected_result: str | None = None
    failure_conditions: str | None = None
    procedure: str | None = None
    inputs: list[str] | None = None
    outputs: list[str] | None = None
    metrics: list[str] | None = None
    hardware: str | None = None
    software: str | None = None
    software_versions: list[str] | None = None
    environment: str | None = None
    configuration: dict | None = None
    seed: str | None = Field(default=None, max_length=100)
    status: str | None = Field(default=None, pattern=EXPERIMENT_STATUS_PATTERN)
    planned_at: str | None = None
    started_at: str | None = None
    completed_at: str | None = None
    actual_result_summary: str | None = None
    raw_data_reference: str | None = None
    processed_data_reference: str | None = None
    execution_notes: str | None = None
    origin: str | None = Field(default=None, pattern=RND_ORIGIN_PATTERN)


class ResultMetric(BaseModel):
    """A single structured metric — values live as data, not prose."""

    name: str
    value: float | str | None = None
    unit: str | None = None
    lower_bound: float | None = None
    upper_bound: float | None = None
    conditions: str | None = None


class ResultOut(ORMModel):
    id: str
    experiment_id: str
    dataset_id: str | None = None
    name: str
    description: str
    result_type: str
    metrics: list
    measurements: list
    benchmark: str
    error_rate: float | None = None
    latency: str | None = None
    throughput: str | None = None
    accuracy: float | None = None
    cost: str | None = None
    resource_usage: str
    observations: str
    anomalies: str
    raw_data_reference: str | None = None
    processed_data_reference: str | None = None
    conditions: str
    confidence: float | None = None
    origin: str
    notes: str


class ResultCreate(BaseModel):
    experiment_id: str = Field(min_length=1)  # a result MUST attribute to an experiment
    dataset_id: str | None = None
    name: str = ""
    description: str = ""
    result_type: str = Field(default="measurement", pattern=RESULT_TYPE_PATTERN)
    metrics: list[ResultMetric] = Field(default_factory=list)
    measurements: list = Field(default_factory=list)
    benchmark: str = ""
    error_rate: float | None = None
    latency: str | None = None
    throughput: str | None = None
    accuracy: float | None = None
    cost: str | None = None
    resource_usage: str = ""
    observations: str = ""
    anomalies: str = ""
    raw_data_reference: str | None = None
    processed_data_reference: str | None = None
    conditions: str = ""
    confidence: float | None = Field(default=None, ge=0, le=100)
    origin: str = Field(default="user", pattern=RND_ORIGIN_PATTERN)
    notes: str = ""


class ResultUpdate(BaseModel):
    dataset_id: str | None = None
    name: str | None = None
    description: str | None = None
    result_type: str | None = Field(default=None, pattern=RESULT_TYPE_PATTERN)
    metrics: list[ResultMetric] | None = None
    measurements: list | None = None
    benchmark: str | None = None
    error_rate: float | None = None
    latency: str | None = None
    throughput: str | None = None
    accuracy: float | None = None
    cost: str | None = None
    resource_usage: str | None = None
    observations: str | None = None
    anomalies: str | None = None
    raw_data_reference: str | None = None
    processed_data_reference: str | None = None
    conditions: str | None = None
    confidence: float | None = Field(default=None, ge=0, le=100)
    origin: str | None = Field(default=None, pattern=RND_ORIGIN_PATTERN)
    notes: str | None = None


# --------------------------------------------------------------------------- #
# R&D layer Phase D — Analysis & Conclusions.
# --------------------------------------------------------------------------- #
class AnalysisOut(ORMModel):
    id: str
    title: str
    statement: str
    classification: str
    reasoning: str
    confidence: float | None = None
    origin: str
    claim_ids: list
    source_ids: list
    result_ids: list
    experiment_ids: list
    notes: str


class AnalysisCreate(BaseModel):
    title: str = Field(default="", max_length=500)
    statement: str = Field(min_length=3)
    classification: str = Field(default="interpretation", pattern=ANALYSIS_CLASSIFICATION_PATTERN)
    reasoning: str = ""
    confidence: float | None = Field(default=None, ge=0, le=100)
    origin: str = Field(default="user", pattern=RND_ORIGIN_PATTERN)
    # Grounding — the API requires at least one of claim/source/result references.
    claim_ids: list[str] = Field(default_factory=list)
    source_ids: list[str] = Field(default_factory=list)
    result_ids: list[str] = Field(default_factory=list)
    experiment_ids: list[str] = Field(default_factory=list)
    notes: str = ""


class AnalysisUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=500)
    statement: str | None = Field(default=None, min_length=3)
    classification: str | None = Field(default=None, pattern=ANALYSIS_CLASSIFICATION_PATTERN)
    reasoning: str | None = None
    confidence: float | None = Field(default=None, ge=0, le=100)
    origin: str | None = Field(default=None, pattern=RND_ORIGIN_PATTERN)
    claim_ids: list[str] | None = None
    source_ids: list[str] | None = None
    result_ids: list[str] | None = None
    experiment_ids: list[str] | None = None
    notes: str | None = None


class ConclusionOut(ORMModel):
    id: str
    title: str
    statement: str
    classification: str
    confidence: float | None = None
    reasoning: str
    origin: str
    analysis_ids: list
    claim_ids: list
    source_ids: list
    question_ids: list
    contradicting_claim_ids: list
    notes: str


class ConclusionCreate(BaseModel):
    title: str = Field(default="", max_length=500)
    statement: str = Field(min_length=3)
    classification: str = Field(default="inconclusive", pattern=CONCLUSION_CLASSIFICATION_PATTERN)
    confidence: float | None = Field(default=None, ge=0, le=100)
    reasoning: str = ""
    origin: str = Field(default="user", pattern=RND_ORIGIN_PATTERN)
    # Grounding — the API requires at least one analysis or claim reference.
    analysis_ids: list[str] = Field(default_factory=list)
    claim_ids: list[str] = Field(default_factory=list)
    source_ids: list[str] = Field(default_factory=list)
    question_ids: list[str] = Field(default_factory=list)
    contradicting_claim_ids: list[str] = Field(default_factory=list)
    notes: str = ""


class ConclusionUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=500)
    statement: str | None = Field(default=None, min_length=3)
    classification: str | None = Field(default=None, pattern=CONCLUSION_CLASSIFICATION_PATTERN)
    confidence: float | None = Field(default=None, ge=0, le=100)
    reasoning: str | None = None
    origin: str | None = Field(default=None, pattern=RND_ORIGIN_PATTERN)
    analysis_ids: list[str] | None = None
    claim_ids: list[str] | None = None
    source_ids: list[str] | None = None
    question_ids: list[str] | None = None
    contradicting_claim_ids: list[str] | None = None
    notes: str | None = None


# --------------------------------------------------------------------------- #
# R&D layer Phase E — Comparisons & Limitations.
# --------------------------------------------------------------------------- #
class ComparisonOut(ORMModel):
    id: str
    title: str
    description: str
    subject_a: str
    subject_b: str | None = None
    criterion: str
    value: str
    unit: str | None = None
    conditions: str
    grounded: bool
    source_ids: list
    experiment_ids: list
    result_ids: list
    confidence: float | None = None
    origin: str
    notes: str


class ComparisonCreate(BaseModel):
    title: str = Field(default="", max_length=500)
    description: str = ""
    subject_a: str = Field(min_length=1, max_length=500)
    subject_b: str | None = Field(default=None, max_length=500)
    criterion: str = Field(default="", max_length=300)
    value: str = ""
    unit: str | None = Field(default=None, max_length=100)
    conditions: str = ""
    source_ids: list[str] = Field(default_factory=list)
    experiment_ids: list[str] = Field(default_factory=list)
    result_ids: list[str] = Field(default_factory=list)
    confidence: float | None = Field(default=None, ge=0, le=100)
    origin: str = Field(default="user", pattern=RND_ORIGIN_PATTERN)
    notes: str = ""


class ComparisonUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=500)
    description: str | None = None
    subject_a: str | None = Field(default=None, min_length=1, max_length=500)
    subject_b: str | None = Field(default=None, max_length=500)
    criterion: str | None = Field(default=None, max_length=300)
    value: str | None = None
    unit: str | None = Field(default=None, max_length=100)
    conditions: str | None = None
    source_ids: list[str] | None = None
    experiment_ids: list[str] | None = None
    result_ids: list[str] | None = None
    confidence: float | None = Field(default=None, ge=0, le=100)
    origin: str | None = Field(default=None, pattern=RND_ORIGIN_PATTERN)
    notes: str | None = None


class LimitationOut(ORMModel):
    id: str
    ltype: str
    title: str
    description: str
    severity: str
    affected_kind: str | None = None
    affected_id: str | None = None
    impact: str
    mitigation: str
    status: str
    source_ids: list
    claim_ids: list
    confidence: float | None = None
    origin: str
    notes: str


class LimitationCreate(BaseModel):
    ltype: str = Field(default="research", pattern=LIMITATION_TYPE_PATTERN)
    title: str = Field(default="", max_length=500)
    description: str = Field(min_length=3)
    severity: str = Field(default="medium", pattern=LIMITATION_SEVERITY_PATTERN)
    affected_kind: str | None = Field(default=None, pattern=LIMITATION_TYPE_PATTERN)
    affected_id: str | None = None
    impact: str = ""
    mitigation: str = ""
    status: str = Field(default="open", pattern=LIMITATION_STATUS_PATTERN)
    source_ids: list[str] = Field(default_factory=list)
    claim_ids: list[str] = Field(default_factory=list)
    confidence: float | None = Field(default=None, ge=0, le=100)
    origin: str = Field(default="user", pattern=RND_ORIGIN_PATTERN)
    notes: str = ""


class LimitationUpdate(BaseModel):
    ltype: str | None = Field(default=None, pattern=LIMITATION_TYPE_PATTERN)
    title: str | None = Field(default=None, max_length=500)
    description: str | None = Field(default=None, min_length=3)
    severity: str | None = Field(default=None, pattern=LIMITATION_SEVERITY_PATTERN)
    affected_kind: str | None = Field(default=None, pattern=LIMITATION_TYPE_PATTERN)
    affected_id: str | None = None
    impact: str | None = None
    mitigation: str | None = None
    status: str | None = Field(default=None, pattern=LIMITATION_STATUS_PATTERN)
    source_ids: list[str] | None = None
    claim_ids: list[str] | None = None
    confidence: float | None = Field(default=None, ge=0, le=100)
    origin: str | None = Field(default=None, pattern=RND_ORIGIN_PATTERN)
    notes: str | None = None


class TaskOut(ORMModel):
    id: str
    agent: str
    description: str
    search_query: str | None
    status: TaskStatus
    attempts: int
    round: int
    error: str | None


class SourceOut(ORMModel):
    id: str
    title: str
    url: str
    source_type: str
    publisher: str | None
    published_date: str | None
    summary: str | None
    reliability_score: float
    relevance_score: float
    freshness: str  # fresh | aging | stale | unknown (computed from published_date)
    provenance: str  # live_web | cached_web | local_document | ... (#5, computed)
    availability: str  # live | cached | local | stale | unknown (#5, computed)
    meta: dict


class FindingOut(ORMModel):
    id: str
    text: str
    source_id: str | None
    question_id: str | None
    relevance_score: float


class ClaimOut(ORMModel):
    id: str
    text: str
    status: ClaimStatus
    confidence: float
    supporting_source_ids: list
    confidence_meta: dict | None = None
    evidence_state: str  # supported | weak | conflicting | outdated | unverified


class ClaimEvidenceItem(BaseModel):
    """One evidence edge for a claim: a source, its quoted passage, and stance."""

    source_id: str
    title: str
    url: str
    source_type: str
    publisher: str | None = None
    published_date: str | None = None
    reliability_score: float
    freshness: str
    provenance: str = "live_web"  # #5 where the evidence came from
    availability: str = "live"  # #5 live | cached | local | stale | unknown
    stance: str  # supports | contradicts | neutral
    passage: str | None = None
    page_number: int | None = None  # for document sources: page the passage came from


class ClaimEvidenceOut(BaseModel):
    claim: ClaimOut
    evidence: list[ClaimEvidenceItem]


class ConflictOut(ORMModel):
    id: str
    statement_a: str
    statement_b: str
    explanation: str
    severity: ConflictSeverity
    status: ConflictStatus
    source_ids: list


class KnowledgeGapOut(ORMModel):
    id: str
    question: str
    reason: str
    followup_query: str
    round: int
    resolved: bool
    # R&D layer Phase E — first-class gap fields (nullable for auto-generated/legacy rows).
    importance: str | None = None
    impact: str | None = None
    potential_investigation: str | None = None
    status: str | None = None
    confidence: float | None = None
    origin: str | None = None
    question_ids: list | None = None
    hypothesis_ids: list | None = None
    experiment_ids: list | None = None
    claim_ids: list | None = None
    conclusion_ids: list | None = None
    source_ids: list | None = None


class KnowledgeGapCreate(BaseModel):
    question: str = Field(min_length=3)
    reason: str = ""
    followup_query: str = ""
    importance: str | None = Field(default=None, pattern="^(high|medium|low)$")
    impact: str | None = None
    potential_investigation: str | None = None
    status: str = Field(default="open", pattern=GAP_STATUS_PATTERN)
    confidence: float | None = Field(default=None, ge=0, le=100)
    origin: str = Field(default="user", pattern=RND_ORIGIN_PATTERN)
    question_ids: list[str] = Field(default_factory=list)
    hypothesis_ids: list[str] = Field(default_factory=list)
    experiment_ids: list[str] = Field(default_factory=list)
    claim_ids: list[str] = Field(default_factory=list)
    conclusion_ids: list[str] = Field(default_factory=list)
    source_ids: list[str] = Field(default_factory=list)


class KnowledgeGapUpdate(BaseModel):
    question: str | None = Field(default=None, min_length=3)
    reason: str | None = None
    followup_query: str | None = None
    resolved: bool | None = None
    importance: str | None = Field(default=None, pattern="^(high|medium|low)$")
    impact: str | None = None
    potential_investigation: str | None = None
    status: str | None = Field(default=None, pattern=GAP_STATUS_PATTERN)
    confidence: float | None = Field(default=None, ge=0, le=100)
    origin: str | None = Field(default=None, pattern=RND_ORIGIN_PATTERN)
    question_ids: list[str] | None = None
    hypothesis_ids: list[str] | None = None
    experiment_ids: list[str] | None = None
    claim_ids: list[str] | None = None
    conclusion_ids: list[str] | None = None
    source_ids: list[str] | None = None


class SolutionOut(ORMModel):
    id: str
    name: str
    description: str
    pros: list
    cons: list
    risks: list
    scores: list
    is_recommended: bool


class RecommendationOut(ORMModel):
    id: str
    recommended_option: str
    rationale: str
    why: str
    confidence: float
    alternatives: list
    risks: list
    proof_of_concept: str
    roadmap: list
    # Phase D additive traceability links + priority.
    conclusion_ids: list = Field(default_factory=list)
    analysis_ids: list = Field(default_factory=list)
    result_ids: list = Field(default_factory=list)
    experiment_ids: list = Field(default_factory=list)
    priority: str | None = None
    expected_benefit: str = ""
    tradeoffs: list = Field(default_factory=list)


class RecommendationLinksUpdate(BaseModel):
    """Explicit action to link the (auto-generated) recommendation into the structured chain and set
    priority/benefit/tradeoffs. Additive — never rewrites recommended_option/rationale/confidence."""

    conclusion_ids: list[str] | None = None
    analysis_ids: list[str] | None = None
    result_ids: list[str] | None = None
    experiment_ids: list[str] | None = None
    priority: str | None = Field(default=None, pattern="^(high|medium|low)$")
    expected_benefit: str | None = None
    tradeoffs: list[str] | None = None


class ReportOut(BaseModel):
    project_id: str
    markdown: str | None
    meta: dict | None


class MessageOut(BaseModel):
    message: str
    ok: bool = True


class KnowledgeSearchOut(BaseModel):
    project_id: str
    title: str
    score: float | None = None  # semantic similarity 0-1; None for keyword matches
    snippet: str = ""
    matches: int = 0


class KnowledgeStatusOut(BaseModel):
    enabled: bool
    semantic: bool  # embeddings reachable -> semantic search active
    embedding_model: str


class GraphNode(BaseModel):
    id: str
    label: str
    type: str
    recommended: bool | None = None
    status: str | None = None
    source_type: str | None = None


class GraphEdge(BaseModel):
    source: str
    target: str
    label: str


class GraphOut(BaseModel):
    nodes: list[GraphNode]
    edges: list[GraphEdge]


# --------------------------------------------------------------------------- #
# Research Diff (#4) — serialized from services/research_diff dataclasses.
# --------------------------------------------------------------------------- #
class DiffModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class DiffEvidenceItem(DiffModel):
    title: str
    url: str
    source_type: str
    stance: str
    passage: str | None = None
    page_number: int | None = None


class SourceDiffItemOut(DiffModel):
    kind: str
    url: str
    title: str
    source_type: str
    changes: list[str] = Field(default_factory=list)


class ClaimDiffItemOut(DiffModel):
    kind: str
    old_text: str | None = None
    new_text: str | None = None
    old_confidence: float | None = None
    new_confidence: float | None = None
    confidence_delta: float | None = None
    direction: str = ""
    reason: str = ""
    match_score: float | None = None
    old_evidence: list[DiffEvidenceItem] = Field(default_factory=list)
    new_evidence: list[DiffEvidenceItem] = Field(default_factory=list)


class DocumentDiffItemOut(DiffModel):
    kind: str
    document_id: str | None = None
    filename: str
    changes: list[str] = Field(default_factory=list)


class SourceDiffOut(DiffModel):
    new: int = 0
    removed: int = 0
    unchanged: int = 0
    changed: int = 0
    items: list[SourceDiffItemOut] = Field(default_factory=list)


class ClaimDiffOut(DiffModel):
    new: int = 0
    removed: int = 0
    unchanged: int = 0
    strengthened: int = 0
    weakened: int = 0
    contradicted: int = 0
    items: list[ClaimDiffItemOut] = Field(default_factory=list)


class DocumentDiffOut(DiffModel):
    new: int = 0
    removed: int = 0
    unchanged: int = 0
    changed: int = 0
    items: list[DocumentDiffItemOut] = Field(default_factory=list)


class ConfidenceDiffOut(BaseModel):
    increased: int = 0
    decreased: int = 0
    unchanged: int = 0


class RecommendationDiffOut(BaseModel):
    kind: str
    old: dict | None = None
    new: dict | None = None


class ResearchDiffOut(BaseModel):
    old_run: dict
    new_run: dict
    sources: SourceDiffOut
    claims: ClaimDiffOut
    confidence: ConfidenceDiffOut
    recommendation: RecommendationDiffOut
    documents: DocumentDiffOut

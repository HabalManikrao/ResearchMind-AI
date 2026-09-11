"""Request/response schemas."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import (
    ClaimStatus,
    ConflictSeverity,
    ConflictStatus,
    CONSTRAINT_TYPE_PATTERN,
    OBJECTIVE_STATUS_PATTERN,
    ProjectStatus,
    QUESTION_CATEGORY_PATTERN,
    QUESTION_STATUS_PATTERN,
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

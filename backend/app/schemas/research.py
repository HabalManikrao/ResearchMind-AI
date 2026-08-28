"""Request/response schemas."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import (
    ClaimStatus,
    ConflictSeverity,
    ConflictStatus,
    ProjectStatus,
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


class ProjectDetail(ProjectSummary):
    objective: str | None
    constraints: dict
    sources_enabled: list
    error: str | None
    report_meta: dict | None


class QuestionOut(ORMModel):
    id: str
    text: str
    priority: int
    is_followup: bool
    answered: bool


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

"""Schemas for the Knowledge Graph API (#7)."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class EntityOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    canonical_name: str
    normalized_name: str
    entity_type: str
    description: str | None
    aliases: list
    mention_count: int
    first_observed_at: datetime | None
    last_observed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class EntitySummary(BaseModel):
    """Compact entity for lists/neighborhoods."""

    id: str
    canonical_name: str
    entity_type: str
    mention_count: int


class RelationshipOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    subject_entity_id: str
    predicate: str
    object_entity_id: str
    description: str | None
    confidence: float
    provenance_kind: str
    status: str
    valid_from: datetime | None
    valid_to: datetime | None
    first_observed_at: datetime | None
    last_observed_at: datetime | None
    project_id: str | None
    claim_id: str | None
    source_id: str | None


class RelatedEntity(BaseModel):
    """An edge from the focus entity to a neighbour, with the neighbour inlined."""

    relationship_id: str
    predicate: str
    direction: str  # "out" (focus is subject) | "in" (focus is object)
    confidence: float
    provenance_kind: str
    status: str
    entity: EntitySummary


class EntityClaim(BaseModel):
    claim_id: str
    text: str
    status: str
    confidence: float
    evidence_state: str
    project_id: str
    run_number: int
    disputed: bool
    superseded: bool  # historical (has been superseded by a newer claim)


class EntitySourceRef(BaseModel):
    source_id: str
    title: str
    url: str
    source_type: str
    provenance: str
    availability: str


class EntityDetail(BaseModel):
    entity: EntityOut
    related: list[RelatedEntity]
    current_claims: int
    historical_claims: int
    source_count: int
    run_count: int


class EntityGraph(BaseModel):
    """Bounded neighborhood: the focus entity, nodes within depth, and edges."""

    root_id: str
    depth: int
    nodes: list[EntitySummary]
    edges: list[RelationshipOut]
    truncated: bool


class EntityHistoryItem(BaseModel):
    kind: str  # observed | superseded_by | supersedes
    at: datetime | None
    project_id: str | None
    detail: str


class EntityHistory(BaseModel):
    entity_id: str
    items: list[EntityHistoryItem]

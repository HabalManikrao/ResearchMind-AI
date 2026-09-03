"""Knowledge Graph + Temporal Knowledge (#7).

A persistent, evidence-backed, temporal model layered **over** the existing research
substrate — entities, entity↔entity relationships, entity↔{claim,source,document,run}
mentions, and claim↔claim links. It never duplicates claims/sources/evidence; it references
them by id and derives its facts from already-extracted structured data (Solutions,
Recommendation, Claims) so a normal run adds no LLM calls (spec §2, §8, §10).

All four tables are new (created by ``create_all``); no existing table is migrated. Every row
carries ``user_id`` (nullable → legacy/unowned, readable by any user) for isolation (§24).
``entity_type`` / ``predicate`` are plain strings validated against an in-code registry, so
new types/predicates need no schema change (§5, §7).
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


# Provenance of a graph fact (spec §18): where it came from / how much to trust the shape.
EXPLICIT = "explicit"   # present verbatim in existing structured data
DERIVED = "derived"     # deterministically derived from claims/solutions/lineage
INFERRED = "inferred"   # produced by the optional bounded LLM tier

# Temporal status of a relationship (spec §13).
ACTIVE = "active"
SUPERSEDED = "superseded"
RETRACTED = "retracted"
DISPUTED = "disputed"
HISTORICAL = "historical"


class KgEntity(Base):
    """A normalized, per-user-canonical entity (spec §5, §6)."""

    __tablename__ = "kg_entities"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    canonical_name: Mapped[str] = mapped_column(String(500))  # display form (preserved)
    # Lowercased/whitespace-collapsed/punctuation-trimmed key used for matching + dedup.
    normalized_name: Mapped[str] = mapped_column(String(500), index=True)
    # Extensible string (validated against a registry), NOT an Enum column, so adding a
    # new type never requires a migration (spec §5).
    entity_type: Mapped[str] = mapped_column(String(40), default="other", index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    aliases: Mapped[list] = mapped_column(JSON, default=list)
    meta: Mapped[dict] = mapped_column(JSON, default=dict)
    mention_count: Mapped[int] = mapped_column(Integer, default=0)
    first_observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )


class KgRelationship(Base):
    """A temporal entity↔entity relationship (spec §7, §13). Provenance-tracked."""

    __tablename__ = "kg_relationships"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    subject_entity_id: Mapped[str] = mapped_column(String(36), index=True)
    predicate: Mapped[str] = mapped_column(String(40), index=True)  # validated registry
    object_entity_id: Mapped[str] = mapped_column(String(36), index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[float] = mapped_column(Float, default=0.5)  # 0-1
    provenance_kind: Mapped[str] = mapped_column(String(20), default=DERIVED)
    status: Mapped[str] = mapped_column(String(20), default=ACTIVE)
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    first_observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Provenance references (ids, never copied passages — spec §15).
    project_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    claim_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    source_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    meta: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )


class KgMention(Base):
    """Polymorphic entity↔{claim,source,document,project} provenance edge (spec §8, §10-§12).

    One lean table connects an entity to existing records **without duplicating them** — the
    ``target_type``/``target_id`` point at the real Claim/Source/Document/ResearchProject.
    """

    __tablename__ = "kg_mentions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    entity_id: Mapped[str] = mapped_column(String(36), index=True)
    target_type: Mapped[str] = mapped_column(String(20), index=True)  # claim|source|document|project
    target_id: Mapped[str] = mapped_column(String(36), index=True)
    project_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)  # run context
    role: Mapped[str | None] = mapped_column(String(30), nullable=True)  # e.g. mentions|about|supported_by
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    provenance_kind: Mapped[str] = mapped_column(String(20), default=DERIVED)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class KgClaimLink(Base):
    """A relationship between two existing Claim rows (spec §9, §13, §14, §38).

    ``SUPERSEDES`` (subject=new claim, object=old claim) is the temporal transition produced
    by reconciling a Research Diff — the existing claims are referenced, never copied.
    """

    __tablename__ = "kg_claim_links"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    subject_claim_id: Mapped[str] = mapped_column(String(36), index=True)
    predicate: Mapped[str] = mapped_column(String(30), index=True)  # supersedes|supports|contradicts|related_to|depends_on
    object_claim_id: Mapped[str] = mapped_column(String(36), index=True)
    project_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    confidence: Mapped[float] = mapped_column(Float, default=0.7)
    provenance_kind: Mapped[str] = mapped_column(String(20), default=DERIVED)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

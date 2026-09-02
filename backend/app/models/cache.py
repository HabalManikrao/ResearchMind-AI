"""Bounded web-source cache (Connectivity Intelligence, #5).

Previously-retrieved *external* source results, kept so a run can reuse them when the
live provider is temporarily unavailable and policy allows (spec §9, §11, §13). Keyed
by ``(project_id, source_type, query_hash)`` so a failed live search can be answered
with the same query's last successful result set.

Isolation (spec §30): every row carries ``project_id`` (and the owning ``user_id``);
all reads filter by ``project_id`` so a cached source in one project can never surface
in another. **Nothing sensitive is cached** — only the public result content, never
API keys, auth headers, cookies, or request credentials.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, Float, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


class CachedSource(Base):
    """One cached external source (a flattened member of a cached query result set)."""

    __tablename__ = "cached_sources"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    # Owning project + user — the isolation boundary (spec §30).
    project_id: Mapped[str] = mapped_column(String(36), index=True)
    user_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    # The query this result answered, hashed, so a failed live search can be matched.
    query_hash: Mapped[str] = mapped_column(String(64), index=True)
    source_type: Mapped[str] = mapped_column(String(50), default="web")

    title: Mapped[str] = mapped_column(String(1000), default="")
    url: Mapped[str] = mapped_column(String(2000))
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    published_date: Mapped[str | None] = mapped_column(String(50), nullable=True)
    reliability_score: Mapped[float] = mapped_column(Float, default=50.0)
    relevance_score: Mapped[float] = mapped_column(Float, default=0.0)
    # sha256 of the content, so a re-fetch with identical content is detectable (§9).
    checksum: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # The original source meta (findings ride here too); never headers/keys (§30).
    meta: Mapped[dict] = mapped_column(JSON, default=dict)

    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    __table_args__ = (
        Index("ix_cached_sources_lookup", "project_id", "source_type", "query_hash"),
    )

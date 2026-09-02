"""Enumerations shared across models, schemas, and the orchestrator."""
from __future__ import annotations

import enum


class ResearchMode(str, enum.Enum):
    QUICK = "quick"
    STANDARD = "standard"
    DEEP = "deep"
    TECHNICAL_RD = "technical_rd"
    COMPARISON = "comparison"
    DECISION = "decision"
    # Recency-biased "what's happening in the market right now" research: prefers
    # recent sources, grounds strictly on fetched content, and reports a snapshot
    # of the current state with an "as of" date.
    MARKET = "market"


class ProjectStatus(str, enum.Enum):
    CREATED = "created"
    PLANNING = "planning"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TaskStatus(str, enum.Enum):
    PENDING = "pending"
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    RETRYING = "retrying"
    PAUSED = "paused"
    CANCELLED = "cancelled"


class ClaimStatus(str, enum.Enum):
    VERIFIED = "verified"
    PARTIALLY_VERIFIED = "partially_verified"
    CONFLICTED = "conflicted"
    UNVERIFIED = "unverified"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


class ConflictStatus(str, enum.Enum):
    NEEDS_VERIFICATION = "needs_verification"
    UNRESOLVED = "unresolved"
    RESOLVED = "resolved"


class ConflictSeverity(str, enum.Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class DocumentStatus(str, enum.Enum):
    """Lifecycle of an uploaded document through the processing pipeline."""

    UPLOADED = "uploaded"
    PARSING = "parsing"
    CHUNKING = "chunking"
    EMBEDDING = "embedding"
    INDEXING = "indexing"
    READY = "ready"
    FAILED = "failed"


class SourcePolicy(str, enum.Enum):
    """How a research run is allowed to source evidence (Connectivity Intelligence,
    #5, spec §11, §12). Controls the live/cached/local fallback behaviour.

    LIVE_ONLY      — external evidence must be freshly retrieved; never serve cache.
    LIVE_PREFERRED — try live first, fall back to cache, then local (the default).
    CACHE_ALLOWED  — same as live_preferred but cache is used freely/eagerly.
    LOCAL_ONLY     — no external fetches at all; documents/memory/DB only (offline).
    """

    LIVE_ONLY = "live_only"
    LIVE_PREFERRED = "live_preferred"
    CACHE_ALLOWED = "cache_allowed"
    LOCAL_ONLY = "local_only"


class EvidenceStance(str, enum.Enum):
    """How a source relates to a claim in the evidence graph (spec §6).

    SUPPORTS  — the source's finding backs the claim.
    CONTRADICTS — the source provides disconfirming evidence (found by the
                  active contradiction search).
    NEUTRAL   — related/context but neither confirms nor refutes.
    """

    SUPPORTS = "supports"
    CONTRADICTS = "contradicts"
    NEUTRAL = "neutral"

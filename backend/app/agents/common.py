"""Shared types for research agents.

Every collection agent (web, docs, github, academic, news, community) returns a
list of CollectedSource so the orchestrator can persist and verify them uniformly,
regardless of where they came from.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class CollectedSource:
    title: str
    url: str
    content: str
    summary: str
    reliability_score: float
    relevance_score: float
    source_type: str  # "web" | "docs" | "github" | "papers" | "news" | "community"
    published_date: str | None = None
    findings: list[str] = field(default_factory=list)
    meta: dict = field(default_factory=dict)  # source-type-specific structured fields


# Human-readable labels for progress/activity messages.
AGENT_LABELS = {
    "web": "Web agent",
    "docs": "Documentation agent",
    "github": "GitHub agent",
    "papers": "Academic agent",
    "news": "News agent",
    "community": "Community agent",
    "documents": "Documents agent",
}

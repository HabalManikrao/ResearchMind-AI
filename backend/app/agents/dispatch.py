"""Routes a research task to the right collection agent by source type.

Adding a new source agent means: implement its `collect(...)`, add a branch here,
and add it to SOURCE_QUESTION_BUDGET in the orchestrator. Nothing else changes —
persistence, verification, and reporting are source-agnostic.
"""
from __future__ import annotations

from app.agents import (
    academic_research,
    document_research,
    github_research,
    tavily_agents,
)
from app.agents.common import CollectedSource
from app.config import Settings
from app.llm.base import AIProvider
from app.search.tavily_client import TavilyClient

TAVILY_SOURCES = {"web", "docs", "news", "community"}
ALL_SOURCES = TAVILY_SOURCES | {"github", "papers", "documents"}


async def collect(
    source_type: str,
    provider: AIProvider,
    tavily: TavilyClient,
    settings: Settings,
    *,
    question: str,
    search_query: str,
    recency_days: int | None = None,
    project_id: str = "",
) -> list[CollectedSource]:
    n = settings.max_sources_per_task
    if source_type in TAVILY_SOURCES:
        return await tavily_agents.collect(
            provider, tavily,
            source_type=source_type,
            question=question,
            search_query=search_query,
            max_results=n,
            recency_days=recency_days,
        )
    if source_type == "github":
        return await github_research.collect(
            provider,
            question=question,
            search_query=search_query,
            token=settings.github_token,
            max_results=n,
        )
    if source_type == "papers":
        return await academic_research.collect(
            provider,
            question=question,
            search_query=search_query,
            max_results=n,
        )
    if source_type == "documents":
        # Local retrieval over the project's uploaded documents (offline-capable).
        return await document_research.collect(
            provider,
            project_id=project_id,
            question=question,
            search_query=search_query,
            max_results=n,
        )
    raise ValueError(f"Unknown source type: {source_type}")

"""Tavily-backed research agents: Web, Documentation, News, Community.

They share the same search+extract machinery but differ in how they query and how
their sources are scored:

- **web**       — general web search.
- **docs**      — biased toward official documentation; higher reliability.
- **news**      — recent items only (topic=news, last N days); dates always shown.
- **community** — restricted to developer communities; labelled as lower authority.
"""
from __future__ import annotations

from app.agents.common import CollectedSource
from app.llm.base import AIProvider
from app.search.tavily_client import SearchResult, TavilyClient
from app.services.scoring import reliability_score

_FINDINGS_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "findings": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["summary", "findings"],
}

_SYSTEM = (
    "You extract factual, on-topic findings from a source's content relative to a "
    "specific research question. Only use information present in the content. Never "
    "invent facts. Return a short summary and a list of concise standalone findings."
)

_COMMUNITY_DOMAINS = [
    "reddit.com",
    "stackoverflow.com",
    "news.ycombinator.com",
    "dev.to",
    "medium.com",
]

# Query hints and Tavily params per source type.
_CONFIG = {
    "web": {"suffix": "", "kwargs": {}},
    "docs": {
        "suffix": " official documentation",
        "kwargs": {},
    },
    "news": {
        "suffix": "",
        "kwargs": {"topic": "news", "days": 30},
    },
    "community": {
        "suffix": " forum discussion experience",
        "kwargs": {"include_domains": _COMMUNITY_DOMAINS},
    },
}


def _time_range_for(days: int) -> str:
    """Map a recency window in days to Tavily's coarse time_range buckets."""
    if days <= 1:
        return "day"
    if days <= 7:
        return "week"
    if days <= 31:
        return "month"
    return "year"


async def collect(
    provider: AIProvider,
    tavily: TavilyClient,
    *,
    source_type: str,
    question: str,
    search_query: str,
    max_results: int = 5,
    recency_days: int | None = None,
) -> list[CollectedSource]:
    cfg = _CONFIG[source_type]
    query = f"{search_query}{cfg['suffix']}".strip()
    kwargs = dict(cfg["kwargs"])
    # Market Intelligence mode: bias toward recent results.
    if recency_days:
        if source_type == "news":
            # News already filters by days; tighten it to the requested window.
            kwargs["days"] = recency_days
        else:
            # General/docs/community search uses Tavily's time_range buckets.
            kwargs["time_range"] = _time_range_for(recency_days)
    results: list[SearchResult] = await tavily.search(
        query, max_results=max_results, **kwargs
    )

    sources: list[CollectedSource] = []
    for r in results:
        if not r.url or not r.content:
            continue
        summary, findings = await _extract(provider, question, r)
        sources.append(
            CollectedSource(
                title=r.title,
                url=r.url,
                content=r.content,
                summary=summary,
                reliability_score=_score(source_type, r),
                relevance_score=round(r.score * 100, 1),
                source_type=source_type,
                published_date=r.published_date,
                findings=findings,
                meta={},
            )
        )
    return sources


def _score(source_type: str, r: SearchResult) -> float:
    base = reliability_score(r.url, relevance=r.score)
    if source_type == "docs":
        # Nudge documentation up; it is meant to prioritise authoritative sources.
        return round(min(100.0, base + 8), 1)
    if source_type == "community":
        # Community is never treated as authoritative as official docs (spec Agent 8).
        return round(min(65.0, base), 1)
    return base


async def _extract(
    provider: AIProvider, question: str, result: SearchResult
) -> tuple[str, list[str]]:
    prompt = (
        f"Research question:\n{question}\n\n"
        f"Source: {result.title} ({result.url})\n\n"
        f"Content:\n{result.content[:3000]}\n\n"
        "Extract findings relevant to the question. Return JSON."
    )
    try:
        data = await provider.structured_output(
            prompt, schema=_FINDINGS_SCHEMA, system=_SYSTEM
        )
    except Exception:
        return (result.content[:300], [])
    summary = str(data.get("summary", "")).strip()
    findings = [str(f).strip() for f in data.get("findings", []) if str(f).strip()]
    return summary, findings

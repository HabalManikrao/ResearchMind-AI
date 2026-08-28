"""Tavily search client.

Tavily is an AI-oriented search API that returns extracted page content and a
relevance score per result, so the web agent does not need to crawl/scrape pages
itself for the MVP. If no API key is configured the client raises SearchError with
a clear message rather than silently returning nothing.
"""
from __future__ import annotations

from dataclasses import dataclass

import httpx

TAVILY_URL = "https://api.tavily.com/search"


class SearchError(RuntimeError):
    pass


@dataclass
class SearchResult:
    title: str
    url: str
    content: str
    score: float  # 0-1 relevance from Tavily
    published_date: str | None = None


class TavilyClient:
    def __init__(self, api_key: str, *, timeout: float = 30.0) -> None:
        self.api_key = api_key
        self.timeout = timeout

    async def search(
        self,
        query: str,
        *,
        max_results: int = 5,
        depth: str = "advanced",
        topic: str | None = None,
        days: int | None = None,
        time_range: str | None = None,
        include_domains: list[str] | None = None,
    ) -> list[SearchResult]:
        """Search the web.

        - topic="news" + days=N restricts to recent news (News agent).
        - time_range="day|week|month|year" biases general search toward recent
          results (Market Intelligence mode).
        - include_domains restricts results to specific hosts (Docs/Community agents).
        """
        if not self.api_key:
            raise SearchError(
                "TAVILY_API_KEY is not set. Add it to backend/.env "
                "(get a free key at https://app.tavily.com)."
            )
        payload: dict = {
            "api_key": self.api_key,
            "query": query,
            "max_results": max_results,
            "search_depth": depth,
            "include_answer": False,
            "include_raw_content": False,
        }
        if topic:
            payload["topic"] = topic
        if days is not None:
            payload["days"] = days
        if time_range:
            payload["time_range"] = time_range
        if include_domains:
            payload["include_domains"] = include_domains
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(TAVILY_URL, json=payload)
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPStatusError as exc:
            raise SearchError(
                f"Tavily returned {exc.response.status_code}: {exc.response.text[:200]}"
            ) from exc
        except httpx.HTTPError as exc:
            raise SearchError(f"Tavily request failed: {exc}") from exc

        results: list[SearchResult] = []
        for item in data.get("results", []):
            results.append(
                SearchResult(
                    title=item.get("title", "Untitled"),
                    url=item.get("url", ""),
                    content=item.get("content", ""),
                    score=float(item.get("score", 0.0)),
                    published_date=item.get("published_date"),
                )
            )
        return results

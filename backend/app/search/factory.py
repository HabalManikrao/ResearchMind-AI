"""Search-client factory.

Selects the search backend from `settings.search_provider`. Both clients expose the
same `search(...)` coroutine returning `list[SearchResult]`, so the orchestrator and
agents are backend-agnostic. Add a new provider by implementing that method and a
branch here.
"""
from __future__ import annotations

from app.config import Settings
from app.search.searxng_client import SearxngClient
from app.search.tavily_client import TavilyClient


def get_search_client(settings: Settings):
    """Return the configured search client (Tavily or SearXNG)."""
    provider = (settings.search_provider or "tavily").lower()
    if provider == "searxng":
        return SearxngClient(
            settings.searxng_url,
            fetch_content=settings.searxng_fetch_content,
            fetch_limit=settings.searxng_fetch_limit,
            engines=settings.searxng_engines,
            verify_ssl=settings.searxng_verify_ssl,
        )
    return TavilyClient(settings.tavily_api_key)

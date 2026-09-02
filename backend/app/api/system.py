"""Health, connectivity & settings endpoints (spec §22, §37)."""
from __future__ import annotations

from fastapi import APIRouter

from app.config import get_settings
from app.llm import get_provider
from app.services import connectivity

router = APIRouter(tags=["system"])


@router.get("/health")
async def health():
    s = get_settings()
    provider = get_provider()
    llm_ok = await provider.health_check()
    emb_check = getattr(provider, "embeddings_available", None)
    emb_ok = await emb_check() if (emb_check and s.knowledge_enabled) else False
    # SearXNG needs a URL; Tavily needs an API key.
    search_configured = (
        bool(s.searxng_url)
        if s.search_provider.lower() == "searxng"
        else bool(s.tavily_api_key)
    )
    return {
        "status": "ok",
        "llm": {
            "provider": provider.name,
            "model": s.ollama_model,
            "reachable": llm_ok,
        },
        "knowledge": {
            "enabled": s.knowledge_enabled,
            "embedding_model": s.embedding_model,
            "semantic": emb_ok,
        },
        "search": {"provider": s.search_provider, "configured": search_configured},
        "agents": {
            "web": search_configured,
            "docs": search_configured,
            "news": search_configured,
            "community": search_configured,
            "github": True,  # works unauthenticated; token only raises rate limits
            "papers": True,  # arXiv needs no key
        },
        "github_token_configured": bool(s.github_token),
    }


@router.get("/system/connectivity")
async def read_connectivity():
    """Layered connectivity snapshot (#5, spec §37): overall state, internet, the
    search provider, and local services (Ollama/Qdrant/DB), plus the effective research
    mode. Cached briefly; exposes no secrets or internal network detail."""
    s = get_settings()
    if not s.connectivity_enabled:
        return {"enabled": False, "overall_status": "unknown"}
    snap = await connectivity.manager.snapshot()
    mode = connectivity.research_mode_for(snap, s.default_source_policy)
    return {
        "enabled": True,
        "overall_status": snap.overall,
        "recovering": snap.recovering,
        "internet": snap.internet,
        "providers": {"search": snap.search_provider},
        "local_services": {
            "ollama": snap.ollama,
            "qdrant": snap.qdrant,
            "database": snap.database,
        },
        "research_mode": mode,
        "last_checked_age_seconds": None,
    }


@router.get("/settings")
async def read_settings():
    s = get_settings()
    return {
        "ollama_base_url": s.ollama_base_url,
        "ollama_model": s.ollama_model,
        "llm_temperature": s.llm_temperature,
        "llm_max_tokens": s.llm_max_tokens,
        "tavily_configured": bool(s.tavily_api_key),
        "github_token_configured": bool(s.github_token),
        "max_research_tasks": s.max_research_tasks,
        "max_followup_rounds": s.max_followup_rounds,
        "max_sources_per_task": s.max_sources_per_task,
    }

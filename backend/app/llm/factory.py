"""Provider factory. Returns the configured default provider (Ollama for MVP)."""
from __future__ import annotations

from functools import lru_cache

from app.config import get_settings
from app.llm.base import AIProvider
from app.llm.ollama_provider import OllamaProvider


@lru_cache
def get_provider() -> AIProvider:
    s = get_settings()
    return OllamaProvider(
        base_url=s.ollama_base_url,
        model=s.ollama_model,
        temperature=s.llm_temperature,
        max_tokens=s.llm_max_tokens,
        embedding_model=s.embedding_model,
        keep_alive=s.ollama_keep_alive,
        num_ctx=s.ollama_num_ctx,
    )

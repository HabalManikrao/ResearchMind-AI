"""Application configuration loaded from environment / .env."""
from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # LLM (Ollama)
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.1:8b"
    llm_temperature: float = 0.2
    llm_max_tokens: int = 4096
    # Keep the model resident between calls (Ollama keep_alive) so slow CPU-only
    # setups don't reload multiple GB on every pipeline step. "0" unloads immediately.
    ollama_keep_alive: str = "30m"
    # Pin the context window (num_ctx). 0 = use the model default. Lowering it speeds
    # prefill on CPU when prompts are short (e.g. snippet-only collection).
    ollama_num_ctx: int = 0

    # Embeddings / knowledge base (Ollama + Qdrant local mode)
    embedding_model: str = "nomic-embed-text"
    qdrant_path: str = "./qdrant_data"  # local on-disk vector store (no server)
    knowledge_enabled: bool = True

    # Search
    # Which backend powers the Web/Docs/News/Community agents: "tavily" (managed,
    # needs a key) or "searxng" (free, self-hosted, no key).
    search_provider: str = "tavily"
    tavily_api_key: str = ""
    # SearXNG (self-hosted metasearch). Point at a running instance with JSON output
    # enabled (settings.yml: search.formats: [html, json]).
    searxng_url: str = "http://localhost:8080"
    # SearXNG returns snippets only; fetch the top results' pages to extract full
    # text (SSRF-safe). Turn off for faster, snippet-only results.
    searxng_fetch_content: bool = True
    searxng_fetch_limit: int = 5
    searxng_engines: str = ""  # optional comma list, e.g. "google,bing,duckduckgo"
    searxng_verify_ssl: bool = True
    # Optional: raises GitHub API rate limits from 10 -> 30 req/min for the
    # GitHub Research Agent. Works without it, just more rate-limited.
    github_token: str = ""

    # Corporate / self-signed CA trust. If this machine sits behind a TLS-inspecting
    # proxy (e.g. Sophos, Zscaler, Netskope), non-Windows TLS clients (httpx/requests)
    # won't trust the proxy's root CA and every outbound HTTPS fetch fails with
    # CERTIFICATE_VERIFY_FAILED. Point this at a PEM bundle that includes the proxy's
    # root CA; on startup it's exported as SSL_CERT_FILE/REQUESTS_CA_BUNDLE so all
    # outbound fetches (content extraction, GitHub, arXiv) verify. Relative to backend/.
    ca_bundle: str = ""

    # Database
    database_url: str = "sqlite+aiosqlite:///./researchmind.db"

    # Server
    cors_origins: str = "http://localhost:5173,http://localhost:3000"

    # Security
    rate_limit_per_minute: int = 120  # per client IP; 0 disables
    allow_private_fetch: bool = False  # allow outbound fetches to private/localhost hosts

    # Authentication (JWT). When auth_enabled is False, endpoints run as a shared
    # local user (no login required) — convenient for a single-user offline setup.
    auth_enabled: bool = True
    jwt_secret: str = "dev-insecure-change-me"  # MUST be overridden in production
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 1440  # 24h
    # If set, the very first registration is allowed and further ones are blocked
    # unless this is empty. Empty string = open registration.
    registration_open: bool = True

    # Research budgets
    max_research_tasks: int = 24
    max_followup_rounds: int = 2
    max_sources_per_task: int = 5

    # Scheduled research (in-process poller; spec §11)
    scheduler_enabled: bool = True
    scheduler_poll_seconds: int = 30  # how often to check for due schedules
    min_schedule_interval_minutes: int = 15  # floor to avoid runaway cadences

    # Market Intelligence mode: how far back "recent" reaches when biasing search.
    market_recency_days: int = 180

    # Active contradiction search (spec §6, §23.3: never trust a single source).
    # After claims are consolidated, the top-priority claims are re-checked by
    # actively searching for *disconfirming* evidence. Bounded to keep CPU-only
    # runs affordable: only claims at/above the confidence floor are checked, and
    # only the top-N of those.
    contradiction_search_enabled: bool = True
    max_contradiction_checks: int = 3
    contradiction_min_confidence: float = 55.0

    # Document RAG (#3): local PDF/DOCX ingestion → chunk → embed → Qdrant → retrieval.
    document_storage_dir: str = "./document_storage"  # uploaded files (gitignored)
    max_document_mb: int = 25                          # per-file upload cap
    document_chunk_tokens: int = 350                   # approx target chunk size
    document_chunk_overlap_tokens: int = 60            # overlap between adjacent chunks
    document_retrieval_top_k: int = 5                  # passages returned per query
    document_retrieval_min_score: float = 0.25         # cosine score floor for a hit
    document_embed_batch: int = 16                     # embedding batch size (CPU-bounded)

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()

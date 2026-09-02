"""Connectivity Intelligence (#5): a layered, cached, non-polling health model.

Not a single ``internet_connected`` boolean and not an ICMP ping (spec §4, §5). We
probe the layers that actually matter to research — external internet reachability, the
configured search provider, and the local dependencies (Ollama, Qdrant, DB) — each with
a short bounded timeout, and cache the resulting snapshot briefly so we don't re-probe
on every source (spec §5, §32). A tiny previous-state memory yields the ``recovering``
transition without any background polling (spec §27).

The probes are module-level async functions so tests can monkeypatch them without
touching the network. The manager is a process-wide singleton (``manager``).
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import asdict, dataclass, field
from urllib.parse import urlparse

import httpx

from app.config import get_settings

# --- Overall connectivity states (spec §6) --------------------------------- #
ONLINE = "online"          # internet + search provider reachable
DEGRADED = "degraded"      # internet up, but a provider/source is down
LOCAL_ONLY = "local_only"  # no internet, but local infra (Ollama/Qdrant) works
OFFLINE = "offline"        # no internet and local infra also impaired
RECOVERING = "recovering"  # just came back after being offline/degraded
UNKNOWN = "unknown"        # could not establish state

# The hosts we actually call — probing these (not a hard-coded unrelated site)
# tells us whether *our* research surface is reachable (spec §5).
_GITHUB_HOST = "https://api.github.com"
_ARXIV_HOST = "https://export.arxiv.org"


@dataclass
class ConnectivitySnapshot:
    overall: str
    internet: bool | None
    search_provider: bool | None
    ollama: bool | None
    qdrant: bool | None
    database: bool | None
    recovering: bool = False
    checked_at: float = 0.0
    layers: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = asdict(self)
        return d


# --------------------------------------------------------------------------- #
# Layer probes (monkeypatchable). Each is bounded and swallows its own errors.
# --------------------------------------------------------------------------- #
async def _head_reachable(url: str, timeout: float) -> bool:
    """True if the host answers at all (any HTTP status = reachable). Only a
    connect/DNS/timeout error counts as unreachable."""
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            await client.head(url)
        return True
    except httpx.HTTPStatusError:
        return True  # a status response still proves reachability
    except httpx.HTTPError:
        return False


async def probe_internet(timeout: float) -> bool:
    """Reachable if ANY of the hosts we use responds (spec §5: not one site, not ICMP)."""
    s = get_settings()
    hosts = [_GITHUB_HOST, _ARXIV_HOST]
    # Include the configured search provider host too.
    if s.search_provider.lower() == "searxng" and s.searxng_url:
        hosts.append(s.searxng_url)
    else:
        hosts.append("https://api.tavily.com")
    results = await asyncio.gather(
        *(_head_reachable(h, timeout) for h in hosts), return_exceptions=True
    )
    return any(r is True for r in results)


async def probe_search_provider(timeout: float) -> bool:
    """Is the configured search backend reachable? SearXNG: GET its base URL. Tavily:
    the host must be reachable AND a key configured (else it can't be used)."""
    s = get_settings()
    if s.search_provider.lower() == "searxng":
        if not s.searxng_url:
            return False
        return await _head_reachable(s.searxng_url, timeout)
    # Tavily: needs a key, and the endpoint must be reachable.
    if not s.tavily_api_key:
        return False
    return await _head_reachable("https://api.tavily.com", timeout)


async def probe_ollama(timeout: float) -> bool:
    try:
        from app.llm import get_provider

        return await asyncio.wait_for(get_provider().health_check(), timeout=timeout + 8)
    except Exception:  # noqa: BLE001
        return False


async def probe_qdrant(timeout: float) -> bool:
    if not get_settings().knowledge_enabled:
        return False
    try:
        from app.knowledge import vector_store

        def _check() -> bool:
            vector_store.get_client().get_collections()
            return True

        return await asyncio.wait_for(asyncio.to_thread(_check), timeout=timeout + 5)
    except Exception:  # noqa: BLE001
        return False


async def probe_database(timeout: float) -> bool:
    try:
        from sqlalchemy import text

        from app.database import SessionLocal

        async def _check() -> bool:
            async with SessionLocal() as db:
                await db.execute(text("SELECT 1"))
            return True

        return await asyncio.wait_for(_check(), timeout=timeout + 5)
    except Exception:  # noqa: BLE001
        return False


def _derive_overall(
    internet: bool, provider: bool, ollama: bool, qdrant: bool
) -> str:
    if internet and provider:
        return ONLINE
    if internet and not provider:
        return DEGRADED
    # No internet (or provider unusable without internet).
    if not internet:
        # Local research still possible if Ollama is up (Qdrant optional).
        return LOCAL_ONLY if ollama else OFFLINE
    return UNKNOWN


class ConnectivityManager:
    """On-demand layered connectivity with a short-TTL cached snapshot (spec §5, §32)."""

    def __init__(self) -> None:
        self._cache: ConnectivitySnapshot | None = None
        self._previous_overall: str | None = None
        self._lock = asyncio.Lock()

    async def snapshot(self, *, force: bool = False) -> ConnectivitySnapshot:
        s = get_settings()
        now = time.monotonic()
        if (
            not force
            and self._cache is not None
            and (now - self._cache.checked_at) < s.connectivity_cache_seconds
        ):
            return self._cache

        async with self._lock:
            # Re-check the cache under the lock (another caller may have refreshed).
            now = time.monotonic()
            if (
                not force
                and self._cache is not None
                and (now - self._cache.checked_at) < s.connectivity_cache_seconds
            ):
                return self._cache

            timeout = float(s.connectivity_timeout_seconds)
            internet, provider, ollama, qdrant, database = await asyncio.gather(
                probe_internet(timeout),
                probe_search_provider(timeout),
                probe_ollama(timeout),
                probe_qdrant(timeout),
                probe_database(timeout),
            )
            overall = _derive_overall(internet, provider, ollama, qdrant)

            # Recovery: a fresh healthy probe after a degraded/offline cached state.
            recovering = (
                overall == ONLINE
                and self._previous_overall in (OFFLINE, LOCAL_ONLY, DEGRADED)
            )
            reported = RECOVERING if recovering else overall

            snap = ConnectivitySnapshot(
                overall=reported,
                internet=internet,
                search_provider=provider,
                ollama=ollama,
                qdrant=qdrant,
                database=database,
                recovering=recovering,
                checked_at=now,
                layers={
                    "internet": internet,
                    "search_provider": provider,
                    "ollama": ollama,
                    "qdrant": qdrant,
                    "database": database,
                },
            )
            self._cache = snap
            # Store the *settled* state (ONLINE, not RECOVERING) as the new baseline.
            self._previous_overall = overall
            return snap

    def invalidate(self) -> None:
        self._cache = None


manager = ConnectivityManager()


def research_mode_for(snapshot: ConnectivitySnapshot, policy: str) -> str:
    """The effective research mode given connectivity + policy (spec §12).
    Returns one of: ``live`` | ``hybrid`` | ``cache`` | ``local``."""
    from app.models.enums import SourcePolicy

    if policy == SourcePolicy.LOCAL_ONLY.value:
        return "local"
    online = snapshot.overall in (ONLINE, RECOVERING)
    if online:
        return "live"
    # Offline/degraded: local infra decides whether we can still research.
    if snapshot.ollama:
        return "local"
    return "local"


def provider_host(url: str) -> str:
    return (urlparse(url).hostname or "").lower()

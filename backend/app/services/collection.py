"""Resilient collection wrapper (Connectivity Intelligence, #5).

A thin, **source-agnostic** layer over ``dispatch.collect`` that adds provenance
stamping and live→cache fallback without touching any individual agent (spec §5 reuse,
§8 live-correctness, §13 fallback). The orchestrator calls this instead of
``dispatch.collect`` directly; the existing per-task try/except still provides
partial-failure resilience (spec §14) — a raised exception here means "this task
genuinely failed", which the orchestrator records as ``UNAVAILABLE``.

Rules:
- **local agents** (``documents``) always run; stamped ``local_document``; never cached.
- **external agents**: honour the run's :class:`SourcePolicy`:
  - ``LOCAL_ONLY`` → skipped (no network at all).
  - live success → stamped ``live_web`` + ``retrieved_at``; cached for reuse unless the
    policy is ``LIVE_ONLY`` (strict verification must never persist a cacheable copy).
  - live failure → ``LIVE_ONLY`` re-raises (honest failure); otherwise serve the last
    good cached result (``cached_web``) if within TTL, else re-raise.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from app.agents import dispatch
from app.agents.common import CollectedSource
from app.models.enums import SourcePolicy
from app.services import provenance as prov
from app.services import source_cache

# Per-task collection outcomes (used for run-health accounting, spec §23, §40).
LIVE = "live"
CACHED = "cached"
LOCAL = "local"
SKIPPED = "skipped"


@dataclass
class CollectionResult:
    sources: list[CollectedSource]
    outcome: str  # live | cached | local | skipped


def _stamp(sources: list[CollectedSource], provenance: str) -> None:
    now = datetime.now(timezone.utc).isoformat()
    for s in sources:
        meta = dict(s.meta or {})
        # Don't overwrite a provenance the agent already set intentionally.
        meta.setdefault("provenance", provenance)
        if provenance == prov.LIVE_WEB:
            meta["retrieved_at"] = now
        s.meta = meta


async def resilient_collect(
    agent: str,
    provider,
    tavily,
    settings,
    *,
    question: str,
    search_query: str,
    recency_days: int | None = None,
    project_id: str = "",
    user_id: str | None = None,
    policy: str = SourcePolicy.LIVE_PREFERRED.value,
) -> CollectionResult:
    query = search_query or question

    # --- Local agents: always available, never cached, no network. ---------- #
    if not prov.is_external(agent):
        sources = await dispatch.collect(
            agent, provider, tavily, settings,
            question=question, search_query=search_query,
            recency_days=recency_days, project_id=project_id,
        )
        _stamp(sources, prov.LOCAL_DOCUMENT)
        return CollectionResult(sources=sources, outcome=LOCAL)

    # --- External agents under LOCAL_ONLY: skip entirely. ------------------- #
    if policy == SourcePolicy.LOCAL_ONLY.value:
        return CollectionResult(sources=[], outcome=SKIPPED)

    allow_cache = policy != SourcePolicy.LIVE_ONLY.value

    # --- Try live first. ---------------------------------------------------- #
    try:
        sources = await dispatch.collect(
            agent, provider, tavily, settings,
            question=question, search_query=search_query,
            recency_days=recency_days, project_id=project_id,
        )
        _stamp(sources, prov.LIVE_WEB)
        if allow_cache and sources:
            await source_cache.put(project_id, user_id, agent, query, sources)
        return CollectionResult(sources=sources, outcome=LIVE)
    except Exception:  # noqa: BLE001 - live fetch failed; consider cache fallback
        if not allow_cache:
            raise  # LIVE_ONLY: a failure is a failure (spec §11 strict verification)
        cached = await source_cache.get(project_id, agent, query)
        if cached:
            return CollectionResult(sources=cached, outcome=CACHED)
        raise  # no cache → genuine UNAVAILABLE (orchestrator marks the task FAILED)

"""Live-web evaluation runner (#11). Drives the EXISTING collection path (no bespoke crawler)
for whichever provider is actually reachable, captures a run manifest, and computes the
collection-quality metrics. Provider-unavailable tasks are recorded as **skipped**, never faked
as live (Phase 5 provenance rule, Phase 2 honesty)."""
from __future__ import annotations

import time

from app.agents import github_research as gh
from app.config import get_settings
from evaluation.live_web import capture, metrics


class ProviderUnavailable(Exception):
    """Raised when a task's required live provider is not reachable in this environment."""


async def collect_github(search_query: str, *, max_results: int = 8) -> list[dict]:
    """Genuine live GitHub retrieval via the production search (no LLM). Each result is stamped
    provenance=live_web ONLY because it was actually retrieved live this run (Phase 5)."""
    settings = get_settings()
    token = settings.github_token or ""
    t0 = time.monotonic()
    repos = await gh._search_repos(search_query, token, max_results)
    elapsed_ms = int((time.monotonic() - t0) * 1000)

    sources: list[dict] = []
    now = _now_iso()
    for rank, repo in enumerate(repos):
        stars = repo.get("stargazers_count", 0)
        active = gh._is_active(repo.get("pushed_at"))
        archived = bool(repo.get("archived", False))
        reliability = gh.github_reliability(stars, active=active, archived=archived)
        sources.append(capture.source_record(
            url=repo.get("html_url", ""),
            title=repo.get("full_name", "repo"),
            source_type="github",
            reliability=reliability,
            rank=rank,
            provenance="live_web",                 # actually retrieved live this run
            published_date=repo.get("pushed_at"),
            discovering_query=search_query,
            latency_ms=elapsed_ms if rank == 0 else None,
            meta={"owner": (repo.get("owner") or {}).get("login"),
                  "stars": stars, "forks": repo.get("forks_count", 0),
                  "language": repo.get("language"), "archived": archived},
        ))
    return sources


def score_sources(task: dict, sources: list[dict], *, live: bool) -> dict:
    """Compute the collection-quality metrics for one task's captured sources."""
    ref = task.get("reference_sources", {})
    return {
        "source_recall": metrics.source_recall(sources, ref),
        "ranking": metrics.ranking_quality(sources),
        "authority": metrics.authority_top_source(sources),
        "diversity": metrics.diversity(sources),
        "deduplication": metrics.deduplication(sources),
        "freshness": metrics.freshness(
            sources, requirement=task.get("freshness_requirement", "none"),
            as_of=task.get("as_of"),
        ),
        "provenance": metrics.provenance_check(sources, expected_live=live),
        "ranking_gain_vs_provider": metrics.ranking_gain_vs_provider(sources),
        "n_sources": len(sources),
    }


async def run_task(task: dict, *, reachable_providers: set[str]) -> dict:
    """Run one task if its provider is reachable; otherwise record a truthful skip."""
    provider = task.get("requires_provider", "web")
    if provider not in reachable_providers:
        return {"task": task["id"], "category": task.get("category"),
                "status": "skipped", "reason": f"provider_unavailable:{provider}",
                "requires_provider": provider}
    try:
        if provider == "github":
            sources = await collect_github(task["search_query"],
                                           max_results=task.get("max_results", 8))
        else:  # a general-web provider would be dispatched here via resilient_collect
            raise ProviderUnavailable(provider)
    except Exception as exc:  # noqa: BLE001 - a genuine live failure is recorded, not faked
        return {"task": task["id"], "category": task.get("category"),
                "status": "failed", "reason": f"{type(exc).__name__}: {str(exc)[:120]}",
                "requires_provider": provider}
    return {"task": task["id"], "category": task.get("category"), "status": "completed",
            "requires_provider": provider, "sources": sources,
            "metrics": score_sources(task, sources, live=True)}


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()

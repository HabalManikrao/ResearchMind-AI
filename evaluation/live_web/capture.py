"""Run manifest + source capture (#11, Phase 5, Phase 8). Records exactly the metadata needed to
evaluate a live run — and NEVER a secret (no API keys/tokens/cookies/headers). Full copyrighted
pages are not stored; URLs + metadata + short excerpts + hashes only."""
from __future__ import annotations

import hashlib
from urllib.parse import urlparse


def source_record(*, url, title, source_type, reliability, rank, provenance,
                  published_date=None, discovering_query=None, meta=None,
                  became_evidence=False, latency_ms=None) -> dict:
    """One captured source. Excerpt/content is intentionally omitted here; evidence passages are
    stored by the existing evidence layer, not duplicated into the manifest."""
    return {
        "url": url,
        "normalized_url_sha1": hashlib.sha1(_norm(url).encode()).hexdigest()[:16],
        "title": title,
        "domain": _domain(url),
        "source_type": source_type,
        "reliability": round(float(reliability), 1),
        "rank": rank,
        "provenance": provenance,          # live_web | cached_web | local_* — never faked
        "published_date": published_date,
        "discovering_query": discovering_query,
        "became_evidence": became_evidence,
        "latency_ms": latency_ms,
        "meta": _safe_meta(meta or {}),
    }


_SECRET_KEYS = {"token", "api_key", "apikey", "authorization", "cookie", "secret", "password"}


def _safe_meta(meta: dict) -> dict:
    """Defensive: strip anything that could carry a secret, even though callers pass only public
    repo/source metadata (Phase 15)."""
    return {k: v for k, v in meta.items() if k.lower() not in _SECRET_KEYS}


def run_manifest(*, git_commit, dataset_version, provider, provider_config_id, llm_model,
                 embedding_model, source_policy, connectivity_state, metric_version,
                 tasks_total, tasks_run, tasks_skipped, timestamp) -> dict:
    """Reproducibility manifest (Phase 8) — a provider *config identifier* only, never the key."""
    return {
        "timestamp": timestamp,
        "git_commit": git_commit,
        "dataset_version": dataset_version,
        "provider": provider,
        "provider_config_id": provider_config_id,   # e.g. "github:unauthenticated" — no secret
        "llm_model": llm_model,
        "embedding_model": embedding_model,
        "source_policy": source_policy,
        "connectivity_state": connectivity_state,
        "metric_version": metric_version,
        "tasks_total": tasks_total,
        "tasks_run": tasks_run,
        "tasks_skipped": tasks_skipped,
    }


def _norm(url: str) -> str:
    try:
        from app.services.dedup import normalize_url
        return normalize_url(url)
    except Exception:  # noqa: BLE001
        return url or ""


def _domain(url: str) -> str:
    try:
        host = urlparse(url or "").netloc.lower()
        return host[4:] if host.startswith("www.") else host
    except Exception:  # noqa: BLE001
        return ""

"""Bounded web-source cache service (Connectivity Intelligence, #5).

Stores the *last successful* external result set per ``(project_id, source_type,
query)`` and serves it back when a live fetch fails and policy allows (spec §9-§11,
§13). TTL depends on the source type (news short, papers long) and is centralised in
config (§10, §29). Fully project-isolated (§30): reads always filter by ``project_id``.

Only public result content is cached — never API keys, auth headers, cookies, or any
request credentials (§30).
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete as sa_delete, select

from app.agents.common import CollectedSource
from app.config import get_settings
from app.database import SessionLocal
from app.models.cache import CachedSource
from app.services import provenance as prov


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime) -> datetime:
    """SQLite strips tzinfo; treat a naive stored timestamp as UTC for arithmetic."""
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def query_hash(source_type: str, query: str) -> str:
    """Stable key for a (source_type, query) pair — normalised whitespace/case."""
    norm = " ".join((query or "").lower().split())
    return hashlib.sha256(f"{source_type}::{norm}".encode()).hexdigest()


def _checksum(content: str | None) -> str | None:
    if not content:
        return None
    return hashlib.sha256(content.encode("utf-8", "ignore")).hexdigest()


def ttl_seconds(source_type: str) -> int:
    """Cache lifetime for a source type, in seconds (spec §10). Centralised in config
    so there are no scattered literals."""
    s = get_settings()
    minutes = {
        "news": s.cache_ttl_news_minutes,
        "web": s.cache_ttl_web_minutes,
        "community": s.cache_ttl_web_minutes,
        "docs": s.cache_ttl_docs_minutes,
        "github": s.cache_ttl_github_minutes,
        "papers": s.cache_ttl_papers_minutes,
        "documents": s.cache_ttl_documents_minutes,
    }.get(source_type, s.cache_ttl_web_minutes)
    return int(minutes) * 60


async def put(
    project_id: str,
    user_id: str | None,
    source_type: str,
    query: str,
    sources: list[CollectedSource],
) -> int:
    """Cache a successful external result set, replacing any prior entry for the key.
    Best-effort: never raises into the caller. Returns rows written."""
    if not get_settings().source_cache_enabled or not sources:
        return 0
    qh = query_hash(source_type, query)
    now = _now()
    try:
        async with SessionLocal() as db:
            await db.execute(
                sa_delete(CachedSource).where(
                    CachedSource.project_id == project_id,
                    CachedSource.source_type == source_type,
                    CachedSource.query_hash == qh,
                )
            )
            for es in sources:
                meta = dict(es.meta or {})
                meta["findings"] = list(es.findings or [])
                db.add(
                    CachedSource(
                        project_id=project_id,
                        user_id=user_id,
                        query_hash=qh,
                        source_type=source_type,
                        title=es.title,
                        url=es.url,
                        content=(es.content or "")[:20000] or None,
                        summary=es.summary,
                        published_date=es.published_date,
                        reliability_score=es.reliability_score,
                        relevance_score=es.relevance_score,
                        checksum=_checksum(es.content),
                        meta=meta,
                        retrieved_at=now,
                    )
                )
            await db.commit()
        return len(sources)
    except Exception:  # noqa: BLE001 - caching must never break a run
        return 0


async def get(
    project_id: str, source_type: str, query: str
) -> list[CollectedSource]:
    """Return the cached result set for this key if still within TTL, else ``[]``.

    HARD-filtered by ``project_id`` (spec §30): a cached source in another project is
    never returned. Reconstructed sources are stamped ``cached_web`` provenance with
    the original retrieval time so they can never be mistaken for live (spec §8, §34).
    """
    if not get_settings().source_cache_enabled:
        return []
    qh = query_hash(source_type, query)
    cutoff = _now() - timedelta(seconds=ttl_seconds(source_type))
    try:
        async with SessionLocal() as db:
            rows = (
                await db.execute(
                    select(CachedSource).where(
                        CachedSource.project_id == project_id,
                        CachedSource.source_type == source_type,
                        CachedSource.query_hash == qh,
                        CachedSource.retrieved_at >= cutoff,
                    )
                )
            ).scalars().all()
    except Exception:  # noqa: BLE001
        return []
    if not rows:
        return []

    out: list[CollectedSource] = []
    for r in rows:
        meta = dict(r.meta or {})
        findings = meta.pop("findings", []) or []
        retrieved = _aware(r.retrieved_at)
        age = int((_now() - retrieved).total_seconds())
        meta["provenance"] = prov.CACHED_WEB
        meta["cached_at"] = retrieved.isoformat()
        meta["cache_age_seconds"] = age
        out.append(
            CollectedSource(
                title=r.title,
                url=r.url,
                content=r.content or "",
                summary=r.summary or "",
                reliability_score=r.reliability_score,
                relevance_score=r.relevance_score,
                source_type=r.source_type,
                published_date=r.published_date,
                findings=list(findings),
                meta=meta,
            )
        )
    return out

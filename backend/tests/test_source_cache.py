"""Web-source cache: hit / miss / expired / isolation / checksum (#5, spec §9-§11, §30)."""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.models.cache import CachedSource
from app.services import source_cache
from tests.conftest import make_collected


async def test_put_then_get_roundtrips(reset_db):
    srcs = [make_collected("web", "https://a.example", findings=["f1", "f2"])]
    n = await source_cache.put("proj1", "user1", "web", "kubernetes runtimes", srcs)
    assert n == 1

    hits = await source_cache.get("proj1", "web", "kubernetes runtimes")
    assert len(hits) == 1
    assert hits[0].url == "https://a.example"
    assert hits[0].findings == ["f1", "f2"]  # findings survive the round-trip
    assert hits[0].meta["provenance"] == "cached_web"
    assert "cached_at" in hits[0].meta and "cache_age_seconds" in hits[0].meta


async def test_get_miss_returns_empty(reset_db):
    assert await source_cache.get("proj1", "web", "never searched") == []


async def test_query_normalization_matches(reset_db):
    await source_cache.put("p", "u", "web", "Docker  VS   Podman", [make_collected("web", "https://x")])
    # Different case/whitespace, same query -> hit.
    assert await source_cache.get("p", "web", "docker vs podman")


async def test_expired_entry_is_not_returned(reset_db):
    await source_cache.put("p", "u", "news", "breaking", [make_collected("news", "https://n")])
    # Force the row's retrieved_at past the news TTL.
    from app.database import SessionLocal

    ttl = source_cache.ttl_seconds("news")
    async with SessionLocal() as db:
        row = (await db.execute(select(CachedSource))).scalars().first()
        row.retrieved_at = datetime.now(timezone.utc) - timedelta(seconds=ttl + 60)
        await db.commit()
    assert await source_cache.get("p", "news", "breaking") == []


async def test_put_replaces_prior_entry_for_key(reset_db):
    await source_cache.put("p", "u", "web", "q", [make_collected("web", "https://old")])
    await source_cache.put("p", "u", "web", "q", [make_collected("web", "https://new")])
    hits = await source_cache.get("p", "web", "q")
    assert len(hits) == 1 and hits[0].url == "https://new"


async def test_checksum_recorded(reset_db):
    await source_cache.put("p", "u", "web", "q", [make_collected("web", "https://a")])
    from app.database import SessionLocal

    async with SessionLocal() as db:
        row = (await db.execute(select(CachedSource))).scalars().first()
    assert row.checksum and len(row.checksum) == 64  # sha256 hex


async def test_cross_project_isolation(reset_db):
    """A cached source in project A must never surface in project B (spec §30)."""
    await source_cache.put("projA", "u", "web", "shared query", [make_collected("web", "https://a")])
    assert await source_cache.get("projB", "web", "shared query") == []
    assert len(await source_cache.get("projA", "web", "shared query")) == 1


async def test_disabled_cache_is_noop(reset_db, monkeypatch):
    from app.config import get_settings

    s = get_settings()
    monkeypatch.setattr(s, "source_cache_enabled", False)
    assert await source_cache.put("p", "u", "web", "q", [make_collected("web", "https://a")]) == 0
    assert await source_cache.get("p", "web", "q") == []

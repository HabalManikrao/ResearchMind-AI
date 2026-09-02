"""Provenance model + resilient collection (#5)."""
import pytest

from app.models.enums import SourcePolicy
from app.services import provenance as prov
from app.services import collection
from app.services.collection import CollectionResult, resilient_collect
from tests.conftest import make_collected

from app.config import get_settings

settings = get_settings()


# --------------------------------------------------------------------------- #
# provenance / availability derivation (spec §3, §7)
# --------------------------------------------------------------------------- #
def test_availability_live_vs_cached_vs_local():
    assert prov.availability_of(prov.LIVE_WEB, "fresh") == prov.LIVE
    assert prov.availability_of(prov.CACHED_WEB, "fresh") == prov.CACHED
    assert prov.availability_of(prov.LOCAL_DOCUMENT, "fresh") == prov.LOCAL
    assert prov.availability_of(prov.LOCAL_MEMORY, "aging") == prov.LOCAL


def test_stale_freshness_overrides_provenance():
    # Evidence exists but exceeds its freshness threshold -> STALE regardless of source.
    assert prov.availability_of(prov.LIVE_WEB, "stale") == prov.STALE
    assert prov.availability_of(prov.LOCAL_DOCUMENT, "stale") == prov.STALE


def test_unknown_provenance_is_unknown():
    assert prov.availability_of("bogus", "unknown") == prov.UNKNOWN


def test_provenance_of_reads_meta_then_defaults():
    assert prov.provenance_of("web", {"provenance": prov.CACHED_WEB}) == prov.CACHED_WEB
    # No stamp: external defaults to live_web, documents default to local_document.
    assert prov.provenance_of("web", {}) == prov.LIVE_WEB
    assert prov.provenance_of("documents", None) == prov.LOCAL_DOCUMENT


def test_is_external():
    assert prov.is_external("web") and prov.is_external("github")
    assert not prov.is_external("documents")


def test_research_health_labels():
    assert prov.research_health(live=5, cached=0, local=0, unavailable=0) == prov.FULLY_LIVE
    assert prov.research_health(live=0, cached=0, local=3, unavailable=0) == prov.LOCAL_ONLY
    assert prov.research_health(live=0, cached=2, local=0, unavailable=1) == prov.CACHE_ASSISTED
    assert prov.research_health(live=0, cached=0, local=0, unavailable=4) == prov.EXTERNAL_UNAVAILABLE
    assert prov.research_health(live=3, cached=1, local=0, unavailable=0) == prov.PARTIALLY_DEGRADED


# --------------------------------------------------------------------------- #
# resilient_collect: live / cached / local / skipped (spec §8, §11, §13)
# --------------------------------------------------------------------------- #
async def _fake_dispatch_ok(monkeypatch, source_type="web"):
    async def fake_collect(agent, provider, tavily, settings, *, question,
                           search_query, recency_days=None, project_id=""):
        return [make_collected(agent, f"https://{agent}.example/x")]
    monkeypatch.setattr(collection.dispatch, "collect", fake_collect)


async def test_live_success_stamps_live_and_caches(reset_db, monkeypatch):
    await _fake_dispatch_ok(monkeypatch)
    put_calls = {}

    async def fake_put(project_id, user_id, source_type, query, sources):
        put_calls["n"] = len(sources)
        return len(sources)
    monkeypatch.setattr(collection.source_cache, "put", fake_put)

    res = await resilient_collect(
        "web", None, None, settings, question="q", search_query="q",
        project_id="p1", user_id="u1", policy=SourcePolicy.LIVE_PREFERRED.value,
    )
    assert res.outcome == collection.LIVE
    assert res.sources[0].meta["provenance"] == prov.LIVE_WEB
    assert "retrieved_at" in res.sources[0].meta
    assert put_calls["n"] == 1  # cached for later reuse


async def test_live_failure_falls_back_to_cache(reset_db, monkeypatch):
    async def boom(*a, **k):
        raise RuntimeError("provider down")
    monkeypatch.setattr(collection.dispatch, "collect", boom)

    cached = [make_collected("web", "https://web.example/cached",
                             meta={"provenance": prov.CACHED_WEB})]

    async def fake_get(project_id, source_type, query):
        return cached
    monkeypatch.setattr(collection.source_cache, "get", fake_get)

    res = await resilient_collect(
        "web", None, None, settings, question="q", search_query="q",
        project_id="p1", policy=SourcePolicy.LIVE_PREFERRED.value,
    )
    assert res.outcome == collection.CACHED
    assert res.sources[0].meta["provenance"] == prov.CACHED_WEB


async def test_live_only_never_serves_cache(reset_db, monkeypatch):
    async def boom(*a, **k):
        raise RuntimeError("provider down")
    monkeypatch.setattr(collection.dispatch, "collect", boom)
    # Even if a cache exists, LIVE_ONLY must fail honestly.
    called = {"get": False}

    async def fake_get(*a, **k):
        called["get"] = True
        return [make_collected("web", "https://web.example/cached")]
    monkeypatch.setattr(collection.source_cache, "get", fake_get)

    with pytest.raises(RuntimeError):
        await resilient_collect(
            "web", None, None, settings, question="q", search_query="q",
            project_id="p1", policy=SourcePolicy.LIVE_ONLY.value,
        )
    assert called["get"] is False  # cache was never consulted


async def test_local_only_skips_external(reset_db, monkeypatch):
    called = {"collect": False}

    async def fake_collect(*a, **k):
        called["collect"] = True
        return []
    monkeypatch.setattr(collection.dispatch, "collect", fake_collect)

    res = await resilient_collect(
        "web", None, None, settings, question="q", search_query="q",
        project_id="p1", policy=SourcePolicy.LOCAL_ONLY.value,
    )
    assert res.outcome == collection.SKIPPED
    assert res.sources == []
    assert called["collect"] is False  # no network call at all


async def test_documents_agent_is_local_never_cached(reset_db, monkeypatch):
    async def fake_collect(agent, *a, **k):
        return [make_collected("documents", "document://d1", meta={})]
    monkeypatch.setattr(collection.dispatch, "collect", fake_collect)
    put_called = {"v": False}

    async def fake_put(*a, **k):
        put_called["v"] = True
        return 0
    monkeypatch.setattr(collection.source_cache, "put", fake_put)

    res = await resilient_collect(
        "documents", None, None, settings, question="q", search_query="q",
        project_id="p1", policy=SourcePolicy.LIVE_PREFERRED.value,
    )
    assert res.outcome == collection.LOCAL
    assert res.sources[0].meta["provenance"] == prov.LOCAL_DOCUMENT
    assert put_called["v"] is False  # local evidence is never cached

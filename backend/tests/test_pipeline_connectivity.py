"""End-to-end connectivity behaviour through the real pipeline (#5, spec §13-§15, §44).

Covers: live research, offline/local-only, hybrid, partial outage, cache fallback,
and connectivity recovery — all with faked collection + connectivity (no network).
"""
import pytest

import app.orchestration.orchestrator as orch
from app.services import collection
from app.services.connectivity import (
    DEGRADED,
    LOCAL_ONLY,
    ONLINE,
    ConnectivitySnapshot,
)
from tests.conftest import make_collected, run_to_completion


def _snap(overall=ONLINE, *, internet=True, provider=True, ollama=True):
    async def fake_snapshot(force=False):
        return ConnectivitySnapshot(
            overall=overall, internet=internet, search_provider=provider,
            ollama=ollama, qdrant=True, database=True,
        )
    return fake_snapshot


async def _create_run(client, *, sources, policy=None):
    body = {"query": "compare tools", "sources_enabled": sources, "auto_start": True}
    if policy:
        body["source_policy"] = policy
    r = await client.post("/research", json=body)
    pid = r.json()["id"]
    await run_to_completion(pid)
    assert (await client.get(f"/research/{pid}")).json()["status"] == "completed"
    return pid


# --------------------------------------------------------------------------- #
# Live research — everything succeeds online (spec §44: Internet available -> LIVE).
# --------------------------------------------------------------------------- #
async def test_live_research_marks_sources_live(client, patch_pipeline, monkeypatch):
    monkeypatch.setattr(orch.connectivity.manager, "snapshot", _snap(ONLINE))
    pid = await _create_run(client, sources=["web"])

    sources = (await client.get(f"/research/{pid}/sources")).json()
    assert sources and all(s["provenance"] == "live_web" for s in sources)
    assert all(s["availability"] in ("live", "stale") for s in sources)

    meta = (await client.get(f"/research/{pid}")).json()["report_meta"]
    health = meta["source_health"]
    assert health["live"] >= 1
    assert health["research_mode"] == "live"
    assert health["research_health"] in ("fully_live", "partially_degraded")


# --------------------------------------------------------------------------- #
# Offline / local-only — no external fetches; documents only (spec §15, §44).
# --------------------------------------------------------------------------- #
async def test_local_only_offline_research(client, patch_pipeline, monkeypatch):
    monkeypatch.setattr(orch.connectivity.manager, "snapshot", _snap(LOCAL_ONLY, internet=False, provider=False))
    pid = await _create_run(client, sources=["documents", "web"], policy="local_only")

    sources = (await client.get(f"/research/{pid}/sources")).json()
    # No external (web) sources — those tasks were skipped; only local documents.
    assert sources and all(s["source_type"] == "documents" for s in sources)
    assert all(s["provenance"] == "local_document" for s in sources)

    health = (await client.get(f"/research/{pid}")).json()["report_meta"]["source_health"]
    assert health["research_mode"] == "local"
    assert health["research_health"] == "local_only"
    # The report honestly discloses local-only sourcing (spec §15).
    report = (await client.get(f"/research/{pid}/report")).json()["markdown"]
    assert "Research Health" in report
    assert "local" in report.lower()


# --------------------------------------------------------------------------- #
# Hybrid — local documents + live web together (spec §44).
# --------------------------------------------------------------------------- #
async def test_hybrid_local_plus_live(client, patch_pipeline, monkeypatch):
    monkeypatch.setattr(orch.connectivity.manager, "snapshot", _snap(ONLINE))
    pid = await _create_run(client, sources=["web", "documents"])

    sources = (await client.get(f"/research/{pid}/sources")).json()
    provs = {s["provenance"] for s in sources}
    assert "live_web" in provs and "local_document" in provs

    health = (await client.get(f"/research/{pid}")).json()["report_meta"]["source_health"]
    assert health["live"] >= 1 and health["local"] >= 1
    assert health["research_mode"] == "hybrid"


# --------------------------------------------------------------------------- #
# Partial outage — one provider fails, healthy ones continue (spec §14, §35).
# --------------------------------------------------------------------------- #
async def test_partial_outage_continues_and_reports_unavailable(
    client, patch_pipeline, monkeypatch
):
    monkeypatch.setattr(orch.connectivity.manager, "snapshot", _snap(DEGRADED))

    async def selective_collect(agent, provider, tavily, settings, *, question,
                                search_query, recency_days=None, project_id=""):
        if agent == "web":
            raise RuntimeError("web provider outage")
        return [make_collected(agent, f"https://{agent}.example/x")]

    monkeypatch.setattr(orch.dispatch, "collect", selective_collect)
    # LIVE_ONLY so the failed web task can't be masked by cache -> counts UNAVAILABLE.
    pid = await _create_run(client, sources=["web", "github"], policy="live_only")

    sources = (await client.get(f"/research/{pid}/sources")).json()
    assert sources and all(s["source_type"] == "github" for s in sources)  # healthy source kept

    health = (await client.get(f"/research/{pid}")).json()["report_meta"]["source_health"]
    assert health["unavailable"] >= 1  # web could not be reached
    assert health["provider_failures"] >= 1
    # Run still completed with partial coverage — the outage didn't kill it (spec §14).


# --------------------------------------------------------------------------- #
# Cache fallback — live fails but a cached result is served (spec §13, §44).
# --------------------------------------------------------------------------- #
async def test_cache_fallback_serves_cached(client, patch_pipeline, monkeypatch):
    monkeypatch.setattr(orch.connectivity.manager, "snapshot", _snap(DEGRADED))

    async def failing_collect(agent, *a, **k):
        raise RuntimeError("live down")
    monkeypatch.setattr(orch.dispatch, "collect", failing_collect)

    async def fake_get(project_id, source_type, query):
        return [make_collected(source_type, f"https://{source_type}.example/cached",
                               meta={"provenance": "cached_web"})]
    monkeypatch.setattr(collection.source_cache, "get", fake_get)

    pid = await _create_run(client, sources=["web"], policy="live_preferred")

    sources = (await client.get(f"/research/{pid}/sources")).json()
    assert sources and all(s["provenance"] == "cached_web" for s in sources)
    assert all(s["availability"] in ("cached", "stale") for s in sources)

    health = (await client.get(f"/research/{pid}")).json()["report_meta"]["source_health"]
    assert health["cached"] >= 1
    assert health["fallback_count"] >= 1
    assert health["research_mode"] == "cache"


# --------------------------------------------------------------------------- #
# Recovery — a transient failure is retried once connectivity is healthy (§26).
# --------------------------------------------------------------------------- #
async def test_recovery_retries_failed_task(client, patch_pipeline, monkeypatch):
    monkeypatch.setattr(orch.connectivity.manager, "snapshot", _snap(ONLINE))
    calls = {"n": 0}

    async def flaky_collect(agent, provider, tavily, settings, *, question,
                            search_query, recency_days=None, project_id=""):
        calls["n"] += 1
        if calls["n"] == 1:  # first task fails, everything after recovers
            raise RuntimeError("transient blip")
        return [make_collected(agent, f"https://{agent}.example/x")]

    monkeypatch.setattr(orch.dispatch, "collect", flaky_collect)
    pid = await _create_run(client, sources=["web"], policy="live_preferred")

    health = (await client.get(f"/research/{pid}")).json()["report_meta"]["source_health"]
    assert health["retry_count"] >= 1  # the failed task was retried after recovery
    # After recovery the previously failed task produced a live source.
    sources = (await client.get(f"/research/{pid}/sources")).json()
    assert any(s["provenance"] == "live_web" for s in sources)

"""Connectivity manager: states, recovery, caching (#5, spec §4-§6, §25)."""
import pytest

from app.services import connectivity
from app.services.connectivity import ConnectivityManager


def _patch_probes(monkeypatch, *, internet, provider, ollama=True, qdrant=True, database=True):
    async def p_internet(timeout):
        return internet

    async def p_provider(timeout):
        return provider

    async def p_ollama(timeout):
        return ollama

    async def p_qdrant(timeout):
        return qdrant

    async def p_database(timeout):
        return database

    monkeypatch.setattr(connectivity, "probe_internet", p_internet)
    monkeypatch.setattr(connectivity, "probe_search_provider", p_provider)
    monkeypatch.setattr(connectivity, "probe_ollama", p_ollama)
    monkeypatch.setattr(connectivity, "probe_qdrant", p_qdrant)
    monkeypatch.setattr(connectivity, "probe_database", p_database)


async def test_online_state(monkeypatch):
    _patch_probes(monkeypatch, internet=True, provider=True)
    snap = await ConnectivityManager().snapshot()
    assert snap.overall == connectivity.ONLINE
    assert snap.internet and snap.search_provider


async def test_degraded_when_provider_down(monkeypatch):
    """Internet up, search provider down -> DEGRADED, not OFFLINE (spec §5, §35)."""
    _patch_probes(monkeypatch, internet=True, provider=False)
    snap = await ConnectivityManager().snapshot()
    assert snap.overall == connectivity.DEGRADED


async def test_local_only_when_no_internet_but_ollama_up(monkeypatch):
    _patch_probes(monkeypatch, internet=False, provider=False, ollama=True)
    snap = await ConnectivityManager().snapshot()
    assert snap.overall == connectivity.LOCAL_ONLY


async def test_offline_when_no_internet_and_no_ollama(monkeypatch):
    _patch_probes(monkeypatch, internet=False, provider=False, ollama=False)
    snap = await ConnectivityManager().snapshot()
    assert snap.overall == connectivity.OFFLINE


async def test_recovery_transition(monkeypatch):
    """Offline -> healthy yields a one-shot RECOVERING state (spec §6, §26)."""
    mgr = ConnectivityManager()
    _patch_probes(monkeypatch, internet=False, provider=False, ollama=True)
    first = await mgr.snapshot(force=True)
    assert first.overall == connectivity.LOCAL_ONLY

    _patch_probes(monkeypatch, internet=True, provider=True)
    second = await mgr.snapshot(force=True)
    assert second.overall == connectivity.RECOVERING
    assert second.recovering is True

    third = await mgr.snapshot(force=True)
    assert third.overall == connectivity.ONLINE  # settles after recovery


async def test_snapshot_is_cached(monkeypatch):
    calls = {"n": 0}

    async def counting_internet(timeout):
        calls["n"] += 1
        return True

    monkeypatch.setattr(connectivity, "probe_internet", counting_internet)
    _patch_probes(monkeypatch, internet=True, provider=True)  # overrides others
    monkeypatch.setattr(connectivity, "probe_internet", counting_internet)

    mgr = ConnectivityManager()
    await mgr.snapshot()
    await mgr.snapshot()  # within TTL -> no re-probe
    assert calls["n"] == 1


async def test_timeout_probe_counts_as_unreachable(monkeypatch):
    """A probe that raises/timeouts is treated as unreachable, not an error (spec §25)."""
    import httpx

    async def failing_head(url, timeout):
        raise httpx.ConnectError("dns/connect failed")

    monkeypatch.setattr(connectivity, "_head_reachable", failing_head)
    # probe_internet uses _head_reachable; with all hosts failing -> not reachable.
    reachable = await connectivity.probe_internet(1.0)
    assert reachable is False


def test_research_mode_for(monkeypatch):
    from app.models.enums import SourcePolicy
    from app.services.connectivity import ConnectivitySnapshot

    online = ConnectivitySnapshot(overall=connectivity.ONLINE, internet=True,
                                  search_provider=True, ollama=True, qdrant=True, database=True)
    offline = ConnectivitySnapshot(overall=connectivity.LOCAL_ONLY, internet=False,
                                   search_provider=False, ollama=True, qdrant=True, database=True)
    assert connectivity.research_mode_for(online, SourcePolicy.LIVE_PREFERRED.value) == "live"
    assert connectivity.research_mode_for(offline, SourcePolicy.LIVE_PREFERRED.value) == "local"
    assert connectivity.research_mode_for(online, SourcePolicy.LOCAL_ONLY.value) == "local"


# --------------------------------------------------------------------------- #
# API endpoint (spec §37)
# --------------------------------------------------------------------------- #
async def test_connectivity_endpoint(client, monkeypatch):
    from app.services.connectivity import ConnectivitySnapshot, manager

    async def fake_snapshot(force=False):
        return ConnectivitySnapshot(
            overall="online", internet=True, search_provider=True,
            ollama=True, qdrant=True, database=True,
        )
    monkeypatch.setattr(manager, "snapshot", fake_snapshot)

    r = await client.get("/system/connectivity")
    assert r.status_code == 200
    body = r.json()
    assert body["enabled"] is True
    assert body["overall_status"] == "online"
    assert body["local_services"]["ollama"] is True
    assert body["research_mode"] == "live"
    # No secrets leaked in the payload (spec §37).
    assert "tavily_api_key" not in body and "jwt_secret" not in str(body)

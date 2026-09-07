"""Capability layer (#8, spec §42): the single implementation, tested independently of any
transport. Valid/invalid input, authorization, missing resource, bounded results, errors."""
import pytest

import app.services.connectivity as conn
from app.capabilities import documents as cap_docs
from app.capabilities import knowledge as cap_kg
from app.capabilities import research as cap_research
from app.capabilities import system as cap_system
from app.capabilities.base import CapabilityError, codes, list_capabilities, resolve_user
from app.database import SessionLocal
from app.models import User
from app.services.connectivity import ONLINE, ConnectivitySnapshot
from tests.conftest import run_to_completion


@pytest.fixture(autouse=True)
def _fake_connectivity(monkeypatch):
    async def fake_snapshot(force=False):
        return ConnectivitySnapshot(overall=ONLINE, internet=True, search_provider=True,
                                    ollama=True, qdrant=True, database=True)
    monkeypatch.setattr(conn.manager, "snapshot", fake_snapshot)


async def _user(client) -> User:
    async with SessionLocal() as db:
        return await db.get(User, client.default_user["id"])


async def _completed(client, query="best vector database") -> str:
    r = await client.post("/research", json={"query": query, "sources_enabled": ["web"],
                                             "auto_start": True})
    pid = r.json()["id"]
    await run_to_completion(pid, timeout=60)
    assert (await client.get(f"/research/{pid}")).json()["status"] == "completed"
    return pid


# --------------------------------------------------------------------------- #
# System + discovery
# --------------------------------------------------------------------------- #
async def test_capability_registry_is_safe():
    caps = list_capabilities()
    assert len(caps) >= 15
    names = {c["name"] for c in caps}
    assert {"research_start", "research_evidence", "knowledge_graph", "system_connectivity"} <= names
    # No implementation detail / secret fields leak.
    for c in caps:
        assert set(c) == {"name", "group", "description", "requires_network",
                          "may_invoke_llm", "long_running", "mutating"}


async def test_system_version_has_no_secrets():
    v = await cap_system.version()
    assert v["interfaces"]["rest"] == "/v1"
    assert "jwt" not in str(v).lower() and "key" not in str(v).lower()


# --------------------------------------------------------------------------- #
# Auth resolution
# --------------------------------------------------------------------------- #
async def test_resolve_user_rejects_bad_token(client):
    with pytest.raises(CapabilityError) as ei:
        await resolve_user("not-a-jwt")
    assert ei.value.code == codes.ACCESS_DENIED
    with pytest.raises(CapabilityError):
        await resolve_user(None)  # auth enabled in the suite


# --------------------------------------------------------------------------- #
# Research capabilities
# --------------------------------------------------------------------------- #
async def test_start_validates_input(client):
    user = await _user(client)
    with pytest.raises(CapabilityError) as ei:
        await cap_research.start(user, query="hi")  # too short
    assert ei.value.code == codes.INVALID_ARGUMENT
    with pytest.raises(CapabilityError):
        await cap_research.start(user, query="a good long query", mode="bogus")


async def test_start_is_idempotent(client, patch_pipeline):
    user = await _user(client)
    r1 = await cap_research.start(user, query="idempotent research topic",
                                  idempotency_key="key-1")
    r2 = await cap_research.start(user, query="idempotent research topic",
                                  idempotency_key="key-1")
    assert r1["research_id"] == r2["research_id"]  # same key never duplicates work
    await run_to_completion(r1["research_id"], timeout=60)


async def test_start_respects_concurrency_limit(client, monkeypatch):
    user = await _user(client)
    # Simulate this user already at the per-user concurrency ceiling (spec §24, §37).
    async def _at_limit(_user):
        return 3
    monkeypatch.setattr(cap_research, "_user_active_count", _at_limit)
    monkeypatch.setattr(cap_research, "get_settings",
                        lambda: type("S", (), {"concurrent_research_limit": 3})())
    with pytest.raises(CapabilityError) as ei:
        await cap_research.start(user, query="another research topic")
    assert ei.value.code == codes.RATE_LIMITED


async def test_status_report_claims_evidence(client, patch_pipeline):
    user = await _user(client)
    pid = await _completed(client)

    st = await cap_research.status(user, pid)
    assert st["research_id"] == pid and st["status"] == "completed"

    rep = await cap_research.report(user, pid, excerpt=True)
    assert "markdown" in rep and "meta" in rep

    cl = await cap_research.claims(user, pid)
    assert cl["research_id"] == pid and isinstance(cl["claims"], list)
    assert cl["limit"] <= 100  # bounded

    if cl["claims"]:
        cid = cl["claims"][0]["claim_id"]
        ev = await cap_research.evidence(user, pid, cid)
        assert ev["claim_id"] == cid
        # Provenance is preserved on each evidence item (spec §10).
        for e in ev["evidence"]:
            assert "provenance" in e and "availability" in e


async def test_status_missing_project(client):
    user = await _user(client)
    with pytest.raises(CapabilityError) as ei:
        await cap_research.status(user, "does-not-exist")
    assert ei.value.code == codes.RESEARCH_NOT_FOUND
    assert ei.value.http_status == 404


async def test_again_requires_completed(client, patch_pipeline):
    user = await _user(client)
    r = await client.post("/research", json={"query": "unfinished research topic"})
    pid = r.json()["id"]  # created, not started
    with pytest.raises(CapabilityError) as ei:
        await cap_research.again(user, pid, intent="refresh")
    assert ei.value.code == codes.RESEARCH_IN_PROGRESS


# --------------------------------------------------------------------------- #
# Documents / knowledge bounded reads
# --------------------------------------------------------------------------- #
async def test_document_search_requires_query(client, patch_pipeline):
    user = await _user(client)
    pid = await _completed(client)
    with pytest.raises(CapabilityError):
        await cap_docs.search(user, pid, "")
    res = await cap_docs.search(user, pid, "anything")
    assert res["project_id"] == pid and isinstance(res["passages"], list)


async def test_knowledge_search_is_bounded(client, patch_pipeline):
    user = await _user(client)
    await _completed(client)  # produces at least one entity via the graph build
    res = await cap_kg.entity_search(user, q=None, limit=500)
    assert res["limit"] <= 100  # clamped to capability_max_page_size
    assert isinstance(res["entities"], list)

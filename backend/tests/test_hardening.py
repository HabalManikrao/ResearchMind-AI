"""Production hardening (#9, spec §26-§38): pagination bounds (regression for the negative-
limit fix), test isolation, failure injection, DB integrity, and the end-to-end lifecycle +
external-client flows. Reuses existing fixtures; fully offline."""
import json

import pytest
from sqlalchemy import func, select

import app.orchestration.orchestrator as orch
import app.services.connectivity as conn
from app.capabilities.base import clamp_page
from app.database import SessionLocal
from app.documents import service as doc_service
from app.models import ClaimSource, KgEntity, KgMention, KgRelationship, ResearchProject
from app.services.connectivity import ONLINE, ConnectivitySnapshot
from tests.conftest import register_user, run_to_completion


@pytest.fixture(autouse=True)
def _fake_connectivity(monkeypatch):
    async def fake_snapshot(force=False):
        return ConnectivitySnapshot(overall=ONLINE, internet=True, search_provider=True,
                                    ollama=True, qdrant=True, database=True)
    monkeypatch.setattr(conn.manager, "snapshot", fake_snapshot)


async def _complete(client, query="best vector db"):
    r = await client.post("/research", json={"query": query, "sources_enabled": ["web"],
                                             "auto_start": True})
    pid = r.json()["id"]
    await run_to_completion(pid, timeout=60)
    assert (await client.get(f"/research/{pid}")).json()["status"] == "completed"
    return pid


# --------------------------------------------------------------------------- #
# Test isolation — the suite must be genuinely offline (spec §36, §37)
# --------------------------------------------------------------------------- #
def test_suite_runs_offline():
    from app.config import get_settings

    # conftest pins Ollama at an unreachable address; if this regresses, tests could
    # silently start depending on a live local Ollama.
    assert get_settings().ollama_base_url == "http://127.0.0.1:1"


# --------------------------------------------------------------------------- #
# Pagination bounds — regression for the negative-limit (unbounded SQLite) P1 fix
# --------------------------------------------------------------------------- #
def test_clamp_page_floors_and_caps():
    assert clamp_page(-1, 0) == (1, 0)      # negative → floored (was unbounded LIMIT -1)
    assert clamp_page(-999, -5) == (1, 0)
    assert clamp_page(0, 0)[0] >= 1
    assert clamp_page(10**9, 0)[0] <= 100   # capped
    assert clamp_page(5, 3) == (5, 3)


async def test_v1_negative_limit_is_bounded(client, patch_pipeline):
    # Seed more rows than one page so an unbounded query would be observable.
    for i in range(4):
        await _complete(client, query=f"pagination hardening topic {i}")
    r = await client.get("/v1/research?limit=-1")
    assert r.status_code == 200
    # Must return a bounded page (floored to 1), never the whole table.
    assert len(r.json()["results"]) == 1


async def test_v1_knowledge_negative_limit_is_bounded(client, patch_pipeline):
    await _complete(client)
    r = await client.get("/v1/knowledge/entities?limit=-1")
    assert r.status_code == 200
    assert len(r.json()["entities"]) <= 1


# --------------------------------------------------------------------------- #
# Failure injection — one subsystem failing must not corrupt the run (spec §31)
# --------------------------------------------------------------------------- #
async def test_embedding_failure_in_document_search_is_graceful(client, patch_pipeline, monkeypatch):
    from app.llm.base import LLMError

    pid = await _complete(client)

    async def boom(texts):
        raise LLMError("embedding backend down")  # how the Ollama provider signals an outage
    monkeypatch.setattr(doc_service.get_provider(), "embed", boom)
    # Document retrieval degrades to no passages on an embedding outage (never 500).
    r = await client.post("/v1/documents/search", json={"project_id": pid, "query": "x"})
    assert r.status_code == 200
    assert r.json()["passages"] == []


async def test_graph_failure_does_not_break_research(client, patch_pipeline, monkeypatch):
    async def boom(project_id):
        raise RuntimeError("graph exploded")
    monkeypatch.setattr(orch.kg_graph, "build_graph_for_project", boom)
    pid = await _complete(client)  # research still completes
    report = (await client.get(f"/research/{pid}/report")).json()
    assert report["meta"]["graph_status"]["state"] == "degraded"


# --------------------------------------------------------------------------- #
# DB integrity — no orphans / duplicates produced by a normal run (spec §29, §33)
# --------------------------------------------------------------------------- #
async def test_no_orphan_or_duplicate_graph_records(client, patch_pipeline):
    await _complete(client)
    async with SessionLocal() as db:
        ent_ids = {e.id for e in (await db.execute(select(KgEntity))).scalars().all()}
        # Every relationship references entities that exist.
        rels = (await db.execute(select(KgRelationship))).scalars().all()
        for r in rels:
            assert r.subject_entity_id in ent_ids and r.object_entity_id in ent_ids
        # Every mention references an existing entity.
        for mnt in (await db.execute(select(KgMention))).scalars().all():
            assert mnt.entity_id in ent_ids
        # No duplicate ClaimSource (claim_id, source_id) edges.
        dup = (
            await db.execute(
                select(ClaimSource.claim_id, ClaimSource.source_id, func.count())
                .group_by(ClaimSource.claim_id, ClaimSource.source_id)
                .having(func.count() > 1)
            )
        ).all()
        assert dup == []


# --------------------------------------------------------------------------- #
# CPU / Ollama budget — monitoring Stage-1 must make NO LLM calls (spec §19)
# --------------------------------------------------------------------------- #
async def test_monitoring_stage1_makes_no_llm_calls(client, patch_pipeline, monkeypatch):
    import app.services.research_monitor as rm

    pid = await _complete(client)
    await client.post(f"/research/{pid}/monitor", json={"frequency": "daily"})

    # Count LLM structured_output / generate calls during a no-change (Stage-1-only) check.
    provider = patch_pipeline
    calls = {"structured": 0, "generate": 0}
    orig_s, orig_g = provider.structured_output, provider.generate

    async def counting_structured(*a, **k):
        calls["structured"] += 1
        return await orig_s(*a, **k)

    async def counting_generate(*a, **k):
        calls["generate"] += 1
        return await orig_g(*a, **k)

    monkeypatch.setattr(provider, "structured_output", counting_structured)
    monkeypatch.setattr(provider, "generate", counting_generate)

    async with SessionLocal() as db:
        from app.models import ResearchMonitor
        mon = (await db.execute(
            select(ResearchMonitor).where(ResearchMonitor.root_id == pid))).scalars().first()
    result = await rm.run_monitor_check(mon.id)
    assert result["status"] == "no_change"       # cheap probe found nothing new
    assert calls["structured"] == 0              # Stage 1 never invokes the LLM (spec §19)
    assert calls["generate"] == 0


# --------------------------------------------------------------------------- #
# End-to-end lifecycle — the most important acceptance test (spec §43)
# --------------------------------------------------------------------------- #
async def test_full_lifecycle_coherent(client, patch_pipeline):
    """research → claims/evidence → report → memory → graph → monitor → research-again →
    diff → graph supersession, all coherent for the same lineage."""
    pid = await _complete(client)

    # Claims + evidence exist and are traceable.
    claims = (await client.get(f"/research/{pid}/claims")).json()
    assert claims
    ev = (await client.get(f"/research/{pid}/claims/{claims[0]['id']}/evidence")).json()
    assert ev["evidence"]

    # Memory record written at completion.
    mem = (await client.get(f"/research/{pid}/memory")).json()
    assert mem["memory"] is not None

    # Graph entities exist for this user.
    async with SessionLocal() as db:
        ents = (await db.execute(
            select(KgEntity).where(KgEntity.user_id == client.default_user["id"]))
        ).scalars().all()
    assert ents

    # Monitor the lineage.
    mon = await client.post(f"/research/{pid}/monitor", json={"frequency": "daily"})
    assert mon.status_code == 201

    # Research Again → new linked run.
    again = await client.post(f"/research/{pid}/research-again",
                              json={"intent": "refresh", "auto_start": True})
    child = again.json()["id"]
    await run_to_completion(child, timeout=60)
    assert (await client.get(f"/research/{child}")).json()["status"] == "completed"

    # Same lineage.
    child_detail = (await client.get(f"/research/{child}")).json()
    assert child_detail["root_id"] == pid

    # Diff is coherent.
    diff = (await client.get(f"/research/{pid}/diff/{child}")).json()
    assert "claims" in diff and "recommendation" in diff

    # Graph reconciled supersession across the lineage.
    async with SessionLocal() as db:
        from app.models import KgClaimLink
        links = (await db.execute(
            select(KgClaimLink).where(KgClaimLink.predicate == "supersedes"))
        ).scalars().all()
    assert links, "Research Again should reconcile at least one supersession into the graph"


# --------------------------------------------------------------------------- #
# External-client E2E — REST and MCP walk the same flow (spec §44, §51)
# --------------------------------------------------------------------------- #
async def test_rest_external_flow(client, patch_pipeline):
    start = await client.post("/v1/research", json={"query": "external rest flow topic"})
    assert start.status_code == 202
    rid = start.json()["research_id"]
    await run_to_completion(rid, timeout=60)
    assert (await client.get(f"/v1/research/{rid}/status")).json()["status"] == "completed"
    assert (await client.get(f"/v1/research/{rid}/report?excerpt=true")).status_code == 200
    claims = (await client.get(f"/v1/research/{rid}/claims")).json()["claims"]
    assert claims
    ev = (await client.get(
        f"/v1/research/{rid}/claims/{claims[0]['claim_id']}/evidence")).json()
    assert "evidence" in ev


async def test_mcp_external_flow(client, patch_pipeline):
    from app.mcp.server import McpServer

    token = client.headers["Authorization"].split(" ", 1)[1]
    server = McpServer(token=token)

    async def call(name, args):
        resp = await server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                    "params": {"name": name, "arguments": args}})
        return json.loads(resp["result"]["content"][0]["text"])

    started = await call("research_start", {"query": "external mcp flow topic"})
    rid = started["research_id"]
    await run_to_completion(rid, timeout=60)
    st = await call("research_status", {"research_id": rid})
    assert st["status"] == "completed"
    rep = await call("research_report", {"research_id": rid})
    assert rep["research_id"] == rid
    claims = (await call("research_claims", {"research_id": rid}))["claims"]
    assert claims

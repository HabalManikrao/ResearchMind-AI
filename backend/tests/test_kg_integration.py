"""Knowledge-graph integration with the pipeline (#7, spec §20-§22, §32, §34).

Graph built after research, updated after Research Again + monitoring, offline-safe (Tier-1,
no LLM), and failure-isolated (a graph failure never fails the run; retry works). Uses the
faked pipeline + faked connectivity (no network), matching the #5/#6 test pattern.
"""
import pytest
from sqlalchemy import select

import app.knowledge.graph as kg
import app.orchestration.orchestrator as orch
import app.services.connectivity as conn
import app.services.research_monitor as rm
from app.database import SessionLocal
from app.models import KgClaimLink, KgEntity, ResearchProject
from app.services.connectivity import ONLINE, ConnectivitySnapshot
from app.services.research_diff import ResearchDiff
from tests.conftest import run_to_completion


@pytest.fixture(autouse=True)
def _fake_connectivity(monkeypatch):
    async def fake_snapshot(force=False):
        return ConnectivitySnapshot(
            overall=ONLINE, internet=True, search_provider=True,
            ollama=True, qdrant=True, database=True,
        )
    monkeypatch.setattr(conn.manager, "snapshot", fake_snapshot)


async def _run(client, query="best vector db", **body):
    r = await client.post("/research", json={"query": query, "sources_enabled": ["web"],
                                             "auto_start": True, **body})
    pid = r.json()["id"]
    await run_to_completion(pid, timeout=60)
    assert (await client.get(f"/research/{pid}")).json()["status"] == "completed"
    return pid


# --------------------------------------------------------------------------- #
# Graph built after a research run (spec §20)
# --------------------------------------------------------------------------- #
async def test_graph_built_after_research(client, patch_pipeline):
    pid = await _run(client)
    # The fake pipeline yields a Solution/Recommendation "OptX" → an entity.
    async with SessionLocal() as db:
        ents = (await db.execute(
            select(KgEntity).where(KgEntity.user_id == client.default_user["id"]))
        ).scalars().all()
    assert ents, "graph produced at least one entity from structured data"
    # Graph status recorded in the existing report_meta (no new column).
    report = (await client.get(f"/research/{pid}/report")).json()
    assert report["meta"]["graph_status"]["state"] == "ok"


# --------------------------------------------------------------------------- #
# Graph updated after Research Again — supersession via the diff (spec §21, §38)
# --------------------------------------------------------------------------- #
async def test_graph_updated_after_research_again(client, patch_pipeline):
    parent = await _run(client)
    r = await client.post(f"/research/{parent}/research-again",
                          json={"intent": "refresh", "auto_start": True})
    child = r.json()["id"]
    await run_to_completion(child, timeout=60)
    assert (await client.get(f"/research/{child}")).json()["status"] == "completed"

    # The child's matching claim supersedes the parent's (temporal transition).
    async with SessionLocal() as db:
        links = (await db.execute(
            select(KgClaimLink).where(KgClaimLink.predicate == "supersedes"))
        ).scalars().all()
    assert links, "Research Again reconciled a supersession into the graph"


# --------------------------------------------------------------------------- #
# Graph updated after a monitoring escalation (spec §22)
# --------------------------------------------------------------------------- #
async def test_graph_updated_after_monitoring(client, patch_pipeline, monkeypatch):
    pid = await _run(client)
    r = await client.post(f"/research/{pid}/monitor", json={"frequency": "daily"})
    mid = r.json()["id"]

    async def escalating_probe(monitor, baseline):
        p = rm._Probe(); p.escalate = True; p.live = 1
        return p
    monkeypatch.setattr(rm, "_cheap_probe", escalating_probe)

    async def fake_diff(old_id, new_id):
        return ResearchDiff(old_run={}, new_run={}, sources={"items": []},
                            claims={"items": []}, confidence={},
                            recommendation={"kind": "reversed", "old": {"option": "OptX"},
                                            "new": {"option": "OptY"}},
                            documents={"items": []})
    monkeypatch.setattr(rm.research_diff, "diff_runs", fake_diff)

    result = await rm.run_monitor_check(mid)
    assert result["status"] == "changes"
    child_id = result["notification_id"] and None  # not needed; find the child run

    # The escalated child run built the graph via its completion hook.
    async with SessionLocal() as db:
        child = (await db.execute(
            select(ResearchProject).where(ResearchProject.parent_id == pid))
        ).scalars().first()
    assert child is not None
    assert (child.report_meta or {}).get("graph_status", {}).get("state") == "ok"


# --------------------------------------------------------------------------- #
# Offline / CPU: Tier-1 build needs no LLM (spec §2, §16, §34)
# --------------------------------------------------------------------------- #
async def test_tier1_build_needs_no_llm(db):
    """With LLM extraction off (default), building the graph must not call the LLM and must
    produce only explicit/derived provenance — never 'inferred'."""
    from app.models import Claim, ClaimStatus, Recommendation, Solution
    from datetime import datetime, timezone

    proj = ResearchProject(user_id="u1", title="t", query="q", objective="o",
                           status="completed", completed_at=datetime.now(timezone.utc),
                           run_number=1)
    db.add(proj)
    await db.flush()
    proj.root_id = proj.id
    db.add(Solution(project_id=proj.id, name="Unreal Engine 5", description="d"))
    db.add(Solution(project_id=proj.id, name="Unity", description="d"))
    db.add(Claim(project_id=proj.id, text="Unreal Engine 5 beats Unity for AAA.",
                 status=ClaimStatus.VERIFIED, confidence=80.0, supporting_source_ids=[]))
    await db.commit()

    # A provider whose LLM call would raise — proving Tier-1 never invokes it.
    class _Boom:
        async def structured_output(self, *a, **k):
            raise AssertionError("Tier-1 build must not call the LLM")
        async def embed(self, texts):
            raise AssertionError("no embeddings in Tier-1 build")
    import app.llm as llm
    orig = llm.get_provider
    llm.get_provider = lambda: _Boom()
    try:
        result = await kg.build_graph_for_project(proj.id)
    finally:
        llm.get_provider = orig

    assert result["state"] == "ok"
    from app.models import KgRelationship
    rels = (await db.execute(select(KgRelationship))).scalars().all()
    assert rels and all(r.provenance_kind in ("explicit", "derived") for r in rels)


# --------------------------------------------------------------------------- #
# Failure isolation + retry (spec §20, §32)
# --------------------------------------------------------------------------- #
async def test_graph_failure_does_not_fail_research_and_can_retry(
    client, patch_pipeline, monkeypatch
):
    async def boom(project_id):
        raise RuntimeError("graph exploded")
    monkeypatch.setattr(orch.kg_graph, "build_graph_for_project", boom)

    pid = await _run(client)  # research must still COMPLETE despite graph failure
    report = (await client.get(f"/research/{pid}/report")).json()
    assert report["meta"]["graph_status"]["state"] == "degraded"

    # Retry once the underlying issue is resolved.
    monkeypatch.undo()
    r = await client.post(f"/knowledge/graph/rebuild/{pid}")
    assert r.status_code == 200 and r.json()["ok"] is True
    async with SessionLocal() as db:
        ents = (await db.execute(
            select(KgEntity).where(KgEntity.user_id == client.default_user["id"]))
        ).scalars().all()
    assert ents  # graph populated on retry

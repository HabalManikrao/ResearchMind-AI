"""R&D layer Phase B — Methods & Hypotheses.

CRUD + validation + versioning + relationships + ownership (cross-user 404) + cross-project
reference rejection + truthfulness (no auto-advance, no fabricated experiment/result) + offline +
planner integration. Additive on the Phase A substrate; Phase A behavior untouched.
"""
import pytest

import app.orchestration.orchestrator as orch
from app.database import SessionLocal
from app.models import Claim, Source
from tests.conftest import register_user, run_to_completion


async def _project(client):
    r = await client.post("/research", json={"query": "compare vector databases",
                                             "sources_enabled": ["web"], "auto_start": False})
    assert r.status_code in (200, 201), r.text
    return r.json()["id"]


async def _add_source_and_claim(project_id: str):
    """Insert a real Source + Claim for this project so relationship tests have valid ids."""
    async with SessionLocal() as db:
        s = Source(project_id=project_id, title="Doc", url="https://ex.com/a", source_type="web")
        db.add(s)
        await db.flush()
        c = Claim(project_id=project_id, text="Qdrant is fast")
        db.add(c)
        await db.flush()
        sid, cid = s.id, c.id
        await db.commit()
    return sid, cid


# --------------------------------------------------------------------------- #
# Methods — CRUD, validation, versioning.
# --------------------------------------------------------------------------- #
async def test_method_crud_and_versioning(client):
    pid = await _project(client)
    r = await client.post(f"/research/{pid}/methods", json={
        "name": "Benchmark methodology", "description": "run workload Z",
        "inputs": ["dataset"], "outputs": ["latency p95"]})
    assert r.status_code == 201, r.text
    m = r.json()
    assert m["status"] == "proposed" and m["origin"] == "user" and m["version"] == 1

    r = await client.patch(f"/research/{pid}/methods/{m['id']}",
                           json={"status": "active", "procedure": "1. warmup 2. measure"})
    assert r.status_code == 200
    assert r.json()["status"] == "active" and r.json()["version"] == 2  # edit bumped version

    got = (await client.get(f"/research/{pid}/methods/{m['id']}")).json()
    assert got["procedure"] == "1. warmup 2. measure"
    assert len((await client.get(f"/research/{pid}/methods")).json()) == 1

    assert (await client.delete(f"/research/{pid}/methods/{m['id']}")).status_code == 204
    assert (await client.get(f"/research/{pid}/methods")).json() == []


async def test_method_invalid_status_rejected(client):
    pid = await _project(client)
    r = await client.post(f"/research/{pid}/methods",
                          json={"name": "M", "status": "totally_bogus"})
    assert r.status_code == 422


async def test_method_links_to_source_and_claim(client):
    pid = await _project(client)
    sid, cid = await _add_source_and_claim(pid)
    r = await client.post(f"/research/{pid}/methods", json={
        "name": "Literature-derived method", "origin": "derived",
        "source_ids": [sid], "claim_ids": [cid]})
    assert r.status_code == 201
    assert r.json()["source_ids"] == [sid] and r.json()["claim_ids"] == [cid]


# --------------------------------------------------------------------------- #
# Hypotheses — CRUD, distinct from claims, status lifecycle.
# --------------------------------------------------------------------------- #
async def test_hypothesis_crud(client):
    pid = await _project(client)
    r = await client.post(f"/research/{pid}/hypotheses", json={
        "statement": "Qdrant will outperform Chroma on workload Z",
        "reasoning": "HNSW tuning", "expected_result": "lower p95"})
    assert r.status_code == 201, r.text
    h = r.json()
    assert h["status"] == "proposed"  # never auto-advances
    assert h["confidence"] is None  # unset until judged
    assert h["origin"] == "user"

    r = await client.patch(f"/research/{pid}/hypotheses/{h['id']}",
                           json={"status": "testing", "confidence": 40})
    assert r.status_code == 200 and r.json()["status"] == "testing" and r.json()["confidence"] == 40

    assert (await client.delete(f"/research/{pid}/hypotheses/{h['id']}")).status_code == 204


async def test_hypothesis_invalid_status_and_confidence_rejected(client):
    pid = await _project(client)
    assert (await client.post(f"/research/{pid}/hypotheses",
            json={"statement": "x y z", "status": "proven"})).status_code == 422
    assert (await client.post(f"/research/{pid}/hypotheses",
            json={"statement": "x y z", "confidence": 500})).status_code == 422


async def test_hypothesis_links_question_objective_claim_method(client):
    pid = await _project(client)
    # Real Phase A question + objective + Phase B method + a claim.
    q = (await client.post(f"/research/{pid}/questions",
                           json={"text": "Is Qdrant faster?", "priority": 1})).json()
    o = (await client.post(f"/research/{pid}/objectives",
                           json={"description": "pick fastest DB"})).json()
    m = (await client.post(f"/research/{pid}/methods", json={"name": "Bench"})).json()
    _, cid = await _add_source_and_claim(pid)

    r = await client.post(f"/research/{pid}/hypotheses", json={
        "statement": "Qdrant beats Chroma", "question_ids": [q["id"]],
        "objective_ids": [o["id"]], "claim_ids": [cid], "method_id": m["id"]})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["question_ids"] == [q["id"]] and body["objective_ids"] == [o["id"]]
    assert body["claim_ids"] == [cid] and body["method_id"] == m["id"]


# --------------------------------------------------------------------------- #
# Cross-project / cross-user reference injection is rejected.
# --------------------------------------------------------------------------- #
async def test_cross_project_reference_rejected(client):
    pid_a = await _project(client)
    pid_b = await _project(client)
    _, cid_b = await _add_source_and_claim(pid_b)  # claim belongs to a DIFFERENT project
    r = await client.post(f"/research/{pid_a}/methods",
                          json={"name": "M", "claim_ids": [cid_b]})
    assert r.status_code == 422  # cannot attach another project's claim
    r = await client.post(f"/research/{pid_a}/hypotheses",
                          json={"statement": "abc", "claim_ids": [cid_b]})
    assert r.status_code == 422


async def test_cross_project_method_id_rejected(client):
    pid_a = await _project(client)
    pid_b = await _project(client)
    m_b = (await client.post(f"/research/{pid_b}/methods", json={"name": "B method"})).json()
    r = await client.post(f"/research/{pid_a}/hypotheses",
                          json={"statement": "abc", "method_id": m_b["id"]})
    assert r.status_code == 422


# --------------------------------------------------------------------------- #
# Security — cross-user isolation + auth.
# --------------------------------------------------------------------------- #
async def test_cross_user_phase_b_is_404(client):
    pid = await _project(client)
    m = (await client.post(f"/research/{pid}/methods", json={"name": "secret method"})).json()
    h = (await client.post(f"/research/{pid}/hypotheses", json={"statement": "secret hyp"})).json()
    token_b, _ = await register_user(client, email="intruder-b@example.com")
    hdr = {"Authorization": f"Bearer {token_b}"}
    for path in (f"/research/{pid}/methods", f"/research/{pid}/methods/{m['id']}",
                 f"/research/{pid}/hypotheses", f"/research/{pid}/hypotheses/{h['id']}"):
        assert (await client.get(path, headers=hdr)).status_code == 404, path
    assert (await client.patch(f"/research/{pid}/methods/{m['id']}", headers=hdr,
                               json={"status": "deprecated"})).status_code == 404
    assert (await client.delete(f"/research/{pid}/hypotheses/{h['id']}",
                                headers=hdr)).status_code == 404


async def test_phase_b_requires_auth(anon_client):
    assert (await anon_client.get("/research/x/methods")).status_code == 401
    assert (await anon_client.get("/research/x/hypotheses")).status_code == 401


# --------------------------------------------------------------------------- #
# Truthfulness — no auto-advance, no fabricated experiment/result, no LLM call.
# --------------------------------------------------------------------------- #
async def test_creating_hypothesis_does_not_fabricate_or_call_llm(client, monkeypatch):
    # Any LLM/provider use during pure CRUD is a bug — the get_provider path must not be touched.
    import app.llm as llm_pkg

    def boom():
        raise AssertionError("no LLM provider may be constructed during Phase B CRUD")

    monkeypatch.setattr(llm_pkg, "get_provider", boom, raising=False)

    pid = await _project(client)
    h = (await client.post(f"/research/{pid}/hypotheses",
                           json={"statement": "X outperforms Y"})).json()
    assert h["status"] == "proposed"  # a plausible statement is NOT auto-SUPPORTED

    # No experiment/result tables exist in Phase B → nothing fabricated. Status stays until
    # an explicit action changes it.
    again = (await client.get(f"/research/{pid}/hypotheses/{h['id']}")).json()
    assert again["status"] == "proposed"


async def test_no_experiment_or_result_tables_yet():
    # Phase B must NOT prematurely create Phase C tables.
    from app.database import Base
    tbls = set(Base.metadata.tables)
    assert "methods" in tbls and "hypotheses" in tbls
    assert "experiments" not in tbls and "results" not in tbls and "datasets" not in tbls


# --------------------------------------------------------------------------- #
# Planner integration — methods/hypotheses reach the deterministic planner hint (offline).
# --------------------------------------------------------------------------- #
async def test_methods_and_hypotheses_reach_planner_context(client, patch_pipeline, monkeypatch):
    pid = await _project(client)
    await client.post(f"/research/{pid}/methods", json={"name": "Benchmark harness"})
    await client.post(f"/research/{pid}/hypotheses",
                      json={"statement": "Qdrant beats Chroma on workload Z"})

    seen = {}
    real_make_plan = orch.planner.make_plan

    async def spy(provider, query, **kwargs):
        seen["brief_context"] = kwargs.get("brief_context")
        return await real_make_plan(provider, query, **kwargs)

    monkeypatch.setattr(orch.planner, "make_plan", spy)
    await client.post(f"/research/{pid}/start")
    await run_to_completion(pid)

    ctx = seen.get("brief_context") or ""
    assert "Benchmark harness" in ctx
    assert "Existing hypotheses" in ctx and "Qdrant beats Chroma" in ctx


# --------------------------------------------------------------------------- #
# Migration idempotency — Phase A data preserved after re-running create_all.
# --------------------------------------------------------------------------- #
async def test_migration_idempotent_preserves_phase_a(client):
    pid = await _project(client)
    await client.put(f"/research/{pid}/brief", json={"problem_statement": "keep me"})
    m = (await client.post(f"/research/{pid}/methods", json={"name": "keep method"})).json()

    from app.database import Base, engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)  # running create_all twice is a no-op

    # Phase A brief + Phase B method both survive.
    assert (await client.get(f"/research/{pid}/brief")).json()["problem_statement"] == "keep me"
    assert (await client.get(f"/research/{pid}/methods/{m['id']}")).json()["name"] == "keep method"

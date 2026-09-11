"""R&D layer Phase A — Brief, Objectives, Scope/Constraints, Questions, Terminology.

CRUD + validation + ownership (cross-user 404) + version-awareness + planner integration,
all offline. Additive on the existing research substrate; existing behavior untouched.
"""
import pytest

import app.orchestration.orchestrator as orch
from tests.conftest import register_user, run_to_completion


async def _project(client):
    r = await client.post("/research", json={"query": "compare vector databases",
                                             "sources_enabled": ["web"], "auto_start": False})
    assert r.status_code in (200, 201), r.text
    return r.json()["id"]


# --------------------------------------------------------------------------- #
# Research Brief — get-or-create, structured, version-aware.
# --------------------------------------------------------------------------- #
async def test_brief_get_or_create_then_update_bumps_version(client):
    pid = await _project(client)
    r = await client.get(f"/research/{pid}/brief")
    assert r.status_code == 200
    brief = r.json()
    assert brief["project_id"] == pid and brief["version"] == 1
    assert brief["problem_statement"] == "" and brief["scope_included"] == []

    r = await client.put(f"/research/{pid}/brief", json={
        "problem_statement": "Which vector DB fits an offline CPU box?",
        "scope_included": ["Qdrant", "Chroma"],
        "scope_excluded": ["managed cloud-only DBs"],
        "success_criteria": ["runs offline", "p95 < 50ms"],
    })
    assert r.status_code == 200
    b = r.json()
    assert b["version"] == 2  # edit bumped the version
    assert b["scope_included"] == ["Qdrant", "Chroma"]
    assert b["scope_excluded"] == ["managed cloud-only DBs"]

    # Persisted + still a single brief (1:1).
    b2 = (await client.get(f"/research/{pid}/brief")).json()
    assert b2["id"] == b["id"] and b2["version"] == 2


async def test_brief_partial_update_leaves_other_fields(client):
    pid = await _project(client)
    await client.put(f"/research/{pid}/brief", json={"background": "bg", "assumptions": ["a1"]})
    r = await client.put(f"/research/{pid}/brief", json={"expected_outcome": "a ranked shortlist"})
    b = r.json()
    assert b["background"] == "bg" and b["assumptions"] == ["a1"]  # untouched
    assert b["expected_outcome"] == "a ranked shortlist"
    assert b["version"] == 3  # two edits after the implicit create(v1)


# --------------------------------------------------------------------------- #
# Objectives — CRUD + validation.
# --------------------------------------------------------------------------- #
async def test_objectives_crud(client):
    pid = await _project(client)
    r = await client.post(f"/research/{pid}/objectives", json={
        "description": "Identify the fastest offline-capable vector DB", "priority": 1})
    assert r.status_code == 201
    oid = r.json()["id"]
    assert r.json()["status"] == "not_started" and r.json()["completion_pct"] == 0

    r = await client.patch(f"/research/{pid}/objectives/{oid}",
                           json={"status": "in_progress", "completion_pct": 40})
    assert r.status_code == 200 and r.json()["status"] == "in_progress"

    lst = (await client.get(f"/research/{pid}/objectives")).json()
    assert len(lst) == 1 and lst[0]["completion_pct"] == 40

    assert (await client.delete(f"/research/{pid}/objectives/{oid}")).status_code == 204
    assert (await client.get(f"/research/{pid}/objectives")).json() == []


async def test_objective_invalid_status_rejected(client):
    pid = await _project(client)
    r = await client.post(f"/research/{pid}/objectives",
                          json={"description": "x y z", "status": "totally_bogus"})
    assert r.status_code == 422  # pattern-validated


# --------------------------------------------------------------------------- #
# Constraints — typed.
# --------------------------------------------------------------------------- #
async def test_constraints_crud_and_type_validation(client):
    pid = await _project(client)
    r = await client.post(f"/research/{pid}/constraints",
                          json={"ctype": "hardware", "text": "CPU only, 16GB RAM"})
    assert r.status_code == 201
    cid = r.json()["id"]
    assert (await client.post(f"/research/{pid}/constraints",
                              json={"ctype": "not_a_type", "text": "x"})).status_code == 422
    assert len((await client.get(f"/research/{pid}/constraints")).json()) == 1
    assert (await client.delete(f"/research/{pid}/constraints/{cid}")).status_code == 204


# --------------------------------------------------------------------------- #
# Terminology — ambiguity preserved (two similar terms coexist).
# --------------------------------------------------------------------------- #
async def test_terminology_crud_preserves_distinct_terms(client):
    pid = await _project(client)
    await client.post(f"/research/{pid}/terminology",
                      json={"term": "HNSW", "definition": "graph index", "acronyms": ["HNSW"]})
    await client.post(f"/research/{pid}/terminology",
                      json={"term": "HNSWlib", "definition": "a library"})
    terms = (await client.get(f"/research/{pid}/terminology")).json()
    assert {t["term"] for t in terms} == {"HNSW", "HNSWlib"}  # not merged by name similarity

    tid = terms[0]["id"]
    r = await client.patch(f"/research/{pid}/terminology/{tid}", json={"confidence": 90})
    assert r.status_code == 200 and r.json()["confidence"] == 90
    assert (await client.delete(f"/research/{pid}/terminology/{tid}")).status_code == 204


# --------------------------------------------------------------------------- #
# Questions — first-class fields via PATCH.
# --------------------------------------------------------------------------- #
async def test_question_patch_sets_rnd_fields(client):
    pid = await _project(client)
    q = (await client.post(f"/research/{pid}/questions",
                           json={"text": "Which DB is fastest offline?", "priority": 1})).json()
    r = await client.patch(f"/research/{pid}/questions/{q['id']}", json={
        "category": "performance", "q_status": "answered",
        "answer": "Qdrant", "answer_confidence": 82})
    assert r.status_code == 200
    body = r.json()
    assert body["category"] == "performance" and body["q_status"] == "answered"
    assert body["answer"] == "Qdrant" and body["answer_confidence"] == 82

    assert (await client.patch(f"/research/{pid}/questions/{q['id']}",
                               json={"q_status": "bogus"})).status_code == 422


# --------------------------------------------------------------------------- #
# Planner integration — the brief steers planning (deterministic, offline).
# --------------------------------------------------------------------------- #
async def test_brief_context_reaches_the_planner(client, patch_pipeline, monkeypatch):
    pid = await _project(client)
    await client.put(f"/research/{pid}/brief", json={
        "problem_statement": "offline vector DB choice",
        "scope_excluded": ["managed cloud-only DBs"]})
    await client.post(f"/research/{pid}/constraints",
                      json={"ctype": "hardware", "text": "CPU only"})

    seen = {}
    real_make_plan = orch.planner.make_plan

    async def spy(provider, query, **kwargs):
        seen["brief_context"] = kwargs.get("brief_context")
        return await real_make_plan(provider, query, **kwargs)

    monkeypatch.setattr(orch.planner, "make_plan", spy)
    await client.post(f"/research/{pid}/start")
    await run_to_completion(pid)

    assert seen.get("brief_context")  # brief was assembled and passed
    assert "Out of scope" in seen["brief_context"]
    assert "CPU only" in seen["brief_context"]


async def test_no_brief_means_no_brief_context(client, patch_pipeline, monkeypatch):
    pid = await _project(client)  # no brief/constraints created
    seen = {"called": False, "value": "unset"}
    real_make_plan = orch.planner.make_plan

    async def spy(provider, query, **kwargs):
        seen["called"] = True
        seen["value"] = kwargs.get("brief_context")
        return await real_make_plan(provider, query, **kwargs)

    monkeypatch.setattr(orch.planner, "make_plan", spy)
    await client.post(f"/research/{pid}/start")
    await run_to_completion(pid)
    assert seen["called"] and seen["value"] is None  # unaffected when no brief exists


# --------------------------------------------------------------------------- #
# Security — cross-user isolation on every Phase A collection.
# --------------------------------------------------------------------------- #
async def test_cross_user_phase_a_is_404(client):
    pid = await _project(client)
    await client.put(f"/research/{pid}/brief", json={"problem_statement": "secret"})
    token_b, _ = await register_user(client, email="intruder@example.com")
    h = {"Authorization": f"Bearer {token_b}"}
    for path in (f"/research/{pid}/brief", f"/research/{pid}/objectives",
                 f"/research/{pid}/constraints", f"/research/{pid}/terminology"):
        assert (await client.get(path, headers=h)).status_code == 404, path
    # Writes are blocked too.
    assert (await client.put(f"/research/{pid}/brief", headers=h,
                             json={"problem_statement": "hack"})).status_code == 404
    assert (await client.post(f"/research/{pid}/objectives", headers=h,
                              json={"description": "hack it"})).status_code == 404


async def test_phase_a_requires_auth(anon_client):
    assert (await anon_client.get("/research/whatever/brief")).status_code == 401
    assert (await anon_client.get("/research/whatever/objectives")).status_code == 401

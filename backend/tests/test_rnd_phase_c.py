"""R&D layer Phase C — Experiments, Datasets, structured Results.

CRUD + lifecycle + relationships + ownership (cross-user 404) + cross-project reference rejection
(422) + truthfulness (planned≠executed, no fabricated metrics/timestamps, result requires explicit
recording) + offline (no LLM) + migration idempotency + planner context. Additive on Phase A/B.
"""
import pytest

import app.orchestration.orchestrator as orch
from app.database import SessionLocal
from app.models import Claim, Source
from tests.conftest import register_user, run_to_completion


async def _project(client):
    r = await client.post("/research", json={"query": "benchmark vector DBs",
                                             "sources_enabled": ["web"], "auto_start": False})
    assert r.status_code in (200, 201), r.text
    return r.json()["id"]


async def _source_and_claim(project_id):
    async with SessionLocal() as db:
        s = Source(project_id=project_id, title="Doc", url="https://ex.com/a", source_type="web")
        db.add(s); await db.flush()
        c = Claim(project_id=project_id, text="Qdrant is fast")
        db.add(c); await db.flush()
        sid, cid = s.id, c.id
        await db.commit()
    return sid, cid


# --------------------------------------------------------------------------- #
# Datasets — CRUD + version distinctness + provenance.
# --------------------------------------------------------------------------- #
async def test_dataset_crud_and_versions_are_distinct(client):
    pid = await _project(client)
    v1 = (await client.post(f"/research/{pid}/datasets", json={
        "name": "WorkloadZ", "version": "1", "source": "internal capture",
        "size": "2.3 GB", "record_count": 1000, "limitations": ["synthetic"]})).json()
    assert v1["version"] == "1" and v1["origin"] == "user" and v1["record_count"] == 1000

    # A new version is a NEW row that supersedes v1 — v1 is not overwritten.
    v2 = (await client.post(f"/research/{pid}/datasets", json={
        "name": "WorkloadZ", "version": "2", "supersedes_id": v1["id"]})).json()
    assert v2["id"] != v1["id"] and v2["supersedes_id"] == v1["id"]
    rows = (await client.get(f"/research/{pid}/datasets")).json()
    assert len(rows) == 2  # both versions retained (distinguishable)

    assert (await client.delete(f"/research/{pid}/datasets/{v2['id']}")).status_code == 204


async def test_dataset_invalid_origin_rejected(client):
    pid = await _project(client)
    r = await client.post(f"/research/{pid}/datasets", json={"name": "X", "origin": "bogus"})
    assert r.status_code == 422


async def test_dataset_cross_project_supersedes_rejected(client):
    pid_a = await _project(client)
    pid_b = await _project(client)
    d_b = (await client.post(f"/research/{pid_b}/datasets", json={"name": "B"})).json()
    r = await client.post(f"/research/{pid_a}/datasets",
                          json={"name": "A2", "supersedes_id": d_b["id"]})
    assert r.status_code == 422


# --------------------------------------------------------------------------- #
# Experiments — planned ≠ executed; relationships; lifecycle.
# --------------------------------------------------------------------------- #
async def test_experiment_created_is_planned_not_executed(client):
    pid = await _project(client)
    e = (await client.post(f"/research/{pid}/experiments", json={
        "name": "Latency benchmark", "expected_result": "p95 < 50ms",
        "procedure": "warmup then measure"})).json()
    # Truthfulness: a fresh experiment is PROPOSED with NO execution data fabricated.
    assert e["status"] == "proposed"
    assert e["started_at"] is None and e["completed_at"] is None
    assert e["actual_result_summary"] is None
    assert e["raw_data_reference"] is None


async def test_experiment_create_ignores_execution_fields(client):
    # Even if a client tries to inject execution fields at create time, they are not accepted
    # (ExperimentCreate has no such fields) — planned can't masquerade as executed.
    pid = await _project(client)
    e = (await client.post(f"/research/{pid}/experiments", json={
        "name": "E", "status": "completed",
        "actual_result_summary": "accuracy 94.2%", "completed_at": "2026-01-01"})).json()
    assert e["status"] == "completed"  # status is client-set (allowed)
    # ...but the fabricated execution payload was ignored (not part of the create contract).
    assert e["actual_result_summary"] is None
    assert e["completed_at"] is None


async def test_experiment_execution_is_recorded_only_by_explicit_patch(client):
    pid = await _project(client)
    e = (await client.post(f"/research/{pid}/experiments", json={"name": "E"})).json()
    # Explicit, deliberate recording of a manually-obtained outcome.
    upd = (await client.patch(f"/research/{pid}/experiments/{e['id']}", json={
        "status": "completed", "completed_at": "2026-02-01",
        "actual_result_summary": "recorded manually: p95=42ms"})).json()
    assert upd["status"] == "completed" and upd["completed_at"] == "2026-02-01"
    assert "recorded manually" in upd["actual_result_summary"]


async def test_experiment_links_all_upstream_objects(client):
    pid = await _project(client)
    q = (await client.post(f"/research/{pid}/questions", json={"text": "fastest DB?", "priority": 1})).json()
    o = (await client.post(f"/research/{pid}/objectives", json={"description": "pick DB"})).json()
    m = (await client.post(f"/research/{pid}/methods", json={"name": "Bench"})).json()
    h = (await client.post(f"/research/{pid}/hypotheses", json={"statement": "Qdrant wins"})).json()
    d = (await client.post(f"/research/{pid}/datasets", json={"name": "WL"})).json()
    e = (await client.post(f"/research/{pid}/experiments", json={
        "name": "E1", "question_id": q["id"], "objective_id": o["id"], "method_id": m["id"],
        "hypothesis_id": h["id"], "dataset_id": d["id"], "dataset_version": "1"})).json()
    assert e["question_id"] == q["id"] and e["objective_id"] == o["id"]
    assert e["method_id"] == m["id"] and e["hypothesis_id"] == h["id"] and e["dataset_id"] == d["id"]


async def test_experiment_cross_project_hypothesis_rejected(client):
    pid_a = await _project(client)
    pid_b = await _project(client)
    h_b = (await client.post(f"/research/{pid_b}/hypotheses", json={"statement": "x y z"})).json()
    r = await client.post(f"/research/{pid_a}/experiments",
                          json={"name": "E", "hypothesis_id": h_b["id"]})
    assert r.status_code == 422


# --------------------------------------------------------------------------- #
# Results — require an experiment; structured metrics; nothing fabricated.
# --------------------------------------------------------------------------- #
async def test_result_crud_with_structured_metrics(client):
    pid = await _project(client)
    e = (await client.post(f"/research/{pid}/experiments", json={"name": "E"})).json()
    d = (await client.post(f"/research/{pid}/datasets", json={"name": "WL"})).json()
    r = await client.post(f"/research/{pid}/results", json={
        "experiment_id": e["id"], "dataset_id": d["id"], "name": "p95 latency",
        "result_type": "benchmark",
        "metrics": [{"name": "p95_latency", "value": 42.0, "unit": "ms",
                     "lower_bound": 40.0, "upper_bound": 45.0, "conditions": "warm cache"}],
        "accuracy": 0.94, "latency": "42ms", "observations": "stable", "confidence": 80})
    assert r.status_code == 201, r.text
    res = r.json()
    assert res["experiment_id"] == e["id"] and res["dataset_id"] == d["id"]
    assert res["metrics"][0]["name"] == "p95_latency" and res["metrics"][0]["unit"] == "ms"
    assert res["metrics"][0]["lower_bound"] == 40.0 and res["accuracy"] == 0.94


async def test_result_requires_valid_experiment_in_project(client):
    pid_a = await _project(client)
    pid_b = await _project(client)
    e_b = (await client.post(f"/research/{pid_b}/experiments", json={"name": "E"})).json()
    r = await client.post(f"/research/{pid_a}/results", json={"experiment_id": e_b["id"]})
    assert r.status_code == 422  # cannot attach another project's experiment


async def test_result_invalid_type_rejected(client):
    pid = await _project(client)
    e = (await client.post(f"/research/{pid}/experiments", json={"name": "E"})).json()
    r = await client.post(f"/research/{pid}/results",
                          json={"experiment_id": e["id"], "result_type": "bogus"})
    assert r.status_code == 422


async def test_deleting_experiment_cascades_results(client):
    pid = await _project(client)
    e = (await client.post(f"/research/{pid}/experiments", json={"name": "E"})).json()
    await client.post(f"/research/{pid}/results", json={"experiment_id": e["id"], "name": "r"})
    assert len((await client.get(f"/research/{pid}/results")).json()) == 1
    assert (await client.delete(f"/research/{pid}/experiments/{e['id']}")).status_code == 204
    assert (await client.get(f"/research/{pid}/results")).json() == []  # cascaded


# --------------------------------------------------------------------------- #
# Truthfulness — an experiment can exist without a result; missing values stay missing.
# --------------------------------------------------------------------------- #
async def test_experiment_can_exist_without_result_and_missing_metrics_stay_missing(client):
    pid = await _project(client)
    e = (await client.post(f"/research/{pid}/experiments", json={"name": "E"})).json()
    assert (await client.get(f"/research/{pid}/results?experiment_id={e['id']}")).json() == []
    r = (await client.post(f"/research/{pid}/results", json={"experiment_id": e["id"]})).json()
    # No measurements supplied → all numeric fields remain null (nothing invented).
    assert r["accuracy"] is None and r["error_rate"] is None and r["latency"] is None
    assert r["metrics"] == [] and r["confidence"] is None


async def test_phase_c_crud_makes_no_llm_call(client, monkeypatch):
    import app.llm as llm_pkg

    def boom():
        raise AssertionError("no LLM provider may be constructed during Phase C CRUD")

    monkeypatch.setattr(llm_pkg, "get_provider", boom, raising=False)
    pid = await _project(client)
    d = (await client.post(f"/research/{pid}/datasets", json={"name": "D"})).json()
    e = (await client.post(f"/research/{pid}/experiments", json={"name": "E", "dataset_id": d["id"]})).json()
    r = await client.post(f"/research/{pid}/results", json={"experiment_id": e["id"]})
    assert r.status_code == 201


# --------------------------------------------------------------------------- #
# Security — cross-user isolation + auth.
# --------------------------------------------------------------------------- #
async def test_cross_user_phase_c_is_404(client):
    pid = await _project(client)
    d = (await client.post(f"/research/{pid}/datasets", json={"name": "secret"})).json()
    e = (await client.post(f"/research/{pid}/experiments", json={"name": "secret"})).json()
    res = (await client.post(f"/research/{pid}/results", json={"experiment_id": e["id"]})).json()
    token_b, _ = await register_user(client, email="intruder-c@example.com")
    hdr = {"Authorization": f"Bearer {token_b}"}
    for path in (f"/research/{pid}/datasets/{d['id']}", f"/research/{pid}/experiments/{e['id']}",
                 f"/research/{pid}/results/{res['id']}"):
        assert (await client.get(path, headers=hdr)).status_code == 404, path
    assert (await client.delete(f"/research/{pid}/experiments/{e['id']}",
                                headers=hdr)).status_code == 404


async def test_phase_c_requires_auth(anon_client):
    for p in ("experiments", "datasets", "results"):
        assert (await anon_client.get(f"/research/x/{p}")).status_code == 401


# --------------------------------------------------------------------------- #
# Migration idempotency — Phase A/B data preserved after re-running create_all.
# --------------------------------------------------------------------------- #
async def test_migration_idempotent_preserves_earlier_phases(client):
    pid = await _project(client)
    await client.put(f"/research/{pid}/brief", json={"problem_statement": "keep A"})  # Phase A
    m = (await client.post(f"/research/{pid}/methods", json={"name": "keep B"})).json()  # Phase B
    e = (await client.post(f"/research/{pid}/experiments", json={"name": "keep C"})).json()  # Phase C

    from app.database import Base, engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)  # idempotent no-op

    assert (await client.get(f"/research/{pid}/brief")).json()["problem_statement"] == "keep A"
    assert (await client.get(f"/research/{pid}/methods/{m['id']}")).json()["name"] == "keep B"
    assert (await client.get(f"/research/{pid}/experiments/{e['id']}")).json()["name"] == "keep C"


# --------------------------------------------------------------------------- #
# Planner integration — experiments/datasets reach the deterministic hint (offline).
# --------------------------------------------------------------------------- #
async def test_experiments_and_datasets_reach_planner_context(client, patch_pipeline, monkeypatch):
    pid = await _project(client)
    await client.post(f"/research/{pid}/experiments", json={"name": "Latency benchmark"})
    await client.post(f"/research/{pid}/datasets", json={"name": "WorkloadZ", "version": "3"})

    seen = {}
    real_make_plan = orch.planner.make_plan

    async def spy(provider, query, **kwargs):
        seen["ctx"] = kwargs.get("brief_context")
        return await real_make_plan(provider, query, **kwargs)

    monkeypatch.setattr(orch.planner, "make_plan", spy)
    await client.post(f"/research/{pid}/start")
    await run_to_completion(pid)

    ctx = seen.get("ctx") or ""
    assert "Latency benchmark" in ctx and "planned ≠ executed" in ctx
    assert "WorkloadZ" in ctx and "v3" in ctx

"""R&D layer Phase F — Reproducibility record, explicit verdict, safe metadata capture.

Covers: get-or-create record; default verdict NOT_ASSESSED; verdict never auto-computed; missing
metadata/git/model stay NULL; secrets never persisted; dataset version preserved; manual verdict keeps
origin/rationale; report projects the record honestly (no invented verdict); safe auto-capture at run
completion (verdict not_assessed, no LLM); run lineage still authoritative; ownership + offline +
migration idempotency (A–E preserved).
"""
import pytest

from app.agents.report import ReportInput, generate_report
from tests.conftest import FakeProvider, register_user, run_to_completion


async def _project(client, auto_start=False):
    r = await client.post("/research", json={"query": "phase f", "sources_enabled": ["web"],
                                             "auto_start": auto_start})
    assert r.status_code in (200, 201), r.text
    return r.json()["id"]


# --------------------------------------------------------------------------- #
# Record + verdict truthfulness.
# --------------------------------------------------------------------------- #
async def test_record_get_or_create_defaults_not_assessed(client):
    pid = await _project(client)
    r = await client.get(f"/research/{pid}/reproducibility")
    assert r.status_code == 200
    body = r.json()
    assert body["project_id"] == pid
    assert body["verdict"] == "not_assessed"  # default is honest
    # Nothing captured yet → identifiers are NULL (never fabricated).
    assert body["model_name"] is None and body["git_commit"] is None
    assert body["model_version"] is None and body["seed"] is None


async def test_complete_metadata_does_not_become_reproducible(client):
    pid = await _project(client)
    # Populate lots of metadata but DON'T set a verdict.
    r = await client.put(f"/research/{pid}/reproducibility", json={
        "model_name": "llama3.1:8b", "model_version": "8b", "embedding_model": "nomic-embed-text",
        "search_provider": "tavily", "seed": "42", "os": "Windows 11", "software_versions": ["py3.12"]})
    assert r.status_code == 200
    body = r.json()
    assert body["model_name"] == "llama3.1:8b"
    # Populated metadata must NOT flip the verdict.
    assert body["verdict"] == "not_assessed"


async def test_manual_verdict_preserves_rationale_and_origin(client):
    pid = await _project(client)
    r = await client.put(f"/research/{pid}/reproducibility", json={
        "verdict": "partially_reproducible", "rationale": "model version pinned but dataset unversioned",
        "assessed_by": "researcher", "origin": "user"})
    assert r.status_code == 200
    body = r.json()
    assert body["verdict"] == "partially_reproducible"
    assert "dataset unversioned" in body["rationale"] and body["assessed_by"] == "researcher"
    assert body["origin"] == "user"


async def test_invalid_verdict_rejected(client):
    pid = await _project(client)
    r = await client.put(f"/research/{pid}/reproducibility", json={"verdict": "definitely_repro"})
    assert r.status_code == 422


async def test_missing_metadata_stays_null(client):
    pid = await _project(client)
    await client.put(f"/research/{pid}/reproducibility", json={"model_name": "x"})
    body = (await client.get(f"/research/{pid}/reproducibility")).json()
    assert body["model_name"] == "x"
    assert body["git_commit"] is None and body["model_version"] is None  # not invented
    assert body["hardware"] is None and body["environment"] is None


# --------------------------------------------------------------------------- #
# Secret safety — hard rule.
# --------------------------------------------------------------------------- #
async def test_secrets_are_never_persisted(client):
    pid = await _project(client)
    r = await client.put(f"/research/{pid}/reproducibility", json={
        "configuration": {
            "model": "llama3.1:8b", "temperature": "0",   # safe → kept
            "api_key": "sk-SECRET", "TAVILY_TOKEN": "tok", "authorization": "Bearer x",
            "password": "p", "session_cookie": "c",        # secret → dropped
        }})
    assert r.status_code == 200
    cfg = r.json()["configuration"]
    assert cfg == {"model": "llama3.1:8b", "temperature": "0"}
    for bad in ("api_key", "TAVILY_TOKEN", "authorization", "password", "session_cookie"):
        assert bad not in cfg


# --------------------------------------------------------------------------- #
# Dataset version preserved exactly.
# --------------------------------------------------------------------------- #
async def test_dataset_version_preserved_exactly(client):
    pid = await _project(client)
    d = (await client.post(f"/research/{pid}/datasets", json={"name": "WL", "version": "2024-05-sha7"})).json()
    r = await client.put(f"/research/{pid}/reproducibility", json={
        "dataset_id": d["id"], "dataset_version": "2024-05-sha7"})
    assert r.status_code == 200
    assert r.json()["dataset_version"] == "2024-05-sha7"  # exact, not normalized


async def test_cross_project_experiment_ref_rejected(client):
    pid_a = await _project(client)
    pid_b = await _project(client)
    e_b = (await client.post(f"/research/{pid_b}/experiments", json={"name": "E"})).json()
    r = await client.put(f"/research/{pid_a}/reproducibility", json={"experiment_id": e_b["id"]})
    assert r.status_code == 422


# --------------------------------------------------------------------------- #
# Security + offline.
# --------------------------------------------------------------------------- #
async def test_cross_user_reproducibility_is_404(client):
    pid = await _project(client)
    await client.put(f"/research/{pid}/reproducibility", json={"model_name": "secret model"})
    token_b, _ = await register_user(client, email="intruder-f@example.com")
    hdr = {"Authorization": f"Bearer {token_b}"}
    assert (await client.get(f"/research/{pid}/reproducibility", headers=hdr)).status_code == 404
    assert (await client.put(f"/research/{pid}/reproducibility", headers=hdr,
                             json={"verdict": "reproducible"})).status_code == 404


async def test_reproducibility_requires_auth(anon_client):
    assert (await anon_client.get("/research/x/reproducibility")).status_code == 401


async def test_reproducibility_crud_makes_no_llm_call(client, monkeypatch):
    import app.llm as llm_pkg

    def boom():
        raise AssertionError("no LLM provider may be constructed during Phase F CRUD")

    monkeypatch.setattr(llm_pkg, "get_provider", boom, raising=False)
    pid = await _project(client)
    assert (await client.get(f"/research/{pid}/reproducibility")).status_code == 200
    assert (await client.put(f"/research/{pid}/reproducibility",
                             json={"seed": "7"})).status_code == 200


# --------------------------------------------------------------------------- #
# Safe auto-capture at run completion (offline pipeline).
# --------------------------------------------------------------------------- #
async def test_completed_run_autocaptures_not_assessed(client, patch_pipeline):
    pid = await _project(client, auto_start=True)
    await run_to_completion(pid)
    assert (await client.get(f"/research/{pid}")).json()["status"] == "completed"
    body = (await client.get(f"/research/{pid}/reproducibility")).json()
    # A completed run has a record — captured safely, verdict NOT_ASSESSED (never auto-positive).
    assert body["verdict"] == "not_assessed"
    assert body["origin"] == "agent"  # auto-captured
    assert body["model_name"] and body["search_provider"]  # safe identifiers captured from config
    assert body["as_of"]
    # Never a secret: provider_config_id is an id, not a key.
    assert body["provider_config_id"] and "sk-" not in (body["provider_config_id"] or "")


async def test_git_commit_never_fabricated(client):
    # The safe git helper returns None on failure and CRUD never invents a commit.
    import app.orchestration.orchestrator as orch
    c, b, d = orch._safe_git()
    assert c is None or isinstance(c, str)  # real value or None
    assert d is None or isinstance(d, bool)
    pid = await _project(client)  # a bare record (no auto-capture) has null git
    assert (await client.get(f"/research/{pid}/reproducibility")).json()["git_commit"] is None


# --------------------------------------------------------------------------- #
# Report projection (unit-level).
# --------------------------------------------------------------------------- #
def _base_input(**over):
    data = dict(
        objective="Choose a DB", query="compare dbs", questions=["Which?"],
        findings=["a finding"],
        claims=[{"text": "Qdrant is fast", "status": "verified", "confidence": 90}],
        sources=[{"title": "Docs", "url": "https://d", "source_type": "docs",
                  "reliability_score": 90, "published_date": "2025-01-01"}],
    )
    data.update(over)
    return ReportInput(**data)


async def test_report_reproducibility_not_assessed_is_honest():
    data = _base_input(reproducibility={
        "verdict": "not_assessed", "rationale": "", "model_name": "llama3.1:8b",
        "search_provider": "tavily", "git_commit": None})
    md, _ = await generate_report(FakeProvider(), data)
    assert "## Reproducibility" in md
    assert "Reproducibility verdict: Not assessed" in md
    assert "does not imply the research was reproduced" in md
    assert "llama3.1:8b" in md
    assert "Git commit" not in md  # null metadata omitted, never fabricated


async def test_report_reproducibility_absent_without_record():
    md, _ = await generate_report(FakeProvider(), _base_input())
    assert "## Reproducibility" not in md  # no record → no section, no invented verdict


async def test_report_does_not_invent_positive_verdict():
    # Even with rich metadata, the report shows only the recorded verdict.
    data = _base_input(reproducibility={
        "verdict": "not_assessed", "rationale": "", "model_name": "m", "model_version": "1",
        "embedding_model": "e", "seed": "42", "os": "linux", "as_of": "2026-01-01"})
    md, _ = await generate_report(FakeProvider(), data)
    assert "Not assessed" in md
    for pos in ("verdict: Reproducible", "Partially reproducible", "Not reproducible"):
        assert pos not in md


# --------------------------------------------------------------------------- #
# Migration idempotency — A–E preserved.
# --------------------------------------------------------------------------- #
async def test_migration_idempotent_preserves_earlier_phases(client):
    pid = await _project(client)
    await client.put(f"/research/{pid}/brief", json={"problem_statement": "keep A"})
    m = (await client.post(f"/research/{pid}/methods", json={"name": "keep B"})).json()
    e = (await client.post(f"/research/{pid}/experiments", json={"name": "keep C"})).json()
    lim = (await client.post(f"/research/{pid}/limitations", json={"description": "keep E"})).json()
    await client.put(f"/research/{pid}/reproducibility", json={"seed": "keep F"})

    from app.database import Base, engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)  # idempotent no-op

    assert (await client.get(f"/research/{pid}/brief")).json()["problem_statement"] == "keep A"
    assert (await client.get(f"/research/{pid}/methods/{m['id']}")).json()["name"] == "keep B"
    assert (await client.get(f"/research/{pid}/experiments/{e['id']}")).json()["name"] == "keep C"
    assert (await client.get(f"/research/{pid}/limitations/{lim['id']}")).json()["description"] == "keep E"
    assert (await client.get(f"/research/{pid}/reproducibility")).json()["seed"] == "keep F"

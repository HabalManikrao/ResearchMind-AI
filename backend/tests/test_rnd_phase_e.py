"""R&D layer Phase E — Comparisons, Limitations & (extended) Research Gaps.

Covers: Comparison CRUD + grounded/ungrounded truthfulness + evidence/experiment/result links;
Limitation CRUD + all types/severities/statuses + affected-object validation; KnowledgeGap extension
(auto-generated gaps preserved; write API; gap-is-not-a-fact); report Comparisons/Limitations/Research
Gaps sections from rows; ownership (cross-user 404) + cross-project rejection (422); offline (no LLM);
migration idempotency (A–D preserved).
"""
import pytest

from app.agents.report import ReportInput, generate_report
from app.database import SessionLocal
from app.models import Claim, KnowledgeGap, Source
from tests.conftest import FakeProvider, register_user


async def _project(client):
    r = await client.post("/research", json={"query": "phase e", "sources_enabled": ["web"],
                                             "auto_start": False})
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


async def _experiment_and_result(client, pid):
    e = (await client.post(f"/research/{pid}/experiments", json={"name": "Bench"})).json()
    r = (await client.post(f"/research/{pid}/results", json={"experiment_id": e["id"], "name": "p95"})).json()
    return e["id"], r["id"]


# --------------------------------------------------------------------------- #
# Comparisons — grounded vs ungrounded truthfulness.
# --------------------------------------------------------------------------- #
async def test_comparison_ungrounded_is_flagged(client):
    pid = await _project(client)
    r = await client.post(f"/research/{pid}/comparisons", json={
        "subject_a": "Model A", "criterion": "accuracy", "value": "91.2%"})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["grounded"] is False  # no source/experiment/result → not evidence-backed


async def test_comparison_grounded_on_result(client):
    pid = await _project(client)
    _, rid = await _experiment_and_result(client, pid)
    sid, _ = await _source_and_claim(pid)
    r = await client.post(f"/research/{pid}/comparisons", json={
        "subject_a": "Model A", "subject_b": "Model B", "criterion": "p95 latency",
        "value": "42", "unit": "ms", "result_ids": [rid], "source_ids": [sid]})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["grounded"] is True and body["result_ids"] == [rid]
    assert body["subject_b"] == "Model B" and body["unit"] == "ms"


async def test_comparison_crud_and_cross_project(client):
    pid = await _project(client)
    c = (await client.post(f"/research/{pid}/comparisons", json={"subject_a": "X", "value": "1"})).json()
    upd = await client.patch(f"/research/{pid}/comparisons/{c['id']}", json={"value": "2"})
    assert upd.status_code == 200 and upd.json()["value"] == "2"
    assert len((await client.get(f"/research/{pid}/comparisons")).json()) == 1
    assert (await client.delete(f"/research/{pid}/comparisons/{c['id']}")).status_code == 204

    pid_b = await _project(client)
    _, rid_b = await _experiment_and_result(client, pid_b)
    r = await client.post(f"/research/{pid}/comparisons",
                          json={"subject_a": "X", "result_ids": [rid_b]})
    assert r.status_code == 422  # cross-project result rejected


# --------------------------------------------------------------------------- #
# Limitations — types/severities/statuses, affected object, cross-project.
# --------------------------------------------------------------------------- #
async def test_limitation_all_types_and_crud(client):
    pid = await _project(client)
    for lt in ("source", "dataset", "method", "experiment", "technology",
               "research", "statistical", "environmental"):
        r = await client.post(f"/research/{pid}/limitations",
                              json={"ltype": lt, "description": f"limitation {lt}", "severity": "low"})
        assert r.status_code == 201, (lt, r.text)
    rows = (await client.get(f"/research/{pid}/limitations")).json()
    assert len(rows) == 8
    lid = rows[0]["id"]
    upd = await client.patch(f"/research/{pid}/limitations/{lid}",
                             json={"status": "mitigated", "mitigation": "use bigger sample"})
    assert upd.status_code == 200 and upd.json()["status"] == "mitigated"
    assert (await client.delete(f"/research/{pid}/limitations/{lid}")).status_code == 204


async def test_limitation_affected_object_validated(client):
    pid = await _project(client)
    _, rid = await _experiment_and_result(client, pid)  # gives an experiment in pid... use experiment id
    exp = (await client.get(f"/research/{pid}/experiments")).json()[0]["id"]
    r = await client.post(f"/research/{pid}/limitations", json={
        "ltype": "experiment", "description": "small sample", "affected_kind": "experiment",
        "affected_id": exp})
    assert r.status_code == 201, r.text

    # Cross-project affected_id rejected.
    pid_b = await _project(client)
    await _experiment_and_result(client, pid_b)
    exp_b = (await client.get(f"/research/{pid_b}/experiments")).json()[0]["id"]
    r = await client.post(f"/research/{pid}/limitations", json={
        "ltype": "experiment", "description": "x", "affected_kind": "experiment", "affected_id": exp_b})
    assert r.status_code == 422


async def test_limitation_invalid_type_and_severity_rejected(client):
    pid = await _project(client)
    assert (await client.post(f"/research/{pid}/limitations",
            json={"ltype": "bogus", "description": "abc"})).status_code == 422
    assert (await client.post(f"/research/{pid}/limitations",
            json={"description": "abc", "severity": "extreme"})).status_code == 422


async def test_limitation_links_to_evidence(client):
    pid = await _project(client)
    sid, cid = await _source_and_claim(pid)
    r = await client.post(f"/research/{pid}/limitations", json={
        "ltype": "source", "description": "single-source claim", "source_ids": [sid],
        "claim_ids": [cid], "confidence": 60})
    assert r.status_code == 201
    assert r.json()["source_ids"] == [sid] and r.json()["confidence"] == 60


# --------------------------------------------------------------------------- #
# Knowledge Gaps — extension preserves auto-generated gaps; write API; not-a-fact.
# --------------------------------------------------------------------------- #
async def test_gap_write_api_and_defaults(client):
    pid = await _project(client)
    r = await client.post(f"/research/{pid}/gaps", json={
        "question": "How does it scale beyond 10M vectors?", "importance": "high",
        "potential_investigation": "run a 10M-vector benchmark"})
    assert r.status_code == 201, r.text
    g = r.json()
    assert g["status"] == "open" and g["origin"] == "user"  # never auto-advanced/verified
    assert g["resolved"] is False and g["importance"] == "high"
    assert g["confidence"] is None  # not fabricated

    upd = await client.patch(f"/research/{pid}/gaps/{g['id']}", json={"status": "investigating"})
    assert upd.status_code == 200 and upd.json()["status"] == "investigating"
    assert (await client.delete(f"/research/{pid}/gaps/{g['id']}")).status_code == 204


async def test_gap_links_and_cross_project(client):
    pid = await _project(client)
    q = (await client.post(f"/research/{pid}/questions", json={"text": "scale?", "priority": 1})).json()
    h = (await client.post(f"/research/{pid}/hypotheses", json={"statement": "it scales"})).json()
    r = await client.post(f"/research/{pid}/gaps", json={
        "question": "gap q", "question_ids": [q["id"]], "hypothesis_ids": [h["id"]]})
    assert r.status_code == 201, r.text
    assert r.json()["hypothesis_ids"] == [h["id"]]

    pid_b = await _project(client)
    h_b = (await client.post(f"/research/{pid_b}/hypotheses", json={"statement": "b hypothesis"})).json()
    r = await client.post(f"/research/{pid}/gaps", json={"question": "x", "hypothesis_ids": [h_b["id"]]})
    assert r.status_code == 422


async def test_auto_generated_gaps_preserved_and_readable(client):
    # A gap created the "old" way (only the original columns) stays valid and readable via GET /gaps
    # with the new nullable fields defaulting to None (extension is backward-compatible).
    pid = await _project(client)
    async with SessionLocal() as db:
        db.add(KnowledgeGap(project_id=pid, question="auto gap", reason="loop", round=1))
        await db.commit()
    gaps = (await client.get(f"/research/{pid}/gaps")).json()
    assert len(gaps) == 1
    assert gaps[0]["question"] == "auto gap"
    assert gaps[0]["status"] is None and gaps[0]["importance"] is None  # nullable, not fabricated


# --------------------------------------------------------------------------- #
# Security + offline.
# --------------------------------------------------------------------------- #
async def test_cross_user_phase_e_is_404(client):
    pid = await _project(client)
    c = (await client.post(f"/research/{pid}/comparisons", json={"subject_a": "X", "value": "1"})).json()
    l = (await client.post(f"/research/{pid}/limitations", json={"description": "abc"})).json()
    g = (await client.post(f"/research/{pid}/gaps", json={"question": "a gap question"})).json()
    token_b, _ = await register_user(client, email="intruder-e@example.com")
    hdr = {"Authorization": f"Bearer {token_b}"}
    for path in (f"/research/{pid}/comparisons/{c['id']}", f"/research/{pid}/limitations/{l['id']}"):
        assert (await client.get(path, headers=hdr)).status_code == 404, path
    assert (await client.delete(f"/research/{pid}/gaps/{g['id']}", headers=hdr)).status_code == 404


async def test_phase_e_requires_auth(anon_client):
    for p in ("comparisons", "limitations"):
        assert (await anon_client.get(f"/research/x/{p}")).status_code == 401


async def test_phase_e_crud_makes_no_llm_call(client, monkeypatch):
    import app.llm as llm_pkg

    def boom():
        raise AssertionError("no LLM provider may be constructed during Phase E CRUD")

    monkeypatch.setattr(llm_pkg, "get_provider", boom, raising=False)
    pid = await _project(client)
    assert (await client.post(f"/research/{pid}/comparisons", json={"subject_a": "X"})).status_code == 201
    assert (await client.post(f"/research/{pid}/limitations", json={"description": "abc"})).status_code == 201
    assert (await client.post(f"/research/{pid}/gaps", json={"question": "a gap"})).status_code == 201


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


async def test_report_renders_phase_e_sections_from_rows():
    data = _base_input(
        comparisons=[{"subject_a": "A", "subject_b": "B", "criterion": "acc", "value": "91",
                      "unit": "%", "grounded": True}],
        limitations=[{"ltype": "dataset", "title": "synthetic data", "description": "d",
                      "severity": "high", "mitigation": "collect real", "status": "open"}],
        gaps=[{"question": "How does it scale?", "importance": "high"}],
    )
    md, _ = await generate_report(FakeProvider(), data)
    assert "## Comparisons" in md and "A vs. B" in md and "91 %" in md
    assert "## Limitations" in md and "synthetic data" in md and "_[dataset/high]_" in md
    assert "## Research Gaps" in md and "How does it scale?" in md
    assert "open questions / missing knowledge, not verified findings" in md


async def test_report_flags_ungrounded_comparison():
    data = _base_input(comparisons=[{"subject_a": "A", "criterion": "acc", "value": "99",
                                     "grounded": False}])
    md, _ = await generate_report(FakeProvider(), data)
    assert "ungrounded" in md  # a value with no source/experiment/result is flagged


async def test_report_without_phase_e_rows_has_no_sections():
    md, _ = await generate_report(FakeProvider(), _base_input())
    assert "## Comparisons" not in md and "## Limitations" not in md and "## Research Gaps" not in md


# --------------------------------------------------------------------------- #
# Migration idempotency — A–D preserved.
# --------------------------------------------------------------------------- #
async def test_migration_idempotent_preserves_earlier_phases(client):
    pid = await _project(client)
    await client.put(f"/research/{pid}/brief", json={"problem_statement": "keep A"})
    m = (await client.post(f"/research/{pid}/methods", json={"name": "keep B"})).json()
    e = (await client.post(f"/research/{pid}/experiments", json={"name": "keep C"})).json()
    _, cid = await _source_and_claim(pid)
    a = (await client.post(f"/research/{pid}/analysis",
                           json={"statement": "keep D analysis", "claim_ids": [cid]})).json()
    l = (await client.post(f"/research/{pid}/limitations", json={"description": "keep E"})).json()

    from app.database import Base, engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)  # idempotent no-op

    assert (await client.get(f"/research/{pid}/brief")).json()["problem_statement"] == "keep A"
    assert (await client.get(f"/research/{pid}/methods/{m['id']}")).json()["name"] == "keep B"
    assert (await client.get(f"/research/{pid}/experiments/{e['id']}")).json()["name"] == "keep C"
    assert (await client.get(f"/research/{pid}/analysis/{a['id']}")).json()["statement"] == "keep D analysis"
    assert (await client.get(f"/research/{pid}/limitations/{l['id']}")).json()["description"] == "keep E"

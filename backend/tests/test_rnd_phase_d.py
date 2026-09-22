"""R&D layer Phase D — Analysis, Conclusions & Recommendation extension.

Covers: Analysis/Conclusion CRUD + all classifications; ≥1-grounding enforcement; the
Result→Analysis→Claim bridge (a Result enters evidence THROUGH Analysis, never as a Source);
Conclusion→Analysis→Claim traceability; Recommendation link extension (existing behavior preserved);
report Analysis/Conclusions sections from rows; the sources-but-no-claims/findings truthfulness gate;
ownership (cross-user 404) + cross-project reference rejection (422); offline (no LLM in CRUD).
"""
import pytest

from app.agents.report import ReportInput, generate_report
from app.database import SessionLocal
from app.models import Claim, Experiment, Result, Source
from tests.conftest import FakeProvider, register_user


async def _project(client):
    r = await client.post("/research", json={"query": "analysis phase",
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


async def _experiment_and_result(client, pid):
    e = (await client.post(f"/research/{pid}/experiments", json={"name": "Bench"})).json()
    r = (await client.post(f"/research/{pid}/results", json={"experiment_id": e["id"], "name": "p95"})).json()
    return e["id"], r["id"]


# --------------------------------------------------------------------------- #
# Analysis — CRUD, grounding, classifications, Result bridge.
# --------------------------------------------------------------------------- #
async def test_analysis_requires_grounding(client):
    pid = await _project(client)
    # No claim/source/result reference → rejected (an analysis can't be ungrounded).
    r = await client.post(f"/research/{pid}/analysis",
                          json={"statement": "X is faster", "classification": "inference"})
    assert r.status_code == 422


async def test_analysis_grounded_on_result_bridges_experiment_evidence(client):
    # Result → Analysis → (Claim) : a Result becomes traceable THROUGH Analysis, not as a Source.
    pid = await _project(client)
    _, rid = await _experiment_and_result(client, pid)
    _, cid = await _source_and_claim(pid)
    r = await client.post(f"/research/{pid}/analysis", json={
        "statement": "Measured p95 supports the latency claim", "classification": "fact",
        "result_ids": [rid], "claim_ids": [cid]})
    assert r.status_code == 201, r.text
    a = r.json()
    assert a["result_ids"] == [rid] and a["claim_ids"] == [cid]
    assert a["classification"] == "fact"  # label doesn't imply independent verification


async def test_analysis_all_classifications_and_crud(client):
    pid = await _project(client)
    _, cid = await _source_and_claim(pid)
    ids = []
    for cls in ("fact", "interpretation", "inference", "hypothesis", "opinion"):
        a = (await client.post(f"/research/{pid}/analysis", json={
            "statement": f"stmt {cls}", "classification": cls, "claim_ids": [cid]})).json()
        assert a["classification"] == cls
        ids.append(a["id"])
    assert len((await client.get(f"/research/{pid}/analysis")).json()) == 5
    # update + delete
    upd = await client.patch(f"/research/{pid}/analysis/{ids[0]}", json={"confidence": 70})
    assert upd.status_code == 200 and upd.json()["confidence"] == 70
    assert (await client.delete(f"/research/{pid}/analysis/{ids[0]}")).status_code == 204


async def test_analysis_invalid_classification_rejected(client):
    pid = await _project(client)
    _, cid = await _source_and_claim(pid)
    r = await client.post(f"/research/{pid}/analysis",
                          json={"statement": "some statement", "classification": "bogus", "claim_ids": [cid]})
    assert r.status_code == 422


# --------------------------------------------------------------------------- #
# Conclusions — CRUD, grounding, classifications, traceability.
# --------------------------------------------------------------------------- #
async def test_conclusion_requires_grounding(client):
    pid = await _project(client)
    r = await client.post(f"/research/{pid}/conclusions",
                          json={"statement": "We should adopt X", "classification": "supported"})
    assert r.status_code == 422  # needs >=1 analysis or claim


async def test_conclusion_traceable_to_analysis_and_claim(client):
    pid = await _project(client)
    _, cid = await _source_and_claim(pid)
    a = (await client.post(f"/research/{pid}/analysis",
                           json={"statement": "interp", "claim_ids": [cid]})).json()
    r = await client.post(f"/research/{pid}/conclusions", json={
        "statement": "X is the best choice", "classification": "strongly_supported",
        "analysis_ids": [a["id"]], "claim_ids": [cid], "confidence": 85})
    assert r.status_code == 201, r.text
    c = r.json()
    assert c["analysis_ids"] == [a["id"]] and c["claim_ids"] == [cid]
    assert c["classification"] == "strongly_supported" and c["confidence"] == 85


async def test_conclusion_all_classifications(client):
    pid = await _project(client)
    _, cid = await _source_and_claim(pid)
    for cls in ("proven", "strongly_supported", "supported", "weakly_supported",
                "inconclusive", "unknown", "contradicted", "disproved"):
        r = await client.post(f"/research/{pid}/conclusions",
                              json={"statement": f"c {cls}", "classification": cls, "claim_ids": [cid]})
        assert r.status_code == 201, (cls, r.text)


async def test_conclusion_confidence_absence_preserved(client):
    pid = await _project(client)
    _, cid = await _source_and_claim(pid)
    c = (await client.post(f"/research/{pid}/conclusions",
                           json={"statement": "a conclusion", "claim_ids": [cid]})).json()
    assert c["confidence"] is None  # never fabricated
    assert c["classification"] == "inconclusive"  # not auto-promoted


# --------------------------------------------------------------------------- #
# Recommendation extension — existing behavior preserved + new links.
# --------------------------------------------------------------------------- #
async def test_recommendation_link_extension(client):
    pid = await _project(client)
    _, cid = await _source_and_claim(pid)
    a = (await client.post(f"/research/{pid}/analysis",
                           json={"statement": "an analysis", "claim_ids": [cid]})).json()
    concl = (await client.post(f"/research/{pid}/conclusions",
                               json={"statement": "a conclusion", "analysis_ids": [a["id"]]})).json()
    # Seed a recommendation row (normally pipeline-generated).
    async with SessionLocal() as db:
        from app.models import Recommendation
        rec = Recommendation(project_id=pid, recommended_option="Qdrant", rationale="fast",
                             confidence=80.0)
        db.add(rec); await db.commit()

    r = await client.patch(f"/research/{pid}/recommendation/links", json={
        "conclusion_ids": [concl["id"]], "analysis_ids": [a["id"]], "priority": "high",
        "expected_benefit": "lower latency", "tradeoffs": ["ops cost"]})
    assert r.status_code == 200, r.text
    body = r.json()
    # Existing fields preserved; new links added.
    assert body["recommended_option"] == "Qdrant" and body["confidence"] == 80.0
    assert body["conclusion_ids"] == [concl["id"]] and body["priority"] == "high"
    assert body["expected_benefit"] == "lower latency" and body["tradeoffs"] == ["ops cost"]


async def test_recommendation_links_reject_cross_project(client):
    pid_a = await _project(client)
    pid_b = await _project(client)
    _, cid_b = await _source_and_claim(pid_b)
    a_b = (await client.post(f"/research/{pid_b}/analysis",
                             json={"statement": "an analysis", "claim_ids": [cid_b]})).json()
    async with SessionLocal() as db:
        from app.models import Recommendation
        db.add(Recommendation(project_id=pid_a, recommended_option="X", confidence=50.0))
        await db.commit()
    r = await client.patch(f"/research/{pid_a}/recommendation/links",
                           json={"analysis_ids": [a_b["id"]]})
    assert r.status_code == 422


async def test_recommendation_links_invalid_priority_rejected(client):
    pid = await _project(client)
    async with SessionLocal() as db:
        from app.models import Recommendation
        db.add(Recommendation(project_id=pid, recommended_option="X", confidence=50.0))
        await db.commit()
    r = await client.patch(f"/research/{pid}/recommendation/links", json={"priority": "urgent"})
    assert r.status_code == 422


# --------------------------------------------------------------------------- #
# Cross-project / cross-user security.
# --------------------------------------------------------------------------- #
async def test_cross_project_analysis_claim_rejected(client):
    pid_a = await _project(client)
    pid_b = await _project(client)
    _, cid_b = await _source_and_claim(pid_b)
    r = await client.post(f"/research/{pid_a}/analysis",
                          json={"statement": "an analysis", "claim_ids": [cid_b]})
    assert r.status_code == 422


async def test_cross_user_phase_d_is_404(client):
    pid = await _project(client)
    _, cid = await _source_and_claim(pid)
    a = (await client.post(f"/research/{pid}/analysis",
                           json={"statement": "an analysis", "claim_ids": [cid]})).json()
    c = (await client.post(f"/research/{pid}/conclusions",
                           json={"statement": "a conclusion", "claim_ids": [cid]})).json()
    token_b, _ = await register_user(client, email="intruder-d@example.com")
    hdr = {"Authorization": f"Bearer {token_b}"}
    for path in (f"/research/{pid}/analysis/{a['id']}", f"/research/{pid}/conclusions/{c['id']}"):
        assert (await client.get(path, headers=hdr)).status_code == 404, path
    assert (await client.delete(f"/research/{pid}/analysis/{a['id']}", headers=hdr)).status_code == 404


async def test_phase_d_requires_auth(anon_client):
    for p in ("analysis", "conclusions"):
        assert (await anon_client.get(f"/research/x/{p}")).status_code == 401


async def test_phase_d_crud_makes_no_llm_call(client, monkeypatch):
    import app.llm as llm_pkg

    def boom():
        raise AssertionError("no LLM provider may be constructed during Phase D CRUD")

    monkeypatch.setattr(llm_pkg, "get_provider", boom, raising=False)
    pid = await _project(client)
    _, cid = await _source_and_claim(pid)
    a = await client.post(f"/research/{pid}/analysis", json={"statement": "an analysis", "claim_ids": [cid]})
    assert a.status_code == 201
    c = await client.post(f"/research/{pid}/conclusions",
                          json={"statement": "a conclusion", "analysis_ids": [a.json()["id"]]})
    assert c.status_code == 201


# --------------------------------------------------------------------------- #
# Report projection + truthfulness gate (unit-level on generate_report).
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


async def test_report_renders_analysis_and_conclusions_from_rows():
    data = _base_input(
        analysis=[{"title": "A1", "statement": "p95 supports the claim",
                   "classification": "fact", "confidence": 80}],
        conclusions=[{"title": "C1", "statement": "Adopt Qdrant",
                      "classification": "strongly_supported", "confidence": 85}],
    )
    md, meta = await generate_report(FakeProvider(), data)
    assert "## Analysis" in md and "p95 supports the claim" in md and "_[Fact]_" in md
    assert "## Conclusions" in md and "Adopt Qdrant" in md and "_[Strongly supported]_" in md


async def test_report_without_analysis_rows_has_no_analysis_section():
    md, _ = await generate_report(FakeProvider(), _base_input())
    assert "## Conclusions" not in md  # section appears ONLY when rows exist


class _NoGenerate(FakeProvider):
    async def generate(self, prompt, system=None):
        raise AssertionError("narrative LLM must not run when there are no claims/findings")


async def test_sources_without_claims_or_findings_blocks_narrative_conclusions():
    # Truthfulness gate: sources exist but nothing extracted → no evidence-backed conclusion prose.
    data = _base_input(claims=[], findings=[])
    md, meta = await generate_report(_NoGenerate(), data)  # LLM must NOT be called
    assert meta["conclusions_unsupported"] is True
    assert meta["evidence_incomplete"] is False  # sources DO exist
    assert "No evidence-backed conclusions available" in md


async def test_sources_with_claims_still_generates_narrative():
    # Regression: the normal path (sources + claims) is unaffected by the new gate.
    data = _base_input()  # has claims + findings + sources
    md, meta = await generate_report(FakeProvider(), data)
    assert meta["conclusions_unsupported"] is False
    assert "## Executive Summary" in md

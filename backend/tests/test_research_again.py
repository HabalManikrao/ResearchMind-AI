"""Research Again + lineage + memory + immutability + security (#4)."""
import pytest

from tests.conftest import _fake_vec, register_user, run_to_completion


async def _run_to_completion_via_api(client, sources=("web",)):
    r = await client.post(
        "/research",
        json={"query": "compare container runtimes", "sources_enabled": list(sources),
              "auto_start": True},
    )
    pid = r.json()["id"]
    await run_to_completion(pid)
    assert (await client.get(f"/research/{pid}")).json()["status"] == "completed"
    return pid


# --------------------------------------------------------------------------- #
# creation, lineage, memory
# --------------------------------------------------------------------------- #
async def test_original_run_is_root_of_its_lineage(client, patch_pipeline):
    pid = await _run_to_completion_via_api(client)
    detail = (await client.get(f"/research/{pid}")).json()
    assert detail["run_number"] == 1
    assert detail["run_intent"] == "original"
    assert detail["root_id"] == pid
    assert detail["parent_id"] is None
    assert detail["completed_at"]


async def test_research_again_creates_linked_run_and_preserves_parent(client, patch_pipeline):
    pid = await _run_to_completion_via_api(client)
    parent_claims = (await client.get(f"/research/{pid}/claims")).json()
    parent_report = (await client.get(f"/research/{pid}/report")).json()["markdown"]

    r = await client.post(f"/research/{pid}/research-again", json={"intent": "refresh"})
    assert r.status_code == 201, r.text
    child = r.json()
    assert child["id"] != pid
    assert child["parent_id"] == pid
    assert child["root_id"] == pid
    assert child["run_number"] == 2
    assert child["run_intent"] == "refresh"

    await run_to_completion(child["id"])
    assert (await client.get(f"/research/{child['id']}")).json()["status"] == "completed"

    # Parent is immutable — its claims and report are byte-for-byte unchanged.
    assert (await client.get(f"/research/{pid}/claims")).json() == parent_claims
    assert (await client.get(f"/research/{pid}/report")).json()["markdown"] == parent_report


async def test_research_again_requires_completed_parent(client, patch_pipeline):
    # create WITHOUT auto-start -> status "created", not completed
    r = await client.post(
        "/research",
        json={"query": "not completed yet", "sources_enabled": ["web"], "auto_start": False},
    )
    pid = r.json()["id"]
    resp = await client.post(f"/research/{pid}/research-again", json={"intent": "refresh"})
    assert resp.status_code == 409


async def test_runs_lineage_endpoint(client, patch_pipeline):
    pid = await _run_to_completion_via_api(client)
    child = (await client.post(f"/research/{pid}/research-again", json={"intent": "deepen"})).json()
    await run_to_completion(child["id"])

    runs = (await client.get(f"/research/{pid}/runs")).json()
    assert [r["run_number"] for r in runs] == [1, 2]
    assert runs[0]["run_intent"] == "original"
    assert runs[1]["run_intent"] == "deepen"
    assert runs[1]["claim_count"] >= 1
    # the lineage is visible from either run's id
    runs_from_child = (await client.get(f"/research/{child['id']}/runs")).json()
    assert {r["id"] for r in runs_from_child} == {r["id"] for r in runs}


async def test_memory_summary_built_at_completion(client, patch_pipeline):
    pid = await _run_to_completion_via_api(client)
    mem = (await client.get(f"/research/{pid}/memory")).json()["memory"]
    assert mem is not None
    assert mem["counts"]["claims"] >= 1
    assert "high_confidence_claims" in mem
    assert mem["as_of"]


# --------------------------------------------------------------------------- #
# prior context feeds the planner (§8) — no extra LLM call
# --------------------------------------------------------------------------- #
async def test_continuation_feeds_prior_context_to_planner(client, patch_pipeline, monkeypatch):
    import app.orchestration.orchestrator as orch
    from app.agents.planner import PlannedQuestion, ResearchPlan

    pid = await _run_to_completion_via_api(client)

    captured = {}

    async def spy_make_plan(provider, query, *, constraints=None, max_questions=8,
                            market=False, as_of=None, prior_context=None, intent="original",
                            brief_context=None):
        captured["prior_context"] = prior_context
        captured["intent"] = intent
        return ResearchPlan(objective="obj", questions=[PlannedQuestion("Q1?", 1, "q1")])

    monkeypatch.setattr(orch.planner, "make_plan", spy_make_plan)

    child = (await client.post(f"/research/{pid}/research-again", json={"intent": "verify"})).json()
    await run_to_completion(child["id"])

    assert captured["intent"] == "verify"
    pc = captured["prior_context"]
    assert pc is not None
    # Prior context is built from the parent's own rows and threaded into the planner
    # (the parent's objective + recommendation prove it flowed through).
    assert pc.objective
    assert pc.recommendation and "OptX" in pc.recommendation
    assert pc.as_of  # previous research date


# --------------------------------------------------------------------------- #
# failure isolation (§26)
# --------------------------------------------------------------------------- #
async def test_research_again_failure_leaves_parent_intact(client, patch_pipeline, monkeypatch):
    import app.orchestration.orchestrator as orch

    pid = await _run_to_completion_via_api(client)
    parent_report = (await client.get(f"/research/{pid}/report")).json()["markdown"]

    async def boom(*args, **kwargs):
        raise RuntimeError("planning exploded")

    monkeypatch.setattr(orch.planner, "make_plan", boom)

    child = (await client.post(f"/research/{pid}/research-again", json={"intent": "refresh"})).json()
    await run_to_completion(child["id"])

    assert (await client.get(f"/research/{child['id']}")).json()["status"] == "failed"
    parent = (await client.get(f"/research/{pid}")).json()
    assert parent["status"] == "completed"
    assert (await client.get(f"/research/{pid}/report")).json()["markdown"] == parent_report


# --------------------------------------------------------------------------- #
# diff endpoint (integration)
# --------------------------------------------------------------------------- #
async def test_diff_endpoint_between_runs(client, patch_pipeline):
    pid = await _run_to_completion_via_api(client)
    child = (await client.post(f"/research/{pid}/research-again", json={"intent": "refresh"})).json()
    await run_to_completion(child["id"])

    d = (await client.get(f"/research/{child['id']}/diff/{pid}")).json()
    assert d["old_run"]["run_number"] == 1
    assert d["new_run"]["run_number"] == 2
    for section in ("sources", "claims", "documents"):
        assert section in d
    assert "kind" in d["recommendation"]


async def test_diff_requires_same_lineage(client, patch_pipeline):
    a = await _run_to_completion_via_api(client)
    b = await _run_to_completion_via_api(client)  # independent investigation
    resp = await client.get(f"/research/{a}/diff/{b}")
    assert resp.status_code == 404


# --------------------------------------------------------------------------- #
# security / isolation (§27)
# --------------------------------------------------------------------------- #
async def test_cross_user_cannot_access_lineage_or_fork(client, patch_pipeline):
    pid = await _run_to_completion_via_api(client)
    token2, _ = await register_user(client, email="intruder@example.com")
    h = {"Authorization": f"Bearer {token2}"}

    assert (await client.get(f"/research/{pid}/runs", headers=h)).status_code == 404
    assert (await client.get(f"/research/{pid}/memory", headers=h)).status_code == 404
    assert (
        await client.post(f"/research/{pid}/research-again", json={"intent": "refresh"}, headers=h)
    ).status_code == 404
    assert (await client.get(f"/research/{pid}/diff/{pid}", headers=h)).status_code == 404


# --------------------------------------------------------------------------- #
# document carry-forward (§13) — copies rows + vectors without re-embedding
# --------------------------------------------------------------------------- #
async def test_carry_forward_documents_copies_rows_and_vectors(db):
    from sqlalchemy import select

    from app.documents.service import carry_forward_documents
    from app.knowledge import vector_store as vs
    from app.models import Document, DocumentChunk, DocumentStatus, ProjectStatus, ResearchProject

    parent = ResearchProject(query="q", title="t", status=ProjectStatus.COMPLETED)
    child = ResearchProject(query="q", title="t", status=ProjectStatus.CREATED)
    db.add_all([parent, child])
    await db.flush()
    parent.root_id = parent.id
    child.root_id = parent.id
    child.parent_id = parent.id
    import tempfile
    import uuid as _uuid
    from pathlib import Path

    cid = _uuid.uuid4().hex  # qdrant local requires UUID-shaped point ids
    src_path = Path(tempfile.mkdtemp(prefix="carry_")) / "a.pdf"
    src_path.write_bytes(b"%PDF-1.4 carried document bytes")
    doc = Document(
        project_id=parent.id, filename="a.stored", original_filename="a.pdf",
        mime_type="application/pdf", size_bytes=10, checksum="sha-abc",
        storage_path=str(src_path), status=DocumentStatus.READY, chunk_count=1,
        meta={"published_date": "2024-01-01"},
    )
    db.add(doc)
    await db.flush()
    db.add(DocumentChunk(
        id=cid, document_id=doc.id, project_id=parent.id, chunk_index=0,
        text="offline local vector search", point_id=cid,
    ))
    await db.commit()

    vs.upsert_documents([{
        "id": cid, "vector": _fake_vec("offline local vector search"),
        "payload": {"project_id": parent.id, "document_id": doc.id, "chunk_id": cid,
                    "text": "offline local vector search", "filename": "a.pdf"},
    }])

    n = await carry_forward_documents(
        parent_project_id=parent.id, new_project_id=child.id, new_user_id=None,
    )
    assert n == 1

    from app.database import SessionLocal
    async with SessionLocal() as s:
        child_docs = (
            await s.execute(select(Document).where(Document.project_id == child.id))
        ).scalars().all()
    assert len(child_docs) == 1
    assert child_docs[0].status == DocumentStatus.READY
    assert child_docs[0].checksum == "sha-abc"  # unchanged content -> UNCHANGED in a diff
    # The copy owns its OWN physical file (deleting one run's doc can't orphan the other).
    assert child_docs[0].storage_path != str(src_path)
    assert Path(child_docs[0].storage_path).exists()

    # the carried vectors are searchable under the CHILD project (isolation preserved)
    hits = vs.search_documents(
        _fake_vec("offline local vector search"), project_id=child.id,
        limit=5, score_threshold=0.0,
    )
    assert hits
    # ...and NOT leaked as a parent-only concept: the child hit points at the new doc id
    assert hits[0].payload["project_id"] == child.id

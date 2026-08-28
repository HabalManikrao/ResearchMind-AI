import pytest

import app.knowledge.service as ksvc
from app.knowledge import vector_store as vs
from app.models import Claim, ProjectStatus, ResearchProject
from app.models.enums import ClaimStatus
from tests.conftest import FakeProvider


@pytest.fixture
def fake_embeddings(monkeypatch):
    monkeypatch.setattr(ksvc, "get_provider", lambda: FakeProvider())
    # Start from a clean collection so cross-test data doesn't leak.
    client = vs.get_client()
    if client.collection_exists(vs.COLLECTION):
        client.delete_collection(vs.COLLECTION)
    yield


async def _seed_project(db, title, objective, claim_text):
    proj = ResearchProject(title=title, query="q", objective=objective, status=ProjectStatus.COMPLETED)
    db.add(proj)
    await db.flush()
    db.add(Claim(project_id=proj.id, text=claim_text, status=ClaimStatus.VERIFIED,
                 confidence=90, supporting_source_ids=[]))
    await db.commit()
    return proj.id


async def test_index_and_semantic_search_ranks_relevant_first(db, fake_embeddings):
    vec_id = await _seed_project(db, "Vector DB", "choose local vector database qdrant offline",
                                 "Qdrant runs offline")
    await _seed_project(db, "Cooking", "authentic italian pasta recipes", "Pasta needs salt")

    assert await ksvc.index_project(vec_id) >= 2
    # index the cooking one too
    from sqlalchemy import select
    others = (await db.execute(select(ResearchProject))).scalars().all()
    for p in others:
        await ksvc.index_project(p.id)

    results = await ksvc.search("local vector database offline", limit=5)
    assert results
    assert results[0].project_id == vec_id
    assert results[0].score > 0


async def test_related_projects_excludes_self(db, fake_embeddings):
    pid = await _seed_project(db, "Vector DB", "vector database comparison", "claim")
    await ksvc.index_project(pid)
    related = await ksvc.related_projects(pid, limit=5)
    assert all(r.project_id != pid for r in related)


async def test_build_graph_from_relational_data(db, fake_embeddings):
    pid = await _seed_project(db, "Graph", "obj", "an important claim")
    graph = await ksvc.build_graph(pid)
    types = {n["type"] for n in graph["nodes"]}
    assert "project" in types and "claim" in types

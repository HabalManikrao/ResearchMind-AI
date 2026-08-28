"""End-to-end: research over uploaded documents (offline) and hybrid (documents + web).

Documents must become the same ClaimSource evidence a web passage does — this asserts
document-backed claims flow through the P0 evidence engine unchanged.
"""
import asyncio

import pytest

import app.documents.service as svc
import app.knowledge.service as ksvc
import app.orchestration.orchestrator as orch
from tests.conftest import FakeProvider, make_docx_bytes, run_to_completion


@pytest.fixture
def rag_pipeline(monkeypatch):
    """Real document retrieval (local Qdrant + fake embeddings), no network."""
    provider = FakeProvider()
    monkeypatch.setattr(orch, "get_provider", lambda: provider)
    monkeypatch.setattr(orch, "_db_lock", asyncio.Lock())
    monkeypatch.setattr(svc, "get_provider", lambda: provider)
    monkeypatch.setattr(ksvc, "get_provider", lambda: provider)
    return provider


async def _seed_document(pid: str) -> None:
    content = make_docx_bytes(
        [
            ("h", "Architecture"),
            ("p", "The system uses a modular offline pipeline. It supports local documents."),
        ]
    )
    doc, _ = await svc.create_document(
        project_id=pid, user_id=None, original_filename="arch.docx", content=content
    )
    await svc.process_document(doc.id)


async def _create_project(client, sources) -> str:
    r = await client.post(
        "/research",
        json={"query": "how does the architecture work", "sources_enabled": sources,
              "auto_start": False},
    )
    return r.json()["id"]


async def test_documents_only_offline_run(client, rag_pipeline):
    pid = await _create_project(client, ["documents"])
    await _seed_document(pid)
    await client.post(f"/research/{pid}/start")
    await run_to_completion(pid, timeout=20)

    detail = (await client.get(f"/research/{pid}")).json()
    assert detail["status"] == "completed"

    sources = (await client.get(f"/research/{pid}/sources")).json()
    assert any(s["source_type"] == "documents" for s in sources)

    claims = (await client.get(f"/research/{pid}/claims")).json()
    assert claims

    # At least one claim must be backed by document evidence with a quoted passage.
    found = False
    for c in claims:
        ev = (await client.get(f"/research/{pid}/claims/{c['id']}/evidence")).json()
        for item in ev["evidence"]:
            if item["source_type"] == "documents":
                found = True
                assert item["passage"]
    assert found, "no document-backed evidence found on any claim"


async def test_hybrid_documents_plus_web(client, rag_pipeline):
    # Web tasks fail offline (no key), but the run completes and document evidence
    # is still produced — documents + web coexist.
    pid = await _create_project(client, ["documents", "web"])
    await _seed_document(pid)
    await client.post(f"/research/{pid}/start")
    await run_to_completion(pid, timeout=25)

    detail = (await client.get(f"/research/{pid}")).json()
    assert detail["status"] == "completed"
    sources = (await client.get(f"/research/{pid}/sources")).json()
    assert any(s["source_type"] == "documents" for s in sources)

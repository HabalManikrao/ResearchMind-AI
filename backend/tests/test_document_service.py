"""Document service: process → index → retrieve, duplicate dedup, delete, failure."""
import pytest
from sqlalchemy import select

import app.documents.service as svc
from app.database import SessionLocal
from app.models import Document, DocumentChunk, DocumentStatus, ResearchProject
from tests.conftest import FakeProvider, make_docx_bytes


@pytest.fixture
def doc_provider(monkeypatch):
    monkeypatch.setattr(svc, "get_provider", lambda: FakeProvider())


async def _project(db) -> str:
    proj = ResearchProject(title="t", query="q", sources_enabled=["documents"])
    db.add(proj)
    await db.commit()
    await db.refresh(proj)
    return proj.id


async def test_process_document_end_to_end(db, doc_provider):
    pid = await _project(db)
    content = make_docx_bytes(
        [("h", "Architecture"), ("p", "The system uses a modular pipeline that is testable.")]
    )
    doc, dup = await svc.create_document(
        project_id=pid, user_id=None, original_filename="a.docx", content=content
    )
    assert dup is False
    await svc.process_document(doc.id)

    async with SessionLocal() as s:
        d = await s.get(Document, doc.id)
        assert d.status == DocumentStatus.READY
        assert d.chunk_count >= 1
        chunks = (
            await s.execute(select(DocumentChunk).where(DocumentChunk.document_id == doc.id))
        ).scalars().all()
        assert chunks and all(c.point_id for c in chunks)

    hits = await svc.retrieve(pid, "modular pipeline", top_k=5)
    assert hits
    assert any("modular pipeline" in h.text for h in hits)


async def test_duplicate_upload_is_deduped(db, doc_provider):
    pid = await _project(db)
    content = make_docx_bytes([("p", "hello world content")])
    d1, dup1 = await svc.create_document(
        project_id=pid, user_id=None, original_filename="a.docx", content=content
    )
    d2, dup2 = await svc.create_document(
        project_id=pid, user_id=None, original_filename="a-copy.docx", content=content
    )
    assert dup1 is False and dup2 is True
    assert d1.id == d2.id


async def test_project_isolation_in_retrieval(db, doc_provider):
    pid_a = await _project(db)
    pid_b = await _project(db)
    content = make_docx_bytes([("p", "confidential project A material")])
    doc, _ = await svc.create_document(
        project_id=pid_a, user_id=None, original_filename="a.docx", content=content
    )
    await svc.process_document(doc.id)
    # Project B must never retrieve project A's document.
    assert await svc.retrieve(pid_b, "confidential material", top_k=5) == []
    assert await svc.retrieve(pid_a, "confidential material", top_k=5)


async def test_delete_removes_chunks_and_vectors(db, doc_provider):
    pid = await _project(db)
    content = make_docx_bytes([("p", "deletable content here")])
    doc, _ = await svc.create_document(
        project_id=pid, user_id=None, original_filename="a.docx", content=content
    )
    await svc.process_document(doc.id)
    assert await svc.delete_document(doc.id) is True

    async with SessionLocal() as s:
        assert await s.get(Document, doc.id) is None
        chunks = (
            await s.execute(select(DocumentChunk).where(DocumentChunk.document_id == doc.id))
        ).scalars().all()
        assert chunks == []
    assert await svc.retrieve(pid, "deletable content", top_k=5) == []


async def test_corrupt_document_marks_failed(db, doc_provider):
    pid = await _project(db)
    doc, _ = await svc.create_document(
        project_id=pid, user_id=None, original_filename="bad.pdf", content=b"%PDF-1.4 broken bytes",
    )
    await svc.process_document(doc.id)
    async with SessionLocal() as s:
        d = await s.get(Document, doc.id)
        assert d.status == DocumentStatus.FAILED
        assert d.error_message

"""Document capabilities (#8): search + list, reusing the existing document ownership/
storage/retrieval layer. No new ingestion path; upload stays on the security-hardened
internal endpoint (spec §13, §38)."""
from __future__ import annotations

from sqlalchemy import select

from app.capabilities.base import clamp_page, owned_project
from app.database import SessionLocal
from app.documents import service as doc_service
from app.models import Document


async def search(user, project_id: str, query: str, *, top_k: int | None = None) -> dict:
    if not query or not query.strip():
        from app.capabilities.base import CapabilityError, codes

        raise CapabilityError(codes.INVALID_ARGUMENT, "query is required")
    lim, _ = clamp_page(top_k, 0)
    async with SessionLocal() as db:
        await owned_project(db, project_id, user)  # ownership + storage isolation (§38)
    chunks = await doc_service.retrieve(project_id, query.strip(), top_k=lim)
    return {
        "project_id": project_id,
        "passages": [
            {"document_id": c.document_id, "chunk_id": c.chunk_id, "filename": c.filename,
             "text": c.text, "score": round(c.score, 4), "page_number": c.page_number,
             "section": c.section}
            for c in chunks
        ],
    }


async def documents_list(user, project_id: str) -> dict:
    async with SessionLocal() as db:
        await owned_project(db, project_id, user)
        rows = (
            await db.execute(
                select(Document).where(Document.project_id == project_id)
                .order_by(Document.created_at.desc())
            )
        ).scalars().all()
    return {
        "project_id": project_id,
        "documents": [
            {"document_id": d.id, "filename": d.original_filename, "status": d.status.value,
             "page_count": d.page_count, "word_count": d.word_count,
             "chunk_count": d.chunk_count, "error": d.error_message,
             "created_at": d.created_at.isoformat() if d.created_at else None}
            for d in rows
        ],
    }

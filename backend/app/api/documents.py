"""Document RAG endpoints (#3): upload, manage, and search a project's documents.

Every endpoint enforces project ownership (a document is only visible to the owner
of its project). Storage paths are never exposed. Processing runs in the background;
clients poll the status endpoint.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.research import _get_project
from app.database import get_db
from app.documents import service as doc_service
from app.documents.service import DocumentValidationError
from app.models import Document, DocumentChunk, User
from app.schemas.document import (
    DocumentChunkOut,
    DocumentOut,
    DocumentPassageOut,
    DocumentSearchRequest,
    DocumentStatusOut,
)
from app.schemas.research import MessageOut
from app.security.auth import get_current_user
from app.services import audit

router = APIRouter(prefix="/documents", tags=["documents"])


async def _get_owned_document(db: AsyncSession, document_id: str, user: User) -> Document:
    doc = await db.get(Document, document_id)
    if doc is None:
        raise HTTPException(404, "Document not found")
    # Ownership flows through the project (404 for someone else's project).
    await _get_project(db, doc.project_id, user)
    return doc


@router.post("", response_model=DocumentOut, status_code=201)
async def upload_document(
    project_id: str = Form(...),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    await _get_project(db, project_id, user)  # ownership
    content = await file.read()
    try:
        doc, is_duplicate = await doc_service.create_document(
            project_id=project_id,
            user_id=user.id,
            original_filename=file.filename or "document",
            content=content,
        )
    except DocumentValidationError as exc:
        raise HTTPException(exc.status_code, str(exc))
    if not is_duplicate:
        doc_service.start_processing(doc.id)
        await audit.record(
            "document.upload", project_id=project_id, user_id=user.id,
            detail={"filename": doc.original_filename, "size": doc.size_bytes},
        )
    return doc


@router.get("", response_model=list[DocumentOut])
async def list_documents(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    await _get_project(db, project_id, user)
    rows = (
        await db.execute(
            select(Document)
            .where(Document.project_id == project_id)
            .order_by(Document.created_at.desc())
        )
    ).scalars().all()
    return rows


@router.get("/{document_id}", response_model=DocumentOut)
async def get_document(
    document_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return await _get_owned_document(db, document_id, user)


@router.get("/{document_id}/status", response_model=DocumentStatusOut)
async def get_document_status(
    document_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    doc = await _get_owned_document(db, document_id, user)
    return DocumentStatusOut(
        id=doc.id, status=doc.status, chunk_count=doc.chunk_count,
        error_message=doc.error_message,
    )


@router.get("/{document_id}/chunks", response_model=list[DocumentChunkOut])
async def get_document_chunks(
    document_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    await _get_owned_document(db, document_id, user)
    rows = (
        await db.execute(
            select(DocumentChunk)
            .where(DocumentChunk.document_id == document_id)
            .order_by(DocumentChunk.chunk_index)
        )
    ).scalars().all()
    return rows


@router.delete("/{document_id}", response_model=MessageOut)
async def delete_document(
    document_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    await _get_owned_document(db, document_id, user)
    await doc_service.delete_document(document_id)
    await audit.record("document.delete", project_id=None, user_id=user.id,
                       detail={"document_id": document_id})
    return MessageOut(message="Document deleted")


@router.post("/search", response_model=list[DocumentPassageOut])
async def search_documents(
    body: DocumentSearchRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    await _get_project(db, body.project_id, user)
    chunks = await doc_service.retrieve(body.project_id, body.query, top_k=body.top_k)
    return [
        DocumentPassageOut(
            document_id=c.document_id, chunk_id=c.chunk_id, filename=c.filename,
            text=c.text, score=round(c.score, 4), page_number=c.page_number, section=c.section,
        )
        for c in chunks
    ]

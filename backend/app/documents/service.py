"""Document ingestion service: validate → store → parse → chunk → embed → index,
plus retrieval and deletion. Untrusted-input safe and fail-safe.

Processing runs as a background asyncio task; status is tracked in the DB so the
client can poll. Every failure path marks the document FAILED with a message and
cleans up partial vectors rather than corrupting the research database.
"""
from __future__ import annotations

import asyncio
import hashlib
import os
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select

from app.config import get_settings
from app.database import SessionLocal
from app.documents.chunking import chunk_document
from app.documents.parsing import DocumentParseError, parse_document
from app.knowledge import vector_store as vs
from app.llm import get_provider
from app.llm.base import LLMError
from app.models import Document, DocumentChunk, DocumentStatus

settings = get_settings()

# Extension -> canonical MIME. Client-declared MIME is never trusted on its own.
ALLOWED_TYPES = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}
# Magic-byte signatures per extension.
_MAGIC = {
    "pdf": (b"%PDF",),
    "docx": (b"PK\x03\x04",),  # DOCX is a zip container
}


class DocumentValidationError(Exception):
    """Raised on an invalid upload. `status_code` maps to the HTTP response."""

    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass
class RetrievedChunk:
    document_id: str
    chunk_id: str
    text: str
    score: float
    page_number: int | None
    section: str | None
    filename: str
    published_date: str | None


# --------------------------------------------------------------------------- #
# Validation / storage (security-critical)
# --------------------------------------------------------------------------- #
def sanitize_filename(name: str) -> str:
    """Keep only the basename and safe characters — never used as a storage path."""
    base = os.path.basename(name or "").strip().replace("\x00", "")
    base = re.sub(r"[^A-Za-z0-9._ -]+", "_", base)
    base = base.lstrip(".") or "document"
    return base[:255]


def _ext_of(filename: str) -> str:
    return Path(filename).suffix.lower().lstrip(".")


def validate_upload(original_filename: str, size_bytes: int, head: bytes) -> str:
    """Validate extension + size + magic bytes. Returns the canonical extension.
    Raises DocumentValidationError (400/413) otherwise."""
    ext = _ext_of(original_filename)
    if ext not in ALLOWED_TYPES:
        raise DocumentValidationError(
            f"Unsupported file type '.{ext}'. Only PDF and DOCX are accepted.", 400
        )
    max_bytes = settings.max_document_mb * 1024 * 1024
    if size_bytes <= 0:
        raise DocumentValidationError("The uploaded file is empty.", 400)
    if size_bytes > max_bytes:
        raise DocumentValidationError(
            f"File exceeds the {settings.max_document_mb} MB limit.", 413
        )
    if not any(head.startswith(sig) for sig in _MAGIC[ext]):
        raise DocumentValidationError(
            f"File content does not match a valid .{ext} (declared type not trusted).", 400
        )
    return ext


def _storage_dir() -> Path:
    d = Path(settings.document_storage_dir)
    if not d.is_absolute():
        d = (Path(__file__).resolve().parent.parent.parent / settings.document_storage_dir).resolve()
    d.mkdir(parents=True, exist_ok=True)
    return d


def _store_file(content: bytes, ext: str) -> str:
    """Write bytes under a UUID name (client filename never touches the path)."""
    path = _storage_dir() / f"{uuid.uuid4().hex}.{ext}"
    path.write_bytes(content)
    return str(path)


# --------------------------------------------------------------------------- #
# Create + process
# --------------------------------------------------------------------------- #
async def create_document(
    *, project_id: str, user_id: str | None, original_filename: str, content: bytes,
) -> tuple[Document, bool]:
    """Validate + store + persist an UPLOADED document. Returns (document, is_duplicate).
    Duplicate (same checksum in the same project) returns the existing row, no reprocess."""
    ext = validate_upload(original_filename, len(content), content[:8])
    checksum = hashlib.sha256(content).hexdigest()

    async with SessionLocal() as db:
        existing = (
            await db.execute(
                select(Document).where(
                    Document.project_id == project_id, Document.checksum == checksum
                )
            )
        ).scalars().first()
        if existing is not None:
            return existing, True

    storage_path = _store_file(content, ext)
    async with SessionLocal() as db:
        doc = Document(
            project_id=project_id,
            user_id=user_id,
            filename=Path(storage_path).name,
            original_filename=sanitize_filename(original_filename),
            mime_type=ALLOWED_TYPES[ext],
            size_bytes=len(content),
            checksum=checksum,
            storage_path=storage_path,
            status=DocumentStatus.UPLOADED,
        )
        db.add(doc)
        await db.commit()
        await db.refresh(doc)
    return doc, False


def start_processing(document_id: str) -> None:
    """Kick off background processing (fire-and-forget; errors captured in the doc row)."""
    asyncio.create_task(process_document(document_id))


async def _set_status(document_id: str, status: DocumentStatus, *, error: str | None = None) -> None:
    async with SessionLocal() as db:
        doc = await db.get(Document, document_id)
        if doc is None:
            return
        doc.status = status
        if error is not None:
            doc.error_message = error
        await db.commit()


async def _embed_texts(texts: list[str]) -> list[list[float]]:
    provider = get_provider()
    batch = max(1, settings.document_embed_batch)
    vectors: list[list[float]] = []
    for i in range(0, len(texts), batch):
        vectors.extend(await provider.embed(texts[i : i + batch]))
    return vectors


async def process_document(document_id: str) -> None:
    """Parse → chunk → embed → index a document. Fail-safe: any error marks the
    document FAILED (with a message) and removes any partial vectors."""
    async with SessionLocal() as db:
        doc = await db.get(Document, document_id)
        if doc is None:
            return
        storage_path, ext = doc.storage_path, _ext_of(doc.original_filename)
        project_id = doc.project_id

    try:
        await _set_status(document_id, DocumentStatus.PARSING)
        parsed = parse_document(storage_path, ext)

        await _set_status(document_id, DocumentStatus.CHUNKING)
        chunks = chunk_document(
            parsed,
            target_tokens=settings.document_chunk_tokens,
            overlap_tokens=settings.document_chunk_overlap_tokens,
        )
        if not chunks:
            await _set_status(
                document_id, DocumentStatus.FAILED, error="No text chunks could be produced."
            )
            return

        await _set_status(document_id, DocumentStatus.EMBEDDING)
        try:
            vectors = await _embed_texts([c.text for c in chunks])
        except LLMError as exc:
            await _set_status(
                document_id, DocumentStatus.FAILED,
                error=f"Embedding failed (is the embedding model available?): {exc}",
            )
            return
        if not vectors or not vectors[0]:
            await _set_status(document_id, DocumentStatus.FAILED, error="No embeddings returned.")
            return

        await _set_status(document_id, DocumentStatus.INDEXING)
        published_date = parsed.meta.get("published_date")
        original_filename = Path(storage_path).name  # placeholder; overwritten below
        async with SessionLocal() as db:
            doc = await db.get(Document, document_id)
            original_filename = doc.original_filename
        points: list[dict] = []
        rows: list[DocumentChunk] = []
        for c, vec in zip(chunks, vectors):
            chunk_id = uuid.uuid4().hex
            rows.append(
                DocumentChunk(
                    id=chunk_id,
                    document_id=document_id,
                    project_id=project_id,
                    chunk_index=c.chunk_index,
                    text=c.text,
                    page_number=c.page_number,
                    section=c.section,
                    char_start=c.char_start,
                    char_end=c.char_end,
                    token_count=c.token_count,
                    point_id=chunk_id,
                )
            )
            points.append(
                {
                    "id": chunk_id,
                    "vector": vec,
                    "payload": {
                        "project_id": project_id,
                        "document_id": document_id,
                        "chunk_id": chunk_id,
                        "chunk_index": c.chunk_index,
                        "page_number": c.page_number,
                        "section": c.section,
                        "filename": original_filename,
                        "text": c.text,
                        "published_date": published_date,
                    },
                }
            )
        vs.upsert_documents(points)

        async with SessionLocal() as db:
            for row in rows:
                db.add(row)
            doc = await db.get(Document, document_id)
            if doc is not None:
                doc.status = DocumentStatus.READY
                doc.page_count = parsed.page_count
                doc.word_count = parsed.word_count
                doc.chunk_count = len(rows)
                doc.processed_at = datetime.now(timezone.utc)
                doc.error_message = None
                meta = dict(doc.meta or {})
                meta.update(parsed.meta)
                doc.meta = meta
            await db.commit()
    except DocumentParseError as exc:
        await _set_status(document_id, DocumentStatus.FAILED, error=str(exc))
        vs.delete_document_vectors(document_id)
    except Exception as exc:  # noqa: BLE001 - never let processing corrupt the DB
        await _set_status(
            document_id, DocumentStatus.FAILED, error=f"Processing error: {exc}"
        )
        vs.delete_document_vectors(document_id)


# --------------------------------------------------------------------------- #
# Retrieval + deletion
# --------------------------------------------------------------------------- #
async def retrieve(
    project_id: str,
    query: str,
    *,
    top_k: int | None = None,
    min_score: float | None = None,
    document_id: str | None = None,
) -> list[RetrievedChunk]:
    top_k = top_k or settings.document_retrieval_top_k
    threshold = settings.document_retrieval_min_score if min_score is None else min_score
    try:
        vector = (await get_provider().embed([query]))[0]
    except LLMError:
        return []
    hits = vs.search_documents(
        vector, project_id=project_id, document_id=document_id,
        limit=top_k, score_threshold=threshold,
    )
    out: list[RetrievedChunk] = []
    for h in hits:
        p = h.payload
        out.append(
            RetrievedChunk(
                document_id=p.get("document_id", ""),
                chunk_id=p.get("chunk_id", h.id),
                text=p.get("text", ""),
                score=h.score,
                page_number=p.get("page_number"),
                section=p.get("section"),
                filename=p.get("filename", "document"),
                published_date=p.get("published_date"),
            )
        )
    return out


async def carry_forward_documents(
    *, parent_project_id: str, new_project_id: str, new_user_id: str | None,
) -> int:
    """Copy a parent run's READY documents into a continuation run (Research Again, #4).

    Reuses the parent's on-disk file (checksum dedup guarantees it exists) and copies
    each chunk's vector WITHOUT re-embedding (``vs.copy_document_vectors``), re-pointed
    under the new project_id so retrieval isolation still holds. Best-effort: returns
    the number of documents carried; a vector-copy failure leaves the doc rows in place
    (retrieval simply finds nothing for it) and never raises into the run.
    """
    async with SessionLocal() as db:
        parent_docs = (
            await db.execute(
                select(Document).where(
                    Document.project_id == parent_project_id,
                    Document.status == DocumentStatus.READY,
                )
            )
        ).scalars().all()
        if not parent_docs:
            return 0
        parent_ids = [d.id for d in parent_docs]
        chunks = (
            await db.execute(
                select(DocumentChunk).where(DocumentChunk.document_id.in_(parent_ids))
            )
        ).scalars().all()

    chunks_by_doc: dict[str, list[DocumentChunk]] = {}
    for ch in chunks:
        chunks_by_doc.setdefault(ch.document_id, []).append(ch)

    carried = 0
    for src_doc in parent_docs:
        new_doc_id = uuid.uuid4().hex
        # Give the copy its OWN physical file so deleting either run's document never
        # orphans the other (delete_document os.remove()s the storage_path).
        try:
            content = Path(src_doc.storage_path).read_bytes()
            new_storage_path = _store_file(content, _ext_of(src_doc.original_filename))
        except OSError:
            continue  # parent file missing -> skip this doc (best-effort)
        vector_map: list[dict] = []
        new_rows: list[DocumentChunk] = []
        for ch in chunks_by_doc.get(src_doc.id, []):
            new_chunk_id = uuid.uuid4().hex
            new_rows.append(
                DocumentChunk(
                    id=new_chunk_id,
                    document_id=new_doc_id,
                    project_id=new_project_id,
                    chunk_index=ch.chunk_index,
                    text=ch.text,
                    page_number=ch.page_number,
                    section=ch.section,
                    char_start=ch.char_start,
                    char_end=ch.char_end,
                    token_count=ch.token_count,
                    point_id=new_chunk_id,
                    meta=dict(ch.meta or {}),
                )
            )
            if ch.point_id:
                vector_map.append(
                    {
                        "old_point_id": ch.point_id,
                        "new_point_id": new_chunk_id,
                        "payload": {
                            "project_id": new_project_id,
                            "document_id": new_doc_id,
                            "chunk_id": new_chunk_id,
                            "chunk_index": ch.chunk_index,
                            "page_number": ch.page_number,
                            "section": ch.section,
                            "filename": src_doc.original_filename,
                            "text": ch.text,
                            "published_date": (src_doc.meta or {}).get("published_date"),
                        },
                    }
                )
        try:
            copied = vs.copy_document_vectors(vector_map)
        except Exception:  # noqa: BLE001 - carry-forward is best-effort, never fatal
            copied = 0

        async with SessionLocal() as db:
            db.add(
                Document(
                    id=new_doc_id,
                    project_id=new_project_id,
                    user_id=new_user_id,
                    filename=src_doc.filename,
                    original_filename=src_doc.original_filename,
                    mime_type=src_doc.mime_type,
                    size_bytes=src_doc.size_bytes,
                    checksum=src_doc.checksum,  # same content → unchanged in the document diff
                    storage_path=new_storage_path,
                    status=DocumentStatus.READY if copied else DocumentStatus.FAILED,
                    page_count=src_doc.page_count,
                    word_count=src_doc.word_count,
                    chunk_count=len(new_rows) if copied else 0,
                    processed_at=src_doc.processed_at,
                    error_message=None if copied else "Vector carry-forward failed.",
                    meta=dict(src_doc.meta or {}),
                )
            )
            if copied:
                for row in new_rows:
                    db.add(row)
            await db.commit()
        carried += 1 if copied else 0
    return carried


async def delete_document(document_id: str) -> bool:
    async with SessionLocal() as db:
        doc = await db.get(Document, document_id)
        if doc is None:
            return False
        storage_path = doc.storage_path
    vs.delete_document_vectors(document_id)
    async with SessionLocal() as db:
        # Remove chunk rows then the document (passive_deletes avoids async lazy-load).
        from sqlalchemy import delete as sa_delete

        await db.execute(sa_delete(DocumentChunk).where(DocumentChunk.document_id == document_id))
        doc = await db.get(Document, document_id)
        if doc is not None:
            await db.delete(doc)
        await db.commit()
    try:
        if storage_path and os.path.exists(storage_path):
            os.remove(storage_path)
    except OSError:
        pass
    return True

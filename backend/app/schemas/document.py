"""Request/response schemas for Document RAG. Storage paths are never exposed."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import DocumentStatus


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class DocumentOut(ORMModel):
    id: str
    project_id: str
    original_filename: str
    mime_type: str
    size_bytes: int
    status: DocumentStatus
    page_count: int
    word_count: int
    chunk_count: int
    error_message: str | None
    processed_at: datetime | None
    created_at: datetime
    meta: dict


class DocumentStatusOut(BaseModel):
    id: str
    status: DocumentStatus
    chunk_count: int
    error_message: str | None = None


class DocumentChunkOut(ORMModel):
    id: str
    chunk_index: int
    text: str
    page_number: int | None
    section: str | None
    token_count: int


class DocumentSearchRequest(BaseModel):
    project_id: str
    query: str = Field(min_length=1)
    top_k: int | None = Field(default=None, ge=1, le=20)


class DocumentPassageOut(BaseModel):
    document_id: str
    chunk_id: str
    filename: str
    text: str
    score: float
    page_number: int | None = None
    section: str | None = None

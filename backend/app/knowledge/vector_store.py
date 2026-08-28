"""Thin wrapper over Qdrant (embedded local mode).

A single process-wide client persists to `settings.qdrant_path`. Local mode holds a
file lock, so we keep exactly one client instance. The collection is created lazily
on first upsert once the embedding dimension is known.
"""
from __future__ import annotations

from dataclasses import dataclass

from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchValue,
    PointStruct,
    VectorParams,
)

from app.config import get_settings

COLLECTION = "knowledge"
# Separate collection for document chunks: different granularity (chunk vs project
# summary), payload, and delete lifecycle than the `knowledge` collection. Reuses the
# same embedded client + embedding model.
DOCUMENTS_COLLECTION = "documents"

_client: QdrantClient | None = None


def get_client() -> QdrantClient:
    global _client
    if _client is None:
        _client = QdrantClient(path=get_settings().qdrant_path)
    return _client


@dataclass
class VectorHit:
    id: str
    score: float
    payload: dict


def ensure_collection(dim: int) -> None:
    client = get_client()
    if not client.collection_exists(COLLECTION):
        client.create_collection(
            COLLECTION,
            vectors_config=VectorParams(size=dim, distance=Distance.COSINE),
        )


def upsert(points: list[dict]) -> None:
    """points: [{id, vector, payload}]."""
    if not points:
        return
    ensure_collection(len(points[0]["vector"]))
    get_client().upsert(
        COLLECTION,
        points=[
            PointStruct(id=p["id"], vector=p["vector"], payload=p["payload"])
            for p in points
        ],
    )


def delete_by_project(project_id: str) -> None:
    client = get_client()
    if not client.collection_exists(COLLECTION):
        return
    client.delete(
        COLLECTION,
        points_selector=Filter(
            must=[FieldCondition(key="project_id", match=MatchValue(value=project_id))]
        ),
    )


def search(
    vector: list[float], *, limit: int = 10, exclude_project: str | None = None
) -> list[VectorHit]:
    client = get_client()
    if not client.collection_exists(COLLECTION):
        return []
    query_filter = None
    if exclude_project:
        query_filter = Filter(
            must_not=[
                FieldCondition(
                    key="project_id", match=MatchValue(value=exclude_project)
                )
            ]
        )
    result = client.query_points(
        COLLECTION, query=vector, limit=limit, query_filter=query_filter
    ).points
    return [VectorHit(id=str(p.id), score=float(p.score), payload=p.payload or {}) for p in result]


# --------------------------------------------------------------------------- #
# Document chunk vectors (Document RAG). Separate collection, project-isolated.
# --------------------------------------------------------------------------- #
def ensure_documents_collection(dim: int) -> None:
    client = get_client()
    if not client.collection_exists(DOCUMENTS_COLLECTION):
        client.create_collection(
            DOCUMENTS_COLLECTION,
            vectors_config=VectorParams(size=dim, distance=Distance.COSINE),
        )


def upsert_documents(points: list[dict]) -> None:
    """points: [{id, vector, payload}] where payload carries project_id/document_id/chunk_id."""
    if not points:
        return
    ensure_documents_collection(len(points[0]["vector"]))
    get_client().upsert(
        DOCUMENTS_COLLECTION,
        points=[
            PointStruct(id=p["id"], vector=p["vector"], payload=p["payload"])
            for p in points
        ],
    )


def search_documents(
    vector: list[float],
    *,
    project_id: str,
    document_id: str | None = None,
    limit: int = 5,
    score_threshold: float | None = None,
) -> list[VectorHit]:
    """Semantic search over document chunks, HARD-filtered by project_id so a
    document in one project can never surface in another."""
    client = get_client()
    if not client.collection_exists(DOCUMENTS_COLLECTION):
        return []
    must = [FieldCondition(key="project_id", match=MatchValue(value=project_id))]
    if document_id:
        must.append(FieldCondition(key="document_id", match=MatchValue(value=document_id)))
    result = client.query_points(
        DOCUMENTS_COLLECTION,
        query=vector,
        limit=limit,
        query_filter=Filter(must=must),
        score_threshold=score_threshold,
    ).points
    return [VectorHit(id=str(p.id), score=float(p.score), payload=p.payload or {}) for p in result]


def delete_document_vectors(document_id: str) -> None:
    client = get_client()
    if not client.collection_exists(DOCUMENTS_COLLECTION):
        return
    client.delete(
        DOCUMENTS_COLLECTION,
        points_selector=Filter(
            must=[FieldCondition(key="document_id", match=MatchValue(value=document_id))]
        ),
    )


def delete_project_documents(project_id: str) -> None:
    client = get_client()
    if not client.collection_exists(DOCUMENTS_COLLECTION):
        return
    client.delete(
        DOCUMENTS_COLLECTION,
        points_selector=Filter(
            must=[FieldCondition(key="project_id", match=MatchValue(value=project_id))]
        ),
    )


__all__ = [
    "COLLECTION",
    "DOCUMENTS_COLLECTION",
    "VectorHit",
    "ensure_collection",
    "upsert",
    "delete_by_project",
    "search",
    "get_client",
    "ensure_documents_collection",
    "upsert_documents",
    "search_documents",
    "delete_document_vectors",
    "delete_project_documents",
]

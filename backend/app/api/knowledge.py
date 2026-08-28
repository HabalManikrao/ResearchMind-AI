"""Knowledge base API (spec §14, §15).

Semantic search over prior research via the vector store, with a graceful keyword
fallback when embeddings are unavailable. Also exposes related-research lookup, a
per-project knowledge graph, and a reindex utility.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.knowledge import service as knowledge
from app.knowledge.service import KnowledgeUnavailable
from app.llm import get_provider
from app.models import ProjectStatus, ResearchProject, User
from app.schemas.research import (
    GraphOut,
    KnowledgeSearchOut,
    KnowledgeStatusOut,
    MessageOut,
)
from app.security.auth import get_current_user

router = APIRouter(
    prefix="/knowledge", tags=["knowledge"], dependencies=[Depends(get_current_user)]
)


async def _keyword_fallback(q: str, db: AsyncSession, completed_only: bool) -> list[KnowledgeSearchOut]:
    like = f"%{q}%"
    conds = [
        ResearchProject.title.ilike(like),
        ResearchProject.query.ilike(like),
        ResearchProject.objective.ilike(like),
    ]
    stmt = select(ResearchProject).where(or_(*conds))
    if completed_only:
        stmt = stmt.where(ResearchProject.status == ProjectStatus.COMPLETED)
    rows = (
        await db.execute(stmt.order_by(ResearchProject.created_at.desc()).limit(25))
    ).scalars().all()
    return [
        KnowledgeSearchOut(
            project_id=r.id, title=r.title, snippet=r.objective or r.query, matches=1
        )
        for r in rows
    ]


@router.get("/status", response_model=KnowledgeStatusOut)
async def knowledge_status():
    s = get_settings()
    semantic = False
    if s.knowledge_enabled:
        provider = get_provider()
        # embeddings_available exists on OllamaProvider; guard for other providers.
        check = getattr(provider, "embeddings_available", None)
        semantic = await check() if check else False
    return KnowledgeStatusOut(
        enabled=s.knowledge_enabled, semantic=semantic, embedding_model=s.embedding_model
    )


@router.get("/search", response_model=list[KnowledgeSearchOut])
async def search_knowledge(
    q: str = Query(min_length=2), db: AsyncSession = Depends(get_db)
):
    if get_settings().knowledge_enabled:
        try:
            results = await knowledge.search(q, limit=15)
            return [
                KnowledgeSearchOut(
                    project_id=r.project_id, title=r.title, score=r.score,
                    snippet=r.snippet, matches=r.matches,
                )
                for r in results
            ]
        except KnowledgeUnavailable:
            pass  # fall back to keyword
    return await _keyword_fallback(q, db, completed_only=False)


@router.get("/related", response_model=list[KnowledgeSearchOut])
async def related_research(
    q: str = Query(min_length=2), db: AsyncSession = Depends(get_db)
):
    if get_settings().knowledge_enabled:
        try:
            results = await knowledge.search(q, limit=10)
            return [
                KnowledgeSearchOut(
                    project_id=r.project_id, title=r.title, score=r.score,
                    snippet=r.snippet, matches=r.matches,
                )
                for r in results
            ]
        except KnowledgeUnavailable:
            pass
    return await _keyword_fallback(q, db, completed_only=True)


@router.get("/graph/{project_id}", response_model=GraphOut)
async def knowledge_graph(project_id: str, db: AsyncSession = Depends(get_db)):
    proj = await db.get(ResearchProject, project_id)
    if proj is None:
        raise HTTPException(404, "Research project not found")
    return await knowledge.build_graph(project_id)


@router.post("/reindex", response_model=MessageOut)
async def reindex(db: AsyncSession = Depends(get_db)):
    """(Re)index all completed projects into the vector store."""
    if not get_settings().knowledge_enabled:
        raise HTTPException(409, "Knowledge base is disabled")
    rows = (
        await db.execute(
            select(ResearchProject).where(
                ResearchProject.status == ProjectStatus.COMPLETED
            )
        )
    ).scalars().all()
    total = 0
    try:
        for r in rows:
            total += await knowledge.index_project(r.id)
    except KnowledgeUnavailable as exc:
        raise HTTPException(
            503, f"Embeddings unavailable — pull the embedding model first. ({exc})"
        )
    return MessageOut(message=f"Indexed {total} item(s) from {len(rows)} project(s)")

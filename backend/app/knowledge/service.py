"""Knowledge base operations: index completed research, semantic search, find
related prior research, and build a per-project knowledge graph.

All embedding-dependent calls raise KnowledgeUnavailable when the embedding model
isn't reachable, so callers can fall back to keyword search (spec §14 reuse, §15 graph).
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import select

from app.database import SessionLocal
from app.knowledge import vector_store as vs
from app.llm import get_provider
from app.llm.base import LLMError
from app.models import (
    Claim,
    Recommendation,
    ResearchProject,
    Solution,
    Source,
)

_NS = uuid.UUID("6f1b8e2a-0000-4000-8000-000000000001")  # stable namespace for point ids


class KnowledgeUnavailable(RuntimeError):
    """Raised when embeddings are not available (e.g. embedding model not pulled)."""


def _point_id(project_id: str, kind: str, key: str) -> str:
    return str(uuid.uuid5(_NS, f"{project_id}:{kind}:{key}"))


@dataclass
class SearchResult:
    project_id: str
    title: str
    score: float
    snippet: str
    matches: int


async def _embed(texts: list[str]) -> list[list[float]]:
    try:
        vectors = await get_provider().embed(texts)
    except LLMError as exc:
        raise KnowledgeUnavailable(str(exc)) from exc
    if not vectors or not vectors[0]:
        raise KnowledgeUnavailable("Embedding model returned no vectors")
    return vectors


async def index_project(project_id: str) -> int:
    """Embed and upsert a completed project's reusable knowledge (objective, claims,
    recommendation). Returns the number of items indexed."""
    async with SessionLocal() as db:
        proj = await db.get(ResearchProject, project_id)
        if proj is None:
            return 0
        claims = (
            await db.execute(select(Claim).where(Claim.project_id == project_id))
        ).scalars().all()
        rec = (
            await db.execute(
                select(Recommendation).where(Recommendation.project_id == project_id)
            )
        ).scalars().first()

    title = proj.title
    items: list[tuple[str, str, str]] = []  # (kind, key, text)
    items.append(("objective", "0", proj.objective or proj.query))
    for i, c in enumerate(claims):
        items.append(("claim", str(i), c.text))
    if rec and rec.recommended_option:
        items.append(
            ("recommendation", "0", f"{rec.recommended_option}: {rec.rationale}")
        )

    texts = [t for _, _, t in items if t.strip()]
    if not texts:
        return 0
    vectors = await _embed(texts)

    points = []
    vi = 0
    for kind, key, text in items:
        if not text.strip():
            continue
        points.append(
            {
                "id": _point_id(project_id, kind, key),
                "vector": vectors[vi],
                "payload": {
                    "project_id": project_id,
                    "project_title": title,
                    "kind": kind,
                    "text": text,
                },
            }
        )
        vi += 1

    vs.delete_by_project(project_id)  # replace prior index for this project
    vs.upsert(points)
    return len(points)


def _group_hits(hits: list[vs.VectorHit]) -> list[SearchResult]:
    grouped: dict[str, dict] = {}
    for h in hits:
        pid = h.payload.get("project_id")
        if not pid:
            continue
        g = grouped.setdefault(
            pid,
            {"title": h.payload.get("project_title", "Untitled"), "score": 0.0, "snippet": "", "matches": 0},
        )
        g["matches"] += 1
        if h.score > g["score"]:
            g["score"] = h.score
            g["snippet"] = h.payload.get("text", "")
    return [
        SearchResult(project_id=pid, title=g["title"], score=round(g["score"], 3),
                     snippet=g["snippet"], matches=g["matches"])
        for pid, g in sorted(grouped.items(), key=lambda kv: kv[1]["score"], reverse=True)
    ]


async def search(query: str, *, limit: int = 10, exclude_project: str | None = None) -> list[SearchResult]:
    vector = (await _embed([query]))[0]
    hits = vs.search(vector, limit=limit * 3, exclude_project=exclude_project)
    return _group_hits(hits)[:limit]


async def related_projects(project_id: str, *, limit: int = 5) -> list[SearchResult]:
    async with SessionLocal() as db:
        proj = await db.get(ResearchProject, project_id)
        if proj is None:
            return []
        query = proj.objective or proj.query
    return await search(query, limit=limit, exclude_project=project_id)


# --------------------------------------------------------------------------- #
# Knowledge graph (spec §15) — derived from the relational data, no vectors.
# --------------------------------------------------------------------------- #
async def build_graph(project_id: str) -> dict:
    async with SessionLocal() as db:
        proj = await db.get(ResearchProject, project_id)
        if proj is None:
            return {"nodes": [], "edges": []}
        solutions = (
            await db.execute(select(Solution).where(Solution.project_id == project_id))
        ).scalars().all()
        claims = (
            await db.execute(select(Claim).where(Claim.project_id == project_id))
        ).scalars().all()
        sources = (
            await db.execute(select(Source).where(Source.project_id == project_id))
        ).scalars().all()
        rec = (
            await db.execute(
                select(Recommendation).where(Recommendation.project_id == project_id)
            )
        ).scalars().first()

    nodes: list[dict] = []
    edges: list[dict] = []
    src_by_id = {s.id: s for s in sources}

    root = f"project:{project_id}"
    nodes.append({"id": root, "label": proj.title, "type": "project"})

    # Solutions (technologies/approaches) considered.
    for s in solutions:
        nid = f"solution:{s.id}"
        nodes.append({"id": nid, "label": s.name, "type": "solution", "recommended": s.is_recommended})
        edges.append({"source": root, "target": nid, "label": "considers"})

    # Recommendation / decision.
    if rec and rec.recommended_option:
        rid = f"rec:{rec.id}"
        nodes.append({"id": rid, "label": rec.recommended_option, "type": "recommendation"})
        edges.append({"source": root, "target": rid, "label": "recommends"})
        for s in solutions:
            if s.is_recommended:
                edges.append({"source": f"solution:{s.id}", "target": rid, "label": "chosen"})

    # Top claims (by confidence) and their supporting sources.
    top_claims = sorted(claims, key=lambda c: c.confidence, reverse=True)[:6]
    seen_sources: set[str] = set()
    for c in top_claims:
        cid = f"claim:{c.id}"
        label = (c.text[:60] + "…") if len(c.text) > 60 else c.text
        nodes.append({"id": cid, "label": label, "type": "claim", "status": c.status.value})
        edges.append({"source": root, "target": cid, "label": "found"})
        for sid in (c.supporting_source_ids or [])[:3]:
            src = src_by_id.get(sid)
            if not src:
                continue
            snid = f"source:{sid}"
            if sid not in seen_sources:
                nodes.append({"id": snid, "label": src.title[:50], "type": "source", "source_type": src.source_type})
                seen_sources.add(sid)
            edges.append({"source": cid, "target": snid, "label": "supported by"})

    return {"nodes": nodes, "edges": edges}

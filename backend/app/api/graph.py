"""Knowledge Graph API (#7). Ownership-enforced, bounded, paginated (spec §23, §24, §30, §33).

All reads are user-scoped: a user sees only entities/relationships they own or legacy/unowned
ones (``user_id IS NULL``) — the same rule the rest of the app uses. Depth and result sizes
are hard-bounded; no unbounded recursion.
"""
from __future__ import annotations

from sqlalchemy import String, and_, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.research import _get_project
from app.config import get_settings
from app.database import get_db
from app.knowledge import graph as kg_graph
from app.models import (
    Claim,
    KgClaimLink,
    KgEntity,
    KgMention,
    KgRelationship,
    ResearchProject,
    Source,
    User,
)
from app.schemas.graph import (
    EntityClaim,
    EntityDetail,
    EntityGraph,
    EntityHistory,
    EntityHistoryItem,
    EntityOut,
    EntitySourceRef,
    EntitySummary,
    RelatedEntity,
    RelationshipOut,
)
from app.schemas.research import MessageOut
from app.security.auth import get_current_user

router = APIRouter(prefix="/knowledge", tags=["knowledge-graph"])


def _owned(model, user: User):
    """Rows the user may see: their own OR legacy/unowned (user_id IS NULL)."""
    return or_(model.user_id == user.id, model.user_id.is_(None))


async def _get_entity(db: AsyncSession, entity_id: str, user: User) -> KgEntity:
    ent = await db.get(KgEntity, entity_id)
    # 404 (not 403) for another user's entity so existence isn't leaked (spec §24).
    if ent is None or (ent.user_id is not None and ent.user_id != user.id):
        raise HTTPException(404, "Entity not found")
    return ent


def _summary(e: KgEntity) -> EntitySummary:
    return EntitySummary(
        id=e.id, canonical_name=e.canonical_name, entity_type=e.entity_type,
        mention_count=e.mention_count,
    )


# --------------------------------------------------------------------------- #
# Entity search / list
# --------------------------------------------------------------------------- #
@router.get("/entities", response_model=list[EntitySummary])
async def list_entities(
    q: str | None = Query(None),
    type: str | None = Query(None),
    limit: int = Query(None),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    s = get_settings()
    # Floor at 1 so a negative limit can't become an unbounded SQLite query (spec §26/§49).
    page = min(max(int(limit) if limit else s.kg_page_size, 1), s.kg_max_page_size)
    stmt = select(KgEntity).where(_owned(KgEntity, user))
    if type:
        stmt = stmt.where(KgEntity.entity_type == type.strip().lower())
    if q and q.strip():
        needle = f"%{q.strip().lower()}%"
        stmt = stmt.where(
            or_(
                func.lower(KgEntity.canonical_name).like(needle),
                KgEntity.normalized_name.like(f"%{kg_graph.normalize_name(q)}%"),
                func.lower(cast(KgEntity.aliases, String)).like(needle),
            )
        )
    stmt = stmt.order_by(
        KgEntity.mention_count.desc(), KgEntity.canonical_name.asc(), KgEntity.id.asc()
    ).offset(offset).limit(page)
    rows = (await db.execute(stmt)).scalars().all()
    return [_summary(e) for e in rows]


# --------------------------------------------------------------------------- #
# Entity detail
# --------------------------------------------------------------------------- #
@router.get("/entities/{entity_id}", response_model=EntityDetail)
async def get_entity(
    entity_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    ent = await _get_entity(db, entity_id, user)
    related = await _related_entities(db, ent, user)

    # Counts (bounded aggregate queries — no N+1).
    claim_ids = await _entity_claim_ids(db, ent, user)
    superseded = await kg_graph.superseded_claim_ids(db, user.id if user else None)
    current = sum(1 for cid in claim_ids if cid not in superseded)
    historical = len(claim_ids) - current
    source_count = (
        await db.execute(
            select(func.count(func.distinct(KgMention.target_id)))
            .where(KgMention.entity_id == ent.id, KgMention.target_type == "source")
        )
    ).scalar() or 0
    run_count = (
        await db.execute(
            select(func.count(func.distinct(KgMention.target_id)))
            .where(KgMention.entity_id == ent.id, KgMention.target_type == "project")
        )
    ).scalar() or 0

    return EntityDetail(
        entity=EntityOut.model_validate(ent),
        related=related,
        current_claims=current,
        historical_claims=historical,
        source_count=int(source_count),
        run_count=int(run_count),
    )


async def _related_entities(db, ent: KgEntity, user: User) -> list[RelatedEntity]:
    rels = (
        await db.execute(
            select(KgRelationship).where(
                _owned(KgRelationship, user),
                or_(
                    KgRelationship.subject_entity_id == ent.id,
                    KgRelationship.object_entity_id == ent.id,
                ),
            ).order_by(KgRelationship.confidence.desc()).limit(200)
        )
    ).scalars().all()
    neighbour_ids = {
        (r.object_entity_id if r.subject_entity_id == ent.id else r.subject_entity_id)
        for r in rels
    }
    neighbours = await _load_entities(db, neighbour_ids)
    out: list[RelatedEntity] = []
    for r in rels:
        if r.subject_entity_id == ent.id:
            nid, direction = r.object_entity_id, "out"
        else:
            nid, direction = r.subject_entity_id, "in"
        n = neighbours.get(nid)
        if n is None:
            continue
        out.append(RelatedEntity(
            relationship_id=r.id, predicate=r.predicate, direction=direction,
            confidence=r.confidence, provenance_kind=r.provenance_kind, status=r.status,
            entity=_summary(n),
        ))
    return out


async def _load_entities(db, ids: set[str]) -> dict[str, KgEntity]:
    if not ids:
        return {}
    rows = (
        await db.execute(select(KgEntity).where(KgEntity.id.in_(list(ids))))
    ).scalars().all()
    return {e.id: e for e in rows}


async def _entity_claim_ids(db, ent: KgEntity, user: User) -> list[str]:
    rows = (
        await db.execute(
            select(KgMention.target_id)
            .where(KgMention.entity_id == ent.id, KgMention.target_type == "claim")
        )
    ).all()
    return [r[0] for r in rows]


# --------------------------------------------------------------------------- #
# Entity claims (current vs historical) — spec §13
# --------------------------------------------------------------------------- #
@router.get("/entities/{entity_id}/claims", response_model=list[EntityClaim])
async def get_entity_claims(
    entity_id: str,
    scope: str = Query("all", pattern="^(current|historical|all)$"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    ent = await _get_entity(db, entity_id, user)
    claim_ids = await _entity_claim_ids(db, ent, user)
    if not claim_ids:
        return []
    superseded = await kg_graph.superseded_claim_ids(db, user.id if user else None)

    claims = (
        await db.execute(select(Claim).where(Claim.id.in_(claim_ids)))
    ).scalars().all()
    # Batch-load owning projects for run_number + ownership double-check (no N+1).
    proj_ids = {c.project_id for c in claims}
    projects = {
        p.id: p for p in (
            await db.execute(select(ResearchProject).where(ResearchProject.id.in_(proj_ids)))
        ).scalars().all()
    }

    out: list[EntityClaim] = []
    for c in claims:
        proj = projects.get(c.project_id)
        if proj is None or (proj.user_id is not None and proj.user_id != user.id):
            continue  # defensive: never surface a claim from another user's project
        is_hist = c.id in superseded
        if scope == "current" and is_hist:
            continue
        if scope == "historical" and not is_hist:
            continue
        out.append(EntityClaim(
            claim_id=c.id, text=c.text, status=c.status.value, confidence=c.confidence,
            evidence_state=c.evidence_state, project_id=c.project_id,
            run_number=proj.run_number or 1, disputed=kg_graph.claim_is_disputed(c),
            superseded=is_hist,
        ))
    # Newest run first, then highest confidence.
    out.sort(key=lambda x: (-x.run_number, -x.confidence))
    return out


# --------------------------------------------------------------------------- #
# Entity neighborhood graph (bounded depth) — spec §23, §33
# --------------------------------------------------------------------------- #
@router.get("/entities/{entity_id}/graph", response_model=EntityGraph)
async def get_entity_graph(
    entity_id: str,
    depth: int = Query(1, ge=1),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    s = get_settings()
    depth = min(depth, s.kg_max_graph_depth)  # hard clamp (§23)
    ent = await _get_entity(db, entity_id, user)

    node_ids: set[str] = {ent.id}
    edges: dict[str, KgRelationship] = {}
    frontier = {ent.id}
    truncated = False
    for _ in range(depth):
        if not frontier:
            break
        rels = (
            await db.execute(
                select(KgRelationship).where(
                    _owned(KgRelationship, user),
                    or_(
                        KgRelationship.subject_entity_id.in_(list(frontier)),
                        KgRelationship.object_entity_id.in_(list(frontier)),
                    ),
                ).limit(s.kg_max_graph_nodes * 4)
            )
        ).scalars().all()
        next_frontier: set[str] = set()
        for r in rels:
            edges[r.id] = r
            for nid in (r.subject_entity_id, r.object_entity_id):
                if nid not in node_ids:
                    if len(node_ids) >= s.kg_max_graph_nodes:
                        truncated = True
                        continue
                    node_ids.add(nid)
                    next_frontier.add(nid)
        frontier = next_frontier

    entities = await _load_entities(db, node_ids)
    return EntityGraph(
        root_id=ent.id, depth=depth,
        nodes=[_summary(e) for e in entities.values()],
        edges=[RelationshipOut.model_validate(r) for r in edges.values()],
        truncated=truncated,
    )


# --------------------------------------------------------------------------- #
# Entity history (observations + supersessions) — spec §13, §15
# --------------------------------------------------------------------------- #
@router.get("/entities/{entity_id}/history", response_model=EntityHistory)
async def get_entity_history(
    entity_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    ent = await _get_entity(db, entity_id, user)
    items: list[EntityHistoryItem] = []

    # When this entity was observed in each run.
    run_mentions = (
        await db.execute(
            select(KgMention).where(
                KgMention.entity_id == ent.id, KgMention.target_type == "project"
            )
        )
    ).scalars().all()
    proj_ids = {m.target_id for m in run_mentions}
    projects = {
        p.id: p for p in (
            await db.execute(select(ResearchProject).where(ResearchProject.id.in_(proj_ids)))
        ).scalars().all()
    }
    for m in run_mentions:
        p = projects.get(m.target_id)
        if p is None or (p.user_id is not None and p.user_id != user.id):
            continue
        items.append(EntityHistoryItem(
            kind="observed", at=p.completed_at or m.created_at, project_id=p.id,
            detail=f"Observed in run #{p.run_number or 1}: {p.title}",
        ))

    # Supersessions among this entity's claims.
    claim_ids = await _entity_claim_ids(db, ent, user)
    if claim_ids:
        links = (
            await db.execute(
                select(KgClaimLink).where(
                    KgClaimLink.predicate == "supersedes",
                    or_(
                        KgClaimLink.subject_claim_id.in_(claim_ids),
                        KgClaimLink.object_claim_id.in_(claim_ids),
                    ),
                )
            )
        ).scalars().all()
        for lk in links:
            items.append(EntityHistoryItem(
                kind="superseded", at=lk.created_at, project_id=lk.project_id,
                detail="A claim about this entity was superseded by a newer claim",
            ))

    items.sort(key=lambda x: (x.at is None, x.at))
    return EntityHistory(entity_id=ent.id, items=items)


# --------------------------------------------------------------------------- #
# Relationship detail
# --------------------------------------------------------------------------- #
@router.get("/relationships/{relationship_id}", response_model=RelationshipOut)
async def get_relationship(
    relationship_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    rel = await db.get(KgRelationship, relationship_id)
    if rel is None or (rel.user_id is not None and rel.user_id != user.id):
        raise HTTPException(404, "Relationship not found")
    return rel


# --------------------------------------------------------------------------- #
# Retry a degraded graph build (spec §20, §32)
# --------------------------------------------------------------------------- #
@router.post("/graph/rebuild/{project_id}", response_model=MessageOut)
async def rebuild_graph(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    proj = await _get_project(db, project_id, user)  # ownership enforced (404 for others)
    status = await kg_graph.build_graph_for_project(project_id)
    if proj.parent_id:
        recon = await kg_graph.reconcile_from_diff(proj.parent_id, project_id)
        status = {**status, **{f"reconcile_{k}": v for k, v in recon.items()}}
    return MessageOut(
        message=f"Graph rebuilt: {status.get('entities', 0)} entities, "
                f"{status.get('relationships', 0)} relationships",
        ok=status.get("state") == "ok",
    )

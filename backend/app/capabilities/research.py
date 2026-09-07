"""Research capabilities (#8): the single implementation of start/status/report/claims/
evidence/again/diff/search. Reuses the existing research engine (manager/orchestrator),
diff engine, verification/evidence, and lineage — no second engine (spec §6-§12, §55)."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, or_, select

from app.capabilities.base import (
    CapabilityError,
    clamp_page,
    codes,
    idempotency_get,
    idempotency_put,
    owned_project,
)
from app.config import get_settings
from app.database import SessionLocal
from app.knowledge import graph as kg_graph
from app.models import (
    Claim,
    ClaimSource,
    ProjectStatus,
    Recommendation,
    ResearchProject,
    Source,
)
from app.models.enums import ResearchMode, SourcePolicy
from app.services import audit, research_diff
from app.services.research_service import manager

_INTENTS = {"refresh", "deepen", "verify", "full"}


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


async def _user_active_count(user) -> int:
    """How many runs THIS user currently has in flight. The concurrency limit is per-user
    (spec §24, §37) — one actor can't be blocked or DoS'd by another's runs."""
    active = manager.active_ids()
    if not active:
        return 0
    async with SessionLocal() as db:
        rows = (
            await db.execute(
                select(ResearchProject.id).where(
                    ResearchProject.id.in_(active), ResearchProject.user_id == user.id
                )
            )
        ).all()
    return len(rows)


# --------------------------------------------------------------------------- #
# Start / Research Again (mutating, long-running, idempotent) — spec §6, §11, §22, §23
# --------------------------------------------------------------------------- #
async def start(
    user,
    *,
    query: str,
    sources_enabled: list[str] | None = None,
    mode: str = "deep",
    source_policy: str | None = None,
    constraints: dict | None = None,
    idempotency_key: str | None = None,
    client_ip: str | None = None,
) -> dict:
    if not query or len(query.strip()) < 3:
        raise CapabilityError(codes.INVALID_ARGUMENT, "query must be at least 3 characters")
    try:
        rmode = ResearchMode(mode)
    except ValueError:
        raise CapabilityError(codes.INVALID_ARGUMENT, f"unknown research mode '{mode}'")
    if source_policy is not None and source_policy not in {p.value for p in SourcePolicy}:
        raise CapabilityError(codes.INVALID_ARGUMENT, f"unknown source_policy '{source_policy}'")

    cached = idempotency_get(user.id, idempotency_key)
    if cached:
        return await status(user, cached)  # same key → same run, never a duplicate

    if await _user_active_count(user) >= get_settings().concurrent_research_limit:
        raise CapabilityError(
            codes.RATE_LIMITED,
            "Too many research runs are already in progress; try again shortly.", 429,
        )

    async with SessionLocal() as db:
        proj = ResearchProject(
            user_id=user.id, title=query.strip()[:120], query=query.strip(), mode=rmode,
            constraints=constraints or {}, sources_enabled=sources_enabled or ["web"],
            source_policy=source_policy, status=ProjectStatus.CREATED,
            run_number=1, run_intent="original",
        )
        db.add(proj)
        await db.flush()
        proj.root_id = proj.id
        await db.commit()
        research_id = proj.id

    manager.start(research_id)
    idempotency_put(user.id, idempotency_key, research_id)
    await audit.record("v1.research.start", project_id=research_id, user_id=user.id,
                       detail={"mode": rmode.value, "client_ip": client_ip})
    return await status(user, research_id)


async def again(
    user,
    project_id: str,
    *,
    intent: str = "refresh",
    sources_enabled: list[str] | None = None,
    idempotency_key: str | None = None,
    client_ip: str | None = None,
) -> dict:
    if intent not in _INTENTS:
        raise CapabilityError(codes.INVALID_ARGUMENT,
                              f"intent must be one of {sorted(_INTENTS)}")
    cached = idempotency_get(user.id, idempotency_key)
    if cached:
        return await status(user, cached)

    async with SessionLocal() as db:
        parent = await owned_project(db, project_id, user)
        if parent.status != ProjectStatus.COMPLETED:
            raise CapabilityError(codes.RESEARCH_IN_PROGRESS,
                                  "You can only continue a completed research run", 409)
        if await _user_active_count(user) >= get_settings().concurrent_research_limit:
            raise CapabilityError(codes.RATE_LIMITED,
                                  "Too many research runs are already in progress.", 429)
        child = ResearchProject(
            user_id=user.id, title=parent.title, query=parent.query, mode=parent.mode,
            constraints=dict(parent.constraints or {}),
            sources_enabled=sources_enabled or list(parent.sources_enabled or ["web"]),
            source_policy=parent.source_policy, status=ProjectStatus.CREATED,
            parent_id=parent.id, root_id=parent.root_id or parent.id,
            run_number=(parent.run_number or 1) + 1, run_intent=intent,
        )
        db.add(child)
        await db.commit()
        child_id = child.id
        parent_id = parent.id

    if get_settings().research_again_carry_documents:
        try:
            from app.documents.service import carry_forward_documents

            await carry_forward_documents(parent_project_id=parent_id,
                                          new_project_id=child_id, new_user_id=user.id)
        except Exception:  # noqa: BLE001 - best-effort
            pass

    manager.start(child_id)
    idempotency_put(user.id, idempotency_key, child_id)
    await audit.record("v1.research.again", project_id=child_id, user_id=user.id,
                       detail={"parent_id": parent_id, "intent": intent, "client_ip": client_ip})
    return await status(user, child_id)


# --------------------------------------------------------------------------- #
# Reads
# --------------------------------------------------------------------------- #
async def status(user, project_id: str) -> dict:
    async with SessionLocal() as db:
        proj = await owned_project(db, project_id, user)
    health = (proj.report_meta or {}).get("source_health") or {}
    return {
        "research_id": proj.id,
        "status": proj.status.value,
        "progress": proj.progress,
        "current_stage": proj.current_stage,
        "run_number": proj.run_number or 1,
        "run_intent": proj.run_intent,
        "parent_id": proj.parent_id,
        "root_id": proj.root_id,
        "source_policy": proj.source_policy,
        "connectivity_state": health.get("connectivity_state"),
        "research_mode": health.get("research_mode"),
        "research_health": health.get("research_health"),
        "error": proj.error,
        "created_at": _iso(proj.created_at),
        "completed_at": _iso(proj.completed_at),
    }


async def report(user, project_id: str, *, excerpt: bool = False) -> dict:
    async with SessionLocal() as db:
        proj = await owned_project(db, project_id, user)
        rec = (
            await db.execute(select(Recommendation).where(Recommendation.project_id == project_id))
        ).scalars().first()
    markdown = proj.report_markdown or ""
    if excerpt:
        cap = get_settings().capability_report_excerpt_chars
        truncated = len(markdown) > cap
        markdown = markdown[:cap] + ("\n\n…[truncated]" if truncated else "")
    recommendation = None
    if rec and rec.recommended_option:
        recommendation = {
            "option": rec.recommended_option, "confidence": rec.confidence,
            "rationale": rec.rationale,
            "alternatives": rec.alternatives or [], "risks": rec.risks or [],
        }
    return {
        "research_id": proj.id,
        "status": proj.status.value,
        "title": proj.title,
        "markdown": markdown,
        "meta": proj.report_meta or {},
        "recommendation": recommendation,
    }


async def claims(user, project_id: str, *, limit: int | None = None, offset: int | None = None) -> dict:
    lim, off = clamp_page(limit, offset)
    async with SessionLocal() as db:
        await owned_project(db, project_id, user)
        total = (
            await db.execute(
                select(func.count()).select_from(Claim).where(Claim.project_id == project_id)
            )
        ).scalar() or 0
        rows = (
            await db.execute(
                select(Claim).where(Claim.project_id == project_id)
                .order_by(Claim.confidence.desc()).offset(off).limit(lim)
            )
        ).scalars().all()
        superseded = await kg_graph.superseded_claim_ids(db, user.id if user.id else None)
        ev_counts = {}
        if rows:
            ev_rows = (
                await db.execute(
                    select(ClaimSource.claim_id, func.count())
                    .where(ClaimSource.claim_id.in_([c.id for c in rows]))
                    .group_by(ClaimSource.claim_id)
                )
            ).all()
            ev_counts = {cid: n for cid, n in ev_rows}

    items = []
    for c in rows:
        meta = c.confidence_meta or {}
        items.append({
            "claim_id": c.id, "text": c.text, "status": c.status.value,
            "confidence": c.confidence, "evidence_state": c.evidence_state,
            "support_count": meta.get("support_count"),
            "contradiction_count": meta.get("contradiction_count"),
            "evidence_count": ev_counts.get(c.id, 0),
            "disputed": kg_graph.claim_is_disputed(c),
            "superseded": c.id in superseded,
        })
    return {"research_id": project_id, "total": int(total), "limit": lim, "offset": off,
            "claims": items}


async def evidence(user, project_id: str, claim_id: str) -> dict:
    """Supporting + contradicting evidence for a claim, provenance preserved (spec §10)."""
    async with SessionLocal() as db:
        await owned_project(db, project_id, user)
        claim = await db.get(Claim, claim_id)
        if claim is None or claim.project_id != project_id:
            raise CapabilityError(codes.NOT_FOUND, "Claim not found", 404)
        rows = (
            await db.execute(
                select(ClaimSource, Source)
                .join(Source, ClaimSource.source_id == Source.id)
                .where(ClaimSource.claim_id == claim_id)
            )
        ).all()

    _rank = {"supports": 0, "neutral": 1, "contradicts": 2}
    rows.sort(key=lambda r: (_rank.get(r[0].stance.value, 1), -r[1].reliability_score))
    ev = [
        {
            "source_id": s.id, "title": s.title, "url": s.url, "source_type": s.source_type,
            "publisher": s.publisher, "published_date": s.published_date,
            "reliability_score": s.reliability_score, "freshness": s.freshness,
            "provenance": s.provenance, "availability": s.availability,
            "stance": cs.stance.value, "passage": cs.passage,
            "page_number": (s.meta or {}).get("page_number"),
        }
        for cs, s in rows
    ]
    return {
        "research_id": project_id, "claim_id": claim.id, "claim_text": claim.text,
        "status": claim.status.value, "confidence": claim.confidence,
        "evidence_state": claim.evidence_state, "evidence": ev,
    }


async def diff(user, project_id: str, other_id: str) -> dict:
    async with SessionLocal() as db:
        base = await owned_project(db, project_id, user)
        other = await owned_project(db, other_id, user)
    if (base.root_id or base.id) != (other.root_id or other.id):
        raise CapabilityError(codes.NOT_FOUND,
                              "The two runs are not in the same research lineage", 404)
    if (base.run_number or 1) <= (other.run_number or 1):
        old_id, new_id = base.id, other.id
    else:
        old_id, new_id = other.id, base.id
    d = await research_diff.diff_runs(old_id, new_id)
    return _serialize_diff(d)


async def search(user, *, q: str | None = None, limit: int | None = None,
                 offset: int | None = None) -> dict:
    lim, off = clamp_page(limit, offset)
    async with SessionLocal() as db:
        stmt = select(ResearchProject).where(
            or_(ResearchProject.user_id == user.id, ResearchProject.user_id.is_(None))
        )
        if q and q.strip():
            like = f"%{q.strip()}%"
            stmt = stmt.where(or_(
                ResearchProject.title.ilike(like),
                ResearchProject.query.ilike(like),
                ResearchProject.objective.ilike(like),
            ))
        rows = (
            await db.execute(stmt.order_by(ResearchProject.created_at.desc()).offset(off).limit(lim))
        ).scalars().all()
    return {
        "limit": lim, "offset": off,
        "results": [
            {"research_id": r.id, "title": r.title, "status": r.status.value,
             "run_number": r.run_number or 1, "created_at": _iso(r.created_at),
             "completed_at": _iso(r.completed_at)}
            for r in rows
        ],
    }


# --------------------------------------------------------------------------- #
# Diff serialization (bounded, JSON-safe) — reuses the existing ResearchDiff
# --------------------------------------------------------------------------- #
def _serialize_diff(d: research_diff.ResearchDiff, *, max_items: int = 100) -> dict:
    def claim_item(it):
        return {
            "kind": it.kind, "old_text": it.old_text, "new_text": it.new_text,
            "old_confidence": it.old_confidence, "new_confidence": it.new_confidence,
            "confidence_delta": it.confidence_delta, "direction": it.direction,
            "reason": it.reason,
        }

    def source_item(it):
        return {"kind": it.kind, "url": it.url, "title": it.title,
                "source_type": it.source_type, "changes": it.changes}

    claims = dict(d.claims)
    claims_items = [claim_item(it) for it in d.claims.get("items", [])[:max_items]]
    sources = dict(d.sources)
    sources_items = [source_item(it) for it in d.sources.get("items", [])[:max_items]]
    return {
        "old_run": d.old_run, "new_run": d.new_run,
        "claims": {**{k: v for k, v in claims.items() if k != "items"}, "items": claims_items},
        "sources": {**{k: v for k, v in sources.items() if k != "items"}, "items": sources_items},
        "confidence": d.confidence,
        "recommendation": d.recommendation,
    }

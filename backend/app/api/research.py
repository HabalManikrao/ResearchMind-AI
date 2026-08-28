"""Research REST + SSE endpoints (spec §16)."""
from __future__ import annotations

import asyncio
import json

import re

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from app.export import EXPORT_FORMATS, ExportError, export_report

from app.database import get_db
from app.models import (
    Claim,
    ClaimSource,
    Conflict,
    Finding,
    KnowledgeGap,
    ProjectStatus,
    Recommendation,
    ResearchProject,
    ResearchQuestion,
    ResearchTask,
    Solution,
    Source,
    User,
)
from app.security.auth import decode_token, get_current_user
from app.config import get_settings
from app.schemas.research import (
    ClaimEvidenceItem,
    ClaimEvidenceOut,
    ClaimOut,
    ConflictOut,
    FindingOut,
    KnowledgeGapOut,
    MessageOut,
    ProjectDetail,
    ProjectSummary,
    QuestionCreate,
    QuestionOut,
    RecommendationOut,
    ReportOut,
    ResearchCreate,
    SolutionOut,
    SourceOut,
    TaskOut,
)
from app.services import audit
from app.services.events import bus
from app.services.research_service import manager

router = APIRouter(prefix="/research", tags=["research"])


async def _get_project(
    db: AsyncSession, project_id: str, user: User
) -> ResearchProject:
    """Fetch a project the user is allowed to see.

    Ownership: a project belongs to its ``user_id``. Legacy projects created
    before auth (``user_id is None``) are treated as shared/unowned and are
    readable by any authenticated user. Accessing someone else's project 404s
    (rather than 403) so we don't reveal that the id exists.
    """
    proj = await db.get(ResearchProject, project_id)
    if proj is None:
        raise HTTPException(404, "Research project not found")
    if proj.user_id is not None and proj.user_id != user.id:
        raise HTTPException(404, "Research project not found")
    return proj


async def _authenticate_query_token(
    request: Request, token: str, db: AsyncSession
) -> User:
    """Auth for endpoints reached by the browser without a header (SSE stream,
    file download): accept the JWT from the Authorization header if present,
    otherwise from the ``?token=`` query parameter.
    """
    if not get_settings().auth_enabled:
        from app.security.auth import _local_user

        return _local_user()
    if not token:
        header = request.headers.get("Authorization", "")
        if header.lower().startswith("bearer "):
            token = header[7:].strip()
    if not token:
        raise HTTPException(401, "Not authenticated")
    user_id = decode_token(token)  # raises 401 on bad/expired token
    user = await db.get(User, user_id)
    if user is None or not user.is_active:
        raise HTTPException(401, "Not authenticated")
    return user


@router.post("", response_model=ProjectDetail, status_code=201)
async def create_research(
    body: ResearchCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    proj = ResearchProject(
        user_id=user.id,
        title=body.title or body.query[:120],
        query=body.query,
        mode=body.mode,
        constraints=body.constraints,
        sources_enabled=body.sources_enabled or ["web"],
        status=ProjectStatus.CREATED,
    )
    db.add(proj)
    await db.commit()
    await db.refresh(proj)
    await audit.record(
        "research.create", project_id=proj.id, user_id=user.id, request=request,
        detail={"mode": proj.mode.value, "auto_start": body.auto_start},
    )
    if body.auto_start:
        manager.start(proj.id)
    return proj


@router.get("", response_model=list[ProjectSummary])
async def list_research(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    # The user's own projects plus legacy/unowned ones (user_id IS NULL).
    rows = (
        await db.execute(
            select(ResearchProject)
            .where(
                (ResearchProject.user_id == user.id)
                | (ResearchProject.user_id.is_(None))
            )
            .order_by(ResearchProject.created_at.desc())
        )
    ).scalars().all()
    return rows


@router.get("/{project_id}", response_model=ProjectDetail)
async def get_research(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return await _get_project(db, project_id, user)


@router.post("/{project_id}/start", response_model=MessageOut)
async def start_research(
    project_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    proj = await _get_project(db, project_id, user)
    if manager.is_active(project_id):
        raise HTTPException(409, "Research is already running")
    if proj.status == ProjectStatus.COMPLETED:
        raise HTTPException(409, "Research already completed")
    manager.start(project_id)
    await audit.record("research.start", project_id=project_id, user_id=user.id,
                       request=request)
    return MessageOut(message="Research started")


@router.post("/{project_id}/pause", response_model=MessageOut)
async def pause_research(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    proj = await _get_project(db, project_id, user)
    ok = manager.pause(project_id)
    if ok:
        proj.status = ProjectStatus.PAUSED
        await db.commit()
    return MessageOut(message="Paused" if ok else "Not running", ok=ok)


@router.post("/{project_id}/resume", response_model=MessageOut)
async def resume_research(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    proj = await _get_project(db, project_id, user)
    ok = manager.resume(project_id)
    if ok:
        proj.status = ProjectStatus.RUNNING
        await db.commit()
    return MessageOut(message="Resumed" if ok else "Not paused", ok=ok)


@router.post("/{project_id}/stop", response_model=MessageOut)
async def stop_research(
    project_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    await _get_project(db, project_id, user)
    ok = manager.stop(project_id)
    await audit.record("research.stop", project_id=project_id, user_id=user.id,
                       request=request)
    return MessageOut(message="Stopping" if ok else "Not running", ok=ok)


@router.get("/{project_id}/questions", response_model=list[QuestionOut])
async def get_questions(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    await _get_project(db, project_id, user)
    rows = (
        await db.execute(
            select(ResearchQuestion)
            .where(ResearchQuestion.project_id == project_id)
            .order_by(ResearchQuestion.priority)
        )
    ).scalars().all()
    return rows


@router.post("/{project_id}/questions", response_model=QuestionOut, status_code=201)
async def add_question(
    project_id: str,
    body: QuestionCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    await _get_project(db, project_id, user)
    q = ResearchQuestion(project_id=project_id, text=body.text, priority=body.priority)
    db.add(q)
    await db.commit()
    await db.refresh(q)
    return q


@router.get("/{project_id}/tasks", response_model=list[TaskOut])
async def get_tasks(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    await _get_project(db, project_id, user)
    rows = (
        await db.execute(select(ResearchTask).where(ResearchTask.project_id == project_id))
    ).scalars().all()
    return rows


@router.get("/{project_id}/sources", response_model=list[SourceOut])
async def get_sources(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    await _get_project(db, project_id, user)
    rows = (
        await db.execute(
            select(Source)
            .where(Source.project_id == project_id)
            .order_by(Source.reliability_score.desc())
        )
    ).scalars().all()
    return rows


@router.get("/{project_id}/findings", response_model=list[FindingOut])
async def get_findings(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    await _get_project(db, project_id, user)
    rows = (
        await db.execute(select(Finding).where(Finding.project_id == project_id))
    ).scalars().all()
    return rows


@router.get("/{project_id}/claims", response_model=list[ClaimOut])
async def get_claims(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    await _get_project(db, project_id, user)
    rows = (
        await db.execute(
            select(Claim).where(Claim.project_id == project_id).order_by(Claim.confidence.desc())
        )
    ).scalars().all()
    return rows


@router.get(
    "/{project_id}/claims/{claim_id}/evidence", response_model=ClaimEvidenceOut
)
async def get_claim_evidence(
    project_id: str,
    claim_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """The evidence behind a claim: every supporting/contradicting source with its
    quoted passage and freshness, so a reader can trace exactly why the claim has
    its status and confidence (spec §6 claim-to-source mapping)."""
    await _get_project(db, project_id, user)
    claim = await db.get(Claim, claim_id)
    if claim is None or claim.project_id != project_id:
        raise HTTPException(404, "Claim not found")

    rows = (
        await db.execute(
            select(ClaimSource, Source)
            .join(Source, ClaimSource.source_id == Source.id)
            .where(ClaimSource.claim_id == claim_id)
        )
    ).all()

    # Supporting evidence first, then contradicting; most reliable first within each.
    _stance_rank = {"supports": 0, "neutral": 1, "contradicts": 2}

    def _key(row):
        cs, s = row
        return (_stance_rank.get(cs.stance.value, 1), -s.reliability_score)

    evidence = [
        ClaimEvidenceItem(
            source_id=s.id,
            title=s.title,
            url=s.url,
            source_type=s.source_type,
            publisher=s.publisher,
            published_date=s.published_date,
            reliability_score=s.reliability_score,
            freshness=s.freshness,
            stance=cs.stance.value,
            passage=cs.passage,
            page_number=(s.meta or {}).get("page_number"),
        )
        for cs, s in sorted(rows, key=_key)
    ]
    return ClaimEvidenceOut(claim=ClaimOut.model_validate(claim), evidence=evidence)


@router.get("/{project_id}/conflicts", response_model=list[ConflictOut])
async def get_conflicts(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    await _get_project(db, project_id, user)
    rows = (
        await db.execute(select(Conflict).where(Conflict.project_id == project_id))
    ).scalars().all()
    return rows


@router.get("/{project_id}/gaps", response_model=list[KnowledgeGapOut])
async def get_gaps(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    await _get_project(db, project_id, user)
    rows = (
        await db.execute(
            select(KnowledgeGap)
            .where(KnowledgeGap.project_id == project_id)
            .order_by(KnowledgeGap.round)
        )
    ).scalars().all()
    return rows


@router.get("/{project_id}/solutions", response_model=list[SolutionOut])
async def get_solutions(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    await _get_project(db, project_id, user)
    rows = (
        await db.execute(select(Solution).where(Solution.project_id == project_id))
    ).scalars().all()
    return rows


@router.get("/{project_id}/recommendation", response_model=RecommendationOut | None)
async def get_recommendation(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    await _get_project(db, project_id, user)
    row = (
        await db.execute(
            select(Recommendation).where(Recommendation.project_id == project_id)
        )
    ).scalars().first()
    return row


@router.get("/{project_id}/report", response_model=ReportOut)
async def get_report(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    proj = await _get_project(db, project_id, user)
    return ReportOut(project_id=proj.id, markdown=proj.report_markdown, meta=proj.report_meta)


@router.get("/{project_id}/export")
async def export_research(
    project_id: str,
    request: Request,
    format: str = Query("pdf", pattern="^(md|html|pdf|docx)$"),
    token: str = Query("", description="JWT (for direct browser download links)"),
    db: AsyncSession = Depends(get_db),
):
    user = await _authenticate_query_token(request, token, db)
    proj = await _get_project(db, project_id, user)
    if not proj.report_markdown:
        raise HTTPException(409, "Report is not ready yet")
    try:
        content = export_report(proj.report_markdown, title=proj.title, fmt=format)
    except ExportError as exc:
        raise HTTPException(422, str(exc))
    await audit.record(
        "research.export", project_id=project_id, user_id=user.id, request=request,
        detail={"format": format},
    )

    media_type, ext = EXPORT_FORMATS[format]
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", proj.title)[:60] or "report"
    filename = f"{safe}.{ext}"
    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/{project_id}/stream")
async def stream_progress(
    project_id: str,
    request: Request,
    token: str = Query("", description="JWT (browser EventSource can't set headers)"),
    db: AsyncSession = Depends(get_db),
):
    """Server-Sent Events stream of live research activity (spec §12).

    The browser ``EventSource`` API cannot send an Authorization header, so this
    endpoint accepts the JWT as a ``?token=`` query parameter instead.
    """
    user = await _authenticate_query_token(request, token, db)
    await _get_project(db, project_id, user)
    queue = bus.subscribe(project_id)

    async def event_gen():
        try:
            # Prime the stream so the client knows it is connected.
            yield {"event": "connected", "data": json.dumps({"project_id": project_id})}
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15.0)
                except asyncio.TimeoutError:
                    yield {"event": "ping", "data": "{}"}  # keep-alive
                    continue
                yield {"event": event.type, "data": json.dumps(event.to_dict())}
                if event.type in ("done", "error"):
                    break
        finally:
            bus.unsubscribe(project_id, queue)

    return EventSourceResponse(event_gen())

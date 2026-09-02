"""Research REST + SSE endpoints (spec §16)."""
from __future__ import annotations

import asyncio
import json

import re

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy import func, select
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
    MemoryOut,
    MessageOut,
    ProjectDetail,
    ProjectSummary,
    QuestionCreate,
    QuestionOut,
    RecommendationOut,
    ReportOut,
    ResearchAgainRequest,
    ResearchCreate,
    ResearchDiffOut,
    RunSummary,
    SolutionOut,
    SourceOut,
    TaskOut,
)
from app.services import audit
from app.services import research_diff
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
        source_policy=body.source_policy,  # None => backend default at run time (#5)
        status=ProjectStatus.CREATED,
        run_number=1,
        run_intent="original",
    )
    db.add(proj)
    await db.flush()  # assign proj.id
    proj.root_id = proj.id  # an original run is the root of its own lineage
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


@router.post("/{project_id}/research-again", response_model=ProjectDetail, status_code=201)
async def research_again(
    project_id: str,
    body: ResearchAgainRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Fork a completed run into a continuation run (#4). The parent is read-only:
    a new project is created, linked via lineage, and (best-effort) the parent's
    documents are carried forward so a re-run can use them. The new run receives the
    parent's selective memory at planning time (orchestrator)."""
    parent = await _get_project(db, project_id, user)
    if parent.status != ProjectStatus.COMPLETED:
        raise HTTPException(409, "You can only continue a completed research run")

    child = ResearchProject(
        user_id=user.id,
        title=parent.title,
        query=parent.query,
        mode=body.mode or parent.mode,
        constraints=dict(parent.constraints or {}),
        sources_enabled=body.sources_enabled or list(parent.sources_enabled or ["web"]),
        status=ProjectStatus.CREATED,
        parent_id=parent.id,
        root_id=parent.root_id or parent.id,
        run_number=(parent.run_number or 1) + 1,
        run_intent=body.intent,
    )
    db.add(child)
    await db.commit()
    await db.refresh(child)

    if get_settings().research_again_carry_documents:
        try:
            from app.documents.service import carry_forward_documents

            await carry_forward_documents(
                parent_project_id=parent.id, new_project_id=child.id, new_user_id=user.id,
            )
        except Exception:  # noqa: BLE001 - carry-forward is best-effort, never blocks a re-run
            pass

    await audit.record(
        "research.again", project_id=child.id, user_id=user.id, request=request,
        detail={"parent_id": parent.id, "intent": body.intent},
    )
    if body.auto_start:
        manager.start(child.id)
    return child


@router.get("/{project_id}/runs", response_model=list[RunSummary])
async def get_runs(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """All runs in this project's lineage (same root), oldest first, with quick
    counts for the history/lineage view (#4)."""
    proj = await _get_project(db, project_id, user)
    root = proj.root_id or proj.id
    rows = (
        await db.execute(
            select(ResearchProject)
            .where(ResearchProject.root_id == root)
            .order_by(ResearchProject.run_number)
        )
    ).scalars().all()

    out: list[RunSummary] = []
    for r in rows:
        # Visibility: same rule as _get_project (own or legacy/unowned runs only).
        if r.user_id is not None and r.user_id != user.id:
            continue
        source_count = (
            await db.execute(
                select(func.count()).select_from(Source).where(Source.project_id == r.id)
            )
        ).scalar() or 0
        claim_count = (
            await db.execute(
                select(func.count()).select_from(Claim).where(Claim.project_id == r.id)
            )
        ).scalar() or 0
        evidence_count = (
            await db.execute(
                select(func.count())
                .select_from(ClaimSource)
                .join(Claim, ClaimSource.claim_id == Claim.id)
                .where(Claim.project_id == r.id)
            )
        ).scalar() or 0
        avg_conf = (
            await db.execute(
                select(func.avg(Claim.confidence)).where(Claim.project_id == r.id)
            )
        ).scalar()
        out.append(
            RunSummary(
                id=r.id,
                run_number=r.run_number or 1,
                run_intent=r.run_intent,
                status=r.status,
                created_at=r.created_at,
                completed_at=r.completed_at,
                parent_id=r.parent_id,
                source_count=source_count,
                claim_count=claim_count,
                evidence_count=evidence_count,
                avg_confidence=round(float(avg_conf or 0.0), 1),
            )
        )
    return out


@router.get("/{project_id}/memory", response_model=MemoryOut)
async def get_memory(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """The run's compact research-memory record built at completion (#4, spec §23)."""
    proj = await _get_project(db, project_id, user)
    return MemoryOut(project_id=proj.id, memory=proj.memory_summary)


@router.get("/{project_id}/diff/{other_id}", response_model=ResearchDiffOut)
async def diff_research(
    project_id: str,
    other_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Deterministic diff of two runs in the same lineage (#4). Read-only; ownership
    enforced on both ids; the runs must share a root (else 404)."""
    base = await _get_project(db, project_id, user)
    other = await _get_project(db, other_id, user)
    if (base.root_id or base.id) != (other.root_id or other.id):
        raise HTTPException(404, "The two runs are not in the same research lineage")

    # Diff old -> new by run order.
    if (base.run_number or 1) <= (other.run_number or 1):
        old_id, new_id = base.id, other.id
    else:
        old_id, new_id = other.id, base.id

    diff = await research_diff.diff_runs(old_id, new_id)
    return ResearchDiffOut(
        old_run=diff.old_run,
        new_run=diff.new_run,
        sources=diff.sources,
        claims=diff.claims,
        confidence=diff.confidence,
        recommendation=diff.recommendation,
        documents=diff.documents,
    )


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
            provenance=s.provenance,
            availability=s.availability,
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

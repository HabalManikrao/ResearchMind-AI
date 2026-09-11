"""R&D layer Phase A REST endpoints — Brief, Objectives, Constraints, Terminology.

Thin CRUD over the Phase A models, mounted under the existing `/research` prefix and reusing
`research._get_project` for ownership (404-no-leak). Additive: no existing route changes. All
handlers are deterministic (no LLM). Scope lives on the brief (`scope_included`/`scope_excluded`);
typed constraints are their own collection.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.research import _get_project
from app.database import get_db
from app.models import Constraint, Objective, ResearchBrief, Terminology, User
from app.schemas.research import (
    ConstraintCreate,
    ConstraintOut,
    ObjectiveCreate,
    ObjectiveOut,
    ObjectiveUpdate,
    ResearchBriefOut,
    ResearchBriefUpdate,
    TerminologyCreate,
    TerminologyOut,
    TerminologyUpdate,
)
from app.security.auth import get_current_user
from app.services import audit

router = APIRouter(prefix="/research", tags=["rnd"])


# --------------------------------------------------------------------------- #
# Research Brief (1:1, get-or-create, version-aware).
# --------------------------------------------------------------------------- #
async def _get_or_create_brief(db: AsyncSession, project_id: str) -> ResearchBrief:
    brief = (
        await db.execute(select(ResearchBrief).where(ResearchBrief.project_id == project_id))
    ).scalars().first()
    if brief is None:
        brief = ResearchBrief(project_id=project_id)
        db.add(brief)
        await db.commit()
        await db.refresh(brief)
    return brief


@router.get("/{project_id}/brief", response_model=ResearchBriefOut)
async def get_brief(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    await _get_project(db, project_id, user)
    return await _get_or_create_brief(db, project_id)


@router.put("/{project_id}/brief", response_model=ResearchBriefOut)
async def update_brief(
    project_id: str,
    body: ResearchBriefUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    await _get_project(db, project_id, user)
    brief = await _get_or_create_brief(db, project_id)
    changed = body.model_dump(exclude_unset=True)
    for field, value in changed.items():
        setattr(brief, field, value)
    if changed:
        brief.version = (brief.version or 1) + 1  # version-aware edit
    await db.commit()
    await db.refresh(brief)
    await audit.record("research.brief.update", project_id=project_id, user_id=user.id,
                       request=request)
    return brief


# --------------------------------------------------------------------------- #
# Objectives.
# --------------------------------------------------------------------------- #
@router.get("/{project_id}/objectives", response_model=list[ObjectiveOut])
async def list_objectives(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    await _get_project(db, project_id, user)
    return (
        await db.execute(
            select(Objective).where(Objective.project_id == project_id)
            .order_by(Objective.priority, Objective.created_at)
        )
    ).scalars().all()


@router.post("/{project_id}/objectives", response_model=ObjectiveOut, status_code=201)
async def create_objective(
    project_id: str,
    body: ObjectiveCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    await _get_project(db, project_id, user)
    obj = Objective(project_id=project_id, **body.model_dump())
    db.add(obj)
    await db.commit()
    await db.refresh(obj)
    return obj


async def _get_owned_objective(db, project_id, objective_id, user) -> Objective:
    await _get_project(db, project_id, user)
    obj = await db.get(Objective, objective_id)
    if obj is None or obj.project_id != project_id:
        raise HTTPException(404, "Objective not found")
    return obj


@router.patch("/{project_id}/objectives/{objective_id}", response_model=ObjectiveOut)
async def update_objective(
    project_id: str,
    objective_id: str,
    body: ObjectiveUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    obj = await _get_owned_objective(db, project_id, objective_id, user)
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(obj, field, value)
    await db.commit()
    await db.refresh(obj)
    return obj


@router.delete("/{project_id}/objectives/{objective_id}", status_code=204)
async def delete_objective(
    project_id: str,
    objective_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    obj = await _get_owned_objective(db, project_id, objective_id, user)
    await db.delete(obj)
    await db.commit()


# --------------------------------------------------------------------------- #
# Constraints (typed).
# --------------------------------------------------------------------------- #
@router.get("/{project_id}/constraints", response_model=list[ConstraintOut])
async def list_constraints(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    await _get_project(db, project_id, user)
    return (
        await db.execute(
            select(Constraint).where(Constraint.project_id == project_id)
            .order_by(Constraint.created_at)
        )
    ).scalars().all()


@router.post("/{project_id}/constraints", response_model=ConstraintOut, status_code=201)
async def create_constraint(
    project_id: str,
    body: ConstraintCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    await _get_project(db, project_id, user)
    row = Constraint(project_id=project_id, **body.model_dump())
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


@router.delete("/{project_id}/constraints/{constraint_id}", status_code=204)
async def delete_constraint(
    project_id: str,
    constraint_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    await _get_project(db, project_id, user)
    row = await db.get(Constraint, constraint_id)
    if row is None or row.project_id != project_id:
        raise HTTPException(404, "Constraint not found")
    await db.delete(row)
    await db.commit()


# --------------------------------------------------------------------------- #
# Terminology (ambiguity preserved — never auto-merge by name).
# --------------------------------------------------------------------------- #
@router.get("/{project_id}/terminology", response_model=list[TerminologyOut])
async def list_terminology(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    await _get_project(db, project_id, user)
    return (
        await db.execute(
            select(Terminology).where(Terminology.project_id == project_id)
            .order_by(Terminology.term)
        )
    ).scalars().all()


@router.post("/{project_id}/terminology", response_model=TerminologyOut, status_code=201)
async def create_terminology(
    project_id: str,
    body: TerminologyCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    await _get_project(db, project_id, user)
    row = Terminology(project_id=project_id, **body.model_dump())
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


async def _get_owned_term(db, project_id, term_id, user) -> Terminology:
    await _get_project(db, project_id, user)
    row = await db.get(Terminology, term_id)
    if row is None or row.project_id != project_id:
        raise HTTPException(404, "Terminology entry not found")
    return row


@router.patch("/{project_id}/terminology/{term_id}", response_model=TerminologyOut)
async def update_terminology(
    project_id: str,
    term_id: str,
    body: TerminologyUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    row = await _get_owned_term(db, project_id, term_id, user)
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(row, field, value)
    await db.commit()
    await db.refresh(row)
    return row


@router.delete("/{project_id}/terminology/{term_id}", status_code=204)
async def delete_terminology(
    project_id: str,
    term_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    row = await _get_owned_term(db, project_id, term_id, user)
    await db.delete(row)
    await db.commit()

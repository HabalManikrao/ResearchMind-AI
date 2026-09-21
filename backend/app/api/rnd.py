"""R&D layer Phase A REST endpoints — Brief, Objectives, Constraints, Terminology.

Thin CRUD over the Phase A models, mounted under the existing `/research` prefix and reusing
`research._get_project` for ownership (404-no-leak). Additive: no existing route changes. All
handlers are deterministic (no LLM). Scope lives on the brief (`scope_included`/`scope_excluded`);
typed constraints are their own collection.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import delete as sa_delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.research import _get_project
from app.database import get_db
from app.models import (
    Claim,
    Constraint,
    Dataset,
    Experiment,
    Hypothesis,
    Method,
    Objective,
    ResearchBrief,
    ResearchQuestion,
    Result,
    Source,
    Terminology,
    User,
)
from app.schemas.research import (
    ConstraintCreate,
    ConstraintOut,
    DatasetCreate,
    DatasetOut,
    DatasetUpdate,
    ExperimentCreate,
    ExperimentOut,
    ExperimentUpdate,
    HypothesisCreate,
    HypothesisOut,
    HypothesisUpdate,
    MethodCreate,
    MethodOut,
    MethodUpdate,
    ObjectiveCreate,
    ObjectiveOut,
    ObjectiveUpdate,
    ResearchBriefOut,
    ResearchBriefUpdate,
    ResultCreate,
    ResultOut,
    ResultUpdate,
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


# --------------------------------------------------------------------------- #
# Phase B — Methods & Hypotheses.
#
# Relationships are JSON id-lists validated to belong to the SAME project, so a client can never
# inject another project's (or user's) Source/Claim/Question/Objective/Method id. Referenced ids
# that don't belong to the project are rejected with 422 (no existence leak beyond "invalid ref").
# --------------------------------------------------------------------------- #
async def _validate_refs(db, project_id, model, ids, label) -> None:
    ids = [i for i in (ids or []) if i]
    if not ids:
        return
    rows = (
        await db.execute(select(model.id).where(
            model.id.in_(ids), model.project_id == project_id))
    ).scalars().all()
    missing = set(ids) - set(rows)
    if missing:
        raise HTTPException(422, f"Unknown or cross-project {label}: {sorted(missing)}")


async def _validate_single_ref(db, project_id, model, id_value, label) -> None:
    if id_value is None:
        return
    row = await db.get(model, id_value)
    if row is None or getattr(row, "project_id", None) != project_id:
        raise HTTPException(422, f"Unknown or cross-project {label}")


# Single-id relationship fields → the model they must reference (all project-scoped).
_SINGLE_REF_MODELS = {
    "question_id": ResearchQuestion,
    "objective_id": Objective,
    "hypothesis_id": Hypothesis,
    "method_id": Method,
    "dataset_id": Dataset,
    "supersedes_id": Dataset,
    "experiment_id": Experiment,
}


async def _validate_object_links(db, project_id, data: dict) -> None:
    """Validate every relationship id in a create/update payload against this project, so a client
    can never attach another project's/user's object (list refs → 422 with the offending ids;
    single-id refs → 422). Only keys actually present in `data` are checked."""
    await _validate_refs(db, project_id, Source, data.get("source_ids"), "source_ids")
    await _validate_refs(db, project_id, Claim, data.get("claim_ids"), "claim_ids")
    await _validate_refs(db, project_id, ResearchQuestion, data.get("question_ids"), "question_ids")
    await _validate_refs(db, project_id, Objective, data.get("objective_ids"), "objective_ids")
    for field, model in _SINGLE_REF_MODELS.items():
        if field in data:
            await _validate_single_ref(db, project_id, model, data.get(field), field)


# --- Methods --------------------------------------------------------------- #
@router.get("/{project_id}/methods", response_model=list[MethodOut])
async def list_methods(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    await _get_project(db, project_id, user)
    return (
        await db.execute(
            select(Method).where(Method.project_id == project_id).order_by(Method.created_at)
        )
    ).scalars().all()


@router.post("/{project_id}/methods", response_model=MethodOut, status_code=201)
async def create_method(
    project_id: str,
    body: MethodCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    await _get_project(db, project_id, user)
    data = body.model_dump()
    await _validate_object_links(db, project_id, data)
    row = Method(project_id=project_id, **data)
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


async def _get_owned_method(db, project_id, method_id, user) -> Method:
    await _get_project(db, project_id, user)
    row = await db.get(Method, method_id)
    if row is None or row.project_id != project_id:
        raise HTTPException(404, "Method not found")
    return row


@router.get("/{project_id}/methods/{method_id}", response_model=MethodOut)
async def get_method(
    project_id: str,
    method_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return await _get_owned_method(db, project_id, method_id, user)


@router.patch("/{project_id}/methods/{method_id}", response_model=MethodOut)
async def update_method(
    project_id: str,
    method_id: str,
    body: MethodUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    row = await _get_owned_method(db, project_id, method_id, user)
    changed = body.model_dump(exclude_unset=True)
    await _validate_object_links(db, project_id, changed)
    for field, value in changed.items():
        setattr(row, field, value)
    if changed:
        row.version = (row.version or 1) + 1  # version-aware edit (methodological history)
    await db.commit()
    await db.refresh(row)
    return row


@router.delete("/{project_id}/methods/{method_id}", status_code=204)
async def delete_method(
    project_id: str,
    method_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    row = await _get_owned_method(db, project_id, method_id, user)
    await db.delete(row)
    await db.commit()


# --- Hypotheses ------------------------------------------------------------ #
@router.get("/{project_id}/hypotheses", response_model=list[HypothesisOut])
async def list_hypotheses(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    await _get_project(db, project_id, user)
    return (
        await db.execute(
            select(Hypothesis).where(Hypothesis.project_id == project_id)
            .order_by(Hypothesis.created_at)
        )
    ).scalars().all()


@router.post("/{project_id}/hypotheses", response_model=HypothesisOut, status_code=201)
async def create_hypothesis(
    project_id: str,
    body: HypothesisCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    await _get_project(db, project_id, user)
    data = body.model_dump()
    await _validate_object_links(db, project_id, data)
    row = Hypothesis(project_id=project_id, **data)
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


async def _get_owned_hypothesis(db, project_id, hypothesis_id, user) -> Hypothesis:
    await _get_project(db, project_id, user)
    row = await db.get(Hypothesis, hypothesis_id)
    if row is None or row.project_id != project_id:
        raise HTTPException(404, "Hypothesis not found")
    return row


@router.get("/{project_id}/hypotheses/{hypothesis_id}", response_model=HypothesisOut)
async def get_hypothesis(
    project_id: str,
    hypothesis_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return await _get_owned_hypothesis(db, project_id, hypothesis_id, user)


@router.patch("/{project_id}/hypotheses/{hypothesis_id}", response_model=HypothesisOut)
async def update_hypothesis(
    project_id: str,
    hypothesis_id: str,
    body: HypothesisUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    row = await _get_owned_hypothesis(db, project_id, hypothesis_id, user)
    changed = body.model_dump(exclude_unset=True)
    await _validate_object_links(db, project_id, changed)
    for field, value in changed.items():
        setattr(row, field, value)
    await db.commit()
    await db.refresh(row)
    return row


@router.delete("/{project_id}/hypotheses/{hypothesis_id}", status_code=204)
async def delete_hypothesis(
    project_id: str,
    hypothesis_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    row = await _get_owned_hypothesis(db, project_id, hypothesis_id, user)
    await db.delete(row)
    await db.commit()


# --------------------------------------------------------------------------- #
# Phase C — Datasets.
# A new version is a NEW row (optionally `supersedes_id` → the prior version); never overwritten.
# --------------------------------------------------------------------------- #
@router.get("/{project_id}/datasets", response_model=list[DatasetOut])
async def list_datasets(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    await _get_project(db, project_id, user)
    return (
        await db.execute(
            select(Dataset).where(Dataset.project_id == project_id).order_by(Dataset.created_at)
        )
    ).scalars().all()


@router.post("/{project_id}/datasets", response_model=DatasetOut, status_code=201)
async def create_dataset(
    project_id: str,
    body: DatasetCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    await _get_project(db, project_id, user)
    data = body.model_dump()
    await _validate_object_links(db, project_id, data)  # supersedes_id must be same-project
    row = Dataset(project_id=project_id, **data)
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


async def _get_owned_dataset(db, project_id, dataset_id, user) -> Dataset:
    await _get_project(db, project_id, user)
    row = await db.get(Dataset, dataset_id)
    if row is None or row.project_id != project_id:
        raise HTTPException(404, "Dataset not found")
    return row


@router.get("/{project_id}/datasets/{dataset_id}", response_model=DatasetOut)
async def get_dataset(
    project_id: str,
    dataset_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return await _get_owned_dataset(db, project_id, dataset_id, user)


@router.patch("/{project_id}/datasets/{dataset_id}", response_model=DatasetOut)
async def update_dataset(
    project_id: str,
    dataset_id: str,
    body: DatasetUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    row = await _get_owned_dataset(db, project_id, dataset_id, user)
    changed = body.model_dump(exclude_unset=True)
    await _validate_object_links(db, project_id, changed)
    for field, value in changed.items():
        setattr(row, field, value)
    await db.commit()
    await db.refresh(row)
    return row


@router.delete("/{project_id}/datasets/{dataset_id}", status_code=204)
async def delete_dataset(
    project_id: str,
    dataset_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    row = await _get_owned_dataset(db, project_id, dataset_id, user)
    await db.delete(row)
    await db.commit()


# --------------------------------------------------------------------------- #
# Phase C — Experiments. PLANNED ≠ EXECUTED: create never accepts execution fields; execution is
# recorded only by an explicit PATCH. The API never fabricates measurements/timestamps/outcomes.
# --------------------------------------------------------------------------- #
@router.get("/{project_id}/experiments", response_model=list[ExperimentOut])
async def list_experiments(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    await _get_project(db, project_id, user)
    return (
        await db.execute(
            select(Experiment).where(Experiment.project_id == project_id)
            .order_by(Experiment.created_at)
        )
    ).scalars().all()


@router.post("/{project_id}/experiments", response_model=ExperimentOut, status_code=201)
async def create_experiment(
    project_id: str,
    body: ExperimentCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    await _get_project(db, project_id, user)
    data = body.model_dump()
    await _validate_object_links(db, project_id, data)
    row = Experiment(project_id=project_id, **data)  # execution fields stay null (not in create schema)
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


async def _get_owned_experiment(db, project_id, experiment_id, user) -> Experiment:
    await _get_project(db, project_id, user)
    row = await db.get(Experiment, experiment_id)
    if row is None or row.project_id != project_id:
        raise HTTPException(404, "Experiment not found")
    return row


@router.get("/{project_id}/experiments/{experiment_id}", response_model=ExperimentOut)
async def get_experiment(
    project_id: str,
    experiment_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return await _get_owned_experiment(db, project_id, experiment_id, user)


@router.patch("/{project_id}/experiments/{experiment_id}", response_model=ExperimentOut)
async def update_experiment(
    project_id: str,
    experiment_id: str,
    body: ExperimentUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    row = await _get_owned_experiment(db, project_id, experiment_id, user)
    changed = body.model_dump(exclude_unset=True)
    await _validate_object_links(db, project_id, changed)
    for field, value in changed.items():
        setattr(row, field, value)
    await db.commit()
    await db.refresh(row)
    return row


@router.delete("/{project_id}/experiments/{experiment_id}", status_code=204)
async def delete_experiment(
    project_id: str,
    experiment_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    row = await _get_owned_experiment(db, project_id, experiment_id, user)
    # Delete this experiment's results explicitly (SQLite doesn't enforce FK cascade; the codebase
    # deletes children explicitly — cf. verification deleting ClaimSource before claims).
    await db.execute(sa_delete(Result).where(Result.experiment_id == experiment_id))
    await db.delete(row)
    await db.commit()


# --------------------------------------------------------------------------- #
# Phase C — structured Results. A Result exists only when explicitly recorded and MUST attribute to
# an experiment in the same project (validated). Numeric fields stay null unless supplied.
# --------------------------------------------------------------------------- #
@router.get("/{project_id}/results", response_model=list[ResultOut])
async def list_results(
    project_id: str,
    experiment_id: str | None = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    await _get_project(db, project_id, user)
    stmt = select(Result).where(Result.project_id == project_id)
    if experiment_id:
        stmt = stmt.where(Result.experiment_id == experiment_id)
    return (await db.execute(stmt.order_by(Result.created_at))).scalars().all()


@router.post("/{project_id}/results", response_model=ResultOut, status_code=201)
async def create_result(
    project_id: str,
    body: ResultCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    await _get_project(db, project_id, user)
    data = body.model_dump()
    await _validate_object_links(db, project_id, data)  # experiment_id + dataset_id → same project
    # metrics are structured dicts (ResultMetric); persisted as JSON as-is.
    row = Result(project_id=project_id, **data)
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


async def _get_owned_result(db, project_id, result_id, user) -> Result:
    await _get_project(db, project_id, user)
    row = await db.get(Result, result_id)
    if row is None or row.project_id != project_id:
        raise HTTPException(404, "Result not found")
    return row


@router.get("/{project_id}/results/{result_id}", response_model=ResultOut)
async def get_result(
    project_id: str,
    result_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return await _get_owned_result(db, project_id, result_id, user)


@router.patch("/{project_id}/results/{result_id}", response_model=ResultOut)
async def update_result(
    project_id: str,
    result_id: str,
    body: ResultUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    row = await _get_owned_result(db, project_id, result_id, user)
    changed = body.model_dump(exclude_unset=True)
    await _validate_object_links(db, project_id, changed)
    for field, value in changed.items():
        setattr(row, field, value)
    await db.commit()
    await db.refresh(row)
    return row


@router.delete("/{project_id}/results/{result_id}", status_code=204)
async def delete_result(
    project_id: str,
    result_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    row = await _get_owned_result(db, project_id, result_id, user)
    await db.delete(row)
    await db.commit()

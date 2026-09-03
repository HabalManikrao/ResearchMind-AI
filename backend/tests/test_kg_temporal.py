"""Temporal knowledge: supersession, current-vs-historical, disputed (#7, spec §13, §14, §38).

Reconciliation consumes the existing Research Diff — no second diff engine. Seed a parent
run + a continuation with matching claims, build both graphs, reconcile, and assert the
temporal transitions.
"""
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.knowledge import graph as kg
from app.models import (
    Claim,
    ClaimStatus,
    KgClaimLink,
    KgEntity,
    KgRelationship,
    Recommendation,
    ResearchProject,
    Solution,
    Source,
)
from app.models.enums import ProjectStatus
from app.models.graph import DISPUTED


def _now():
    return datetime.now(timezone.utc)


async def _run(db, *, user_id="u1", root_id=None, parent_id=None, run_number=1,
               solutions, claims, completed_delta_min=0):
    """Seed one completed run. claims: list of (text, status, conf, meta)."""
    proj = ResearchProject(
        user_id=user_id, title="Lumen research", query="lumen",
        objective="evaluate lumen", status=ProjectStatus.COMPLETED,
        completed_at=_now() + timedelta(minutes=completed_delta_min),
        parent_id=parent_id, run_number=run_number, run_intent="original" if not parent_id else "refresh",
    )
    db.add(proj)
    await db.flush()
    proj.root_id = root_id or proj.id
    src = Source(project_id=proj.id, title="src", url="https://a.example/x",
                 source_type="web", reliability_score=80.0)
    db.add(src)
    await db.flush()
    for name in solutions:
        db.add(Solution(project_id=proj.id, name=name, description=f"{name} d"))
    for text, status, conf, meta in claims:
        db.add(Claim(project_id=proj.id, text=text, status=status, confidence=conf,
                     supporting_source_ids=[src.id], confidence_meta=meta or {}))
    await db.commit()
    return proj


async def test_supersession_and_current_vs_historical(db):
    parent = await _run(
        db, solutions=["Lumen"],
        claims=[("Lumen performs reliably under load.", ClaimStatus.VERIFIED, 82.0, {})],
    )
    child = await _run(
        db, root_id=parent.root_id, parent_id=parent.id, run_number=2,
        solutions=["Lumen"],
        claims=[("Lumen performs reliably under load.", ClaimStatus.PARTIALLY_VERIFIED, 55.0,
                 {"support_count": 1})],
        completed_delta_min=10,
    )
    await kg.build_graph_for_project(parent.id)
    await kg.build_graph_for_project(child.id)
    recon = await kg.reconcile_from_diff(parent.id, child.id)
    assert recon["superseded"] >= 1

    # A SUPERSEDES link: new claim supersedes the old.
    old_claim = (await db.execute(
        select(Claim).where(Claim.project_id == parent.id))).scalars().first()
    new_claim = (await db.execute(
        select(Claim).where(Claim.project_id == child.id))).scalars().first()
    link = (await db.execute(select(KgClaimLink).where(
        KgClaimLink.predicate == "supersedes"))).scalars().first()
    assert link.subject_claim_id == new_claim.id
    assert link.object_claim_id == old_claim.id

    # The old claim is now historical (superseded); the new one is current.
    superseded = await kg.superseded_claim_ids(db, "u1")
    assert old_claim.id in superseded
    assert new_claim.id not in superseded


async def test_reconcile_is_idempotent(db):
    parent = await _run(db, solutions=["Lumen"],
                        claims=[("Lumen is fast.", ClaimStatus.VERIFIED, 80.0, {})])
    child = await _run(db, root_id=parent.root_id, parent_id=parent.id, run_number=2,
                       solutions=["Lumen"],
                       claims=[("Lumen is fast.", ClaimStatus.VERIFIED, 78.0, {})],
                       completed_delta_min=10)
    await kg.reconcile_from_diff(parent.id, child.id)
    await kg.reconcile_from_diff(parent.id, child.id)  # again
    links = (await db.execute(select(KgClaimLink))).scalars().all()
    assert len(links) == 1  # no duplicate supersession


async def test_contradiction_disputes_derived_relationship(db):
    claim_text = "Lumen performs reliably on GPU."
    parent = await _run(
        db, solutions=["Lumen", "GPU"],
        claims=[(claim_text, ClaimStatus.VERIFIED, 80.0, {})],
    )
    child = await _run(
        db, root_id=parent.root_id, parent_id=parent.id, run_number=2,
        solutions=["Lumen", "GPU"],
        claims=[(claim_text, ClaimStatus.CONFLICTED, 40.0, {"contradiction_count": 1})],
        completed_delta_min=10,
    )
    await kg.build_graph_for_project(parent.id)
    await kg.build_graph_for_project(child.id)
    recon = await kg.reconcile_from_diff(parent.id, child.id)
    assert recon["disputed"] >= 1

    # The Lumen↔GPU relationship derived from the now-contradicted claim is DISPUTED.
    rel = (await db.execute(
        select(KgRelationship).where(KgRelationship.predicate == "related_to")
    )).scalars().first()
    assert rel is not None and rel.status == DISPUTED


async def test_disputed_is_derived_from_verification(db):
    # claim_is_disputed reads existing verification, not a new engine (spec §9, §14).
    conflicted = Claim(project_id="p", text="x", status=ClaimStatus.CONFLICTED,
                       confidence=30.0, confidence_meta={})
    contradicted = Claim(project_id="p", text="y", status=ClaimStatus.VERIFIED,
                         confidence=60.0, confidence_meta={"contradiction_count": 2})
    clean = Claim(project_id="p", text="z", status=ClaimStatus.VERIFIED,
                  confidence=90.0, confidence_meta={})
    assert kg.claim_is_disputed(conflicted) is True
    assert kg.claim_is_disputed(contradicted) is True
    assert kg.claim_is_disputed(clean) is False

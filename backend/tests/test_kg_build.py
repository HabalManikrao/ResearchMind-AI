"""Knowledge-graph build + deterministic extraction (#7, spec §5-§19).

DB-level (no network, no LLM): seed a completed project's structured rows (Solutions,
Claims, Recommendation, Sources) and assert the graph build produces normalized entities,
claim/source/run mentions, and derived relationships — idempotently.
"""
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from app.knowledge import graph as kg
from app.knowledge.graph import normalize_name
from app.models import (
    Claim,
    ClaimStatus,
    KgEntity,
    KgMention,
    KgRelationship,
    Recommendation,
    ResearchProject,
    Solution,
    Source,
)
from app.models.enums import ProjectStatus


def _now():
    return datetime.now(timezone.utc)


async def _seed(db, *, user_id="u1", solutions, claims, recommended=None):
    proj = ResearchProject(
        user_id=user_id, title="Game engines", query="best game engine",
        objective="compare game engines", status=ProjectStatus.COMPLETED,
        completed_at=_now(), root_id=None, run_number=1, run_intent="original",
    )
    db.add(proj)
    await db.flush()
    proj.root_id = proj.id

    src = Source(project_id=proj.id, title="A source", url="https://a.example/x",
                 source_type="web", reliability_score=80.0)
    db.add(src)
    await db.flush()

    for name in solutions:
        db.add(Solution(project_id=proj.id, name=name, description=f"{name} desc",
                        is_recommended=(name == recommended)))
    for text in claims:
        db.add(Claim(project_id=proj.id, text=text, status=ClaimStatus.VERIFIED,
                     confidence=80.0, supporting_source_ids=[src.id], confidence_meta={}))
    if recommended:
        db.add(Recommendation(project_id=proj.id, recommended_option=recommended,
                              rationale="best", confidence=85.0))
    await db.commit()
    return proj.id, src.id


async def _entities(db, user_id="u1"):
    return (await db.execute(select(KgEntity).where(KgEntity.user_id == user_id))).scalars().all()


# --------------------------------------------------------------------------- #
# Normalization
# --------------------------------------------------------------------------- #
def test_normalize_name():
    assert normalize_name("  Unreal   Engine 5 ") == "unreal engine 5"
    assert normalize_name("Unreal Engine 5.") == "unreal engine 5"
    assert normalize_name("(Nanite)") == "nanite"
    assert normalize_name("C++") == "c++"  # inner punctuation preserved


# --------------------------------------------------------------------------- #
# Entities from structured data (Tier 1, no LLM)
# --------------------------------------------------------------------------- #
async def test_build_creates_entities_from_solutions_and_recommendation(db):
    pid, _ = await _seed(
        db, solutions=["Unreal Engine 5", "Unity", "Godot"],
        claims=["Unreal Engine 5 improves Nanite performance."],
        recommended="Unreal Engine 5",
    )
    result = await kg.build_graph_for_project(pid)
    assert result["state"] == "ok"

    ents = await _entities(db)
    names = {e.canonical_name for e in ents}
    assert {"Unreal Engine 5", "Unity", "Godot"} <= names
    for e in ents:
        assert e.entity_type == "technology"
        assert e.mention_count >= 1


async def test_claim_entity_and_source_mentions(db):
    pid, sid = await _seed(
        db, solutions=["Unreal Engine 5", "Nanite"],
        claims=["Unreal Engine 5 improves Nanite performance on modern GPUs."],
        recommended="Unreal Engine 5",
    )
    await kg.build_graph_for_project(pid)
    ents = {e.canonical_name: e for e in await _entities(db)}
    ue5 = ents["Unreal Engine 5"]

    claim_mentions = (
        await db.execute(
            select(KgMention).where(KgMention.entity_id == ue5.id,
                                    KgMention.target_type == "claim")
        )
    ).scalars().all()
    assert len(claim_mentions) == 1  # entity linked to the EXISTING claim, not duplicated

    source_mentions = (
        await db.execute(
            select(KgMention).where(KgMention.entity_id == ue5.id,
                                    KgMention.target_type == "source")
        )
    ).scalars().all()
    assert source_mentions and source_mentions[0].target_id == sid


async def test_co_occurrence_and_alternative_relationships(db):
    pid, _ = await _seed(
        db, solutions=["Unreal Engine 5", "Nanite", "Unity"],
        claims=["Unreal Engine 5 pairs with Nanite for detailed geometry."],
        recommended="Unreal Engine 5",
    )
    await kg.build_graph_for_project(pid)
    rels = (await db.execute(select(KgRelationship))).scalars().all()
    preds = {r.predicate for r in rels}
    # UE5 & Nanite co-occur in a claim → related_to; the three solutions → alternative_to.
    assert "related_to" in preds
    assert "alternative_to" in preds
    for r in rels:
        assert r.provenance_kind in ("derived", "explicit")
        assert 0.0 <= r.confidence <= 1.0


# --------------------------------------------------------------------------- #
# Conservative resolution (spec §6, §39) + idempotency (§19)
# --------------------------------------------------------------------------- #
async def test_similar_names_are_not_merged(db):
    pid, _ = await _seed(
        db, solutions=["Apple", "Apple Inc.", "Apple Records"],
        claims=["Apple builds hardware."],
    )
    await kg.build_graph_for_project(pid)
    names = {e.canonical_name for e in await _entities(db)}
    # Three distinct entities — never auto-merged on name similarity alone.
    assert {"Apple", "Apple Inc.", "Apple Records"} <= names


async def test_build_is_idempotent(db):
    pid, _ = await _seed(
        db, solutions=["Unreal Engine 5", "Unity"],
        claims=["Unreal Engine 5 is popular."], recommended="Unreal Engine 5",
    )
    r1 = await kg.build_graph_for_project(pid)
    n_entities_1 = len(await _entities(db))
    n_mentions_1 = len((await db.execute(select(KgMention))).scalars().all())
    n_rels_1 = len((await db.execute(select(KgRelationship))).scalars().all())

    r2 = await kg.build_graph_for_project(pid)  # re-run
    assert len(await _entities(db)) == n_entities_1
    assert len((await db.execute(select(KgMention))).scalars().all()) == n_mentions_1
    assert len((await db.execute(select(KgRelationship))).scalars().all()) == n_rels_1
    assert r1["state"] == r2["state"] == "ok"


async def test_disabled_flag_skips_build(db, monkeypatch):
    from app.config import get_settings
    monkeypatch.setattr(get_settings(), "knowledge_graph_enabled", False)
    pid, _ = await _seed(db, solutions=["Unity"], claims=["Unity is a game engine."])
    result = await kg.build_graph_for_project(pid)
    assert result["state"] == "skipped"
    assert await _entities(db) == []

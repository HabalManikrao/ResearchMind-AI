"""Knowledge-graph build / extraction / temporal reconciliation service (#7).

Builds a persistent, evidence-backed entity graph **from existing structured data** — a
normal run adds no LLM calls (spec §2, §16, §19). Entity resolution is conservative
(§6, §39); temporal transitions reuse the existing Research Diff (§14, §38); every fact
references real claim/source/run ids (no copied passages, §15). All operations are
best-effort at the call site: a graph failure must never fail a research run (§20, §32).
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

from sqlalchemy import select

from app.config import get_settings
from app.database import SessionLocal
from app.knowledge import registry
from app.models import (
    Claim,
    ClaimStatus,
    KgClaimLink,
    KgEntity,
    KgMention,
    KgRelationship,
    Recommendation,
    ResearchProject,
    Solution,
    Source,
)
from app.models.graph import ACTIVE, DERIVED, DISPUTED, EXPLICIT, INFERRED, SUPERSEDED
from app.services import research_diff

log = logging.getLogger("researchmind.graph")

_WS = re.compile(r"\s+")
_EDGE_PUNCT = re.compile(r"^[\s\-–—:;,.\"'()\[\]]+|[\s\-–—:;,.\"'()\[\]]+$")


def _now() -> datetime:
    return datetime.now(timezone.utc)


# --------------------------------------------------------------------------- #
# Normalization + matching (spec §6)
# --------------------------------------------------------------------------- #
def normalize_name(name: str) -> str:
    """Trim → collapse whitespace → casefold → strip surrounding punctuation. Inner
    punctuation (``.``/``+``) is preserved so ``C++`` / ``Unreal Engine 5`` survive."""
    if not name:
        return ""
    s = _WS.sub(" ", name).strip()
    s = _EDGE_PUNCT.sub("", s)
    return s.casefold().strip()


def _name_in_text(normalized_name: str, normalized_text: str) -> bool:
    """Whole-token containment (non-word boundaries), safe for names with punctuation."""
    if len(normalized_name) < get_settings().kg_min_entity_length:
        return False
    pattern = r"(?<!\w)" + re.escape(normalized_name) + r"(?!\w)"
    return re.search(pattern, normalized_text) is not None


# --------------------------------------------------------------------------- #
# Entity resolution (conservative — spec §6, §39)
# --------------------------------------------------------------------------- #
async def _resolve_or_create_entity(
    db, cache: dict, *, user_id, name: str, entity_type: str,
    observed_at: datetime, description: str | None = None,
) -> KgEntity | None:
    """Match an entity by (user_id, normalized_name, entity_type) or create a new one.
    NEVER merges two entities by name similarity alone (spec §39)."""
    norm = normalize_name(name)
    etype = registry.normalize_entity_type(entity_type)
    if len(norm) < get_settings().kg_min_entity_length:
        return None
    key = (norm, etype)
    if key in cache:
        return cache[key]

    stmt = select(KgEntity).where(
        KgEntity.normalized_name == norm, KgEntity.entity_type == etype
    )
    stmt = stmt.where(KgEntity.user_id == user_id) if user_id is not None \
        else stmt.where(KgEntity.user_id.is_(None))
    entity = (await db.execute(stmt)).scalars().first()

    if entity is None:
        entity = KgEntity(
            user_id=user_id, canonical_name=name.strip(), normalized_name=norm,
            entity_type=etype, description=description, aliases=[], meta={},
            mention_count=0, first_observed_at=observed_at, last_observed_at=observed_at,
        )
        db.add(entity)
        await db.flush()
    else:
        # Same identity re-observed. Keep a display alias if the surface form differs;
        # never fuzzy-merge distinct identities.
        display = name.strip()
        if display and display != entity.canonical_name and display not in (entity.aliases or []):
            entity.aliases = [*(entity.aliases or []), display]
        if description and not entity.description:
            entity.description = description
        entity.last_observed_at = observed_at
    cache[key] = entity
    return entity


async def _add_mention(
    db, seen: set, *, user_id, entity: KgEntity, target_type: str, target_id: str,
    project_id: str | None, role: str, provenance_kind: str = DERIVED, confidence: float = 1.0,
) -> bool:
    """Add an entity↔target provenance edge (deduped within this build). Returns True if new."""
    dk = (entity.id, target_type, target_id, project_id)
    if dk in seen:
        return False
    seen.add(dk)
    exists = (
        await db.execute(
            select(KgMention.id)
            .where(KgMention.entity_id == entity.id)
            .where(KgMention.target_type == target_type)
            .where(KgMention.target_id == target_id)
            .where(KgMention.project_id == project_id)
        )
    ).first()
    if exists:
        return False
    db.add(KgMention(
        user_id=user_id, entity_id=entity.id, target_type=target_type, target_id=target_id,
        project_id=project_id, role=role, provenance_kind=provenance_kind, confidence=confidence,
    ))
    entity.mention_count = (entity.mention_count or 0) + 1
    return True


async def _upsert_relationship(
    db, *, user_id, subject: KgEntity, predicate: str, obj: KgEntity,
    observed_at: datetime, confidence: float, provenance_kind: str,
    project_id: str | None = None, claim_id: str | None = None,
    source_id: str | None = None, description: str | None = None,
) -> KgRelationship | None:
    if subject.id == obj.id:
        return None
    pred = registry.normalize_predicate(predicate)
    existing = (
        await db.execute(
            select(KgRelationship)
            .where(KgRelationship.subject_entity_id == subject.id)
            .where(KgRelationship.predicate == pred)
            .where(KgRelationship.object_entity_id == obj.id)
        )
    ).scalars().first()
    if existing is not None:
        existing.last_observed_at = observed_at
        # A re-observation only raises confidence; provenance is upgraded, never downgraded.
        existing.confidence = max(existing.confidence, confidence)
        if provenance_kind == EXPLICIT:
            existing.provenance_kind = EXPLICIT
        return existing
    rel = KgRelationship(
        user_id=user_id, subject_entity_id=subject.id, predicate=pred,
        object_entity_id=obj.id, description=description, confidence=confidence,
        provenance_kind=provenance_kind, status=ACTIVE, valid_from=observed_at,
        first_observed_at=observed_at, last_observed_at=observed_at,
        project_id=project_id, claim_id=claim_id, source_id=source_id,
    )
    db.add(rel)
    await db.flush()
    return rel


async def _add_claim_link(
    db, *, user_id, subject_claim_id: str, predicate: str, object_claim_id: str,
    project_id: str | None, confidence: float, provenance_kind: str = DERIVED,
) -> bool:
    if subject_claim_id == object_claim_id:
        return False
    exists = (
        await db.execute(
            select(KgClaimLink.id)
            .where(KgClaimLink.subject_claim_id == subject_claim_id)
            .where(KgClaimLink.predicate == predicate)
            .where(KgClaimLink.object_claim_id == object_claim_id)
        )
    ).first()
    if exists:
        return False
    db.add(KgClaimLink(
        user_id=user_id, subject_claim_id=subject_claim_id, predicate=predicate,
        object_claim_id=object_claim_id, project_id=project_id, confidence=confidence,
        provenance_kind=provenance_kind,
    ))
    return True


# --------------------------------------------------------------------------- #
# Build (incremental, idempotent) — spec §19, §20
# --------------------------------------------------------------------------- #
async def build_graph_for_project(project_id: str) -> dict:
    """Build/update the graph for one completed run from its structured rows. Idempotent:
    re-running upserts without creating duplicates. Returns {state, entities, relationships}."""
    settings = get_settings()
    if not settings.knowledge_graph_enabled:
        return {"state": "skipped", "entities": 0, "relationships": 0}

    async with SessionLocal() as db:
        proj = await db.get(ResearchProject, project_id)
        if proj is None:
            return {"state": "skipped", "entities": 0, "relationships": 0}
        user_id = proj.user_id
        observed_at = proj.completed_at or _now()
        solutions = (
            await db.execute(select(Solution).where(Solution.project_id == project_id))
        ).scalars().all()
        rec = (
            await db.execute(
                select(Recommendation).where(Recommendation.project_id == project_id)
            )
        ).scalars().first()
        claims = (
            await db.execute(select(Claim).where(Claim.project_id == project_id))
        ).scalars().all()
        sources = (
            await db.execute(select(Source).where(Source.project_id == project_id))
        ).scalars().all()

        cache: dict = {}
        mention_seen: set = set()
        entity_ids: set[str] = set()
        src_ids = {s.id for s in sources}

        # --- Tier 1: entities from Solutions (already-extracted tech/approach names) --- #
        solution_entities: list[KgEntity] = []
        for sol in solutions:
            ent = await _resolve_or_create_entity(
                db, cache, user_id=user_id, name=sol.name, entity_type="technology",
                observed_at=observed_at, description=(sol.description or None),
            )
            if ent is None:
                continue
            solution_entities.append(ent)
            entity_ids.add(ent.id)
            await _add_mention(
                db, mention_seen, user_id=user_id, entity=ent, target_type="project",
                target_id=project_id, project_id=project_id, role="about",
                provenance_kind=EXPLICIT,
            )

        # --- Recommendation's chosen option is an explicit entity. --- #
        if rec and rec.recommended_option:
            rec_ent = await _resolve_or_create_entity(
                db, cache, user_id=user_id, name=rec.recommended_option,
                entity_type="technology", observed_at=observed_at,
            )
            if rec_ent is not None:
                entity_ids.add(rec_ent.id)
                await _add_mention(
                    db, mention_seen, user_id=user_id, entity=rec_ent, target_type="project",
                    target_id=project_id, project_id=project_id, role="recommended",
                    provenance_kind=EXPLICIT,
                )

        # --- Claim ↔ entity (deterministic substring) + entity ↔ source. --- #
        known = list(cache.values())
        for c in claims:
            ctext = normalize_name(c.text)
            mentioned: list[KgEntity] = []
            for ent in known:
                if _name_in_text(ent.normalized_name, ctext):
                    mentioned.append(ent)
                    await _add_mention(
                        db, mention_seen, user_id=user_id, entity=ent, target_type="claim",
                        target_id=c.id, project_id=project_id, role="mentions",
                    )
                    for sid in (c.supporting_source_ids or [])[:5]:
                        if sid in src_ids:
                            await _add_mention(
                                db, mention_seen, user_id=user_id, entity=ent,
                                target_type="source", target_id=sid, project_id=project_id,
                                role="mentioned_in",
                            )
            # RELATED_TO for entities co-occurring in one claim (DERIVED, spec §17).
            for i in range(len(mentioned)):
                for j in range(i + 1, len(mentioned)):
                    await _upsert_relationship(
                        db, user_id=user_id, subject=mentioned[i], predicate="related_to",
                        obj=mentioned[j], observed_at=observed_at, confidence=0.5,
                        provenance_kind=DERIVED, project_id=project_id, claim_id=c.id,
                    )

        # --- ALTERNATIVE_TO among all solutions compared in this run (DERIVED). --- #
        for i in range(len(solution_entities)):
            for j in range(i + 1, len(solution_entities)):
                await _upsert_relationship(
                    db, user_id=user_id, subject=solution_entities[i],
                    predicate="alternative_to", obj=solution_entities[j],
                    observed_at=observed_at, confidence=0.6, provenance_kind=DERIVED,
                    project_id=project_id, description="considered in the same research",
                )

        # --- Tier 2: bounded, optional LLM entity extraction (off by default). --- #
        if settings.kg_llm_extraction_enabled and claims:
            try:
                extra = await _llm_extract_entities([c.text for c in claims])
                for name, etype in extra:
                    ent = await _resolve_or_create_entity(
                        db, cache, user_id=user_id, name=name, entity_type=etype,
                        observed_at=observed_at,
                    )
                    if ent is not None:
                        entity_ids.add(ent.id)
                        await _add_mention(
                            db, mention_seen, user_id=user_id, entity=ent,
                            target_type="project", target_id=project_id,
                            project_id=project_id, role="about", provenance_kind=INFERRED,
                        )
            except Exception:  # noqa: BLE001 - LLM tier is optional; never fail the build
                log.warning("KG LLM extraction failed for %s", project_id, exc_info=False)

        n_rel = (
            await db.execute(
                select(KgRelationship).where(KgRelationship.project_id == project_id)
            )
        ).scalars().all()
        await db.commit()
        return {"state": "ok", "entities": len(entity_ids), "relationships": len(n_rel)}


# --------------------------------------------------------------------------- #
# Temporal reconciliation from a Research Diff (spec §14, §21, §22, §38)
# --------------------------------------------------------------------------- #
async def reconcile_from_diff(old_id: str, new_id: str) -> dict:
    """Consume the existing Research Diff to create knowledge transitions: a new run's claim
    SUPERSEDES the matching prior claim; relationships derived from a now-contradicted claim
    become DISPUTED. Reuses ``research_diff`` — no second diff engine (spec §38)."""
    settings = get_settings()
    if not settings.knowledge_graph_enabled:
        return {"state": "skipped", "superseded": 0, "disputed": 0}

    diff = await research_diff.diff_runs(old_id, new_id)

    async with SessionLocal() as db:
        new_proj = await db.get(ResearchProject, new_id)
        user_id = new_proj.user_id if new_proj else None
        old_claims = (
            await db.execute(select(Claim).where(Claim.project_id == old_id))
        ).scalars().all()
        new_claims = (
            await db.execute(select(Claim).where(Claim.project_id == new_id))
        ).scalars().all()
        old_by = {normalize_name(c.text): c for c in old_claims}
        new_by = {normalize_name(c.text): c for c in new_claims}

        superseded = 0
        disputed = 0
        for item in diff.claims.get("items", []):
            kind = item.kind
            old_text = item.old_text
            new_text = item.new_text
            if not old_text or not new_text:
                continue  # NEW/REMOVED have no matched pair to supersede
            oc = old_by.get(normalize_name(old_text))
            nc = new_by.get(normalize_name(new_text))
            if not oc or not nc:
                continue
            # The new run's claim supersedes the prior run's matching claim (temporal).
            if await _add_claim_link(
                db, user_id=user_id, subject_claim_id=nc.id, predicate="supersedes",
                object_claim_id=oc.id, project_id=new_id, confidence=0.9,
            ):
                superseded += 1
            # A claim that became contradicted disputes the relationships derived from it.
            if kind == research_diff.CONTRADICTED:
                rels = (
                    await db.execute(
                        select(KgRelationship).where(
                            KgRelationship.claim_id.in_([oc.id, nc.id])
                        )
                    )
                ).scalars().all()
                for r in rels:
                    if r.status != DISPUTED:
                        r.status = DISPUTED
                        disputed += 1

        await db.commit()
        return {"state": "ok", "superseded": superseded, "disputed": disputed}


# --------------------------------------------------------------------------- #
# Tier-2 bounded LLM extraction (optional; strict, schema-validated — spec §16, §17)
# --------------------------------------------------------------------------- #
_ENTITY_SCHEMA = {
    "type": "object",
    "properties": {
        "entities": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "type": {"type": "string"},
                },
                "required": ["name", "type"],
            },
        }
    },
    "required": ["entities"],
}


async def _llm_extract_entities(claim_texts: list[str]) -> list[tuple[str, str]]:
    """One bounded, schema-validated call (INFERRED). Rejects malformed output; never lets
    raw LLM output mutate the graph (spec §17). Returns [(name, type)] capped by config."""
    from app.llm import get_provider

    settings = get_settings()
    texts = [t for t in claim_texts if t.strip()][: settings.kg_llm_max_claims]
    if not texts:
        return []
    corpus = "\n".join(f"- {t}" for t in texts)[:6000]
    system = (
        "Extract distinct named entities (technologies, products, companies, people, "
        "concepts) mentioned in these research claims. Return strict JSON only."
    )
    prompt = f"Claims:\n{corpus}\n\nList the entities with a type from: " + ", ".join(
        sorted(registry.ENTITY_TYPES)
    )
    try:
        out = await get_provider().structured_output(prompt, _ENTITY_SCHEMA, system=system)
    except Exception:  # noqa: BLE001
        return []
    items = (out or {}).get("entities", [])
    result: list[tuple[str, str]] = []
    seen: set[str] = set()
    for it in items:
        if not isinstance(it, dict):
            continue
        name = str(it.get("name", "")).strip()
        etype = registry.normalize_entity_type(str(it.get("type", "")))
        norm = normalize_name(name)
        if len(norm) < settings.kg_min_entity_length or norm in seen:
            continue
        seen.add(norm)
        result.append((name, etype))
        if len(result) >= settings.kg_llm_max_entities:
            break
    return result


# --------------------------------------------------------------------------- #
# Read helpers used by the API (bounded, user-scoped)
# --------------------------------------------------------------------------- #
async def superseded_claim_ids(db, user_id) -> set[str]:
    """Claim ids that have been superseded (→ historical). Scoped to the user."""
    stmt = select(KgClaimLink.object_claim_id).where(KgClaimLink.predicate == "supersedes")
    stmt = stmt.where(KgClaimLink.user_id == user_id) if user_id is not None \
        else stmt.where(KgClaimLink.user_id.is_(None))
    return {r[0] for r in (await db.execute(stmt)).all()}


def claim_is_disputed(claim: Claim) -> bool:
    """Derived from existing verification — never a new contradiction engine (spec §9, §14)."""
    meta = claim.confidence_meta or {}
    return claim.status == ClaimStatus.CONFLICTED or bool(meta.get("contradiction_count"))

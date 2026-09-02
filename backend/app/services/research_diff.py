"""Research Diff engine (#4): deterministic-first comparison of two runs.

Compares two ``ResearchProject`` runs (same lineage) and reports what changed:
sources, claims (evidence-aware), confidence, the recommendation, and document
evidence. The default path makes **zero LLM calls** (spec §25): source/document
matching is by stable identifier, claim matching is normalized-text → token-overlap,
and only the still-ambiguous remainder optionally uses embeddings. Confidence-change
reasons are built from the stored ``confidence_meta`` — never invented (spec §20).

Purely read-only: neither run is modified (spec §26).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from sqlalchemy import select

from app.config import get_settings
from app.database import SessionLocal
from app.llm import get_provider
from app.llm.base import LLMError
from app.models import (
    Claim,
    ClaimSource,
    ClaimStatus,
    Document,
    Recommendation,
    Source,
)
from app.services.dedup import normalize_url

settings = get_settings()

_WORD = re.compile(r"[a-z0-9]+")

# Explicit diff categories (spec §19).
UNCHANGED = "unchanged"
NEW = "new"
REMOVED = "removed"
CHANGED = "changed"
STRENGTHENED = "strengthened"
WEAKENED = "weakened"
CONTRADICTED = "contradicted"


# --------------------------------------------------------------------------- #
# Result shapes
# --------------------------------------------------------------------------- #
@dataclass
class EvidenceItem:
    title: str
    url: str
    source_type: str
    stance: str
    passage: str | None
    page_number: int | None


@dataclass
class SourceDiffItem:
    kind: str
    url: str
    title: str
    source_type: str
    changes: list[str] = field(default_factory=list)


@dataclass
class ClaimDiffItem:
    kind: str
    old_text: str | None
    new_text: str | None
    old_confidence: float | None
    new_confidence: float | None
    confidence_delta: float | None
    direction: str  # up | down | flat | ""
    reason: str
    match_score: float | None  # similarity that produced the match (1.0 = exact/normalized)
    old_evidence: list[EvidenceItem] = field(default_factory=list)
    new_evidence: list[EvidenceItem] = field(default_factory=list)


@dataclass
class DocumentDiffItem:
    kind: str
    document_id: str | None
    filename: str
    changes: list[str] = field(default_factory=list)


@dataclass
class ResearchDiff:
    old_run: dict
    new_run: dict
    sources: dict
    claims: dict
    confidence: dict
    recommendation: dict
    documents: dict


# --------------------------------------------------------------------------- #
# Snapshot loading (read-only)
# --------------------------------------------------------------------------- #
@dataclass
class _ClaimSnap:
    id: str
    text: str
    norm: str
    tokens: set[str]
    status: str
    confidence: float
    support_count: int
    contra_count: int
    freshness: str | None
    evidence: list[EvidenceItem]


def _normalize_text(text: str) -> str:
    return " ".join(_WORD.findall((text or "").lower()))


def _tokens(text: str) -> set[str]:
    return set(_WORD.findall((text or "").lower()))


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


async def _load_claims(project_id: str) -> list[_ClaimSnap]:
    async with SessionLocal() as db:
        claims = (
            await db.execute(select(Claim).where(Claim.project_id == project_id))
        ).scalars().all()
        rows = (
            await db.execute(
                select(ClaimSource, Source)
                .join(Source, ClaimSource.source_id == Source.id)
                .where(ClaimSource.claim_id.in_([c.id for c in claims] or [""]))
            )
        ).all()

    ev_by_claim: dict[str, list[EvidenceItem]] = {}
    for cs, s in rows:
        ev_by_claim.setdefault(cs.claim_id, []).append(
            EvidenceItem(
                title=s.title,
                url=s.url,
                source_type=s.source_type,
                stance=cs.stance.value,
                passage=cs.passage,
                page_number=(s.meta or {}).get("page_number"),
            )
        )

    snaps: list[_ClaimSnap] = []
    for c in claims:
        meta = c.confidence_meta or {}
        ev = ev_by_claim.get(c.id, [])
        support = meta.get("support_count")
        contra = meta.get("contradiction_count")
        if support is None:
            support = sum(1 for e in ev if e.stance == "supports")
        if contra is None:
            contra = sum(1 for e in ev if e.stance == "contradicts")
        snaps.append(
            _ClaimSnap(
                id=c.id,
                text=c.text,
                norm=_normalize_text(c.text),
                tokens=_tokens(c.text),
                status=c.status.value,
                confidence=c.confidence,
                support_count=int(support),
                contra_count=int(contra),
                freshness=meta.get("freshness"),
                evidence=ev,
            )
        )
    return snaps


# --------------------------------------------------------------------------- #
# Claim matching (deterministic-first; optional embeddings) — spec §10
# --------------------------------------------------------------------------- #
async def _match_claims(
    old: list[_ClaimSnap], new: list[_ClaimSnap]
) -> tuple[list[tuple[_ClaimSnap, _ClaimSnap, float]], list[_ClaimSnap], list[_ClaimSnap]]:
    """Returns (matched pairs with score, unmatched_old, unmatched_new)."""
    matched: list[tuple[_ClaimSnap, _ClaimSnap, float]] = []
    old_left = list(old)
    new_left = list(new)

    # 1) exact / normalized text.
    by_norm: dict[str, _ClaimSnap] = {}
    for c in new_left:
        by_norm.setdefault(c.norm, c)
    still_old: list[_ClaimSnap] = []
    used_new: set[str] = set()
    for oc in old_left:
        nc = by_norm.get(oc.norm)
        if nc and nc.id not in used_new:
            matched.append((oc, nc, 1.0))
            used_new.add(nc.id)
        else:
            still_old.append(oc)
    old_left = still_old
    new_left = [c for c in new_left if c.id not in used_new]

    # 2) token-set (Jaccard) near-match, greedy best pair above the floor.
    token_thr = settings.research_diff_token_threshold
    pairs = sorted(
        (
            (_jaccard(oc.tokens, nc.tokens), oc, nc)
            for oc in old_left
            for nc in new_left
        ),
        key=lambda t: t[0],
        reverse=True,
    )
    taken_old: set[str] = set()
    taken_new: set[str] = set()
    for score, oc, nc in pairs:
        if score < token_thr:
            break
        if oc.id in taken_old or nc.id in taken_new:
            continue
        matched.append((oc, nc, round(score, 3)))
        taken_old.add(oc.id)
        taken_new.add(nc.id)
    old_left = [c for c in old_left if c.id not in taken_old]
    new_left = [c for c in new_left if c.id not in taken_new]

    # 3) semantic (optional) on the remainder — one batched embed, offline-safe.
    if old_left and new_left and settings.research_diff_semantic:
        sem = await _semantic_pairs(old_left, new_left)
        taken_old.clear()
        taken_new.clear()
        for score, oc, nc in sem:
            if oc.id in taken_old or nc.id in taken_new:
                continue
            matched.append((oc, nc, round(score, 3)))
            taken_old.add(oc.id)
            taken_new.add(nc.id)
        old_left = [c for c in old_left if c.id not in taken_old]
        new_left = [c for c in new_left if c.id not in taken_new]

    return matched, old_left, new_left


async def _semantic_pairs(
    old: list[_ClaimSnap], new: list[_ClaimSnap]
) -> list[tuple[float, _ClaimSnap, _ClaimSnap]]:
    """Embedding cosine matches above the semantic threshold, best-first. Returns []
    when embeddings are unavailable (offline degradation, spec §25)."""
    try:
        vectors = await get_provider().embed([c.text for c in old] + [c.text for c in new])
    except LLMError:
        return []
    if not vectors or not vectors[0]:
        return []
    ov = vectors[: len(old)]
    nv = vectors[len(old):]
    thr = settings.research_diff_semantic_threshold
    scored: list[tuple[float, _ClaimSnap, _ClaimSnap]] = []
    for i, oc in enumerate(old):
        for j, nc in enumerate(new):
            score = _cosine(ov[i], nv[j])
            if score >= thr:
                scored.append((score, oc, nc))
    scored.sort(key=lambda t: t[0], reverse=True)
    return scored


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


# --------------------------------------------------------------------------- #
# Classification (evidence-aware) — spec §11, §19, §20
# --------------------------------------------------------------------------- #
def _classify(oc: _ClaimSnap, nc: _ClaimSnap) -> tuple[str, str]:
    """Return (kind, reason). Reason is built only from what actually changed."""
    delta = nc.confidence - oc.confidence
    min_delta = settings.research_diff_confidence_delta

    reasons: list[str] = []
    if nc.contra_count != oc.contra_count:
        reasons.append(f"contradictions {oc.contra_count} → {nc.contra_count}")
    if nc.support_count != oc.support_count:
        reasons.append(f"supporting sources {oc.support_count} → {nc.support_count}")
    if nc.freshness and oc.freshness and nc.freshness != oc.freshness:
        reasons.append(f"freshness {oc.freshness} → {nc.freshness}")
    if abs(delta) >= 0.5:
        reasons.append(f"confidence {round(oc.confidence)} → {round(nc.confidence)}")
    reason = "; ".join(reasons)

    newly_contradicted = (nc.contra_count > 0 and oc.contra_count == 0) or (
        nc.status == ClaimStatus.CONFLICTED.value
        and oc.status != ClaimStatus.CONFLICTED.value
    )
    if newly_contradicted:
        return CONTRADICTED, reason or "new contradicting evidence discovered"
    if delta <= -min_delta or nc.support_count < oc.support_count:
        return WEAKENED, reason or "confidence decreased"
    if delta >= min_delta or nc.support_count > oc.support_count:
        return STRENGTHENED, reason or "confidence increased"
    return UNCHANGED, reason


def _direction(old_c: float, new_c: float) -> str:
    d = new_c - old_c
    if d >= settings.research_diff_confidence_delta:
        return "up"
    if d <= -settings.research_diff_confidence_delta:
        return "down"
    return "flat"


# --------------------------------------------------------------------------- #
# Top-level diff
# --------------------------------------------------------------------------- #
async def diff_runs(old_id: str, new_id: str) -> ResearchDiff:
    sources = await _diff_sources(old_id, new_id)
    claims, confidence = await _diff_claims(old_id, new_id)
    recommendation = await _diff_recommendation(old_id, new_id)
    documents = await _diff_documents(old_id, new_id)
    old_run, new_run = await _run_headers(old_id, new_id)
    return ResearchDiff(
        old_run=old_run,
        new_run=new_run,
        sources=sources,
        claims=claims,
        confidence=confidence,
        recommendation=recommendation,
        documents=documents,
    )


async def _run_headers(old_id: str, new_id: str) -> tuple[dict, dict]:
    from app.models import ResearchProject

    async with SessionLocal() as db:
        old = await db.get(ResearchProject, old_id)
        new = await db.get(ResearchProject, new_id)

    def hdr(p) -> dict:
        return {
            "id": p.id,
            "run_number": p.run_number,
            "run_intent": p.run_intent,
            "completed_at": p.completed_at.isoformat() if p.completed_at else None,
        }

    return hdr(old), hdr(new)


async def _diff_sources(old_id: str, new_id: str) -> dict:
    async with SessionLocal() as db:
        old = (
            await db.execute(select(Source).where(Source.project_id == old_id))
        ).scalars().all()
        new = (
            await db.execute(select(Source).where(Source.project_id == new_id))
        ).scalars().all()

    old_by = {normalize_url(s.url): s for s in old}
    new_by = {normalize_url(s.url): s for s in new}
    items: list[SourceDiffItem] = []
    counts = {NEW: 0, REMOVED: 0, UNCHANGED: 0, CHANGED: 0}

    for key, s in new_by.items():
        if key not in old_by:
            counts[NEW] += 1
            items.append(SourceDiffItem(NEW, s.url, s.title, s.source_type))
        else:
            o = old_by[key]
            changes: list[str] = []
            if abs(o.reliability_score - s.reliability_score) >= 1.0:
                changes.append(
                    f"reliability {round(o.reliability_score)} → {round(s.reliability_score)}"
                )
            if o.freshness != s.freshness:
                changes.append(f"freshness {o.freshness} → {s.freshness}")
            # Provenance/availability change (#5, spec §21): live↔cached, stale↔fresh,
            # etc. Built from the actual availability fields — never invented.
            if o.availability != s.availability:
                changes.append(f"availability {o.availability} → {s.availability}")
            if (o.published_date or None) != (s.published_date or None):
                changes.append("publish date changed")
            if changes:
                counts[CHANGED] += 1
                items.append(SourceDiffItem(CHANGED, s.url, s.title, s.source_type, changes))
            else:
                counts[UNCHANGED] += 1
                items.append(SourceDiffItem(UNCHANGED, s.url, s.title, s.source_type))
    for key, s in old_by.items():
        if key not in new_by:
            counts[REMOVED] += 1
            items.append(SourceDiffItem(REMOVED, s.url, s.title, s.source_type))

    return {**counts, "items": items}


async def _diff_claims(old_id: str, new_id: str) -> tuple[dict, dict]:
    old = await _load_claims(old_id)
    new = await _load_claims(new_id)
    matched, unmatched_old, unmatched_new = await _match_claims(old, new)

    items: list[ClaimDiffItem] = []
    counts = {NEW: 0, REMOVED: 0, UNCHANGED: 0, STRENGTHENED: 0, WEAKENED: 0, CONTRADICTED: 0}
    conf = {"increased": 0, "decreased": 0, "unchanged": 0}

    for oc, nc, score in matched:
        kind, reason = _classify(oc, nc)
        counts[kind] += 1
        direction = _direction(oc.confidence, nc.confidence)
        conf["increased" if direction == "up" else "decreased" if direction == "down" else "unchanged"] += 1
        items.append(
            ClaimDiffItem(
                kind=kind,
                old_text=oc.text,
                new_text=nc.text,
                old_confidence=oc.confidence,
                new_confidence=nc.confidence,
                confidence_delta=round(nc.confidence - oc.confidence, 1),
                direction=direction,
                reason=reason,
                match_score=score,
                old_evidence=oc.evidence,
                new_evidence=nc.evidence,
            )
        )
    for nc in unmatched_new:
        counts[NEW] += 1
        items.append(
            ClaimDiffItem(
                kind=NEW, old_text=None, new_text=nc.text, old_confidence=None,
                new_confidence=nc.confidence, confidence_delta=None, direction="",
                reason="new claim", match_score=None, new_evidence=nc.evidence,
            )
        )
    for oc in unmatched_old:
        counts[REMOVED] += 1
        items.append(
            ClaimDiffItem(
                kind=REMOVED, old_text=oc.text, new_text=None, old_confidence=oc.confidence,
                new_confidence=None, confidence_delta=None, direction="",
                reason="claim no longer present", match_score=None, old_evidence=oc.evidence,
            )
        )

    # Order: contradicted → weakened → strengthened → new → removed → unchanged.
    order = {CONTRADICTED: 0, WEAKENED: 1, STRENGTHENED: 2, NEW: 3, REMOVED: 4, UNCHANGED: 5}
    items.sort(key=lambda it: order.get(it.kind, 9))
    return {**counts, "items": items}, conf


async def _diff_recommendation(old_id: str, new_id: str) -> dict:
    async with SessionLocal() as db:
        old = (
            await db.execute(
                select(Recommendation).where(Recommendation.project_id == old_id)
            )
        ).scalars().first()
        new = (
            await db.execute(
                select(Recommendation).where(Recommendation.project_id == new_id)
            )
        ).scalars().first()

    old_opt = (old.recommended_option or "").strip() if old else ""
    new_opt = (new.recommended_option or "").strip() if new else ""
    old_view = {"option": old_opt, "confidence": old.confidence} if old and old_opt else None
    new_view = {"option": new_opt, "confidence": new.confidence} if new and new_opt else None

    if not old_opt and not new_opt:
        kind = UNCHANGED
    elif old_opt and not new_opt:
        kind = REMOVED
    elif new_opt and not old_opt:
        kind = NEW
    elif _normalize_text(old_opt) != _normalize_text(new_opt):
        kind = "reversed"
    elif old and new and (
        _normalize_text(old.rationale) != _normalize_text(new.rationale)
        or abs(old.confidence - new.confidence) >= settings.research_diff_confidence_delta
    ):
        kind = "modified"
    else:
        kind = UNCHANGED
    return {"kind": kind, "old": old_view, "new": new_view}


async def _diff_documents(old_id: str, new_id: str) -> dict:
    """Compare document evidence between runs, keyed by the underlying document
    (identity + checksum). Only documents that actually contributed evidence, and
    documents carried into the run, are considered (spec §13)."""
    async with SessionLocal() as db:
        old_docs = (
            await db.execute(select(Document).where(Document.project_id == old_id))
        ).scalars().all()
        new_docs = (
            await db.execute(select(Document).where(Document.project_id == new_id))
        ).scalars().all()

    # Key documents by (original_filename, checksum) so the same file across runs
    # (carried forward → identical checksum) matches; a re-uploaded changed file
    # (same name, new checksum) shows as changed.
    def by_name(docs):
        out: dict[str, list[Document]] = {}
        for d in docs:
            out.setdefault(d.original_filename, []).append(d)
        return out

    old_by = by_name(old_docs)
    new_by = by_name(new_docs)
    items: list[DocumentDiffItem] = []
    counts = {NEW: 0, REMOVED: 0, UNCHANGED: 0, CHANGED: 0}

    for name, ds in new_by.items():
        nd = ds[0]
        if name not in old_by:
            counts[NEW] += 1
            items.append(DocumentDiffItem(NEW, nd.id, name))
        else:
            od = old_by[name][0]
            if od.checksum != nd.checksum:
                counts[CHANGED] += 1
                items.append(DocumentDiffItem(CHANGED, nd.id, name, ["checksum changed"]))
            else:
                counts[UNCHANGED] += 1
                items.append(DocumentDiffItem(UNCHANGED, nd.id, name))
    for name, ds in old_by.items():
        if name not in new_by:
            counts[REMOVED] += 1
            items.append(DocumentDiffItem(REMOVED, ds[0].id, name))

    return {**counts, "items": items}

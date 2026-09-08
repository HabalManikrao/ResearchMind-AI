"""Verification Agent (spec §6).

Synthesises key claims from the collected findings and assigns each an
evidence-based status and confidence. Status/confidence are computed
deterministically — the LLM only clusters findings into claims and flags
apparent contradictions (spec rule §23.4: never trust a single source).

The confidence model is transparent and inspectable. It combines:
- **source count** — a claim needs >= 2 distinct sources to be VERIFIED;
- **source reliability** — authority/relevance from `services.scoring`;
- **recency** — fresher supporting evidence counts for more (`services.freshness`);
- **contradiction** — disconfirming evidence (from the active contradiction
  search) lowers confidence and can flip a claim to CONFLICTED.

Every claim carries a ``confidence_meta`` breakdown (counts, average
reliability, aggregate freshness, and human-readable reasons) so the UI can
explain *why* a claim has the confidence it does.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from app.llm.base import AIProvider
from app.models.enums import ClaimStatus, EvidenceStance
from app.services.freshness import (
    AGING,
    FRESH,
    FRESHNESS_WEIGHT,
    STALE,
    UNKNOWN,
    freshness_state,
)

_CLAIMS_SCHEMA = {
    "type": "object",
    "properties": {
        "claims": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "source_indices": {"type": "array", "items": {"type": "integer"}},
                    "conflicting": {"type": "boolean"},
                },
                "required": ["text", "source_indices"],
            },
        }
    },
    "required": ["claims"],
}

_SYSTEM = (
    "You consolidate research findings into a set of distinct, verifiable claims. "
    "Each claim references the indices of the sources that support it. If sources "
    "disagree on a point, emit the claim with conflicting=true. Do not invent "
    "claims that are not grounded in the provided findings."
)


@dataclass
class EvidenceSource:
    index: int
    source_id: str
    url: str
    reliability: float
    published_date: str | None = None
    source_type: str = "web"


@dataclass
class ClaimEvidence:
    """One evidence edge: a source and the quoted passage bearing on the claim."""

    source_id: str
    passage: str = ""
    stance: str = EvidenceStance.SUPPORTS.value


@dataclass
class VerifiedClaim:
    text: str
    status: ClaimStatus
    confidence: float
    evidence: list[ClaimEvidence] = field(default_factory=list)
    confidence_meta: dict = field(default_factory=dict)

    @property
    def supporting_source_ids(self) -> list[str]:
        return [
            e.source_id
            for e in self.evidence
            if e.stance == EvidenceStance.SUPPORTS.value
        ]


def score_claim(
    supporting: list[EvidenceSource],
    contradicting: list[EvidenceSource] | tuple = (),
    *,
    conflicting: bool = False,
    as_of: date | None = None,
) -> tuple[ClaimStatus, float, dict]:
    """Compute (status, confidence, breakdown) for a claim from its evidence.

    Inputs used: distinct supporting source count, mean supporting reliability,
    recency of supporting evidence, and count of contradicting sources. Returns a
    ``confidence_meta`` dict explaining the result.
    """
    contradicting = list(contradicting)
    if not supporting:
        return (
            ClaimStatus.INSUFFICIENT_EVIDENCE,
            0.0,
            {
                "support_count": 0,
                "contradiction_count": len(contradicting),
                "avg_reliability": 0.0,
                "freshness": UNKNOWN,
                "outdated": False,
                "reasons": ["No supporting evidence was found for this claim."],
            },
        )

    n = len(supporting)
    n_contra = len(contradicting)
    avg_rel = sum(s.reliability for s in supporting) / n

    # --- Recency ----------------------------------------------------------- #
    states = [
        freshness_state(s.published_date, s.source_type, as_of=as_of)
        for s in supporting
    ]
    fresh_mean = sum(FRESHNESS_WEIGHT[st] for st in states) / n
    known = [st for st in states if st != UNKNOWN]
    if known:
        stale_known = sum(1 for st in known if st == STALE)
        # A claim is "outdated" only when *more than half* of its dated evidence is stale.
        # A tie (e.g. one fresh + one stale authoritative source) is NOT outdated — a fresh
        # source still supporting the claim means it is currently established, not merely
        # historically true (#10 evaluation finding: the old `>= (n+1)//2` rounded a 1-1 split
        # up to "majority", over-flagging current claims as outdated).
        outdated = stale_known > len(known) / 2
        km = sum(FRESHNESS_WEIGHT[st] for st in known) / len(known)
        aggregate_freshness = FRESH if km >= 0.85 else (AGING if km >= 0.45 else STALE)
    else:
        outdated = False
        aggregate_freshness = UNKNOWN

    # --- Status ------------------------------------------------------------ #
    conflicting_effective = conflicting or n_contra > 0
    if conflicting_effective:
        status = ClaimStatus.CONFLICTED
    elif n >= 2 and avg_rel >= 80:
        status = ClaimStatus.VERIFIED
    elif n >= 2:
        status = ClaimStatus.PARTIALLY_VERIFIED
    elif avg_rel >= 85:
        status = ClaimStatus.PARTIALLY_VERIFIED
    else:
        status = ClaimStatus.UNVERIFIED

    # --- Base confidence by status ---------------------------------------- #
    if status == ClaimStatus.VERIFIED:
        base = min(99.0, 60 + avg_rel * 0.4)
    elif status == ClaimStatus.PARTIALLY_VERIFIED and n >= 2:
        base = min(85.0, 40 + avg_rel * 0.4)
    elif status == ClaimStatus.PARTIALLY_VERIFIED:
        base = min(70.0, avg_rel * 0.6)
    elif status == ClaimStatus.CONFLICTED:
        base = min(60.0, avg_rel * 0.6)
    else:
        base = avg_rel * 0.4

    # Recency scales confidence within [0.76 (all stale) .. 1.0 (all fresh)];
    # unknown dates are near-neutral (~0.955) so missing metadata isn't punished.
    recency_factor = 0.7 + 0.3 * fresh_mean
    # Each contradicting source cuts confidence; floored so it never fully zeroes.
    contradiction_factor = max(0.4, 1.0 - 0.25 * n_contra)
    confidence = round(max(0.0, min(99.0, base * recency_factor * contradiction_factor)), 1)

    reasons = _reasons(
        n, n_contra, avg_rel, aggregate_freshness, outdated, status
    )
    meta = {
        "support_count": n,
        "contradiction_count": n_contra,
        "avg_reliability": round(avg_rel, 1),
        "freshness": aggregate_freshness,
        "outdated": outdated,
        "reasons": reasons,
    }
    return status, confidence, meta


def _reasons(n, n_contra, avg_rel, freshness, outdated, status) -> list[str]:
    reasons: list[str] = []
    if n >= 2:
        reasons.append(f"{n} independent sources support this claim.")
    else:
        reasons.append("Only one source supports this claim — it cannot be fully verified.")
    reasons.append(f"Average source reliability is {avg_rel:.0f}/100.")
    if freshness == FRESH:
        reasons.append("Supporting evidence is recent.")
    elif freshness == AGING:
        reasons.append("Some supporting evidence is getting old.")
    elif freshness == STALE or outdated:
        reasons.append("Supporting evidence appears outdated for this topic.")
    else:
        reasons.append("Publication dates were unavailable, so recency is unknown.")
    if n_contra:
        reasons.append(
            f"{n_contra} source(s) were found that contradict this claim."
        )
    return reasons


def _score_claim(
    sources: list[EvidenceSource], *, conflicting: bool
) -> tuple[ClaimStatus, float]:
    """Backward-compatible (status, confidence) helper over :func:`score_claim`."""
    status, confidence, _ = score_claim(sources, conflicting=conflicting)
    return status, confidence


async def verify(
    provider: AIProvider,
    findings: list[tuple[str, EvidenceSource]],
    *,
    as_of: date | None = None,
) -> list[VerifiedClaim]:
    """`findings` is a list of (finding_text, EvidenceSource)."""
    if not findings:
        return []

    by_index = {es.index: es for _, es in findings}
    findings_by_index: dict[int, list[str]] = {}
    for text, es in findings:
        findings_by_index.setdefault(es.index, []).append(text)

    listing = "\n".join(
        f"[{es.index}] (source rel={es.reliability}) {text}" for text, es in findings
    )
    prompt = (
        "Findings (each tagged with a source index):\n"
        f"{listing}\n\n"
        "Consolidate these into distinct claims with their supporting source indices. "
        "Return JSON."
    )
    try:
        data = await provider.structured_output(
            prompt, schema=_CLAIMS_SCHEMA, system=_SYSTEM
        )
    except Exception:
        return []

    claims: list[VerifiedClaim] = []
    for c in data.get("claims", []):
        text = str(c.get("text", "")).strip()
        if not text:
            continue
        idxs = c.get("source_indices", []) or []
        evidence: list[ClaimEvidence] = []
        supporting: list[EvidenceSource] = []
        seen: set[str] = set()
        for i in idxs:
            es = by_index.get(i)
            if es is None or es.source_id in seen:
                continue
            seen.add(es.source_id)
            supporting.append(es)
            passage = next(iter(findings_by_index.get(i, [])), "")
            evidence.append(
                ClaimEvidence(source_id=es.source_id, passage=passage)
            )
        status, confidence, meta = score_claim(
            supporting, conflicting=bool(c.get("conflicting", False)), as_of=as_of
        )
        claims.append(
            VerifiedClaim(
                text=text,
                status=status,
                confidence=confidence,
                evidence=evidence,
                confidence_meta=meta,
            )
        )
    return claims

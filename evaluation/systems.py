"""The two evaluated systems (#10, spec §17):

- ``researchmind_outcome`` composes ResearchMind's **real** quality engines exactly as the
  pipeline composes them — ``verification.score_claim`` over stance-labelled evidence,
  ``provenance_of``/``freshness_state`` for provenance & recency — so the quality-bearing
  computation is production code, not a re-implementation (spec §29-§31).
- ``baseline_outcome`` is the conventional workflow: accept every candidate claim as supported
  at a flat confidence, cite the first available source regardless of stance/entailment, no
  contradiction detection, no provenance, no temporal discrimination (spec §17).

Both consume the identical task corpus + candidate claims, so any score difference is due to
ResearchMind's architecture, not the underlying evidence or LLM (spec §18).
"""
from __future__ import annotations

from datetime import date

from app.agents import verification
from app.agents.verification import EvidenceSource
from app.models.enums import ClaimStatus
from app.services import provenance as prov
from app.services.freshness import freshness_state

# Result claim status vocabulary (spec §8).
SUPPORTED = "SUPPORTED"
PARTIALLY_SUPPORTED = "PARTIALLY_SUPPORTED"
CONTESTED = "CONTESTED"
OUTDATED = "OUTDATED"
UNSUPPORTED = "UNSUPPORTED"

_STATUS_MAP = {
    ClaimStatus.VERIFIED: SUPPORTED,
    ClaimStatus.PARTIALLY_VERIFIED: PARTIALLY_SUPPORTED,
    ClaimStatus.CONFLICTED: CONTESTED,
    ClaimStatus.UNVERIFIED: UNSUPPORTED,
    ClaimStatus.INSUFFICIENT_EVIDENCE: UNSUPPORTED,
}


def _as_of(task: dict) -> date | None:
    v = task.get("as_of")
    return date.fromisoformat(v) if v else None


def _sources_for(task: dict, claim_id: str, stance: str) -> list[dict]:
    return [s for s in task["corpus"] if claim_id in s.get("refs", []) and s.get("stance") == stance]


def _evidence_source(s: dict, i: int) -> EvidenceSource:
    return EvidenceSource(
        index=i, source_id=s["id"], url=s.get("url", ""), reliability=float(s["reliability"]),
        published_date=s.get("published_date"), source_type=s.get("source_type", "web"),
    )


def _availability(s: dict, as_of: date | None) -> str:
    provenance = prov.provenance_of(s.get("source_type", "web"), s.get("meta"))
    fresh = freshness_state(s.get("published_date"), s.get("source_type", "web"), as_of=as_of)
    return prov.availability_of(provenance, fresh)


# --------------------------------------------------------------------------- #
# ResearchMind — the real engines, composed
# --------------------------------------------------------------------------- #
def researchmind_outcome(task: dict) -> dict:
    as_of = _as_of(task)
    claims = []
    for cc in task["candidate_claims"]:
        cid = cc["id"]
        supporting = _sources_for(task, cid, "supports")
        contradicting = _sources_for(task, cid, "contradicts")
        sup_es = [_evidence_source(s, i) for i, s in enumerate(supporting)]
        con_es = [_evidence_source(s, i) for i, s in enumerate(contradicting)]
        status, confidence, meta = verification.score_claim(
            sup_es, con_es, conflicting=bool(contradicting), as_of=as_of,
        )
        result_status = _STATUS_MAP[status]
        # Temporal discrimination: a claim whose supporting evidence is majority-stale is
        # OUTDATED for a current-scope question — historically-true ≠ currently-true (spec §14).
        if result_status in (SUPPORTED, PARTIALLY_SUPPORTED) and meta.get("outdated"):
            result_status = OUTDATED
        # Citations = the supporting sources ResearchMind actually relied on.
        citations = [s["id"] for s in supporting]
        claims.append({
            "id": cid, "status": result_status, "confidence": confidence,
            "citations": citations, "provenance": [_availability(s, as_of) for s in supporting],
            "contradiction_detected": bool(contradicting),
        })
    return {"system": "researchmind", "claims": claims,
            "dimensions_covered": _covered_dimensions(task, claims, reject_unsupported=True)}


# --------------------------------------------------------------------------- #
# Baseline — conventional one-shot synthesis (accept-all)
# --------------------------------------------------------------------------- #
def baseline_outcome(task: dict) -> dict:
    claims = []
    for cc in task["candidate_claims"]:
        cid = cc["id"]
        # Cite the first source that mentions the claim, regardless of stance/entailment.
        mentioning = [s for s in task["corpus"] if cid in s.get("refs", [])]
        first = mentioning[0]["id"] if mentioning else None
        claims.append({
            "id": cid,
            "status": SUPPORTED,               # naive: accept every candidate claim
            "confidence": 75.0,                # flat, undiscriminated
            "citations": [first] if first else [],
            "provenance": ["live"],            # assumes everything is fresh live web
            "contradiction_detected": False,   # no contradiction machinery
        })
    return {"system": "baseline", "claims": claims,
            "dimensions_covered": _covered_dimensions(task, claims, reject_unsupported=False)}


def _covered_dimensions(task: dict, claims: list[dict], *, reject_unsupported: bool) -> list[str]:
    """A dimension is covered if a claim tagged with it survives (isn't rejected as UNSUPPORTED
    when the system does verification). Baseline (reject_unsupported=False) 'covers' everything —
    including junk — which the report flags as inflated completeness (spec §16)."""
    dims = set()
    status_by_id = {c["id"]: c["status"] for c in claims}
    for cc in task["candidate_claims"]:
        for d in cc.get("dimensions", []):
            st = status_by_id.get(cc["id"])
            if reject_unsupported and st == UNSUPPORTED:
                continue
            dims.add(d)
    return sorted(dims)

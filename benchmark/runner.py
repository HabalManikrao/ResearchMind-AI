"""Benchmark runner (#9): dispatches each scenario to the REAL deterministic engine and
returns a structured outcome for scoring. No engine is reimplemented here (spec §1, §25)."""
from __future__ import annotations

from datetime import date

from app.agents import verification
from app.agents.verification import EvidenceSource
from app.config import get_settings
from app.models.enums import ClaimStatus
from app.services import provenance as prov
from app.services import research_diff as rd
from app.services import significance
from app.services.freshness import freshness_state
from app.knowledge import graph as kg

settings = get_settings()

# Importance weights for aggregate scoring (spec §9).
IMPORTANCE_WEIGHT = {"critical": 3, "major": 2, "minor": 1}


def _as_of(scenario: dict) -> date | None:
    v = scenario.get("as_of")
    return date.fromisoformat(v) if v else None


# --------------------------------------------------------------------------- #
# claim_scoring — drives verification.score_claim (spec §8, §9)
# --------------------------------------------------------------------------- #
def run_claim_scoring(sc: dict) -> dict:
    as_of = _as_of(sc)
    supporting = [
        EvidenceSource(
            index=i, source_id=s.get("id", f"s{i}"), url=s.get("url", f"https://x/{i}"),
            reliability=float(s["reliability"]), published_date=s.get("published_date"),
            source_type=s.get("source_type", "web"),
        )
        for i, s in enumerate(sc.get("supporting", []))
    ]
    contradicting = [
        EvidenceSource(
            index=i, source_id=s.get("id", f"c{i}"), url=s.get("url", f"https://y/{i}"),
            reliability=float(s["reliability"]), published_date=s.get("published_date"),
            source_type=s.get("source_type", "web"),
        )
        for i, s in enumerate(sc.get("contradicting", []))
    ]
    status, confidence, meta = verification.score_claim(
        supporting, contradicting, conflicting=sc.get("conflicting", False), as_of=as_of,
    )
    # Derived evidence state (mirrors Claim.evidence_state) for the support label.
    if status == ClaimStatus.CONFLICTED or meta.get("contradiction_count"):
        support_label = "contradicted"
    elif status == ClaimStatus.VERIFIED:
        support_label = "supported"
    elif status == ClaimStatus.PARTIALLY_VERIFIED:
        support_label = "weakly_supported"
    else:
        support_label = "unsupported"
    return {
        "status": status.value,
        "confidence": confidence,
        "support_label": support_label,
        "support_count": meta["support_count"],
        "contradiction_count": meta["contradiction_count"],
        "freshness": meta["freshness"],
        "outdated": meta["outdated"],
    }


# --------------------------------------------------------------------------- #
# freshness — drives services.freshness.freshness_state (spec §8)
# --------------------------------------------------------------------------- #
def run_freshness(sc: dict) -> dict:
    state = freshness_state(sc.get("published_date"), sc.get("source_type", "web"),
                            as_of=_as_of(sc))
    return {"freshness": state}


# --------------------------------------------------------------------------- #
# provenance — drives Source.provenance/.availability logic (spec §8, §17)
# --------------------------------------------------------------------------- #
def run_provenance(sc: dict) -> dict:
    source_type = sc.get("source_type", "web")
    meta = sc.get("meta", {})
    provenance = prov.provenance_of(source_type, meta)
    freshness = freshness_state(sc.get("published_date"), source_type, as_of=_as_of(sc))
    availability = prov.availability_of(provenance, freshness)
    return {"provenance": provenance, "availability": availability, "freshness": freshness}


# --------------------------------------------------------------------------- #
# diff — drives research_diff._classify (spec §10)
# --------------------------------------------------------------------------- #
def _snap(d: dict) -> rd._ClaimSnap:
    text = d.get("text", "claim")
    return rd._ClaimSnap(
        id=d.get("id", "c"), text=text, norm=rd._normalize_text(text),
        tokens=rd._tokens(text), status=d.get("status", "verified"),
        confidence=float(d.get("confidence", 50.0)),
        support_count=int(d.get("support_count", 1)),
        contra_count=int(d.get("contra_count", 0)),
        freshness=d.get("freshness"), evidence=[],
    )


def run_diff(sc: dict) -> dict:
    kind, reason = rd._classify(_snap(sc["old"]), _snap(sc["new"]))
    direction = rd._direction(float(sc["old"].get("confidence", 50.0)),
                              float(sc["new"].get("confidence", 50.0)))
    return {"kind": kind, "direction": direction, "reason": reason}


# --------------------------------------------------------------------------- #
# significance — drives services.significance.evaluate (spec §12)
# --------------------------------------------------------------------------- #
def run_significance(sc: dict) -> dict:
    diff = rd.ResearchDiff(
        old_run={}, new_run={},
        sources={"items": sc.get("sources", [])},
        claims={"items": sc.get("claims", [])},
        confidence={},
        recommendation=sc.get("recommendation", {"kind": "unchanged", "old": None, "new": None}),
        documents={"items": []},
    )
    rel = {k: tuple(v) for k, v in (sc.get("source_reliability") or {}).items()}
    changes = significance.evaluate(diff, settings, source_reliability=rel)
    meaningful = [c for c in changes if significance.is_meaningful(c)]
    return {
        "max_impact": significance.max_impact(changes),
        "meaningful_count": len(meaningful),
        "total_changes": len(changes),
        "impacts": sorted({c.impact for c in changes}),
    }


# --------------------------------------------------------------------------- #
# entity_resolution — drives kg_graph normalization + conservative merge rule (spec §13)
# --------------------------------------------------------------------------- #
def run_entity_resolution(sc: dict) -> dict:
    etype = sc.get("entity_type", "technology")
    # Group names by (normalized_name, entity_type) exactly as _resolve_or_create_entity does.
    groups: dict[tuple[str, str], list[str]] = {}
    for name in sc["names"]:
        key = (kg.normalize_name(name), etype)
        groups.setdefault(key, []).append(name)
    # Distinct entities = number of groups; each group is one entity.
    distinct = [sorted(v) for v in groups.values()]
    return {"distinct_entities": sorted(distinct), "entity_count": len(groups)}


DISPATCH = {
    "claim_scoring": run_claim_scoring,
    "freshness": run_freshness,
    "provenance": run_provenance,
    "diff": run_diff,
    "significance": run_significance,
    "entity_resolution": run_entity_resolution,
}


def run_scenario(scenario: dict) -> dict:
    fn = DISPATCH.get(scenario["type"])
    if fn is None:
        raise ValueError(f"unknown scenario type: {scenario['type']}")
    return fn(scenario)

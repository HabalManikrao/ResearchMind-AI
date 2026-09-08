"""Product-value loop evaluation (#10, spec §33-§36, §53): does accumulated knowledge make
later research better? Measured with the REAL diff-classification + significance + entity
resolution engines over two-run longitudinal tasks. Honest rule (§35): a Research-Again that
merely repeats run 1 scores low."""
from __future__ import annotations

from app.config import get_settings
from app.knowledge import graph as kg
from app.services import research_diff as rd
from app.services import significance

settings = get_settings()


def _snap(c: dict) -> rd._ClaimSnap:
    text = c["text"]
    return rd._ClaimSnap(
        id=c["id"], text=text, norm=rd._normalize_text(text), tokens=rd._tokens(text),
        status=c.get("status", "verified"), confidence=float(c.get("confidence", 50.0)),
        support_count=int(c.get("support_count", 1)), contra_count=int(c.get("contra_count", 0)),
        freshness=c.get("freshness"), evidence=[],
    )


def evaluate_longitudinal(task: dict) -> dict:
    """task carries run1_claims / run2_claims (with status/confidence/support_count) and an
    optional recommendation change + monitoring corpus. Returns measured value signals."""
    run1 = {c["id"]: c for c in task["run1_claims"]}
    run2 = {c["id"]: c for c in task["run2_claims"]}

    new_claims = [cid for cid in run2 if cid not in run1]
    removed = [cid for cid in run1 if cid not in run2]
    matched = [cid for cid in run2 if cid in run1]

    # Research Again value: how many matched claims actually CHANGED (via the real classifier)
    # vs were pure repeats. A run that only repeats is low-value (spec §35).
    changed, repeats, corrected = [], [], []
    for cid in matched:
        kind, _ = rd._classify(_snap(run1[cid]), _snap(run2[cid]))
        if kind == rd.UNCHANGED:
            repeats.append(cid)
        else:
            changed.append(cid)
            if kind in (rd.CONTRADICTED, rd.WEAKENED, rd.STRENGTHENED):
                corrected.append(cid)

    # Recommendation change significance (via the real engine).
    rec_impact = None
    if task.get("recommendation"):
        diff = rd.ResearchDiff(old_run={}, new_run={}, sources={"items": []},
                               claims={"items": []}, confidence={},
                               recommendation=task["recommendation"], documents={"items": []})
        changes = significance.evaluate(diff, settings)
        rec_impact = significance.max_impact(changes)

    # Monitoring value: does significance surface the meaningful change and suppress noise?
    monitoring = None
    if task.get("monitoring_sources") is not None:
        diff = rd.ResearchDiff(old_run={}, new_run={},
                               sources={"items": task["monitoring_sources"]},
                               claims={"items": task.get("monitoring_claims", [])},
                               confidence={}, recommendation={"kind": "unchanged", "old": None, "new": None},
                               documents={"items": []})
        changes = significance.evaluate(diff, settings)
        meaningful = [c for c in changes if significance.is_meaningful(c)]
        monitoring = {"meaningful": len(meaningful), "total": len(changes),
                      "max_impact": significance.max_impact(changes)}

    # Graph value: entity continuity across runs (same normalized identity resolves).
    ents1 = {kg.normalize_name(n) for n in task.get("run1_entities", [])}
    ents2 = {kg.normalize_name(n) for n in task.get("run2_entities", [])}
    continuity = round(len(ents1 & ents2) / len(ents1), 3) if ents1 else None

    # Memory value: fraction of run1's settled (high-confidence) claims NOT re-litigated as new
    # candidate work in run2 (prior context lets run2 build on, not repeat, settled knowledge).
    settled = [cid for cid, c in run1.items() if float(c.get("confidence", 0)) >= 75
               and int(c.get("contra_count", 0)) == 0]
    re_litigated = [cid for cid in settled if cid in new_claims]
    memory_reuse = round(1 - (len(re_litigated) / len(settled)), 3) if settled else None

    n_matched = len(matched) or 1
    return {
        "task": task["id"],
        "again": {"new": len(new_claims), "changed": len(changed), "corrected": len(corrected),
                  "repeats": len(repeats), "removed": len(removed),
                  "useful_change_ratio": round((len(new_claims) + len(changed)) /
                                               (len(new_claims) + n_matched), 3)},
        "recommendation_impact": rec_impact,
        "monitoring": monitoring,
        "graph_continuity": continuity,
        "memory_reuse": memory_reuse,
    }

"""Claim-level scoring against independent ground truth (#10, spec §9-§16). Importance-weighted
(spec §10). Every metric is computed identically for both systems so the comparison is fair."""
from __future__ import annotations

IMPORTANCE_WEIGHT = {"critical": 3, "major": 2, "minor": 1}

# Which result statuses count as "not over-claiming" for a given expected status (spec §12).
_OK_FOR_EXPECTED = {
    "SUPPORTED": {"SUPPORTED", "PARTIALLY_SUPPORTED"},
    "PARTIALLY_SUPPORTED": {"PARTIALLY_SUPPORTED", "SUPPORTED", "CONTESTED"},
    "CONTESTED": {"CONTESTED"},
    "OUTDATED": {"OUTDATED", "CONTESTED"},
    "UNSUPPORTED": {"UNSUPPORTED", "CONTESTED"},
    "UNKNOWN": {"UNSUPPORTED", "PARTIALLY_SUPPORTED", "CONTESTED"},
}


def _entails(task: dict, source_id: str, claim_id: str) -> bool:
    for s in task["corpus"]:
        if s["id"] == source_id:
            return claim_id in s.get("entails", [])
    return False


def _gt_by_id(task: dict) -> dict:
    return {c["id"]: c for c in task["ground_truth"]["claims"]}


def score_task(task: dict, outcome: dict) -> dict:
    gt = _gt_by_id(task)
    by_id = {c["id"]: c for c in outcome["claims"]}
    known_contra = {k["claim"] for k in task["ground_truth"].get("known_contradictions", [])}

    # accumulators: metric -> (weighted_correct, weighted_total)
    acc: dict[str, list[float]] = {}

    def add(metric: str, correct: bool, w: float):
        a = acc.setdefault(metric, [0.0, 0.0])
        a[0] += w if correct else 0.0
        a[1] += w

    conf_correct, conf_wrong = [], []  # for calibration ordering

    for cid, g in gt.items():
        w = IMPORTANCE_WEIGHT.get(g.get("importance", "major"), 2)
        oc = by_id.get(cid)
        expected = g["expected_status"]
        got = oc["status"] if oc else "UNSUPPORTED"

        # claim accuracy — exact-or-acceptable-variant.
        acceptable = {expected} | set(g.get("acceptable_variants", []))
        add("claim_accuracy", got in acceptable, w)

        # evidence support — must not over-claim (SUPPORTED when truth is weaker).
        add("evidence_support", got in _OK_FOR_EXPECTED.get(expected, {expected}), w)

        # citation correctness — for claims the SYSTEM actually asserts, the cited sources must
        # entail them. A claim the system rejected (UNSUPPORTED/CONTESTED) is not "cited" — the
        # system isn't vouching for it — so it isn't scored here (spec §11: correctness only for
        # asserted claims). Evaluated identically for both systems, so the comparison is fair.
        cites = oc["citations"] if oc else []
        system_asserts = got in ("SUPPORTED", "PARTIALLY_SUPPORTED")
        if system_asserts:
            if cites:
                good = sum(1 for s in cites if _entails(task, s, cid))
                add("citation_correctness", good == len(cites), w)
            else:
                add("citation_correctness", False, w)  # asserted a claim with no citation

        # citation completeness — a claim that IS truly supported should be asserted+cited with
        # an entailing source; failing to back it is a completeness miss (gated on expected).
        if expected in ("SUPPORTED", "PARTIALLY_SUPPORTED"):
            has_entailing = system_asserts and any(_entails(task, s, cid) for s in cites)
            add("citation_completeness", has_entailing, w)

        # contradiction handling — known-contested claims must be flagged, not asserted.
        if cid in known_contra:
            flagged = bool(oc and oc.get("contradiction_detected")) or got == "CONTESTED"
            add("contradiction_handling", flagged, w)

        # temporal correctness — outdated claims must not read as currently SUPPORTED.
        if expected == "OUTDATED":
            add("temporal_correctness", got in ("OUTDATED", "CONTESTED"), w)

        # provenance — cached/local evidence must never read as live.
        provs = oc.get("provenance", []) if oc else []
        expected_prov = g.get("expected_provenance")
        if expected_prov:
            add("provenance_correctness", expected_prov in provs, w)
        if g.get("evidence_not_live"):
            add("no_false_live", all(p != "live" for p in provs) if provs else True, w)

        # calibration bucket: was this claim judged correctly, and at what confidence?
        judged_right = got in acceptable
        conf = oc["confidence"] if oc else 0.0
        (conf_correct if judged_right and expected in ("SUPPORTED", "PARTIALLY_SUPPORTED")
         else conf_wrong if expected in ("UNSUPPORTED", "CONTESTED", "OUTDATED")
         else []).append(conf)

    # research completeness — expected dimensions actually covered.
    exp_dims = set(task["ground_truth"].get("expected_dimensions", []))
    if exp_dims:
        covered = set(outcome.get("dimensions_covered", []))
        add("research_completeness", exp_dims <= covered, 2.0)

    # confidence calibration ordering — supported-correct should outrank contested/unsupported.
    calibration_ok = True
    if conf_correct and conf_wrong:
        calibration_ok = (sum(conf_correct) / len(conf_correct)) > (sum(conf_wrong) / len(conf_wrong))
    add("confidence_appropriateness", calibration_ok, 2.0)

    metric_scores = {m: round(c / t, 3) if t else None for m, (c, t) in acc.items()}
    return {"task": task["id"], "category": task.get("category"),
            "system": outcome["system"], "metric_scores": metric_scores, "weights": acc}


def aggregate(scored: list[dict]) -> dict:
    """Combine per-task scored results (one system) into weighted metric + category scores."""
    metric_acc: dict[str, list[float]] = {}
    cat_acc: dict[str, list[float]] = {}
    for r in scored:
        cat = r.get("category", "uncategorized")
        for metric, (c, t) in r["weights"].items():
            a = metric_acc.setdefault(metric, [0.0, 0.0])
            a[0] += c
            a[1] += t
            ca = cat_acc.setdefault(cat, [0.0, 0.0])
            ca[0] += c
            ca[1] += t
    metric_scores = {m: round(c / t, 3) if t else None for m, (c, t) in metric_acc.items()}
    category_scores = {c: round(cc / ct, 3) if ct else None for c, (cc, ct) in cat_acc.items()}
    # Overall = weighted correct / total across all metrics.
    tot_c = sum(c for c, _ in metric_acc.values())
    tot_t = sum(t for _, t in metric_acc.values())
    return {"overall": round(tot_c / tot_t, 3) if tot_t else None,
            "metric_scores": metric_scores, "category_scores": category_scores}

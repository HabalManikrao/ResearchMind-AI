"""Benchmark scoring (#9): compare a scenario's real-engine outcome against its ground truth
and emit per-scenario pass/fail + the metric each check feeds. Failures stay visible (spec §23,
§40). Claims are importance-weighted (spec §9)."""
from __future__ import annotations

from benchmark.runner import IMPORTANCE_WEIGHT


class Check:
    __slots__ = ("metric", "passed", "detail")

    def __init__(self, metric: str, passed: bool, detail: str = ""):
        self.metric = metric
        self.passed = passed
        self.detail = detail

    def to_dict(self) -> dict:
        return {"metric": self.metric, "passed": self.passed, "detail": self.detail}


def score(scenario: dict, outcome: dict) -> list[Check]:
    exp = scenario.get("expected", {})
    t = scenario["type"]
    if t == "claim_scoring":
        return _score_claim(exp, outcome)
    if t == "freshness":
        return [Check("freshness_correctness",
                      outcome["freshness"] == exp["freshness"],
                      f"got {outcome['freshness']} want {exp['freshness']}")]
    if t == "provenance":
        checks = [Check("provenance_correctness",
                        outcome["provenance"] == exp["provenance"],
                        f"got {outcome['provenance']} want {exp['provenance']}")]
        if "availability" in exp:
            checks.append(Check("provenance_correctness",
                                outcome["availability"] == exp["availability"],
                                f"avail got {outcome['availability']} want {exp['availability']}"))
        # A cached/local source must NEVER read as live — hard gate (spec §8, §17, §39).
        if exp.get("availability") and exp["availability"] != "live":
            checks.append(Check("no_false_live", outcome["availability"] != "live",
                                "must not be labelled live"))
        return checks
    if t == "diff":
        return [Check("diff_quality", outcome["kind"] == exp["kind"],
                      f"got {outcome['kind']} want {exp['kind']}")]
    if t == "significance":
        checks = [Check("significance_accuracy",
                        outcome["max_impact"] == exp.get("max_impact"),
                        f"impact got {outcome['max_impact']} want {exp.get('max_impact')}")]
        if "meaningful" in exp:
            got = outcome["meaningful_count"] > 0
            checks.append(Check("significance_accuracy", got == exp["meaningful"],
                                f"meaningful got {got} want {exp['meaningful']}"))
        return checks
    if t == "entity_resolution":
        want = sorted(sorted(g) for g in exp["distinct_entities"])
        got = outcome["distinct_entities"]
        return [Check("entity_resolution", got == want, f"got {got} want {want}")]
    return [Check("unknown", False, f"no scorer for type {t}")]


def _score_claim(exp: dict, outcome: dict) -> list[Check]:
    checks: list[Check] = []
    if "support_label" in exp:
        ok = outcome["support_label"] == exp["support_label"]
        checks.append(Check("evidence_support", ok,
                            f"label got {outcome['support_label']} want {exp['support_label']}"))
        # citation correctness: a claim declared 'supported' must actually clear verification
        # (>=2 sources), not merely have a source present (spec §8, §40).
        if exp["support_label"] == "supported":
            checks.append(Check("citation_correctness", outcome["support_count"] >= 2,
                                f"support_count={outcome['support_count']}"))
    if "status" in exp:
        checks.append(Check("claim_accuracy", outcome["status"] == exp["status"],
                            f"status got {outcome['status']} want {exp['status']}"))
    if exp.get("expect_contradiction"):
        checks.append(Check("contradiction_detection", outcome["contradiction_count"] > 0
                            or outcome["status"] == "conflicted", "expected a detected conflict"))
    if "confidence_min" in exp:
        checks.append(Check("confidence_behavior", outcome["confidence"] >= exp["confidence_min"],
                            f"conf {outcome['confidence']} >= {exp['confidence_min']}"))
    if "confidence_max" in exp:
        checks.append(Check("confidence_behavior", outcome["confidence"] <= exp["confidence_max"],
                            f"conf {outcome['confidence']} <= {exp['confidence_max']}"))
    return checks


def aggregate(results: list[dict]) -> dict:
    """results: [{scenario, outcome, checks:[Check], importance, category}]. Returns weighted
    metric scores, category scores, and the visible failure list (spec §23)."""
    by_metric: dict[str, list[float]] = {}
    by_metric_w: dict[str, list[float]] = {}   # weighted
    by_category: dict[str, list[bool]] = {}
    failures: list[dict] = []

    for r in results:
        w = IMPORTANCE_WEIGHT.get(r.get("importance", "major"), 2)
        cat = r.get("category", "uncategorized")
        scenario_pass = all(c.passed for c in r["checks"])
        by_category.setdefault(cat, []).append(scenario_pass)
        for c in r["checks"]:
            by_metric.setdefault(c.metric, []).append(1.0 if c.passed else 0.0)
            by_metric_w.setdefault(c.metric, [])
            by_metric_w[c.metric].extend([1.0 if c.passed else 0.0] * w)
            if not c.passed:
                failures.append({"scenario": r["scenario"]["id"], "metric": c.metric,
                                 "detail": c.detail})

    metric_scores = {m: round(sum(v) / len(v), 3) for m, v in by_metric.items()}
    metric_scores_weighted = {m: round(sum(v) / len(v), 3) for m, v in by_metric_w.items()}
    category_scores = {c: round(sum(v) / len(v), 3) for c, v in by_category.items()}
    n_pass = sum(1 for r in results if all(c.passed for c in r["checks"]))
    return {
        "scenarios_total": len(results),
        "scenarios_passed": n_pass,
        "scenarios_failed": len(results) - n_pass,
        "metric_scores": metric_scores,
        "metric_scores_weighted": metric_scores_weighted,
        "category_scores": category_scores,
        "failures": failures,
    }

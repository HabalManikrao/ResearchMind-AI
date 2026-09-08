"""Real-world evaluation regression guard (#10, spec §44): run the evaluation under pytest and
assert the acceptance thresholds — ResearchMind must beat the conventional baseline on every
architecture-differentiated metric, with zero false-live — so a future change that regresses
research quality or the architecture's value turns the suite red. Also proves the harness is
diagnostic (spec §1, §49)."""
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from evaluation import run_evaluation, scorer, systems  # noqa: E402


@pytest.fixture(scope="module")
def report():
    return run_evaluation.run()


def test_enough_tasks(report):
    assert report["tasks_total"] >= 15  # spec §4 (20-50 target; claim tasks subset)


def test_researchmind_beats_baseline_overall(report):
    assert report["researchmind"]["overall"] > report["baseline"]["overall"]


def test_architecture_differentiated_metrics(report):
    """ResearchMind must strictly beat the baseline where its architecture provides a capability
    the baseline lacks (spec §49): contradiction handling, provenance, no-false-live, temporal,
    citation correctness, confidence calibration."""
    d = report["delta_researchmind_minus_baseline"]
    for metric in ("contradiction_handling", "provenance_correctness", "no_false_live",
                   "temporal_correctness", "citation_correctness", "confidence_appropriateness"):
        assert d.get(metric, 0) > 0, f"{metric} delta = {d.get(metric)}"


def test_hard_gates(report):
    ms = report["researchmind"]["metric_scores"]
    assert ms["no_false_live"] == 1.0            # zero false-live (spec §48)
    assert ms["provenance_correctness"] == 1.0
    assert ms["claim_accuracy"] >= 0.9           # critical/major accuracy (spec §48)
    assert ms["citation_correctness"] >= 0.9
    assert ms["contradiction_handling"] >= 0.9
    assert ms["temporal_correctness"] >= 0.9


def test_product_value_loop(report):
    """Research Again must show measurable useful change on the longitudinal task where evidence
    changed, and none on the pure-repeat task; monitoring must surface the meaningful change and
    suppress noise (spec §35, §36, §53)."""
    lv = {r["task"]: r for r in report["longitudinal"]}
    assert lv["long_001"]["again"]["useful_change_ratio"] > 0.3      # real change added
    assert lv["long_001"]["recommendation_impact"] == "critical"    # reversal detected
    assert lv["long_001"]["monitoring"]["meaningful"] >= 1          # authoritative signal
    assert lv["long_002"]["again"]["useful_change_ratio"] == 0.0    # pure repeat adds nothing
    assert lv["long_002"]["monitoring"]["meaningful"] == 0          # noise suppressed


def test_temporal_fix_regression():
    """A claim backed by a fresh authoritative source + an older one is currently SUPPORTED,
    not OUTDATED (#10 quality fix). Guards against reintroducing the over-flag."""
    task = {
        "id": "regress_temporal", "as_of": "2026-09-04",
        "corpus": [
            {"id": "s1", "reliability": 88, "published_date": "2026-08-01", "source_type": "docs",
             "stance": "supports", "refs": ["c1"], "entails": ["c1"]},
            {"id": "s2", "reliability": 85, "published_date": "2023-01-01", "source_type": "docs",
             "stance": "supports", "refs": ["c1"], "entails": ["c1"]},
        ],
        "candidate_claims": [{"id": "c1", "text": "P currently supports C", "importance": "critical"}],
    }
    out = systems.researchmind_outcome(task)
    assert out["claims"][0]["status"] == "SUPPORTED"


def test_evaluation_is_diagnostic():
    """The scorer must fail a system that over-claims — proof it isn't rubber-stamping (§1)."""
    task = {
        "id": "diag", "as_of": "2026-09-04",
        "corpus": [{"id": "s1", "reliability": 60, "source_type": "web", "stance": "neutral",
                    "refs": ["c1"], "entails": []}],
        "candidate_claims": [{"id": "c1", "text": "unsupported claim", "importance": "critical"}],
        "ground_truth": {"claims": [{"id": "c1", "expected_status": "UNSUPPORTED",
                                     "importance": "critical", "temporal_scope": "current"}],
                         "expected_dimensions": [], "known_contradictions": []},
    }
    baseline = scorer.score_task(task, systems.baseline_outcome(task))
    assert baseline["metric_scores"]["evidence_support"] < 1.0  # baseline over-claims → fails

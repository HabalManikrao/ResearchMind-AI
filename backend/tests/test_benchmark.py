"""Benchmark regression guard (#9, spec §39, §47): run the research-quality benchmark under
pytest and assert the acceptance thresholds, so a future change that regresses research
quality turns the suite red. Also proves the harness is genuinely diagnostic (§4, §40)."""
import sys
from pathlib import Path

import pytest

# The benchmark package lives at the repo root (sibling of backend/); make it importable.
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from benchmark import metrics as m  # noqa: E402
from benchmark import run_benchmark  # noqa: E402


@pytest.fixture(scope="module")
def report():
    return run_benchmark.run()


def test_benchmark_has_enough_scenarios(report):
    assert report["scenarios_total"] >= 24  # spec §5: 20-30 representative scenarios


def test_benchmark_all_scenarios_pass(report):
    # Baseline is clean; this locks it in so a regression is visible (spec §39).
    assert report["scenarios_failed"] == 0, report["failures"]


def test_benchmark_hard_gates(report):
    ms = report["metric_scores"]
    # Zero false-live provenance and zero cross-lived cache mislabelling (spec §39, §17).
    assert ms.get("no_false_live", 1.0) == 1.0
    assert ms.get("provenance_correctness", 0.0) == 1.0
    # Contradiction detection must not systematically fail (spec §39).
    assert ms.get("contradiction_detection", 0.0) >= 0.9
    # Critical/major claim support + citation correctness thresholds (spec §39).
    assert ms.get("evidence_support", 0.0) >= 0.85
    assert ms.get("citation_correctness", 0.0) >= 0.9
    # Diff / significance / entity resolution accuracy (spec §10, §12, §13).
    assert ms.get("diff_quality", 0.0) >= 0.9
    assert ms.get("significance_accuracy", 0.0) >= 0.9
    assert ms.get("entity_resolution", 0.0) == 1.0  # no wrong merges


def test_benchmark_records_engine_config(report):
    cfg = report["engine_config"]
    assert "research_diff_confidence_delta" in cfg  # reproducibility metadata (spec §21)


def test_benchmark_is_diagnostic():
    """A scenario whose ground truth is wrong MUST be reported as a failure — proof the
    benchmark exposes problems rather than rubber-stamping (spec §4, §40)."""
    bad = {
        "id": "diagnostic_check", "type": "freshness", "as_of": "2026-09-04",
        "published_date": "2026-09-01", "source_type": "news",
        "expected": {"freshness": "stale"},  # real answer is "fresh"
    }
    from benchmark import runner

    outcome = runner.run_scenario(bad)
    checks = m.score(bad, outcome)
    assert any(not c.passed for c in checks)

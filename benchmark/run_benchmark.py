"""Benchmark entrypoint (#9): run every scenario against the real engines and write a
machine-readable result. Deterministic + offline (spec §21).

    python -m benchmark.run_benchmark            # from the repo root
    python -m benchmark.run_benchmark --json     # print full JSON to stdout

Results are written to ``benchmark/results/latest.json`` (git-ignored — regenerable, §22/§45).
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# --- Hermetic, offline environment (must precede importing app.*) ---------- #
# Point every external service at an unreachable address so the benchmark can never depend
# on a live provider, real Ollama, or the internet (spec §21, §36, §37).
os.environ.setdefault("OLLAMA_BASE_URL", "http://127.0.0.1:1")
os.environ.setdefault("TAVILY_API_KEY", "")
os.environ.setdefault("KNOWLEDGE_ENABLED", "false")

_REPO_ROOT = Path(__file__).resolve().parent.parent
_BACKEND = _REPO_ROOT / "backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from benchmark import BENCHMARK_SCHEMA_VERSION  # noqa: E402
from benchmark import metrics as m  # noqa: E402
from benchmark import runner  # noqa: E402

SCENARIOS_DIR = Path(__file__).resolve().parent / "scenarios"
RESULTS_DIR = Path(__file__).resolve().parent / "results"


def load_scenarios() -> list[dict]:
    scenarios: list[dict] = []
    for path in sorted(SCENARIOS_DIR.glob("*.json")):
        scenarios.extend(json.loads(path.read_text(encoding="utf-8")))
    # Deterministic order by id.
    return sorted(scenarios, key=lambda s: s["id"])


def run() -> dict:
    scenarios = load_scenarios()
    results = []
    per_scenario = []
    for sc in scenarios:
        try:
            outcome = runner.run_scenario(sc)
            checks = m.score(sc, outcome)
            error = None
        except Exception as exc:  # noqa: BLE001 - a crashing scenario is a visible failure
            outcome, error = {}, f"{type(exc).__name__}: {exc}"
            checks = [m.Check("execution", False, error)]
        results.append({"scenario": sc, "outcome": outcome, "checks": checks,
                        "importance": sc.get("importance", "major"),
                        "category": sc.get("category", "uncategorized")})
        per_scenario.append({
            "id": sc["id"], "category": sc.get("category"), "type": sc["type"],
            "importance": sc.get("importance", "major"),
            "passed": all(c.passed for c in checks) and error is None,
            "outcome": outcome, "checks": [c.to_dict() for c in checks],
            "error": error,
        })

    agg = m.aggregate(results)
    return {
        "schema_version": BENCHMARK_SCHEMA_VERSION,
        "engine_config": _engine_config(),
        **agg,
        "scenarios": per_scenario,
    }


def _engine_config() -> dict:
    from app.config import get_settings

    s = get_settings()
    return {
        "research_diff_confidence_delta": s.research_diff_confidence_delta,
        "monitor_high_confidence": s.monitor_high_confidence,
        "monitor_major_delta": s.monitor_major_delta,
        "monitor_authoritative_reliability": s.monitor_authoritative_reliability,
        "kg_min_entity_length": s.kg_min_entity_length,
    }


def _summary(report: dict) -> str:
    lines = [
        "ResearchMind Research-Quality Benchmark",
        f"  scenarios: {report['scenarios_passed']}/{report['scenarios_total']} passed",
        "  metric scores (unweighted):",
    ]
    for metric, sc in sorted(report["metric_scores"].items()):
        lines.append(f"    {metric:24s} {sc:.3f}")
    lines.append("  category scores:")
    for cat, sc in sorted(report["category_scores"].items()):
        lines.append(f"    {cat:24s} {sc:.3f}")
    if report["failures"]:
        lines.append(f"  FAILURES ({len(report['failures'])}):")
        for f in report["failures"]:
            lines.append(f"    [{f['scenario']}] {f['metric']}: {f['detail']}")
    else:
        lines.append("  no failures")
    return "\n".join(lines)


def main() -> int:
    report = run()
    RESULTS_DIR.mkdir(exist_ok=True)
    (RESULTS_DIR / "latest.json").write_text(
        json.dumps(report, indent=2, default=str), encoding="utf-8"
    )
    if "--json" in sys.argv:
        print(json.dumps(report, indent=2, default=str))
    else:
        print(_summary(report))
    # Non-zero exit if any scenario failed, so CI/callers notice.
    return 0 if report["scenarios_failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())

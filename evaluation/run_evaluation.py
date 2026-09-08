"""Evaluation entrypoint (#10): run both systems on every task, score against independent
ground truth, compare, and write a machine-readable report. Deterministic + offline (spec §21).

    python -m evaluation.run_evaluation           # from the repo root
    python -m evaluation.run_evaluation --json

Writes ``evaluation/results/latest.json`` (git-ignored — regenerable, spec §22)."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

os.environ.setdefault("OLLAMA_BASE_URL", "http://127.0.0.1:1")  # hermetic/offline (spec §21)
os.environ.setdefault("TAVILY_API_KEY", "")
os.environ.setdefault("KNOWLEDGE_ENABLED", "false")

_REPO_ROOT = Path(__file__).resolve().parent.parent
_BACKEND = _REPO_ROOT / "backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from evaluation import EVALUATION_SCHEMA_VERSION, product_value, scorer, systems  # noqa: E402

TASKS_DIR = Path(__file__).resolve().parent / "tasks"
RESULTS_DIR = Path(__file__).resolve().parent / "results"


def _load(name: str) -> list[dict]:
    path = TASKS_DIR / name
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else []


def load_claim_tasks() -> list[dict]:
    tasks: list[dict] = []
    for path in sorted(TASKS_DIR.glob("*.json")):
        if path.name == "longitudinal.json":
            continue
        tasks.extend(json.loads(path.read_text(encoding="utf-8")))
    return sorted(tasks, key=lambda t: t["id"])


def run() -> dict:
    tasks = load_claim_tasks()
    rm_scored, base_scored = [], []
    per_task = []
    for t in tasks:
        rm = scorer.score_task(t, systems.researchmind_outcome(t))
        bl = scorer.score_task(t, systems.baseline_outcome(t))
        rm_scored.append(rm)
        base_scored.append(bl)
        per_task.append({
            "id": t["id"], "category": t.get("category"),
            "researchmind": rm["metric_scores"], "baseline": bl["metric_scores"],
            "note": t.get("note"),
        })

    rm_agg = scorer.aggregate(rm_scored)
    base_agg = scorer.aggregate(base_scored)

    # Longitudinal product-value tasks (§33-§36, §53).
    longitudinal = [product_value.evaluate_longitudinal(t) for t in _load("longitudinal.json")]

    # Per-metric ResearchMind - baseline deltas (honest comparison, §49).
    deltas = {}
    for m, rm_v in rm_agg["metric_scores"].items():
        bl_v = base_agg["metric_scores"].get(m)
        if rm_v is not None and bl_v is not None:
            deltas[m] = round(rm_v - bl_v, 3)

    return {
        "schema_version": EVALUATION_SCHEMA_VERSION,
        "engine_config": _engine_config(),
        "tasks_total": len(tasks),
        "researchmind": rm_agg,
        "baseline": base_agg,
        "delta_researchmind_minus_baseline": deltas,
        "per_task": per_task,
        "longitudinal": longitudinal,
    }


def _engine_config() -> dict:
    from app.config import get_settings

    s = get_settings()
    return {"research_diff_confidence_delta": s.research_diff_confidence_delta,
            "monitor_high_confidence": s.monitor_high_confidence}


def _summary(r: dict) -> str:
    lines = [
        "ResearchMind Real-World Research Evaluation",
        f"  tasks: {r['tasks_total']}",
        f"  overall — ResearchMind {r['researchmind']['overall']}  vs  baseline {r['baseline']['overall']}",
        "  metric (ResearchMind | baseline | delta):",
    ]
    for m in sorted(r["researchmind"]["metric_scores"]):
        rm = r["researchmind"]["metric_scores"][m]
        bl = r["baseline"]["metric_scores"].get(m)
        d = r["delta_researchmind_minus_baseline"].get(m)
        lines.append(f"    {m:26s} {str(rm):>6} | {str(bl):>6} | {('+' if (d or 0) >= 0 else '')}{d}")
    if r["longitudinal"]:
        lines.append("  longitudinal product-value:")
        for lv in r["longitudinal"]:
            lines.append(f"    {lv['task']}: again_useful={lv['again']['useful_change_ratio']} "
                         f"rec={lv['recommendation_impact']} monitoring={lv['monitoring']} "
                         f"graph_continuity={lv['graph_continuity']} memory_reuse={lv['memory_reuse']}")
    return "\n".join(lines)


def main() -> int:
    r = run()
    RESULTS_DIR.mkdir(exist_ok=True)
    (RESULTS_DIR / "latest.json").write_text(json.dumps(r, indent=2, default=str), encoding="utf-8")
    print(json.dumps(r, indent=2, default=str) if "--json" in sys.argv else _summary(r))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

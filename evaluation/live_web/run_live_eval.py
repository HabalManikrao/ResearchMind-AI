"""Live-web evaluation entrypoint (#11). Detects which live providers are actually reachable,
runs the reachable tasks through the production collection path, computes collection metrics,
and writes a secret-free run manifest + results. Honest by construction: unreachable providers
produce **skipped** tasks, never faked live results.

    python -m evaluation.live_web.run_live_eval          # from the repo root

Results (git-ignored, regenerable) go to evaluation/live_web/results/latest.json.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_BACKEND = _REPO_ROOT / "backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from evaluation.live_web import LIVE_EVAL_SCHEMA_VERSION, capture, runner  # noqa: E402

TASKS = Path(__file__).resolve().parent / "tasks.json"
RESULTS = Path(__file__).resolve().parent / "results"


def _apply_ca_bundle() -> None:
    """Trust the corporate CA for outbound HTTPS (mirrors app.main._apply_ca_bundle) so live
    GitHub/HTTPS retrieval works behind a TLS-inspecting proxy. No-op if no bundle is found.

    Robust to cwd: pydantic-settings loads `.env` relative to the current directory, so running
    from the repo root leaves `settings.ca_bundle` empty. We therefore also look for the
    conventional `backend/corp-ca-bundle.pem`."""
    from app.config import get_settings

    candidates = []
    ca = get_settings().ca_bundle
    if ca:
        p = Path(ca)
        candidates.append(p if p.is_absolute() else (_BACKEND / ca).resolve())
    candidates.append(_BACKEND / "corp-ca-bundle.pem")
    for p in candidates:
        if p.exists():
            # Force-set (not setdefault): a stale/empty SSL_CERT_FILE already in the environment
            # would otherwise shadow the corporate bundle and break HTTPS behind the proxy.
            os.environ["SSL_CERT_FILE"] = str(p)
            os.environ["REQUESTS_CA_BUNDLE"] = str(p)
            return


async def _reachable_providers() -> tuple[set[str], str]:
    """Probe which live providers actually work here (Phase 0 honesty)."""
    import httpx

    from app.config import get_settings

    s = get_settings()
    reachable: set[str] = set()
    notes = []

    # GitHub (no search provider needed).
    try:
        async with httpx.AsyncClient(timeout=8, trust_env=True) as c:
            r = await c.get("https://api.github.com", headers={"Accept": "application/vnd.github+json"})
            if r.status_code < 500:
                reachable.add("github")
                notes.append("github:reachable")
    except Exception as exc:  # noqa: BLE001
        notes.append(f"github:unreachable({type(exc).__name__})")

    # General web provider (tavily needs a key; searxng needs a running instance).
    if s.search_provider.lower() == "tavily" and s.tavily_api_key:
        try:
            async with httpx.AsyncClient(timeout=8, trust_env=True) as c:
                await c.get("https://api.tavily.com")
            reachable.add("web")
            notes.append("web:tavily")
        except Exception:  # noqa: BLE001
            notes.append("web:tavily-unreachable")
    elif s.search_provider.lower() == "searxng":
        try:
            async with httpx.AsyncClient(timeout=5, trust_env=True) as c:
                r = await c.get(f"{s.searxng_url}/healthz")
                if r.status_code < 500:
                    reachable.add("web")
                    notes.append("web:searxng")
        except Exception:  # noqa: BLE001
            notes.append("web:searxng-unreachable")
    else:
        notes.append("web:no-provider-configured")
    return reachable, ", ".join(notes)


async def run() -> dict:
    _apply_ca_bundle()
    from app.config import get_settings

    s = get_settings()
    tasks = json.loads(TASKS.read_text(encoding="utf-8"))
    reachable, provider_notes = await _reachable_providers()

    results = [await runner.run_task(t, reachable_providers=reachable) for t in tasks]
    completed = [r for r in results if r["status"] == "completed"]
    skipped = [r for r in results if r["status"] == "skipped"]
    failed = [r for r in results if r["status"] == "failed"]

    manifest = capture.run_manifest(
        git_commit=_git_commit(), dataset_version="1.0",
        provider=",".join(sorted(reachable)) or "none",
        provider_config_id=f"github:{'auth' if s.github_token else 'unauthenticated'}",
        llm_model=s.ollama_model, embedding_model=s.embedding_model,
        source_policy=s.default_source_policy, connectivity_state=provider_notes,
        metric_version=LIVE_EVAL_SCHEMA_VERSION, tasks_total=len(tasks),
        tasks_run=len(completed), tasks_skipped=len(skipped) + len(failed),
        timestamp=_now(),
    )
    return {"schema_version": LIVE_EVAL_SCHEMA_VERSION, "manifest": manifest,
            "reachable_providers": sorted(reachable), "provider_notes": provider_notes,
            "aggregate": _aggregate(completed), "results": results}


def _aggregate(completed: list[dict]) -> dict:
    if not completed:
        return {"tasks_scored": 0}

    def _mean(vals):
        vals = [v for v in vals if v is not None]
        return round(sum(vals) / len(vals), 3) if vals else None

    recalls = [c["metrics"]["source_recall"]["recall"] for c in completed
               if c["metrics"]["source_recall"]]
    return {
        "tasks_scored": len(completed),
        "source_recall": _mean(recalls),
        "mrr_authoritative": _mean(c["metrics"]["ranking"]["mrr_authoritative"] for c in completed),
        "reliability_rank_correlation": _mean(
            c["metrics"]["ranking"]["reliability_rank_correlation"] for c in completed),
        "unique_domains_avg": _mean(c["metrics"]["diversity"]["unique_domains"] for c in completed),
        "normalized_duplicates_total": sum(
            c["metrics"]["deduplication"]["normalized_duplicate_urls"] for c in completed),
        "no_false_live_all": all(c["metrics"]["provenance"]["pass"] for c in completed),
        "ranking_gain_vs_provider_avg": _mean(
            c["metrics"]["ranking_gain_vs_provider"] for c in completed),
    }


def _git_commit() -> str:
    try:
        import subprocess
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"],
                                       cwd=str(_REPO_ROOT)).decode().strip()
    except Exception:  # noqa: BLE001
        return "unknown"


def _now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def main() -> int:
    r = asyncio.run(run())
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / "latest.json").write_text(json.dumps(r, indent=2, default=str), encoding="utf-8")
    m = r["manifest"]
    print("ResearchMind Live-Web Evaluation")
    print(f"  reachable providers: {r['reachable_providers'] or 'NONE'}  ({r['provider_notes']})")
    print(f"  tasks: {m['tasks_total']} total, {m['tasks_run']} run, {m['tasks_skipped']} skipped")
    agg = r["aggregate"]
    if agg.get("tasks_scored"):
        for k, v in agg.items():
            print(f"    {k:32s} {v}")
    else:
        print("  no live tasks were runnable in this environment (no reachable provider).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Live-web evaluation — offline guarantees (#11, Phases 9, 10, 14, 15). These tests are fully
deterministic and network-free: the live GitHub call is mocked. They verify benchmark isolation,
provenance truthfulness (no false-live), failure handling, the collection metrics, and that no
secret can leak into captured artifacts."""
import hashlib
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from evaluation.live_web import capture, metrics, runner  # noqa: E402


# --------------------------------------------------------------------------- #
# Benchmark isolation (Phase 9) — live evaluation cannot contaminate #9/#10
# --------------------------------------------------------------------------- #
def _checksum_tree(path: Path) -> str:
    h = hashlib.sha1()
    for p in sorted(path.rglob("*.json")):
        h.update(p.read_bytes())
    return h.hexdigest()


async def test_live_run_does_not_mutate_deterministic_fixtures(monkeypatch):
    bench_dir = _REPO_ROOT / "benchmark" / "scenarios"
    eval_dir = _REPO_ROOT / "evaluation" / "tasks"
    before = (_checksum_tree(bench_dir), _checksum_tree(eval_dir))

    async def fake_search(query, token, max_results):
        return [{"full_name": "qdrant/qdrant", "html_url": "https://github.com/qdrant/qdrant",
                 "stargazers_count": 20000, "pushed_at": "2026-08-01T00:00:00Z",
                 "owner": {"login": "qdrant"}, "forks_count": 1000, "archived": False}]
    monkeypatch.setattr(runner.gh, "_search_repos", fake_search)

    task = {"id": "iso", "category": "technical", "requires_provider": "github",
            "search_query": "vector database",
            "reference_sources": {"substrings": ["qdrant"]}}
    await runner.run_task(task, reachable_providers={"github"})

    after = (_checksum_tree(bench_dir), _checksum_tree(eval_dir))
    assert before == after  # a live run touched no deterministic fixture


def test_live_modules_do_not_import_benchmark_or_fixtures():
    # Importing the live harness must not pull in the deterministic benchmark/evaluation runners.
    # Checked in a CLEAN subprocess so other test files (which do import those runners) can't
    # pollute the result — this proves the isolation at the import-graph level, not global state.
    import os
    import subprocess
    code = (
        "import sys, os;"
        "sys.path.insert(0, os.path.join(os.getcwd(), 'backend'));"
        "import evaluation.live_web.runner, evaluation.live_web.metrics;"
        "assert 'benchmark.run_benchmark' not in sys.modules, 'live harness imported the benchmark runner';"
        "assert 'evaluation.run_evaluation' not in sys.modules, 'live harness imported the #10 eval runner';"
        "print('isolated')"
    )
    env = {**os.environ, "OLLAMA_BASE_URL": "http://127.0.0.1:1", "TAVILY_API_KEY": ""}
    r = subprocess.run([sys.executable, "-c", code], cwd=str(_REPO_ROOT),
                       capture_output=True, text=True, env=env)
    assert r.returncode == 0, r.stderr
    assert "isolated" in r.stdout


# --------------------------------------------------------------------------- #
# Provenance: no false-live (Phase 5 CRITICAL, Phase 14)
# --------------------------------------------------------------------------- #
async def test_live_github_sources_are_marked_live(monkeypatch):
    async def fake_search(query, token, max_results):
        return [{"full_name": "a/b", "html_url": "https://github.com/a/b",
                 "stargazers_count": 100, "pushed_at": "2026-08-01T00:00:00Z",
                 "owner": {"login": "a"}, "forks_count": 1, "archived": False}]
    monkeypatch.setattr(runner.gh, "_search_repos", fake_search)
    sources = await runner.collect_github("q")
    assert sources and all(s["provenance"] == "live_web" for s in sources)


def test_provenance_check_rejects_false_live():
    # A non-live run must not carry any live_web label.
    non_live = [{"provenance": "cached_web"}, {"provenance": "local_document"}]
    assert metrics.provenance_check(non_live, expected_live=False)["pass"] is True
    faked = [{"provenance": "live_web"}]
    assert metrics.provenance_check(faked, expected_live=False)["pass"] is False


# --------------------------------------------------------------------------- #
# Failure handling (Phase 10) — a provider failure is recorded, never faked live
# --------------------------------------------------------------------------- #
async def test_provider_failure_is_recorded_not_faked(monkeypatch):
    async def boom(query, token, max_results):
        raise ConnectionError("DNS failure")
    monkeypatch.setattr(runner.gh, "_search_repos", boom)
    res = await runner.run_task(
        {"id": "f", "requires_provider": "github", "search_query": "q"},
        reachable_providers={"github"})
    assert res["status"] == "failed"
    assert "sources" not in res  # nothing labelled live on failure


async def test_unavailable_provider_is_skipped_not_failed():
    res = await runner.run_task(
        {"id": "s", "requires_provider": "web", "search_query": "q"},
        reachable_providers={"github"})  # web not reachable
    assert res["status"] == "skipped"
    assert res["reason"].startswith("provider_unavailable")


# --------------------------------------------------------------------------- #
# Collection metrics (Phase 6) — unit tests over synthetic manifests
# --------------------------------------------------------------------------- #
def test_source_recall_matches_by_substring_and_domain():
    sources = [{"url": "https://github.com/qdrant/qdrant", "title": "qdrant/qdrant"},
               {"url": "https://example.com/x", "title": "milvus overview"}]
    r = metrics.source_recall(sources, {"substrings": ["qdrant", "milvus", "weaviate"]})
    assert r["hit"] == 2 and r["total"] == 3 and r["recall"] == round(2 / 3, 3)
    assert metrics.source_recall(sources, {}) is None  # no reference → not applicable


def test_ranking_quality_and_gain():
    sources = [{"rank": 0, "reliability": 90}, {"rank": 1, "reliability": 70},
               {"rank": 2, "reliability": 40}]
    rq = metrics.ranking_quality(sources)
    assert rq["mrr_authoritative"] == 1.0             # top source is authoritative
    assert rq["reliability_rank_correlation"] > 0.5   # rank order tracks reliability
    assert metrics.ranking_gain_vs_provider(sources) >= 1.0


def test_diversity_and_dedup():
    sources = [{"url": "https://github.com/a/b", "source_type": "github", "meta": {"owner": "a"}},
               {"url": "https://github.com/a/b", "source_type": "github", "meta": {"owner": "a"}},
               {"url": "https://other.com/c", "source_type": "web", "meta": {}}]
    d = metrics.diversity(sources)
    assert d["unique_domains"] == 2 and d["source_types"] == 2
    dd = metrics.deduplication(sources)
    assert dd["exact_duplicate_urls"] == 1


def test_freshness_metric_current_task():
    sources = [{"published_date": "2026-08-20", "source_type": "news"},
               {"published_date": "2020-01-01", "source_type": "news"}]
    f = metrics.freshness(sources, requirement="recent", as_of="2026-09-04")
    assert f["dated_sources"] == 2 and 0.0 <= f["fresh_or_aging_ratio"] <= 1.0


# --------------------------------------------------------------------------- #
# Security (Phase 15) — no secret can enter a captured artifact
# --------------------------------------------------------------------------- #
def test_capture_strips_secrets_from_meta():
    rec = capture.source_record(
        url="https://github.com/a/b", title="a/b", source_type="github", reliability=80,
        rank=0, provenance="live_web",
        meta={"owner": "a", "token": "ghp_SECRET", "authorization": "Bearer x", "stars": 5})
    assert "token" not in rec["meta"] and "authorization" not in rec["meta"]
    assert rec["meta"]["owner"] == "a" and rec["meta"]["stars"] == 5
    # The manifest carries a config id, never a key.
    man = capture.run_manifest(
        git_commit="abc", dataset_version="1.0", provider="github",
        provider_config_id="github:unauthenticated", llm_model="llama", embedding_model="nomic",
        source_policy="live_preferred", connectivity_state="github:reachable",
        metric_version="1.0", tasks_total=8, tasks_run=8, tasks_skipped=0, timestamp="t")
    blob = str(man).lower()
    assert "ghp_" not in blob and "bearer" not in blob and "token" not in blob

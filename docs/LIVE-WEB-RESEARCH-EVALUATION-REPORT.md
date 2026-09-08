# Live-Web Research Evaluation — Report (#11)

_An empirical snapshot from `python -m evaluation.live_web.run_live_eval`. Live internet is
non-deterministic (sites/indexes/rankings/APIs change), so these numbers are **not** a permanent
reproducible truth — the #9/#10 deterministic suites remain the regression baseline. Failures and
gaps are reported in full (Phase 11); nothing is inflated._

---

## Executive summary

- **What was measured:** a genuine **live GitHub slice** — 8 technical tasks run against the real
  GitHub API through the **production collection path** (`github_research`), with real
  star-ranking, real reliability scoring, real provenance, and real latency.
- **What was NOT measured (honest gap):** the **general-web** live evaluation (Tavily/SearXNG
  recall/ranking/contradiction discovery/current-event freshness across reputable sites). This
  sandbox has **no general web search provider** — `SEARCH_PROVIDER=searxng` but SearXNG isn't
  running, and there is **no `TAVILY_API_KEY`**. Those 8 tasks are recorded **skipped —
  provider_unavailable**, never faked as live.
- **Verdict:** ResearchMind's live **ranking, authority ordering, deduplication, and provenance
  are healthy**; **GitHub source recall is weak on multi-word conceptual queries**, but the
  evidence shows this is a limitation of **GitHub keyword search**, *not* a ResearchMind ranking/
  query defect — so **no production change is justified** (Phase 12). The milestone's central
  live-web question is therefore **partially answered**; the general-web verdict awaits a
  provisioned provider.

## Baseline (verified before any change — Phase 0)

Git `c12df35` (Milestone #10). #9 benchmark **30/30**. #10 evaluation **RM 1.0 / baseline 0.677**.
337 backend / 50 frontend tests, build + typecheck green.

## Environment / reachability (measured)

| Provider | Status |
|---|---|
| GitHub API | **reachable** (200 through the corporate CA bundle) |
| Tavily (web/docs/news/community) | **unavailable** — no API key |
| SearXNG (web/docs/news/community) | **unavailable** — not running (connection refused) |
| arXiv (papers) | unreliable — times out through the proxy |
| Ollama | up (localhost:11434) |

## Live results — GitHub slice (8 tasks, real data)

| Metric | Value | Reading |
|---|---|---|
| tasks run / skipped | 8 / 8 | general-web tasks skipped honestly |
| source_recall (avg) | **0.377** | GitHub keyword search misses well-known conceptual matches (see analysis) |
| mrr_authoritative | **1.000** | the top-ranked source is always high-authority |
| reliability_rank_correlation | **0.869** | provider rank order tracks reliability strongly |
| unique_domains (avg) | 1.0 | single source type (github.com) — diversity N/A for a one-provider slice |
| normalized_duplicates (total) | **0** | no duplicate/syndicated results |
| no_false_live (all tasks) | **True** | every live source correctly labelled `live_web` |
| ranking_gain_vs_provider | 1.006 | reliability re-rank ≈ GitHub star order (reliability derives from stars) |

### Per-task source recall

| Task | Query | Recall | Note |
|---|---|---|---|
| gh_002 | python web framework | **1.00** | fastapi, django, flask all found |
| gh_005 | python data validation | 0.67 | pydantic, cerberus found |
| gh_001 | vector database | 0.60 | milvus, qdrant found; missed weaviate/chroma/faiss |
| gh_003 | local llm inference runtime | 0.25 | keyword search returned obscure repos |
| gh_006 | container orchestration | 0.25 | missed kubernetes/nomad (names don't contain the query words) |
| gh_007 | javascript frontend framework | 0.25 | found vue; missed react/angular/svelte |
| gh_004 | search engine self-hosted | 0.00 | matched proxies/torrent-search, not searxng/meilisearch |
| gh_008 | workflow orchestration engine | 0.00 | missed airflow/prefect/dagster/temporal |

## Failure analysis (grouped by root cause — Phase 11)

- **Source recall (the one real weakness):** low recall on **multi-word conceptual** GitHub
  queries. **Root cause = GitHub keyword search**, not ResearchMind. Evidence: switching the
  GitHub API from `sort=stars` to **best-match relevance** produced **identical** recall — the
  well-known projects (kubernetes, airflow, searxng, ollama) simply don't literally contain the
  conceptual query words, so GitHub's index never returns them. Simple, literal queries
  (`python web framework`) score 1.0. This is a provider-index limitation; a fix would require
  either semantic GitHub discovery (out of scope) or **task-specific query rewriting (forbidden —
  overfitting)**. → **P3, documented, no production change.**
- **Ranking / authority / dedup / provenance:** no failures — all healthy on real data.
- **Infrastructure:** the harness's CA-bundle resolution failed when run from the repo root
  (`settings.ca_bundle` empty because pydantic-settings loads `.env` relative to cwd). Fixed in
  the **harness** (fall back to `backend/corp-ca-bundle.pem`) — an evaluation-tooling fix, not a
  production change.

## Comparison (Phase 7, honest)

The conventional baseline (raw provider top-k, no reliability re-rank/dedup) is **not
meaningfully different** on the GitHub slice, because GitHub already returns star-sorted results
and reliability derives from stars (`ranking_gain ≈ 1.006`). The value of ResearchMind's
re-ranking/dedup is best demonstrated on a **general web provider** returning heterogeneous,
duplicate-prone results — which is unmeasured here. These live numbers are **not** comparable to
the #10 fixture baseline (0.677) or the #9 benchmark; they measure different things (Phase 7).

## Cost / performance (measured; Phase 13)

The collection slice makes **zero LLM/embedding calls** (collection metrics need none). GitHub
latency ~0.2–0.8 s/query (measured, real). Estimated cost: **$0** (unauthenticated GitHub search;
no LLM). No unbounded loops; existing bounded-call protections untouched.

## Human review (Phase 11)

Not required for this slice — collection metrics are deterministic over captured metadata.
Synthesis/prose quality is not exercised (no general provider, no synthesis run). Documented as a
gap, not a passed criterion.

## Defects

| Sev | Found | Remaining | Note |
|---|---|---|---|
| P0 | 0 | 0 | no false-live, no fabricated evidence, no security/isolation failure |
| P1 | 0 | 0 | ranking/provenance/dedup sound; no systematic RM failure |
| P2 | 0 | 0 | best-match test ruled out a fixable RM ranking/query cause |
| P3 | 1 | 1 (documented) | GitHub conceptual-query recall is provider-limited; general-web recall unmeasured |

**Production fixes implemented: 0** — the evidence does not support an RM defect (Phase 12: only
change production with evidence). One **harness-only** fix (CA-bundle resolution).

## Deterministic-benchmark isolation (Phase 9)

**PASS** — verified by `test_live_web_eval.py`: a live run mutates no #9/#10 fixture (checksum
unchanged); the live harness does not import the deterministic runners; the #9/#10 suites remain
network-free (Ollama pinned to a dead port).

## Provenance (Phase 5)

**PASS** — every live GitHub source is `live_web`; provider failure / unavailable-provider paths
never produce a live label (tested); the no-false-live gate holds on all 8 live tasks.

## Security (Phase 15)

**PASS** — the run manifest carries a provider **config id** (`github:unauthenticated`), never a
key; captured source metadata is secret-stripped (tested); the GitHub token is never logged or
stored.

## Limitations (explicit)

1. **General-web live quality is UNMEASURED** here (no Tavily/SearXNG) — the milestone's central
   question is only **partially** answered.
2. Live internet is non-deterministic: GitHub itself returned `ConnectError` on one attempt and
   200 on the next — these numbers are a snapshot.
3. The slice is a **single source type** (GitHub), so diversity/contradiction/freshness across
   heterogeneous reputable sources is not exercised.
4. No synthesis/citation/contradiction *discovery* was run live (needs a general provider + a full
   research run); those remain covered only by #9/#10 (fixtures) and the offline tests.

## Recommendation

Proceed to a **provisioned live evaluation**: configure a `TAVILY_API_KEY` (or a running SearXNG)
and re-run `evaluation.live_web` — the harness is provider-agnostic and will exercise the general
web/docs/news/community/papers paths unchanged, filling the unmeasured metrics. Do **not** ship a
GitHub-query hack (overfitting). Consider **semantic GitHub discovery** (topic/embedding-assisted)
as future work if GitHub recall proves material once the general-web path is measured.

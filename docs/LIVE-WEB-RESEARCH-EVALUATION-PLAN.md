# Live-Web Research Evaluation + Collection/Ranking Quality (#11) — Plan

_Written **before** implementation (Phase 1). Measures how well ResearchMind discovers, ranks,
diversifies, and verifies information from the **real internet** — a dimension #9 (deterministic
engines) and #10 (fixture corpora) explicitly do **not** cover. The operating rule is truth:
measure, don't inflate; a high fixture score is **not** proof of live-web quality (§0)._

---

## 0. Audit + baseline (verified before any code)

- Git clean at `c12df35` (Milestone #10). #9 benchmark **30/30**; #10 evaluation **RM 1.0 vs
  baseline 0.677**. Committed state: **337 backend / 50 frontend** tests, build/typecheck green.
- **Environment reality (measured, not assumed):** this repo's sandbox has **no general web
  search provider** — `SEARCH_PROVIDER=searxng` but SearXNG is **not running** (connection
  refused), and there is **no `TAVILY_API_KEY`**. Raw HTTPS needs the corporate CA bundle.
  **Real Ollama is up** (localhost:11434). The **only working live retrieval path is the GitHub
  API** (verified: `api.github.com` returns 200 through the CA bundle); arXiv times out through
  the proxy.

**Consequence:** the *general-web* live evaluation (Tavily/SearXNG web/docs/news/community
recall, ranking, contradiction discovery across reputable sites, current-event freshness) **cannot
be executed in this environment**. What *can* be executed genuinely is a **GitHub live slice**:
real search → real star-ranked results → real reliability scoring → real provenance, for
technical/primary-source tasks. This plan builds the **full provider-agnostic harness** (so the
general-web evaluation runs unchanged when a provider is configured) and executes the runnable
GitHub slice + all offline isolation/resilience guarantees. The report states this plainly (§11).

## 1. Purpose

Measure live-web research quality **independently** from deterministic downstream engine
correctness. Establish an evidence-backed direction; do not redesign the architecture on imperfect
live results (§ "Architectural Rule").

## 2. Research questions (§2)

Find important sources? Rank quality appropriately? Find multiple independent sources? Discover
contradictions? Prefer fresh info when it matters? Extract usable evidence? Are citations
supported and complete? Does query planning target the right directions? Does synthesis reflect
the evidence? Compute cost? Latency? Behaviour under partial web failure?

## 3. Separated metric families (§3) — never one opaque score

- **Collection quality:** search/source recall@k, ranking (MRR/authority order), authority,
  freshness, diversity (unique domains/owners, source-type mix), contradiction discovery,
  deduplication (normalized-URL), query planning. *(runnable on the GitHub slice + offline units)*
- **Evidence quality:** extraction, passage usefulness, evidence↔claim alignment, citation
  correctness, citation completeness. *(structural checks + small real-Ollama sample)*
- **Downstream reasoning quality:** claim accuracy, contradiction handling, temporal correctness,
  recommendation, synthesis. *(covered deterministically by #9/#10; live synthesis = human review)*

## 4. Non-reproducibility statement (§2 non-reproducibility)

Live internet research is **non-deterministic** — sites, indexes, rankings, pages, APIs, and
network all change, and model outputs vary. Therefore **the live evaluation is an empirical
snapshot, not a permanent reproducible truth.** The deterministic **#9/#10 benchmark remains the
regression baseline**; live results never feed back into fixtures (§9 isolation).

## 5. Dataset (Phase 2) — 20–30 tasks with annotations

Categories A–G (stable-factual, recent/current, comparative, contradiction-sensitive,
recommendation, temporal, technical/primary). Each task: `task_id, question, category, search_query,
expected_intent, required_concepts, expected_source_types, reference_sources (domains/repos where
knowable), freshness_requirement, contradiction_relevant, min_diversity, annotations, scoring_rules,
requires_provider`. Tasks whose `requires_provider` is unavailable here (general `web`) are recorded
as **skipped-provider-unavailable**, not failed. The **technical** subset (`requires_provider:
github`) is genuinely runnable. Annotations live **only** in the harness, never in the production
pipeline (no hard-coded answers, no task-specific query hacks — § "Do not overfit").

## 6. Provider (Phase 3) & LLM (Phase 4)

Tavily/SearXNG/GitHub/arXiv all sit **behind the existing collection abstraction** (`agents/
dispatch.py`, `resilient_collect`) — the harness calls the production collection path, not a
bespoke crawler. **Never** hard-code/commit/log the API key; `.env.example` keeps a placeholder;
the run manifest stores a **provider config identifier without secrets**. Real Ollama via the
existing LLM abstraction; every run captures LLM/embedding call counts, model, elapsed time,
retries, iterations. No unrestricted loops; existing bounded-call protections preserved.

## 7. Capture (Phase 5) & manifest (Phase 8)

Per source: url, normalized_url, title, domain, source_type, provider, retrieval_timestamp,
publication_date, freshness, reliability, discovering_query, provider_rank, selected, became_evidence,
provenance, availability, cache_status, latency. Per run: timestamp, git_commit, dataset_version,
provider, provider_config_id (no secret), llm_model, embedding_model, source_policy, connectivity
state, task/run ids, metric_version, env summary. **No** keys/tokens/cookies/secret headers; no full
copyrighted pages — URLs + metadata + short evidence excerpts + hashes only. Results are git-ignored
and regenerable.

## 8. Provenance rule (Phase 5 CRITICAL)

A source is `live_web` **only** when actually retrieved live this run. Cache fallback →
`cached_web`; local → `local_*`. A provider failure followed by cache fallback is **never**
reported as successful live retrieval. Tested explicitly (offline, mocked fallback).

## 9. Benchmark isolation (Phase 9) — mandatory

Live evaluation is **physically isolated** from #9/#10: live modules live under
`evaluation/live_web/`, never import into the deterministic benchmark/fixtures, never write live
URLs or cache into fixture data, and the #9/#10 suites run with **network disabled** (Ollama pinned
to a dead port). An explicit test asserts the #9/#10 fixture files are byte-unchanged after a live
run and that the deterministic suites don't depend on Tavily/internet.

## 10. Resilience (Phase 10)

Healthy / provider-failure / DNS-failure / timeout / cache-fallback / local-only / stale-cache /
partial-failure / recovery — exercised via the **existing** resilient-collection + retry
infrastructure; where a real provider can't be forced into a state, deterministic **mocked**
injection is used. No new retry/parallel system.

## 11. Fair baseline (Phase 7)

A conventional baseline over the **same captured sources**: raw provider top-k with **no
reliability re-ranking, no dedup, no verification** — to isolate the value of ResearchMind's
ranking/dedup/reliability. Clearly distinguished from the #9 and #10 baselines (not equivalent).

## 12. Improvement policy (Phase 12) & anti-overfit

Baseline first; classify P0/P1/P2/P3; fix only evidence-supported P0/P1 at root with a regression
test + benchmark re-verify; **no task-specific URL lists / domain hacks / special-case prompts**.
Prefer general improvements (generic ranking/query-planning/evidence-selection).

## 13. Security (Phase 15) & migrations (Phase 16)

No key leakage (manifest/report/logs/fixtures); reuse existing auth/ownership/SSRF (`net.validate_url`)
boundaries; no arbitrary URL-fetch tool. **No database migration** — reuse existing models + git-
ignored evaluation artifacts.

## 14. Non-goals (Phase 17)

No OCR/enterprise/multi-tenant/new-DB/scheduler/memory/citation/evidence/LLM-framework, no
permanent Tavily coupling, no autonomous agents, no UI redesign. Worthwhile ideas → "Future Work".

## 15. Acceptance (honest)

Harness + offline isolation/resilience/provenance/security = READY and executed. The **GitHub live
slice** is genuinely measured (collection metrics on real data). The **general-web live metrics are
NOT executed here** (no provider) and are reported as such — the milestone's live-quality verdict is
therefore **partial**, and the report recommends running the harness in a provisioned environment.

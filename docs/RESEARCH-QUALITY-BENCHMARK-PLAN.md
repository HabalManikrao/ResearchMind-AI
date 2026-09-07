# Research Quality Benchmark + Production Hardening (#9) — Plan

_Written **before** benchmark implementation (spec §3). This milestone validates and hardens
the existing architecture (spec §0, §1) — it adds **no** new engine. It produces two outputs:
a reproducible research-quality benchmark, and a hardened codebase with the P0/P1 defects the
benchmark exposes fixed at root._

---

## 1. Audit summary (measured, not assumed)

- Working tree clean; milestone #8 is committed (`f3fccc6`). **313 backend tests**, 50 frontend,
  `tsc`+build green, no benchmark dir yet.
- The pipeline's **decision-bearing outputs are computed deterministically**, not by the LLM:
  - **Confidence/status/contradiction**: `agents/verification.score_claim(supporting,
    contradicting, *, conflicting, as_of) -> (ClaimStatus, confidence, meta)` — a pure function
    of source count, mean reliability, recency, and contradiction count.
  - **Freshness**: `services/freshness.freshness_state(published_date, source_type, as_of)`.
  - **Provenance/availability**: `services/provenance` + `Source.provenance/.availability`.
  - **Diff**: `services/research_diff.diff_runs(old,new)` → NEW/STRENGTHENED/WEAKENED/
    CONTRADICTED/REMOVED + confidence/recommendation/source/provenance changes (no LLM in the
    default path).
  - **Significance**: `services/significance.evaluate(diff, settings, source_reliability=)` →
    impact LOW/MEDIUM/HIGH/CRITICAL + dedup keys (deterministic).
  - **Entity resolution / temporal**: `knowledge/graph.normalize_name`,
    `_resolve_or_create_entity` (conservative), `reconcile_from_diff` (SUPERSEDES/DISPUTED).
  - **Capability layer** (`app/capabilities/`) enforces ownership + bounds identically for REST
    and MCP.
  - The **LLM only** does: planning (question generation), clustering findings into claim text,
    and interpretive report prose. Web collection is the only other non-deterministic input.

**Consequence for benchmarking (§4, §21):** everything that determines *research quality that
can be objectively judged* — evidence support, confidence, contradiction handling, freshness,
provenance, diff categories, monitoring significance, entity resolution, temporal state,
authorization, bounds — is deterministic and can be benchmarked reproducibly **offline** with
controlled inputs carrying ground truth. The two non-reproducible inputs (live web, LLM prose)
are handled by controllable fixtures + a **manual-review protocol** for synthesis quality
(§41). This is honest: we automate what is objectively scorable and manually review what is not.

---

## 2. Benchmark objectives

1. Quantify research quality across claim accuracy, evidence support, citation correctness/
   completeness, contradiction detection/precision, confidence calibration, freshness,
   provenance, recommendation quality, completeness.
2. Quantify the behavior of Diff, Research Again, Monitoring, Knowledge Graph, Document RAG,
   offline, connectivity recovery, and cache.
3. Establish a **reproducible baseline** future milestones cannot silently regress (a pytest
   wrapper asserts thresholds).
4. Expose failures (§4, §23, §40) — the benchmark is a diagnostic instrument, not a demo.

## 3. Methodology

Each scenario is a machine-readable JSON fixture carrying the **inputs** (question, mode, a
deterministic set of collected sources with reliability/date/type/stance, optional prior-run
claims for diff/again/monitoring, documents for RAG) and the **ground truth** (expected claim
support labels, expected contradictions, expected confidence ordering, expected provenance,
expected diff categories, expected significance impact, expected entity identities). The runner
drives the **real deterministic engines** on those inputs and the metrics module scores the
structured outcomes against ground truth. No engine is reimplemented in the benchmark (§1, §25).

## 4. Scenario categories & distribution (spec §5) — 24 scenarios

```
5 factual/current          4 comparative            4 technical
3 conflicting-evidence     3 document/local         3 temporal/change
2 recommendation           2 knowledge-graph        + 1 end-to-end lifecycle (§43)
```
Deliberately difficult cases (§4): conflicting sources, outdated sources, ambiguous entities
(Apple/Apple Inc./Apple Records), low-quality vs authoritative sources, incomplete evidence,
changing facts, local-only, stale cache, recommendation reversal, monitoring false-positive/
false-negative, claim supersession.

## 5. Ground truth (spec §7)

- **Deterministic** — for confidence ordering, freshness, provenance, diff category,
  significance impact, entity identity (computed by pure functions → exact expected values).
- **Evidence-based** — each important claim declares its expected support label
  (supported / weakly_supported / contradicted / unsupported) from its labelled evidence.
- **Reference/expert** — recommendation appropriateness and synthesis get a manual-review note
  per scenario (§41); not auto-scored as pass/fail on prose.

## 6. Metrics (spec §8, §9) + weighting

Claims carry importance `critical|major|minor`; the aggregate score weights `critical=3,
major=2, minor=1` (§9). Metrics: claim_accuracy, evidence_support (supported/weak/contradicted/
unsupported breakdown), citation_correctness (cited evidence actually bears the declared
stance — not mere presence, §8/§40), citation_completeness, contradiction_detection (recall on
known conflicts), contradiction_precision, confidence_calibration (mean confidence of
correct-supported ≥ mean of unsupported — an ordering check, not a perfect model, §8),
freshness_correctness, provenance_correctness (zero false-live is a hard gate), diff_quality
(category accuracy), significance_accuracy, entity_resolution (no wrong merges; correct
aliases). Every metric emits per-scenario pass/fail so failures are visible.

## 7. Reproducibility (spec §21)

Fully deterministic: same fixtures → same scores, no network, no real Ollama (the pytest
wrapper pins `OLLAMA_BASE_URL` to a dead port, as the hardened suite already does). Results
record engine config (thresholds from `Settings`) + a schema version. `benchmark/results/
latest.json` is machine-readable; not committed as a large artifact (§22, §45) — regenerated
by `python -m benchmark.run_benchmark`.

## 8. Sub-benchmarks

- **Offline (§15)** — documents-only + knowledge/graph/memory reads with providers disabled;
  assert no false-live provenance.
- **Connectivity (§16)** — snapshot states + fallback + recovery via the existing connectivity
  manager (already unit-tested; benchmark asserts provenance + no false "no change").
- **Cache (§17)** — TTL, project isolation, cached≠live labelling.
- **Diff (§10) / Again (§11) / Monitoring (§12) / Graph (§13) / RAG (§14)** — scenario-driven
  against the real engines.
- **Performance & CPU/Ollama (§18, §19)** — count LLM/embedding calls per operation using an
  instrumented counting provider; assert monitoring Stage-1 makes **zero** LLM calls and only
  escalations invoke bounded Stage-2 work; record durations of the deterministic stages.

## 9. Acceptance thresholds (spec §39)

- **P0 = 0** (security / data-integrity / correctness), **P1 = 0** (major research-quality).
- critical claim support ≥ 0.95; major ≥ 0.85; citation_correctness ≥ 0.9;
  contradiction_detection ≥ 0.9 on known authoritative contradictions;
  confidence ordering holds; **provenance false-live = 0**; **cross-user violations = 0**;
  diff category accuracy ≥ 0.9; significance impact accuracy ≥ 0.9; entity wrong-merges = 0.
- All existing + new regression tests pass; tsc + build green.
Thresholds are asserted by `test_benchmark.py`; a regression drops the suite red.

## 10. Hardening (spec §24-§38)

Baseline first, then triage P0/P1/P2/P3; fix P0/P1 at root **with a regression test each**
(§25, §38) — never weaken a test or edit ground truth to hide a defect (§40). Security audit
(§26): authz (REST==MCP), cross-user/project, path traversal, SSRF, SQL/secret leakage,
bounds/pagination/idempotency/concurrency abuse. Failure injection (§31): provider/Ollama/
Qdrant/parser/graph/notification failures isolated. Recovery/restart (§32). DB integrity
(§29). Test isolation (§36, §37): the suite must be genuinely offline (the #8 fix pinning
Ollama to a dead port is verified here).

## 11. Non-goals (spec §1, §40, §14)

No new engine/DB/provider/scheduler/queue; no OCR; no penetration-testing project; no metric
gaming (no removing hard scenarios, no editing expected answers, no counting source-presence as
citation correctness); no requirement of byte-identical LLM reports or 100% factual accuracy;
no enterprise/billing/collaboration. LLM-synthesis prose quality is manually reviewed, not
auto-graded.

## 12. Deliverables

`benchmark/{scenarios,metrics.py,runner.py,run_benchmark.py}`, `backend/tests/test_benchmark.py`
(threshold guard) + hardening/failure-injection/E2E tests, `docs/RESEARCH-QUALITY-BENCHMARK-
REPORT.md`, `docs/PRODUCTION-HARDENING-COMPLETION.md`, updated `CLAUDE.md` + `GAP-ANALYSIS.md`.

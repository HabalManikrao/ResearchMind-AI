# Production Hardening — Completion (#9)

_Companion to `RESEARCH-QUALITY-BENCHMARK-REPORT.md`. Covers the security audit, failure
injection, test isolation, DB integrity, recovery, and end-to-end validation performed in
milestone #9. This milestone **added no engine and no dependency** and required **no
migration** — it validates and hardens the existing architecture (spec §0, §1)._

---

## Final Validation Report

```
Milestone #9 — Research Quality Benchmarking + Production Hardening

Audit:                         PASS
Plan Before Implementation:    PASS
Baseline Captured:             PASS
Benchmark Infrastructure:      PASS
Research Quality:              PASS
Claim Accuracy:                1.000
Evidence Support:              1.000
Citation Correctness:          1.000
Citation Completeness:         1.000   (every important scenario claim carries a support label)
Contradiction Detection:       1.000
Confidence Behavior:           1.000   (ordering/calibration gates)
Freshness:                     1.000
Recommendation Quality:        PASS    (auto: significance impact; prose: manual review §41)
Research Completeness:         PASS    (category coverage; end-to-end lifecycle coherent)
Research Again:                PASS
Research Diff:                 PASS
Monitoring:                    PASS
Knowledge Graph:               PASS
Document RAG:                  PASS
Offline:                       PASS
Connectivity Recovery:         PASS
Cache:                         PASS
Provenance:                    PASS    (zero false-live)
Performance:                   PASS
CPU/Ollama Budget:             PASS    (monitoring Stage-1 = 0 LLM calls, verified)
Security:                      PASS
Failure Injection:             PASS
Recovery:                      PASS
REST E2E:                      PASS
MCP E2E:                       PASS
Regression:                    PASS
Documentation:                 PASS

Benchmark Scenarios:           30
Scenarios Passed:              30
Scenarios Failed:              0

P0 Issues:                     0
P1 Issues:                     0  (1 found + fixed with regression tests)
P2 Issues:                     0
P3 Issues:                     1  (documented — /v1 validation/auth error shape)

Backend Tests:                 329 passed   (was 313; +16)
Frontend Tests:                50 passed
Benchmark Tests:               5 passed  (test_benchmark.py) + 30 scenarios
Security/Hardening Tests:      11 passed  (test_hardening.py) + existing security suite

Type Check:                    PASS
Build:                         PASS
Migration:                     NOT REQUIRED

Overall:                       READY
```

## Security audit (spec §26, §27, §45)

- **Cross-user / cross-project** isolation for research, claims, evidence, documents, graph,
  and monitors — enforced in the capability layer and verified via **both** REST and MCP
  (`test_capability_security.py`, incl. `test_cross_user_denied_via_mcp`). MCP does not bypass
  application security (spec §27, §37).
- **No dangerous tools**: `read_file`/`fetch_url`/arbitrary-SQL/shell are asserted absent from
  the capability registry and the MCP tool set; every MCP tool schema sets
  `additionalProperties:false` (`test_capability_security.py::test_no_dangerous_capabilities_or_tools`).
- **Path traversal / malformed ids** (`../../etc/passwd`, `'; DROP TABLE …`) → 404/422, never
  500 or an escape.
- **Graph traversal bounded** (depth hard-clamped ≤ 2); **research concurrency bounded**
  (per-user `concurrent_research_limit`); **idempotency** prevents duplicate expensive research
  on retry.
- **Pagination abuse — P1 FIXED**: `clamp_page(-1,…)` produced `LIMIT -1` (unbounded in SQLite),
  letting an external client pull an entire table. Fixed at root (floor page size at 1) in
  `capabilities/base.clamp_page` and `api/graph.list_entities`; regression tests added.
- **Secret / error leakage**: capability errors return a stable code + safe message + request
  id — no stack traces, SQL, paths, or secrets; `system_*` returns no keys/paths/env.
- **SSRF**: unchanged — all outbound fetches still route through the existing `net.validate_url`
  guard; #9 added no new outbound-fetch path.

## Failure injection (spec §31)

- **Embedding/Ollama outage** → document search degrades to zero passages, never 500
  (`test_hardening.py::test_embedding_failure_in_document_search_is_graceful`).
- **Graph build failure** → research still COMPLETES; `report_meta.graph_status` = degraded;
  retryable (`test_graph_failure_does_not_break_research`, plus `test_kg_integration.py`).
- **Provider/connectivity failure & recovery**, **monitoring degraded (incomplete external
  check → never "no change")**, **notification failure swallowed** — covered by the existing
  `test_pipeline_connectivity.py`, `test_monitoring_pipeline.py`, and `services/notifications`
  (best-effort by construction).

## Test isolation (spec §36, §37)

The suite is **genuinely offline**: `conftest.py` pins `OLLAMA_BASE_URL` to an unreachable
address and every LLM/embedding path is injected with `FakeProvider`. A guard test
(`test_hardening.py::test_suite_runs_offline`) fails if that regresses, so tests can never
silently start depending on a developer's running Ollama (the latent flake found while
hardening #8). The benchmark applies the same pin.

## DB integrity (spec §29, §33)

After a real run: every `KgRelationship`/`KgMention` references an existing entity; no
duplicate `(claim_id, source_id)` `ClaimSource` edges; lineage/root ids coherent
(`test_hardening.py::test_no_orphan_or_duplicate_graph_records`,
`test_full_lifecycle_coherent`). Referential integrity is maintained at the ORM/application
layer (cascades + ownership checks + idempotent upserts) — no destructive "cleaning" performed,
no migration introduced.

## Recovery & lifecycle (spec §32, §43, §44)

- **End-to-end lifecycle** (the key acceptance test, §43): research → evidence → claims →
  verification → report → memory → knowledge graph → monitoring → Research Again → diff → graph
  supersession, all coherent for one lineage (`test_full_lifecycle_coherent`).
- **External-client E2E** (§44): the full REST flow and the full MCP flow
  (`research_start → status → report → claims`) both consume the system without bypassing
  application logic (`test_rest_external_flow`, `test_mcp_external_flow`).
- **Restart / duplicate-prevention**: monitors persist and the poller is restart-safe with a
  concurrency guard (existing `test_monitor_service.py`); connectivity recovery retries failed
  external tasks once when the provider returns (existing `test_pipeline_connectivity.py`).

## CPU / Ollama observations (spec §18, §19)

- **Monitoring Stage-1 makes zero LLM calls** — verified by counting `structured_output`/
  `generate` on a no-change check (`test_monitoring_stage1_makes_no_llm_calls`). Only a
  candidate-significant change escalates to a bounded Stage-2 run.
- Research start/again are gated by `concurrent_research_limit` (per-user), so an external
  client cannot fan out unbounded LLM work.
- No new LLM/embedding calls were introduced; the benchmark itself makes **zero** LLM calls.

## Files

**New:** `docs/RESEARCH-QUALITY-BENCHMARK-PLAN.md`, `docs/RESEARCH-QUALITY-BENCHMARK-REPORT.md`,
this file; `benchmark/{__init__,runner,metrics,run_benchmark}.py` + `benchmark/scenarios/*.json`
(10 category files, 30 scenarios); `backend/tests/test_hardening.py`, `backend/tests/test_benchmark.py`.
**Modified:** `backend/app/capabilities/base.py` (clamp_page P1 fix),
`backend/app/api/graph.py` (list_entities P1 fix), `.gitignore` (benchmark results),
`CLAUDE.md`, `docs/GAP-ANALYSIS.md`.
**Dependencies added:** 0. **Migrations added:** 0.

## Known limitations / deferred

1. LLM-synthesis prose quality is manually reviewed, not auto-scored (spec §41).
2. Live-web collection quality is out of scope for a reproducible benchmark (no fixed corpus).
3. `/v1` validation/auth errors keep FastAPI's default `detail` shape (capability errors use the
   envelope); unifying them would change existing routes and is intentionally not done (P3).
4. SQLite FK enforcement is not globally enabled (many cross-table ids are intentionally plain
   strings, not declared FKs); integrity is enforced at the application layer as designed.

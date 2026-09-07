# API + MCP + Extensibility (#8) — Completion Report

_Completed: 2026-09-03. ResearchMind is now a research operating system whose capabilities
are consumed by humans (the existing UI), programmatically (REST `/v1`), and autonomously by
AI agents (MCP) — all through **one capability layer**, preserving the same evidence,
verification, provenance, memory, graph, monitoring and security semantics everywhere. Plan:
`docs/API-MCP-EXTENSIBILITY-PLAN.md`._

---

## Final Validation Report

```
Milestone #8 — API + MCP + Extensibility

Audit:                       PASS
Plan Before Code:            PASS
Capability Layer:            PASS
REST API:                    PASS
OpenAPI:                     PASS   (FastAPI auto-generates /openapi.json for /v1)
MCP Server:                  PASS
MCP Protocol Tests:          PASS
Authentication:              PASS
Authorization:               PASS
Research Capabilities:       PASS
Evidence Capabilities:       PASS
Document Capabilities:       PASS
Knowledge Capabilities:      PASS
Monitoring Capabilities:     PASS
Offline:                     PASS
Security:                    PASS
Performance Bounds:          PASS
Idempotency:                 PASS
Regression:                  PASS
Documentation:               PASS

Backend Tests:               313 passed
Frontend Tests:              50 passed
Capability Tests:            11 passed
MCP Tests:                   12 passed
(REST /v1: 10, capability security: 5 — included in the backend total)

Type Check:                  PASS
Build:                       PASS
Migration:                   NOT REQUIRED

Overall:                     READY
```

- **Backend tests:** 313 passed, 0 failed (was 275; **+38** — 11 capability, 10 REST /v1,
  12 MCP protocol, 5 security). **No test weakened or deleted.**
- **Frontend tests:** 50 passed (was 48; **+2** Integrations page).
- **Type check + build:** `tsc --noEmit` clean + `vite build` OK.
- **Migration:** **NOT REQUIRED** — no schema change. Idempotency is in-memory (bounded,
  TTL); audit reuses the existing `audit_logs` table.
- **Dependencies:** **none added.** The `mcp` pip SDK force-upgrades starlette/pydantic and
  breaks FastAPI 0.115, so MCP is implemented as a **dependency-free** stdlib JSON-RPC stdio
  server speaking the standard protocol. `requirements.txt` is unchanged.

---

## The architecture, proven (spec §55)

```
   REST /v1  ──┐                          MCP (stdio JSON-RPC)  ──┐
   (envelope,  │                           (tools/list, tools/call,│
    request-id,│                            resources, bounded)     │
    idempotency)▼                                                   ▼
             app/capabilities/   ← ONE implementation per capability
                   │               (ownership-enforced, bounded, plain dicts)
                   ▼
   research_service.manager · orchestrator · research_diff · knowledge.graph ·
   research_monitor · connectivity · documents.service · evidence
                   ▼
               SQLite / Qdrant / Ollama
```

There is **no** `MCP → database`, `MCP → custom research/evidence/graph logic`. The
`test_rest_and_mcp_equivalent` test proves REST and MCP hit the same capability and return
the same underlying data; `test_cross_user_denied_via_mcp` proves authorization is enforced
in the capability layer, not the adapter.

## Capability layer (`app/capabilities/`)

- **base.py** — `CapabilityError` + stable codes (`RESEARCH_NOT_FOUND`, `ACCESS_DENIED`,
  `INVALID_ARGUMENT`, `RESEARCH_IN_PROGRESS`, `CAPABILITY_UNAVAILABLE`,
  `CONNECTIVITY_DEGRADED`, `RATE_LIMITED`, `NOT_FOUND`); `resolve_user(token)` (mirrors
  `get_current_user` for MCP); `owned_project` (same 404-no-leak rule); the **capability
  registry** (20 entries with availability flags); an in-memory bounded **idempotency store**;
  `map_http_error` (reused internal helper errors → stable contract).
- **research / documents / knowledge / monitoring / system** — the single implementations,
  reusing the existing services and the #7 `api/graph.py` + #6 `api/monitors.py` read helpers
  (so REST/MCP/UI share exactly one graph/monitor read path).

## REST `/v1` (`app/api/v1.py`)

20 endpoints, additive/versioned — existing routes untouched, so the frontend and all 275
prior tests are unaffected. Auth via the same JWT dependency; **error envelope**
(`{"error":{code,message,request_id}}`) via a `CapabilityError` handler scoped to the
capability layer; **request IDs** via `RequestIdMiddleware` (echoed on every response);
**idempotency** via `Idempotency-Key`; **202 + Location** for long-running research;
pagination/limits bounded by config; OpenAPI auto-documented.

## MCP (`app/mcp/`, dependency-free)

A stdlib JSON-RPC 2.0 stdio server (`python -m app.mcp`) implementing `initialize`,
`tools/list`, `tools/call`, `resources/list`, `resources/read`, `ping`. **15 tools** with
strict input schemas (`additionalProperties: false`) binding to capabilities; results are
bounded structured content; `CapabilityError` → `isError` tool result with a machine code;
resources expose `research://{id}`, `research://{id}/claims`, `knowledge://entity/{id}`,
`knowledge://entity/{id}/history`. Auth via `RESEARCHMIND_TOKEN` (or the shared local user
when `AUTH_ENABLED=false`) — the documented local trust model. Tested at the protocol layer.

## Security controls (spec §37, §38, §39, §45)

- Every capability enforces ownership (own or legacy-NULL); cross-user research/claims/
  evidence/documents/graph/monitor all DENY (tested via REST **and** MCP).
- **No** `read_file` / `fetch_url` / arbitrary-SQL / shell tools — asserted absent from both
  the capability registry and the MCP tool set. Every tool schema forbids extra properties.
- Malformed/traversal ids (`../../etc/passwd`, `'; DROP TABLE…`) → 404/422, never 500 or an
  escape. Graph depth is hard-clamped (`depth=99 → ≤ 2`). Errors carry a code + safe message
  + request id — no stack traces/SQL/paths/secrets; `system_*` returns no keys/paths/env.

## Offline / provenance (spec §33, §46)

`knowledge_search`, `document_search`, and cached/local research work with no internet;
evidence keeps the #5 provenance (`live_web`/`cached_web`/`local_*`) verbatim — a cached/local
result is never labelled live. The transport never changes research semantics (§51).

## Performance / reliability (spec §22, §24, §49)

`concurrent_research_limit` (default 3) gates `start`/`again`; page sizes + graph depth reuse
existing bounds; MCP reports are excerpts by default; **idempotency prevents a client retry
from launching duplicate expensive research** (tested). MCP adds no extra LLM calls — same
underlying behaviour as REST. Long-running research returns 202 + an id and runs on the
existing background orchestrator (no second queue/scheduler).

## Files

**New (backend):** `capabilities/{__init__,base,research,documents,knowledge,monitoring,
system}.py`, `api/v1.py`, `mcp/{__init__,__main__,server,tools}.py`; tests
`test_capabilities.py`, `test_v1_api.py`, `test_mcp.py`, `test_capability_security.py`.
**New (frontend):** `pages/Integrations.tsx`; test `pages/Integrations.test.tsx`.
**New (docs):** this file + `API-MCP-EXTENSIBILITY-PLAN.md`.
**Modified (backend):** `config.py` (capability/idempotency/concurrency settings),
`security/middleware.py` (`RequestIdMiddleware`), `main.py` (middleware + `CapabilityError`
handler + `/v1` router).
**Modified (frontend):** `api/types.ts`, `api/client.ts`, `App.tsx` (route),
`components/Layout.tsx` (nav).
**Modified (docs):** `CLAUDE.md`, `GAP-ANALYSIS.md`.

- **Endpoints added:** 20 (`/v1/*`). **MCP tools:** 15. **MCP resources:** 4 URI templates.
  **Capability services:** 20 (across 6 modules). **Migrations:** 0. **Dependencies:** 0.

## Known limitations / deferred (with seams)

1. **Idempotency is in-memory** (single-instance) — documented; a shared store lands with the
   Postgres/Redis swap (Phase 7).
2. **MCP mutations** are limited to `research_start`/`research_again`; monitor create/update
   stays on the internal endpoint (read-only monitor tools exposed).
3. Future adapters (CLI, webhook) attach to the same registry — **not built** (§34, §52).
4. No SSO/OAuth-provider/billing/marketplace/GraphQL — explicit non-goals (§52).

## Definition of Done — acceptance (spec §53)

Audit + plan-before-code; capability layer with REST **and** MCP as thin adapters and no
duplicated logic (reusing engine/tasks/security); research start/status/report/claims/
evidence/again/diff; document search with preserved ingestion security; knowledge entity
search/detail/graph/history with bounds + provenance; monitor status/history reusing the #6
scheduler (no duplicate); stable REST contracts + OpenAPI + consistent errors + request ids +
auth + authz + pagination + limits + idempotency; MCP server with tested protocol calls,
schemas, error mapping, bounded output, offline; full cross-user security matrix + no
filesystem/SQL/URL escape + no secret leakage; long-running handled + retries idempotent +
capability failure isolated + offline correct; backend/frontend/MCP tests + type check +
build + regression green; docs complete; no scope creep — **all ✅**.

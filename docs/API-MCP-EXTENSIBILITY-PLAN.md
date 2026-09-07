# API + MCP + Extensibility (#8) — Implementation Plan

_Pre-implementation audit + design, written **before** code (spec §2, §3). The one rule:
**REST, MCP, and future adapters call the same capability services; they never duplicate
business logic** (§1, §4, §55). The property that matters is **consistency**, not endpoint
count (§56)._

---

## 1. Audit — current external interfaces & reusable pieces

Read: `main.py`, `api/*.py` (research, documents, knowledge, graph, monitors, notifications,
schedules, system, auth, monitoring), `security/{auth,middleware}.py`, `services/{audit,
research_service,research_diff,research_monitor,connectivity}.py`, `knowledge/graph.py`,
`documents/service.py`, `config.py`, `requirements.txt`, frontend `api/{client,types}.ts`.

| Concern | Current state | Reuse for #8 |
|---|---|---|
| **HTTP framework** | FastAPI 0.115 — **auto-generates OpenAPI** at `/openapi.json`, `/docs` | Use it; no hand-maintained schema (§19). |
| **Auth** | `get_current_user` (JWT bearer; or `_local_user()` when `AUTH_ENABLED=false`); `decode_token(token)->sub` | One auth model. Capability layer adds `resolve_user(token)` mirroring this for MCP (§30, §37). |
| **Ownership** | `research._get_project(db,id,user)` (404, no leak); `graph._get_entity`, `_related_entities`, `superseded_claim_ids`; monitor `_get_owned` | **Reused directly** — capabilities call these; authz stays server-side (§37). |
| **Research engine / tasks** | `research_service.manager` (`start`/`is_active`/`active_ids`), `orchestrator.run_research` (background asyncio) | Reused. No second engine/queue (§22, §52). |
| **Diff / graph / monitor / connectivity / documents** | `research_diff.diff_runs`, `knowledge.graph`, `research_monitor`, `connectivity.manager`, `documents.service` | Reused. No second diff/graph/scheduler/evidence (§12, §14, §15, §52). |
| **Audit** | `audit.record(action, project_id, user_id, request, detail)` (best-effort, own session) | Reused for external mutations (§36). |
| **Rate limit** | `RateLimitMiddleware` (per-IP sliding window) | Reused; add a `concurrent_research_limit` in the research capability (§24). |
| **Error shape** | `HTTPException(status, detail)` — the frontend + 275 tests expect `{"detail": ...}` | **Unchanged** on existing routes. The new `/v1` surface adds a structured **error envelope** so nothing breaks (§20). |
| **Versioning** | none (routes at root) | Add `/v1` as the **additive external contract**; existing routes stay for the frontend (§17, §18). |
| **MCP / capability layer** | **none** | New — the heart of #8. |
| **MCP SDK** | `mcp` pip package **force-upgrades starlette→1.6 / pydantic→2.13**, breaking FastAPI 0.115 | **Rejected.** MCP is implemented **dependency-free** as a stdlib JSON-RPC stdio server speaking the real MCP protocol (§25; "don't invent a custom protocol" — we implement the standard one). |

**Conclusion:** #8 = one capability layer + a thin `/v1` REST adapter + a thin stdlib MCP
adapter + request-IDs + an in-memory idempotency store. **No new dependency, no DB
migration, no change to existing routes or services.**

---

## 2. Architecture

```
        REST /v1  ─┐                         MCP (stdio JSON-RPC)  ─┐
   (error envelope,│                          (tools/list, tools/call,│
    request-id,    │                           resources, bounded)    │
    idempotency)   ▼                                                  ▼
                app/capabilities/  ← ONE implementation, transport-agnostic,
                     │                ownership-enforced, bounded, returns plain dicts
                     ▼
   research_service.manager · orchestrator · research_diff · knowledge.graph ·
   research_monitor · connectivity · documents.service · verification/evidence
                     ▼
                 existing SQLite / Qdrant / Ollama
```

A capability **never** touches the DB with bespoke research/evidence/graph logic — it calls
the existing services and the existing ownership helpers (§55). REST and MCP are adapters.

---

## 3. Capability layer (`app/capabilities/`)

Plain async functions grouped by domain; each takes a resolved `User` + validated args,
manages its own `SessionLocal`, enforces ownership, bounds output, and returns a JSON-safe
dict. Errors are raised as `CapabilityError(code, message, http_status)`.

- **base.py** — `CapabilityError` + machine-readable `codes` (`RESEARCH_NOT_FOUND`,
  `ACCESS_DENIED`, `INVALID_ARGUMENT`, `RESEARCH_IN_PROGRESS`, `CAPABILITY_UNAVAILABLE`,
  `CONNECTIVITY_DEGRADED`, `RATE_LIMITED`, `NOT_FOUND`); `resolve_user(token)`;
  `owned_project(db, id, user)` (wraps `research._get_project`); the **capability registry**
  (`Capability` dataclass: name, description, group, requires_network, may_invoke_llm,
  long_running); a bounded **idempotency store** (in-memory, TTL, per-user key → result).
- **research.py** — `search`, `start`, `status`, `report`, `claims`, `evidence`, `again`,
  `diff`. `start`/`again` honour an idempotency key and the `concurrent_research_limit`.
- **documents.py** — `search`, `list`, `status` (reuse `documents.service`; ownership).
- **knowledge.py** — `entity_search`, `entity`, `graph` (depth ≤ `kg_max_graph_depth`),
  `entity_claims`, `entity_history` (reuse the #7 `api/graph.py` helpers).
- **monitoring.py** — `status`, `history` (reuse `research_monitor` + models; read-only).
- **system.py** — `health`, `connectivity`, `capabilities`, `version`.

Everything is unit-tested **independently of any transport** (§42) — this is what proves the
adapters are thin.

---

## 4. REST `/v1` adapter (`app/api/v1.py`)

Thin endpoints calling capabilities. Additive `/v1` prefix; existing routes untouched.
- **Auth**: `get_current_user` (same JWT).
- **Error envelope** (§20): a `/v1` exception handler renders `CapabilityError` and
  `HTTPException` as `{"error": {"code","message","request_id"}}` with the right status —
  no stack traces / SQL / secrets.
- **Request IDs** (§21): a lightweight middleware sets/propagates `X-Request-ID` on every
  response and stashes it on `request.state`; the envelope includes it.
- **Idempotency** (§23): `start`/`again`/monitor-create accept an `Idempotency-Key` header;
  a repeat key returns the same result instead of launching duplicate expensive work.
- **Long-running** (§22): `POST /v1/research` returns **202** + `research_id`; clients poll
  `GET /v1/research/{id}/status` then `/report`. Reuses the background orchestrator.
- **Pagination/limits** (§30, §49): `limit`/`offset` bounded by config; graph depth clamped.
- **OpenAPI** (§19): response models + descriptions + tags so `/openapi.json` documents it.

Surface (all ownership-enforced):
```
GET  /v1/research?q=&limit=&offset=            POST /v1/research           (202)
GET  /v1/research/{id}/status                   GET  /v1/research/{id}/report
GET  /v1/research/{id}/claims                   GET  /v1/research/{id}/claims/{cid}/evidence
POST /v1/research/{id}/again        (202)       GET  /v1/research/{id}/diff/{otherId}
GET  /v1/documents?project_id=                  POST /v1/documents/search
GET  /v1/knowledge/entities                     GET  /v1/knowledge/entities/{id}
GET  /v1/knowledge/entities/{id}/graph          GET  /v1/knowledge/entities/{id}/claims
GET  /v1/knowledge/entities/{id}/history        GET  /v1/monitors/{project_id}
GET  /v1/monitors/{project_id}/history          GET  /v1/system/connectivity
GET  /v1/system/capabilities                    GET  /v1/system/version
```

---

## 5. MCP adapter (`app/mcp/`, dependency-free)

A stdlib **JSON-RPC 2.0 over stdio** server speaking the real MCP protocol:
- `initialize` → server info + capabilities; `tools/list` → tool schemas; `tools/call` →
  dispatch to a capability; `resources/list` / `resources/read` → read-only URIs
  (`research://{id}`, `research://{id}/claims`, `knowledge://entity/{id}`).
- **Handlers call the capability layer only** — never the DB/services directly (§25, §55).
- **Auth/trust** (§30): a stdio MCP process is local; the user is `resolve_user(token)` where
  the token comes from the `RESEARCHMIND_TOKEN` env var, or the shared local user when
  `AUTH_ENABLED=false` (documented local trust model). Credentials never appear in tool
  descriptions or outputs.
- **Bounded output** (§29, §31): concise structured results, pagination args, drill-down by
  id; reports return metadata + a bounded excerpt, not the whole document.
- **Error mapping** (§32): `CapabilityError.code` → MCP `isError` tool result with a
  machine-readable code; internal exceptions never leak.
- **Entrypoint**: `python -m app.mcp` runs the stdio loop.
- **Tested at the protocol layer** (§44): drive `initialize`→`tools/list`→`tools/call`
  (success, invalid args, unauthorized, missing, bounded, offline) against the real
  dispatcher, asserting MCP message shapes — not just helper functions.

Initial tools (≈15, high-value): `research_search`, `research_start`, `research_status`,
`research_report`, `research_claims`, `research_evidence`, `research_again`, `research_diff`,
`document_search`, `knowledge_search`, `knowledge_entity`, `knowledge_graph`,
`monitor_status`, `monitor_changes`, `system_connectivity`.

---

## 6. Security model (§30, §37, §38, §39, §45)

- Every capability enforces the existing ownership rule (own or legacy-`NULL`); cross-user
  access → `ACCESS_DENIED`/404, tested for research/claims/evidence/documents/graph/monitor.
- **No** `read_file`, no arbitrary SQL, no generic `fetch_url` (§38, §39, §52). Document
  access goes through the existing ownership/storage layer; web research goes through the
  existing collection/provenance/cache path only.
- Errors carry a stable code + safe message + request id — never stack traces, SQL, paths,
  or secrets (`system_*` never returns keys/paths/env).
- MCP is not assumed trusted: it authenticates via the same token mechanism.

---

## 7. Offline & provenance (§33, §46)

Knowledge/document/graph capabilities work fully offline (SQLite/Qdrant/Ollama). Research
capabilities preserve the existing #5 provenance: a cached/local result is labelled
`cached`/`local_*`, never `live_web`; the response carries `connectivity` + `research_mode`
so an agent can tell. No transport ever changes research semantics (§51).

---

## 8. Extensibility (§34, §35)

The capability registry (name/description/availability/requires_network/may_invoke_llm/
long_running) is the discovery surface, exposed at `GET /v1/system/capabilities` (and the
`system_connectivity`/tools list for MCP). Future adapters (CLI, webhook) attach to the same
registry — none are built now (§34, §52).

---

## 9. Performance / limits (§24, §49)

`concurrent_research_limit` (default 3) gates `start`/`again`; page sizes and graph depth
reuse the existing bounds; reports/evidence are bounded; MCP adds **no** extra LLM calls —
identical underlying behaviour to REST. Retries are idempotent, so a client retry never
launches duplicate research.

---

## 10. Migration & deps (§48)

**None.** Idempotency is in-memory (bounded, TTL) — documented single-instance limitation;
audit reuses the existing table. **No new Python dependency** (MCP is stdlib). `requirements.txt`
unchanged.

---

## 11. Testing (§42–§47, §51)

Capability unit tests (valid/invalid/authz/missing/bounded/degraded), REST `/v1` tests
(auth/authz/start-202/status/report/claims/evidence/again/diff/doc-search/knowledge/graph/
monitor/connectivity/errors/pagination/request-id/idempotency), **MCP protocol tests**
(initialize/tools-list/tools-call/invalid-args/unauthorized/error-mapping/bounded/offline/
long-running), security cross-user matrix + malformed-id + depth/pagination bounds + secret
leakage, offline (knowledge/doc/cached research, no false live), and **compatibility**
(REST and MCP → same capability → equivalent result). Regression: full `pytest` + `vitest`
+ `tsc --noEmit` + `vite build` green.

---

## 12. Non-goals (§52) — explicitly not built

SSO/OAuth platform, billing, marketplace, developer portal, webhooks, Slack/Teams/email/
Zapier, plugin marketplace, arbitrary code/SQL/filesystem/URL-fetch tools, browser
automation, second queue/scheduler/engine/evidence/diff/memory/graph, Neo4j, GraphQL,
distributed/multi-tenant. Future adapters (CLI/webhook) are documented, not implemented.

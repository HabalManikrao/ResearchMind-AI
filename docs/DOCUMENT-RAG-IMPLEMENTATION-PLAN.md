# Document RAG (#3) — Implementation Plan

_Planned: 2026-08-28. Inspection-first, per the milestone brief. The governing principle: **make
user documents first-class research evidence by EXTENDING the P0 evidence architecture, not by
adding a parallel citation system.** A document passage becomes the same `ClaimSource` evidence a
web passage does._

---

## 1. Existing architecture (inspected)

- **Collection is pluggable.** `agents/dispatch.py::collect(source_type, provider, tavily, settings,
  *, question, search_query, recency_days)` maps a source key → an agent's `collect(...)` that
  returns a uniform `CollectedSource` (title, url, content, summary, reliability, relevance,
  source_type, published_date, findings[], meta{}). The orchestrator persists these as `Source` +
  `Finding` rows **source-agnostically**, then `verify()` builds `Claim` + `ClaimSource(passage)`.
  → **A document retriever that returns `CollectedSource` needs zero pipeline changes downstream.**
- **Qdrant** (`knowledge/vector_store.py`): one embedded on-disk client (`get_client()`, file-locked
  singleton), one `knowledge` collection (project-summary vectors). Cosine, lazy create, payload
  filtering by `project_id`.
- **Embeddings** (`llm/ollama_provider.embed`, `nomic-embed-text`, batched via `/api/embed`);
  `knowledge/service._embed` wraps with `KnowledgeUnavailable` fallback. `FakeProvider.embed` gives
  deterministic vectors in tests → offline-testable.
- **Evidence** (P0): `ClaimSource(claim_id, source_id, stance, passage)`; `Source.freshness` property
  via `services/freshness.freshness_state(published_date, source_type)`; evidence exposed at
  `GET /research/{id}/claims/{claim_id}/evidence`.
- **Freshness** thresholds centralized in `services/freshness._THRESHOLDS` (per source type).
- **Background work**: in-process asyncio (`RunManager`); no Celery. Startup `init_db()` =
  idempotent `create_all` + `_ensure_columns`.
- **Deps present**: `python-docx` (already, for export), `qdrant-client`, `httpx`. **Missing: a PDF
  parser** → add `pypdf` (pure-python, offline).
- **Frontend**: sidebar `NAV` (`Layout.tsx`), routes (`App.tsx`), source picker (`NewResearch.tsx`
  `SOURCES`), project tabs (`LiveResearch.tsx`), evidence rendering (`EvidenceGroup`). Multipart
  upload does not exist; `api.req()` always sets JSON content-type → needs a dedicated upload path.

## 2. Reusable components (do NOT duplicate)

`CollectedSource` + `dispatch` (add a branch), `Source`/`Finding`/`Claim`/`ClaimSource` persistence,
`verify()`/`score_claim` (unchanged), `services/freshness` (add a `documents` threshold), the Qdrant
client + embeddings, the evidence endpoint (add `page_number`), the frontend evidence component
(extend to render 📄 sources), `_get_project` ownership pattern.

## 3. New components

- **Models** `models/document.py`: `Document`, `DocumentChunk`, enum `DocumentStatus`.
- **Parsing** `documents/parsing.py`: `parse_pdf` (pypdf, per-page + metadata), `parse_docx`
  (python-docx, paragraphs/headings/tables + core props). Both → `ParsedDoc(blocks, page_count,
  word_count, meta)`. No OCR (out of scope).
- **Chunking** `documents/chunking.py`: structure-aware (heading/paragraph/page boundaries, token
  budget + overlap), deterministic, no LLM. Emits page/section/char offsets.
- **Vector store** (extend `vector_store.py`): `documents` collection + `upsert_documents`,
  `search_documents(vector, project_id, document_id?, limit, score_threshold)`, `delete_document`,
  `delete_documents_by_project`.
- **Service** `documents/service.py`: validate → store → checksum → `process_document` (async
  pipeline with status transitions, fail-safe) → `retrieve` → `delete`. Duplicate detection by
  checksum+project.
- **Collection agent** `agents/document_research.py`: `collect(...)` retrieves top chunks for the
  query (project-filtered), LLM-extracts findings from each (reusing the existing extract pattern),
  returns `CollectedSource(source_type="documents", url="document://…", meta={document_id, chunk_id,
  page_number, filename, section})`.
- **API** `api/documents.py` + **schemas** `schemas/document.py`.
- **Frontend**: `pages/` Documents tab in `LiveResearch`, upload/list/search, evidence extension.

## 4. Data model

**Document**: id, project_id (FK CASCADE), user_id (FK SET NULL, ownership defense-in-depth),
filename (stored uuid name), original_filename, mime_type, size_bytes, checksum (sha256, indexed),
storage_path (internal, never exposed), status (`DocumentStatus`), page_count, word_count,
chunk_count, error_message, meta (JSON: title, created/modified dates), created_at/updated_at,
processed_at.

**DocumentChunk**: id, document_id (FK CASCADE), project_id (denormalized for Qdrant-independent
isolation), chunk_index, text, page_number, section, char_start, char_end, token_count, point_id
(Qdrant), meta, created_at.

**DocumentStatus**: `uploaded → parsing → chunking → embedding → indexing → ready` | `failed`.

Both are **new tables** → `create_all` handles them; **no column added to an existing table**, so no
`_ensure_columns` change. `ClaimEvidenceItem` gains `page_number` (schema-only; read from
`Source.meta`).

## 5. Retrieval architecture

Query → embed (nomic-embed-text) → `search_documents` (Qdrant, **filtered by `project_id`** ⇒ hard
project isolation; optional `document_id`) → top-K above `min_score` → load chunk rows → passages
with {filename, page, section, text, score}. Used by both the Documents "search" endpoint and the
document collection agent. Separate `documents` collection (justified: chunk-granularity vs the
`knowledge` collection's project-summary granularity, independent delete lifecycle, distinct
payload).

## 6. Pipeline integration (the crux)

Add `documents` to `dispatch.ALL_SOURCES`, `SOURCE_ORDER`, `SOURCE_QUESTION_BUDGET`, `AGENT_LABELS`,
and thread `project_id` through `dispatch.collect` (needed only by the document agent). The agent
returns `CollectedSource`s; **everything after collection is unchanged** — Source/Finding persist,
`verify()` builds Claims + `ClaimSource(passage=finding)`, `score_claim` applies reliability +
freshness (document date) + contradiction. Document reliability = fixed primary-ish base (~70, not
authoritative like official docs) nudged by retrieval score.

- **Offline**: a run with `sources_enabled=["documents"]` makes **zero network calls** (local Qdrant
  + local Ollama). This is the offline research path.
- **Hybrid**: `["documents","web",…]` dispatches both; evidence is unified with provenance intact.

## 7. API design

`POST /documents` (multipart: file + project_id) → 201; `GET /documents?project_id=`;
`GET /documents/{id}`; `GET /documents/{id}/status`; `GET /documents/{id}/chunks`;
`DELETE /documents/{id}`; `POST /documents/search` {project_id, query, top_k?}. Every endpoint
enforces project ownership (reusing the `_get_project` rule). Storage paths never leave the server.
Processing runs as a background asyncio task; the client polls `/status`.

## 8. UI design

- **Documents tab** in the project view: upload (file input; drag-drop optional), list (original
  filename, status badge, size, pages, uploaded date, error), delete, and "search within documents"
  → passages with filename + page. Dedicated multipart upload in the api client.
- **Evidence**: extend `EvidenceGroup` so a `source_type==="documents"` item renders 📄 filename ·
  p.N + passage (no external link) instead of a web link. Same stance/freshness/confidence UI.
- **NewResearch**: add `Documents` to the source picker.

## 9. Testing strategy

Backend: parsing (real DOCX via python-docx; real PDF via `reportlab`, dev-only), chunking
(boundaries/overlap/metadata/determinism), security (ext/mime/size/magic-byte/sanitize), service
(process end-to-end with `FakeProvider` embeddings, retrieve, duplicate dedup, delete), API (upload,
ownership cross-user/cross-project 404, invalid/oversize, list/get/status/chunks/search/delete),
pipeline (documents-only offline run → document `ClaimSource` evidence; hybrid). Frontend: Documents
component (upload/status/list/search) + document evidence rendering. **All existing P0 tests must
stay green.**

## 10. Migration strategy

Additive only: two new tables via `create_all` (idempotent, no data touched); a new Qdrant
collection created lazily. No changes to existing tables/rows. Verified by starting twice.

## 11. Security

Untrusted input: extension allowlist (.pdf/.docx) + **magic-byte sniff** (not client MIME), size cap
(`max_document_mb`), filename sanitization (basename only, no traversal), UUID storage names (client
filename never used as a path), sha256 checksum + duplicate detection, cleanup on failure, uploaded
bytes never executed, storage dir gitignored. Ownership enforced on every endpoint and in the Qdrant
`project_id` filter (Project A docs can never surface in Project B).

## 12. Offline behavior

Documents-only research is fully local (no web/API calls). The report/agent label makes clear the
evidence is document-derived. Upload date ≠ publication date: freshness uses document metadata dates
only; missing → UNKNOWN (never "fresh" just because uploaded now). Full internet-loss auto-detection
(P1 item #5) is **out of scope**; "offline" here means the documents source needs no network.

## Config additions

`document_storage_dir=./document_storage`, `max_document_mb=25`, `document_chunk_tokens=350`,
`document_chunk_overlap_tokens=60`, `document_retrieval_top_k=5`, `document_retrieval_min_score=0.25`,
`document_embed_batch=16`.

## Out of scope (§33)

OCR, images/video/audio, annotation, KG redesign, alerts, diff, MCP, connectors, and full
connectivity auto-detection.

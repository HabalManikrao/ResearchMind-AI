# Document RAG (#3) — Completion Report

_Completed: 2026-08-28. Implements PDF/DOCX ingestion and offline document research by **extending**
the P0 evidence architecture. Plan: `docs/DOCUMENT-RAG-IMPLEMENTATION-PLAN.md`._

---

## Final Validation Report

```
Document RAG Status:  READY

Backend tests:        152 passed, 0 failed  (pytest, all offline)
Frontend tests:        13 passed, 0 failed  (vitest: evidence + ClaimsTab + DocumentsPanel)
Build:                frontend `npm run build` OK (tsc --noEmit clean + vite build)
Migration:            additive + idempotent (2 new tables); existing data preserved

PDF ingestion:        READY  (pypdf, per-page text + metadata; encrypted/scanned/empty → FAILED)
DOCX ingestion:       READY  (python-docx paragraphs/headings/tables + core props)
Qdrant indexing:      READY  (separate `documents` collection, project-id filtered)
Retrieval:            READY  (semantic, project-isolated, top-K + score threshold)
ClaimSource integration: READY  (document passages become the same evidence a web passage does)
Evidence UI:          READY  (📄 filename · page in the expandable Claims drill-down)
Offline research:     READY  (documents-only run makes zero network calls)
Hybrid research:      READY  (documents + web dispatched together)
Security:             READY  (magic-byte + size + sanitize + ownership + project isolation)
Performance:          READY  (deterministic parse/chunk; batched embeddings; bounded)
```

---

## What was implemented

Uploaded PDF/DOCX are now **first-class research evidence**. A document is a project-scoped upload
that is validated, stored safely, parsed, chunked, embedded, and indexed into Qdrant. At research
time a `documents` collection agent retrieves the most relevant passages and returns them as the
uniform `CollectedSource` every other agent returns — so persistence, verification, claim
consolidation, `ClaimSource` evidence links, freshness, confidence, and the evidence drill-down UI
all work **unchanged**. A documents-only run is fully local (offline); documents + web run together
(hybrid). A Documents tab lets users upload, watch processing status, list/delete, and semantically
search within their documents.

## Files changed

**New (backend):** `models/document.py`, `documents/{__init__,parsing,chunking,service}.py`,
`agents/document_research.py`, `api/documents.py`, `schemas/document.py`, and tests
`test_document_{parsing,chunking,security,service,pipeline}.py`, `test_api_documents.py`.
**New (frontend):** `components/DocumentsPanel.tsx` (+ `DocumentsPanel.test.tsx`).
**New (docs):** this file + `DOCUMENT-RAG-IMPLEMENTATION-PLAN.md`.
**Modified (backend):** `models/enums.py` (`DocumentStatus`), `models/__init__.py`, `config.py`
(`document_*`), `services/freshness.py` (`documents` threshold), `services/scoring.py`
(`document_reliability`), `knowledge/vector_store.py` (`documents` collection fns),
`agents/dispatch.py` (+`documents` branch, `project_id` param), `agents/common.py` (label),
`orchestration/orchestrator.py` (`SOURCE_ORDER`/budget + thread `project_id`),
`schemas/research.py` (`ClaimEvidenceItem.page_number`), `api/research.py` (evidence page_number),
`main.py` (router), `requirements.txt` (`pypdf`, `python-multipart`), `requirements-dev.txt`
(`reportlab`), `tests/conftest.py` (builders + env pins).
**Modified (frontend):** `api/types.ts`, `api/client.ts` (upload/list/delete/search),
`pages/LiveResearch.tsx` (Documents tab + 📄 evidence + source style), `pages/NewResearch.tsx`
(source), `pages/ClaimsTab.test.tsx`.

## Database changes

Two **new** tables (additive; `create_all` handles them, no `_ensure_columns` needed):
- **`documents`** — id, project_id (FK CASCADE), user_id (FK SET NULL), filename, original_filename,
  mime_type, size_bytes, checksum (sha256, indexed), storage_path (internal), status, page_count,
  word_count, chunk_count, error_message, processed_at, meta, timestamps.
- **`document_chunks`** — id, document_id (FK CASCADE), project_id (denormalized for isolation),
  chunk_index, text, page_number, section, char_start, char_end, token_count, point_id (Qdrant), meta.

No existing table or row was modified. Vectors live in a new Qdrant `documents` collection.

## APIs added

`POST /documents` (multipart upload) · `GET /documents?project_id=` · `GET /documents/{id}` ·
`GET /documents/{id}/status` · `GET /documents/{id}/chunks` · `DELETE /documents/{id}` ·
`POST /documents/search`. Every endpoint enforces project ownership (404 for another user/project).
`ClaimEvidenceItem` gained `page_number`.

## Verification methodology (unchanged, extended to documents)

Document passages are persisted as `Source(source_type="documents")` + `Finding`, consolidated by the
existing `verify()`/`score_claim`, and linked as `ClaimSource(passage)`. Document reliability is a
fixed primary-ish base (~70, not authoritative like official docs) nudged by retrieval score;
freshness uses the document's own publication/creation date (never the upload time). Contradiction
search and confidence apply identically.

## UI

The Claims drill-down renders document evidence as `📄 filename · p.N` + quoted passage (sky-styled,
no external link), grouped supporting/contradicting exactly like web evidence. A Documents tab
provides upload (PDF/DOCX), live status, list with size/pages/chunks/date/error, delete, and
search-within-documents showing passages with page numbers. `Documents` is a selectable research
source.

## Testing

- **Parsing** — real PDF (reportlab) + DOCX (python-docx); pages/headings/sections; empty & corrupt → error.
- **Chunking** — heading/size boundaries, page/section/char metadata, overlap, determinism, empty.
- **Security** — extension/mime/size rejection, magic-byte mismatch, filename traversal sanitization.
- **Service** — process→index→retrieve, duplicate dedup, **project isolation in retrieval**, delete
  removes chunks+vectors, corrupt doc → FAILED (no DB corruption).
- **API** — multipart upload→ready→search, bad type/mismatch 400, cross-user & cross-project 404, delete.
- **Pipeline** — documents-only **offline** run produces document-backed `ClaimSource` evidence with
  passages; **hybrid** documents + web completes with document evidence.
- **Frontend** — DocumentsPanel upload/list/status/empty/search; document evidence rendering in Claims.

All 152 backend + 13 frontend tests pass; existing P0 tests unchanged and green.

## Performance / cost (CPU Ollama)

Parsing and chunking are deterministic and CPU-cheap (no LLM). Embeddings are batched
(`document_embed_batch`, default 16), one pass per document. Per research task the document agent
does 1 retrieval embed + up to `max_sources_per_task` extraction calls (same as web). No fan-out; a
large PDF yields more chunks (bounded embedding batches) but not uncontrolled LLM calls. Retrieval is
a single vector query.

## Known limitations

1. **Text-based documents only** — no OCR; scanned/image PDFs are rejected with a clear message (OCR
   is a future milestone, explicitly out of scope).
2. **Freshness thresholds centralized but not env-configurable** (same as P0).
3. **SQLite FKs not enforced by default** — integrity via ORM + explicit deletes; enforced natively
   after the planned Postgres swap. (`delete_document` explicitly removes vectors + chunk rows.)
4. **Upload-then-run UX**: a document must be READY before the run's collection stage uses it; the
   smooth flow is upload in the Documents tab, then run with the Documents source enabled. A
   one-click "research my documents" is nicer once **Research Again (#4)** lands.
5. **"Offline" = the documents source needs no network** (local Qdrant + Ollama). Full
   internet-loss auto-detection / live-vs-cached tagging is **#5**, not this milestone.
6. **Retrieval is pure semantic** (no hybrid keyword/rerank) — sufficient for the corpus sizes a
   personal tool handles.

## Future improvements

OCR for scanned PDFs; hybrid keyword+vector retrieval + reranking; document preview/deep-linking to a
page; per-document freshness override; auto-enable the Documents source when a project has documents;
larger-file streaming ingestion.

## Recommended next milestone

**#4 Research Memory + "Research Again" + Diff** — versioned runs, continue-with-prior-context, and a
"what changed" delta. It also smooths the document upload→run flow (limitation #4) and builds directly
on the now-complete evidence + document substrate.

---

## Definition of Done — checklist

| Criterion | Status |
|---|---|
| Upload PDF/DOCX | ✅ |
| Safe parse/chunk/index | ✅ |
| Relevant passage retrieval | ✅ |
| Passages → ClaimSource evidence | ✅ |
| Claims cite exact document passages | ✅ (filename + page) |
| Expand claim → document evidence in UI | ✅ |
| Document evidence in confidence/contradiction logic | ✅ (same engine) |
| Offline research (local docs + local infra) | ✅ |
| Hybrid document + web research | ✅ |
| Cross-user / cross-project isolation | ✅ |
| Failures don't corrupt existing research | ✅ |
| Existing tests green + new coverage | ✅ (152 + 13) |
| Documentation updated | ✅ |

"""Document research agent: retrieve relevant passages from the project's uploaded
documents and return them as `CollectedSource`s.

By emitting the same uniform `CollectedSource` the web/GitHub/arXiv agents do, document
passages flow through the existing pipeline unchanged — persisted as `Source`/`Finding`,
consolidated into `Claim`s, and linked as `ClaimSource` evidence with the same
stance/passage/freshness/confidence treatment. This is the offline research path:
retrieval + extraction are fully local (Qdrant + Ollama), no network.
"""
from __future__ import annotations

from app.agents.common import CollectedSource
from app.documents import service as doc_service
from app.llm.base import AIProvider
from app.services.scoring import document_reliability

_FINDINGS_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "findings": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["summary", "findings"],
}

_SYSTEM = (
    "You extract factual, on-topic findings from a passage of a user's document, "
    "relative to a specific research question. Only use information present in the "
    "passage. Never invent facts. Return a short summary and concise standalone findings."
)


async def collect(
    provider: AIProvider,
    *,
    project_id: str,
    question: str,
    search_query: str,
    max_results: int = 5,
    min_score: float | None = None,
) -> list[CollectedSource]:
    chunks = await doc_service.retrieve(
        project_id, search_query or question, top_k=max_results, min_score=min_score
    )
    sources: list[CollectedSource] = []
    for ch in chunks:
        if not ch.text.strip():
            continue
        summary, findings = await _extract(provider, question, ch.text)
        rel01 = max(0.0, min(1.0, ch.score))
        sources.append(
            CollectedSource(
                title=ch.filename,
                url=f"document://{ch.document_id}",  # synthetic; no filesystem path exposed
                content=ch.text,
                summary=summary or ch.text[:200],
                reliability_score=document_reliability(relevance=rel01),
                relevance_score=round(rel01 * 100, 1),
                source_type="documents",
                published_date=ch.published_date,
                findings=findings,
                meta={
                    "document_id": ch.document_id,
                    "chunk_id": ch.chunk_id,
                    "page_number": ch.page_number,
                    "section": ch.section,
                    "filename": ch.filename,
                },
            )
        )
    return sources


async def _extract(provider: AIProvider, question: str, text: str) -> tuple[str, list[str]]:
    prompt = (
        f"Research question:\n{question}\n\n"
        f"Document passage:\n{text[:3000]}\n\n"
        "Extract findings relevant to the question. Return JSON."
    )
    try:
        data = await provider.structured_output(prompt, schema=_FINDINGS_SCHEMA, system=_SYSTEM)
    except Exception:  # noqa: BLE001
        return (text[:300], [])
    summary = str(data.get("summary", "")).strip()
    findings = [str(f).strip() for f in data.get("findings", []) if str(f).strip()]
    return summary, findings

"""Knowledge Gap Analysis (spec §8).

Given the research questions and how much evidence each accumulated, decide which
questions remain under-answered and propose follow-up search queries. This drives
the automatic follow-up research loop — a core feature (spec rule §23.11).
"""
from __future__ import annotations

from dataclasses import dataclass

from app.llm.base import AIProvider

_GAP_SCHEMA = {
    "type": "object",
    "properties": {
        "gaps": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "question": {"type": "string"},
                    "reason": {"type": "string"},
                    "followup_query": {"type": "string"},
                },
                "required": ["question", "followup_query"],
            },
        }
    },
    "required": ["gaps"],
}

_SYSTEM = (
    "You assess whether each research question has been sufficiently answered by the "
    "available findings. For questions with weak or missing evidence, you propose a "
    "focused follow-up web search query that would fill the gap. Only flag genuine "
    "gaps; if a question is well covered, do not include it."
)


@dataclass
class KnowledgeGap:
    question: str
    reason: str
    followup_query: str


async def find_gaps(
    provider: AIProvider,
    *,
    questions: list[str],
    evidence_by_question: dict[str, list[str]],
    max_gaps: int = 4,
) -> list[KnowledgeGap]:
    blocks = []
    for q in questions:
        ev = evidence_by_question.get(q, [])
        joined = "\n".join(f"  - {e}" for e in ev[:6]) or "  (no findings collected)"
        blocks.append(f"Question: {q}\nFindings:\n{joined}")
    prompt = (
        "Assess evidence coverage per question and identify knowledge gaps.\n\n"
        + "\n\n".join(blocks)
        + "\n\nReturn JSON listing only questions with insufficient evidence."
    )
    try:
        data = await provider.structured_output(
            prompt, schema=_GAP_SCHEMA, system=_SYSTEM
        )
    except Exception:
        return []

    gaps: list[KnowledgeGap] = []
    for g in data.get("gaps", [])[:max_gaps]:
        q = str(g.get("question", "")).strip()
        fq = str(g.get("followup_query", "")).strip()
        if not q or not fq:
            continue
        gaps.append(
            KnowledgeGap(
                question=q, reason=str(g.get("reason", "")).strip(), followup_query=fq
            )
        )
    return gaps

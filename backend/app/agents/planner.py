"""Research Planner Agent (spec §2, Agent 2).

Converts a natural-language request into a structured objective plus a list of
research questions, each with a concrete web search query.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.llm.base import AIProvider

_PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "objective": {"type": "string"},
        "questions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "priority": {"type": "integer"},
                    "search_query": {"type": "string"},
                },
                "required": ["text", "priority", "search_query"],
            },
        },
    },
    "required": ["objective", "questions"],
}

_SYSTEM = (
    "You are a meticulous research planner. Given a user's research request, you "
    "produce a crisp research objective and a set of specific, non-overlapping "
    "research questions that together fully cover the request. For each question "
    "you also write a focused web search query. Prioritise 1 (most important) to "
    "5 (least). Do not answer the questions; only plan."
)

_MARKET_SYSTEM = (
    "You are a market-intelligence research planner. The user wants to know what is "
    "happening RIGHT NOW in a market or field. Produce a crisp objective and a set of "
    "specific, non-overlapping questions that capture the CURRENT state: key players "
    "and their recent moves, latest products/releases, pricing and adoption, funding/"
    "M&A, notable trends, and near-term outlook. For each question write a web search "
    "query that targets recent information — include the current year and words like "
    "'latest', 'recent', or 'this year' where useful. Prioritise 1 (most important) to "
    "5. Do not answer the questions; only plan."
)


# Per-intent steering appended to the planner system prompt when a run continues a
# previous one (#4 Research Again). Kept short so it biases, not overwhelms, the plan.
_INTENT_ADDENDA = {
    "refresh": (
        " This is a REFRESH of earlier research. Re-verify whether the prior findings below "
        "still hold and prioritise information that is NEWER than the previous research date "
        "and any changes since then. Do not simply repeat settled, high-confidence claims."
    ),
    "deepen": (
        " This CONTINUES earlier research. Focus your questions on the unresolved / open "
        "questions below and on gaps the prior run did not answer; do not re-litigate the "
        "high-confidence claims already established."
    ),
    "verify": (
        " This VERIFIES earlier research. Design questions that specifically re-check the "
        "important prior claims below — look for corroborating and, especially, contradicting "
        "evidence for each."
    ),
    "full": (
        " This is a fresh, comprehensive re-research of the same objective. Cover it fully, but "
        "avoid trivially repeating the settled high-confidence claims below unless re-checking "
        "them is essential."
    ),
}


@dataclass
class PriorContext:
    """Selective memory of a previous run fed to the planner on a continuation
    (#4). Deliberately compact — never the whole prior report (spec §8)."""

    objective: str = ""
    as_of: str | None = None  # previous research date
    high_confidence_claims: list[str] = None  # type: ignore[assignment]
    open_questions: list[str] = None  # type: ignore[assignment]
    contradictions: list[str] = None  # type: ignore[assignment]
    recommendation: str | None = None

    def as_prompt(self) -> str:
        parts: list[str] = ["\n\n=== Previous research (for context; do not just repeat it) ==="]
        if self.as_of:
            parts.append(f"Previous research date: {self.as_of}")
        if self.objective:
            parts.append(f"Previous objective: {self.objective}")
        if self.high_confidence_claims:
            parts.append("Established high-confidence claims:")
            parts += [f"- {c}" for c in self.high_confidence_claims]
        if self.open_questions:
            parts.append("Open / unresolved questions:")
            parts += [f"- {q}" for q in self.open_questions]
        if self.contradictions:
            parts.append("Known contradictions:")
            parts += [f"- {c}" for c in self.contradictions]
        if self.recommendation:
            parts.append(f"Previous recommendation: {self.recommendation}")
        return "\n".join(parts)


@dataclass
class PlannedQuestion:
    text: str
    priority: int
    search_query: str


@dataclass
class ResearchPlan:
    objective: str
    questions: list[PlannedQuestion]


async def make_plan(
    provider: AIProvider,
    query: str,
    *,
    constraints: dict | None = None,
    max_questions: int = 8,
    market: bool = False,
    as_of: str | None = None,
    prior_context: "PriorContext | None" = None,
    intent: str = "original",
    brief_context: str | None = None,
) -> ResearchPlan:
    constraint_str = ""
    if constraints:
        constraint_str = "\nUser constraints/preferences:\n" + "\n".join(
            f"- {k}: {v}" for k, v in constraints.items() if v
        )
    # R&D layer (Phase A): the structured research brief (problem/scope/constraints/
    # objectives) steers planning deterministically — assembled by the caller, no extra LLM.
    brief_str = f"\n{brief_context}" if brief_context else ""
    date_str = f"\nToday's date is {as_of}." if as_of else ""
    prior_str = prior_context.as_prompt() if prior_context else ""
    prompt = (
        f"Research request:\n{query}\n{constraint_str}{brief_str}{date_str}{prior_str}\n\n"
        f"Produce a research objective and up to {max_questions} research questions "
        "that cover this request. Return JSON matching the schema."
    )
    system = _MARKET_SYSTEM if market else _SYSTEM
    if prior_context and intent in _INTENT_ADDENDA:
        system = system + _INTENT_ADDENDA[intent]
    data = await provider.structured_output(prompt, schema=_PLAN_SCHEMA, system=system)

    objective = str(data.get("objective", "")).strip() or query
    questions: list[PlannedQuestion] = []
    for q in data.get("questions", [])[:max_questions]:
        text = str(q.get("text", "")).strip()
        if not text:
            continue
        try:
            priority = int(q.get("priority", 3))
        except (TypeError, ValueError):
            priority = 3
        priority = min(5, max(1, priority))
        search_query = str(q.get("search_query", "")).strip() or text
        questions.append(
            PlannedQuestion(text=text, priority=priority, search_query=search_query)
        )

    if not questions:
        # Defensive fallback so a weak model response never yields an empty plan.
        questions = [PlannedQuestion(text=query, priority=1, search_query=query)]

    return ResearchPlan(objective=objective, questions=questions)

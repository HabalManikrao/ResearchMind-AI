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
) -> ResearchPlan:
    constraint_str = ""
    if constraints:
        constraint_str = "\nUser constraints/preferences:\n" + "\n".join(
            f"- {k}: {v}" for k, v in constraints.items() if v
        )
    date_str = f"\nToday's date is {as_of}." if as_of else ""
    prompt = (
        f"Research request:\n{query}\n{constraint_str}{date_str}\n\n"
        f"Produce a research objective and up to {max_questions} research questions "
        "that cover this request. Return JSON matching the schema."
    )
    system = _MARKET_SYSTEM if market else _SYSTEM
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

"""R&D Analysis Agent (spec §5 R&D, §13 report sections).

Turns the verified evidence into structured, traceable R&D outputs in three stages:

1. **Comparison** — identify the candidate solutions/technologies/approaches and
   assess each on shared criteria (pros / cons / risks / per-criterion rating).
2. **Recommendation** — pick the best option for the objective, with rationale,
   confidence, alternatives, and risks — grounded in the verified claims.
3. **Delivery plan** — a proof-of-concept and an implementation roadmap.

Each stage is a separate constrained LLM call so the outputs are structured objects
(persisted), not prose — the report renders them deterministically.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.llm.base import AIProvider

# --- Stage 1: comparison ---------------------------------------------------- #
_COMPARISON_SCHEMA = {
    "type": "object",
    "properties": {
        "criteria": {"type": "array", "items": {"type": "string"}},
        "options": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "description": {"type": "string"},
                    "pros": {"type": "array", "items": {"type": "string"}},
                    "cons": {"type": "array", "items": {"type": "string"}},
                    "risks": {"type": "array", "items": {"type": "string"}},
                    "scores": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "criterion": {"type": "string"},
                                "rating": {"type": "string"},
                            },
                            "required": ["criterion", "rating"],
                        },
                    },
                },
                "required": ["name", "description"],
            },
        },
    },
    "required": ["options"],
}

_COMPARISON_SYSTEM = (
    "You are an R&D analyst. From the research findings and verified claims, identify "
    "the concrete candidate solutions, technologies, or approaches relevant to the "
    "objective, and compare them. Choose sensible comparison criteria and rate each "
    "option per criterion (e.g. strong / moderate / weak / unknown). Only include "
    "options that are actually supported by the evidence. If the research is about a "
    "single subject, it is fine to return one option."
)

# --- Stage 2: recommendation ------------------------------------------------ #
_RECO_SCHEMA = {
    "type": "object",
    "properties": {
        "recommended_option": {"type": "string"},
        "rationale": {"type": "string"},
        "why": {"type": "string"},
        "confidence": {"type": "integer"},
        "alternatives": {"type": "array", "items": {"type": "string"}},
        "risks": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["recommended_option", "rationale"],
}

_RECO_SYSTEM = (
    "You make a single, decisive R&D recommendation for the objective, chosen from the "
    "compared options and grounded ONLY in the verified evidence. Give a concise "
    "rationale, a deeper 'why', a confidence score 0-100 reflecting evidence strength, "
    "the main alternatives, and the key risks. If evidence is too thin to recommend, "
    "say so in the rationale and give a low confidence."
)

# --- Stage 3: delivery plan ------------------------------------------------- #
_PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "proof_of_concept": {"type": "string"},
        "roadmap": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "step": {"type": "string"},
                    "detail": {"type": "string"},
                },
                "required": ["step"],
            },
        },
    },
    "required": ["roadmap"],
}

_PLAN_SYSTEM = (
    "You produce a practical delivery plan for the recommended approach: a small, "
    "concrete proof-of-concept to validate it first, then an ordered implementation "
    "roadmap of pragmatic steps. Keep it actionable and specific to the recommendation."
)


@dataclass
class SolutionOption:
    name: str
    description: str
    pros: list[str] = field(default_factory=list)
    cons: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    scores: list[dict] = field(default_factory=list)
    is_recommended: bool = False


@dataclass
class Recommendation:
    recommended_option: str
    rationale: str
    why: str
    confidence: float
    alternatives: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    proof_of_concept: str = ""
    roadmap: list[dict] = field(default_factory=list)


@dataclass
class RDResult:
    criteria: list[str]
    options: list[SolutionOption]
    recommendation: Recommendation | None


def _evidence_block(objective: str, claims: list[dict], findings: list[str]) -> str:
    claims_txt = "\n".join(
        f"- [{c['status']}] ({c['confidence']}%) {c['text']}" for c in claims
    ) or "(no consolidated claims)"
    findings_txt = "\n".join(f"- {f}" for f in findings[:50]) or "(no findings)"
    return (
        f"Objective: {objective}\n\n"
        f"Verified & other claims:\n{claims_txt}\n\n"
        f"Findings:\n{findings_txt}"
    )


async def analyse(
    provider: AIProvider,
    *,
    objective: str,
    claims: list[dict],
    findings: list[str],
) -> RDResult:
    evidence = _evidence_block(objective, claims, findings)

    # Stage 1: comparison.
    options: list[SolutionOption] = []
    criteria: list[str] = []
    try:
        comp = await provider.structured_output(
            f"{evidence}\n\nCompare the candidate options. Return JSON.",
            schema=_COMPARISON_SCHEMA,
            system=_COMPARISON_SYSTEM,
        )
        criteria = [str(c).strip() for c in comp.get("criteria", []) if str(c).strip()]
        for o in comp.get("options", []):
            name = str(o.get("name", "")).strip()
            if not name:
                continue
            options.append(
                SolutionOption(
                    name=name,
                    description=str(o.get("description", "")).strip(),
                    pros=[str(x).strip() for x in o.get("pros", []) if str(x).strip()],
                    cons=[str(x).strip() for x in o.get("cons", []) if str(x).strip()],
                    risks=[str(x).strip() for x in o.get("risks", []) if str(x).strip()],
                    scores=[
                        s for s in o.get("scores", [])
                        if isinstance(s, dict) and s.get("criterion")
                    ],
                )
            )
    except Exception:
        options = []

    # Stage 2: recommendation.
    recommendation: Recommendation | None = None
    option_names = [o.name for o in options]
    try:
        options_txt = "\n".join(
            f"- {o.name}: {o.description}" for o in options
        ) or "(no distinct options identified)"
        reco = await provider.structured_output(
            f"{evidence}\n\nCompared options:\n{options_txt}\n\n"
            "Recommend the best option for the objective. Return JSON.",
            schema=_RECO_SCHEMA,
            system=_RECO_SYSTEM,
        )
        try:
            confidence = float(reco.get("confidence", 0))
        except (TypeError, ValueError):
            confidence = 0.0
        recommendation = Recommendation(
            recommended_option=str(reco.get("recommended_option", "")).strip(),
            rationale=str(reco.get("rationale", "")).strip(),
            why=str(reco.get("why", "")).strip(),
            confidence=max(0.0, min(100.0, confidence)),
            alternatives=[
                str(a).strip() for a in reco.get("alternatives", []) if str(a).strip()
            ],
            risks=[str(r).strip() for r in reco.get("risks", []) if str(r).strip()],
        )
    except Exception:
        recommendation = None

    # Flag the recommended option among the compared set (case-insensitive match).
    if recommendation and recommendation.recommended_option:
        target = recommendation.recommended_option.lower()
        for o in options:
            if o.name.lower() == target or o.name.lower() in target:
                o.is_recommended = True
                break

    # Stage 3: delivery plan (only if we have a recommendation).
    if recommendation and recommendation.recommended_option:
        try:
            plan = await provider.structured_output(
                f"Objective: {objective}\n"
                f"Recommended approach: {recommendation.recommended_option}\n"
                f"Rationale: {recommendation.rationale}\n\n"
                "Produce a proof-of-concept and an implementation roadmap. Return JSON.",
                schema=_PLAN_SCHEMA,
                system=_PLAN_SYSTEM,
            )
            recommendation.proof_of_concept = str(plan.get("proof_of_concept", "")).strip()
            recommendation.roadmap = [
                {"step": str(s.get("step", "")).strip(), "detail": str(s.get("detail", "")).strip()}
                for s in plan.get("roadmap", [])
                if isinstance(s, dict) and s.get("step")
            ]
        except Exception:
            pass

    return RDResult(criteria=criteria, options=options, recommendation=recommendation)

"""Conflict Detection Agent (spec §7).

Examines the consolidated claims and surfaces genuine contradictions between them,
with an explanation and severity. The orchestrator persists these and the report
lists unresolved conflicts — the system must never hide conflicts (spec rule §23.10).

The LLM references claims by index; we map indices back to claim texts and the union
of their supporting source ids for traceability.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.llm.base import AIProvider
from app.models.enums import ConflictSeverity

_SCHEMA = {
    "type": "object",
    "properties": {
        "conflicts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "claim_a_index": {"type": "integer"},
                    "claim_b_index": {"type": "integer"},
                    "explanation": {"type": "string"},
                    "severity": {"type": "string", "enum": ["high", "medium", "low"]},
                },
                "required": ["claim_a_index", "claim_b_index", "explanation"],
            },
        }
    },
    "required": ["conflicts"],
}

_SYSTEM = (
    "You detect genuine factual contradictions between research claims. Two claims "
    "conflict only if they cannot both be true. Do NOT report claims that are merely "
    "different, complementary, or about different things. For each real contradiction, "
    "reference the two claim indices, explain the contradiction, and rate its severity "
    "(high if it would change a recommendation). Return an empty list if none conflict."
)


@dataclass
class ClaimRef:
    index: int
    text: str
    source_ids: list[str]


@dataclass
class DetectedConflict:
    statement_a: str
    statement_b: str
    explanation: str
    severity: ConflictSeverity
    source_ids: list[str] = field(default_factory=list)


async def detect(provider: AIProvider, claims: list[ClaimRef]) -> list[DetectedConflict]:
    if len(claims) < 2:
        return []

    by_index = {c.index: c for c in claims}
    listing = "\n".join(f"[{c.index}] {c.text}" for c in claims)
    prompt = (
        "Claims:\n"
        f"{listing}\n\n"
        "Identify any pairs of claims that genuinely contradict each other. Return JSON."
    )
    try:
        data = await provider.structured_output(prompt, schema=_SCHEMA, system=_SYSTEM)
    except Exception:
        return []

    conflicts: list[DetectedConflict] = []
    seen: set[frozenset[int]] = set()
    for c in data.get("conflicts", []):
        ia, ib = c.get("claim_a_index"), c.get("claim_b_index")
        if ia == ib or ia not in by_index or ib not in by_index:
            continue
        key = frozenset((ia, ib))
        if key in seen:
            continue
        seen.add(key)
        a, b = by_index[ia], by_index[ib]
        try:
            severity = ConflictSeverity(str(c.get("severity", "medium")).lower())
        except ValueError:
            severity = ConflictSeverity.MEDIUM
        conflicts.append(
            DetectedConflict(
                statement_a=a.text,
                statement_b=b.text,
                explanation=str(c.get("explanation", "")).strip(),
                severity=severity,
                source_ids=list({*a.source_ids, *b.source_ids}),
            )
        )
    return conflicts

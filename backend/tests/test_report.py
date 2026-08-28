from app.agents.report import ReportInput, generate_report
from tests.conftest import FakeProvider


def _base_input(**overrides):
    data = dict(
        objective="Choose a vector DB",
        query="compare vector dbs",
        questions=["Which is best?"],
        findings=["Qdrant is fast"],
        claims=[{"text": "Qdrant is fast", "status": "verified", "confidence": 90}],
        sources=[
            {"title": "Docs", "url": "https://docs.qdrant.tech", "source_type": "docs",
             "reliability_score": 100, "published_date": "2025-01-01"}
        ],
    )
    data.update(overrides)
    return ReportInput(**data)


async def test_report_has_deterministic_sections_and_meta():
    data = _base_input(
        solutions=[
            {"name": "Qdrant", "description": "d", "pros": ["fast"], "cons": [],
             "risks": [], "scores": [{"criterion": "Offline", "rating": "strong"}],
             "is_recommended": True}
        ],
        recommendation={
            "recommended_option": "Qdrant", "rationale": "fast", "why": "reasons",
            "confidence": 88, "alternatives": ["Chroma"], "risks": ["ops"],
            "proof_of_concept": "poc", "roadmap": [{"step": "S1", "detail": "d"}],
        },
    )
    md, meta = await generate_report(FakeProvider(), data)
    for section in [
        "## Technology / Solution Comparison",
        "## Recommended Solution",
        "## Why This Recommendation",
        "## Proof of Concept",
        "## Implementation Roadmap",
        "## Sources",
        "## Research Confidence",
    ]:
        assert section in md, f"missing {section}"
    assert meta["sources_analyzed"] == 1
    assert meta["verified_claims"] == 1
    assert meta["source_breakdown"] == {"docs": 1}


async def test_report_conflicts_section_is_deterministic():
    data = _base_input(
        conflicts=[
            {"statement_a": "Supports Windows", "statement_b": "Linux only",
             "explanation": "OS mismatch", "severity": "high", "status": "needs_verification"}
        ]
    )
    md, meta = await generate_report(FakeProvider(), data)
    assert "## Conflicting Information" in md
    assert "Supports Windows" in md and "Linux only" in md
    assert meta["conflicted_claims"] == 1


async def test_report_no_conflicts_states_none():
    md, _ = await generate_report(FakeProvider(), _base_input())
    assert "No contradictions were detected" in md

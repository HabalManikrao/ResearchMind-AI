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


class _NoGenerateProvider(FakeProvider):
    """Fails if the narrative LLM is invoked — proves a zero-evidence run does not synthesise
    prose (#post-11 hardening: never fabricate an evidence-backed report from the plan alone)."""

    async def generate(self, prompt, system=None):
        raise AssertionError("narrative LLM must not run for a zero-evidence report")


async def test_zero_source_run_is_marked_evidence_incomplete():
    data = _base_input(findings=[], claims=[], sources=[],
                       source_health={"research_mode": "unknown", "unavailable": 8,
                                      "research_health": "external_unavailable",
                                      "live": 0, "cached": 0, "local": 0})
    md, meta = await generate_report(_NoGenerateProvider(), data)  # LLM must NOT be called
    assert meta["evidence_incomplete"] is True
    assert meta["overall_confidence"] == 0.0
    assert meta["sources_analyzed"] == 0 and meta["verified_claims"] == 0
    assert "Research incomplete" in md
    assert "evidence-backed conclusion" in md
    # No fabricated evidence-backed sections, and the plan/questions stay visible.
    assert "## Recommended Solution" not in md
    assert "_No sources collected._" in md
    assert "Which is best?" in md  # research questions preserved
    assert "External sources unavailable" in md  # health disclosure present


async def test_sources_without_verified_claims_is_not_incomplete():
    # Case D: sources exist but nothing verified — a real (weak) result, NOT zero-evidence.
    data = _base_input(
        claims=[{"text": "Maybe fast", "status": "unverified", "confidence": 30}],
    )
    md, meta = await generate_report(FakeProvider(), data)
    assert meta["evidence_incomplete"] is False
    assert meta["sources_analyzed"] == 1
    assert "Research incomplete" not in md


async def test_document_only_run_is_not_incomplete():
    # Case E: local document evidence is a normal, evidence-backed result.
    data = _base_input(sources=[
        {"title": "spec.pdf", "url": "document://spec/p1", "source_type": "documents",
         "reliability_score": 80, "published_date": "2025-06-01"}])
    md, meta = await generate_report(FakeProvider(), data)
    assert meta["evidence_incomplete"] is False
    assert "Research incomplete" not in md

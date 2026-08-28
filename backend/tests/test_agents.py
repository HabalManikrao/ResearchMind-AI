from app.agents import conflict_detection, gap_analysis, planner, rd_analysis
from app.agents.conflict_detection import ClaimRef
from app.models.enums import ConflictSeverity
from tests.conftest import FakeProvider


async def test_planner_produces_objective_and_questions():
    plan = await planner.make_plan(FakeProvider(), "research vector dbs")
    assert plan.objective
    assert len(plan.questions) >= 1
    assert all(q.text and q.search_query for q in plan.questions)
    assert all(1 <= q.priority <= 5 for q in plan.questions)


async def test_planner_fallback_on_empty_questions():
    class Empty(FakeProvider):
        async def structured_output(self, prompt, schema, system=None):
            return {"objective": "", "questions": []}

    plan = await planner.make_plan(Empty(), "my query")
    assert len(plan.questions) == 1  # defensive fallback
    assert plan.objective == "my query"


async def test_conflict_detection_maps_indices_and_sources():
    provider = FakeProvider(
        conflicts=[{"claim_a_index": 0, "claim_b_index": 1,
                    "explanation": "contradiction", "severity": "high"}]
    )
    claims = [
        ClaimRef(index=0, text="Supports Windows", source_ids=["s1"]),
        ClaimRef(index=1, text="Linux only", source_ids=["s2"]),
    ]
    conflicts = await conflict_detection.detect(provider, claims)
    assert len(conflicts) == 1
    c = conflicts[0]
    assert c.severity == ConflictSeverity.HIGH
    assert set(c.source_ids) == {"s1", "s2"}


async def test_conflict_detection_needs_two_claims():
    assert await conflict_detection.detect(FakeProvider(), []) == []


async def test_gap_analysis_returns_gaps():
    provider = FakeProvider(
        gaps=[{"question": "Q1?", "reason": "thin", "followup_query": "more q1"}]
    )
    gaps = await gap_analysis.find_gaps(
        provider, questions=["Q1?"], evidence_by_question={"Q1?": []}
    )
    assert len(gaps) == 1
    assert gaps[0].followup_query == "more q1"


async def test_rd_analysis_produces_comparison_recommendation_plan():
    result = await rd_analysis.analyse(
        FakeProvider(), objective="obj",
        claims=[{"text": "c", "status": "verified", "confidence": 90}],
        findings=["f"],
    )
    assert result.options and result.options[0].name == "OptX"
    assert result.options[0].is_recommended  # matched recommended_option
    assert result.recommendation.recommended_option == "OptX"
    assert result.recommendation.roadmap  # delivery plan produced

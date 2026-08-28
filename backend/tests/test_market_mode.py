"""Market Intelligence mode: recency-biased search + dated snapshot report."""
from app.agents import report as report_agent
from app.agents import tavily_agents
from app.agents.tavily_agents import _time_range_for
from app.search.tavily_client import SearchResult
from tests.conftest import FakeProvider, run_to_completion


def test_time_range_buckets():
    assert _time_range_for(1) == "day"
    assert _time_range_for(7) == "week"
    assert _time_range_for(30) == "month"
    assert _time_range_for(180) == "year"


class _StubTavily:
    def __init__(self):
        self.calls = []

    async def search(self, query, *, max_results=5, **kwargs):
        self.calls.append(kwargs)
        return [SearchResult(title="t", url="https://ex/y", content="c",
                             score=0.9, published_date="2026-08-01")]


async def test_recency_applies_time_range_for_web():
    stub = _StubTavily()
    await tavily_agents.collect(
        FakeProvider(), stub, source_type="web",
        question="q", search_query="q", recency_days=180,
    )
    assert stub.calls[0].get("time_range") == "year"


async def test_recency_tightens_days_for_news():
    stub = _StubTavily()
    await tavily_agents.collect(
        FakeProvider(), stub, source_type="news",
        question="q", search_query="q", recency_days=5,
    )
    assert stub.calls[0].get("days") == 5


async def test_no_recency_when_not_market():
    stub = _StubTavily()
    await tavily_agents.collect(
        FakeProvider(), stub, source_type="web", question="q", search_query="q",
    )
    assert "time_range" not in stub.calls[0]


async def test_market_report_has_dated_snapshot_header():
    data = report_agent.ReportInput(
        objective="AI coding assistants market",
        query="what's happening in the AI coding assistant market",
        questions=["Who are the key players?"],
        findings=["Vendor X shipped a new agent"],
        claims=[{"text": "X released Y", "status": "verified", "confidence": 80}],
        sources=[{"title": "News", "url": "https://n/1", "source_type": "news",
                  "reliability_score": 70, "published_date": "2026-08-10"}],
        mode="market",
        as_of="2026-08-25",
    )
    md, _ = await report_agent.generate_report(FakeProvider(), data)
    assert md.startswith("# Market Intelligence Report:")
    assert "Market snapshot as of 2026-08-25" in md


async def test_pipeline_market_mode_end_to_end(client, patch_pipeline):
    r = await client.post(
        "/research",
        json={"query": "current market for local LLM tools", "mode": "market",
              "sources_enabled": ["web", "news"], "auto_start": True},
    )
    pid = r.json()["id"]
    await run_to_completion(pid)

    detail = (await client.get(f"/research/{pid}")).json()
    assert detail["status"] == "completed"
    assert detail["mode"] == "market"

    report = (await client.get(f"/research/{pid}/report")).json()
    assert report["markdown"].startswith("# Market Intelligence Report:")
    assert "Market snapshot as of" in report["markdown"]

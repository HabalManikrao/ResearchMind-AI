"""Orchestrator wiring for the active contradiction search: it must persist
CONTRADICTS evidence links and re-score the affected claim."""
import asyncio

from sqlalchemy import select

import app.orchestration.orchestrator as orch
from app.database import SessionLocal
from app.models import (
    Claim,
    ClaimSource,
    ClaimStatus,
    EvidenceStance,
    ResearchProject,
    Source,
)
from tests.conftest import FakeProvider


class FakeResult:
    def __init__(self, url, content, *, title="t", score=0.5, published_date="2025-05-01"):
        self.url = url
        self.content = content
        self.title = title
        self.score = score
        self.published_date = published_date


class FakeSearch:
    def __init__(self, results):
        self._results = results

    async def search(self, query, *, max_results=5, **kwargs):
        return self._results[:max_results]


async def test_seek_contradictions_persists_and_rescores(db, monkeypatch):
    # Rebind the module lock to this test's event loop (pytest-asyncio uses a fresh one).
    monkeypatch.setattr(orch, "_db_lock", asyncio.Lock())

    proj = ResearchProject(title="t", query="q", sources_enabled=["web"])
    db.add(proj)
    await db.flush()
    src = Source(
        project_id=proj.id, title="S", url="https://s.example", source_type="web",
        published_date="2025-05-01", reliability_score=90.0, relevance_score=50.0, meta={},
    )
    db.add(src)
    await db.flush()
    claim = Claim(
        project_id=proj.id, text="X is true", status=ClaimStatus.VERIFIED, confidence=90.0,
        supporting_source_ids=[src.id],
        confidence_meta={"support_count": 1, "contradiction_count": 0},
    )
    db.add(claim)
    await db.flush()
    db.add(
        ClaimSource(
            claim_id=claim.id, source_id=src.id,
            stance=EvidenceStance.SUPPORTS, passage="X holds",
        )
    )
    await db.commit()

    provider = FakeProvider(contradictions=[{"index": 0, "quote": "X is false"}])
    search = FakeSearch([FakeResult("https://critic.example", "X is false because ...")])

    added = await orch._seek_contradictions(proj.id, provider, search)
    assert added == 1

    async with SessionLocal() as s:
        c = await s.get(Claim, claim.id)
        assert c.status == ClaimStatus.CONFLICTED
        assert c.confidence < 90.0
        assert c.confidence_meta["contradiction_count"] == 1

        links = (
            await s.execute(select(ClaimSource).where(ClaimSource.claim_id == claim.id))
        ).scalars().all()
        assert sorted(l.stance.value for l in links) == ["contradicts", "supports"]

        contra = (
            await s.execute(select(Source).where(Source.url == "https://critic.example"))
        ).scalars().first()
        assert contra is not None
        assert contra.meta.get("contradiction") is True


async def test_seek_contradictions_noop_when_disabled(db, monkeypatch):
    monkeypatch.setattr(orch, "_db_lock", asyncio.Lock())
    monkeypatch.setattr(orch.settings, "contradiction_search_enabled", False)
    proj = ResearchProject(title="t", query="q", sources_enabled=["web"])
    db.add(proj)
    await db.commit()
    added = await orch._seek_contradictions(proj.id, FakeProvider(), FakeSearch([]))
    assert added == 0

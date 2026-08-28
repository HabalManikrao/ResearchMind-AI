from app.models import Finding, ResearchProject, Source
from app.services.dedup import _jaccard, _tokens, dedupe_project, normalize_url


def test_normalize_url_collapses_variants():
    a = normalize_url("https://www.Example.com/page/")
    b = normalize_url("http://example.com/page")
    c = normalize_url("https://example.com/page?utm=1#frag")
    assert a == b == c == "example.com/page"


def test_jaccard():
    assert _jaccard(_tokens("the cat sat"), _tokens("the cat sat")) == 1.0
    assert _jaccard(_tokens("a b"), _tokens("c d")) == 0.0


async def test_dedupe_sources_keeps_highest_reliability_and_reassigns_findings(db):
    proj = ResearchProject(title="t", query="q")
    db.add(proj)
    await db.flush()
    keep = Source(project_id=proj.id, title="keep", url="https://x.io/a", reliability_score=100)
    dup = Source(project_id=proj.id, title="dup", url="http://www.x.io/a/", reliability_score=40)
    db.add_all([keep, dup])
    await db.flush()
    db.add(Finding(project_id=proj.id, source_id=dup.id, text="unique finding one"))
    await db.commit()

    stats = await dedupe_project(proj.id)
    assert stats["sources_removed"] == 1

    from sqlalchemy import select

    sources = (await db.execute(select(Source).where(Source.project_id == proj.id))).scalars().all()
    assert len(sources) == 1 and sources[0].reliability_score == 100
    # The duplicate's finding was reassigned to the surviving source.
    findings = (await db.execute(select(Finding).where(Finding.project_id == proj.id))).scalars().all()
    assert len(findings) == 1 and findings[0].source_id == sources[0].id


async def test_dedupe_findings_removes_near_duplicates(db):
    proj = ResearchProject(title="t", query="q")
    db.add(proj)
    await db.flush()
    src = Source(project_id=proj.id, title="s", url="https://x.io/a", reliability_score=80)
    db.add(src)
    await db.flush()
    db.add_all([
        Finding(project_id=proj.id, source_id=src.id, text="Qdrant supports offline deployment mode"),
        Finding(project_id=proj.id, source_id=src.id, text="Qdrant supports offline deployment mode"),
        Finding(project_id=proj.id, source_id=src.id, text="Completely different unrelated statement here"),
    ])
    await db.commit()

    stats = await dedupe_project(proj.id)
    assert stats["findings_removed"] == 1

    from sqlalchemy import select

    findings = (await db.execute(select(Finding).where(Finding.project_id == proj.id))).scalars().all()
    assert len(findings) == 2

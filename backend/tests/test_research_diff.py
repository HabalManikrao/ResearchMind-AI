"""Unit tests for the Research Diff engine (#4) — deterministic, offline.

Builds two runs (projects) directly in the DB and asserts the diff. Data is
committed before each ``diff_runs`` call because the engine opens its own sessions.
"""
import pytest

from app.models import (
    Claim,
    ClaimSource,
    ClaimStatus,
    Document,
    DocumentStatus,
    EvidenceStance,
    ProjectStatus,
    Recommendation,
    ResearchProject,
    Source,
)
from app.services import research_diff

pytestmark = pytest.mark.usefixtures("reset_db")


# --------------------------------------------------------------------------- #
# builders
# --------------------------------------------------------------------------- #
async def _mk_run(db, *, run_number=1, root_id=None, parent_id=None):
    p = ResearchProject(
        query="q", title="t", status=ProjectStatus.COMPLETED,
        run_number=run_number, parent_id=parent_id,
    )
    db.add(p)
    await db.flush()
    p.root_id = root_id or p.id
    await db.commit()
    await db.refresh(p)
    return p


async def _add_source(db, project_id, url, *, reliability=80.0, source_type="web",
                      published_date="2025-01-01", meta=None, title=None):
    s = Source(
        project_id=project_id, url=url, title=title or url, source_type=source_type,
        reliability_score=reliability, published_date=published_date, meta=meta or {},
    )
    db.add(s)
    await db.flush()
    return s


async def _add_claim(db, project_id, text, *, status=ClaimStatus.VERIFIED, confidence=80.0,
                     support=(), contra=(), freshness="fresh"):
    meta = {
        "support_count": len(support),
        "contradiction_count": len(contra),
        "avg_reliability": 80,
        "freshness": freshness,
        "outdated": False,
        "reasons": [],
    }
    c = Claim(
        project_id=project_id, text=text, status=status, confidence=confidence,
        supporting_source_ids=[s.id for s in support], confidence_meta=meta,
    )
    db.add(c)
    await db.flush()
    for s in support:
        db.add(ClaimSource(claim_id=c.id, source_id=s.id, stance=EvidenceStance.SUPPORTS, passage="supports"))
    for s in contra:
        db.add(ClaimSource(claim_id=c.id, source_id=s.id, stance=EvidenceStance.CONTRADICTS, passage="contradicts"))
    await db.flush()
    return c


# --------------------------------------------------------------------------- #
# sources
# --------------------------------------------------------------------------- #
async def test_identical_runs_are_unchanged(db):
    old = await _mk_run(db, run_number=1)
    new = await _mk_run(db, run_number=2, root_id=old.id, parent_id=old.id)
    for p in (old, new):
        s = await _add_source(db, p.id, "https://a.example/x")
        await _add_claim(db, p.id, "Podman is a good Docker alternative", support=[s])
    await db.commit()

    d = await research_diff.diff_runs(old.id, new.id)
    assert d.sources["unchanged"] == 1 and d.sources["new"] == 0 and d.sources["removed"] == 0
    assert d.claims["unchanged"] == 1
    assert d.claims["new"] == 0 and d.claims["removed"] == 0


async def test_new_and_removed_sources(db):
    old = await _mk_run(db, run_number=1)
    new = await _mk_run(db, run_number=2, root_id=old.id)
    await _add_source(db, old.id, "https://only-old.example/p")
    await _add_source(db, new.id, "https://only-new.example/p")
    await _add_source(db, old.id, "https://shared.example/p")
    await _add_source(db, new.id, "https://www.shared.example/p/")  # normalized-equal
    await db.commit()

    d = await research_diff.diff_runs(old.id, new.id)
    assert d.sources["new"] == 1
    assert d.sources["removed"] == 1
    assert d.sources["unchanged"] == 1


async def test_changed_source_metadata(db):
    old = await _mk_run(db, run_number=1)
    new = await _mk_run(db, run_number=2, root_id=old.id)
    await _add_source(db, old.id, "https://s.example/p", reliability=60.0)
    await _add_source(db, new.id, "https://s.example/p", reliability=90.0)
    await db.commit()

    d = await research_diff.diff_runs(old.id, new.id)
    assert d.sources["changed"] == 1
    item = next(i for i in d.sources["items"] if i.kind == research_diff.CHANGED)
    assert any("reliability" in c for c in item.changes)


# --------------------------------------------------------------------------- #
# claims: classification (evidence-aware) — §11, §20
# --------------------------------------------------------------------------- #
async def test_claim_strengthened_and_weakened(db):
    old = await _mk_run(db, run_number=1)
    new = await _mk_run(db, run_number=2, root_id=old.id)
    so = await _add_source(db, old.id, "https://a.example/1")
    sn = await _add_source(db, new.id, "https://a.example/1")
    await _add_claim(db, old.id, "Option X scales well", confidence=60.0, support=[so])
    await _add_claim(db, new.id, "Option X scales well", confidence=85.0, support=[sn])
    # second claim weakens
    await _add_claim(db, old.id, "Option Y is cheaper", confidence=80.0, support=[so])
    await _add_claim(db, new.id, "Option Y is cheaper", confidence=55.0, support=[sn])
    await db.commit()

    d = await research_diff.diff_runs(old.id, new.id)
    assert d.claims["strengthened"] == 1
    assert d.claims["weakened"] == 1
    assert d.confidence["increased"] == 1
    assert d.confidence["decreased"] == 1
    strong = next(i for i in d.claims["items"] if i.kind == research_diff.STRENGTHENED)
    assert "confidence 60 → 85" in strong.reason


async def test_claim_contradicted_when_disconfirming_evidence_appears(db):
    old = await _mk_run(db, run_number=1)
    new = await _mk_run(db, run_number=2, root_id=old.id)
    so = await _add_source(db, old.id, "https://a.example/1")
    sn = await _add_source(db, new.id, "https://a.example/1")
    scontra = await _add_source(db, new.id, "https://contra.example/1")
    await _add_claim(db, old.id, "The library is production ready", confidence=80.0, support=[so])
    await _add_claim(
        db, new.id, "The library is production ready", confidence=55.0,
        status=ClaimStatus.CONFLICTED, support=[sn], contra=[scontra],
    )
    await db.commit()

    d = await research_diff.diff_runs(old.id, new.id)
    assert d.claims["contradicted"] == 1
    item = next(i for i in d.claims["items"] if i.kind == research_diff.CONTRADICTED)
    assert "contradictions 0 → 1" in item.reason
    assert any(e.stance == "contradicts" for e in item.new_evidence)


async def test_new_and_removed_claims(db):
    old = await _mk_run(db, run_number=1)
    new = await _mk_run(db, run_number=2, root_id=old.id)
    await _add_claim(db, old.id, "This claim disappears next run")
    await _add_claim(db, new.id, "This is a brand new claim about something else entirely")
    await db.commit()

    d = await research_diff.diff_runs(old.id, new.id)
    assert d.claims["new"] == 1
    assert d.claims["removed"] == 1


# --------------------------------------------------------------------------- #
# claim matching strategy — §10
# --------------------------------------------------------------------------- #
async def test_claim_matching_exact_and_normalized(db):
    old = await _mk_run(db, run_number=1)
    new = await _mk_run(db, run_number=2, root_id=old.id)
    await _add_claim(db, old.id, "Podman is a drop-in replacement for Docker.")
    # differs only by punctuation/case -> normalized match, not new/removed
    await _add_claim(db, new.id, "podman is a drop in replacement for docker")
    await db.commit()

    d = await research_diff.diff_runs(old.id, new.id)
    assert d.claims["new"] == 0 and d.claims["removed"] == 0
    assert d.claims["unchanged"] == 1
    matched = next(i for i in d.claims["items"] if i.kind == research_diff.UNCHANGED)
    assert matched.match_score == 1.0


async def test_claim_matching_token_overlap(db):
    old = await _mk_run(db, run_number=1)
    new = await _mk_run(db, run_number=2, root_id=old.id)
    await _add_claim(db, old.id, "Qdrant supports on-disk local vector storage without a server")
    # same tokens, reordered / slightly reworded -> token-set (Jaccard) match
    await _add_claim(db, new.id, "local vector storage on-disk without a server Qdrant supports")
    await db.commit()

    d = await research_diff.diff_runs(old.id, new.id)
    assert d.claims["new"] == 0 and d.claims["removed"] == 0
    item = next(i for i in d.claims["items"] if i.kind in (research_diff.UNCHANGED,))
    assert item.match_score is not None and item.match_score >= 0.6


async def test_claim_matching_semantic_and_unrelated(db, monkeypatch):
    """Force the semantic branch with controlled vectors: two claims that share few
    tokens but have (by construction) identical embeddings should match; a truly
    unrelated claim should not."""
    old = await _mk_run(db, run_number=1)
    new = await _mk_run(db, run_number=2, root_id=old.id)
    await _add_claim(db, old.id, "Rootless mode improves container security posture")
    await _add_claim(db, new.id, "Daemonless execution strengthens isolation guarantees")  # synonym-y
    await _add_claim(db, new.id, "Bananas are an excellent source of potassium")  # unrelated
    await db.commit()

    vecs = {
        "Rootless mode improves container security posture": [1.0, 0.0, 0.0],
        "Daemonless execution strengthens isolation guarantees": [0.98, 0.199, 0.0],  # cos≈0.98
        "Bananas are an excellent source of potassium": [0.0, 0.0, 1.0],
    }

    class _VecProvider:
        async def embed(self, texts):
            return [vecs.get(t, [0.0, 0.0, 0.0]) for t in texts]

    monkeypatch.setattr(research_diff, "get_provider", lambda: _VecProvider())
    # ensure token match can't claim it first
    monkeypatch.setattr(research_diff.settings, "research_diff_token_threshold", 0.95)

    d = await research_diff.diff_runs(old.id, new.id)
    # the synonym pair matched semantically; the banana claim is genuinely new
    assert d.claims["new"] == 1
    assert d.claims["removed"] == 0
    assert any(
        i.kind in (research_diff.UNCHANGED, research_diff.STRENGTHENED, research_diff.WEAKENED)
        and i.match_score is not None and i.match_score < 1.0
        for i in d.claims["items"]
    )


# --------------------------------------------------------------------------- #
# recommendation — §9
# --------------------------------------------------------------------------- #
async def _add_rec(db, project_id, option, *, rationale="because", confidence=80.0):
    db.add(Recommendation(
        project_id=project_id, recommended_option=option, rationale=rationale, confidence=confidence,
    ))
    await db.flush()


async def test_recommendation_reversed_modified_new(db):
    # reversed
    old = await _mk_run(db, run_number=1)
    new = await _mk_run(db, run_number=2, root_id=old.id)
    await _add_rec(db, old.id, "Option A")
    await _add_rec(db, new.id, "Option B")
    await db.commit()
    d = await research_diff.diff_runs(old.id, new.id)
    assert d.recommendation["kind"] == "reversed"

    # modified (same option, confidence jumps)
    o2 = await _mk_run(db, run_number=1)
    n2 = await _mk_run(db, run_number=2, root_id=o2.id)
    await _add_rec(db, o2.id, "Option A", confidence=60.0)
    await _add_rec(db, n2.id, "Option A", confidence=90.0)
    await db.commit()
    d2 = await research_diff.diff_runs(o2.id, n2.id)
    assert d2.recommendation["kind"] == "modified"

    # newly introduced
    o3 = await _mk_run(db, run_number=1)
    n3 = await _mk_run(db, run_number=2, root_id=o3.id)
    await _add_rec(db, n3.id, "Option A")
    await db.commit()
    d3 = await research_diff.diff_runs(o3.id, n3.id)
    assert d3.recommendation["kind"] == "new"


# --------------------------------------------------------------------------- #
# documents — §13
# --------------------------------------------------------------------------- #
async def _add_doc(db, project_id, name, checksum):
    db.add(Document(
        project_id=project_id, filename=f"{name}.stored", original_filename=name,
        mime_type="application/pdf", size_bytes=10, checksum=checksum,
        storage_path=f"/x/{name}", status=DocumentStatus.READY,
    ))
    await db.flush()


async def test_document_diff(db):
    old = await _mk_run(db, run_number=1)
    new = await _mk_run(db, run_number=2, root_id=old.id)
    await _add_doc(db, old.id, "unchanged.pdf", "aaa")
    await _add_doc(db, new.id, "unchanged.pdf", "aaa")   # unchanged
    await _add_doc(db, old.id, "edited.pdf", "bbb")
    await _add_doc(db, new.id, "edited.pdf", "ccc")       # checksum changed
    await _add_doc(db, old.id, "gone.pdf", "ddd")         # removed
    await _add_doc(db, new.id, "fresh.pdf", "eee")        # new
    await db.commit()

    d = await research_diff.diff_runs(old.id, new.id)
    assert d.documents["unchanged"] == 1
    assert d.documents["changed"] == 1
    assert d.documents["removed"] == 1
    assert d.documents["new"] == 1


# --------------------------------------------------------------------------- #
# provenance / availability change (#5, spec §21)
# --------------------------------------------------------------------------- #
async def test_source_availability_change_live_to_cached(db):
    old = await _mk_run(db, run_number=1)
    new = await _mk_run(db, run_number=2, root_id=old.root_id, parent_id=old.id)
    # Same URL & publish date across runs; provenance flips live -> cached.
    await _add_source(db, old.id, "https://x.example", published_date="2026-08-15",
                      meta={"provenance": "live_web"})
    await _add_source(db, new.id, "https://x.example", published_date="2026-08-15",
                      meta={"provenance": "cached_web"})
    await db.commit()

    d = await research_diff.diff_runs(old.id, new.id)
    assert d.sources["changed"] == 1
    changed = next(i for i in d.sources["items"] if i.kind == "changed")
    assert any("availability live → cached" in c for c in changed.changes)


async def test_unchanged_source_provenance_not_flagged(db):
    old = await _mk_run(db, run_number=1)
    new = await _mk_run(db, run_number=2, root_id=old.root_id, parent_id=old.id)
    # Identical live source across runs -> unchanged (no false positive, spec §21).
    for pid in (old.id, new.id):
        await _add_source(db, pid, "https://y.example", published_date="2026-08-15",
                          meta={"provenance": "live_web"})
    await db.commit()

    d = await research_diff.diff_runs(old.id, new.id)
    assert d.sources["unchanged"] == 1
    assert d.sources["changed"] == 0

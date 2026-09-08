from datetime import date

from app.agents.verification import EvidenceSource, _score_claim, score_claim, verify
from app.models.enums import ClaimStatus
from tests.conftest import FakeProvider

AS_OF = date(2025, 6, 1)


def _src(i, rel, published_date=None, source_type="web"):
    return EvidenceSource(
        index=i,
        source_id=f"s{i}",
        url=f"https://x/{i}",
        reliability=rel,
        published_date=published_date,
        source_type=source_type,
    )


def test_score_claim_two_strong_sources_verified():
    status, conf = _score_claim([_src(0, 100), _src(1, 90)], conflicting=False)
    assert status == ClaimStatus.VERIFIED
    assert conf > 60


def test_score_claim_two_weak_sources_partial():
    status, _ = _score_claim([_src(0, 60), _src(1, 55)], conflicting=False)
    assert status == ClaimStatus.PARTIALLY_VERIFIED


def test_score_claim_single_weak_source_unverified():
    status, _ = _score_claim([_src(0, 40)], conflicting=False)
    assert status == ClaimStatus.UNVERIFIED


def test_score_claim_no_sources_insufficient():
    status, conf = _score_claim([], conflicting=False)
    assert status == ClaimStatus.INSUFFICIENT_EVIDENCE
    assert conf == 0.0


def test_score_claim_conflicting_flag():
    status, _ = _score_claim([_src(0, 100), _src(1, 100)], conflicting=True)
    assert status == ClaimStatus.CONFLICTED


async def test_verify_dedupes_sources_by_id():
    # Same source id cited twice must count once (rule §23.4).
    es = EvidenceSource(index=0, source_id="dup", url="https://x", reliability=100)
    provider = FakeProvider(
        claims=[{"text": "C", "source_indices": [0, 0], "conflicting": False}]
    )
    claims = await verify(provider, [("f1", es), ("f2", es)])
    assert len(claims) == 1
    assert claims[0].supporting_source_ids == ["dup"]


async def test_verify_empty_findings():
    assert await verify(FakeProvider(), []) == []


# --- Recency + contradiction-aware scoring -------------------------------- #
def test_recency_boosts_confidence():
    fresh = score_claim(
        [_src(0, 90, "2025-05-20"), _src(1, 90, "2025-05-20")], as_of=AS_OF
    )
    stale = score_claim(
        [_src(0, 90, "2019-01-01"), _src(1, 90, "2019-01-01")], as_of=AS_OF
    )
    assert fresh[0] == ClaimStatus.VERIFIED and stale[0] == ClaimStatus.VERIFIED
    assert fresh[1] > stale[1]  # same reliability, fresher evidence -> higher confidence


def test_contradiction_flips_to_conflicted_and_lowers_confidence():
    supporting = [_src(0, 90, "2025-05-20"), _src(1, 90, "2025-05-20")]
    contra = [_src(9, 80, "2025-05-20")]
    status, conf, meta = score_claim(supporting, contra, as_of=AS_OF)
    assert status == ClaimStatus.CONFLICTED
    assert meta["contradiction_count"] == 1
    clean_conf = score_claim(supporting, as_of=AS_OF)[1]
    assert conf < clean_conf


def test_outdated_flag_when_supporting_evidence_stale():
    _, _, meta = score_claim(
        [_src(0, 90, "2019-01-01", "news"), _src(1, 90, "2019-01-01", "news")],
        as_of=AS_OF,
    )
    assert meta["outdated"] is True
    assert meta["freshness"] == "stale"


def test_fresh_source_keeps_claim_current_not_outdated():
    """#10 regression: a claim backed by one FRESH and one stale authoritative source must NOT
    be flagged outdated — a fresh source still supporting it means it is currently established,
    not merely historically true. (Old majority rule rounded a 1-1 split up to 'outdated'.)"""
    status, _, meta = score_claim(
        [_src(0, 88, "2025-05-01", "docs"), _src(1, 85, "2022-01-01", "docs")],
        as_of=AS_OF,
    )
    assert meta["outdated"] is False
    assert status == ClaimStatus.VERIFIED
    # Two stale sources is still a genuine majority → outdated (unchanged behaviour).
    _, _, meta2 = score_claim(
        [_src(0, 90, "2019-01-01", "news"), _src(1, 90, "2019-01-01", "news")], as_of=AS_OF,
    )
    assert meta2["outdated"] is True


def test_confidence_meta_reports_inputs():
    _, _, meta = score_claim([_src(0, 90, "2025-05-20"), _src(1, 70, "2025-05-20")], as_of=AS_OF)
    assert meta["support_count"] == 2
    assert meta["contradiction_count"] == 0
    assert meta["avg_reliability"] == 80.0
    assert isinstance(meta["reasons"], list) and meta["reasons"]


async def test_verify_attaches_passages_and_meta():
    es = EvidenceSource(
        index=0, source_id="s0", url="https://x", reliability=90,
        published_date="2025-05-20", source_type="web",
    )
    provider = FakeProvider(
        claims=[{"text": "C", "source_indices": [0], "conflicting": False}]
    )
    claims = await verify(provider, [("the finding passage", es)], as_of=AS_OF)
    assert len(claims) == 1
    ev = claims[0].evidence
    assert len(ev) == 1
    assert ev[0].source_id == "s0"
    assert ev[0].passage == "the finding passage"
    assert ev[0].stance == "supports"
    assert claims[0].confidence_meta["support_count"] == 1

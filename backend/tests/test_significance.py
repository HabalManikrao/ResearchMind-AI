"""Significance engine (#6, spec §8, §10, §18): impact classification + suppression.

Deterministic — built on synthetic ``ResearchDiff`` shapes so the impact rules are
pinned without needing two real research runs. Verifies the product rule: a new source
alone is noise; a change to what the user should believe is significant.
"""
from app.config import get_settings
from app.services import significance
from app.services.research_diff import (
    CONTRADICTED,
    NEW,
    STRENGTHENED,
    WEAKENED,
    ResearchDiff,
)

settings = get_settings()


def _diff(*, claims=None, sources=None, recommendation=None) -> ResearchDiff:
    return ResearchDiff(
        old_run={}, new_run={},
        sources={"items": sources or []},
        claims={"items": claims or []},
        confidence={},
        recommendation=recommendation or {"kind": "unchanged", "old": None, "new": None},
        documents={"items": []},
    )


def _claim(kind, *, old_c=None, new_c=None, delta=None, text="A claim", evidence=None):
    return {
        "kind": kind, "old_text": text, "new_text": text,
        "old_confidence": old_c, "new_confidence": new_c, "confidence_delta": delta,
        "reason": "", "new_evidence": evidence or [],
    }


# --------------------------------------------------------------------------- #
# Impact levels
# --------------------------------------------------------------------------- #
def test_recommendation_reversal_is_critical():
    diff = _diff(recommendation={"kind": "reversed",
                                 "old": {"option": "OptX"}, "new": {"option": "OptY"}})
    changes = significance.evaluate(diff, settings)
    assert changes[0].kind == "recommendation_reversed"
    assert changes[0].impact == significance.CRITICAL


def test_recommendation_modified_is_high():
    diff = _diff(recommendation={"kind": "modified",
                                 "old": {"option": "OptX"}, "new": {"option": "OptX"}})
    changes = significance.evaluate(diff, settings)
    assert changes[0].impact == significance.HIGH


def test_contradicted_high_confidence_claim_is_critical():
    diff = _diff(claims=[_claim(CONTRADICTED, old_c=85.0, new_c=40.0)])
    (c,) = significance.evaluate(diff, settings)
    assert c.kind == "claim_contradicted"
    assert c.impact == significance.CRITICAL


def test_contradicted_low_confidence_claim_is_high():
    diff = _diff(claims=[_claim(CONTRADICTED, old_c=40.0, new_c=20.0)])
    (c,) = significance.evaluate(diff, settings)
    assert c.impact == significance.HIGH


def test_major_confidence_drop_is_high_minor_is_medium():
    big = _diff(claims=[_claim(WEAKENED, old_c=80.0, new_c=55.0, delta=-25.0)])
    small = _diff(claims=[_claim(WEAKENED, old_c=80.0, new_c=72.0, delta=-8.0)])
    assert significance.evaluate(big, settings)[0].impact == significance.HIGH
    assert significance.evaluate(small, settings)[0].impact == significance.MEDIUM


def test_strengthened_major_is_medium_minor_is_low():
    big = _diff(claims=[_claim(STRENGTHENED, old_c=50.0, new_c=75.0, delta=25.0)])
    small = _diff(claims=[_claim(STRENGTHENED, old_c=50.0, new_c=55.0, delta=5.0)])
    assert significance.evaluate(big, settings)[0].impact == significance.MEDIUM
    assert significance.evaluate(small, settings)[0].impact == significance.LOW


def test_new_claim_impact_depends_on_evidence():
    strong = _diff(claims=[_claim(
        NEW, new_c=70.0,
        evidence=[{"stance": "supports", "source_type": "web"},
                  {"stance": "supports", "source_type": "news"}],
    )])
    weak = _diff(claims=[_claim(
        NEW, new_c=40.0, evidence=[{"stance": "supports", "source_type": "web"}],
    )])
    authoritative = _diff(claims=[_claim(
        NEW, new_c=40.0, evidence=[{"stance": "supports", "source_type": "papers"}],
    )])
    assert significance.evaluate(strong, settings)[0].impact == significance.MEDIUM
    assert significance.evaluate(weak, settings)[0].impact == significance.LOW
    assert significance.evaluate(authoritative, settings)[0].impact == significance.MEDIUM


# --------------------------------------------------------------------------- #
# The core product rule (spec §18): noise vs signal
# --------------------------------------------------------------------------- #
def test_ten_low_quality_new_sources_produce_no_meaningful_change():
    sources = [
        {"kind": NEW, "url": f"https://blog{i}.example/x", "title": f"blog {i}",
         "source_type": "web", "changes": []}
        for i in range(10)
    ]
    changes = significance.evaluate(_diff(sources=sources), settings)
    assert changes, "changes are recorded"
    assert all(c.impact == significance.LOW for c in changes)
    assert [c for c in changes if significance.is_meaningful(c)] == []


def test_one_authoritative_contradiction_is_meaningful_and_critical():
    diff = _diff(claims=[_claim(
        CONTRADICTED, old_c=82.0, new_c=30.0,
        evidence=[{"stance": "contradicts", "source_type": "papers"}],
    )])
    changes = significance.evaluate(diff, settings)
    meaningful = [c for c in changes if significance.is_meaningful(c)]
    assert len(meaningful) == 1
    assert meaningful[0].impact == significance.CRITICAL


def test_authoritative_new_source_is_medium_via_reliability_map():
    sources = [{"kind": NEW, "url": "https://arxiv.org/abs/1", "title": "paper",
                "source_type": "papers", "changes": []}]
    rel = {"https://arxiv.org/abs/1": (90.0, "papers")}
    (c,) = significance.evaluate(_diff(sources=sources), settings, source_reliability=rel)
    assert c.impact == significance.MEDIUM


def test_source_became_unavailable_is_medium():
    sources = [{"kind": "changed", "url": "https://x.example/a", "title": "A",
                "source_type": "web", "changes": ["availability live → unavailable"]}]
    (c,) = significance.evaluate(_diff(sources=sources), settings)
    assert c.kind == "source_unavailable"
    assert c.impact == significance.MEDIUM


def test_live_to_cached_provenance_change_is_not_an_alert():
    # Provenance disclosure is not a knowledge change (spec §16, §19).
    sources = [{"kind": "changed", "url": "https://x.example/a", "title": "A",
                "source_type": "web", "changes": ["availability live → cached"]}]
    assert significance.evaluate(_diff(sources=sources), settings) == []


# --------------------------------------------------------------------------- #
# Thresholds + dedup
# --------------------------------------------------------------------------- #
def test_notify_threshold_by_policy():
    assert significance.notify_threshold("all") == significance.MEDIUM
    assert significance.notify_threshold("important") == significance.HIGH
    assert significance.notify_threshold("critical") == significance.CRITICAL


def test_dedup_key_is_stable_and_content_derived():
    d1 = _diff(claims=[_claim(WEAKENED, old_c=80.0, new_c=55.0, delta=-25.0)])
    d2 = _diff(claims=[_claim(WEAKENED, old_c=80.0, new_c=55.0, delta=-25.0)])
    k1 = significance.evaluate(d1, settings)[0].dedup_key
    k2 = significance.evaluate(d2, settings)[0].dedup_key
    assert k1 == k2 and k1  # deterministic, non-empty


def test_dedup_key_changes_when_confidence_moves_further():
    a = _diff(claims=[_claim(WEAKENED, old_c=80.0, new_c=55.0, delta=-25.0)])
    b = _diff(claims=[_claim(WEAKENED, old_c=80.0, new_c=20.0, delta=-60.0)])
    ka = significance.evaluate(a, settings)[0].dedup_key
    kb = significance.evaluate(b, settings)[0].dedup_key
    assert ka != kb  # a further move is a new alert, not a duplicate

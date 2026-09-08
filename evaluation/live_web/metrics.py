"""Live-web collection-quality metrics (#11, Phase 6). Deterministic functions over a captured
run manifest — they MEASURE the production collection output, they do not reimplement it. Reuses
the production `dedup.normalize_url` and `freshness.freshness_state` so the harness and pipeline
agree on URL identity and recency (Phase 6 reuse)."""
from __future__ import annotations

import math
from urllib.parse import urlparse

from app.services.dedup import normalize_url
from app.services.freshness import freshness_state

# --- helpers --------------------------------------------------------------- #
def _domain(url: str) -> str:
    try:
        host = urlparse(url).netloc.lower()
        return host[4:] if host.startswith("www.") else host
    except Exception:  # noqa: BLE001
        return ""


def _norm_set(urls) -> set[str]:
    return {normalize_url(u) for u in urls if u}


# --- METRIC 1: source recall (Phase 6.1) ----------------------------------- #
def source_recall(sources: list[dict], reference: dict) -> dict | None:
    """Fraction of a task's reference sources discovered. Matches by normalized URL OR domain OR
    a reference substring in the url/title (so multiple equivalent sources count). Returns None
    when the task declares no reference set (recall not applicable)."""
    ref_urls = _norm_set(reference.get("urls", []))
    ref_domains = {d.lower() for d in reference.get("domains", [])}
    ref_substrings = [s.lower() for s in reference.get("substrings", [])]
    if not (ref_urls or ref_domains or ref_substrings):
        return None
    found_urls, found_domains, found_subs = set(), set(), set()
    for s in sources:
        nu = normalize_url(s.get("url", ""))
        dom = _domain(s.get("url", ""))
        hay = f"{s.get('url', '')} {s.get('title', '')}".lower()
        if nu in ref_urls:
            found_urls.add(nu)
        if dom in ref_domains:
            found_domains.add(dom)
        for sub in ref_substrings:
            if sub in hay:
                found_subs.add(sub)
    total = len(ref_urls) + len(ref_domains) + len(ref_substrings)
    hit = len(found_urls) + len(found_domains) + len(found_subs)
    return {"recall": round(hit / total, 3) if total else None, "hit": hit, "total": total}


# --- METRIC 2/3: ranking + authority (Phase 6.2, 6.3) ---------------------- #
def ranking_quality(sources: list[dict]) -> dict:
    """Do higher-reliability sources appear earlier? Measures MRR of the first high-authority
    source and whether reliability is monotonically non-increasing with rank (Spearman-like)."""
    if not sources:
        return {"mrr_authoritative": None, "reliability_rank_correlation": None, "n": 0}
    ordered = sorted(sources, key=lambda s: s.get("rank", 1e9))
    hi_thresh = 70.0
    mrr = 0.0
    for i, s in enumerate(ordered, start=1):
        if s.get("reliability", 0) >= hi_thresh:
            mrr = 1.0 / i
            break
    # rank correlation between provider rank order and reliability (should be positive:
    # earlier rank -> higher reliability).
    corr = _rank_correlation([s.get("rank", i) for i, s in enumerate(ordered)],
                             [s.get("reliability", 0) for s in ordered])
    return {"mrr_authoritative": round(mrr, 3), "reliability_rank_correlation": corr,
            "n": len(ordered)}


def _rank_correlation(ranks: list[float], scores: list[float]) -> float | None:
    n = len(ranks)
    if n < 2:
        return None
    # Spearman on (rank ascending) vs (score) — negate score so both ascending means agreement.
    def _rankify(xs):
        order = sorted(range(len(xs)), key=lambda i: xs[i])
        r = [0.0] * len(xs)
        for pos, i in enumerate(order):
            r[i] = pos
        return r
    a, b = _rankify(ranks), _rankify([-x for x in scores])
    d2 = sum((a[i] - b[i]) ** 2 for i in range(n))
    return round(1 - (6 * d2) / (n * (n * n - 1)), 3)


def authority_top_source(sources: list[dict]) -> dict:
    """Is the top-ranked source at least as authoritative as the median? (low-quality suppression)."""
    if len(sources) < 2:
        return {"top_at_or_above_median": None, "top_reliability": None}
    ordered = sorted(sources, key=lambda s: s.get("rank", 1e9))
    rels = sorted(s.get("reliability", 0) for s in sources)
    median = rels[len(rels) // 2]
    top = ordered[0].get("reliability", 0)
    return {"top_at_or_above_median": top >= median, "top_reliability": top}


# --- METRIC 4: diversity (Phase 6.4) --------------------------------------- #
def diversity(sources: list[dict]) -> dict:
    if not sources:
        return {"unique_domains": 0, "unique_owners": 0, "source_types": 0, "concentration": None}
    domains = [_domain(s.get("url", "")) for s in sources]
    owners = [(s.get("meta") or {}).get("owner") for s in sources if (s.get("meta") or {}).get("owner")]
    types = {s.get("source_type") for s in sources}
    top_dom = max((domains.count(d) for d in set(domains)), default=0)
    return {"unique_domains": len(set(d for d in domains if d)),
            "unique_owners": len(set(owners)),
            "source_types": len(types),
            "concentration": round(top_dom / len(sources), 3)}


# --- METRIC 6: deduplication (Phase 6.6) ----------------------------------- #
def deduplication(sources: list[dict]) -> dict:
    urls = [s.get("url", "") for s in sources if s.get("url")]
    norm = [normalize_url(u) for u in urls]
    exact_dups = len(urls) - len(set(urls))
    norm_dups = len(norm) - len(set(norm))
    return {"exact_duplicate_urls": exact_dups, "normalized_duplicate_urls": norm_dups,
            "collapsed": norm_dups - exact_dups}


# --- METRIC 5: freshness (Phase 6.5) --------------------------------------- #
def freshness(sources: list[dict], *, requirement: str, as_of: str | None = None) -> dict:
    """For freshness-sensitive tasks, what fraction of dated sources are fresh/aging (not stale)?
    For stable tasks, freshness should NOT dominate — reported but not gated."""
    from datetime import date

    ref = date.fromisoformat(as_of) if as_of else None
    states = [freshness_state(s.get("published_date"), s.get("source_type", "web"), as_of=ref)
              for s in sources if s.get("published_date")]
    if not states:
        return {"requirement": requirement, "dated_sources": 0, "fresh_or_aging_ratio": None}
    good = sum(1 for st in states if st in ("fresh", "aging"))
    return {"requirement": requirement, "dated_sources": len(states),
            "fresh_or_aging_ratio": round(good / len(states), 3)}


# --- Provenance: no false-live (Phase 5 CRITICAL) -------------------------- #
def provenance_check(sources: list[dict], *, expected_live: bool) -> dict:
    """When live retrieval genuinely occurred, sources are live_web; when it did not (skip/
    fallback), NONE may be labelled live_web. Returns a hard pass/fail."""
    labelled_live = [s for s in sources if s.get("provenance") == "live_web"]
    if expected_live:
        ok = len(labelled_live) > 0 or not sources  # live run: live labels expected if any source
    else:
        ok = len(labelled_live) == 0                # non-live: no false-live allowed
    return {"expected_live": expected_live, "live_labelled": len(labelled_live),
            "no_false_live": (len(labelled_live) == 0) if not expected_live else True,
            "pass": ok}


# --- METRIC 2 baseline comparison: NDCG-style value of re-ranking ---------- #
def ranking_gain_vs_provider(sources: list[dict]) -> float | None:
    """DCG of reliability under ResearchMind's reliability-sorted order vs the provider's raw rank
    order — how much the reliability re-rank improves top-heavy authority. >1.0 means RM's order
    concentrates authority earlier than the raw provider order."""
    if len(sources) < 2:
        return None

    def dcg(order):
        return sum((s.get("reliability", 0)) / math.log2(i + 2) for i, s in enumerate(order))

    raw = sorted(sources, key=lambda s: s.get("rank", 1e9))
    rm = sorted(sources, key=lambda s: -s.get("reliability", 0))
    raw_dcg = dcg(raw) or 1.0
    return round(dcg(rm) / raw_dcg, 3)

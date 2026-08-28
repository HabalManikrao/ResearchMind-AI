"""Source reliability scoring (spec §5).

A base score is derived from the source type/domain, then adjusted by search
relevance. This is deliberately simple and transparent; it can be extended with
citation counts, cross-source agreement, and author credibility later.
"""
from __future__ import annotations

from urllib.parse import urlparse

# Base authority by category.
_BASE = {
    "official_docs": 100,
    "gov_standards": 95,
    "peer_reviewed": 95,
    "university": 90,
    "official_github": 90,
    "established_tech": 80,
    "major_news": 80,
    "community": 60,
    "personal_blog": 40,
    "unknown": 20,
}

_GOV_EDU_SUFFIXES = (".gov", ".edu", ".ac.uk", ".mil")
_ACADEMIC_HOSTS = ("arxiv.org", "ieee.org", "acm.org", "dl.acm.org", "semanticscholar.org")
_MAJOR_NEWS = ("reuters.com", "bloomberg.com", "nytimes.com", "bbc.com", "theverge.com")
_DOCS_HINTS = ("docs.", "developer.", "documentation")
_COMMUNITY = ("reddit.com", "stackoverflow.com", "news.ycombinator.com", "medium.com", "dev.to")


def categorize(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    if not host:
        return "unknown"
    if host.endswith(_GOV_EDU_SUFFIXES):
        return "gov_standards" if host.endswith((".gov", ".mil")) else "university"
    if any(h in host for h in _ACADEMIC_HOSTS):
        return "peer_reviewed"
    if "github.com" in host or "github.io" in host:
        return "official_github"
    if any(h in host for h in _MAJOR_NEWS):
        return "major_news"
    if any(hint in host for hint in _DOCS_HINTS):
        return "official_docs"
    if any(h in host for h in _COMMUNITY):
        return "community"
    return "established_tech"


def reliability_score(url: str, *, relevance: float = 0.0) -> float:
    """Return 0-100. `relevance` is Tavily's 0-1 score, used as a small modifier."""
    base = _BASE[categorize(url)]
    # Nudge by up to +/-10 based on relevance around a 0.5 midpoint.
    adjustment = (relevance - 0.5) * 20
    return round(max(0.0, min(100.0, base + adjustment)), 1)


def github_reliability(stars: int, *, active: bool, archived: bool) -> float:
    """Score a repository: base official-github authority modified by popularity
    and maintenance activity."""
    import math

    base = _BASE["official_github"]  # 90
    # Popularity: up to +8 on a log scale (10k stars ~ +8).
    popularity = min(8.0, math.log10(max(1, stars)) * 2)
    activity = 0.0 if active else -15.0
    if archived:
        activity -= 10.0
    return round(max(20.0, min(100.0, base + popularity + activity)), 1)


def academic_reliability(*, relevance: float = 0.0) -> float:
    """Peer-reviewed / preprint academic base score with a small relevance nudge."""
    base = _BASE["peer_reviewed"]  # 95
    return round(max(0.0, min(100.0, base + (relevance - 0.5) * 10)), 1)


def document_reliability(*, relevance: float = 0.0) -> float:
    """User-uploaded document: a credible primary-ish source, but not independently
    authoritative like official docs. `relevance` is the 0-1 retrieval score."""
    base = 70.0
    return round(max(20.0, min(90.0, base + (relevance - 0.5) * 20)), 1)

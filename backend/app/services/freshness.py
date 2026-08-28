"""Source freshness / recency (spec §5, §14).

Every source has a freshness *state* derived from its publish date, judged
against a threshold that depends on the source type — news goes stale in days,
academic papers stay useful for years. There is deliberately **no single
universal threshold**.

Freshness feeds two things:
- the claim confidence model (`agents/verification.score_claim`), so recent
  evidence counts for more than dated evidence, and
- the UI badges (fresh / aging / potentially outdated / unknown) on sources and
  claims, so a reader can see at a glance how current the evidence is.

Parsing is tolerant and dependency-free: publish dates arrive as assorted
strings (``2025-01-01``, ISO datetimes, arXiv/news formats) or not at all.
"""
from __future__ import annotations

import re
from datetime import date, datetime

# Freshness states (ordered fresh -> unknown).
FRESH = "fresh"
AGING = "aging"
STALE = "stale"
UNKNOWN = "unknown"

# (fresh_max_days, aging_max_days) by source type. Beyond aging_max -> stale.
_THRESHOLDS: dict[str, tuple[int, int]] = {
    "news": (7, 30),
    "community": (90, 365),
    "papers": (730, 1825),  # 2y fresh, 5y aging
    "docs": (180, 545),
    "github": (180, 545),
    "web": (180, 545),
    # User-uploaded documents age slowly; judged on their own metadata dates
    # (publication/creation), never on the upload time.
    "documents": (365, 1095),  # 1y fresh, 3y aging
}
_DEFAULT_THRESHOLD = (180, 545)

# How much each freshness state is worth when averaging recency into confidence.
# `unknown` is treated as near-neutral: a missing date is not evidence of being
# stale, so it should not be penalised as if it were.
FRESHNESS_WEIGHT: dict[str, float] = {
    FRESH: 1.0,
    AGING: 0.65,
    STALE: 0.2,
    UNKNOWN: 0.85,
}

_DATE_RE = re.compile(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})")


def parse_date(value: str | None) -> date | None:
    """Best-effort parse of an assorted publish-date string. Returns None if the
    value is missing or unparseable (caller treats that as UNKNOWN freshness)."""
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    # ISO date/datetime (handles "2025-01-01" and "2025-01-01T12:00:00Z").
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        pass
    # A few common explicit formats.
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%d %b %Y", "%b %d, %Y", "%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    # Fall back to the first yyyy-mm-dd-ish run anywhere in the string.
    m = _DATE_RE.search(text)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
    return None


def freshness_state(
    published_date: str | None,
    source_type: str | None = None,
    *,
    as_of: date | None = None,
) -> str:
    """Classify a source as fresh / aging / stale / unknown for its type."""
    d = parse_date(published_date)
    if d is None:
        return UNKNOWN
    ref = as_of or date.today()
    age_days = (ref - d).days
    if age_days < 0:  # future-dated -> treat as fresh, not an error
        return FRESH
    fresh_max, aging_max = _THRESHOLDS.get(source_type or "", _DEFAULT_THRESHOLD)
    if age_days <= fresh_max:
        return FRESH
    if age_days <= aging_max:
        return AGING
    return STALE

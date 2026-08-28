from datetime import date

from app.services.freshness import (
    AGING,
    FRESH,
    STALE,
    UNKNOWN,
    freshness_state,
    parse_date,
)

AS_OF = date(2025, 6, 1)


def test_parse_date_variants():
    assert parse_date("2025-01-01") == date(2025, 1, 1)
    assert parse_date("2025-01-01T12:00:00Z") == date(2025, 1, 1)
    assert parse_date("2025/03/04") == date(2025, 3, 4)
    assert parse_date(None) is None
    assert parse_date("") is None
    assert parse_date("not a date") is None


def test_news_goes_stale_fast():
    assert freshness_state("2025-05-28", "news", as_of=AS_OF) == FRESH  # 4 days
    assert freshness_state("2025-05-10", "news", as_of=AS_OF) == AGING  # ~22 days
    assert freshness_state("2025-01-01", "news", as_of=AS_OF) == STALE  # ~5 months


def test_papers_stay_fresh_for_years():
    assert freshness_state("2024-01-01", "papers", as_of=AS_OF) == FRESH  # ~1.4y
    assert freshness_state("2022-01-01", "papers", as_of=AS_OF) == AGING  # ~3.4y
    assert freshness_state("2015-01-01", "papers", as_of=AS_OF) == STALE


def test_unknown_when_no_or_bad_date():
    assert freshness_state(None, "web", as_of=AS_OF) == UNKNOWN
    assert freshness_state("", "news", as_of=AS_OF) == UNKNOWN
    assert freshness_state("garbage", "web", as_of=AS_OF) == UNKNOWN


def test_threshold_is_domain_dependent():
    # A one-year-old source is stale news but a fresh paper.
    one_year = "2024-06-01"
    assert freshness_state(one_year, "news", as_of=AS_OF) == STALE
    assert freshness_state(one_year, "papers", as_of=AS_OF) == FRESH


def test_future_date_is_fresh():
    assert freshness_state("2026-01-01", "web", as_of=AS_OF) == FRESH

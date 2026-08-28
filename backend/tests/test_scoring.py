from app.services.scoring import (
    academic_reliability,
    categorize,
    github_reliability,
    reliability_score,
)


def test_categorize_by_host():
    assert categorize("https://docs.python.org/3/") == "official_docs"
    assert categorize("https://github.com/foo/bar") == "official_github"
    assert categorize("https://arxiv.org/abs/1234") == "peer_reviewed"
    assert categorize("https://some.gov/report") == "gov_standards"
    assert categorize("https://mit.edu/paper") == "university"
    assert categorize("https://reddit.com/r/x") == "community"
    assert categorize("https://random-blog.io/post") == "established_tech"
    assert categorize("not a url") == "unknown"


def test_reliability_score_bounds_and_relevance():
    high = reliability_score("https://docs.python.org", relevance=1.0)
    low = reliability_score("https://docs.python.org", relevance=0.0)
    assert 0 <= low <= high <= 100
    # Official docs base is 100, so it should stay near the top.
    assert high == 100.0


def test_github_reliability_rewards_stars_penalizes_inactive():
    active_popular = github_reliability(10000, active=True, archived=False)
    inactive = github_reliability(10000, active=False, archived=False)
    archived = github_reliability(10000, active=False, archived=True)
    assert active_popular > inactive > archived
    assert github_reliability(0, active=True, archived=False) >= 20.0


def test_academic_reliability_is_high():
    assert academic_reliability() >= 90.0

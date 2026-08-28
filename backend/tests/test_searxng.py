"""SearXNG search client: parsing, score normalization, param mapping, factory."""
import httpx
import pytest

from app.config import Settings
from app.search import SearxngClient, TavilyClient, get_search_client
from app.search import searxng_client as sx


def test_days_to_range_buckets():
    assert sx._days_to_range(1) == "day"
    assert sx._days_to_range(7) == "week"
    assert sx._days_to_range(31) == "month"
    assert sx._days_to_range(180) == "year"


def test_html_to_text_strips_scripts_and_tags():
    raw = "<html><head><style>.x{}</style><script>evil()</script></head><body><p>Hello &amp; world</p></body></html>"
    text = sx._html_to_text(raw)
    assert "evil" not in text and ".x{" not in text
    assert "Hello & world" in text


def test_factory_selects_backend():
    assert isinstance(get_search_client(Settings(search_provider="searxng")), SearxngClient)
    assert isinstance(get_search_client(Settings(search_provider="tavily")), TavilyClient)


class _FakeResp:
    def __init__(self, json_data):
        self._j = json_data
        self.headers = {"content-type": "application/json"}

    def raise_for_status(self):
        pass

    def json(self):
        return self._j


class _FakeClient:
    """Captures the request params and returns a canned SearXNG JSON payload."""

    captured: dict = {}

    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, url, params=None, headers=None):
        _FakeClient.captured = dict(params or {})
        return _FakeResp({
            "results": [
                {"title": "A", "url": "https://a.example/1", "content": "snippet A",
                 "score": 4.0, "publishedDate": "2026-08-01"},
                {"title": "B", "url": "https://b.example/2", "content": "snippet B",
                 "score": 2.0},
            ]
        })


@pytest.fixture
def fake_http(monkeypatch):
    _FakeClient.captured = {}
    monkeypatch.setattr(sx.httpx, "AsyncClient", _FakeClient)


async def test_search_parses_and_normalizes_scores(fake_http):
    client = SearxngClient("http://localhost:8080", fetch_content=False)
    results = await client.search("vector databases", max_results=5)
    assert [r.url for r in results] == ["https://a.example/1", "https://b.example/2"]
    # Top score normalized to 1.0, the other to 0.5 (2.0 / 4.0).
    assert results[0].score == 1.0
    assert results[1].score == 0.5
    assert results[0].published_date == "2026-08-01"


async def test_news_topic_and_recency_map_to_params(fake_http):
    client = SearxngClient("http://localhost:8080", fetch_content=False)
    await client.search("ai funding", topic="news", days=5)
    assert _FakeClient.captured.get("categories") == "news"
    assert _FakeClient.captured.get("time_range") == "week"  # 5 days -> week bucket


async def test_include_domains_becomes_site_operators(fake_http):
    client = SearxngClient("http://localhost:8080", fetch_content=False)
    await client.search("rag tips", include_domains=["reddit.com", "stackoverflow.com"])
    q = _FakeClient.captured.get("q", "")
    assert "site:reddit.com" in q and "site:stackoverflow.com" in q


async def test_missing_url_raises_clear_error():
    from app.search.tavily_client import SearchError

    client = SearxngClient("", fetch_content=False)
    with pytest.raises(SearchError):
        await client.search("anything")

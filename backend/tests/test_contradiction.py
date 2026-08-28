"""Active contradiction search agent."""
from app.agents import contradiction
from app.search import SearchError
from tests.conftest import FakeProvider


class FakeResult:
    def __init__(self, url, content, *, title="t", score=0.5, published_date=None):
        self.url = url
        self.content = content
        self.title = title
        self.score = score
        self.published_date = published_date


class FakeSearch:
    def __init__(self, results):
        self._results = results
        self.queries: list[str] = []

    async def search(self, query, *, max_results=5, **kwargs):
        self.queries.append(query)
        return self._results[:max_results]


class BadSearch:
    async def search(self, query, *, max_results=5, **kwargs):
        raise SearchError("no key")


async def test_seek_finds_contradicting_source():
    search = FakeSearch([FakeResult("https://critic.example", "X is actually false because ...")])
    provider = FakeProvider(contradictions=[{"index": 0, "quote": "X is actually false"}])

    out = await contradiction.seek(provider, search, [("c1", "X is true")], max_results=3)

    assert len(out) == 1
    assert out[0].claim_id == "c1"
    assert len(out[0].sources) == 1
    src = out[0].sources[0]
    assert src.url == "https://critic.example"
    assert src.passage == "X is actually false"
    assert src.source_type == "web"
    assert src.reliability > 0
    # The query is disconfirming-biased.
    assert "criticism" in search.queries[0] or "debunked" in search.queries[0]


async def test_seek_returns_empty_when_nothing_contradicts():
    search = FakeSearch([FakeResult("https://x.example", "supportive content")])
    provider = FakeProvider(contradictions=[])
    out = await contradiction.seek(provider, search, [("c1", "X")], max_results=3)
    assert out == []


async def test_seek_survives_search_error():
    out = await contradiction.seek(FakeProvider(), BadSearch(), [("c1", "X")], max_results=3)
    assert out == []


async def test_seek_ignores_out_of_range_index():
    search = FakeSearch([FakeResult("https://x.example", "content")])
    provider = FakeProvider(contradictions=[{"index": 5, "quote": "q"}])  # only index 0 exists
    out = await contradiction.seek(provider, search, [("c1", "X")], max_results=3)
    assert out == []

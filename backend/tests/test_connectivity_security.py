"""Cache/source isolation across projects & users (#5, spec §27, §30)."""
import pytest

from app.models.enums import SourcePolicy
from app.services import collection, source_cache
from app.services.collection import resilient_collect
from tests.conftest import make_collected

from app.config import get_settings

settings = get_settings()


async def test_cached_source_does_not_leak_across_projects(reset_db, monkeypatch):
    """A cache entry seeded for project A must never be served to project B, even
    when B's live fetch fails and policy allows cache (spec §30)."""
    # Seed a real cache row for project A.
    await source_cache.put("projA", "userA", "web", "shared query",
                           [make_collected("web", "https://a.example/secret")])

    # Project B's live fetch fails; fallback consults the cache — must find nothing.
    async def boom(*a, **k):
        raise RuntimeError("live down")
    monkeypatch.setattr(collection.dispatch, "collect", boom)

    with pytest.raises(RuntimeError):
        await resilient_collect(
            "web", None, None, settings, question="shared query",
            search_query="shared query", project_id="projB", user_id="userB",
            policy=SourcePolicy.LIVE_PREFERRED.value,
        )

    # Project A, same query, still gets its own cached source back.
    res = await resilient_collect(
        "web", None, None, settings, question="shared query",
        search_query="shared query", project_id="projA", user_id="userA",
        policy=SourcePolicy.LIVE_PREFERRED.value,
    )
    assert res.outcome == collection.CACHED
    assert res.sources[0].url == "https://a.example/secret"


async def test_cross_user_cannot_read_another_projects_health(client, patch_pipeline):
    """Report meta (incl. source_health) is behind project ownership (spec §27)."""
    from tests.conftest import register_user, run_to_completion

    r = await client.post("/research", json={"query": "x y z", "sources_enabled": ["web"],
                                             "auto_start": True})
    pid = r.json()["id"]
    await run_to_completion(pid)

    token2, _ = await register_user(client, email="intruder2@example.com")
    h = {"Authorization": f"Bearer {token2}"}
    assert (await client.get(f"/research/{pid}", headers=h)).status_code == 404
    assert (await client.get(f"/research/{pid}/sources", headers=h)).status_code == 404

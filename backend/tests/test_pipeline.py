"""End-to-end pipeline integration with all external calls faked."""
from tests.conftest import run_to_completion


async def test_full_deep_research_run(client, patch_pipeline):
    r = await client.post(
        "/research",
        json={"query": "compare vector databases", "sources_enabled": ["web", "docs"],
              "auto_start": True},
    )
    pid = r.json()["id"]
    await run_to_completion(pid)

    detail = (await client.get(f"/research/{pid}")).json()
    assert detail["status"] == "completed"
    assert detail["progress"] == 100
    assert detail["objective"]

    # The pipeline produced persisted artifacts at each stage.
    assert len(((await client.get(f"/research/{pid}/questions")).json())) >= 1
    assert len(((await client.get(f"/research/{pid}/sources")).json())) >= 1
    assert len(((await client.get(f"/research/{pid}/claims")).json())) >= 1

    solutions = (await client.get(f"/research/{pid}/solutions")).json()
    assert any(s["is_recommended"] for s in solutions)
    rec = (await client.get(f"/research/{pid}/recommendation")).json()
    assert rec["recommended_option"] == "OptX"

    report = (await client.get(f"/research/{pid}/report")).json()
    assert report["markdown"] and "## Recommended Solution" in report["markdown"]
    assert report["meta"]["sources_analyzed"] >= 1

    # A completed run is exportable.
    pdf = await client.get(f"/research/{pid}/export", params={"format": "pdf"})
    assert pdf.status_code == 200 and pdf.content[:4] == b"%PDF"


async def test_run_survives_contradiction_stage_failure(client, patch_pipeline, monkeypatch):
    # A failure in the (best-effort) contradiction search must NOT abort a run that
    # has otherwise completed — the research result is preserved.
    import app.orchestration.orchestrator as orch

    async def boom(*args, **kwargs):
        raise RuntimeError("contradiction search exploded")

    monkeypatch.setattr(orch, "_seek_contradictions", boom)

    r = await client.post(
        "/research",
        json={"query": "topic", "sources_enabled": ["web"], "auto_start": True},
    )
    pid = r.json()["id"]
    await run_to_completion(pid)

    detail = (await client.get(f"/research/{pid}")).json()
    assert detail["status"] == "completed"
    assert detail["progress"] == 100
    assert (await client.get(f"/research/{pid}/report")).json()["markdown"]


async def test_run_dispatches_multiple_source_agents(client, patch_pipeline):
    r = await client.post(
        "/research",
        json={"query": "topic", "sources_enabled": ["web", "docs", "github", "papers"],
              "auto_start": True},
    )
    pid = r.json()["id"]
    await run_to_completion(pid)

    sources = (await client.get(f"/research/{pid}/sources")).json()
    source_types = {s["source_type"] for s in sources}
    # Each enabled agent should have contributed at least one source.
    assert {"web", "docs", "github", "papers"}.issubset(source_types)

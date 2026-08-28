"""Evidence drill-down API: /research/{id}/claims/{claim_id}/evidence + freshness."""
from tests.conftest import register_user, run_to_completion


async def _run(client, sources=("web", "docs")):
    r = await client.post(
        "/research",
        json={"query": "topic", "sources_enabled": list(sources), "auto_start": True},
    )
    pid = r.json()["id"]
    await run_to_completion(pid)
    return pid


async def test_claims_carry_evidence_state_and_meta(client, patch_pipeline):
    pid = await _run(client)
    claims = (await client.get(f"/research/{pid}/claims")).json()
    assert claims
    c = claims[0]
    assert c["evidence_state"] in {
        "supported", "weak", "conflicting", "outdated", "unverified",
    }
    assert "confidence_meta" in c


async def test_claim_evidence_endpoint_returns_passages(client, patch_pipeline):
    pid = await _run(client)
    claims = (await client.get(f"/research/{pid}/claims")).json()
    cid = claims[0]["id"]

    ev = (await client.get(f"/research/{pid}/claims/{cid}/evidence")).json()
    assert ev["claim"]["id"] == cid
    assert isinstance(ev["evidence"], list) and ev["evidence"]
    item = ev["evidence"][0]
    for key in ("source_id", "title", "url", "reliability_score", "freshness", "stance", "passage"):
        assert key in item
    assert item["stance"] in {"supports", "contradicts", "neutral"}
    assert item["freshness"] in {"fresh", "aging", "stale", "unknown"}


async def test_sources_expose_freshness(client, patch_pipeline):
    pid = await _run(client, sources=("web",))
    sources = (await client.get(f"/research/{pid}/sources")).json()
    assert sources
    assert all(
        s["freshness"] in {"fresh", "aging", "stale", "unknown"} for s in sources
    )


async def test_claim_evidence_unknown_claim_404(client, patch_pipeline):
    pid = await _run(client, sources=("web",))
    resp = await client.get(f"/research/{pid}/claims/does-not-exist/evidence")
    assert resp.status_code == 404


async def test_claim_evidence_cross_user_404(client, patch_pipeline):
    pid = await _run(client, sources=("web",))
    claims = (await client.get(f"/research/{pid}/claims")).json()
    cid = claims[0]["id"]

    token2, _ = await register_user(client, email="other@example.com")
    resp = await client.get(
        f"/research/{pid}/claims/{cid}/evidence",
        headers={"Authorization": f"Bearer {token2}"},
    )
    assert resp.status_code == 404

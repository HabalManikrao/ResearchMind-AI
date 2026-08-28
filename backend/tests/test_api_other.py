from app.models import Claim, ProjectStatus, Recommendation, ResearchProject, Solution
from app.models.enums import ClaimStatus


async def test_health_ok(client):
    r = await client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert "knowledge" in body and "llm" in body


async def test_monitoring_stats_shape(client):
    await client.post("/research", json={"query": "a topic", "auto_start": False})
    r = await client.get("/monitoring/stats")
    assert r.status_code == 200
    body = r.json()
    assert body["projects"]["total"] == 1
    assert body["projects"]["active_runs"] == 0
    assert set(body["totals"]) == {"sources", "claims", "conflicts"}


async def test_monitoring_audit_records_create(client):
    await client.post("/research", json={"query": "a topic", "auto_start": False})
    r = await client.get("/monitoring/audit")
    assert r.status_code == 200
    actions = [e["action"] for e in r.json()]
    assert "research.create" in actions


async def test_knowledge_status_and_keyword_fallback(client):
    # Embeddings unreachable in tests -> semantic False, keyword fallback used.
    st = await client.get("/knowledge/status")
    assert st.status_code == 200
    assert st.json()["semantic"] is False

    await client.post("/research", json={"query": "unique vector database topic", "auto_start": False})
    res = await client.get("/knowledge/search", params={"q": "vector"})
    assert res.status_code == 200
    assert len(res.json()) == 1
    assert res.json()[0]["score"] is None  # keyword match has no score


async def test_knowledge_graph_endpoint(client, db):
    proj = ResearchProject(title="Graph", query="q", status=ProjectStatus.COMPLETED, objective="obj")
    db.add(proj)
    await db.flush()
    sol = Solution(project_id=proj.id, name="OptX", is_recommended=True)
    db.add(sol)
    db.add(Recommendation(project_id=proj.id, recommended_option="OptX", rationale="r", confidence=80))
    db.add(Claim(project_id=proj.id, text="a claim", status=ClaimStatus.VERIFIED, confidence=90,
                 supporting_source_ids=[]))
    await db.commit()

    r = await client.get(f"/knowledge/graph/{proj.id}")
    assert r.status_code == 200
    types = {n["type"] for n in r.json()["nodes"]}
    assert {"project", "solution", "recommendation", "claim"}.issubset(types)
    assert len(r.json()["edges"]) >= 3

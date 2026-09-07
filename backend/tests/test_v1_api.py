"""External REST API v1 (#8, spec §43): thin adapter over capabilities — auth, authz,
error envelope, request ids, idempotency, pagination, 202 for long-running research."""
import pytest

import app.services.connectivity as conn
from app.services.connectivity import ONLINE, ConnectivitySnapshot
from tests.conftest import run_to_completion


@pytest.fixture(autouse=True)
def _fake_connectivity(monkeypatch):
    async def fake_snapshot(force=False):
        return ConnectivitySnapshot(overall=ONLINE, internet=True, search_provider=True,
                                    ollama=True, qdrant=True, database=True)
    monkeypatch.setattr(conn.manager, "snapshot", fake_snapshot)


async def _complete(client, query="best vector db"):
    r = await client.post("/research", json={"query": query, "sources_enabled": ["web"],
                                             "auto_start": True})
    pid = r.json()["id"]
    await run_to_completion(pid, timeout=60)
    return pid


# --------------------------------------------------------------------------- #
# Auth + discovery
# --------------------------------------------------------------------------- #
async def test_v1_requires_auth(anon_client):
    assert (await anon_client.get("/v1/system/version")).status_code == 401
    assert (await anon_client.get("/v1/research")).status_code == 401


async def test_v1_capabilities_and_version(client):
    r = await client.get("/v1/system/capabilities")
    assert r.status_code == 200
    assert len(r.json()["capabilities"]) >= 15
    v = await client.get("/v1/system/version")
    assert v.json()["interfaces"]["rest"] == "/v1"
    # Every response carries a correlation id (spec §21).
    assert "x-request-id" in {k.lower() for k in v.headers}


async def test_v1_connectivity(client):
    r = await client.get("/v1/system/connectivity")
    assert r.status_code == 200
    assert r.json()["overall_status"] == "online"


# --------------------------------------------------------------------------- #
# Research lifecycle (202 → status → report → claims → evidence)
# --------------------------------------------------------------------------- #
async def test_v1_research_lifecycle(client, patch_pipeline):
    r = await client.post("/v1/research", json={"query": "compare vector databases"})
    assert r.status_code == 202  # long-running: accepted, not blocking (spec §22)
    rid = r.json()["research_id"]
    assert r.headers.get("Location", "").endswith(f"/v1/research/{rid}/status")
    await run_to_completion(rid, timeout=60)

    st = await client.get(f"/v1/research/{rid}/status")
    assert st.json()["status"] == "completed"

    rep = await client.get(f"/v1/research/{rid}/report?excerpt=true")
    assert rep.status_code == 200 and "markdown" in rep.json()

    cl = await client.get(f"/v1/research/{rid}/claims?limit=5")
    assert cl.status_code == 200 and cl.json()["limit"] == 5
    claims = cl.json()["claims"]
    if claims:
        ev = await client.get(f"/v1/research/{rid}/claims/{claims[0]['claim_id']}/evidence")
        assert ev.status_code == 200


async def test_v1_research_again_and_diff(client, patch_pipeline):
    parent = await _complete(client)
    again = await client.post(f"/v1/research/{parent}/again", json={"intent": "refresh"})
    assert again.status_code == 202
    child = again.json()["research_id"]
    await run_to_completion(child, timeout=60)
    d = await client.get(f"/v1/research/{parent}/diff/{child}")
    assert d.status_code == 200
    assert "claims" in d.json() and "recommendation" in d.json()


async def test_v1_idempotency_prevents_duplicate_research(client, patch_pipeline):
    headers = {"Idempotency-Key": "abc-123"}
    r1 = await client.post("/v1/research", json={"query": "idempotent api topic"}, headers=headers)
    r2 = await client.post("/v1/research", json={"query": "idempotent api topic"}, headers=headers)
    assert r1.json()["research_id"] == r2.json()["research_id"]
    await run_to_completion(r1.json()["research_id"], timeout=60)
    # Only one project actually created for that query.
    listing = await client.get("/v1/research?q=idempotent api topic")
    assert len(listing.json()["results"]) == 1


# --------------------------------------------------------------------------- #
# Error envelope + pagination
# --------------------------------------------------------------------------- #
async def test_v1_error_envelope(client):
    r = await client.get("/v1/research/does-not-exist/status")
    assert r.status_code == 404
    body = r.json()
    assert body["error"]["code"] == "RESEARCH_NOT_FOUND"
    assert body["error"]["request_id"]  # correlation id in the envelope
    assert "message" in body["error"]
    # No stack traces / SQL / internals leaked.
    assert "Traceback" not in body["error"]["message"]


async def test_v1_pagination(client, patch_pipeline):
    for i in range(3):
        pid = await _complete(client, query=f"pagination topic {i}")
    r = await client.get("/v1/research?limit=2")
    assert len(r.json()["results"]) == 2


# --------------------------------------------------------------------------- #
# Knowledge + documents + monitoring through v1
# --------------------------------------------------------------------------- #
async def test_v1_knowledge_and_documents(client, patch_pipeline):
    pid = await _complete(client)
    ents = await client.get("/v1/knowledge/entities")
    assert ents.status_code == 200 and "entities" in ents.json()
    ds = await client.post("/v1/documents/search", json={"project_id": pid, "query": "x"})
    assert ds.status_code == 200 and "passages" in ds.json()


async def test_v1_monitor_status(client, patch_pipeline):
    pid = await _complete(client)
    await client.post(f"/research/{pid}/monitor", json={"frequency": "daily"})
    r = await client.get(f"/v1/monitors/{pid}")
    assert r.status_code == 200 and r.json()["monitor"]["health"] == "healthy"
    # No monitor → capability 404 envelope.
    pid2 = await _complete(client, query="unmonitored topic")
    r2 = await client.get(f"/v1/monitors/{pid2}")
    assert r2.status_code == 404 and r2.json()["error"]["code"] == "NOT_FOUND"

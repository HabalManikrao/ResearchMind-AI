"""Capability/API/MCP security (#8, spec §45): cross-user isolation, malformed ids, bounded
depth, and the absence of dangerous tools (arbitrary SQL / filesystem / URL fetch)."""
import httpx
import pytest
from sqlalchemy import select

import app.services.connectivity as conn
from app.database import SessionLocal
from app.main import app
from app.mcp import tools as mcp_tools
from app.models import KgEntity
from app.capabilities.base import REGISTRY
from app.services.connectivity import ONLINE, ConnectivitySnapshot
from tests.conftest import register_user, run_to_completion


@pytest.fixture(autouse=True)
def _fake_connectivity(monkeypatch):
    async def fake_snapshot(force=False):
        return ConnectivitySnapshot(overall=ONLINE, internet=True, search_provider=True,
                                    ollama=True, qdrant=True, database=True)
    monkeypatch.setattr(conn.manager, "snapshot", fake_snapshot)


async def _other_user_project(query="secret research"):
    """A second user completes a run; returns (project_id, one entity id owned by them)."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as other:
        token, ouser = await register_user(other, email="victim@example.com")
        other.headers["Authorization"] = f"Bearer {token}"
        r = await other.post("/research", json={"query": query, "sources_enabled": ["web"],
                                                "auto_start": True})
        pid = r.json()["id"]
        await run_to_completion(pid, timeout=60)
        await other.post(f"/research/{pid}/monitor", json={"frequency": "daily"})
    async with SessionLocal() as db:
        ent = (await db.execute(
            select(KgEntity).where(KgEntity.user_id == ouser["id"]))).scalars().first()
    return pid, (ent.id if ent else "no-entity")


# --------------------------------------------------------------------------- #
# Cross-user matrix — every capability must DENY (spec §45)
# --------------------------------------------------------------------------- #
async def test_cross_user_access_is_denied(client, patch_pipeline):
    pid_b, eid_b = await _other_user_project()

    # User A cannot touch User B's research / claims / documents / monitor.
    assert (await client.get(f"/v1/research/{pid_b}/status")).status_code == 404
    assert (await client.get(f"/v1/research/{pid_b}/claims")).status_code == 404
    assert (await client.get(f"/v1/research/{pid_b}/claims/whatever/evidence")).status_code == 404
    assert (await client.get(f"/v1/documents?project_id={pid_b}")).status_code == 404
    assert (await client.get(f"/v1/monitors/{pid_b}")).status_code == 404
    # …nor start a continuation of it.
    assert (await client.post(f"/v1/research/{pid_b}/again", json={"intent": "refresh"})).status_code == 404
    # …nor read User B's knowledge entity.
    r = await client.get(f"/v1/knowledge/entities/{eid_b}")
    assert r.status_code == 404
    assert r.json()["error"]["code"] in ("NOT_FOUND", "RESEARCH_NOT_FOUND")


async def test_cross_user_denied_via_mcp(client):
    """The same isolation holds through the MCP adapter."""
    from app.mcp.server import McpServer
    import json

    pid_b, _ = await _other_user_project(query="secret mcp research")
    server = McpServer(token=client.headers["Authorization"].split(" ", 1)[1])
    result = await server.handle({
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": "research_claims", "arguments": {"research_id": pid_b}},
    })
    payload = json.loads(result["result"]["content"][0]["text"])
    assert result["result"]["isError"] is True
    assert payload["error"]["code"] == "RESEARCH_NOT_FOUND"


# --------------------------------------------------------------------------- #
# Malformed ids / path traversal / bounded depth
# --------------------------------------------------------------------------- #
async def test_malformed_and_traversal_ids_are_safe(client):
    for bad in ["..", "../../etc/passwd", "%2e%2e", "'; DROP TABLE claims;--"]:
        r = await client.get(f"/v1/research/{bad}/status")
        assert r.status_code in (404, 422)  # never 500, never a filesystem/SQL escape


async def test_graph_depth_is_clamped(client, patch_pipeline):
    # Own entity, then request an excessive depth — must clamp, never explode.
    r = await client.post("/research", json={"query": "depth clamp topic",
                                             "sources_enabled": ["web"], "auto_start": True})
    pid = r.json()["id"]
    await run_to_completion(pid, timeout=60)
    async with SessionLocal() as db:
        ent = (await db.execute(
            select(KgEntity).where(KgEntity.user_id == client.default_user["id"]))
        ).scalars().first()
    if ent:
        g = await client.get(f"/v1/knowledge/entities/{ent.id}/graph?depth=99")
        assert g.status_code == 200 and g.json()["depth"] <= 2


# --------------------------------------------------------------------------- #
# No dangerous tools exist (spec §38, §39, §52)
# --------------------------------------------------------------------------- #
def test_no_dangerous_capabilities_or_tools():
    forbidden = {"read_file", "fetch_url", "sql", "exec", "shell", "write_file", "eval"}
    cap_names = {c.name for c in REGISTRY}
    tool_names = {t.name for t in mcp_tools.TOOLS}
    assert not (forbidden & cap_names)
    assert not (forbidden & tool_names)
    # Every tool input schema forbids extra properties (bounded, no arbitrary injection).
    for t in mcp_tools.TOOLS:
        assert t.input_schema.get("additionalProperties") is False
